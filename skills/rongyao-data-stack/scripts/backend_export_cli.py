#!/usr/bin/env python3
"""Minimal credential-free 荣耀 backend export helper for portable Codex Skills."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")


BACKEND_LOGIN_ORIGIN = os.environ.get("RONGYAO_LOGIN_ORIGIN", "http://power.houtai.backend.example.invalid/")
BACKEND_DIRECT_HOST = os.environ.get("RONGYAO_BACKEND_HOST", "data.houtai.cn.sy.backend.example.invalid")
BACKEND_DIRECT_MARKET_PATH = os.environ.get(
    "RONGYAO_BACKEND_MARKET_PATH",
    "/marketng/?_c=adopenplatformSource&_a=index",
)
BACKEND_DIRECT_PROFILE = os.environ.get("RONGYAO_BACKEND_CHROME_PROFILE", "Default")
BACKEND_DIRECT_COOKIE_ENV = os.environ.get("RONGYAO_BACKEND_COOKIE_ENV", "RONGYAO_BACKEND_COOKIE")
BACKEND_DIRECT_GID = os.environ.get("RONGYAO_BACKEND_GID", "193")
BACKEND_DIRECT_DATE_GROUP = os.environ.get("RONGYAO_BACKEND_DATE_GROUP", "tenyear")
BACKEND_DIRECT_GROUP = os.environ.get("RONGYAO_BACKEND_GROUP", "mid")
BACKEND_DOWNLOAD_DIR = Path(os.environ.get("RONGYAO_WEEKLY_DOWNLOAD_DIR", Path.home() / "Downloads")).expanduser()

ACTIVE_CHROME_SESSION_GUIDANCE = (
    "该后台可能使用仅保存在运行中 Chrome 内存里的会话 Cookie；关闭 Chrome 后它不会出现在 Cookie 数据库。"
    "请在已启用 Codex Chrome 扩展的 Default Profile 中手动打开后台并登录，保持该页面和 Chrome 运行，"
    "再由 Codex 通过该页面调用同一只读后台接口；不要导出、复制或发送 Cookie 值"
)


def login_required(message: str) -> SystemExit:
    return SystemExit(
        f"{message}。请在 Chrome 打开 {BACKEND_LOGIN_ORIGIN} 并手动完成登录，"
        "然后回复 Codex‘已登录’再重试；不要把密码发到对话中。"
    )


def chrome_profile_dirs(profile: str) -> list[Path]:
    supplied = Path(profile).expanduser()
    if supplied.is_absolute():
        return [supplied]
    home = Path.home()
    candidates = [
        home / "Library/Application Support/Google/Chrome" / profile,
        home / ".config/google-chrome" / profile,
        home / ".config/chromium" / profile,
    ]
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "Google/Chrome/User Data" / profile)
    return candidates


def backend_chrome_cookie_db(profile: str = BACKEND_DIRECT_PROFILE) -> Path:
    checked: list[Path] = []
    for profile_dir in chrome_profile_dirs(profile):
        for relative in ("Cookies", "Network/Cookies"):
            candidate = profile_dir / relative
            checked.append(candidate)
            if candidate.is_file():
                return candidate
    raise login_required(f"未找到 Chrome Profile {profile!r} 的 Cookie 数据库")


def crypto_backend_name() -> str | None:
    if importlib.util.find_spec("Crypto") is not None:
        return "pycryptodome"
    if importlib.util.find_spec("cryptography") is not None:
        return "cryptography"
    return None


def _aes_gcm_decrypt(key: bytes, nonce: bytes, payload: bytes) -> bytes:
    try:
        from Crypto.Cipher import AES

        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(payload[:-16], payload[-16:])
    except ImportError:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            return AESGCM(key).decrypt(nonce, payload, None)
        except ImportError as error:
            raise SystemExit(
                "缺少 AES 解密依赖；请先征得用户同意后安装 "
                "pycryptodome 或 cryptography。"
            ) from error


def _aes_cbc_decrypt(key: bytes, body: bytes) -> bytes:
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad

        return unpad(AES.new(key, AES.MODE_CBC, b" " * 16).decrypt(body), 16)
    except ImportError:
        try:
            from cryptography.hazmat.primitives import padding
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

            decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
            padded = decryptor.update(body) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            return unpadder.update(padded) + unpadder.finalize()
        except ImportError as error:
            raise SystemExit(
                "缺少 AES 解密依赖；请先征得用户同意后安装 "
                "pycryptodome 或 cryptography。"
            ) from error


def _strip_cookie_host_digest(host: str, value: bytes) -> bytes:
    host_digest = hashlib.sha256(str(host).encode("utf-8")).digest()
    return value[32:] if value.startswith(host_digest) else value


def _windows_dpapi_decrypt(data: bytes) -> bytes:
    if platform.system() != "Windows":
        raise RuntimeError("DPAPI 只能在 Windows 上调用。")
    if not data:
        return b""
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    source_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = DataBlob(len(data), source_buffer)
    destination = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)
    ):
        raise login_required(f"Windows DPAPI 解密失败（{ctypes.get_last_error()}）")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


def _windows_local_state_path(cookie_db: Path) -> Path:
    profile_dir = cookie_db.parent.parent if cookie_db.parent.name == "Network" else cookie_db.parent
    return profile_dir.parent / "Local State"


@lru_cache(maxsize=8)
def _windows_chrome_master_key(cookie_db: Path) -> bytes:
    local_state = _windows_local_state_path(Path(cookie_db))
    if not local_state.is_file():
        raise login_required(f"未找到 Chrome Local State：{local_state}")
    try:
        payload = json.loads(local_state.read_text(encoding="utf-8"))
        encoded_key = payload["os_crypt"]["encrypted_key"]
        protected_key = base64.b64decode(encoded_key)
    except (KeyError, ValueError, json.JSONDecodeError) as error:
        raise login_required("Chrome Local State 中缺少可用的 Windows 密钥") from error
    if not protected_key.startswith(b"DPAPI"):
        raise login_required("Chrome Windows 密钥格式不受支持")
    return _windows_dpapi_decrypt(protected_key[5:])


def backend_decrypt_chrome_cookie(
    host: str,
    encrypted_value: bytes,
    cookie_db: Path | None = None,
) -> str:
    data = bytes(encrypted_value or b"")
    if not data:
        return ""
    system = platform.system()
    if system == "Windows":
        if data.startswith(b"v20"):
            raise SystemExit(
                "Chrome 当前使用 Windows App-Bound Encryption（v20）；"
                "内置 Python 助手不绕过 Chrome 的应用身份保护。"
                "请使用经审阅的外部后台助手，或由用户提供权限受限的临时 Cookie 文件；"
                "不要降低 Chrome 安全策略。"
            )
        if data.startswith((b"v10", b"v11")):
            if cookie_db is None:
                raise login_required("Windows Chrome Cookie 解密缺少 Cookie 数据库路径")
            body = data[3:]
            if len(body) < 28:
                raise login_required("Windows Chrome Cookie 密文长度无效")
            try:
                value = _aes_gcm_decrypt(
                    _windows_chrome_master_key(Path(cookie_db)), body[:12], body[12:]
                )
            except Exception as error:
                raise login_required("Windows Chrome Cookie 解密失败") from error
        else:
            value = _windows_dpapi_decrypt(data)
        return _strip_cookie_host_digest(host, value).decode("utf-8", errors="replace")

    if system != "Darwin":
        raise SystemExit(
            f"当前内置助手尚不支持 {system} Chrome Cookie 解密；"
            "请使用权限受限的 --cookie-file，或提供经审阅的外部后台助手。"
        )
    try:
        password = subprocess.check_output(
            ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        raise login_required("无法从 macOS Keychain 读取 Chrome Safe Storage") from error
    key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, dklen=16)
    body = data[3:] if data.startswith((b"v10", b"v11")) else data
    try:
        value = _aes_cbc_decrypt(key, body)
    except ValueError as error:
        raise login_required("Chrome Cookie 解密失败") from error
    return _strip_cookie_host_digest(host, value).decode("utf-8", errors="replace")


def backend_cookie_header_from_chrome(
    profile: str = BACKEND_DIRECT_PROFILE,
    host: str = BACKEND_DIRECT_HOST,
) -> str:
    cookie_db = backend_chrome_cookie_db(profile)
    handle, temp_name = tempfile.mkstemp(prefix="rongyao-cookies-", suffix=".sqlite")
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(cookie_db, temp_path)
    except PermissionError as error:
        temp_path.unlink(missing_ok=True)
        raise SystemExit(
            "Chrome 正在占用 Cookie 数据库，磁盘 Cookie 路径当前不可读。"
            + ACTIVE_CHROME_SESSION_GUIDANCE
        ) from error
    try:
        connection = sqlite3.connect(temp_path)
        hosts = [host, f".{host}", "power.houtai.backend.example.invalid", ".backend.example.invalid"]
        placeholders = ",".join("?" for _ in hosts)
        rows = connection.execute(
            f"SELECT host_key, name, value, encrypted_value FROM cookies WHERE host_key IN ({placeholders})",
            hosts,
        ).fetchall()
        connection.close()
    finally:
        temp_path.unlink(missing_ok=True)
    parts = []
    for cookie_host, name, value, encrypted_value in rows:
        normalized_cookie_host = str(cookie_host or "").lstrip(".").lower()
        normalized_request_host = str(host or "").lower()
        if not (
            normalized_request_host == normalized_cookie_host
            or normalized_request_host.endswith("." + normalized_cookie_host)
        ):
            continue
        cookie_value = value or backend_decrypt_chrome_cookie(
            cookie_host, encrypted_value, cookie_db
        )
        if cookie_value:
            parts.append(f"{name}={cookie_value}")
    if not parts:
        raise SystemExit(
            f"Chrome Profile {profile!r} 的磁盘数据库中没有 {host} 的登录 Cookie。"
            + ACTIVE_CHROME_SESSION_GUIDANCE
        )
    return "; ".join(parts)


def normalize_backend_cookie_header(value: str) -> str:
    cookie = str(value or "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()
    if not cookie or any(char in cookie for char in ("\r", "\n", "\0")):
        raise SystemExit("荣耀后台 Cookie 必须是非空的单行请求头")
    parts = []
    for item in cookie.split(";"):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit("荣耀后台 Cookie 格式无效：每一项都必须是 name=value")
        name, raw_value = item.split("=", 1)
        if not name.strip() or any(char.isspace() for char in name):
            raise SystemExit("荣耀后台 Cookie 名不能为空或包含空白")
        parts.append(f"{name.strip()}={raw_value.strip()}")
    if not parts:
        raise SystemExit("荣耀后台 Cookie 为空")
    return "; ".join(parts)


def cookie_file_permissions_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    if platform.system() == "Windows":
        # Windows uses ACLs rather than POSIX group/other mode bits.
        return True
    return not bool(path.stat().st_mode & 0o077)


def backend_cookie_header(
    cookie_file: str = "",
    cookie_env: str = BACKEND_DIRECT_COOKIE_ENV,
    profile: str = BACKEND_DIRECT_PROFILE,
    host: str = BACKEND_DIRECT_HOST,
) -> str:
    if cookie_file:
        path = Path(cookie_file).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"未找到荣耀后台 Cookie 文件：{path}")
        if not cookie_file_permissions_ok(path):
            raise SystemExit(f"Cookie 文件权限过宽，请先将读取权限限制为当前用户：{path}")
        return normalize_backend_cookie_header(path.read_text(encoding="utf-8"))
    if cookie_env:
        cookie = os.environ.get(cookie_env, "")
        if cookie:
            return normalize_backend_cookie_header(cookie)
    return backend_cookie_header_from_chrome(profile, host)


def backend_url(host: str, path: str) -> str:
    if str(path).startswith(("http://", "https://")):
        return str(path)
    return f"http://{host}{path if str(path).startswith('/') else '/' + str(path)}"


def backend_http_request(
    host: str,
    path: str,
    cookie_header: str,
    data: dict[str, Any] | None = None,
    timeout: int = 120,
    accept: str = "*/*",
):
    body = None
    headers = {
        "Cookie": cookie_header,
        "User-Agent": "Mozilla/5.0",
        "Accept": accept,
        "X-Requested-With": "XMLHttpRequest",
    }
    if data is not None:
        body = urllib.parse.urlencode(data, doseq=False).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    request = urllib.request.Request(backend_url(host, path), data=body, headers=headers)
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            raise login_required(f"荣耀后台返回 HTTP {error.code}") from error
        raise SystemExit(f"请求荣耀后台失败：HTTP {error.code}；{path}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"请求荣耀后台失败：{path}；{error.reason}") from error


def backend_json(host: str, path: str, cookie_header: str, timeout: int = 120) -> dict[str, Any]:
    with backend_http_request(
        host,
        path,
        cookie_header,
        timeout=timeout,
        accept="application/json, text/javascript, */*; q=0.01",
    ) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"荣耀后台 API 返回非 JSON：{path}；{raw[:200]}") from error
    if not isinstance(result, dict):
        raise SystemExit(f"荣耀后台 API 响应不是对象：{path}")
    return result


def parse_backend_page_config(page_html: str) -> dict[str, Any]:
    config_match = re.search(r"var\s+_pageConfig\s*=\s*(\{.*?\});\s*/\*\s*\{search", page_html, re.S)
    rand_match = re.search(r"var\s+_initRand\s*=\s*'([^']*)'", page_html)
    get_data_match = re.search(r"var\s+_getDataUrl\s*=\s*'([^']+)'", page_html)
    if not config_match or not rand_match or not get_data_match:
        if "login" in page_html.lower() or "feishu" in page_html.lower() or "飞书" in page_html:
            raise login_required("荣耀后台登录态失效")
        raise SystemExit("无法解析新素材2.0页面配置，后台页面结构可能已变化")
    try:
        config = json.loads(config_match.group(1))
    except json.JSONDecodeError as error:
        raise SystemExit("解析新素材2.0页面筛选配置失败") from error
    return {
        "config": config,
        "initRand": rand_match.group(1),
        "getDataUrl": get_data_match.group(1).replace("\\/", "/"),
        "controller": "adopenplatformSource",
    }


def backend_default_search(config: dict[str, Any], init_rand: str) -> dict[str, Any]:
    search: dict[str, Any] = {
        "date": "",
        "page": 1,
        "pagesize": config.get("pagesize") or 20,
        "sort": "",
        "desc": "",
        "rand_num": init_rand or "",
    }
    for field in config.get("search") or []:
        if field.get("type") == "button":
            continue
        search[field.get("key")] = field.get("default") if "default" in field else ([] if field.get("multiple") else "")
    return search


def backend_selected_pcids(
    host: str,
    cookie_header: str,
    operation_clients: list[str],
    timeout: int = 120,
) -> list[str]:
    op_value = ",".join(str(item) for item in (operation_clients or []))
    result = backend_json(
        host,
        "/marketng/api/ApiGetPcidList.php?operation_client=" + urllib.parse.quote(op_value),
        cookie_header,
        timeout=timeout,
    )
    return list((((result.get("info") or {}).get("pcid_list") or {}).keys()))


def backend_gid_values(gid: str | list[str]) -> list[str]:
    candidates = gid if isinstance(gid, list) else str(gid or "").split(",")
    values = []
    for item in candidates:
        value = str(item).strip()
        if not value:
            continue
        if not value.isdigit():
            raise SystemExit(f"母游戏 ID 无效：{value}")
        if value not in values:
            values.append(value)
    if not values:
        raise SystemExit("至少需要选择一个母游戏")
    return values


def backend_option_keys(value: Any) -> list[str]:
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


def backend_gid_dependencies(
    host: str, cookie_header: str, gids: list[str], timeout: int = 120
) -> tuple[list[str], list[str]]:
    categories: list[str] = []
    subgames: list[str] = []
    for gid in gids:
        categories.extend(
            backend_option_keys(
                backend_json(host, f"/market/api/ApiGetCategory.php?gid={gid}", cookie_header, timeout)
            )
        )
        subgames.extend(
            backend_option_keys(
                backend_json(host, f"/market/api/ApiGetAllPkList.php?gid={gid}", cookie_header, timeout)
            )
        )
    return list(dict.fromkeys(categories)), list(dict.fromkeys(subgames))


def detect_csv_encoding(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def backend_export_summary(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    encoding = detect_csv_encoding(raw)
    rows = list(csv.reader(raw.decode(encoding, errors="replace").splitlines()))
    has_total = bool(rows[1:2] and rows[1][0] == "总计")
    return {
        "encoding": encoding,
        "rows": len(rows),
        "dataRows": max(0, len(rows) - (2 if has_total else 1)),
        "columns": len(rows[0]) if rows else 0,
        "headers": rows[0] if rows else [],
    }


def backend_export_direct(args: argparse.Namespace) -> dict[str, Any]:
    cookie_header = backend_cookie_header(
        cookie_file=args.cookie_file or "",
        cookie_env=args.cookie_env,
        profile=args.chrome_profile,
        host=args.host,
    )
    with backend_http_request(
        args.host,
        args.market_path,
        cookie_header,
        timeout=args.timeout,
        accept="text/html,application/xhtml+xml",
    ) as response:
        page_html = response.read().decode("utf-8", errors="replace")
    page = parse_backend_page_config(page_html)
    search = backend_default_search(page["config"], page["initRand"])
    gid_values = backend_gid_values(args.gid)
    categories, subgames = backend_gid_dependencies(
        args.host, cookie_header, gid_values, timeout=args.timeout
    )
    material_range = args.material_range or f"2023/01/01-{datetime.now():%Y/%m/%d}"
    search.update(
        {
            "date": args.date_range,
            "date2": material_range,
            "gid": gid_values,
            "category": categories,
            "pkid": subgames,
            "date_group": args.date_group,
            "group": args.group,
            "source_video_type": "1",
            "record_type": "3",
            "filter": "1",
            "page": 1,
        }
    )
    if search.get("operation_client"):
        search["pcid"] = backend_selected_pcids(
            args.host,
            cookie_header,
            search.get("operation_client"),
            timeout=args.timeout,
        )
    post_data = {
        f"search[{key}]": ",".join(str(item) for item in value) if isinstance(value, list) else value
        for key, value in search.items()
    }
    post_data["search[page_component_version]"] = 1
    post_data["search[submit]"] = 1
    with backend_http_request(
        args.host,
        page["getDataUrl"],
        cookie_header,
        data=post_data,
        timeout=args.timeout,
        accept="application/json",
    ) as response:
        raw_query = response.read().decode("utf-8", errors="replace")
    try:
        query_result = json.loads(raw_query)
    except json.JSONDecodeError as error:
        raise SystemExit(f"荣耀后台查询返回非 JSON：{raw_query[:200]}") from error
    if not query_result.get("status"):
        raise SystemExit("荣耀后台查询失败：status=false")
    info = query_result.get("info") or {}
    rand = str(info.get("rand") or "")
    if not rand:
        raise SystemExit("荣耀后台查询未返回 rand，无法导出")
    export_path = f"/marketng/?_c=adopenplatformSource&_a=index&ac=export&rand={urllib.parse.quote(rand)}"
    with backend_http_request(
        args.host,
        export_path,
        cookie_header,
        timeout=args.timeout,
        accept="text/csv,application/vnd.ms-excel,*/*",
    ) as response:
        raw_file = response.read()
        content_type = response.headers.get("Content-Type") or ""
    if b"<html" in raw_file[:200].lower():
        raise login_required("荣耀后台导出返回 HTML，登录态可能失效")
    output = Path(args.output).expanduser().resolve() if args.output else (
        Path(args.output_dir).expanduser().resolve()
        / f"weekly-backend-export-{datetime.now():%Y%m%d-%H%M%S}.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw_file)
    return {
        "ok": True,
        "file": str(output),
        "bytes": len(raw_file),
        "contentType": content_type,
        "filters": {
            "entry": "新素材2.0",
            "gid": gid_values[0] if len(gid_values) == 1 else gid_values,
            "gidCount": len(gid_values),
            "game": "忍界大战" if gid_values == ["193"] else "多母游戏",
            "dateRange": args.date_range,
            "materialRange": material_range,
            "dateGroup": args.date_group,
            "group": args.group,
            "sourceVideoType": "视频",
            "recordType": "新注册",
            "filter": "是",
        },
        "query": {
            "count": info.get("count"),
            "totalpage": info.get("totalpage"),
            "pagesize": info.get("pagesize"),
        },
        "fileSummary": backend_export_summary(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("backend-export")
    export.add_argument("--date-range", required=True)
    export.add_argument("--material-range", default="")
    export.add_argument("--output", default="")
    export.add_argument("--output-dir", default=str(BACKEND_DOWNLOAD_DIR))
    export.add_argument("--cookie-file", default="")
    export.add_argument("--cookie-env", default=BACKEND_DIRECT_COOKIE_ENV)
    export.add_argument("--chrome-profile", default=BACKEND_DIRECT_PROFILE)
    export.add_argument("--host", default=BACKEND_DIRECT_HOST)
    export.add_argument("--market-path", default=BACKEND_DIRECT_MARKET_PATH)
    export.add_argument("--gid", default=BACKEND_DIRECT_GID)
    export.add_argument("--date-group", default=BACKEND_DIRECT_DATE_GROUP)
    export.add_argument("--group", default=BACKEND_DIRECT_GROUP)
    export.add_argument("--timeout", type=int, default=180)
    export.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args()
    result = backend_export_direct(args)
    if args.format == "text":
        summary = result["fileSummary"]
        query = result["query"]
        print(f"导出成功：{result['file']}")
        print(f"后台查询：{query.get('count')} 条 / {query.get('totalpage')} 页")
        print(f"文件校验：{summary.get('rows')} 行 · {summary.get('columns')} 列 · {summary.get('encoding')}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
