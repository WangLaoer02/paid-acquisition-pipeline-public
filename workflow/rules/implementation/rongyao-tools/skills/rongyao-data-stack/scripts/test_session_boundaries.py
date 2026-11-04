"""Offline session detection must not claim login or silently switch channels."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import active_session_cli as session
import preflight


class SessionBoundaryTests(unittest.TestCase):
    def test_export_disconnected_or_unknown_never_falls_back(self):
        args = session.build_parser().parse_args(["backend-export", "--date-range", "2020/01/01-2020/01/01"])
        for reason in ("devtools_unreachable", "status_unavailable", None):
            with self.subTest(reason=reason), patch.object(session, "session_status", return_value={"active": False, "reason": reason}), patch.object(session, "fallback_backend_export") as fallback:
                with self.assertRaises(RuntimeError):
                    session.run_export(args)
                fallback.assert_not_called()

    def test_only_absent_session_permits_legacy_fallback(self):
        args = session.build_parser().parse_args([
            "backend-export", "--date-range", "2020/01/01-2020/01/01", "--no-auto-recover"
        ])
        with patch.object(session, "session_status", return_value={"active": False, "reason": "state_missing"}), patch.object(session, "fallback_backend_export", return_value=0) as fallback:
            self.assertEqual(session.run_export(args), 0)
            fallback.assert_called_once()

    def test_default_ensure_restarts_same_profile_after_process_exit(self):
        state = Path("/tmp/rongyao-state.json")
        profile = Path("/tmp/rongyao-profile")
        with patch.object(session, "session_status", return_value={"active": False, "reason": "process_missing"}), patch.object(
            session, "open_session", return_value={"active": True, "profileDir": str(profile)}
        ) as opened:
            result = session.ensure_active_session(state, profile)
        opened.assert_called_once_with(state, profile)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["recoveredFrom"], "process_missing")

    def test_background_capture_never_opens_browser_but_reuses_active_session(self):
        with patch.dict(session.os.environ, {"RONGYAO_CAPTURE_BACKGROUND": "1"}), patch.object(session, "open_session") as opened:
            for reason in ("state_missing", "process_missing"):
                with patch.object(session, "session_status", return_value={"active": False, "reason": reason}):
                    with self.assertRaisesRegex(RuntimeError, "AUTH_REQUIRED"):
                        session.ensure_active_session(Path("state"), Path("profile"))
            with patch.object(session, "session_status", return_value={"active": True}):
                self.assertTrue(session.ensure_active_session(Path("state"), Path("profile"))["active"])
            opened.assert_not_called()

    def test_explicit_login_can_open_when_background_setting_is_inherited(self):
        args = session.build_parser().parse_args(["backend-login"])
        def confirm_background_removed(*_args):
            self.assertNotIn("RONGYAO_CAPTURE_BACKGROUND", session.os.environ)
            return {"active": True}
        with patch.dict(session.os.environ, {"RONGYAO_CAPTURE_BACKGROUND": "1"}), patch.object(
            session, "ensure_active_session", side_effect=confirm_background_removed
        ) as ensured, patch.object(session, "run_node", return_value={"ok": True}) as node, patch("builtins.print"):
            self.assertEqual(session.run_login(args), 0)
            ensured.assert_called_once()
            node.assert_called_once()
            self.assertEqual(session.os.environ.get("RONGYAO_CAPTURE_BACKGROUND"), "1")

    def test_ensure_never_duplicates_uncertain_live_process(self):
        with patch.object(session, "session_status", return_value={"active": False, "reason": "devtools_unreachable"}), patch.object(
            session, "open_session"
        ) as opened:
            with self.assertRaises(RuntimeError):
                session.ensure_active_session(Path("state"), Path("profile"))
        opened.assert_not_called()

    def test_require_active_stops_when_absent(self):
        args = session.build_parser().parse_args(["backend-export", "--date-range", "2020/01/01-2020/01/01", "--require-active"])
        with patch.object(session, "session_status", return_value={"active": False, "reason": "state_missing"}), patch.object(session, "fallback_backend_export") as fallback:
            with self.assertRaises(SystemExit):
                session.run_export(args)
            fallback.assert_not_called()

    def test_status_reads_payload_not_just_success_exit(self):
        helper = Path(session.__file__)
        result = subprocess.CompletedProcess([], 0, json.dumps({"active": False, "reason": "state_missing"}), "")
        with patch.object(preflight.subprocess, "run", return_value=result):
            self.assertFalse(preflight.active_session_ready(helper))

    def test_malformed_status_is_unknown(self):
        helper = Path(session.__file__)
        for raw in ("invalid", "{}", "[]", '{"active":"true"}'):
            result = subprocess.CompletedProcess([], 0, raw, "")
            with self.subTest(raw=raw), patch.object(preflight.subprocess, "run", return_value=result):
                self.assertEqual(preflight.active_session_status(helper)["reason"], "status_unavailable")

    def test_preflight_default_never_reads_disk_cookies(self):
        root = Path(__file__).resolve().parents[2]
        with patch.object(preflight, "active_session_status", return_value={"active": True}), patch.object(preflight, "chrome_cookie_encryption") as cookies, patch.object(preflight, "python_launcher_status", return_value={"launchers": []}):
            result = preflight.inspect_stack(root, "", "Default", "")
            cookies.assert_not_called()
            self.assertTrue(result["capabilities"]["capture_environment_ready"])
            self.assertFalse(result["login"]["authenticated_session_verified"])
            self.assertFalse(result["login"]["disk_cookie_checked"])

    def test_unchecked_cookie_source_cannot_be_ready(self):
        self.assertFalse(preflight.bundled_helper_login_ready("Darwin", "not_checked", "cryptography", False))

    def test_dead_session_blocks_even_if_disk_candidate_exists(self):
        root = Path(__file__).resolve().parents[2]
        with patch.object(preflight, "active_session_status", return_value={"active": False, "reason": "devtools_unreachable"}), patch.object(preflight, "cookie_file_permissions_ok", return_value=True), patch.object(preflight, "python_launcher_status", return_value={"launchers": []}):
            result = preflight.inspect_stack(root, "", "Default", "")
            self.assertFalse(result["capabilities"]["capture_environment_ready"])


if __name__ == "__main__":
    unittest.main()
