#!/usr/bin/env python3
"""Check the published project-console contract; write only named business slots."""
import argparse, copy, hashlib, json, os, re, struct, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'workflow/console-template.json'
COMPACT_ID='STORY-CONSOLE-COMPACT-1'
DIRECTOR_ID='DIRECTOR-STORYBOARD-1'
INCLUDE='value,formula,style,comment,data_validation'

def canonical_node_labels(values):
    if not isinstance(values,list):return None
    graph=json.loads((ROOT/'workflow/stages.json').read_text())
    aliases={label:node['label'] for nodes in graph['families'].values() for node in nodes for label in node.get('legacy_labels',[])}
    return [aliases.get(value,value) for value in values]


def contract_for(config):
    if config.get('template_id')==DIRECTOR_ID:return director_contract(config)
    legacy=json.loads(CONTRACT.read_text())
    if config.get('template_id')==legacy['template_id']:return legacy
    if config.get('template_id')==COMPACT_ID:
        return json.loads((ROOT/'workflow/console-compact-template.json').read_text())
    raise ValueError('Unregistered console template; maintenance must bind the approved template first.')

def director_contract(config):
    if config.get('layout_profile') == 'receiver-compact-2':
        return receiver_compact_contract(config)
    spec=json.loads((ROOT/'workflow/director-storyboard-template.json').read_text())
    count=config.get('shot_count')
    if type(count) is not int or not 1<=count<=spec['max_shots']:
        raise ValueError('Actual shot_count must be an integer from 1 to 100; do not add placeholder shots.')
    end=count+4; columns=spec['columns']
    labels={'A2':'来源','F2':'交付','I2':'当前阶段','A3':'补充','H3':'规则'}
    slots={'source':'B2','final_video':'G2','remarks':'B3','rules':'I3','current_node':'J2'}
    styles=[]
    for r in range(1,end+1):
        row=[]
        for col in columns:
            bg='#263D42' if r==1 else '#F2F4F4' if r<=3 else col['background']
            row.append({'cell_styles':{'background_color':bg,'font_color':'#FFFFFF' if r==1 else '#1D292D','font_size':12,'font_weight':'bold' if r in (1,4) else 'normal','horizontal_alignment':'left','vertical_alignment':'middle','number_format':'@'},'border_styles':{side:{'color':'#D7DEDF','style':'solid','weight':'thin'} for side in ('top','bottom','left','right')}})
            # Feishu omits normal weight on native readback; bold remains explicit.
            if r not in (1,4):row[-1]['cell_styles'].pop('font_weight')
        styles.append(row)
    for i,col in enumerate(columns):
        letter=chr(65+i);labels[letter+'4']=col['label']
        if col['key']=='shot_id':
            for n in range(count):labels[letter+str(n+5)]=f'SC-{n+1:02}'
        else:slots[col['key']]=[letter+str(n+5) for n in range(count)]
    schema={k:{'allowed_representations':['value','rich_text'],'max_text_chars':12000,'notes_allowed':False} for k in slots if k!='current_node'}
    widths=[]
    for i,col in enumerate(columns):
        letter=chr(65+i)
        if widths and widths[-1]['width']==col['width']:widths[-1]['cols']=widths[-1]['cols'].split(':')[0]+':'+letter
        else:widths.append({'cols':letter+':'+letter,'type':'custom','width':col['width']})
    return {'template_id':DIRECTOR_ID,'authority':spec['authority'],'range':f'A1:J{end}','fixed_labels':labels,'slots':slots,'slot_schemas':schema,'styles':styles,'identity_cell':'A1','layout_scope_rows':end,'initial_placeholders':[],'current_node_validation':spec['current_node_validation'],'state_binding':spec['state_binding'],'layout':{'column_widths':widths+[{'cols':'K:T','type':'default','width':105}],'row_heights':[{'rows':'1:1','type':'custom','height':42},{'rows':'2:3','type':'custom','height':48},{'rows':'4:4','type':'custom','height':44},{'rows':f'5:{end}','type':'custom','height':180}],'merged_cells':[{'range':x} for x in ['A1:J1','B2:E2','G2:H2','B3:G3','I3:J3']],'frozen_rows':4,'frozen_columns':0,'hidden_rows':[],'hidden_columns':[],'row_groups':[],'column_groups':[]}}

