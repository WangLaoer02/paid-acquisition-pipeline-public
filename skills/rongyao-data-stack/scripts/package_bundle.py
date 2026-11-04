#!/usr/bin/env python3
"""Create a credential-free portable archive of the Codex 荣耀 Skill stack."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable


SKILLS = (
    "rongyao-data-stack",
    "rongyao-dashboard-filter-finder",
    "rongyao-material-performance",
    "rongyao-material-analysis",
)
OPTIONAL_SKILLS = ("rongyao-keyring",)
EXCLUDED_PARTS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAMES = {".DS_Store"}
SECRET_PATTERNS = {
    "personal_path": re.compile(rb"(?:[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][^\s`\"']+|/(?:Users|home)/[A-Za-z0-9_.-]+/)"),
    "account_literal": re.compile(rb"user_id=[0-9]+"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(rb"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"),
    "openai_key": re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    "slack_token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
}


def default_skills_root() -> Path:
    configured = os.environ.get("AGENTS_SKILLS", "").strip()
    if configured:return Path(configured).expanduser()
    source=Path(__file__).resolve().parents[2]
    installed=Path(os.environ.get("CODEX_HOME",Path.home()/".codex"))/"skills"
    if (installed/"rongyao-data-stack").resolve()==source/"rongyao-data-stack":return installed
    return source


def eligible_files(root: Path) -> Iterable[tuple[str, Path]]:
    # A directory alias is one installed Skill, not an extra implementation.
    # Copy only allowlisted regular files; nested links and private targets remain forbidden.
    manifest=json.loads((root/"rongyao-data-stack/references/bundle-files.json").read_text(encoding="utf-8"))
    selected=list(SKILLS);allowlist=list(manifest['files'])
    optional=manifest.get('optionalFiles',{})
    if set(optional)-set(OPTIONAL_SKILLS):raise SystemExit('Unknown optional Skill')
    for name,paths in optional.items():
        if any(not p.startswith(name+'/') for p in paths):raise SystemExit('Invalid optional allowlist')
        if (root/name).exists():selected.append(name);allowlist.extend(paths)
    for skill in selected:
        folder=root/skill
        if 'private-skills' in folder.resolve().parts or (folder/'.private-skill').exists() or re.search(r'^private:\s*true\s*$',(folder/'SKILL.md').read_text(encoding='utf-8'),re.M):
            raise SystemExit('Private Skill cannot be packaged: '+skill)
    for relative in allowlist:
        parts=Path(relative).parts;path=root/relative
        if not parts or parts[0] not in selected or Path(relative).is_absolute() or '..' in parts:raise SystemExit('Invalid bundle allowlist path')
        canonical=(root/parts[0]).resolve()
        if not path.resolve().is_relative_to(canonical) or path.is_symlink() or not path.is_file():raise SystemExit('Missing or nonportable allowlisted file: '+relative)
        yield parts[0],path


def scan_secrets(path: Path, raw: bytes) -> None:
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(raw):
            raise SystemExit(f"拒绝打包：{path} 命中 {label}。")


def archive_name(root: Path, skill: str, path: Path) -> str:
    return (Path("skills") / skill / path.relative_to(root / skill)).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    root = Path(args.skills_root).expanduser() if args.skills_root else default_skills_root()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = output_dir / (args.name or f"rongyao-codex-skills-{stamp}.tar.gz")
    if Path(args.name).name != args.name or ".." in Path(args.name).parts:
        raise SystemExit("Archive name must be a basename")
    if archive.exists():
        raise SystemExit("Archive already exists; choose a new name")
    if archive.suffixes[-2:] != [".tar", ".gz"]:
        archive = archive.with_name(archive.name + ".tar.gz")

    manifest_files = []
    files = list(eligible_files(root))
    handoff_path = root / "rongyao-data-stack/references/codex-handoff.md"
    if not handoff_path.is_file():
        raise SystemExit(f"缺少 Codex 根入口说明：{handoff_path}")
    # Scan every selected file before creating an archive; a failure leaves no partial archive.
    for _, path in files:
        scan_secrets(path, path.read_bytes())
    with tarfile.open(archive, "w:gz") as bundle:
        for skill, path in files:
            raw = path.read_bytes()
            scan_secrets(path, raw)
            arcname = archive_name(root, skill, path)
            info = tarfile.TarInfo(arcname)
            info.size = len(raw)
            info.mode = 0o644
            with path.open("rb") as handle:
                bundle.addfile(info, handle)
            manifest_files.append(
                {
                    "path": arcname,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        handoff_raw = handoff_path.read_bytes()
        scan_secrets(handoff_path, handoff_raw)
        handoff_info = tarfile.TarInfo("START_HERE_FOR_CODEX.md")
        handoff_info.size = len(handoff_raw)
        handoff_info.mode = 0o644
        bundle.addfile(handoff_info, io.BytesIO(handoff_raw))
        manifest = {
            "format": "rongyao-codex-skill-bundle-v2",
            "version": json.loads((root / "rongyao-data-stack/references/bundle-files.json").read_text(encoding="utf-8"))["version"],
            "validation_scope": "offline_candidate_only",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "entrypoint": "START_HERE_FOR_CODEX.md",
            "target_runtime": "Codex",
            "openclaw_required": False,
            "install_layout": (
                "skills/<skill-name> -> "
                "${AGENTS_SKILLS:-${CODEX_HOME:-$HOME/.codex}/skills}/<skill-name>"
            ),
            "skills": sorted(set(skill for skill,_ in files)),
            "optional_dependencies_not_bundled": [name for name in OPTIONAL_SKILLS if name not in {skill for skill,_ in files}],
            "credential_free": True,
            "login_policy": "Use the existing authorized keyring when separately configured; otherwise initialize login on the target machine. No credentials are transferred.",
            "files": manifest_files,
        }
        raw_manifest = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw_manifest)
        info.mode = 0o644
        bundle.addfile(info, io.BytesIO(raw_manifest))

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "ok": True,
                "archive": str(archive),
                "sha256": digest,
                "skills": sorted(set(skill for skill,_ in files)),
            "optional_dependencies_not_bundled": [name for name in OPTIONAL_SKILLS if name not in {skill for skill,_ in files}],
                "file_count": len(manifest_files),
                "entrypoint": "START_HERE_FOR_CODEX.md",
                "credential_free": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
