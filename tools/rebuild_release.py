from pathlib import Path
import hashlib,json,zipfile,shutil
R=Path(__file__).resolve().parents[1]
# Explicit maintenance action only: review diffs/tests before publishing the resulting new marker.
import argparse,re
parser=argparse.ArgumentParser(description='Rebuild a reviewed recipient release; does not publish or authorize execution.')
parser.add_argument('--release-id',required=True);args=parser.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_.-]+',args.release_id):raise SystemExit('INVALID_RELEASE_ID')
RELEASE=args.release_id
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
def save(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def files(p):return {str(x.relative_to(p)):sha(x) for x in sorted(p.rglob('*')) if x.is_file() and '__pycache__' not in x.parts}
# Assign the recipient's explicit version to active JSON contracts.
for cfg in R.rglob('*.json'):
 if cfg.name in ('PUBLIC-MANIFEST.json','SKILLS-MANIFEST.json','receiver.local.json') or any(x in cfg.relative_to(R).parts for x in ('projects','evidence','library','.git')):continue
 try:value=load(cfg)
 except ValueError:continue
 def version(v):
  if isinstance(v,dict):
   for k in v:
    if k=='release_id':v[k]=RELEASE
    else:version(v[k])
  elif isinstance(v,list):
   for x in v:version(x)
 original=json.dumps(value,sort_keys=True)
 version(value)
 if json.dumps(value,sort_keys=True)!=original:save(cfg,value)
# Synchronize the actual packaged execution mirrors from the reviewed owner scripts.
backend=R/'workflow/rules/implementation/backend-upload/workspace'
for source in (R/'scripts').glob('*.py'):
 target=backend/'scripts'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
for source in (R/'workflow').glob('*.json'):
 if source.name not in ('state_bindings.json','state_checkpoint.json','execution-profile.json'):
  target=backend/'workflow'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
console=R/'workflow/rules/implementation/console'
for target in console.glob('*'):
 owner=R/('scripts' if target.suffix=='.py' else 'workflow')/target.name
 if target.is_file() and owner.is_file():shutil.copy2(owner,target)
# Repair independent Skill manifests only after reviewed transformations.
for p in (R/'skills').glob('*/manifest.json'):
 d=load(p)
 if 'files' in d:d['files']={n:sha(p.parent/n) for n in d['files'] if (p.parent/n).is_file()};save(p,d)
p=R/'workflow/rules/skill-dependencies.json';d=load(p)
for v in d['skills'].values():v.pop('local_candidate_manifest_sha256',None)
save(p,d)
# Preserve route logic while rebuilding exact source-hash maps after portable edits.
for p in (R/'workflow/rules/implementation').rglob('contract.json'):
 d=load(p)
 if 'workspace_dependencies' in d:d['workspace_dependencies']={n:sha(R/n) for n in d['workspace_dependencies'] if (R/n).is_file()};save(p,d)
p=R/'workflow/rules/policy-index.json';d=load(p)
for v in d['policies'].values():
 if not v.get('external_skill') and (R/'workflow/rules'/v['path']).is_file():v['sha256']=sha(R/'workflow/rules'/v['path'])
save(p,d)
p=R/'workflow/rules/manifest.json';d=load(p);d['distribution']='public_source';d['authority']='recipient-configured Feishu rules center';d.pop('local_revision',None)
for v in d['modules'].values():v['sha256']=sha(p.parent/v['path']);v['bytes']=(p.parent/v['path']).stat().st_size
for field,base in [('implementation_files',p.parent),('reference_files',p.parent),('workspace_contract_files',R)]:
 d[field]={n:sha(base/n) for n in d.get(field,{}) if (base/n).is_file()}
# Include every active script/tool/contract in integrity, configuration is explicitly outside code hashes.
for folder in ('scripts','workflow/tools'):
 for f in (R/folder).rglob('*'):
  if f.is_file() and '__pycache__' not in f.parts:d['workspace_contract_files'][str(f.relative_to(R))]=sha(f)
save(p,d)
# Main installed skill carries the full portable rules/workspace contract, not a private installed snapshot.
sk=R/'skills/seedance-paid-skit-production-pipeline/references'
for folder in ('rules','workspace-contract'):
 if (sk/folder).exists():shutil.rmtree(sk/folder)
shutil.copytree(R/'workflow/rules',sk/'rules')
for folder in ('scripts','workflow/tools','tests'):
 shutil.copytree(R/folder,sk/'workspace-contract'/folder,ignore=shutil.ignore_patterns('__pycache__'))
for f in (R/'workflow').glob('*.json'):
 if f.name not in ('state_bindings.json','state_checkpoint.json'):p=sk/'workspace-contract/workflow'/f.name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,p)