def receiver_compact_contract(config):
    count=config.get('shot_count')
    ids=config.get('shot_ids')
    if type(count) is not int or not 1<=count<=100 or not isinstance(ids,list) or len(ids)!=count or len(set(ids))!=count or any(not isinstance(x,str) or not re.fullmatch(r'SC-[0-9]{2,}',x) for x in ids):
        raise ValueError('Explicit unique stable shot_ids required for compact layout.')
    name=config.get('sheet_name','')
    if not name.startswith(config.get('project_id','')+'｜') or not config.get('project_id'):
        raise ValueError('Exact project sheet identity required.')
    height=config.get('shot_row_height',180)
    if type(height) is not int or not 60<=height<=500:raise ValueError('Invalid shot row height.')
    base=director_contract({**config,'layout_profile':None})
    c=copy.deepcopy(base);c['range']=f'A1:J{count+2}';c['layout_scope_rows']=count+2
    c['styles']=[copy.deepcopy(base['styles'][1]),copy.deepcopy(base['styles'][3])]+copy.deepcopy(base['styles'][4:4+count])
    c['fixed_labels']={'A1':'来源','F1':'交付','I1':'当前阶段'}
    spec=json.loads((ROOT/'workflow/director-storyboard-template.json').read_text())
    for i,col in enumerate(spec['columns']):
        letter=chr(65+i);c['fixed_labels'][letter+'2']=col['label']
        if col['key']=='shot_id':
            for n,shot in enumerate(ids):c['fixed_labels'][letter+str(n+3)]=shot
        else:c['slots'][col['key']]=[letter+str(n+3) for n in range(count)]
    c['slots'].update(source='B1',final_video='G1',current_node='J1')
    c['slots'].pop('remarks',None);c['slots'].pop('rules',None)
    c['identity_cell']=None;c['identity_sheet_name']=name
    c['state_binding']={'anchor_cell':'I1','cell':'J1','anchor_value':'当前阶段','identity_sheet_name':name}
    c['layout']['column_widths']=[{**x,'width':88} if x['cols']=='D:D' else x for x in c['layout']['column_widths']]
    c['layout'].update(row_heights=[{'rows':'1:1','type':'custom','height':48},{'rows':'2:2','type':'custom','height':44},{'rows':f'3:{count+2}','type':'custom','height':height}],merged_cells=[{'range':'B1:E1'},{'range':'G1:H1'}],frozen_rows=2)
    return c

def scoped_heights(rows,limit):
    result={}
    for item in rows:
        first,last=map(int,item['rows'].split(':'))
        for row in range(max(1,first),min(limit,last)+1):
            result[row]={k:v for k,v in item.items() if k!='rows'}
    return result

def cli(args,input_payload=None):
    extra={'input':input_payload} if input_payload is not None else {}
    r=subprocess.run(['lark-cli',*args,'--as','user'],cwd=ROOT,capture_output=True,text=True,timeout=55,**extra)
    d=json.loads(r.stdout or r.stderr)
    if '--dry-run' in args and r.returncode==0:return d
    if r.returncode or not d.get('ok') or d.get('identity')!='user':raise ValueError('Feishu operation failed: '+str(d.get('error',{})))
    return d['data']

def cells_by_coordinate(data):
    if data.get('has_more'):raise ValueError('Truncated console read.')
    out={}
    for r in data['ranges']:
        if r.get('truncated'):raise ValueError('Truncated console range.')
        for row_id,row in zip(r['row_indices'],r['cells']):
            for col,c in zip(r['col_indices'],row):out[col+str(row_id)]=c
    return out

def text(c):return c.get('value',''.join(x.get('text','') for x in c.get('rich_text',[])))

def validate(contract,data,layout,project):
    cells=cells_by_coordinate(data);errors=[]
    for key,value in contract['fixed_labels'].items():
        if text(cells.get(key,{}))!=value:errors.append('label:'+key)
    compact=contract.get('template_id') in (COMPACT_ID,DIRECTOR_ID)
    identity=contract.get('identity_cell','C17')
    identity_text=text(cells.get(identity,{}))
    valid_identity=(layout.get('sheet_name')==contract['identity_sheet_name'] and contract['identity_sheet_name'].startswith(project+'｜')) if contract.get('identity_sheet_name') else (identity_text.startswith(project+'｜') if compact else identity_text==project)
    if not valid_identity:errors.append('identity:'+(identity or 'sheet_name'))
    for ri,row in enumerate(contract['styles'],1):
        for ci,expected in enumerate(row):
            key=chr(65+ci)+str(ri)
            for field in ('cell_styles','border_styles'):
                if cells.get(key,{}).get(field,{})!=expected.get(field,{}):errors.append(field+':'+key)
    for key,expected in contract['layout'].items():
        actual=layout.get(key,0 if key.startswith('frozen_') else [])
        if compact and key=='row_heights':
            actual=scoped_heights(actual,contract['layout_scope_rows']);expected=scoped_heights(expected,contract['layout_scope_rows'])
        if compact and key=='merged_cells':
            actual={x['range'] for x in actual if min(map(int,re.findall(r'\d+',x['range'])))<=contract['layout_scope_rows']}
            expected={x['range'] for x in expected}
        if actual!=expected:errors.append('layout:'+key)
    node_coord=contract['slots']['current_node'];node=cells.get(node_coord,{});rule=node.get('data_validation',{})
    if rule.get('type')!='list' or rule.get('support_multiple_values',False) or canonical_node_labels(rule.get('items'))!=canonical_node_labels(contract['current_node_validation']['items']) or len(node.get('multiple_values',[]))>1:errors.append('single_node:'+node_coord)
    if canonical_node_labels([text(node)])[0] not in canonical_node_labels(contract['current_node_validation']['items']):errors.append('node_value:'+node_coord)
    if 'actual_ai' in contract['slots']:
        ai_coord=contract['slots']['actual_ai'];ai=cells.get(ai_coord,{}).get('data_validation',{})
        if ai.get('items')!=contract['actual_ai_validation']['items'] or ai.get('support_multiple_values') is not True:errors.append('ai:'+ai_coord)
    if errors:raise ValueError('CONSOLE_FORMAT_MISMATCH: '+', '.join(errors))
    return {'ok':True,'template_id':contract['template_id'],'project':project,'revision':data['revision'],'styles_checked':sum(map(len,contract['styles'])),'fixed_labels_checked':len(contract['fixed_labels']),'current_node':text(node),'gate_pass_inferred':False}

