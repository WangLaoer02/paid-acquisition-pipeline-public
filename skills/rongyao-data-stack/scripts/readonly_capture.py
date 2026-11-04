#!/usr/bin/env python3
"""Universal read-only 荣耀 backend query transport.

The default transport reuses or restarts one credential-isolated Chrome profile.
The reviewed disk-Cookie helper remains an explicit compatibility path.  This
module never persists credentials and never calls a write, reset, upload, or
delete API.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import concurrent.futures
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")


SCRIPT_DIR = Path(__file__).resolve().parent
ACTIVE_SESSION_PATH = SCRIPT_DIR / "active_session_cli.py"
BUNDLED_HELPER_PATH = SCRIPT_DIR / "backend_export_cli.py"
DEFAULT_STATE = Path.home() / ".codex/state/rongyao-active-session/session.json"
DEFAULT_SESSION_PROFILE = Path.home() / ".codex/browser-profiles/rongyao-weekly-market"
DEFAULT_MATERIAL_RANGE = ""  # Callers must declare the material-date boundary.
DEFAULT_HOST = "data.houtai.cn.sy.backend.example.invalid"
DEFAULT_MARKET_PATH = "/marketng/?_c=adopenplatformSource&_a=index"
HIGH_COST_GROUPS = {"material_serial_number"}
ALLOWED_FILTERS = {
    "date", "date2", "gid", "category", "pkid", "osid", "divide",
    "operation_client", "pcid", "manager", "product_id", "design_name",
    "demand_name", "accountId", "date_group", "group", "self_tag",
    "keyword", "negative_keyword", "start_cost", "end_cost", "source_type",
    "source_direction", "role", "region_type", "custom_list",
    "source_video_type", "record_type", "aweme_id", "big_aweme_id", "filter",
    "weekday", "page", "pagesize", "sort", "desc", "rand_num",
}
DATE_RANGE_RE = re.compile(r"^\d{4}/\d{2}/\d{2}-\d{4}/\d{2}/\d{2}$")


class CaptureError(RuntimeError):
    """Controlled read-only query failure."""


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CaptureError(f"无法加载只读后台模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def csv_value(value: Any) -> Any:
    return ",".join(str(item) for item in value) if isinstance(value, list) else value


def list_value(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    source = value if isinstance(value, list) else str(value).split(",")
    return list(dict.fromkeys(str(item).strip() for item in source if str(item).strip()))


def parse_date_range(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not DATE_RANGE_RE.fullmatch(value):
        raise CaptureError(f"{label} 必须使用 YYYY/MM/DD-YYYY/MM/DD")
    left, right = value.split("-", 1)
    try:
        dt.datetime.strptime(left, "%Y/%m/%d")
        dt.datetime.strptime(right, "%Y/%m/%d")
    except ValueError as error:
        raise CaptureError(f"{label}包含无效日期") from error
    if left > right:
        raise CaptureError(f"{label}开始日期不能晚于结束日期")
    return value


def normalized_request(raw: dict[str, Any], index: int = 0) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CaptureError(f"请求 #{index + 1} 不是对象")
    search = dict(raw.get("search") or {})
    for key in raw.get("filters") or {}:
        if key in search:
            raise CaptureError(f"筛选字段重复：{key}")
        search[key] = raw["filters"][key]
    unknown = sorted(set(search) - ALLOWED_FILTERS)
    if unknown:
        raise CaptureError("不允许的筛选字段：" + ",".join(unknown))
    date_range = raw.get("date") or search.get("date")
    material_range = raw.get("date2") or search.get("date2") or DEFAULT_MATERIAL_RANGE
    search["date"] = parse_date_range(date_range, "投放日期")
    search["date2"] = parse_date_range(material_range, "素材产出日期")
    gids = list_value(raw.get("gid") or search.get("gid"))
    if not gids or any(not item.isdigit() for item in gids):
        raise CaptureError("gid 必须是至少一个数字 ID")
    search.update(
        {
            "gid": gids,
            "date_group": str(raw.get("date_group") or search.get("date_group") or "tenyear"),
            "group": str(raw.get("group") or search.get("group") or "mid"),
            "source_video_type": str(search.get("source_video_type", "1")),
            "record_type": str(search.get("record_type", "3")),
            "filter": str(search.get("filter", "1")),
            "page": 1,
            "rand_num": "",
        }
    )
    include = str(raw.get("include") or "summary")
    if include not in {"summary", "rows"}:
        raise CaptureError("include 只能是 summary 或 rows")
    all_pages = bool(raw.get("all_pages", False))
    max_pages = int(raw.get("max_pages") or 20)
    max_rows = int(raw.get("max_rows") or 5000)
    if not 1 <= max_pages <= 200:
        raise CaptureError("max_pages 必须在 1-200")
    if not 1 <= max_rows <= 100000:
        raise CaptureError("max_rows 必须在 1-100000")
    high_cost = search["group"] in HIGH_COST_GROUPS
    if high_cost and include != "rows":
        include = "rows"
    return {
        "id": str(raw.get("id") or f"request-{index + 1}"),
        "search": search,
        "include": include,
        "all_pages": all_pages,
        "max_pages": max_pages,
        "max_rows": max_rows,
        "expand_gid_dependencies": bool(raw.get("expand_gid_dependencies", True)),
        "expand_pcid": bool(raw.get("expand_pcid", True)),
        "high_cost": high_cost,
    }


def normalize_batch(raw: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = raw.get("requests") if isinstance(raw, dict) else raw
    if not isinstance(source, list) or not source:
        raise CaptureError("批量请求必须包含非空 requests 数组")
    requests = [normalized_request(item, index) for index, item in enumerate(source)]
    if any(item["high_cost"] for item in requests) and len(requests) > 1:
        raise CaptureError("高成本素材编号查询必须单独运行，禁止与其他请求批量混跑")
    ids = [item["id"] for item in requests]
    signatures = [json.dumps(item["search"], sort_keys=True, ensure_ascii=False) for item in requests]
    if len(set(ids)) != len(ids) or len(set(signatures)) != len(signatures):
        raise CaptureError("重复请求 ID 或相同筛选；提交前已停止")
    return requests


def safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SystemExit as error:
        raise CaptureError(str(error)) from error
    except CaptureError:
        raise
    except Exception as error:
        raise CaptureError(str(error)) from error


def read_json_response(response) -> dict[str, Any]:
    raw = response.read().decode("utf-8", errors="replace")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CaptureError("荣耀后台返回非 JSON；未输出响应正文") from error
    if not isinstance(result, dict):
        raise CaptureError("荣耀后台查询响应不是对象")
    if not result.get("status"):
        raise CaptureError("荣耀后台查询返回 status=false")
    return result


def compact_sum(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    # Summary fields are backend aggregates, not credentials. Preserve them for
    # broad query coverage while dropping nested detail collections.
    return {str(key): item for key, item in value.items() if not isinstance(item, (dict, list))}


def option_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    info = value.get("info") if isinstance(value.get("info"), dict) else {}
    candidates = [
        info.get("category_list"), info.get("pkid_list"), info.get("pcid_list"), info, value
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        keys = [str(key) for key in candidate if str(key).isdigit()]
        if keys:
            return keys
    return []


def rand_evidence(value: Any) -> dict[str, Any]:
    text = str(value or "")
    return {
        "ready": bool(text),
        "session_fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else None,
    }


class DirectContext:
    """One-process direct context with bounded run-local metadata caches."""

    def __init__(
        self,
        profile: str,
        cookie_file: str,
        cookie_env: str,
        host: str,
        market_path: str,
        timeout: int,
    ) -> None:
        self.helper = load_module("rongyao_readonly_backend", BUNDLED_HELPER_PATH)
        self.host = host
        self.timeout = timeout
        self.cookie = safe_call(
            self.helper.backend_cookie_header,
            cookie_file=cookie_file,
            cookie_env=cookie_env,
            profile=profile,
            host=host,
        )
        with safe_call(
            self.helper.backend_http_request,
            host,
            market_path,
            self.cookie,
            timeout=timeout,
            accept="text/html,application/xhtml+xml",
        ) as response:
            html = response.read().decode("utf-8", errors="replace")
        self.page = safe_call(self.helper.parse_backend_page_config, html)
        self.base = self.helper.backend_default_search(self.page["config"], self.page["initRand"])
        self._dependency_cache: dict[tuple[str, str], list[str]] = {}
        self._cache_lock = threading.Lock()
        self.cache_hits = 0
        self.cache_misses = 0

    def dependency(self, kind: str, value: str) -> list[str]:
        key = (kind, value)
        with self._cache_lock:
            if key in self._dependency_cache:
                self.cache_hits += 1
                return list(self._dependency_cache[key])
        if kind == "category":
            path = f"/market/api/ApiGetCategory.php?gid={value}"
        elif kind == "pkid":
            path = f"/market/api/ApiGetAllPkList.php?gid={value}"
        elif kind == "pcid":
            values = list_value(value)
            result = safe_call(
                self.helper.backend_selected_pcids,
                self.host,
                self.cookie,
                values,
                timeout=self.timeout,
            )
            with self._cache_lock:
                if len(self._dependency_cache) < 64:
                    self._dependency_cache[key] = list(result)
                self.cache_misses += 1
            return list(result)
        else:
            raise CaptureError(f"未知依赖类型：{kind}")
        result = safe_call(self.helper.backend_json, self.host, path, self.cookie, timeout=self.timeout) or {}
        values = option_keys(result)
        with self._cache_lock:
            if len(self._dependency_cache) < 64:
                self._dependency_cache[key] = values
            self.cache_misses += 1
        return list(values)

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        search = dict(self.base)
        search.update(request["search"])
        gids = list_value(search["gid"])
        if request["expand_gid_dependencies"]:
            if not request["search"].get("category"):
                search["category"] = list(
                    dict.fromkeys(item for gid in gids for item in self.dependency("category", gid))
                )
            if not request["search"].get("pkid"):
                search["pkid"] = list(
                    dict.fromkeys(item for gid in gids for item in self.dependency("pkid", gid))
                )
        if request["expand_pcid"] and search.get("operation_client") and not request["search"].get("pcid"):
            cache_key = ",".join(list_value(search["operation_client"]))
            search["pcid"] = self.dependency("pcid", cache_key)
        return search

    def query_page(self, search: dict[str, Any], submit: bool) -> dict[str, Any]:
        post = {f"search[{key}]": csv_value(value) for key, value in search.items()}
        post["search[page_component_version]"] = 1
        if submit:
            post["search[submit]"] = 1
        with safe_call(
            self.helper.backend_http_request,
            self.host,
            self.page["getDataUrl"],
            self.cookie,
            data=post,
            timeout=self.timeout,
            accept="application/json",
        ) as response:
            return read_json_response(response)


def result_from_pages(
    request: dict[str, Any], search: dict[str, Any], first: dict[str, Any], page_loader
) -> dict[str, Any]:
    started = time.perf_counter()
    info = first.get("info") or {}
    rand = str(info.get("rand") or "")
    total_pages = int(info.get("totalpage") or 1)
    if total_pages < 1:
        total_pages = 1
    if request["all_pages"] and total_pages > request["max_pages"]:
        raise CaptureError(f"分页数 {total_pages} 超出安全上限 {request['max_pages']}")
    rows: list[Any] = []
    pages_completed = 0
    if request["include"] == "rows":
        rows.extend(info.get("data") or [])
    pages_completed = 1
    if len(rows) > request["max_rows"]:
        raise CaptureError("明细行数超过安全上限")
    if request["all_pages"]:
        if not rand:
            raise CaptureError("首次查询未返回 rand，禁止无会话翻页")
        for page_number in range(2, total_pages + 1):
            page = page_loader(page_number, rand)
            page_info = page.get("info") or {}
            returned_rand = str(page_info.get("rand") or rand)
            if returned_rand != rand:
                raise CaptureError("分页 rand 发生变化，拒绝混合查询会话")
            rows.extend(page_info.get("data") or [])
            pages_completed += 1
            if len(rows) > request["max_rows"]:
                raise CaptureError(f"明细行数超过安全上限 {request['max_rows']}")
    identity = {
        "entry": "新素材2.0",
        "gid": list_value(search.get("gid")),
        "date": search.get("date"),
        "date2": search.get("date2"),
        "date_group": search.get("date_group"),
        "group": search.get("group"),
        "source_video_type": search.get("source_video_type"),
        "record_type": search.get("record_type"),
        "filter": search.get("filter"),
        "filters": {
            key: search.get(key)
            for key in ("category", "source_type", "source_direction", "role", "self_tag", "keyword", "negative_keyword")
            if search.get(key) not in (None, "", [])
        },
    }
    return {
        "id": request["id"],
        "ok": True,
        "status": "confirmed_response",
        "identity": identity,
        "summary": compact_sum(info.get("sum")),
        "query": {
            "count": info.get("count"),
            "totalpage": total_pages,
            "pagesize": info.get("pagesize"),
            "pages_completed": pages_completed,
        },
        "rows": rows if request["include"] == "rows" else None,
        "export_preflight": rand_evidence(rand),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def run_direct_request(context: DirectContext, request: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    search = context.prepare(request)
    first = context.query_page(search, submit=True)

    def load(page_number: int, rand: str) -> dict[str, Any]:
        paging = dict(search)
        paging.update({"page": page_number, "rand_num": rand})
        return context.query_page(paging, submit=False)

    result = result_from_pages(request, search, first, load)
    result["transport"] = "direct_disk_cookie"
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


def transient_error(message: str) -> bool:
    text = message.lower()
    return any(token in text for token in ("timed out", "timeout", "http 408", "http 429", "http 500", "http 502", "http 503", "http 504"))


def with_retries(fn, request: dict[str, Any], retries: int) -> dict[str, Any]:
    attempts = 0
    allowed = 0  # A timeout after dispatch does not establish that the server did no work.
    while True:
        try:
            result = fn()
            result["attempts"] = attempts + 1
            return result
        except CaptureError as error:
            if attempts >= allowed or not transient_error(str(error)):
                raise
            attempts += 1
            time.sleep(min(2.0, 0.25 * (2**attempts)))


def direct_batch(
    requests: list[dict[str, Any]],
    *,
    profile: str,
    cookie_file: str,
    cookie_env: str,
    host: str,
    market_path: str,
    timeout: int,
    retries: int,
    concurrency: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    context = DirectContext(profile, cookie_file, cookie_env, host, market_path, timeout)

    def execute(request: dict[str, Any]) -> dict[str, Any]:

        def once() -> dict[str, Any]:
            item_started = time.perf_counter()
            search = context.prepare(request)
            first = context.query_page(search, submit=True)

            def load(page_number: int, rand: str) -> dict[str, Any]:
                paging = dict(search)
                paging.update({"page": page_number, "rand_num": rand})
                return context.query_page(paging, submit=False)

            result = result_from_pages(request, search, first, load)
            result["transport"] = "direct_disk_cookie"
            result["elapsed_ms"] = round((time.perf_counter() - item_started) * 1000, 2)
            return result

        try:
            return with_retries(once, request, retries)
        except CaptureError as error:
            return {
                "id": request["id"], "ok": False, "status": "missing",
                "error": str(error), "summary": None, "rows": None, "attempts": 1, "replayed": False,
            }

    workers = 1 if any(item["high_cost"] for item in requests) else min(max(1, concurrency), 6, len(requests))
    if workers == 1:
        results = [execute(item) for item in requests]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(execute, requests))
    return {
        "ok": all(item.get("ok") for item in results),
        "transport": "direct_disk_cookie",
        "results": results,
        "cache": {
            "scope": "single_run_metadata_only",
            "max_entries": 64,
            "hits": context.cache_hits,
            "misses": context.cache_misses,
        },
        "concurrency": workers,
        "page_defaults": {"date2": context.base.get("date2")},
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def active_status(state_file: Path) -> dict[str, Any]:
    module = load_module("rongyao_active_session_readonly", ACTIVE_SESSION_PATH)
    return module.session_status(state_file)


def active_ensure(state_file: Path, profile_dir: Path) -> dict[str, Any]:
    module = load_module("rongyao_active_session_readonly", ACTIVE_SESSION_PATH)
    return module.ensure_active_session(state_file, profile_dir)


def active_batch(
    requests: list[dict[str, Any]],
    *,
    state_file: Path,
    market_path: str,
    timeout: int,
    retries: int,
    concurrency: int,
) -> dict[str, Any]:
    module = load_module("rongyao_active_session_readonly", ACTIVE_SESSION_PATH)
    payload = {
        "version": 1,
        "requests": requests,
        "concurrency": 1 if any(item["high_cost"] for item in requests) else min(max(1, concurrency), 6),
        "timeout_ms": timeout * 1000,
        "retries": retries,
    }
    with tempfile.TemporaryDirectory(prefix="rongyao-readonly-") as directory:
        request_file = Path(directory) / "requests.json"
        request_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        try:
            result = module.run_node(
                "query",
                "--state-file", str(state_file),
                "--request-file", str(request_file),
                "--market-path", market_path,
                "--timeout", str(timeout * 1000),
                timeout=timeout * max(1, len(requests)) + 30,
            )
        except RuntimeError as error:
            detail = str(error)
            if "LOGIN_REQUIRED" in detail:
                raise CaptureError(
                    "专用 Chrome 尚未登录荣耀后台；请在已打开的专用窗口手动完成登录并保持窗口运行"
                ) from error
            if "PAGE_CONFIG_CHANGED" in detail:
                raise CaptureError("荣耀后台页面配置已变化；已停止查询，禁止使用旧字段猜测") from error
            if any(token in detail for token in ("timed out", "HTTP_504", "QUERY_STATUS_FALSE")):
                raise CaptureError("荣耀后台查询超时或服务异常；本批未跨通道重放") from error
            raise CaptureError(detail[-1000:]) from error
    result["transport"] = "active_chrome_page_context"
    return result


def run_batch(
    raw: dict[str, Any] | list[dict[str, Any]],
    *,
    transport: str = "auto",
    state_file: str = str(DEFAULT_STATE),
    session_profile_dir: str = str(DEFAULT_SESSION_PROFILE),
    auto_recover: bool = True,
    profile: str = "Default",
    cookie_file: str = "",
    cookie_env: str = "RONGYAO_BACKEND_COOKIE",
    host: str = DEFAULT_HOST,
    market_path: str = DEFAULT_MARKET_PATH,
    timeout: int = 180,
    retries: int = 0,
    concurrency: int = 4,
) -> dict[str, Any]:
    requests = normalize_batch(raw)
    if not 1 <= concurrency <= 6:
        raise CaptureError("concurrency 必须在 1-6")
    if not 5 <= timeout <= 600:
        raise CaptureError("timeout 必须在 5-600 秒")
    if retries != 0:
        raise CaptureError("提交后禁止自动重试；retries 必须为 0")
    state = Path(state_file).expanduser().resolve()
    if transport in {"auto", "active"}:
        status = active_status(state)
        if (
            not status.get("active")
            and auto_recover
            and status.get("reason") in {"state_missing", "process_missing"}
        ):
            try:
                status = active_ensure(
                    state,
                    Path(session_profile_dir).expanduser().resolve(),
                )
            except RuntimeError as error:
                raise CaptureError(str(error)) from error
        if status.get("active"):
            return active_batch(
                requests,
                state_file=state,
                market_path=market_path,
                timeout=timeout,
                retries=retries,
                concurrency=concurrency,
            )
        if status.get("reason") in {"devtools_unreachable", "status_unavailable"}:
            raise CaptureError("专用会话连接状态未知；停止，不跨通道重放")
        if transport == "active":
            raise CaptureError(
                "专用 Chrome 会话未运行；默认自动恢复已被关闭，可执行 "
                "active_session_cli.py backend-ensure"
            )
    if transport not in {"auto", "direct"}:
        raise CaptureError("transport 只能是 auto、active 或 direct")
    return direct_batch(
        requests,
        profile=profile,
        cookie_file=cookie_file,
        cookie_env=cookie_env,
        host=host,
        market_path=market_path,
        timeout=timeout,
        retries=retries,
        concurrency=concurrency,
    )


def parse_filter(value: str) -> tuple[str, Any]:
    key, separator, raw = value.partition("=")
    if not separator or key not in ALLOWED_FILTERS:
        raise argparse.ArgumentTypeError("--filter 必须使用允许的 KEY=VALUE")
    raw = raw.strip()
    if raw.startswith(("[", "{", '"')):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise argparse.ArgumentTypeError(f"筛选 JSON 无效：{error}") from error
    elif "," in raw:
        parsed = list_value(raw)
    else:
        parsed = raw
    return key, parsed


def query_request(args: argparse.Namespace) -> dict[str, Any]:
    filters = dict(args.filter)
    for key, values in (
        ("role", args.role), ("source_type", args.source_type),
        ("source_direction", args.source_direction), ("category", args.category),
    ):
        if values:
            filters[key] = values
    if args.self_tag:
        filters["self_tag"] = args.self_tag
    if args.keyword:
        filters["keyword"] = args.keyword
    return {
        "id": args.id or "query-1",
        "date": args.date_range,
        "date2": args.material_range,
        "gid": args.gid,
        "date_group": args.date_group,
        "group": args.group,
        "filters": filters,
        "include": "rows" if args.rows or args.all_pages else "summary",
        "all_pages": args.all_pages,
        "max_pages": args.max_pages,
        "max_rows": args.max_rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    query = sub.add_parser("query", help="执行一次已定义的只读查询")
    query.add_argument("--id", default="")
    query.add_argument("--date-range", required=True)
    query.add_argument("--material-range", required=True)
    query.add_argument("--gid", action="append", required=True)
    query.add_argument("--date-group", default="tenyear")
    query.add_argument("--group", default="mid")
    query.add_argument("--filter", action="append", default=[], type=parse_filter)
    query.add_argument("--role", action="append", default=[])
    query.add_argument("--source-type", action="append", default=[])
    query.add_argument("--source-direction", action="append", default=[])
    query.add_argument("--category", action="append", default=[])
    query.add_argument("--self-tag", default="")
    query.add_argument("--keyword", default="")
    query.add_argument("--rows", action="store_true")
    query.add_argument("--all-pages", action="store_true")
    query.add_argument("--max-pages", type=int, default=20)
    query.add_argument("--max-rows", type=int, default=5000)
    batch = sub.add_parser("batch", help="在一次页面初始化中运行批量只读查询")
    batch.add_argument("--request-file", required=True)
    for target in (query, batch):
        target.add_argument("--transport", choices=("auto", "active", "direct"), default="auto")
        target.add_argument("--state-file", default=str(DEFAULT_STATE))
        target.add_argument("--session-profile-dir", default=str(DEFAULT_SESSION_PROFILE))
        target.add_argument("--no-auto-recover", action="store_false", dest="auto_recover")
        target.set_defaults(auto_recover=True)
        target.add_argument("--profile", default="Default")
        target.add_argument("--cookie-file", default="")
        target.add_argument("--cookie-env", default="RONGYAO_BACKEND_COOKIE")
        target.add_argument("--host", default=DEFAULT_HOST)
        target.add_argument("--market-path", default=DEFAULT_MARKET_PATH)
        target.add_argument("--timeout", type=int, default=180)
        target.add_argument("--retries", type=int, default=0)
        target.add_argument("--concurrency", type=int, default=4)
        target.add_argument("--output", default="")
        target.add_argument("--format", choices=("json", "text"), default="json")
    return parser


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"ok={str(bool(payload.get('ok'))).lower()}",
        f"transport={payload.get('transport')}",
        f"requests={len(payload.get('results') or [])}",
        f"elapsed_ms={payload.get('elapsed_ms')}",
    ]
    for item in payload.get("results") or []:
        lines.append(
            f"{item.get('id')}: status={item.get('status')} count={(item.get('query') or {}).get('count')} "
            f"cost={(item.get('summary') or {}).get('cost')} total={(item.get('summary') or {}).get('count')}"
        )
    return "\n".join(lines)


def write_result(output: Path, payload: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    try:
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "query":
            raw: dict[str, Any] | list[dict[str, Any]] = {"requests": [query_request(args)]}
        else:
            raw = json.loads(Path(args.request_file).expanduser().read_text(encoding="utf-8"))
        payload = run_batch(
            raw,
            transport=args.transport,
            state_file=args.state_file,
            session_profile_dir=args.session_profile_dir,
            auto_recover=args.auto_recover,
            profile=args.profile,
            cookie_file=args.cookie_file,
            cookie_env=args.cookie_env,
            host=args.host,
            market_path=args.market_path,
            timeout=args.timeout,
            retries=args.retries,
            concurrency=args.concurrency,
        )
        if args.output:
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            write_result(output, payload)
        print(render_text(payload) if args.format == "text" else json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 2
    except (CaptureError, RuntimeError, OSError, json.JSONDecodeError) as error:
        failure = {"ok": False, "status": "blocked", "error": str(error), "replayed": False}
        if args.output:
            write_result(Path(args.output).expanduser().resolve(), failure)
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
