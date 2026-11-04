#!/usr/bin/env python3
"""Read one live node and the next review boundary. Never performs production.

--timing-record reads an existing workflow-timing-v1 receipt: started_at,
optional finished_at, optional spans (kind=active/external_wait/user_review,
started_at, ended_at), final_delivery (path/sha256), and upload_readback
(status, material_id, file_sha256, source_ref, observed_at). Times require an
explicit timezone. The 300-second wall time includes review and service waits.
This report measures recorded times; it does not certify production acceptance.
"""
import argparse, datetime, json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TARGET_SECONDS=300
NODES={f'A{i:02}' for i in range(1,16)}|{f'B{i:02}' for i in range(1,6)}|{f'LIBRARY{i:02}' for i in range(1,5)}
def execution_plan(current,route,project_id=None,workspace=None):
    """Return argv plans for the selected workspace; never choose another deployment."""
    base=Path(workspace or ROOT).resolve()
    def source(name):
        path=base/'scripts'/name
        return path.read_text() if path.is_file() else ''
    content=source('console_content.py');template=source('console_template.py')
    batch_available="'--operations'" in content and 'def batch_patch(' in template
    compiler_source=source('production_order.py')
    compiler_available="'console-plan'" in compiler_source and 'def console_operations(' in compiler_source
    join_batch_available='join-batch' in compiler_source and 'b-join-batch-v1' in compiler_source
    manifest_path=base/'workflow/rules/manifest.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    unpublished=manifest.get('local_revision',{}).get('publication_status')=='local_maintenance_not_cloud_published'
    if current in ('A01','A02','A03'):phase='reference_creative'
    elif current.startswith('A') and int(current[1:])<=9:phase='script_prompts'
    elif current in ('A10','A11','A12'):phase='generation'
    elif current.startswith('LIBRARY'):phase='library_preparation'
    else:phase='postproduction_delivery'
    project=project_id or '{real_project_id}'
    operations='{current_operations_json}';receipt='{same_intent_receipt_json}'
    console=['python3',str(base/'scripts/console_content.py')]
    http_client=base/'workflow/tools/rongyao-http-upload/scripts/rongyao_upload.py'
    http_service=base/'workflow/tools/rongyao-http-upload/scripts/upload_service.py'
    http_available=http_client.is_file() and http_service.is_file()
    ai_impl=base/'workflow/rules/implementation/rongyao-tools/skills/rongyao-ai-generator/scripts/ryai.py'
    ai_source=ai_impl.read_text() if ai_impl.is_file() else ''
    recovery_available=(base/'scripts/ryai.py').is_file() and "sub.add_parser('recover-original'" in ai_source and 'def recover_original_result(' in ai_source
    producer=['python3',str(base/'scripts/production_order.py'),'console-plan','--root',str(base),'--project',project,'--record','{current_director_json}']
    check=console+['check','--project',project,'--operations',operations]
    patch=console+['patch','--project',project,'--operations',operations,'--receipt',receipt]
    reconcile=console+['check','--project',project,'--operations',operations,'--receipt',receipt]
    join_batch=['python3',str(base/'scripts/production_order.py'),'join-batch','--root',str(base),
        '--record','{current_join_batch_plan_json}','--receipt','{same_join_batch_receipt_json}']
    join_applicable=route=='ab' and current.startswith(('A','B'))
    post_steps=[
        {'id':'original_download','action':'Download the accepted original to its explicit destination; verify actual media and SHA.'},
        {'id':'original_content_qa','action':'Before PR or three variants, inspect actual action cause/result, identity and dialogue. Unknown audio remains unverified; failed required content blocks downstream production.'},
        {'id':'local_repair_if_needed','action':'Only if needed, use an existing authorized no-fee local edit and recheck affected content.',
            'preserve':'original file, source intervals, original audio with the moved shots and user PR edits',
            'new_paid_generation_authorized':False},
        {'id':'lock_current_a','action':'Bind current director revision, source intervals and current A path/SHA; invalidate old downstream artifacts if A changes.'},
        {'id':'premiere_native_a','action':'Export the locked current A once through the verified Premiere native route; read back its actual frames, duration and SHA. Reuse that one output for every B.'},
    ]
    if join_applicable:post_steps.append({'id':'join_batch','action':'One b-join-batch-v1 record for the requested existing B variants; use the same locked native A and bounded parallel local rendering. Candidates only.'})
    post_steps.extend([
        {'id':'checkpoint_3','action':'Stop for actual final videos, matching storyboard and complete visual/audio review. Rejected or unadopted files cannot proceed to upload.'},
        {'id':'single_upload_plan','action':'Only after CP3 and current authorization, bind adopted file SHAs into one plan.items upload plan for the requested files; query unknown results by the original job only.'},
    ])
    return {
        'schema':'workflow-execution-plan-v1','phase':phase,'cwd':str(base),'executed':False,
        'fixed_sequence':['reference_creative','script_prompts','generation','premiere_native_a']+(['join_batch'] if route=='ab' else [])+['final_video','upload_readback'],
        'side_effects_executed':[],'new_authorization_granted':False,
        'deployment_capability_gap':unpublished and (batch_available or compiler_available or join_batch_available),
        'deployment_policy':'Batch operations, director-to-batch compilation, join-batch and this entry plan require a matching published and installed release. Existing interface presence is not account, quota, host readiness or execution authorization.',
        'postproduction_pipeline':{
            'applicable':current.startswith(('A','B')),
            'sequence':post_steps,'native_a_exports_for_three_variants':1,
            'three_version_request':{'b_variants':3,'upload_plans':1,'upload_plan_items':3},
            'default_variant_count':None,'variant_count_source':'current explicit request; never create three variants merely because this plan describes that case',
            'current_a_sha_required':True,'changed_a_invalidates_existing_batch':True,
            'block_on_required_content_failure':True,'unknown_audio_remains_unverified':True,
            'review_checkpoint_after_node':'B04' if join_applicable else 'A14',
            'executed':False,'upload_authorized':False},
        'batch_postproduction':{
            'applicable':join_applicable,'available_in_selected_workspace':join_batch_available,
            'unpublished_candidate':unpublished,
            'status':'CAPABILITY_MISSING' if not join_batch_available else ('OFFLINE_CANDIDATE_ONLY' if unpublished else 'PLAN_REQUIRES_CURRENT_GUARDS'),
            'missing_capability_action':'Keep the selected fixed workspace; request a matching reviewed release. Never copy or fall back to maintenance/global renderers.' if not join_batch_available else None,
            'record_schema':'b-join-batch-v1','required_fields':['project_id','a_video','postproduction','a_acceptance','subtitles','bgm','bgm_gain','variants'],
            'required_proofs':['a_video','postproduction','a_acceptance','subtitles','bgm'],
            'proof_shape':{'path':'workspace-relative current file','sha256':'actual file SHA256'},
            'variant_fields':['id','b_source','output'],'variants_range':[1,3],'max_parallel_workers':3,
            'check_argv':join_batch if join_batch_available and join_applicable else None,
            'compile_argv':['python3',str(base/'scripts/production_order.py'),'join-plan','--root',str(base),'--record','{current_join_plan_input_json}'] if 'def join_plan(' in compiler_source and join_applicable else None,
            'execute_argv':join_batch+['--execute'] if join_batch_available and join_applicable else None,
            'extra_check_round_trip_required':False,
            'execution_policy':'Without --execute: local validation/probe only, no outputs or receipt writes. Execute once validates the same inputs before rendering; an extra separate preflight call is optional.',
            'requires':['current locked PR-native A SHA and actual video duration','original join-preview candidate guard for every variant','current same-version workspace and actual media/proofs'],
            'audio_policy':'Native A already contains its independent BGM. Only B continues the same BGM/gain from measured A video duration; ASS applies to A only.',
            'existing_output_policy':'Existing output or receipt is rejected; preserve completed files and inspect the original receipt. Never regenerate or overwrite to recover.',
            'partial_failure_policy':'Keep successful outputs and failures in the original batch receipt; inspect before any retry within existing authorized scope. Scope changes still require current authorization.',
            'auto_retry_failed_variants':False,'candidate_only':True,'final_review_required':True,
            'final_complete_audio_review_required':True,'upload_authorized':False,'executed':False},
        'native_control_recovery':{
            'same_goal_no_change_limit':2,'route_switch_resets_no_change_count':False,
            'fresh_ax':{'before_each_action':True,'target_by':'visible label','reuse_old_index':False,
                'action':'Read fresh AX, resolve the current visible label and verify the resulting state; indices from an older snapshot are not targets.'},
            'unchanged_web_click':{'fresh_recheck_count':1,'same_goal_no_change_limit':2,
                'actual_mouse_click':{'durationMs':120},
                'action':'If the default web click clearly had no effect, refresh AX and verify the same visible target once, then use the real mouse click with durationMs:120. Stop after two ineffective attempts for the same goal.',
                'require_confirmed_no_submission_before_retry':True,'retry_unknown_submit':False,
                'submission_exception':'If a send might have been accepted, query its original task/job; do not apply a second click or route switch as a resubmit.'},
            'same_window_connection':{'total_budget_ms':30000,'restart_budget_per_attempt':False,
                'budget_starts_at':'first control attempt for the same window and goal',
                'fallback_requires_existing_authorization':True,
                'action':'Use one cumulative control-failure budget per window/goal. Within 30 seconds stop the failed controller and switch automatically to the already authorized native route, preserving account, current input and guards. Do not spend a new 30 seconds on each repeated connection.',
                'missing_authorized_route':'Keep the affected action blocked; a timeout grants no new route, login or fee permission.'},
            'stale_generating_ui':{'action':'Reload or query the original task in the same session only; retain its ID and budget reservation.',
                'resubmit':False,'infer_service_wait_from_stale_ui':False,
                'timing_policy':'Classify stale UI/control failure separately from verified service waiting; all time remains in the end-to-end wall clock.'},
            'safe_refusal_bypass':False,'executed':False},
        'batch_console':{
            'available_in_selected_workspace':batch_available,'director_compiler_available':compiler_available,
            'unpublished_candidate':unpublished,'requires_verified_live_context_and_write_scope':True,
            'status':'CAPABILITY_MISSING' if not batch_available else ('OFFLINE_CANDIDATE_ONLY' if unpublished else 'PLAN_REQUIRES_CURRENT_GUARDS'),
            'missing_capability_action':'Keep the selected fixed workspace; request a matching reviewed release. Never copy or fall back to maintenance/global tools.' if not batch_available else None,
            'compile_director':{'applicable':phase=='script_prompts','available':compiler_available,
                'argv':producer if compiler_available else None,'stdout_to':operations,
                'output_policy':'create new local evidence or reuse identical bytes; preserve a different existing file',
                'requires':['current production-director-v1 record','matching project shot IDs/count and visible named slots'],
                'executed':False},
            'check_argv':check if batch_available else None,
            'patch_argv':patch if batch_available else None,
            'reconcile_argv':reconcile if batch_available else None,
            'parameters_to_resolve':['current_director_json','current_operations_json','same_intent_receipt_json']+([] if project_id else ['real_project_id']),
            'sequence':['compile current director once for this revision','one local check for the whole operations array','one patch for the same operations and receipt','on partial/unknown: reconcile the canonical batch; never resend'],
            'repeat_policy':'Reuse the current stage artifact. Do not rewrite unchanged cells or run an extra remote check per cell; patch performs its own snapshots/readback.',
            'scope':'Only known nonempty visible text slots. No stage/identity, new images, hidden columns or blank clearing. Changed inputs require revalidation.'},
        'parallel_read_only_preparation':[
            {'id':'b_source','read_only':True,'applicable':route=='ab','when':'before generation or while the original generation is running','requires':['A+B requested','existing selected B source'],
             'action':'Read only the selected B ID, source SHA and meaningful cut points; reserve its real duration. Do not rebuild/amend the library or trim/upload.',
             'argv':None,'executed':False},
            {'id':'premiere_status','read_only':True,'applicable':current.startswith('A') and current!='A15','when':'while the original generation is running','requires':['existing Premiere bridge'],
             'action':'Query the existing bridge; connection failure blocks dependent native work only. Do not start/reload it or open/save/export a project in parallel.',
             'argv':['python3',str(base/'workflow/tools/premiere-bridge/manage.py'),'status'] if (base/'workflow/tools/premiere-bridge/manage.py').is_file() else None,'executed':False},
            {'id':'upload_fields','read_only':True,'when':'while the original generation is running','requires':['existing authenticated target account','requested final scope'],
             'action':'Read current naming/ownership enums and existing submissions; prepare fields only. Preserve pending login and unknown jobs; no SMS, login retry, file selection or upload.',
             'argv':['python3',str(http_client),'fields','--session','{existing_http_session_id}','--gid','{actual_gid}','--source-type','{actual_type}'] if http_available else None,'executed':False}],
        'original_result_recovery':{
            'interface_present':recovery_available,
            'requires_original_result_identity':True,'verified_original_or_current_job_only':True,
            'requires':['original accepted task identity','live result from that task','authorized target destination'],
            'download_argv':['python3',str(base/'scripts/ryai.py'),'recover-original','--input-sha256','{original_input_sha256}','--destination','{new_or_original_media_path}','--execute'] if recovery_available else None,
            'watch_argv':['python3',str(base/'scripts/ryai.py'),'recover-original','--input-sha256','{original_input_sha256}','--destination','{new_or_original_media_path}','--execute','--wait-seconds','45','--existing-session-only','--deadline-at','{original_task_deadline_iso}'] if recovery_available and "'--wait-seconds'" in ai_source else None,
            'use_expected_sha256_when_known':True,
            'fallback':'already-authorized native download, bounded by same two-attempt/30-second recovery policy',
            'on_uncertain_or_absent_result':'query only original job; never guess URL, repeat generation or bypass refusal',
            'resubmit_allowed':False,'executed':False,'playback_or_acceptance_inferred':False},
        'http_upload_plan':{
            'available_in_selected_workspace':http_available,'interface':'plan.items',
            'grouping':'Use one approved HTTP plan containing every requested final file (three items for a three-version request); do not create one plan per file.',
            'requires':['final adopted file SHA for each item','current ownership fields','explicit upload scope and current ticket','existing authenticated HTTP session'],
            'submit_argv':['python3',str(http_client),'submit','--session','{existing_http_session_id}','--plan','{multi_item_upload_plan_json}','--workspace',str(base),'--authorization-ticket','{current_upload_ticket_json}'] if http_available else None,
            'reconcile_after_seconds':0,
            'first_readback':'Query the original job once immediately; if not listed, use its durable next_lookup_at/original processing interval and server Retry-After. No fixed idle sleep.',
            'reconcile_argv':['python3',str(http_client),'reconcile','--session','{existing_http_session_id}','--job-id','{original_upload_job_id}'] if http_available else None,
            'no_new_plan_or_resubmit_for_unknown':True,'executed':False,'upload_authorized':False},
        'serialized_guarded_actions':['paid generation submission','material upload submission','same-project console writes','Premiere native open/save/export'],
        'second_review_to_native_send':{
            'applies_only_to_generation_tool':'rongyao-ai-generator',
            'interface_present':(base/'scripts/ryai.py').is_file(),
            'review_bundle':['actual mode/model','ordered reference files with roles/names/SHA','current prompt and parameters','real quote and total budget including in-flight reservations','current input SHA, ticket and adoption evidence'],
            'approval_status':'not_verified_by_this_plan','reuse_only_same_approved_input':True,
            'native_submit_argv':['python3',str(base/'scripts/ryai.py'),'native-submit','--plan','{locked_native_plan_json}','--workspace',str(base),'--authorization-ticket','{current_input_ticket_json}','--budget-ledger','{project_budget_ledger_json}','--execute'] if (base/'scripts/ryai.py').is_file() else None,
            'executor':'same current execution owner from approved second review through the existing native-submit path',
            'on_ready':'After READY_FOR_ONE_NATIVE_SEND, recheck the observed page, send once and return actual acceptance evidence to the held CLI; do not hand off to a parent chat for duplicate confirmation.',
            'requires':['actual second review approval','same current input/ticket','current quote within remaining total cap','published matching workspace and native guard'],
            'unknown_result':'query the original job/task and keep budget reserved; never send again',
            'same_goal_gui_no_change_limit':2,'executed':False,'new_fee_or_adoption_authorized':False},
        'dreamina_canvas_submission':{
            'applies_only_to_generation_tool':'dreamina-canvas-cli',
            'available_in_selected_workspace':(base/'scripts/dreamina_workflow.py').is_file(),
            'entry':str(base/'scripts/dreamina_workflow.py'),
            'schema':'dreamina-workflow-plan-v1',
            'requires':['same published manifest and registered adapter','A12 live current item and unchanged approved Sheet/input files','same personal account and exact saved t2v draft/quote','current input SHA authorization ticket and existing project budget'],
            'submit_argv':['python3',str(base/'scripts/dreamina_workflow.py'),'submit','--plan','{approved_canvas_plan_json}','--authorization-ticket','{current_input_ticket_json}','--budget-ledger','{existing_project_budget_json}','--receipt','{original_canvas_receipt_json}'],
            'query_argv':['python3',str(base/'scripts/dreamina_workflow.py'),'query','--receipt','{original_canvas_receipt_json}'],
            'missing_adapter_action':'Keep paid submission blocked; prepare the same reviewed release, never run an unsealed candidate.',
            'unknown_result':'query original submit ID only; keep reservation',
            'executed':False,'new_fee_or_adoption_authorized':False},
        'first_original_qa_before_postproduction':{
            'when':'immediately after the first original is downloaded, before building PR/AB versions',
            'checks':['spatial/action cause and result, including projectile direction/contact','actual character and speaker attribution, complete dialogue','real media/decode, adopted intervals and continuity'],
            'allowed_to_prepare_postproduction':['passed content','explicitly marked unverified candidate'],
            'block_postproduction_on':'failed required content; identify the affected shot before requesting any authorized repair',
            'required_content_failure_blocks_even_candidate':True,
            'local_repair_before_native_export':True,'lock_current_a_before_native_export':True,
            'final_audio_and_user_adoption_remain_required':True,'executed':False},
        'artifact_reuse':{
            'download':'recover-original with destination already returns download/media/SHA/full-decode evidence; do not repeat verify-download for unchanged bytes',
            'native_export':'Use the original bridge export job as postproduction.native_export; output_sha256, saved_copy_sha256 and native result are already bound',
            'join_batch':'Execute validates itself; do not precede the same --execute with a separate join-batch check unless inputs actually need diagnosis',
            'current_input_revalidation_required':True,'semantic_acceptance_inferred':False},
        'task_clock':{'entry_option':'--timing-record <existing_workflow_timing_json>',
            'start_source':'original task started_at, including preparation and all review/service waits',
            'context_shows_elapsed_and_remaining':True,'restart_on_resume':False,'target_seconds':TARGET_SECONDS},
        'read_reuse':'Use the current context and reread only changed inputs.',
        'target_wall_seconds_including_upload':TARGET_SECONDS,'target_guaranteed':False,
        'clock_policy':'Reuse the existing attempt start time, including preparation/login, review and service waits. Never restart timing at submission or resumed context.',
    }

