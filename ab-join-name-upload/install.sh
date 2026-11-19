#!/usr/bin/env bash
# 兼容入口：真正的安装逻辑在 install.py（macOS / Windows 通用）。
exec python3 "$(cd "$(dirname "$0")" && pwd)/install.py" "$@"
