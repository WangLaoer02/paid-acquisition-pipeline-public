#!/usr/bin/env python3
"""Check installed references without truncating paths or following ../ via symlinks.

The selected skills root is a logical installation namespace. Bare references/
 and scripts/ paths are skill-root relative; Markdown links and explicit ./ or
../ paths are document-relative. A leading skill-name/ is skills-root relative.
Normalize lexically BEFORE opening files, so a linked skill has the same sibling
namespace as a physical installation. See runtime-and-validation.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")

# Do not resolve symlinks here: callers select the installation namespace.
SKILLS = Path(os.path.abspath(__file__)).parents[2]
TARGETS = ["rongyao-data-stack", "rongyao-dashboard-filter-finder",
           "rongyao-material-performance", "rongyao-material-analysis"]
# Exact external reference, not a filename/suffix exemption for other links.
OPTIONAL_EXTERNAL_REFERENCES = {
    ("rongyao-data-stack/references/portability.md",
     "$HOME/Documents/荣耀统计后台/scripts/weekly_report_cli.py"):
        "Optional legacy external helper; bundled transport remains available.",
}
LINK = re.compile(r"\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)")
DEFINITION = re.compile(r'^ {0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|([^\s]+))[^\n]*$', re.M)
REFERENCE_USE = re.compile(r'\[([^\]\n]+)\](?:[ \t]*\[([^\]\n]*)\])?')
TOKEN = re.compile(r"[^\s`\"'()\[\]，。；：、]+")
LOCAL_FILE = re.compile(r"\.(?:md|py|mjs|js|json|yaml|yml|sh|ps1|txt)(?:[?#].*)?$", re.I)


def references(text):
    """Yield complete local link/code paths once; never search for a suffix."""
    seen = set()
    for match in LINK.finditer(text):
        value = match.group(1) or match.group(2)
        if value not in seen:
            seen.add(value)
            yield value, True
    # Standard full/collapsed/shortcut reference links use document-relative
    # destinations from definitions; labels are case/whitespace insensitive.
    normalize_label = lambda label: " ".join(label.split()).casefold()
    definitions = {}
    for match in DEFINITION.finditer(text):
        definitions.setdefault(normalize_label(match.group(1)), match.group(2) or match.group(3))
    plain = DEFINITION.sub(" ", LINK.sub(" ", text))
    for match in REFERENCE_USE.finditer(plain):
        label = normalize_label(match.group(2) or match.group(1))
        value = definitions.get(label)
        if value and value not in seen:
            seen.add(value)
            yield value, True
    # Mask links/definitions so relative paths are not also root-relative tokens.
    for match in TOKEN.finditer(plain):
        value = match.group().rstrip(",.;")
        if "/" not in value or not LOCAL_FILE.search(value):
            continue
        if value not in seen:
            seen.add(value)
            yield value, False


def resolve_reference(skills, root, markdown, reference, is_link=False):
    """Return (path, disposition); optional/template/remote paths are explicit."""
    relative_doc = markdown.relative_to(skills).as_posix()
    if (relative_doc, reference) in OPTIONAL_EXTERNAL_REFERENCES:
        return None, "optional_external"
    if reference.startswith("#") or urlsplit(reference).scheme or reference.startswith("//"):
        return None, "remote_or_anchor"
    if any(marker in reference for marker in ("$", "<", ">", "{", "}", "*")):
        return None, "template"
    path = unquote(reference.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return None, "remote_or_anchor"
    target = Path(path).expanduser()
    if target.is_absolute():
        base = Path("/")
    elif path.startswith(("./", "../")) or is_link:
        base = markdown.parent
    elif path.startswith(("references/", "scripts/", "assets/", "agents/")):
        base = root
    elif path.startswith("skills/") and path.split("/", 2)[1] in TARGETS:
        base = skills
        target = Path(path.removeprefix("skills/"))
    elif "/" in path:
        base = skills  # skill-name/path: no probe of unrelated skill roots
    else:
        base = markdown.parent
    return Path(os.path.abspath(os.path.join(base, target))), "required"



def markdown_files(root, errors):
    """Follow child directory aliases while retaining logical document paths.

    Track physical ancestors per branch to reject cycles without deduplicating
    distinct logical aliases, whose document-relative links can differ.
    """
    def visit(directory, ancestors):
        try:
            stat = directory.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity in ancestors:
                errors.append(f'reference_scan_cycle:{directory}')
                return
            children = sorted(directory.iterdir())
            for child in children:
                if child.is_dir():
                    yield from visit(child, ancestors | {identity})
                elif child.suffix.lower() == '.md':
                    if child.is_file():
                        yield child
                    else:
                        errors.append(f'reference_scan_unreadable:{child}')
        except OSError as error:
            errors.append(f'reference_scan_failed:{directory}:{error.__class__.__name__}')
    yield from visit(root, set())


def check(skills=None):
    skills = Path(os.path.abspath(skills if skills is not None else SKILLS))
    errors, skipped, resolved = [], [], []
    for skill_name in TARGETS:
        root = skills / skill_name
        if not (root / "SKILL.md").is_file():
            errors.append(f"missing:{root / 'SKILL.md'}")
            continue
        for markdown in markdown_files(root, errors):
            for reference, is_link in references(markdown.read_text(encoding="utf-8")):
                target, disposition = resolve_reference(skills, root, markdown, reference, is_link)
                record = {"document": str(markdown), "reference": reference}
                if disposition != "required":
                    skipped.append({**record, "reason": disposition})
                    continue
                resolved.append({**record, "target": str(target)})
                if not target.is_file():
                    errors.append(f"broken_reference:{markdown}:{reference} -> {target}")
    dashboard_scripts = "\n".join(path.read_text(encoding="utf-8")
        for path in (skills / "rongyao-dashboard-filter-finder/scripts").glob("capture_*.py"))
    for forbidden in ("backend_cookie_header(", "backend_http_request(", "weekly_report_cli.py"):
        if forbidden in dashboard_scripts:
            errors.append(f"dashboard_bypasses_universal_transport:{forbidden}")
    analysis = skills / "rongyao-material-analysis/SKILL.md"
    if analysis.is_file() and "本 Skill 不抓取后台" not in analysis.read_text(encoding="utf-8"):
        errors.append("analysis_capture_boundary_missing")
    bridge = skills / "rongyao-data-stack/scripts/active_chrome_bridge.mjs"
    if not bridge.is_file():
        errors.append(f"missing:{bridge}")
    else:
        for forbidden in ("document.cookie", "localStorage", "sessionStorage"):
            if any(forbidden in line and "expression.includes" not in line
                   for line in bridge.read_text(encoding="utf-8").splitlines()):
                errors.append(f"active_bridge_reads_credentials:{forbidden}")
    return {"ok": not errors, "reference_base": "logical_installation_root",
            "skills_root": str(skills), "references_checked": len(resolved),
            "resolved_references": resolved, "skipped_references": skipped, "errors": errors}


def main(skills=None):
    payload = check(skills)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, help="Logical installation root; symlinks are not resolved first")
    args = parser.parse_args()
    raise SystemExit(main(args.skills_root))
