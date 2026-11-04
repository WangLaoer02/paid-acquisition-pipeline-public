"""Install one source directory; optional links expose it to both agents."""
import argparse,json,shutil
from pathlib import Path
def main():
    p=argparse.ArgumentParser();p.add_argument('--destination',required=True);p.add_argument('--register',action='store_true');a=p.parse_args()
    source=Path(__file__).resolve().parent.parent;target=Path(a.destination).expanduser().resolve()
    links=[Path.home()/'.codex/skills/rongyao-http-readonly',Path.home()/'.agents/skills/rongyao-http-readonly']
    if a.register:
        for link in links:
            if link.exists() and not link.is_symlink():raise SystemExit('EXISTING_REAL_SKILL_DIRECTORY_REQUIRES_REVIEW')
    if target!=source:
        if target.exists():raise SystemExit('DESTINATION_EXISTS')
        shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    if a.register:
        for link in links:
            link.parent.mkdir(parents=True,exist_ok=True)
            if link.is_symlink():link.unlink()
            link.symlink_to(target,target_is_directory=True)
    print(json.dumps({'ok':True,'source':str(target),'registered':a.register,'credential_imported':False}))
if __name__=='__main__':main()
