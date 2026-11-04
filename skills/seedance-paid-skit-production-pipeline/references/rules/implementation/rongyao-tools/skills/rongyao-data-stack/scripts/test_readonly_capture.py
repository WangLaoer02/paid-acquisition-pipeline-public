#!/usr/bin/env python3
"""Offline regression tests for the universal read-only capture transport."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import readonly_capture as capture


BASE_REQUEST = {
    "id": "sample",
    "date": "2026/08/01-2026/08/07",
    "date2": "2023/01/01-2026/08/05",
    "gid": ["193"],
}


class FakeContext:
    def __init__(self, *args, **kwargs):
        self.cache_hits = 1
        self.cache_misses = 2
        self.calls = 0
        self.base = {"date2": "2023/01/01-2026/08/05"}

    def prepare(self, request):
        search = dict(request["search"])
        search["category"] = ["133"]
        search["pkid"] = ["1"]
        return search

    def query_page(self, search, submit):
        self.calls += 1
        if search.get("page") == 2:
            return {"status": True, "info": {"rand": "session", "data": [{"row": 2}]}}
        return {
            "status": True,
            "info": {
                "rand": "session",
                "count": 2,
                "totalpage": 2,
                "pagesize": 1,
                "sum": {"cost": 123, "count": 7, "nested": {"drop": True}},
                "data": [{"row": 1}],
            },
        }


class FlakyContext(FakeContext):
    def query_page(self, search, submit):
        self.calls += 1
        if self.calls == 1:
            raise capture.CaptureError("HTTP 503")
        return super().query_page(search, submit)


class BrokenContext(FakeContext):
    def query_page(self, search, submit):
        raise capture.CaptureError("field missing")


class ReadonlyCaptureTest(unittest.TestCase):
    def test_filter_contract_and_identity_are_preserved(self):
        request = capture.normalized_request(
            {**BASE_REQUEST, "filters": {"role": ["凯"], "source_direction": ["攻略"]}}
        )
        self.assertEqual(request["search"]["role"], ["凯"])
        self.assertEqual(request["search"]["source_direction"], ["攻略"])
        self.assertEqual(request["search"]["record_type"], "3")

    def test_cli_maps_role_direction_category_label_and_keyword(self):
        args = capture.build_parser().parse_args(
            [
                "query", "--date-range", "2026/08/01-2026/08/07",
                "--material-range", "2023/01/01-2026/08/05", "--gid", "193",
                "--role", "凯", "--source-type", "攻略", "--source-direction", "原生录屏",
                "--category", "133", "--self-tag", "潜力素材", "--keyword", "ZX",
            ]
        )
        request = capture.query_request(args)
        self.assertEqual(request["filters"]["role"], ["凯"])
        self.assertEqual(request["filters"]["source_type"], ["攻略"])
        self.assertEqual(request["filters"]["source_direction"], ["原生录屏"])
        self.assertEqual(request["filters"]["category"], ["133"])
        self.assertEqual(request["filters"]["self_tag"], "潜力素材")
        self.assertEqual(request["filters"]["keyword"], "ZX")

    def test_unknown_filter_is_rejected(self):
        with self.assertRaisesRegex(capture.CaptureError, "不允许"):
            capture.normalized_request({**BASE_REQUEST, "filters": {"delete": "all"}})

    def test_high_cost_query_cannot_share_a_batch(self):
        heavy = {**BASE_REQUEST, "group": "material_serial_number", "all_pages": True}
        with self.assertRaisesRegex(capture.CaptureError, "必须单独运行"):
            capture.normalize_batch({"requests": [heavy, BASE_REQUEST]})

    def test_single_submit_rand_pagination(self):
        request = {**BASE_REQUEST, "group": "material_serial_number", "all_pages": True, "include": "rows"}
        with patch.object(capture, "DirectContext", FakeContext):
            payload = capture.direct_batch(
                capture.normalize_batch({"requests": [request]}),
                profile="Default", cookie_file="", cookie_env="", host="example",
                market_path="/marketng/", timeout=30, retries=2, concurrency=6,
            )
        item = payload["results"][0]
        self.assertTrue(item["ok"])
        self.assertEqual(item["rows"], [{"row": 1}, {"row": 2}])
        self.assertEqual(item["query"]["pages_completed"], 2)
        self.assertEqual(payload["concurrency"], 1)

    def test_light_query_does_not_replay_after_transient_failure(self):
        with patch.object(capture, "DirectContext", FlakyContext):
            payload = capture.direct_batch(
                capture.normalize_batch({"requests": [BASE_REQUEST]}),
                profile="Default", cookie_file="", cookie_env="", host="example",
                market_path="/marketng/", timeout=30, retries=2, concurrency=4,
            )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["results"][0]["attempts"], 1)

    def test_missing_data_is_never_coerced_to_zero(self):
        with patch.object(capture, "DirectContext", BrokenContext):
            payload = capture.direct_batch(
                capture.normalize_batch({"requests": [BASE_REQUEST]}),
                profile="Default", cookie_file="", cookie_env="", host="example",
                market_path="/marketng/", timeout=30, retries=2, concurrency=4,
            )
        item = payload["results"][0]
        self.assertFalse(item["ok"])
        self.assertIsNone(item["summary"])
        self.assertEqual(item["status"], "missing")

    def test_active_login_failure_is_controlled_and_actionable(self):
        class Module:
            @staticmethod
            def run_node(*args, **kwargs):
                raise RuntimeError("Error: LOGIN_REQUIRED\nstack")

        request = capture.normalize_batch({"requests": [BASE_REQUEST]})
        with patch.object(capture, "load_module", return_value=Module):
            with self.assertRaisesRegex(capture.CaptureError, "手动完成登录"):
                capture.active_batch(
                    request,
                    state_file=capture.DEFAULT_STATE,
                    market_path=capture.DEFAULT_MARKET_PATH,
                    timeout=30,
                    retries=0,
                    concurrency=1,
                )

    def test_auto_transport_recovers_profile_before_first_query(self):
        recovered = {"active": True, "recovered": True, "recoveredFrom": "process_missing"}
        result = {"ok": True, "transport": "active_chrome_page_context", "results": []}
        with patch.object(capture, "active_status", return_value={"active": False, "reason": "process_missing"}), patch.object(
            capture, "active_ensure", return_value=recovered
        ) as ensure, patch.object(capture, "active_batch", return_value=result) as active, patch.object(
            capture, "direct_batch"
        ) as direct:
            actual = capture.run_batch({"requests": [BASE_REQUEST]})
        self.assertEqual(actual, result)
        ensure.assert_called_once_with(capture.DEFAULT_STATE.resolve(), capture.DEFAULT_SESSION_PROFILE.resolve())
        active.assert_called_once()
        direct.assert_not_called()

    def test_auto_recover_can_be_explicitly_disabled_for_legacy_fallback(self):
        with patch.object(capture, "active_status", return_value={"active": False, "reason": "state_missing"}), patch.object(
            capture, "active_ensure"
        ) as ensure, patch.object(capture, "direct_batch", return_value={"ok": True}) as direct:
            capture.run_batch({"requests": [BASE_REQUEST]}, auto_recover=False)
        ensure.assert_not_called()
        direct.assert_called_once()


if __name__ == "__main__":
    unittest.main()
