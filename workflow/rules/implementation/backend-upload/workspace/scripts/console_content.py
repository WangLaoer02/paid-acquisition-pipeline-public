#!/usr/bin/env python3
"""Local console-content preflight; delegates writes to the sealed named-slot helper."""
import argparse,json,re,subprocess,sys,hashlib,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import workflow_runtime as runtime
PUBLIC_TEXT_SLOTS={'original_copy','structure','script','video_prompt','checkpoint','dialogue','shot_scale','camera','sound','duration'}
TECHNICAL=re.compile(r'ASR|SHA(?:256)?|ffmpeg|ffprobe|Whisper|机器转写|机器转录|抽帧|采样|完整解码|字节一致|\b\d+(?:\.\d+)?\s*fps\b|\d{3,}\s*[×xX]\s*\d{3,}|原版视觉核对|技术核验|不代表.*验收',re.I)
STORY_SLOTS={'original_copy','script','dialogue','structure'}
def story_preflight(slot,content):
    if slot not in STORY_SLOTS:return
    normalized=unicodedata.normalize('NFKC',content)
    for line in normalized.splitlines():
        # A character can say the literal name of a segment. Production notes
        # outside quoted dialogue belong in the visible remarks slot.
        if re.match(r'^\s*[^：:\n]{1,24}[：:]\s*[“「"]',line):continue
        if re.search(r'(?<![A-Za-z])B\s*段',line,re.I):
            raise ValueError('A_STORY_BODY_ONLY: move B-segment selection, joining and delivery explanations to --slot remarks; keep A-story dialogue/actions here.')
    if slot in {'original_copy','script'} and re.search(r'(?m)^\s{2,}(?:场景|画风|角色|A段|动作|说话)\s*$',content):
        raise ValueError('STORY_READABLE_FORMAT_REQUIRED: use the registered storyboard shot rows; preserve the source words/actions instead of copying mindmap indentation.')
def preflight(slot,payload):
    if payload.get('note') not in (None,'') or any(k in payload for k in ('comment','comments')):
        raise ValueError('CONSOLE_NOTES_FORBIDDEN: user forbids cell notes/comments; keep explanations in visible slots or evidence.')
    if payload.get('rich_text') == []:
        raise ValueError('EMPTY_RICH_TEXT_UNSUPPORTED: use explicit value empty string; retained references still protected.')
    if slot not in PUBLIC_TEXT_SLOTS:return
    content=str(payload.get('value',''))+'\n'+''.join(str(r.get('text','')) for r in payload.get('rich_text',[]))
    story_preflight(slot,content)
    if 'formula' in payload or 'multiple_values' in payload:raise ValueError('CONTENT_REVIEW_REQUIRED: text slot requires visible text.')
    if TECHNICAL.search(content):raise ValueError('CONSOLE_CONTENT_MISMATCH: keep technical verification in local evidence, not business text.')
    if slot=='original_copy' and re.search(r'视觉核对|画面核对|结构分析|原版视觉|改编方向|因果：',content):raise ValueError('CONSOLE_CONTENT_MISMATCH: original_copy is source copy, not an analysis summary.')
def image_plan_without_notes(original,template,contract,slot,index,old,image,caption,source_url=''):
    """Keep the published image/ref protections and apply the user's no-note override."""
    coord,payload=original(contract,slot,index,old,image,caption,source_url)
    payload['note']=None
    preflight(slot,payload)
    template.plan_patch(contract,slot,index,old,payload)
    return coord,payload

def mount_image_without_notes(args):
    import console_template as template
    original=template.plan_image
    def plan(contract,slot,index,old,image,caption,source_url=''):
        return image_plan_without_notes(original,template,contract,slot,index,old,image,caption,source_url)
    # A process-local override leaves the sealed release files unchanged.
    template.plan_image=plan
    try:
        return template.mount_image(args.project,args.slot,args.index,args.image,args.expected_sha256,args.caption,args.source_url,args.receipt)
    finally:
        template.plan_image=original

