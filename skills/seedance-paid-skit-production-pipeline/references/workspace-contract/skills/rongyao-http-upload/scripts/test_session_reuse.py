import http.cookiejar
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.request
import urllib.error
from email.utils import formatdate

from upload_api import Api, ENTRY, PORTAL, PRECHECK, Stop


class SessionReuseTests(unittest.TestCase):
    def api(self, portal='<a href="http://adopenplatform.backend.example.invalid/native-entry">advertising</a>'):
        transport=SimpleNamespace(client=None,jar=http.cookiejar.CookieJar(),
                                  request=Mock(side_effect=[(200,{},portal),(200,{},'<html>entry</html>')]))
        return Api(SimpleNamespace(http=transport,state={'status':'ready'}))

    def response(self, body=b'protected-page'):
        r=Mock();r.__enter__=lambda self:self;r.__exit__=lambda *a:None
        r.status=200;r.headers.get_content_charset.return_value='utf-8';r.read.return_value=body
        return r

    def redirect(self, opener, req):
        handler=next(x for x in opener.handlers if isinstance(x,urllib.request.HTTPRedirectHandler))
        return handler.redirect_request(req,None,302,'',{},PORTAL+'?login=1')

    def test_successful_normal_read_does_not_add_checks(self):
        api=self.api()
        with patch.object(urllib.request.OpenerDirector,'open',return_value=self.response()) as opened:
            self.assertEqual(api.request(ENTRY),'protected-page')
        self.assertEqual(opened.call_count,1);api.engine.http.request.assert_not_called()

    def test_ad_redirect_reuses_native_portal_and_retries_read_once(self):
        api=self.api();calls=[]
        def opened(opener,req,timeout):
            calls.append(req.full_url)
            if len(calls)==1:return self.redirect(opener,req)
            return self.response()
        with patch.object(urllib.request.OpenerDirector,'open',opened):
            self.assertEqual(api.request(ENTRY),'protected-page')
        self.assertEqual(calls,[ENTRY,ENTRY])
        self.assertEqual([x.args for x in api.engine.http.request.call_args_list],
                         [(PORTAL,),('http://adopenplatform.backend.example.invalid/native-entry',)])

    def test_expired_portal_stops_without_password_or_sms(self):
        api=self.api('<input type="password">')
        with patch.object(urllib.request.OpenerDirector,'open',lambda opener,req,timeout:self.redirect(opener,req)):
            with self.assertRaisesRegex(Stop,'LOGIN_EXPIRED'):api.request(ENTRY)
        self.assertEqual(api.engine.state['status'],'login_required')
        api.engine.http.request.assert_called_once_with(PORTAL)

    def test_second_redirect_stops_no_login_loop(self):
        api=self.api()
        with patch.object(urllib.request.OpenerDirector,'open',lambda opener,req,timeout:self.redirect(opener,req)):
            with self.assertRaisesRegex(Stop,'LOGIN_EXPIRED'):api.request(ENTRY)
        self.assertEqual(api.engine.http.request.call_count,2)

    def test_post_redirect_never_rebinds_or_replays_write(self):
        api=self.api()
        with patch.object(urllib.request.OpenerDirector,'open',lambda opener,req,timeout:self.redirect(opener,req)):
            with self.assertRaisesRegex(Stop,'HTTP_REDIRECT_STOPPED'):api.request(PRECHECK,{'name':'fixture'})
        api.engine.http.request.assert_not_called()

    def test_untrusted_redirect_is_not_treated_as_login(self):
        api=self.api()
        def opened(opener,req,timeout):
            handler=next(x for x in opener.handlers if isinstance(x,urllib.request.HTTPRedirectHandler))
            return handler.redirect_request(req,None,302,'',{},'http://example.invalid/')
        with patch.object(urllib.request.OpenerDirector,'open',opened):
            with self.assertRaisesRegex(Stop,'HTTP_REDIRECT_STOPPED'):api.request(ENTRY)
        api.engine.http.request.assert_not_called()

    def test_portal_permission_or_structure_change_is_not_login_expiry(self):
        api=self.api('<html>permission missing</html>')
        with patch.object(urllib.request.OpenerDirector,'open',lambda opener,req,timeout:self.redirect(opener,req)):
            with self.assertRaisesRegex(Stop,'AD_PORTAL_ENTRY_UNVERIFIED'):api.request(ENTRY)
        self.assertEqual(api.engine.state['status'],'ready')
    def test_read_throttle_retains_seconds_and_http_date_without_retry(self):
        from upload_api import ReadBackoff
        for status,header,seconds in [(429,'90',90),(503,formatdate(1120,usegmt=True),120),(503,None,None)]:
            with self.subTest(status=status,header=header):
                api=self.api();error=urllib.error.HTTPError(ENTRY,status,'fixture',{'Retry-After':header} if header else {},None)
                with patch.object(urllib.request.OpenerDirector,'open',side_effect=error) as opened,patch('upload_api.time.time',return_value=1000):
                    with self.assertRaises(ReadBackoff) as result:api.request(ENTRY)
                self.assertEqual(result.exception.status_code,status);self.assertEqual(result.exception.retry_after_seconds,seconds)
                self.assertEqual(opened.call_count,1);api.engine.http.request.assert_not_called()
    def test_write_throttle_is_still_unknown_acceptance_without_retry(self):
        api=self.api();error=urllib.error.HTTPError(PRECHECK,429,'fixture',{'Retry-After':'2'},None)
        with patch.object(urllib.request.OpenerDirector,'open',side_effect=error) as opened:
            with self.assertRaisesRegex(Stop,'ACCEPTANCE_UNKNOWN'):api.request(PRECHECK,{'name':'fixture'})
        self.assertEqual(opened.call_count,1);api.engine.http.request.assert_not_called()
    def test_probe_redirect_stops_without_rebind_or_auth_state_mutation(self):
        api=self.api();before=dict(api.engine.state)
        with patch.object(urllib.request.OpenerDirector,'open',lambda opener,req,timeout:self.redirect(opener,req)):
            with self.assertRaisesRegex(Stop,'LOGIN_EXPIRED'):api.request(ENTRY,_rebind=False,_timeout=10,_probe=True)
        api.engine.http.request.assert_not_called();self.assertEqual(api.engine.state,before)


