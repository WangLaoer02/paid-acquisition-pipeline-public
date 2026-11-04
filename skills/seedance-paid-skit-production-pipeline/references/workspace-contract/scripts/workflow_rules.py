#!/usr/bin/env python3
"""Read the current Feishu release; never resolve retired external rule sources."""
import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RULES=ROOT/'workflow/rules'
CENTER=None
MARKER='WF_RELEASE_JSON='

def _manifest():
    manifest_path=RULES/'manifest.json'
    raw=manifest_path.read_bytes()
    manifest=json.loads(raw)
    if manifest.get('mode')!='standalone_feishu' or manifest.get('external_rule_dependencies'):
        raise ValueError('Invalid independent rule release.')
    return manifest,hashlib.sha256(raw).hexdigest()

def _package_only(group,name):
    # These files are not consumed by a rule context. Actual media inputs still
    # require their own current-input/selection/evidence SHA checks at point of use.
    if group=='reference_files' and name.startswith('archive/'):return 'historical_archive'
    if group=='workspace_contract_files':
        if name.startswith('tests/'):return 'package_tests'
        if name.startswith('workflow/assets/naruto/') and Path(name).suffix.lower()=='.jpg':return 'gallery_images'
    return None

def check_local(scope='full',report=None):
    if scope not in ('full','offline_preparation'):raise ValueError('Invalid integrity scope.')
    manifest,manifest_digest=_manifest()
    stats={'scope':scope,'checked_entries':0,'files_hashed':0,'bytes_hashed':0,
           'deferred_entries':0,'deferred_categories':{},'production_authorized':False}
    failures=[]

    def checked(base,name,expected,group,allow_defer=True):
        # Report only validated relative names, never an external path or OS error.
        if not isinstance(name,str) or not name or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('INTEGRITY_PATH_INVALID: '+group+' contains an unsafe relative path.')
        path=(base/name).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError('INTEGRITY_PATH_INVALID: '+group+' path resolves outside its root.')
        category=_package_only(group,name) if allow_defer else None
        if scope=='offline_preparation' and category:
            stats['deferred_entries']+=1
            stats['deferred_categories'][category]=stats['deferred_categories'].get(category,0)+1
            return
        stats['checked_entries']+=1
        label=(Path('workflow/rules')/name).as_posix() if base==RULES else name
        try:
            raw=path.read_bytes()
        except OSError:
            failures.append(group+': '+label+' (missing or unreadable)')
            return
        stats['files_hashed']+=1;stats['bytes_hashed']+=len(raw)
        if hashlib.sha256(raw).hexdigest()!=expected:
            failures.append(group+': '+label+' (SHA-256 mismatch)')

    for item in manifest['modules'].values():
        checked(RULES,item['path'],item['sha256'],'modules')
    for name,digest in manifest['implementation_files'].items():
        checked(RULES,name,digest,'implementation_files')
    for name,digest in manifest.get('reference_files',{}).items():
        checked(RULES,name,digest,'reference_files')
    for name,digest in manifest.get('workspace_contract_files',{}).items():
        checked(ROOT,name,digest,'workspace_contract_files')
    if failures:
        raise ValueError('LOCAL_INTEGRITY_MISMATCH ['+scope+']: '+ '; '.join(failures)+
            '. Content differs from the published release or reviewed local candidate. '
            'Compare these files with their owning source and preserve manual edits; review affected checks '
            'before updating the local candidate manifest. Do not overwrite edits or rehash blindly. '
            'For production use the current verified fixed workspace; offline preparation is not publication.')
    for name in manifest.get('dependency_contracts',[]):
        path=(RULES/name).resolve()
        if Path(name).is_absolute() or '..' in Path(name).parts or not path.is_relative_to(RULES.resolve()):
            raise ValueError('Dependency contract path escapes rule root.')
        contract=json.loads(path.read_text())
        if contract.get('release_id')!=manifest['release_id']:
            raise ValueError('Dependency contract release differs: '+name)
        for target,expected in contract.get('workspace_dependencies',{}).items():
            checked(ROOT,target,expected,'Dependency contract',allow_defer=False)
    if failures:raise ValueError('LOCAL_INTEGRITY_MISMATCH: '+'; '.join(failures)+'. Review the nested dependency contract and its owning source.')
    if hashlib.sha256((RULES/'manifest.json').read_bytes()).hexdigest()!=manifest_digest:
        raise ValueError('MANIFEST_CHANGED_DURING_READ: retry with one stable reviewed candidate.')
    if report is not None:report.update(stats)
    return manifest,manifest_digest

