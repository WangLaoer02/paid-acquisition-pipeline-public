#!/usr/bin/env python3
"""Verify actual installed Skill files against the Feishu-pinned installer manifest."""
import hashlib
import json
from pathlib import Path

CRITICAL=('paid-skit-production-pipeline','rongyao-material-upload','paid-skit-premiere','paid-skit-video-prompts','rongyao-operations','rongyao-video-upload','rongyao-keyring','rongyao-data-stack','rongyao-ai-generator','rongyao-http-readonly','rongyao-http-upload')
COMPANIONS={'paid-skit-production-pipeline':('seedance-paid-skit-production-pipeline',),'rongyao-http-upload':('rongyao-http-readonly',),'rongyao-ai-generator':('rongyao-keyring','rongyao-data-stack','rongyao-operations'),
            'rongyao-operations':('rongyao-keyring','rongyao-data-stack'),
            'rongyao-keyring':('rongyao-data-stack','rongyao-operations')}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def profile_roots(workspace,marker=None):
    """Select an explicit sealed deployment; an invalid pin never falls back."""
    workspace=Path(workspace).resolve();path=workspace/'workflow/execution-profile.json'
    if not path.exists() and not path.is_symlink():return None
    if path.is_symlink():raise ValueError('EXECUTION_PROFILE_INVALID: profile is a symlink')
    profile=json.loads(path.read_text())
    required={'schema_version','release_id','rules_manifest_sha256','installer_manifest_sha256','skills_root'}
    if set(profile)!=required or profile['schema_version']!=1:
        raise ValueError('EXECUTION_PROFILE_INVALID: schema')
    manifest_path=workspace/'workflow/rules/manifest.json'
    manifest=json.loads(manifest_path.read_text())
    if profile['release_id']!=manifest['release_id'] or profile['rules_manifest_sha256']!=sha(manifest_path):
        raise ValueError('EXECUTION_PROFILE_MISMATCH: workspace release')
    if marker and any(profile[key]!=marker[field] for key,field in [('release_id','release_id'),('rules_manifest_sha256','manifest_sha256'),('installer_manifest_sha256','installer_manifest_sha256')]):
        raise ValueError('EXECUTION_PROFILE_MISMATCH: current published release')
    root=Path(profile['skills_root'])
    if not root.is_absolute() or root!=root.resolve() or not root.is_dir():
        raise ValueError('EXECUTION_PROFILE_INVALID: fixed skills directory missing or linked')
    setup=root/'paid-skit-progressive-setup/manifest.json'
    if not setup.is_file() or setup.is_symlink() or sha(setup)!=profile['installer_manifest_sha256']:
        raise ValueError('EXECUTION_PROFILE_MISMATCH: fixed installer')
    return [root]

def legacy_verify_workspace(marker,workspace):
    roots=profile_roots(workspace,marker)
    result=verify(marker,roots=roots,required=CRITICAL if roots else ('paid-skit-production-pipeline',))
    if roots:
        result['execution_profile']={'skills_root':str(roots[0]),'release_id':marker['release_id'],'shared_tool_directories_used':False}
    return result

def verify_files(root,files):
    root=Path(root).resolve()
    for name,expected in files.items():
        p=(root/name).resolve()
        if not p.is_relative_to(root) or not p.is_file() or sha(p)!=expected:
            raise ValueError('SKILL_DEPLOYMENT_MISMATCH: '+str(root/name))
    return len(files)

def verify(marker,roots=None,required=('paid-skit-production-pipeline',)) :
    roots=[Path(r) for r in (roots or [Path.home()/'.agents/skills',Path.home()/'.codex/skills'])]
    setups=list(dict.fromkeys((r/'paid-skit-progressive-setup').resolve() for r in roots if (r/'paid-skit-progressive-setup/manifest.json').is_file()))
    if not setups or not marker.get('installer_manifest_sha256'):raise ValueError('SKILL_DEPLOYMENT_MISSING: install current verified package')
    total=0;installed=[];verified=set()
    def checked(root,name):
        root=Path(root).resolve();key=(root,name)
        if key in verified:return 0
        count=verify_files(root,meta['packages'][name]['files']);verified.add(key)
        return count
    for setup in setups:
        if sha(setup/'manifest.json')!=marker['installer_manifest_sha256']:raise ValueError('SKILL_DEPLOYMENT_MISMATCH: installer manifest')
        meta=json.loads((setup/'manifest.json').read_text())
        if not meta['version'].endswith('-'+marker['release_id']):raise ValueError('SKILL_DEPLOYMENT_MISMATCH: release')
        total+=verify_files(setup,{x['path']:x['sha256'] for x in meta['files']})
    for name in CRITICAL:
        copies=list(dict.fromkeys((r/name).resolve() for r in roots if (r/name).is_dir()))
        if not copies and name in required:raise ValueError('SKILL_DEPLOYMENT_MISSING: '+name)
        for copy in copies:
            if name=='paid-skit-production-pipeline':
                canonical=(copy.parent/'seedance-paid-skit-production-pipeline').resolve()
                for part in ('references','scripts'):
                    link=copy/part
                    if not link.is_symlink() or link.resolve() != canonical/part:
                        raise ValueError('SKILL_DEPLOYMENT_MISMATCH: alias link '+str(link))
            for dependency in COMPANIONS.get(name,()):
                target=copy.parent/dependency
                if not target.is_dir():raise ValueError('SKILL_DEPLOYMENT_MISSING: '+str(target))
                total+=checked(target,dependency)
            total+=checked(copy,name);installed.append(str(copy))
    return {'ok':True,'release_id':marker['release_id'],'installed_copies':installed,'files_verified':total,'business_validation_inferred':False}


def dependency_roots(workspace):
    workspace=Path(workspace).resolve()
    if json.loads((workspace/'workflow/rules/manifest.json').read_text()).get('distribution')=='public_source':
        return [workspace/'skills']
    raise ValueError('UNSUPPORTED_DISTRIBUTION: this release supports public_source only')

def verify_workspace(marker,workspace):
    workspace=Path(workspace).resolve()
    manifest=json.loads((workspace/'workflow/rules/manifest.json').read_text())
    if manifest.get('distribution')!='public_source':raise ValueError('UNSUPPORTED_DISTRIBUTION: this release supports public_source only')
    import receiver_config
    config=receiver_config.load(True)
    receiver_config.validate(config,production=True)
    if marker.get('receiver_config_sha256')!=receiver_config.security_digest(config):raise ValueError('RECEIVER_SECURITY_CONFIG_NOT_PUBLISHED')
    path=workspace/'SKILLS-MANIFEST.json'
    if marker.get('skills_manifest_sha256')!=sha(path):raise ValueError('PUBLIC_SKILLS_PIN_MISMATCH')
    listing=json.loads(path.read_text()); count=0
    for name,files in listing.items():count+=verify_files(workspace/'skills'/name,files)
    return {'ok':True,'files_verified':count,'skills_root':str(workspace/'skills'),'author_accounts_used':False,'business_validation_inferred':False}
