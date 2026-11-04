#!/usr/bin/env python3
"""Count original materials for selected 荣耀素材编号 without retry storms."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None


TIMEZONE = "Asia/Shanghai"
READONLY_CAPTURE = Path(__file__).resolve().parents[2] / "rongyao-data-stack/scripts/readonly_capture.py"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
STATUS_PATH = CODEX_HOME / "state/rongyao-dashboard-filter-finder/original-last-run.json"
LOCK_PATH = Path(tempfile.gettempdir()) / "rongyao-dashboard-original-materials.lock"
PROJECTS: dict[str, dict[str, Any]] = {
    "火影": {"gids": ["193"], "labels": ["忍界大战(193)"]},
    "咒术": {"gids": ["197", "192"], "labels": ["新咒术师(197)", "最强咒术师(192)"]},
    "烈焰": {"gids": ["185"], "labels": ["烈焰之刃(185)"]},
}


class CaptureError(RuntimeError):
    """Controlled failure that must not trigger a request storm."""


def load_capture(path: Path = READONLY_CAPTURE):
    if not path.is_file():
        raise CaptureError(f"未找到统一只读抓取入口：{path}")
    spec = importlib.util.spec_from_file_location("rongyao_readonly_capture_originals", path)
    if spec is None or spec.loader is None:
        raise CaptureError(f"无法加载统一只读抓取入口：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("日期必须使用 YYYY-MM-DD。") from error


def extract_group_code(raw: Any) -> str:
    match = re.search(r"data-serial=[\"']([^\"']*)", str(raw or ""))
    return html.unescape(match.group(1)).strip().upper() if match else ""


def extract_material_names(raw: Any) -> list[str]:
    names = []
    for captured in re.findall(r"<li><a[^>]*>(.*?)</a>", str(raw or ""), flags=re.I | re.S):
        name = html.unescape(re.sub(r"<[^>]+>", "", captured)).strip()
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def repeated_code(name: str, code: str) -> bool:
    prefix = re.match(r"^\d{6}([A-Za-z]+)\d*", name)
    if not prefix or prefix.group(1).upper() != code:
        return False
    return re.search(
        rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])",
        name[prefix.end() :],
        flags=re.I,
    ) is not None


def classify_names(names: list[str], code: str) -> dict[str, int]:
    unique = list(dict.fromkeys(names))
    original = {name for name in unique if "原创" in name}
    repeated = {name for name in unique if repeated_code(name, code)}
    return {
        "candidate_material_count": len(unique),
        "original_marker_count": len(original),
        "repeated_code_count": len(repeated),
        "overlap_count": len(original & repeated),
        "matched_unique_count": len(original | repeated),
    }


def self_test() -> int:
    samples = [
        "260101ZX1-测试-原创-A",
        "260102ZX2-测试-ZX",
        "260103ZX3-测试-XGA",
        "260104WY1-测试-ZX",
    ]
    result = classify_names(samples, "ZX")
    expected = {
        "candidate_material_count": 4,
        "original_marker_count": 1,
        "repeated_code_count": 1,
        "overlap_count": 0,
        "matched_unique_count": 2,
    }
    ok = result == expected
    print(json.dumps({"ok": ok, "actual": result, "expected": expected}, ensure_ascii=False))
    return 0 if ok else 1


def write_status(payload: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def acquire_lock():
    handle = LOCK_PATH.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            if msvcrt is None:
                raise CaptureError("Windows 文件锁模块不可用。")
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            if fcntl is None:
                raise CaptureError("POSIX 文件锁模块不可用。")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError) as error:
        handle.close()
        raise CaptureError("已有原创素材抓取实例在运行；禁止叠加高成本查询。") from error
    return handle


def release_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    elif fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


def run_capture(args: argparse.Namespace) -> dict[str, Any]:
    capture = load_capture()
    gids = list(dict.fromkeys(gid for project in args.project for gid in PROJECTS[project]["gids"]))
    request = {
        "id": "original-materials",
        "date": f"{args.start_date:%Y/%m/%d}-{args.end_date:%Y/%m/%d}",
        "date2": args.material_range,
        "gid": gids,
        "date_group": "tenyear",
        "group": "material_serial_number",
        "filters": {
            "negative_keyword": "",
            "source_video_type": "1",
            "record_type": "3",
            "filter": "1",
            "pagesize": 20,
        },
        "include": "rows",
        "all_pages": True,
        "max_pages": args.max_pages,
        "max_rows": args.max_rows,
        "expand_gid_dependencies": True,
        "expand_pcid": True,
    }
    kwargs = {
        "transport": args.transport,
        "profile": args.profile,
        "cookie_file": args.cookie_file,
        "cookie_env": args.cookie_env,
        "timeout": args.timeout,
        "retries": 0,
        "concurrency": 1,
    }
    if args.state_file:
        kwargs["state_file"] = args.state_file
    batch = capture.run_batch({"requests": [request]}, **kwargs)
    item = (batch.get("results") or [{}])[0]
    if not item.get("ok"):
        raise CaptureError(item.get("error") or "高成本素材编号查询失败")
    query = item.get("query") or {}
    total_pages = int(query.get("totalpage") or 1)
    pages_completed = int(query.get("pages_completed") or 0)
    if pages_completed != total_pages:
        raise CaptureError(f"分页不完整：{pages_completed}/{total_pages}")
    wanted = set(args.code)
    by_code: dict[str, dict[str, int]] = {}
    for row in item.get("rows") or []:
        if not isinstance(row, dict):
            continue
        code = extract_group_code(row.get("material_serial_number"))
        if code in wanted:
            by_code[code] = classify_names(
                extract_material_names(row.get("material_serial_number")), code
            )
    missing_codes = sorted(wanted - set(by_code))
    if missing_codes:
        raise CaptureError("指定编号未在完整分页中找到：" + ",".join(missing_codes))
    totals = {
        key: sum(values[key] for values in by_code.values())
        for key in (
            "candidate_material_count",
            "original_marker_count",
            "repeated_code_count",
            "overlap_count",
            "matched_unique_count",
        )
    }
    return {
        "ok": True,
        "status": "confirmed_response",
        "request": {
            "date": request["date"],
            "material_output_date": args.material_range,
            "projects": args.project,
            "codes": args.code,
            "group": "material_serial_number",
            "concurrency": 1,
            "pagination": "single_submit_then_rand_reuse",
        },
        "distinct_code_count": len(by_code),
        "pages_expected": total_pages,
        "pages_completed": pages_completed,
        "blocker": None,
        "transport": batch.get("transport"),
        "elapsed_ms": batch.get("elapsed_ms"),
        "cache": batch.get("cache"),
        **totals,
        "by_code": by_code,
        "observed_at": dt.datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=parse_date)
    parser.add_argument("--end-date", type=parse_date)
    parser.add_argument("--material-range")
    parser.add_argument("--project", action="append", choices=PROJECTS)
    parser.add_argument("--code", action="append", help="素材编号；可重复。")
    parser.add_argument("--profile", default="Default")
    parser.add_argument(
        "--cookie-file",
        default="",
        help="可选的临时 Cookie 文件；读取权限必须限制为当前用户。",
    )
    parser.add_argument(
        "--backend-helper",
        default="",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--preflight-timeout", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--transport", choices=("auto", "active", "direct"), default="auto")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--cookie-env", default="RONGYAO_BACKEND_COOKIE")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.status:
        if not STATUS_PATH.exists():
            print(json.dumps({"ok": False, "status": "never_run"}, ensure_ascii=False))
            return 1
        print(STATUS_PATH.read_text(encoding="utf-8"), end="")
        return 0
    if not args.start_date or not args.end_date or not args.project or not args.code or not args.material_range:
        parser.error("必须提供日期范围、--material-range、至少一个项目和至少一个素材编号。")
    if args.start_date > args.end_date:
        parser.error("开始日期不能晚于结束日期。")
    args.project = list(dict.fromkeys(args.project))
    args.code = list(dict.fromkeys(code.strip().upper() for code in args.code if code.strip()))
    if not args.code:
        parser.error("素材编号不能为空。")
    lock = None
    try:
        lock = acquire_lock()
        payload = run_capture(args)
        write_status(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except CaptureError as error:
        payload = {
            "ok": False,
            "status": "backend_unhealthy",
            "blocker": str(error),
            "pages_expected": None,
            "pages_completed": 0,
            "observed_at": dt.datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds"),
        }
        write_status(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    finally:
        if lock is not None:
            release_lock(lock)


if __name__ == "__main__":
    sys.exit(main())
