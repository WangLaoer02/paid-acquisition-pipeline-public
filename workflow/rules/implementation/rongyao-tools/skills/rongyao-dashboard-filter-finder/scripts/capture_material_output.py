#!/usr/bin/env python3
"""Capture monthly 荣耀素材产出 total counts through the authenticated backend."""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")


TIMEZONE = "Asia/Shanghai"
READONLY_CAPTURE = Path(__file__).resolve().parents[2] / "rongyao-data-stack/scripts/readonly_capture.py"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
STATUS_PATH = CODEX_HOME / "state/rongyao-dashboard-filter-finder/material-output-last-run.json"
PROJECTS: dict[str, dict[str, Any]] = {
    "火影": {"gids": ["193"], "labels": ["忍界大战(193)"]},
    "咒术": {"gids": ["197", "192"], "labels": ["新咒术师(197)", "最强咒术师(192)"]},
    "烈焰": {"gids": ["185"], "labels": ["烈焰之刃(185)"]},
}


class CaptureError(RuntimeError):
    """Raised when the live query cannot satisfy the material-output contract."""


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
        raise CaptureError("开始月份不能晚于结束月份。")
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def month_date_range(month_key: str) -> str:
    year, month = parse_month(month_key)
    start = dt.date(year, month, 1)
    end = dt.date(year, month, calendar.monthrange(year, month)[1])
    return f"{start:%Y/%m/%d}-{end:%Y/%m/%d}"


