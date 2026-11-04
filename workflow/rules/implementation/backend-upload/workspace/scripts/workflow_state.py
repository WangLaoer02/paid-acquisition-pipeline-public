#!/usr/bin/env python3
"""Read Feishu's current node; reconcile user edits without generating or replacing media."""
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import workflow_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / 'workflow/stages.json'
BINDINGS = ROOT / 'workflow/state_bindings.json'
CHECKPOINT = ROOT / 'workflow/state_checkpoint.json'


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def stamp():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def source_id(source):
    return ':'.join(source[k] for k in ['spreadsheet_token', 'sheet_id', 'cell'])


def call(command, source, flags, payload=None):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
    result = subprocess.run(['lark-cli', 'sheets', command, '--as', 'user', '--spreadsheet-token', source['spreadsheet_token'], '--sheet-id', source['sheet_id'], *flags], input=payload, capture_output=True, text=True, env=env, cwd=ROOT, timeout=45)
    response = json.loads(result.stdout or result.stderr)
    if result.returncode or not response.get('ok') or response.get('identity') != 'user':
        raise ValueError('Feishu operation failed: ' + str(response.get('error', {})))
    return response['data']


def single_node_value(cell):
    rule = cell.get('data_validation', {})
    # Feishu omits the false boolean on single-select list rules.
    if rule.get('type') != 'list' or rule.get('support_multiple_values', False) is not False or len(cell.get('multiple_values', [])) > 1:
        raise ValueError('Current node is not a single selection.')
    return cell.get('value', '')


def read_source(source):
    a = re.fullmatch(r'([A-Z]+)(\d+)', source['anchor_cell'])
    b = re.fullmatch(r'([A-Z]+)(\d+)', source['cell'])
    if not a or not b or a[2] != b[2]:
        raise ValueError('Invalid state/anchor binding.')
    if source.get('identity_sheet_name'):
        info=call('+sheet-info',source,[])
        if info.get('sheet_id')!=source['sheet_id'] or info.get('sheet_name')!=source['identity_sheet_name']:
            raise ValueError('Record moved or identity changed; refresh the binding instead of using an old row.')
    if source.get('identity_cell'):
        if not source.get('identity_value'):raise ValueError('Explicit project identity is required for a compact state source.')
        identity = call('+cells-get', source, ['--range', source['identity_cell'], '--include', 'value'])
        if identity.get('has_more') or any(r.get('truncated') for r in identity.get('ranges', [])):
            raise ValueError('Project identity read was truncated.')
        values=[c.get('value','') for area in identity.get('ranges',[]) for row in area['cells'] for c in row]
        if values != [source['identity_value']]:raise ValueError('Record moved or identity changed; refresh the binding instead of using an old row.')
    data = call('+cells-get', source, ['--range', source['anchor_cell'] + ':' + source['cell'], '--include', 'value,data_validation'])
    if data.get('has_more'):
        raise ValueError('State read was truncated.')
    cells = {}
    for area in data['ranges']:
        if area.get('truncated'):
            raise ValueError('State read was truncated.')
        for row_id, row in zip(area['row_indices'], area['cells']):
            for col, cell in zip(area['col_indices'], row):
                cells[col + str(row_id)] = cell
    if not cells.get(source['anchor_cell'],{}).get('value') and not cells.get(source['cell'],{}).get('value'):
        raise ValueError('STATE_SOURCE_MISSING: identity/current node absent; preserve Sheet and edits, locate the real single-select source. Do not infer from artifacts, mirrors or checkpoints.')
    if cells.get(source['anchor_cell'],{}).get('value') != source['anchor_value']:
        raise ValueError('Record moved or identity changed; refresh the binding instead of using an old row.')
    return source_id(source), single_node_value(cells[source['cell']])


