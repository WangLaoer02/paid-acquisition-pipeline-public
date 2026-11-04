"""Global run projection, observable steps, issue annotations and registered local media."""
from pathlib import Path
import hashlib, json, re, subprocess, time, uuid, mimetypes
import store
from catalog import SPECS, catalog
from configuration import MEDIA_ROOTS

TITLES={s[0]:s[1] for s in SPECS}
CATEGORIES={'routing':'Skill 调用','input':'输入与参考','execution':'执行步骤','tool':'工具错误','output':'输出结果','recording':'过程记录'}
STEP_KINDS={'tool','input','check','artifact','skill','reference'}

def category_for(issue):
    return issue.get('category') or {'content':'output','file':'output','recording':'recording','manual':'output'}.get(issue.get('kind'),'execution')

def skill_snapshot(run_id,slug):
    with store.connection() as db:
        run=store.load(db,'runs',run_id)
        ref=next((s for s in run['skills'] if s['slug']==slug),None)
        if not ref:raise store.StudioError('这次运行没有使用该 Skill',404)
        row=db.execute('SELECT body FROM skill_snapshots WHERE sha256=?',(ref.get('snapshot_id',ref['sha256']),)).fetchone()
        if not row:raise store.StudioError('这次运行没有保存正文快照',404)
        return clean(json.loads(row['body']))

def read_skill(run_id,who,slug,reason='',reference=None,parent_step_id=None):
    """Record a real instruction read; lock a newly routed Skill before returning its text."""
    who=store.actor(who)
    current={s['slug']:s for s in catalog()['skills']}
    if slug not in current or not current[slug]['available']:raise store.StudioError('Skill 不存在或不可用')
    with store.connection() as db:
        run=assert_running(db,run_id,who)
        events=[]
        for row in db.execute('SELECT seq,body FROM events WHERE task_id=?',(run['task_id'],)):
            e=json.loads(row['body']);e['seq']=row['seq'];events.append(e)
        validate_parent(events,run_id,parent_step_id)
        ref=next((s for s in run['skills'] if s['slug']==slug),None)
        snap=json.loads(db.execute('SELECT body FROM skill_snapshots WHERE sha256=?',(ref.get('snapshot_id',ref['sha256']),)).fetchone()['body']) if ref else current[slug]
        target=None
        if reference:
            matches=[r for r in snap['references'] if r['path']==reference or r['name']==reference]
            if len(matches)!=1:raise store.StudioError('指定本次 Skill 快照中唯一的参考文件路径')
            target=matches[0]
        if not ref:
            ref=store.lock_skill(db,snap);run['skills'].append(ref);store.write(db,'runs',run)
        event=store.event(db,run['task_id'],'reference_read' if target else 'skill_read',who,
                          '读取参考：'+target['name'] if target else '调用 Skill：'+TITLES[slug],run_id=run_id,
                          skill_slug=slug,parent_step_id=parent_step_id,reason=clean(reason),path=target['path'] if target else snap['path'],
                          sha256=target['sha256'] if target else snap['sha256'])
    return clean(dict(step_id='event_'+str(event['seq']),skill=slug,reason=reason,document=target or snap))

def validate_parent(events,run_id,parent):
    if parent and not any(e.get('run_id')==run_id and (e.get('step_id')==parent and e['type']=='step_started' or 'event_'+str(e.get('seq'))==parent) for e in events):
        raise store.StudioError('上游步骤不属于本次运行')


def clean(value):
    """Redact common credential forms before writing tool output or returning a projection."""
    if isinstance(value,dict):
        return {k:('[已隐藏]' if re.search(r'password|secret|token|cookie|authorization|api.?key',k,re.I) else clean(v)) for k,v in value.items()}
    if isinstance(value,list):return [clean(v) for v in value]
    if not isinstance(value,str):return value
    value=re.sub(r'(?i)(Bearer\s+)[\w.\-/+=]+',r'\1[已隐藏]',value)
    value=re.sub(r'(?i)((?:password|secret|token|cookie|authorization|api[_-]?key)\s*[=:]\s*)[^\s,;]+',r'\1[已隐藏]',value)
    value=re.sub(r'(?i)([?&](?:token|key|signature|auth|secret|credential|x-amz-signature)=)[^&\s]+',r'\1[已隐藏]',value)
    return value