if __name__=='__main__':unittest.main()


class UploadIdleSessionTests(unittest.TestCase):
    def api(self,checked=0,status='ready'):
        engine=SimpleNamespace(state={'status':status,'last_protected_read_at':checked,'last_portal_session_read_at':checked})
        return SimpleNamespace(engine=engine,fields=Mock(),bind_ad=Mock())

    def test_idle_status_refreshes_protected_read_and_rotated_cookie(self):
        from upload_service import refresh_session
        api=self.api()
        with patch('session_store.remember') as remember:
            refresh_session(api,now=1000)
        api.fields.assert_called_once_with();remember.assert_called_once_with(api.engine,'upload')

    def test_fresh_session_does_not_add_network_read(self):
        from upload_service import refresh_session
        api=self.api(checked=950)
        with patch('session_store.remember') as remember:refresh_session(api,now=1000)
        api.fields.assert_not_called();remember.assert_not_called()

    def test_network_failure_does_not_save_or_retry(self):
        from upload_service import refresh_session
        api=self.api();api.fields.side_effect=Stop('HTTP_READ_FAILED')
        with patch('session_store.remember') as remember:
            with self.assertRaisesRegex(Stop,'HTTP_READ_FAILED'):refresh_session(api,now=1000)
        api.fields.assert_called_once_with();remember.assert_not_called()

    def test_known_login_required_never_sends_password_or_code(self):
        from upload_service import refresh_session
        api=self.api(status='login_required')
        with self.assertRaisesRegex(ValueError,'UPLOAD_HTTP_LOGIN_REQUIRED'):refresh_session(api,now=1000)
        api.fields.assert_not_called()

    def test_clock_moved_back_requires_actual_read(self):
        from upload_service import refresh_session
        api=self.api(checked=1100)
        with patch('session_store.remember'):refresh_session(api,now=1000)
        api.fields.assert_called_once_with()


class PortalIdleRecoveryTests(unittest.TestCase):
    def test_idle_refresh_verifies_portal_before_upload_form(self):
        from upload_service import refresh_session
        api=Mock();api.engine.state={'status':'ready','last_protected_read_at':0}
        with patch('session_store.remember'):refresh_session(api,now=1000)
        self.assertEqual(api.method_calls,[unittest.mock.call.bind_ad(),unittest.mock.call.fields()])


class PortalIndependentTimerTests(unittest.TestCase):
    def test_busy_ad_reads_do_not_starve_portal_renewal(self):
        from upload_service import refresh_session
        api=Mock();api.engine.state={'status':'ready','last_protected_read_at':999,'last_portal_session_read_at':0}
        with patch('session_store.remember'):refresh_session(api,now=1000)
        api.bind_ad.assert_called_once_with();api.fields.assert_called_once_with()
        self.assertEqual(api.engine.state['last_portal_session_read_at'],1000)
