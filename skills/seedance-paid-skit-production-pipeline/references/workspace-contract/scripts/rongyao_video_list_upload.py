#!/usr/bin/env python3
"""已验视频的正确视频列表入口；仅原生预检、20MiB分片、完整合并、回读。"""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit, urlencode

from bs4 import BeautifulSoup
import requests

from material_upload import UploadError, atomic_json, fail, read_json
import rongyao_material_upload as native
from rongyao_upload_preview import filename_parameters

BASE = 'http://adopenplatform.backend.example.invalid'
ENTRY = BASE + '/app/data/?_c=jrttList&_a=index&ac=toImgInfo&do=video'
LIST = BASE + '/app/data/?_c=jrttList&_a=index&ac=jrttVideoList'
PRECHECK = BASE + '/app/data/?_c=jrttList&_a=index&ac=getVideoNames'
CDN = 'http://cdnapk.backend.example.invalid/api/controller/ApiUploadVideo.php'
CHUNK_BYTES = 20971520
ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'workflow/maintenance/upload-acceptance/evidence/folder-20260930-run-20261010/plan.json'
OUT = ROOT/'workflow/maintenance/upload-acceptance/evidence/fast-native-20261010'
RULES = ROOT/'workflow/maintenance/upload-acceptance/config/requester-ai-rules.json'
FIXED_DEFAULTS={'is_redbag':'0','region_type':'','origin_type':'1'}


def business_fields(row, command=None, rules=None):
    """需求人与设计师分开；没有已证实名字的缩写禁止采用页面默认人。"""
    command=command or {}
    rules=rules or read_json(RULES)
    position=rules.get('requester_segment')
    if position not in ('last','penultimate'):
        fail('REQUESTER_POSITION_UNCONFIRMED','待确认需求人缩写使用最后段还是倒数第二段。')
    parts=Path(row['upload_name']).stem.split('-')
    index=-1 if position=='last' else -2
    if len(parts)<3 or not re.fullmatch('[A-Za-z]+',parts[index]):
        fail('REQUESTER_CODE_INVALID','素材尾部缺少需求人字母缩写。')
    code=parts[index].upper()
    person=rules.get('requesters',{}).get(code,{})
    if person.get('verified') is not True or not person.get('backend_value'):
        fail('REQUESTER_UNMAPPED','需求人缩写 '+code+' 尚无已确认的姓名映射，未上传。')
    confirmed_ai=command.get('confirmed_ai') is True or row['request'].get('confirmed_ai') is True
    ai_label=row['request'].get('source_direction') in ('AI','小剧场AI','AI-Q版')
    name_ai=re.search(r'(?<![A-Za-z])AI(?![A-Za-z])',row['upload_name'],re.I) is not None
    is_ai=confirmed_ai or ai_label or name_ai
    fields=dict(FIXED_DEFAULTS,demand_name=person['backend_value'],
                ai_source=rules['ai_default']['backend_value'] if is_ai else rules['non_ai_value'])
    return fields,{'requester_code':code,'requester_name':person['name'],
                   'requester_segment':position,'requester_backend_numeric_id':person.get('backend_numeric_id'),
                   'ai_required':is_ai,'ai_evidence':{'filename':name_ai,'confirmed_request':confirmed_ai,'checked_class':ai_label}}


def acknowledged(value):
    return value is True or type(value) is int and value == 1 or value == '1'


