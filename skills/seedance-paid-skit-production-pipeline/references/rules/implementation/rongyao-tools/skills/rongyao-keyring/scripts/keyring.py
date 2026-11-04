#!/usr/bin/env python3
"""Build and invoke the fixed, credential-isolated macOS helper."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BINARY = Path.home()/'.codex/state/rongyao-keyring/bin/rongyao-keychain'

def main():
    p = argparse.ArgumentParser(description='荣耀钥匙包；不输出账号密码')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ['build','status','import-existing','check-credentials','ensure-query','ensure-ai','disable']:
        sub.add_parser(name)
    upload = sub.add_parser('verify-upload-chrome')
    upload.add_argument('--entry', choices=['ai'])
    video = sub.add_parser('fast-video')
    actions = video.add_subparsers(dest='video_command', required=True)
    actions.add_parser('status')
    search = actions.add_parser('search')
    for name in ['date-range','material-range','gid']:
        search.add_argument('--'+name, required=True)
    search.add_argument('--keyword', default='')
    search.add_argument('--limit', type=int, choices=range(1,51), default=20)
    search.add_argument('--refresh', action='store_true')
    for name in ['resolve','frames']:
        cmd = actions.add_parser(name); cmd.add_argument('--id', required=True)
        if name == 'frames': cmd.add_argument('--count', type=int, choices=range(2,13), default=8)
    args = p.parse_args()
    # Preserve exact business arguments only after parsing validates them. Help
    # and invalid arguments exit before checking or invoking the native helper.
    arguments = sys.argv[2:]
    if args.command == 'build':
        if BINARY.exists():
            print(json.dumps({'ok':True,'status':'ALREADY_BUILT','rebuilt':False}))
            return 0
        BINARY.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = subprocess.run(['/usr/bin/swiftc',str(ROOT/'keychain.swift'),'-o',str(BINARY),'-framework','Security'],
                                capture_output=True,text=True,timeout=60)
        if result.returncode:
            print(json.dumps({'ok':False,'status':'BUILD_FAILED'}))
            sys.stderr.write(result.stderr)
            return 1
        os.chmod(BINARY,0o700)
        print(json.dumps({'ok':True,'status':'BUILT','credential_read':False}))
        return 0
    if not BINARY.is_file():
        print(json.dumps({'ok':False,'status':'HELPER_NOT_BUILT'}))
        return 1
    try:
        native_args = ['verify-upload-chrome','--entry','ai'] if args.command == 'ensure-ai' else [args.command,*arguments]
        result = subprocess.run([str(BINARY),*native_args], timeout=210)
        if args.command == 'import-existing' and result.returncode == 0:
            marker = BINARY.parent.parent/'provider.json'
            marker.write_text(json.dumps({'provider':'macos-keychain','service':'com.codex.rongyao-keyring',
                                          'account':'existing-rongyao-account','legacy_fallback':False})+'\n')
            os.chmod(marker,0o600)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(json.dumps({'ok':False,'status':'HELPER_TIMEOUT','auto_retry':False}))
        return 1

if __name__ == '__main__':
    sys.exit(main())
