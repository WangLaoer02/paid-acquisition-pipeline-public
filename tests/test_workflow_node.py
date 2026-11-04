"""Real contract/fragment reads and synthetic state faults; no network or external writes."""
import copy,hashlib,importlib.util,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import workflow_node as n
import workflow_state as state
import workflow_rules as rules

class NodeContractTests(unittest.TestCase):
    def test_review_locations_do_not_require_another_continue_after_approval(self):
        for route, final in [('a', 'A14'), ('ab', 'B04')]:
            for node in ['A03', 'A09', final]:
                boundary=n.make_context(node, route=route)['execution_boundary']
                self.assertTrue(boundary['stop_after_current_node'])
                self.assertFalse(boundary['next_node_requires_user_request'])
                self.assertEqual(boundary['review_required_when'], 'checkpoint_output_ready_and_current_revision_not_adopted')
                self.assertIn('same revision', boundary['after_review_approval'])
            review=boundary['review_checkpoints'][1]
            self.assertIn('current quote and remaining authorized budget', review['ready_before_review'])
            self.assertIn('actual reference assets and B source/cut if applicable', review['ready_before_review'])

    def test_list_points_unmatched_reference_to_existing_preparation_context(self):
        import contextlib, io
        output=io.StringIO()
        with patch.object(sys, 'argv', ['workflow_node.py', 'list']), contextlib.redirect_stdout(output):
            n.main()
        data=json.loads(output.getvalue())
        command=data['next_actions']['unmatched_new_reference']
        self.assertIn('--offline-preparation', command)
        self.assertIn('new-project', command)
        self.assertIn('A01', command)
        self.assertFalse(data['live_node_verified'])

    def test_daily_route_keeps_fixed_sequence_and_three_reviews(self):
        for route in ('a','ab'):
            data=n.make_context('A07',route=route)
            boundary=data['execution_boundary'];plan=boundary['execution_plan']
            expected=['reference_creative','script_prompts','generation','premiere_native_a']
            if route=='ab':expected.append('join_batch')
            expected+=['final_video','upload_readback']
            self.assertEqual(plan['fixed_sequence'],expected)
            self.assertEqual([x['id'] for x in boundary['review_checkpoints']],
                             ['reference_creative','script_prompts','final_video'])
            for removed in ('resumable_execution','readiness_bundle','fast_execution'):
                self.assertNotIn(removed,plan)

    def setUp(self):
        # Contracts ship without project state; tests must not depend on live bindings.
        def sources(name):
            return [{'spreadsheet_token':'fixture-only','sheet_id':name,'cell':cell,'role':role}
                    for cell,role in [('D1','authority'),('D2','mirror')]]
        fixture=[
            {'id':'SK003-A','project_id':'SK003','kind':'a','family':'a','sources':sources('three')},
            {'id':'SK002-A','project_id':'SK002','kind':'a','family':'a','sources':sources('two')},
            {'id':'SK002-B','project_id':'SK002','kind':'b','family':'b','parent':'SK002-A','b_asset':'fixture-B','sources':sources('b')},
            {'id':'LIB-B','kind':'library','family':'library','asset_name':'fixture-B','sources':sources('lib')},
        ]
        patched=patch.object(n,'bindings',side_effect=lambda:copy.deepcopy(fixture));patched.start();self.addCleanup(patched.stop)

    @unittest.skip("Author historical archive is intentionally excluded; current 24-node routing is verified separately")
    def test_complete_original_rule_coverage(self):
        v=n.check_coverage();self.assertEqual(v['source_module_count'],11);self.assertEqual(v['business_rule_deletions'],0);self.assertGreater(v['source_characters_preserved'],60000)
    @unittest.skip("Author historical archive is intentionally excluded; current 24-node routing is verified separately")
    def test_exact_original_node_id_label_order(self):
        old=n.load(ROOT/'workflow/rules/archive/WF20261010.5/manifest.json')
        route=n.catalog();graph=n.load(ROOT/'workflow/stages.json')
        self.assertEqual(len(route['nodes']),24)
        for fam,ns in graph['families'].items():
            self.assertEqual([x['order'] for x in ns],list(range(1,len(ns)+1)))
            for node in ns:self.assertEqual(route['nodes'][node['id']]['label'],node['label'])
    def test_conditions_are_not_loaded_until_selected(self):
        base=n.make_context('A07');extra=n.make_context('A07',['favoritism'])
        self.assertFalse(any(x['id'].startswith('copywriting.') for x in base['required_reads']))
        self.assertEqual(extra['external_skills'][0]['skill_id'],'naruto-favoritism-skit-generator')
        self.assertFalse(base['external_skills'])
    def test_unrelated_condition_is_rejected(self):
        with self.assertRaises(ValueError):n.make_context('A05',['backend-upload'])
    def test_duplicate_conditions_do_not_duplicate_reads(self):
        a=n.make_context('A07',['favoritism']);b=n.make_context('A07',['favoritism','favoritism'])
        self.assertEqual(a['required_reads'],b['required_reads'])
    def test_unknown_node_not_inferred(self):
        with self.assertRaises(ValueError):n.make_context('A99')
    def test_unknown_policy_not_inferred(self):
        with self.assertRaises(ValueError):n.policy_text('nonexistent',{})
    def test_path_escape_is_rejected(self):
        for value in ['../escape','/tmp/escape','']:
            with self.assertRaises(ValueError):n.inside(ROOT,value)
    def test_fragment_tamper_stops_before_any_network(self):
        idx=n.load(n.RULES/'policy-index.json')['policies'];key=next(iter(idx));bad=copy.deepcopy(idx);bad[key]['sha256']='0'*64
        with self.assertRaises(ValueError):n.policy_text(key,bad)
    def test_full_manual_policy_pointer_rejected(self):
        with self.assertRaises(ValueError):n.policy_text('x',{'x':{'path':'main.md'}})
    def test_character_and_prompt_catalogs_are_not_default_dump(self):
        for node in ['A05','A06','A09']:
            d=n.make_context(node)
            self.assertFalse(any(x['path'].endswith(('/main.md','/character-format.md','/video-prompts.md')) for x in d['required_reads']))
    def test_a05_reuses_adopted_boards_without_forcing_new_independent_images(self):
        d=n.make_context('A05',['character-turnaround']);c=d['contract'];reads={x['id']:x['text'] for x in d['required_reads']}
        policy=next(x['text'] for x in n.make_context('A06',['character-turnaround'])['required_reads'] if x['id']=='character-sheet.05')
        self.assertIn('已采用合板满足输入且跨视图QC通过时直接复用',policy)
        self.assertIn('只有当前任务或目标模型确需独立视图时',policy)
        self.assertIn('禁止裁切冒充原始独立生成',policy)
        self.assertNotIn('多图必须独立生成，禁止一次生成后裁切',policy)
        self.assertIn('合板或独立图满足实际需要直接复用',c['gate'][2]['criterion'])
        self.assertTrue(any('原件' in item for item in c['deliver']))
        graph=n.load(ROOT/'workflow/stages.json')
        listed=next(x for group in graph['families'].values() for x in group if x['id']=='A05')
        self.assertEqual(listed['required_output'],n.catalog()['nodes']['A05']['required_output'])
        self.assertFalse(d['paid_generation_authorized']);self.assertFalse(d['gate_pass_inferred'])

    def test_a05_reuse_preserves_identity_cross_view_alpha_and_adoption_checks(self):
        c=n.get_contract('A05');criteria={g['id']:g['criterion'] for g in c['gate']}
        self.assertEqual(list(criteria),['A05.G01','A05.G02','A05.G03','A05.G04'])
        self.assertTrue(all(g['evidence_required'] for g in c['gate']))
        d=n.make_context('A05',['character-turnaround'])
        reads={x['id']:x['text'] for x in d['required_reads']}
        for term in ['Identity','Geometry','Outfit','不对称']:
            self.assertIn(term,reads['character-sheet.04'])
        self.assertIn('Alpha',reads['character-sheet.07'])
        self.assertIn('黑白底',reads['character-sheet.07'])
        self.assertIn('合板内各面',reads['character-sheet.08'])
        self.assertIn('用户采用分开',criteria['A05.G04'])
        self.assertFalse(c['after_pass']['automatic_side_effects'])

    def test_a05_adopted_board_does_not_replace_actual_model_input_evidence(self):
        c=n.get_contract('A05')
        self.assertEqual([x['id'] for x in c['input_requirements']],['A05.I01','A05.I02'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'inputs.json'
            record={'schema_version':1,'release_id':c['release_id'],'node':'A05','inputs':[
                {'id':'A05.I01','status':'verified','source_ref':'fixture:adopted-board-and-original-sha'}]}
            path.write_text(json.dumps(record))
            r=n.inspect_inputs('A05',path);self.assertFalse(r['complete']);self.assertIn('A05.I02',r['missing_or_unverified'])
            record['inputs'].append({'id':'A05.I02','status':'verified'})
            path.write_text(json.dumps(record));self.assertFalse(n.inspect_inputs('A05',path)['complete'])
            record['inputs'][-1]['source_ref']='fixture:current-model-input-and-binding-observation'
            path.write_text(json.dumps(record));r=n.inspect_inputs('A05',path)
            self.assertFalse(r['complete']);self.assertIn('REFERENCE_CURRENT_SELECTION_AND_BINDING_REQUIRED',r['missing_or_unverified']);self.assertFalse(r['semantic_truth_inferred'])

    def test_a05_fragments_match_current_owning_source_ranges(self):
        index=n.load(n.RULES/'policy-index.json')['policies']
        source=(n.RULES/'character-sheet.md').read_text().splitlines(keepends=True)
        for key in [f'character-sheet.{i:02}' for i in range(1,11)]:
            policy,text=n.policy_text(key,index)
            self.assertEqual(policy['source_path'],'character-sheet.md')
            actual=''.join(source[policy['source_line_start']-1:policy['source_line_end']])
            self.assertEqual(actual,text,key)
            self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(),policy['source_sha256'],key)
    def test_b_uses_ffmpeg_not_a_pr_requirement(self):
        for node in ['B02','B03']:
            c=n.get_contract(node);self.assertIn('FFmpeg',' '.join(c['environment']))
            self.assertIn('FFmpeg',n.text_context(n.make_context(node)))
    def test_context_does_not_authorize_actions(self):
        d=n.make_context('A12');self.assertFalse(d['paid_generation_authorized']);self.assertFalse(d['upload_authorized']);self.assertFalse(d['gate_pass_inferred']);self.assertEqual(d['side_effects'],[])
    def test_ambiguous_project_requires_exact_item(self):
        with self.assertRaises(ValueError):n.select_item(None,'SK002')
    def test_unrelated_bindings_not_read(self):
        b=n.bindings();target=n.select_item(None,'SK003');selected=n.relevant_bindings(target,b)
        self.assertEqual([v['id'] for v in selected],[target['id']])
    def test_b_reader_includes_only_its_parent_and_own_asset(self):
        b=n.bindings();target=next(x for x in b if x['kind']=='b');selected=n.relevant_bindings(target,b)
        self.assertIn(target['id'],{x['id'] for x in selected});self.assertIn(target['parent'],{x['id'] for x in selected})
        self.assertTrue(all(x['kind']!='b' or x['id']==target['id'] for x in selected))
    def test_dependency_missing_fails_closed(self):
        with self.assertRaises(ValueError):n.relevant_bindings({'id':'B:x','parent':'missing'},[])
    def test_live_repeated_resume_has_no_writes(self):
        target=n.select_item(None,'SK003');chosen=[target];obs={state.source_id(s):'05 三视图' for s in target['sources']}
        checkpoint={'sources':obs.copy(),'items':{target['id']:{'current_node':'05 三视图'}}}
        real_load=n.load
        def loader(p):return checkpoint if p.name=='state_checkpoint.json' else real_load(p)
        with patch.object(state,'observe',return_value=obs) as observe,patch.object(n,'load',side_effect=loader),patch.object(state,'save') as save:
            a=n.live_state(target['id'],None);b=n.live_state(target['id'],None)
            self.assertEqual(a['resume_key'],b['resume_key']);self.assertEqual(a['item']['current_node_id'],'A05');self.assertFalse(a['automatic_writes']);self.assertEqual(a['pending_sync'],[]);save.assert_not_called()
            self.assertEqual([x['id'] for x in observe.call_args.args[0]],[target['id']])
    def test_conflicting_live_sources_do_not_retry_writes(self):
        target=n.select_item(None,'SK003');obs={state.source_id(s):('04 角色正视母版' if i==0 else '06 人物特征') for i,s in enumerate(target['sources'])}
        old={k:'05 三视图' for k in obs};checkpoint={'sources':old,'items':{target['id']:{'current_node':'05 三视图'}}}
        real_load=n.load
        with patch.object(state,'observe',return_value=obs),patch.object(n,'load',side_effect=lambda p:checkpoint if p.name=='state_checkpoint.json' else real_load(p)),patch.object(state,'save') as save:
            with self.assertRaises(ValueError):n.live_state(target['id'],None)
            save.assert_not_called()
    def offline_fixture(self, root):
        # A local test manifest is deliberately confined to a temporary workspace.
        # It never updates the published manifest or represents a production release.
        router = copy.deepcopy(n.catalog())
        contract = copy.deepcopy(n.get_contract('A05'))
        fixture_release = 'TEST_OFFLINE_ONLY'
        router['release_id'] = contract['release_id'] = fixture_release
        files = ['scripts/workflow_node.py', 'scripts/reference_scope.py', 'scripts/workflow_rules.py', 'scripts/workflow_step.py', 'workflow/rules/policy-index.json']
        index = n.load(n.RULES / 'policy-index.json')['policies']
        files += ['workflow/rules/' + name for name in contract['shared']]
        files += ['workflow/rules/' + index[key]['path'] for key in contract['references']]
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        (root / 'workflow/node_skills.json').write_text(json.dumps(router))
        target = root / router['nodes']['A05']['contract_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(contract))
        files += ['workflow/node_skills.json', router['nodes']['A05']['contract_path']]
        manifest = {'release_id': fixture_release, 'mode': 'standalone_feishu', 'external_rule_dependencies': [],
                    'modules': {}, 'implementation_files': {}, 'workspace_contract_files': {
                        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}}
        (root / 'workflow/rules/manifest.json').write_text(json.dumps(manifest))

    def test_offline_cli_cannot_claim_online_or_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.offline_fixture(root)
            r=subprocess.run([sys.executable,str(root/'scripts/workflow_node.py'),'context','--node','A05','--offline-preparation','--format','json'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr);d=json.loads(r.stdout);self.assertIsNone(d['live_state']);self.assertFalse(d['release']['live_center_verified']);self.assertFalse(d['gate_pass_inferred'])
            self.assertEqual(d['release']['release_id'], 'TEST_OFFLINE_ONLY')
            self.assertFalse(d['paid_generation_authorized']);self.assertFalse(d['upload_authorized'])

    def test_offline_fixture_still_rejects_changed_helper(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.offline_fixture(root)
            (root / 'scripts/workflow_node.py').write_text((root / 'scripts/workflow_node.py').read_text() + '\n# altered after fixture manifest\n')
            r=subprocess.run([sys.executable,str(root/'scripts/workflow_node.py'),'context','--node','A05','--offline-preparation','--format','json'],capture_output=True,text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('differs from the published release', r.stderr)
    def test_evidence_integrity_not_semantic_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);proof=root/'proof.txt';proof.write_text('synthetic recorded observation; not a user approval')
            c=n.get_contract('A05');record={'release_id':c['release_id'],'node':'A05','checks':[{'id':g['id'],'status':'pass','evidence':[{'path':'proof.txt','sha256':hashlib.sha256(proof.read_bytes()).hexdigest()}]} for g in c['gate']]};p=root/'evidence.json';p.write_text(json.dumps(record))
            with patch.object(n,'ROOT',root),patch.object(n,'get_contract',return_value=c):
                r=n.inspect_evidence('A05',p);self.assertFalse(r['ready_for_semantic_review']);self.assertIn('REFERENCE_CURRENT_SELECTION_AND_BINDING_REQUIRED',r['missing_or_not_passed']);self.assertFalse(r['gate_pass_inferred']);self.assertFalse(r['user_authorization_verified'])
                proof.write_text('changed')
                with self.assertRaises(ValueError):n.inspect_evidence('A05',p)

    def test_input_manifest_is_machine_checked_without_claiming_semantic_truth(self):
        c=n.get_contract('A05')
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root=Path(folder);proof=root/'input.txt';proof.write_text('synthetic input bytes')
            rel=str(proof.relative_to(ROOT))
            entries=[]
            for i,req in enumerate(c['input_requirements']):
                if i==0:
                    entries.append({'id':req['id'],'status':'verified','source_ref':'local:'+rel,'path':rel,'sha256':hashlib.sha256(proof.read_bytes()).hexdigest()})
                else:
                    entries.append({'id':req['id'],'status':'verified','source_ref':'synthetic:verified-nonfile'})
            m=root/'inputs.json';m.write_text(json.dumps({'schema_version':1,'release_id':c['release_id'],'node':'A05','inputs':entries}))
            r=n.inspect_inputs('A05',m);self.assertFalse(r['complete']);self.assertIn('REFERENCE_CURRENT_SELECTION_AND_BINDING_REQUIRED',r['missing_or_unverified']);self.assertFalse(r['semantic_truth_inferred'])
            proof.write_text('changed')
            with self.assertRaises(ValueError):n.inspect_inputs('A05',m)

    def test_missing_required_input_is_not_complete(self):
        c=n.get_contract('A05')
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            p=Path(folder)/'inputs.json';p.write_text(json.dumps({'schema_version':1,'release_id':c['release_id'],'node':'A05','inputs':[]}))
            r=n.inspect_inputs('A05',p);self.assertFalse(r['complete']);self.assertTrue(r['missing_or_unverified'])

    def test_missing_evidence_never_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'evidence.json';c=n.get_contract('A05');p.write_text(json.dumps({'node':'A05','release_id':c['release_id'],'checks':[]}));r=n.inspect_evidence('A05',p);self.assertFalse(r['ready_for_semantic_review']);self.assertTrue(r['missing_or_not_passed'])

def contract_case(node):
    def test(self):
        d=n.make_context(node);c=d['contract'];self.assertEqual(c['id'],node);self.assertTrue(c['gate']);self.assertTrue(c['read']);self.assertTrue(c['deliver']);self.assertTrue(c['environment']);self.assertTrue(c['input_requirements']);self.assertFalse(c['after_pass']['automatic_side_effects']);self.assertFalse(d['gate_pass_inferred']);self.assertLess(d['reading_characters'],8000 if node=='A13' else 6500) # A13 adds mandatory 1,366-character storyboard parity contract; no whole manual loaded.
        self.assertEqual(len(d['required_reads']),len({x['path'] for x in d['required_reads']}))
        self.assertFalse(any('/archive/' in x['path'] or x['path'].endswith('/main.md') for x in d['required_reads']))
        for flag in c['conditional_reads']:self.assertTrue(n.make_context(node,[flag])['ok'])
    return test
for node in n.catalog()['nodes']:setattr(NodeContractTests,'test_contract_'+node,contract_case(node))
if __name__=='__main__':unittest.main()
