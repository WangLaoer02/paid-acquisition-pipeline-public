"""Persistent native upload action budget and evidence checks. No UI or network calls."""
import hashlib
import json
import re
from pathlib import Path
import sqlite3

class NativeGuardError(ValueError):
    pass

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

EXECUTION_FILES = ('scripts/native_upload_controller.py', 'scripts/native_upload_guard.py',
                   'workflow/tools/native-upload/native-ui.swift')

def execution_descriptor(workspace, binary, window_title):
    root = Path(workspace).resolve()
    binary = Path(binary).resolve()
    if not window_title or not window_title.startswith('adopenplatform.backend.example.invalid/'):
        raise NativeGuardError('EXPLICIT_UPLOAD_WINDOW_REQUIRED')
    if binary != root/'workflow/tools/native-upload/native-ui' or not binary.is_file():
        raise NativeGuardError('PUBLISHED_NATIVE_BINARY_REQUIRED')
    manifest = json.loads((root/'workflow/rules/manifest.json').read_text())
    files = {}
    for name in EXECUTION_FILES:
        value = sha(root/name)
        if manifest['workspace_contract_files'].get(name) != value:
            raise NativeGuardError('NATIVE_SOURCE_NOT_PUBLISHED')
        files[name] = value
    receipt = json.loads((binary.parent/'build.json').read_text())
    if receipt.get('source_sha256') != files[EXECUTION_FILES[-1]] or receipt.get('binary_sha256') != sha(binary):
        raise NativeGuardError('NATIVE_BUILD_RECEIPT_MISMATCH')
    files[str(binary.relative_to(root))] = sha(binary)
    return {'schema_version': 1, 'release_id': manifest['release_id'], 'files': files,
            'window_title': window_title, 'transport': 'native_accessibility',
            'production_validation_inferred': False}

def verify_execution(workspace, descriptor):
    root = Path(workspace).resolve()
    if not isinstance(descriptor, dict):
        raise NativeGuardError('NATIVE_EXECUTION_CONTRACT_REQUIRED')
    wanted = execution_descriptor(root, root/'workflow/tools/native-upload/native-ui',
                                  descriptor.get('window_title'))
    if descriptor != wanted:
        raise NativeGuardError('NATIVE_EXECUTION_CHANGED_CREATE_NEW_PLAN')
    return wanted

def observation(rows, filename, window_title):
    windows = [r for r in rows if r.get('role') == 'AXWindow' and r.get('title') == window_title]
    if len(windows) != 1:
        raise NativeGuardError('NATIVE_WINDOW_NOT_UNIQUE')
    prefix = windows[0]['path'] + '.'
    scoped = [r for r in rows if str(r.get('path', '')).startswith(prefix)]
    inputs = [r for r in scoped if r.get('dom_id') == 'file' and r.get('role') == 'AXButton']
    if len(inputs) != 1:
        raise NativeGuardError('NATIVE_FILE_INPUT_NOT_UNIQUE')
    sheets = [r for r in scoped if r.get('role') == 'AXSheet']
    selected = bool(re.search(r'(?<![\w.\-])' + re.escape(filename) + r'(?![\w.\-])', inputs[0].get('title', '')))
    progress = [str(r.get('value', '')) for r in scoped
                if r.get('role') == 'AXStaticText' and
                re.match(re.escape(filename.removesuffix('.mp4')) + r'(?:\.mp4)?(?:\s|[:：]|$)', str(r.get('value', ''))) and
                any(s in str(r.get('value', '')) for s in ('上传进度', ':成功', '：成功'))]
    paths = sorted(set(str(r.get('value')) for r in scoped if r.get('role') in {'AXTextField','AXComboBox'}
                       and not r.get('dom_id') and str(r.get('value', '')).endswith('.mp4')))
    preview = any(r.get('role') == 'AXStaticText' and r.get('value') == filename
                  and not r.get('actions') for r in scoped)
    value = {'window_title': window_title, 'filename': filename, 'chooser_open': bool(sheets),
             'file_selected': selected, 'file_progress': progress, 'resolved_paths': paths,
             'file_preview': preview}
    value['fingerprint'] = digest(value)
    return value