def resolve(project):
    p=(ROOT/'projects'/project/'console.json').resolve()
    if not p.is_relative_to(ROOT/'projects'):raise ValueError('Invalid project.')
    c=json.loads(p.read_text())
    if c.get('project_id')!=project:raise ValueError('Project identity differs from its registered config.')
    contract_for(c)
    return c

def sheet_args(config):return ['--spreadsheet-token',config['spreadsheet_token'],'--sheet-id',config['sheet_id']]

def read(config):
    args=sheet_args(config)
    return cli(['sheets','+cells-get',*args,'--range',contract_for(config)['range'],'--include',INCLUDE]),cli(['sheets','+sheet-info',*args,'--include','merges,row_heights,col_widths,hidden_rows,hidden_cols,groups,frozen'])

def check(project,local_only=False):
    if not local_only:
        # The complete release manifest seals this contract and this helper.
        r=subprocess.run([sys.executable,str(ROOT/'scripts/workflow_rules.py'),'check'],cwd=ROOT,capture_output=True,text=True,timeout=60)
        if r.returncode:raise ValueError('Published rule/contract release is unavailable or differs from local files.')
    c=resolve(project);d,l=read(c)
    return validate(contract_for(c),d,l,project),c,d,l

def slot_coordinate(contract,slot,index):
    if slot in ('current_node','identity'):raise ValueError('State/identity are reserved; use workflow_state or coordinated migration.')
    value=contract['slots'].get(slot)
    if value is None:raise ValueError('SLOT_NOT_DISPLAYED: no such visible slot in this profile; retain execution details in project evidence instead of restoring removed management fields.')
    if isinstance(value,list):
        if index is None or not 0<=index<len(value):raise ValueError('Choose an actual slot index.')
        return value[index]
    if index is not None:raise ValueError('Scalar slot has no index.')
    return value

def reference_set(cell):
    return {(x['type'],x.get('image_token') or x.get('attachment_token') or x.get('link')) for x in cell.get('rich_text',[]) if x['type'] in ('embed-image','attachment','link')}

def plan_patch(contract,slot,index,old,payload):
    coord=slot_coordinate(contract,slot,index)
    schema=contract.get('slot_schemas',{}).get(slot)
    if not schema:raise ValueError('Missing slot schema; maintenance must publish a reviewed schema before writing.')
    if not payload or set(payload)-{'value','formula','rich_text','multiple_values','note'}:raise ValueError('A business patch cannot modify styles, labels, layout or validation.')
    if payload.get('rich_text') == []:raise ValueError('EMPTY_RICH_TEXT_UNSUPPORTED: use explicit value empty string; do not repeat an unknown write.')
    reps=set(payload)&{'value','formula','rich_text','multiple_values'}
    if len(reps)>1:raise ValueError('Choose exactly one content representation.')
    result=copy.deepcopy(old)
    if reps:
        for k in ('value','formula','rich_text','multiple_values'):result.pop(k,None)
    result.update(payload)
    # Preserve the older, stronger invariant first: a type mismatch may never hide that the patch would drop a real attachment/link.
    if reference_set(old)-reference_set(result):raise ValueError('Patch would drop existing attachments/links; retain the refs or coordinate an explicit replacement with maintenance.')
    if reps and not reps.issubset(set(schema['allowed_representations'])):raise ValueError('SLOT_SCHEMA_MISMATCH: representation is not allowed for '+slot)
    visible=str(payload.get('value',''))+''.join(str(x.get('text','')) for x in payload.get('rich_text',[]) if isinstance(x,dict))
    if len(visible)>schema.get('max_text_chars',50000):raise ValueError('SLOT_SCHEMA_MISMATCH: content exceeds slot limit.')
    if schema.get('notes_allowed') is False and payload.get('note') not in (None,''):raise ValueError('SLOT_SCHEMA_MISMATCH: notes are forbidden.')
    return coord,result

def patch(project,slot,index,payload,receipt):
    result,config,before,layout=check(project);contract=contract_for(config)
    coord=slot_coordinate(contract,slot,index);old=cells_by_coordinate(before)[coord]
    _,expected=plan_patch(contract,slot,index,old,payload)
    guard,guard_layout=read(config)
    if guard!=before or guard_layout!=layout:raise ValueError('Concurrent console change; reread before writing.')
    p=Path(receipt).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('Receipt must stay within this workspace.')
    p.parent.mkdir(parents=True,exist_ok=True)
    # Keep complete before refs even if the network write has an unknown outcome.
    p.write_text(json.dumps({'slot':slot,'cell':coord,'before':old,'payload':payload,'state':'PREPARED'},ensure_ascii=False,indent=2)+'\n')
    temp=p.with_suffix('.payload.json');temp.write_text(json.dumps([[payload]],ensure_ascii=False))
    cli(['sheets','+cells-set',*sheet_args(config),'--range',coord,'--cells','@./'+str(temp.relative_to(ROOT))])
    after,after_layout=read(config);validation=validate(contract,after,after_layout,project);new=cells_by_coordinate(after)
    for key,c in cells_by_coordinate(before).items():
        if key!=coord and new[key]!=c:raise ValueError('Non-target cell changed: '+key)
    if any(new[coord].get(k)!=v for k,v in payload.items() if k!='value' or 'rich_text' not in payload):raise ValueError('Payload readback differs; do not retry blindly.')
    p.write_text(json.dumps({'slot':slot,'cell':coord,'before':old,'payload':payload,'after':new[coord],'validation':validation,'state':'VERIFIED'},ensure_ascii=False,indent=2)+'\n')
    return validation

