import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow_node as n
class RecoveryOutputTests(unittest.TestCase):
 def test_text_contains_failure_contract(self):
  d=n.make_context('A12');s=n.text_context(d)
  for v in d['contract']['failure'].values():self.assertIn(v,s)
  self.assertFalse(d['gate_pass_inferred'])
 def test_live_text_keeps_dependent_rollback_pending_sync_and_resume(self):
  d=n.make_context('B02');d['live_state']={'item':{'id':'fixture-B','action':'fixture action'},'dependency_items':[{'id':'fixture-parent','revalidation_required':['fixture rollback']}],'pending_sync':[{'target':'fixture mirror'}],'resume_key':'fixture-resume'}
  s=n.text_context(d)
  for v in ['fixture-parent','fixture rollback','fixture mirror','fixture-resume']:self.assertIn(v,s)
