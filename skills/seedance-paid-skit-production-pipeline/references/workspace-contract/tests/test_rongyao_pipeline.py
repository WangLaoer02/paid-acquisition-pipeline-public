"""Exercise the public CLI submission seam using real guards and isolated receipts; no network."""
import contextlib,copy,hashlib,importlib.util,json,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import receiver_config
SOURCE=ROOT/'workflow/rules/implementation/rongyao-tools/skills/rongyao-operations/scripts/rongyao.py'
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
ry=module('pipeline_ops',SOURCE)
rt=module('pipeline_rt',ROOT/'scripts/workflow_runtime.py')

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        self.state=self.root/'isolated-ledger';self.state.mkdir()
        self.file=self.root/'synthetic.mp4';self.file.write_bytes(b'synthetic fixture; never send')
        self.item={'file':str(self.file),'filename':self.file.name,'sha256':ry.sha256(self.file),'parameters':{'demand_name':'fixture-only'}}
        self.plan={'schema_version':1,'job_id':'isolated-job','items':[self.item],'test_only':False}
        self.ledger=ry.Ledger(self.state);self.ledger.create(self.plan)
        self.plan_path=self.root/'plan.json';ry.save(self.plan_path,self.plan)
        self.policy={'release_id':'TEST','writer_hosts':['writer.local'],'authorization':{'directory':'workflow/authorizations','max_lifetime_minutes':120,'high_risk_actions':['material_upload']},'event_log':{'directory':'events'},'dependency_profiles':{'material_upload':{'executables':[],'python_imports':[]}},'circuit':{'failure_threshold':2,'window_seconds':600,'cooldown_seconds':900}}
        (self.root/'workflow').mkdir();ry.save(self.root/'workflow/runtime-policy.json',self.policy)
        ry.save(self.root/'receiver.local.json',{'schema_version':1,'writer_host':'writer.local'})
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(receiver_config,'ROOT',self.root))
        self.addCleanup(self.stack.close)
        for k,v in {'ROOT':self.root,'POLICY_PATH':self.root/'workflow/runtime-policy.json','RUNTIME':self.root/'runtime','LOCKS':self.root/'runtime/locks','CIRCUITS':self.root/'runtime/circuits.json','AUTH_LEDGER':self.root/'runtime/auth-ledger.json'}.items():self.stack.enter_context(patch.object(rt,k,v))
        self.stack.enter_context(patch.object(rt,'host',return_value='writer.local'))
        self.stack.enter_context(patch.object(rt,'ensure_release',return_value={'release_id':'TEST','live_center_verified':True}))
        self.stack.enter_context(patch.object(ry,'load_runtime',return_value=rt))
        self.transport=self.stack.enter_context(patch.object(ry,'transport',side_effect=self.select))
        self.ticket=self.make_ticket()
    def tearDown(self):self.stack.close();self.ledger.db.close();self.tmp.cleanup()
    def make_ticket(self,digest=None):return rt.create_ticket('material_upload',ry.UPLOAD_SCOPE,digest or ry.plan_digest(self.plan),'isolated-test-approval',30)[0]
    def select(self,action,item,state,checkpoint):
        self.assertEqual(action,'upload');self.assertTrue(rt.AUTH_LEDGER.exists())
        checkpoint();self.assertEqual(self.ledger.existing(item['filename'])['state'],'selection_pending')
        return {'ok':True,'status':'FILE_SELECTED_PENDING_BACKEND'}
    def submit(self,ticket=None):return ry.upload('isolated-job',self.state,workspace=str(self.root),authorization_ticket=ticket or self.ticket,exported_plan=self.plan_path)
    def test_valid_ticket_enters_guard_before_selection_and_records_pending(self):
        r=self.submit();self.transport.assert_called_once();self.assertFalse(r['receipt']['all_listed'])
        self.assertEqual(self.ledger.existing(self.file.name)['state'],'submitted_pending')
        self.assertTrue(list((self.root/'events').glob('*.jsonl')))
    def test_missing_ticket_never_loads_input_or_transport(self):
        with patch.object(ry,'registered_plan') as read:
            with self.assertRaisesRegex(ValueError,'AUTHORIZATION_TICKET_REQUIRED'):ry.upload('missing',self.state,workspace=str(self.root))
            read.assert_not_called();self.transport.assert_not_called()
    def test_nonwriter_never_reads_plan(self):
        with patch.object(rt,'host',return_value='reader.local'),patch.object(ry,'reviewed_plan') as read:
            with self.assertRaisesRegex(ValueError,'WRITER_HOST_REQUIRED'):self.submit()
            read.assert_not_called();self.transport.assert_not_called()
    def test_live_release_failure_never_selects(self):
        with patch.object(rt,'ensure_release',side_effect=rt.GuardError('LIVE_RELEASE_MISMATCH')):
            with self.assertRaisesRegex(ValueError,'LIVE_RELEASE_MISMATCH'):self.submit()
        self.transport.assert_not_called();self.assertFalse(rt.AUTH_LEDGER.exists())
    def test_wrong_input_hash_never_selects(self):
        with self.assertRaisesRegex(ValueError,'input hash differs'):self.submit(self.make_ticket('0'*64))
        self.transport.assert_not_called()
    def test_expired_ticket_never_selects(self):
        t=ry.read(self.ticket);t['expires_at']='2000-01-01T00:00:00+00:00';ry.save(self.ticket,t)
        with self.assertRaisesRegex(ValueError,'expired'):self.submit()
        self.transport.assert_not_called()
    def test_wrong_ticket_release_never_selects(self):
        t=ry.read(self.ticket);t['release_id']='OLD';ry.save(self.ticket,t)
        with self.assertRaisesRegex(ValueError,'mismatch: release_id'):self.submit()
        self.transport.assert_not_called()
    def test_same_scope_concurrent_process_cannot_select(self):
        with rt.lock(ry.UPLOAD_SCOPE,'material_upload'):
            with self.assertRaisesRegex(ValueError,'WORKFLOW_LOCKED'):self.submit()
        self.transport.assert_not_called()
    def test_ticket_cannot_be_reused(self):
        self.submit()
        with self.assertRaisesRegex(ValueError,'already reserved'):self.submit()
        self.transport.assert_called_once()
    def test_unknown_submission_not_retried_even_with_new_ticket(self):
        def fail(a,b,c,checkpoint):checkpoint();raise ConnectionError('synthetic disconnect')
        self.transport.side_effect=fail
        with self.assertRaises(ConnectionError):self.submit()
        self.assertEqual(self.ledger.existing(self.file.name)['state'],'submission_unknown')
        with self.assertRaisesRegex(ValueError,'PRIOR_SUBMISSION'):self.submit(self.make_ticket())
        self.transport.assert_called_once()
    def test_historical_listed_identical_item_is_skipped(self):
        self.ledger.claim('isolated-job',self.item);self.ledger.update('isolated-job',self.file.name,'listed','fixture-id')
        r=self.submit();self.transport.assert_not_called();self.assertEqual(r['results'][0]['status'],'SKIP_ALREADY_LISTED')
    def test_changed_media_rejected_before_ticket_reservation(self):
        self.file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'PLAN_FILE_CHANGED'):self.submit()
        self.transport.assert_not_called();self.assertFalse(rt.AUTH_LEDGER.exists())
    def test_edited_exported_plan_is_rejected(self):
        p=copy.deepcopy(self.plan);p['items'][0]['parameters']['demand_name']='changed';ry.save(self.plan_path,p)
        with self.assertRaisesRegex(ValueError,'PLAN_WAS_EDITED'):self.submit()
        self.transport.assert_not_called()
    def test_test_only_plan_refused(self):
        p={**self.plan,'job_id':'offline','test_only':True};self.ledger.create(p)
        r=ry.upload('offline',self.state,workspace=str(self.root),authorization_ticket=self.ticket)
        self.assertEqual(r['status'],'OFFLINE_TEST_PLAN_CANNOT_UPLOAD');self.transport.assert_not_called()
    def test_inspect_plan_is_read_only_and_does_not_grant_authorization(self):
        before=ry.sha256(self.state/'jobs.sqlite3');r=ry.inspect_plan(self.plan_path,str(self.root),self.state)
        self.assertEqual(r['input_sha256'],ry.plan_digest(self.plan));self.assertFalse(r['authorization_granted'])
        self.assertEqual(before,ry.sha256(self.state/'jobs.sqlite3'));self.assertFalse(rt.AUTH_LEDGER.exists());self.transport.assert_not_called()
    def test_open_circuit_stops_before_select(self):
        for _ in range(2):rt.record_failure('material_upload',ry.UPLOAD_SCOPE,'network','synthetic')
        with self.assertRaisesRegex(ValueError,'CIRCUIT_OPEN'):self.submit()
        self.transport.assert_not_called()

class PublicCLITests(unittest.TestCase):
    def test_missing_ticket_exits_before_any_business_file_or_browser(self):
        r=subprocess.run([sys.executable,str(SOURCE),'video','upload','--plan','/nonexistent.json','--workspace',str(ROOT)],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('--authorization-ticket',r.stderr)
    def test_unreleased_external_cli_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);(root/'scripts').mkdir();(root/'scripts/workflow_runtime.py').write_text('raise AssertionError("must not import")')
            (root/'workflow/rules').mkdir(parents=True);ry.save(root/'workflow/rules/manifest.json',{'implementation_files':{ry.RELEASE_SOURCE:'0'*64}})
            with self.assertRaisesRegex(ValueError,'UPLOAD_CLI_RELEASE_MISMATCH'):ry.load_runtime(str(root))

if __name__=='__main__':unittest.main()
