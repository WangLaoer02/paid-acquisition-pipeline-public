import http.cookiejar
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch

import session_store as store


def cookie(domain='adopenplatform.backend.example.invalid',expires=None):
    return http.cookiejar.Cookie(0,'session','fixture-private-value',None,False,domain,False,False,
                                 '/',True,False,expires,True,None,None,{'HttpOnly':None},False)


class SavedSessionTests(unittest.TestCase):
    def setUp(self):
        running=patch.object(store,'running_saved_service',return_value=None)
        running.start();self.addCleanup(running.stop)

    def engine(self):
        jar=http.cookiejar.CookieJar();jar.set_cookie(cookie())
        return SimpleNamespace(http=SimpleNamespace(jar=jar),state={'status':'ready',
                              'authentication_method':'existing_keychain_password_and_manual_sms'})

    def test_roundtrip_keeps_session_cookie_and_httponly_without_public_secrets(self):
        engine=self.engine();captured={}
        def vault(command,scope,value=None):
            if command=='save':captured.update(value);return {'ok':True}
            return captured
        with patch.object(store,'vault',side_effect=vault):
            store.save(engine,'upload')
            restored=store.load('upload')
        actual=list(restored.http.jar)[0]
        self.assertEqual(actual.value,'fixture-private-value')
        self.assertIn('HttpOnly',actual._rest)
        self.assertTrue(restored.state['restored_from_keychain'])
        self.assertNotIn('fixture-private-value',json.dumps(engine.state))

    def test_successive_business_reads_do_not_rewrite_unchanged_keychain(self):
        engine=self.engine()
        with patch.object(store,'vault',return_value={'ok':True}) as vault:
            store.remember(engine,'upload');store.remember(engine,'upload')
        self.assertEqual(vault.call_count,1)

    def test_cookie_rotation_updates_saved_session(self):
        engine=self.engine()
        with patch.object(store,'vault',return_value={'ok':True}) as vault:
            store.remember(engine,'upload')
            list(engine.http.jar)[0].value='rotated-private-value'
            store.remember(engine,'upload')
        self.assertEqual(vault.call_count,2)

    def test_foreign_cookies_are_never_saved(self):
        engine=self.engine();engine.http.jar.set_cookie(cookie('example.invalid'))
        with patch.object(store,'vault',return_value={'ok':True}) as vault:store.save(engine,'upload')
        self.assertEqual(len(vault.call_args.args[2]['cookies']),1)

    def test_storage_denial_does_not_replay_or_fail_finished_operation(self):
        engine=self.engine()
        with patch.object(store,'vault',side_effect=ValueError('SESSION_VAULT_ACCESS_REQUIRED')):
            store.remember(engine,'upload')
        self.assertFalse(engine.state['cookies_persisted'])
        self.assertEqual(engine.state['session_persistence_error'],'SESSION_VAULT_ACCESS_REQUIRED')

    def test_expired_saved_session_cleared_without_sms(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binary=root/'vault';binary.touch()
            with patch.object(store,'BASE',root),patch.object(store,'BINARY',binary),patch.object(
                    store,'load',return_value=self.engine()),patch.object(store,'verify',side_effect=ValueError('LOGIN_EXPIRED')), patch.object(store,'vault') as vault,patch.object(store,'spawn') as spawn:
                self.assertIsNone(store.restore_service(root,scope='upload'))
            vault.assert_called_once_with('clear','upload');spawn.assert_not_called()

    def test_network_error_keeps_saved_session_and_never_logs_in(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binary=root/'vault';binary.touch()
            with patch.object(store,'BASE',root),patch.object(store,'BINARY',binary),patch.object(
                    store,'load',return_value=self.engine()),patch.object(store,'verify',side_effect=ValueError('HTTP_READ_FAILED')), patch.object(store,'vault') as vault,patch.object(store,'spawn') as spawn:
                with self.assertRaisesRegex(ValueError,'HTTP_READ_FAILED'):store.restore_service(root,scope='upload')
            vault.assert_not_called();spawn.assert_not_called()

    def test_revocation_stops_before_native_vault_access(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);marker=home/'.codex/state/rongyao-keyring/disabled'
            marker.parent.mkdir(parents=True);marker.touch()
            with patch.object(store.Path,'home',return_value=home),patch.object(store.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'ACCESS_REVOKED'):store.vault('load','upload')
            run.assert_not_called()

    def test_initializer_is_explicit_manual_not_a_batch_or_auto_sms_change(self):
        from initialize_session import worker_source
        text=worker_source()
        self.assertIn('with hidden answer',text)
        self.assertNotIn('from sms_receiver import baseline,receive',text)
        self.assertIn('existing_keychain_password_and_manual_sms',text)

    def test_clean_service_process_receives_no_password_or_cookie_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);sid='0123456789';target=home/'.codex/state/rongyao-upload-http'
            target.mkdir(parents=True);(target/(sid+'.sock')).touch();(target/(sid+'.json')).write_text('{}')
            with patch.object(store.Path,'home',return_value=home),patch.object(store,'BASE',home),patch.dict(
                    os.environ,{'RONGYAO_PASSWORD':'fixture-password','RONGYAO_USERNAME':'fixture-user'}),patch.object(
                    store.subprocess,'Popen') as popen,patch.object(store.os,'fork',side_effect=AssertionError('fork forbidden')):
                result=store.spawn(self.engine(),home,86400,'upload',session_id=sid)
            self.assertTrue(result['authenticated'])
            self.assertNotIn('fixture-password',json.dumps(popen.call_args.args))
            self.assertNotIn('RONGYAO_PASSWORD',popen.call_args.kwargs['env'])
            self.assertTrue(popen.call_args.kwargs['start_new_session'])

    def test_concurrent_restore_reuses_new_service_instead_of_spawning_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binary=root/'vault';binary.touch()
            existing={'ok':True,'status':'ready','cookies_persisted':True,'session_id':'0123456789'}
            with patch.object(store,'BASE',root),patch.object(store,'BINARY',binary),patch.object(
                    store,'running_saved_service',return_value=existing),patch.object(store,'load') as load:
                self.assertEqual(store.restore_service(root,scope='upload'),existing)
            load.assert_not_called()


if __name__=='__main__':unittest.main()


class RestoreDiagnosticTests(unittest.TestCase):
    def test_demand_failure_keeps_upload_cookie_and_records_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binary=root/'vault';binary.touch()
            with patch.object(store,'BASE',root),patch.object(store,'BINARY',binary),patch.object(store,'running_saved_service',return_value=None),patch.object(store,'load',return_value=object()),patch.object(store,'verify',side_effect=ValueError('DEMAND_LOGIN_REQUIRED')),patch.object(store,'vault') as vault:
                with self.assertRaisesRegex(ValueError,'DEMAND_LOGIN_REQUIRED'):store.restore_service(root,scope='upload')
            vault.assert_not_called()
            result=json.loads((root/'restore-upload-status.json').read_text())
            self.assertEqual(result['status'],'DEMAND_LOGIN_REQUIRED');self.assertFalse(result['keychain_cleared'])

    def test_missing_saved_session_records_no_sms_and_no_remote_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);binary=root/'vault';binary.touch()
            with patch.object(store,'BASE',root),patch.object(store,'BINARY',binary),patch.object(store,'running_saved_service',return_value=None),patch.object(store,'load',return_value=None),patch.object(store,'verify') as verify:
                self.assertIsNone(store.restore_service(root,scope='upload'))
            verify.assert_not_called()
            result=json.loads((root/'restore-upload-status.json').read_text());self.assertEqual(result['status'],'NO_VALID_SAVED_SESSION');self.assertFalse(result['sms_sent'])


class PersistentFailureReasonTests(unittest.TestCase):
    def test_missing_session_poll_does_not_erase_reason_cookie_was_cleared(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'BASE',Path(folder)):
            store.recovery_status('upload','LOGIN_EXPIRED',keychain_cleared=True)
            store.recovery_status('upload','NO_VALID_SAVED_SESSION',keychain_cleared=False)
            value=json.loads((Path(folder)/'restore-upload-status.json').read_text())
            self.assertEqual(value['last_authentication_failure']['status'],'LOGIN_EXPIRED')
            self.assertTrue(value['last_authentication_failure']['keychain_cleared'])
            self.assertFalse(value['sms_sent'])
