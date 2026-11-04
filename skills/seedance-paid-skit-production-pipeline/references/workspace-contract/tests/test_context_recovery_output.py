import copy,hashlib,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'tests'))
import workflow_node as n
import workflow_step as step
class RecoveryOutputTests(unittest.TestCase):
 def test_structured_context_retains_failure_contract_with_concise_text(self):
  d=n.make_context('A12');s=n.text_context(d)
  self.assertEqual(d['contract']['failure'],n.get_contract('A12')['failure'])
  self.assertTrue(d['contract']['failure']);self.assertIn('取回原任务：',s)
  self.assertIn('未知受理只查原任务',s);self.assertFalse(d['gate_pass_inferred'])
 def test_live_text_keeps_dependent_rollback_pending_sync_and_resume(self):
  d=n.make_context('B02');d['live_state']={'item':{'id':'fixture-B','action':'fixture action'},'dependency_items':[{'id':'fixture-parent','revalidation_required':['fixture rollback']}],'pending_sync':[{'target':'fixture mirror'}],'resume_key':'fixture-resume'}
  s=n.text_context(d)
  for v in ['fixture-parent','fixture rollback','fixture mirror','fixture-resume']:self.assertIn(v,s)
 def test_source_and_completed_nodes_do_not_offer_unneeded_production_work(self):
  for node in ['A01','A15']:
   with self.subTest(node=node):
    data=n.make_context(node,route='ab');text=n.text_context(data);summary=text.split('\n## ',1)[0]
    for command in ['--operations','--execute','join-batch','native-submit']:
     self.assertNotIn(command,summary)
    for instruction in ['控件恢复：','后期顺序：','整批本地预检：','生成前或原任务等待期间并行只读：']:
     self.assertNotIn(instruction,summary)
    self.assertIn('batch_postproduction',data['execution_boundary']['execution_plan'])
    for gate in data['contract']['gate']:self.assertIn(gate['criterion'],text)
    self.assertEqual(data['contract']['gate'],n.get_contract(node)['gate'])
    for read in data['required_reads']:self.assertIn(read['text'],text)
 def test_postproduction_text_exposes_one_candidate_batch_and_bounded_native_recovery(self):
  data=n.make_context('A13',route='ab');text=n.text_context(data)
  commands=[line for line in text.splitlines() if 'production_order.py' in line and 'join-batch' in line and '--execute' in line]
  self.assertEqual(len(commands),1);self.assertIn('--record',commands[0]);self.assertIn('--receipt',commands[0])
  for value in ['核原片','PR原生导出一个A','FFmpeg批量接已有B','第三停点']:
   self.assertIn(value,text)
  flow=data['execution_boundary']['execution_plan']['postproduction_pipeline']
  self.assertLess([x['id'] for x in flow['sequence']].index('lock_current_a'),[x['id'] for x in flow['sequence']].index('premiere_native_a'))
  self.assertEqual(data['execution_boundary']['execution_plan']['native_control_recovery']['same_goal_no_change_limit'],2)
  self.assertFalse(data['paid_generation_authorized']);self.assertFalse(data['upload_authorized'])


