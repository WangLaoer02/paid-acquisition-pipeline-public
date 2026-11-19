#!/usr/bin/env bash
# 安装「接B·命名·上传」Codex Skill。不登录、不改系统设置、不覆盖已有配置。
# 用法：bash install.sh            首次安装
#       bash install.sh --upgrade  升级：旧版本移到 ~/.codex/skills/.ab-backup-<时间>/
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="ab-join-name-upload"
SKILLS="${CODEX_HOME:-$HOME/.codex}/skills"
DEST="$SKILLS/$NAME"
# 配置目录：有工作台时是 工作台/配置，否则是旧版 ~/.ab-join-name-upload
CONF="$(python3 "$HERE/skill/$NAME/scripts/abtool.py" workspace config-dir)"

mkdir -p "$SKILLS" "$CONF"
if [ -e "$DEST" ]; then
  if diff -rq "$HERE/skill/$NAME" "$DEST" >/dev/null 2>&1; then
    echo "已是同一版本：$DEST"
  elif [ "${1:-}" = "--upgrade" ]; then
    BK="$SKILLS/.ab-backup-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$BK"; mv "$DEST" "$BK/"
    cp -R "$HERE/skill/$NAME" "$DEST"
    echo "已升级；旧版本保留在 $BK"
  else
    echo "已存在不同版本：$DEST"
    echo "没有改动。确认要升级时运行：bash install.sh --upgrade"
    exit 2
  fi
else
  cp -R "$HERE/skill/$NAME" "$DEST"
  echo "已安装：$DEST"
fi

TS="$(date +%Y%m%d%H%M%S)"
for f in codes fields library; do
  SRC="$HERE/team-config/$f.json"
  [ -f "$SRC" ] || SRC="$DEST/config/$f.example.json"
  if [ ! -e "$CONF/$f.json" ]; then
    cp "$SRC" "$CONF/$f.json"; echo "已放入团队配置：$CONF/$f.json"
  elif cmp -s "$SRC" "$CONF/$f.json"; then
    echo "团队配置已是最新：$f.json"
  elif [ "$SRC" != "$HERE/team-config/$f.json" ]; then
    # 公开版只有示例配置：本机已有的（导入过的团队配置）绝不用示例覆盖
    echo "保留本机团队配置：$f.json（升级不会用示例配置覆盖）"
  elif [ "$f" = "library" ] && [ "$SRC" = "$HERE/team-config/library.json" ] && [ "${KEEP_LIBRARY:-}" = "1" ]; then
    echo "保留本机选B台地址：$CONF/$f.json"
  else
    cp "$CONF/$f.json" "$CONF/$f.json.bak-$TS"; cp "$SRC" "$CONF/$f.json"
    echo "已更新团队配置：$f.json（旧的备份为 $f.json.bak-$TS）"
  fi
done

if [ ! -d "$HERE/team-config" ]; then
  echo "提示：公开版不含团队配置。拿到负责人发的『团队配置』zip 后运行："
  echo "  python3 \"$DEST/scripts/abtool.py\" import-config --from <团队配置.zip>"
fi
python3 "$DEST/scripts/abtool.py" doctor || {
  echo "doctor 未通过：按上面的输出补齐（通常是安装 FFmpeg）后重跑 install.sh"; exit 2; }
