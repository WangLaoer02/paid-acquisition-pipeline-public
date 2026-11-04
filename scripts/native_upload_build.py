#!/usr/bin/env python3
"""Compile the published native helper locally; never opens UI or uploads a file."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import os
ROOT = Path(__file__).resolve().parents[1]
def build(root=ROOT):
    root = Path(root).resolve()
    source = root/'workflow/tools/native-upload/native-ui.swift'
    manifest = json.loads((root/'workflow/rules/manifest.json').read_text())
    digest = lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    expected = manifest['workspace_contract_files'].get(str(source.relative_to(root)))
    source_sha = digest(source)
    if expected != source_sha:
        raise ValueError('NATIVE_SOURCE_NOT_PUBLISHED')
    target = source.with_name('native-ui')
    with tempfile.TemporaryDirectory(dir=source.parent) as temporary:
        compiled = Path(temporary)/'native-ui'
        subprocess.run(['swiftc',str(source),'-o',str(compiled)],check=True,capture_output=True,timeout=120)
        if digest(source) != source_sha:
            raise ValueError('NATIVE_SOURCE_CHANGED_DURING_BUILD')
        receipt = {'source_sha256':source_sha,'binary_sha256':digest(compiled),
                   'release_id':manifest['release_id'],'compilation_only':True,'ui_executed':False}
        receipt_path = Path(temporary)/'build.json'
        receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
        os.chmod(compiled,0o700)
        os.replace(compiled,target)
        os.replace(receipt_path,source.with_name('build.json'))
    return receipt
if __name__=='__main__':
    print(json.dumps(build(),ensure_ascii=False,indent=2))
