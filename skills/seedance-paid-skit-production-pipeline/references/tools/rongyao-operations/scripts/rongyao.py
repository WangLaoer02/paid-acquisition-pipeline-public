#!/usr/bin/env python3
"""荣耀操作 CLI: existing auth, read-only search, finished-video plans and receipts."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parent
SKILLS = ROOT.parent.parent
STACK = SKILLS / 'rongyao-data-stack/scripts'
KEYRING = SKILLS / 'rongyao-keyring/scripts/keyring.py'
STATE = Path.home() / '.codex/state/rongyao-operations'
FIELDS = {'category_type', 'ai_source', 'origin_type', 'demand_name', 'source_ip',
          'source_type', 'source_direction', 'gid', 'role', 'region_type', 'is_redbag'}
MULTI = {'source_ip', 'source_type', 'source_direction', 'role'}
PENDING = {'preparing', 'selection_pending', 'submitted_pending', 'submission_unknown'}
UPLOAD_SCOPE = 'material-upload:rongyao-operations'
RELEASE_SOURCE = 'implementation/rongyao-tools/skills/rongyao-operations/scripts/rongyao.py'

def load_runtime(workspace):
    if not workspace:
        raise ValueError('WORKSPACE_REQUIRED')
    root = Path(workspace).expanduser()
    if not root.is_absolute() or not (root/'scripts/workflow_runtime.py').is_file():
        raise ValueError('WORKSPACE_RUNTIME_REQUIRED')
    root = root.resolve()
    manifest = read(root/'workflow/rules/manifest.json')
    if manifest.get('implementation_files', {}).get(RELEASE_SOURCE) != sha256(Path(__file__)):
        raise ValueError('UPLOAD_CLI_RELEASE_MISMATCH')
    spec = importlib.util.spec_from_file_location('rongyao_pipeline_runtime', root/'scripts/workflow_runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    return runtime

def registered_plan(jid, state=STATE):
    """Read an existing plan without creating or altering its SQLite ledger."""
    db_path = Path(state)/'jobs.sqlite3'
    if not db_path.is_file():
        raise ValueError('JOB_NOT_FOUND')
    with sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro', uri=True) as db:
        row = db.execute('SELECT plan FROM jobs WHERE id=?', (jid,)).fetchone()
    if not row:
        raise ValueError('JOB_NOT_FOUND')
    return json.loads(row[0])

def plan_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def reviewed_plan(path, state=STATE):
    supplied = read(path)
    stored = registered_plan(supplied['job_id'], state)
    if supplied != stored:
        raise ValueError('PLAN_WAS_EDITED_CREATE_NEW_PLAN')
    for item in stored['items']:
        file = Path(item['file'])
        if not file.is_file() or sha256(file) != item['sha256']:
            raise ValueError('PLAN_FILE_CHANGED')
    return stored

def inspect_plan(path, workspace, state=STATE):
    runtime = load_runtime(workspace)
    plan_value = reviewed_plan(path, state)
    if 'native_execution' in plan_value:
        sys.path.insert(0,str(Path(workspace).resolve()/'scripts'))
        from native_upload_guard import verify_execution
        verify_execution(workspace, plan_value['native_execution'])
    return {'ok':True, 'job_id':plan_value['job_id'], 'scope':UPLOAD_SCOPE,
            'release_id':runtime.policy()['release_id'], 'input_sha256':plan_digest(plan_value),
            'test_only':plan_value.get('test_only') is True, 'upload_performed':False,
            'authorization_granted':False, 'live_release_verified':False,'transport':'native_accessibility' if 'native_execution' in plan_value else 'official_page_cdp'}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('x', encoding='utf-8') as f:
        os.chmod(tmp, 0o600)
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')
    tmp.replace(path)

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def params(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('ALL_FORM_FIELDS_REQUIRED')
    out = {}
    for k, v in value.items():
        if k in MULTI:
            if not isinstance(v, list) or any(not isinstance(x, str) or not x for x in v):
                raise ValueError('INVALID_MULTI_FIELD:' + k)
            out[k] = sorted(set(v))
        else:
            if not isinstance(v, str):
                raise ValueError('INVALID_STRING_FIELD:' + k)
            out[k] = v
    for k in ('category_type', 'origin_type', 'demand_name', 'gid', 'is_redbag'):
        if not out[k]:
            raise ValueError('EMPTY_REQUIRED_FIELD:' + k)
    if out['gid'] == '193' and not out['role']:
        raise ValueError('MAIN_ROLE_REQUIRED_FOR_193')
    return out

def filename(value):
    if not isinstance(value, str) or not value.endswith('.mp4') or value != value.strip() or len(value) > 240:
        raise ValueError('EXPLICIT_MP4_FILENAME_REQUIRED')
    if re.search(r'[\\/\x00-\x1f:*?"<>|]', value) or value in {'.mp4', '..mp4'}:
        raise ValueError('INVALID_FILENAME')
    return value

def production_number(name):
    """Only interpret the established leading number; never guess identity suffixes."""
    match = re.match(r'^(\d{6}[A-Z]+[1-9]\d*)-', name)
    return match[1] if match else None

def inherited_parameters(request, item, ledger):
    """Explicit item > explicit batch > identified registered source > fallback."""
    inherited, provenance = {}, {}
    source = item.get('inherit_from')
    if source is not None:
        if not isinstance(source, dict) or set(source) != {'job_id', 'filename'}:
            raise ValueError('INVALID_PARAMETER_SOURCE')
        prior = ledger.job(source['job_id'])
        matches = [i for i in prior['items'] if i['filename'] == source['filename']]
        if len(matches) != 1:
            raise ValueError('PARAMETER_SOURCE_NOT_UNIQUE')
        inherited = matches[0]['parameters']
        provenance = dict(matches[0].get('provenance') or {})
        provenance['inherited_from'] = {**source, 'plan_sha256': plan_digest(prior)}
    provenance.update(request.get('shared_provenance') or {})
    provenance.update(item.get('provenance') or {})
    values = {**inherited, **request.get('shared_parameters', {}), **item.get('parameters', {})}
    values.setdefault('demand_name', '原创')
    if values['demand_name'] != '原创':
        provenance.pop('requester_explicit_original_override', None)
    return params(values), provenance

def command_json(cmd, timeout=100):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'status': 'TOOL_TIMEOUT', 'auto_retry': False}
    try:
        r = json.loads(p.stdout)
        if not isinstance(r, dict):
            raise ValueError()
        return r
    except ValueError:
        return {'ok': False, 'status': 'INVALID_TOOL_OUTPUT', 'auto_retry': False}

def auth():
    return command_json([sys.executable, str(KEYRING), 'ensure-query'], 110)

def block_status(state=STATE):
    p = state / 'upload-block.json'
    if p.exists():
        b = read(p)
        return {'ok': False, 'status': b['status'], 'authenticated': None,
                'error_code': b.get('error_code'), 'observed_at': b.get('observed_at'),
                'cause': b.get('cause'), 'native_user_action_required': b.get('native_user_action_required', False),
                'target_id': b.get('target_id'),
                'access_state': 'blocked_on_last_observation', 'live_check_performed': False,
                'automatic_retry': False, 'upload_performed': False,
                'next_step': 'Last observation only. Explicit one-time recheck: auth recheck --service video-list.'}
    return None

def transport(action, payload, state=STATE, authorize=None, *, explicit_recheck=False):
    if explicit_recheck and action != 'probe-list':
        raise ValueError('RECHECK_IS_READ_ONLY')
    blocked = block_status(state)
    if blocked and not explicit_recheck:
        return blocked
    ready = command_json([sys.executable, str(KEYRING), 'verify-upload-chrome'])
    if not ready.get('ok'):
        return ready
    sys.path.insert(0, str(STACK))
    import active_session_cli
    # Payload travels through a private file, never through argv; no cookies or tokens.
    fp = state / ('request-' + uuid.uuid4().hex + '.json')
    save(fp, payload)
    proc = None
    timer = None
    try:
        proc = subprocess.Popen([str(active_session_cli.node_bin()), str(ROOT/'upload_bridge.mjs'),
                                 action, str(active_session_cli.DEFAULT_STATE), str(fp)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1)
        timer = threading.Timer(150, proc.kill)
        timer.daemon = True
        timer.start()
        result = None
        # Handshake commits the uncertain-selection checkpoint before Chrome receives files.
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('event') == 'before_file_selection':
                if not authorize:
                    proc.stdin.write('STOP\n')
                else:
                    authorize()
                    proc.stdin.write('SELECT\n')
                proc.stdin.flush()
            elif event.get('event') == 'result':
                result = event['result']
                break
        proc.stdin.close()
        proc.wait(timeout=10)
        result = result or {'ok': False, 'status': 'TRANSPORT_INTERRUPTED', 'auto_retry': False}
        if result.get('status') in {'UPLOAD_CLIENT_BLOCKED', 'BROWSER_HTTP_CONFIRMATION_REQUIRED'}:
            save(state/'upload-block.json', {'status': result['status'], 'error_code': result.get('error_code'),
                 'observed_at': now(), 'surface': 'existing_dedicated_chrome',
                 'entry': result.get('entry', action),
                 'cause': result.get('cause'), 'native_user_action_required': result.get('native_user_action_required', False),
                 'target_id': result.get('target_id'),
                 'automatic_retry': False, 'upload_performed': False})
        return result
    finally:
        if timer:
            timer.cancel()
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc:
            for stream in (proc.stdin, proc.stdout):
                if stream:
                    stream.close()
        fp.unlink(missing_ok=True)

def recheck_video_list(state=STATE, probe=None):
    """One explicitly requested read-only probe; never erase evidence before success."""
    marker = state / 'upload-block.json'
    previous = read(marker) if marker.exists() else None
    attempt = now()
    archive = state / 'access-history' / (uuid.uuid4().hex + '.json')
    save(archive, {'attempted_at': attempt, 'previous_block': previous,
                   'entry': 'video-list', 'status': 'RECHECK_STARTED'})
    try:
        result = (probe or transport)('probe-list', {}, state, explicit_recheck=True)
    except Exception:
        save(archive, {'attempted_at': attempt, 'previous_block': previous,
                       'entry': 'video-list', 'status': 'RECHECK_TOOL_FAILED'})
        raise
    verified = (result.get('ok') is True and result.get('authenticated') is True
                and result.get('source') == 'live_official_video_list'
                and result.get('entry') == 'video-list')
    if result.get('ok') is True and not verified:
        result = {**result, 'ok': False, 'status': 'VIDEO_LIST_UNVERIFIED'}
    cleared = False
    if verified and marker.exists():
        # Do not clear a newer block written by a concurrent operation.
        if read(marker) != previous:
            result = {'ok': False, 'status': 'BLOCK_RECORD_CHANGED',
                      'authenticated': True, 'entry': 'video-list'}
        else:
            marker.unlink()
            cleared = True
    save(archive, {'attempted_at': attempt, 'previous_block': previous,
                   'entry': 'video-list', 'result': result, 'block_cleared': cleared})
    return {**result, 'history_file': str(archive), 'block_cleared': cleared,
            'automatic_retry': False, 'upload_performed': False}

def media(path):
    ffprobe = shutil.which('ffprobe') or str(Path.home()/'.local/bin/ffprobe')
    ffmpeg = shutil.which('ffmpeg') or str(Path.home()/'.local/bin/ffmpeg')
    p = subprocess.run([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                       capture_output=True, text=True, timeout=30)
    if p.returncode:
        raise ValueError('MEDIA_PROBE_FAILED')
    info = json.loads(p.stdout)
    video = [s for s in info['streams'] if s.get('codec_type') == 'video']
    audio = [s for s in info['streams'] if s.get('codec_type') == 'audio']
    if not video or not audio or video[0].get('codec_name') != 'h264' or audio[0].get('codec_name') != 'aac':
        raise ValueError('H264_AAC_MP4_REQUIRED')
    r = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
                        '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                       capture_output=True, timeout=600)
    if r.returncode or r.stderr.strip():
        raise ValueError('FULL_DECODE_FAILED')
    return {'bytes': path.stat().st_size, 'duration_seconds': float(info['format']['duration']),
            'width': video[0]['width'], 'height': video[0]['height'],
            'video_codec': 'h264', 'audio_codec': 'aac', 'full_decode_passed': True}

class Ledger:
    def __init__(self, state=STATE):
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(state/'jobs.sqlite3', timeout=10)
        os.chmod(state/'jobs.sqlite3', 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, plan TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS files(name TEXT PRIMARY KEY, sha TEXT NOT NULL, owner TEXT NOT NULL,
          state TEXT NOT NULL, record_id TEXT, updated TEXT NOT NULL, evidence TEXT);''')
    def create(self, plan):
        with self.db:
            self.db.execute('INSERT INTO jobs VALUES(?,?,?)', (plan['job_id'], json.dumps(plan, ensure_ascii=False), now()))
    def job(self, jid):
        r = self.db.execute('SELECT plan FROM jobs WHERE id=?', (jid,)).fetchone()
        if not r:
            raise ValueError('JOB_NOT_FOUND')
        return json.loads(r['plan'])
    def existing(self, name):
        r = self.db.execute('SELECT * FROM files WHERE name=?', (name,)).fetchone()
        return dict(r) if r else None
    def same_parameters(self, old, item):
        prior = self.job(old['owner'])
        match = next((i for i in prior['items'] if i['filename']==item['filename']), None)
        return bool(match and match['parameters']==item['parameters'])
    def check_content_and_number(self, item):
        # Called inside claim's BEGIN IMMEDIATE as well as during preparation.
        # A proven pre-send rejection may be corrected; unknown acceptance may not.
        rows = self.db.execute('SELECT * FROM files WHERE name!=?', (item['filename'],)).fetchall()
        number = production_number(item['filename'])
        for row in rows:
            if row['state'] == 'blocked_before_selection':
                continue
            if row['sha'] == item['sha256']:
                raise ValueError('SAME_FILE_OTHER_NAME_HELD')
            if number and production_number(row['name']) == number:
                raise ValueError('PRODUCTION_NUMBER_HELD')
    def claim(self, jid, item):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.check_content_and_number(item)
            old = self.existing(item['filename'])
            if old:
                if old['sha'] != item['sha256']:
                    raise ValueError('SAME_NAME_DIFFERENT_SHA')
                if old['state'] != 'blocked_before_selection' and not self.same_parameters(old, item):
                    raise ValueError('SAME_FILE_DIFFERENT_PARAMETERS')
                if old['state'] == 'listed' and old['record_id']:
                    self.db.commit()
                    return old
                if old['state'] not in {'blocked_before_selection'}:
                    raise ValueError('PRIOR_SUBMISSION_NEEDS_RECONCILIATION')
            self.db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)',
                            (item['filename'], item['sha256'], jid, 'preparing', None, now(), None))
            self.db.commit()
            return None
        except Exception:
            self.db.rollback()
            raise
    def update(self, jid, name, state, record_id=None, evidence=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.existing(name)
            if old and old['owner'] == jid and old['state'] == 'listed' and state != 'listed':
                return  # A late worker reply must not erase a reconciled record ID.
            cur = self.db.execute('UPDATE files SET state=?,record_id=?,updated=?,evidence=? WHERE name=? AND owner=?',
              (state, str(record_id) if record_id else None, now(), json.dumps(evidence, ensure_ascii=False), name, jid))
            if cur.rowcount != 1:
                raise ValueError('JOB_DOES_NOT_OWN_RESERVATION')
    def status(self, jid):
        p = self.job(jid)
        rows = []
        for i in p['items']:
            current = self.existing(i['filename'])
            if current and current['sha'] == i['sha256'] and self.same_parameters(current, i):
                rows.append({k:current[k] for k in ('name', 'state', 'record_id', 'owner', 'updated')})
            else:
                rows.append({'name':i['filename'], 'state':'planned', 'record_id':None})
        return {'ok':True, 'job_id':jid, 'files':rows,
                'all_listed':bool(rows) and all(x['state']=='listed' for x in rows),
                'remote_playback_verified':False, 'metadata_verified':False}

def plan(manifest, output, copy_dir=None, state=STATE, *, native_execution=None):
    request = read(manifest)
    source_plan = None
    if request.get('scope') == 'local_preparation_only':
        if request.get('can_proceed_to_ui') is not True or request.get('blocked'):
            raise ValueError('LEGACY_PREPARATION_NOT_READY')
        source_plan = {'file':str(Path(manifest).resolve()), 'sha256':sha256(manifest)}
        pending = [i for i in request.get('items', []) if i.get('state') == 'ready_for_ui']
        if not pending:
            return {'ok':True, 'status':'NO_PENDING_LEGACY_FILES', 'upload_performed':False}
        request = {'test_only': request.get('test_only') is True,
                   'shared_provenance': request.get('shared_provenance') or {},
                   'items':[{'file':i['upload_file'], 'filename':i['filename'], 'expected_sha256':i['sha256'],
                    'parameters':i['form_values'], 'review':i.get('quality_review'),
                    'inherit_from':i.get('inherit_from'),
                    'provenance':{'source':'existing_ab_preparation', **(i.get('provenance') or {}),
                                  'b_source':i.get('b_source')}} for i in pending]}
    raw = request.get('items')
    if not isinstance(raw, list) or not raw:
        raise ValueError('NONEMPTY_ITEMS_REQUIRED')
    if native_execution is not None and any((i.get('provenance') or {}).get('parameter_encoding') != 'visible_ui_labels_only_native_adapter' for i in raw):
        raise ValueError('NATIVE_VISIBLE_PARAMETER_ENCODING_REQUIRED')
    staged, names, hashes, numbers = [], set(), set(), set()
    ledger = Ledger(state)
    for i in raw:
        p = Path(i.get('file', '')).expanduser()
        if not p.is_absolute() or not p.is_file() or p.suffix.lower() != '.mp4':
            raise ValueError('EXISTING_ABSOLUTE_MP4_REQUIRED')
        p = p.resolve()
        name = filename(i.get('filename', p.name))
        if name in names:
            raise ValueError('DUPLICATE_FILENAME_IN_BATCH')
        names.add(name)
        values, provenance = inherited_parameters(request, i, ledger)
        before = sha256(p)
        if i.get('expected_sha256') and i['expected_sha256'] != before:
            raise ValueError('LEGACY_PLAN_FILE_CHANGED')
        if before in hashes:
            raise ValueError('DUPLICATE_CONTENT_IN_BATCH')
        hashes.add(before)
        number = production_number(name)
        if number and number in numbers:
            raise ValueError('DUPLICATE_PRODUCTION_NUMBER_IN_BATCH')
        if number:
            numbers.add(number)
        ledger.check_content_and_number({'filename':name, 'sha256':before})
        technical = media(p)
        if sha256(p) != before:
            raise ValueError('FILE_CHANGED_DURING_VALIDATION')
        dst = Path(copy_dir).expanduser()/name if copy_dir else p
        if not dst.is_absolute():
            raise ValueError('ABSOLUTE_COPY_DIR_REQUIRED')
        if not copy_dir and p.name != name:
            raise ValueError('USE_COPY_DIR_FOR_EXPLICIT_RENAMING')
        if dst.exists() and sha256(dst) != before:
            raise ValueError('DESTINATION_CONTENT_CONFLICT')
        old = ledger.existing(name)
        if old and old['sha'] != before:
            raise ValueError('SAME_NAME_DIFFERENT_SHA')
        if old and old['state'] in PENDING:
            raise ValueError('PRIOR_SUBMISSION_NEEDS_RECONCILIATION')
        staged.append({'file':str(dst), 'source_file':str(p), 'filename':name, 'sha256':before,
                       'parameters':values, 'media':technical,
                       'review':i.get('review'), 'provenance':provenance})
    # Validate every file before creating any naming copies.
    for i in staged:
        dst = Path(i['file'])
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            with Path(i['source_file']).open('rb') as src, dst.open('xb') as target:
                shutil.copyfileobj(src, target)
            if sha256(dst) != i['sha256']:
                raise ValueError('COPY_HASH_MISMATCH')
    groups = {}
    for i in staged:
        key = json.dumps(i['parameters'], sort_keys=True, ensure_ascii=False)
        groups.setdefault(key, {'parameters':i['parameters'], 'files':[]})['files'].append(i['filename'])
    result = {'ok':True, 'schema_version':1, 'job_id':uuid.uuid4().hex, 'created_at':now(),
              'test_only':request.get('test_only') is True,
              'source_plan':source_plan,
              'items':staged, 'batches':list(groups.values()), 'upload_performed':False,
              'remote_fields_verified':False, 'backend_duplicate_check_performed':False,
              'visual_review_verified':False}
    if native_execution is not None:
        result["native_execution"] = native_execution
    ledger.create(result)
    save(output, result)
    return {'ok':True, 'status':'PLAN_CREATED', 'job_id':result['job_id'], 'plan':str(output),
            'files':len(staged), 'batches':len(groups), 'upload_performed':False,
            'upload_transport':block_status(state) or {'status':'UNVERIFIED'}}

def upload(jid, state=STATE, *, workspace=None, authorization_ticket=None, exported_plan=None):
    """The public submission interface always uses the existing pipeline guard."""
    if not authorization_ticket:
        raise ValueError('AUTHORIZATION_TICKET_REQUIRED')
    runtime = load_runtime(workspace)
    runtime.ensure_writer('material_upload')
    value = reviewed_plan(exported_plan, state) if exported_plan else registered_plan(jid, state)
    if 'native_execution' in value:raise ValueError('NATIVE_PLAN_REQUIRES_PINNED_NATIVE_CONTROLLER')
    if value['job_id'] != jid:
        raise ValueError('PLAN_JOB_MISMATCH')
    if value.get('test_only'):
        return {'ok':False, 'status':'OFFLINE_TEST_PLAN_CANNOT_UPLOAD', 'job_id':jid, 'upload_performed':False}
    for item in value['items']:
        if not Path(item['file']).is_file() or sha256(item['file']) != item['sha256']:
            raise ValueError('PLAN_FILE_CHANGED')
    digest = plan_digest(value)
    with runtime.mutation('material_upload', UPLOAD_SCOPE,
                          authorization_ticket=authorization_ticket, input_sha256=digest):
        # A changed registry after preflight cannot silently change ticket scope.
        if registered_plan(jid, state) != value:
            raise ValueError('REGISTERED_PLAN_CHANGED')
        try:
            result = _upload_registered(jid, state)
        except Exception as exc:
            runtime.record_failure('material_upload',UPLOAD_SCOPE,'upload_transport',type(exc).__name__)
            raise
        runtime.event('material_upload','result',UPLOAD_SCOPE,job_id=jid,
                      input_sha256=digest,ok=result.get('ok'),listed_verified=result.get('listed_verified',False))
        if not result.get('ok'):
            runtime.record_failure('material_upload',UPLOAD_SCOPE,'upload_transport','UPLOAD_RESULT_NOT_OK')
        return result

def _upload_registered(jid, state=STATE):
    ledger = Ledger(state)
    p = ledger.job(jid)
    if 'native_execution' in p:raise ValueError('NATIVE_PLAN_REQUIRES_PINNED_NATIVE_CONTROLLER')
    if p.get('test_only'):
        return {'ok':False, 'status':'OFFLINE_TEST_PLAN_CANNOT_UPLOAD', 'job_id':jid, 'upload_performed':False}
    # Validate all files again before any external side effect.
    for i in p['items']:
        if not Path(i['file']).is_file() or sha256(i['file']) != i['sha256']:
            raise ValueError('PLAN_FILE_CHANGED')
    blocked = block_status(state)
    if blocked:
        return {**blocked, 'job_id':jid}
    results = []
    for i in p['items']:
        old = ledger.claim(jid, i)
        if old:
            results.append({'filename':i['filename'], 'status':'SKIP_ALREADY_LISTED', 'record_id':old['record_id']})
            continue
        selected = False
        def checkpoint():
            nonlocal selected
            if sha256(i['file']) != i['sha256']:
                raise ValueError('PLAN_FILE_CHANGED')
            ledger.update(jid, i['filename'], 'selection_pending')
            selected = True
        try:
            r = transport('upload', i, state, checkpoint)
        except Exception:
            ledger.update(jid, i['filename'], 'submission_unknown' if selected else 'blocked_before_selection')
            raise
        # Once selection was authorized, *every* failure is uncertain. Never auto-resubmit.
        if selected:
            new_state = 'submitted_pending' if r.get('ok') else 'submission_unknown'
        else:
            new_state = 'blocked_before_selection'
        ledger.update(jid, i['filename'], new_state, evidence=r)
        results.append({'filename':i['filename'], **r})
        if not r.get('ok'):
            break
    return {'ok':all(x.get('ok', x.get('status')=='SKIP_ALREADY_LISTED') for x in results),
            'job_id':jid, 'results':results, 'receipt':ledger.status(jid), 'listed_verified':False}

def reconcile(jid, state=STATE):
    ledger = Ledger(state)
    p = ledger.job(jid)
    results = []
    for i in p['items']:
        old = ledger.existing(i['filename'])
        if not old or old['owner'] != jid or old['sha'] != i['sha256']:
            results.append({'filename':i['filename'], 'status':'NO_OWNED_SUBMISSION'})
            continue
        if old['state'] == 'listed':
            results.append({'filename':i['filename'], 'status':'ALREADY_LISTED'})
            continue
        if old['state'] not in PENDING or old['state'] == 'preparing':
            results.append({'filename':i['filename'], 'status':'NOT_SUBMITTED'})
            continue
        r = transport('list', {'name':i['filename'][:-4]}, state)
        if not r.get('ok'):
            return {**r, 'job_id':jid}
        exact = [x for x in r['rows'] if x['name'] in {i['filename'], i['filename'][:-4]} and x.get('record_id')]
        if len(exact) == 1:
            ledger.update(jid, i['filename'], 'listed', exact[0]['record_id'],
                          {'observed_at':now(), 'source':'live_backend_list', 'row':exact[0]})
            results.append({'filename':i['filename'], 'status':'LISTED', 'record_id':exact[0]['record_id']})
        else:
            results.append({'filename':i['filename'], 'status':'AMBIGUOUS' if exact else 'NOT_LISTED_YET'})
    return {'ok':True, 'job_id':jid, 'results':results, 'receipt':ledger.status(jid), 'upload_performed':False}

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', action='version', version='rongyao 0.2.3')
    groups = p.add_subparsers(dest='group', required=True)
    a = groups.add_parser('auth').add_subparsers(dest='action', required=True)
    x = a.add_parser('ensure'); x.add_argument('--service', choices=['query','upload'], default='query')
    x = a.add_parser('recheck'); x.add_argument('--service', choices=['video-list'], required=True)
    a.add_parser('status')
    v = groups.add_parser('video').add_subparsers(dest='action', required=True)
    s = v.add_parser('search'); s.add_argument('--gid', required=True); s.add_argument('--date-range', required=True)
    s.add_argument('--material-range', required=True); s.add_argument('--keyword', default='')
    s.add_argument('--limit', type=int, default=20); s.add_argument('--refresh', action='store_true')
    for cmd in ('resolve','frames'):
        x = v.add_parser(cmd); x.add_argument('--id', required=True)
        if cmd == 'frames': x.add_argument('--count', type=int, default=8)
    x = v.add_parser('fields'); x.add_argument('--game'); x.add_argument('--source-type', action='append', default=[])
    x = v.add_parser('list'); x.add_argument('--name', required=True)
    x = v.add_parser('plan'); x.add_argument('--manifest', required=True); x.add_argument('--output', required=True)
    x.add_argument('--copy-dir')
    x = v.add_parser('native-plan'); x.add_argument('--manifest',required=True); x.add_argument('--output',required=True); x.add_argument('--workspace',required=True); x.add_argument('--window-title',required=True)
    x = v.add_parser('native-upload'); x.add_argument('--plan',required=True); x.add_argument('--workspace',required=True); x.add_argument('--authorization-ticket',required=True)
    x = v.add_parser('inspect-plan'); x.add_argument('--plan', required=True); x.add_argument('--workspace',required=True)
    x = v.add_parser('upload'); x.add_argument('--plan', required=True)
    x.add_argument('--workspace',required=True);x.add_argument('--authorization-ticket',required=True)
    j = groups.add_parser('job').add_subparsers(dest='action', required=True)
    for cmd in ('status','reconcile'):
        x = j.add_parser(cmd); x.add_argument('job_id')
    groups.add_parser('doctor')
    return p

def main():
    a = parser().parse_args()
    if a.group == 'doctor':
        return {'ok':True, 'health':'degraded' if block_status() else 'unverified', 'version':'0.2.3', 'query':'existing_keyring',
                'upload_transport':block_status() or {'status':'UNVERIFIED'},
                'credentials_embedded':False, 'automatic_retry':False}
    if a.group == 'auth':
        if a.action == 'status':
            return {'ok':True, 'keyring':command_json([sys.executable, str(KEYRING), 'status']),
                    'upload_transport':block_status() or {'status':'UNVERIFIED'}}
        if a.action == 'recheck':
            return recheck_video_list()
        return transport('fields', {}) if a.service == 'upload' else auth()
    if a.group == 'job':
        return Ledger().status(a.job_id) if a.action == 'status' else reconcile(a.job_id)
    if a.action in {'search','resolve','frames'}:
        cmd = [sys.executable, str(KEYRING), 'fast-video', a.action]
        for k,v in vars(a).items():
            if k in {'group','action'} or v is False: continue
            cmd.append('--'+k.replace('_','-'))
            if v is not True: cmd.append(str(v))
        return command_json(cmd, 210)
    if a.action == 'fields':
        return transport('fields', {'gid':a.game, 'source_type':a.source_type})
    if a.action == 'list':
        return transport('list', {'name':a.name})
    if a.action == 'plan':
        output = Path(a.output).expanduser()
        if not output.is_absolute(): raise ValueError('ABSOLUTE_OUTPUT_REQUIRED')
        return plan(a.manifest, output, a.copy_dir)
    if a.action in {'native-plan','native-upload'}:
        root = Path(a.workspace).resolve()
        runtime = load_runtime(root)
        # Resolve only the current published workspace; never a project-local adapter.
        sys.path.insert(0, str(root/'scripts'))
        from native_upload_guard import execution_descriptor, verify_execution
        runtime.ensure_release(True)
        if a.action == 'native-plan':
            output = Path(a.output)
            if not output.is_absolute(): raise ValueError('ABSOLUTE_OUTPUT_REQUIRED')
            descriptor = execution_descriptor(root,root/'workflow/tools/native-upload/native-ui',a.window_title)
            return plan(a.manifest,output,native_execution=descriptor)
        from native_upload_controller import run
        run(a.plan,a.authorization_ticket)
        return {'ok':True,'status':'NATIVE_CONTROLLER_ENDED','backend_success_inferred':False}
    if a.action == 'inspect-plan':
        return inspect_plan(a.plan,a.workspace)
    if a.action == 'upload':
        # Writer check precedes reading business input; mutation rechecks before selection.
        runtime=load_runtime(a.workspace);runtime.ensure_writer('material_upload')
        workspace=Path(a.workspace).resolve()
        published=workspace/'workflow/rules'/RELEASE_SOURCE
        if Path(__file__).resolve()!=published.resolve():
            wrapper=workspace/'scripts/rongyao.py'
            expected=read(workspace/'workflow/rules/manifest.json').get('workspace_contract_files',{}).get('scripts/rongyao.py')
            if not expected or not wrapper.is_file() or sha256(wrapper)!=expected:
                raise ValueError('REGISTERED_UPLOAD_WRAPPER_CHANGED')
            # Replace this process before any file selection; the pinned caller
            # then enters the existing guard, with the same plan and ledger.
            os.execv(sys.executable,[sys.executable,str(wrapper),*sys.argv[1:]])
        supplied=read(a.plan)
        return upload(supplied['job_id'],workspace=a.workspace,
                      authorization_ticket=a.authorization_ticket,exported_plan=a.plan)

if __name__ == '__main__':
    try:
        result = main()
    except (ValueError, KeyError, TypeError) as exc:
        # Only code-defined validation errors are emitted; raw media, auth and stderr stay private.
        message = str(exc)
        code = re.match(r'^([A-Z][A-Z0-9_]+)(?::|$)', message)
        result = {'ok':False, 'status':code.group(1) if code else 'INVALID_REQUEST', 'auto_retry':False}
    except Exception as exc:
        result = {'ok':False, 'status':'LOCAL_OR_TOOL_ERROR', 'error_type':type(exc).__name__, 'auto_retry':False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get('ok') else 1)
