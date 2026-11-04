import contextlib,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import upload_service as service
from upload_api import validate_url,CDN,PRECHECK,Stop
def operations_path():
    file=Path(__file__).resolve()
    sibling=file.parents[2]/'rongyao-operations/scripts/rongyao.py'
    return sibling if sibling.is_file() else file.parents[3]/'rules/implementation/rongyao-tools/skills/rongyao-operations/scripts/rongyao.py'

class UploadTests(unittest.TestCase):
    def test_exact_post_allowlist(self):
        for u in ['http://attacker.example/','http://adopenplatform.backend.example.invalid/','http://cdnapk.backend.example.invalid/api/controller/ApiUploadVideo.php?act=delete']:
            with self.assertRaises(Stop):validate_url(u,True)
        validate_url(CDN+'?act=upload',True);validate_url(CDN+'?act=join',True);validate_url(PRECHECK,True)
    def run_case(self,fail_chunk=False,fail_join=False,conflict=False):
        from types import SimpleNamespace
        path=operations_path()
        spec=importlib.util.spec_from_file_location('test_real_ops',path);ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(ops)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'state';file=root/'v.mp4';file.write_bytes(b'synthetic video bytes')
            p={'category_type':'117','ai_source':'','origin_type':'1','demand_name':'原创','gid':'193','is_redbag':'0','region_type':'','role':['凯'],'source_ip':[],'source_type':['口播'],'source_direction':['攻略']}
            item={'file':str(file),'filename':'260101D1-test-原创-37.mp4','sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'parameters':p,'provenance':{'requester_explicit_original_override':True,'designer_name':'fixture','designer_source':'explicit test fixture'}}
            value={'job_id':'fixture','items':[item],'test_only':False};ledger=ops.Ledger(state);ledger.create(value)
            proxy=SimpleNamespace(load_runtime=lambda w:SimpleNamespace(mutation=lambda *a,**kw:contextlib.nullcontext()),reviewed_plan=lambda p:value,plan_digest=ops.plan_digest,production_number=ops.production_number,PENDING=ops.PENDING,Ledger=lambda:ops.Ledger(state),registered_plan=lambda jid:ops.registered_plan(jid,state),UPLOAD_SCOPE=ops.UPLOAD_SCOPE,save=ops.save)
            class Api:
                def __init__(self):self.calls=[]
                def validate_fields(self,*a):return {'token':'fixture-token','advertiser_id':'fixture-id','create_name':'fixture'}
                def lookup(self,*a):return None
                def json(self,url,fields=None,content=None):
                    self.calls.append((url,fields,content))
                    if url==PRECHECK:return {'status':1,'info':[{'num':1 if conflict else 0,'status':1}]}
                    if fail_chunk or (fail_join and url==CDN+'?act=join'):raise Stop('ACCEPTANCE_UNKNOWN')
                    return {'status':1}
            api=Api()
            with patch.object(service,'operations',lambda:proxy),patch.object(service,'verify_source',lambda:'fixture'),patch.object(service,'legacy_hold',lambda i:None):
                args={'workspace':str(root),'plan':'fixture','authorization_ticket':'fixture'}
                if conflict:
                    with self.assertRaisesRegex(ValueError,'NATIVE_NUMBER_OR_NAME_CONFLICT'):service.submit(api,args,root)
                    self.assertEqual(ledger.existing(item['filename'])['state'],'blocked_before_selection')
                    self.assertEqual([x[0] for x in api.calls],[PRECHECK])
                elif fail_chunk or fail_join:
                    with self.assertRaises(Stop):service.submit(api,args,root)
                    self.assertEqual(ledger.existing(item['filename'])['state'],'submission_unknown')
                    count=len(api.calls)
                    retry=service.submit(api,args,root)
                    self.assertEqual(retry['items'][0]['status'],'PRIOR_SUBMISSION_NEEDS_RECONCILIATION')
                    self.assertEqual(len(api.calls),count)
                    evidence=json.loads(ledger.existing(item['filename'])['evidence'])
                    self.assertEqual(evidence['error'],'ACCEPTANCE_UNKNOWN')
                else:
                    r=service.submit(api,args,root);self.assertEqual(r['items'][0]['status'],'submitted_pending')
                    self.assertEqual(r['items'][0]['reconcile_after_seconds'],0);self.assertEqual(r['items'][0]['fallback_processing_seconds'],120)
                    self.assertEqual(ledger.existing(item['filename'])['state'],'submitted_pending')
                    chunk=api.calls[1];join=api.calls[2];self.assertEqual(dict(chunk[1])['time'],dict(join[1])['time']);self.assertEqual(dict(join[1])['tag'],'凯')
                    self.assertNotIn('fixture-token',json.dumps(r))
    def test_unknown_acceptance_never_reuploads(self):self.run_case(True)
    def test_native_chunk_join_and_shared_checkpoint(self):self.run_case(False)
    def test_unknown_join_never_reuploads(self):self.run_case(fail_join=True)
    def test_native_number_conflict_stops_before_bytes(self):self.run_case(conflict=True)
    def test_old_service_code_cannot_submit_after_source_update(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'scripts').mkdir()
            (root/'scripts/upload_service.py').write_text('new code')
            (root/'manifest.json').write_text(json.dumps({'version':'new','files':{'scripts/upload_service.py':hashlib.sha256(b'new code').hexdigest()}}))
            with patch.object(service,'SOURCE',root),patch.object(service,'LOADED_SOURCE',{'upload_service.py':hashlib.sha256(b'old code').hexdigest()}):
                with self.assertRaisesRegex(ValueError,'UPLOAD_SERVICE_RESTART_REQUIRED'):service.submit(None,{},root)

class FieldReadTests(unittest.TestCase):
    """Count actual API entry calls while keeping every validation on fresh data."""
    def setUp(self):
        from types import SimpleNamespace
        from upload_api import Api,ENTRY,ROLES,DIRECTIONS
        self.ENTRY,self.ROLES,self.DIRECTIONS=ENTRY,ROLES,DIRECTIONS
        self.form_reads=0;self.role='佐助';self.direction='AI'
        self.params={'category_type':'117','ai_source':'SD2拼框','origin_type':'1',
                     'demand_name':'fixture-requester','gid':'193','is_redbag':'0',
                     'region_type':'fixture-second','role':['佐助'],'source_ip':[],
                     'source_type':['小剧场'],'source_direction':['AI']}
        self.api=Api(SimpleNamespace(http=SimpleNamespace(client=None),state={}))
        request_patch=patch.object(self.api,'request',side_effect=self.respond)
        self.request=request_patch.start();self.addCleanup(request_patch.stop)
    def respond(self,url,fields=None,content=None,**kwargs):
        if url==self.ENTRY:
            self.form_reads+=1
            selects=''.join(f'<select id="{key}"><option value="{value}">{value}</option></select>'
                            for key,value in [('category_type','117'),('ai_source','SD2拼框'),
                                              ('demand_name','fixture-requester'),('gid','193'),
                                              ('region_type','fixture-second'),('is_redbag','0'),
                                              ('source_type','小剧场')])
            return (selects+'<select id="source_ip"></select>'
                    '<input id="advertiser_id" value="fixture-advertiser">'
                    '<input id="token" value="fixture-private-token">'
                    f'<input id="create_name" value="fixture-account-{self.form_reads}">'
                    '<input name="origin_type" value="1" checked>'
                    '<script>20971520 act=upload act=join tag:roleTag tmp_flag:1 ac=getVideoNames</script>')
        if url==self.ROLES:return json.dumps({'status':1,'info':[{'name':self.role}]})
        if url==self.DIRECTIONS:return json.dumps({'status':1,'info':{'394':self.direction}})
        self.fail('Unexpected API call: '+url)
    def test_validate_reads_one_form_and_both_current_enums(self):
        hidden=self.api.validate_fields(self.params)
        self.assertEqual(self.form_reads,1)
        self.assertEqual([call.args[0] for call in self.request.call_args_list],
                         [self.ENTRY,self.ROLES,self.DIRECTIONS])
        self.assertEqual(hidden['create_name'],'fixture-account-1')
    def test_three_items_read_three_forms_without_cross_call_identity_or_enum_cache(self):
        accounts=[self.api.validate_fields(self.params)['create_name'] for _ in range(3)]
        self.assertEqual(accounts,['fixture-account-1','fixture-account-2','fixture-account-3'])
        self.assertEqual(self.form_reads,3)
        self.assertEqual(sum(call.args[0]==self.ROLES for call in self.request.call_args_list),3)
        self.assertEqual(sum(call.args[0]==self.DIRECTIONS for call in self.request.call_args_list),3)
    def test_later_role_or_direction_change_is_not_reused_from_an_earlier_validation(self):
        self.api.validate_fields(self.params)
        self.role='卡卡西'
        with self.assertRaisesRegex(Stop,'ROLE_OPTION_MISSING'):self.api.validate_fields(self.params)
        self.role='佐助';self.direction='AE'
        with self.assertRaisesRegex(Stop,'DIRECTION_OPTION_MISSING'):self.api.validate_fields(self.params)
    def test_form_read_failure_stops_before_enum_queries(self):
        self.request.side_effect=Stop('LOGIN_EXPIRED')
        with self.assertRaisesRegex(Stop,'LOGIN_EXPIRED'):self.api.validate_fields(self.params)
        self.assertEqual([call.args[0] for call in self.request.call_args_list],[self.ENTRY])
    def test_public_fields_still_reads_its_own_form_without_exposing_private_fields(self):
        result=self.api.fields('193','小剧场')
        self.assertEqual(self.form_reads,1)
        self.assertEqual(result['display_name'],'fixture-account-1')
        self.assertEqual(result['roles'],[{'name':'佐助'}])
        self.assertEqual(result['directions'],{'394':'AI'})
        self.assertNotIn('fixture-private-token',json.dumps(result))
        self.assertNotIn('fixture-advertiser',json.dumps(result))
    def test_probe_is_one_protected_get_without_auth_or_enum_side_effects(self):
        self.api.engine.state={'status':'ready','last_protected_read_at':42}
        result=self.api.fields('193','小剧场',probe=True)
        self.assertTrue(result['authenticated']);self.assertEqual(result['probe_scope'],'form_only')
        self.assertFalse(result['dynamic_enums_verified']);self.assertEqual(self.form_reads,1)
        self.assertEqual(self.api.engine.state,{'status':'ready','last_protected_read_at':42})
        self.assertEqual(len(self.request.call_args_list),1)
        call=self.request.call_args_list[0];self.assertEqual(call.args,(self.ENTRY,))
        self.assertEqual(call.kwargs,{'_rebind':False,'_timeout':10,'_probe':True})
        self.assertNotIn('fixture-private-token',json.dumps(result));self.assertNotIn('fixture-advertiser',json.dumps(result))

class ReadbackTests(unittest.TestCase):
    def api(self,html):
        from upload_api import Api
        api=object.__new__(Api);api.request=lambda *a:html
        return api
    def card(self,ident='1',name='sample'):
        return f'<div><input name="id[]" value="{ident}"><input type="text" onchange="saveName(this)" value="{name}"></div>'
    def test_login_or_unknown_page_is_not_empty(self):
        with self.assertRaisesRegex(Stop,'LIST_TOTAL_UNVERIFIED'):self.api('<html>login</html>').lookup('sample.mp4')
    def test_partial_page_cannot_prove_absence_or_uniqueness(self):
        with self.assertRaisesRegex(Stop,'LIST_REQUIRES_PAGINATION'):
            self.api('视频数量为：2'+self.card()).lookup('sample.mp4')
    def test_total_mismatch_rejected(self):
        with self.assertRaisesRegex(Stop,'LIST_TOTAL_MISMATCH'):
            self.api('视频数量为：0'+self.card()).lookup('sample.mp4')
    def test_unique_full_name(self):
        self.assertEqual(self.api('视频数量为：1'+self.card()).lookup('sample.mp4')['id'],'1')
    def test_duplicate_full_name(self):
        with self.assertRaisesRegex(Stop,'AMBIGUOUS_NAME'):
            self.api('视频数量为：2'+self.card()+self.card('2')).lookup('sample.mp4')
    def test_duplicate_id(self):
        with self.assertRaisesRegex(Stop,'LIST_DUPLICATE_ID'):
            self.api('视频数量为：2'+self.card()+self.card()).lookup('sample.mp4')
    def test_detail_missing_or_wrong_attribution_not_verified(self):
        p={'role':['凯'],'source_type':['口播'],'source_direction':['攻略'],'demand_name':'原创','ai_source':''}
        self.assertFalse(service.detail_acceptance({},p)['verified'])
        fields={'角色/标签':['凯'],'一类':['口播'],'二类':['攻略'],'需求人':'别人','AI来源':''}
        r=service.detail_acceptance(fields,p)
        self.assertEqual(r['checks']['需求人']['status'],'mismatch');self.assertFalse(r['verified'])
    def test_receipts_do_not_overwrite_batch(self):
        with tempfile.TemporaryDirectory() as d:
            class Ops:
                @staticmethod
                def save(path,obj):path.write_text(json.dumps(obj))
            for n in ['a.mp4','b.mp4']:service.save_receipt(Ops,Path(d),'job',{'filename':n},{'filename':n})
            self.assertEqual(len(list(Path(d).glob('*receipt.json'))),2)
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        path=operations_path()
        spec=importlib.util.spec_from_file_location('recovery_ops',path);self.ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.ops)
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ledger=self.ops.Ledger(self.root/'state')
        self.item={'filename':'261020D1-test-原创-37.mp4','sha256':'a'*64,'parameters':{'category_type':'117','region_type':'','origin_type':'1','source_ip':[],'role':['凯'],'source_type':['口播'],'source_direction':['攻略'],'demand_name':'原创','ai_source':''},'provenance':{'designer_name':'fixture','designer_source':'explicit fixture'}}
        self.ledger.create({'job_id':'job','items':[self.item]});self.ledger.claim('job',self.item)
        self.proxy=SimpleNamespace(Ledger=lambda:self.ledger,save=self.ops.save)
        self.patch=patch.object(service,'operations',lambda:self.proxy);self.patch.start()
        from unittest.mock import Mock
        self.api=Mock();self.api.lookup.return_value={'id':'123','name':self.item['filename'][:-4]};self.api.detail.return_value={}
        self.api.fields.return_value={'selects':{'category_type':{'options':[{'value':'117','text':'火影'}]},'ai_source':{'options':[{'value':'','text':'无'}]},'region_type':{'options':[{'value':'','text':'原创'}]}}}
    def tearDown(self):
        self.patch.stop();self.ledger.db.close();self.tmp.cleanup()
    def pending(self,age=130):
        import time
        self.ledger.update('job',self.item['filename'],'submission_unknown',evidence={'submitted_at':time.time()-age,'transport':'direct_http_sms'})
    def test_preparing_cannot_be_promoted_by_remote_name(self):
        result=service.reconcile(self.api,'job',self.root)
        self.assertFalse(result['all_listed']);self.api.lookup.assert_not_called()
    def test_foreign_pending_transport_requires_original_executor(self):
        self.ledger.update('job',self.item['filename'],'submission_unknown',evidence={'transport':'chrome'})
        result=service.reconcile(self.api,'job',self.root)
        self.assertEqual(result['items'][0]['error'],'RECONCILE_ORIGINAL_TRANSPORT_REQUIRED')
        self.api.lookup.assert_not_called();self.api.json.assert_not_called()
    def test_first_early_read_can_confirm_existing_original_record(self):
        self.pending(1);result=service.reconcile(self.api,'job',self.root)
        self.assertTrue(result['all_listed']);self.api.lookup.assert_called_once_with(self.item['filename'])
        self.api.json.assert_not_called();self.assertEqual(self.ledger.existing(self.item['filename'])['record_id'],'123')
    def test_first_absent_read_is_durable_and_waits_until_original_submit_plus_120(self):
        with patch.object(service.time,'time',return_value=1001):
            self.pending(1);self.api.lookup.return_value=None
            first=service.reconcile(self.api,'job',self.root)
        receipt=json.loads(self.ledger.existing(self.item['filename'])['evidence'])
        self.assertEqual(receipt['next_lookup_at'],1120);self.assertEqual(receipt['lookup_attempts'],1)
        self.assertEqual(first['items'][0]['next_lookup_at'],1120);self.assertEqual(first['items'][0]['retry_after_seconds'],119)
        self.assertTrue(first['items'][0]['lookup_attempted'])
        self.assertFalse(first['all_listed']);self.api.lookup.assert_called_once();self.api.reset_mock()
        with patch.object(service.time,'time',return_value=1119):
            pending=service.reconcile(self.api,'job',self.root)
        self.api.lookup.assert_not_called();self.assertEqual(pending['items'][0]['next_lookup_at'],1120)
        self.assertEqual(pending['items'][0]['retry_after_seconds'],1);self.api.json.assert_not_called()
        self.api.lookup.return_value={'id':'123','name':self.item['filename'][:-4]}
        with patch.object(service.time,'time',return_value=1120):
            listed=service.reconcile(self.api,'job',self.root)
        self.assertTrue(listed['all_listed']);self.api.lookup.assert_called_once()
    def test_late_absent_result_does_not_turn_into_busy_polling(self):
        with patch.object(service.time,'time',return_value=1000):
            self.pending(130);self.api.lookup.return_value=None
            service.reconcile(self.api,'job',self.root)
            service.reconcile(self.api,'job',self.root)
        self.api.lookup.assert_called_once();receipt=json.loads(self.ledger.existing(self.item['filename'])['evidence'])
        self.assertEqual(receipt['next_lookup_at'],1120);self.assertEqual(receipt['lookup_attempts'],1)
    def test_rate_limit_persists_retry_after_and_does_not_query_or_submit_again(self):
        from upload_api import ReadBackoff
        with patch.object(service.time,'time',return_value=1000):
            self.pending(1);self.api.lookup.side_effect=ReadBackoff(429,300)
            result=service.reconcile(self.api,'job',self.root)
        self.assertEqual(result['items'][0]['error'],'HTTP_READ_BACKOFF')
        receipt=json.loads(self.ledger.existing(self.item['filename'])['evidence'])
        self.assertEqual(receipt['next_lookup_at'],1300);self.assertEqual(receipt['lookup_http_status'],429)
        self.assertEqual(self.ledger.existing(self.item['filename'])['state'],'submission_unknown')
        self.api.reset_mock()
        with patch.object(service.time,'time',return_value=1299):
            service.reconcile(self.api,'job',self.root)
        self.api.lookup.assert_not_called();self.api.json.assert_not_called()
    def test_detail_failure_keeps_id_and_can_be_repaired_readonly(self):
        self.pending();self.api.detail.side_effect=Stop('DETAIL_IDENTITY_MISMATCH')
        result=service.reconcile(self.api,'job',self.root)
        self.assertTrue(result['all_listed']);self.assertFalse(result['items'][0]['detail_readback_verified'])
        self.api.detail.side_effect=None;self.api.detail.return_value={'一类':['口播']}
        self.api.lookup.reset_mock();result=service.reconcile(self.api,'job',self.root)
        self.api.lookup.assert_not_called();self.assertTrue(result['items'][0]['detail_readback_verified'])
        self.assertFalse(result['items'][0]['metadata_verified']);self.api.json.assert_not_called()
    def test_fresh_detail_failure_does_not_reuse_old_verified_flag(self):
        self.ledger.update('job',self.item['filename'],'listed','123',evidence={
            'metadata_verified':True,'detail_readback_verified':True,'attribution_schema':2})
        self.api.fields.side_effect=Stop('LOGIN_EXPIRED')
        result=service.reconcile(self.api,'job',self.root,refresh_details=True)
        self.assertTrue(result['all_listed'])
        self.assertFalse(result['all_metadata_verified'])
        self.assertEqual(result['items'][0]['detail_error'],'LOGIN_EXPIRED')
        self.assertEqual(self.ledger.existing(self.item['filename'])['record_id'],'123')
        self.api.json.assert_not_called()
    def test_failed_list_keeps_unknown_and_precise_error(self):
        self.pending();self.api.lookup.side_effect=Stop('LIST_REQUIRES_PAGINATION')
        result=service.reconcile(self.api,'job',self.root)
        self.assertFalse(result['ok']);self.assertEqual(result['items'][0]['error'],'LIST_REQUIRES_PAGINATION')
        self.assertEqual(self.ledger.existing(self.item['filename'])['state'],'submission_unknown')
    def test_sha_drift_prevents_reconcile(self):
        self.pending();self.ledger.db.execute("UPDATE files SET sha='wrong'");self.ledger.db.commit()
        with self.assertRaisesRegex(ValueError,'JOB_RESERVATION_MISMATCH'):service.reconcile(self.api,'job',self.root)
        self.api.lookup.assert_not_called()
    def test_skipped_listed_other_job_can_reconcile_original_id(self):
        self.ledger.update('job',self.item['filename'],'listed','123',evidence={'detail_readback_verified':True})
        self.ledger.create({'job_id':'reuse','items':[self.item]})
        result=service.reconcile(self.api,'reuse',self.root)
        self.assertTrue(result['all_listed']);self.assertEqual(result['items'][0]['record_id'],'123')
        self.api.lookup.assert_not_called()
    def partial_batch(self,unstarted_first=False):
        self.pending()
        untouched={**self.item,'filename':'261020D2-unstarted-原创-37.mp4','sha256':'b'*64}
        items=[untouched,self.item] if unstarted_first else [self.item,untouched]
        self.ledger.db.execute('UPDATE jobs SET plan=? WHERE id=?',(json.dumps({'job_id':'job','items':items}),'job'))
        self.ledger.db.commit()
        result=service.reconcile(self.api,'job',self.root)
        self.assertFalse(result['all_listed']);self.assertFalse(result['ok'])
        expected=['planned','listed'] if unstarted_first else ['listed','planned']
        self.assertEqual([r['status'] for r in result['items']],expected)
        unstarted=next(r for r in result['items'] if r['status']=='planned')
        self.assertEqual(unstarted['error'],'NO_UPLOAD_CHECKPOINT')
        self.assertIsNone(self.ledger.existing(untouched['filename']))
        self.api.json.assert_not_called()
    def test_partial_batch_unstarted_item_does_not_abort_reconcile(self):self.partial_batch()
    def test_unstarted_first_item_does_not_block_later_checkpoint(self):self.partial_batch(True)
    def retry_incomplete_detail(self,fields):
        complete={'角色/标签':['凯'],'一类':['口播'],'二类':['攻略'],'需求人':'原创','所用AI':'无','设计师':'fixture','分类':'火影','创作类型':'迭代','第二设计师':'原创','素材ip':[]}
        self.pending();self.api.detail.return_value=fields
        first=service.reconcile(self.api,'job',self.root)
        self.assertFalse(first['items'][0]['attribution_acceptance']['verified'])
        self.api.detail.reset_mock();self.api.detail.return_value=complete
        second=service.reconcile(self.api,'job',self.root)
        self.api.detail.assert_called_once()
        self.assertTrue(second['items'][0]['attribution_acceptance']['verified'])
        self.assertTrue(second['items'][0]['metadata_verified'])
        self.api.json.assert_not_called()
    def test_missing_detail_fields_can_be_rechecked(self):self.retry_incomplete_detail({})
    def test_mismatched_detail_fields_can_be_rechecked(self):
        self.retry_incomplete_detail({'角色/标签':['凯'],'一类':['口播'],'二类':['攻略'],'需求人':'其他','AI来源':''})
    def test_verified_detail_fields_do_not_repeat_query(self):
        self.pending()
        self.api.detail.return_value={'角色/标签':['凯'],'一类':['口播'],'二类':['攻略'],'需求人':'原创','所用AI':'无','设计师':'fixture','分类':'火影','创作类型':'迭代','第二设计师':'原创','素材ip':[]}
        service.reconcile(self.api,'job',self.root);self.api.reset_mock()
        second=service.reconcile(self.api,'job',self.root)
        self.assertEqual(second['items'][0]['record_id'],'123')
        self.api.lookup.assert_not_called();self.api.detail.assert_not_called();self.api.json.assert_not_called()

