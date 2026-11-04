#!/usr/bin/env python3
"""Install the current short-drama tools progressively; never generate or log in."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def verify():
    manifest = read_json(ROOT / "manifest.json")
    for item in manifest["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("清单含不安全路径")
        path = ROOT / item["path"]
        if any((ROOT / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
            raise ValueError("清单引用符号链接")
        if not path.is_file() or sha(path.read_bytes()) != item["sha256"]:
            raise ValueError("安装包校验失败：" + item["path"])
    return manifest


def package_files(name, manifest):
    if name == "paid-skit-progressive-setup":
        out = {i["path"]: (ROOT / i["path"]).read_bytes() for i in manifest["files"]}
        out["manifest.json"] = (ROOT / "manifest.json").read_bytes()
        return out
    meta = manifest["packages"][name]
    if meta.get("external"):
        raise ValueError("EXTERNAL_DEPENDENCY_REQUIRED: " + name + "; " + meta["source"])
    archive = ROOT / meta["archive"]
    with zipfile.ZipFile(archive) as z:
        files = {}
        for item in z.infolist():
            path = Path(item.filename)
            if item.is_dir():
                continue
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename:
                raise ValueError("归档含不安全路径")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("归档含符号链接")
            data = z.read(item)
            if sha(data) != meta["files"].get(item.filename):
                raise ValueError("源文件哈希不一致：" + name + "/" + item.filename)
            files[item.filename] = data
        if set(files) != set(meta["files"]):
            raise ValueError("归档清单不一致：" + name)
        return files


def names_for(args, manifest):
    names = list(manifest["phases"][args.phase]["skills"])
    if args.phase in ("4", "5") and args.backend == "dreamina":
        names = [n for n in names if not n.startswith("rongyao-")] + ["dreamina-canvas-cli"]
    return names


def state_for(name, destination, manifest):
    if manifest["packages"].get(name, {}).get("external"):
        return "external_present_unverified" if (destination/"SKILL.md").is_file() else "external_missing"
    if not destination.exists() and not destination.is_symlink():
        return "missing"
    if destination.is_symlink() or not destination.is_dir():
        return "conflict"
    if name in {"paid-skit-production-pipeline", "douyin-video"}:
        canonical = destination.parent / ("seedance-paid-skit-production-pipeline" if name == "paid-skit-production-pipeline" else "seedance-douyin-video")
        for part in (("references", "scripts") if name == "paid-skit-production-pipeline" else ("references", "scripts", "recipes")):
            link = destination / part
            if not link.is_symlink() or link.resolve() != (canonical / part).resolve():
                return "conflict"
    for relative, data in package_files(name, manifest).items():
        existing = destination / relative
        if any((destination / Path(*Path(relative).parts[:i])).is_symlink() for i in range(1, len(Path(relative).parts) + 1)):
            return "conflict"
        if not existing.is_file() or existing.is_symlink() or sha(existing.read_bytes()) != sha(data):
            return "conflict"
    return "identical"


def default_skills():
    codex_dir = os.environ.get("CODEX_HOME")
    return Path(codex_dir).expanduser() / "skills" if codex_dir else Path.home() / ".codex/skills"


def guard_path(root, path):
    """Reject links below the selected root, including dangling links."""
    relative = path.relative_to(root)
    for count in range(1, len(relative.parts) + 1):
        current = root / Path(*relative.parts[:count])
        if current.is_symlink():
            raise ValueError("保留符号链接目标；未写入或执行：" + str(current))


def guard_state(args):
    guard_path(args.tool_root, args.tool_root / "installation-state.json")


def record(args, entry):
    guard_state(args)
    args.tool_root.mkdir(parents=True, exist_ok=True)
    path = args.tool_root / "installation-state.json"
    state = read_json(path) if path.exists() else {"purpose": "installation_only", "events": []}
    state["events"].append(entry)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.tool_root,
                                     prefix=".installation-state-", delete=False) as stream:
        stream.write(json.dumps(state, ensure_ascii=False, indent=2))
        temp = Path(stream.name)
    try:
        guard_state(args)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def install(args, manifest):
    guard_state(args)
    names = names_for(args, manifest)
    states = {n: state_for(n, args.skills_dir / n, manifest) for n in names}
    conflicts = [n for n, status in states.items() if status == "conflict"]
    if conflicts:
        raise ValueError("保留已有Skill，本阶段未写入；需逐文件核对冲突：" + ", ".join(conflicts))
    args.skills_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    for name in names:
        if states[name] == "identical" or manifest["packages"].get(name, {}).get("external"):
            continue
        destination = args.skills_dir / name
        with tempfile.TemporaryDirectory(prefix=".skit-install-", dir=args.skills_dir) as tmp:
            staged = Path(tmp) / name
            staged.mkdir()
            for relative, data in package_files(name, manifest).items():
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if name in {"paid-skit-production-pipeline", "douyin-video"}:
                canonical = "seedance-paid-skit-production-pipeline" if name == "paid-skit-production-pipeline" else "seedance-douyin-video"
                for part in (("references", "scripts") if name == "paid-skit-production-pipeline" else ("references", "scripts", "recipes")):
                    (staged / part).symlink_to(Path("..") / canonical / part, target_is_directory=True)
            if destination.exists() or destination.is_symlink():
                raise ValueError("目标在安装期间出现，已保留：" + str(destination))
            staged.rename(destination)
        installed.append(name)
    entry = {"phase": args.phase, "backend": args.backend, "files_installed": installed,
             "identical_skipped": [n for n, s in states.items() if s == "identical"],
             "external_dependencies": {n: states[n] for n in names if manifest["packages"].get(n, {}).get("external")},
             "business_phase_passed": False, "accounts_authorized": False}
    record(args, entry)
    emit(entry)


def tool_binary(args, name):
    local = args.tool_root / "npm/node_modules/.bin" / (name + (".cmd" if os.name == "nt" else ""))
    guard_path(args.tool_root, local.parent)
    return str(local) if local.is_file() else shutil.which(name)


def doctor(args, manifest):
    names = names_for(args, manifest)
    installed = {n: state_for(n, args.skills_dir / n, manifest) for n in names}
    checks = {"python_3_10_plus": sys.version_info >= (3, 10),
              "platform": platform.system(), "skills": installed}
    needed = {"0": ["lark-cli"], "1": ["ffmpeg", "ffprobe"],
              "4": ["node"] if args.backend == "rongyao" else ["dreamina-canvas"],
              "5": ["ffmpeg", "ffprobe"], "6": ["ffmpeg", "ffprobe"],
              "7": ["ffmpeg", "ffprobe"]}.get(args.phase, [])
    checks["binaries"] = {n: bool(tool_binary(args, n)) for n in needed}
    if args.phase == "4" and args.backend == "rongyao" and shutil.which("node"):
        result = subprocess.run([shutil.which("node"), "-e", "process.exit(typeof WebSocket === 'function' ? 0 : 1)"], capture_output=True)
        checks["cdp_websocket_if_using_cdp"] = result.returncode == 0
    checks["manual_gates"] = manifest["phases"][args.phase].get("manual_gates", [])
    checks["conditional_dependencies"] = manifest.get("conditional_dependencies", [])
    required_profile = {"1": "media", "6": "premiere", "upload": "upload"}.get(args.phase)
    if required_profile:
        guard_path(args.tool_root, args.tool_root / "envs" / required_profile)
        interpreter = env_python(args.tool_root / "envs" / required_profile)
        guard_path(args.tool_root, interpreter.parent)
        ok = False
        if interpreter.is_file():
            probe = read_json(ROOT / "references/environment-probes.json")[required_profile]
            result = subprocess.run([str(interpreter), "-c", probe], capture_output=True)
            ok = result.returncode == 0
        checks["environment"] = {"profile": required_profile, "imports_verified": ok}
    checks["files_ready"] = all(s in ("identical", "external_present_unverified") for s in installed.values())
    checks["external_compatibility_verified"] = False
    checks["software_probe_passed"] = checks["python_3_10_plus"] and all(checks["binaries"].values())
    if required_profile:
        checks["software_probe_passed"] = checks["software_probe_passed"] and checks["environment"]["imports_verified"]
    checks["production_authorized"] = False
    checks["native_premiere_reopen_verified"] = False
    emit(checks)
    return 0 if checks["files_ready"] and checks["software_probe_passed"] else 2


def env_python(path):
    return path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def env_install(args):
    lock = ROOT / "requirements" / (args.profile + ".txt")
    if not lock.is_file():
        raise ValueError("未知环境配置")
    target = args.tool_root / "envs" / args.profile
    marker = target / ".skit-lock.sha256"
    guard_path(args.tool_root, marker)
    guard_path(args.tool_root, env_python(target).parent)
    guard_state(args)
    if args.ca_bundle and not args.ca_bundle.expanduser().is_file():
        raise ValueError("指定的受信任CA文件不存在")
    if target.exists() and (not marker.exists() or marker.read_text().strip() != sha(lock.read_bytes())):
        raise ValueError("保留已有环境；需人工核对环境与锁文件：" + str(target))
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True).create(target)
        marker.write_text(sha(lock.read_bytes()), encoding="utf-8")
    command = [str(env_python(target)), "-m", "pip", "install", "-r", str(lock)]
    guard_path(args.tool_root, env_python(target).parent)
    if args.ca_bundle:
        if not args.ca_bundle.expanduser().is_file():
            raise ValueError("指定的受信任CA文件不存在")
        command += ["--cert", str(args.ca_bundle.expanduser().resolve())]
    result = subprocess.run(command)
    if result.returncode:
        raise ValueError("依赖安装失败；保留环境以续接，未标可用")
    probe = read_json(ROOT / "references/environment-probes.json")[args.profile]
    check = subprocess.run([str(env_python(target)), "-c", probe], capture_output=True, text=True)
    if check.returncode:
        raise ValueError("依赖导入检查失败；未标可用")
    entry = {"environment": args.profile, "python": str(env_python(target)), "imports_verified": True,
             "model_weights_installed": False, "native_premiere_verified": False}
    record(args, entry)
    emit(entry)


def install_feishu(args):
    destination = args.tool_root / "npm"
    pkg = destination / "node_modules/@larksuite/cli/package.json"
    guard_path(args.tool_root, pkg)
    guard_path(args.tool_root, destination / "node_modules/.bin")
    guard_state(args)
    if pkg.exists() and read_json(pkg).get("version") != "1.0.93":
        raise ValueError("保留已有CLI版本，未升级或覆盖")
    existing = shutil.which("lark-cli")
    if existing and not pkg.exists():
        emit({"existing_cli_preserved": True, "next": "核对现有lark-cli --version及所需shortcut，兼容则直接复用"})
        return
    npm = shutil.which("npm")
    if not npm:
        raise ValueError("缺npm：先通过Node官方安装来源准备Node与npm")
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([npm, "install", "--prefix", str(destination), "@larksuite/cli@1.0.93"])
    if result.returncode or not pkg.exists():
        raise ValueError("CLI安装未完成")
    binary = tool_binary(args, "lark-cli")
    check = subprocess.run([binary, "--version"], capture_output=True, text=True)
    if check.returncode:
        raise ValueError("CLI版本探测未通过")
    emit({"cli_version": "1.0.93", "binary": binary, "login_performed": False,
          "next": "读取lark-shared，在接收者自己的身份下配置与登录"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=default_skills())
    parser.add_argument("--tool-root", type=Path, default=Path.home() / ".local/share/codex-tools/paid-skit")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("verify")
    for command in ("plan", "install", "doctor"):
        p = subs.add_parser(command)
        p.add_argument("--phase", choices=["bootstrap", "cleanup", "upload", "seedance-specialists", "asset-turnaround", "asset-catalog", "asset-archive", "asset-image", "naruto-b-library"] + [str(i) for i in range(8)], required=True)
        p.add_argument("--backend", choices=["rongyao", "dreamina"], default="rongyao")
    p = subs.add_parser("env-install")
    p.add_argument("--profile", choices=["media", "vision", "speech", "align", "premiere", "upload"], required=True)
    p.add_argument("--ca-bundle", type=Path, help="Explicit trusted CA bundle; certificate checks remain enabled")
    subs.add_parser("tool-install-feishu")
    p = subs.add_parser("path")
    p.add_argument("--skill", required=True)
    p.add_argument("--file", default="SKILL.md")
    args = parser.parse_args()
    args.skills_dir = args.skills_dir.expanduser().resolve()
    args.tool_root = args.tool_root.expanduser().resolve()
    try:
        manifest = verify()
        if manifest.get("local_revision", {}).get("publication_status") == "local_maintenance_not_cloud_published" and args.command not in {"verify", "plan", "doctor", "path"}:
            if args.command != "install" or "--skills-dir" not in sys.argv or "--tool-root" not in sys.argv:
                raise ValueError("LOCAL_CANDIDATE: only explicit isolated Skill installation is supported; no environment installation or business actions")
            protected = [Path.home()/".codex", Path.home()/".agents", Path.home()/".local/share/codex-tools"]
            if any(p.resolve().is_relative_to(r.resolve()) for p in [args.skills_dir,args.tool_root] for r in protected):
                raise ValueError("LOCAL_CANDIDATE: preserve installed user Skills and fixed deployments")
        if args.command == "verify": emit({"verified_files": len(manifest["files"]), "packages": len(manifest["packages"])})
        elif args.command == "plan":
            names = names_for(args, manifest)
            actions = dict(manifest["phases"][args.phase])
            actions["skills"] = names
            emit({"phase": args.phase, "skills": {n: state_for(n, args.skills_dir / n, manifest) for n in names},
                  "actions": actions, "writes_performed": False})
        elif args.command == "install": install(args, manifest)
        elif args.command == "doctor": return doctor(args, manifest)
        elif args.command == "env-install": env_install(args)
        elif args.command == "tool-install-feishu": install_feishu(args)
        elif args.command == "path":
            if args.skill not in manifest["packages"] and args.skill != "paid-skit-progressive-setup":
                raise ValueError("未收录的Skill")
            relative = Path(args.file)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("文件参数必须是Skill内部相对路径")
            target = args.skills_dir / args.skill / relative
            if not target.is_file() or not target.resolve().is_relative_to((args.skills_dir / args.skill).resolve()):
                raise ValueError("尚未安装或引用越界")
            emit({"path": str(target)})
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        emit({"ok": False, "reason": str(exc), "no_overwrite": True})
        return 2


if __name__ == "__main__":
    sys.exit(main())
