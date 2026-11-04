"""Offline request planning and result-preservation regressions."""
import datetime as dt
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import material_performance as performance

NOW = dt.datetime(2026, 9, 3, 4, tzinfo=dt.timezone.utc)


class CaptureHabitsTests(unittest.TestCase):
    def args(self, *options):
        return performance.build_parser().parse_args(["run", *options])

    def plan(self, *options, now=NOW):
        with patch.dict("os.environ", {"RONGYAO_MATERIAL_START": ""}):
            return performance.plan_capture(self.args(*options), now=now)

    def test_this_week_is_calendar_week_not_rolling_week(self):
        plan = self.plan("--period", "this-week")
        self.assertEqual(plan["date_range"], "2026/08/31-2026/09/03")
        self.assertEqual(plan["new_material_range"], plan["date_range"])
        self.assertEqual(plan["planned_query_count"], 1)
        self.assertTrue(plan["maturity"]["includes_recent_days"])

    def test_timezone_is_shanghai_across_utc_midnight(self):
        now = dt.datetime(2026, 9, 6, 18, tzinfo=dt.timezone.utc)
        self.assertEqual(self.plan("--period", "this-week", now=now)["date_range"], "2026/09/07-2026/09/07")

    def test_year_boundary(self):
        now = dt.datetime(2026, 1, 1, 4, tzinfo=dt.timezone.utc)
        self.assertEqual(self.plan("--period", "this-week", now=now)["date_range"], "2025/12/29-2026/01/01")

    def test_last_week_is_complete_calendar_week(self):
        self.assertEqual(self.plan("--period", "last-week")["date_range"], "2026/08/24-2026/08/30")

    def test_recent_keeps_lag_without_automatic_comparison(self):
        plan = self.plan("--recent-days", "7")
        self.assertEqual(plan["date_range"], "2026/08/26-2026/09/01")
        self.assertIsNone(plan["compare_range"])
        self.assertFalse(plan["maturity"]["includes_recent_days"])

    def test_explicit_comparison_is_equal_and_adjacent(self):
        plan = self.plan("--period", "this-week", "--compare")
        self.assertEqual(plan["compare_range"], "2026/08/27-2026/08/30")
        self.assertEqual(plan["planned_query_count"], 2)

    def test_legacy_material_window_is_disclosed_not_full_history(self):
        plan = self.plan("--period", "this-week")
        self.assertEqual(plan["material_range"], "2023/01/01-2026/09/03")
        self.assertEqual(plan["material_range_source"], "legacy_default_unverified")
        self.assertFalse(plan["history_complete"])

    def test_explicit_material_start(self):
        plan = self.plan("--material-start", "2025-02-01")
        self.assertEqual(plan["material_range"], "2025/02/01-2026/09/03")
        self.assertEqual(plan["material_range_source"], "explicit_start")

    def test_local_config_and_explicit_range_precedence(self):
        with patch.dict("os.environ", {"RONGYAO_MATERIAL_START": "2024/01/01"}):
            plan = performance.plan_capture(self.args(), NOW)
            self.assertEqual(plan["material_range_source"], "local_environment")
            plan = performance.plan_capture(self.args("--material-range", "2020-01-01-2020-02-01"), NOW)
            self.assertEqual(plan["material_range"], "2020/01/01-2020/02/01")
            self.assertEqual(plan["material_range_source"], "explicit_range")

    def test_new_material_narrow_window_is_visible(self):
        plan = self.plan("--period", "this-week", "--material-range", "2026/09/01-2026/09/02")
        self.assertFalse(plan["new_material_window_covered"])

    def test_invalid_inputs_stop_before_capture_or_output_creation(self):
        cases = [
            ["--new-start", "2026/08/31"],
            ["--new-start", "2026/09/02", "--new-end", "2026/09/01"],
            ["--spend-threshold", "nan"], ["--roi1-threshold", "0"],
            ["--two-day-threshold", "inf"], ["--gid", "0"],
            ["--recent-days", "0"], ["--lag-days", "-1"],
            ["--compare", "--no-auto-compare"],
            ["--date-range", "2026/09/01-2026/09/02", "--period", "this-week"],
            ["--date-range", "2026/09/01-2026/09/02", "--lag-days", "2"],
            ["--period", "last-week", "--lag-days", "2"],
            ["--material-range", "2026/02/31-2026/03/01"],
        ]
        for options in cases:
            with self.subTest(options=options), patch.object(performance, "capture_one") as capture, patch.object(performance, "output_dir") as output:
                with self.assertRaises(ValueError):
                    performance.run_capture(self.args(*options))
                capture.assert_not_called()
                output.assert_not_called()

    def test_monday_with_lag_does_not_silently_change_week(self):
        now = dt.datetime(2026, 9, 7, 4, tzinfo=dt.timezone.utc)
        with self.assertRaises(ValueError):
            self.plan("--period", "this-week", "--lag-days", "2", now=now)

    def test_future_and_nonadjacent_comparisons_rejected(self):
        for options in (["--date-range", "2026/09/01-2026/09/04"],
                        ["--period", "this-week", "--compare-range", "2026/08/01-2026/08/04"],
                        ["--material-range", "2026/01/01-2026/10/01"]):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.plan(*options)

    def test_dry_run_does_not_access_backend_files_or_state(self):
        with patch.object(performance, "capture_one") as capture, patch.object(performance, "output_dir") as output, patch.object(performance, "write_state") as state, redirect_stdout(StringIO()) as stream:
            self.assertEqual(performance.run_capture(self.args("--period", "this-week", "--dry-run")), 0)
            result = json.loads(stream.getvalue())
            self.assertEqual(result["query_count"], 0)
            capture.assert_not_called()
            output.assert_not_called()
            state.assert_not_called()

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "current.csv"
            original.write_text("previous successful result", encoding="utf-8")
            with self.assertRaises(ValueError):
                performance.output_dir(directory)
            self.assertEqual(original.read_text(encoding="utf-8"), "previous successful result")

    def test_default_outputs_are_unique_and_portable(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(tempfile, "tempdir", directory):
            first, second = performance.output_dir(None), performance.output_dir(None)
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(directory))

    def test_null_spend_sorts_last_without_becoming_zero(self):
        result = performance.compact_groups({"missing": {"spend": None}, "zero": {"spend": 0}, "valid": {"spend": 5}})
        self.assertEqual(list(result), ["valid", "zero", "missing"])
        self.assertIsNone(result["missing"]["spend"])

    def test_all_direction_groups_can_be_kept(self):
        groups = {str(i): {"spend": i} for i in range(20)}
        self.assertEqual(len(performance.compact_groups(groups, limit=None)), 20)


if __name__ == "__main__":
    unittest.main()
