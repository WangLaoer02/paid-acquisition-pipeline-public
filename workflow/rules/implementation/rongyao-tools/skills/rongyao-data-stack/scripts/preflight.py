#!/usr/bin/env python3
"""Read-only portability preflight for the Codex 荣耀 data Skill stack."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")


CORE_SKILLS = {
    "rongyao-dashboard-filter-finder": [
        "SKILL.md",
        "scripts/capture_material_output.py",
        "scripts/capture_original_materials.py",
    ],
    "rongyao-material-performance": [
        "SKILL.md",
        "scripts/material_performance.py",
        "references/normalization-rules.json",
    ],
    "rongyao-material-analysis": [
        "SKILL.md",
        "references/judging-rules.md",
        "references/metrics-glossary.md",
    ],
    "rongyao-data-stack": [
        "SKILL.md",
        "START_HERE.md",
        "scripts/active_chrome_bridge.mjs",
        "scripts/active_session_cli.py",
        "scripts/backend_export_cli.py",
        "scripts/readonly_capture.py",
        "scripts/test_readonly_capture.py",
        "scripts/static_reference_check.py",
        "scripts/live_regression.py",
        "references/portability.md",
    ],
}
TARGET_COOKIE_HOSTS = (
    "data.houtai.cn.sy.backend.example.invalid",
    ".data.houtai.cn.sy.backend.example.invalid",
    ".backend.example.invalid",
)


def default_skills_root() -> Path:
    configured = os.environ.get("AGENTS_SKILLS", "").strip()
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parents[2]


def helper_candidates(skills_root: Path, explicit: str = "") -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if explicit:
        candidates.append(("explicit", Path(explicit).expanduser()))
    for name in ("RONGYAO_WEEKLY_REPORT_CLI", "RONGYAO_BACKEND_HELPER"):
        value = os.environ.get(name, "").strip()
        if value:
            candidates.append((name, Path(value).expanduser()))
    candidates.extend(
        [
            ("active_session", skills_root / "rongyao-data-stack/scripts/active_session_cli.py"),
            ("home_project", Path.home() / "Documents/荣耀统计后台/scripts/weekly_report_cli.py"),
            ("bundled", skills_root / "rongyao-data-stack/scripts/backend_export_cli.py"),
        ]
    )
    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []
    for source, path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            unique.append((source, path))
            seen.add(key)
    return unique


def active_session_status(helper: Path | None) -> dict[str, Any]:
    if helper is None or helper.name != "active_session_cli.py" or not helper.is_file():
        return {"active": False, "reason": "helper_missing"}
    try:
        completed = subprocess.run(
            [sys.executable, str(helper), "backend-status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return {"active": False, "reason": "status_unavailable"}
    try:
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("active"), bool):
            raise ValueError("invalid status")
        if result["active"] and completed.returncode != 0:
            raise ValueError("inconsistent exit status")
        return {"active": result["active"], "reason": result.get("reason"),
                "has_login_page": result.get("hasLoginPage")}
    except (ValueError, TypeError):
        return {"active": False, "reason": "status_unavailable"}


def active_session_ready(helper: Path | None) -> bool:
    return active_session_status(helper).get("active") is True


def chrome_cookie_candidates(profile: str) -> list[Path]:
    supplied = Path(profile).expanduser()
    if supplied.is_absolute():
        return [supplied / "Cookies", supplied / "Network/Cookies"]
    home = Path.home()
    candidates = [
        home / "Library/Application Support/Google/Chrome" / profile / "Cookies",
        home / ".config/google-chrome" / profile / "Cookies",
        home / ".config/chromium" / profile / "Cookies",
    ]
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "Google/Chrome/User Data" / profile / "Network/Cookies")
    return candidates


def crypto_backend_name() -> str | None:
    if importlib.util.find_spec("Crypto") is not None:
        return "pycryptodome"
    if importlib.util.find_spec("cryptography") is not None:
        return "cryptography"
    return None


def python_launcher_status() -> dict[str, Any]:
    """Detect Windows Store aliases that look present but cannot run Python."""
    candidates = []
    for name in ("python", "python3", "py"):
        path = shutil.which(name)
        if not path:
            continue
        try:
            command = [path, "-3", "--version"] if name == "py" else [path, "--version"]
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=4
            )
            candidates.append(
                {
                    "name": name,
                    "path": path,
                    "usable": completed.returncode == 0,
                    "version": (completed.stdout or completed.stderr).strip() or None,
                    "exit_code": completed.returncode,
                }
            )
        except (OSError, subprocess.SubprocessError) as error:
            candidates.append({"name": name, "path": path, "usable": False, "error": str(error)})
    return {"current_executable": sys.executable, "launchers": candidates}


def cookie_file_permissions_ok(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    if platform.system() == "Windows":
        return True
    return not bool(path.stat().st_mode & 0o077)


def chrome_cookie_encryption(cookie_db: Path | None) -> str:
    """Inspect only encryption prefixes for target-host rows; never return cookie values."""
    if cookie_db is None or not cookie_db.is_file():
        return "missing"
    placeholders = ",".join("?" for _ in TARGET_COOKIE_HOSTS)
    try:
        with tempfile.TemporaryDirectory(prefix="rongyao-preflight-") as directory:
            copied_db = Path(directory) / cookie_db.name
            shutil.copy2(cookie_db, copied_db)
            for suffix in ("-wal", "-shm"):
                companion = Path(str(cookie_db) + suffix)
                if companion.is_file():
                    shutil.copy2(companion, Path(str(copied_db) + suffix))
            uri = copied_db.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=1)
            try:
                rows = connection.execute(
                    "SELECT length(value) > 0, hex(substr(encrypted_value, 1, 3)) "
                    f"FROM cookies WHERE host_key IN ({placeholders})",
                    TARGET_COOKIE_HOSTS,
                ).fetchall()
            finally:
                connection.close()
    except PermissionError:
        return "locked"
    except (OSError, sqlite3.Error):
        return "unreadable"
    modes: set[str] = set()
    for has_plaintext, prefix_hex in rows:
        if has_plaintext:
            modes.add("plaintext")
            continue
        prefix = str(prefix_hex or "").upper()
        if prefix == "763230":
            modes.add("v20")
        elif prefix in {"763130", "763131"}:
            modes.add("v10/v11")
        elif prefix:
            modes.add("legacy-dpapi")
    if not modes:
        return "none"
    if "v20" in modes:
        return "v20"
    if "v10/v11" in modes:
        return "v10/v11"
    if "legacy-dpapi" in modes:
        return "legacy-dpapi"
    return "plaintext"


def bundled_helper_login_ready(
    system: str,
    encryption: str,
    crypto_backend: str | None,
    cookie_file_ok: bool,
) -> bool:
    if cookie_file_ok:
        return True
    if encryption in {"missing", "none", "locked", "unreadable", "v20", "not_checked"}:
        return False
    if encryption == "plaintext":
        return True
    if system == "Windows":
        return encryption == "legacy-dpapi" or (
            encryption == "v10/v11" and crypto_backend is not None
        )
    if system == "Darwin":
        return crypto_backend is not None
    return False


def inspect_stack(skills_root: Path, helper: str, profile: str, cookie_file: str,
                  check_disk_cookie: bool = False) -> dict[str, Any]:
    skill_checks: dict[str, Any] = {}
    for skill, required in CORE_SKILLS.items():
        root = skills_root / skill
        missing = [relative for relative in required if not (root / relative).is_file()]
        skill_checks[skill] = {"present": root.is_dir(), "missing": missing, "ok": root.is_dir() and not missing}

    helpers = helper_candidates(skills_root, helper)
    selected = next(((source, path) for source, path in helpers if path.is_file()), None)
    cookie_path = Path(cookie_file).expanduser() if cookie_file else None
    cookie_file_ok = cookie_file_permissions_ok(cookie_path)
    chrome_paths = chrome_cookie_candidates(profile) if check_disk_cookie else []
    chrome_cookie_db = next((path for path in chrome_paths if path.is_file()), None)
    encryption = chrome_cookie_encryption(chrome_cookie_db) if check_disk_cookie else "not_checked"
    crypto_backend = crypto_backend_name()
    python_ready = sys.version_info >= (3, 10)
    launchers = python_launcher_status()
    analysis_ready = python_ready and all(item["ok"] for item in skill_checks.values())
    system = platform.system()
    session = active_session_status(selected[1] if selected else None)
    active_ready = session.get("active") is True
    login_source_present = cookie_file_ok or encryption not in {
        "missing",
        "none",
        "locked",
        "unreadable",
        "not_checked",
    } or active_ready
    if selected is None:
        helper_login_ready = False
    elif selected[0] == "active_session":
        helper_login_ready = active_ready or bundled_helper_login_ready(
            system, encryption, crypto_backend, cookie_file_ok
        )
    elif selected[0] == "bundled":
        helper_login_ready = bundled_helper_login_ready(
            system, encryption, crypto_backend, cookie_file_ok
        )
    else:
        helper_login_ready = login_source_present
    # A disconnected known session is not an absent session; do not recommend fallback.
    session_failed = bool(selected and selected[0] == "active_session" and not active_ready
                          and session.get("reason") not in {"state_missing", "process_missing"})
    if session_failed:
        helper_login_ready = False
    capture_environment_ready = analysis_ready and selected is not None and helper_login_ready

    actions: list[str] = []
    if not python_ready:
        actions.append("安装 Python 3.10 或更高版本。")
    if launchers["launchers"] and not any(item.get("usable") for item in launchers["launchers"]):
        actions.append(
            f"系统 python/python3/py 启动器不可用；请使用当前已验证解释器：{sys.executable}"
        )
    if not all(item["ok"] for item in skill_checks.values()):
        actions.append("重新解压完整 Skill 包；当前存在缺失文件。")
    if selected is None:
        actions.append("恢复迁移包自带 backend_export_cli.py，或设置 RONGYAO_WEEKLY_REPORT_CLI。")
    if session_failed:
        actions.append("专用会话断连或状态无法确认；先核查原会话，不切换通道、不提交查询。")
    elif selected and selected[0] == "active_session" and not active_ready and not helper_login_ready:
        actions.append(
            "未发现专用活动会话；实时抓取会用同一专用配置自动恢复。"
            "只有服务端跳转登录页时才需用户在该窗口手动登录一次。"
        )
    using_active_session = bool(selected and selected[0] == "active_session")
    if encryption == "locked" and not cookie_file_ok and not using_active_session:
        actions.append("Chrome 正在占用 Cookie 数据库；完全关闭 Chrome 后重新运行预检。")
    elif encryption == "unreadable" and not cookie_file_ok and not using_active_session:
        actions.append("Chrome Cookie 数据库无法只读检查；关闭 Chrome 后重试，或使用经审阅的外部后台助手。")
    elif encryption == "none" and not cookie_file_ok and not using_active_session:
        actions.append(
            "目标域 Cookie 未写入磁盘数据库，可能是仅存于 Chrome 进程内的会话 Cookie。"
            "不要继续通过关闭 Chrome 重试；请在 Default Profile 手动打开后台并登录，保持页面和 Chrome 运行，"
            "再让 Codex 通过该页面调用同一只读后台接口。"
        )
    elif not login_source_present and not using_active_session:
        actions.append("在 Chrome 登录荣耀后台；登录完成后重新运行预检。")
    elif selected and selected[0] == "bundled" and encryption == "v20" and not cookie_file_ok:
        actions.append(
            "Windows Chrome 使用 App-Bound Encryption（v20）；内置助手不绕过该保护。"
            "请使用经审阅的外部后台助手，或由用户提供权限受限的临时 Cookie 文件。"
        )
    elif (
        selected
        and selected[0] == "bundled"
        and encryption == "v10/v11"
        and crypto_backend is None
        and not cookie_file_ok
    ):
        actions.append("经用户同意后安装 pycryptodome 或 cryptography，以解密 Chrome 登录态。")
    elif selected and selected[0] == "bundled" and not helper_login_ready:
        actions.append(f"内置后台助手尚不支持 {system} 的 Chrome Cookie 模式：{encryption}。")
    elif capture_environment_ready:
        actions.append("传输环境可用但登录尚未验证；用用户本次已授权查询验证，不另加重型冒烟。")

    return {
        "ok": analysis_ready,
        "platform": {"system": system, "python": platform.python_version(), "python_launcher": launchers},
        "skills_root": str(skills_root),
        "skills": skill_checks,
        "backend_helper": {
            "available": selected is not None,
            "source": selected[0] if selected else None,
            "path": str(selected[1]) if selected else None,
            "active_session_ready": active_ready,
            "session_reason": session.get("reason"),
            "has_login_page": session.get("has_login_page"),
            "universal_query": str(skills_root / "rongyao-data-stack/scripts/readonly_capture.py"),
        },
        "login": {
            "cookie_file_ready": cookie_file_ok,
            "chrome_profile": profile,
            "chrome_cookie_db_present": chrome_cookie_db is not None,
            "chrome_cookie_db": str(chrome_cookie_db) if chrome_cookie_db else None,
            "chrome_cookie_encryption": encryption,
            "disk_cookie_checked": check_disk_cookie,
            "crypto_backend": crypto_backend,
            "authenticated_session_verified": False,
        },
        "capabilities": {
            "analysis_ready": analysis_ready,
            "capture_environment_ready": capture_environment_ready,
            "login_verification_required": True,
            "active_session_query_ready": active_ready,
            "authenticated_session_verified": False,
            "direct_cookie_fallback_ready": bundled_helper_login_ready(
                system, encryption, crypto_backend, cookie_file_ok
            ),
        },
        "actions": actions,
        "safety": "No password, plaintext Cookie value, Token, or backend data was read.",
    }


def render_text(result: dict[str, Any]) -> str:
    caps = result["capabilities"]
    lines = [
        f"analysis_ready={str(caps['analysis_ready']).lower()}",
        f"capture_environment_ready={str(caps['capture_environment_ready']).lower()}",
        "login_verification_required=true",
        f"backend_helper={result['backend_helper']['source'] or 'missing'}",
    ]
    lines.extend(f"action: {item}" for item in result["actions"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", default="")
    parser.add_argument("--backend-helper", default="")
    parser.add_argument("--profile", default="Default")
    parser.add_argument("--cookie-file", default="")
    parser.add_argument("--check-disk-cookie", action="store_true", help="显式启用旧磁盘兼容诊断；默认不复制或读取Cookie库")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args()
    root = Path(args.skills_root).expanduser() if args.skills_root else default_skills_root()
    result = inspect_stack(root, args.backend_helper, args.profile, args.cookie_file, args.check_disk_cookie)
    if args.format == "text":
        print(render_text(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["capabilities"]["analysis_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
