#!/usr/bin/env python3
"""Release-bound Canvas t2v adapter. No draft creation, login, implicit retry or settlement."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import workflow_runtime as runtime

SCOPE = 'paid-generation:dreamina-canvas-cli'
GEN_KEYS = ('mode', 'prompt', 'model', 'ratio', 'resolution', 'durationSeconds', 'outputCount', 'references')


class CliError(ValueError):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.details = details or {}


def safe_error(envelope):
    error = envelope.get('error', {})
    result = {}
    for key in ('code', 'reason', 'class', 'requiredAction', 'requestId', 'traceId'):
        value = error.get(key, envelope.get('meta', {}).get(key))
        if isinstance(value, str):
            result[key] = value if re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value) else 'unstructured_redacted'
    for key in ('retryable', 'serviceCode'):
        if type(error.get(key)) in (bool, int):
            result[key] = error[key]
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_path(plan, value):
    base = (ROOT / 'projects' / plan['project_id']).resolve()
    path = Path(value)
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    require(path.is_relative_to(base), 'PROJECT_PATH_REQUIRED')
    return path


def invoke(argv):
    # Never emit argv/stdout/stderr on failure: confirm carries a short-lived token.
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=60)
        envelope = json.loads(result.stdout or result.stderr)
    except OSError:
        raise CliError('CLI_NOT_STARTED', {'requiredAction': 'restore_cli', 'dispatch_state': 'not_started'}) from None
    except (subprocess.SubprocessError, ValueError):
        raise CliError('CLI_RESPONSE_UNAVAILABLE', {'requiredAction': 'inspect_original_operation'}) from None
    if result.returncode != 0 or envelope.get('ok') is not True:
        raise CliError('CLI_REQUEST_FAILED', safe_error(envelope))
    return envelope.get('data', envelope)


def canvas(plan, *args):
    import receiver_config
    cli=receiver_config.load(True).get('dreamina_cli') or 'dreamina-canvas'
    return invoke([cli, '--profile', plan['profile'], *args])


def validate_plan(plan):
    require(plan.get('schema') == 'dreamina-workflow-plan-v1', 'PLAN_SCHEMA')
    require(bool(re.fullmatch(r'[A-Za-z0-9_-]+', plan.get('project_id', ''))), 'PROJECT_ID')
    require(plan.get('profile') and not plan['profile'].startswith('-'), 'PROFILE_REQUIRED')
    for key in ('canvas_id', 'submit_id'):
        require(str(uuid.UUID(plan[key])) == plan[key], 'CANONICAL_UUID_REQUIRED')
    require(plan.get('node_id', '').startswith('node_'), 'NODE_ID_REQUIRED')
    require(str(plan.get('account_id', '')).isdigit(), 'ACCOUNT_ID_REQUIRED')
    require(isinstance(plan.get('consumption_kind'), str) and plan['consumption_kind'], 'QUOTED_CONSUMPTION_KIND_REQUIRED')
    require(plan.get('item_id') and plan.get('story_version'), 'CURRENT_ITEM_VERSION_REQUIRED')
    require(plan.get('approval_ref') and plan.get('approved') is True, 'USER_APPROVAL_REQUIRED')
    require(plan.get('current_input_files'), 'CURRENT_INPUT_FILES_REQUIRED')
    require(plan.get('sheet', {}).get('values_sha256'), 'CURRENT_SHEET_PROOF_REQUIRED')
    generation = plan.get('generation', {})
    require(set(generation) == set(GEN_KEYS), 'GENERATION_FIELDS_REQUIRED')
    require(generation['mode'] == 't2v' and generation['references'] == [], 'T2V_WITHOUT_REFERENCES_ONLY')
    require(generation['outputCount'] == 1, 'ONE_OUTPUT_ONLY')
    require(all(generation.get(k) for k in ('prompt', 'model', 'ratio', 'resolution', 'durationSeconds')), 'GENERATION_INPUT_REQUIRED')
    require(type(plan.get('max_credits')) is int and plan['max_credits'] > 0, 'REAL_QUOTE_REQUIRED')
    require(type(plan.get('draft_version')) is int and plan['draft_version'] >= 0, 'DRAFT_VERSION_REQUIRED')
    require(plan.get('budget_ledger') and type(plan.get('budget_total_cap')) in (int, float) and math.isfinite(plan['budget_total_cap']) and plan['budget_total_cap'] >= 0, 'APPROVED_BUDGET_REQUIRED')
    manifest = read(ROOT / 'workflow/rules/manifest.json')
    require(plan.get('release_id') == manifest.get('release_id'), 'PLAN_RELEASE_MISMATCH')
    require(plan.get('manifest_sha256') == file_sha(ROOT / 'workflow/rules/manifest.json'), 'PLAN_MANIFEST_MISMATCH')
    for relative in ('scripts/dreamina_workflow.py', 'scripts/workflow_runtime.py', 'workflow/runtime-policy.json'):
        require(manifest.get('workspace_contract_files', {}).get(relative) == file_sha(ROOT / relative), 'UNSEALED_ADAPTER: ' + relative)
    for proof in plan['current_input_files']:
        require(file_sha(project_path(plan, proof['path'])) == proof['sha256'], 'CURRENT_INPUT_CHANGED')
    for key in ('input_manifest', 'reference_scope'):
        proof = plan.get(key, {})
        require(proof.get('path') and proof.get('sha256'), 'NODE_INPUT_MANIFEST_AND_SCOPE_REQUIRED')
        require(file_sha(project_path(plan, proof['path'])) == proof['sha256'], 'NODE_INPUT_PROOF_CHANGED')
    return runtime.digest(plan)


def account(plan):
    data = canvas(plan, 'auth', 'account')
    require(str(data.get('userId')) == str(plan['account_id']), 'ACCOUNT_MISMATCH')
    available = float(data.get('availableCredits', data.get('credits', {}).get('available', 'nan')))
    require(math.isfinite(available) and available >= plan['max_credits'], 'INSUFFICIENT_OR_UNKNOWN_CREDITS')
    return {'user_id': str(data['userId']), 'available_credits': available}


def current_node(plan):
    data = invoke([sys.executable, str(ROOT / 'scripts/workflow_node.py'), 'context', '--item', plan['item_id'], '--format', 'json'])
    live = data.get('live_state', {})
    require(data.get('release_id') == plan['release_id'] and data.get('release', {}).get('live_center_verified') is True, 'LIVE_RELEASE_MISMATCH')
    require(live.get('project_id') == plan['project_id'] and live.get('item', {}).get('id') == plan['item_id'], 'LIVE_ITEM_MISMATCH')
    require(live.get('live_node_verified') is True and data.get('node') == 'A12', 'FORMAL_GENERATION_NODE_REQUIRED')
    item = live['item']
    require(not live.get('pending_sync') and not item.get('revalidation_required') and not item.get('affected_nodes_require_revalidation'), 'UPSTREAM_REVALIDATION_REQUIRED')
    sheet = plan['sheet']
    current = invoke(['lark-cli', 'sheets', '+csv-get', '--spreadsheet-token', sheet['spreadsheet_token'], '--sheet-id', sheet['sheet_id'], '--range', sheet['range'], '--max-chars', '30000'])
    require(current.get('has_more') is False and current.get('actual_range') == sheet['range'], 'CURRENT_SHEET_INCOMPLETE')
    require(hashlib.sha256(current['annotated_csv'].encode()).hexdigest() == sheet['values_sha256'], 'CURRENT_SHEET_CHANGED')
    inspected = invoke([sys.executable, str(ROOT / 'scripts/workflow_node.py'), 'inspect-inputs', '--node', 'A12',
                        '--input-manifest', str(project_path(plan, plan['input_manifest']['path'])),
                        '--reference-scope', str(project_path(plan, plan['reference_scope']['path'])), '--format', 'json'])
    require(inspected.get('node') == 'A12' and inspected.get('release_id') == plan['release_id'] and inspected.get('complete') is True and not inspected.get('missing_or_unverified'), 'NODE_INPUT_REQUIREMENTS_INCOMPLETE')


def quote(plan):
    shown = canvas(plan, 'node', 'show', '--project-id', plan['canvas_id'], '--node-id', plan['node_id'])
    rows = shown.get('nodes', [])
    require(len(rows) == 1 and rows[0].get('node', {}).get('nodeId') == plan['node_id'], 'NODE_READ_REQUIRED')
    node = rows[0]['node']
    require(node.get('type') == 'video', 'VIDEO_NODE_REQUIRED')
    require(not node.get('resources'), 'EXISTING_CANVAS_RESOURCE_REVIEW_REQUIRED')
    generation = node.get('generation', {})
    effective = {k: generation.get(k, [] if k == 'references' else None) for k in GEN_KEYS}
    require(effective == plan['generation'], 'CANVAS_INPUT_CHANGED')
    data = canvas(plan, 'node', 'quote', '--project-id', plan['canvas_id'], '--node-id', plan['node_id'])
    subject = data.get('consumptionSubject', {})
    require(subject.get('kind') == plan['consumption_kind'] and not subject.get('teamId') and str(subject.get('userId')) == str(plan['account_id']), 'CONSUMPTION_ACCOUNT_MISMATCH')
    items = data.get('items', [])
    require(len(items) == 1 and items[0].get('nodeId') == plan['node_id'] and not items[0].get('error'), 'COMPLETE_QUOTE_REQUIRED')
    require(not items[0].get('generationDiff'), 'SERVER_GENERATION_DIFF')
    require(data.get('draftVersion') == plan['draft_version'], 'QUOTE_DRAFT_CHANGED')
    require(type(data.get('totalMaxCredits')) is int and data['totalMaxCredits'] == plan['max_credits'] and items[0].get('maxCredits') == plan['max_credits'], 'QUOTE_CHANGED')
    return {'draft_version': data['draftVersion'], 'max_credits': data['totalMaxCredits']}


def budget_check(plan, path):
    budget = read(path)
    for key in ('settled_points', 'reserved_points', 'total_cap'):
        value = budget.get(key)
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'INVALID_BUDGET')
    require(not budget.get('unknown_outcome_jobs'), 'RECONCILE_UNKNOWN_BUDGET_FIRST')
    require(budget['total_cap'] == plan['budget_total_cap'], 'BUDGET_AUTHORIZATION_CHANGED')
    require(budget['settled_points'] + budget['reserved_points'] + plan['max_credits'] <= budget['total_cap'], 'PROJECT_BUDGET_EXCEEDED')
    require(isinstance(budget.get('submitted_jobs'), list), 'EXISTING_BUDGET_LEDGER_REQUIRED')
    key = runtime.digest([plan['canvas_id'], plan['node_id'], plan['generation'], plan['project_id'], plan['story_version']])
    matches = [x for x in budget['submitted_jobs'] if x.get('canvas_input_key') == key or x.get('submit_id') == plan['submit_id']]
    require(all(x.get('state') == 'NOT_SENT' and x.get('submit_id') == plan['submit_id'] and x.get('input_sha256') == runtime.digest(plan) for x in matches), 'ORIGINAL_OPERATION_REQUIRED')
    return budget, key


def query(receipt_path):
    receipt = read(receipt_path)
    require(receipt.get('transport') == 'dreamina-canvas' and receipt.get('submit_id'), 'CANVAS_RECEIPT_REQUIRED')
    # Read-only and works for accepted/unknown operations even after ticket expiry.
    data = canvas(receipt, 'auth', 'account')
    require(str(data.get('userId')) == str(receipt['account_id']), 'ACCOUNT_MISMATCH')
    result = canvas(receipt, 'operation', 'status', receipt['submit_id'], '--project-id', receipt['canvas_id'])
    return {'ok': True, 'submit_id': receipt['submit_id'], 'state': result.get('state'),
            'submission_state': result.get('submission', {}).get('state'),
            'resources': [{'resource_id': r.get('resourceId'), 'state': r.get('state')} for r in result.get('resources', [])],
            'resubmit_allowed': False, 'settlement_inferred': False}


def submit(plan, ticket_path, budget_path, receipt_path, execute=False):
    digest = validate_plan(plan)
    budget_path = project_path(plan, budget_path)
    require(budget_path == project_path(plan, plan['budget_ledger']), 'BUDGET_LEDGER_MISMATCH')
    receipt_path = project_path(plan, receipt_path)
    if receipt_path.exists():
        existing = read(receipt_path)
        require(existing.get('input_sha256') == digest, 'RECEIPT_INPUT_MISMATCH')
        if existing.get('state') != 'NOT_SENT':
            return query(receipt_path)
    runtime.ensure_writer('paid_generation')
    runtime.dependencies('paid_generation', SCOPE)
    runtime.ensure_release(True)
    ticket = runtime.authorization(ticket_path, 'paid_generation', SCOPE, digest, False)
    require(ticket.get('approval_ref') == plan['approval_ref'], 'APPROVAL_REFERENCE_MISMATCH')
    current_node(plan)
    account(plan)
    quote(plan)
    budget_check(plan, budget_path)
    if not execute:
        return {'ok': True, 'input_sha256': digest, 'state': 'CHECKED_NOT_SUBMITTED', 'side_effects': []}
    with runtime.mutation('paid_generation', SCOPE, authorization_ticket=ticket_path, input_sha256=digest):
        validate_plan(plan)
        current_node(plan)
        account(plan)
        quote(plan)
        budget, key = budget_check(plan, budget_path)
        require(not receipt_path.exists() or read(receipt_path).get('state') == 'NOT_SENT', 'ORIGINAL_OPERATION_REQUIRED')
        receipt = {'transport': 'dreamina-canvas', 'profile': plan['profile'], 'account_id': plan['account_id'],
                   'canvas_id': plan['canvas_id'], 'node_id': plan['node_id'], 'submit_id': plan['submit_id'],
                   'input_sha256': digest, 'canvas_input_key': key, 'state': 'RESERVED', 'max_credits': plan['max_credits'], 'run_started': False}
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        runtime.atomic(receipt_path, receipt)
        budget['reserved_points'] += plan['max_credits']
        job = {**receipt, 'reserved_points': plan['max_credits'], 'receipt_path': str(receipt_path.relative_to(ROOT))}
        previous = next((i for i, row in enumerate(budget['submitted_jobs']) if row.get('submit_id') == plan['submit_id']), None)
        if previous is None:
            budget['submitted_jobs'].append(job)
        else:
            budget['submitted_jobs'][previous] = job
        runtime.atomic(budget_path, budget)
        run_started = False
        try:
            confirmation = canvas(plan, 'node', 'confirm', '--project-id', plan['canvas_id'], '--node-id', plan['node_id'], '--credit-ceiling', str(plan['max_credits']))
            token = confirmation.get('creditConfirmationToken')
            require(token and confirmation.get('creditCeiling') == plan['max_credits'], 'CONFIRMATION_INVALID')
            subject = confirmation.get('consumptionSubject', {})
            require(subject.get('kind') == plan['consumption_kind'] and not subject.get('teamId') and str(subject.get('userId')) == str(plan['account_id']), 'CONFIRMATION_ACCOUNT_MISMATCH')
            validate_plan(plan)
            current_node(plan)
            account(plan)
            quote(plan)
            receipt['state'] = job['state'] = 'SUBMISSION_UNKNOWN'
            receipt['run_started'] = job['run_started'] = True
            runtime.atomic(receipt_path, receipt)
            runtime.atomic(budget_path, budget)
            run_started = True
            result = canvas(plan, 'node', 'run', '--project-id', plan['canvas_id'], '--node-id', plan['node_id'], '--submit-id', plan['submit_id'], '--credit-token', token)
            token = None
            subject = result.get('consumptionSubject', {})
            require(subject.get('kind') == plan['consumption_kind'] and not subject.get('teamId') and str(subject.get('userId')) == str(plan['account_id']), 'RUN_ACCOUNT_MISMATCH')
            items = result.get('items', [])
            require(len(items) == 1 and items[0].get('submitId') == plan['submit_id'] and items[0].get('nodeId') == plan['node_id'], 'RUN_RECEIPT_MISMATCH')
            state = items[0].get('state')
            require(state in ('accepted', 'rejected', 'unknown'), 'RUN_STATE_UNKNOWN')
            receipt['state'] = job['state'] = state
            receipt['generation_diff'] = bool(items[0].get('generationDiff'))
            if state == 'unknown':
                budget.setdefault('unknown_outcome_jobs', []).append(plan['submit_id'])
            runtime.atomic(receipt_path, receipt)
            runtime.atomic(budget_path, budget)
            runtime.event('paid_generation', state, SCOPE, input_sha256=digest, submit_id=plan['submit_id'])
            return {'ok': state == 'accepted' and not receipt['generation_diff'], **receipt, 'production_accepted': False}
        except Exception as exc:
            details = getattr(exc, 'details', {})
            if details.get('dispatch_state') == 'not_started':
                run_started = False
            cause = str(exc).split(';')[0]
            details = {**details, 'cause': cause if re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', cause) else 'local_failure', 'run_started': run_started}
            receipt['failure'] = details
            if run_started:
                # Never infer refund/non-acceptance after invoking run.
                receipt['state'] = job['state'] = 'SUBMISSION_UNKNOWN'
                if plan['submit_id'] not in budget.setdefault('unknown_outcome_jobs', []):
                    budget['unknown_outcome_jobs'].append(plan['submit_id'])
            else:
                # Confirm grants a ceiling; it does not submit or spend credits.
                receipt['state'] = job['state'] = 'NOT_SENT'
                receipt['run_started'] = job['run_started'] = False
                budget['reserved_points'] -= plan['max_credits']
                job['reserved_points'] = 0
            runtime.atomic(receipt_path, receipt)
            runtime.atomic(budget_path, budget)
            runtime.event('paid_generation', receipt['state'], SCOPE, input_sha256=digest, submit_id=plan['submit_id'], failure=details)
            raise CliError('ORIGINAL_OPERATION_REQUIRED' if run_started else 'PRE_SEND_FAILED', details) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for command in ('check', 'submit'):
        sub = subs.add_parser(command)
        sub.add_argument('--plan', required=True)
        sub.add_argument('--authorization-ticket', required=True)
        sub.add_argument('--budget-ledger', required=True)
        sub.add_argument('--receipt', required=True)
    sub = subs.add_parser('query')
    sub.add_argument('--receipt', required=True)
    args = parser.parse_args()
    try:
        result = query(args.receipt) if args.command == 'query' else submit(read(args.plan), args.authorization_ticket, args.budget_ledger, args.receipt, args.command == 'submit')
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Fixed codes only; never echo a command or provider payload.
        print(json.dumps({'ok': False, 'error': str(exc).split(';')[0], 'details': getattr(exc, 'details', {}), 'retry_submit': False}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