def batch_targets(contract,operations):
    if not isinstance(operations,list) or not operations:raise ValueError('Nonempty operations array required.')
    targets=[];seen=set()
    for op in operations:
        if not isinstance(op,dict) or set(op)-{'slot','index','payload','prompt_review','prompt_review_sha256'} or not isinstance(op.get('slot'),str) or not isinstance(op.get('payload'),dict):
            raise ValueError('Each operation requires slot/index/payload only.')
        index=op.get('index')
        if index is not None and type(index) is not int:raise ValueError('Operation index must be an integer.')
        coord=slot_coordinate(contract,op['slot'],index)
        if coord in seen:raise ValueError('DUPLICATE_BATCH_TARGET: '+coord)
        seen.add(coord);targets.append({**op,'cell':coord})
    return targets

def _batch_save(path,journal,receipt=None):
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf-8') as stream:
        json.dump(journal,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)
    if receipt is not None and receipt!=path:_batch_save(receipt,journal)

def read_batch_operations(path,expected_sha256):
    raw=Path(path).read_bytes()
    if not expected_sha256 or hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('BATCH_PREPARED_INPUT_CHANGED: helper input differs from the checked bytes.')
    return json.loads(raw)

def _batch_cell(cell):
    # Native readback may add plain text derived from the exact rich-text runs.
    # Only that exact duplicate is metadata; differing text/links/styles remain.
    result={k:v for k,v in cell.items() if k!='note' or v is not None}
    runs=result.get('rich_text')
    if isinstance(runs,list) and runs and all(isinstance(part,dict) and isinstance(part.get('text'),str) for part in runs):
        if result.get('value')==''.join(part['text'] for part in runs):result.pop('value',None)
    return result

def _batch_layout(layout):
    # The Sheet revision changes on every successful content write. Retain it
    # in evidence, but compare the actual layout fields rather than its clock.
    return {k:v for k,v in layout.items() if k!='revision'}

def _batch_readback(project,contract,journal,after,after_layout,path,receipt):
    old=cells_by_coordinate(journal['before']);current=cells_by_coordinate(after)
    targets={op['cell'] for op in journal['operations']};observations=[]
    for op in journal['operations']:
        cell=current.get(op['cell'],{})
        status='APPLIED' if _batch_cell(cell)==_batch_cell(op['expected']) else ('NOT_APPLIED' if _batch_cell(cell)==_batch_cell(op['before']) else 'CONFLICT')
        observations.append({'slot':op['slot'],'index':op.get('index'),'cell':op['cell'],'status':status})
    non_targets=[key for key in set(old)|set(current) if key not in targets and _batch_cell(current.get(key,{}))!=_batch_cell(old.get(key,{}))]
    journal.update(after=after,after_layout=after_layout,target_observations=observations,non_target_changes=sorted(non_targets),layout_changed=_batch_layout(after_layout)!=_batch_layout(journal['before_layout']))
    conflicts=non_targets or journal['layout_changed'] or any(x['status']=='CONFLICT' for x in observations)
    complete=all(x['status']=='APPLIED' for x in observations)
    # Later manual edits invalidate current content, not an already-observed terminal outcome.
    journal['remote_outcome_confirmed']=journal.get('remote_outcome_confirmed') is True or journal.get('state')=='VERIFIED' or complete
    journal['state']='CONFLICT' if conflicts else ('VERIFIED' if complete else ('PARTIAL' if any(x['status']=='APPLIED' for x in observations) else 'OUTCOME_UNKNOWN'))
    if complete and not conflicts:
        try:journal['validation']=validate(contract,after,after_layout,project)
        except ValueError:
            journal['state']='CONFLICT';_batch_save(path,journal,receipt);raise
    _batch_save(path,journal,receipt)
    if journal['state']!='VERIFIED':raise ValueError('BATCH_'+journal['state']+': use check --operations with this intent and receipt to reconcile; never resubmit automatically.')
    return {**journal['validation'],'batch_state':'VERIFIED','targets':len(observations),'submission_attempted':journal.get('submission_attempted',False),'resubmitted':False,'canonical_journal':journal['canonical_journal'],'adoption_inferred':False}

