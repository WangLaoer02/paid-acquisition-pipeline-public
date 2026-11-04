"""Offline routing/state contracts; no semantic visual pass or business action inferred."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import workflow_node as node
import workflow_state as state

class MaterialPreparationTests(unittest.TestCase):
 def test_default_reads_do_not_require_image_skills_or_turnaround(self):
  for n in ('A04','A05','A06'):
   c=node.make_context(n)
   self.assertEqual(c['external_skills'],[])
   self.assertFalse(any(r['id'].startswith(('character-sheet.','character-format.')) for r in c['required_reads']))
   self.assertFalse(c['execution_boundary']['stop_after_current_node'])
   self.assertFalse(c['paid_generation_authorized']);self.assertFalse(c['upload_authorized'])
   self.assertFalse(c['gate_pass_inferred']);self.assertEqual(c['side_effects'],[])
 def test_identity_or_expression_gap_at_lookup_does_not_load_production_methods(self):
  for flag in ('identity-noise-repair','performance-traits','outfit-breakdown','blogger-identity','parallel-character-delivery'):
   c=node.make_context('A05',[flag]);keys={r['id'] for r in c['required_reads']}
   self.assertEqual(keys,{'material-preparation.02','material-preparation.04','reference-scope.02'})
   self.assertIn('不在A05制作新资产',node.text_context(c))
   self.assertEqual(c['contract']['after_pass']['next_node'],'A06')
  repair=node.make_context('A06',['identity-noise-repair'])
  self.assertIn('main.70',{r['id'] for r in repair['required_reads']})
  self.assertFalse({'character-format.13','character-format.14'} & {r['id'] for r in repair['required_reads']})
  traits=node.make_context('A06',['performance-traits'])
  self.assertIn('character-format.11',{r['id'] for r in traits['required_reads']})
  self.assertFalse({'character-format.13','character-format.14'} & {r['id'] for r in traits['required_reads']})
  self.assertFalse(repair['paid_generation_authorized'])
 def test_optional_turnaround_only_at_actual_lookup_or_gap_repair(self):
  for n in ('A05','A06'):
   keys={r['id'] for r in node.make_context(n,['character-turnaround'])['required_reads']}
   expected=([3,4,7,8] if n=='A05' else range(1,11))
   self.assertEqual({k for k in keys if k.startswith('character-sheet.')},{f'character-sheet.{i:02}' for i in expected})
  for n,flag in [('A04','character-turnaround'),('A05','unknown-asset-library')]:
   with self.assertRaises(node.WorkflowError):node.make_context(n,[flag])
 def test_single_source_fragments_and_text_are_current(self):
  idx=node.load(node.RULES/'policy-index.json')['policies'];lines=(node.RULES/'material-preparation.md').read_text().splitlines(keepends=True)
  for i in range(1,5):
   p,t=node.policy_text(f'material-preparation.{i:02}',idx)
   self.assertEqual(t,''.join(lines[p['source_line_start']-1:p['source_line_end']]))
   self.assertEqual(hashlib.sha256(t.encode()).hexdigest(),p['source_sha256'])
  for n in ('A04','A05','A06'):
   c=node.make_context(n);self.assertIn(c['label'],node.text_context(c))
 def test_no_extra_checkpoints_or_state_edges(self):
  graph=node.load(ROOT/'workflow/stages.json');self.assertEqual(sum(map(len,graph['families'].values())),24)
  for n,previous,next_node in [('A04','A03','A05'),('A05','A04','A06'),('A06','A05','A07')]:
   c=node.get_contract(n);self.assertEqual(c['depends_on'],[previous]);self.assertEqual(c['after_pass']['next_node'],next_node);self.assertFalse(c['after_pass']['automatic_side_effects'])
  for route,final in [('a','A14'),('ab','B04')]:
   points=node.make_context('A06',route=route)['execution_boundary']['review_checkpoints']
   self.assertEqual([p['after_node'] for p in points],['A03','A09',final])
 def test_exact_legacy_labels_preserve_raw_values_and_do_not_migrate(self):
  graph=node.load(ROOT/'workflow/stages.json');byid={x['id']:x for x in graph['families']['a']}
  sources=[{'spreadsheet_token':'fixture','sheet_id':'fixture','cell':'A1','role':'authority'},{'spreadsheet_token':'fixture','sheet_id':'fixture','cell':'B1','role':'mirror'}]
  binding={'id':'fixture','kind':'project','family':'a','sources':sources}
  for n,old in [('A04','04 角色正视母版'),('A05','05 三视图'),('A06','06 人物特征')]:
   observations={state.source_id(s):old for s in sources};snapshot={'sources':copy.deepcopy(observations),'items':{'fixture':{'current_node':old}}}
   for actual in [old,byid[n]['label']]:
    current=dict(observations);current[state.source_id(sources[0])]=actual
    result=state.plan([binding],current,snapshot,graph)
    self.assertFalse(result['conflicts']);self.assertEqual(result['writes'],[])
    self.assertEqual(result['items'][0]['current_node_id'],n);self.assertEqual(result['items'][0]['current_node'],actual)
    self.assertEqual(result['items'][0]['action'],'CONTINUE');self.assertFalse(result['items'][0]['gate_pass_inferred'])
   self.assertEqual(snapshot['sources'],observations)
 def test_unknown_similar_label_and_conflicting_edits_still_reject(self):
  graph=node.load(ROOT/'workflow/stages.json');sources=[{'spreadsheet_token':'fixture','sheet_id':'fixture','cell':'A1','role':'authority'},{'spreadsheet_token':'fixture','sheet_id':'fixture','cell':'B1','role':'mirror'}]
  b={'id':'fixture','kind':'project','family':'a','sources':sources};old={state.source_id(s):'05 三视图' for s in sources};snapshot={'sources':old,'items':{'fixture':{'current_node':'05 三视图'}}}
  for values in [('05 三视图新版','05 三视图新版'),('04 物料判断与分发','06 补充缺失资产')]:
   obs={state.source_id(s):v for s,v in zip(sources,values)};r=state.plan([b],obs,snapshot,graph)
   self.assertTrue(r['conflicts']);self.assertFalse(r['writes'])
 def test_declared_files_do_not_infer_visual_qa_or_adoption(self):
  c=node.get_contract('A06')
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'inputs.json';p.write_text(json.dumps({'schema_version':1,'release_id':c['release_id'],'node':'A06','inputs':[{'id':'A06.I01','status':'verified','source_ref':'fixture:no-gap-assertion'}]}))
   r=node.inspect_inputs('A06',p)
   self.assertFalse(r['complete']);self.assertFalse(r['semantic_truth_inferred'])

if __name__=='__main__':unittest.main()
