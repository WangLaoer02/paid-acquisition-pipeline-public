"""Actual local CLI probes only; no video, Premiere host, login or upload."""
import contextlib,datetime,importlib.util,io,json,socket,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import workflow_readiness as ready

class ReadinessTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
  self.scope=self.root/'projects/P/剪辑/bridge';self.scope.mkdir(parents=True)
  self.request={'schema':ready.SCHEMA,'premiere_scope':'projects/P/剪辑/bridge','upload_session':'same_session'}
 def script(self,relative,data,*,barrier=None,delay=0):
  path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True)
  code='import json,time,sys\n# allowed command: '+repr('probe')+'\n'
  if barrier:
   mine,other=barrier
   code+='from pathlib import Path\nPath('+repr(str(self.root/mine))+').touch()\n'
   code+='end=time.monotonic()+2\nwhile not Path('+repr(str(self.root/other))+').exists() and time.monotonic()<end:time.sleep(.01)\n'
   code+='assert Path('+repr(str(self.root/other))+').exists(), "parallel probe missing"\n'
  if delay:code+='time.sleep('+str(delay)+')\n'
  code+='print(json.dumps('+repr(data)+'))\n';path.write_text(code)
 def probes(self,*,scope=None,job=None,barrier=False,delay=0,upload=None):
  self.script('workflow/tools/premiere-bridge/manage.py',{'scope':scope or str(self.scope),'jobs':{'held':job} if job else {}},barrier=('pr','http') if barrier else None,delay=delay)
  self.script('workflow/tools/rongyao-http-upload/scripts/rongyao_upload.py',upload or {'ok':True,'authenticated':True,'probe_scope':'form_only','dynamic_enums_verified':False,'selects':{'kind':[{'value':'existing','label':'Known'}]}},barrier=('http','pr') if barrier else None,delay=delay)
 def test_real_subprocess_probes_start_together_and_only_report_preparation(self):
  self.probes(barrier=True);result=ready.check(self.root,self.request,'P')
  self.assertEqual([result['checks'][k]['state'] for k in ('premiere','upload')],['checked','checked'])
  self.assertFalse(result['new_authorization_granted']);self.assertFalse(result['media_job_started']);self.assertFalse(result['project_or_sheet_written'])
  self.assertFalse(result['checks']['premiere']['native_host_verified']);self.assertFalse(result['checks']['upload']['target_fields_verified'])
 def test_wrong_scope_or_unknown_job_cannot_be_ready(self):
  for kwargs in [{'scope':'another-project'},{'job':{'status':'unknown','request':{'action':'export-a'}}}]:
   self.probes(**kwargs);result=ready.check(self.root,self.request,'P')
   self.assertEqual(result['checks']['premiere']['state'],'hold');self.assertFalse(result['checks']['premiere']['reuse_controller_without_restart'])
 def test_unverified_form_does_not_authorize_upload(self):
  self.probes(upload={'ok':True,'authenticated':True,'probe_scope':'form_only','dynamic_enums_verified':True})
  self.assertEqual(ready.check(self.root,self.request,'P')['checks']['upload']['state'],'hold')
 def test_missing_explicit_session_does_not_probe_or_login(self):
  with patch.object(ready.subprocess,'run') as run:
   result=ready.check(self.root,{'schema':ready.SCHEMA},'P')
  run.assert_not_called();self.assertEqual(result['checks']['upload']['error'],'EXPLICIT_EXISTING_SESSION_REQUIRED');self.assertFalse(result['login_started'])
 def test_hung_probe_has_bounded_local_timeout_and_does_not_restart(self):
  self.probes(delay=2);started=time.monotonic()
  with patch.object(ready,'TIMEOUT_SECONDS',.2):result=ready.check(self.root,self.request,'P')
  self.assertLess(time.monotonic()-started,1.5)
  self.assertTrue(all(x['error']=='READINESS_TIMEOUT' for x in result['checks'].values()))
 def test_arbitrary_commands_and_other_project_paths_are_rejected(self):
  for change in [{'argv':['anything']},{'premiere_scope':'projects/OTHER/bridge'},{'premiere_scope':str(self.scope)},{'upload_session':'bad/session'}]:
   with self.assertRaises(ValueError):ready.check(self.root,{**self.request,**change},'P')
 def test_raw_error_output_is_not_exposed(self):
  self.probes(upload={'ok':False,'error':'cookie=must_not_escape','private':'must_not_escape'})
  result=ready.check(self.root,self.request,'P');self.assertNotIn('must_not_escape',json.dumps(result));self.assertEqual(result['checks']['upload']['error'],'PROBE_FAILED')
 def test_original_cli_refuses_readiness_before_offline_network_or_host_checks(self):
  result=subprocess.run([sys.executable,str(ROOT/'scripts/workflow_node.py'),'context','--node','A01','--offline-preparation','--readiness-request','absent.json'],text=True,capture_output=True,timeout=3)
  self.assertNotEqual(result.returncode,0);self.assertIn('unrecognized arguments: --readiness-request',result.stderr)
 @unittest.skip("Frozen entry no longer exposes --readiness-request; standalone preparation probes remain tested")
 def test_original_context_checks_live_version_and_state_before_optional_parallel_probes(self):
  import workflow_node as node
  import workflow_rules
  payload=self.root/'request.json';payload.write_text(json.dumps(self.request));calls=[]
  clock=self.root/'clock.json';clock_bytes=json.dumps({'schema':'workflow-timing-v1','started_at':(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(seconds=12)).isoformat()});clock.write_text(clock_bytes)
  state={'project_id':'P','item':{'current_node_id':'A09','family':'a'}}
  def version(*args):calls.append('version');return {'live_center_verified':True}
  def live(*args):calls.append('state');return state
  def probe(*args):calls.append('probe');return {'checks':{},'elapsed_seconds':0}
  with patch.object(node,'ROOT',self.root),patch.object(workflow_rules,'check',side_effect=version),patch.object(node,'live_state',side_effect=live),patch.object(node,'make_context',return_value={'paid_generation_authorized':False}),patch.object(ready,'check',side_effect=probe),patch.object(sys,'argv',['workflow_node.py','context','--item','P-A','--readiness-request','request.json','--timing-record','clock.json','--format','json']),contextlib.redirect_stdout(io.StringIO()) as output:
   node.main()
  self.assertEqual(calls,['version','state','probe']);result=json.loads(output.getvalue());self.assertFalse(result['paid_generation_authorized'])
  self.assertGreaterEqual(result['timing']['elapsed_seconds'],12);self.assertLess(result['timing']['remaining_seconds'],288);self.assertFalse(result['timing']['five_minute_pass_inferred']);self.assertEqual(clock.read_text(),clock_bytes)
  with patch.object(workflow_rules,'check',side_effect=ValueError('VERSION_MISMATCH')),patch.object(ready,'check') as probe,patch.object(sys,'argv',['workflow_node.py','context','--item','P-A','--readiness-request','request.json']):
   with self.assertRaisesRegex(ValueError,'VERSION_MISMATCH'):node.main()
  probe.assert_not_called()