def safe_command(args):
    result=[];hide=False
    for arg in args:
        if hide:result.append('[已隐藏]');hide=False;continue
        result.append(clean(arg))
        if re.match(r'^--?(?:password|token|secret|cookie|authorization|api[_-]?key)$',arg,re.I):hide=True
    return result

def raw_state():
    with store.connection() as db:
        runs=[json.loads(r['body']) for r in db.execute('SELECT body FROM runs ORDER BY rowid DESC')]
        tasks={r['id']:json.loads(r['body']) for r in db.execute('SELECT id,body FROM tasks')}
        events=[]
        for row in db.execute('SELECT seq,body FROM events ORDER BY seq'):
            item=json.loads(row['body']);item['seq']=row['seq'];events.append(item)
        issues={r['id']:json.loads(r['body']) for r in db.execute('SELECT id,body FROM issues')}
    return runs,tasks,events,issues

def file_items(run,events):
    paths=[];input_paths=set()
    for item in run.get('evidence',[]):
        if isinstance(item,str):paths.append(item)
        elif isinstance(item,dict) and item.get('path'):paths.append(item['path'])
    for ref in run.get('input_snapshot',{}).get('references',[]):
        if isinstance(ref,dict) and ref.get('path'):
            paths.append(ref['path']);input_paths.add(str(Path(ref['path']).expanduser().resolve()))
    for e in events:
        for item in e.get('evidence',[]) or []:
            if isinstance(item,str):paths.append(item)
            elif isinstance(item,dict) and item.get('path'):paths.append(item['path'])
    items=[];seen=set()
    for name in paths:
        path=Path(name).expanduser()
        if not path.is_absolute():continue
        path=path.resolve()
        if not any(path.is_relative_to(root) for root in [*MEDIA_ROOTS, store.DB.parent.resolve()]):continue
        if str(path) in seen:continue
        seen.add(str(path));exists=path.is_file();mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        key=hashlib.sha256((run['id']+'\0'+str(path)).encode()).hexdigest()[:32]
        items.append(dict(id=key,name=path.name,path=str(path),exists=exists,role='input' if str(path) in input_paths else 'output',type=mime,size=path.stat().st_size if exists else None,url='/api/files/'+key))
    return items

def steps_for(run,events):
    steps=[];structured={}
    for e in events:
        if e['type']=='step_started':
            step=dict(id=e['step_id'],title=e['summary'],kind=e.get('step_kind','tool'),status='running',at=e['at'],finished_at=None,
                      actor=e['actor'],inputs=e.get('inputs',{}),output='',error='',duration_ms=None,seq=e['seq'],evidence=[],
                      skill_slug=e.get('skill_slug'),parent_step_id=e.get('parent_step_id'),reason=e.get('reason',''),expected=e.get('expected',''))
            structured[step['id']]=step;steps.append(step)
        elif e['type']=='step_finished':
            step=structured.get(e['step_id'])
            if step:
                step.update(status=e['status'],output=e.get('output',''),error=e.get('error',''),finished_at=e['at'],
                            duration_ms=e.get('duration_ms'),evidence=e.get('evidence',[]),exit_code=e.get('exit_code'),outcome=e.get('outcome'))
        elif e['type'] in {'run_queued','run_started','progress','run_completed','run_failed','run_blocked','run_cancelled','context_read','skill_read','reference_read'}:
            if e['type']=='progress' and e.get('step_id') in structured:
                structured[e['step_id']].setdefault('notes',[]).append(e);continue
            title={'run_queued':'等待执行','run_started':'开始运行','run_completed':'运行结果','run_failed':'运行失败',
                   'run_blocked':'运行等待','run_cancelled':'运行取消','context_read':'读取 Skill 与本次输入'}.get(e['type'],'进度记录')
            if e['type'] in {'skill_read','reference_read'}:title=e['summary']
            steps.append(dict(id='event_'+str(e['seq']),title=title,kind=e['type'],status='failed' if e['type']=='run_failed' else 'completed',
                              at=e['at'],actor=e['actor'],inputs=run.get('input_snapshot',{}).get('form',{}) if e['type']=='run_started' else e.get('details',{}),
                              output=run.get('output','') if e['type']=='run_completed' else e['summary'],
                              summary=e['summary'],error=e['summary'] if e['type']=='run_failed' else '',duration_ms=None,seq=e['seq'],evidence=e.get('evidence',[]),
                              skill_slug=e.get('skill_slug'),parent_step_id=e.get('parent_step_id'),reason=e.get('reason',''),path=e.get('path'),sha256=e.get('sha256')))
    return steps