def prepare_operations(project,operations,verify_prompts=True):
    """Local checks for slot/index/payload operations; retain prompt evidence for the helper."""
    import console_template as template
    if not isinstance(operations,list) or not operations:raise ValueError('Nonempty operations array required.')
    contract=template.contract_for(template.resolve(project));prepared=[]
    for op in operations:
        if not isinstance(op,dict) or set(op)-{'slot','index','payload','prompt_review','prompt_review_sha256'} or not isinstance(op.get('slot'),str) or not isinstance(op.get('payload'),dict):
            raise ValueError('Operation requires slot/index/payload and optional prompt_review.')
        payload=dict(op['payload']);preflight(op['slot'],payload)
        item={'slot':op['slot'],'payload':payload}
        if op['slot']=='video_prompt':
            if not op.get('prompt_review'):raise ValueError('PROMPT_REVIEW_REQUIRED: each video_prompt operation needs its own review.')
            item['prompt_review']=op['prompt_review']
            if verify_prompts:
                import prompt_contract
                raw=Path(op['prompt_review']).read_bytes();digest=hashlib.sha256(raw).hexdigest()
                if op.get('prompt_review_sha256',digest)!=digest:raise ValueError('PROMPT_REVIEW_CHANGED_AFTER_PREFLIGHT')
                prompt_contract.check(payload,json.loads(raw),ROOT);item['prompt_review_sha256']=digest
        payload['note']=None
        if 'index' in op:item['index']=op['index']
        prepared.append(item)
    template.batch_targets(contract,prepared)
    for op in prepared:template.plan_patch(contract,op['slot'],op.get('index'),{},op['payload'])
    return prepared

def ensure_no_pending_batch(project,allowed_canonical=None):
    """Freeze new project writes while any already-sent batch remains unresolved."""
    allowed=Path(allowed_canonical).resolve() if allowed_canonical is not None else None
    for path in (ROOT/'workflow/runtime/console-batches').glob('*.json'):
        if path.resolve()==allowed:continue
        try:journal=json.loads(path.read_text())
        except (ValueError,OSError):raise ValueError('CONSOLE_BATCH_JOURNAL_INVALID: preserve '+str(path)) from None
        if not isinstance(journal,dict):raise ValueError('CONSOLE_BATCH_JOURNAL_INVALID: preserve '+str(path))
        sent=journal.get('submission_attempted') or journal.get('state') in {'SUBMITTING','OUTCOME_UNKNOWN','PARTIAL'}
        if journal.get('identity',{}).get('project')==project and sent and journal.get('state')!='VERIFIED' and journal.get('remote_outcome_confirmed') is not True:
            raise ValueError('CONSOLE_BATCH_PENDING: use check --operations --receipt to reconcile '+str(path.relative_to(ROOT))+'; no new project write performed.')

