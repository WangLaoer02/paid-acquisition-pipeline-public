#!/usr/bin/env python3
"""Read-only 荣耀后台 material capture and deterministic performance analysis."""

from __future__ import annotations

import argparse
import concurrent.futures
from evidence_contract import number, rounded, difference, ratio, source_link, coverage
import csv
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")


SKILL_DIR = Path(__file__).resolve().parents[1]
RULES_PATH = SKILL_DIR / "references" / "normalization-rules.json"
WEEKLY_REPORT_CLI_ENV = "RONGYAO_WEEKLY_REPORT_CLI"
BUNDLED_BACKEND_CLI = SKILL_DIR.parent / "rongyao-data-stack" / "scripts" / "backend_export_cli.py"
ACTIVE_SESSION_CLI = SKILL_DIR.parent / "rongyao-data-stack" / "scripts" / "active_session_cli.py"
STATE_PATH = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "state" / "rongyao-material-performance" / "status.json"
CACHE_SCHEMA_VERSION = 1
CACHE_DIR = Path.home() / ".cache" / "codex" / "rongyao-material-performance"
DEFAULT_CACHE_TTL_MINUTES = 30
DEFAULT_CACHE_MAX_ENTRIES = 16
DEFAULT_BACKEND_HOST = "data.houtai.cn.sy.backend.example.invalid"
REQUIRED_COLUMNS = {
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
}
SUMMARY_OVERALL_FIELDS = (
    "material_count",
    "spend",
    "new_paid_count",
    "cost_per_new_paid",
    "roi1",
    "roi2",
    "two_day_multiplier",
    "observable_count",
    "roi1_pass_count",
    "roi1_pass_rate",
    "missing_metrics",
)


def resolve_weekly_report_cli(
    explicit: str | None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    bundled: Path | None = None,
    active: Path | None = None,
) -> Path:
    """Resolve explicit/env, installed HTTP, active-session, then legacy helpers."""
    env = os.environ if environ is None else environ
    if explicit and explicit.strip():
        return Path(explicit).expanduser()
    configured = (env.get(WEEKLY_REPORT_CLI_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    home_dir = Path.home() if home is None else home
    project_helper = home_dir / "Documents" / "荣耀统计后台" / "scripts" / "weekly_report_cli.py"
    active_helper = ACTIVE_SESSION_CLI if active is None else active
    bundled_helper = BUNDLED_BACKEND_CLI if bundled is None else bundled
    http_helper = home_dir / '.codex/skills/rongyao-http-readonly/scripts/market_export_cli.py'
    if http_helper.is_file():
        return http_helper
    if active_helper.is_file():
        return active_helper
    if project_helper.is_file():
        return project_helper
    return bundled_helper


parse_number = number


def parse_date(value: str) -> dt.date:
    value = value.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"invalid date: {value}")


def parse_optional_date(value: str) -> dt.date | None:
    value = (value or "").strip()[:10]
    if not value:
        return None
    try:
        return parse_date(value)
    except ValueError:
        return None


def parse_range(value: str) -> tuple[dt.date, dt.date]:
    parts = value.strip().split("-")
    if len(parts) == 6 and "/" not in value:
        left = "-".join(parts[:3])
        right = "-".join(parts[3:])
    else:
        left, sep, right = value.partition("-")
        if not sep:
            raise ValueError(f"invalid date range: {value}")
    start, end = parse_date(left), parse_date(right)
    if start > end:
        raise ValueError(f"range start is after end: {value}")
    return start, end


def range_text(start: dt.date, end: dt.date) -> str:
    return f"{start:%Y/%m/%d}-{end:%Y/%m/%d}"


def previous_equal_range(start: dt.date, end: dt.date) -> tuple[dt.date, dt.date]:
    days = (end - start).days + 1
    previous_end = start - dt.timedelta(days=1)
    return previous_end - dt.timedelta(days=days - 1), previous_end


def plan_capture(args: argparse.Namespace, now: dt.datetime | None = None) -> dict[str, Any]:
    """Resolve and validate the entire request before any filesystem or backend work."""
    timezone = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
    today = (now or dt.datetime.now(timezone)).astimezone(timezone).date()
    period = args.period or "recent"
    lag = args.lag_days if args.lag_days is not None else (2 if period == "recent" else 0)
    if lag < 0 or args.recent_days < 1 or args.gid < 1:
        raise ValueError("lag-days must be nonnegative; recent-days and gid must be positive")
    for key in ("spend_threshold", "roi1_threshold", "two_day_threshold"):
        value = getattr(args, key)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be finite and positive")
    if args.cache_ttl_minutes < 0:
        raise ValueError("cache-ttl-minutes must be nonnegative")
    if args.capture_workers not in (1, 2):
        raise ValueError("capture-workers must be 1 or 2")
    if args.date_range:
        if args.period or args.lag_days is not None:
            raise ValueError("explicit date-range cannot be combined with period or lag-days")
        start, end = parse_range(args.date_range)
        period = "explicit"
    elif period == "this-week":
        start = today - dt.timedelta(days=today.weekday())
        end = today - dt.timedelta(days=lag)
    elif period == "last-week":
        if lag:
            raise ValueError("last-week is a complete calendar week; lag-days must be 0")
        end = today - dt.timedelta(days=today.weekday() + 1)
        start = end - dt.timedelta(days=6)
    else:
        end = today - dt.timedelta(days=lag)
        start = end - dt.timedelta(days=args.recent_days - 1)
    if start > end:
        raise ValueError("no days remain in the requested week after lag-days; do not substitute last week")
    if end > today:
        raise ValueError("requested period includes future dates")
    if args.no_auto_compare and (args.compare or args.compare_range):
        raise ValueError("no-auto-compare conflicts with an explicit comparison")
    compare = parse_range(args.compare_range) if args.compare_range else (
        previous_equal_range(start, end) if args.compare else None
    )
    if compare and compare != previous_equal_range(start, end):
        raise ValueError("compare range must be equal-length and immediately precede current range")
    if args.material_range:
        material_start, material_end = parse_range(args.material_range)
        material_source = "explicit_range"
    else:
        configured_start = args.material_start or os.environ.get("RONGYAO_MATERIAL_START", "").strip()
        material_start = parse_date(configured_start or "2023/01/01")
        material_end = today
        material_source = "explicit_start" if args.material_start else (
            "local_environment" if configured_start else "legacy_default_unverified"
        )
    if material_start > material_end or material_end > today:
        raise ValueError("invalid material range: reversed or future dates")
    if bool(args.new_start) != bool(args.new_end):
        raise ValueError("new-start and new-end must be provided together")
    new_start = parse_date(args.new_start) if args.new_start else start
    new_end = parse_date(args.new_end) if args.new_end else end
    if new_start > new_end or new_end > today:
        raise ValueError("invalid new material range")
    # An explicitly narrower date2 window is allowed, but does not cover the whole new cohort.
    new_covered = material_start <= new_start <= new_end <= material_end
    mature_through = today - dt.timedelta(days=2)
    return {
        "source": "荣耀后台新素材2.0已登录直接接口",
        "timezone": "Asia/Shanghai", "as_of_date": today.isoformat(), "period": period,
        "date_range": range_text(start, end),
        "compare_range": range_text(*compare) if compare else None,
        "material_range": range_text(material_start, material_end),
        "material_range_source": material_source,
        "history_complete": False,
        "new_material_range": range_text(new_start, new_end),
        "new_material_window_covered": new_covered,
        "maturity": {
            "conservative_cutoff": mature_through.isoformat(),
            "includes_recent_days": end > mature_through,
            "basis": "two_day_lag_heuristic_not_backend_verification",
        },
        "gid": args.gid, "date_group": "tenyear", "group": "mid",
        "planned_query_count": 2 if compare else 1, "automatic_retries": 0,
        "capture_strategy": "parallel_periods" if compare and args.capture_workers == 2 else "serial",
        "capture_workers": args.capture_workers,
        "cache_mode": args.cache,
        "cache_ttl_minutes": args.cache_ttl_minutes,
    }


def load_rules() -> dict[str, Any]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str, dict[str, str] | None]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                all_rows = [dict(row) for row in reader]
                total_row = next(
                    (row for row in all_rows if (row.get("日期") or "").strip() == "总计"), None
                )
                rows = [
                    row
                    for row in all_rows
                    if (row.get("日期") or "").strip() != "总计" and (row.get("素材") or "").strip()
                ]
                return rows, list(reader.fieldnames or []), encoding, total_row
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"cannot decode CSV {path}: {last_error}")


