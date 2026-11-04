#!/usr/bin/env python3
"""Project evidence projection, not project state. No media decoding or external writes."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

CONTENT = ('story', 'action', 'dialogue', 'screen_text', 'sound', 'uncertainties')
DOWNSTREAM = {f'A{i:02}' for i in range(2, 16)} | {f'B{i:02}' for i in range(1, 6)}
APPLICABLE = DOWNSTREAM | {'A01'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def local(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('REFERENCE_RELATIVE_PATH_REQUIRED')
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('REFERENCE_FILE_MISSING_OR_OUTSIDE_ROOT')
    return path


def proof(root, entry):
    if not isinstance(entry, dict) or set(entry) != {'path', 'sha256'}:
        raise ValueError('REFERENCE_PROOF_REQUIRED')
    path = local(root, entry.get('path'))
    if file_sha(path) != entry.get('sha256'):
        raise ValueError('REFERENCE_EVIDENCE_CHANGED: ' + entry['path'])
    return path


def ref(root, path):
    path = Path(path).resolve()
    return {'path': path.relative_to(Path(root).resolve()).as_posix(), 'sha256': file_sha(path)}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def unit_view(unit):
    # Do not forward optional archive metadata or an embedded full transcript.
    return {key: unit[key] for key in ('id', 'start', 'end', *CONTENT, 'evidence')}


def seconds(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def packet(root, selection_path, project_id=None):
    """Return only whole selected evidence units and explicitly justified context.

    Full A01 JSON is parsed locally to validate original strings; it is never
    returned to the caller. Hashing archives is disk integrity I/O, not a new
    video/ASR/OCR analysis. No range rounding or silent text clipping is allowed.
    """
    selection_name = selection_path
    selection_path = local(root, selection_name)
    selection_ref = ref(root, selection_path)
    s = load(selection_path)
    if (not isinstance(s, dict) or s.get('schema') != 'reference-selection-v1' or not nonempty(s.get('project_id'))
            or not nonempty(s.get('revision'))):
        raise ValueError('REFERENCE_SELECTION_IDENTITY_REQUIRED')
    if project_id and s['project_id'] != project_id:
        raise ValueError('REFERENCE_PROJECT_MISMATCH')
    authority = s.get('authority', {})
    if not isinstance(authority, dict) or not all(nonempty(authority.get(k)) for k in ('source_ref', 'revision')):
        raise ValueError('REFERENCE_CURRENT_SELECTION_SOURCE_REQUIRED')
    source = load(proof(root, s.get('source')))
    if not isinstance(source, dict) or source.get('schema') != 'reference-source-v1' or not nonempty(source.get('source_id')):
        raise ValueError('REFERENCE_SOURCE_REQUIRED')
    duration = source.get('duration_seconds')
    if not seconds(duration) or duration <= 0:
        raise ValueError('REFERENCE_DURATION_REQUIRED')
    proof(root, source.get('video'))
    units = source.get('units', [])
    if not isinstance(units, list) or not units:
        raise ValueError('REFERENCE_TIMED_UNITS_REQUIRED')
    ids = set(); previous = 0
    for u in units:
        if not isinstance(u, dict) or not nonempty(u.get('id')) or u['id'] in ids:
            raise ValueError('REFERENCE_UNIT_ID_REQUIRED_UNIQUE')
        ids.add(u['id'])
        a, b = u.get('start'), u.get('end')
        if not seconds(a) or not seconds(b) or not previous <= a < b <= duration:
            raise ValueError('REFERENCE_UNIT_TIME_INVALID')
        previous = b
        if any(not isinstance(u.get(k), str) for k in CONTENT):
            raise ValueError('REFERENCE_FOUR_DIMENSIONS_REQUIRED: unknowns remain explicit strings')
        evidence = u.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ValueError('REFERENCE_UNIT_EVIDENCE_REQUIRED')
        # Outside units are not opened or sent downstream. Their strings remain
        # untouched in the source archive and its SHA binds the complete file.
    interval = s.get('range', {})
    if not isinstance(interval, dict) or set(interval) != {'start', 'end'}:
        raise ValueError('REFERENCE_RANGE_START_END_ONLY')
    start, end = interval.get('start'), interval.get('end')
    if not seconds(start) or not seconds(end) or not 0 <= start < end <= duration:
        raise ValueError('REFERENCE_SELECTION_TIME_INVALID')
    selected = []; cursor = start
    for u in units:
        if u['end'] <= start or u['start'] >= end:
            continue
        if u['start'] != cursor or u['end'] > end:
            raise ValueError('REFERENCE_SPLIT_OR_GAP: verify and split the source unit; never clip its original text')
        selected.append(unit_view(u)); cursor = u['end']
    if cursor != end:
        raise ValueError('REFERENCE_SELECTION_NOT_COVERED')
    context = []; used = {u['id'] for u in selected}
    exceptions = s.get('context_exceptions', [])
    if not isinstance(exceptions, list):
        raise ValueError('REFERENCE_CONTEXT_LIST_REQUIRED')
    for exception in exceptions:
        if (not isinstance(exception, dict) or exception.get('basis') not in ('necessary_causality', 'explicit_user_request')
                or not nonempty(exception.get('reason')) or not exception.get('unit_ids')):
            raise ValueError('REFERENCE_CONTEXT_JUSTIFICATION_REQUIRED')
        if not isinstance(exception['unit_ids'], list) or any(not nonempty(uid) for uid in exception['unit_ids']):
            raise ValueError('REFERENCE_CONTEXT_UNIT_IDS_REQUIRED')
        proof(root, exception.get('evidence'))
        rows = []
        for uid in exception['unit_ids']:
            if uid not in ids or uid in used:
                raise ValueError('REFERENCE_CONTEXT_UNKNOWN_OR_DUPLICATE')
            used.add(uid); rows.append(unit_view(next(u for u in units if u['id'] == uid)))
        context.append({'basis': exception['basis'], 'reason': exception['reason'],
                        'evidence': exception['evidence'], 'units': rows,
                        'use': 'context_only; not selected story or implicit adaptation permission'})
    for u in selected + [u for e in context for u in e['units']]:
        for evidence in u['evidence']:
            proof(root, evidence)
    # Recheck selection after dependent reads rather than return a mixed revision.
    if ref(root, local(root, selection_name)) != selection_ref:
        raise ValueError('REFERENCE_SELECTION_CHANGED_DURING_READ')
    proof(root, s['source'])
    scope = digest({'selection': selection_ref, 'source': s['source']})
    chars = lambda rows: sum(sum(len(u[k]) for k in CONTENT) for u in rows)
    return {'schema': 'reference-packet-v1', 'project_id': s['project_id'],
            'revision': s['revision'], 'scope_sha256': scope, 'selection': selection_ref,
            'authority': {k: authority[k] for k in ('source_ref', 'revision')}, 'source_archive': s['source'],
            'source_id': source['source_id'], 'video': source['video'],
            'range': interval, 'selected': selected, 'context_exceptions': context,
            'reading_comparison': {'archive_units': len(units), 'selected_units': len(selected),
                'context_units': len(used) - len(selected), 'archive_content_characters': chars(units),
                'delivered_content_characters': chars([u for u in units if u['id'] in used]),
                'source_seconds': duration, 'selected_seconds': end - start,
                'context_seconds': sum(u['end'] - u['start'] for e in context for u in e['units']),
                'measurement': 'exact evidence-string characters; not tokens or end-to-end speed'},
            'semantic_truth_inferred': False, 'user_adoption_inferred': False,
            'side_effects': []}


def binding(p):
    return {k: p[k] for k in ('project_id', 'revision', 'scope_sha256', 'selection')}


def check_binding(record, expected):
    if not isinstance(record, dict):
        raise ValueError('REFERENCE_USE_RECORD_REQUIRED')
    if record.get('project_id') and record['project_id'] != expected['project_id']:
        raise ValueError('REFERENCE_PROJECT_MISMATCH')
    if record.get('reference_scope') != expected:
        raise ValueError('REFERENCE_SCOPE_CHANGED_OR_MISSING: revalidate affected structure, shots, prompts and delivery; preserve old work')
    return {'ok': True, 'binding': expected, 'semantic_truth_inferred': False,
            'automatic_regeneration': False, 'automatic_sheet_write': False}


def check_use(root, record, current_path):
    """Fresh selection is supplied by the caller; never infer it from an old use."""
    if not current_path:
        raise ValueError('REFERENCE_CURRENT_SELECTION_REQUIRED: reread the existing authority')
    if not isinstance(record, dict):
        raise ValueError('REFERENCE_USE_RECORD_REQUIRED')
    return check_binding(record, binding(packet(root, current_path, record.get('project_id'))))


def context(root, node, selection_path=None, use_path=None, project_id=None):
    if node not in APPLICABLE:
        if selection_path or use_path:
            raise ValueError('REFERENCE_SCOPE_NOT_APPLICABLE_TO_LIBRARY_NODE')
        return None
    if use_path and not selection_path:
        raise ValueError('REFERENCE_CURRENT_SELECTION_REQUIRED')
    if not selection_path:
        return {'status': 'selection_not_supplied', 'ready_for_reference_use': False,
                'next': 'Read existing A01/Sheet/current user selection; provide --reference-scope. Legacy files remain intact; do not infer whole-video scope.'}
    p = packet(root, selection_path, project_id)
    review = check_binding(load(local(root, use_path)), binding(p)) if use_path else None
    return {'status': 'bounded_reference_available', 'ready_for_reference_use': True,
            'packet': p, 'binding': binding(p), 'downstream_check': review,
            'existing_downstream_validated': review is not None,
            'read_boundary': 'Only selected source-time range by default; explicit context stays separate. No full-video reanalysis unless actually necessary or requested.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--selection', required=True)
    parser.add_argument('--use')
    args = parser.parse_args()
    result = check_use(args.root, load(local(args.root, args.use)), args.selection) if args.use else packet(args.root, args.selection)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'side_effects': []}, ensure_ascii=False))
        raise SystemExit(1)
