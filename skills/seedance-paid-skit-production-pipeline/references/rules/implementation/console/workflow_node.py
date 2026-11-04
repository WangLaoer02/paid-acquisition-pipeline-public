#!/usr/bin/env python3
"""Resolve one live work item to a small, verified node context. Read-only: never generates, uploads, or advances a Gate."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
RULES=ROOT/'workflow/rules'
sys.path.insert(0,str(ROOT/'scripts'))

class WorkflowError(ValueError):
    pass

def load(path:Path)->Any:
    return json.loads(path.read_text(encoding='utf-8'))

def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def inside(base:Path,name:str)->Path:
    if not isinstance(name,str) or not name or Path(name).is_absolute():
        raise WorkflowError('A nonempty relative path is required.')
    p=(base/name).resolve()
    if not p.is_relative_to(base.resolve()):
        raise WorkflowError('Path escapes its permitted root.')
    return p

def catalog()->dict[str,Any]:
    return load(ROOT/'workflow/node_skills.json')

def get_contract(node:str)->dict[str,Any]:
    routes=catalog()
    if node not in routes['nodes']:
        raise WorkflowError('Unknown node; use list, not a guessed node ID.')
    p=inside(ROOT,routes['nodes'][node]['contract_path'])
    c=load(p)
    if c.get('id')!=node or c.get('release_id')!=routes.get('release_id'):
        raise WorkflowError('Node contract identity or release differs from the router.')
    return c

def policy_text(policy_id:str,index:dict[str,Any])->tuple[dict[str,Any],str]:
    if policy_id not in index:
        raise WorkflowError('Unknown policy ID: '+policy_id)
    p=index[policy_id]
    if p.get('external_skill'):
        import workflow_skill_dependencies as deps
        name=p['external_skill'];contract=load(RULES/'skill-dependencies.json')['skills'][name]
        resolved=deps.resolve(name,contract);read=resolved['reads'][-1]
        alias=dict(p,path=read['path'],sha256=read['source']['sha256'])
        return alias,deps.section(read['text'],p['external_section'])
    if 'archive' in Path(p['path']).parts or p['path'] in ('main.md','operations.md'):
        raise WorkflowError('The runtime cannot expand whole-manual or archive pointers.')
    path=inside(RULES,p['path']);raw=path.read_bytes()
    if sha(raw)!=p['sha256']:
        raise WorkflowError('A selected rule fragment has changed: '+policy_id)
    return p,raw.decode('utf-8')

def execution_boundary(node:str,route:str|None=None,project_id:str|None=None)->dict[str,Any]:
    # workflow_step imports no node module; its CLI delegates back via subprocess.
    from workflow_step import boundary
    return boundary(node,node,route,project_id,ROOT)

def make_context(node:str,conditions:list[str]|None=None,route:str|None=None,project_id:str|None=None)->dict[str,Any]:
    c=get_contract(node)
    boundary=execution_boundary(node,route,project_id)
    idx=load(RULES/'policy-index.json')['policies']
    flags=list(dict.fromkeys(conditions or []))
    unknown=set(flags)-set(c['conditional_reads'])
    if unknown:raise WorkflowError('Condition not applicable to this node: '+', '.join(sorted(unknown)))
    selected=list(c['references'])
    for flag in flags:selected+=c['conditional_reads'][flag]['policy_ids']
    selected=list(dict.fromkeys(selected))
    content=[]
    external=[]
    for key in selected:
        policy,text=policy_text(key,idx)
        content.append({'path':'workflow/rules/'+policy['path'],'id':key,'text':text,'reason':'current-node rule','source':{'path':policy['source_path'],'lines':[policy['source_line_start'],policy['source_line_end']]}})
    dependency_groups=[c.get('required_external_skills',[])] + [c['conditional_reads'][flag].get('external_skills',[]) for flag in flags]
    for names in dependency_groups:
        for name in names:
            if any(x['skill_id']==name for x in external):continue
            import workflow_skill_dependencies as deps
            resolved=deps.resolve(name,load(RULES/'skill-dependencies.json')['skills'][name])
            headings=c.get('skill_read_sections',{}).get(name)
            if headings:
                # Validate the entire dependency first, then expose only this stage's methods.
                read=resolved['reads'][-1]
                read['text']='\n'.join(deps.section(read['text'],heading) for heading in headings)
                read['source']['sections']=headings
                resolved['reads']=[read]
            content.extend(resolved.pop('reads'));external.append(resolved)
    result={'execution_boundary':boundary,'external_skills':external,'ok':True,'release_id':c['release_id'],'node':node,'label':c['label'],'contract':c,'selected_conditions':flags,'required_reads':content,'reading_characters':sum(len(p['text']) for p in content),'gate_pass_inferred':False,'side_effects':[],'paid_generation_authorized':False,'upload_authorized':False}
    if node=='A09':
        requirements=c['preparation_requirements']
        result['generation_preparation']={'b_required':boundary['route']=='ab','required':requirements['common']+(requirements['ab'] if boundary['route']=='ab' else [])}
    return result

def bindings()->list[dict[str,Any]]:
    p=ROOT/'workflow/state_bindings.json'
    return load(p).get('bindings',[]) if p.exists() else []

def select_item(item_id:str|None,project:str|None)->dict[str,Any]:
    values=bindings()
    if item_id:
        matches=[x for x in values if x['id']==item_id]
    elif project:
        matches=[x for x in values if x.get('project_id')==project or x['id'].startswith('PROJECT:'+project+':')]
    else:
        raise WorkflowError('Choose a real --item or --project from list.')
    if len(matches)!=1:
        raise WorkflowError('Project/item is absent or ambiguous; select an exact item ID from list.')
    return matches[0]

def relevant_bindings(target:dict[str,Any],all_bindings:list[dict[str,Any]])->list[dict[str,Any]]:
    by_id={b['id']:b for b in all_bindings};selected={target['id']};pending=[target]
    while pending:
        b=pending.pop()
        parents=[]
        if b.get('parent'):
            if b['parent'] not in by_id:raise WorkflowError('Bound parent is missing; do not guess the A source.')
            parents.append(by_id[b['parent']])
        if b.get('b_asset'):
            libs=[x for x in all_bindings if x.get('kind')=='library' and x.get('asset_name')==b['b_asset']]
            if len(libs)!=1:raise WorkflowError('B-asset binding is absent or ambiguous.')
            parents+=libs
        for p in parents:
            if p['id'] not in selected:selected.add(p['id']);pending.append(p)
    return [x for x in all_bindings if x['id'] in selected]

def live_state(item_id:str|None,project:str|None)->dict[str,Any]:
    import workflow_state as state
    target=select_item(item_id,project)
    chosen=relevant_bindings(target,bindings())
    observed=state.observe(chosen)
    checkpoint=load(ROOT/'workflow/state_checkpoint.json')
    result=state.plan(chosen,observed,checkpoint,load(ROOT/'workflow/stages.json'))
    if result['conflicts']:
        raise WorkflowError('Live node/dependency conflict; preserve edits: '+json.dumps(result['conflicts'],ensure_ascii=False))
    current=next((x for x in result['items'] if x['id']==target['id']),None)
    if current is None:raise WorkflowError('The current work item was not resolved.')
    resume=sha(json.dumps({'item':target['id'],'node':current['current_node_id'],'observations':observed},sort_keys=True).encode())
    return {'item':current,'project_id':target.get('project_id'),'observed_sources':observed,'observed_at':result['observed_at'],'dependency_items':result['items'],'pending_sync':result['writes'],'resume_key':resume,'live_node_verified':True,'gate_pass_inferred':False,'automatic_writes':False}

def validate_routes()->dict[str,Any]:
    route=catalog();idx=load(RULES/'policy-index.json')['policies'];graph=load(ROOT/'workflow/stages.json')
    declared={n['id']:n for group in graph['families'].values() for n in group}
    if len(declared)!=24 or set(declared)!=set(route['nodes']):raise WorkflowError('All original 24 node IDs must be covered exactly once.')
    results=[]
    for node in declared:
        c=get_contract(node)
        for field in ('goal','depends_on','environment','references','read','deliver','gate','after_pass','failure','input_requirements'):
            if field not in c:raise WorkflowError(f'{node} lacks {field}.')
        if not isinstance(c['goal'],str) or not c['goal'].strip() or not all(isinstance(c[k],list) and c[k] for k in ('environment','read','deliver','gate','input_requirements')):
            raise WorkflowError('Node required fields must be nonempty: '+node)
        if c['label']!=declared[node]['label']:raise WorkflowError('Stable node label changed.')
        if len({g.get('id') for g in c['gate']})!=len(c['gate']):raise WorkflowError('Duplicate Gate IDs.')
        if any(not isinstance(g.get('criterion'),str) or not g['criterion'].strip() or g.get('evidence_required') is not True for g in c['gate']):raise WorkflowError('Every Gate requires criterion and evidence_required=true: '+node)
        if len({x.get('id') for x in c['input_requirements']})!=len(c['input_requirements']) or any(not x.get('description') for x in c['input_requirements']):raise WorkflowError('Invalid input requirements: '+node)
        if c['references']!=route['nodes'][node].get('required_policy_ids') or c['input_requirements']!=route['nodes'][node].get('input_requirements'):raise WorkflowError('Node route and contract disagree: '+node)
        for d in c['depends_on']:
            if d not in declared:raise WorkflowError('Unresolved dependency: '+d)
        if c['after_pass'].get('automatic_side_effects') is not False:raise WorkflowError('Gate must not perform implicit effects.')
        data=make_context(node)
        for flag in c['conditional_reads']:make_context(node,[flag])
        results.append({'node':node,'reading_characters':data['reading_characters'],'required_files':len(data['required_reads']),'default_main_loaded':False})
    # Check cyclic dependencies, including edges not currently traversed.
    done=set();visiting=set()
    def visit(n):
        if n in visiting:raise WorkflowError('Cyclic node dependencies.')
        if n in done:return
        visiting.add(n)
        for dep in get_contract(n)['depends_on']:visit(dep)
        visiting.remove(n);done.add(n)
    for n in declared:visit(n)
    return {'ok':True,'release_id':route['release_id'],'node_count':len(results),'all_nodes':results,'policy_count':len(idx),'automatic_side_effects':False}

def check_coverage()->dict[str,Any]:
    if not (RULES/'archive').exists():raise WorkflowError('HISTORICAL_COVERAGE_NOT_DISTRIBUTED: use validate for the current 24-node contracts.')
    coverage=load(RULES/'coverage.json');index=load(RULES/'policy-index.json')['policies']
    groups={}
    for part in coverage['pieces']:groups.setdefault(part['source'],[]).append(part)
    total=0
    for source,parts in groups.items():
        raw=inside(RULES/'archive/WF20261010.5',source).read_text();lines=raw.splitlines(keepends=True);cursor=1
        for part in sorted(parts,key=lambda p:p['start']):
            if part['start']!=cursor:raise WorkflowError('Rule coverage has an omitted/duplicated interval.')
            original=''.join(lines[part['start']-1:part['end']])
            if sha(original.encode())!=part['source_sha256']:raise WorkflowError('Original rule byte evidence changed.')
            external=index[part['id']].get('external_skill')
            if external:
                # The archived source is retained as historical evidence, not executed.
                cursor=part['end']+1;total+=len(original);continue
            p,text=policy_text(part['id'],index)
            retired=coverage.get('retired_policies',{}).get(part['id'])
            if retired:
                if not retired.get('reason') or not retired.get('replacement_release'):
                    raise WorkflowError('Retired rule requires an explicit replacement record.')
                historical=inside(RULES,retired['path'])
                if not retired['path'].startswith('archive/') or sha(historical.read_bytes())!=retired['sha256']:
                    raise WorkflowError('Retired rule historical evidence changed.')
                slice_fields=('start','end','source_sha256')
                if any(key in retired for key in slice_fields):
                    if (any(key not in retired for key in (*slice_fields,'replacement_sha256')) or
                            type(retired['start']) is not int or type(retired['end']) is not int or
                            retired['start']!=part['start'] or retired['end']!=part['end'] or
                            retired['path']!='archive/WF20261010.5/'+source or
                            retired['source_sha256']!=part['source_sha256']):
                        raise WorkflowError('Retired source slice differs from its coverage interval.')
                    historical_lines=historical.read_text().splitlines(keepends=True)
                    if not 1<=retired['start']<=retired['end']<=len(historical_lines):
                        raise WorkflowError('Retired source slice is outside its archived file.')
                    text=''.join(historical_lines[retired['start']-1:retired['end']])
                    if sha(text.encode())!=retired['source_sha256']:
                        raise WorkflowError('Retired source slice bytes changed.')
                    if p['sha256']!=retired['replacement_sha256']:
                        raise WorkflowError('Retired rule replacement is not the registered current fragment.')
                else:
                    text=historical.read_text()
            def fix(m):
                target=m.group(2)
                if '://' in target or target.startswith(('#','/')):return m.group(0)
                if target=='templates/project-config.json':target='implementation/paid-skit-production-pipeline/templates/project-config.json'
                return '['+m.group(1)+'](../'+target+')'
            normalized=re.sub(r'\[([^\]\n]*)\]\(([^)\n]+)\)',fix,original)
            if retired and any(key in retired for key in ('start','end','source_sha256')):
                text=re.sub(r'\[([^\]\n]*)\]\(([^)\n]+)\)',fix,text)
            if normalized!=text:raise WorkflowError('A policy fragment lost or changed its original rule text.')
            cursor=part['end']+1;total+=len(original)
        if cursor!=len(lines)+1:raise WorkflowError('Rule tail is not covered.')
    return {'ok':True,'source_module_count':len(groups),'source_characters_preserved':total,'fragments':len(coverage['pieces']),'only_text_transformation':'relative-link-normalization','business_rule_deletions':0,'retired_policy_count':len(coverage.get('retired_policies',{})),'coverage_scope':'retained historical source; retired format is not active; independent Skill verified separately'}

def inspect_inputs(node:str,path:Path,reference_selection:str|None=None)->dict[str,Any]:
    c=get_contract(node);record=load(path)
    if record.get('schema_version')!=1 or record.get('node')!=node or record.get('release_id')!=c['release_id']:
        raise WorkflowError('Input manifest refers to a different node/release/schema.')
    expected={x['id']:x for x in c['input_requirements']};seen=set();verified=[];missing=[]
    for entry in record.get('inputs',[]):
        iid=entry.get('id')
        if iid not in expected or iid in seen:raise WorkflowError('Unknown or duplicate input requirement: '+str(iid))
        seen.add(iid)
        if entry.get('status')!='verified' or not entry.get('source_ref'):missing.append(iid);continue
        if entry.get('path'):
            q=inside(ROOT,entry['path'])
            if not q.is_file():raise WorkflowError('Input file missing: '+entry['path'])
            if entry.get('sha256')!=sha(q.read_bytes()):raise WorkflowError('Input file hash changed: '+entry['path'])
        verified.append(iid)
    missing+=sorted(i for i,x in expected.items() if x.get('required') and i not in seen)
    missing=list(dict.fromkeys(missing))
    import reference_scope
    scope=None
    if node in reference_scope.DOWNSTREAM:
        if not record.get('reference_scope') or not reference_selection:
            missing.append('REFERENCE_CURRENT_SELECTION_AND_BINDING_REQUIRED')
        else:scope=reference_scope.check_use(ROOT,record,reference_selection)
    return {'reference_scope_check':scope,'ok':True,'node':node,'release_id':c['release_id'],'verified':verified,'missing_or_unverified':missing,'complete':not missing,'semantic_truth_inferred':False,'side_effects':[]}

def inspect_evidence(node:str,path:Path,reference_selection:str|None=None)->dict[str,Any]:
    """Validate claimed evidence files, not their semantic truth or human authorization."""
    c=get_contract(node);record=load(path)
    if record.get('node')!=node or record.get('release_id')!=c['release_id']:
        raise WorkflowError('Evidence refers to a different node or rule release.')
    known={g['id'] for g in c['gate']};seen=set();files=[];missing=[]
    for claim in record.get('checks',[]):
        gid=claim.get('id')
        if gid not in known or gid in seen:raise WorkflowError('Unknown or duplicate evidence criterion.')
        seen.add(gid)
        proof=claim.get('evidence',[])
        if claim.get('status')!='pass' or not proof:missing.append(gid)
        for entry in proof:
            p=inside(ROOT,entry.get('path',''))
            if not p.is_file() or p.stat().st_size==0:raise WorkflowError('Evidence file absent or empty.')
            if sha(p.read_bytes())!=entry.get('sha256'):raise WorkflowError('Evidence bytes no longer match the reviewed input.')
            files.append(str(p.relative_to(ROOT.resolve())))
    missing+=sorted(known-seen)
    delivery=None
    if c.get('delivery_check_required'):
        ref=record.get('delivery_contract')
        if not ref:missing.append('DELIVERY_CONTRACT_MISSING')
        else:
            import delivery_contract
            req=inside(ROOT,ref['requirements_path']);rev=inside(ROOT,ref['review_path'])
            if sha(req.read_bytes())!=ref.get('requirements_file_sha256') or sha(rev.read_bytes())!=ref.get('review_file_sha256'):raise WorkflowError('Delivery contract changed since evidence review')
            delivery=delivery_contract.inspect(ROOT,load(req),load(rev))
            if not delivery['coverage_complete']:missing+=delivery['missing_or_unverified']
    parity=None;parities=[];parity_docs=[]
    if c.get('storyboard_check_required'):
        ref=record.get('storyboard_contract')
        refs=[ref] if ref else []
        if node=='B04' and 'storyboard_contracts' in record:
            if 'storyboard_contract' in record:raise WorkflowError('Choose storyboard_contract or storyboard_contracts, not both.')
            refs=record['storyboard_contracts']
            if not isinstance(refs,list):raise WorkflowError('B04 storyboard_contracts must be a list.')
        if not refs:missing.append('STORYBOARD_CONTRACT_MISSING')
        reviewed=set()
        for ref in refs:
            import storyboard_parity
            docs={k:load(storyboard_parity.proof(ROOT,ref[k])) for k in ('script','review','latest')}
            result=storyboard_parity.inspect(ROOT,docs['script'],docs['review'],docs['latest'])
            parities.append(result);parity_docs.append(docs)
            if not result['coverage_complete']:missing+=result['missing_or_unverified']
            if node=='B04':
                video=docs['review']['video']
                key=(str(inside(ROOT,video['path'])),result['video_sha256'])
                if key in reviewed:raise WorkflowError('Duplicate B04 storyboard video binding.')
                reviewed.add(key)
            elif delivery is not None and result['video_sha256'] not in {x.get('sha256') for x in load(rev).get('outputs',[])}:missing.append('STORYBOARD_DELIVERY_VIDEO_MISMATCH')
        parity=parities[0] if len(parities)==1 else None
        if node=='B04' and delivery is not None:
            expected={(str(inside(ROOT,x['path'])),x['sha256']) for x in load(rev).get('outputs',[])}
            for path,digest in sorted(expected-reviewed):missing.append('STORYBOARD_DELIVERY_VIDEO_MISSING:'+str(Path(path).relative_to(ROOT.resolve())))
            if reviewed-expected:missing.append('STORYBOARD_DELIVERY_VIDEO_MISMATCH')
    import reference_scope
    scope=None
    if node in reference_scope.APPLICABLE:
        if not record.get('reference_scope') or not reference_selection:
            missing.append('REFERENCE_CURRENT_SELECTION_AND_BINDING_REQUIRED')
        else:
            scope=reference_scope.check_use(ROOT,record,reference_selection)
            # A fresh Gate wrapper cannot bless an old storyboard/delivery.
            for docs in parity_docs:
                for key in ('script','latest'):
                    reference_scope.check_binding(docs[key],scope['binding'])
            if delivery is not None:
                for p in (req,rev):reference_scope.check_binding(load(p),scope['binding'])
    return {'reference_scope_check':scope,'storyboard_check':parity,**({'storyboard_checks':parities} if node=='B04' else {}),'delivery_check':delivery,'ok':True,'node':node,'evidence_files_verified':list(dict.fromkeys(files)),'missing_or_not_passed':missing,'ready_for_semantic_review':not missing,'gate_pass_inferred':False,'user_authorization_verified':False,'note':'File integrity and recorded checks only; inspect real visual/audio/user evidence before a Gate decision. No state is written.'}

def text_context(data:dict[str,Any])->str:
    import shlex
    c=data['contract'];boundary=data['execution_boundary'];plan=boundary['execution_plan']
    out=[f"# {data['release_id']} | {c['id']} {c['label']}",c['goal'],
         '流程：'+('A+B' if boundary['route']=='ab' else 'A'),
         '确认：①参考与创意 → ②完整剧本与提示词、引用及当前报价 → ③成片。',
         '只在产物齐备且本版尚未采用时停审；同版已确认后直接续跑，不再索要“继续”。']
    release=data.get('release',{})
    if release.get('publication_status')=='local_maintenance_not_cloud_published':
        out.append('本地未发布候选：'+release['local_revision']+'；规则基线 '+release['release_id']+'。仅供离线准备；未核验当前线上发布，不授权生成、费用、写入或上传。')
    elif release and not release.get('live_center_verified'):
        out.append('离线准备：未核验当前线上发布；本次读取不授权生产动作。')
    if c['id'] in ('A09','A10','A11','A12'):
        out.append('同版批准后由原执行者继续：荣耀使用native-submit；即梦使用同版scripts/dreamina_workflow.py，保留Canvas服务端积分确认；未知受理只查原任务，不重复确认。')
    if c['id']=='A09':out.append('第二停点前备齐：'+'；'.join(data['generation_preparation']['required'])+'；内部核对不另设确认。')
    if data.get('live_state'):
        state=data['live_state'];out.append('对象：'+state['item']['id'])
        if state['item'].get('revalidation_required'):out.append('需更新：'+json.dumps(state['item']['revalidation_required'],ensure_ascii=False))
        affected=[{'id':x['id'],'revalidation_required':x['revalidation_required']} for x in state.get('dependency_items',[]) if x.get('revalidation_required')]
        if affected:out.append('依赖需复验：'+json.dumps(affected,ensure_ascii=False))
        if state.get('pending_sync'):out.append('待同步：'+json.dumps(state['pending_sync'],ensure_ascii=False))
        if state.get('resume_key'):out.append('续接：'+state['resume_key'])
    if data.get('timing'):out.append('本轮已用：'+str(round(data['timing']['elapsed_seconds'],1))+'秒')
    if data.get('reference_scope'):
        scope=data['reference_scope']
        if scope['ready_for_reference_use']:
            out.append('本版参考选段（源时间，结束不含；原文字段不改写）：\n'+json.dumps(scope,ensure_ascii=False,indent=2))
        else:out.append('参考范围待核：未提供本次选段，不默认整片；规则可读，选段来源补齐后再用于下游。')
    batch=plan['batch_console'];producer=batch['compile_director']
    if producer['applicable'] and producer['available']:
        out.append('当前稿编译：'+shlex.join(producer['argv']))
    if producer['applicable'] or 'console-write' in data.get('selected_conditions',[]):
        if batch['available_in_selected_workspace']:
            out.extend(['写前检查：'+shlex.join(batch['check_argv']),'写回：'+shlex.join(batch['patch_argv'])])
    if c['id'] in ('A10','A11','A12'):
        recovery=plan['original_result_recovery']
        command=recovery.get('watch_argv') or recovery.get('download_argv')
        if command:out.append('取回原任务：'+shlex.join(command))
        out.append('等待生成时并行准备已有B、字幕音乐、PR和上传字段。')
    if c['id'] in ('A13','A14','B01','B02','B03','B04'):
        out.append('后期：核原片 → PR原生导出一个A'+(' → FFmpeg批量接已有B' if boundary['route']=='ab' else ''))
        join=plan['batch_postproduction']
        if join['applicable'] and join.get('execute_argv'):
            if join.get('compile_argv'):out.append('接片计划：'+shlex.join(join['compile_argv']))
            out.append('接片：'+shlex.join(join['execute_argv'])+('（B03先核后复用同版结果，仅待导出时执行）' if c['id']=='B03' else ''))
    if c.get('actions'):out.append('执行：'+'；'.join(c['actions']))
    if c.get('skill_calls'):out.append('按需方法：'+'；'.join(x['skill']+'：'+x['when'] for x in c['skill_calls']))
    if c.get('candidate_preparation') and boundary['route']=='ab':out.append('候选衔接：'+c['candidate_preparation']['constraint'])
    out.append('输入：'+'；'.join(c['read']))
    out.append('产出：'+'；'.join(c['deliver']))
    out.append('验收：'+'；'.join(x['criterion'] for x in c['gate']))
    for item in data['required_reads']:out.append(item['text'])
    return '\n\n'.join(out)

def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['list','context','status','resume','validate','coverage','lookup','inspect-evidence','inspect-inputs'])
    parser.add_argument('--item');parser.add_argument('--project');parser.add_argument('--node');parser.add_argument('--policy')
    parser.add_argument('--condition',action='append',default=[]);parser.add_argument('--evidence');parser.add_argument('--input-manifest')
    parser.add_argument('--offline-preparation',action='store_true');parser.add_argument('--format',choices=['text','json'],default='text')
    parser.add_argument('--route',choices=['a','ab'],help='A+B scope must choose ab; B work items infer ab')
    parser.add_argument('--timing-record',help='Existing workflow-timing-v1 record; retain the original task start and include all waits')
    parser.add_argument('--reference-scope',help='Current reference-selection-v1 evidence, reread from existing A01/Sheet/user selection; not another state source')
    parser.add_argument('--reference-use',help='Existing downstream input/evidence JSON with reference_scope binding; requires the current --reference-scope')
    args=parser.parse_args()
    if args.item and args.project:raise WorkflowError('Choose --item or --project, not both.')
    if args.route and args.command not in ('context','status','resume'):raise WorkflowError('--route applies only to context/status/resume.')
    if args.timing_record and args.command not in ('context','status','resume'):raise WorkflowError('--timing-record applies only to the original context/status/resume entry.')
    if args.reference_scope and args.command not in ('context','status','resume','inspect-inputs','inspect-evidence'):raise WorkflowError('--reference-scope is not applicable to this command.')
    if args.reference_use and args.command not in ('context','status','resume'):raise WorkflowError('--reference-use applies only to context/status/resume.')
    if args.command=='list':
        result={'ok':True,'items':[{'id':b['id'],'project':b.get('project_id'),'family':b['family']} for b in bindings()],'nodes':[{'id':k,'label':v['label']} for k,v in catalog()['nodes'].items()],'live_node_verified':False,'gate_pass_inferred':False,
                'next_actions':{
                    'matching_existing_item':'python3 scripts/workflow_node.py context --item <matching_real_item_id>',
                    'unmatched_new_reference':['python3','scripts/workflow_node.py','context','--node','A01','--condition','new-project','--offline-preparation'],
                    'scope':'List locates objects only. Unmatched reference preparation reads A01 and new-project rules without selecting an old item; after source verification read A02 then A03 creative preview for the first review. Bind the unique real Sheet before live production.'}}
    elif args.command=='validate':result=validate_routes()
    elif args.command=='coverage':result=check_coverage()
    else:
        import workflow_rules
        version=workflow_rules.check(args.offline_preparation)
        if args.command=='lookup':
            if not args.policy:raise WorkflowError('lookup requires one known --policy ID.')
            p,t=policy_text(args.policy,load(RULES/'policy-index.json')['policies'])
            result={'ok':True,'release':version,'policy':p,'text':t,'gate_pass_inferred':False}
        elif args.command=='inspect-inputs':
            if not args.node or not args.input_manifest:raise WorkflowError('inspect-inputs requires --node and --input-manifest.')
            result=inspect_inputs(args.node,inside(ROOT,args.input_manifest),args.reference_scope)
        elif args.command=='inspect-evidence':
            if not args.node or not args.evidence:raise WorkflowError('inspect-evidence requires --node and --evidence.')
            result=inspect_evidence(args.node,inside(ROOT,args.evidence),args.reference_scope)
        else:
            state=None
            if args.offline_preparation:
                if not args.node:raise WorkflowError('Offline preview requires an explicit --node; do not treat cached status as online.')
                node=args.node
            else:
                if args.node:raise WorkflowError('Live execution resolves node from --item/--project, not a supplied node.')
                state=live_state(args.item,args.project);node=state['item']['current_node_id']
            route=args.route
            if state and state['item'].get('family')=='b':
                if route=='a':raise WorkflowError('B_NODE_REQUIRES_AB_ROUTE')
                route='ab'
            project_id=state.get('project_id') if state else None
            if args.command in ('status','resume'):
                result={'ok':True,'release':version,'node':node,'live_state':state,'execution_boundary':execution_boundary(node,route,project_id),'gate_pass_inferred':False,'side_effects':[],'paid_generation_authorized':False,'upload_authorized':False}
            else:
                result=make_context(node,args.condition,route,project_id);result.update(release=version,live_state=state)
            import reference_scope
            result['reference_scope']=reference_scope.context(ROOT,node,args.reference_scope,args.reference_use,project_id)
            if args.timing_record:
                from workflow_step import timing_report
                result['timing']=timing_report(load(inside(ROOT,args.timing_record)),ROOT)
                watch=result.get('execution_boundary',{}).get('execution_plan',{}).get('original_result_recovery',{}).get('watch_argv')
                if watch:result['execution_boundary']['execution_plan']['original_result_recovery']['watch_argv']=[result['timing']['deadline_at'] if x=='{original_task_deadline_iso}' else x for x in watch]
            if args.command=='context' and args.format=='text':print(text_context(result));return
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:
        print(json.dumps({'ok':False,'error':str(exc),'side_effects':[],'paid_generation_authorized':False},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)
