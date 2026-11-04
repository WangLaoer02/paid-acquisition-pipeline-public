"""No-charge behavioral checks; synthetic task responses are never production evidence."""
import copy
import contextlib
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hailuo_workflow', ROOT / 'scripts/hailuo_workflow.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HailuoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.runtime_guard=patch.object(module.runtime,'mutation',side_effect=lambda *a,**kw: contextlib.nullcontext())
        self.runtime_guard.start();self.addCleanup(self.runtime_guard.stop)
        # Isolated fixtures replace retired project files and actual production media.
        self.job = {'run_id':'TEST_ONLY','project_id':'SK002','a_product_id':'A_TEST',
                    'story_version':'V_TEST','segment':'A','prompt':'synthetic fixture',
                    'model':'MiniMax-Hailuo-2.3','project_console_url':'https://example.invalid/test','assets':[]}
        original_load = module.load
        def load_fixture(path):
            name = Path(path).name
            if name == 'hailuo.json': return {'default_model':'MiniMax-Hailuo-2.3','models':['MiniMax-H3','MiniMax-Hailuo-2.3'],'run_directory':'fixture-runs','output_directory':'fixture-outputs'}
            if name == 'state_bindings.json': return {'bindings':[{'id':'PROJECT:SK002:V011','family':'a','project_id':'SK002','version':'V011'}]}
            if name == 'stages.json': return {'families':{'a':[{'order':7,'label':'07 正式剧本'}]}}
            return original_load(path)
        mock_load = patch.object(module,'load',side_effect=load_fixture)
        mock_load.start(); self.addCleanup(mock_load.stop)
        self.job.update(purpose='production', story_version='V_TEST')
        self.job['approvals'] = dict.fromkeys(['current_rules_verified', 'upstream_gates_passed', 'account_and_quote_verified', 'paid_generation_authorized'], True)
        self.job['approvals']['evidence'] = [{'type': 'test_fixture', 'description': 'Synthetic approval; no live generation.'}]
        self.job['budget'] = {'unit': 'CNY', 'limit': 10, 'confirmed_spend': 0, 'in_flight_reserved': 0, 'this_task_maximum': 2}

    def test_unavailable_entitlement_never_calls_generate(self):
        with patch.object(module, 'read_rule_release', return_value={'test_fixture': True}), patch.object(module, 'doctor', return_value={'generation_ready': False}), patch.object(module, 'preview') as preview:
            with self.assertRaisesRegex(ValueError, 'entitlement'):
                module.submit(self.job)
            preview.assert_not_called()

    def test_budget_failure_precedes_paid_submission(self):
        self.job['budget']['in_flight_reserved'] = 9
        with self.assertRaisesRegex(ValueError, 'cap'):
            module.paid_checks(self.job, {'generation_ready': True})

    def test_changed_reference_and_wrong_model_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'first.png'
            image.write_bytes(b'actual bytes changed')
            self.job['assets'] = [{'role': 'first_frame', 'path': str(image), 'sha256': '0' * 64}]
            with self.assertRaisesRegex(ValueError, 'changed'):
                module.generate_args(self.job)
        self.job['assets'] = []
        self.job['parameters'] = {'duration': 10}
        with self.assertRaisesRegex(ValueError, 'H3 only'):
            module.generate_args(self.job)

    def test_unknown_acceptance_is_saved_and_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)), patch.object(module, 'read_rule_release', return_value={'test_fixture': True}), patch.object(module, 'doctor', return_value={'generation_ready': True}), patch.object(module, 'require_workflow_node', return_value={'test_fixture': True}), patch.object(module, 'preview', return_value={'request_sha256': 'test-only'}), patch.object(module, 'mmx', side_effect=RuntimeError('timeout')) as cli:
            with self.assertRaises(RuntimeError):
                module.submit(self.job)
            state = module.load(module.state_path(self.job))
            self.assertEqual(state['phase'], 'SUBMISSION_UNKNOWN')
            self.assertEqual(state['maximum_reserved'], 2)
            with self.assertRaisesRegex(ValueError, 'already'):
                module.submit(self.job)
            another = copy.deepcopy(self.job)
            another['run_id'] += '_NEW'
            with self.assertRaisesRegex(ValueError, 'claimed'):
                module.submit(another)
            self.assertEqual(cli.call_count, 1)

    def test_unverified_rule_release_stops_before_account_or_generation(self):
        with patch.object(module, 'read_rule_release', side_effect=ValueError('release mismatch')), patch.object(module, 'doctor') as doctor, patch.object(module, 'mmx') as cli:
            with self.assertRaisesRegex(ValueError, 'release mismatch'):
                module.submit(self.job)
            doctor.assert_not_called()
            cli.assert_not_called()

    def test_submit_requires_live_formal_generation_node(self):
        self.job['story_version'] = 'V011'
        result = {'observed_at': 'synthetic', 'conflicts': [], 'writes': [], 'items': [{'id': 'PROJECT:SK002:V011', 'current_node_id': 'A09', 'current_node': '09 生成准备', 'revalidation_required': []}]}
        with patch.object(module, 'read_workflow_state', return_value=result):
            with self.assertRaisesRegex(ValueError, '12 正式生成'):
                module.require_workflow_node(self.job)
            result['items'][0].update(current_node_id='A12', current_node='12 正式生成')
            check = module.require_workflow_node(self.job)
            self.assertFalse(check['gate_pass_inferred'])

    def test_upstream_rollback_prevents_generation_even_at_later_node(self):
        self.job['story_version'] = 'V011'
        result = {'observed_at': 'synthetic', 'conflicts': [], 'writes': [], 'items': [{'id': 'PROJECT:SK002:V011', 'current_node_id': 'A12', 'current_node': '12 正式生成', 'revalidation_required': ['07 正式剧本']}]}
        with patch.object(module, 'read_workflow_state', return_value=result):
            with self.assertRaisesRegex(ValueError, 'rollback'):
                module.require_workflow_node(self.job)

    def test_H3_query_preserves_returned_url_and_v2_model(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / 'state.json'
            module.save(state_path, {**{k: self.job[k] for k in ['run_id', 'project_id', 'story_version', 'segment']}, 'task_id': 'synthetic-test', 'model': 'MiniMax-H3', 'phase': 'SUBMITTED'})
            response = {'task_id': 'synthetic-test', 'status': 'succeeded', 'url': 'https://example.invalid/test.mp4'}
            with patch.object(module, 'mmx', return_value=response) as cli:
                result = module.query(state_path)
            self.assertEqual(result['phase'], 'GENERATION_SUCCEEDED')
            self.assertEqual(result['last_query']['url'], response['url'])
            self.assertEqual(cli.call_args.args[0][-2:], ['--model', 'MiniMax-H3'])
            self.assertFalse(cli.call_args.kwargs['quiet'])

    def test_pending_task_never_downloads_or_regenerates(self):
        with patch.object(module, 'query', return_value={'task_status': 'Processing'}), patch.object(module, 'mmx') as cli:
            with self.assertRaisesRegex(ValueError, 'not successful'):
                module.collect('synthetic-state')
            cli.assert_not_called()

    def test_file_download_uses_file_id_and_outputs_review_handoff(self):
        fixture = tempfile.TemporaryDirectory(); self.addCleanup(fixture.cleanup)
        source = Path(fixture.name)/'synthetic.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=64x64:d=0.2','-c:v','libx264',str(source)],check=True,capture_output=True)
        state = {**{k: self.job[k] for k in ['run_id', 'project_id', 'a_product_id', 'story_version', 'segment', 'project_console_url']}, 'task_id': 'synthetic-test', 'model': 'MiniMax-Hailuo-2.3', 'phase': 'GENERATION_SUCCEEDED', 'task_status': 'Success', 'last_query': {'file_id': 'synthetic-file'}}
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)), patch.object(module, 'query', return_value=state):
            def fake_download(args, quiet):
                self.assertEqual(args[2:4], ['--file-id', 'synthetic-file'])
                Path(args[-1]).write_bytes(source.read_bytes())
                return {'saved': args[-1]}
            path = Path(folder) / 'state.json'
            with patch.object(module, 'mmx', side_effect=fake_download):
                result = module.collect(path)
            self.assertTrue(result['media']['full_decode_passed'])
            self.assertEqual(result['media']['content_qa'], 'PENDING')
            handoff = module.load(Path(result['media']['path']).parent / 'raw_inputs.json')
            self.assertFalse(handoff['content_adopted'])
            self.assertFalse(handoff['replace_existing_premiere_media'])


if __name__ == '__main__':
    unittest.main()