def batch_patch(project,operations,receipt,reconcile_only=False):
    """Called only by console_content inside its project lock and verified release."""
    if os.environ.get('WORKFLOW_CONSOLE_DELEGATED')!='1':raise ValueError('Use console_content.py for batch writes.')
    import console_content as content
    operations=content.prepare_operations(project,operations,verify_prompts=not reconcile_only)
    _,config,before,layout=check(project,local_only=True);contract=contract_for(config)
    targets=batch_targets(contract,operations);cells=cells_by_coordinate(before)
    intent=[{k:op[k] for k in ('slot','payload')}|({'index':op['index']} if 'index' in op else {}) for op in targets]
    canonical=lambda value:hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    identity={'project':project,'spreadsheet_token':config['spreadsheet_token'],'sheet_id':config['sheet_id'],'contract_sha256':canonical(contract),'operations_sha256':canonical(intent)}
    receipt=Path(receipt).resolve()
    if not receipt.is_relative_to(ROOT):raise ValueError('Receipt must stay within this workspace.')
    receipt.parent.mkdir(parents=True,exist_ok=True)
    remote_intent={'project':project,'spreadsheet_token':config['spreadsheet_token'],'sheet_id':config['sheet_id'],'targets':sorted([{'cell':op['cell'],'payload':op['payload']} for op in targets],key=lambda op:op['cell'])}
    path=(ROOT/'workflow/runtime/console-batches'/(canonical(remote_intent)+'.json')).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Canonical batch journal escapes the workspace.')
    if not reconcile_only:content.ensure_no_pending_batch(project,allowed_canonical=path)
    if reconcile_only and not path.is_file():raise ValueError('BATCH_NOT_REGISTERED: readonly reconciliation cannot submit.')
    path.parent.mkdir(parents=True,exist_ok=True)
    if receipt.exists() and not path.exists():raise ValueError('BATCH_RECEIPT_INTENT_MISMATCH: preserve the existing unregistered receipt.')
    if path.exists():
        journal=json.loads(path.read_text())
        if journal.get('schema')!='console-batch-receipt-v1' or journal.get('identity')!=identity:raise ValueError('BATCH_RECEIPT_INTENT_MISMATCH: preserve the original receipt.')
        if receipt.exists():
            mirror=json.loads(receipt.read_text())
            if any(mirror.get(key)!=journal.get(key) for key in ('identity','canonical_journal','operations','before','before_layout')):raise ValueError('BATCH_RECEIPT_CHANGED: receipt differs from the canonical journal.')
        saved=journal.get('operations',[]);saved_cells=cells_by_coordinate(journal['before'])
        if not isinstance(saved,list) or len(saved)!=len(targets) or any(not isinstance(op,dict) for op in saved) or type(journal.get('submission_attempted')) is not bool:raise ValueError('BATCH_RECEIPT_CHANGED: preserve and review the receipt.')
        for prior,wanted in zip(saved,targets):
            if any(prior.get(key)!=wanted.get(key) for key in ('slot','index','payload','cell')) or prior.get('before')!=saved_cells.get(prior.get('cell')):
                raise ValueError('BATCH_RECEIPT_CHANGED: stored operations differ from the requested intent.')
            _,expected=plan_patch(contract,prior['slot'],prior.get('index'),prior['before'],prior['payload'])
            if prior.get('expected')!=expected:raise ValueError('BATCH_RECEIPT_CHANGED: stored target expectation changed.')
        if reconcile_only or journal.get('submission_attempted') or journal.get('state') not in {'PREPARED','PREWRITE_CONFLICT'}:
            return _batch_readback(project,contract,journal,before,layout,path,receipt)
        if before!=journal['before'] or layout!=journal['before_layout']:raise ValueError('Concurrent console change; preserve the prepared batch.')
    else:
        planned=[]
        for op in targets:
            old=cells[op['cell']];_,expected=plan_patch(contract,op['slot'],op.get('index'),old,op['payload'])
            planned.append({**op,'before':old,'expected':expected})
        journal={'schema':'console-batch-receipt-v1','canonical_journal':str(path.relative_to(ROOT)),'identity':identity,'state':'PREPARED','submission_attempted':False,'before':before,'before_layout':layout,'operations':planned}
        _batch_save(path,journal,receipt)
    changed=[op for op in journal['operations'] if _batch_cell(op['before'])!=_batch_cell(op['expected'])]
    if not changed:return _batch_readback(project,contract,journal,before,layout,path,receipt)
    sparse=[{'shortcut':'+cells-set','input':{'sheet_id':config['sheet_id'],'range':op['cell'],'cells':[[op['payload']]]}} for op in changed]
    request=receipt.with_suffix('.operations.json')
    raw=json.dumps(sparse,ensure_ascii=False,indent=2)+'\n'
    if request.exists():
        if request.read_text()!=raw:raise ValueError('BATCH_REQUEST_CHANGED: preserve the earlier request.')
    else:
        with request.open('x',encoding='utf-8') as stream:stream.write(raw)
    guard,guard_layout=read(config)
    if guard!=before or guard_layout!=layout:
        journal['state']='PREWRITE_CONFLICT';_batch_save(path,journal,receipt);raise ValueError('Concurrent console change; no batch write performed.')
    content.prepare_operations(project,operations)
    if request.read_text()!=raw:raise ValueError('BATCH_REQUEST_CHANGED: the audit request changed; no send performed.')
    journal.update(state='SUBMITTING',submission_attempted=True,submitted_operations_sha256=hashlib.sha256(raw.encode()).hexdigest());_batch_save(path,journal,receipt)
    try:cli(['sheets','+batch-update','--spreadsheet-token',config['spreadsheet_token'],'--operations','-','--yes'],raw)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        journal.update(state='OUTCOME_UNKNOWN',submission_error_type=type(error).__name__);_batch_save(path,journal,receipt)
    try:after,after_layout=read(config)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        journal.update(state='OUTCOME_UNKNOWN',readback_error_type=type(error).__name__);_batch_save(path,journal,receipt)
        raise ValueError('BATCH_OUTCOME_UNKNOWN: reread the same receipt; do not submit a new batch.') from None
    return _batch_readback(project,contract,journal,after,after_layout,path,receipt)

