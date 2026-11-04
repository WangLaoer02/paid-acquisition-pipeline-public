import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import native_upload_guard as g
import native_upload_controller as ctl
import workflow_runtime as rt
TITLE='adopenplatform.backend.example.invalid/upload — Google Chrome'
NAME='261012D4-成片-原创-37.mp4'
def rows(chooser=False,selected=False,progress=None):
    r=[{'path':'0','role':'AXWindow','title':TITLE},
       {'path':'0.1','role':'AXButton','dom_id':'file','title':'选择文件：'+(NAME if selected else '未选择文件')}]
    if chooser:r.append({'path':'0.2','role':'AXSheet','title':'打开'})
    if progress:r.append({'path':'0.3','role':'AXStaticText','value':progress})
    return r
class EvidenceTests(unittest.TestCase):
    def test_cancel_is_not_submission(self):
        self.assertEqual(g.submission_state(g.observation(rows(),NAME,TITLE),'selection_pending'),'blocked_before_selection')
    def test_open_is_not_submission(self):
        self.assertEqual(g.submission_state(g.observation(rows(True),NAME,TITLE),'selection_pending'),'selection_pending')
    def test_closed_with_exact_selected_file_pending_only(self):
        self.assertEqual(g.submission_state(g.observation(rows(selected=True),NAME,TITLE),'selection_pending'),'submitted_pending')
    def test_open_with_selected_name_is_still_chooser(self):
        self.assertEqual(g.submission_state(g.observation(rows(True,True),NAME,TITLE),'selection_pending'),'selection_pending')
    def test_own_progress_pending_not_listed(self):
        self.assertEqual(g.submission_state(g.observation(rows(progress=NAME+' 上传进度：100%'),NAME,TITLE),'submission_unknown'),'submitted_pending')
    def test_similar_filename_progress_is_rejected(self):
        self.assertFalse(g.observation(rows(progress=NAME[:-4]+'extra.mp4 上传进度：100%'),NAME,TITLE)['file_progress'])
    def test_similar_input_filename_is_rejected(self):
        r=rows(selected=True);r[1]['title']='选择文件：extra'+NAME
        self.assertFalse(g.observation(r,NAME,TITLE)['file_selected'])
    def test_unknown_not_optimistically_resumed(self):
        self.assertEqual(g.submission_state(g.observation(rows(True),NAME,TITLE),'submission_unknown'),'submission_unknown')
    def test_listed_not_downgraded(self):
        self.assertEqual(g.submission_state(g.observation(rows(),NAME,TITLE),'listed'),'listed')
    def test_ambiguous_window_rejected(self):
        with self.assertRaisesRegex(g.NativeGuardError,'WINDOW_NOT_UNIQUE'):g.observation(rows()+[{'path':'9','role':'AXWindow','title':TITLE}],NAME,TITLE)
    def test_wrong_window_rejected(self):
        with self.assertRaisesRegex(g.NativeGuardError,'WINDOW_NOT_UNIQUE'):g.observation(rows(),NAME,'other')
    def test_other_window_progress_not_used(self):
        r=rows()+[{'path':'9.1','role':'AXStaticText','value':NAME+' 上传进度：100%'}]
        self.assertFalse(g.observation(r,NAME,TITLE)['file_progress'])
    def test_path_combo_box_is_observed(self):
        r=rows(True)+[{'path':'0.2.1','role':'AXComboBox','value':'/fixture/'+NAME}]
        self.assertEqual(g.observation(r,NAME,TITLE)['resolved_paths'],['/fixture/'+NAME])
    def test_duplicate_input_rejected(self):
        with self.assertRaisesRegex(g.NativeGuardError,'INPUT_NOT_UNIQUE'):g.observation(rows()+[dict(rows()[1],path='0.8')],NAME,TITLE)
    def test_coordinates_and_unrelated_text_do_not_reset_goal(self):
        a=rows();b=rows();b[1]['position']=[30,40];b.append({'path':'0.8','role':'AXStaticText','value':'clock changed'})
        self.assertEqual(g.observation(a,NAME,TITLE)['fingerprint'],g.observation(b,NAME,TITLE)['fingerprint'])
