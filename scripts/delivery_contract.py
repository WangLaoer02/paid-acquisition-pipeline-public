#!/usr/bin/env python3
"""Read-only delivery completeness checks and immutable revision storage (no adoption)."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

BASE_REQUIREMENTS = {'source', 'transition', 'panels', 'header', 'disclaimer', 'watermark', 'naming', 'version'}

def nonempty_text(value):
    return isinstance(value,str) and bool(value.strip())

def digest(path):
    with Path(path).open('rb') as f:
        h=hashlib.file_digest(f,'sha256')
    return h.hexdigest()

def inside(root,name):
    p=(Path(root)/name).resolve()
    if not p.is_relative_to(Path(root).resolve()):raise ValueError('Path escapes delivery root')
    return p

def file_proof(root,entry):
    p=inside(root,entry['path'])
    if not p.is_file() or not p.stat().st_size or digest(p)!=entry.get('sha256'):
        raise ValueError('Missing or stale delivery evidence: '+entry['path'])
    return p

def inspect(root,requirements,review):
    """Validate coverage and hashes only; human observations must still be read."""
    if requirements.get('schema_version')!=1 or review.get('schema_version')!=1:raise ValueError('Unsupported delivery schema')
    reqs=requirements.get('requirements',[]);ids=[r['id'] for r in reqs]
    if len(ids)!=len(set(ids)) or not BASE_REQUIREMENTS.issubset(ids):raise ValueError('Required delivery checklist omitted or duplicated')
    if not nonempty_text(requirements.get('source_ref')):raise ValueError('Requirements need latest user/rule source')
    if review.get('requirements_sha256')!=hashlib.sha256(json.dumps(requirements,ensure_ascii=False,sort_keys=True).encode()).hexdigest():raise ValueError('Review refers to stale requirements')
    outputs=review.get('outputs',[])
    if not outputs:raise ValueError('No delivery output')
    seen=set();missing=[];verified=[]
    for output in outputs:
        p=file_proof(root,output);key=str(p)
        if key in seen:raise ValueError('Duplicate output')
        seen.add(key)
        checks=output.get('checks',[]);cids=[c['id'] for c in checks]
        if len(cids)!=len(set(cids)) or set(cids)-set(ids):raise ValueError('Unknown or duplicate delivery check')
        by_id={c['id']:c for c in checks}
        for req in reqs:
            rid=req['id'];check=by_id.get(rid,{})
            if any(not nonempty_text(req.get(key)) for key in ('source_ref','scope','criterion')):raise ValueError('Requirement lacks source/scope/criterion')
            if check.get('status')=='not_applicable':
                if req.get('allow_not_applicable') is not True or not nonempty_text(check.get('reason')) or not nonempty_text(check.get('source_ref')):missing.append(p.name+':'+rid)
                continue
            if check.get('status')!='recorded' or not nonempty_text(check.get('source_ref')) or not check.get('evidence'):
                missing.append(p.name+':'+rid);continue
            if check.get('output_sha256')!=output['sha256']:raise ValueError('Check does not bind reviewed output')
            for proof in check['evidence']:file_proof(root,proof)
            # Project-specific numeric/string constraints are explicit, not global defaults.
            for k,v in req.get('expected',{}).items():
                if check.get('observed',{}).get(k)!=v:missing.append(p.name+':'+rid+':'+k)
        verified.append(output['sha256'])
    return {'ok':True,'coverage_complete':not missing,'missing_or_unverified':missing,'outputs_sha256':verified,'semantic_pass_inferred':False,'listening_inferred':False,'user_adoption_inferred':False,'side_effects':[]}

def verify_mapping(mapping,fields,filename):
    """Explicit user choices require current backend enum values, never suffix guesses."""
    for key in ('requester','designer'):
        choice=mapping.get(key,{})
        options=fields.get(key,[])
        if not choice.get('source_ref') or choice.get('value') not in options:raise ValueError('Missing actual field mapping: '+key)
    if not fields.get('source_ref') or mapping.get('filename_sha256')!=hashlib.sha256(filename.encode()).hexdigest():raise ValueError('Missing or stale mapping dictionary/name binding')
    return {'ok':True,'mapping_verified':True,'source_ref':fields['source_ref'],'upload_authorized':False}

@contextmanager
def store_lock(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with (root/'.revision.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)

def immutable_write(path,content):
    """Atomic create; interrupted temp files never become an accepted revision."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.revision-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            if isinstance(content,Path):
                with content.open('rb') as src:shutil.copyfileobj(src,out)
            else:out.write(content)
            out.flush();os.fsync(out.fileno())
        os.link(tmp,path)  # Never replaces an existing revision.
    finally:os.unlink(tmp)