IMAGE_SLOTS={'source_screenshots','storyboard_images','scenes','keyframes','props','characters'}

def image_dimensions(data):
    if len(data)>=24 and data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16]==b'IHDR':
        width,height=struct.unpack('>II',data[16:24])
    elif data[:2]==b'\xff\xd8':
        position=2;width=height=0
        while position+4<len(data):
            if data[position]!=255:raise ValueError('Invalid JPEG marker.')
            while position<len(data) and data[position]==255:position+=1
            if position>=len(data):raise ValueError('Truncated JPEG marker.')
            marker=data[position];position+=1
            if marker in (0xD8,0xD9) or 0xD0<=marker<=0xD7:continue
            length=int.from_bytes(data[position:position+2],'big')
            if length<2 or position+length>len(data):raise ValueError('Invalid JPEG segment.')
            if marker in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF):
                height=int.from_bytes(data[position+3:position+5],'big');width=int.from_bytes(data[position+5:position+7],'big');break
            position+=length
    else:raise ValueError('Use a verified PNG or JPEG original.')
    if not width or not height:raise ValueError('Invalid image dimensions.')
    return width,height

def plan_image(contract,slot,index,old,image,caption,source_url=''):
    if slot not in IMAGE_SLOTS:raise ValueError('This named slot does not accept images.')
    coord=slot_coordinate(contract,slot,index)
    if any(x['type']=='embed-image' for x in old.get('rich_text',[])):
        raise ValueError('Existing primary image is protected; coordinate an explicit version replacement with maintenance.')
    if old.get('formula') or old.get('multiple_values'):raise ValueError('Image cannot replace formula/multiple values.')
    rich=[image]
    if old.get('rich_text'):rich.extend(copy.deepcopy(old['rich_text']))
    elif old.get('value'):rich.append({'type':'text','text':'\n'+str(old['value'])})
    rich.append({'type':'text','text':'\n'+caption})
    if source_url:rich.append({'type':'link','text':'原件与来源','link':source_url})
    # Captions are visible content; a forbidden note must not be created even
    # transiently before the outer console_content wrapper can remove it.
    payload={'rich_text':rich,'note':None if contract.get('slot_schemas',{}).get(slot,{}).get('notes_allowed') is False else (old.get('note','')+'\n'+caption).strip()}
    plan_patch(contract,slot,index,old,payload)
    return coord,payload