if __name__=='__main__':unittest.main()


class ForkTransportRegressionTests(unittest.TestCase):
    def test_fixed_backend_openers_never_query_system_proxies(self):
        import http.cookiejar, urllib.request
        from types import SimpleNamespace
        from unittest.mock import Mock
        from upload_api import Api, ENTRY, PORTAL
        engine=SimpleNamespace(http=SimpleNamespace(client=None,jar=http.cookiejar.CookieJar(),request=lambda url:(200,{},'<a href="http://demand.backend.example.invalid/">native</a>')))
        api=Api(engine)
        response=Mock();response.__enter__=lambda self:self;response.__exit__=lambda *a:None
        response.status=200;response.headers.get_content_charset.return_value='utf-8'
        response.read.return_value=b'ok';response.url='http://demand.backend.example.invalid/'
        with patch('urllib.request.getproxies',side_effect=AssertionError('macOS proxy lookup after fork')):
            with patch.object(urllib.request.OpenerDirector,'open',return_value=response):
                self.assertEqual(api.request(ENTRY),'ok')
                api.request=lambda url:'<a href="http://demand.backend.example.invalid/">native</a>'
                api.bind_demand()

    def test_service_eof_is_not_retried_or_reported_as_json_error(self):
        import rongyao_upload as cli
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);meta={'session_id':'fixture','socket':str(root/'fixture.sock')}
            (root/'fixture.json').write_text(json.dumps(meta))
            connection=MagicMock();connection.__enter__.return_value=connection
            connection.makefile.return_value.readline.return_value=b''
            with patch.object(cli,'BASE',root),patch.object(cli.socket,'socket',return_value=connection):
                with self.assertRaisesRegex(ValueError,'UPLOAD_SERVICE_CONNECTION_CLOSED_RECONCILE_BEFORE_RETRY'):
                    cli.rpc('submit',plan='fixture')
            connection.sendall.assert_called_once()


