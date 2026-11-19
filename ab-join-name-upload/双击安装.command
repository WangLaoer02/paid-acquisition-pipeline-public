#!/bin/bash
# macOS：双击安装「接B·命名·上传」技能并建好买量工作台。不登录、不上传。
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 python3：请先安装 Python 3（https://www.python.org/downloads/），装好后再双击本文件。"
  read -r -p "按回车关闭…" _; exit 1
fi
python3 ./install.py
rc=$?
read -r -p "按回车关闭…" _
exit $rc