def mount_image(project,slot,index,image_path,digest,caption,source_url,receipt):
    if not caption.strip():raise ValueError('Image usage and candidate/adoption scope must be explicit.')
    path=Path(image_path).resolve();project_root=(ROOT/'projects'/project).resolve()
    if not path.is_relative_to(project_root) or not path.is_file():raise ValueError('Image must be a project-local original.')
    content=path.read_bytes();actual=hashlib.sha256(content).hexdigest()
    if actual!=digest or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Image SHA differs from the reviewed input.')
    if len(content)>20*1024*1024:raise ValueError('Image exceeds upload_all limit; use an explicit multipart workflow.')
    width,height=image_dimensions(content)
    if source_url and not source_url.startswith('https://example.invalid/receiver-feishu-document'):raise ValueError('Use the actual Feishu original/library source URL.')
    result,config,before,layout=check(project);contract=contract_for(config)
    coord=slot_coordinate(contract,slot,index);old=cells_by_coordinate(before)[coord]
    p=Path(receipt).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('Receipt must stay within the workspace.')
    p.parent.mkdir(parents=True,exist_ok=True)
    identity={'project':project,'slot':slot,'index':index,'cell':coord,'sha256':digest,'caption':caption,'source_url':source_url}
    journal=json.loads(p.read_text()) if p.exists() else None
    if journal:
        if journal['identity']!=identity:raise ValueError('Do not reuse a receipt for another image or intent.')
        if journal['state'] in ('UPLOADING','UPLOAD_UNKNOWN'):raise ValueError('Upload outcome unknown; reconcile the journal before retrying, do not upload again.')
        token=journal.get('file_token')
        if not token:raise ValueError('Incomplete image journal; review before retry.')
        if ('embed-image',token) in reference_set(old):
            if reference_set(journal['before_cell'])-reference_set(old):raise ValueError('Earlier references disappeared; retain them before marking the image linked.')
            if caption not in str(old):raise ValueError('Image usage label is missing; reconcile before marking verified.')
            journal.update(state='VERIFIED',validation=result);p.write_text(json.dumps(journal,ensure_ascii=False,indent=2)+'\n')
            return {**result,'image_token':token,'already_linked':True,'no_new_upload':True}
        if journal['state']=='VERIFIED':raise ValueError('The previously linked image changed; do not restore an old image automatically.')
        if old!=journal['before_cell']:raise ValueError('Target changed after upload; preserve the edit and coordinate the existing uploaded image.')
    else:
        placeholder={'type':'embed-image','text':'','image_token':'pending','image_name':path.name,'image_width':width,'image_height':height}
        plan_image(contract,slot,index,old,placeholder,caption,source_url)
        guard,guard_layout=read(config)
        if guard!=before or guard_layout!=layout:raise ValueError('Console changed before upload; no upload performed.')
        journal={'identity':identity,'before_cell':old,'state':'UPLOADING','bytes':len(content),'dimensions':[width,height]}
        p.write_text(json.dumps(journal,ensure_ascii=False,indent=2)+'\n')
        body={'file_name':path.name,'parent_type':'sheet_image','parent_node':config['spreadsheet_token'],'size':len(content)}
        call=subprocess.run(['lark-cli','api','POST','/open-apis/drive/v1/medias/upload_all','--as','user','--data',json.dumps(body,ensure_ascii=False),'--file','file=./'+str(path.relative_to(ROOT))],cwd=ROOT,capture_output=True,text=True,timeout=55)
        response=call.stdout or call.stderr
        p.with_suffix('.upload-response.json').write_text(response)
        try:
            d=json.loads(response);token=d['data']['file_token']
            if call.returncode or not token or d.get('code',0)!=0 or d.get('ok',True) is False:raise ValueError('Upload failed or outcome unknown.')
        except (ValueError,KeyError):
            journal['state']='UPLOAD_UNKNOWN';p.write_text(json.dumps(journal,ensure_ascii=False,indent=2)+'\n');raise ValueError('Upload outcome unknown; no Sheet write and no automatic retry.')
        journal.update(file_token=token,state='UPLOADED');p.write_text(json.dumps(journal,ensure_ascii=False,indent=2)+'\n')
    # Verify uploaded bytes before modifying the cell. A retry reuses the known token.
    downloaded=p.with_suffix('.cloud-original'+path.suffix)
    download=subprocess.run(['lark-cli','api','GET','/open-apis/drive/v1/medias/'+token+'/download','--as','user','--output','./'+str(downloaded.relative_to(ROOT))],cwd=ROOT,capture_output=True,text=True,timeout=55)
    p.with_suffix('.download-response.txt').write_text(download.stdout+download.stderr)
    if download.returncode or not downloaded.exists() or hashlib.sha256(downloaded.read_bytes()).hexdigest()!=digest:raise ValueError('Mounted image byte readback failed; token retained, no cell write.')
    _,_,current,_=check(project)
    if cells_by_coordinate(current)[coord]!=journal['before_cell']:raise ValueError('Target changed during upload; no cell write, preserve the edit.')
    image={'type':'embed-image','text':'','image_token':token,'image_name':'','image_width':width,'image_height':height}
    _,payload=plan_image(contract,slot,index,old,image,caption,source_url)
    validation=patch(project,slot,index,payload,p.with_suffix('.link.json'))
    # Separate persistent read protects against immediate-only embed results.
    _,_,after,_=check(project);cell=cells_by_coordinate(after)[coord]
    if ('embed-image',token) not in reference_set(cell) or reference_set(old)-reference_set(cell):raise ValueError('Persistent image/ref readback failed; retain the journal and reconcile.')
    journal.update(state='VERIFIED',uploaded_bytes_sha_verified=True,after_cell=cell,validation=validation)
    p.write_text(json.dumps(journal,ensure_ascii=False,indent=2)+'\n')
    return {**validation,'image_token':token,'uploaded_bytes_sha_verified':True,'original_refs_preserved':True,'adoption_inferred':False}

