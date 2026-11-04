#!/usr/bin/env python3
"""Run this workspace's exact released Rongyao CLI; never import an unpinned global copy."""
import runpy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    runpy.run_path(str(ROOT/'workflow/rules/implementation/rongyao-tools/skills/rongyao-operations/scripts/rongyao.py'),run_name='__main__')
