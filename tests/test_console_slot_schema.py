import contextlib,copy,hashlib,json,os,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import console_template as c
import console_content as content
class SlotSchemaTests(unittest.TestCase):
 def setUp(self):self.contract=json.loads((ROOT/'workflow/console-template.json').read_text())
 def test_image_slot_rejects_plain_value(self):
  with self.assertRaisesRegex(ValueError,'SLOT_SCHEMA_MISMATCH'):c.plan_patch(self.contract,'characters',0,{}, {'value':'not-an-image'})
 def test_text_slot_rejects_formula(self):
  with self.assertRaisesRegex(ValueError,'SLOT_SCHEMA_MISMATCH'):c.plan_patch(self.contract,'script',None,{}, {'formula':'=1+1'})
 def test_notes_rejected_by_schema(self):
  with self.assertRaisesRegex(ValueError,'SLOT_SCHEMA_MISMATCH'):c.plan_patch(self.contract,'script',None,{}, {'value':'ok','note':'no'})
 def test_text_or_rich_text_allowed_for_text_slot(self):
  c.plan_patch(self.contract,'script',None,{}, {'value':'script'});c.plan_patch(self.contract,'script',None,{}, {'rich_text':[{'type':'text','text':'script'}]})
 def test_batch_transport_passes_the_checked_memory_bytes_on_stdin(self):
  raw='[{"shortcut":"+cells-set","input":{"range":"A1"}}]'
  response=subprocess.CompletedProcess([],0,json.dumps({'ok':True,'identity':'user','data':{}}),'')
  with patch.object(c.subprocess,'run',return_value=response) as run:c.cli(['sheets','+batch-update','--operations','-'],raw)
  self.assertEqual(run.call_args.kwargs['input'],raw)
  self.assertEqual(run.call_args.args[0][run.call_args.args[0].index('--operations')+1],'-')


class ConsoleBatchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
  self.config={'project_id':'TEST','spreadsheet_token':'fixture-only','sheet_id':'fixture-sheet'}
  self.contract={'slots':{'script':['A1','A2','A3'],'dialogue':['B1','B2','B3'],'video_prompt':['B1','B2','B3'],'current_node':'C3'},
   'slot_schemas':{key:{'allowed_representations':['value','rich_text'],'max_text_chars':12000,'notes_allowed':False} for key in ['script','dialogue','video_prompt']}}
  self.cloud={'revision':1,'ranges':[{'row_indices':[1,2,3],'col_indices':['A','B','C'],
   'cells':[[{'value':f'user-{col}{row}','cell_styles':{'background_color':'#FFF'}} for col in 'ABC'] for row in range(1,4)]}]}
  self.layout={'frozen_rows':2,'merged_cells':[]};self.receipt=self.root/'receipt.json';self.reads=0;self.sends=0
  self.apply_limit=None;self.send_error=False;self.readback_error=False;self.on_read=None;self.after_send=None
  self.ops=[{'slot':'script','index':0,'payload':{'value':'new script','note':None}},
            {'slot':'dialogue','index':1,'payload':{'value':'new dialogue','note':None}}]
  stack=contextlib.ExitStack();self.addCleanup(stack.close)
  stack.enter_context(patch.object(c,'ROOT',self.root));stack.enter_context(patch.object(content,'ROOT',self.root))
  stack.enter_context(patch.object(c,'resolve',return_value=self.config));stack.enter_context(patch.object(c,'contract_for',return_value=self.contract))
  self.check=stack.enter_context(patch.object(c,'check',side_effect=self.check_project))
  stack.enter_context(patch.object(c,'read',side_effect=self.read));stack.enter_context(patch.object(c,'cli',side_effect=self.send))
  stack.enter_context(patch.object(c,'validate',return_value={'ok':True,'project':'TEST','revision':1,'gate_pass_inferred':False}))
  stack.enter_context(patch.dict(os.environ,{'WORKFLOW_CONSOLE_DELEGATED':'1'}))
 def read(self,config):
  self.reads+=1
  if self.on_read:self.on_read(self.reads)
  if self.readback_error and self.sends:raise subprocess.TimeoutExpired('fixture-read',1)
  return copy.deepcopy(self.cloud),copy.deepcopy(self.layout)
 def check_project(self,project,local_only=False):
  before,layout=self.read(self.config)
  return {'ok':True},self.config,before,layout
 def apply(self,operations):
  for op in operations:
   coord=op['input']['range'];cell=self.cloud['ranges'][0]['cells'][int(coord[1:])-1][ord(coord[0])-65]
   payload=copy.deepcopy(op['input']['cells'][0][0])
   if set(payload)&{'value','rich_text','formula','multiple_values'}:
    for key in ['value','rich_text','formula','multiple_values']:cell.pop(key,None)
   cell.update(payload)
   if cell.get('note') is None:cell.pop('note',None)
  self.cloud['revision']+=1
 def send(self,args,input_payload=None):
  self.assertEqual(args[:2],['sheets','+batch-update']);self.sends+=1
  self.assertEqual(args[args.index('--operations')+1],'-');self.request=json.loads(input_payload)
  self.apply(self.request if self.apply_limit is None else self.request[:self.apply_limit])
  if self.after_send:self.after_send()
  if self.send_error:raise subprocess.TimeoutExpired('fixture-batch',1)
  return {'ok':True}
 def run_batch(self):return c.batch_patch('TEST',self.ops,self.receipt)
 def test_sparse_multi_field_write_preserves_manual_non_targets_and_uses_one_batch(self):
  before=copy.deepcopy(c.cells_by_coordinate(self.cloud));result=self.run_batch();after=c.cells_by_coordinate(self.cloud)
  self.assertEqual(result['batch_state'],'VERIFIED');self.assertEqual(self.sends,1);self.assertEqual(self.reads,3)
  self.check.assert_called_once_with('TEST',local_only=True)
  self.assertEqual([op['input']['range'] for op in self.request],['A1','B2'])
  for key in set(before)-{'A1','B2'}:self.assertEqual(after[key],before[key])
  self.assertEqual(after['A1']['cell_styles'],before['A1']['cell_styles'])
  self.run_batch();self.assertEqual(self.sends,1)
 def test_compiled_director_15_fields_take_one_transport_round(self):
  import production_order
  self.config.update(template_id=c.DIRECTOR_ID,shot_count=3)
  spec=self.root/'workflow/director-storyboard-template.json';spec.parent.mkdir(parents=True,exist_ok=True)
  spec.write_bytes((ROOT/'workflow/director-storyboard-template.json').read_bytes())
  contract=c.director_contract(self.config)
  self.cloud={'revision':1,'ranges':[{'row_indices':list(range(1,8)),'col_indices':list('ABCDEFGHIJ'),
   'cells':[[{'value':f'user-{col}{row}'} for col in 'ABCDEFGHIJ'] for row in range(1,8)]}]}
  record={'schema':'production-director-v1','purpose':'preproduction','scope':'A_only','project_id':'TEST',
   'source_ref':'synthetic performance fixture','revision':'r1','history_status':'before_generation',
   'shots':[{'id':f'SC-{i+1:02}','segment':'A','action':'raises hand','dialogue':'hello','original_copy':'',
    'camera':'fixed','sound':'dialogue','composition':'center','planned_seconds':4} for i in range(3)]}
  before=copy.deepcopy(c.cells_by_coordinate(self.cloud))
  with patch.object(c,'contract_for',return_value=contract):
   self.ops=production_order.console_operations(self.root,record,self.config)
   self.assertEqual(len(self.ops),15)
   self.run_batch()
  self.assertEqual((self.sends,self.reads),(1,3))
  after=c.cells_by_coordinate(self.cloud)
  # Original-copy and manually edited non-target cells stay untouched.
  for coord in ['F5','F6','F7','C3','J2']:self.assertEqual(before[coord],after[coord])
  self.assertEqual(len(self.request),15)
 def test_native_rich_text_derived_value_and_layout_revision_do_not_fail_verified_batch(self):
  self.layout['revision']=804
  self.ops[0]['payload']={'rich_text':[{'type':'link','text':'原片参考','link':'https://example.invalid/source'}],'note':None}
  def native_readback():
   cell=self.cloud['ranges'][0]['cells'][0][0]
   cell['value']=''.join(part['text'] for part in cell['rich_text'])
   self.layout['revision']=805
  self.after_send=native_readback
  result=self.run_batch()
  self.assertEqual(result['batch_state'],'VERIFIED');self.assertEqual(self.sends,1)
  journal=json.loads(self.receipt.read_text())
  self.assertTrue(journal['remote_outcome_confirmed']);self.assertFalse(journal['layout_changed'])
  self.assertEqual(journal['before_layout']['revision'],804)
  self.assertEqual(journal['after_layout']['revision'],805)
  # The same receipt is read again, never sent again.
  self.assertEqual(self.run_batch()['batch_state'],'VERIFIED');self.assertEqual(self.sends,1)
 def test_native_normalization_keeps_real_text_link_style_and_layout_conflicts(self):
  cases=['text','link','style','layout']
  original_cloud=copy.deepcopy(self.cloud);original_layout=copy.deepcopy(self.layout)
  for case in cases:
   with self.subTest(case=case):
    self.cloud=copy.deepcopy(original_cloud);self.layout=copy.deepcopy(original_layout)
    self.layout['revision']=804;self.receipt=self.root/(case+'-receipt.json')
    self.ops[0]['payload']={'rich_text':[{'type':'link','text':'原片参考','link':'https://example.invalid/'+case}],'note':None}
    def manual_edit(case=case):
     cell=self.cloud['ranges'][0]['cells'][0][0];cell['value']='原片参考';self.layout['revision']=805
     if case=='text':cell['value']='真实手改'
     if case=='link':cell['rich_text'][0]['link']='https://example.invalid/changed'
     if case=='style':cell['cell_styles']['background_color']='#000'
     if case=='layout':self.layout['frozen_rows']=3
    self.after_send=manual_edit
    isolated=self.root/case;isolated.mkdir();self.receipt=isolated/'receipt.json'
    with patch.object(c,'ROOT',isolated),patch.object(content,'ROOT',isolated):
     with self.assertRaisesRegex(ValueError,'BATCH_CONFLICT'):self.run_batch()
 def test_duplicate_real_cell_target_is_rejected_before_write(self):
  self.ops.append(copy.deepcopy(self.ops[0]))
  with self.assertRaisesRegex(ValueError,'DUPLICATE_BATCH_TARGET'):self.run_batch()
  self.assertEqual(self.sends,0);self.assertFalse(self.receipt.exists())
 def test_distinct_slot_aliases_cannot_write_the_same_cell_twice(self):
  self.contract['slots']['script_alias']=['A1','A2','A3'];self.contract['slot_schemas']['script_alias']=self.contract['slot_schemas']['script']
  self.ops.append({'slot':'script_alias','index':0,'payload':{'value':'same cell through another slot'}})
  with self.assertRaisesRegex(ValueError,'DUPLICATE_BATCH_TARGET'):self.run_batch()
  self.assertEqual(self.sends,0)
 def test_concurrent_manual_change_before_send_is_preserved(self):
  def change(count):
   if count==2:self.cloud['ranges'][0]['cells'][2][2]['value']='new manual note'
  self.on_read=change
  with self.assertRaisesRegex(ValueError,'Concurrent console change'):self.run_batch()
  self.assertEqual(self.sends,0);self.assertEqual(self.cloud['ranges'][0]['cells'][2][2]['value'],'new manual note')
  self.assertFalse(json.loads(self.receipt.read_text())['submission_attempted'])
 def test_existing_link_cannot_be_dropped_by_any_operation(self):
  self.cloud['ranges'][0]['cells'][0][0]={'rich_text':[{'type':'link','text':'original source','link':'https://example.invalid/original'}]}
  with self.assertRaisesRegex(ValueError,'drop existing'):self.run_batch()
  self.assertEqual(self.sends,0)
 def test_partial_timeout_is_reconciled_without_resending_and_can_observe_late_completion(self):
  self.apply_limit=1;self.send_error=True
  with self.assertRaisesRegex(ValueError,'BATCH_PARTIAL'):self.run_batch()
  journal=json.loads(self.receipt.read_text());self.assertEqual(journal['submission_error_type'],'TimeoutExpired')
  self.assertEqual([x['status'] for x in journal['target_observations']],['APPLIED','NOT_APPLIED'])
  with self.assertRaisesRegex(ValueError,'BATCH_PARTIAL'):self.run_batch()
  self.assertEqual(self.sends,1)
  self.apply(self.request[1:]);self.assertEqual(self.run_batch()['batch_state'],'VERIFIED');self.assertEqual(self.sends,1)
 def test_unknown_no_changes_and_unavailable_readback_never_reposts(self):
  self.apply_limit=0;self.send_error=True;self.readback_error=True
  with self.assertRaisesRegex(ValueError,'BATCH_OUTCOME_UNKNOWN'):self.run_batch()
  self.assertTrue(json.loads(self.receipt.read_text())['submission_attempted'])
  self.readback_error=False
  with self.assertRaisesRegex(ValueError,'BATCH_OUTCOME_UNKNOWN'):self.run_batch()
  self.assertEqual(self.sends,1)
 def test_non_target_manual_change_after_send_is_recorded_without_restoration(self):
  self.after_send=lambda:self.cloud['ranges'][0]['cells'][2][2].update(value='manual during batch')
  with self.assertRaisesRegex(ValueError,'BATCH_CONFLICT'):self.run_batch()
  journal=json.loads(self.receipt.read_text());self.assertEqual(journal['non_target_changes'],['C3'])
  self.assertEqual(self.cloud['ranges'][0]['cells'][2][2]['value'],'manual during batch')
  with self.assertRaisesRegex(ValueError,'BATCH_CONFLICT'):self.run_batch()
  self.assertEqual(self.sends,1)
 def test_later_target_hand_edit_does_not_reopen_a_confirmed_remote_outcome(self):
  self.run_batch();self.cloud['ranges'][0]['cells'][0][0]['value']='later legitimate manual edit'
  with self.assertRaisesRegex(ValueError,'BATCH_CONFLICT'):c.batch_patch('TEST',self.ops,self.receipt,reconcile_only=True)
  journal=json.loads(self.receipt.read_text());self.assertTrue(journal['remote_outcome_confirmed'])
  self.assertEqual(journal['target_observations'][0]['status'],'CONFLICT');content.ensure_no_pending_batch('TEST')
  self.assertEqual(self.cloud['ranges'][0]['cells'][0][0]['value'],'later legitimate manual edit');self.assertEqual(self.sends,1)
 def test_same_receipt_rejects_a_new_intent_and_preserves_original(self):
  self.run_batch();original=self.receipt.read_bytes();self.ops[0]['payload']['value']='a later edit'
  with self.assertRaisesRegex(ValueError,'BATCH_RECEIPT_INTENT_MISMATCH'):self.run_batch()
  self.assertEqual(self.receipt.read_bytes(),original);self.assertEqual(self.sends,1)
 def test_changed_stored_plan_cannot_change_a_recovered_write_or_verification(self):
  self.apply_limit=0;self.send_error=True
  with self.assertRaisesRegex(ValueError,'BATCH_OUTCOME_UNKNOWN'):self.run_batch()
  journal=json.loads(self.receipt.read_text());journal['operations'][0]['expected']['value']='edited receipt'
  self.receipt.write_text(json.dumps(journal))
  with self.assertRaisesRegex(ValueError,'BATCH_RECEIPT_CHANGED'):self.run_batch()
  self.assertEqual(self.sends,1)
 def test_existing_request_file_is_not_overwritten(self):
  request=self.receipt.with_suffix('.operations.json');request.write_text('manual earlier evidence')
  with self.assertRaisesRegex(ValueError,'BATCH_REQUEST_CHANGED'):self.run_batch()
  self.assertEqual(request.read_text(),'manual earlier evidence');self.assertEqual(self.sends,0)
 def test_batch_entry_preflights_each_slot_and_requires_each_prompt_review(self):
  for operations,error in [([{'slot':'script','index':0,'payload':{'value':'ASR result'}}],'CONSOLE_CONTENT_MISMATCH'),
   ([{'slot':'video_prompt','index':0,'payload':{'value':'visible prompt'}}],'PROMPT_REVIEW_REQUIRED'),
   ([{'slot':'current_node','payload':{'value':'15 已完成'}}],'reserved'),
   ([{'slot':'script','index':0,'payload':{'value':'text','comment':'corner marker'}}],'CONSOLE_NOTES_FORBIDDEN')]:
   with self.subTest(error=error),self.assertRaisesRegex(ValueError,error):content.prepare_operations('TEST',operations)
  self.assertEqual(self.sends,0)
 def prompt_operations(self):
  requirement=self.root/'requirement.txt';requirement.write_text('Synthetic current user requirement')
  proof={'path':requirement.name,'sha256':hashlib.sha256(requirement.read_bytes()).hexdigest()}
  heads=['全局视觉风格锁定','角色锁定','场景锁定','分段剧情','全局限制']
  body='\n'.join('## '+head+'\n测试正文' for head in heads);operations=[]
  for index in range(2):
   text=body+'\n'+str(index);review=self.root/f'prompt-review-{index}.json'
   review.write_text(json.dumps({'schema_version':1,'prompt_sha256':hashlib.sha256(text.encode()).hexdigest(),'current_user_requirement':proof,'format':'five_modules','mode':'original'}))
   operations.append({'slot':'video_prompt','index':index,'payload':{'value':text},'prompt_review':str(review)})
  return operations
 def test_each_prompt_uses_its_own_current_evidence_binding(self):
  operations=self.prompt_operations()
  self.assertEqual(len(content.prepare_operations('TEST',operations)),2)
  operations[1]['payload']['value']+=' changed after review'
  with self.assertRaisesRegex(ValueError,'PROMPT_REVIEW_STALE_OR_EMPTY'):content.prepare_operations('TEST',operations)
  self.assertEqual(self.sends,0)
 def test_parent_checked_prepared_bytes_cannot_be_swapped_before_helper_read(self):
  operations=self.root/'input.json';operations.write_text(json.dumps(self.ops))
  def delegate(args,**kwargs):
   prepared=Path(args[args.index('--payload')+1]);ops=json.loads(prepared.read_text())
   ops[0]['payload']['value']='ASR unreviewed replacement';prepared.write_text(json.dumps(ops))
   with patch.dict(os.environ,kwargs['env']):
    c.batch_patch('TEST',c.read_batch_operations(prepared,args[args.index('--expected-payload-sha256')+1]),args[args.index('--receipt')+1])
  with patch.object(sys,'argv',['console_content.py','patch','--project','TEST','--operations',str(operations),'--receipt',str(self.receipt)]), \
       patch.object(content.runtime,'mutation',return_value=contextlib.nullcontext()),patch.object(content.subprocess,'run',side_effect=delegate):
   with self.assertRaisesRegex(ValueError,'BATCH_PREPARED_INPUT_CHANGED'):content.main()
  self.assertEqual(self.sends,0)
 def test_helper_rechecks_prompt_source_after_parent_preflight(self):
  operations=self.root/'input.json';operations.write_text(json.dumps(self.prompt_operations()))
  @contextlib.contextmanager
  def changed_requirement(*args):
   (self.root/'requirement.txt').write_text('Changed current user requirement')
   yield
  def delegate(args,**kwargs):
   with patch.dict(os.environ,kwargs['env']):
    c.batch_patch('TEST',c.read_batch_operations(args[args.index('--payload')+1],args[args.index('--expected-payload-sha256')+1]),args[args.index('--receipt')+1])
  with patch.object(sys,'argv',['console_content.py','patch','--project','TEST','--operations',str(operations),'--receipt',str(self.receipt)]), \
       patch.object(content.runtime,'mutation',side_effect=changed_requirement),patch.object(content.subprocess,'run',side_effect=delegate):
   with self.assertRaisesRegex(ValueError,'PROMPT_REVIEW_SOURCE_CHANGED'):content.main()
  self.assertEqual(self.sends,0)
 def test_prompt_source_changed_during_sheet_guard_still_blocks_the_send(self):
  self.ops=content.prepare_operations('TEST',self.prompt_operations())
  def change(count):
   if count==2:(self.root/'requirement.txt').write_text('Changed during the Sheet guard read')
  self.on_read=change
  with self.assertRaisesRegex(ValueError,'PROMPT_REVIEW_SOURCE_CHANGED'):self.run_batch()
  self.assertEqual(self.sends,0);self.assertFalse(json.loads(self.receipt.read_text())['submission_attempted'])
 def test_mutable_request_file_cannot_redirect_the_stdin_batch_to_reserved_cells(self):
  def tamper(count):
   if count==2:
    path=self.receipt.with_suffix('.operations.json');ops=json.loads(path.read_text())
    ops[0]['input']['range']='C3';ops[0]['input']['cells']=[[{'value':'15 已完成'}]];path.write_text(json.dumps(ops))
  self.on_read=tamper
  with self.assertRaisesRegex(ValueError,'BATCH_REQUEST_CHANGED'):self.run_batch()
  self.assertEqual(self.sends,0);self.assertEqual(self.cloud['ranges'][0]['cells'][2][2]['value'],'user-C3')
 def test_new_receipt_cannot_resubmit_the_same_unknown_intent(self):
  self.apply_limit=0;self.send_error=True
  with self.assertRaisesRegex(ValueError,'BATCH_OUTCOME_UNKNOWN'):self.run_batch()
  original=json.loads(self.receipt.read_text())['canonical_journal'];self.receipt=self.root/'retry-new-receipt.json'
  with self.assertRaisesRegex(ValueError,'BATCH_OUTCOME_UNKNOWN'):self.run_batch()
  self.assertEqual(self.sends,1);self.assertEqual(json.loads(self.receipt.read_text())['canonical_journal'],original)
 def test_partial_batch_freezes_subset_extra_operations_and_all_new_project_writes(self):
  self.apply_limit=1;self.send_error=True
  with self.assertRaisesRegex(ValueError,'BATCH_PARTIAL'):self.run_batch()
  for operations in [[copy.deepcopy(self.ops[1])],self.ops+[{'slot':'script','index':2,'payload':{'value':'extra'}}]]:
   with self.subTest(operations=len(operations)),self.assertRaisesRegex(ValueError,'CONSOLE_BATCH_PENDING'):
    c.batch_patch('TEST',operations,self.root/f'new-intent-{len(operations)}.json')
  self.assertEqual(self.sends,1);self.assertEqual(len(list((self.root/'workflow/runtime/console-batches').glob('*.json'))),1)
  payload=self.root/'single.json';payload.write_text(json.dumps({'value':'single slot retry'}))
  for argv in [['console_content.py','patch','--project','TEST','--slot','script','--index','2','--payload',str(payload),'--receipt',str(self.root/'single-receipt.json')],
               ['console_content.py','image','--project','TEST','--slot','characters','--image','unused.png','--expected-sha256','f'*64,'--caption','fixture','--receipt',str(self.root/'image-receipt.json')]]:
   with self.subTest(command=argv[1]),patch.object(sys,'argv',argv), \
        patch.object(content.runtime,'mutation',return_value=contextlib.nullcontext()),patch.object(content.subprocess,'run') as invoke,patch.object(content,'mount_image_without_notes') as image:
    with self.assertRaisesRegex(ValueError,'CONSOLE_BATCH_PENDING'):content.main()
    invoke.assert_not_called();image.assert_not_called()
  content.ensure_no_pending_batch('A_DIFFERENT_PROJECT')
 def test_readonly_reconciliation_does_not_enter_mutation_or_resubmit_when_circuit_is_open(self):
  self.apply_limit=0;self.send_error=True
  with self.assertRaisesRegex(ValueError,'BATCH_OUTCOME_UNKNOWN'):self.run_batch()
  operations=self.root/'input.json';operations.write_text(json.dumps(self.ops))
  def delegate(args,**kwargs):
   self.assertIn('--reconcile-only',args)
   with patch.dict(os.environ,kwargs['env']):
    c.batch_patch('TEST',c.read_batch_operations(args[args.index('--payload')+1],args[args.index('--expected-payload-sha256')+1]),args[args.index('--receipt')+1],reconcile_only=True)
  with patch.object(sys,'argv',['console_content.py','check','--project','TEST','--operations',str(operations),'--receipt',str(self.receipt)]), \
       patch.object(content.runtime,'mutation',side_effect=AssertionError('write circuit must not be entered')), \
       patch.object(content.runtime,'ensure_release') as release,patch.object(content.runtime,'lock',return_value=contextlib.nullcontext()) as lock, \
       patch.object(content.subprocess,'run',side_effect=delegate):
   with self.assertRaisesRegex(ValueError,'BATCH_OUTCOME_UNKNOWN'):content.main()
  release.assert_called_once_with(True);lock.assert_called_once_with('console:TEST','console_write');self.assertEqual(self.sends,1)
 def test_original_public_entry_takes_one_project_lock_and_one_delegated_batch(self):
  operations=self.root/'input.json';operations.write_text(json.dumps(self.ops))
  def delegate(args,**kwargs):
   prepared=Path(args[args.index('--payload')+1]);receipt=args[args.index('--receipt')+1]
   with patch.dict(os.environ,kwargs['env']):c.batch_patch('TEST',c.read_batch_operations(prepared,args[args.index('--expected-payload-sha256')+1]),receipt,reconcile_only='--reconcile-only' in args)
   return subprocess.CompletedProcess(args,0)
  with patch.object(sys,'argv',['console_content.py','patch','--project','TEST','--operations',str(operations),'--receipt',str(self.receipt)]), \
       patch.object(content.runtime,'mutation',return_value=contextlib.nullcontext()) as mutation, \
       patch.object(content.runtime,'event') as event,patch.object(content.subprocess,'run',side_effect=delegate) as execute:
   content.main()
  mutation.assert_called_once_with('console_write','console:TEST');execute.assert_called_once();event.assert_called_once()
  self.assertEqual(self.sends,1);self.check.assert_called_once_with('TEST',local_only=True)

if __name__=='__main__':unittest.main()