shutil.copy2(R/'AGENTS.md',sk/'workspace-contract/AGENTS.md')
for name in load(R/'workflow/rules/manifest.json')['workspace_contract_files']:
 target=sk/'workspace-contract'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(R/name,target)
if (sk/'tools').exists():shutil.rmtree(sk/'tools')
shutil.copytree(R/'workflow/tools',sk/'tools',ignore=shutil.ignore_patterns('__pycache__'))
# Supply relocated references without editing hash-pinned rule bytes.
import re
for unused in range(3):
 added=False
 for markdown in list(sk.rglob('*.md')):
  for url in re.findall(r'\[[^\]]*\]\(([^)]+)\)',markdown.read_text()):
   if '://' in url or url.startswith('#'):continue
   target=(markdown.parent/url.split('#')[0]).resolve()
   if target.exists():continue
   for name in ('rongyao-http-upload','rongyao-operations'):
    if name+'/' not in url:continue
    tail=url.split(name+'/')[-1].split('#')[0]
    owner=R/'skills'/name
    if (owner/tail).is_file() and target.is_relative_to(sk.parent):
     dest=target
     for part in Path(tail).parts:dest=dest.parent
     if not dest.exists():shutil.copytree(owner,dest);added=True
 if not added:break
# Rule adapters that ship references retain their own local rules, source remains canonical in workspace.
listing={p.name:files(p) for p in sorted((R/'skills').iterdir()) if p.is_dir()};save(R/'SKILLS-MANIFEST.json',listing)
inst=R/'installer';m=load(inst/'manifest.json');m['version']=RELEASE;m['canonical']=None;m.pop('local_revision',None);m['external_rule_dependencies']=[]
external={'lark-doc','lark-sheets','lark-drive','lark-shared','dreamina-canvas-cli'}
for name in list(m['packages']):
 if name in external:
  m['packages'][name]={'external':True,'source':'https://github.com/larksuite/cli' if name.startswith('lark-') else 'https://dreamina.capcut.com/ai-tool/install?from_page=explore','redistribution':'not_included_no_local_redistribution_evidence','files':{}}
  continue
 p=R/'skills'/name;dest=inst/'assets/payloads'/(name+'.zip');dest.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
  for n in files(p):
   info=zipfile.ZipInfo(n,(2026,11,4,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,(p/n).read_bytes())
 m['packages'][name]={'kind':'public_reviewed_source','archive':str(dest.relative_to(inst)),'sha256':sha(dest),'files':files(p),'file_count':len(files(p)),'bytes':dest.stat().st_size}
for v in m['phases'].values():v['manual_gates']=[x for x in v.get('manual_gates',[]) if 'Notion' not in x]
m['conditional_dependencies']=[{'trigger':'Selected service or method','state':'external_requirements','action':'See docs/dependencies.md; install official software using your own account. No accounts or author datasets are included.'}]
m['files']=[{'path':n,'sha256':h} for n,h in files(inst).items() if n!='manifest.json'];save(inst/'manifest.json',m)
save(R/'PUBLIC-MANIFEST.json',{'schema_version':1,'release_id':RELEASE,'production_release':False,'files':{n:h for n,h in files(R).items() if n not in ('PUBLIC-MANIFEST.json','receiver.local.json') and not n.startswith(('projects/','evidence/','library/','.git/','workflow/runtime/','workflow/authorizations/')) and n not in ('workflow/state_bindings.json','workflow/state_checkpoint.json','workflow/execution-profile.json')}})
print('REBUILT',len(load(R/'PUBLIC-MANIFEST.json')['files']),'files',len(listing),'skills')