def feedback(receipt):
    target=receipt.get('target',{})
    confirmed=receipt.get('status')=='CONFIRMED'
    return {'提示':'上传成功，已回查素材ID及分类' if confirmed else '已提交，等待入库确认' if receipt.get('native_upload_success') else '未上传／请看回执',
            '成功数量':1 if confirmed else 0,'项目名称':target.get('category'),'一类':target.get('source_type'),
            '类标签':{'二类':target.get('source_direction'),'角色提交值':target.get('roles',[])},
            '需求人':target.get('defaults',{}).get('demand_name'),
            '需求人编号':target.get('business_mapping',{}).get('requester_code'),
            '所用AI':target.get('defaults',{}).get('ai_source') or '无',
            '素材名称':receipt.get('upload_name'),'素材ID':receipt.get('material_id'),
            '上传合并秒数':receipt.get('upload_elapsed_seconds'),
            '本条计时秒数':receipt.get('elapsed_seconds'),'一分钟内回查成功':receipt.get('within_60_seconds',False),
            '提醒':receipt.get('warnings',[]),'回执':receipt.get('evidence_path'),
            'verification_scope':'ID、名称、分类、一类和二类来自列表回查；角色字段明确标为提交值，详情审计另留证。'}


class Api:
    def __init__(self, secret, creator_hash, display_name, started=None):
        self.secret = secret
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({'User-Agent': 'RongyaoVideoListUpload/20261010', 'Referer': ENTRY})
        self.response_metadata=[]
        self.started = started or time.monotonic()
        self.deadline = self.started+60
        self.form_html = self.request(ENTRY, html=True)
        self.soup = BeautifulSoup(self.form_html, 'html.parser')
        self.private_form = {}
        for key in ('advertiser_id', 'token', 'create_name'):
            fields = self.soup.select('#' + key)
            if len(fields) != 1 or not fields[0].get('value'):
                fail('FORM_NOT_READY', '正确入口的认证表单字段不唯一。')
            self.private_form[key] = fields[0]['value']
        # 浏览器只读工具会把隐藏字段值变成<redacted>，不能用于认证摘要。
        if self.private_form['create_name'].strip() != display_name:
            fail('IDENTITY_MISMATCH', '正确入口API返回的制作人不是指定登录名。')
        self.identity = {'display_name': display_name, 'user_id': None,
                         'proof': '同页API实际create_name与指定登录名一致',
                         'numeric_user_id_verified': False, 'scope': 'single_current_session'}

    def fork(self):
        """每个线程独立HTTP会话；本批复用一次已认证表单与共同计时。"""
        child=object.__new__(Api)
        child.secret=self.secret
        child.session=requests.Session()
        child.session.trust_env=False
        child.session.headers.update(self.session.headers)
        child.started,child.deadline=self.started,self.deadline
        child.form_html,child.soup=self.form_html,self.soup
        child.private_form=dict(self.private_form)
        child.identity=dict(self.identity)
        child.response_metadata=[]
        return child

    def request(self, url, method='GET', params=None, file=None, html=False):
        p = urlsplit(url)
        if p.scheme != 'http' or p.hostname not in ('adopenplatform.backend.example.invalid', 'cdnapk.backend.example.invalid') or p.port not in (None,80) or p.username or p.password or p.fragment:
            fail('ORIGIN_INVALID', '只使用已观察的正确后台及CDN。')
        remaining = 60 if self.deadline is None else self.deadline - time.monotonic()
        if remaining <= 0:
            fail('TIME_BUDGET', '一分钟已用完；保留受理账本，不重发。')
        origin = p.scheme + '://' + p.netloc
        headers = {'Cookie': self.secret['cookies_by_origin'].get(origin, '')}
        if method == 'POST':
            headers['Origin'] = BASE
        connect=min(3,remaining/3)
        kwargs = {'timeout': (connect,max(.01,min(20,remaining-connect-.05))), 'allow_redirects':False,'headers':headers}
        if method == 'GET': kwargs['params'] = params
        else:
            kwargs['data'] = params
            if file is not None: kwargs['files'] = {'data': ('blob',file,'application/octet-stream')}
        try: response = self.session.request(method,url,**kwargs)
        except requests.RequestException:
            fail('ACCEPTANCE_UNKNOWN' if method=='POST' else 'READ_FAILED', '请求未取得结果；不自动重试写入。')
        if response.status_code in (301,302,303,307,308,401): fail('LOGIN_EXPIRED','正确后台要求重新登录。')
        if response.status_code != 200: fail('HTTP_ERROR','HTTP '+str(response.status_code))
        self.response_metadata.append({'host':p.hostname,'status':response.status_code,
                                       'content_type':response.headers.get('Content-Type'),
                                       'cache_control':response.headers.get('Cache-Control'),
                                       'server':response.headers.get('Server'),
                                       'set_cookie_count':len(response.cookies)})
        if html:
            response.encoding = response.apparent_encoding or 'utf-8'
            return response.text
        try: data=response.json()
        except ValueError: fail('RESPONSE_INVALID','后台响应不是预期JSON。')
        if not isinstance(data,dict): fail('RESPONSE_INVALID','后台JSON结构变化。')
        return data

    def redacted_message(self,response):
        message=response.get('message',response.get('info',''))
        if not isinstance(message,str): return None
        for value in sorted([*self.private_form.values(),*self.secret['cookies_by_origin'].values()],key=len,reverse=True):
            if value: message=message.replace(value,'[private]')
        for cookie in self.secret['cookies_by_origin'].values():
            for part in cookie.split(';'):
                value=part.partition('=')[2].strip()
                if value: message=message.replace(value,'[private]')
        return re.sub(r'https?://\S+|[A-Za-z0-9_=-]{24,}','[private]',message)[:500]

    def defaults(self):
        out={}
        for key in ('ai_source','demand_name','is_redbag','region_type'):
            select=self.soup.select_one('#'+key)
            if select is None: fail('FORM_CHANGED','原生表单缺字段：'+key)
            options=select.select('option[selected]') or select.select('option')[:1]
            out[key]=options[0].get('value','') if options else ''
        radio=self.soup.select_one('input[name="origin_type"][checked]')
        out['origin_type']=radio.get('value','1') if radio else '1'
        return out

    def list_html(self,params=None):
        return self.request(LIST,params=params,html=True)

    def lookup(self,name,target=None):
        stem=name[:-4]
        params={'category_type':'117','name':stem}
        if target:
            params.update(source_type=target['source_type'],source_direction=target['source_direction'])
        soup=BeautifulSoup(self.list_html(params),'html.parser')
        matches=[]
        for checkbox in soup.select('input[name="id[]"]'):
            card=checkbox.parent
            title=card.select_one('input[type="text"][onchange^="saveName"]')
            if title and title.get('value')==stem:
                ident=checkbox.get('value','')
                if not re.fullmatch('[1-9][0-9]*',ident): fail('READBACK_INVALID','素材ID不是有效数字。')
                matches.append({'id':ident,'name':stem,'category':'火影','category_type':'117',
                                'link':LIST+'&'+urlencode(params),
                                'metadata_proof':'同一视频列表按分类、一类、二类筛选后的完整名称及ID' if target else '同一视频列表完整名称及ID',
                                'source_type':target['source_type'] if target else None,
                                'source_direction':target['source_direction'] if target else None})
        if len(matches)>1: fail('READBACK_AMBIGUOUS','完整名称返回多条素材，停止新增或修改。')
        return matches[0] if matches else None


