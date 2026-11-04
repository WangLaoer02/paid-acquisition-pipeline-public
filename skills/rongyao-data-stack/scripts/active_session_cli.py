#!/usr/bin/env python3
"""Drop-in 荣耀 backend helper that prefers a dedicated active Chrome session."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")


SCRIPT_DIR = Path(__file__).resolve().parent
NODE_BRIDGE = SCRIPT_DIR / "active_chrome_bridge.mjs"
BUNDLED_HELPER = SCRIPT_DIR / "backend_export_cli.py"
DEFAULT_STATE = Path.home() / ".codex/state/rongyao-active-session/session.json"
DEFAULT_PROFILE = Path.home() / ".codex/browser-profiles/rongyao-weekly-market"
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"
DEFAULT_MARKET_PATH = "/marketng/?_c=adopenplatformSource&_a=index"
RECOVERABLE_SESSION_REASONS = {"state_missing", "process_missing"}


def node_bin() -> Path:
    configured = os.environ.get("NODE_BIN", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe",
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
    ]
    found = shutil.which("node")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise SystemExit("未找到 Node.js；活动 Chrome 会话桥需要 Codex bundled Node 或 PATH 中的 node。")


def chrome_bin() -> Path:
    configured = os.environ.get("RONGYAO_CHROME_BIN", "").strip()
    candidates = [Path(configured).expanduser() if configured else None]
    if sys.platform == "win32":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(variable, "").strip()
            if root:
                candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise SystemExit("未找到 Google Chrome；可设置 RONGYAO_CHROME_BIN。")


def safe_state_payload(port: int, pid: int, profile_dir: Path) -> dict[str, Any]:
    """Return the only state fields the bridge is allowed to persist."""
    return {
        "version": 1,
        "port": int(port),
        "pid": int(pid),
        "profileDir": str(profile_dir.resolve()),
    }


def run_node(command: str, *arguments: str, timeout: int = 300) -> dict[str, Any]:
    completed = subprocess.run(
        [str(node_bin()), str(NODE_BRIDGE), command, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "活动 Chrome 会话桥失败").strip()
        raise RuntimeError(detail[-2000:])
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("活动 Chrome 会话桥返回非 JSON") from error


def session_status(state_file: Path) -> dict[str, Any]:
    return run_node("status", "--state-file", str(state_file), timeout=15)


def open_session(state_file: Path, profile_dir: Path) -> dict[str, Any]:
    return run_node(
        "open",
        "--chrome",
        str(chrome_bin()),
        "--profile-dir",
        str(profile_dir),
        "--state-file",
        str(state_file),
        timeout=35,
    )


def ensure_active_session(state_file: Path, profile_dir: Path) -> dict[str, Any]:
    """Reuse a healthy session or restart its credential-isolated Chrome profile."""
    status = session_status(state_file)
    if status.get("active"):
        return {**status, "recovered": False}
    reason = status.get("reason")
    if reason not in RECOVERABLE_SESSION_REASONS:
        raise RuntimeError(
            "专用会话状态异常或断连，未重启浏览器、未提交查询。"
            "先核查原会话；不要启动第二个会话或跨通道重放。"
        )
    if os.environ.get("RONGYAO_CAPTURE_BACKGROUND") == "1":
        raise RuntimeError("AUTH_REQUIRED: 专用会话未运行，请点击网页的打开专用登录窗口；后台抓取不会弹窗。")
    opened = open_session(state_file, profile_dir)
    if not opened.get("active"):
        raise RuntimeError("专用 Chrome 自动恢复后仍不可用，未提交查询。")
    return {**opened, "recovered": True, "recoveredFrom": reason}


def backend_export_summary(path: Path) -> dict[str, Any]:
    # Reuse the reviewed CSV detector without invoking its Cookie path.
    import importlib.util

    spec = importlib.util.spec_from_file_location("rongyao_bundled_export", BUNDLED_HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {BUNDLED_HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.backend_export_summary(path)


def fallback_backend_export(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(BUNDLED_HELPER),
        "backend-export",
        "--date-range",
        args.date_range,
        "--material-range",
        args.material_range,
        "--output",
        args.output,
        "--output-dir",
        args.output_dir,
        "--chrome-profile",
        args.chrome_profile,
        "--host",
        args.host,
        "--market-path",
        args.market_path,
        "--gid",
        args.gid,
        "--date-group",
        args.date_group,
        "--group",
        args.group,
        "--timeout",
        str(args.timeout),
        "--format",
        args.format,
    ]
    if args.cookie_file:
        command.extend(["--cookie-file", args.cookie_file])
    if args.cookie_env:
        command.extend(["--cookie-env", args.cookie_env])
    completed = subprocess.run(command, check=False)
    return completed.returncode


def run_open(args: argparse.Namespace) -> int:
    if args.dry_run:
        result = {
            "ok": True,
            "dryRun": True,
            "chrome": str(chrome_bin()),
            "profileDir": str(Path(args.profile_dir).expanduser().resolve()),
            "stateFile": str(Path(args.state_file).expanduser().resolve()),
            "loginOrigin": "http://power.houtai.backend.example.invalid/",
            "safety": "State contains only PID, localhost DevTools port, profile path, and timestamps; no credentials.",
        }
    else:
        result = open_session(
            Path(args.state_file).expanduser().resolve(),
            Path(args.profile_dir).expanduser().resolve(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_login(args: argparse.Namespace) -> int:
    state_file = Path(args.state_file).expanduser().resolve()
    # This command is the user's explicit request to show a login window. Do not
    # let an inherited worker setting turn that deliberate action into a no-op.
    background = os.environ.pop("RONGYAO_CAPTURE_BACKGROUND", None)
    try:
        ensure_active_session(state_file, Path(args.profile_dir).expanduser().resolve())
    finally:
        if background is not None:
            os.environ["RONGYAO_CAPTURE_BACKGROUND"] = background
    result = run_node("login", "--state-file", str(state_file), timeout=25)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_status(args: argparse.Namespace) -> int:
    result = session_status(Path(args.state_file).expanduser().resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("active") else 1


def run_ensure(args: argparse.Namespace) -> int:
    result = ensure_active_session(
        Path(args.state_file).expanduser().resolve(),
        Path(args.profile_dir).expanduser().resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_export(args: argparse.Namespace) -> int:
    state_file = Path(args.state_file).expanduser().resolve()
    status = session_status(state_file)
    if not status.get("active"):
        if args.require_active:
            raise SystemExit(
                "专用 Chrome 会话未运行。去掉 --require-active 可自动用同一专用配置恢复；"
                "服务端登录已过期时才需在打开的窗口中手动登录一次。"
            )
        if args.auto_recover:
            status = ensure_active_session(
                state_file,
                Path(args.profile_dir).expanduser().resolve(),
            )
        elif status.get("reason") != "state_missing":
            raise RuntimeError(
                "专用会话状态异常或断连，未切换磁盘 Cookie、未提交查询。"
                "先核查原会话；不要跨通道重放。"
            )
        else:
            return fallback_backend_export(args)
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else Path(args.output_dir).expanduser().resolve()
        / f"weekly-backend-export-{datetime.now():%Y%m%d-%H%M%S}.csv"
    )
    material_range = args.material_range or f"2023/01/01-{datetime.now():%Y/%m/%d}"
    try:
        result = run_node(
            "export",
            "--state-file",
            str(state_file),
            "--date-range",
            args.date_range,
            "--material-range",
            material_range,
            "--gid",
            args.gid,
            "--date-group",
            args.date_group,
            "--group",
            args.group,
            "--market-path",
            args.market_path,
            "--output",
            str(output),
            "--timeout",
            str(args.timeout * 1000),
            timeout=args.timeout + 30,
        )
    except RuntimeError as error:
        if "LOGIN_REQUIRED" in str(error):
            raise RuntimeError(
                "专用 Chrome 已自动打开，但荣耀服务端登录已过期。"
                "请在该窗口手动登录一次，然后原命令直接重跑；不需要复制 Cookie 或关闭日常 Chrome。"
            ) from error
        raise
    result["fileSummary"] = backend_export_summary(output)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(str(output))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    opened = subparsers.add_parser("backend-open", help="启动或复用专用 Chrome 登录会话")
    opened.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))
    opened.add_argument("--state-file", default=str(DEFAULT_STATE))
    opened.add_argument("--dry-run", action="store_true")

    login = subparsers.add_parser("backend-login", help="保留并前置专用 Chrome 登录页；不提交数据查询")
    login.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))
    login.add_argument("--state-file", default=str(DEFAULT_STATE))

    status = subparsers.add_parser("backend-status", help="只检查专用会话是否存活")
    status.add_argument("--state-file", default=str(DEFAULT_STATE))

    ensure = subparsers.add_parser("backend-ensure", help="复用或自动重启同一专用 Chrome 会话")
    ensure.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))
    ensure.add_argument("--state-file", default=str(DEFAULT_STATE))

    export = subparsers.add_parser("backend-export", help="优先复用专用活动 Chrome 会话导出")
    export.add_argument("--date-range", required=True)
    export.add_argument("--material-range", default="")
    export.add_argument("--output", default="")
    export.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    export.add_argument("--cookie-file", default="")
    export.add_argument("--cookie-env", default="RONGYAO_BACKEND_COOKIE")
    export.add_argument("--chrome-profile", default="Default")
    export.add_argument("--host", default="data.houtai.cn.sy.backend.example.invalid")
    export.add_argument("--market-path", default=DEFAULT_MARKET_PATH)
    export.add_argument("--gid", default="193")
    export.add_argument("--date-group", default="tenyear")
    export.add_argument("--group", default="mid")
    export.add_argument("--timeout", type=int, default=240)
    export.add_argument("--format", choices=("json", "text"), default="json")
    export.add_argument("--state-file", default=str(DEFAULT_STATE))
    export.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))
    export.add_argument("--require-active", action="store_true")
    export.add_argument("--no-auto-recover", action="store_false", dest="auto_recover")
    export.set_defaults(auto_recover=True)

    subparsers.add_parser("self-test", help="运行无网络安全自检")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "backend-open":
        return run_open(args)
    if args.command == "backend-login":
        return run_login(args)
    if args.command == "backend-status":
        return run_status(args)
    if args.command == "backend-ensure":
        return run_ensure(args)
    if args.command == "backend-export":
        return run_export(args)
    if args.command == "self-test":
        result = run_node("self-test", timeout=15)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    raise SystemExit("unknown command")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error)) from error
