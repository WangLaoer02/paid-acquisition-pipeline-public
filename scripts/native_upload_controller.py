"""Pinned native chooser controller; stdin JSON commands, no automatic retry/fallback."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from native_upload_guard import ActionJournal, NativeGuardError, observation, submission_state, verify_execution

ROOT = Path(__file__).resolve().parents[1]

def one(rows, predicate):
    found = [r for r in rows if predicate(r)]
    if len(found) != 1:
        raise NativeGuardError('NATIVE_CONTROL_NOT_UNIQUE')
    return found[0]

def goal_reached(goal, item, obs):
    goals = {'open_chooser':obs['chooser_open'],
             'resolve_file_path':item['file'] in obs['resolved_paths'],
             'select_current_file':obs['file_preview'],
             'submit_current_file':submission_state(obs,'selection_pending') == 'submitted_pending'}
    if goal not in goals:
        raise NativeGuardError('UNSUPPORTED_NATIVE_GOAL')
    return goals[goal]

def verify_submission_file(item, obs, file_sha):
    """Validate the current bytes and exact chooser selection before pressing Open."""
    source = Path(item['file'])
    if not source.is_file() or file_sha(source) != item['sha256']:
        raise NativeGuardError('NATIVE_PLAN_FILE_CHANGED')
    if not obs['chooser_open'] or obs['file_selected'] or obs['file_progress']:
        raise NativeGuardError('EXISTING_SELECTION_RECONCILE_ONLY')
    paths = obs['resolved_paths']
    if (not obs['file_preview'] or not paths or
            any(not Path(p).is_absolute() for p in paths) or
            {Path(p).resolve() for p in paths} != {source.resolve()}):
        raise NativeGuardError('EXACT_CHOOSER_FILE_NOT_VERIFIED')

def load_cli():
    path = ROOT/'workflow/rules/implementation/rongyao-tools/skills/rongyao-operations/scripts/rongyao.py'
    spec = importlib.util.spec_from_file_location('released_rongyao', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def run(plan_path, ticket):
    rg = load_cli(); plan = rg.reviewed_plan(plan_path)
    descriptor = verify_execution(ROOT, plan.get('native_execution'))
    if plan.get('test_only'):
        raise NativeGuardError('OFFLINE_TEST_PLAN_CANNOT_UPLOAD')
    runtime = rg.load_runtime(ROOT)
    ledger = rg.Ledger()
    journal = ActionJournal(rg.STATE/'native-actions.sqlite3')
    helper = ROOT/'workflow/tools/native-upload/native-ui'
    env = {**os.environ, 'WORKFLOW_NATIVE_CONTROLLER_PID': str(os.getpid()), 'WORKFLOW_NATIVE_WINDOW_TITLE': descriptor['window_title']}
    current = None
    pre_submit_rejected = False
    window = descriptor['window_title']

    def native(*args):
        verify_execution(ROOT, descriptor)  # Recheck before every event, including rebuilt binary.
        p = subprocess.run([str(helper), *args], env=env, capture_output=True, text=True, timeout=20)
        if 'NATIVE_ACCESSIBILITY_UNAVAILABLE' in p.stdout:
            journal.block_capability(window, 'accessibility', 'native permission unavailable')
            raise NativeGuardError('NATIVE_ACCESSIBILITY_UNAVAILABLE')
        if not args:
            if p.returncode:
                raise NativeGuardError('NATIVE_READ_FAILED')
            return json.loads(p.stdout)
        return p.returncode

    def observed(item):
        rows = native()
        return rows, observation(rows, item['filename'], window)

    def verify_form(rows, item):
        prefix = one(rows, lambda r:r.get('role') == 'AXWindow' and r.get('title') == window)['path'] + '.'
        rows = [r for r in rows if str(r.get('path','')).startswith(prefix)]
        for key, wanted in item['parameters'].items():
            if key == 'is_redbag' and wanted == 'platform_default_not_visible':
                continue
            if key == 'origin_type':
                field = one(rows, lambda r:r.get('role') == 'AXRadioButton' and r.get('title') == wanted)
                actual = field.get('value')
                if actual != 1:raise NativeGuardError('NATIVE_FORM_FIELD_MISMATCH')
            else:
                field = one(rows, lambda r:r.get('dom_id') == key)
                if isinstance(wanted, list):
                    parent = field['path'].rsplit('.',1)[0]
                    actual = one(rows, lambda r:r['path'] == parent+'.1').get('title')
                    if actual != (', '.join(wanted) if wanted else 'Nothing selected'):raise NativeGuardError('NATIVE_FORM_FIELD_MISMATCH')
                else:
                    if field.get('value') != wanted:raise NativeGuardError('NATIVE_FORM_FIELD_MISMATCH')
        return one(rows, lambda r:r.get('dom_id') == 'file' and r.get('role') == 'AXButton')

    def observe(item):
        _, obs = observed(item)
        old = ledger.existing(item['filename'])
        state = submission_state(obs, old['state'])
        # Preserve actual unknown error, never replace with a guessed helper failure.
        if state != old['state']:
            ledger.update(plan['job_id'], item['filename'], state,
                          evidence={'native_observation': obs, 'prior_state': old['state'],
                                    'prior_evidence': json.loads(old['evidence']) if old.get('evidence') else None})
        return state, obs

    try:
        with runtime.mutation('material_upload', rg.UPLOAD_SCOPE,
                              authorization_ticket=ticket, input_sha256=rg.plan_digest(plan)):
            for line in sys.stdin:
                c = json.loads(line); op = c['op']
                if op == 'finish':
                    break
                if op == 'capability-recheck':
                    item = plan['items'][c['index']]
                    _, fresh = observed(item)
                    journal.clear_capability(window, 'accessibility', bool(fresh), c.get('approval_ref'))
                    print(json.dumps({'capability_rechecked':True,'upload_performed':False}),flush=True)
                    continue
                if op not in {'observe'}:
                    journal.capability(window, 'accessibility')
                if op == 'open':
                    if current is not None:
                        raise NativeGuardError('FINISH_CURRENT_FILE_FIRST')
                    item = plan['items'][c['index']]
                    rows, before = observed(item)
                    if before['chooser_open'] or before['file_selected'] or before['file_progress']:
                        raise NativeGuardError('EXISTING_SELECTION_RECONCILE_ONLY')
                    button = verify_form(rows, item)
                    if ledger.claim(plan['job_id'], item):
                        print(json.dumps({'state':'listed','skipped':True}), flush=True); continue
                    ledger.update(plan['job_id'], item['filename'], 'selection_pending', evidence={'before':before})
                    current = item
                    args = ['press', button['path']]
                    goal = 'open_chooser'
                elif op == 'observe':
                    item = current or plan['items'][c['index']]
                    state, obs = observe(item)
                    print(json.dumps({'filename':item['filename'],'state':state,'observation':obs},ensure_ascii=False),flush=True)
                    if state in {'submitted_pending','listed','blocked_before_selection'}:
                        current = None
                    continue
                elif op == 'checkpoint':
                    item = current or plan['items'][c['index']]
                    _, fresh = observed(item)
                    if not goal_reached(c['goal'], item, fresh):
                        raise NativeGuardError('USER_CHECKPOINT_GOAL_NOT_OBSERVED')
                    key = journal.key(item['sha256'],window,item['filename'],c['goal'])
                    journal.user_checkpoint(key,fresh['fingerprint'],c.get('approval_ref'))
                    print(json.dumps({'checkpoint_recorded':True,'upload_performed':False}),flush=True)
                    continue
                elif op == 'resume':
                    if current is not None:
                        raise NativeGuardError('FINISH_CURRENT_FILE_FIRST')
                    item = plan['items'][c['index']]
                    old = ledger.existing(item['filename'])
                    if not old or old['owner'] != plan['job_id']:
                        raise NativeGuardError('JOB_DOES_NOT_OWN_RESERVATION')
                    state, obs = observe(item)
                    if state != 'selection_pending':
                        raise NativeGuardError('UNKNOWN_OR_SUBMITTED_RECONCILE_ONLY')
                    if item['file'] not in obs['resolved_paths'] and not obs['file_preview']:
                        raise NativeGuardError('SAME_FILE_CHOOSER_NOT_CONFIRMED')
                    current = item
                    print(json.dumps({'state':state,'continued':True}),flush=True); continue
                else:
                    if current is None:
                        raise NativeGuardError('NO_CURRENT_SELECTION')
                    item = current; rows, before = observed(item)
                    if not before['chooser_open']:
                        raise NativeGuardError('CHOOSER_CLOSED_OBSERVE_ONLY')
                    prefix = one(rows, lambda r:r.get('role') == 'AXWindow' and r.get('title') == window)['path']+'.'
                    sheets = [r['path']+'.' for r in rows if r.get('role') == 'AXSheet' and r['path'].startswith(prefix)]
                    if op == 'goto':
                        args = ['goto']; goal = 'resolve_file_path'
                    else:
                        row = one(rows, lambda r:r['path'] == c['path'])
                        if not any(row['path'].startswith(p) for p in sheets) or row.get('dom_id'):
                            raise NativeGuardError('CONTROL_OUTSIDE_CURRENT_CHOOSER')
                        if op == 'set' and row['role'] in {'AXTextField','AXComboBox'}:
                            args = ['set',row['path'],item['file']]; goal = 'resolve_file_path'
                        elif op == 'press' and row['role'] == 'AXButton' and row.get('title') in {'打开','Open','前往','Go'}:
                            args = ['press',row['path']]; goal = 'resolve_file_path' if row.get('title') in {'前往','Go'} else 'submit_current_file'
                        elif op == 'select_file_row' and row['role'] == 'AXTextField' and row.get('value') == item['filename']:
                            args = ['select',row['path']]; goal = 'select_current_file'
                        else:
                            raise NativeGuardError('UNSUPPORTED_NATIVE_OPERATION')
                if goal == 'submit_current_file':
                    try:
                        verify_submission_file(item, before, rg.sha256)
                        verify_form(rows, item)
                    except (NativeGuardError, OSError):
                        # No submit event was issued; retain the pending chooser for inspection.
                        pre_submit_rejected = True
                        raise
                key = journal.key(item['sha256'], window, item['filename'], goal)
                journal.begin(key, before['fingerprint'])
                rc = native(*args); time.sleep(.35)
                _, after = observed(item)
                success = goal_reached(goal,item,after)
                passed = journal.finish(key,before['fingerprint'],after['fingerprint'],success,
                                        error=None if success else 'TARGET_STATE_UNCHANGED')
                print(json.dumps({'goal':goal,'observed_success':passed,'helper_returncode':rc},ensure_ascii=False),flush=True)
                # State only follows evidence; process exit zero never means submitted.
                observe(item)
    except BaseException as exc:
        if current is not None:
            old = ledger.existing(current['filename'])
            evidence = {'error_type':type(exc).__name__,'phase':'native_pre_submit_rejected' if pre_submit_rejected else 'native_interrupted','auto_retry':False,
                        'prior_state':old['state'],
                        'prior_evidence':json.loads(old['evidence']) if old.get('evidence') else None}
            if isinstance(exc, NativeGuardError):
                evidence['error_code'] = str(exc)
            if isinstance(exc, subprocess.TimeoutExpired):
                evidence['timeout_seconds'] = exc.timeout
            if isinstance(exc, OSError):
                evidence['errno'] = exc.errno
            ledger.update(plan['job_id'],current['filename'],old['state'] if pre_submit_rejected else 'submission_unknown', evidence=evidence)
        raise
    finally:
        journal.close(); ledger.db.close()