def native_join_fields(api,row,nonce,total,business):
    request=row['request']
    values=dict(total=total,time=nonce,name=row['upload_name'],**api.private_form,**business,
                tag=','.join(request['roles']),category_type='117',tmp_flag=1)
    fields=list(values.items())
    fields.append(('source_ip',''))
    fields.append(('source_type[]',request['source_type']))
    fields.append(('source_direction[]',request['source_direction']))
    return fields


def execute(command,api,precheck_item=None,defer_readback=False):
    items=read_json(PLAN)['items']
    candidates=[x for x in items if x['upload_name']==command.get('name')]
    if len(candidates)!=1: fail('INPUT_INVALID','只处理本批已检查且唯一的文件名。')
    row=candidates[0]
    if row['status']!='READY' or row['media'].get('full_decode') is not True:
        fail('INPUT_UNCHECKED','没有本批已有的完整解码检查。')
    parsed=filename_parameters(row['upload_name'])
    if parsed['suggested_upload_name']!=row['upload_name']: fail('NAME_CORRECTION_REQUIRED','上传前需要修正名称。')
    target={k:row['request'][k] for k in ('category','source_type','source_direction','roles')}
    business,mapping=business_fields(row,command)
    if any(api.defaults().get(k)!=v for k,v in FIXED_DEFAULTS.items()):
        fail('DEFAULT_MAPPING_CHANGED','页面默认业务参数已变化，保留固定映射，未上传。')
    for field in ('demand_name','ai_source'):
        options={x.get('value') for x in api.soup.select('#'+field+' option')}
        if business[field] not in options:
            fail('BUSINESS_OPTION_MISSING','当前表单缺少已配置的 '+field+' 选项，未上传。')
    if (target['source_type'],target['source_direction']) not in {('剪辑','竞品'),('小剧场','AI'),('口播','攻略')}:
        fail('CLASS_MAPPING_INVALID','本批一类／二类不在已有核验映射内。')
    if set(target['roles'])-{'宇智波鼬','佐助','带土','卡卡西'}:
        fail('ROLE_MAPPING_INVALID','角色标签不在本批核验字典内。')
    categories={x.get_text(strip=True):x.get('value') for x in api.soup.select('#category_type option')}
    firsts={x.get('value') for x in api.soup.select('#source_type option')}
    if target['category']!='火影' or categories.get('火影')!='117' or target['source_type'] not in firsts:
        fail('MAPPING_CHANGED','当前原生表单的目标分类或一类变化。')
    # 已有目录检查只复用媒体结论；直接读取一次成为本次发送的固定字节快照。
    content=Path(row['path']).read_bytes()
    if len(content)!=row['media']['bytes'] or hashlib.sha256(content).hexdigest()!=row['media']['sha256']:
        fail('INPUT_CHANGED','此前检查后文件已改变，未提交。')
    target.update(category_type='117',defaults=business,business_mapping=mapping)
    receipt={'schema':'rongyao-video-list-fast-1','entry':ENTRY,'upload_name':row['upload_name'],
             'file_sha256':row['media']['sha256'],'bytes':len(content),'target':target,
             'identity':api.identity,'warnings':parsed['warnings'],'status':'PREPARED','material_id':None,
             'phases':{},'timing_scope':'从命令开始计时，含表单、文件SHA、全批预检、排队、上传合并和回查；认证文件接入另记',
             'cached_media_check_reused':True,'browser_video_upload':False,
             'started_at_epoch':time.time()-(time.monotonic()-api.started)}
    key=native.digest({'entry':ENTRY,'file_sha256':receipt['file_sha256'],'name':row['upload_name'],'target':target})
    receipt['request_key']=key
    queue=native.private_queue_dir('~/.config/rongyao-material-upload','single-current')
    OUT.mkdir(parents=True,exist_ok=True)
    evidence=OUT/(key+'.json')
    def save(status):
        receipt['status']=status
        receipt['elapsed_seconds']=round(time.monotonic()-api.started,3)
        receipt['within_60_seconds']=status=='CONFIRMED' and receipt['elapsed_seconds']<60
        receipt['evidence_path']=str(evidence)
        with native.ledger(queue) as db:
            native.save_receipt(db,key,status,receipt)
            atomic_json(evidence,receipt)
    with native.ledger(queue) as db:
        prior=db.execute('SELECT receipt FROM receipts WHERE request_key=?',(key,)).fetchone()
        if prior:
            old=json.loads(prior[0])
            return dict(old,replayed=False,existing_receipt_reused=True)
        for other in db.execute('SELECT receipt FROM receipts'):
            old=json.loads(other[0])
            if old.get('file_sha256')==receipt['file_sha256'] or old.get('upload_name')==row['upload_name']:
                join=old.get('phases',{}).get('join',old.get('phases',{}).get('join_register',{}))
                response=join.get('response',join)
                if (command.get('retry_rejected') is True and join.get('state')=='REJECTED'
                        and type(response.get('status')) is int and response['status']==0 and not old.get('material_id')
                        and old.get('entry')!=ENTRY):
                    receipt['supersedes_rejected_request_key']=old.get('request_key')
                    receipt['retry_authorization']='用户本轮明确要求重新提交；只重试旧入口明确status=0的拒绝，仍须新入口名称预检。'
                else:
                    fail('PRIOR_ATTEMPT_HELD','同文件已有受理记录，只能回查，未重发。')
        receipt['evidence_path']=str(evidence)
        native.save_receipt(db,key,'RESERVED',dict(receipt,status='RESERVED'))
    phase=None
    try:
        began=time.monotonic()
        if precheck_item is None:
            data=api.request(PRECHECK,'POST',[('names[]',row['upload_name'])])
            info=data.get('info')
            if not acknowledged(data.get('status')) or not isinstance(info,list) or len(info)!=1:
                fail('PRECHECK_INVALID','原生批量名称预检结构不符，未上传。')
            item=info[0]
            if not isinstance(item,dict) or str(item.get('num'))!='0':
                fail('PRECHECK_INVALID','原生名称预检未返回本条对应结果。')
        else:
            item=precheck_item
        receipt['phases']['name_precheck']={'status':item.get('status'),'message':api.redacted_message(item),
                                           'elapsed_seconds':round(time.monotonic()-began,3)}
        if not acknowledged(item.get('status')):
            record=api.lookup(row['upload_name'])
            receipt.update(readback=record,material_id=record['id'] if record else None)
            save('SKIPPED_EXISTING' if record else 'NAME_REJECTED')
            return receipt
        total=(len(content)+CHUNK_BYTES-1)//CHUNK_BYTES
        nonce=native.reserve_nonce(queue,key)
        receipt['chunk_count']=total
        for index in range(total):
            phase='chunk_'+str(index+1)
            receipt['phases'][phase]={'state':'SENDING'}
            save('SENDING')
            began=time.monotonic()
            data=api.request(CDN+'?act=upload','POST',{'name':row['upload_name'],'total':total,'index':index+1,'time':nonce},
                             file=content[index*CHUNK_BYTES:(index+1)*CHUNK_BYTES])
            receipt['phases'][phase]={'state':'ACK' if acknowledged(data.get('status')) else 'REJECTED',
                                     'status':data.get('status'),'message':api.redacted_message(data),
                                     'elapsed_seconds':round(time.monotonic()-began,3)}
            if not acknowledged(data.get('status')):
                save('REJECTED'); return receipt
            save('SENDING')
        phase='join_register'
        receipt['phases'][phase]={'state':'SENDING','field_names':[x[0] for x in native_join_fields(api,row,nonce,total,business)]}
        save('SENDING')
        began=time.monotonic()
        data=api.request(CDN+'?act=join','POST',native_join_fields(api,row,nonce,total,business))
        public_data=data.get('data')
        if isinstance(public_data,(int,float,bool)) or public_data is None:
            data_info=public_data
        elif isinstance(public_data,str):
            data_info=api.redacted_message({'message':public_data})
        elif isinstance(public_data,dict):
            data_info={k:v if isinstance(v,(int,float,bool)) or v is None else api.redacted_message({'message':v}) if isinstance(v,str) else {'type':type(v).__name__}
                       for k,v in public_data.items() if k.lower() not in ('token','advertiser_id','cookie','password')}
        else:
            data_info={'type':type(public_data).__name__,'length':len(public_data)}
        receipt['phases'][phase].update(state='ACK' if acknowledged(data.get('status')) else 'REJECTED',
                                       status=data.get('status'),message=api.redacted_message(data),
                                       response_keys=list(data),data_summary=data_info,elapsed_seconds=round(time.monotonic()-began,3))
        if not acknowledged(data.get('status')):
            save('REJECTED'); return receipt
        receipt.update(native_upload_success=True,upload_elapsed_seconds=round(time.monotonic()-api.started,3),
                       upload_within_60_seconds=time.monotonic()-api.started<60,
                       roles_sent=target['roles'],roles_independently_readback=False)
        save('JOIN_ACK')
        if defer_readback:
            save('JOIN_ACK_PENDING_READBACK')
            return receipt
        began=time.monotonic()
        record=None
        attempts=[]
        for due in (0,30,58):
            wait=due-(time.monotonic()-api.started)
            if wait>0: time.sleep(wait)
            record=api.lookup(row['upload_name'],target)
            attempts.append({'at_seconds':round(time.monotonic()-api.started,3),'found':record is not None})
            if record: break
        receipt['phases']['readback']={'elapsed_seconds':round(time.monotonic()-began,3),'found':record is not None,'attempts':attempts}
        receipt.update(readback=record,material_id=record['id'] if record else None,
                       roles_sent=target['roles'],roles_independently_readback=False)
        save('CONFIRMED' if record else 'JOIN_ACK_PENDING_READBACK')
        return receipt
    except UploadError as exc:
        receipt.update(error=exc.code,reason=str(exc))
        save('ACCEPTANCE_UNKNOWN' if phase and receipt['phases'][phase].get('state')=='SENDING' else
             'JOIN_ACK_PENDING_READBACK' if receipt['phases'].get('join_register',{}).get('state')=='ACK' else 'BLOCKED')
        return receipt



