#!/bin/bash
# 双击安装「接B·命名·上传」Codex 技能。只装到本人电脑，不登录、不上传。
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
if [ -d "$HOME/.codex/skills/ab-join-name-upload" ]; then bash ./install.sh --upgrade; else bash ./install.sh; fi
rc=$?
CFG=$(ls -t ./团队配置*.zip "$HOME/Downloads"/团队配置*.zip 2>/dev/null | head -1)
if [ -n "$CFG" ]; then
  echo "导入团队配置：$CFG"
  python3 "$HOME/.codex/skills/ab-join-name-upload/scripts/abtool.py" import-config --from "$CFG" && rc=0
  python3 "$HOME/.codex/skills/ab-join-name-upload/scripts/abtool.py" doctor >/dev/null 2>&1 && echo "团队配置已就绪。"
else
  echo "还没找到『团队配置』zip：请从飞书文档下载到『下载』文件夹后，再双击本文件一次。"
fi
echo
if [ $rc -eq 0 ]; then echo "安装完成。打开 Codex，按《同事使用说明》里的那句话开始用。"; else echo "安装没有完成，请把上面的文字截图发给负责人。"; fi
read -r -p "按回车关闭…" _
exit $rc
