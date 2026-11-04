"""Machine configuration only; importing this module never opens or creates a DB."""
from pathlib import Path
import json
import os

BASE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get('SEEDANCE_STUDIO_CONFIG', str(Path.home() / '.config/seedance-studio/config.json'))).expanduser()
if 'SEEDANCE_STUDIO_CONFIG' in os.environ and not CONFIG.is_file():
    raise SystemExit('STUDIO_CONFIG_MISSING: ' + str(CONFIG))
try:
    settings = json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
except (OSError, ValueError) as exc:
    raise SystemExit('STUDIO_CONFIG_INVALID: ' + str(exc))
if not isinstance(settings, dict):
    raise SystemExit('STUDIO_CONFIG_INVALID: expected an object')

def path(value):
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise SystemExit('STUDIO_CONFIG_INVALID: paths must be absolute')
    return p.resolve()

default_skills = Path(os.environ['CODEX_HOME']).expanduser() / 'skills' if os.environ.get('CODEX_HOME') else BASE.parents[2]
SKILLS_ROOT = path(os.environ.get('SEEDANCE_SKILLS_ROOT', settings.get('skills_root', str(default_skills))))
DB = path(os.environ.get('SEEDANCE_STUDIO_DB', settings.get('db', str(Path.home() / '.local/share/seedance-studio/studio.sqlite3'))))
if settings.get('db') and 'SEEDANCE_STUDIO_DB' not in os.environ and not DB.is_file():
    raise SystemExit('STUDIO_DATABASE_MISSING: configured database is absent; restore its location or explicitly configure a new workbench')
roots = os.environ.get('SEEDANCE_STUDIO_MEDIA_ROOTS')
roots = roots.split(os.pathsep) if roots is not None else settings.get('media_roots', [str(Path.home() / 'Documents'), str(Path.home() / 'Downloads')])
if not isinstance(roots, list) or not all(isinstance(p, str) and p for p in roots):
    raise SystemExit('STUDIO_CONFIG_INVALID: media_roots must be a list of paths')
MEDIA_ROOTS = list(dict.fromkeys([path(p) for p in roots] + [DB.parent]))
PORT = int(os.environ.get('SEEDANCE_STUDIO_PORT', settings.get('port', 8786)))
if not 1 <= PORT <= 65535:
    raise SystemExit('STUDIO_CONFIG_INVALID: port outside 1..65535')

def runtime_info():
    return dict(schema='seedance.runtime.v1', runtime=str(BASE), db=str(DB),
                db_exists=DB.is_file(), skills_root=str(SKILLS_ROOT),
                media_roots=[str(p) for p in MEDIA_ROOTS], port=PORT,
                config=str(CONFIG), config_exists=CONFIG.is_file(),
                database_opened=False, business_actions=False)