class OriginalEntrypointTests(unittest.TestCase):
 def fixture(self,root):
  # Reuse the existing isolated release fixture, then add only selected nodes.
  # All hashes stay in this temporary workspace; no production manifest changes.
  import test_workflow_node as fixtures
  fixtures.NodeContractTests('test_offline_cli_cannot_claim_online_or_gate').offline_fixture(root)
  manifest=json.loads((root/'workflow/rules/manifest.json').read_text())
  index=n.load(n.RULES/'policy-index.json')['policies']
  files={'scripts/workflow_step.py','scripts/console_content.py','scripts/console_template.py','scripts/production_order.py',
   'workflow/tools/premiere-bridge/manage.py','workflow/tools/rongyao-http-upload/scripts/rongyao_upload.py','workflow/tools/rongyao-http-upload/scripts/upload_service.py'}
  for node in ['A02','A03','A08','A09','A14','B04']:
   contract=copy.deepcopy(n.get_contract(node));contract['release_id']=manifest['release_id']
   # This fixture isolates node boundaries; independent Skill resolution is exercised
   # by verify_packages against the fully installed sealed workspace.
   contract['required_external_skills']=[]
   target=root/n.catalog()['nodes'][node]['contract_path'];target.parent.mkdir(parents=True,exist_ok=True)
   target.write_text(json.dumps(contract))
   files.update('workflow/rules/'+path for path in contract['shared'])
   files.update('workflow/rules/'+index[key]['path'] for key in contract['references'])
  for name in files:
   target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
  manifest['workspace_contract_files']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
   for p in root.rglob('*') if p.is_file() and p.name!='manifest.json'}
  (root/'workflow/rules/manifest.json').write_text(json.dumps(manifest))
 def run_cli(self,root,command,node,*args):
  return subprocess.run([sys.executable,str(root/'scripts/workflow_node.py'),command,
   '--node',node,'--offline-preparation',*args],capture_output=True,text=True)
 def test_original_json_context_returns_three_review_points_with_no_business_authority(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root)
   for node,stop in [('A02',False),('A03',True),('A09',True),('A14',False),('B04',True)]:
    with self.subTest(node=node):
     r=self.run_cli(root,'context',node,'--route','ab','--format','json')
     self.assertEqual(r.returncode,0,r.stderr);d=json.loads(r.stdout)
     self.assertEqual(d['execution_boundary']['route'],'ab')
     self.assertEqual(d['execution_boundary']['stop_after_current_node'],stop)
     self.assertEqual([p['after_node'] for p in d['execution_boundary']['review_checkpoints']],['A03','A09','B04'])
     self.assertFalse(d['execution_boundary']['auto_advance']);self.assertIsNone(d['live_state'])
     self.assertFalse(d['release']['live_center_verified']);self.assertFalse(d['gate_pass_inferred'])
     self.assertFalse(d['paid_generation_authorized']);self.assertFalse(d['upload_authorized']);self.assertEqual(d['side_effects'],[])
 def test_original_text_context_contains_review_points_and_continuation_rule(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root)
   r=self.run_cli(root,'context','A14','--route','ab')
   self.assertEqual(r.returncode,0,r.stderr)
   for value in ['确认：①参考与创意','②完整剧本与提示词、引用及当前报价','③成片','B04','本版尚未采用','直接续跑','未核验当前线上发布']:
    self.assertIn(value,r.stdout)
 def test_status_and_resume_keep_the_same_boundary_and_b_family_default(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root)
   for command in ['status','resume']:
    with self.subTest(command=command):
     r=self.run_cli(root,command,'B04','--format','json')
     self.assertEqual(r.returncode,0,r.stderr);d=json.loads(r.stdout)
     self.assertEqual(d['execution_boundary']['review_checkpoints'],n.execution_boundary('B04')['review_checkpoints'])
     self.assertEqual(d['execution_boundary']['execution_plan']['cwd'],str(root.resolve()))
     self.assertTrue(d['execution_boundary']['stop_after_current_node'])
     self.assertFalse(d['paid_generation_authorized']);self.assertFalse(d['upload_authorized'])
 def test_b_scope_cannot_select_a_only_review_boundary(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root)
   r=self.run_cli(root,'context','B04','--route','a','--format','json')
   self.assertNotEqual(r.returncode,0);self.assertIn('B_NODE_REQUIRES_AB_ROUTE',r.stderr)
 def test_original_guard_rejects_modified_boundary_helper_even_offline(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root)
   helper=root/'scripts/workflow_step.py';helper.write_text(helper.read_text()+'\n# changed after fixture manifest\n')
   r=self.run_cli(root,'context','A02','--route','ab','--format','json')
   self.assertNotEqual(r.returncode,0);self.assertIn('differs from the published release',r.stderr)
   self.assertFalse(json.loads(r.stderr)['paid_generation_authorized'])
 def test_original_a08_entry_produces_executable_batch_argv_and_director_compiler_plan(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root)
   r=self.run_cli(root,'context','A08','--route','ab','--format','json')
   self.assertEqual(r.returncode,0,r.stderr);data=json.loads(r.stdout)
   plan=data['execution_boundary']['execution_plan'];batch=plan['batch_console']
   self.assertEqual(plan['phase'],'script_prompts');self.assertFalse(plan['executed'])
   self.assertIn('console-plan',batch['compile_director']['argv'])
   self.assertEqual(batch['compile_director']['stdout_to'],'{current_operations_json}')
   for key,command in [('check_argv','check'),('patch_argv','patch'),('reconcile_argv','check')]:
    self.assertIn(command,batch[key]);self.assertIn('--operations',batch[key]);self.assertTrue(Path(batch[key][1]).resolve().is_relative_to(root.resolve()))
   self.assertIn('--receipt',batch['patch_argv']);self.assertIn('--receipt',batch['reconcile_argv'])
   self.assertFalse(data['paid_generation_authorized']);self.assertFalse(data['upload_authorized'])
   text=self.run_cli(root,'context','A08','--route','ab')
   self.assertEqual(text.returncode,0,text.stderr)
   for value in ['当前稿编译：','console-plan','--operations','写前检查：','写回：']:
    self.assertIn(value,text.stdout)
 def test_original_a14_join_batch_command_reaches_real_cli_without_any_write(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root)
   result=self.run_cli(root,'context','A14','--route','ab','--format','json')
   self.assertEqual(result.returncode,0,result.stderr);data=json.loads(result.stdout)
   batch=data['execution_boundary']['execution_plan']['batch_postproduction']
   self.assertTrue(batch['available_in_selected_workspace']);self.assertFalse(batch['upload_authorized'])
   self.assertTrue(Path(batch['check_argv'][1]).resolve().is_relative_to(root.resolve()))
   missing=root/'absent-current-plan.json';receipt=root/'must-not-write.json'
   argv=[str(missing) if x=='{current_join_batch_plan_json}' else str(receipt) if x=='{same_join_batch_receipt_json}' else x for x in batch['check_argv']]
   files_before={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
   checked=subprocess.run(argv,cwd=root,capture_output=True,text=True)
   self.assertNotEqual(checked.returncode,0);self.assertNotIn('invalid choice',checked.stderr)
   self.assertNotIn('unrecognized arguments',checked.stderr);self.assertIn('absent-current-plan.json',checked.stdout+checked.stderr)
   self.assertEqual({str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()},files_before)
   self.assertFalse(receipt.exists());self.assertEqual(data['side_effects'],[])


class ExecutionPlanTests(unittest.TestCase):
 def test_a03_preview_has_first_checkpoint_without_script_compilation(self):
  d=n.make_context('A03',route='ab');plan=d['execution_boundary']['execution_plan']
  self.assertEqual(plan['phase'],'reference_creative');self.assertTrue(d['execution_boundary']['stop_after_current_node'])
  self.assertFalse(plan['batch_console']['compile_director']['applicable']);self.assertNotIn('console-plan',n.text_context(d))
 def test_canvas_route_is_explicit_in_both_json_and_concise_text(self):
  for node in ['A09','A10','A11','A12']:
   d=n.make_context(node);plan=d['execution_boundary']['execution_plan']
   self.assertEqual(plan['second_review_to_native_send']['applies_only_to_generation_tool'],'rongyao-ai-generator')
   self.assertEqual(plan['dreamina_canvas_submission']['applies_only_to_generation_tool'],'dreamina-canvas-cli')
   self.assertFalse(plan['dreamina_canvas_submission']['new_fee_or_adoption_authorized'])
   self.assertIn('scripts/dreamina_workflow.py',n.text_context(d));self.assertIn('Canvas服务端积分确认',n.text_context(d))

 def test_bound_project_is_used_without_guessed_sheet_or_per_cell_payload_files(self):
  data=n.make_context('A03',route='ab',project_id='fixture-PROJECT')
  batch=data['execution_boundary']['execution_plan']['batch_console']
  self.assertEqual(batch['check_argv'][batch['check_argv'].index('--project')+1],'fixture-PROJECT')
  self.assertEqual(batch['compile_director']['argv'][batch['compile_director']['argv'].index('--project')+1],'fixture-PROJECT')
  self.assertNotIn('--slot',batch['patch_argv']);self.assertNotIn('--index',batch['patch_argv'])
 def test_selected_legacy_workspace_missing_batch_never_borrows_candidate_helpers(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'scripts').mkdir();(root/'workflow/rules').mkdir(parents=True)
   (root/'scripts/console_content.py').write_text("# legacy single slot helper\n")
   (root/'scripts/console_template.py').write_text("def patch(): pass\n")
   (root/'workflow/rules/manifest.json').write_text(json.dumps({'release_id':'LEGACY'}))
   plan=step.boundary('A03','A03','ab',workspace=root)['execution_plan'];batch=plan['batch_console']
   self.assertEqual(plan['cwd'],str(root.resolve()));self.assertEqual(batch['status'],'CAPABILITY_MISSING')
   self.assertFalse(batch['available_in_selected_workspace']);self.assertIsNone(batch['patch_argv'])
   self.assertIsNone(batch['compile_director']['argv']);self.assertIn('Never copy or fall back',batch['missing_capability_action'])
 def test_candidate_plan_is_not_deployment_readiness_or_a_restarted_clock(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'scripts').mkdir();(root/'workflow/rules').mkdir(parents=True)
   for name in ['console_content.py','console_template.py','production_order.py']:shutil.copyfile(ROOT/'scripts'/name,root/'scripts'/name)
   (root/'workflow/rules/manifest.json').write_text(json.dumps({'release_id':'TEST','local_revision':{'publication_status':'local_maintenance_not_cloud_published'}}))
   plan=step.boundary('A03','A03','ab',workspace=root)['execution_plan']
   self.assertTrue(plan['deployment_capability_gap']);self.assertEqual(plan['batch_console']['status'],'OFFLINE_CANDIDATE_ONLY')
   self.assertEqual(plan['batch_postproduction']['status'],'OFFLINE_CANDIDATE_ONLY')
   self.assertFalse(plan['batch_postproduction']['upload_authorized']);self.assertFalse(plan['batch_postproduction']['executed'])
   self.assertFalse(plan['executed']);self.assertFalse(plan['new_authorization_granted']);self.assertFalse(plan['target_guaranteed'])
   self.assertEqual(plan['target_wall_seconds_including_upload'],300);self.assertIn('Never restart',plan['clock_policy'])
 def test_waiting_work_is_read_only_and_http_upload_reconciles_the_original_job_without_fixed_idle(self):
  plan=step.boundary('A12','A12','ab')['execution_plan']
  for task in plan['parallel_read_only_preparation']:
   self.assertTrue(task['read_only']);self.assertFalse(task['executed'])
   if task['argv']:
    for token in ['submit','--execute','start','--new-session']:self.assertNotIn(token,task['argv'])
  fields=next(task for task in plan['parallel_read_only_preparation'] if task['id']=='upload_fields')['argv']
  self.assertIn('rongyao-http-upload',fields[1]);self.assertEqual(fields[fields.index('--gid')+1],'{actual_gid}')
  self.assertNotIn('193',fields);self.assertIn('--session',fields)
  upload=plan['http_upload_plan'];self.assertEqual(upload['interface'],'plan.items');self.assertEqual(upload['reconcile_after_seconds'],0)
  self.assertIn('next_lookup_at',upload['first_readback']);self.assertIn('Retry-After',upload['first_readback'])
  self.assertIn('{original_upload_job_id}',upload['reconcile_argv']);self.assertFalse(upload['upload_authorized'])
  self.assertIn('one approved HTTP plan',upload['grouping']);self.assertTrue(upload['no_new_plan_or_resubmit_for_unknown'])
 def test_second_review_requires_real_bundle_same_owner_and_first_original_qa(self):
  plan=step.boundary('A09','A09','ab')['execution_plan'];handoff=plan['second_review_to_native_send']
  self.assertEqual(handoff['approval_status'],'not_verified_by_this_plan');self.assertTrue(handoff['reuse_only_same_approved_input'])
  self.assertFalse(handoff['new_fee_or_adoption_authorized']);self.assertIn('--authorization-ticket',handoff['native_submit_argv'])
  self.assertIn('--budget-ledger',handoff['native_submit_argv']);self.assertEqual(handoff['same_goal_gui_no_change_limit'],2)
  self.assertIn('same current execution owner',handoff['executor']);self.assertIn('do not hand off',handoff['on_ready'])
  qa=plan['first_original_qa_before_postproduction'];self.assertIn('before building PR/AB versions',qa['when'])
  self.assertIn('explicitly marked unverified candidate',qa['allowed_to_prepare_postproduction'])
  self.assertTrue(qa['final_audio_and_user_adoption_remain_required']);self.assertFalse(qa['executed'])
 def test_postproduction_sequence_locks_current_a_before_one_native_export_and_three_b(self):
  plan=step.boundary('A13','A13','ab')['execution_plan'];flow=plan['postproduction_pipeline']
  self.assertEqual([x['id'] for x in flow['sequence']],['original_download','original_content_qa','local_repair_if_needed','lock_current_a','premiere_native_a','join_batch','checkpoint_3','single_upload_plan'])
  self.assertEqual(flow['native_a_exports_for_three_variants'],1)
  self.assertEqual(flow['three_version_request'],{'b_variants':3,'upload_plans':1,'upload_plan_items':3})
  self.assertIsNone(flow['default_variant_count']);self.assertFalse(flow['executed'])
  self.assertEqual(flow['review_checkpoint_after_node'],'B04');self.assertFalse(flow['upload_authorized'])
  repair=flow['sequence'][2];self.assertFalse(repair['new_paid_generation_authorized'])
  self.assertIn('source intervals',repair['preserve']);self.assertTrue(flow['current_a_sha_required'])
  self.assertTrue(flow['block_on_required_content_failure']);self.assertTrue(flow['unknown_audio_remains_unverified'])
 def test_native_control_recovery_bounds_one_window_and_does_not_repeat_unknown_send(self):
  plan=step.boundary('A12','A12','ab')['execution_plan'];control=plan['native_control_recovery']
  self.assertEqual(control['same_goal_no_change_limit'],2);self.assertFalse(control['route_switch_resets_no_change_count'])
  self.assertTrue(control['fresh_ax']['before_each_action']);self.assertEqual(control['fresh_ax']['target_by'],'visible label')
  self.assertFalse(control['fresh_ax']['reuse_old_index'])
  click=control['unchanged_web_click'];self.assertEqual(click['fresh_recheck_count'],1)
  self.assertEqual(click['actual_mouse_click']['durationMs'],120);self.assertEqual(click['same_goal_no_change_limit'],2)
  self.assertTrue(click['require_confirmed_no_submission_before_retry']);self.assertFalse(click['retry_unknown_submit'])
  connection=control['same_window_connection'];self.assertEqual(connection['total_budget_ms'],30000)
  self.assertFalse(connection['restart_budget_per_attempt']);self.assertTrue(connection['fallback_requires_existing_authorization'])
  self.assertIn('same session',control['stale_generating_ui']['action']);self.assertFalse(control['stale_generating_ui']['resubmit'])
  self.assertFalse(control['stale_generating_ui']['infer_service_wait_from_stale_ui']);self.assertFalse(control['executed'])
 def test_join_batch_plan_uses_only_selected_workspace_and_retains_candidate_review(self):
  plan=step.boundary('A13','A13','ab')['execution_plan'];batch=plan['batch_postproduction']
  self.assertTrue(batch['available_in_selected_workspace']);self.assertTrue(batch['applicable'])
  self.assertEqual(batch['record_schema'],'b-join-batch-v1');self.assertEqual(batch['variants_range'],[1,3])
  self.assertEqual(batch['max_parallel_workers'],3);self.assertFalse(batch['extra_check_round_trip_required'])
  for command in ['check_argv','execute_argv']:
   argv=batch[command];self.assertIn('join-batch',argv);self.assertIn('--record',argv);self.assertIn('--receipt',argv)
   self.assertEqual(Path(argv[1]).resolve(),ROOT/'scripts/production_order.py')
   self.assertEqual(argv[argv.index('--root')+1],str(ROOT.resolve()))
  self.assertNotIn('--execute',batch['check_argv']);self.assertEqual(batch['execute_argv'],batch['check_argv']+['--execute'])
  self.assertTrue(batch['candidate_only']);self.assertTrue(batch['final_review_required']);self.assertTrue(batch['final_complete_audio_review_required'])
  self.assertFalse(batch['upload_authorized']);self.assertFalse(batch['executed']);self.assertFalse(batch['auto_retry_failed_variants'])
  self.assertIn('subtitles',batch['required_proofs']);self.assertIn('bgm',batch['required_proofs'])
 def test_legacy_or_a_only_route_cannot_borrow_or_run_batch_renderer(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'scripts').mkdir();(root/'workflow/rules').mkdir(parents=True)
   (root/'scripts/production_order.py').write_text('# legacy single-variant verifier\n')
   (root/'workflow/rules/manifest.json').write_text(json.dumps({'release_id':'LEGACY'}))
   batch=step.boundary('A13','A13','ab',workspace=root)['execution_plan']['batch_postproduction']
   self.assertFalse(batch['available_in_selected_workspace']);self.assertEqual(batch['status'],'CAPABILITY_MISSING')
   self.assertIsNone(batch['check_argv']);self.assertIsNone(batch['execute_argv']);self.assertIn('Never copy or fall back',batch['missing_capability_action'])
  plan=step.boundary('A13','A13','a')['execution_plan']
  self.assertFalse(plan['batch_postproduction']['applicable']);self.assertIsNone(plan['batch_postproduction']['execute_argv'])
  self.assertNotIn('join_batch',[x['id'] for x in plan['postproduction_pipeline']['sequence']])
  self.assertEqual(plan['postproduction_pipeline']['review_checkpoint_after_node'],'A14')


class RetiredSliceCoverageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.rules=Path(self.temp.name);self.archive=self.rules/'archive/WF20261010.5/source.md'
  self.archive.parent.mkdir(parents=True);self.original='# Original rule\n\nSee [asset](templates/project-config.json)\n'
  self.archive.write_text(self.original);self.lines=self.original.splitlines(keepends=True)
  (self.rules/'fragments').mkdir()
  self.current=self.rules/'fragments/source-01.md';self.current.write_text('# Current reviewed replacement\n')
  self.second=self.rules/'fragments/source-02.md';self.second.write_text('See [asset](../implementation/paid-skit-production-pipeline/templates/project-config.json)\n')
  digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
  self.coverage={'pieces':[{'id':'source.01','source':'source.md','start':1,'end':2,'source_sha256':digest(''.join(self.lines[:2]))},
   {'id':'source.02','source':'source.md','start':3,'end':3,'source_sha256':digest(self.lines[2])}],
   'retired_policies':{'source.01':{'path':'archive/WF20261010.5/source.md','sha256':digest(self.original),
    'start':1,'end':2,'source_sha256':digest(''.join(self.lines[:2])),
    'reason':'Explicit reviewed local rule replacement','replacement_release':'local-maintenance-20261101',
    'replacement_sha256':digest(self.current.read_text())}}}
  self.index={'policies':{key:{'path':str(path.relative_to(self.rules)),'sha256':digest(path.read_text())}
   for key,path in [('source.01',self.current),('source.02',self.second)]}}
 def check(self):
  (self.rules/'coverage.json').write_text(json.dumps(self.coverage));(self.rules/'policy-index.json').write_text(json.dumps(self.index))
  with patch.object(n,'RULES',self.rules):return n.check_coverage()
 def test_full_archived_source_slice_preserves_history_with_normalized_links(self):
  # Put the link-containing interval through the slice mode as well.
  self.coverage['retired_policies']['source.02']={**self.coverage['retired_policies']['source.01'],
   'start':3,'end':3,'source_sha256':self.coverage['pieces'][1]['source_sha256'],
   'replacement_sha256':self.index['policies']['source.02']['sha256']}
  result=self.check();self.assertEqual(result['business_rule_deletions'],0)
  self.assertEqual(result['retired_policy_count'],2);self.assertEqual(result['source_characters_preserved'],len(self.original))
 def test_wrong_slice_range_or_original_hash_is_rejected(self):
  record=self.coverage['retired_policies']['source.01'];original=copy.deepcopy(record)
  for key,value in [('start',2),('end',3),('source_sha256','0'*64),('path','archive/WF20261010.5/other.md')]:
   with self.subTest(field=key):
    record.clear();record.update(original);record[key]=value
    with self.assertRaises((ValueError,OSError)):self.check()
 def test_archive_file_changes_and_unregistered_current_replacement_are_rejected(self):
  self.archive.write_text(self.original+'changed archive tail\n')
  with self.assertRaisesRegex(ValueError,'historical evidence changed'):self.check()
  self.archive.write_text(self.original)
  self.current.write_text('# A later unregistered replacement\n')
  self.index['policies']['source.01']['sha256']=hashlib.sha256(self.current.read_bytes()).hexdigest()
  with self.assertRaisesRegex(ValueError,'not the registered current fragment'):self.check()
 def test_missing_slice_metadata_and_missing_retirement_record_are_rejected(self):
  del self.coverage['retired_policies']['source.01']['replacement_sha256']
  with self.assertRaisesRegex(ValueError,'coverage interval'):self.check()
  self.coverage['retired_policies']={}
  with self.assertRaisesRegex(ValueError,'lost or changed'):self.check()
 def test_original_independent_archived_fragment_mode_remains_compatible(self):
  path=self.rules/'archive/previous/source-01.md';path.parent.mkdir(parents=True)
  path.write_text(''.join(self.lines[:2]))
  self.coverage['retired_policies']['source.01']={
   'path':'archive/previous/source-01.md','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
   'reason':'Original independent historical fragment','replacement_release':'previous-local'}
  self.assertEqual(self.check()['business_rule_deletions'],0)