def initialize(project):
    """Lay out an already-created, empty Sheet. Never reset an existing console."""
    check_rule=subprocess.run([sys.executable,str(ROOT/'scripts/workflow_rules.py'),'check'],cwd=ROOT,capture_output=True,text=True,timeout=60)
    if check_rule.returncode:raise ValueError('Read the current published release before creating a console.')
    config=resolve(project);contract=contract_for(config);before,layout=read(config)
    if config.get('layout_profile')=='receiver-compact-2':raise ValueError('Existing compact layout is migration-only; never initialize or rebuild it.')
    if any(c.get('value') or c.get('rich_text') or c.get('formula') or c.get('note') for c in cells_by_coordinate(before).values()):
        # Repeat initialization is harmless only if the registered layout already matches.
        return validate(contract,before,layout,project)
    if any(m['range']!='A1:E1' for m in layout.get('merged_cells',[])):raise ValueError('Existing custom merges require maintenance review.')
    cells=copy.deepcopy(contract['styles'])
    for row in cells:
        for c in row:c['value']=''
    def setcell(coord,payload):
        cell=cells[int(coord[1:])-1][ord(coord[0])-65]
        if set(payload)&{'value','formula','rich_text','multiple_values'}:
            for k in ('value','formula','rich_text','multiple_values'):cell.pop(k,None)
        cell.update(payload)
    for coord,value in contract['fixed_labels'].items():setcell(coord,{'value':value})
    for coord in contract.get('initial_placeholders',['B7','C7','D7','E7','B10','C10','D10','E10','B12','C12','D12','E12','C13','E13','C14','E14','E15','C16','E16','E17','C18','E18','C19','E19','C20','E20']):
        setcell(coord,{'value':'待准备；按本项目实际输入填写'})
    setcell('A1',{'value':project+'｜'+config['name']+(' · 分镜导演稿' if contract['template_id']==DIRECTOR_ID else ' · 项目控制台')})
    if contract['template_id'] not in (COMPACT_ID,DIRECTOR_ID):
        setcell('C17',{'value':project});setcell('A42',{'value':project+'｜V001筹备'})
    setcell(contract['slots']['remarks'],{'value':'' if contract['template_id']==DIRECTOR_ID else '备注｜B段衔接与制作说明\n待填写；无B段时写“无”。'})
    setcell(contract['slots']['current_node'],{'value':'01 来源分析','data_validation':contract['current_node_validation']})
    if 'actual_ai' in contract['slots']:
        setcell(contract['slots']['actual_ai'],{'value':'','data_validation':contract['actual_ai_validation']})
    receiver=__import__('receiver_config').load(True)
    __import__('receiver_config').validate(receiver,production=True)
    rules_url=receiver['feishu_origin'].rstrip('/')+'/docx/'+receiver['rules_center']
    setcell(contract['slots']['rules'],{'rich_text':[{'type':'link','text':'飞书独立工作流中心','link':rules_url}]})
    ops=[{'shortcut':'+cells-unmerge','input':{'range':'A1:E1'}}] if layout.get('merged_cells') else []
    ops.append({'shortcut':'+cells-set','input':{'range':contract['range'],'cells':cells}})
    for m in contract['layout']['merged_cells']:ops.append({'shortcut':'+cells-merge','input':{'range':m['range']}})
    for c in contract['layout']['column_widths']:ops.append({'shortcut':'+cols-resize','input':{'range':c['cols'],'type':'pixel','size':c['width']}})
    for r in contract['layout']['row_heights']:ops.append({'shortcut':'+rows-resize','input':{'range':r['rows'],'type':'auto' if r['type']=='auto' else 'pixel',**({'size':r['height']} if r['type']!='auto' else {})}})
    # Current CLI resets the other freeze dimension: clear columns BEFORE setting rows.
    ops.extend([{'shortcut':'+dim-freeze','input':{'dimension':'column','count':0}},{'shortcut':'+dim-freeze','input':{'dimension':'row','count':contract['layout']['frozen_rows']}}])
    for op in ops:op['input']['sheet_id']=config['sheet_id']
    receipt=ROOT/'projects'/project/'evidence/console-initialization.json';receipt.parent.mkdir(parents=True,exist_ok=True)
    payload=receipt.with_suffix('.operations.json');payload.write_text(json.dumps(ops,ensure_ascii=False))
    guard,guard_layout=read(config)
    if guard!=before or guard_layout!=layout:raise ValueError('Sheet changed during initialization; no write performed.')
    cli(['sheets','+batch-update','--spreadsheet-token',config['spreadsheet_token'],'--operations','@./'+str(payload.relative_to(ROOT)),'--dry-run'])
    result=cli(['sheets','+batch-update','--spreadsheet-token',config['spreadsheet_token'],'--operations','@./'+str(payload.relative_to(ROOT)),'--yes'])
    after,after_layout=read(config);validation=validate(contract,after,after_layout,project)
    receipt.write_text(json.dumps({'before':before,'before_layout':layout,'result':result,'after':after,'validation':validation,'binding_required_before_execution':True},ensure_ascii=False,indent=2)+'\n')
    return validation

def main():
    global ROOT,CONTRACT
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['check','patch','batch','init','image']);p.add_argument('--project',required=True);p.add_argument('--workspace',type=Path);p.add_argument('--slot');p.add_argument('--index',type=int);p.add_argument('--payload');p.add_argument('--receipt');p.add_argument('--image');p.add_argument('--expected-sha256');p.add_argument('--caption');p.add_argument('--source-url',default='');p.add_argument('--expected-payload-sha256');p.add_argument('--reconcile-only',action='store_true');a=p.parse_args()
    if a.command!='batch' and (a.reconcile_only or a.expected_payload_sha256):raise ValueError('Batch-only validation flags cannot be used for a single-slot command.')
    if a.command in {'patch','batch','image'} and os.environ.get('WORKFLOW_CONSOLE_DELEGATED')!='1':raise ValueError('Use console_content.py for project writes; direct console_template mutation is blocked.')
    if a.workspace:ROOT=a.workspace.resolve();CONTRACT=ROOT/'workflow/console-template.json'
    if a.command=='check':result=check(a.project)[0]
    elif a.command=='init':result=initialize(a.project)
    elif a.command=='batch':
        if not a.payload or not a.receipt:raise ValueError('Batch requires operations payload and receipt.')
        result=batch_patch(a.project,read_batch_operations(a.payload,a.expected_payload_sha256),a.receipt,reconcile_only=a.reconcile_only)
    elif a.command=='image':
        if not all([a.slot,a.image,a.expected_sha256,a.caption,a.receipt]):raise ValueError('image requires slot, local image, expected SHA, caption and receipt.')
        result=mount_image(a.project,a.slot,a.index,a.image,a.expected_sha256,a.caption,a.source_url,a.receipt)
    else:
        if not all([a.slot,a.payload,a.receipt]):raise ValueError('patch requires slot, payload and receipt.')
        result=patch(a.project,a.slot,a.index,json.loads(Path(a.payload).read_text()),a.receipt)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError,subprocess.SubprocessError) as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(1)
