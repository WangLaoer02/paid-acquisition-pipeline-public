#!/usr/bin/env python3
"""Offline regression tests for dashboard capture entrypoints."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


monthly = load("rongyao_monthly_capture_test", "capture_monthly_spend.py")
output = load("rongyao_material_output_test", "capture_material_output.py")
original = load("rongyao_original_capture_test", "capture_original_materials.py")


class FakeCapture:
    def __init__(self, results):
        self.results = results
        self.requests = None

    def run_batch(self, payload, **kwargs):
        self.requests = payload["requests"]
        return {
            "ok": all(item.get("ok") for item in self.results),
            "transport": "active_chrome_page_context",
            "results": self.results,
            "page_defaults": {"date2": "2023/01/01-2026/08/05"},
            "cache": {"scope": "single_run_metadata_only", "hits": 2, "misses": 3},
            "concurrency": kwargs.get("concurrency"),
            "elapsed_ms": 123.4,
        }


class DashboardCaptureTest(unittest.TestCase):
    def test_monthly_live_capture_always_calibrates_and_preserves_missing(self):
        fake = FakeCapture(
            [
                {"id": "2026-06", "ok": True, "summary": {"cost": 1200}},
                {"id": "2026-08", "ok": False, "status": "missing", "error": "timeout"},
            ]
        )
        args = argparse.Namespace(
            start_month="2026-08", end_month="2026-08", transport="auto", profile="Default",
            cookie_file="", cookie_env="", timeout=30, retries=0, workers=4, state_file="",
            material_range="2020/01/01-2020/12/31", control_month="2026-06", control_spend=1200,
        )
        with patch.object(monthly, "load_capture", return_value=fake):
            payload = monthly.build_live_payload(args)
        self.assertEqual([item["id"] for item in fake.requests], ["2026-06", "2026-08"])
        self.assertIsNone(payload["rows"][0]["spend"])
        self.assertEqual(payload["rows"][0]["status"], "missing")

    def test_monthly_calibration_mismatch_stops_batch(self):
        fake = FakeCapture([{"id": "2026-06", "ok": True, "summary": {"cost": 1}}])
        args = argparse.Namespace(
            start_month="2026-06", end_month="2026-06", transport="auto", profile="Default",
            cookie_file="", cookie_env="", timeout=30, retries=0, workers=4, state_file="",
            material_range="2020/01/01-2020/12/31", control_month="2026-06", control_spend=1200,
        )
        with patch.object(monthly, "load_capture", return_value=fake):
            with self.assertRaisesRegex(monthly.ContractError, "已停止整批"):
                monthly.build_live_payload(args)

    def test_material_output_multi_gid_request_uses_dynamic_dependencies(self):
        request = output.build_request("咒术", "2026-01", "2020/01/01-2020/12/31")
        self.assertEqual(request["gid"], ["197", "192"])
        self.assertTrue(request["expand_gid_dependencies"])
        self.assertEqual(request["filters"]["negative_keyword"], "")

    def test_material_output_missing_sum_is_not_zero(self):
        row = output.convert_result(
            {"ok": True, "summary": {}, "query": {"count": 5}}, "火影", "2026-01"
        )
        self.assertIsNone(row["material_output_count"])
        self.assertEqual(row["status"], "missing")

    def test_original_capture_consumes_complete_active_session_pages(self):
        fake = FakeCapture(
            [
                {
                    "id": "original-materials",
                    "ok": True,
                    "query": {"totalpage": 2, "pages_completed": 2},
                    "rows": [
                        {"material_serial_number": '<div data-serial="ZX"><li><a>260101ZX1-原创-A</a></li></div>'}
                    ],
                }
            ]
        )
        args = argparse.Namespace(
            start_date=original.dt.date(2026, 1, 1), end_date=original.dt.date(2026, 1, 31),
            project=["火影"], code=["ZX"], max_pages=20, max_rows=5000,
            transport="auto", profile="Default", cookie_file="", cookie_env="",
            timeout=30, state_file="", material_range="2020/01/01-2020/12/31",
        )
        with patch.object(original, "load_capture", return_value=fake):
            payload = original.run_capture(args)
        self.assertEqual(payload["matched_unique_count"], 1)
        self.assertEqual(payload["pages_completed"], 2)
        self.assertEqual(payload["transport"], "active_chrome_page_context")


if __name__ == "__main__":
    unittest.main()