def reconcile(command,api):
    row=next(x for x in read_json(PLAN)['items'] if x['upload_name']==command['name'])
    record=api.lookup(row['upload_name'])
    filtered=api.lookup(row['upload_name'],row['request'])
    current={'checked_at_epoch':time.time(),'record':record,'filtered_record':filtered,'read_only':True}
    for file in OUT.glob('*.json'):
        previous=read_json(file)
        if previous.get('upload_name')!=row['upload_name']: continue
        previous['latest_reconciliation']=current
        if record and filtered and record['id']==filtered['id']:
            first=previous.get('status')!='CONFIRMED'
            previous.update(status='CONFIRMED',material_id=record['id'],readback=filtered)
            if first:
                previous['confirmation_elapsed_seconds']=round(time.time()-previous.get('started_at_epoch',file.stat().st_mtime-previous['elapsed_seconds']),3)
                previous['within_60_seconds']=False
        queue=native.private_queue_dir('~/.config/rongyao-material-upload','single-current')
        with native.ledger(queue) as db: native.save_receipt(db,previous['request_key'],previous['status'],previous)
        atomic_json(file,previous)
        return previous
    return current


def execute_batch(command,api):
    items=read_json(PLAN)['items']
    names=command.get('names') or [x['upload_name'] for x in items]
    if not isinstance(names,list) or not names or len(set(names))!=len(names):
        fail('INPUT_INVALID','批量名称必须是无重复列表。')
    by_name={x['upload_name']:x for x in items}
    for name in names:
        if name not in by_name: fail('INPUT_INVALID','只接受已验Plan内的素材。')
        business_fields(by_name[name],command)
    data=api.request(PRECHECK,'POST',[('names[]',x) for x in names])
    info=data.get('info')
    if not acknowledged(data.get('status')) or not isinstance(info,list) or len(info)!=len(names):
        fail('PRECHECK_INVALID','批量名称预检不完整，未上传。')
    checks={}
    for item in info:
        if not isinstance(item,dict) or str(item.get('num')) not in {str(i) for i in range(len(names))}:
            fail('PRECHECK_INVALID','批量名称预检编号不符，未上传。')
        i=int(item['num'])
        if i in checks: fail('PRECHECK_INVALID','批量名称预检编号重复，未上传。')
        checks[i]=item
    results={}
    def run_one(index,name):
        child=api.fork()
        try:
            return execute(dict(command,action='run',name=name),child,checks[index],defer_readback=True)
        except UploadError as exc:
            return {'status':'BLOCKED','upload_name':name,'error':exc.code,'reason':str(exc)}
        finally:
            child.session.close()
    workers=min(4,len(names))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(run_one,i,name):name for i,name in enumerate(names)}
        for future in as_completed(futures): results[futures[future]]=future.result()
        # 合并受理就释放发送线程；异步入库等待不能堵住后面的文件。
        def read_one(name):
            row=results[name]
            child=api.fork()
            try:
                record=child.lookup(name,row['target'])
                attempts=row.setdefault('phases',{}).setdefault('readback',{}).setdefault('attempts',[])
                attempts.append({'at_seconds':round(time.monotonic()-api.started,3),'found':record is not None})
                row.update(readback=record,material_id=record['id'] if record else None,
                           status='CONFIRMED' if record else 'JOIN_ACK_PENDING_READBACK',
                           elapsed_seconds=round(time.monotonic()-api.started,3))
                row['within_60_seconds']=row['status']=='CONFIRMED' and row['elapsed_seconds']<60
            except UploadError as exc:
                row.update(error=exc.code,reason=str(exc),status='JOIN_ACK_PENDING_READBACK')
            finally:
                child.session.close()
            queue=native.private_queue_dir('~/.config/rongyao-material-upload','single-current')
            with native.ledger(queue) as db:
                native.save_receipt(db,row['request_key'],row['status'],row)
                atomic_json(Path(row['evidence_path']),row)
            return row
        for due in (0,30,56):
            pending=[name for name,row in results.items() if row.get('status')=='JOIN_ACK_PENDING_READBACK']
            if not pending: break
            wait=due-(time.monotonic()-api.started)
            if wait>0: time.sleep(wait)
            futures={pool.submit(read_one,name):name for name in pending}
            for future in as_completed(futures): results[futures[future]]=future.result()
    receipts=[results[name] for name in names]
    result={'schema':'rongyao-fast-batch-1','entry':ENTRY,'parallel_workers':workers,
            'form_reads':1,'native_name_prechecks':1,'feedback_deadline_seconds':60,
            'elapsed_seconds':round(time.monotonic()-api.started,3),
            'successful_count':sum(x.get('status')=='CONFIRMED' for x in receipts),
            'pending_count':sum(x.get('status') in ('JOIN_ACK','JOIN_ACK_PENDING_READBACK','ACCEPTANCE_UNKNOWN') for x in receipts),
            'items':[dict(feedback(x),状态=x.get('status'),错误=x.get('error'),说明=x.get('reason')) for x in receipts]}
    atomic_json(OUT/'latest-batch-feedback.json',result)
    return result


