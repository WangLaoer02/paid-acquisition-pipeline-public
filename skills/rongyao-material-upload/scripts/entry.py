#!/usr/bin/env python3
"""Read-only release, route and public-receipt reporting; never submits uploads."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

SKILL = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guarded(root, name):
    rel = Path(name)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('UNSAFE_CONTRACT_PATH')
    path = root / rel
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('UNSAFE_CONTRACT_PATH')
    return path


def local_check(workspace):
    contract = read(SKILL / 'references/contract.json')
    manifest = read(workspace / 'workflow/rules/manifest.json')
    if manifest['release_id'] != contract['release_id']:
        raise ValueError('RELEASE_MISMATCH')
    prefix = 'implementation/backend-upload/skill/'
    expected = {k[len(prefix):]: v for k, v in manifest['implementation_files'].items() if k.startswith(prefix)}
    actual = {str(p.relative_to(SKILL)): digest(p) for p in SKILL.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    if not expected or actual != expected:
        raise ValueError('SKILL_PACKAGE_MISMATCH')
    for name, sha in contract['workspace_dependencies'].items():
        path = guarded(workspace, name)
        if not path.is_file() or digest(path) != sha:
            raise ValueError('WORKSPACE_DEPENDENCY_MISMATCH: ' + name)
    for name in contract['python_imports']:
        if importlib.util.find_spec(name) is None:
            raise ValueError('PYTHON_DEPENDENCY_MISSING: ' + name)
    stages = read(workspace / 'workflow/stages.json')
    routes = read(workspace / 'workflow/node_skills.json')
    nodes = [n for family in stages['families'].values() for n in family]
    if routes['release_id'] != contract['release_id'] or set(routes['nodes']) != {n['id'] for n in nodes}:
        raise ValueError('NODE_ROUTE_MISMATCH')
    for node in nodes:
        item = routes['nodes'][node['id']]
        if item['label'] != node['label'] or item['required_output'] != node['required_output']:
            raise ValueError('ORIGINAL_NODE_CHANGED')
    return contract, routes


def public_status(workspace, contract):
    output = guarded(workspace, contract['public_receipts_path'])
    counts = Counter()
    recent = None
    last_time = None
    if output.exists():
        for path in output.glob('*.json'):
            if path.is_symlink():
                continue
            try:
                data = read(path)
            except (OSError, ValueError):
                continue
            # Only adapter receipts; never include raw response dictionaries or authentication.
            if data.get('schema') != 'rongyao-video-list-fast-1':
                continue
            counts[str(data.get('status', 'UNKNOWN'))] += 1
            if last_time is None or path.stat().st_mtime > last_time:
                last_time = path.stat().st_mtime
                recent = {'path': str(path), 'status': data.get('status'),
                          'material_id': data.get('material_id'),
                          'started_at_epoch': data.get('started_at_epoch')}
    return {'historical_receipt_counts': dict(counts), 'last_public_receipt': recent,
            'output_path': str(output), 'this_invocation_uploaded': 0,
            'successful_new_uploads_this_invocation': 0,
            'known_blockers': contract['unverified_capabilities'],
            'numeric_login_uid_verified': False, 'multiple_login_sessions_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'route', 'status'])
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--node')
    parser.add_argument('--offline-preparation', action='store_true')
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    try:
        contract, routes = local_check(workspace)
        check = [sys.executable, '-B', str(workspace / 'scripts/workflow_rules.py'), 'check']
        if args.offline_preparation:
            check.append('--offline-preparation')
        run = subprocess.run(check, cwd=workspace, capture_output=True, text=True, timeout=58)
        if run.returncode:
            raise ValueError('CENTER_OR_PACKAGE_CHECK_FAILED')
        release = json.loads(run.stdout)
        if not release.get('ok'):
            raise ValueError('CENTER_OR_PACKAGE_CHECK_FAILED')
        plan_path = guarded(workspace, contract['reviewed_plan_path'])
        plan_present = plan_path.is_file()
        if plan_present:
            if digest(plan_path) != contract['reviewed_plan_sha256']:
                raise ValueError('REVIEWED_PLAN_CHANGED')
            plan = read(plan_path)
            if len(plan.get('items', [])) != contract['reviewed_plan_count']:
                raise ValueError('REVIEWED_PLAN_CHANGED')
        result = {'ok': True, 'release_id': release['release_id'],
                  'live_center_verified': release['live_center_verified'],
                  'writes_performed': False, 'submits_upload': False,
                  'reviewed_plan_count': contract['reviewed_plan_count'] if plan_present else 0,
                  'input_scope_status': 'REGISTERED_GENERIC_PLAN_WITH_INPUT_SHA_TICKET',
                  'legacy_input_scope_status': 'FIXED_REVIEWED_PLAN_ONLY' if plan_present else 'MISSING_REVIEWED_PLAN',
                  'generic_cli_version': contract['generic_cli']['version'], 'live_generic_upload_verified': False,
                  'default_http': contract.get('default_http'), 'generic_cli_route': contract['generic_cli'].get('default_route')}
        if args.command == 'route':
            if args.node not in routes['nodes']:
                raise ValueError('UNKNOWN_ORIGINAL_NODE')
            result.update(node_reference=routes['nodes'][args.node],
                          selected_node_is_reference_only=True,
                          instruction='Use workflow_node.py context --item <real item id> to resolve the actual online node; route metadata alone does not verify or change it.')
        elif args.command == 'status':
            result.update(public_status(workspace, contract))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError):
        # Do not echo arbitrary file contents, subprocess output or private input.
        print(json.dumps({'ok': False, 'error': 'RELEASE_DEPENDENCY_OR_INPUT_CHECK_FAILED',
                          'writes_performed': False, 'submits_upload': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
