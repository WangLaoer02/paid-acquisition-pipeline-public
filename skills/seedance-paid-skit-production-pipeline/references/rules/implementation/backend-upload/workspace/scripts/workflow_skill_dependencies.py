"""Read a compatible, self-contained installed Skill only when its branch is selected."""
from pathlib import Path
import hashlib,json,os,re

def version(value):
    if not isinstance(value,str) or not re.fullmatch(r"\d+(?:\.\d+){1,2}",value):
        raise ValueError('SKILL_VERSION_INVALID: '+str(value))
    return tuple((list(map(int,value.split('.')))+[0,0])[:3])

def resolve(name,contract,roots=None):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",name):raise ValueError('SKILL_ID_INVALID')
    if roots is None:
        import workflow_deployment
        workspace=Path(__file__).resolve().parents[1]
        roots=getattr(workflow_deployment,'dependency_roots',workflow_deployment.profile_roots)(workspace)
        local=json.loads((workspace/'workflow/rules/manifest.json').read_text()).get('local_revision',{})
        pin=contract.get('local_candidate_manifest_sha256')
        if pin and local.get('publication_status')=='local_maintenance_not_cloud_published':
            # Explicit per-Skill maintenance pin; never a production/global fallback.
            codex=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))).expanduser()/'skills'
            roots=roots if roots is not None else [codex,Path.home()/'.agents/skills']
            found=list(dict.fromkeys((root/name/'manifest.json').resolve() for root in roots if (root/name/'manifest.json').is_file()))
            if not found or any(hashlib.sha256(p.read_bytes()).hexdigest()!=pin for p in found):
                raise ValueError('LOCAL_SKILL_PIN_MISMATCH: '+name)
        if roots is None:
            codex=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))).expanduser()/'skills'
            roots=[codex,Path.home()/'.agents/skills']
    copies=list(dict.fromkeys((Path(r)/name).resolve() for r in roots if (Path(r)/name/'manifest.json').is_file()))
    if not copies:raise ValueError('SKILL_DEPENDENCY_MISSING: '+name+'; install the independent Skill; other nodes remain available')
    results=[]
    for root in copies:
        raw=(root/'manifest.json').read_bytes();m=json.loads(raw)
        if m.get('name')!=name or m.get('interface_version')!=contract['interface_version']:raise ValueError('SKILL_INTERFACE_MISMATCH: '+name)
        if not version(contract['min_version'])<=version(m.get('version'))<version(contract['max_version_exclusive']):raise ValueError('SKILL_VERSION_INCOMPATIBLE: '+name)
        files=m.get('files',{});reads=[]
        if not files or any(key not in files for key in (m.get('entrypoint'),m.get('rules'))):raise ValueError('SKILL_MANIFEST_INCOMPLETE: '+name)
        for rel,expected in files.items():
            if Path(rel).is_absolute() or '..' in Path(rel).parts:raise ValueError('SKILL_PATH_INVALID')
            p=(root/rel).resolve()
            if not p.is_relative_to(root) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('SKILL_CONTENT_CHANGED: '+name+'/'+rel)
        entry=(root/m['entrypoint']).read_text()
        if not re.search(r'^  version: [\"\']?'+re.escape(m['version'])+r'[\"\']?$',entry,re.M):raise ValueError('SKILL_METADATA_VERSION_MISMATCH: '+name)
        seen_reads=set()
        for kind,rel in [('entrypoint',m['entrypoint']),('rules',m['rules'])]:
            if rel in seen_reads:continue
            seen_reads.add(rel)
            reads.append({'id':name+':'+kind,'path':str(root/rel),'text':(root/rel).read_text(),'reason':'selected independent Skill','source':{'skill_id':name,'version':m['version'],'sha256':files[rel]}})
        results.append({'skill_id':name,'version':m['version'],'interface_version':m['interface_version'],'manifest_sha256':hashlib.sha256(raw).hexdigest(),'rules_sha256':files[m['rules']],'reads':reads})
    if len({r['manifest_sha256'] for r in results})!=1:raise ValueError('SKILL_DUPLICATE_CONFLICT: '+name+'; reconcile installed copies')
    return results[0]

def section(text,heading):
    matches=list(re.finditer(r'^## (.+)$',text,re.M))
    for i,m in enumerate(matches):
        if m.group(1)==heading:return text[m.start():matches[i+1].start() if i+1<len(matches) else len(text)]
    raise ValueError('SKILL_SECTION_MISSING: '+heading)