def verify_marker(xml,manifest,digest):
    import xml.etree.ElementTree as ET
    root=ET.fromstring('<root>'+xml+'</root>')
    matches=[]
    for node in root.iter('p'):
        value=''.join(node.itertext())
        if value.startswith(MARKER):matches.append(json.loads(value[len(MARKER):]))
    if len(matches)!=1:raise ValueError('Center release marker must be unique.')
    current=matches[0]
    if current.get('release_id')!=manifest['release_id'] or current.get('manifest_sha256')!=digest:
        raise ValueError('Center and local release differ; read the current Feishu package and synchronize before execution.')
    return current

def check(offline=False,full_integrity=False):
    manifest,initial_digest=_manifest()
    revision=manifest.get('local_revision',{})
    # Refuse production candidates before scanning unrelated package content.
    if revision.get('publication_status')=='local_maintenance_not_cloud_published' and not offline:
        raise ValueError('LOCAL_CANDIDATE_NOT_PUBLISHED: this workspace supports offline preparation only; use --offline-preparation for local reads or the verified fixed production workspace for live execution. No publication or authorization is inferred.')
    integrity={}
    manifest,digest=check_local('offline_preparation' if offline and not full_integrity else 'full',integrity)
    if digest!=initial_digest:raise ValueError('MANIFEST_CHANGED_DURING_READ: retry with one stable reviewed candidate.')
    result={'ok':True,'release_id':manifest['release_id'],'manifest_sha256':digest,'module_count':len(manifest['modules']),'mode':'standalone_feishu','paid_generation_authorized':False,'upload_authorized':False,'production_authorized':False,'live_center_verified':False,'integrity':integrity}
    if revision.get('publication_status')=='local_maintenance_not_cloud_published':
        result.update(local_revision=revision['id'],publication_status=revision['publication_status'],production_authorized=False)
    if offline:
        result['allowed_scope']='explicit nonpaid preparation only'
        return result
    import receiver_config
    config=receiver_config.load(True);receiver_config.validate(config,production=True)
    center=config['rules_center']
    response=subprocess.run(['lark-cli','docs','+fetch','--api-version','v2','--doc',center,'--as','user','--scope','keyword','--keyword',MARKER,'--detail','full'],cwd=ROOT,text=True,capture_output=True,timeout=55)
    if response.returncode:raise ValueError('Current Feishu release unavailable; no paid execution from a cached release.')
    data=json.loads(response.stdout)
    if not data.get('ok'):raise ValueError('Current Feishu release could not be read.')
    current=verify_marker(data['data']['document']['content'],manifest,digest)
    import workflow_deployment
    result['skill_deployment']=workflow_deployment.verify_workspace(current,ROOT)
    result.update(live_center_verified=True,center_revision=data['data']['document']['revision_id'],bundle_file_token=current.get('bundle_file_token'))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['check','read'])
    p.add_argument('--module')
    p.add_argument('--offline-preparation',action='store_true')
    p.add_argument('--full-integrity',action='store_true',help='Include tests, gallery images and archives in offline package acceptance; live checks always include them.')
    args=p.parse_args()
    result=check(args.offline_preparation,args.full_integrity)
    if args.command=='read':
        manifest,digest=_manifest()
        if digest!=result['manifest_sha256']:raise ValueError('MANIFEST_CHANGED_DURING_READ')
        if args.module not in manifest['modules']:raise ValueError('Choose an actual module from manifest.json.')
        raw=(RULES/manifest['modules'][args.module]['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=manifest['modules'][args.module]['sha256']:raise ValueError('Rule module changed during read: '+args.module)
        print(json.dumps(result,ensure_ascii=False))
        print(raw.decode('utf-8'))
    else:print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        sys.exit(1)
