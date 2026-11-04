import tempfile,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import workflow_step
import workflow_node
class ResultRecoveryPlanTests(unittest.TestCase):
 def test_original_result_direct_path_and_guards_are_exposed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'scripts').mkdir();(root/'scripts/ryai.py').touch()
   implementation=root/'workflow/rules/implementation/rongyao-tools/skills/rongyao-ai-generator/scripts/ryai.py';implementation.parent.mkdir(parents=True);implementation.write_text("def recover_original_result(args): pass\nsub.add_parser('recover-original')")
   plan=workflow_step.execution_plan('A11','ab','SK012',root)['original_result_recovery']
   self.assertEqual(plan['download_argv'],['python3',str(root.resolve()/'scripts/ryai.py'),'recover-original','--input-sha256','{original_input_sha256}','--destination','{new_or_original_media_path}','--execute'])
   self.assertFalse(plan['executed']);self.assertFalse(plan['resubmit_allowed'])
   self.assertTrue(plan['requires_original_result_identity']);self.assertTrue(plan['verified_original_or_current_job_only'])
   self.assertEqual(plan['fallback'],'already-authorized native download, bounded by same two-attempt/30-second recovery policy')
 def test_missing_helper_never_borrows_other_workspace(self):
  with tempfile.TemporaryDirectory() as d:
   plan=workflow_step.execution_plan('A11','a','X',Path(d))['original_result_recovery']
   self.assertIsNone(plan['download_argv']);self.assertFalse(plan['interface_present'])
 def test_original_entry_shows_recovery_only_for_generation(self):
  for node in ('A10','A11','A12'):
   data=workflow_node.make_context(node,route='ab');text=workflow_node.text_context(data)
   self.assertIn('取回原任务：',text)
   self.assertIn('--destination',text)
   self.assertEqual(data['execution_boundary']['unknown_external_result'],'query_original_task_only')
   self.assertFalse(data['execution_boundary']['execution_plan']['original_result_recovery']['resubmit_allowed'])
   self.assertFalse(data['paid_generation_authorized']);self.assertFalse(data['upload_authorized'])
  for node in ('A01','A15'):
   text=workflow_node.text_context(workflow_node.make_context(node,route='ab'))
   self.assertNotIn('取回原任务：',text)
if __name__=='__main__': unittest.main()
