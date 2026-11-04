#!/usr/bin/env python3
"""Fixed credential-consuming workers; stdout is structured and secret-free."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STACK = ROOT.parent.parent / 'rongyao-data-stack' / 'scripts'
sys.path.insert(0, str(STACK))

def main():
    import fast_video
    command, *args = sys.argv[1:]
    if command == 'ensure-query':
        result = fast_video.prepare()
        result.update(surface='dedicated_chrome', entry='query',
                      account_identity_verified=False, business_query_performed=False)
    elif command == 'verify-upload-chrome':
        if args not in ([], ['--entry', 'ai']):
            return {'ok': False, 'status': 'INVALID_ENTRY'}
        fast_video.session.ensure_active_session(fast_video.STATE,fast_video.session.DEFAULT_PROFILE)
        probe = 'ai_probe.mjs' if args else 'upload_probe.mjs'
        p = subprocess.run([str(fast_video.session.node_bin()), str(ROOT/probe), str(fast_video.STATE)],
                           capture_output=True, text=True, timeout=90)
        result = json.loads(p.stdout)
        result['credential_provider'] = 'macos-keychain'
    elif command == 'fast-video':
        if not args or args[0] not in {'status', 'search', 'resolve', 'frames'}:
            return {'ok': False, 'status': 'INVALID_VIDEO_COMMAND'}
        p = subprocess.run([sys.executable, str(STACK/'fast_video.py'), *args],
                           capture_output=True, text=True, timeout=180)
        result = json.loads(p.stdout)
    else:
        result = {'ok': False, 'status': 'INVALID_COMMAND'}
    return result

if __name__ == '__main__':
    try:
        result = main()
    except Exception as exc:
        # Exception arguments may contain browser output or credentials.
        kind = type(exc).__name__
        status = 'TIMEOUT' if isinstance(exc, subprocess.TimeoutExpired) else 'LOGIN_OR_TOOL_ERROR'
        safe = str(exc)
        for known in ('LOGIN_OR_VERIFICATION_REQUIRED', 'LOGIN_REQUIRED', 'KEYCHAIN_ACCESS_REQUIRED',
                      'CREDENTIALS_NOT_CONFIGURED', 'PAGE_LOAD_TIMEOUT', 'PAGE_CONFIG_CHANGED'):
            if known in safe:
                status = known
                break
        result = {'ok': False, 'status': status, 'error_type': kind, 'auto_retry': False}
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get('ok', False) else 1)
