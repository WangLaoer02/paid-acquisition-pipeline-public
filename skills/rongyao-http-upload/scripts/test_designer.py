import contextlib,copy,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from attribution import intended_designer,acceptance
from upload_api import Api,SAVE_DESIGNER,Stop,validate_url
from upload_page import Page
import upload_service as service
from test_upload import operations_path

PARAMS={'category_type':'117','ai_source':'SD2拼框','origin_type':'1','demand_name':'需求人',
        'region_type':'2','source_ip':[],'source_type':['小剧场'],'source_direction':['AI'],
        'role':['带土'],'gid':'193','is_redbag':'0'}
SELECTS={'category_type':{'options':[{'value':'117','text':'火影'}]},
         'ai_source':{'options':[{'value':'SD2拼框','text':'SD2拼框'}]},
         'region_type':{'options':[{'value':'2','text':'第二设计师'}]}}
FIELDS={'分类':'火影','所用AI':'SD2拼框','创作类型':'迭代','需求人':'需求人',
        '设计师':'原设计师','第二设计师':'第二设计师','角色/标签':['带土'],'一类':['小剧场'],
        '二类':['AI'],'素材ip':'','类型':'横版','上传时间':'unchanged'}

class DesignerEvidenceTests(unittest.TestCase):
    def test_requester_and_filename_cannot_supply_designer(self):
        with self.assertRaisesRegex(Stop,'DESIGNER_SOURCE_REQUIRED'):
            intended_designer({'filename':'261021CJW8-name-某人.mp4','parameters':PARAMS})
    def test_source_designer_is_independent_of_requester(self):
        self.assertEqual(intended_designer({'provenance':{'source_native_fields':FIELDS}}),'原设计师')
    def test_conflicting_override_requires_explicit_evidence(self):
        with self.assertRaisesRegex(Stop,'DESIGNER_SOURCE_CONFLICT'):
            intended_designer({'provenance':{'source_native_fields':FIELDS,'designer_name':'需求人'}})
    def test_all_visible_fields_including_primary_designer_required(self):
        self.assertTrue(acceptance(FIELDS,PARAMS,'原设计师',SELECTS)['verified'])
        wrong={**FIELDS,'设计师':'上传账号'}
        self.assertFalse(acceptance(wrong,PARAMS,'原设计师',SELECTS)['verified'])
        missing={k:v for k,v in FIELDS.items() if k!='设计师'}
        self.assertFalse(acceptance(missing,PARAMS,'原设计师',SELECTS)['verified'])
        self.assertFalse(acceptance(FIELDS,PARAMS,None,SELECTS)['verified'])
    def test_primary_secondary_and_ai_are_separate_and_type_is_ignored(self):
        self.assertFalse(acceptance({**FIELDS,'第二设计师':'原设计师'},PARAMS,'原设计师',SELECTS)['verified'])
        result=acceptance(FIELDS,PARAMS,'原设计师',SELECTS)
        self.assertIn('所用AI',result['checks']);self.assertNotIn('AI来源',result['checks'])
        self.assertFalse(result['all_parameters_verified']);self.assertIn('类型',result['ignored_fields'])
    def test_only_exact_native_endpoint_is_allowed(self):
        validate_url(SAVE_DESIGNER,True)
        for url in [SAVE_DESIGNER+'&extra=1',SAVE_DESIGNER.replace('saveDesignName','saveOtherName')]:
            with self.assertRaises(Stop):validate_url(url,True)
    def test_native_designer_action_sends_name_and_id_only(self):
        api=object.__new__(Api)
        html="""<script>function changeDesignName(e) {var arr='{"1":"原设计师"}'; $.post('/data/?_c=creativeVideoList&_a=index&ac=saveDesignName',{id:e.id,design_name:username})} function changeSecondDesignName(e) {}</script>"""
        api.detail_page=Mock(return_value=Page(html));api.json=Mock(return_value={'status':True})
        api.set_designer({'id':'123','name':'exact-name'},'原设计师')
        api.json.assert_called_once_with(SAVE_DESIGNER,[('id','123'),('design_name','原设计师')])
        api.json.reset_mock()
        with self.assertRaisesRegex(Stop,'DESIGNER_OPTION_MISSING'):api.set_designer({'id':'123','name':'exact-name'},'猜的姓名')
        api.json.assert_not_called()