class JournalTests(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.p=Path(self.t.name)/'actions.db';self.j=g.ActionJournal(self.p);self.k=self.j.key('file-sha',TITLE,NAME,'submit')
    def tearDown(self):self.j.close();self.t.cleanup()
    def fail(self):self.j.begin(self.k,'before');return self.j.finish(self.k,'before','before',True)
    def test_new_plan_or_window_title_cannot_reset_same_artifact_goal(self):
        self.assertEqual(self.k,self.j.key('file-sha','renamed window',NAME,'submit'))
    def test_exit_zero_without_observed_change_is_failure(self):self.assertFalse(self.fail())
    def test_two_failures_persist_across_processes(self):
        self.fail();self.j.close();self.j=g.ActionJournal(self.p);self.fail();self.j.close();self.j=g.ActionJournal(self.p)
        with self.assertRaisesRegex(g.NativeGuardError,'TWO_FAILURES'):self.j.begin(self.k,'fresh')
    def test_inflight_unknown_cannot_be_reissued(self):
        self.j.begin(self.k,'before');self.j.close();self.j=g.ActionJournal(self.p)
        with self.assertRaisesRegex(g.NativeGuardError,'INFLIGHT_UNKNOWN'):self.j.begin(self.k,'other')
    def test_concurrent_controller_cannot_claim(self):
        self.j.begin(self.k,'before');other=g.ActionJournal(self.p)
        try:
            with self.assertRaisesRegex(g.NativeGuardError,'INFLIGHT_UNKNOWN'):other.begin(self.k,'before')
        finally:other.close()
    def test_success_with_new_observation_resets(self):
        self.fail();self.j.begin(self.k,'before');self.assertTrue(self.j.finish(self.k,'before','new',True));self.fail();self.j.begin(self.k,'before')
    def test_new_state_without_goal_does_not_reset(self):
        for i in range(2):self.j.begin(self.k,str(i));self.j.finish(self.k,str(i),str(i+1),False)
        with self.assertRaises(g.NativeGuardError):self.j.begin(self.k,'3')
    def test_checkpoint_requires_explicit_user_ref_and_actual_change(self):
        self.fail();self.fail()
        for fp,ref in [('before','user'),('new','')]:
            with self.assertRaises(g.NativeGuardError):self.j.user_checkpoint(self.k,fp,ref)
        self.j.user_checkpoint(self.k,'new','direct-user-message');self.j.begin(self.k,'new')
    def test_capability_block_survives_restart_and_only_recheck_clears(self):
        self.j.block_capability(TITLE,'accessibility','permission');self.j.close();self.j=g.ActionJournal(self.p)
        with self.assertRaises(g.NativeGuardError):self.j.capability(TITLE,'accessibility')
        with self.assertRaises(g.NativeGuardError):self.j.clear_capability(TITLE,'accessibility',False,'user')
        self.j.clear_capability(TITLE,'accessibility',True,'user');self.j.capability(TITLE,'accessibility')
class DescriptorTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
        for n in g.EXECUTION_FILES:
            p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('source '+n)
        self.binary=self.root/'workflow/tools/native-upload/native-ui';self.binary.write_text('fixture binary never executed')
        self.manifest=self.root/'workflow/rules/manifest.json';self.manifest.parent.mkdir(parents=True,exist_ok=True)
        self.manifest.write_text(json.dumps({'release_id':'FIXTURE','workspace_contract_files':{n:g.sha(self.root/n) for n in g.EXECUTION_FILES}}))
        self.build=self.binary.with_name('build.json');self.build.write_text(json.dumps({'source_sha256':g.sha(self.root/g.EXECUTION_FILES[-1]),'binary_sha256':g.sha(self.binary)}))
        self.desc=g.execution_descriptor(self.root,self.binary,TITLE)
    def tearDown(self):self.t.cleanup()
    def test_unchanged_executor_verified(self):self.assertEqual(g.verify_execution(self.root,self.desc),self.desc)
    def test_controller_edit_rejected_before_ui(self):
        (self.root/g.EXECUTION_FILES[0]).write_text('changed')
        with self.assertRaisesRegex(g.NativeGuardError,'SOURCE_NOT_PUBLISHED'):g.verify_execution(self.root,self.desc)
    def test_swift_edit_rejected(self):
        (self.root/g.EXECUTION_FILES[-1]).write_text('changed')
        with self.assertRaises(g.NativeGuardError):g.verify_execution(self.root,self.desc)
    def test_binary_rebuild_rejected(self):
        self.binary.write_text('changed')
        with self.assertRaisesRegex(g.NativeGuardError,'BUILD_RECEIPT'):g.verify_execution(self.root,self.desc)
    def test_build_receipt_edit_rejected(self):
        self.build.write_text('{}')
        with self.assertRaises(g.NativeGuardError):g.verify_execution(self.root,self.desc)
    def test_release_change_requires_new_plan(self):
        m=json.loads(self.manifest.read_text());m['release_id']='OTHER';self.manifest.write_text(json.dumps(m))
        with self.assertRaisesRegex(g.NativeGuardError,'EXECUTION_CHANGED'):g.verify_execution(self.root,self.desc)
    def test_project_binary_not_accepted(self):
        with self.assertRaisesRegex(g.NativeGuardError,'PUBLISHED_NATIVE_BINARY'):g.execution_descriptor(self.root,self.root/'project-helper',TITLE)
    def test_window_required(self):
        with self.assertRaises(g.NativeGuardError):g.execution_descriptor(self.root,self.binary,'')
class RuntimeEntryTests(unittest.TestCase):
    def test_unregistered_project_adapter_is_rejected_before_writer_or_ui(self):
        with patch.object(rt,'ensure_writer') as writer:
            with self.assertRaisesRegex(rt.GuardError,'UNREGISTERED_UPLOAD_ENTRYPOINT'):
                with rt.mutation('material_upload','material-upload:rongyao-operations'):pass
            writer.assert_not_called()
    def test_registered_call_preserves_all_existing_gates(self):
        source=rt.ROOT/'scripts/native_upload_controller.py'
        scope={};exec(compile("def enter(rt):\n    with rt.mutation('material_upload','material-upload:rongyao-operations',authorization_ticket='fixture',input_sha256='sha'):\n        return True\n",str(source),'exec'),scope)
        with patch.object(rt,'ensure_writer') as a,patch.object(rt,'check_circuit') as b,patch.object(rt,'dependencies') as c,patch.object(rt,'ensure_release',return_value={'release_id':'FIXTURE'}) as d,patch.object(rt,'lock',return_value=contextlib.nullcontext()) as e,patch.object(rt,'authorization',return_value={'ticket_id':'fake-no-production'}) as f,patch.object(rt,'event'):
            self.assertTrue(scope['enter'](rt));a.assert_called_once();b.assert_called_once();c.assert_called_once();d.assert_called_once_with(True);e.assert_called_once();f.assert_called_once_with('fixture','material_upload','material-upload:rongyao-operations','sha',True)
class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.state=Path(self.t.name);self.rg=ctl.load_cli();self.realLedger=self.rg.Ledger
        self.item={'file':str(self.state/NAME),'filename':NAME,'sha256':'sha-fixture','parameters':{}}
        self.plan={'job_id':'isolated-fixture','items':[self.item],'native_execution':{'window_title':TITLE}}
        with contextlib.closing(self.realLedger(self.state).db) as db:db.execute('INSERT INTO jobs VALUES(?,?,?)',(self.plan['job_id'],json.dumps(self.plan),'now'));db.commit()
    def tearDown(self):self.t.cleanup()
    def run_controller(self,reads,commands,action_error=None):
        it=iter(reads);self.actions=[]
        def native(args,**kw):
            if len(args)==1:
                value=next(it);value=value() if callable(value) else value
                return subprocess.CompletedProcess(args,0,json.dumps(value),'')
            self.actions.append(args[1:])
            if action_error:raise action_error
            return subprocess.CompletedProcess(args,0,'','')
        fake_runtime=type('Runtime',(),{'mutation':staticmethod(lambda *a,**k:contextlib.nullcontext())})()
        with patch.object(ctl,'load_cli',return_value=self.rg),patch.object(self.rg,'reviewed_plan',return_value=self.plan),patch.object(self.rg,'load_runtime',return_value=fake_runtime),patch.object(self.rg,'Ledger',side_effect=lambda:self.realLedger(self.state)),patch.object(self.rg,'STATE',self.state),patch.object(ctl,'verify_execution',return_value={'window_title':TITLE}),patch.object(ctl.subprocess,'run',side_effect=native),patch.object(ctl.time,'sleep'),patch.object(sys,'stdin',io.StringIO(commands)),patch.object(sys,'stdout',io.StringIO()):ctl.run('fixture-plan','fixture-no-production-ticket')
    def read_file(self):
        ledger=self.realLedger(self.state)
        try:return ledger.existing(NAME)
        finally:ledger.db.close()
    def test_goal_requires_actual_submission_and_rejects_unknown_goal(self):
        o=g.observation(rows(),NAME,TITLE)
        self.assertFalse(ctl.goal_reached('submit_current_file',self.item,o))
        with self.assertRaises(g.NativeGuardError):ctl.goal_reached('invented_reset',self.item,o)
    def test_wrong_form_field_rejected_before_claim_or_ui_action(self):
        self.item['parameters']={'demand_name':'wanted'}
        r=rows()+[{'path':'0.4','role':'AXTextField','dom_id':'demand_name','value':'wrong'}]
        with self.assertRaisesRegex(g.NativeGuardError,'FORM_FIELD_MISMATCH'):self.run_controller([r],'{\"op\":\"open\",\"index\":0}\n')
        self.assertIsNone(self.read_file())
    def test_cancel_after_open_remains_not_submitted(self):
        self.run_controller([rows(),rows(True),rows(True),rows()],'{"op":"open","index":0}\n{"op":"observe","index":0}\n{"op":"finish"}\n')
        self.assertEqual(self.read_file()['state'],'blocked_before_selection')
    def test_timeout_records_actual_type_and_preserves_prior_evidence(self):
        with self.assertRaises(subprocess.TimeoutExpired):self.run_controller([rows()],'{"op":"open","index":0}\n',subprocess.TimeoutExpired('fake-helper',20))
        f=self.read_file();e=json.loads(f['evidence']);self.assertEqual(f['state'],'submission_unknown');self.assertEqual(e['error_type'],'TimeoutExpired');self.assertEqual(e['timeout_seconds'],20);self.assertIn('before',e['prior_evidence']);self.assertNotIn('prior_failure',e)
    def test_unknown_resume_does_not_select_or_fabricate_failure(self):
        ledger=self.realLedger(self.state);ledger.claim(self.plan['job_id'],self.item);ledger.update(self.plan['job_id'],NAME,'submission_unknown',evidence={'error_type':'BrokenPipeError'});ledger.db.close()
        with self.assertRaisesRegex(g.NativeGuardError,'UNKNOWN_OR_SUBMITTED'):self.run_controller([rows(True)],'{"op":"resume","index":0}\n')
        self.assertEqual(json.loads(self.read_file()['evidence']),{'error_type':'BrokenPipeError'})
    def test_native_plan_cannot_be_sent_to_cdp_transport(self):
        with patch.object(self.rg,'load_runtime',return_value=type('Runtime',(),{'ensure_writer':lambda *a:None})()),patch.object(self.rg,'transport') as tx:
            with self.assertRaisesRegex(ValueError,'NATIVE_PLAN_REQUIRES'):self.rg.upload(self.plan['job_id'],self.state,workspace='fixture',authorization_ticket='fixture')
            tx.assert_not_called()
    def test_native_plan_requires_explicit_visible_parameter_encoding(self):
        manifest=self.state/'request.json';manifest.write_text(json.dumps({'items':[self.item]}))
        with self.assertRaisesRegex(ValueError,'NATIVE_VISIBLE_PARAMETER_ENCODING_REQUIRED'):self.rg.plan(manifest,self.state/'new.json',state=self.state,native_execution={})
    def test_offline_plan_cannot_enter_mutation_or_ui(self):
        self.plan['test_only']=True
        with self.assertRaisesRegex(g.NativeGuardError,'OFFLINE_TEST_PLAN'):self.run_controller([], '')
class FinalSubmitTests(unittest.TestCase):
    setUp=ControllerTests.setUp
    tearDown=ControllerTests.tearDown
    run_controller=ControllerTests.run_controller
    read_file=ControllerTests.read_file
    # Real temporary media bytes plus a persistent isolated ledger; UI and runtime are mocked.
    def prepare_submit(self):
        Path(self.item['file']).write_bytes(b'reviewed fixture video')
        self.item['sha256']=self.rg.sha256(Path(self.item['file']))
        self.item['parameters']={'demand_name':'reviewed demand'}
    def form(self,chooser=False,selected=False):
        return rows(chooser,selected)+[{'path':'0.4','role':'AXTextField','dom_id':'demand_name','value':'reviewed demand'}]
    def chosen(self):
        return self.form(True)+[
            {'path':'0.2.1','role':'AXTextField','value':self.item['file']},
            {'path':'0.2.2','role':'AXStaticText','value':NAME},
            {'path':'0.2.3','role':'AXButton','title':'Open'}]
    def submit_case(self,final):
        self.prepare_submit()
        reads=[self.form(),self.form(True),self.form(True),final,self.form(selected=True),self.form(selected=True)]
        self.run_controller(reads,'{"op":"open","index":0}\n{"op":"press","path":"0.2.3"}\n{"op":"finish"}\n')
    def rejected(self,code,final):
        with self.assertRaisesRegex(g.NativeGuardError,code):self.submit_case(final)
        self.assertEqual(self.actions,[['press','0.1']])
        record=self.read_file();self.assertEqual(record['state'],'selection_pending')
        self.assertEqual(json.loads(record['evidence'])['phase'],'native_pre_submit_rejected')
    def test_changed_media_after_open_blocks_submit(self):
        def changed():
            Path(self.item['file']).write_bytes(b'changed after opening chooser');return self.chosen()
        self.rejected('NATIVE_PLAN_FILE_CHANGED',changed)
    def test_deleted_media_after_open_blocks_submit(self):
        def removed():Path(self.item['file']).unlink();return self.chosen()
        self.rejected('NATIVE_PLAN_FILE_CHANGED',removed)
    def test_changed_field_after_open_blocks_submit(self):
        def changed():
            r=self.chosen();next(x for x in r if x.get('dom_id')=='demand_name')['value']='unreviewed demand';return r
        self.rejected('FORM_FIELD_MISMATCH',changed)
    def test_same_filename_in_other_directory_blocks_submit(self):
        def changed():
            r=self.chosen();next(x for x in r if x['path']=='0.2.1')['value']='/different/'+NAME;return r
        self.rejected('EXACT_CHOOSER_FILE_NOT_VERIFIED',changed)
    def test_filename_preview_without_absolute_path_blocks_submit(self):
        self.rejected('EXACT_CHOOSER_FILE_NOT_VERIFIED',lambda:[x for x in self.chosen() if x['path']!='0.2.1'])
    def test_path_without_selected_file_preview_blocks_submit(self):
        self.rejected('EXACT_CHOOSER_FILE_NOT_VERIFIED',lambda:[x for x in self.chosen() if x['path']!='0.2.2'])
    def test_ambiguous_paths_block_submit(self):
        self.rejected('EXACT_CHOOSER_FILE_NOT_VERIFIED',lambda:self.chosen()+[{'path':'0.2.9','role':'AXComboBox','value':'/other/'+NAME}])
    def test_already_selected_file_never_submits_again(self):
        def selected():
            r=self.chosen();r[1]['title']='选择文件：'+NAME;return r
        self.rejected('EXISTING_SELECTION_RECONCILE_ONLY',selected)
    def test_unchanged_file_and_fields_submit_once_pending_only(self):
        self.submit_case(self.chosen)
        self.assertEqual(self.actions,[['press','0.1'],['press','0.2.3']])
        self.assertEqual(self.read_file()['state'],'submitted_pending')

if __name__=='__main__':unittest.main(verbosity=2)