def automatic_issues(run,steps,files):
    issues=[]
    def add(key,title,step=None,kind='execution',position=None,description='',category=None):
        issues.append(dict(id=key+'_'+run['id'],run_id=run['id'],task_id=run['task_id'],title=title,description=description,
                           step_id=step['id'] if step else None,kind=kind,category=category or {'content':'output','file':'output','recording':'recording'}.get(kind,'execution'),
                           related_skill=step.get('skill_slug') if step else None,expected=step.get('expected','') if step else '',actual=step.get('output','') if step else '',
                           position_seconds=position,status='open',created_at=run.get('finished_at') or run['created_at'],source='record'))
    text=run.get('summary','')+'\n'+run.get('output','')
    # Compatibility adapter for the original reported problem, not a video diagnostic engine.
    match=re.search(r'(\d+(?:\.\d+)?)\s*秒[^\d\n；;。]{0,4}(?:接点|切点).{0,35}?(?:跳变|跳帧|不连续)',text)
    if match:
        pos=float(match.group(1));step=next((s for s in reversed(steps) if s['kind']=='run_completed'),None)
        add('reported_jump',f'{pos:g} 秒接点跳变',step,'content',pos,match.group(0))
        issues[-1].update(actual=match.group(0),basis='运行结果原文')
    is_test=bool(run.get('is_test'))
    middle=[s for s in steps if s['kind'] in {'tool','input','check','artifact','progress'}]
    if not is_test and (run.get('actor') or {}).get('kind')=='agent' and run['status'] in store.TERMINAL and not middle:
        add('missing_process','没有记录中间步骤',kind='recording',description='这次运行没有保存实际执行步骤。')
    failed=[s for s in steps if s['status']=='failed' and s['kind']!='run_failed']
    for step in failed:
        add('failed_'+step['id'],('检查不符：' if step['kind']=='check' else '执行失败：')+step['title'],step,description=step.get('error',''),category={'check':'output','tool':'tool','input':'input','reference':'input','skill':'routing'}.get(step['kind'],'execution'))
    if run['status']=='failed' and not failed:add('run_failed','运行失败',next((s for s in steps if s['kind']=='run_failed'),None),description=run.get('summary',''))
    for step in steps:
        if step.get('outcome')=='different' and step['status']!='failed':add('different_'+step['id'],'检查不符：'+step['title'],step,category='output')
        if step['status']=='running' and run['status'] in store.TERMINAL:add('unfinished_'+step['id'],'步骤没有记录返回：'+step['title'],step,kind='recording')
    groups={}
    for s in steps:
        if s['kind']=='tool':groups.setdefault(s['title'],[]).append(s)
    for title,attempts in groups.items():
        if len(attempts)>=3:
            add('repeat_'+hashlib.sha256(title.encode()).hexdigest()[:8],f'“{title}”执行 {len(attempts)} 次',attempts[-1],description='展开相同名称的步骤，对照每次输入和返回。')
    for file in files:
        if not file['exists']:add('missing_file_'+file['id'],('输入参考不存在：' if file['role']=='input' else '输出文件不存在：')+file['name'],kind='file',description=file['path'],category='input' if file['role']=='input' else 'output')
    return issues

