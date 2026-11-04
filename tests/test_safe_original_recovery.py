import importlib.util,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'workflow/rules/implementation/rongyao-tools/skills/rongyao-ai-generator/scripts/ryai.py'
spec=importlib.util.spec_from_file_location('recovery_test',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class SafeRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.digest='a'*64;self.ledger=patch.object(m,'GenerationLedger',return_value=SimpleNamespace(read=lambda digest:{'input_sha256':self.digest,'state':'submitted','task_id':'job-1'}));self.ledger.start();self.addCleanup(self.ledger.stop)
 def args(self): return SimpleNamespace(input_sha256=self.digest,destination='/fixture/result.mp4',expected_sha256=None,execute=True,return_result=False)
 def response(self): return {'ok':True,'data':{'task_id':'job-1','generation':{'status':'done','videos':[{'url':'https://example.invalid/result.mp4'}]}}}
 def test_live_read_matches_original_then_downloads_once_without_submitting(self):
  with patch.object(m,'dispatch',return_value=self.response()) as read,patch.object(m,'download_to_destination',return_value={'ok':True}) as dl,patch.object(m.subprocess,'run',side_effect=AssertionError('no subprocess')):
   result=m.recover_original_result(self.args())
  self.assertTrue(result['download_attempted']);self.assertEqual(read.call_args.args[0]['action'],'taskStatus');self.assertEqual(read.call_args.args[0]['query']['task_id'],'job-1');self.assertEqual(dl.call_count,1)
 def test_pending_wrong_id_and_ambiguous_results_fail_closed(self):
  for value in [{'ok':True,'data':{'task_id':'job-1','generation':{'status':'running'}}},{'ok':True,'data':{'task_id':'other','generation':{'status':'done','videos':[{'url':'https://example.invalid/a'}]}}},{'ok':True,'data':{'task_id':'job-1','generation':{'status':'done','videos':[{'url':'https://example.invalid/a'},{'url':'https://example.invalid/b'}]}}},0]:
   with self.subTest(value=value),patch.object(m,'dispatch',return_value=value),patch.object(m,'download_to_destination') as dl,patch.object(m.subprocess,'run',side_effect=AssertionError('no subprocess')):
    with self.assertRaises(ValueError):m.recover_original_result(self.args())
    dl.assert_not_called()
 def test_dry_run_never_downloads(self):
  a=self.args();a.execute=False
  with patch.object(m,'dispatch',return_value=self.response()),patch.object(m,'download_to_destination') as dl,patch.object(m.subprocess,'run',side_effect=AssertionError('no subprocess')):
   r=m.recover_original_result(a);self.assertFalse(r['download_attempted']);dl.assert_not_called()
if __name__=='__main__':unittest.main()