def store_revision(source,store,revision,expected_sha256):
    source=Path(source);store=Path(store)
    if not re.fullmatch(r'V\d{3,}',revision):raise ValueError('Use explicit Vnnn revision')
    if digest(source)!=expected_sha256:raise ValueError('Source changed before revision')
    target=store/revision/source.name
    with store_lock(store):
        if target.exists():
            if digest(target)!=expected_sha256:raise ValueError('Revision already exists with different bytes; increment version')
        else:immutable_write(target,source)
        if digest(target)!=expected_sha256:raise ValueError('Source changed during revision; preserve for investigation')
        receipt=target.with_name(target.name+'.revision.json')
        body={'revision':revision,'name':source.name,'sha256':expected_sha256}
        if receipt.exists():
            if json.loads(receipt.read_text())!=body:raise ValueError('Revision receipt differs')
        else:immutable_write(receipt,json.dumps(body,ensure_ascii=False,sort_keys=True).encode())
    return {'ok':True,'path':str(target),'sha256':expected_sha256,'existing_bytes_preserved':True,'alias_changed':False}

def promote_alias(revision,alias,archive,expected_old_sha256):
    """Keep a business filename only after immutable backup + compare-and-swap."""
    revision=Path(revision);alias=Path(alias);archive=Path(archive)
    receipt=revision.with_name(revision.name+'.revision.json')
    if not receipt.is_file() or json.loads(receipt.read_text()).get('sha256')!=digest(revision):raise ValueError('Revision not sealed')
    with store_lock(archive):
        current=digest(alias) if alias.exists() else None
        if current!=expected_old_sha256:raise ValueError('Alias changed; preserve user edit')
        if current:
            backup=archive/'previous'/current/alias.name
            if backup.exists():
                if digest(backup)!=current:raise ValueError('Old backup corrupt')
            else:immutable_write(backup,alias)
            if digest(alias)!=current or digest(backup)!=current:raise ValueError('Alias changed during backup')
        fd,tmp=tempfile.mkstemp(prefix='.alias-',dir=alias.parent);os.close(fd)
        try:
            shutil.copyfile(revision,tmp)
            if digest(tmp)!=digest(revision):raise ValueError('Revision changed during promotion')
            if (digest(alias) if alias.exists() else None)!=expected_old_sha256:raise ValueError('Alias changed; preserve user edit')
            os.replace(tmp,alias)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    return {'ok':True,'sha256':digest(alias),'previous_sha256':current,'revision':str(revision)}

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('check');q.add_argument('--root',required=True);q.add_argument('--requirements',required=True);q.add_argument('--review',required=True)
    q=sub.add_parser('store');q.add_argument('--source',required=True);q.add_argument('--store',required=True);q.add_argument('--revision',required=True);q.add_argument('--sha256',required=True)
    a=p.parse_args()
    if a.command=='check':
        r=inspect(a.root,json.loads(Path(a.requirements).read_text()),json.loads(Path(a.review).read_text()))
        print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['coverage_complete'] else 2
    print(json.dumps(store_revision(a.source,a.store,a.revision,a.sha256),ensure_ascii=False));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError) as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));raise SystemExit(1)
