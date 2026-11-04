"""No network or uploads; exercise published routing and safe reporting boundaries."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT/'workflow/rules/implementation/backend-upload/skill'
spec = importlib.util.spec_from_file_location('upload_skill_entry', SKILL/'scripts/entry.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class UploadSkillEntryTests(unittest.TestCase):
    def test_existing_nodes_preserved_and_upload_is_conditional(self):
        contract, routes = entry.local_check(ROOT)
        self.assertEqual(len(routes['nodes']), 24)
        self.assertFalse(routes['upload_extension']['is_original_single_select_node'])
        self.assertEqual(routes['nodes']['A12']['upload_relation'], 'preparation_only_no_automatic_upload')
        self.assertFalse(routes['nodes']['A15']['gate_pass_inferred'])
        self.assertEqual(contract['reviewed_plan_count'], 14)

    def test_skill_byte_drift_fails_before_running_any_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'references').mkdir()
            (root/'references/contract.json').write_bytes((SKILL/'references/contract.json').read_bytes())
            with patch.object(entry, 'SKILL', root), patch.object(entry.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'SKILL_PACKAGE_MISMATCH'):
                    entry.local_check(ROOT)
                run.assert_not_called()

    def test_status_counts_only_receipts_and_does_not_echo_private_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);out = root/'evidence';out.mkdir()
            (out/'noise.json').write_text(json.dumps({'token':'DO_NOT_ECHO', 'status':'CONFIRMED'}))
            (out/'valid.json').write_text(json.dumps({'schema':'rongyao-video-list-fast-1',
                'status':'JOIN_ACK_PENDING_READBACK', 'token':'DO_NOT_ECHO'}))
            status = entry.public_status(root, {'public_receipts_path':'evidence','unverified_capabilities':[]})
            self.assertEqual(status['historical_receipt_counts'], {'JOIN_ACK_PENDING_READBACK':1})
            self.assertEqual(status['successful_new_uploads_this_invocation'], 0)
            self.assertNotIn('DO_NOT_ECHO', json.dumps(status))

    def test_contract_paths_reject_traversal(self):
        with self.assertRaisesRegex(ValueError, 'UNSAFE_CONTRACT_PATH'):
            entry.guarded(ROOT, '../outside.json')


if __name__ == '__main__':
    unittest.main()
