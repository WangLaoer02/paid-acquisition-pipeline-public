#!/usr/bin/env python3
"""Check recorded face-reference roles and hashes; this is not visual recognition."""
import argparse
import hashlib
import json
from pathlib import Path


def check(root, record, stage):
    errors = []
    inputs = {item['path']: item for item in record.get('generation_inputs', [])}
    roles = record.get('reference_roles', [])
    real_identity = []
    for role in roles:
        path = role.get('path')
        item = inputs.get(path)
        if item is None:
            errors.append(f'reference role is not an actual input: {path}')
            continue
        p = Path(path)
        if not p.is_absolute():
            p = root / p
        if not p.is_file():
            errors.append(f'missing input: {path}')
        elif hashlib.sha256(p.read_bytes()).hexdigest() != item.get('sha256'):
            errors.append(f'input hash mismatch: {path}')
        if role.get('role') in ('real_identity_primary', 'real_identity_auxiliary'):
            if role.get('source_role') not in ('raw_frame', 'raw_photo', 'source_view'):
                errors.append(f'identity input is not a real source: {path}')
            elif not role.get('author_verified') or role.get('character_id') != record.get('character_id'):
                errors.append(f'identity source lacks matching person binding: {path}')
            else:
                real_identity.append(path)
    if len({r.get('path') for r in roles}) != len(inputs):
        errors.append('every actual input needs one distinct role record')
    if not real_identity:
        errors.append('no directly bound real facial identity input')
    if record.get('edit_lineage', {}).get('failed_output_used_as_identity_or_texture') is not False:
        errors.append('failed-output identity/texture exclusion not recorded')
    if stage == 'delivery':
        if record.get('current_selected') is not True:
            errors.append('not the current selected candidate')
        if record.get('artifact_review', {}).get('status') not in ('passed', 'passed_with_limits'):
            errors.append('artifact review is rejected, failed or pending')
        for key in ('face_texture_review', 'face_likeness_review', 'face_decoration_review'):
            if record.get(key, {}).get('status') != 'passed':
                errors.append(f'{key} is not passed')
        if record.get('face_texture_review', {}).get('native_scale_checked') is not True:
            errors.append('native-scale face inspection missing')
        if record.get('head_visual_review') != 'passed':
            errors.append('head visual review is not passed')
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root', type=Path)
    ap.add_argument('records', nargs='+', type=Path)
    ap.add_argument('--stage', choices=('generate', 'delivery'), required=True)
    args = ap.parse_args()
    output = []
    for name in args.records:
        path = name if name.is_absolute() else args.root / name
        errors = check(args.root, json.loads(path.read_text()), args.stage)
        output.append({'record': str(name), 'stage': args.stage, 'passed': not errors, 'errors': errors})
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(x['passed'] for x in output) else 1)


if __name__ == '__main__':
    main()
