"""Real controller + real plugin transport with isolated Adobe host and files."""
from pathlib import Path
import contextlib,hashlib,json,socket,subprocess,sys,tempfile,time,urllib.request,urllib.error,unittest,importlib.util,plistlib
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];BRIDGE=ROOT/'workflow/tools/premiere-bridge'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
class BridgeHarness(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.media_dir=tempfile.TemporaryDirectory();cls.media=Path(cls.media_dir.name)/'one.mp4'
  subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:s=32x32:r=24:d=1','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','1','-c:v','libx264','-c:a','aac',str(cls.media)],check=True)
 @classmethod
 def tearDownClass(cls):cls.media_dir.cleanup()
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='pr-bridge-test-');self.root=Path(self.tmp.name).resolve();self.original=self.root/'original.prproj';self.original.write_text('original-user-bytes');self.copy=self.root/'candidate.prproj';self.copy.write_text('candidate-user-bytes');self.mailbox=self.root/'mailbox';self.receipts=self.root/'receipts';self.mailbox.mkdir();self.receipts.mkdir();(self.receipts/'bridge-ready.json').write_text(json.dumps({'version':'0.2.0'}));self.proc=None
  self.preset=self.root/'preset.epr';self.preset.write_text('<Preset><ExportParamContainer/><DoAudio>true</DoAudio><DoVideo>true</DoVideo><CaptionParamContainer/><DoCaptions>true</DoCaptions><ExporterParam><ParamIdentifier>ADBECaptionExportOption</ParamIdentifier><ParamValue>2</ParamValue></ExporterParam></Preset>');self.start()
 def tearDown(self):
  self.stop();self.assertEqual(self.original.read_text(),'original-user-bytes');self.tmp.cleanup()
 def start(self,refresh_health=True):
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
  code="import sys;from types import SimpleNamespace;sys.path.insert(0,sys.argv[1]);import bridge;bridge.PORT=int(sys.argv[2]);bridge.serve(SimpleNamespace(scope=sys.argv[3],original=sys.argv[4],mailbox=sys.argv[5],receipt_dir=sys.argv[6]))"
  self.proc=subprocess.Popen([sys.executable,'-B','-c',code,str(BRIDGE),str(self.port),str(self.root),str(self.original),str(self.mailbox/'bridge-job.json'),str(self.receipts)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  self.assertIn('ready',self.proc.stdout.readline())
  # Exercise the actual plugin heartbeat against this controller's boot nonce.
  if refresh_health:self.heartbeat()
 def heartbeat(self,mode='heartbeat'):
  data={'plugin':str(BRIDGE/'plugin/main.js'),'mode':mode,'project_path':str(self.copy),'copy_path':str(self.copy),'receipts':str(self.receipts),'mailbox':str(self.mailbox)}
  src=self.root/'heartbeat-input.json';src.write_text(json.dumps(data));p=subprocess.run(['node',str(ROOT/'tests/fixtures/premiere_host.cjs'),str(src)],capture_output=True,text=True,timeout=5);self.assertEqual(p.returncode,0,p.stderr)
  self.assertEqual(json.loads(p.stdout)['effects'],[])
 def stop(self):
  if self.proc:
   self.proc.terminate();out,error=self.proc.communicate(timeout=5);self.proc=None
   if error:print(error,file=sys.stderr)
 def call(self,path,data=None):
  req=urllib.request.Request(f'http://127.0.0.1:{self.port}'+path,data=None if data is None else json.dumps(data).encode(),headers={'X-Premiere-Bridge':'0.1.0','Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=15) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def wait(self,predicate):
  end=time.time()+4
  while time.time()<end:
   if predicate():return
   time.sleep(.05)
  self.fail('timed out: '+json.dumps(self.call('/status')[1]))
 def status(self,jid):return self.call('/job/'+jid)[1]
 def run_plugin(self,job,mode='normal',project=None):
  self.wait(lambda:(self.mailbox/'bridge-job.json').exists() and json.loads((self.mailbox/'bridge-job.json').read_text()).get('id')==job['id'])
  data={'plugin':str(BRIDGE/'plugin/main.js'),'mode':mode,'project_path':str(project or self.copy),'copy_path':str(self.copy),'receipts':str(self.receipts),'mailbox':str(self.mailbox),'media':str(self.media)}
  src=self.root/'host-input.json';src.write_text(json.dumps(data));p=subprocess.run(['node',str(ROOT/'tests/fixtures/premiere_host.cjs'),str(src)],capture_output=True,text=True,timeout=15);self.assertEqual(p.returncode,0,p.stderr)
  self.wait(lambda:self.status(job['id'])['status'] in {'failed','unknown','native_call_returned','verification_required'})
  return json.loads(p.stdout)
 def open(self):
  job={'id':'open-one','action':'open-copy','copy_path':str(self.copy)};self.assertEqual(self.call('/submit',job)[0],200);self.run_plugin(job)
 def request(self,jid='export-one'):
  return {'id':jid,'action':'export-a','copy_path':str(self.copy),'expected_copy_sha256':sha(self.copy),'sequence_guid':'sequence-1','in_seconds':0,'out_seconds':1,'output_path':str(self.root/'output.mp4'),'preset_path':str(self.preset),'preset_sha256':sha(self.preset)}
 def submit_export(self):
  self.open();job=self.request();status,result=self.call('/submit',job);self.assertEqual(status,200,result);return job
 def blocked(self):
  code,_=self.call('/submit',self.request('new-id'));self.assertNotEqual(code,200)
class BridgeSafety(BridgeHarness):
 def test_normal_copy_export_and_decode(self):
  job=self.submit_export();result=self.run_plugin(job);self.assertEqual(result['effects'],['saveAs','export']);self.assertEqual(self.copy.read_text(),'candidate-user-bytes');self.assertEqual(self.status(job['id'])['status'],'verification_required');self.blocked();code,result=self.call('/verify/'+job['id'],{});self.assertEqual(code,200,result);self.assertEqual(result['status'],'completed');self.assertFalse(result['content_acceptance'])
 def test_old_plugin_refused(self):
  (self.receipts/'bridge-ready.json').write_text(json.dumps({'version':'0.1.0'}));code,result=self.call('/submit',{'id':'inspect-old','action':'inspect'});self.assertEqual(code,400);self.assertEqual(result['error'],'MATCHING_PLUGIN_NOT_READY')
 def test_existing_snapshot_refused(self):
  job={'id':'snapshot','action':'snapshot-copy','copy_path':str(self.copy),'expected_original_sha256':sha(self.original)};code,result=self.call('/submit',job);self.assertEqual(code,400);self.assertEqual(result['error'],'COPY_TARGET_EXISTS');self.assertEqual(self.copy.read_text(),'candidate-user-bytes')
 def test_snapshot_preserves_unsaved_memory(self):
  target=self.root/'new-copy.prproj';job={'id':'snapshot','action':'snapshot-copy','copy_path':str(target),'expected_original_sha256':sha(self.original)};self.assertEqual(self.call('/submit',job)[0],200);result=self.run_plugin(job,project=self.original);self.assertEqual(target.read_text(),'current-unsaved-memory');self.assertEqual(result['effects'],['saveAs'])
 def test_snapshot_target_created_after_queue(self):
  target=self.root/'new-copy.prproj';job={'id':'snapshot','action':'snapshot-copy','copy_path':str(target),'expected_original_sha256':sha(self.original)};self.assertEqual(self.call('/submit',job)[0],200);target.write_text('later-user-edit');self.assertEqual(self.run_plugin(job,project=self.original)['effects'],[]);self.assertEqual(target.read_text(),'later-user-edit')
 def test_missing_and_empty_guid(self):
  self.open()
  for value in [None,'','   ']:
   job=self.request()
   if value is None:del job['sequence_guid']
   else:job['sequence_guid']=value
   code,data=self.call('/submit',job);self.assertEqual(code,400);self.assertEqual(data['error'],'SEQUENCE_GUID_REQUIRED')
 def test_wrong_guid_no_save(self):
  job=self.submit_export();self.assertEqual(self.run_plugin(job,'wrong-guid')['effects'],[]);self.assertEqual(self.status(job['id'])['status'],'failed')
 def test_disk_change_after_open_requires_reopen(self):
  self.open();self.copy.write_text('user-new-disk');code,data=self.call('/submit',self.request());self.assertEqual(code,400);self.assertEqual(data['error'],'FRESH_COPY_OPEN_OR_SNAPSHOT_REQUIRED')
 def test_disk_change_after_queue_no_save(self):
  job=self.submit_export();self.copy.write_text('user-new-disk');self.assertEqual(self.run_plugin(job)['effects'],[]);self.assertEqual(self.copy.read_text(),'user-new-disk')
 def test_preset_change_after_queue_no_save(self):
  job=self.submit_export();self.preset.write_text('changed');self.assertEqual(self.run_plugin(job)['effects'],[])
 def test_output_created_after_queue_no_save(self):
  job=self.submit_export();Path(job['output_path']).write_text('old-output');self.assertEqual(self.run_plugin(job)['effects'],[]);self.assertEqual(Path(job['output_path']).read_text(),'old-output')
 def test_change_during_save_no_export(self):
  job=self.submit_export();self.assertEqual(self.run_plugin(job,'change-during-save')['effects'],['saveAs']);self.assertEqual(self.copy.read_text(),'external-user-edit');self.assertEqual(self.status(job['id'])['status'],'unknown');self.blocked()
 def test_save_failure_holds(self):
  job=self.submit_export();self.assertEqual(self.run_plugin(job,'save-failure')['effects'],['saveAs']);self.assertEqual(self.status(job['id'])['status'],'unknown');self.blocked()
 def test_unknown_holds_across_restart_and_late_failure(self):
  job=self.submit_export();self.assertEqual(self.run_plugin(job,'unknown')['effects'],['saveAs','export']);self.assertEqual(self.status(job['id'])['status'],'unknown');self.blocked();self.assertEqual(self.call('/verify/'+job['id'],{})[0],400);self.stop();self.start();self.blocked();self.call('/result/'+job['id'],{'status':'failed'});self.assertEqual(self.status(job['id'])['status'],'unknown');self.assertNotEqual(self.call('/submit',job)[0],200)
 def test_receipt_failure_unknown(self):
  job=self.submit_export();self.run_plugin(job,'receipt-failure');self.assertEqual(self.status(job['id'])['status'],'unknown');self.blocked()
 def test_false_native_return_not_verified(self):
  job=self.submit_export();self.run_plugin(job,'false-return');self.assertEqual(self.call('/verify/'+job['id'],{})[0],400);self.blocked()
 def test_terminal_evidence_must_match(self):
  job=self.submit_export();self.run_plugin(job,'unknown');self.assertEqual(self.call('/verify/'+job['id'],{'evidence':{'job_id':'wrong'}})[0],400);self.blocked()
 def test_safe_failure_remains_terminal_after_restart(self):
  job=self.submit_export();self.run_plugin(job,'wrong-guid');self.assertEqual(self.status(job['id'])['status'],'failed');self.stop();self.start();self.assertEqual(self.status(job['id'])['status'],'failed')
 def test_legacy_failure_is_not_automatically_safe(self):
  self.stop();records=self.root/'bridge-jobs';records.mkdir(exist_ok=True)
  legacy={'id':'old-export','status':'failed','request':{'action':'export-a'},'events':[]};(records/'old-export.json').write_text(json.dumps(legacy));self.start();self.assertEqual(self.status('old-export')['status'],'unknown');self.assertNotEqual(self.call('/submit',{'id':'next','action':'inspect'})[0],200)
 def test_native_terminal_reconciliation_no_resubmit(self):
  job=self.submit_export();self.run_plugin(job,'unknown');e=self.root/'native-observation.txt';e.write_text('fake host terminal failure; no active native task')
  evidence={'job_id':job['id'],'native_terminal_confirmed':True,'observer':'test-harness','observation':'isolated host terminated with no output','evidence_path':str(e),'evidence_sha256':sha(e),'outcome':'failed'}
  code,result=self.call('/verify/'+job['id'],{'evidence':evidence});self.assertEqual(code,200,result);self.assertEqual(result['status'],'failed');self.assertNotEqual(self.call('/submit',job)[0],200)

class BridgeHealth(BridgeHarness):
 def expired(self):
  p=self.receipts/'bridge-ready.json';ready=json.loads(p.read_text());ready['heartbeat_at_ms']=0;p.write_text(json.dumps(ready))
 def pending(self,jid='original-inspect'):
  job={'id':jid,'action':'inspect'};code,result=self.call('/submit',job);self.assertEqual(code,200,result)
  self.wait(lambda:self.status(jid)['status']=='dispatched' and (self.mailbox/'bridge-job.json').is_file())
  (self.receipts/'claimed-jobs.json').write_text('[]');self.expired();return job
 def recover(self,job):return self.call('/recover-inspect/'+job['id'],{})
 def test_old_ready_without_heartbeat_cannot_submit(self):
  (self.receipts/'bridge-ready.json').write_text('{"version":"0.2.1"}')
  self.assertFalse(self.call('/health')[1]['ready']);self.assertEqual(self.call('/submit',{'id':'stale','action':'inspect'})[0],400);self.assertEqual(self.call('/status')[1]['jobs'],{})
 def test_expired_wrong_controller_wrong_path_disabled_invalid_ready_fail_closed(self):
  p=self.receipts/'bridge-ready.json';base=json.loads(p.read_text())
  for change in ({'heartbeat_at_ms':0},{'heartbeat_at_ms':time.time()*1000+60000},{'controller_id':'old-boot'},{'mailbox_path':'/other/bridge-job.json'},{'enabled':False},{'session_id':''},{'heartbeat_at_ms':'bad'}):
   p.write_text(json.dumps({**base,**change}));self.assertFalse(self.call('/health')[1]['ready'],change);self.assertEqual(self.call('/submit',{'id':'blocked','action':'inspect'})[0],400)
  for raw in ('not-json','[]','null'):
   p.write_text(raw);self.assertFalse(self.call('/health')[1]['ready'])
 def test_queued_task_is_not_dispatched_using_previous_controller_ready(self):
  self.stop();records=self.root/'bridge-jobs';records.mkdir(exist_ok=True)
  job={'id':'queued-old','status':'queued','request':{'id':'queued-old','action':'inspect','protocol':2,'bridge_version':'0.2.1'},'events':[]};(records/'queued-old.json').write_text(json.dumps(job))
  self.start(False);time.sleep(.65);self.assertEqual(self.status('queued-old')['status'],'queued');self.assertFalse((self.mailbox/'bridge-job.json').exists());self.assertEqual(self.call('/next')[0],409)
  self.heartbeat();self.wait(lambda:self.status('queued-old')['status']=='dispatched')
 def test_real_plugin_heartbeat_is_current_and_cannot_survive_controller_restart(self):
  ready=json.loads((self.receipts/'bridge-ready.json').read_text());self.assertTrue(self.call('/health')[1]['ready'])
  self.stop();self.start();(self.receipts/'bridge-ready.json').write_text(json.dumps(ready))
  self.assertFalse(self.call('/health')[1]['ready']);self.heartbeat();self.assertTrue(self.call('/health')[1]['ready'])
 def test_plugin_disconnect_immediately_invalidates_heartbeat(self):
  self.heartbeat('stopped');self.assertFalse(self.call('/health')[1]['ready']);self.assertEqual(self.call('/submit',{'id':'stopped','action':'inspect'})[0],400)
 def test_queued_inspect_recovers_without_premature_or_duplicate_dispatch(self):
  self.stop();records=self.root/'bridge-jobs';records.mkdir(exist_ok=True)
  job={'id':'queued-read','status':'queued','request':{'id':'queued-read','action':'inspect','protocol':2,'bridge_version':'0.2.1'},'events':[]};(records/'queued-read.json').write_text(json.dumps(job));(self.receipts/'claimed-jobs.json').write_text('[]');self.start(False)
  self.assertEqual(self.recover(job)[0],200);self.assertEqual(self.status(job['id'])['status'],'queued');self.assertFalse((self.mailbox/'bridge-job.json').exists())
  self.heartbeat();self.assertEqual(self.run_plugin(job)['effects'],[]);self.assertEqual(self.status(job['id'])['status'],'native_call_returned')
 def test_queued_recovery_rejects_other_unclaimed_mailbox(self):
  self.stop();records=self.root/'bridge-jobs';records.mkdir(exist_ok=True)
  job={'id':'queued-read','status':'queued','request':{'id':'queued-read','action':'inspect','protocol':2,'bridge_version':'0.2.1'},'events':[]};(records/'queued-read.json').write_text(json.dumps(job));(self.receipts/'claimed-jobs.json').write_text('[]');(self.mailbox/'bridge-job.json').write_text('{"id":"other","action":"export-a"}');self.start(False)
  self.assertEqual(self.recover(job)[0],400);self.assertEqual(self.status(job['id'])['status'],'queued')
 def test_unclaimed_inspect_recovers_same_mailbox_and_id_once(self):
  job=self.pending();mailbox=self.mailbox/'bridge-job.json';before=mailbox.read_bytes()
  code,result=self.recover(job);self.assertEqual(code,200,result);self.assertTrue(result['request_unchanged']);self.assertEqual(mailbox.read_bytes(),before)
  self.assertEqual(self.run_plugin(job)['effects'],[]);returned=self.status(job['id']);self.assertEqual(returned['status'],'native_call_returned');self.assertEqual(returned['result']['project_path'],str(self.copy));self.assertEqual(mailbox.read_bytes(),before)
  self.assertEqual(self.run_plugin(job)['effects'],[]);self.assertEqual(self.status(job['id']),returned);self.assertEqual(self.call('/submit',job)[0],409)
 def test_claim_receipt_missing_or_corrupt_claims_and_changed_mailbox_refuse(self):
  job=self.pending();claims=self.receipts/'claimed-jobs.json';receipt=self.receipts/f"receipt-{job['id']}.json"
  for raw in ('["original-inspect"]','{}','bad-json'):
   claims.write_text(raw);self.assertEqual(self.recover(job)[0],400)
  claims.unlink();self.assertEqual(self.recover(job)[0],400);claims.write_text('[]')
  receipt.write_text('partial-invalid-receipt');self.assertEqual(self.recover(job)[0],400);receipt.unlink()
  (self.mailbox/'bridge-job.json').write_text('{}');self.assertEqual(self.recover(job)[0],400)
  self.assertEqual(self.status(job['id'])['status'],'dispatched')
 def test_live_plugin_cannot_be_reloaded_by_recovery(self):
  job=self.pending();self.heartbeat();code,result=self.recover(job);self.assertEqual(code,400);self.assertEqual(result['error'],'PLUGIN_LIVE_QUERY_ORIGINAL_JOB')
 def test_inspect_cannot_acquire_write_permit(self):
  job=self.pending();code,result=self.call('/guard/'+job['id'],{'phase':'save','nonce':'none'});self.assertEqual(code,400);self.assertEqual(result['error'],'READONLY_INSPECT_HAS_NO_WRITE_PERMIT');self.assertNotIn('save_permit',self.status(job['id']))
 def test_claim_race_after_recovery_check_never_reexecutes(self):
  job=self.pending();self.assertEqual(self.recover(job)[0],200)
  (self.receipts/'claimed-jobs.json').write_text(json.dumps([job['id']]))
  # Call fixture directly because this request must remain dispatched, not return.
  data={'plugin':str(BRIDGE/'plugin/main.js'),'project_path':str(self.copy),'copy_path':str(self.copy),'receipts':str(self.receipts),'mailbox':str(self.mailbox)}
  src=self.root/'race.json';src.write_text(json.dumps(data));p=subprocess.run(['node',str(ROOT/'tests/fixtures/premiere_host.cjs'),str(src)],capture_output=True,text=True,timeout=5);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['effects'],[])
  self.assertFalse((self.receipts/f"receipt-{job['id']}.json").exists());self.assertEqual(self.status(job['id'])['status'],'dispatched')
 def test_corrupt_claim_storage_does_not_replay_write(self):
  job=self.submit_export();(self.receipts/'claimed-jobs.json').write_text('not-json')
  data={'plugin':str(BRIDGE/'plugin/main.js'),'project_path':str(self.copy),'copy_path':str(self.copy),'receipts':str(self.receipts),'mailbox':str(self.mailbox)}
  self.wait(lambda:json.loads((self.mailbox/'bridge-job.json').read_text()).get('id')==job['id'])
  src=self.root/'corrupt.json';src.write_text(json.dumps(data));p=subprocess.run(['node',str(ROOT/'tests/fixtures/premiere_host.cjs'),str(src)],capture_output=True,text=True,timeout=5);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['effects'],[]);self.assertEqual(self.copy.read_text(),'candidate-user-bytes')
 def test_recovery_never_unlocks_writes_or_unknown_outcomes(self):
  job=self.submit_export();self.run_plugin(job,'unknown');self.expired();self.assertEqual(self.recover(job)[0],400);self.assertEqual(self.status(job['id'])['status'],'unknown');self.blocked()
 def test_accepted_inspect_requires_original_receipt_not_reload(self):
  job=self.pending();self.assertEqual(self.call('/result/'+job['id'],{'status':'accepted','action':'inspect'})[0],200)
  self.assertEqual(self.recover(job)[0],400);self.assertEqual(self.status(job['id'])['status'],'accepted');self.assertEqual(self.call('/verify/'+job['id'],{})[0],400)
 def test_legacy_write_does_not_get_readonly_compatibility(self):
  job={'id':'legacy-write','action':'snapshot-copy','copy_path':str(self.root/'new.prproj'),'expected_original_sha256':sha(self.original)};self.assertEqual(self.call('/submit',job)[0],200)
  self.wait(lambda:self.status(job['id'])['status']=='dispatched');self.stop();record=self.root/'bridge-jobs'/f"{job['id']}.json";old=json.loads(record.read_text());old['request']['bridge_version']='0.2.0';record.write_text(json.dumps(old));(self.mailbox/'bridge-job.json').write_text(json.dumps(old['request']));self.start();self.expired()
  self.assertEqual(self.recover(job)[0],400);self.assertEqual(self.run_plugin(job,project=self.original)['effects'],[]);self.assertEqual(self.status(job['id'])['error'],'BRIDGE_PROTOCOL_MISMATCH')
 def test_legacy_readonly_mailbox_finishes_without_rewrite(self):
  job=self.pending();self.stop();record=self.root/'bridge-jobs'/f"{job['id']}.json";old=json.loads(record.read_text());old['request']['bridge_version']='0.2.0';record.write_text(json.dumps(old));mailbox=self.mailbox/'bridge-job.json';mailbox.write_text(json.dumps(old['request']));before=mailbox.read_bytes();self.start();self.expired()
  self.assertEqual(self.recover(job)[0],200);self.assertEqual(self.run_plugin(job)['effects'],[]);self.assertEqual(mailbox.read_bytes(),before);self.assertEqual(self.status(job['id'])['request']['bridge_version'],'0.2.0')
 def test_manage_recovery_only_loads_original_plugin_then_reads_same_id(self):
  job=self.pending();sys.path.insert(0,str(BRIDGE))
  try:import manage
  finally:sys.path.pop(0)
  settings=self.root/'settings.json';settings.write_text('{"developer":true}');app=self.root/'Adobe.app';(app/'Contents').mkdir(parents=True)
  with (app/'Contents/Info.plist').open('wb') as f:plistlib.dump({'CFBundleShortVersionString':'26.5.2'},f)
  calls=[]
  def cli(*args):
   calls.append(args)
   if args==('apps','list'):return 'premierepro 26.5.2'
   self.assertEqual(args[:2],('plugin','load'));self.run_plugin(job);return ''
  def http(path,data=None):
   status,result=self.call(path,data);self.assertEqual(status,200,result);return result
  with patch.multiple(manage,PLUGIN=self.mailbox,SETTINGS=settings,APP=app,NODE=settings,CLI=settings),patch.object(manage,'cli',cli),patch.object(manage,'available',return_value=True),patch.object(manage.bridge,'http',http):
   result=manage.recover_inspect(job['id'],self.root)
  self.assertTrue(result['native_inspect_returned']);self.assertFalse(result['request_resubmitted']);self.assertEqual([x[:2] for x in calls],[('apps','list'),('plugin','load')]);self.assertEqual(set(self.call('/status')[1]['jobs']),{job['id']})
 def test_manage_rejects_legacy_controller_before_any_native_or_file_action(self):
  sys.path.insert(0,str(BRIDGE))
  try:import manage
  finally:sys.path.pop(0)
  with patch.object(manage.bridge,'http',return_value={'scope':str(self.root)}),patch.object(manage,'cli') as cli:
   with self.assertRaisesRegex(AssertionError,'CONTROLLER_UPGRADE_REQUIRES_RELEASE_MIGRATION'):manage.recover_inspect('original-inspect',self.root)
   cli.assert_not_called()

class BridgeParentPreparation(unittest.TestCase):
 """Controller-only requests: no Adobe host, plugin, media or encoder is run."""
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='pr-parent-test-');self.root=Path(self.tmp.name).resolve();self.scope=self.root/'scope';self.scope.mkdir()
  self.original=self.root/'original.prproj';self.original.write_text('protected-original')
  self.copy=self.scope/'candidate.prproj';self.copy.write_text('candidate')
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
  code="import sys;from types import SimpleNamespace;sys.path.insert(0,sys.argv[1]);import bridge;bridge.PORT=int(sys.argv[2]);bridge.serve(SimpleNamespace(scope=sys.argv[3],original=sys.argv[4],mailbox=None,receipt_dir=None))"
  self.proc=subprocess.Popen([sys.executable,'-B','-c',code,str(BRIDGE),str(self.port),str(self.scope),str(self.original)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  self.assertIn('ready',self.proc.stdout.readline())
 def tearDown(self):
  self.proc.terminate();self.proc.communicate(timeout=5);self.assertEqual(self.original.read_text(),'protected-original');self.tmp.cleanup()
 def call(self,path,data=None):
  req=urllib.request.Request(f'http://127.0.0.1:{self.port}'+path,data=None if data is None else json.dumps(data).encode(),headers={'X-Premiere-Bridge':'0.1.0','Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=5) as response:return response.status,json.load(response)
  except urllib.error.HTTPError as error:return error.code,json.load(error)
 def snapshot(self,target=None):
  return {'id':'snapshot','action':'snapshot-copy','copy_path':str(target or self.scope/'snapshots'/'nested'/'copy.prproj'),'expected_original_sha256':sha(self.original)}
 def test_snapshot_creates_only_missing_parent_after_validation(self):
  request=self.snapshot();status,result=self.call('/submit',request);self.assertEqual(status,200,result)
  self.assertTrue(Path(request['copy_path']).parent.is_dir());self.assertFalse(Path(request['copy_path']).exists());self.assertEqual(result['status'],'queued')
 def test_export_creates_only_output_parent(self):
  # Synthetic terminal callback binds the isolated candidate; no native call.
  self.assertEqual(self.call('/submit',{'id':'open-fixture','action':'open-copy','copy_path':str(self.copy)})[0],200)
  self.assertEqual(self.call('/result/open-fixture',{'status':'native_call_returned','result':{'project_path':str(self.copy),'project_guid':'fixture-only'}})[0],200)
  preset=self.scope/'preset.epr';preset.write_text('<Preset><ExportParamContainer/><DoAudio>true</DoAudio><DoVideo>true</DoVideo></Preset>')
  output=self.scope/'output'/'nested'/'a.mp4'
  request={'id':'export','action':'export-a','copy_path':str(self.copy),'expected_copy_sha256':sha(self.copy),'sequence_guid':'fixture-only','in_seconds':0,'out_seconds':1,'output_path':str(output),'preset_path':str(preset),'preset_sha256':sha(preset),'require_captions':False}
  status,result=self.call('/submit',request);self.assertEqual(status,200,result);self.assertTrue(output.parent.is_dir());self.assertFalse(output.exists());self.assertEqual(self.copy.read_text(),'candidate')
 def test_rejected_input_does_not_create_parent(self):
  request=self.snapshot();request['expected_original_sha256']='0'*64
  self.assertEqual(self.call('/submit',request)[0],400);self.assertFalse((self.scope/'snapshots').exists());self.assertEqual(self.call('/status')[1]['jobs'],{})
 def test_pending_job_does_not_create_parent(self):
  self.assertEqual(self.call('/submit',{'id':'pending','action':'inspect'})[0],200)
  status,result=self.call('/submit',self.snapshot());self.assertEqual(status,400);self.assertEqual(result['error'],'ANOTHER_JOB_ACTIVE_QUERY_FIRST');self.assertFalse((self.scope/'snapshots').exists())
 def test_symlink_cannot_create_parent_outside_scope(self):
  outside=self.root/'outside';outside.mkdir();(self.scope/'snapshots').symlink_to(outside,target_is_directory=True)
  status,result=self.call('/submit',self.snapshot());self.assertEqual(status,400);self.assertEqual(result['error'],'PATH_OUTSIDE_TEST_SCOPE');self.assertEqual(list(outside.iterdir()),[]);self.assertEqual(self.call('/status')[1]['jobs'],{})
 def test_existing_parent_file_or_destination_is_preserved(self):
  parent=self.scope/'snapshots';parent.write_text('user-parent')
  self.assertEqual(self.call('/submit',self.snapshot())[0],400);self.assertEqual(parent.read_text(),'user-parent');self.assertEqual(self.call('/status')[1]['jobs'],{})
  for target in (self.copy,self.scope/'existing-directory'):
   if target!=self.copy:target.mkdir()
   self.assertEqual(self.call('/submit',self.snapshot(target))[0],400)
  self.assertEqual(self.copy.read_text(),'candidate');self.assertTrue((self.scope/'existing-directory').is_dir())

if __name__=='__main__':unittest.main(verbosity=2)