def monitor():
    runs,tasks,events,saved=raw_state();result=[];all_issues=[];by_run={}
    current={s['slug']:s for s in catalog()['skills']}
    with store.connection() as db:snapshots={r['sha256']:json.loads(r['body']) for r in db.execute('SELECT sha256,body FROM skill_snapshots')}
    for e in events:
        if e.get('run_id'):by_run.setdefault(e['run_id'],[]).append(e)
    for raw in runs:
        run=dict(raw);run['title']=run.get('input_snapshot',tasks[run['task_id']])['form'].get('title','未命名运行')
        run['is_test']=bool(raw.get('is_test')) or '协作验收' in run['title']
        relevant=by_run.get(run['id'],[]);run['steps']=steps_for(run,relevant);run['files']=file_items(run,relevant)
        automatic=automatic_issues(run,run['steps'],run['files']);ids={i['id'] for i in automatic}
        run['issues']=[dict(i,**saved[i['id']]) if i['id'] in saved else i for i in automatic]
        run['issues'] += [v for v in saved.values() if v['run_id']==run['id'] and v['id'] not in ids]
        for item in run['issues']:item['category']=category_for(item)
        run['skill_trace']=[]
        for ref in run['skills']:
            snap=snapshots.get(ref.get('snapshot_id',ref['sha256']),{})
            reads=[e for e in relevant if e['type']=='skill_read' and e.get('skill_slug')==ref['slug']]
            context=any(e['type']=='context_read' and any(s['slug']==ref['slug'] for s in e.get('details',{}).get('skills',[])) for e in relevant)
            references=[]
            for r in snap.get('references',[]):
                hits=[e for e in relevant if e['type']=='reference_read' and e.get('skill_slug')==ref['slug'] and e.get('path')==r['path']]
                references.append(dict(name=r['name'],path=r['path'],sha256=r['sha256'],read_steps=['event_'+str(e['seq']) for e in hits]))
            live=current.get(ref['slug'],{})
            run['skill_trace'].append(dict(**ref,title=TITLES.get(ref['slug'],ref['slug']),version=snap.get('version',''),
                description=snap.get('description',''),reason=reads[-1].get('reason','') if reads else '',
                read_steps=['event_'+str(e['seq']) for e in reads],context_included=context,references=references,
                body_changed=live.get('sha256')!=ref['sha256'],references_changed=sorted((r['path'],r['sha256']) for r in live.get('references',[]))!=sorted((r['path'],r['sha256']) for r in references)))
        run['issue_count']=sum(i['status']!='resolved' for i in run['issues'])
        run['related_run_ids']=[r['id'] for r in runs if r['task_id']==run['task_id'] and r['id']!=run['id']]
        run['skill_titles']=[TITLES.get(s['slug'],s['slug']) for s in run['skills']]
        result.append(run);all_issues.extend(run['issues'])
    return clean(dict(runs=result,issues=all_issues,skills=[dict(slug=s[0],title=s[1]) for s in SPECS],
                      categories=CATEGORIES,sequence=events[-1]['seq'] if events else 0,read_at=store.now()))

def inspection(run_id,step_id=None,issue_id=None):
    """A read-only, self-contained handoff for exactly one run, with locked instructions."""
    view=monitor();run=next((r for r in view['runs'] if r['id']==run_id),None)
    if not run:raise store.StudioError('运行不存在',404)
    selected_step=next((s for s in run['steps'] if s['id']==step_id),None)
    selected_issue=next((i for i in run['issues'] if i['id']==issue_id),None)
    if step_id and not selected_step:raise store.StudioError('步骤不属于本次运行',404)
    if issue_id and not selected_issue:raise store.StudioError('问题不属于本次运行',404)
    return clean(dict(schema='seedance.inspection.v1',exported_at=store.now(),run=run,
                     focus=dict(step_id=step_id,issue_id=issue_id),
                     skill_instructions=[skill_snapshot(run_id,s['slug']) for s in run['skills']],
                     note='只读排查记录。正文和参考来自本次锁定版本；文件为原位置索引，未复制媒体。原因与改法应对应原要求、规则或实际步骤。'))