def observe(bindings):
    sources = [s for item in bindings for s in item['sources']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        return dict(pool.map(read_source, sources))


def node_labels(nodes):
    labels={}
    for node in nodes:
        for label in [node['label'], *node.get('legacy_labels',[])]:
            if label in labels:raise ValueError('Duplicate workflow node label/alias.')
            labels[label]=node
    return labels


def plan(bindings, observations, checkpoint, graph):
    result = {'observed_at': stamp(), 'items': [], 'writes': [], 'conflicts': []}
    previous = checkpoint.get('sources', {})
    for binding in bindings:
        nodes = graph['families'][binding['family']]
        by_label = node_labels(nodes)
        def identity(value):return by_label[value]['id'] if value in by_label else value
        values = [observations[source_id(s)] for s in binding['sources']]
        authorities=[src for src in binding['sources'] if src.get('role')=='authority']
        if len(authorities)!=1:
            result['conflicts'].append({'id': binding['id'], 'values': values, 'reason': 'Exactly one authoritative state source is required.'})
            continue
        authority=authorities[0];selected=observations[source_id(authority)]
        changed_sources=[src for src in binding['sources'] if identity(observations[source_id(src)]) != identity(previous.get(source_id(src), observations[source_id(src)]))]
        changed_values={identity(observations[source_id(src)]) for src in changed_sources}
        if len(changed_values)>1:
            result['conflicts'].append({'id': binding['id'], 'values': values, 'reason': 'Authoritative and mirror sources changed to different values; preserve both and arbitrate.'})
            continue
        if changed_sources and authority not in changed_sources:
            result['conflicts'].append({'id': binding['id'], 'values': values, 'reason': 'Mirror changed while authoritative project Sheet did not; mirror data cannot overwrite authority.'})
            continue
        if not changed_sources and len({identity(value) for value in values})>1:
            result['conflicts'].append({'id': binding['id'], 'values': values, 'reason': 'Sources disagree without a new authoritative edit; no status will be overwritten.'})
            continue
        if selected not in by_label:
            result['conflicts'].append({'id': binding['id'], 'values': values, 'reason': 'Unknown workflow node.'})
            continue
        node = by_label[selected]
        old = checkpoint.get('items', {}).get(binding['id'], {}).get('current_node', selected)
        old_order = by_label.get(old, node)['order']
        action = 'CONTINUE' if identity(selected) == identity(old) else ('ROLLBACK_REWORK' if node['order'] < old_order else 'FORWARD_REQUEST')
        item = {'id': binding['id'], 'family': binding['family'], 'current_node': selected, 'current_node_id': node['id'], 'action': action, 'resume_at': selected, 'required_output': node['required_output'], 'affected_nodes_require_revalidation': [n['label'] for n in nodes if n['order'] >= node['order']] if action == 'ROLLBACK_REWORK' else [], 'gate_pass_inferred': False}
        result['items'].append(item)
    items = {i['id']: i for i in result['items']}
    for binding in bindings:
        changed = items.get(binding['id'])
        if not changed or changed['action'] != 'ROLLBACK_REWORK':
            continue
        for dependent in bindings:
            affected = dependent.get('parent') == binding['id'] or (binding['kind'] == 'library' and dependent.get('b_asset') == binding.get('asset_name'))
            if not affected or dependent['id'] not in items:
                continue
            item = items[dependent['id']]
            first = graph['families'][dependent['family']][0]
            item.update(current_node=first['label'], current_node_id=first['id'], resume_at=first['label'], required_output=first['required_output'], action='DEPENDENCY_RECHECK', invalidated_by=binding['id'], affected_nodes_require_revalidation=[n['label'] for n in graph['families'][dependent['family']]])
    for binding in bindings:
        item = items.get(binding['id'])
        if item:
            prior = checkpoint.get('items', {}).get(binding['id'], {})
            family_nodes=graph['families'][binding['family']]
            labels=node_labels(family_nodes)
            def same_node(a,b):return a==b or (a in labels and b in labels and labels[a]['id']==labels[b]['id'])
            pending=list(dict.fromkeys(prior.get('revalidation_required',[])+item['affected_nodes_require_revalidation']))
            item['revalidation_required']=[value for node in family_nodes for value in pending if same_node(value,node['label'])]
            for source in binding['sources']:
                if not same_node(observations[source_id(source)],item['current_node']):
                    reason='dependency_recheck' if item.get('action')=='DEPENDENCY_RECHECK' else 'mirror_sync'
                    if source.get('role')=='authority' and reason!='dependency_recheck':
                        result['conflicts'].append({'id': binding['id'], 'values': [observations[source_id(x)] for x in binding['sources']], 'reason': 'Non-authoritative data attempted to overwrite the authoritative source.'})
                        continue
                    result['writes'].append({'source': source, 'before': observations[source_id(source)], 'after': item['current_node'], 'reason': reason})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'sync'])
    parser.add_argument('--receipt')
    args = parser.parse_args()
    bindings = load(BINDINGS)['bindings']
    checkpoint = load(CHECKPOINT)
    graph = load(GRAPH)
    # Registered consoles must pass their current format contract before execution/sync.
    import console_template
    for project in sorted({b.get('project_id') for b in bindings if b.get('project_id')}):
        config_path = ROOT / 'projects' / project / 'console.json'
        if config_path.exists() and load(config_path).get('template_id'):
            console_template.check(project)
    observations = observe(bindings)
    result = plan(bindings, observations, checkpoint, graph)
    if args.command == 'sync':
        scope='workflow-state:'+hashlib.sha256(json.dumps(sorted(source_id(src) for b in bindings for src in b['sources'])).encode()).hexdigest()[:20]
        with runtime.mutation('state_sync',scope):
            if result['conflicts']:raise ValueError('Conflicting node edits; resolve them before syncing.')
            expected=dict(observations)
            for change in result['writes']:
                if change['source'].get('role')=='authority' and change.get('reason')!='dependency_recheck':
                    raise ValueError('Arbitration violation: only dependency recheck may move an authoritative project state automatically.')
                # Each write depends on the whole observed authority/mirror graph.
                # A changed upstream invalidates the remaining plan even if the next
                # target cell itself has not changed. Include our completed writes.
                if observe(bindings) != expected:
                    raise ValueError('Concurrent state change; preserve edits and reread before syncing the remaining cells.')
                call('+cells-set', change['source'], ['--range', change['source']['cell'], '--cells', '-', '--allow-overwrite=true'], json.dumps([[{'value': change['after']}]], ensure_ascii=False))
                expected[source_id(change['source'])]=change['after']
            final=observe(bindings)
            if final!=expected:raise ValueError('Sync outcome differs from the plan; reread before continuing.')
            save(CHECKPOINT, {'updated_at': stamp(), 'sources': final, 'items': {i['id']: i for i in result['items']}})
            save(ROOT / 'evidence/workflow-state-events' / (stamp().replace(':', '-') + '.json'), result)
            runtime.event('state_sync','verified',scope,observation_sha256=runtime.digest(observations),final_sha256=runtime.digest(final),writes=len(result['writes']))
            result['sync_verified']=True
    if args.receipt:
        save(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        raise SystemExit(1)
