#!/usr/bin/env python3
"""安装「接B·命名·上传」技能并建好买量工作台。macOS、Windows 通用。

做的事：建工作台（默认 ~/买量工作台，已有就补齐）→ 装技能到 Codex → 导入团队配置 → 搬入旧版数据 → 检查 → 刷新看板。
不登录、不上传、不改系统设置。已有的团队配置绝不会被示例配置覆盖。

用法：python3 install.py [--root 路径] [--designer D] [--config 团队配置.zip] [--pipeline 管线工作区]
"""
import argparse
import datetime as dt
import filecmp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "ab-join-name-upload"
SRC_SKILL = HERE / "skill" / NAME
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", ".claude")


def say(msg=""):
    print(msg, flush=True)


def abtool(script, *args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(script), *args], capture_output=True, env=env)
    text = r.stdout.decode("utf-8", "replace")
    try:
        data = json.loads(text) if text.strip().startswith("{") else {"raw": text.strip()}
    except ValueError:
        data = {"raw": text.strip()}
    if r.returncode != 0 and "error" not in data:
        data["error"] = (r.stderr.decode("utf-8", "replace").strip() or text.strip())[-500:]
    data["_rc"] = r.returncode
    return data


def same_tree(a, b):
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".DS_Store", ".claude"])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    if any(not filecmp.cmp(a / f, b / f, shallow=False) for f in cmp.common_files):
        return False
    return all(same_tree(a / d, b / d) for d in cmp.common_dirs)


def install_skill():
    skills = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills"
    dest = skills / NAME
    skills.mkdir(parents=True, exist_ok=True)
    if dest.is_dir() and same_tree(SRC_SKILL, dest):
        return dest, "已是同一版本"
    if dest.exists():
        bk = skills / f".ab-backup-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
        bk.mkdir()
        shutil.move(str(dest), str(bk / NAME))
        shutil.copytree(SRC_SKILL, dest, ignore=IGNORE)
        return dest, f"已升级；旧版本保留在 {bk}"
    shutil.copytree(SRC_SKILL, dest, ignore=IGNORE)
    return dest, "已安装"


def find_config(arg, downloads):
    if arg:
        return Path(arg).expanduser()
    if (HERE / "team-config").is_dir():
        return HERE / "team-config"
    zips = [p for d in (HERE, downloads) if d.is_dir() for p in d.glob("团队配置*.zip")]
    return max(zips, key=lambda p: p.stat().st_mtime) if zips else None


def ffmpeg_hint():
    if os.name == "nt":
        return "Windows：在 PowerShell 运行 winget install Gyan.FFmpeg（或从 https://ffmpeg.org/download.html 安装），装好后重新打开终端再安装一次。"
    if shutil.which("brew"):
        return "macOS：在终端运行 brew install ffmpeg，装好后再安装一次。"
    return "macOS：请从 https://ffmpeg.org/download.html 安装 FFmpeg，或找负责人要安装方式。"


def main():
    ap = argparse.ArgumentParser(description="安装接B技能并建好买量工作台（macOS / Windows）")
    ap.add_argument("--root", help="工作台位置，默认 ~/买量工作台（已有工作台就沿用）")
    ap.add_argument("--designer", help="本人设计师码，如 D")
    ap.add_argument("--config", help="团队配置 zip 或文件夹；不给就找“下载”里最新的「团队配置*.zip」")
    ap.add_argument("--pipeline", action="append", help="要在看板上显示状态的买量管线工作区（可多次）")
    ap.add_argument("--upgrade", action="store_true", help="兼容旧参数；现在总是升级并备份旧版本")
    a = ap.parse_args()

    say("== 接B·命名·上传 安装（买量工作台）==")
    if sys.version_info < (3, 9):
        say(f"Python 版本太旧（{sys.version.split()[0]}），需要 3.9 以上：https://www.python.org/downloads/")
        return 1
    problems = []

    # 1. 工作台
    pkg_ab = SRC_SKILL / "scripts" / "abtool.py"
    init_args = ["workspace", "init"]
    for flag, val in (("--root", a.root), ("--designer", a.designer)):
        if val:
            init_args += [flag, val]
    for p in a.pipeline or []:
        init_args += ["--pipeline", p]
    ws = abtool(pkg_ab, *init_args)
    if not ws.get("ok"):
        say("工作台没建好：" + str(ws.get("error")))
        return 1
    say(f"工作台：{ws['workspace']}")

    # 2. 技能
    dest, how = install_skill()
    say(f"技能：{how}（{dest}）")
    ab = dest / "scripts" / "abtool.py"

    # 3. 团队配置（找不到就保留本机已有的；只在完全没有时放示例，示例绝不覆盖已有配置）
    sys.path.insert(0, str(SRC_SKILL / "scripts"))
    import abtool as _ab  # noqa: E402  只借用桌面/下载路径的判断
    cfg = find_config(a.config, _ab.downloads_dir())
    conf_dir = Path(abtool(ab, "workspace", "config-dir").get("raw", ""))
    if cfg:
        r = abtool(ab, "import-config", "--from", str(cfg))
        if r.get("ok"):
            say(f"团队配置：已导入 {cfg.name}")
        else:
            problems.append("团队配置导入失败：" + str(r.get("error")))
    else:
        missing = [n for n in ("codes", "fields", "library") if not (conf_dir / f"{n}.json").is_file()]
        for n in missing:
            ex = dest / "config" / f"{n}.example.json"
            if ex.is_file():
                conf_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ex, conf_dir / f"{n}.json")
        if missing:
            problems.append("还没找到「团队配置」zip：向负责人领取，放进“下载”文件夹后再安装一次")
        else:
            say("团队配置：保留本机已有的")

    # 4. 旧版数据
    m = abtool(ab, "workspace", "migrate")
    moved = len([x for x in m.get("files", []) if x.get("action") == "moved"])
    if moved:
        say(f"旧版数据：已搬进工作台 {moved} 个文件")
    if m.get("conflicts"):
        problems.append(f"旧版数据有 {len(m['conflicts'])} 个文件和工作台里同名但内容不同，没有搬")

    # 5. 检查与看板
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        problems.append("没有找到 FFmpeg（含 ffprobe）。" + ffmpeg_hint())
    doc = abtool(ab, "doctor")
    lib = doc.get("library") or {}
    if lib and not lib.get("reachable"):
        problems.append("选B台连不上：" + str(lib.get("error")))
    b = abtool(ab, "workspace", "board")
    if b.get("ok"):
        say(f"看板：{b.get('path')}")
        link = (b.get("desktop_link") or {})
        if link.get("ok"):
            say(f"桌面快捷方式：{Path(link['path']).name}")
    say()
    if problems or not doc.get("ok"):
        say("安装没有全部完成：")
        for p in problems or ["doctor 未通过：" + json.dumps({k: doc.get(k) for k in ('python_ok', 'ffmpeg', 'codes_json', 'fields_json')}, ensure_ascii=False)]:
            say(" - " + p)
        say("处理后再安装一次即可（不会重复建、不会覆盖你的文件）。")
        return 2
    say("安装完成。双击桌面「买量看板」看进度；在工作台里打开 Codex，按《同事使用说明》那句话开始用。")
    return 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
