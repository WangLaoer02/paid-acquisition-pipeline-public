#!/usr/bin/env python3
"""Regression tests for total-row handling and previous-period role analysis."""

from __future__ import annotations

import csv
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from material_performance import (
    analyze_dataset,
    build_parser,
    canonical_role_name,
    capture_one_cached,
    machine_summary,
    resolve_weekly_report_cli,
    run_compare_role,
    run_capture,
    validate_capture_identity,
)


HEADERS = [
    "日期",
    "素材",
    "一类",
    "二类",
    "角色",
    "产出日期",
    "花费",
    "新付费数",
    "roi1",
    "roi2",
    "2日倍率",
]


def write_fixture(path: Path, total_spend: int, material_spend: int, roi1: str, roi2: str) -> None:
    rows = [
        {
            "日期": "总计",
            "素材": "",
            "花费": str(total_spend),
            "新付费数": "2",
            "roi1": roi1,
            "roi2": roi2,
        },
        {
            "日期": "2020",
            "素材": "测试宇智波鼬攻略",
            "一类": "口播",
            "二类": "攻略",
            "角色": "宇智波鼬",
            "产出日期": "2026-07-20",
            "花费": str(material_spend),
            "新付费数": "2",
            "roi1": roi1,
            "roi2": roi2,
            "2日倍率": "2",
        },
    ]
    with path.open("w", encoding="gb18030", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


class MaterialPerformanceRegressionTest(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory(prefix="rongyao-test-state-")
        self.addCleanup(self.runtime.cleanup)
        state = patch("material_performance.STATE_PATH", Path(self.runtime.name) / "status.json")
        state.start()
        self.addCleanup(state.stop)

    def test_kai_role_is_normalized(self) -> None:
        self.assertEqual(canonical_role_name("死门凯"), "凯")

    def test_weekly_report_cli_path_resolution_precedence(self) -> None:
        fake_home = Path("/tmp/test-home")
        environment = {"RONGYAO_WEEKLY_REPORT_CLI": "/opt/shared/env-helper.py"}
        bundled = Path("/opt/shared/bundled-helper.py")
        active = Path("/opt/shared/active-helper.py")

        self.assertEqual(
            resolve_weekly_report_cli("/opt/explicit/helper.py", environment, fake_home, bundled, active),
            Path("/opt/explicit/helper.py"),
        )
        self.assertEqual(
            resolve_weekly_report_cli(None, environment, fake_home, bundled, active),
            Path("/opt/shared/env-helper.py"),
        )
        self.assertEqual(
            resolve_weekly_report_cli(None, {}, fake_home, bundled, active),
            bundled,
        )

        with tempfile.TemporaryDirectory() as directory:
            active_file = Path(directory) / "active_session_cli.py"
            active_file.write_text("# helper\n", encoding="utf-8")
            self.assertEqual(
                resolve_weekly_report_cli(None, {}, fake_home, bundled, active_file),
                active_file,
            )

    def test_total_row_is_not_double_counted_and_previous_roles_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current.csv"
            previous = root / "previous.csv"
            write_fixture(current, 1000, 990, "10%", "20%")
            write_fixture(previous, 500, 495, "8%", "16%")

            result = analyze_dataset(current, previous, [], None, None, 500, 9, 1.9)

            self.assertEqual(result["current"]["overall"]["spend"], 1000)
            self.assertEqual(result["current"]["roles"]["鼬"]["spend"], 990)
            self.assertEqual(result["previous"]["roles"]["鼬"]["spend"], 495)
            self.assertIn("roi1_change_pp", result["comparison"]["roles"]["鼬"])
            self.assertEqual(result["data_quality"]["current"]["detail_total_spend_difference"], -10)

    def test_machine_summary_uses_fixed_fields_without_material_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current.csv"
            write_fixture(current, 1000, 990, "10%", "20%")
            result = analyze_dataset(current, None, [], None, None, 500, 9, 1.9)
            summary = machine_summary(result, {"gid": 193}, [str(Path(directory) / "analysis.json")])

            serialized = json.dumps(summary, ensure_ascii=False)
            self.assertEqual(summary["overall"]["spend"], 1000)
            self.assertIn("鼬", summary["roles"])
            self.assertNotIn("representative_materials", serialized)
            self.assertNotIn("测试宇智波鼬攻略", serialized)
            self.assertNotIn("素材地址", serialized)

    def test_machine_summary_keeps_query_and_grouped_row_counts_at_separate_grains(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current.csv"
            write_fixture(current, 1000, 990, "10%", "20%")
            result = analyze_dataset(current, None, [], None, None, 500, 9, 1.9)
            result["capture"] = {
                "current": {
                    "validation": {
                        "ok": True,
                        "group": "mid",
                        "query_count": 1255,
                        "query_totalpage": 63,
                        "query_pagesize": 20,
                    }
                }
            }

            summary = machine_summary(result, {"gid": 193}, [])

            validation = summary["capture_validation"]
            self.assertEqual(validation["query_count"], 1255)
            self.assertEqual(validation["exported_detail_rows"], 1)
            self.assertEqual(validation["query_count_scope"], "underlying_records")
            self.assertEqual(validation["exported_rows_scope"], "grouped_materials")

    def test_capture_identity_rejects_wrong_project_or_date(self) -> None:
        payload = {
            "filters": {
                "entry": "新素材2.0",
                "gid": "193",
                "game": "忍界大战",
                "dateRange": "2026/08/02-2026/08/07",
                "materialRange": "2023/01/01-2026/08/05",
                "dateGroup": "tenyear",
                "group": "mid",
                "sourceVideoType": "视频",
                "recordType": "新注册",
                "filter": "是",
            }
        }
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            validate_capture_identity(
                payload, "2026/08/01-2026/08/07", "2023/01/01-2026/08/05", 193
            )

    def test_capture_identity_requires_new_registration_dimension(self) -> None:
        payload = {
            "filters": {
                "entry": "新素材2.0", "gid": "193", "game": "忍界大战",
                "dateRange": "2026/08/01-2026/08/07",
                "materialRange": "2023/01/01-2026/08/05",
                "dateGroup": "tenyear", "group": "mid",
                "sourceVideoType": "视频", "recordType": "活跃", "filter": "是",
            }
        }
        with self.assertRaisesRegex(RuntimeError, "recordType"):
            validate_capture_identity(
                payload, "2026/08/01-2026/08/07", "2023/01/01-2026/08/05", 193
            )

    def test_explicit_no_compare_run_calls_backend_once_and_prints_small_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            args = build_parser().parse_args(
                [
                    "run",
                    "--date-range",
                    "2026/08/01-2026/08/07",
                    "--material-range",
                    "2023/01/01-2026/08/05",
                    "--gid",
                    "193",
                    "--no-auto-compare",
                    "--cache",
                    "off",
                    "--new-start",
                    "2026/08/01",
                    "--new-end",
                    "2026/08/05",
                    "--output-dir",
                    str(destination),
                ]
            )

            def fake_capture(*capture_args, **capture_kwargs):
                output = capture_args[4]
                write_fixture(output, 1000, 990, "10%", "20%")
                return {
                    "ok": True,
                    "validation": {
                        "ok": True,
                        "game": "忍界大战",
                        "gid": "193",
                        "date_range": "2026/08/01-2026/08/07",
                        "material_range": "2023/01/01-2026/08/05",
                        "date_group": "tenyear",
                        "group": "mid",
                        "source_video_type": "视频",
                        "filter": "是",
                        "query_count": 1,
                    },
                }

            output = StringIO()
            with patch("material_performance.capture_one", side_effect=fake_capture) as capture:
                with redirect_stdout(output):
                    self.assertEqual(run_capture(args), 0)

            self.assertEqual(capture.call_count, 1)
            self.assertTrue((destination / "summary.json").exists())
            self.assertIn('"analysis_path"', output.getvalue())
            self.assertNotIn("representative_materials", output.getvalue())

    def test_shared_helper_prefers_installed_http_but_preserves_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            http = home / ".codex/skills/rongyao-http-readonly/scripts/market_export_cli.py"
            http.parent.mkdir(parents=True)
            http.touch()
            active = home / "active.py"
            active.touch()
            self.assertEqual(resolve_weekly_report_cli(None, {}, home, active=active), http)
            self.assertEqual(resolve_weekly_report_cli(str(active), {}, home, active=active), active)

    def test_export_then_analysis_reuses_one_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = ["--date-range", "2026/08/01-2026/08/07",
                      "--material-range", "2023/01/01-2026/08/07",
                      "--gid", "193", "--cache-dir", str(root / "cache")]

            def fake_capture(*capture_args, **capture_kwargs):
                write_fixture(capture_args[4], 1000, 990, "10%", "20%")
                return {"ok": True, "filters": {
                    "entry": "新素材2.0", "game": "忍界大战", "gid": "193",
                    "dateRange": common[1], "materialRange": common[3],
                    "dateGroup": "tenyear", "group": "mid",
                    "sourceVideoType": "视频", "recordType": "新注册", "filter": "是"},
                    "validation": {"ok": True}}

            with patch("material_performance.capture_one", side_effect=fake_capture) as capture:
                export_args = build_parser().parse_args(
                    ["export", *common, "--output-dir", str(root / "export")])
                with patch("material_performance.analyze_dataset") as analyze, redirect_stdout(StringIO()):
                    self.assertEqual(run_capture(export_args), 0)
                    analyze.assert_not_called()
                receipt = json.loads((root / "export/export.json").read_text())
                self.assertEqual(receipt["mode"], "export")
                self.assertEqual(receipt["files"][0]["row_count"], 1)
                self.assertEqual(receipt["files"][0]["capture"]["cache"]["status"], "miss")
                self.assertFalse((root / "export/analysis.json").exists())
                # Even an old caller using run after export shares the exact cache.
                run_args = build_parser().parse_args(
                    ["run", *common, "--output-dir", str(root / "analysis")])
                with redirect_stdout(StringIO()):
                    self.assertEqual(run_capture(run_args), 0)
                self.assertEqual(capture.call_count, 1)
                self.assertEqual((root / "export/current.csv").read_bytes(),
                                 (root / "analysis/current.csv").read_bytes())
                self.assertTrue((root / "analysis/summary.json").is_file())

    def test_export_plan_has_no_backend_or_file_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "not-created"
            args = build_parser().parse_args([
                "export", "--period", "this-week", "--dry-run", "--output-dir", str(destination)])
            with patch("material_performance.capture_one_cached") as capture, \
                    patch("material_performance.write_state") as state, redirect_stdout(StringIO()):
                self.assertEqual(run_capture(args), 0)
                capture.assert_not_called()
                state.assert_not_called()
            self.assertFalse(destination.exists())
            with self.assertRaisesRegex(ValueError, "requires date-range or period"):
                run_capture(build_parser().parse_args(["export"]))

    def test_export_rejects_missing_columns_without_analysis_or_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = build_parser().parse_args([
                "export", "--period", "last-week", "--cache", "off", "--output-dir", str(root)])

            def fake_capture(*capture_args, **capture_kwargs):
                capture_args[4].write_text("素材,花费\n测试,1\n", encoding="utf-8")
                return {"ok": True, "validation": {"ok": True}}

            with patch("material_performance.capture_one", side_effect=fake_capture) as capture, \
                    patch("material_performance.analyze_dataset") as analyze, redirect_stdout(StringIO()):
                with self.assertRaisesRegex(RuntimeError, "missing required columns"):
                    run_capture(args)
                self.assertEqual(capture.call_count, 1)
                analyze.assert_not_called()
            self.assertFalse((root / "export.json").exists())

    def test_compare_role_reuses_current_and_captures_previous_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current.csv"
            current_summary = root / "current-summary.json"
            destination = root / "focus"
            write_fixture(current, 1000, 990, "10%", "20%")
            current_summary.write_text(
                json.dumps(
                    {
                        "contract": {
                            "date_range": "2026/08/22-2026/08/28",
                            "material_range": "2023/01/01-2026/08/30",
                            "gid": 193,
                        },
                        "data_quality": {
                            "rows": 1,
                            "columns": len(HEADERS),
                            "missing_required_columns": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = build_parser().parse_args(
                [
                    "compare-role",
                    "--role",
                    "鼬",
                    "--current",
                    str(current),
                    "--current-summary",
                    str(current_summary),
                    "--current-range",
                    "2026/08/22-2026/08/28",
                    "--compare-range",
                    "2026/08/15-2026/08/21",
                    "--material-range",
                    "2023/01/01-2026/08/30",
                    "--output-dir",
                    str(destination),
                    "--cache",
                    "off",
                ]
            )

            def fake_capture(*capture_args, **capture_kwargs):
                output = capture_args[4]
                write_fixture(output, 500, 495, "8%", "16%")
                return {
                    "ok": True,
                    "validation": {
                        "ok": True,
                        "gid": "193",
                        "date_range": "2026/08/15-2026/08/21",
                    },
                }

            output = StringIO()
            with patch("material_performance.capture_one", side_effect=fake_capture) as capture:
                with redirect_stdout(output):
                    self.assertEqual(run_compare_role(args), 0)

            self.assertEqual(capture.call_count, 1)
            result = json.loads((destination / "focus-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(result["current"]["spend"], 990)
            self.assertEqual(result["previous"]["spend"], 495)
            self.assertEqual(result["change"]["spend_change_pct"], 100.0)

    def test_exact_capture_cache_reuses_csv_without_second_backend_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "cache"
            first = root / "first.csv"
            second = root / "second.csv"

            def fake_capture(*capture_args, **capture_kwargs):
                output = capture_args[4]
                write_fixture(output, 1000, 990, "10%", "20%")
                return {
                    "ok": True,
                    "file": str(output),
                    "filters": {
                        "entry": "新素材2.0", "gid": "193", "game": "忍界大战",
                        "dateRange": "2026/08/01-2026/08/31",
                        "materialRange": "2023/01/01-2026/09/04",
                        "dateGroup": "tenyear", "group": "mid",
                        "sourceVideoType": "视频", "recordType": "新注册", "filter": "是",
                    },
                    "query": {"count": 1, "totalpage": 1, "pagesize": 20},
                }

            with patch("material_performance.capture_one", side_effect=fake_capture) as backend:
                first_result = capture_one_cached(
                    Path("/opt/backend_export_cli.py"),
                    "2026/08/01-2026/08/31", "2023/01/01-2026/09/04", 193,
                    first, None, None, None, None,
                    cache_mode="auto", cache_ttl_minutes=30, cache_dir=cache_dir,
                )
                second_result = capture_one_cached(
                    Path("/opt/backend_export_cli.py"),
                    "2026/08/01-2026/08/31", "2023/01/01-2026/09/04", 193,
                    second, None, None, None, None,
                    cache_mode="auto", cache_ttl_minutes=30, cache_dir=cache_dir,
                )

            self.assertEqual(backend.call_count, 1)
            self.assertEqual(first_result["cache"]["status"], "miss")
            self.assertEqual(second_result["cache"]["status"], "hit")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_compare_capture_uses_two_bounded_workers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "result"
            barrier = threading.Barrier(2)
            args = build_parser().parse_args(
                [
                    "run", "--date-range", "2026/08/01-2026/08/07",
                    "--compare", "--material-range", "2023/01/01-2026/09/04",
                    "--capture-workers", "2", "--cache", "off",
                    "--output-dir", str(destination),
                ]
            )

            def fake_capture(*capture_args, **capture_kwargs):
                output = capture_args[4]
                barrier.wait(timeout=2)
                write_fixture(output, 1000, 990, "10%", "20%")
                date_range = capture_args[1]
                return {
                    "ok": True,
                    "validation": {"ok": True, "gid": "193", "date_range": date_range},
                }

            with patch("material_performance.capture_one", side_effect=fake_capture) as backend:
                with redirect_stdout(StringIO()):
                    self.assertEqual(run_capture(args), 0)

            self.assertEqual(backend.call_count, 2)


if __name__ == "__main__":
    unittest.main()
