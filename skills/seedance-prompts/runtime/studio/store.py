"""Shared local tasks, immutable usage events and explicit Skill runs. No model execution."""
from pathlib import Path
from contextlib import contextmanager
import datetime, hashlib, json, os, sqlite3, uuid
from catalog import catalog

BASE = Path(__file__).resolve().parent
from configuration import DB
TERMINAL = {'completed', 'blocked', 'failed', 'cancelled'}

class StudioError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds')

def encode(value):
    return json.dumps(value, ensure_ascii=False)

@contextmanager
def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id), body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS versions(task_id TEXT NOT NULL REFERENCES tasks(id), revision INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(task_id,revision));
      CREATE TABLE IF NOT EXISTS skill_snapshots(sha256 TEXT PRIMARY KEY, body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS issues(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), body TEXT NOT NULL);
    ''')
    try:
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()

def actor(value):
    if not isinstance(value, dict) or value.get('kind') not in {'human', 'agent', 'system'}:
        raise StudioError('actor.kind must be human, agent or system')
    if not str(value.get('name', '')).strip():
        raise StudioError('actor.name is required')
    return {'kind': value['kind'], 'name': str(value['name'])[:120]}

def load(db, table, key):
    row = db.execute(f'SELECT body FROM {table} WHERE id=?', (key,)).fetchone()
    if not row:
        raise StudioError(f'{table}: item not found', 404)
    return json.loads(row['body'])

def write(db, table, item):
    db.execute(f'UPDATE {table} SET body=? WHERE id=?', (encode(item), item['id']))

def event(db, task_id, kind, who, summary, **extra):
    item = dict(task_id=task_id, type=kind, actor=who, summary=summary, at=now(), **extra)
    cur = db.execute('INSERT INTO events(task_id,body) VALUES (?,?)', (task_id, encode(item)))
    item['seq'] = cur.lastrowid
    return item

def all_rows(db, table, task_id):
    return [json.loads(r['body']) for r in db.execute(f'SELECT body FROM {table} WHERE task_id=? ORDER BY rowid', (task_id,))]

def task_bundle(db, task_id):
    task = load(db, 'tasks', task_id)
    events = []
    for r in db.execute('SELECT seq,body FROM events WHERE task_id=? ORDER BY seq DESC LIMIT 200', (task_id,)):
        item = json.loads(r['body']); item['seq'] = r['seq']; events.append(item)
    versions=[dict(revision=r['revision'],updated_at=json.loads(r['body'])['updated_at']) for r in db.execute('SELECT revision,body FROM versions WHERE task_id=? ORDER BY revision DESC LIMIT 100',(task_id,))]
    return dict(task=task, runs=all_rows(db, 'runs', task_id), events=events, versions=versions)

def workspace():
    with connection() as db:
        tasks = [json.loads(r['body']) for r in db.execute('SELECT body FROM tasks ORDER BY rowid DESC')]
        current = db.execute("SELECT value FROM settings WHERE key='active_task'").fetchone()
        task_id = current['value'] if current else None
        return dict(active_task_id=task_id, tasks=[dict(id=t['id'], title=t['form'].get('title','未命名'), revision=t['revision'], updated_at=t['updated_at']) for t in tasks],
                    current=task_bundle(db, task_id) if task_id else None,
                    sequence=db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0],
                    capabilities={'shared_tasks': True, 'persistent_history': True, 'agent_cli': True, 'automatic_agent_worker': False})

def validate_payload(value):
    if not isinstance(value, dict) or not isinstance(value.get('form'), dict):
        raise StudioError('form object is required')
    allowed = {s['slug'] for s in catalog()['skills']}
    selected = value.get('skills', [])
    if not isinstance(selected, list) or not selected or any(s not in allowed for s in selected):
        raise StudioError('skills must contain canonical Seedance names')
    primary = value.get('primary', selected[0])
    if primary not in selected:
        raise StudioError('primary must be a selected skill')
    form = dict(title='未命名任务',source='',style='',keep='',duration='',aspect='16:9',format='natural',stop='prompt',project='')
    form.update({k: str(v) for k,v in value['form'].items() if k in form})
    return dict(form=form, skills=list(dict.fromkeys(selected)), primary=primary,
                draft=str(value.get('draft','')), compiled=bool(value.get('compiled')), dirty=bool(value.get('dirty')), edited=bool(value.get('edited')),
                references=value.get('references', []), positions=value.get('positions', {}))

def create_task(value, who):
    payload = validate_payload(value); who = actor(who); stamp = now()
    item = dict(id='task_'+uuid.uuid4().hex[:12], revision=1, created_at=stamp, updated_at=stamp, **payload)
    with connection() as db:
        db.execute('INSERT INTO tasks VALUES (?,?)', (item['id'], encode(item)))
        db.execute('INSERT INTO versions VALUES (?,?,?)', (item['id'],1,encode(item)))
        db.execute("INSERT OR REPLACE INTO settings VALUES ('active_task',?)", (item['id'],))
        event(db, item['id'], 'task_created', who, '创建共用任务', revision=1)
    return item

def update_task(task_id, value, who, expected_revision, kind='task_saved'):
    payload = validate_payload(value); who = actor(who)
    with connection() as db:
        old = load(db, 'tasks', task_id)
        if old['revision'] != expected_revision:
            raise StudioError('任务已有新版本；保留本地内容，读取并合并后再保存。', 409)
        if all(old.get(k) == v for k,v in payload.items()):
            return old
        item = dict(old, **payload, revision=old['revision']+1, updated_at=now())
        write(db, 'tasks', item)
        db.execute('INSERT INTO versions VALUES (?,?,?)', (task_id,item['revision'],encode(item)))
        event(db, task_id, kind, who, {'draft_prepared':'整理交接草稿（页面规则）','candidate_adopted':'采用使用结果为当前草稿'}.get(kind,'保存任务修改'), revision=item['revision'])
    return item

def activate(task_id, who):
    who = actor(who)
    with connection() as db:
        load(db, 'tasks', task_id)
        db.execute("INSERT OR REPLACE INTO settings VALUES ('active_task',?)", (task_id,))
        event(db, task_id, 'task_opened', who, '打开共用任务')
    return workspace()

def add_note(task_id, who, summary, run_id=None, evidence=None):
    who = actor(who)
    if not str(summary).strip(): raise StudioError('summary is required')
    with connection() as db:
        load(db, 'tasks', task_id)
        if run_id and load(db, 'runs', run_id)['task_id'] != task_id:
            raise StudioError('run belongs to another task')
        return event(db, task_id, 'progress', who, str(summary), run_id=run_id, evidence=evidence or [])

def lock_skill(db, skill):
    key=hashlib.sha256(encode({'sha256':skill['sha256'],'references':sorted((r['path'],r['sha256']) for r in skill['references'])}).encode()).hexdigest()
    db.execute('INSERT OR IGNORE INTO skill_snapshots VALUES (?,?)',(key,encode(skill)))
    return dict(slug=skill['slug'],path=skill['path'],sha256=skill['sha256'],snapshot_id=key)

def start_run(task_id, who, skills=None, queued=False, summary='', request_key=None):
    who = actor(who)
    current_catalog = {s['slug']:s for s in catalog()['skills']}
    with connection() as db:
        task = load(db, 'tasks', task_id)
        if request_key:
            for r in all_rows(db, 'runs', task_id):
                if r.get('request_key') == request_key:
                    return r
        skills = skills or task['skills']
        if not skills or any(s not in current_catalog or not current_catalog[s]['available'] for s in skills):
            raise StudioError('unknown or unavailable skill')
        item = dict(id='run_'+uuid.uuid4().hex[:12], task_id=task_id, status='queued' if queued else 'running',
                    requested_by=who, actor=None if queued else who, created_at=now(), started_at=None if queued else now(),
                    input_revision=task['revision'], input_snapshot=task,
                    skills=[lock_skill(db,current_catalog[s]) for s in skills],
                    summary=summary or ('等待 Agent 领取' if queued else '开始使用 Skill'), output='', evidence=[], request_key=request_key,
                    completion_scope='skill_work_only_not_platform_generation')
        db.execute('INSERT INTO runs VALUES (?,?,?)', (item['id'], task_id, encode(item)))
        event(db, task_id, 'run_queued' if queued else 'run_started', who, item['summary'], run_id=item['id'], skills=item['skills'])
    return item

def claim_run(run_id, who):
    who = actor(who)
    with connection() as db:
        item = load(db, 'runs', run_id)
        if item['status'] != 'queued': raise StudioError('使用记录已被领取或结束，请读取当前状态。', 409)
        item.update(status='running', actor=who, started_at=now(), summary='已领取，正在使用 Skill')
        write(db, 'runs', item)
        event(db, item['task_id'], 'run_started', who, item['summary'], run_id=run_id)
    return item

def finish_run(run_id, who, status, summary, output='', evidence=None):
    who = actor(who)
    if status not in TERMINAL or not str(summary).strip(): raise StudioError('terminal status and summary are required')
    if status == 'completed' and not str(output).strip() and not evidence: raise StudioError('completed requires output or evidence')
    with connection() as db:
        item = load(db, 'runs', run_id)
        if item['status'] in TERMINAL: raise StudioError('这条使用记录已结束；修订请新建记录。', 409)
        if status != 'cancelled' and (item['status'] != 'running' or item['actor'] != who):
            raise StudioError('先领取记录，并用原执行者身份提交结果。', 409)
        item.update(status=status, summary=str(summary), output=str(output), evidence=evidence or [], finished_at=now())
        write(db, 'runs', item)
        event(db, item['task_id'], 'run_'+status, who, str(summary), run_id=run_id, evidence=evidence or [])
    return item

def context(task_id, run_id=None):
    with connection() as db:
        bundle = task_bundle(db, task_id)
        run = load(db, 'runs', run_id) if run_id else None
        if run and run['task_id'] != task_id: raise StudioError('run belongs to another task')
        snapshots=[json.loads(db.execute('SELECT body FROM skill_snapshots WHERE sha256=?',(s.get('snapshot_id',s['sha256']),)).fetchone()['body']) for s in run['skills']] if run else None
    selected = [s['slug'] for s in run['skills']] if run else bundle['task']['skills']
    if run and run['status']=='running':
        with connection() as db:
            event(db, task_id, 'context_read', run['actor'], '读取本次 Skill 正文与输入', run_id=run_id,
                  details={'skills':run['skills'],'input_revision':run['input_revision']})
    return dict(**bundle, run=run, input=run['input_snapshot'] if run else bundle['task'],
                skill_instructions=snapshots if run else [s for s in catalog()['skills'] if s['slug'] in selected],
                execution_note='Apply the selected Skills yourself. This store does not execute models or platform operations. Return a candidate; preserve the current human draft.')

def pending():
    with connection() as db:
        return [json.loads(r['body']) for r in db.execute('SELECT body FROM runs ORDER BY rowid') if json.loads(r['body'])['status']=='queued']

def asset_path(asset_id):
    with connection() as db: return load(db, 'assets', asset_id)

def save_asset(task_id, name, mime, stream, length):
    if not mime.startswith(('image/','video/','audio/')): raise StudioError('仅支持图片、视频和音频')
    if length <= 0 or length > 256*1024*1024: raise StudioError('素材大小须在 1 字节到 256 MiB 之间', 413)
    with connection() as db: load(db, 'tasks', task_id)
    folder = DB.parent/'assets'; folder.mkdir(exist_ok=True)
    asset_id = 'asset_'+uuid.uuid4().hex
    path = folder/asset_id; digest=hashlib.sha256(); remaining=length
    try:
        with path.open('xb') as out:
            while remaining:
                chunk=stream.read(min(remaining, 1024*1024))
                if not chunk: raise StudioError('素材上传不完整')
                remaining-=len(chunk); digest.update(chunk); out.write(chunk)
        item=dict(id=asset_id,task_id=task_id,name=Path(name).name[:200],type=mime,size=length,path=str(path),sha256=digest.hexdigest(),url='/api/assets/'+asset_id)
        with connection() as db: db.execute('INSERT INTO assets VALUES (?,?,?)',(asset_id,task_id,encode(item)))
        return item
    except BaseException:
        path.unlink(missing_ok=True)
        raise
