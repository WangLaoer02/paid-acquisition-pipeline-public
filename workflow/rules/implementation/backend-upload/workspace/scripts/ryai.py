#!/usr/bin/env python3
"""Registered generation entry point; actual implementation is release-pinned."""
from pathlib import Path
import runpy
ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT/'workflow/rules/implementation/rongyao-tools/skills/rongyao-ai-generator/scripts/ryai.py'), run_name='__main__')
