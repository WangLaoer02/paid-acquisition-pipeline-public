import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

STACK=Path(__file__).resolve().parents[2]/'rongyao-data-stack/scripts'
sys.path.insert(0,str(STACK))
import fast_video as video

class KeyringTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
        self.helper=self.state/'helper'
        self.helper.touch()
        for name,value in [('KEYRING_STATE',self.state),('KEYRING_HELPER',self.helper)]:
            p=patch.object(video,name,value);p.start();self.addCleanup(p.stop)
        p=patch.dict(video.os.environ,{},clear=True);p.start();self.addCleanup(p.stop)

    def test_migrated_prepare_uses_fixed_helper_without_legacy_read(self):
        (self.state/'provider.json').write_text('{}')
        p=subprocess.CompletedProcess([],0,json.dumps({'ok':True,'authenticated':True}),'')
        with patch.object(video.subprocess,'run',return_value=p) as run,patch.object(video.session,'ensure_active_session') as session:
            self.assertTrue(video.prepare()['authenticated'])
            self.assertEqual(run.call_args.args[0],[str(self.helper),'ensure-query'])
            session.assert_not_called()

    def test_denied_keychain_is_not_silently_replaced_by_legacy(self):
        (self.state/'provider.json').write_text('{}')
        p=subprocess.CompletedProcess([],1,json.dumps({'ok':False,'status':'KEYCHAIN_ACCESS_REQUIRED'}),'')
        with patch.object(video.subprocess,'run',return_value=p) as run:
            with self.assertRaisesRegex(RuntimeError,'KEYCHAIN_ACCESS_REQUIRED'):video.prepare()
            self.assertEqual(run.call_count,1)

    def test_disabled_blocks_before_browser_or_credential_use(self):
        (self.state/'disabled').touch()
        with patch.object(video.subprocess,'run') as run,patch.object(video.session,'ensure_active_session') as session:
            with self.assertRaisesRegex(RuntimeError,'ACCESS_REVOKED'):video.prepare()
            run.assert_not_called();session.assert_not_called()

    def test_injected_worker_uses_existing_bridge_without_recursing(self):
        (self.state/'provider.json').write_text('{}')
        with patch.dict(video.os.environ,{'RONGYAO_USERNAME':'test-user','RONGYAO_PASSWORD':'test-secret'}),patch.object(video,'bridge',return_value={'ok':True}) as bridge,patch.object(video.session,'ensure_active_session'):
            self.assertTrue(video.prepare()['ok'])
            bridge.assert_called_once_with('prepare')

    def test_resolve_does_not_read_old_plaintext_after_migration(self):
        (self.state/'provider.json').write_text('{}')
        legacy=self.state/'login.json';legacy.write_text('not valid json and must not be read')
        p=subprocess.CompletedProcess([],0,json.dumps({'ok':True}),'')
        with patch.object(video,'LOGIN',legacy),patch.object(video.session,'node_bin',return_value=Path('/node')),patch.object(video.subprocess,'run',return_value=p) as run:
            self.assertTrue(video.bridge('resolve','http://demand.backend.example.invalid/data/')['ok'])
            self.assertNotIn('RONGYAO_PASSWORD',run.call_args.kwargs['env'])

if __name__=='__main__':unittest.main()
