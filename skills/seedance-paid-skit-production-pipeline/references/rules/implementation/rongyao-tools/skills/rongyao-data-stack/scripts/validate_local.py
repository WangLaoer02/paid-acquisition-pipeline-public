#!/usr/bin/env python3
"""Run installed-skill checks only; never log in or issue a backend query."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ("rongyao-data-stack", "rongyao-dashboard-filter-finder",
          "rongyao-material-performance", "rongyao-material-analysis")


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ required; use a verified interpreter")
    if importlib.util.find_spec("yaml") is None:
        raise SystemExit("PyYAML missing: use the isolated validation environment; no checks were skipped as passed")
    if importlib.util.find_spec("cryptography") is None:
        raise SystemExit("cryptography missing: required for synthetic encryption regressions")
    import yaml
    for name in SKILLS:
        source = (ROOT / name / "SKILL.md").read_text(encoding="utf-8")
        front = yaml.safe_load(source.split("---", 2)[1])
        if front.get("name") != name or not isinstance(front.get("description"), str) or not front["description"].strip():
            raise SystemExit(f"Invalid Skill metadata: {name}")
    for name in SKILLS[:3]:
        subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s",
                        str(ROOT / name / "scripts"), "-p", "test_*.py", "-v"], check=True)
    for script, arguments in (("static_reference_check.py", []),
                              ("active_session_cli.py", ["self-test"])):
        subprocess.run([sys.executable, "-B", str(ROOT / SKILLS[0] / "scripts" / script), *arguments], check=True)
    print(json.dumps({"ok": True, "scope": "installed_offline_tests_only",
                      "authenticated_live_validation": "NOT_RUN"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