class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        spec=importlib.util.spec_from_file_location('designer_test_ops',operations_path());self.ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.ops)
        self.ledger=self.ops.Ledger(self.root/'state')
        self.item={'filename':'261021TEST1-fixture.mp4','sha256':'a'*64,'parameters':copy.deepcopy(PARAMS),'provenance':{'source_native_fields':copy.deepcopy(FIELDS)}}
        self.plan={'job_id':'job','items':[self.item]};self.ledger.create(self.plan);self.ledger.claim('job',self.item);self.ledger.update('job',self.item['filename'],'listed','123')
        self.runtime=SimpleNamespace(mutation=lambda *a,**kw:contextlib.nullcontext())
        proxy=SimpleNamespace(Ledger=lambda:self.ledger,registered_plan=lambda jid:self.plan,load_runtime=lambda w:self.runtime,plan_digest=self.ops.plan_digest,UPLOAD_SCOPE=self.ops.UPLOAD_SCOPE,save=self.ops.save)
        self.patches=[patch.object(service,'operations',lambda:proxy),patch.object(service,'verify_source',lambda:'test')]
        for p in self.patches:p.start()
        self.api=Mock();self.api.fields.return_value={'selects':SELECTS}
        self.record={'id':'123','name':self.item['filename'][:-4]}
        self.good={'record':self.record,'fields':copy.deepcopy(FIELDS),'media':['http://example.invalid/fixture.mp4']}
        self.bad={**self.good,'fields':{**FIELDS,'设计师':'上传账号'}}
        self.args={'job_id':'job','workspace':str(self.root),'authorization_ticket':'fixture'}
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.ledger.db.close();self.tmp.cleanup()
    def test_change_existing_id_only_and_verify_every_other_field(self):
        self.api.detail_snapshot.side_effect=[self.bad,self.good]
        r=service.finalize_attribution(self.api,self.args,self.root)
        self.assertTrue(r['ok']);self.api.set_designer.assert_called_once_with(self.record,'原设计师')
        self.api.json.assert_not_called();self.assertFalse(r['upload_performed'])
        self.assertEqual(self.ledger.existing(self.item['filename'])['record_id'],'123')
    def test_already_correct_is_readonly_noop(self):
        self.api.detail_snapshot.return_value=self.good
        self.assertTrue(service.finalize_attribution(self.api,self.args,self.root)['ok'])
        self.api.set_designer.assert_not_called();self.api.json.assert_not_called()
    def test_other_tag_mismatch_stops_before_write(self):
        self.api.detail_snapshot.return_value={**self.bad,'fields':{**self.bad['fields'],'角色/标签':['错误角色']}}
        with self.assertRaisesRegex(ValueError,'OTHER_METADATA_MISMATCH'):service.finalize_attribution(self.api,self.args,self.root)
        self.api.set_designer.assert_not_called()
    def test_write_unknown_never_replayed_and_can_recover_by_readback(self):
        self.api.detail_snapshot.return_value=self.bad;self.api.set_designer.side_effect=Stop('ACCEPTANCE_UNKNOWN')
        with self.assertRaises(Stop):service.finalize_attribution(self.api,self.args,self.root)
        self.api.set_designer.reset_mock()
        with self.assertRaisesRegex(ValueError,'DESIGNER_WRITE_UNKNOWN'):service.finalize_attribution(self.api,self.args,self.root)
        self.api.set_designer.assert_not_called()
        self.api.detail_snapshot.return_value=self.good
        self.assertTrue(service.finalize_attribution(self.api,self.args,self.root)['ok'])
        self.api.set_designer.assert_not_called()
    def test_media_drift_after_write_does_not_pass(self):
        self.api.detail_snapshot.side_effect=[self.bad,{**self.good,'media':['changed']}]
        with self.assertRaisesRegex(ValueError,'DESIGNER_READBACK'):service.finalize_attribution(self.api,self.args,self.root)
    def test_ticket_failure_prevents_remote_write(self):
        self.runtime.mutation=Mock(side_effect=ValueError('AUTHORIZATION_TICKET_REQUIRED'))
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION_TICKET'):service.finalize_attribution(self.api,self.args,self.root)
        self.api.set_designer.assert_not_called();self.api.detail_snapshot.assert_not_called()

if __name__=='__main__':unittest.main()