def load_capture(path: Path = READONLY_CAPTURE):
    if not path.is_file():
        raise CaptureError(f"未找到统一只读抓取入口：{path}")
    spec = importlib.util.spec_from_file_location("rongyao_readonly_capture_material_output", path)
    if spec is None or spec.loader is None:
        raise CaptureError(f"无法加载统一只读抓取入口：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_request(project: str, month_key: str, material_range: str) -> dict[str, Any]:
    observe_range = month_date_range(month_key)
    return {
        "id": f"{month_key}|{project}",
        "date": observe_range,
        "date2": material_range,
        "gid": PROJECTS[project]["gids"],
        "date_group": "tenyear",
        "group": "mid",
        "filters": {
            "negative_keyword": "",
            "source_video_type": "1",
            "record_type": "3",
            "filter": "1",
        },
        "include": "summary",
        "expand_gid_dependencies": True,
        "expand_pcid": True,
    }


def convert_result(item: dict[str, Any], project: str, month_key: str, material_range: str = "未提供") -> dict[str, Any]:
    summary = item.get("summary") or {}
    raw_count = summary.get("count")
    error = item.get("error")
    try:
        count = int(raw_count) if raw_count is not None else None
        if count is not None and count < 0:
            raise ValueError("总数量不能为负数")
    except (TypeError, ValueError) as exc:
        count = None
        error = str(exc)
    confirmed = bool(item.get("ok")) and count is not None
    return {
        "month": month_key,
        "project": project,
        "project_labels": PROJECTS[project]["labels"],
        "material_output_date": material_range,
        "observation_date": month_date_range(month_key),
        "material_output_count": count if confirmed else None,
        "status": "confirmed_response" if confirmed else "missing",
        "error": None if confirmed else (error or "成功响应缺少 info.sum.count（总数量）"),
        "metric_location": "info.sum.count",
        "unit": "条",
        "transport": item.get("transport"),
        "elapsed_ms": item.get("elapsed_ms"),
    }


def write_status(payload: dict[str, Any], output_path: str) -> None:
    rows = payload.get("rows") or []
    status = {
        "last_run": payload.get("observed_at"),
        "success_count": sum(row.get("status") == "confirmed_response" for row in rows),
        "failure_count": sum(row.get("status") != "confirmed_response" for row in rows),
        "output_path": output_path or None,
        "calibration": payload.get("calibration"),
        "known_blockers": sorted({row.get("error") for row in rows if row.get("error")}),
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "抓取口径：日期=自然月｜素材产出日期=后台默认全范围（不按月筛选）｜否定词留空｜视频｜区间汇总｜总数量｜条",
        "",
        "| 月份 | 项目 | 素材产出日期 | 日期观察窗口 | 产出数量（条） | 状态 |",
        "|---|---|---|---|---:|---|",
    ]
    for row in payload["rows"]:
        value = row["material_output_count"] if row["material_output_count"] is not None else "—"
        lines.append(
            f"| {row['month']} | {row['project']} | {row['material_output_date']} | "
            f"{row['observation_date']} | {value} | {row['status']} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-month", help="YYYY-MM")
    parser.add_argument("--end-month", help="YYYY-MM")
    parser.add_argument("--project", action="append", choices=PROJECTS, help="可重复；不允许省略后猜项目。")
    parser.add_argument("--material-range")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retries", type=int, default=0, help="必须为0；提交后禁止自动重试。")
    parser.add_argument("--profile", default="Default", help="Chrome profile name")
    parser.add_argument(
        "--cookie-file",
        default="",
        help="可选的临时 Cookie 文件；权限必须限制为当前用户。",
    )
    parser.add_argument(
        "--backend-helper",
        default="",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--transport", choices=("auto", "active", "direct"), default="auto")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--cookie-env", default="RONGYAO_BACKEND_COOKIE")
    parser.add_argument("--output", default="", help="可选 JSON 输出路径。")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--status", action="store_true", help="只读取上次运行状态。")
    args = parser.parse_args()

    if args.status:
        if not STATUS_PATH.exists():
            print(json.dumps({"ok": False, "error": "尚无运行状态"}, ensure_ascii=False))
            return 1
        print(STATUS_PATH.read_text(encoding="utf-8"), end="")
        return 0
    if not args.start_month or not args.end_month or not args.project or not args.material_range:
        parser.error("抓取时必须提供 --start-month、--end-month、--material-range 和至少一个 --project。")
    if args.workers < 1 or args.workers > 6:
        parser.error("--workers 必须在 1 到 6 之间。")
    if args.retries != 0:
        parser.error("--retries 必须为0。")
    args.project = list(dict.fromkeys(args.project))

    material_range = args.material_range
    try:
        months = list(iter_months(args.start_month, args.end_month))
        jobs = [(project, month) for month in months for project in args.project]
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
            {"requests": [build_request(project, month, material_range) for project, month in jobs]},
            **kwargs,
        )
        by_id = {item.get("id"): item for item in batch.get("results") or []}
        rows = [
            convert_result(by_id.get(f"{month}|{project}", {}), project, month, material_range)
            for project, month in jobs
        ]
        project_order = {name: index for index, name in enumerate(args.project)}
        rows.sort(key=lambda row: (row["month"], project_order[row["project"]]))

        payload = {
            "ok": all(row["status"] == "confirmed_response" for row in rows),
            "request": {
                "start_month": args.start_month,
                "end_month": args.end_month,
                "projects": args.project,
                "metric": "material_output_count",
                "metric_location": "info.sum.count",
                "unit": "条",
                "material_output_window": material_range,
                "material_output_window_strategy": "explicit_material_range",
                "observation_window": "calendar_month",
                "negative_keyword": "",
                "source_video_type": "1",
                "date_group": "tenyear",
                "group": "mid",
                "timezone": TIMEZONE,
            },
            "calibration": {"passed": None, "source": "not_configured"},
            "rows": rows,
            "observed_at": dt.datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds"),
            "capture": {
                "transport": batch.get("transport"),
                "elapsed_ms": batch.get("elapsed_ms"),
                "concurrency": batch.get("concurrency"),
                "cache": batch.get("cache"),
            },
        }
        if args.output:
            output_path = Path(args.output).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_status(payload, args.output)
        print(render_markdown(payload) if args.format == "markdown" else json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 2
    except CaptureError as error:
        failure = {
            "ok": False,
            "observed_at": dt.datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds"),
            "error": str(error),
        }
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