def registered_file(file_id):
    runs,tasks,events,_=raw_state()
    for run in runs:
        for item in file_items(run,[e for e in events if e.get('run_id')==run['id']]):
            if item['id']==file_id:
                if not item['exists']:raise store.StudioError('文件不存在',404)
                return item
    raise store.StudioError('文件没有登记在运行记录中',404)

def save_issue(value,who,issue_id=None):
    who=store.actor(who);data=monitor();all_runs={r['id']:r for r in data['runs']};found={i['id']:i for i in data['issues']}
    if issue_id:
        if issue_id not in found:raise store.StudioError('问题不存在',404)
        item=dict(found[issue_id])
    else:
        run_id=value.get('run_id')
        if run_id not in all_runs:raise store.StudioError('运行不存在',404)
        run=all_runs[run_id]
        if value.get('step_id') and value['step_id'] not in {s['id'] for s in run['steps']}:raise store.StudioError('步骤不存在',404)
        item=dict(id='issue_'+uuid.uuid4().hex[:12],run_id=run_id,task_id=run['task_id'],step_id=value.get('step_id'),kind='manual',
                  created_at=store.now(),status='open',source=who['kind'],title='',description='')
    for key in ['title','description','status','comparison_run_id','category','expected','actual','cause','fix','basis','related_skill','file_id']:
        if key in value:item[key]=value[key]
    if 'position_seconds' in value:
        position=value['position_seconds']
        if position is not None:
            position=float(position)
            if not 0<=position<=86400:raise store.StudioError('视频位置无效')
        item['position_seconds']=position
    item['category']=category_for(item)
    if item['category'] not in CATEGORIES:raise store.StudioError('问题类型无效')
    if item.get('related_skill') and item['related_skill'] not in {s['slug'] for s in all_runs[item['run_id']]['skills']}:raise store.StudioError('关联 Skill 不属于本次运行')
    if item.get('file_id') and item['file_id'] not in {f['id'] for f in all_runs[item['run_id']]['files']}:raise store.StudioError('关联文件不属于本次运行')
    if not str(item['title']).strip():raise store.StudioError('请填写具体问题')
    if item['status'] not in {'open','working','resolved'}:raise store.StudioError('问题状态无效')
    if item.get('comparison_run_id') and item['comparison_run_id'] not in all_runs:raise store.StudioError('对照运行不存在')
    item.update(updated_at=store.now(),updated_by=who)
    item=clean(item)
    with store.connection() as db:
        db.execute('INSERT OR REPLACE INTO issues VALUES (?,?,?)',(item['id'],item['run_id'],store.encode(item)))
        store.event(db,item['task_id'],'issue_updated',who,{'open':'记录问题：','working':'正在处理：','resolved':'已解决：'}[item['status']]+item['title'],run_id=item['run_id'],issue_id=item['id'])
    return item

def frame(file_id,at):
    item=registered_file(file_id)
    if not item['type'].startswith('video/'):raise store.StudioError('这个文件不是视频')
    at=float(at)
    if not 0<=at<=86400:raise store.StudioError('视频位置无效')
    import shutil
    executable=shutil.which('ffmpeg')
    if not executable:raise store.StudioError('本机没有 ffmpeg，直接打开视频查看',503)
    path=Path(item['path']);folder=store.DB.parent/'previews';folder.mkdir(exist_ok=True)
    cache=folder/(hashlib.sha256((file_id+str(path.stat().st_mtime_ns)+str(at)).encode()).hexdigest()+'.jpg')
    if cache.is_file():return cache.read_bytes()
    try:
        result=subprocess.run([executable,'-hide_banner','-loglevel','error','-ss',str(at),'-i',str(path),'-frames:v','1','-vf','scale=-2:320','-f','image2pipe','-vcodec','mjpeg','pipe:1'],capture_output=True,timeout=15)
    except subprocess.TimeoutExpired:raise store.StudioError('画面提取超时，请打开原视频',503)
    if result.returncode or not result.stdout:raise store.StudioError('这个位置没有可读取的画面',404)
    cache.write_bytes(result.stdout)
    return result.stdout

