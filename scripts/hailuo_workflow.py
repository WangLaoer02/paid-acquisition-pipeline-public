#!/usr/bin/env python3
"""MiniMax CLI adapter: prepare, submit once, query, and collect raw media."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import getpass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import workflow_runtime as runtime
CONFIG = ROOT / 'workflow/hailuo.json'
GOOD = {'Success', 'succeeded'}
BAD = {'Failed', 'failed', 'cancelled', 'expired'}


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def load(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def scrub(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if k.lower() in {'api_key', 'key', 'access_token', 'refresh_token', 'authorization', 'password'} else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str) and value.startswith('data:'):
        return {'inline_media_sha256': hashlib.sha256(value.encode()).hexdigest(), 'encoded_length': len(value)}
    return value


def mmx(args, quiet=True):
    cfg = load(CONFIG)
    env = dict(os.environ, MMX_CONFIG_DIR=str(Path(cfg['credential_directory']).expanduser()), NO_COLOR='1', MINIMAX_VERBOSE='0')
    command = [cfg['executable'], *args, '--region', cfg['region'], '--base-url', cfg['base_url'], '--output', 'json', '--non-interactive', '--timeout', '45']
    if quiet:
        command.append('--quiet')
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=55, cwd=ROOT)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('CLI timeout; do not replay a generation submission.') from exc
    if result.returncode:
        # stderr can contain a status bar with a credential prefix. Never archive it.
        raise RuntimeError(f'mmx failed with exit {result.returncode}; inspect the original task/account before continuing.')
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('CLI returned no structured result; generation acceptance may be unknown.') from exc


def doctor():
    cfg = load(CONFIG)
    version = subprocess.check_output([cfg['executable'], '--version'], text=True).strip()
    if version != 'mmx ' + cfg['verified_cli_version']:
        raise ValueError('CLI version changed; recheck generate/query/download help before continuing.')
    auth = mmx(['auth', 'status'])
    usage = auth.get('usage') or (mmx(['quota', 'show']) if auth.get('method') == 'oauth' else {})
    if usage.get('base_resp', {}).get('status_code') != 0:
        raise ValueError('Live usage authentication was not confirmed.')
    video = next((v for v in usage.get('model_remains', []) if v.get('model_name') == 'video'), None)
    ready = False
    status = 'video_entitlement_unverified'
    if video:
        unavailable = all(video.get(k) == 0 for k in ['current_interval_total_count', 'current_weekly_total_count']) and all(video.get(k) == 3 for k in ['current_interval_status', 'current_weekly_status'])
        exhausted = any(video.get(k) == 2 for k in ['current_interval_status', 'current_weekly_status']) or any(video.get(k) == 0 for k in ['current_interval_remaining_percent', 'current_weekly_remaining_percent'])
        if unavailable:
            status = 'not_in_current_token_plan'
        elif exhausted:
            status = 'video_quota_exhausted'
        elif video.get('current_interval_status') == 1 and video.get('current_weekly_status') in {1, 3}:
            status, ready = 'video_quota_reported_available', True
    elif 'available_amount' in usage:
        amount = float(usage['available_amount'])
        if math.isfinite(amount) and amount > 0:
            # The job's account-and-quote approval remains mandatory before submission.
            status, ready = 'paid_balance_available_quote_required', True
        else:
            status = 'paid_balance_empty'
    return {'checked_at': now(), 'cli_version': version, 'region': cfg['region'], 'credential_directory': cfg['credential_directory'], 'authentication': auth.get('method'), 'live_authentication_passed': True, 'video_entitlement': status, 'generation_ready': ready, 'public_usage': scrub(usage)}


def configure_account():
    if not sys.stdin.isatty():
        raise ValueError('Run configure-account in a local terminal; never pass a Key through chat or command arguments.')
    secret = getpass.getpass('海螺视频 API Key（隐藏输入）: ').strip()
    if not secret:
        raise ValueError('No credential entered; configuration unchanged.')
    cfg = load(CONFIG)
    directory = Path(cfg['credential_directory']).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / 'config.json'
    current = path.read_bytes() if path.exists() else None
    values = json.loads(current) if current else {}
    values.pop('oauth', None)
    values.update(api_key=secret, region=cfg['region'], default_video_model=cfg['default_model'])
    temp = directory / 'config.new.json'
    with temp.open('w', opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
        json.dump(values, output)
    os.chmod(temp, 0o600)
    temp.replace(path)
    try:
        return doctor()
    except Exception:
        if current is None:
            path.unlink()
        else:
            path.write_bytes(current)
            os.chmod(path, 0o600)
        raise


def job(path):
    data = load(path)
    for key in ['run_id', 'project_id', 'story_version', 'segment']:
        if not isinstance(data.get(key), str) or not re.fullmatch(r'[A-Za-z0-9_\-]{1,100}', data[key]):
            raise ValueError(f'Missing or unsafe {key}.')
    if not data.get('prompt', '').strip():
        raise ValueError('A real prompt is required.')
    reg = load(ROOT / load(CONFIG)['project_registry'])
    project = next((p for p in reg['projects'] if p['project_id'] == data['project_id']), None)
    if not project or data.get('project_console_url') != project['console_url']:
        raise ValueError('Job must point to the registered unique project console.')
    if not data.get('a_product_id'):
        raise ValueError('Parent A identifier is required.')
    return data


def generate_args(data):
    model = data.get('model', load(CONFIG)['default_model'])
    if model not in load(CONFIG)['models']:
        raise ValueError('Unsupported configured model.')
    args = ['video', 'generate', '--model', model, '--prompt', data['prompt'], '--async']
    flags = {'first_frame': '--image', 'last_frame': '--last-frame', 'subject': '--subject-image', 'reference_image': '--reference-image', 'reference_video': '--reference-video', 'reference_audio': '--reference-audio'}
    roles = []
    for asset in data.get('assets', []):
        role = asset.get('role')
        if role not in flags:
            raise ValueError('Invalid asset role.')
        asset_path = Path(asset['path']).expanduser().resolve()
        if not asset_path.is_file() or hashlib.sha256(asset_path.read_bytes()).hexdigest() != asset.get('sha256'):
            raise ValueError('Missing or changed reference asset.')
        roles.append(role)
        args += [flags[role], str(asset_path)]
    if any(roles.count(k) > 1 for k in ['first_frame', 'last_frame', 'subject']):
        raise ValueError('Only one first frame, last frame or subject is allowed.')
    if model != 'MiniMax-H3' and any(r.startswith('reference_') for r in roles):
        raise ValueError('Reference images/video/audio require H3.')
    if model == 'MiniMax-H3' and 'subject' in roles:
        raise ValueError('H3 subject references use reference_image, not subject.')
    if model == 'MiniMax-Hailuo-2.3-Fast' and 'first_frame' not in roles:
        raise ValueError('Fast requires an input image.')
    if model == 'MiniMax-Hailuo-02' and not {'first_frame', 'last_frame'} <= set(roles):
        raise ValueError('Hailuo-02 requires first and last frames.')
    if model == 'S2V-01' and roles != ['subject']:
        raise ValueError('S2V requires exactly one subject reference.')
    if model in {'MiniMax-Hailuo-2.3', 'MiniMax-Hailuo-2.3-Fast'} and any(r != 'first_frame' for r in roles):
        raise ValueError('Select Hailuo-02 or S2V explicitly for the requested mode.')
    if 'reference_audio' in roles and not any(r in roles for r in ['reference_image', 'reference_video']):
        raise ValueError('H3 reference audio requires a reference image or video.')
    params = data.get('parameters', {})
    if set(params) - {'duration', 'ratio'} or (params and model != 'MiniMax-H3'):
        raise ValueError('This CLI exposes duration/ratio for H3 only; unsupported parameters are never silently ignored.')
    for key, value in params.items():
        args += ['--' + key, str(value)]
    return args


def preview(data):
    response = mmx(generate_args(data) + ['--dry-run'])
    if not response.get('request') or response.get('taskId') or response.get('task_id'):
        raise ValueError('Expected a dry-run request without a task.')
    return {'prepared_at': now(), 'project_id': data['project_id'], 'a_product_id': data['a_product_id'], 'story_version': data['story_version'], 'segment': data['segment'], 'job_sha256': digest(data), 'request_sha256': digest(response['request']), 'request': scrub(response['request']), 'generation_submitted': False}


def state_path(data):
    return ROOT / load(CONFIG)['run_directory'] / data['run_id'] / 'state.json'


def paid_checks(data, health):
    if data.get('purpose') != 'production':
        raise ValueError('Tool-validation jobs cannot be submitted.')
    if not health['generation_ready']:
        raise ValueError('Video entitlement is not ready; no generation will be submitted.')
    approval = data.get('approvals', {})
    for key in ['current_rules_verified', 'upstream_gates_passed', 'account_and_quote_verified', 'paid_generation_authorized']:
        if approval.get(key) is not True:
            raise ValueError('Missing current project evidence: ' + key)
    if not approval.get('evidence') or not all(a.get('approved') is True for a in data.get('assets', [])):
        raise ValueError('Approval evidence and approved reference assets are required.')
    budget = data.get('budget', {})
    keys = ['limit', 'confirmed_spend', 'in_flight_reserved', 'this_task_maximum']
    if not budget.get('unit') or any(isinstance(budget.get(k), bool) or not isinstance(budget.get(k), (int, float)) or not math.isfinite(budget[k]) or budget[k] < 0 for k in keys):
        raise ValueError('A consistent, finite, nonnegative budget and unit are required.')
    if budget['confirmed_spend'] + budget['in_flight_reserved'] + budget['this_task_maximum'] > budget['limit']:
        raise ValueError('Budget cap exceeded.')


def read_workflow_state():
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/workflow_state.py'), 'check'], capture_output=True, text=True, cwd=ROOT, timeout=55)
    response = json.loads(result.stdout)
    if result.returncode or response.get('ok') is False:
        raise ValueError('Live workflow node could not be verified; reread the project before submitting.')
    return response


def require_workflow_node(data):
    bindings = load(ROOT / 'workflow/state_bindings.json')['bindings']
    matches = [b for b in bindings if b['family'] == 'a' and b.get('project_id') == data['project_id'] and b.get('version') == data['story_version']]
    if len(matches) != 1:
        raise ValueError('Register a unique project/version workflow binding before submitting.')
    result = read_workflow_state()
    if result['conflicts'] or result['writes']:
        raise ValueError('Reconcile changed workflow nodes before submitting.')
    item = next((i for i in result['items'] if i['id'] == matches[0]['id']), None)
    if not item or item['current_node_id'] != 'A12':
        raise ValueError('Current project node must be 12 正式生成 before submitting.')
    nodes = load(ROOT / 'workflow/stages.json')['families']['a']
    upstream = {n['label'] for n in nodes if n['order'] < 12}
    if upstream.intersection(item.get('revalidation_required', [])):
        raise ValueError('Upstream rollback checks remain unresolved; refresh the actual artifacts and approvals.')
    return {'observed_at': result['observed_at'], 'id': item['id'], 'current_node': item['current_node'], 'gate_pass_inferred': False}


def read_rule_release():
    response = subprocess.run([sys.executable, str(ROOT / 'scripts/workflow_rules.py'), 'check'], capture_output=True, text=True, cwd=ROOT, timeout=55)
    if response.returncode:
        raise ValueError('Current Feishu rule release could not be verified; do not submit from a stale cache.')
    result = json.loads(response.stdout)
    if not result.get('ok') or not result.get('live_center_verified'):
        raise ValueError('A live Feishu rule release is required for submission.')
    return result


def submit(data, authorization_ticket=None):
    path=state_path(data)
    if path.exists():raise ValueError('This run already has a submission record; query or reconcile it instead of resubmitting.')
    rules_check=read_rule_release();health=doctor();paid_checks(data,health);workflow_check=require_workflow_node(data);prepared=preview(data)
    job_sha=digest(data);scope='paid-generation:'+data['project_id']+':'+data['story_version']+':'+data['segment']
    with runtime.mutation('paid_generation',scope,authorization_ticket=authorization_ticket,input_sha256=job_sha):
        state={'run_id':data['run_id'],'project_id':data['project_id'],'a_product_id':data['a_product_id'],'story_version':data['story_version'],'segment':data['segment'],'model':data['model'],'project_console_url':data['project_console_url'],'phase':'SUBMISSION_PENDING','prepared':prepared,'job':data,'health':health,'workflow_node_check':workflow_check,'rules_check':rules_check,'maximum_reserved':data['budget']['this_task_maximum'],'created_at':now()}
        path.parent.mkdir(parents=True,exist_ok=True);slot=path.parent.parent/'.slots'/(digest([data['project_id'],data['story_version'],data['segment']])+'.json');slot.parent.mkdir(parents=True,exist_ok=True)
        if slot.exists():raise ValueError('This project/version/segment has already been claimed; recover its original task instead of using a new run ID.')
        with slot.open('x') as f:json.dump({'run_id':data['run_id'],'state':str(path),'created_at':now()},f)
        with path.open('x') as f:json.dump(state,f,ensure_ascii=False,indent=2)
        try:
            response=mmx(generate_args(data));task=response.get('taskId') or response.get('task_id')
            if not task:raise ValueError('No real task identifier returned.')
            state.update(phase='SUBMITTED',task_id=str(task),submitted_at=now(),response=scrub(response));runtime.event('paid_generation','accepted',scope,input_sha256=job_sha,task_id=str(task),maximum_reserved=state['maximum_reserved'])
        except Exception as exc:
            state.update(phase='SUBMISSION_UNKNOWN',error='Acceptance or charge is unknown. Preserve reservation; never replay this submission.');save(path,state);runtime.record_failure('paid_generation',scope,'submission_unknown',type(exc).__name__+':'+str(exc));raise
        save(path,state);return state


def query(path):
    state = load(path)
    for key in ['run_id', 'project_id', 'story_version', 'segment']:
        if not re.fullmatch(r'[A-Za-z0-9_\-]{1,100}', state.get(key, '')):
            raise ValueError('Invalid task receipt identity.')
    if not state.get('task_id'):
        raise ValueError('No known task; unknown acceptance requires account-side reconciliation.')
    args = ['video', 'task', 'get', '--task-id', state['task_id']]
    if state['model'] == 'MiniMax-H3':
        args += ['--model', 'MiniMax-H3']
    response = mmx(args, quiet=False)
    if str(response.get('task_id')) != state['task_id']:
        raise ValueError('Task response does not match the recorded task.')
    status = response.get('status')
    state.update(task_status=status, last_query=scrub(response), queried_at=now())
    if status in BAD:
        state['phase'] = 'GENERATION_FAILED'
    elif status in GOOD and state.get('phase') != 'MEDIA_DOWNLOADED':
        state['phase'] = 'GENERATION_SUCCEEDED'
    save(path, state)
    return state


def collect(path):
    state = query(path)
    if state['task_status'] not in GOOD:
        raise ValueError('Task is not successful; no download or new submission was attempted.')
    folder = ROOT / load(CONFIG)['output_directory'] / state['run_id']
    target = folder / (state['project_id'] + '_' + state['story_version'] + '_' + state['segment'] + '_RAW.mp4')
    if target.exists():
        if state.get('media', {}).get('sha256') == hashlib.sha256(target.read_bytes()).hexdigest():
            return state
        raise ValueError('Output exists without a matching receipt; preserve it for reconciliation.')
    folder.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.part')
    if temp.exists():
        raise ValueError('Partial output exists; preserve it and reconcile the previous download first.')
    result = state['last_query']
    if state['model'] == 'MiniMax-H3':
        url = result.get('url', '')
        if not url.startswith('https://'):
            raise ValueError('H3 returned no HTTPS output URL.')
        with urllib.request.urlopen(url, timeout=45) as source, temp.open('xb') as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
    else:
        if not result.get('file_id'):
            raise ValueError('Successful legacy task returned no file ID.')
        mmx(['video', 'download', '--file-id', str(result['file_id']), '--out', str(temp)], quiet=False)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(temp)], capture_output=True, text=True, timeout=45)
    decode = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(temp), '-f', 'null', '-'], capture_output=True, text=True, timeout=55)
    info = json.loads(probe.stdout) if probe.returncode == 0 else {}
    if probe.returncode or decode.returncode or not any(s.get('codec_type') == 'video' for s in info.get('streams', [])):
        raise ValueError('Media inspection failed; preserve partial media and do not advance to editing.')
    temp.rename(target)
    media = {'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'bytes': target.stat().st_size, 'ffprobe': info, 'full_decode_passed': True, 'content_qa': 'PENDING', 'user_adoption': 'PENDING', 'actual_cost': None}
    state.update(phase='MEDIA_DOWNLOADED', media=media, downloaded_at=now())
    save(path, state)
    save(folder / 'raw_inputs.json', {'project_id': state['project_id'], 'a_product_id': state['a_product_id'], 'story_version': state['story_version'], 'segment': state['segment'], 'ai': '海螺AI（MiniMax）', 'model': state['model'], 'task_id': state['task_id'], 'raw_media': media, 'console_url': state['project_console_url'], 'generation_receipt': str(Path(path).resolve()), 'ready_for_content_review': True, 'content_adopted': False, 'replace_existing_premiere_media': False})
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['configure-account', 'doctor', 'preview', 'submit', 'query', 'collect']:
        cmd = sub.add_parser(name)
        if name in {'preview', 'submit'}:
            cmd.add_argument('--job', required=True)
        if name == 'submit':
            cmd.add_argument('--authorization-ticket', required=True)
        if name in {'query', 'collect'}:
            cmd.add_argument('--state', required=True)
        cmd.add_argument('--receipt')
    args = parser.parse_args()
    if args.command == 'configure-account':
        result = configure_account()
    elif args.command == 'doctor':
        result = doctor()
    elif args.command in {'preview', 'submit'}:
        data = job(args.job)
        result = preview(data) if args.command == 'preview' else submit(data,args.authorization_ticket)
    else:
        result = query(args.state) if args.command == 'query' else collect(args.state)
    if args.receipt:
        save(args.receipt, scrub(result))
    print(json.dumps(scrub(result), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
