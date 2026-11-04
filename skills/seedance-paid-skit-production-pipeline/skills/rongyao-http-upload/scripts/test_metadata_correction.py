import contextlib,copy,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from upload_api import Api,Stop,SAVE_DEMAND,SAVE_SECOND,SAVE_TAG,validate_url
from upload_page import Page
from metadata_correction import OPERATION
from upload_service import correct_metadata
from test_designer import FIELDS,PARAMS,SELECTS

class NativeMetadataTests(unittest.TestCase):
    def api(self):
        api=object.__new__(Api)
        code='''<script>
function changeDemandName(e) {var arr='{"1":"需求人"}'; $.post('/data/?_c=creativeVideoList&_a=index&ac=saveDemandName', {id:e.id,demand_name:username}, function(res){});}
function changeSecondDesignName(e) {var arr='{"2":"第二设计师"}'; $.post('/data/?_c=creativeVideoList&_a=index&ac=saveSecondDesignName', {id:e.id,region_type:second_design_id},function(res){});}
function addTag(e) {var arr='{"tag":{"带土":"带土","卡卡西":"卡卡西"}}'; $.post('/data/?_c=creativeVideoList&_a=index&ac=saveVideoTag', {id:e.id,tag:tag_arr}, function(res){});}
</script>'''
        api.detail_page=Mock(return_value=Page(code));api.json=Mock(return_value={'status':1});return api
    def test_native_encoding_and_exact_allowlist(self):
        api=self.api();record={'id':'123','name':'fixture'}
        for label,value,url,fields in [('需求人','需求人',SAVE_DEMAND,[('id','123'),('demand_name','需求人')]),('第二设计师','第二设计师',SAVE_SECOND,[('id','123'),('region_type','2')]),('角色/标签',['带土','卡卡西'],SAVE_TAG,[('id','123'),('tag[]','带土'),('tag[]','卡卡西')])]:
            validate_url(url,True);api.set_metadata(record,label,value);api.json.assert_called_with(url,fields)
            with self.assertRaises(Stop):validate_url(url+'&id=123',True)
    def test_invalid_enum_or_other_field_never_writes(self):
        api=self.api()
        for label,value in [('设计师','需求人'),('需求人','猜的人'),('角色/标签',['带土','带土']),('角色/标签',[]),('角色/标签',['猜的角色'])]:
            with self.assertRaises(Stop):api.set_metadata({'id':'123','name':'fixture'},label,value)
        api.json.assert_not_called()
    def test_native_contract_change_never_writes(self):
        api=self.api();api.detail_page.return_value=Page('<script>function addTag(e){}</script>')
        with self.assertRaisesRegex(Stop,'CONTRACT_CHANGED'):api.set_metadata({'id':'123','name':'fixture'},'角色/标签',['带土'])
        api.json.assert_not_called()

class MetadataWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.file=self.root/'fixture.mp4';self.file.write_bytes(b'video')
        self.auth=self.root/'auth.json';self.auth.write_text('actual scoped human authorization fixture')
        self.digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
        self.record={'id':'123','name':'fixture'};self.before={**FIELDS,'需求人':'错误需求','角色/标签':''}
        self.spec={'record':self.record,'media':['http://example.invalid/fixture.mp4'],'before_fields':self.before,'authorization':{'evidence_file':str(self.auth),'sha256':self.digest(self.auth)},'changes':{'需求人':{'before':'错误需求','after':'需求人'},'角色/标签':{'before':'','after':['带土']}}}
        self.item={'filename':'fixture.mp4','file':str(self.file),'sha256':self.digest(self.file),'parameters':PARAMS,'provenance':{'source_native_fields':FIELDS,'operation':OPERATION,'metadata_correction':self.spec}}
        self.plan={'job_id':'job','items':[self.item]};self.runtime=SimpleNamespace(mutation=lambda *a,**kw:contextlib.nullcontext())
        def save(p,obj):Path(p).write_text(json.dumps(obj))
        self.ops=SimpleNamespace(registered_plan=lambda j:copy.deepcopy(self.plan),sha256=self.digest,load_runtime=lambda w:self.runtime,UPLOAD_SCOPE='fixture',plan_digest=lambda p:hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest(),save=save)
        self.patches=[patch('upload_service.operations',lambda:self.ops),patch('upload_service.verify_source',lambda:'fixture')]
        for p in self.patches:p.start()
        self.live=copy.deepcopy(self.before);self.api=Mock();self.api.fields.return_value={'selects':SELECTS};self.api.lookup.return_value=self.record
        self.api.detail_snapshot.side_effect=lambda r:{'record':r,'fields':copy.deepcopy(self.live),'media':self.spec['media']}
        self.api.set_metadata.side_effect=lambda r,k,v:self.live.update({k:v});self.args={'job_id':'job','workspace':str(self.root),'authorization_ticket':'fixture'}
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def run_action(self):return correct_metadata(self.api,self.args,self.root)
    def test_correct_same_id_no_upload_and_no_receipt_adoption(self):
        r=self.run_action();self.assertTrue(r['ok']);self.assertFalse(r['upload_performed']);self.assertEqual(self.api.set_metadata.call_count,2);self.api.json.assert_not_called()
        self.api.set_metadata.reset_mock();self.assertTrue(self.run_action()['ok']);self.api.set_metadata.assert_not_called()
    def test_unknown_write_is_not_replayed_even_with_new_ticket(self):
        self.api.set_metadata.side_effect=Stop('ACCEPTANCE_UNKNOWN')
        with self.assertRaises(Stop):self.run_action()
        self.api.set_metadata.reset_mock()
        with self.assertRaisesRegex(ValueError,'READBACK_ONLY'):self.run_action()
        self.api.set_metadata.assert_not_called()
        self.live['需求人']='需求人';self.api.set_metadata.side_effect=lambda r,k,v:self.live.update({k:v})
        self.assertTrue(self.run_action()['ok']);self.api.set_metadata.assert_called_once_with(self.record,'角色/标签',['带土'])
    def test_authorization_media_id_file_or_untouched_drift_stops(self):
        cases=['auth','media','id','file','unchanged','scope']
        for case in cases:
            with self.subTest(case=case):
                oldspec=copy.deepcopy(self.spec);oldlive=copy.deepcopy(self.live);oldfile=self.file.read_bytes();oldauth=self.auth.read_text()
                if case=='auth':self.auth.write_text('changed')
                elif case=='media':self.api.detail_snapshot.side_effect=lambda r:{'record':r,'fields':copy.deepcopy(self.live),'media':['different']}
                elif case=='id':self.api.lookup.return_value={'id':'999','name':'fixture'}
                elif case=='file':self.file.write_bytes(b'changed')
                elif case=='unchanged':self.live['设计师']='someone else'
                elif case=='scope':self.item['provenance']['operation']='upload'
                with self.assertRaises(ValueError):self.run_action()
                self.api.set_metadata.assert_not_called();self.spec.clear();self.spec.update(oldspec);self.live=oldlive;self.file.write_bytes(oldfile);self.auth.write_text(oldauth);self.item['provenance']['operation']=OPERATION;self.api.lookup.return_value=self.record;self.api.detail_snapshot.side_effect=lambda r:{'record':r,'fields':copy.deepcopy(self.live),'media':self.spec['media']}
    def test_real_runtime_accepts_only_registered_service_entrypoint(self):
        import importlib.util,shutil
        runtime_path=Path(__file__).resolve().parents[2]/'paid-skit-production-pipeline/references/workspace-contract/scripts/workflow_runtime.py'
        spec=importlib.util.spec_from_file_location('actual_metadata_guard_fixture',runtime_path);runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
        home=self.root/'home';published=self.root/'published';source=home/'.codex/skills/rongyao-http-upload/scripts/upload_service.py';source.parent.mkdir(parents=True)
        original=Path(__import__('upload_service').__file__);shutil.copyfile(original,source)
        spec=importlib.util.spec_from_file_location('registered_metadata_fixture_service',source);entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
        manifest=published/'workflow/rules/manifest.json';manifest.parent.mkdir(parents=True);manifest.write_text(json.dumps({'workspace_contract_files':{'workflow/tools/rongyao-http-upload/scripts/upload_service.py':self.digest(source)}}));runtime.ROOT=published
        runtime.ensure_writer=lambda a:None;runtime.check_circuit=lambda *a:None;runtime.dependencies=lambda a:None;runtime.ensure_release=lambda live:{'release_id':'fixture'};runtime.lock=lambda *a:contextlib.nullcontext();runtime.authorization=lambda *a:None;runtime.event=Mock()
        entry.operations=lambda:self.ops;entry.verify_source=lambda:'fixture';self.ops.load_runtime=lambda w:runtime
        with patch.object(Path,'home',return_value=home):
            with self.assertRaisesRegex(runtime.GuardError,'UNREGISTERED_UPLOAD_ENTRYPOINT'):
                with runtime.mutation('material_upload','material-upload:rongyao-operations',authorization_ticket='fixture',input_sha256='a'*64):pass
            self.ops.UPLOAD_SCOPE='material-upload:rongyao-operations'
            self.assertTrue(entry.correct_metadata(self.api,self.args,self.root)['ok'])
        self.assertEqual(self.api.set_metadata.call_count,2)
    def test_metadata_plan_cannot_submit_video(self):
        import upload_service
        self.ops.reviewed_plan=lambda p:self.plan;self.ops.Ledger=lambda:None
        with self.assertRaisesRegex(ValueError,'METADATA_ONLY_PLAN_NOT_SUBMITTABLE'):upload_service.submit(self.api,{'workspace':str(self.root),'plan':'fixture'},self.root)
        self.api.set_metadata.assert_not_called();self.api.json.assert_not_called()
    def test_ticket_failure_prevents_write(self):
        self.runtime.mutation=Mock(side_effect=ValueError('AUTHORIZATION_TICKET_REQUIRED'))
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION_TICKET'):self.run_action()
        self.api.set_metadata.assert_not_called()
    def test_unapproved_additional_change_after_write_is_detected(self):
        def bad(r,k,v):self.live.update({k:v,'设计师':'wrong'})
        self.api.set_metadata.side_effect=bad
        with self.assertRaisesRegex(ValueError,'UNCHANGED_FIELD_DRIFT'):self.run_action()
        self.assertEqual(self.api.set_metadata.call_count,1)

if __name__=='__main__':unittest.main()
