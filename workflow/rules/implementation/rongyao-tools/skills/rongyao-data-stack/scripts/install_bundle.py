#!/usr/bin/env python3
"""Verify and install the allowlisted Skills with local backup and reversible replacement."""
import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from package_bundle import SKILLS


def read_bundle(archive):
    with tarfile.open(archive, 'r:gz') as bundle:
        members=bundle.getmembers()
        names=[member.name for member in members]
        if len(set(names))!=len(names): raise ValueError('Duplicate archive paths')
        for member in members:
            parts=PurePosixPath(member.name)
            if not member.isfile() or parts.is_absolute() or '..' in parts.parts or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe archive member')
            if member.size > 5*1024*1024: raise ValueError('Archive member too large')
        if sum(m.size for m in members)>32*1024*1024: raise ValueError('Archive too large')
        manifest=json.load(bundle.extractfile('manifest.json'))
        if manifest.get('format')!='rongyao-codex-skill-bundle-v2' or set(manifest.get('skills',[]))!=set(SKILLS):
            raise ValueError('Unexpected bundle contract')
        entries=manifest['files']
        expected={entry['path'] for entry in entries}
        if len(expected)!=len(entries) or set(names)!=expected|{'manifest.json','START_HERE_FOR_CODEX.md'}:
            raise ValueError('Unexpected or missing archive file')
        files={}
        for entry in entries:
            relative=PurePosixPath(entry['path'])
            if len(relative.parts)<3 or relative.parts[0]!='skills' or relative.parts[1] not in SKILLS:
                raise ValueError('File outside selected Skills')
            raw=bundle.extractfile(entry['path']).read()
            if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                raise ValueError('Bundle integrity mismatch')
            files[str(relative.relative_to('skills'))]=raw
        for name in SKILLS:
            if name+'/SKILL.md' not in files: raise ValueError('Incomplete Skill')
        handoff=files['rongyao-data-stack/references/codex-handoff.md']
        if bundle.extractfile('START_HERE_FOR_CODEX.md').read()!=handoff:
            raise ValueError('Handoff integrity mismatch')
        return manifest,files


def child(root, name):
    root=root.resolve()
    result=root/name
    if result.is_symlink() or not result.resolve().is_relative_to(root):
        raise ValueError('Target escapes intended root')
    return result


def install(archive, target, backup, *, apply=False, replace=False):
    manifest,files=read_bundle(archive)
    target=target.resolve(); backup=backup.resolve()
    if backup==target or backup.is_relative_to(target) or target.is_relative_to(backup):
        raise ValueError('Target and backup roots must be disjoint')
    existing=[name for name in SKILLS if child(target,name).exists()]
    if existing and not replace: raise ValueError('Existing Skills require explicit --replace')
    if backup.exists(): raise ValueError('Backup directory must be new')
    plan={'version':manifest.get('version'), 'skills':list(SKILLS), 'existing':existing, 'applied':apply}
    if not apply: return plan
    target.mkdir(parents=True,exist_ok=True)
    backup.mkdir(parents=True)
    changed=[]; moved=[]
    with tempfile.TemporaryDirectory(prefix='.rongyao-install-',dir=target.parent) as temporary:
        stage=Path(temporary)
        for relative,raw in files.items():
            dest=stage/relative; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw)
        try:
            for name in SKILLS:
                dest=child(target,name)
                if name in existing:
                    os.replace(dest,child(backup,name)); moved.append(name)
                os.replace(child(stage,name),dest); changed.append(name)
            receipt={**plan,'target':str(target),'rolled_back':False}
            (backup/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        except Exception:
            for name in reversed(changed):
                os.replace(child(target,name),child(stage,name))
            for name in reversed(moved):
                os.replace(child(backup,name),child(target,name))
            raise
    return plan


def rollback(backup, *, apply=False):
    backup=backup.resolve()
    receipt=json.loads((backup/'receipt.json').read_text(encoding='utf-8'))
    if receipt.get('rolled_back'): raise ValueError('Backup already restored')
    if set(receipt['skills'])!=set(SKILLS) or not set(receipt['existing']).issubset(SKILLS):
        raise ValueError('Invalid receipt')
    target=Path(receipt['target']).resolve()
    if target==backup or target.is_relative_to(backup) or backup.is_relative_to(target):
        raise ValueError('Overlapping roots')
    for name in SKILLS:
        if not child(target,name).is_dir(): raise ValueError('Installed target missing')
        if name in receipt['existing'] and not child(backup,name).is_dir(): raise ValueError('Backup missing')
    if not apply: return {'rollback_ready':True,'applied':False}
    replaced=child(backup,'replaced-version')
    replaced.mkdir()
    moved=[]; restored=[]
    try:
        for name in SKILLS:
            os.replace(child(target,name),child(replaced,name)); moved.append(name)
            if name in receipt['existing']:
                os.replace(child(backup,name),child(target,name)); restored.append(name)
        receipt['rolled_back']=True
        (backup/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    except Exception:
        for name in reversed(restored): os.replace(child(target,name),child(backup,name))
        for name in reversed(moved): os.replace(child(replaced,name),child(target,name))
        raise
    return {'rolled_back':True,'replaced_version_preserved':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    install_parser=sub.add_parser('install')
    install_parser.add_argument('--archive',type=Path,required=True)
    install_parser.add_argument('--target',type=Path,required=True)
    install_parser.add_argument('--replace',action='store_true')
    for command in (install_parser,sub.add_parser('rollback')):
        command.add_argument('--backup-dir',type=Path,required=True)
        command.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.command=='install': result=install(args.archive,args.target,args.backup_dir,apply=args.apply,replace=args.replace)
    else: result=rollback(args.backup_dir,apply=args.apply)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