def boundary(current,requested,route=None,project_id=None,workspace=None):
    if current!=requested:raise ValueError('NODE_MISMATCH: requested node differs from the live Sheet; reconcile the Sheet before execution.')
    if current not in NODES:raise ValueError('UNKNOWN_NODE')
    if route is None:route='ab' if current.startswith('B') else 'a'
    if route not in ('a','ab'):raise ValueError('UNKNOWN_ROUTE')
    if current.startswith('B') and route!='ab':raise ValueError('B_NODE_REQUIRES_AB_ROUTE')
    checkpoints=[
        {'id':'reference_creative','after_node':'A03','review':'reference breakdown, creative candidates and minimal visual-text previews',
         'ready_before_review':['same-version A01 facts, judgments and unknowns','A02 borrowed core, applicable methods and differentiated candidates','A03 key visual text/actions/necessary dialogue for each candidate; user quantity overrides']},
        {'id':'script_prompts','after_node':'A09','review':'complete script, video prompts, bindings and current quoted budget',
         'ready_before_review':['complete storyboard and video prompts',
             'actual reference assets and B source/cut if applicable',
             'current model parameters, durations and layout',
             'current quote and remaining authorized budget',
             'subtitle, voice, music, variant count and requested upload scope']},
        {'id':'final_video','after_node':'B04' if route=='ab' else 'A14','review':'complete final video and matching storyboard; exact upload scope if requested'},
    ]
    stop=any(c['after_node']==current for c in checkpoints)
    return {
        'allowed_node':current,'route':route,'stop_after_current_node':stop,
        'auto_advance':False,'next_node_requires_user_request':False,
        'review_required_when':'checkpoint_output_ready_and_current_revision_not_adopted',
        'after_review_approval':'Continue the same revision within its approved scope without another continue request; keep runtime and node Gate checks.',
        'review_response':'A direct affirmative response to the presented checkpoint adopts that presented revision only. Do not ask for a second confirmation of it.',
        'review_changes':'Revalidate only changed content or newly missing authorization; do not reopen unchanged adopted creative or script.',
        'internal_checks_require_user_confirmation':False,
        'review_checkpoints':checkpoints,
        'continuation':'continue existing authorized scope after verified Gate and a new live context',
        'gate_pass_required_before_continuation':True,
        'read_live_context_before_each_node':True,
        'missing_authorization_blocks_affected_action':True,
        'high_risk_actions_require_current_runtime_guard':True,
        'cost_authorization_inherited_from_other_projects':False,
        'unknown_external_result':'query_original_task_only',
        'review_reuse':'reuse only approval of the same current input revision; changed input requires revalidation',
        'legacy_review_compatibility':{'prior_A02_adoption':'Preserve actual same-revision adoption; do not repeat unchanged creative approval merely because CP1 moved. Existing storyboards may supply preview evidence.',
            'new_preview':'Old adoption does not prove a newly added preview accepted. Check only actual changed/unreviewed content; node position is not adoption.',
            'existing_later_nodes':'Do not roll back, rewrite history or regenerate because of the rename/checkpoint move; retain pending revalidation.',
            'automatic_state_migration':False},
        'ab_before_final_review':'join-preview candidate only; original production Gate remains required',
        'production_contract_override':False,
        'target_wall_seconds_including_upload':TARGET_SECONDS,
        'target_guaranteed':False,
        'execution_plan':execution_plan(current,route,project_id,workspace),
    }

