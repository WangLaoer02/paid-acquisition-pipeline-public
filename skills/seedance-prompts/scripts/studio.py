"""Optional workbench CLI, with its implementation shipped in this Skill."""
from pathlib import Path
import json
import runpy
import sys

runtime = Path(__file__).resolve().parents[1] / 'runtime/studio'
required = ('studio.py', 'store.py', 'catalog.py', 'diagnostics.py', 'configuration.py')
missing = [name for name in required if not (runtime / name).is_file()]
if missing:
    raise SystemExit('WORKBENCH_PACKAGE_INCOMPLETE: ' + ', '.join(missing))
sys.path.insert(0, str(runtime))
if sys.argv[1:] == ['--diagnose']:
    from configuration import runtime_info
    print(json.dumps(runtime_info(), ensure_ascii=False, indent=2))
else:
    runpy.run_path(str(runtime / 'studio.py'), run_name='__main__')