def submission_state(obs, previous):
    if previous in {'listed', 'submitted_pending'}:
        return previous
    if obs['file_progress'] or (not obs['chooser_open'] and obs['file_selected']):
        return 'submitted_pending'
    if previous == 'submission_unknown':
        return 'submission_unknown'  # No fabricated cause or optimistic downgrade.
    if obs['chooser_open']:
        return 'selection_pending'
    return 'blocked_before_selection'

class ActionJournal:
    """Atomic per-goal budget, persisted across process/interface/window movement."""
    def __init__(self, path):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('CREATE TABLE IF NOT EXISTS actions(k TEXT PRIMARY KEY, failures INTEGER NOT NULL, inflight INTEGER NOT NULL, fingerprint TEXT, error TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS capabilities(k TEXT PRIMARY KEY, reason TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS checkpoints(k TEXT, prior_fingerprint TEXT, new_fingerprint TEXT, approval_ref TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')
    def block_capability(self, window, capability, reason):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO capabilities VALUES(?,?)', (digest([window, capability]), reason))
    def capability(self, window, capability):
        row = self.db.execute('SELECT reason FROM capabilities WHERE k=?', (digest([window, capability]),)).fetchone()
        if row:
            raise NativeGuardError('CAPABILITY_BLOCKED_USER_STATE_CHANGE_REQUIRED')
    def clear_capability(self, window, capability, verified, approval_ref):
        if not verified or not approval_ref:
            raise NativeGuardError("OBSERVED_USER_CHECKPOINT_REQUIRED")
        with self.db:
            self.db.execute("DELETE FROM capabilities WHERE k=?", (digest([window, capability]),))
    def key(self, artifact_sha, window, filename, goal):
        return digest([artifact_sha, 'rongyao:material-upload', filename, goal])  # Window identity stays pinned separately; renaming it cannot reset the goal.
    def begin(self, key, fingerprint):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT failures,inflight FROM actions WHERE k=?', (key,)).fetchone()
            if row and row[1]:
                raise NativeGuardError('INFLIGHT_UNKNOWN_RECONCILE_ONLY')
            if row and row[0] >= 2:
                raise NativeGuardError('TWO_FAILURES_STOP_USER_CHECKPOINT_REQUIRED')
            self.db.execute('INSERT OR REPLACE INTO actions VALUES(?,?,1,?,NULL)', (key, row[0] if row else 0, fingerprint))
    def finish(self, key, before, after, success, error=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT failures,inflight,fingerprint FROM actions WHERE k=?', (key,)).fetchone()
            if not row or not row[1] or row[2] != before:
                raise NativeGuardError('ACTION_NOT_OWNED')
            # Only an observed goal, never return code or arbitrary UI movement, resets failures.
            passed = bool(success and before != after)
            self.db.execute('UPDATE actions SET failures=?,inflight=0,fingerprint=?,error=? WHERE k=?',
                            (0 if passed else row[0] + 1, after, error, key))
            return passed
    def user_checkpoint(self, key, new_fingerprint, approval_ref):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT fingerprint,inflight FROM actions WHERE k=?', (key,)).fetchone()
            if not row or not approval_ref or row[0] == new_fingerprint or row[1]:
                raise NativeGuardError('OBSERVED_USER_CHECKPOINT_REQUIRED')
            self.db.execute('INSERT INTO checkpoints(k,prior_fingerprint,new_fingerprint,approval_ref) VALUES(?,?,?,?)',(key,row[0],new_fingerprint,approval_ref))
            self.db.execute('UPDATE actions SET failures=0,fingerprint=?,error=NULL WHERE k=?', (new_fingerprint, key))
    def close(self):
        self.db.close()
