#!/usr/bin/env python3
"""Initialize and inspect a recipient-owned workspace; never generates or logs in."""
import argparse,hashlib,json,os,re,shutil,socket,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import receiver_config

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def emit(v):print(json.dumps(v,ensure_ascii=False,indent=2))
def verify(root=ROOT):
 manifest=json.loads((root/'PUBLIC-MANIFEST.json').read_text())
 missing=[]
 for name,h in manifest['files'].items():
  p=root/name
  if Path(name).is_absolute() or '..' in Path(name).parts or p.is_symlink() or not p.is_file() or digest(p)!=h:missing.append(name)
 if missing:raise ValueError('RELEASE_CONTENT_CHANGED: '+', '.join(missing[:12]))
 return {'ok':True,'files_verified':len(manifest['files']),'release_id':manifest['release_id'],'production_authorized':False}
def init(args):
 verify();target=args.workspace.expanduser().resolve()
 if target.exists():raise ValueError('WORKSPACE_MUST_NOT_EXIST: existing edits are preserved')
 cfg=json.loads(args.config.read_text()) if args.config else json.loads((ROOT/'receiver.example.json').read_text())
 receiver_config.validate(cfg)
 # Only explicitly enumerated release files are copied: never .git, private tests, login or evidence.
 manifest=json.loads((ROOT/'PUBLIC-MANIFEST.json').read_text())
 target.mkdir(parents=True)
 for name in [*manifest['files'],'PUBLIC-MANIFEST.json']:
  p=target/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
 (target/'receiver.local.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
 (target/'workflow/state_bindings.json').write_text('{"bindings":[]}\n')
 (target/'workflow/state_checkpoint.json').write_text('{"sources":{},"items":{}}\n')
 for name in ('projects','evidence','library'): (target/name).mkdir(exist_ok=True)
 emit({'ok':True,'workspace':str(target),'bindings':0,'writer_configured':bool(cfg.get('writer_host')),'production_authorized':False,'next':'Read nodes with --offline-preparation; configure your own services before production.'})
def config_check(args):
 d=json.loads(args.config.read_text()) if args.config else receiver_config.load(True)
 emit(receiver_config.validate(d,args.production))
def marker(args):
 # This writes only a local marker candidate. Recipient reviews and publishes in their own Feishu document.
 verify();receiver_config.validate(receiver_config.load(True),production=True)
 m=json.loads((ROOT/'workflow/rules/manifest.json').read_text())
 emit({'release_id':m['release_id'],'manifest_sha256':digest(ROOT/'workflow/rules/manifest.json'),'skills_manifest_sha256':digest(ROOT/'SKILLS-MANIFEST.json'),'receiver_config_sha256':receiver_config.security_digest(receiver_config.load(True)),'publication_performed':False,'prefix':'WF_RELEASE_JSON='})
def prepare(args):
 verify();cfg=receiver_config.load(True)
 receiver_config.validate(cfg)
 exe=cfg.get('dreamina_cli') or 'dreamina-canvas'
 if not shutil.which(exe):raise ValueError('DREAMINA_CLI_MISSING: install from the official source in docs/dependencies.md')
 if not args.live:
  emit({'ok':True,'cli_available':True,'account_verified':False,'model_verified':False,'quote_verified':False,'paid_generation_authorized':False,'next':'With your own login, rerun dreamina-prepare --live; this calls version/schema/auth status/model list only.'});return
 # Explicit live flag, no creation, save, quote acceptance, submission or account switch.
 results=[]
 for label,argv in [('version',[exe,'--version']),('schema',[exe,'schema']),('auth_status',[exe,'auth','status']),('video_models',[exe,'model','list','--type','video'])]:
  r=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=45)
  results.append({'check':label,'exit_code':r.returncode,'response_sha256':hashlib.sha256(r.stdout.encode()).hexdigest()})
  if r.returncode:raise ValueError('DREAMINA_READONLY_CHECK_FAILED: '+label+'; inspect the official CLI locally; response is not logged')
 emit({'ok':True,'checks':results,'identity_and_model_content_review_required':True,'quote_verified':False,'paid_generation_authorized':False})
def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 sub.add_parser('verify')
 q=sub.add_parser('init');q.add_argument('--workspace',type=Path,required=True);q.add_argument('--config',type=Path)
 q=sub.add_parser('config-check');q.add_argument('--config',type=Path);q.add_argument('--production',action='store_true')
 sub.add_parser('release-marker')
 q=sub.add_parser('dreamina-prepare');q.add_argument('--live',action='store_true')
 a=p.parse_args()
 if a.command=='verify':emit(verify())
 elif a.command=='init':init(a)
 elif a.command=='config-check':config_check(a)
 elif a.command=='release-marker':marker(a)
 else:prepare(a)
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,KeyError,subprocess.SubprocessError) as e:
  emit({'ok':False,'error':str(e),'production_authorized':False});sys.exit(1)
