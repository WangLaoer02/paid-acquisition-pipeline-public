import contextlib
import hashlib
import http.server
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
import threading
import urllib.request
import unittest
import wave
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

class MediaDownloadContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('ffprobe') or not shutil.which('ffmpeg'):
            raise unittest.SkipTest('ffprobe and ffmpeg are required for real media fixture checks')
        def wav(sample):
            output = io.BytesIO()
            with wave.open(output, 'wb') as sound:
                sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(8000)
                sound.writeframes(sample * 800)
            return output.getvalue()
        cls.first, cls.second = wav(b'\x00\x00'), wav(b'\x10\x00')
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.server.requests.append((self.path, dict(self.headers)))
                if self.path == '/missing':
                    self.send_error(404);return
                if self.path == '/unsafe-redirect':
                    self.send_response(302);self.send_header('Location','http://name:secret@127.0.0.1/media')
                    self.end_headers();return
                body = cls.second if self.path == '/other' else cls.first
                kind = 'audio/wav'
                if self.path in {'/html', '/hidden-html'}:
                    body = b'  <!doctype html><html>login</html>'
                    kind = 'text/html' if self.path == '/html' else 'application/octet-stream'
                elif self.path == '/invalid':
                    body = b'not an audio or video file';kind = 'application/octet-stream'
                self.send_response(200)
                if self.path != '/no-type':self.send_header('Content-Type',kind)
                self.send_header('Content-Length',str(len(body) + (100 if self.path == '/truncated' else 0)))
                self.end_headers();self.wfile.write(body)
                if self.path == '/truncated':self.close_connection = True
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.server.requests = []
        cls.worker = threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.worker.join(timeout=2)

    def setUp(self):
        self.m = module('test_ryai_download', TOOLS/'rongyao-ai-generator/scripts/ryai.py')
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name)/'media'/'result.wav'

    def test_direct_download_verifies_bytes_streams_and_full_decode_without_browser(self):
        args = ['ryai.py','download','--url',self.base+'/media','--name','result.wav',
                '--destination',str(self.target)]
        output = io.StringIO()
        with patch.object(sys,'argv',args), patch.object(self.m,'dispatch') as browser, \
             patch.object(self.m,'resolve_session') as auth, contextlib.redirect_stdout(output):
            self.assertEqual(self.m.main(),0)
        browser.assert_not_called();auth.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result['file'],str(self.target));self.assertEqual(self.target.read_bytes(),self.first)
        self.assertEqual(result['sha256'],hashlib.sha256(self.first).hexdigest())
        self.assertTrue(result['download_verified']);self.assertTrue(result['full_decode_verified'])
        self.assertFalse(result['playback_verified']);self.assertIsNone(result['visual_acceptance'])
        self.assertEqual(result['media']['streams'][0]['codec_type'],'audio')
        headers = {k.lower():v for k,v in self.server.requests[-1][1].items()}
        self.assertNotIn('cookie',headers);self.assertNotIn('authorization',headers)
        self.assertEqual(list(self.target.parent.glob('*.part')),[])

    def test_same_bytes_reuse_without_overwriting_and_expected_hash_avoids_network(self):
        self.m.download_to_destination(self.base+'/media',self.target)
        before = self.target.stat()
        reused = self.m.download_to_destination(self.base+'/media',self.target)
        self.assertTrue(reused['reused']);self.assertEqual(self.target.stat().st_mtime_ns,before.st_mtime_ns)
        count = len(self.server.requests)
        reused = self.m.download_to_destination(self.base+'/media',self.target,hashlib.sha256(self.first).hexdigest())
        self.assertTrue(reused['reused']);self.assertEqual(len(self.server.requests),count)

    def test_expected_hash_reuse_rejects_inplace_edits_during_probe_or_decode(self):
        self.target.parent.mkdir()
        run = self.m.subprocess.run
        for boundary in ('ffprobe','ffmpeg'):
            with self.subTest(boundary=boundary):
                self.target.write_bytes(self.first);before = self.target.stat()
                def edit(command, *args, **kwargs):
                    if Path(command[0]).name == boundary:
                        self.target.write_bytes(self.second)
                        os.utime(self.target,ns=(before.st_atime_ns,before.st_mtime_ns))
                    return run(command,*args,**kwargs)
                with patch.object(self.m.subprocess,'run',side_effect=edit), \
                     patch.object(self.m.urllib.request,'build_opener') as network:
                    with self.assertRaisesRegex(ValueError,'MEDIA_CHANGED_DURING_VALIDATION'):
                        self.m.download_to_destination(self.base+'/media',self.target,hashlib.sha256(self.first).hexdigest())
                network.assert_not_called();self.assertEqual(self.target.read_bytes(),self.second)

    def test_existing_target_rejects_atomic_replacement_during_ffprobe(self):
        self.target.parent.mkdir();self.target.write_bytes(self.first)
        before = self.target.stat();run = self.m.subprocess.run
        replacement = self.target.with_name('user-edit.wav');replacement.write_bytes(self.second)
        os.utime(replacement,ns=(before.st_atime_ns,before.st_mtime_ns))
        def edit(command,*args,**kwargs):
            if Path(command[0]).name == 'ffprobe' and command[-1] == str(self.target):
                replacement.replace(self.target)
            return run(command,*args,**kwargs)
        with patch.object(self.m.subprocess,'run',side_effect=edit):
            with self.assertRaisesRegex(ValueError,'MEDIA_CHANGED_DURING_VALIDATION'):
                self.m.download_to_destination(self.base+'/media',self.target)
        self.assertEqual(self.target.read_bytes(),self.second)
        self.assertEqual(list(self.target.parent.glob('*.part')),[])

    def test_missing_content_type_still_requires_real_readable_media(self):
        result = self.m.download_to_destination(self.base+'/no-type',self.target)
        self.assertTrue(result['full_decode_verified']);self.assertEqual(self.target.read_bytes(),self.first)

    def test_concurrent_destination_creation_never_overwrites_other_bytes(self):
        link = self.m.os.link
        def concurrent_write(partial, target):
            target.write_bytes(self.second)
            return link(partial,target)
        with patch.object(self.m.os,'link',side_effect=concurrent_write):
            with self.assertRaisesRegex(ValueError,'MEDIA_DESTINATION_CONFLICT'):
                self.m.download_to_destination(self.base+'/media',self.target)
        self.assertEqual(self.target.read_bytes(),self.second)
        self.assertEqual(list(self.target.parent.glob('*.part')),[])

    def test_different_remote_bytes_preserve_existing_file(self):
        self.m.download_to_destination(self.base+'/media',self.target)
        with self.assertRaisesRegex(ValueError,'MEDIA_DESTINATION_CONFLICT'):
            self.m.download_to_destination(self.base+'/other',self.target)
        self.assertEqual(self.target.read_bytes(),self.first)
        self.assertEqual(list(self.target.parent.glob('*.part')),[])

    def test_bad_responses_and_incomplete_download_never_replace_existing_file(self):
        self.target.parent.mkdir();self.target.write_bytes(self.first)
        for route, error in [('/html','MEDIA_RESPONSE_NOT_MEDIA'),('/hidden-html','MEDIA_RESPONSE_IS_HTML'),
                             ('/invalid','MEDIA_NOT_READABLE'),('/truncated','MEDIA_DOWNLOAD_INCOMPLETE'),
                             ('/missing','MEDIA_DOWNLOAD_HTTP_ERROR'),('/unsafe-redirect','INVALID_MEDIA_URL')]:
            with self.subTest(route=route), self.assertRaisesRegex(ValueError,error):
                self.m.download_to_destination(self.base+route,self.target)
            self.assertEqual(self.target.read_bytes(),self.first)
            self.assertEqual(list(self.target.parent.glob('*.part')),[])

    def test_failed_download_leaves_no_final_file_or_partial(self):
        for route, expected, error in [('/truncated',None,'MEDIA_DOWNLOAD_INCOMPLETE'),
                                       ('/media','a'*64,'MEDIA_DOWNLOAD_SHA_MISMATCH')]:
            with self.subTest(route=route), self.assertRaisesRegex(ValueError,error):
                self.m.download_to_destination(self.base+route,self.target,expected)
            self.assertFalse(self.target.exists());self.assertEqual(list(self.target.parent.glob('*.part')),[])

    def test_invalid_urls_and_expected_hashes_fail_before_network(self):
        for url, expected in [('file:///tmp/media',None),('http://name:secret@localhost/media',None),
                              (self.base+'/media','short')]:
            with self.subTest(url=url), patch.object(self.m.urllib.request,'build_opener') as request:
                with self.assertRaises(ValueError):self.m.download_to_destination(url,self.target,expected)
                request.assert_not_called()

    def test_legacy_download_keeps_requested_only_browser_contract(self):
        with patch.object(sys,'argv',['ryai.py','download','--url',self.base+'/media','--name','result.wav']), \
             patch.object(self.m,'dispatch',return_value=0) as browser:
            self.assertEqual(self.m.main(),0)
        self.assertEqual(browser.call_args.args[0],{'command':'download','operation':'download',
                         'url':self.base+'/media','name':'result.wav'})

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
