import importlib.util,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
P=Path(__file__).resolve().parents[1]/'workflow/rules/implementation/rongyao-tools/skills/rongyao-ai-generator/scripts/ryai.py'
s=importlib.util.spec_from_file_location('id_test',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class NativeIdTests(unittest.TestCase):
 def test_visible_id_survives_interrupted_budget_and_blocks_repeat(self):
  with tempfile.TemporaryDirectory() as d:
   l=m.GenerationLedger(Path(d));digest='a'*64;l.reserve(digest,'model')
   receipt={'state':'submitted','task_id':'job-123'}
   m.persist_native_receipt(l,digest,receipt,'accepted task_id: job-123')
   l.update(digest,state='submission_unknown') # simulate crash after receipt, before budget commit
   l=m.GenerationLedger(Path(d)) # a new process would reconstruct the ledger from disk
   r=l.read(digest);self.assertEqual(r['task_id'],'job-123');self.assertEqual(r['state'],'submission_unknown')
   with self.assertRaisesRegex(ValueError,'GENERATION_ALREADY_REGISTERED'):l.reserve(digest,'model')
   with self.assertRaisesRegex(ValueError,'ORIGINAL_TASK_ID_CONFLICT'):m.persist_native_receipt(l,digest,{'state':'submitted','task_id':'job-456'},'task_id: job-456')
   self.assertEqual(l.read(digest)['task_id'],'job-123')
 def test_missing_id_never_guessed_and_unseen_id_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   l=m.GenerationLedger(Path(d));digest='b'*64;l.reserve(digest,'model')
   with self.assertRaisesRegex(ValueError,'NATIVE_TASK_ID_NOT_IN_EVIDENCE'):m.persist_native_receipt(l,digest,{'state':'submitted','task_id':'job-123'},'accepted, no id')
   m.persist_native_receipt(l,digest,{'state':'submitted'},'accepted, no id');self.assertIsNone(l.read(digest)['task_id'])
 def test_recovery_from_ledger_fails_closed_without_id(self):
  with tempfile.TemporaryDirectory() as d:
   l=m.GenerationLedger(Path(d));digest='c'*64;l.reserve(digest,'model');l.update(digest,state='submitted',task_id=None)
   a=SimpleNamespace(input_sha256=digest,destination='/fixture/result.mp4',expected_sha256=None,execute=True,return_result=False)
   with patch.object(m,'GenerationLedger',return_value=l),patch.object(m,'dispatch') as read,patch.object(m,'download_to_destination') as dl,patch.object(m.subprocess,'run',side_effect=AssertionError('no subprocess')):
    with self.assertRaisesRegex(ValueError,'ORIGINAL_TASK_ID_UNAVAILABLE'):m.recover_original_result(a)
    read.assert_not_called();dl.assert_not_called()
if __name__=='__main__':unittest.main()