def command(command,secret,_legacy_creator_hash,display_name):
    started=time.monotonic()
    # 在认证GET和网络写入前暴露缺失映射，避免为此启动长流程。
    if command['action'] in ('run','batch'):
        selected=set(command.get('names',[])) if command['action']=='batch' else {command.get('name')}
        for row in read_json(PLAN)['items']:
            if command['action']=='batch' and not selected or row['upload_name'] in selected:
                business_fields(row,command)
    api=Api(secret,None,display_name,started)
    if command['action']=='run': return execute(command,api)
    if command['action']=='batch': return execute_batch(command,api)
    if command['action']=='reconcile': return reconcile(command,api)
    if command['action']=='precheck':
        names=command.get('names') or [x['upload_name'] for x in read_json(PLAN)['items']]
        data=api.request(PRECHECK,'POST',[('names[]',x) for x in names])
        result={'status':data.get('status'),'names':names,'checked_at_epoch':time.time(),
                'items':[{'status':x.get('status'),'num':x.get('num'),'message':api.redacted_message(x)}
                         for x in data.get('info',[]) if isinstance(x,dict)]}
        OUT.mkdir(parents=True,exist_ok=True)
        atomic_json(OUT/'name-precheck-final.json',result)
        return result
    fail('COMMAND_INVALID','只接受run、batch、precheck、reconcile、quit。')
