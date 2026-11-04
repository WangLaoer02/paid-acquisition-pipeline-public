import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import os
import signal
import shutil
import time
import urllib.request
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'workflow/rules/implementation/rongyao-tools/skills'

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

class HelpContract(unittest.TestCase):
    def test_help_and_bad_arguments_never_invoke_native(self):
        m = module('test_keyring_cli', TOOLS/'rongyao-keyring/scripts/keyring.py')
        with tempfile.TemporaryDirectory() as tmp:
            m.BINARY = Path(tmp)/'helper'; m.BINARY.touch()
            for args in [['--help'], ['ensure-ai','--help'], ['ensure-ai','-h'],
                         ['verify-upload-chrome','--help'], ['ensure-ai','--unknown'],
                         ['fast-video','search','--help'], ['fast-video','resolve']]:
                with self.subTest(args=args), patch.object(sys,'argv',['keyring.py',*args]), \
                     patch.object(m.subprocess,'run') as run, \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    run.return_value = SimpleNamespace(returncode=0)
                    try: m.main()
                    except SystemExit: pass
                    run.assert_not_called()

class GenerationContract(unittest.TestCase):
    def setUp(self):
        self.m = module('test_ryai_cli', TOOLS/'rongyao-ai-generator/scripts/ryai.py')

    def test_default_transport_is_automatic(self):
        with patch.object(sys,'argv',['ryai.py','status']), patch.object(self.m,'dispatch') as call:
            self.m.main()
        self.assertEqual(call.call_args.args[1].transport, 'auto')

    def test_unprotected_submit_is_rejected_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp)/'plan.json'
            p = self.m.build_plan(SimpleNamespace(type='video',model='bytedance_seedance_2_0_pinkuang',
                prompt='fixture only',prompt_file=None,attachments=None,subject_refs=None,chatid=None,
                parent_ids=None,video_mode='full',ratio='16:9',resolution='720p',duration=8,
                count=1,audio=False,no_optimize=True,size=None,quality=None,format=None,background=None))
            plan.write_text(json.dumps(p))
            with patch.object(sys,'argv',['ryai.py','submit','--plan',str(plan),'--execute']), \
                 patch.object(self.m,'dispatch') as send, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'WORKSPACE_REQUIRED'):
                    self.m.main()
            send.assert_not_called()

    def test_registered_generation_is_not_sent_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.m.GenerationLedger(Path(tmp))
            digest = 'a'*64
            ledger.reserve(digest, 'fixture-model')
            ledger.update(digest, state='submitted', task_id='fixture-task')
            with self.assertRaisesRegex(ValueError, 'GENERATION_ALREADY_REGISTERED'):
                ledger.reserve(digest, 'fixture-model')
            self.assertEqual(ledger.read(digest)['task_id'], 'fixture-task')

    def test_unpriced_plan_requires_explicit_exception(self):
        with self.assertRaisesRegex(ValueError,'UNPRICED_GENERATION'):
            self.m.check_pricing({'estimated_cost':None}, False)
        self.m.check_pricing({'estimated_cost':None}, True)

    def test_unknown_result_blocks_second_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.m.GenerationLedger(Path(tmp))
            @contextlib.contextmanager
            def mutation(*args, **kwargs): yield {}
            runtime = SimpleNamespace(ensure_writer=lambda action:None, mutation=mutation)
            args = SimpleNamespace(workspace=tmp, authorization_ticket='fixture', transport='auto',
                                   allow_unpriced=True, output=None)
            plan={'estimated_cost':None,'body':{'model':'fixture'}}
            with patch.object(self.m,'generation_runtime',return_value=runtime), \
                 patch.object(self.m,'GenerationLedger',return_value=ledger), \
                 patch.object(self.m,'resolve_session'), \
                 patch.object(self.m,'dispatch',side_effect=RuntimeError('fixture disconnect')) as send:
                with self.assertRaisesRegex(RuntimeError,'disconnect'):
                    self.m.guarded_submit(plan,plan['body'],args)
                self.assertEqual(ledger.read(self.m.plan_digest(plan))['state'],'submission_unknown')
                with self.assertRaisesRegex(ValueError,'GENERATION_ALREADY_REGISTERED'):
                    self.m.guarded_submit(plan,plan['body'],args)
                self.assertEqual(send.call_count,1)

    def test_authentication_failure_has_no_send_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=self.m.GenerationLedger(Path(tmp))
            @contextlib.contextmanager
            def mutation(*args,**kwargs): yield {}
            runtime=SimpleNamespace(ensure_writer=lambda action:None,mutation=mutation)
            args=SimpleNamespace(workspace=tmp,authorization_ticket='fixture',transport='auto',allow_unpriced=True,output=None)
            plan={'estimated_cost':None,'body':{'model':'fixture'}}
            with patch.object(self.m,'generation_runtime',return_value=runtime), \
                 patch.object(self.m,'GenerationLedger',return_value=ledger), \
                 patch.object(self.m,'resolve_session',side_effect=ValueError('AI_SESSION_REQUIRED')), \
                 patch.object(self.m,'dispatch') as send:
                with self.assertRaisesRegex(ValueError,'AI_SESSION_REQUIRED'):
                    self.m.guarded_submit(plan,plan['body'],args)
                send.assert_not_called();self.assertIsNone(ledger.read(self.m.plan_digest(plan)))

class SessionLifecycle(unittest.TestCase):
    def test_detached_session_survives_cli_parent_exit(self):
        node=shutil.which('node')
        self.assertIsNotNone(node)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);profile=folder/'profile';state=folder/'session.json';fake=folder/'fake-chrome'
            fake.write_text('#!'+node+'\n'+r'''
const fs=require('fs'),http=require('http');
const dir=process.argv.find(x=>x.startsWith('--user-data-dir=')).split('=')[1];
const server=http.createServer((req,res)=>{res.setHeader('content-type','application/json');res.end(JSON.stringify(req.url==='/json/list'?[]:{Browser:'fixture',webSocketDebuggerUrl:'ws://127.0.0.1:'+server.address().port+'/fixture'}));});
server.listen(0,'127.0.0.1',()=>{fs.mkdirSync(dir,{recursive:true});fs.writeFileSync(dir+'/DevToolsActivePort',String(server.address().port)+'\n/fixture');});
''');fake.chmod(0o700)
            process_pid=None
            try:
                bridge=TOOLS/'rongyao-data-stack/scripts/active_chrome_bridge.mjs'
                result=subprocess.run([node,str(bridge),'open','--chrome',str(fake),'--profile-dir',str(profile),'--state-file',str(state)],capture_output=True,text=True,timeout=8)
                self.assertEqual(result.returncode,0,result.stderr)
                info=json.loads(result.stdout);process_pid=info['pid']
                time.sleep(.3);os.kill(process_pid,0)
                with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/json/version",timeout=2) as response:
                    self.assertEqual(json.load(response)['Browser'],'fixture')
                second=subprocess.run([node,str(bridge),'open','--chrome',str(fake),'--profile-dir',str(profile),'--state-file',str(state)],capture_output=True,text=True,timeout=5)
                self.assertTrue(json.loads(second.stdout)['reused'])
                self.assertEqual(json.loads(second.stdout)['pid'],process_pid)
            finally:
                if process_pid:
                    try:os.kill(process_pid,signal.SIGTERM)
                    except ProcessLookupError:pass

if __name__ == '__main__': unittest.main()
