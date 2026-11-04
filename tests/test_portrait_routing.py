"""Regression for conditional packaging; synthetic inputs never authorize production."""
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import workflow_node as node
import workflow_rules as rules

class PortraitRoutingTests(unittest.TestCase):
    def test_source_policy_metadata_matches_actual_conditions(self):
        p=json.loads((ROOT/'workflow/rules/policy-index.json').read_text())['policies']['portrait-layout.01']
        self.assertEqual(p['required_for'],[])
        self.assertEqual(set(p['conditional_for']),{'B01:portrait-layout','B02:portrait-layout','B03:portrait-layout','B04:portrait-layout'})
        for key in p['conditional_for']:
            n=key.split(':')[0]
            c=node.get_contract(n);r=node.catalog()['nodes'][n]
            self.assertEqual(c['references'],r['required_policy_ids'])
            self.assertEqual(c['conditional_reads']['portrait-layout']['policy_ids'],r['conditional_policy_ids']['portrait-layout'])

    def test_missing_inputs_still_block_portrait_preparation(self):
        ctx=node.make_context('B02',['portrait-layout'])
        self.assertTrue(any(x['id']=='portrait-layout.01' for x in ctx['required_reads']))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'inputs.json'
            p.write_text(json.dumps({'schema_version':1,'node':'B02','release_id':ctx['release_id'],'inputs':[]}))
            result=node.inspect_inputs('B02',p)
            self.assertFalse(result['complete'])
            self.assertTrue(result['missing_or_unverified'])
        self.assertFalse(ctx['upload_authorized'])

    def test_new_project_not_given_sk005_music_instructions(self):
        for n in ('B01','B02','B03','B04'):
            ctx=node.make_context(n,['portrait-layout'])
            method=next(x['text'] for x in ctx['required_reads'] if x['id']=='portrait-layout.01')
            self.assertNotIn('本轮SK005',method)
            self.assertIn('未选定素材保持待选',method)
            self.assertIn('不重复',method)

    def test_existing_silent_a_keeps_current_audio_choice(self):
        ctx=node.make_context('A13',['nonpaid-previs'])
        method=next(x['text'] for x in ctx['required_reads'] if x['id']=='main.05')
        self.assertIn('无音轨A按已确认声音方案处理，不自行补配音或音乐',method)
        self.assertFalse(ctx['paid_generation_authorized'])
        self.assertFalse(ctx['gate_pass_inferred'])

    def test_stale_center_marker_remains_rejected(self):
        m,h=rules.check_local()
        xml='<p>WF_RELEASE_JSON='+json.dumps({'release_id':'WF20261011.2','manifest_sha256':h})+'</p>'
        with self.assertRaisesRegex(ValueError,'Center and local release differ'):rules.verify_marker(xml,m,h)

def route_case(n,portrait):
    def check(self):
        ctx=node.make_context(n,['portrait-layout'] if portrait else [])
        self.assertEqual(any(x['id']=='portrait-layout.01' for x in ctx['required_reads']),portrait)
        self.assertTrue(any(x['id']=='main.05' for x in ctx['required_reads']))
        self.assertEqual(ctx['side_effects'],[])
    return check
for n in ('B01','B02','B03','B04'):
    setattr(PortraitRoutingTests,'test_'+n+'_horizontal',route_case(n,False))
    setattr(PortraitRoutingTests,'test_'+n+'_portrait',route_case(n,True))
if __name__=='__main__':unittest.main()
