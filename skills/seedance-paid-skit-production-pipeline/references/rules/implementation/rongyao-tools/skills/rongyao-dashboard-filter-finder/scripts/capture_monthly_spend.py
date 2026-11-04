#!/usr/bin/env python3
"""Build and validate 火影 monthly interval-query capture results.

This helper deliberately does not call the obsolete monthly-summary archive.
The authenticated dashboard UI remains the authoritative capture surface.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")


TIMEZONE = "Asia/Shanghai"
PROJECT_ALIAS = "火影"
PROJECT_FIELD = "母游戏"
PROJECT_LABEL = "忍界大战"
PROJECT_ID = 193
DATE_GROUP_LABEL = "区间汇总2"
DATE_GROUP_VALUE = "tenyear"
READONLY_CAPTURE = Path(__file__).resolve().parents[2] / "rongyao-data-stack/scripts/readonly_capture.py"
VALIDATED_FIXED_FILTERS: dict[str, object] = {
    "gid": ["193"],
    "category": ["133", "145", "146", "147", "148", "163", "165", "166"],
    "osid": "",
    "divide": "",
    "operation_client": ["1", "2", "3", "4", "5", "6", "7"],
    "design_name": [],
    "demand_name": [],
    "accountId": [],
    "date_group": "tenyear",
    "group": "mid",
    "self_tag": "",
    "keyword": "",
    "negative_keyword": "",
    "start_cost": "0",
    "end_cost": "999999999",
    "source_type": [],
    "source_direction": [],
    "role": [],
    "region_type": [],
    "custom_list": [],
    "source_video_type": "1",
    "record_type": "3",
    "aweme_id": [],
    "big_aweme_id": [],
    "filter": "1",
    "weekday": "",
}
DYNAMIC_ALL_SELECTIONS = ["pkid", "pcid", "manager", "product_id"]


class ContractError(ValueError):
    """Raised when a requested or captured value breaks the query contract."""


def load_capture(path: Path = READONLY_CAPTURE):
    if not path.is_file():
        raise ContractError(f"未找到统一只读抓取入口：{path}")
    spec = importlib.util.spec_from_file_location("rongyao_readonly_capture_monthly_spend", path)
    if spec is None or spec.loader is None:
        raise ContractError(f"无法加载统一只读抓取入口：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_month(value: str) -> tuple[int, int]:
    try:
        parsed = dt.date.fromisoformat(f"{value}-01")
    except ValueError as error:
        raise argparse.ArgumentTypeError("月份必须使用 YYYY-MM 格式。") from error
    return parsed.year, parsed.month


def iter_months(start: str, end: str) -> Iterable[str]:
    year, month = parse_month(start)
    end_year, end_month = parse_month(end)
    if (year, month) > (end_year, end_month):
        raise ContractError("开始月份不能晚于结束月份。")
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}-{month:02d}"
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def month_bounds(month_key: str) -> tuple[str, str, str]:
    year, month = parse_month(month_key)
    last_day = calendar.monthrange(year, month)[1]
    start = f"{month_key}-01"
    end = f"{month_key}-{last_day:02d}"
    ui_range = f"{year:04d}/{month:02d}/01-{year:04d}/{month:02d}/{last_day:02d}"
    return start, end, ui_range


def parse_result(value: str) -> tuple[str, int]:
    month_key, separator, raw_spend = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("--result 必须使用 YYYY-MM=SPEND 格式。")
    parse_month(month_key)
    try:
        spend = int(raw_spend)
    except ValueError as error:
        raise argparse.ArgumentTypeError("SPEND 必须是后台显示的精确整数。") from error
    if spend < 0:
        raise argparse.ArgumentTypeError("SPEND 不能为负数。")
    return month_key, spend


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    months = list(iter_months(args.start_month, args.end_month))
    control_month = getattr(args, "control_month", None)
    control_spend = getattr(args, "control_spend", None)
    if (control_month is None) != (control_spend is None):
        raise ContractError("控制月和校准值必须成对提供")
    supplied: dict[str, int] = {}
    for month_key, spend in args.result:
        if month_key in supplied:
            raise ContractError(f"月份重复：{month_key}")
        if month_key not in months:
            raise ContractError(f"结果月份不在请求范围内：{month_key}")
        supplied[month_key] = spend

    if control_month in supplied and supplied[control_month] != control_spend:
        raise ContractError(
            f"控制月 {control_month} 应为 {control_spend}，"
            f"实际传入 {supplied[control_month]}；请重新检查日期、母游戏和区间汇总。"
        )

    rows: list[dict[str, object]] = []
    for month_key in months:
        date_start, date_end, ui_range = month_bounds(month_key)
        spend = supplied.get(month_key)
        rows.append(
            {
                "month": month_key,
                "date_start": date_start,
                "date_end": date_end,
                "ui_date_range": ui_range,
                "query_contract": {
                    "fixed_filters": VALIDATED_FIXED_FILTERS,
                    "dynamic_all_selections": DYNAMIC_ALL_SELECTIONS,
                    "date2_strategy": "preserve_current_full_material_output_range",
                },
                "spend": spend,
                "status": "user_supplied_value" if spend is not None else "missing",
                "source_type": (
                    "user_input" if spend is not None else None
                ),
            }
        )

    calibration_in_scope = control_month in months
    calibration_passed = supplied.get(control_month) == control_spend
    return {
        "request": {
            "project_alias": PROJECT_ALIAS,
            "project_field": PROJECT_FIELD,
            "project_label": PROJECT_LABEL,
            "project_id": PROJECT_ID,
            "start_month": args.start_month,
            "end_month": args.end_month,
            "grain": "calendar_month",
            "aggregation_method": "interval_total",
            "date_group_label": DATE_GROUP_LABEL,
            "date_group": DATE_GROUP_VALUE,
            "metric": "spend",
            "metric_location": "总计.花费",
            "unit": "CNY",
            "timezone": TIMEZONE,
        },
        "rows": rows,
        "calibration": {
            "month": control_month,
            "expected_spend": control_spend,
            "in_scope": calibration_in_scope,
            "passed": calibration_passed if calibration_in_scope else None,
        },
        "export_contract": {
            "precondition": "successful_query_with_current_filters",
            "endpoint_template": (
                "/marketng/?_c=adopenplatformSource&_a=index&ac=export&rand={info.rand}"
            ),
            "stale_filter_guard": "never_export_after_filter_change_before_query",
            "format": "backend_response_defined",
        },
        "observed_at": dt.datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds"),
    }


def live_request(month_key: str, material_range: str) -> dict[str, object]:
    _, _, ui_range = month_bounds(month_key)
    filters = {
        key: value
        for key, value in VALIDATED_FIXED_FILTERS.items()
        if key not in {"gid", "category", "date_group", "group"}
    }
    return {
        "id": month_key,
        "date": ui_range,
        "date2": material_range,
        "gid": [str(PROJECT_ID)],
        "date_group": DATE_GROUP_VALUE,
        "group": "mid",
        "filters": filters,
        "include": "summary",
        "expand_gid_dependencies": True,
        "expand_pcid": True,
    }


def build_live_payload(args: argparse.Namespace) -> dict[str, object]:
    months = list(iter_months(args.start_month, args.end_month))
    control_month = getattr(args, "control_month", None)
    control_spend = getattr(args, "control_spend", None)
    if (control_month is None) != (control_spend is None):
        raise ContractError("控制月和校准值必须成对提供")
    query_months = list(dict.fromkeys(([control_month] if control_month else []) + months))
    capture = load_capture()
    kwargs = {
        "transport": args.transport,
        "profile": args.profile,
        "cookie_file": args.cookie_file,
        "cookie_env": args.cookie_env,
        "timeout": args.timeout,
        "retries": args.retries,
        "concurrency": args.workers,
    }
    if args.state_file:
        kwargs["state_file"] = args.state_file
    batch = capture.run_batch(
        {"requests": [live_request(month, args.material_range) for month in query_months]},
        **kwargs,
    )
    by_month = {item.get("id"): item for item in batch.get("results") or []}
    control = by_month.get(control_month) or {}
    control_cost = (control.get("summary") or {}).get("cost")
    try:
        control_cost = int(float(str(control_cost).replace(",", "")))
    except (TypeError, ValueError):
        control_cost = None
    if control_month and (not control.get("ok") or control_cost != control_spend):
        raise ContractError(
            f"控制月 {control_month} 应为 {control_spend}，实际 {control_cost!r}；"
            "已停止整批，请核验日期、母游戏、动态全选和区间汇总口径。"
        )
    rows: list[dict[str, object]] = []
    for month in months:
        date_start, date_end, ui_range = month_bounds(month)
        item = by_month.get(month) or {}
        raw = (item.get("summary") or {}).get("cost")
        try:
            spend = int(float(str(raw).replace(",", ""))) if raw is not None else None
            if spend is not None and spend < 0:
                raise ValueError("花费不能为负数")
        except (TypeError, ValueError):
            spend = None
        confirmed = bool(item.get("ok")) and spend is not None
        rows.append(
            {
                "month": month,
                "date_start": date_start,
                "date_end": date_end,
                "ui_date_range": ui_range,
                "spend": spend if confirmed else None,
                "status": "confirmed_response" if confirmed else "missing",
                "source_type": "authenticated_dashboard_interval_query" if confirmed else None,
                "error": None if confirmed else (item.get("error") or "成功响应缺少 info.sum.cost"),
                "elapsed_ms": item.get("elapsed_ms"),
            }
        )
    payload = build_payload(argparse.Namespace(
        start_month=args.start_month,
        end_month=args.end_month,
        result=[(row["month"], row["spend"]) for row in rows if row["spend"] is not None],
    ))
    payload["rows"] = rows
    payload["ok"] = all(row["status"] == "confirmed_response" for row in rows)
    payload["request"]["material_range"] = args.material_range
    payload["calibration"] = {
        "month": control_month,
        "expected_spend": control_spend,
        "actual": control_cost,
        "in_scope": control_month is not None,
        "passed": True if control_month else None,
        "source": "user_supplied_control" if control_month else "not_configured",
    }
    payload["capture"] = {
        "transport": batch.get("transport"),
        "elapsed_ms": batch.get("elapsed_ms"),
        "concurrency": batch.get("concurrency"),
        "cache": batch.get("cache"),
        "query_count": len(query_months),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-month", required=True, help="YYYY-MM")
    parser.add_argument("--end-month", required=True, help="YYYY-MM")
    parser.add_argument(
        "--result",
        action="append",
        default=[],
        type=parse_result,
        metavar="YYYY-MM=SPEND",
        help="已从实时区间查询的总计→花费读取的精确结果；可重复。",
    )
    parser.add_argument("--material-range", required=True, help="明确本次素材产出边界，不使用历史默认日期")
    parser.add_argument("--control-month", default=None)
    parser.add_argument("--control-spend", type=int, default=None)
    parser.add_argument("--capture", action="store_true", help="通过统一只读入口实时抓取；不导出。")
    parser.add_argument("--transport", choices=("auto", "active", "direct"), default="auto")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--profile", default="Default")
    parser.add_argument("--cookie-file", default="")
    parser.add_argument("--cookie-env", default="RONGYAO_BACKEND_COOKIE")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    try:
        if args.capture and args.result:
            raise ContractError("--capture 与 --result 不能同时使用")
        payload = build_live_payload(args) if args.capture else build_payload(args)
    except (ContractError, argparse.ArgumentTypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok", True) else 2


if __name__ == "__main__":
    sys.exit(main())
