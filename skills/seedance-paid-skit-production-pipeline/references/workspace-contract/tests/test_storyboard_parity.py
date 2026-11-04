import unittest,tempfile,json,copy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import storyboard_parity as sp
import console_template as ct
class ParityTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  self.script={'schema':'storyboard-parity-v1','source_ref':'feishu://fixture','revision':'1','shots':[{'id':'SC-01','characters':'鸣人','action':'回头','dialogue':'给我机会','camera':'中景固定','sound':'风声'},{'id':'B-01','characters':'鼬','action':'技能展示','dialogue':'培养鼬','camera':'游戏界面','sound':'游戏声音'}]}
  def file(n,b):
   p=self.root/n;p.write_bytes(b);return {'path':n,'sha256':sp.sha(p)}
  video=file('clip.mp4',b'isolated-fixture-not-real-media');probe=file('probe.json',json.dumps({'video_sha256':video['sha256'],'frames':20,'fps':10}).encode());image=file('frame.png',b'isolated-evidence')
  self.review={'schema':'storyboard-review-v1','script_sha256':sp.fingerprint(self.script),'observer':'isolated-test','observed_at':'2026-10-29','video':video,'probe':probe,'complete_audio_reviewed':True,'shots':[{'id':shot['id'],'in_frame':i*10,'out_frame':(i+1)*10,'expected_sha256':sp.fingerprint(shot),'actual_dialogue':shot['dialogue'],'frame_evidence':image,'checks':{f:{'status':'match','observation':'fixture only'} for f in sp.FIELDS}} for i,shot in enumerate(self.script['shots'])]}
 def check(self):return sp.inspect(self.root,self.script,self.review,self.script)
 def test_valid_coverage_never_claims_semantics(self):
  r=self.check();self.assertTrue(r['coverage_complete']);self.assertFalse(r['semantic_pass_inferred'])
 def test_user_edit_invalidates(self):
  new=copy.deepcopy(self.script);new['shots'][0]['dialogue']='改稿'
  with self.assertRaisesRegex(ValueError,'STORYBOARD_CHANGED'):sp.inspect(self.root,self.script,self.review,new)
  self.assertEqual(sp.changes(self.script,new)['changed'],['SC-01'])
 def test_missing_shot(self):
  self.review['shots'].pop()
  with self.assertRaisesRegex(ValueError,'MISSING_EXTRA'):self.check()
 def test_extra_tail(self):
  self.review['shots'][-1]['out_frame']=19
  with self.assertRaisesRegex(ValueError,'UNCOVERED'):self.check()
 def test_overlap_and_gap(self):
  for start in [9,11]:
   self.review['shots'][1]['in_frame']=start
   with self.assertRaisesRegex(ValueError,'FRAME_GAP'):self.check()
 def test_wrong_dialogue_is_not_accepted(self):
  self.review['shots'][0]['actual_dialogue']='错台词'
  self.assertFalse(self.check()['coverage_complete'])
 def test_unreviewed_audio_stays_pending(self):
  self.review['complete_audio_reviewed']=False;self.assertFalse(self.check()['coverage_complete'])
 def test_changed_video_rejected(self):
  (self.root/'clip.mp4').write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'STALE_OR_MISSING'):self.check()
 def test_reorder_and_remove_are_distinct(self):
  new=copy.deepcopy(self.script);new['shots'].reverse();self.assertTrue(sp.changes(self.script,new)['order_changed'])
  new['shots'].pop();self.assertEqual(sp.changes(self.script,new)['removed'],['SC-01'])
 def test_director_image_has_no_note_and_keeps_reference(self):
  contract=ct.contract_for({'template_id':ct.DIRECTOR_ID,'shot_count':1});old={'rich_text':[{'type':'link','text':'source','link':'https://example.com'}]}
  _,p=ct.plan_image(contract,'source_screenshots',0,old,{'type':'embed-image','image_token':'fixture'},'reference')
  self.assertIsNone(p['note']);self.assertIn(old['rich_text'][0],p['rich_text'])
if __name__=='__main__':unittest.main()