def timestamp(value):
    if not isinstance(value,str):raise ValueError('TIMESTAMP_REQUIRED')
    try:dt=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('INVALID_TIMESTAMP')
    if dt.tzinfo is None:raise ValueError('TIMESTAMP_TIMEZONE_REQUIRED')
    return dt

def union_seconds(spans):
    merged=[]
    for start,end in sorted(spans):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    return sum((end-start).total_seconds() for start,end in merged)

def timing_report(record,root=ROOT,observed_at=None):
    if not isinstance(record,dict) or record.get('schema')!='workflow-timing-v1':raise ValueError('TIMING_RECORD_REQUIRED')
    start=timestamp(record.get('started_at'))
    finished=record.get('finished_at')
    end=timestamp(finished) if finished else (observed_at or datetime.datetime.now(datetime.timezone.utc))
    if end.tzinfo is None or end<start:raise ValueError('INVALID_TIMING_RANGE')
    categories={k:[] for k in ('active','external_wait','user_review')}
    spans=record.get('spans',[])
    if not isinstance(spans,list):raise ValueError('TIMING_SPANS_REQUIRED')
    for span in spans:
        if not isinstance(span,dict):raise ValueError('TIMING_SPAN_REQUIRED')
        kind=span.get('kind')
        if kind not in categories:raise ValueError('UNKNOWN_TIMING_CATEGORY')
        begin=timestamp(span.get('started_at'));stop=timestamp(span.get('ended_at'))
        if not start<=begin<=stop<=end:raise ValueError('SPAN_OUTSIDE_WORKFLOW')
        categories[kind].append((begin,stop))
    upload=record.get('upload_readback',{})
    if not isinstance(upload,dict):raise ValueError('UPLOAD_READBACK_RECORD_REQUIRED')
    endpoints=False
    if upload.get('status')=='verified':
        import production_order
        delivery=record.get('final_delivery',{})
        production_order.proof(root,delivery)
        if not upload.get('material_id') or not upload.get('source_ref') or upload.get('file_sha256')!=delivery.get('sha256'):
            raise ValueError('UPLOAD_TIMING_BINDING_MISMATCH')
        if not finished or timestamp(upload.get('observed_at'))!=end:
            raise ValueError('FINISH_MUST_MATCH_UPLOAD_READBACK')
        endpoints=True
    elapsed=(end-start).total_seconds()
    return {
        'ok':True,'measurement':'recorded wall time; service waits and human review included',
        'elapsed_seconds':elapsed,'target_seconds':TARGET_SECONDS,
        'deadline_at':(start+datetime.timedelta(seconds=TARGET_SECONDS)).isoformat(),
        'elapsed_within_target':elapsed<=TARGET_SECONDS,
        'remaining_seconds':max(0,TARGET_SECONDS-elapsed),
        'category_seconds':{k:union_seconds(v) for k,v in categories.items()},
        'categories_can_overlap':True,
        'upload_status':upload.get('status','not_recorded'),
        'required_timing_endpoints_present':endpoints,
        'five_minute_pass_inferred':False,'production_acceptance_inferred':False,
        'overrun_action':'continue querying original task; never resubmit to meet deadline',
        'side_effects':[],
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--item');p.add_argument('--node');p.add_argument('--route',choices=['a','ab'],help='B nodes infer ab; choose ab for A nodes that will join B')
    p.add_argument('--condition',action='append',default=[]);p.add_argument('--timing-record')
    a=p.parse_args()
    try:
        if a.timing_record:
            if a.item or a.node or a.condition or a.route:p.error('--timing-record cannot be combined with live node arguments')
            print(json.dumps(timing_report(json.loads(Path(a.timing_record).read_text())),ensure_ascii=False,indent=2));return 0
        if not a.item or not a.node:p.error('--item and --node are required for live context')
        cmd=[sys.executable,str(ROOT/'scripts/workflow_node.py'),'context','--item',a.item,'--format','json']
        for flag in a.condition:cmd+=['--condition',flag]
        if a.route:cmd+=['--route',a.route]
        r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
        if r.returncode:print(r.stdout or r.stderr);return r.returncode
        d=json.loads(r.stdout)
        if d['node']!=a.node:raise ValueError('NODE_MISMATCH: requested node differs from the live Sheet; reconcile the Sheet before execution.')
        if 'execution_boundary' not in d:raise ValueError('EXECUTION_BOUNDARY_MISSING: use the matching workflow_node context entrypoint.')
        d['handoff_required']=['actual_output_links','completed_and_unverified','latest_source_revision','existing_external_task_ids_if_any','next_verified_node_or_review_checkpoint']
        print(json.dumps(d,ensure_ascii=False,indent=2));return 0
    except (ValueError,KeyError,TypeError,OSError) as e:
        print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
