"""Bounded reference delivery and stale-scope rejection. Local fixtures, no business writes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import reference_scope as r
import workflow_node as n
import workflow_rules


class ReferenceScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root = ROOT
        self.rel = lambda p: p.relative_to(ROOT).as_posix()
        self.video = self.folder / 'original.bin'
        self.video.write_bytes(b'fixture media bytes, no claim of decoding')
        self.evidence = self.folder / 'observation.txt'
        self.evidence.write_text('synthetic observed evidence; not user adoption')
        self.source = self.folder / 'source.json'
        self.selection = self.folder / 'selection.json'
        self.use = self.folder / 'input.json'
        self.units = []
        for index, label in enumerate(('OUTSIDE_BEFORE', 'SELECTED', 'OUTSIDE_AFTER')):
            self.units.append({'id': str(index), 'start': index * 5, 'end': (index + 1) * 5,
                'story': label + ': cause/result', 'action': label + ': action',
                'dialogue': label + ': “原字\n不改写！”', 'screen_text': label + ': 原画面字',
                'sound': '待核对；不能冒称已听审', 'uncertainties': '说话人待核对',
                'evidence': [r.ref(ROOT, self.evidence)]})
        self.archive = {'schema': 'reference-source-v1', 'source_id': 'synthetic-source',
            'duration_seconds': 15, 'video': r.ref(ROOT, self.video), 'units': self.units}
        self.save(self.source, self.archive)
        self.s = {'schema': 'reference-selection-v1', 'project_id': 'fixture-project',
            'revision': 'V1', 'source': r.ref(ROOT, self.source),
            'authority': {'source_ref': 'fixture:current-user-choice', 'revision': 'request-1'},
            'range': {'start': 5, 'end': 10}, 'context_exceptions': []}
        self.save(self.selection, self.s)

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

    def packet(self):
        return r.packet(ROOT, self.rel(self.selection))

    def record(self, node='A03'):
        c = n.get_contract(node)
        return {'schema_version': 1, 'release_id': c['release_id'], 'node': node,
            'project_id': 'fixture-project', 'reference_scope': r.binding(self.packet()),
            'inputs': [{'id': x['id'], 'status': 'verified', 'source_ref': 'fixture:verified'}
                       for x in c['input_requirements']]}

    def test_normal_delivers_only_selected_and_exact_original_strings(self):
        before = self.source.read_bytes()
        p = self.packet()
        self.assertEqual(p['selected'], [self.units[1]])
        self.assertEqual(p['selected'][0]['dialogue'], 'SELECTED: “原字\n不改写！”')
        body = json.dumps(p, ensure_ascii=False)
        self.assertNotIn('OUTSIDE_BEFORE', body)
        self.assertNotIn('OUTSIDE_AFTER', body)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(p['semantic_truth_inferred'])
        self.assertFalse(p['user_adoption_inferred'])
        self.assertEqual(p['reading_comparison']['selected_seconds'], 5)

    def test_necessary_context_is_explicit_and_separate(self):
        for basis in ('necessary_causality', 'explicit_user_request'):
            self.s['context_exceptions'] = [{'basis': basis, 'reason': '核对冲突触发；不加入改编',
                'unit_ids': ['0'], 'evidence': r.ref(ROOT, self.evidence)}]
            self.save(self.selection, self.s)
            p = self.packet()
            self.assertEqual(p['selected'], [self.units[1]])
            self.assertEqual(p['context_exceptions'][0]['units'], [self.units[0]])
            self.assertNotIn('OUTSIDE_AFTER', json.dumps(p))
            self.assertEqual(p['reading_comparison']['context_seconds'], 5)

    def test_context_without_justification_or_proof_is_rejected(self):
        for exception in ({'unit_ids': ['0']}, {'basis': 'necessary_causality',
                           'reason': 'needed', 'unit_ids': ['0']}):
            self.s['context_exceptions'] = [exception]
            self.save(self.selection, self.s)
            with self.assertRaises(ValueError): self.packet()

    def test_changed_range_rejects_prior_inputs_without_touching_them(self):
        old = self.record(); self.save(self.use, old); before = self.use.read_bytes()
        self.s.update(revision='V2', range={'start': 0, 'end': 5})
        self.save(self.selection, self.s)
        with self.assertRaisesRegex(ValueError, 'REFERENCE_SCOPE_CHANGED'):
            r.check_use(ROOT, old, self.rel(self.selection))
        self.assertEqual(self.use.read_bytes(), before)
        self.assertEqual(self.packet()['selected'], [self.units[0]])

    def test_new_filename_still_compares_against_current_selection(self):
        old = self.record()
        new = self.folder / 'selection-v2.json'
        self.s.update(revision='V2', range={'start': 10, 'end': 15})
        self.save(new, self.s)
        with self.assertRaisesRegex(ValueError, 'REFERENCE_SCOPE_CHANGED'):
            r.check_use(ROOT, old, self.rel(new))
        with self.assertRaisesRegex(ValueError, 'CURRENT_SELECTION_REQUIRED'):
            r.check_use(ROOT, old, None)

    def test_revision_only_change_requires_revalidation(self):
        old = self.record()
        self.s['authority']['revision'] = 'manual-edit-2'
        self.save(self.selection, self.s)
        with self.assertRaises(ValueError): r.check_use(ROOT, old, self.rel(self.selection))

    def test_concurrent_selection_edit_or_link_change_is_rejected(self):
        other = self.folder / 'new-selection.json'
        new = dict(self.s, revision='V2', range={'start': 0, 'end': 5})
        self.save(other, new)
        link = self.folder / 'current-selection.json'
        link.symlink_to(self.selection)
        original = r.proof
        for pointer in (self.selection, link):
            self.save(self.selection, self.s)
            def changed(root, entry):
                result = original(root, entry)
                if entry == self.archive['video']:
                    if pointer == link:
                        link.unlink(); link.symlink_to(other)
                    else:
                        self.save(self.selection, new)
                return result
            with self.subTest(pointer=pointer.name), patch.object(r, 'proof', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'SELECTION_CHANGED_DURING_READ'):
                    r.packet(ROOT, self.rel(pointer))

    def test_malformed_archive_or_selection_stops_cleanly(self):
        for value in ([], None, 'unknown'):
            self.save(self.selection, value)
            with self.assertRaises(ValueError): self.packet()
        self.save(self.selection, self.s)
        self.s['context_exceptions'] = 'unbounded-context'
        self.save(self.selection, self.s)
        with self.assertRaisesRegex(ValueError, 'CONTEXT_LIST_REQUIRED'): self.packet()

    def test_original_or_observation_changes_are_not_silently_accepted(self):
        for path in (self.source, self.video, self.evidence):
            before = path.read_bytes()
            path.write_bytes(before + b' changed')
            with self.assertRaisesRegex(ValueError, 'EVIDENCE_CHANGED'): self.packet()
            path.write_bytes(before)

    def test_half_open_edges_do_not_include_neighbors(self):
        for start, end, uid in ((0, 5, '0'), (5, 10, '1'), (10, 15, '2')):
            self.s['range'] = {'start': start, 'end': end}; self.save(self.selection, self.s)
            self.assertEqual([u['id'] for u in self.packet()['selected']], [uid])

    def test_partial_units_gaps_and_nonfinite_ranges_rejected(self):
        for start, end in ((6, 10), (5, 9), (-1, 10), (10, 5), (5, float('nan')), (True, 10)):
            self.s['range'] = {'start': start, 'end': end}; self.save(self.selection, self.s)
            with self.assertRaises(ValueError): self.packet()
        self.s['range'] = {'start': 0, 'end': 10}
        self.archive['units'][1]['start'] = 6
        self.save(self.source, self.archive); self.s['source'] = r.ref(ROOT, self.source)
        self.save(self.selection, self.s)
        with self.assertRaisesRegex(ValueError, 'SPLIT_OR_GAP'): self.packet()

    def test_unknown_dimensions_not_fabricated(self):
        del self.archive['units'][1]['sound']
        self.save(self.source, self.archive); self.s['source'] = r.ref(ROOT, self.source)
        self.save(self.selection, self.s)
        with self.assertRaisesRegex(ValueError, 'FOUR_DIMENSIONS'): self.packet()

    def test_archive_extras_are_not_forwarded(self):
        self.archive['units'][1]['full_transcript'] = 'OUTSIDE_BEFORE OUTSIDE_AFTER'
        self.s['authority']['archive_notes'] = 'OUTSIDE_BEFORE OUTSIDE_AFTER'
        self.save(self.source, self.archive); self.s['source'] = r.ref(ROOT, self.source)
        self.save(self.selection, self.s)
        body = json.dumps(self.packet())
        self.assertNotIn('OUTSIDE_BEFORE', body)
        self.assertNotIn('OUTSIDE_AFTER', body)

    def test_context_checks_current_packet_once(self):
        self.save(self.use, self.record())
        with patch.object(r, 'packet', wraps=r.packet) as compile_packet:
            data = r.context(ROOT, 'A03', self.rel(self.selection), self.rel(self.use))
        self.assertTrue(data['existing_downstream_validated'])
        self.assertEqual(compile_packet.call_count, 1)

    def test_a01_evidence_also_requires_a_recorded_selection(self):
        c = n.get_contract('A01')
        record = self.record('A01')
        record['checks'] = [{'id': g['id'], 'status': 'pass', 'evidence': [r.ref(ROOT, self.evidence)]}
                            for g in c['gate']]
        self.save(self.use, record)
        self.assertFalse(n.inspect_evidence('A01', self.use)['ready_for_semantic_review'])
        self.assertTrue(n.inspect_evidence('A01', self.use, self.rel(self.selection))['ready_for_semantic_review'])

    def test_path_project_and_library_boundaries(self):
        with self.assertRaises(ValueError): r.packet(ROOT, self.rel(self.selection), 'wrong-project')
        with self.assertRaises(ValueError): r.local(ROOT, '../outside')
        with self.assertRaises(ValueError): r.context(ROOT, 'L01', self.rel(self.selection))
        self.assertIsNone(r.context(ROOT, 'L01'))

    def test_missing_legacy_selection_reads_rules_but_does_not_pass_inputs(self):
        scope = r.context(ROOT, 'A02')
        self.assertFalse(scope['ready_for_reference_use'])
        record = self.record('A02'); del record['reference_scope']; self.save(self.use, record)
        data = n.inspect_inputs('A02', self.use)
        self.assertFalse(data['complete'])
        self.assertIn('REFERENCE_CURRENT_SELECTION_AND_BINDING_REQUIRED', data['missing_or_unverified'])

    def test_bound_input_and_gate_evidence_use_current_scope(self):
        record = self.record(); self.save(self.use, record)
        self.assertTrue(n.inspect_inputs('A03', self.use, self.rel(self.selection))['complete'])
        c = n.get_contract('A03')
        record['checks'] = [{'id': g['id'], 'status': 'pass', 'evidence': [r.ref(ROOT, self.evidence)]}
                            for g in c['gate']]
        self.save(self.use, record)
        checked = n.inspect_evidence('A03', self.use, self.rel(self.selection))
        self.assertTrue(checked['ready_for_semantic_review'])
        self.assertFalse(checked['gate_pass_inferred'])
        self.s['range'] = {'start': 0, 'end': 5}; self.save(self.selection, self.s)
        for inspect in (n.inspect_inputs, n.inspect_evidence):
            with self.assertRaisesRegex(ValueError, 'REFERENCE_SCOPE_CHANGED'):
                inspect('A03', self.use, self.rel(self.selection))

    def test_real_cli_offline_context_a_and_ab_and_use_validation(self):
        self.save(self.use, self.record('A03'))
        for route in ('a', 'ab'):
            command = [sys.executable, str(ROOT / 'scripts/workflow_node.py'), 'context',
                '--node', 'A03', '--offline-preparation', '--route', route,
                '--reference-scope', self.rel(self.selection), '--reference-use', self.rel(self.use)]
            run = subprocess.run(command + ['--format', 'json'], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads(run.stdout)
            self.assertEqual(data['reference_scope']['packet']['selected'], [self.units[1]])
            self.assertTrue(data['reference_scope']['existing_downstream_validated'])
            self.assertEqual(len(data['execution_boundary']['review_checkpoints']), 3)
            self.assertEqual(data['execution_boundary']['route'], route)
            self.assertFalse(data['release']['live_center_verified'])
            self.assertFalse(data['paid_generation_authorized']); self.assertFalse(data['upload_authorized'])
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('SELECTED', run.stdout)
            self.assertNotIn('OUTSIDE_AFTER', run.stdout)
            self.assertNotIn('OUTSIDE_BEFORE', run.stdout)

    def test_formal_release_rejects_unmatched_live_marker(self):
        manifest, digest = workflow_rules.check_local()
        with self.assertRaisesRegex(ValueError, 'Center and local release differ'):
            workflow_rules.verify_marker('<p>WF_RELEASE_JSON={"release_id":"old","manifest_sha256":"old"}</p>', manifest, digest)



if __name__ == '__main__':
    unittest.main()
