import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rongyao_video_list_upload as upload
import rongyao_fast_session as session
from bs4 import BeautifulSoup
from material_upload import UploadError


def slow_local_worker(pipe,command,secret,display_name):
    time.sleep(3)  # 完全本地阻塞，用于证明进程截止，不访问网站。


class FakeApi:
    def __init__(self,state):
        self.state=state
        self.started=time.monotonic()
        self.deadline=self.started+60
        self.private_form={'create_name':'test','advertiser_id':'test','token':'test'}
        self.identity={'display_name':'test','user_id':None}
        self.session=type('Session',(),{'close':lambda self:None})()
        self.soup=BeautifulSoup('''<select id="category_type"><option value="117">火影</option></select>
          <select id="source_type"><option value="剪辑">剪辑</option><option value="小剧场">小剧场</option></select>
          <select id="demand_name"><option value="示例人员4">示例人员4</option><option value="示例人员3">示例人员3</option></select>
          <select id="ai_source"><option value=""></option><option value="SD2拼框">SD2拼框</option></select>''','html.parser')
    def fork(self):
        result=FakeApi(self.state)
        result.started=self.started
        return result
    def defaults(self): return upload.FIXED_DEFAULTS
    def redacted_message(self,data): return 'test'
    def request(self,url,method='GET',params=None,file=None,html=False):
        if url==upload.PRECHECK:
            with self.state['lock']: self.state['prechecks']+=1
            return {'status':True,'info':[{'num':i,'status':True} for i,_ in enumerate(params)]}
        with self.state['lock']:
            self.state['active']+=1
            self.state['max_active']=max(self.state['max_active'],self.state['active'])
            self.state['writes']+=1
            if 'act=join' in url: self.state['joins'].append(dict(params))
        time.sleep(.04)
        with self.state['lock']: self.state['active']-=1
        return {'status':1,'message':'获取成功','data':[]}
    def lookup(self,name,target=None):
        with self.state['lock']:
            self.state.setdefault('join_counts_at_lookup',[]).append(len(self.state['joins']))
        return {'id':'100','name':name,'source_type':target['source_type'] if target else None}


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.rules=copy.deepcopy(upload.read_json(upload.RULES))
        self.rules['requester_segment']='penultimate'
    def row(self,name,direction='竞品'):
        return {'upload_name':name,'request':{'category':'火影','source_type':'小剧场' if direction=='AI' else '剪辑',
                                           'source_direction':direction,'roles':[]}}
    def test_requester_not_designer_and_ai_cases(self):
        for name,direction,confirmed,person,ai in [
            ('260930D1-测试AI-JZY-QW.mp4','竞品',False,'示例人员3','SD2拼框'),
            ('260930D2-测试-JZY-QW.mp4','AI',False,'示例人员3','SD2拼框'),
            ('260930D3-hair-DY-LY.mp4','竞品',False,'示例人员4',''),
            ('260930D4-测试-DY-LY.mp4','竞品',True,'示例人员4','SD2拼框')]:
            values,_=upload.business_fields(self.row(name,direction),{'confirmed_ai':confirmed},self.rules)
            self.assertEqual((values['demand_name'],values['ai_source']),(person,ai))
    def test_unconfirmed_unknown_and_unverified_stop(self):
        for position,code,verified in [(None,'DY',True),('last','LY',True),('penultimate','DY',False)]:
            rules=copy.deepcopy(self.rules);rules['requester_segment']=position
            if code in rules['requesters']: rules['requesters'][code]['verified']=verified
            with self.assertRaises(UploadError): upload.business_fields(self.row('260930D1-测试-DY-LY.mp4'),rules=rules)

    def fixture(self,folder,count):
        rows=[]
        for i in range(count):
            name=f'260930D{i+1}-测试{i}-DY-LY.mp4';content=f'unique-{i}'.encode()
            path=folder/name;path.write_bytes(content)
            rows.append(dict(self.row(name),path=str(path),status='READY',
                             media={'full_decode':True,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}))
        plan=folder/'plan.json';plan.write_text(json.dumps({'items':rows}))
        rules=folder/'rules.json';rules.write_text(json.dumps(self.rules))
        queue=folder/'queue';queue.mkdir()
        return rows,plan,rules,queue
    def test_batch_parallel_single_precheck_and_persistent_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);rows,plan,rules,queue=self.fixture(folder,4)
            state={'lock':threading.Lock(),'active':0,'max_active':0,'writes':0,'prechecks':0,'joins':[]}
            with patch.object(upload,'PLAN',plan),patch.object(upload,'RULES',rules),patch.object(upload,'OUT',folder/'out'),\
                 patch.object(upload.native,'private_queue_dir',return_value=queue):
                result=upload.execute_batch({'action':'batch'},FakeApi(state))
                self.assertEqual(result['successful_count'],4)
                self.assertEqual(state['prechecks'],1)
                self.assertGreater(state['max_active'],1)
                self.assertEqual(len({x['time'] for x in state['joins']}),4)
                self.assertEqual(state['join_counts_at_lookup'][0],4)
                self.assertTrue(all(x['demand_name']=='示例人员4' for x in state['joins']))
                writes=state['writes']
                upload.execute({'name':rows[0]['upload_name']},FakeApi(state))
                self.assertEqual(state['writes'],writes)
    def test_same_file_concurrent_submissions_write_once(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);rows,plan,rules,queue=self.fixture(folder,1)
            state={'lock':threading.Lock(),'active':0,'max_active':0,'writes':0,'prechecks':0,'joins':[]}
            with patch.object(upload,'PLAN',plan),patch.object(upload,'RULES',rules),patch.object(upload,'OUT',folder/'out'),\
                 patch.object(upload.native,'private_queue_dir',return_value=queue),ThreadPoolExecutor(max_workers=2) as pool:
                jobs=[pool.submit(upload.execute,{'name':rows[0]['upload_name']},FakeApi(state)) for _ in range(2)]
                for job in jobs: job.result()
                self.assertEqual(state['writes'],2)
                self.assertEqual(state['prechecks'],1)
    def test_deadline_stops_stalled_worker_without_false_success(self):
        with tempfile.TemporaryDirectory() as d:
            queue=Path(d)/'queue';queue.mkdir()
            name='260930D1-测试-DY-LY.mp4'
            with upload.native.ledger(queue) as db:
                upload.native.save_receipt(db,'test','SENDING',{'status':'SENDING','upload_name':name,
                         'started_at_epoch':time.time()+1,'phases':{'join_register':{'state':'SENDING'}}})
            with patch.object(session,'_run_command',slow_local_worker),patch.object(session,'EXECUTION_SECONDS',.1),\
                 patch.object(upload.native,'private_queue_dir',return_value=queue):
                start=time.monotonic()
                result=session.execute_bounded({'action':'run','name':name},{},'test')
                self.assertLess(time.monotonic()-start,1)
                self.assertEqual(result['成功数量'],0)
                self.assertEqual(result['items'][0]['状态'],'ACCEPTANCE_UNKNOWN')


if __name__=='__main__': unittest.main()
