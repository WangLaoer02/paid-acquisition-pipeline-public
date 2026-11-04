"""Synthetic state edits: no cloud writes, no re-rendering or paid generation."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workflow_state', ROOT / 'scripts/workflow_state.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WorkflowStateTests(unittest.TestCase):
    def setUp(self):
        self.graph = json.loads((ROOT / 'workflow/stages.json').read_text())
        def sources(n,mirror=False):
            one={'spreadsheet_token':'synthetic-no-network','sheet_id':'fixture','cell':'D'+str(n),'role':'authority'}
            return [dict(one,cell='C'+str(n),role='mirror'),one] if mirror else [one]
        self.bindings=[
            {'id':'A:fixture','kind':'a','family':'a','sources':sources(1,True)},
            {'id':'P:revision','kind':'project','family':'a','sources':sources(2,True)},
            {'id':'B:one','kind':'b','family':'b','parent':'A:fixture','b_asset':'fixture-one','sources':sources(3)},
            {'id':'B:two','kind':'b','family':'b','parent':'A:fixture','b_asset':'fixture-two','sources':sources(4)},
            {'id':'L:one','kind':'library','family':'library','asset_name':'fixture-one','sources':sources(5)},
            {'id':'P:new','kind':'project','project_id':'SK003','family':'a','sources':sources(6,True)}]
        self.a = self.bindings[0]
        self.project = self.bindings[1]
        self.old = {}
        self.items = {}
        for b in self.bindings:
            node = '14 A段验收' if b['kind'] == 'a' else '09 生成准备' if b['kind'] == 'project' else '04 成片验收' if b['kind'] == 'b' else '04 可接'
            for s in b['sources']:
                self.old[module.source_id(s)] = node
            self.items[b['id']] = {'current_node': node}
        self.checkpoint = {'sources': self.old.copy(), 'items': self.items}

    def resolve(self, observed):
        return module.plan(self.bindings, observed, self.checkpoint, self.graph)

    def test_no_edit_preserves_current_work_nodes(self):
        result = self.resolve(self.old)
        self.assertFalse(result['writes'])
        self.assertFalse(result['conflicts'])
        self.assertTrue(all(i['action'] == 'CONTINUE' for i in result['items']))

    def test_API_omitted_false_is_single_but_missing_rule_is_rejected(self):
        self.assertEqual(module.single_node_value({'value': '07 正式剧本', 'data_validation': {'type': 'list', 'items': ['07 正式剧本']}}), '07 正式剧本')
        for cell in [{'value': '07 正式剧本'}, {'value': '07 正式剧本', 'data_validation': {'type': 'list', 'support_multiple_values': True}}]:
            with self.assertRaises(ValueError):
                module.single_node_value(cell)

    def test_master_rollback_syncs_mirror_and_invalidates_B_dependents(self):
        observed = self.old.copy()
        observed[module.source_id(self.a['sources'][-1])] = '07 正式剧本'
        result = self.resolve(observed)
        self.assertEqual(len(result['writes']), 3)
        a = next(i for i in result['items'] if i['id'] == self.a['id'])
        self.assertEqual(a['action'], 'ROLLBACK_REWORK')
        self.assertIn('15 已完成', a['affected_nodes_require_revalidation'])
        dependents = [i for i in result['items'] if i['family'] == 'b']
        self.assertTrue(all(i['current_node'] == '01 B段匹配' for i in dependents))
        self.assertTrue(all(isinstance(i['required_output'],str) and i['required_output'].strip() for i in dependents))

    def test_B_rollback_is_local_to_selected_variant(self):
        observed = self.old.copy()
        target = next(b for b in self.bindings if b['kind'] == 'b')
        observed[module.source_id(target['sources'][0])] = '02 接B剪辑'
        result = self.resolve(observed)
        changed = [i for i in result['items'] if i['action'] != 'CONTINUE']
        self.assertEqual([i['id'] for i in changed], [target['id']])

    def test_conflicting_mirror_edits_are_not_silently_overwritten(self):
        observed = self.old.copy()
        observed[module.source_id(self.a['sources'][0])] = '07 正式剧本'
        observed[module.source_id(self.a['sources'][-1])] = '08 镜头设计'
        result = self.resolve(observed)
        self.assertTrue(result['conflicts'])
        self.assertFalse(result['writes'])

    def test_forward_selection_does_not_pass_gates(self):
        observed = self.old.copy()
        observed[module.source_id(self.a['sources'][-1])] = '15 已完成'
        result = self.resolve(observed)
        a = next(i for i in result['items'] if i['id'] == self.a['id'])
        self.assertEqual(a['action'], 'FORWARD_REQUEST')
        self.assertFalse(a['gate_pass_inferred'])

    def test_formal_revision_rollback_does_not_rework_history(self):
        observed = self.old.copy()
        observed[module.source_id(self.project['sources'][0])] = '08 镜头设计'
        result = self.resolve(observed)
        self.assertTrue(all(i['action'] == 'CONTINUE' for i in result['items'] if i['id'] != self.project['id']))

    def test_new_project_rollback_syncs_its_mirror_without_touching_history(self):
        project = next(b for b in self.bindings if b.get('project_id') == 'SK003')
        observed = self.old.copy()
        observed[module.source_id(project['sources'][-1])] = '03 粗分镜'
        result = self.resolve(observed)
        changed = [i for i in result['items'] if i['action'] != 'CONTINUE']
        self.assertEqual([i['id'] for i in changed], [project['id']])
        self.assertEqual(changed[0]['action'], 'ROLLBACK_REWORK')
        self.assertEqual([w['source'] for w in result['writes']], [project['sources'][0]])


    def test_mirror_only_edit_never_overwrites_authority(self):
        project = next(b for b in self.bindings if b.get('project_id') == 'SK003')
        observed = self.old.copy()
        observed[module.source_id(project['sources'][0])] = '03 粗分镜'
        result = self.resolve(observed)
        self.assertTrue(result['conflicts'])
        self.assertFalse(result['writes'])
        self.assertIn('Mirror changed', result['conflicts'][0]['reason'])

    def test_B_asset_rework_only_invalidates_its_own_variant(self):
        library = next(b for b in self.bindings if b['kind'] == 'library')
        observed = self.old.copy()
        observed[module.source_id(library['sources'][0])] = '02 剪辑整理'
        result = self.resolve(observed)
        changed = {i['id'] for i in result['items'] if i['action'] != 'CONTINUE'}
        expected = {library['id']} | {b['id'] for b in self.bindings if b.get('b_asset') == library['asset_name']}
        self.assertEqual(changed, expected)

    def test_later_selection_keeps_outstanding_revalidation_visible(self):
        self.checkpoint['items'][self.a['id']]['revalidation_required'] = ['07 正式剧本', '08 镜头设计']
        observed = self.old.copy()
        observed[module.source_id(self.a['sources'][-1])] = '15 已完成'
        result = self.resolve(observed)
        a = next(i for i in result['items'] if i['id'] == self.a['id'])
        self.assertEqual(a['revalidation_required'], ['07 正式剧本', '08 镜头设计'])
        self.assertFalse(a['gate_pass_inferred'])


class SyncRecoveryTests(unittest.TestCase):
    """Exercise the sync entrypoint with persistent checkpoints and an isolated Sheet transport."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings = [
            {'id': 'fixture-A', 'kind': 'a', 'family': 'a', 'sources': [
                {'spreadsheet_token': 'isolated', 'sheet_id': 'a', 'cell': 'A1', 'role': 'authority'},
                {'spreadsheet_token': 'isolated', 'sheet_id': 'a', 'cell': 'A2', 'role': 'mirror'}]},
            {'id': 'fixture-B', 'kind': 'b', 'family': 'b', 'parent': 'fixture-A', 'sources': [
                {'spreadsheet_token': 'isolated', 'sheet_id': 'b', 'cell': 'A1', 'role': 'authority'}]}]
        self.graph = json.loads((ROOT / 'workflow/stages.json').read_text())
        self.old = {module.source_id(s): ('14 A段验收' if b['family'] == 'a' else '04 成片验收')
                    for b in self.bindings for s in b['sources']}
        self.cloud = self.old.copy()
        self.checkpoint = self.root / 'checkpoint.json'
        module.save(self.checkpoint, {'sources': self.old, 'items': {
            'fixture-A': {'current_node': '14 A段验收'},
            'fixture-B': {'current_node': '04 成片验收'}}})
        self.bindings_path = self.root / 'bindings.json'
        module.save(self.bindings_path, {'bindings': self.bindings})
        self.graph_path = self.root / 'graph.json'
        module.save(self.graph_path, self.graph)
        self.writes = []

    def run_sync(self, after_write=None):
        def write(command, source, flags, payload=None):
            self.assertEqual(command, '+cells-set')
            key = module.source_id(source)
            value = json.loads(payload)[0][0]['value']
            self.writes.append((key, value))
            self.cloud[key] = value
            if after_write:
                after_write(len(self.writes))
            return {}
        with contextlib.ExitStack() as stack:
            for name, value in [('ROOT', self.root), ('BINDINGS', self.bindings_path),
                                ('GRAPH', self.graph_path), ('CHECKPOINT', self.checkpoint)]:
                stack.enter_context(patch.object(module, name, value))
            stack.enter_context(patch.object(module, 'read_source', side_effect=lambda s: (module.source_id(s), self.cloud[module.source_id(s)])))
            stack.enter_context(patch.object(module, 'call', side_effect=write))
            stack.enter_context(patch.object(module.runtime, 'mutation', return_value=contextlib.nullcontext()))
            stack.enter_context(patch.object(module.runtime, 'event'))
            stack.enter_context(patch.object(sys, 'argv', ['workflow_state.py', 'sync']))
            stack.enter_context(patch.object(sys, 'stdout', io.StringIO()))
            module.main()

    def rollback(self):
        self.cloud[module.source_id(self.bindings[0]['sources'][0])] = '07 正式剧本'

    def test_interrupted_write_recovers_only_remaining_changes_and_keeps_revalidation(self):
        self.rollback()
        original = self.checkpoint.read_bytes()
        def interrupt(count):
            if count == 1:
                raise subprocess.TimeoutExpired('isolated-transport', 1)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_sync(interrupt)
        self.assertEqual(self.checkpoint.read_bytes(), original)
        self.run_sync()
        self.assertEqual(len(self.writes), 2)
        self.assertEqual(len({key for key, _ in self.writes}), 2)
        resumed = module.load(self.checkpoint)
        self.assertIn('15 已完成', resumed['items']['fixture-A']['revalidation_required'])
        self.assertIn('05 已完成', resumed['items']['fixture-B']['revalidation_required'])
        self.run_sync()
        self.assertEqual(len(self.writes), 2)
        repeated = module.load(self.checkpoint)
        self.assertEqual(repeated['items']['fixture-B']['revalidation_required'], resumed['items']['fixture-B']['revalidation_required'])
        self.assertFalse(repeated['items']['fixture-B']['gate_pass_inferred'])

    def test_user_edit_during_batch_is_preserved_and_checkpoint_not_advanced(self):
        self.rollback()
        original = self.checkpoint.read_bytes()
        target = module.source_id(self.bindings[1]['sources'][0])
        def manual_edit(count):
            if count == 1:
                self.cloud[target] = '02 接B剪辑'
        with self.assertRaisesRegex(ValueError, 'Concurrent state change'):
            self.run_sync(manual_edit)
        self.assertEqual(self.cloud[target], '02 接B剪辑')
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.checkpoint.read_bytes(), original)

    def test_upstream_edit_during_batch_prevents_stale_dependent_write(self):
        self.rollback()
        original = self.checkpoint.read_bytes()
        upstream = module.source_id(self.bindings[0]['sources'][0])
        dependent = module.source_id(self.bindings[1]['sources'][0])
        def manual_edit(count):
            if count == 1:
                self.cloud[upstream] = '08 镜头设计'
        with self.assertRaisesRegex(ValueError, 'Concurrent state change'):
            self.run_sync(manual_edit)
        self.assertEqual(self.cloud[upstream], '08 镜头设计')
        self.assertEqual(self.cloud[dependent], '04 成片验收')
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.checkpoint.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