def batch_command(args):
    reconcile=args.command=='check' and bool(args.receipt)
    operations=prepare_operations(args.project,json.loads(Path(args.operations).read_text()),verify_prompts=not reconcile)
    if args.command=='check' and not reconcile:
        print(json.dumps({'ok':True,'operations':len(operations),'automatic_screen_only':True,'side_effects':[]}));return
    if not args.receipt:raise ValueError('Batch patch requires --receipt; use check with the same intent to reconcile.')
    receipt=Path(args.receipt).resolve()
    if not receipt.is_relative_to(ROOT):raise ValueError('Receipt must stay within this workspace.')
    raw=json.dumps(operations,ensure_ascii=False,sort_keys=True,indent=2)+'\n';digest=hashlib.sha256(raw.encode()).hexdigest()
    prepared=receipt.with_suffix('.content-batch-'+digest[:12]+'.json');prepared.parent.mkdir(parents=True,exist_ok=True)
    if prepared.exists():
        if prepared.read_text()!=raw:raise ValueError('BATCH_PREPARED_INPUT_CHANGED: preserve the existing batch input.')
    else:
        with prepared.open('x',encoding='utf-8') as stream:stream.write(raw)
    command=[sys.executable,str(ROOT/'scripts/console_template.py'),'batch','--project',args.project,'--payload',str(prepared),'--expected-payload-sha256',digest,'--receipt',str(receipt)]
    if reconcile:command.append('--reconcile-only')
    def execute():
        return subprocess.run(command,cwd=ROOT,check=True,env={**__import__('os').environ,'WORKFLOW_CONSOLE_DELEGATED':'1'})
    scope='console:'+args.project
    if reconcile:
        runtime.ensure_release(True)
        with runtime.lock(scope,'console_write'):execute()
    else:
        with runtime.mutation('console_write',scope):
            ensure_no_pending_batch(args.project);execute();runtime.event('console_write','verified',scope,project=args.project,operations=len(operations),input_sha256=digest,receipt=str(receipt.relative_to(ROOT)))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['check','patch','image']);parser.add_argument('--project',required=True);parser.add_argument('--slot');parser.add_argument('--payload');parser.add_argument('--receipt');parser.add_argument('--index',type=int);parser.add_argument('--image');parser.add_argument('--expected-sha256');parser.add_argument('--caption');parser.add_argument('--source-url',default='');parser.add_argument('--prompt-review');parser.add_argument('--operations',help='JSON array of {slot,index,payload,prompt_review?}; batch check/patch; check with --receipt reconciles the canonical batch without resending');args=parser.parse_args()
    if args.operations:
        if args.command=='image' or args.slot or args.payload or args.index is not None or args.prompt_review or args.image or args.expected_sha256 or args.caption or args.source_url:parser.error('--operations is exclusive with single-slot arguments; put prompt_review in each operation')
        return batch_command(args)
    if not args.slot:parser.error('--slot or --operations is required')
    if args.command=='image':
        if not all([args.image,args.expected_sha256,args.caption,args.receipt]):parser.error('image requires local image, expected SHA, caption and receipt')
        scope='console:'+args.project
        with runtime.mutation('console_write',scope):
            ensure_no_pending_batch(args.project)
            result=mount_image_without_notes(args)
            runtime.event('console_write','verified',scope,project=args.project,slot=args.slot,index=args.index,input_sha256=args.expected_sha256,receipt=args.receipt)
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if not args.payload:parser.error('check/patch requires --payload')
    payload=json.loads(Path(args.payload).read_text());preflight(args.slot,payload)
    if args.slot=='video_prompt':
        if not args.prompt_review:raise ValueError('PROMPT_REVIEW_REQUIRED: bind current format and source/scope evidence before writing.')
        import prompt_contract
        prompt_contract.check(payload,json.loads(Path(args.prompt_review).read_text()),ROOT)
    if args.command=='check':print(json.dumps({'ok':True,'slot':args.slot,'automatic_screen_only':True}));return
    if not args.receipt:parser.error('patch requires --receipt')
    if not Path(args.receipt).resolve().is_relative_to(ROOT):
        raise ValueError('Receipt must stay within this workspace.')
    # Null clears an existing note and never creates a corner marker.
    payload['note']=None
    prepared=Path(args.receipt).with_suffix('.no-notes.payload.json');prepared.parent.mkdir(parents=True,exist_ok=True);prepared.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    cmd=[sys.executable,str(ROOT/'scripts/console_template.py'),'patch','--project',args.project,'--slot',args.slot,'--payload',str(prepared),'--receipt',args.receipt]
    if args.index is not None:cmd+=['--index',str(args.index)]
    scope='console:'+args.project
    payload_sha=hashlib.sha256(prepared.read_bytes()).hexdigest()
    with runtime.mutation('console_write',scope):
        ensure_no_pending_batch(args.project)
        subprocess.run(cmd,cwd=ROOT,check=True,env={**__import__('os').environ,'WORKFLOW_CONSOLE_DELEGATED':'1'})
        runtime.event('console_write','verified',scope,project=args.project,slot=args.slot,index=args.index,input_sha256=payload_sha,receipt=args.receipt)
if __name__=='__main__':
    try:main()
    except (ValueError,subprocess.CalledProcessError) as error:print(str(error),file=sys.stderr);raise SystemExit(1)