def assert_running(db,run_id,who):
    run=store.load(db,'runs',run_id)
    if run['status']!='running' or run['actor']!=who:raise store.StudioError('使用原执行者身份续接正在运行的记录',409)
    return run

def start_step(run_id,who,title,kind='tool',inputs=None,skill_slug=None,parent_step_id=None,reason='',expected=''):
    who=store.actor(who)
    if not title.strip():raise store.StudioError('步骤名称不能为空')
    if kind not in STEP_KINDS:raise store.StudioError('步骤类型无效')
    step_id='step_'+uuid.uuid4().hex[:12]
    with store.connection() as db:
        run=assert_running(db,run_id,who)
        if skill_slug and skill_slug not in {s['slug'] for s in run['skills']}:raise store.StudioError('先用 read-skill 记录本次调用，再关联步骤')
        events=[]
        for row in db.execute('SELECT seq,body FROM events WHERE task_id=?',(run['task_id'],)):
            e=json.loads(row['body']);e['seq']=row['seq'];events.append(e)
        validate_parent(events,run_id,parent_step_id)
        return store.event(db,run['task_id'],'step_started',who,clean(title),run_id=run_id,step_id=step_id,step_kind=kind,inputs=clean(inputs or {}),skill_slug=skill_slug,parent_step_id=parent_step_id,reason=clean(reason),expected=clean(expected))

def finish_step(run_id,step_id,who,status,output='',error='',duration_ms=None,evidence=None,exit_code=None,outcome=None):
    who=store.actor(who)
    if outcome not in {None,'matched','different'}:raise store.StudioError('检查结果无效')
    if status not in {'completed','failed'}:raise store.StudioError('步骤状态无效')
    with store.connection() as db:
        run=assert_running(db,run_id,who);started=False
        for r in db.execute('SELECT body FROM events WHERE task_id=?',(run['task_id'],)):
            e=json.loads(r['body'])
            if e.get('step_id')==step_id:
                if e['type']=='step_finished':raise store.StudioError('这一步已经结束',409)
                if e['type']=='step_started' and e.get('run_id')==run_id:started=True
        if not started:raise store.StudioError('步骤不存在',404)
        return store.event(db,run['task_id'],'step_finished',who,'步骤完成' if status=='completed' else '步骤失败',run_id=run_id,step_id=step_id,
                           status=status,output=clean(str(output)[-20000:]),error=clean(str(error)[-12000:]),duration_ms=duration_ms,evidence=clean(evidence or []),exit_code=exit_code,outcome=outcome)

def execute(run_id,who,title,args,cwd=None,skill_slug=None,parent_step_id=None,reason='',expected=''):
    if args and args[0]=='--':args=args[1:]
    if not args:raise store.StudioError('请在 -- 后提供要执行的命令')
    step=start_step(run_id,who,title,'tool',{'command':safe_command(args),'cwd':str(Path(cwd or Path.cwd()).resolve())},skill_slug,parent_step_id,reason,expected)
    start=time.monotonic()
    # Output goes to scratch files rather than an unbounded in-memory pipe.
    import tempfile,os
    folder=store.DB.parent/'scratch';folder.mkdir(exist_ok=True)
    with tempfile.TemporaryFile(dir=folder) as stdout,tempfile.TemporaryFile(dir=folder) as stderr:
        try:
            process=subprocess.Popen(args,cwd=cwd,stdout=stdout,stderr=stderr)
            try:code=process.wait()
            except KeyboardInterrupt:
                process.terminate();code=process.wait();raise
            def tail(file,limit):
                file.seek(0,os.SEEK_END);file.seek(max(0,file.tell()-limit));return file.read().decode('utf-8','replace')
            result=finish_step(run_id,step['step_id'],who,'completed' if code==0 else 'failed',tail(stdout,20000),tail(stderr,12000),round((time.monotonic()-start)*1000),exit_code=code)
            return result,code
        except (OSError,KeyboardInterrupt) as exc:
            result=finish_step(run_id,step['step_id'],who,'failed',error=type(exc).__name__+': '+str(exc),duration_ms=round((time.monotonic()-start)*1000))
            return result,130 if isinstance(exc,KeyboardInterrupt) else 127
