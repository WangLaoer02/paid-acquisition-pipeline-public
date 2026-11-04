#!/usr/bin/env python3
"""Build a deterministic 荣耀后台 火影 query-then-export contract."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys


DATE_GROUPS = {
    "day": "日",
    "week": "周",
    "month": "月",
    "quarter": "季",
    "tenyear": "区间汇总2",
}
GROUPS = {
    "mid": "素材维度",
    "material_serial_number": "素材编号",
    "demand_name": "需求人",
    "design_name": "设计师",
    "source_type": "一类",
    "source_direction": "二类",
    "region_type": "第二设计师",
    "source_ip": "ip",
    "role": "角色",
}
EXTRA_COLUMNS = {
    "clickCount": "点击",
    "pcids": "母渠道",
    "showCount": "展示",
}
FIRE_CATEGORIES = ["133", "145", "146", "147", "148", "163", "165", "166"]


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("日期必须使用 YYYY-MM-DD。") from error


def build(args: argparse.Namespace) -> dict[str, object]:
    if args.start_date > args.end_date:
        raise ValueError("开始日期不能晚于结束日期。")
    ui_range = (
        f"{args.start_date.strftime('%Y/%m/%d')}-"
        f"{args.end_date.strftime('%Y/%m/%d')}"
    )
    filters: dict[str, object] = {
        "date": ui_range,
        "gid": ["193"],
        "category": FIRE_CATEGORIES,
        "osid": "",
        "divide": "",
        "operation_client": ["1", "2", "3", "4", "5", "6", "7"],
        "design_name": [],
        "demand_name": [],
        "accountId": [],
        "date_group": args.date_group,
        "group": args.group,
        "self_tag": "",
        "keyword": "",
        "negative_keyword": "",
        "start_cost": "0",
        "end_cost": "999999999",
        "source_type": [],
        "source_direction": [],
        "role": [],
        "region_type": [],
        "custom_list": args.extra_column,
        "source_video_type": "1",
        "record_type": "3",
        "aweme_id": [],
        "big_aweme_id": [],
        "filter": "1",
        "weekday": "",
    }
    return {
        "project": {"alias": "火影", "field": "母游戏", "label": "忍界大战", "id": 193},
        "filters": filters,
        "labels": {
            "date_group": DATE_GROUPS[args.date_group],
            "group": GROUPS[args.group],
            "extra_columns": [EXTRA_COLUMNS[key] for key in args.extra_column],
        },
        "dynamic_all_selections": ["pkid", "pcid", "manager", "product_id"],
        "preserve": ["date2"],
        "dependency_order": [
            "gid",
            "category/pkid",
            "operation_client",
            "pcid",
            "accountId",
            "independent_filters",
        ],
        "actions": [
            "set_all_filters_without_querying",
            "query_once",
            "wait_for_refreshed_summary_and_count",
            "export_once_if_explicitly_requested",
        ],
        "export": {
            "endpoint_template": (
                "/marketng/?_c=adopenplatformSource&_a=index&ac=export&rand={info.rand}"
            ),
            "format": "backend_response_defined",
            "guard": "do_not_export_stale_query_session",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, type=parse_date)
    parser.add_argument("--end-date", required=True, type=parse_date)
    parser.add_argument("--date-group", choices=DATE_GROUPS, default="tenyear")
    parser.add_argument("--group", choices=GROUPS, default="mid")
    parser.add_argument(
        "--extra-column",
        choices=EXTRA_COLUMNS,
        action="append",
        default=[],
        help="可重复：clickCount、pcids、showCount。",
    )
    args = parser.parse_args()
    try:
        payload = build(args)
    except ValueError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