def match_aliases(text: str, mapping: dict[str, list[str]]) -> list[str]:
    return [name for name, aliases in mapping.items() if any(alias in text for alias in aliases)]


def resolve_roles(row: dict[str, str], rules: dict[str, Any]) -> tuple[list[str], dict[str, Any] | None]:
    tag = (row.get("角色") or "").strip()
    material = row.get("素材") or ""
    tag_roles = match_aliases(tag, rules["roles"])
    name_roles = match_aliases(material, rules["roles"])
    invalid = tag in set(rules["invalid_role_labels"])
    primary = tag_roles if tag_roles and not invalid else name_roles
    conflict = None
    if tag_roles and name_roles and set(tag_roles).isdisjoint(name_roles):
        conflict = {
            "material": material,
            "role_label": tag,
            "label_roles": tag_roles,
            "name_roles": name_roles,
            "final_roles": primary,
            "rule": "parseable label wins",
        }
    return primary, conflict


def resolve_directions(row: dict[str, str], rules: dict[str, Any]) -> list[str]:
    text = " ".join((row.get("素材") or "", row.get("一类") or "", row.get("二类") or ""))
    return match_aliases(text, rules["directions"])


def blank_stats() -> dict[str, Any]:
    return {
        "material_count": 0,
        "spend": 0.0,
        "new_paid_count": 0.0,
        "roi1_value": 0.0,
        "roi2_value": 0.0,
        "missing": {key: 0 for key in ("spend", "new_paid_count", "roi1", "roi2", "two_day_multiplier")},
        "observable_count": 0,
        "roi1_pass_count": 0,
        "materials": [],
    }


def material_fact(row: dict[str, str]) -> dict[str, Any]:
    spend = parse_number(row.get("花费"))
    roi1 = parse_number(row.get("roi1"))
    roi2 = parse_number(row.get("roi2"))
    return {
        "material": row.get("素材") or "",
        "project_id": row.get("gid") or row.get("项目") or None,
        "material_id": row.get("素材编号") or row.get("mid") or None,
        "evidence_type": "backend_metric",
        "name_evidence_type": "material_name",
        "link": source_link(row.get("demand_url") if "demand_url" in row else row.get("素材地址")),
        "category_1": row.get("一类") or "",
        "category_2": row.get("二类") or "",
        "role_label": row.get("角色") or "",
        "production_date": row.get("产出日期") or "",
        "spend": rounded(spend),
        "new_paid_count": rounded(parse_number(row.get("新付费数"))),
        "roi1": rounded(roi1),
        "roi2": rounded(roi2),
        "two_day_multiplier": rounded(parse_number(row.get("2日倍率"))) if roi1 not in (None, 0) else None,
        "derived_two_day_multiplier": rounded(ratio(roi2, roi1)),
    }


def add_row(stats: dict[str, Any], row: dict[str, str], spend_threshold: float, roi1_threshold: float) -> None:
    fact = material_fact(row)
    spend = fact["spend"]
    stats["material_count"] += 1
    for key in stats["missing"]:
        if fact[key] is None:
            stats["missing"][key] += 1
    if spend is not None:
        stats["spend"] += spend
    if fact["new_paid_count"] is not None:
        stats["new_paid_count"] += fact["new_paid_count"]
    for metric in ("roi1", "roi2"):
        if spend is not None and fact[metric] is not None:
            stats[metric + "_value"] += spend * fact[metric] / 100
    if spend is not None and spend >= spend_threshold:
        stats["observable_count"] += 1
        if fact["roi1"] is not None and fact["roi1"] >= roi1_threshold:
            stats["roi1_pass_count"] += 1
    stats["materials"].append(fact)


def finalize_stats(stats: dict[str, Any], roi1_threshold: float, two_day_threshold: float) -> dict[str, Any]:
    spend = None if stats["missing"]["spend"] else stats["spend"]
    roi1 = ratio(stats["roi1_value"] * 100, spend) if not stats["missing"]["roi1"] else None
    roi2 = ratio(stats["roi2_value"] * 100, spend) if not stats["missing"]["roi2"] else None
    paid = None if stats["missing"]["new_paid_count"] else stats["new_paid_count"]
    result = {
        "material_count": stats["material_count"],
        "spend": rounded(spend),
        "new_paid_count": rounded(paid),
        "cost_per_new_paid": rounded(ratio(spend, paid)),
        "roi1": rounded(roi1),
        "roi2": rounded(roi2),
        "two_day_multiplier": rounded(ratio(roi2, roi1)),
        "observable_count": stats["observable_count"],
        "roi1_pass_count": stats["roi1_pass_count"],
        "roi1_pass_rate": round(stats["roi1_pass_count"] / stats["observable_count"] * 100, 2)
        if stats["observable_count"]
        else None,
    }
    result["missing_metrics"] = dict(stats["missing"])
    by_spend = sorted(stats["materials"], key=lambda item: item["spend"] if item["spend"] is not None else -1, reverse=True)
    passing = [item for item in by_spend if item["spend"] is not None and item["spend"] > 0 and item["roi1"] is not None and item["roi1"] >= roi1_threshold]
    weak = [item for item in by_spend if item["spend"] is not None and item["spend"] > 0 and item["roi1"] is not None and item["roi1"] < roi1_threshold]
    selected: list[dict[str, Any]] = []
    for item in (by_spend[:1] + passing[:2] + weak[:1]):
        if item not in selected:
            selected.append(item)
    result["representative_materials"] = selected[:3]
    return result


def aggregate_groups(
    rows: Iterable[dict[str, str]],
    resolver: Callable[[dict[str, str]], Iterable[str]],
    spend_threshold: float,
    roi1_threshold: float,
    two_day_threshold: float,
) -> dict[str, dict[str, Any]]:
    raw: dict[str, dict[str, Any]] = defaultdict(blank_stats)
    for row in rows:
        for group in dict.fromkeys(resolver(row)):
            if group:
                add_row(raw[group], row, spend_threshold, roi1_threshold)
    return {
        group: finalize_stats(stats, roi1_threshold, two_day_threshold)
        for group, stats in sorted(raw.items(), key=lambda item: item[1]["spend"], reverse=True)
    }