class NativeSsoRedirectTests(unittest.TestCase):
    def test_only_existing_business_hosts_can_redirect_during_binding(self):
        import urllib.request, http.cookiejar
        from types import SimpleNamespace
        from unittest.mock import Mock
        from upload_api import Api
        api=Api(SimpleNamespace(http=SimpleNamespace(client=None,jar=http.cookiejar.CookieJar(),request=lambda url:(200,{},'<a href="http://demand.backend.example.invalid/native">native</a>'))))
        def opened(opener,req,timeout):
            handler=next(x for x in opener.handlers if isinstance(x,urllib.request.HTTPRedirectHandler))
            for target in ['http://power.houtai.backend.example.invalid/','https://demand.backend.example.invalid/']:
                self.assertIsNotNone(handler.redirect_request(req,None,302,'',{},target))
            for target in ['http://attacker.example/','http://demand.backend.example.invalid:9000/','http://user:pw@demand.backend.example.invalid/']:
                with self.assertRaisesRegex(Stop,'DEMAND_ENTRY_REDIRECT_REJECTED'):
                    handler.redirect_request(req,None,302,'',{},target)
            response=Mock();response.__enter__=lambda self:self;response.__exit__=lambda *a:None
            response.status=200;response.url='http://demand.backend.example.invalid/';response.read.return_value=b'<html>native</html>'
            return response
        with patch.object(urllib.request.OpenerDirector,'open',opened):api.bind_demand()