class ProbeClientTests(unittest.TestCase):
 def module(self):
  path=ROOT/'workflow/tools/rongyao-http-upload/scripts/rongyao_upload.py'
  spec=importlib.util.spec_from_file_location('probe_client_fixture',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 def test_no_session_fails_before_connecting_or_restoring(self):
  module=self.module()
  with patch.object(module.socket,'socket') as connect:
   with self.assertRaisesRegex(ValueError,'PROBE_REQUIRES_EXPLICIT_EXISTING_SESSION'):module.rpc('probe')
  connect.assert_not_called()
 def test_exact_original_session_receives_only_probe_request(self):
  module=self.module()
  with tempfile.TemporaryDirectory() as directory:
   folder=Path(directory);server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.addCleanup(server.close)
   sock=folder/'existing.sock';server.bind(str(sock));server.listen(1)
   (folder/'existing.json').write_text(json.dumps({'session_id':'existing','socket':str(sock)}));captured=[]
   def handle():
    connection,_=server.accept()
    with connection:
     captured.append(json.loads(connection.makefile('rb').readline()));connection.sendall(b'{"ok":true,"probe_scope":"form_only"}\n')
   worker=threading.Thread(target=handle,daemon=True);worker.start()
   with patch.object(module,'BASE',folder):result=module.rpc('probe','existing',gid='193')
   worker.join(1);self.assertEqual(captured,[{'command':'probe','gid':'193'}]);self.assertTrue(result['ok'])

if __name__=='__main__':unittest.main()