def aggregate_overall(
    rows: Iterable[dict[str, str]], spend_threshold: float, roi1_threshold: float, two_day_threshold: float
) -> dict[str, Any]:
    stats = blank_stats()
    for row in rows:
        add_row(stats, row, spend_threshold, roi1_threshold)
    return finalize_stats(stats, roi1_threshold, two_day_threshold)


def apply_total_row(
    detail_stats: dict[str, Any],
    total_row: dict[str, str] | None,
    roi1_threshold: float,
    two_day_threshold: float,
) -> dict[str, Any]:
    """Use the backend total row for project totals while retaining detail-derived sample counts."""
    if not total_row:
        return detail_stats
    result = dict(detail_stats)
    spend = parse_number(total_row.get("花费"))
    paid = parse_number(total_row.get("新付费数"))
    roi1 = parse_number(total_row.get("roi1"))
    roi2 = parse_number(total_row.get("roi2"))
    result.update(
        {
            "spend": rounded(spend),
            "new_paid_count": rounded(paid),
            "cost_per_new_paid": rounded(ratio(spend, paid)),
            "roi1": rounded(roi1),
            "roi2": rounded(roi2),
            "two_day_multiplier": rounded(ratio(roi2, roi1)),
        }
    )
    return result


def subset_by_production_date(rows: Iterable[dict[str, str]], start: dt.date, end: dt.date) -> list[dict[str, str]]:
    result = []
    for row in rows:
        production_date = parse_optional_date(row.get("产出日期") or "")
        if production_date and start <= production_date <= end:
            result.append(row)
    return result


def observed_production_range(rows: Iterable[dict[str, str]]) -> tuple[str | None, str | None]:
    dates = [date for row in rows if (date := parse_optional_date(row.get("产出日期") or ""))]
    if not dates:
        return None, None
    return min(dates).isoformat(), max(dates).isoformat()


def comparison(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any] | None:
    if previous is None:
        return None

    def pct_change(now, before):
        value = ratio(now, before)
        return rounded((value - 1) * 100) if value is not None else None

    return {
        "spend_change_pct": pct_change(current["spend"], previous["spend"]),
        "new_paid_change_pct": pct_change(current["new_paid_count"], previous["new_paid_count"]),
        "cost_per_new_paid_change_pct": pct_change(current["cost_per_new_paid"], previous["cost_per_new_paid"]),
        "roi1_change_pp": difference(current["roi1"], previous["roi1"]),
        "roi2_change_pp": difference(current["roi2"], previous["roi2"]),
        "two_day_multiplier_change": difference(current["two_day_multiplier"], previous["two_day_multiplier"]),
        "roi1_pass_rate_change_pp": difference(current["roi1_pass_rate"], previous["roi1_pass_rate"]),
    }


