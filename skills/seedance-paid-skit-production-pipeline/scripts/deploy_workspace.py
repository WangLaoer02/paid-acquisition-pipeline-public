#!/usr/bin/env python3
"""Deploy a verified Skill's workspace files into an empty or identical workspace; no login, media, or state updates."""
from pathlib import Path
import argparse,hashlib,json,shutil,sys
SKILL=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args();target=a.workspace.expanduser().resolve();rules=SKILL/'references/rules';m=json.loads((rules/'manifest.json').read_text());sources={}
 for path in rules.rglob('*'):
  if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':sources['workflow/rules/'+str(path.relative_to(rules))]=path
 for name,sha in m['workspace_contract_files'].items():
  path=SKILL/'references/workspace-contract'/name
  if not path.is_file() or digest(path)!=sha:raise ValueError('SOURCE_PACKAGE_MISMATCH: '+name)
  sources[name]=path
 for key in ['modules','implementation_files','reference_files']:
  for name,value in m.get(key,{}).items():
   path=rules/(value['path'] if key=='modules' else name);sha=value['sha256'] if key=='modules' else value
   if not path.is_file() or digest(path)!=sha:raise ValueError('SOURCE_RULE_MISMATCH')
 conflicts=[]
 for name,src in sources.items():
  rel=Path(name)
  if rel.is_absolute() or '..' in rel.parts:raise ValueError('UNSAFE_PATH')
  dst=target/rel
  if any((target/Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)):raise ValueError('SYMLINK_TARGET')
  if dst.exists() and (not dst.is_file() or digest(dst)!=digest(src)):conflicts.append(name)
 if conflicts:raise ValueError('EXISTING_WORKSPACE_PRESERVED: '+', '.join(conflicts[:10]))
 written=[]
 if a.apply:
  for name,src in sources.items():
   dst=target/name
   if dst.exists():continue
   dst.parent.mkdir(parents=True,exist_ok=True)
   with dst.open('xb') as out:out.write(src.read_bytes())
   written.append(name)
 print(json.dumps({'ok':True,'files':len(sources),'written':len(written),'project_state_created':False,'business_actions_authorized':False,'publication_status':'public_source_requires_recipient_configuration','local_revision':m.get('local_revision',{}).get('id'),'live_center_verified':False,'next':'Register the actual project identity and existing Sheet; then workflow_node.py context --item. Do not copy historical bindings.'},ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,KeyError) as e:print(json.dumps({'ok':False,'error':str(e)}));sys.exit(1)
