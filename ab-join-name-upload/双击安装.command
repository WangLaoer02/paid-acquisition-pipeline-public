#!/bin/bash
# 双击安装「接B·命名·上传」Codex 技能，并建好「买量工作台」。只装到本人电脑，不登录、不上传。
cd "$(dirname "$0")" || exit 1
echo "== 接B·命名·上传 技能安装 =="
if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 python3：请先安装 Python 3（https://www.python.org/downloads/），装好后再双击本文件。"
  read -r -p "按回车关闭…" _; exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "没有找到 FFmpeg。"
  if command -v brew >/dev/null 2>&1; then
    echo "可以在终端运行：brew install ffmpeg   装好后再双击本文件。"
  else
    echo "请找负责人要 FFmpeg 安装方式（或从 https://ffmpeg.org/download.html 安装），装好后再双击本文件。"
  fi
  read -r -p "按回车关闭…" _; exit 1
fi
# 1. 工作台（默认 ~/买量工作台；已有就只补齐，不覆盖）
if ! python3 ./skill/ab-join-name-upload/scripts/abtool.py workspace init >/tmp/ab-ws-init.json; then
  cat /tmp/ab-ws-init.json
  echo "工作台没建好，请把上面的文字截图发给负责人。"
  read -r -p "按回车关闭…" _; exit 1
fi
# 2. 技能
if [ -d "$HOME/.codex/skills/ab-join-name-upload" ]; then bash ./install.sh --upgrade; else bash ./install.sh; fi
rc=$?
AB="$HOME/.codex/skills/ab-join-name-upload/scripts/abtool.py"
# 3. 团队配置
CFG=$(ls -t ./团队配置*.zip "$HOME/Downloads"/团队配置*.zip 2>/dev/null | head -1)
if [ -n "$CFG" ]; then
  echo "导入团队配置：$CFG"
  python3 "$AB" import-config --from "$CFG" >/dev/null && rc=0
  python3 "$AB" doctor >/dev/null 2>&1 && echo "团队配置已就绪。"
else
  echo "还没找到『团队配置』zip：请从飞书文档下载到『下载』文件夹后，再双击本文件一次。"
fi
# 4. 旧版数据（~/.ab-join-name-upload、桌面/待上传）搬进工作台；有冲突的不动
python3 "$AB" workspace migrate >/tmp/ab-ws-migrate.json || echo "有旧文件和工作台里的同名文件内容不同，没有搬，详见 /tmp/ab-ws-migrate.json"
WS=$(python3 -c 'import json;print(json.load(open("/tmp/ab-ws-init.json"))["workspace"])')
echo
if [ $rc -eq 0 ]; then
  echo "安装完成。工作台：$WS"
  echo "桌面上的『今日待上传』就是今天的成片和上传清单。在工作台里打开 Codex，按《同事使用说明》那句话开始用。"
else
  echo "安装没有完成，请把上面的文字截图发给负责人。"
fi
read -r -p "按回车关闭…" _
exit $rc