def compare_group_maps(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    output = {}
    for name in sorted(set(current) | set(previous), key=lambda key: (current.get(key, {}).get("spend") or 0), reverse=True):
        now = current.get(name)
        before = previous.get(name)
        if now and before:
            output[name] = comparison(now, before)
        elif now:
            output[name] = {"status": "current_only"}
        else:
            output[name] = {"status": "previous_only"}
    return output


def analyze_dataset(
    current_path: Path,
    previous_path: Path | None,
    keywords: list[str],
    new_start: dt.date | None,
    new_end: dt.date | None,
    spend_threshold: float,
    roi1_threshold: float,
    two_day_threshold: float,
) -> dict[str, Any]:
    rules = load_rules()
    current_rows, current_headers, current_encoding, current_total_row = read_csv(current_path)
    missing = sorted(REQUIRED_COLUMNS - set(current_headers))
    if missing:
        raise RuntimeError(f"current CSV missing required columns: {', '.join(missing)}")
    previous_rows: list[dict[str, str]] = []
    previous_headers: list[str] = []
    previous_encoding = None
    previous_total_row = None
    if previous_path:
        previous_rows, previous_headers, previous_encoding, previous_total_row = read_csv(previous_path)
        previous_missing = sorted(REQUIRED_COLUMNS - set(previous_headers))
        if previous_missing:
            raise RuntimeError(f"previous CSV missing required columns: {', '.join(previous_missing)}")

    conflicts: list[dict[str, Any]] = []

    def roles(row: dict[str, str]) -> list[str]:
        resolved, conflict = resolve_roles(row, rules)
        if conflict and len(conflicts) < 30:
            conflicts.append(conflict)
        return resolved

    def directions(row: dict[str, str]) -> list[str]:
        return resolve_directions(row, rules)

    def first_tags(row: dict[str, str]) -> list[str]:
        return [(row.get("一类") or "未标注").strip() or "未标注"]

    def second_tags(row: dict[str, str]) -> list[str]:
        return [(row.get("二类") or "未标注").strip() or "未标注"]

    current_detail_overall = aggregate_overall(current_rows, spend_threshold, roi1_threshold, two_day_threshold)
    current_overall = apply_total_row(
        current_detail_overall, current_total_row, roi1_threshold, two_day_threshold
    )
    current_production_min, current_production_max = observed_production_range(current_rows)
    current_roles = aggregate_groups(current_rows, roles, spend_threshold, roi1_threshold, two_day_threshold)
    current_directions = aggregate_groups(current_rows, directions, spend_threshold, roi1_threshold, two_day_threshold)
    current_first = aggregate_groups(current_rows, first_tags, spend_threshold, roi1_threshold, two_day_threshold)
    current_second = aggregate_groups(current_rows, second_tags, spend_threshold, roi1_threshold, two_day_threshold)

    previous_overall = None
    previous_roles: dict[str, Any] = {}
    previous_directions: dict[str, Any] = {}
    if previous_rows:
        previous_detail_overall = aggregate_overall(
            previous_rows, spend_threshold, roi1_threshold, two_day_threshold
        )
        previous_overall = apply_total_row(
            previous_detail_overall, previous_total_row, roi1_threshold, two_day_threshold
        )
        previous_production_min, previous_production_max = observed_production_range(previous_rows)
        previous_roles = aggregate_groups(
            previous_rows, roles, spend_threshold, roi1_threshold, two_day_threshold
        )
        previous_directions = aggregate_groups(
            previous_rows, directions, spend_threshold, roi1_threshold, two_day_threshold
        )
    else:
        previous_detail_overall = None
        previous_production_min = previous_production_max = None

    keyword_results: dict[str, Any] = {}
    for keyword in keywords:
        matched = [row for row in current_rows if keyword in (row.get("素材") or "")]
        keyword_results[keyword] = {
            "match_type": "material_name",
            "status": "matched" if matched else "not_detected_in_scope",
            "boundary": "名称匹配；本次口径未检出不等于历史未做过或异名结构不存在",
            "summary": aggregate_overall(matched, spend_threshold, roi1_threshold, two_day_threshold),
            "materials": [material_fact(row) for row in sorted(matched, key=lambda r: parse_number(r.get("花费")) if parse_number(r.get("花费")) is not None else -1, reverse=True)],
        }

    new_material = None
    if new_start and new_end:
        new_rows = subset_by_production_date(current_rows, new_start, new_end)
        production_date_counts = Counter(
            (row.get("产出日期") or "").strip() for row in new_rows if (row.get("产出日期") or "").strip()
        )
        new_material = {
            "production_range": range_text(new_start, new_end),
            "row_count": len(new_rows),
            "production_date_counts": dict(sorted(production_date_counts.items())),
            "overall": aggregate_overall(new_rows, spend_threshold, roi1_threshold, two_day_threshold),
            "roles": aggregate_groups(new_rows, roles, spend_threshold, roi1_threshold, two_day_threshold),
            "directions": aggregate_groups(new_rows, directions, spend_threshold, roi1_threshold, two_day_threshold),
        }

    return {
        "ok": True,
        "data_quality": {
            "current": {
                "path": str(current_path),
                "rows": len(current_rows),
                "columns": len(current_headers),
                "encoding": current_encoding,
                "backend_total_row": bool(current_total_row),
                "detail_spend": current_detail_overall["spend"],
                "backend_total_spend": current_overall["spend"] if current_total_row else None,
                "detail_total_spend_difference": difference(current_detail_overall["spend"], current_overall["spend"]) if current_total_row else None,
                "observed_production_date_min": current_production_min,
                "observed_production_date_max": current_production_max,
                "missing_required_columns": [],
            },
            "previous": {
                "path": str(previous_path),
                "rows": len(previous_rows),
                "columns": len(previous_headers),
                "encoding": previous_encoding,
                "backend_total_row": bool(previous_total_row),
                "detail_spend": previous_detail_overall["spend"] if previous_detail_overall else None,
                "backend_total_spend": previous_overall["spend"] if previous_total_row else None,
                "detail_total_spend_difference": difference(previous_detail_overall["spend"], previous_overall["spend"])
                if previous_detail_overall and previous_total_row
                else None,
                "observed_production_date_min": previous_production_min,
                "observed_production_date_max": previous_production_max,
                "missing_required_columns": [],
            }
            if previous_path
            else None,
        },
        "thresholds": {
            "source": "configured_analysis_parameters_not_user_confirmed_business_standard",
            "spend": spend_threshold,
            "roi1": roi1_threshold,
            "two_day_multiplier": two_day_threshold,
        },
        "current": {
            "overall": current_overall,
            "detail_overall": current_detail_overall,
            "backend_total": material_fact(current_total_row) if current_total_row else None,
            "roles": current_roles,
            "directions": current_directions,
            "category_1": current_first,
            "category_2": current_second,
        },
        "previous": {
            "overall": previous_overall,
            "detail_overall": previous_detail_overall,
            "roles": previous_roles,
            "directions": previous_directions,
        }
        if previous_path
        else None,
        "comparison": {
            "overall": comparison(current_overall, previous_overall),
            "roles": compare_group_maps(current_roles, previous_roles),
            "directions": compare_group_maps(current_directions, previous_directions),
        }
        if previous_path
        else None,
        "new_material": new_material,
        "keyword_results": keyword_results,
        "role_label_name_conflicts": conflicts,
    }


def fmt(value: Any, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def markdown_report(payload: dict[str, Any], contract: dict[str, Any] | None) -> str:
    current = payload["current"]
    lines = ["# 荣耀素材表现分析", ""]
    if contract:
        lines.extend(
            [
                "## 数据口径",
                "",
                f"- 数据源：{contract.get('source', '荣耀后台新素材2.0直接接口')}",
                f"- 当前期：{contract.get('date_range', '由CSV提供')}",
                f"- 对比期：{contract.get('compare_range') or '无'}",
                f"- 素材产出日期：{contract.get('material_range', '由CSV提供')}",
                f"- 项目GID：{contract.get('gid', '未提供')}",
                f"- 当前样本：{payload['data_quality']['current']['rows']}条",
                "",
            ]
        )
    quality = payload["data_quality"]["current"]
    lines.extend([f"- 明细消耗：{fmt(quality['detail_spend'])}；后台总计：{fmt(quality['backend_total_spend'])}；差额（明细−后台）：{fmt(quality['detail_total_spend_difference'])}。",
                  ""])
    overall = current["overall"]
    lines.extend(
        [
            "## 总体表现",
            "",
            "| 消耗 | 新付费数 | ROI1 | ROI2 | 2日倍率 | 观察素材 | ROI1达标 |",
            "|---:|---:|---:|---:|---:|---:|---:|",
            f"| {fmt(overall['spend'])} | {fmt(overall['new_paid_count'])} | {fmt(overall['roi1'])}% | {fmt(overall['roi2'])}% | {fmt(overall['two_day_multiplier'])} | {overall['observable_count']} | {overall['roi1_pass_count']} |",
            "",
        ]
    )
    if payload.get("comparison"):
        change = payload["comparison"]["overall"]
        lines.extend(
            [
                "## 前后变化",
                "",
                "| 消耗变化 | 新付费变化 | 单次付费成本变化 | ROI1变化 | ROI2变化 | 2日倍率变化 |",
                "|---:|---:|---:|---:|---:|---:|",
                f"| {fmt(change['spend_change_pct'], '%')} | {fmt(change['new_paid_change_pct'], '%')} | {fmt(change['cost_per_new_paid_change_pct'], '%')} | {fmt(change['roi1_change_pp'])}pp | {fmt(change['roi2_change_pp'])}pp | {fmt(change['two_day_multiplier_change'])} |",
                "",
            ]
        )

    def group_table(title: str, groups: dict[str, Any], limit: int = 15) -> None:
        lines.extend(
            [
                f"## {title}",
                "",
                "| 对象 | 消耗 | 新付费数 | ROI1 | ROI2 | 2日倍率 | 达标/观察 |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for name, stats in list(groups.items())[:limit]:
            lines.append(
                f"| {name} | {fmt(stats['spend'])} | {fmt(stats['new_paid_count'])} | {fmt(stats['roi1'])}% | {fmt(stats['roi2'])}% | {fmt(stats['two_day_multiplier'])} | {stats['roi1_pass_count']}/{stats['observable_count']} |"
            )
        lines.append("")

    group_table("角色表现", current["roles"])
    group_table("方向表现", current["directions"])
    if payload.get("new_material"):
        group_table("新产素材角色表现", payload["new_material"]["roles"], 12)
    if payload["keyword_results"]:
        for keyword, result in payload["keyword_results"].items():
            stats = result["summary"]
            lines.extend(
                [
                    f"## 关键词：{keyword}",
                    "",
                    f"合计消耗{fmt(stats['spend'])}，新付费数{fmt(stats['new_paid_count'])}，ROI1 {fmt(stats['roi1'])}%，ROI2 {fmt(stats['roi2'])}%。",
                    "",
                    "| 素材 | 消耗 | 新付费数 | ROI1 | ROI2 |",
                    "|---|---:|---:|---:|---:|",
                ]
            )
            for item in result["materials"][:20]:
                lines.append(
                    f"| {item['material']} | {fmt(item['spend'])} | {fmt(item['new_paid_count'])} | {fmt(item['roi1'])}% | {fmt(item['roi2'])}% |"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"success_count": 0, "failure_count": 0}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"success_count": 0, "failure_count": 0}


def write_state(ok: bool, mode: str, outputs: list[str], blocker: str | None) -> None:
    state = read_state()
    state["success_count" if ok else "failure_count"] = state.get("success_count" if ok else "failure_count", 0) + 1
    state.update(
        {
            "last_run_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "last_mode": mode,
            "last_ok": ok,
            "outputs": outputs,
            "blocker": blocker,
        }
    )
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_error_text(completed: subprocess.CompletedProcess[str]) -> str:
    text = (completed.stderr or completed.stdout or "backend export failed").strip()
    return text[-1500:]


def validate_capture_identity(
    payload: dict[str, Any], date_range: str, material_range: str, gid: int
) -> dict[str, Any]:
    """Stop if the backend response does not match the requested read-only contract."""
    filters = payload.get("filters")
    if not isinstance(filters, dict):
        raise RuntimeError("backend export missing filters identity")
    expected = {
        "entry": "新素材2.0",
        "gid": str(gid),
        "dateRange": date_range,
        "materialRange": material_range,
        "dateGroup": "tenyear",
        "group": "mid",
        "sourceVideoType": "视频",
        "recordType": "新注册",
        "filter": "是",
    }
    if gid == 193:
        expected["game"] = "忍界大战"
    mismatches = {
        key: {"expected": value, "actual": filters.get(key)}
        for key, value in expected.items()
        if str(filters.get(key)) != str(value)
    }
    if mismatches:
        raise RuntimeError(
            "backend export identity mismatch: "
            + ", ".join(f"{key}={values['actual']!r}" for key, values in mismatches.items())
        )
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    return {
        "ok": True,
        "entry": filters["entry"],
        "game": filters.get("game"),
        "gid": filters["gid"],
        "date_range": filters["dateRange"],
        "material_range": filters["materialRange"],
        "date_group": filters["dateGroup"],
        "group": filters["group"],
        "source_video_type": filters["sourceVideoType"],
        "record_type": filters["recordType"],
        "filter": filters["filter"],
        "query_count": query.get("count"),
        "query_totalpage": query.get("totalpage"),
        "query_pagesize": query.get("pagesize"),
    }


def capture_one(
    cli_path: Path,
    date_range: str,
    material_range: str,
    gid: int,
    output: Path,
    chrome_profile: str | None,
    cookie_file: str | None,
    cookie_env: str | None,
    host: str | None,
) -> dict[str, Any]:
    if not cli_path.exists():
        raise RuntimeError(f"backend CLI not found: {cli_path}")
    command = [
        sys.executable,
        str(cli_path),
        "backend-export",
        "--date-range",
        date_range,
        "--material-range",
        material_range,
        "--gid",
        str(gid),
        "--date-group",
        "tenyear",
        "--group",
        "mid",
        "--output",
        str(output),
        "--format",
        "json",
    ]
    for flag, value in (
        ("--chrome-profile", chrome_profile),
        ("--cookie-file", cookie_file),
        ("--cookie-env", cookie_env),
        ("--host", host),
    ):
        if value:
            command.extend([flag, value])
    completed = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(safe_error_text(completed))
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"backend CLI returned invalid JSON: {exc}") from exc
    if not payload.get("ok") or not output.exists():
        raise RuntimeError(payload.get("error") or "backend export did not create output")
    payload["validation"] = validate_capture_identity(payload, date_range, material_range, gid)
    return payload


def capture_cache_key(
    cli_path: Path,
    date_range: str,
    material_range: str,
    gid: int,
    host: str | None,
) -> tuple[str, dict[str, Any]]:
    """Return an exact-contract cache key; credentials never enter the signature."""
    contract = {
        "schema": CACHE_SCHEMA_VERSION,
        "capture_contract": "new-material-v2-mid",
        "host": host or DEFAULT_BACKEND_HOST,
        "date_range": date_range,
        "material_range": material_range,
        "gid": gid,
        "date_group": "tenyear",
        "group": "mid",
        "source_video_type": "1",
        "record_type": "3",
        "filter": "1",
    }
    encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24], contract


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prune_capture_cache(cache_dir: Path, max_entries: int = DEFAULT_CACHE_MAX_ENTRIES) -> None:
    metadata = sorted(cache_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in metadata[max_entries:]:
        stale.with_suffix(".csv").unlink(missing_ok=True)
        stale.unlink(missing_ok=True)


def capture_one_cached(
    cli_path: Path,
    date_range: str,
    material_range: str,
    gid: int,
    output: Path,
    chrome_profile: str | None,
    cookie_file: str | None,
    cookie_env: str | None,
    host: str | None,
    *,
    cache_mode: str = "auto",
    cache_ttl_minutes: int = DEFAULT_CACHE_TTL_MINUTES,
    cache_dir: Path = CACHE_DIR,
) -> dict[str, Any]:
    """Reuse a recent exact capture or perform one live read and cache it locally."""
    if cache_mode not in {"auto", "refresh", "off"}:
        raise ValueError("cache mode must be auto, refresh, or off")
    if cache_ttl_minutes < 0:
        raise ValueError("cache ttl must be nonnegative")
    key, contract = capture_cache_key(cli_path, date_range, material_range, gid, host)
    csv_cache = cache_dir / f"{key}.csv"
    metadata_cache = cache_dir / f"{key}.json"
    now = time.time()

    if cache_mode == "auto" and cache_ttl_minutes > 0 and csv_cache.is_file() and metadata_cache.is_file():
        try:
            metadata = json.loads(metadata_cache.read_text(encoding="utf-8"))
            age_seconds = max(0.0, now - float(metadata["created_at_epoch"]))
            if (
                metadata.get("contract") == contract
                and age_seconds <= cache_ttl_minutes * 60
                and metadata.get("sha256") == file_sha256(csv_cache)
            ):
                rows, headers, _, _ = read_csv(csv_cache)
                if REQUIRED_COLUMNS.issubset(headers) and rows:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(csv_cache, output)
                    payload = dict(metadata["capture"])
                    payload["file"] = str(output)
                    payload["validation"] = validate_capture_identity(payload, date_range, material_range, gid)
                    payload["cache"] = {
                        "status": "hit",
                        "key": key,
                        "age_seconds": round(age_seconds, 2),
                        "ttl_minutes": cache_ttl_minutes,
                    }
                    os.utime(metadata_cache, None)
                    os.utime(csv_cache, None)
                    return payload
        except (KeyError, ValueError, OSError, json.JSONDecodeError, RuntimeError):
            # A corrupt or incompatible cache is ignored; the live path remains fail-closed.
            pass

    payload = capture_one(
        cli_path,
        date_range,
        material_range,
        gid,
        output,
        chrome_profile,
        cookie_file,
        cookie_env,
        host,
    )
    payload["cache"] = {
        "status": "disabled" if cache_mode == "off" else ("refresh" if cache_mode == "refresh" else "miss"),
        "key": key,
        "ttl_minutes": cache_ttl_minutes,
    }
    if cache_mode != "off":
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(cache_dir, 0o700)
        csv_temp = cache_dir / f".{key}.{os.getpid()}.csv.tmp"
        json_temp = cache_dir / f".{key}.{os.getpid()}.json.tmp"
        shutil.copyfile(output, csv_temp)
        cached_capture = dict(payload)
        cached_capture["file"] = None
        metadata = {
            "schema": CACHE_SCHEMA_VERSION,
            "created_at_epoch": now,
            "contract": contract,
            "sha256": file_sha256(csv_temp),
            "capture": cached_capture,
        }
        json_temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(csv_temp, 0o600)
        os.chmod(json_temp, 0o600)
        os.replace(csv_temp, csv_cache)
        os.replace(json_temp, metadata_cache)
        prune_capture_cache(cache_dir)
    return payload


def output_dir(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
    else:
        path = Path(tempfile.mkdtemp(prefix="rongyao-material-performance-"))
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("output directory must be empty; choose a new directory to preserve existing results")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_analysis(payload: dict[str, Any], destination: Path, contract: dict[str, Any] | None) -> list[str]:
    json_path = destination / "analysis.json"
    md_path = destination / "analysis.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(payload, contract), encoding="utf-8")
    return [str(json_path), str(md_path)]


def compact_overall(stats: dict[str, Any] | None) -> dict[str, Any] | None:
    if stats is None:
        return None
    return {key: stats.get(key) for key in SUMMARY_OVERALL_FIELDS}


def compact_groups(groups: dict[str, dict[str, Any]] | None, limit: int | None = 12) -> dict[str, dict[str, Any]]:
    """Keep only aggregated fields for the highest-spend groups."""
    ranked = sorted((groups or {}).items(), key=lambda item: (
        item[1].get("spend") is not None,
        item[1].get("spend") if item[1].get("spend") is not None else 0,
    ), reverse=True)
    return {name: compact_overall(stats) or {} for name, stats in ranked[:limit]}


def compact_keyword_results(results: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    compact: dict[str, dict[str, Any]] = {}
    for keyword, result in (results or {}).items():
        compact[keyword] = {
            "summary": compact_overall(result.get("summary")),
            "match_type": result.get("match_type"), "status": result.get("status"), "boundary": result.get("boundary"),
            "materials": [
                {
                    key: item.get(key)
                    for key in (
                        "material",
                        "category_1",
                        "category_2",
                        "role_label",
                        "production_date",
                "project_id", "material_id", "link", "evidence_type", "name_evidence_type",
                        "spend",
                        "new_paid_count",
                        "roi1",
                        "roi2",
                        "two_day_multiplier",
                    )
                }
                for item in (result.get("materials") or [])[:3]
            ],
        }
    return compact


def canonical_role_name(requested: str, rules: dict[str, Any] | None = None) -> str:
    requested = requested.strip()
    role_rules = (rules or load_rules()).get("roles") or {}
    for canonical, aliases in role_rules.items():
        if requested == canonical or requested in aliases:
            return canonical
    return requested


def focus_role_stats(
    csv_path: Path,
    requested_role: str,
    spend_threshold: float,
    roi1_threshold: float,
    two_day_threshold: float,
    production_start: dt.date | None = None,
    production_end: dt.date | None = None,
) -> dict[str, Any]:
    """Aggregate one role without exposing the rest of the material table."""
    rows, _, _, _ = read_csv(csv_path)
    if production_start and production_end:
        rows = subset_by_production_date(rows, production_start, production_end)
    rules = load_rules()
    canonical = canonical_role_name(requested_role, rules)

    def matches(row: dict[str, str]) -> bool:
        resolved, _ = resolve_roles(row, rules)
        if canonical in resolved:
            return True
        tag = (row.get("角色") or "").strip()
        material = row.get("素材") or ""
        return requested_role == tag or (not resolved and requested_role in material)

    return aggregate_overall(
        [row for row in rows if matches(row)],
        spend_threshold,
        roi1_threshold,
        two_day_threshold,
    )


def compact_focus_stats(stats: dict[str, Any]) -> dict[str, Any]:
    compact = compact_overall(stats) or {}
    compact["representative_materials"] = [
        {
            key: item.get(key)
            for key in (
                "material",
                "category_1",
                "category_2",
                "role_label",
                "production_date",
                "project_id", "material_id", "link", "evidence_type", "name_evidence_type",
                "spend",
                "new_paid_count",
                "roi1",
                "roi2",
                "two_day_multiplier",
            )
        }
        for item in stats.get("representative_materials", [])[:3]
    ]
    return compact


def validate_reused_current_summary(
    summary_path: Path, date_range: str, material_range: str, gid: int
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    contract = summary.get("contract") or {}
    expected = {
        "date_range": date_range,
        "material_range": material_range,
        "gid": gid,
    }
    mismatches = {
        key: {"expected": value, "actual": contract.get(key)}
        for key, value in expected.items()
        if str(contract.get(key)) != str(value)
    }
    if mismatches:
        raise RuntimeError(
            "reused current summary identity mismatch: "
            + ", ".join(f"{key}={values['actual']!r}" for key, values in mismatches.items())
        )
    quality = summary.get("data_quality") or {}
    if quality.get("missing_required_columns"):
        raise RuntimeError("reused current CSV previously failed required-column validation")
    return {
        "ok": True,
        "date_range": contract["date_range"],
        "material_range": contract["material_range"],
        "gid": contract["gid"],
        "rows": quality.get("rows"),
        "columns": quality.get("columns"),
    }


def machine_summary(
    payload: dict[str, Any], contract: dict[str, Any] | None, outputs: list[str]
) -> dict[str, Any]:
    """Return fixed, small fields safe to feed back into an agent context."""
    quality = payload["data_quality"]["current"]
    capture = payload.get("capture") or {}
    current_capture = capture.get("current") or {}
    identity = current_capture.get("validation")
    # The backend's `count` is the number of underlying query records.  With
    # group=mid the exported CSV is aggregated to one row per material, so it
    # is expected to differ from the exported detail-row count.  Preserve both
    # numbers for auditability instead of treating different grains as data
    # loss.  Empty exports and missing required columns are validated earlier.
    if isinstance(identity, dict):
        identity = {
            **identity,
            "exported_detail_rows": quality["rows"],
            "query_count_scope": "underlying_records",
            "exported_rows_scope": "grouped_materials",
        }
    new_material = payload.get("new_material")
    analysis_path = next((path for path in outputs if path.endswith("analysis.json")), None)
    summary_path = next((path for path in outputs if path.endswith("summary.json")), None)
    return {
        "ok": bool(payload.get("ok")),
        "contract": contract,
        "coverage": coverage({**(contract or {}), "included_projects": (contract or {}).get("included_projects", [str(contract["gid"])] if contract and contract.get("gid") is not None else [])}),
        "thresholds": payload.get("thresholds"),
        "analysis_path": analysis_path,
        "summary_path": summary_path,
        "data_quality": {
            "rows": quality["rows"],
            "columns": quality["columns"],
            "missing_required_columns": quality["missing_required_columns"],
            "backend_total_row": quality["backend_total_row"],
            "detail_spend": quality["detail_spend"],
            "backend_total_spend": quality["backend_total_spend"],
            "detail_total_spend_difference": quality["detail_total_spend_difference"],
            "observed_production_date_min": quality["observed_production_date_min"],
            "observed_production_date_max": quality["observed_production_date_max"],
        },
        "capture_validation": identity,
        "capture_performance": {
            "strategy": (contract or {}).get("capture_strategy", "serial"),
            "workers": (contract or {}).get("capture_workers", 1),
            "cache_mode": (contract or {}).get("cache_mode", "off"),
            "cache_ttl_minutes": (contract or {}).get("cache_ttl_minutes"),
            "current_cache": (current_capture.get("cache") or {}).get("status"),
            "previous_cache": ((capture.get("previous") or {}).get("cache") or {}).get("status"),
        },
        "overall": compact_overall(payload["current"]["overall"]),
        "roles": compact_groups(payload["current"].get("roles")),
        "directions": compact_groups(payload["current"].get("directions"), limit=None),
        "group_coverage": {
            "roles_total": len(payload["current"].get("roles") or {}),
            "roles_shown": min(12, len(payload["current"].get("roles") or {})),
            "directions_total": len(payload["current"].get("directions") or {}),
            "direction_matching": "configured_name_and_label_rules_not_exhaustive_taxonomy",
        },
        "new_material": {
            "production_range": new_material["production_range"],
            "row_count": new_material["row_count"],
            "production_date_counts": new_material.get("production_date_counts", {}),
            "overall": compact_overall(new_material["overall"]),
            "roles": compact_groups(new_material.get("roles")),
            "directions": compact_groups(new_material.get("directions"), limit=None),
        }
        if new_material
        else None,
        "keyword_results": compact_keyword_results(payload.get("keyword_results")),
    }


def save_machine_summary(
    payload: dict[str, Any], destination: Path, contract: dict[str, Any] | None, outputs: list[str]
) -> tuple[str, dict[str, Any]]:
    summary_path = destination / "summary.json"
    all_outputs = outputs + [str(summary_path)]
    summary = machine_summary(payload, contract, all_outputs)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(summary_path), summary


def common_analysis_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--keyword", action="append", default=[], help="素材名关键词，可重复")
    parser.add_argument("--new-start", help="新产素材开始日期")
    parser.add_argument("--new-end", help="新产素材结束日期")
    parser.add_argument("--spend-threshold", type=float, default=500.0)
    parser.add_argument("--roi1-threshold", type=float, default=9.0)
    parser.add_argument("--two-day-threshold", type=float, default=1.9)
    parser.add_argument("--output-dir")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="分析已有CSV，不访问后台")
    analyze.add_argument("--current", required=True)
    analyze.add_argument("--previous")
    common_analysis_args(analyze)

    run = subparsers.add_parser("run", aliases=["export"], help="共用素材抓取流程；run分析，export只交付CSV")
    run.add_argument("--date-range", help="明确投放日期，YYYY/MM/DD-YYYY/MM/DD")
    run.add_argument("--period", choices=("this-week", "last-week", "recent"), help="本周/上周/滚动近期；北京时间")
    run.add_argument("--dry-run", action="store_true", help="只输出已解析的查询计划；不访问后台、不写文件或状态")
    run.add_argument("--compare", action="store_true", help="明确要求查询紧邻的等长上一期；默认不对比")
    run.add_argument("--compare-range", help="明确对比日期")
    run.add_argument("--recent-days", type=int, default=31)
    run.add_argument("--lag-days", type=int, help="recent默认留2天；this-week默认截至今天")
    run.add_argument("--no-auto-compare", action="store_true")
    material = run.add_mutually_exclusive_group()
    material.add_argument("--material-range", help="明确素材产出日期；优先于环境配置")
    material.add_argument("--material-start", help="素材产出起点，截至今天；否则用RONGYAO_MATERIAL_START或原有2023/01/01起点")
    run.add_argument("--gid", type=int, default=193)
    run.add_argument(
        "--cli-path",
        help=f"后台助手显式路径；默认先读 {WEEKLY_REPORT_CLI_ENV}，再用已安装HTTP适配器，否则走原Chrome兼容入口",
    )
    run.add_argument("--chrome-profile")
    run.add_argument("--cookie-file")
    run.add_argument("--cookie-env")
    run.add_argument("--host")
    run.add_argument(
        "--capture-workers",
        type=int,
        choices=(1, 2),
        default=2,
        help="有对比期时最多并行抓取两个独立区间；设为1可强制串行",
    )
    run.add_argument("--cache", choices=("auto", "refresh", "off"), default="auto")
    run.add_argument("--cache-ttl-minutes", type=int, default=DEFAULT_CACHE_TTL_MINUTES)
    run.add_argument("--cache-dir", default=str(CACHE_DIR), help=argparse.SUPPRESS)
    common_analysis_args(run)

    compare_role = subparsers.add_parser(
        "compare-role",
        help="复用已校验当前期CSV，只抓取上一期并直接输出单角色对比摘要",
    )
    compare_role.add_argument("--role", required=True)
    compare_role.add_argument("--current", required=True)
    compare_role.add_argument("--current-summary", required=True)
    compare_role.add_argument("--current-range", required=True)
    compare_role.add_argument("--compare-range", required=True)
    compare_role.add_argument("--material-range", required=True)
    compare_role.add_argument("--gid", type=int, default=193)
    compare_role.add_argument("--cli-path")
    compare_role.add_argument("--chrome-profile")
    compare_role.add_argument("--cookie-file")
    compare_role.add_argument("--cookie-env")
    compare_role.add_argument("--host")
    compare_role.add_argument("--cache", choices=("auto", "refresh", "off"), default="auto")
    compare_role.add_argument("--cache-ttl-minutes", type=int, default=DEFAULT_CACHE_TTL_MINUTES)
    compare_role.add_argument("--cache-dir", default=str(CACHE_DIR), help=argparse.SUPPRESS)
    common_analysis_args(compare_role)

    summary = subparsers.add_parser("summary", help="只输出analysis.json中的固定小摘要，不访问后台")
    summary.add_argument("--analysis", required=True)

    subparsers.add_parser("status", help="输出最近运行状态")
    return parser


def run_analyze(args: argparse.Namespace) -> int:
    destination = output_dir(args.output_dir)
    new_start = parse_date(args.new_start) if args.new_start else None
    new_end = parse_date(args.new_end) if args.new_end else None
    if bool(new_start) != bool(new_end):
        raise ValueError("--new-start and --new-end must be provided together")
    payload = analyze_dataset(
        Path(args.current).expanduser().resolve(),
        Path(args.previous).expanduser().resolve() if args.previous else None,
        args.keyword,
        new_start,
        new_end,
        args.spend_threshold,
        args.roi1_threshold,
        args.two_day_threshold,
    )
    contract = {"source": "user_provided_csv_offline_schema_checked", "date_range": "由CSV提供", "compare_range": "由CSV提供" if args.previous else None}
    outputs = save_analysis(payload, destination, contract)
    summary_path, summary = save_machine_summary(payload, destination, contract, outputs)
    outputs.append(summary_path)
    write_state(True, "analyze", outputs, None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def run_summary(args: argparse.Namespace) -> int:
    analysis_path = Path(args.analysis).expanduser().resolve()
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    contract = (payload.get("capture") or {}).get("contract")
    print(json.dumps(machine_summary(payload, contract, [str(analysis_path)]), ensure_ascii=False, indent=2))
    return 0


def run_compare_role(args: argparse.Namespace) -> int:
    current_start, current_end = parse_range(args.current_range)
    compare_start, compare_end = parse_range(args.compare_range)
    if (current_end - current_start) != (compare_end - compare_start):
        raise ValueError("current and compare ranges must have equal length")
    if compare_end != current_start - dt.timedelta(days=1):
        raise ValueError("compare range must immediately precede current range")
    parse_range(args.material_range)

    current_csv = Path(args.current).expanduser().resolve()
    cache_validation = validate_reused_current_summary(
        Path(args.current_summary).expanduser().resolve(),
        range_text(current_start, current_end),
        args.material_range,
        args.gid,
    )
    destination = output_dir(args.output_dir)
    previous_csv = destination / "previous.csv"
    contract = {
        "source": "validated current CSV + one live previous-period query",
        "date_range": range_text(current_start, current_end),
        "compare_range": range_text(compare_start, compare_end),
        "material_range": args.material_range,
        "gid": args.gid,
        "date_group": "tenyear",
        "group": "mid",
        "focus_role": canonical_role_name(args.role),
    }
    print(json.dumps({"query_contract": contract}, ensure_ascii=False), flush=True)
    previous_capture = capture_one_cached(
        resolve_weekly_report_cli(args.cli_path),
        contract["compare_range"],
        args.material_range,
        args.gid,
        previous_csv,
        args.chrome_profile,
        args.cookie_file,
        args.cookie_env,
        args.host,
        cache_mode=args.cache,
        cache_ttl_minutes=args.cache_ttl_minutes,
        cache_dir=Path(args.cache_dir).expanduser().resolve(),
    )
    new_start = parse_date(args.new_start) if args.new_start else current_start
    new_end = parse_date(args.new_end) if args.new_end else current_end
    payload = analyze_dataset(
        current_csv,
        previous_csv,
        [],
        new_start,
        new_end,
        args.spend_threshold,
        args.roi1_threshold,
        args.two_day_threshold,
    )
    payload["capture"] = {
        "contract": contract,
        "current": {"reused": True, "validation": cache_validation},
        "previous": previous_capture,
    }
    outputs = [str(previous_csv)] + save_analysis(payload, destination, contract)
    current_stats = focus_role_stats(
        current_csv, args.role, args.spend_threshold, args.roi1_threshold, args.two_day_threshold
    )
    previous_stats = focus_role_stats(
        previous_csv, args.role, args.spend_threshold, args.roi1_threshold, args.two_day_threshold
    )
    current_new_stats = focus_role_stats(
        current_csv,
        args.role,
        args.spend_threshold,
        args.roi1_threshold,
        args.two_day_threshold,
        new_start,
        new_end,
    )
    focus_summary = {
        "ok": True,
        "contract": contract,
        "role": canonical_role_name(args.role),
        "current": compact_focus_stats(current_stats),
        "previous": compact_focus_stats(previous_stats),
        "change": comparison(current_stats, previous_stats),
        "current_new_material": {
            "production_range": range_text(new_start, new_end),
            **compact_focus_stats(current_new_stats),
        },
        "data_quality": {
            "current": payload["data_quality"]["current"],
            "previous": payload["data_quality"]["previous"],
        },
        "capture_validation": {
            "current": cache_validation,
            "previous": previous_capture.get("validation"),
        },
        "capture_performance": {
            "current": "reused_validated_csv",
            "previous_cache": (previous_capture.get("cache") or {}).get("status"),
            "cache_mode": args.cache,
            "cache_ttl_minutes": args.cache_ttl_minutes,
        },
        "analysis_path": outputs[-2],
        "report_path": outputs[-1],
    }
    focus_path = destination / "focus-summary.json"
    focus_path.write_text(json.dumps(focus_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    outputs.append(str(focus_path))
    write_state(True, "compare-role", outputs, None)
    print(json.dumps(focus_summary, ensure_ascii=False, indent=2))
    return 0


def run_capture(args: argparse.Namespace) -> int:
    export_only = args.command == "export"
    if export_only and not (args.date_range or args.period):
        raise ValueError("export requires date-range or period; do not assume a date window")
    contract = plan_capture(args)
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "query_count": 0, "query_contract": contract}, ensure_ascii=False, indent=2))
        return 0
    material_range = contract["material_range"]
    compare = contract["compare_range"]
    new_start, new_end = parse_range(contract["new_material_range"])
    destination = output_dir(args.output_dir)
    current_csv = destination / "current.csv"
    previous_csv = destination / "previous.csv" if compare else None
    print(json.dumps({"query_contract": contract}, ensure_ascii=False), flush=True)
    resolved_cli = resolve_weekly_report_cli(args.cli_path)
    cache_dir = Path(args.cache_dir).expanduser().resolve()

    def capture_period(date_range: str, output: Path) -> dict[str, Any]:
        return capture_one_cached(
            resolved_cli,
            date_range,
            material_range,
            args.gid,
            output,
            args.chrome_profile,
            args.cookie_file,
            args.cookie_env,
            args.host,
            cache_mode=args.cache,
            cache_ttl_minutes=args.cache_ttl_minutes,
            cache_dir=cache_dir,
        )
    previous_capture = None
    if compare and previous_csv and args.capture_workers == 2:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            current_future = pool.submit(capture_period, contract["date_range"], current_csv)
            previous_future = pool.submit(capture_period, contract["compare_range"], previous_csv)
            current_capture = current_future.result()
            previous_capture = previous_future.result()
    else:
        current_capture = capture_period(contract["date_range"], current_csv)
        if compare and previous_csv:
            previous_capture = capture_period(contract["compare_range"], previous_csv)
    if export_only:
        files = []
        for label, path, receipt in (
            ("current", current_csv, current_capture),
            ("previous", previous_csv, previous_capture),
        ):
            if path is None:
                continue
            rows, headers, encoding, _ = read_csv(path)
            missing = sorted(REQUIRED_COLUMNS - set(headers))
            if missing:
                raise RuntimeError("export missing required columns: " + ", ".join(missing))
            files.append({"period": label, "path": str(path), "row_count": len(rows),
                          "column_count": len(headers), "encoding": encoding,
                          "sha256": file_sha256(path), "capture": receipt})
        result = {"ok": True, "mode": "export", "query_contract": contract, "files": files}
        receipt_path = destination / "export.json"
        receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_state(True, "export", [item["path"] for item in files] + [str(receipt_path)], None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    payload = analyze_dataset(
        current_csv,
        previous_csv,
        args.keyword,
        new_start,
        new_end,
        args.spend_threshold,
        args.roi1_threshold,
        args.two_day_threshold,
    )
    payload["capture"] = {"contract": contract, "current": current_capture, "previous": previous_capture}
    outputs = [str(current_csv)] + ([str(previous_csv)] if previous_csv else [])
    outputs += save_analysis(payload, destination, contract)
    summary_path, summary = save_machine_summary(payload, destination, contract, outputs)
    outputs.append(summary_path)
    write_state(True, "run", outputs, None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(read_state(), ensure_ascii=False, indent=2))
        return 0
    try:
        if args.command == "analyze":
            return run_analyze(args)
        if args.command == "summary":
            return run_summary(args)
        if args.command == "compare-role":
            return run_compare_role(args)
        return run_capture(args)
    except Exception as exc:  # Convert subprocess and schema failures into a controlled stop.
        if not getattr(args, "dry_run", False):
            write_state(False, args.command, [], str(exc))
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
