"""Agent CLI; same SQLite store as the UI, works while the HTTP server is stopped."""
import argparse, json, sys
from pathlib import Path
import store
import diagnostics

def read_json(path):
    return json.load(sys.stdin) if path=='-' else json.loads(Path(path).read_text())

def compact_instructions(value):
    """Keep locked snapshots intact; disclose only entry text and reference indexes."""
    if isinstance(value, list):
        return [compact_instructions(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: compact_instructions(v) for k, v in value.items()}
    if 'body' in value and 'sha256' in value and 'references' in value:
        result['references'] = [{k: v for k, v in r.items() if k != 'body'} for r in value['references']]
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--include-references',action='store_true',help='Return reference bodies as well as their index (explicit review/export only)')
    p.add_argument('--actor',default='Codex');p.add_argument('--kind',choices=['agent','human'],default='agent')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ['state','pending','runs']: sub.add_parser(name)
    s=sub.add_parser('inspect');s.add_argument('--run',required=True);s.add_argument('--step');s.add_argument('--issue')
    s=sub.add_parser('new');s.add_argument('--json',required=True)
    s=sub.add_parser('update');s.add_argument('--task',required=True);s.add_argument('--revision',type=int,required=True);s.add_argument('--json',required=True)
    s=sub.add_parser('activate');s.add_argument('--task',required=True)
    s=sub.add_parser('context');s.add_argument('--task',required=True);s.add_argument('--run')
    for name in ['start','queue']:
        s=sub.add_parser(name);s.add_argument('--task',required=True);s.add_argument('--skill',action='append');s.add_argument('--summary',default='');s.add_argument('--request-key')
    s=sub.add_parser('claim');s.add_argument('--run',required=True)
    s=sub.add_parser('note');s.add_argument('--task',required=True);s.add_argument('--run');s.add_argument('--summary',required=True)
    s=sub.add_parser('finish');s.add_argument('--run',required=True);s.add_argument('--status',choices=sorted(store.TERMINAL),required=True);s.add_argument('--summary',required=True);s.add_argument('--output-file');s.add_argument('--evidence',action='append',default=[])
    s=sub.add_parser('step-start');s.add_argument('--run',required=True);s.add_argument('--title',required=True);s.add_argument('--type',choices=sorted(diagnostics.STEP_KINDS),default='tool');s.add_argument('--input-json');s.add_argument('--skill');s.add_argument('--parent-step');s.add_argument('--reason',default='');s.add_argument('--expected',default='')
    s=sub.add_parser('step-finish');s.add_argument('--run',required=True);s.add_argument('--step',required=True);s.add_argument('--status',choices=['completed','failed'],required=True);s.add_argument('--output-file');s.add_argument('--error',default='');s.add_argument('--evidence',action='append',default=[]);s.add_argument('--outcome',choices=['matched','different'])
    s=sub.add_parser('read-skill');s.add_argument('--run',required=True);s.add_argument('--skill',required=True);s.add_argument('--reason',default='');s.add_argument('--reference');s.add_argument('--parent-step')
    s=sub.add_parser('issue');s.add_argument('--json',required=True);s.add_argument('--id')
    s=sub.add_parser('exec');s.add_argument('--run',required=True);s.add_argument('--title',required=True);s.add_argument('--cwd');s.add_argument('--skill');s.add_argument('--parent-step');s.add_argument('--reason',default='');s.add_argument('--expected',default='');s.add_argument('args',nargs=argparse.REMAINDER)
    a=p.parse_args();who={'kind':a.kind,'name':a.actor}
    if a.command=='state': result=store.workspace()
    elif a.command=='runs':result=diagnostics.monitor()
    elif a.command=='inspect':result=diagnostics.inspection(a.run,a.step,a.issue)
    elif a.command=='pending': result=store.pending()
    elif a.command=='new': result=store.create_task(read_json(a.json),who)
    elif a.command=='update': result=store.update_task(a.task,read_json(a.json),who,a.revision)
    elif a.command=='activate': result=store.activate(a.task,who)
    elif a.command=='context': result=store.context(a.task,a.run)
    elif a.command in {'start','queue'}: result=store.start_run(a.task,who,a.skill,a.command=='queue',a.summary,a.request_key)
    elif a.command=='claim': result=store.claim_run(a.run,who)
    elif a.command=='note': result=store.add_note(a.task,who,a.summary,a.run)
    elif a.command=='step-start':result=diagnostics.start_step(a.run,who,a.title,a.type,read_json(a.input_json) if a.input_json else {},a.skill,a.parent_step,a.reason,a.expected)
    elif a.command=='step-finish':result=diagnostics.finish_step(a.run,a.step,who,a.status,Path(a.output_file).read_text() if a.output_file else '',a.error,evidence=a.evidence,outcome=a.outcome)
    elif a.command=='read-skill':result=diagnostics.read_skill(a.run,who,a.skill,a.reason,a.reference,a.parent_step)
    elif a.command=='issue':result=diagnostics.save_issue(read_json(a.json),who,a.id)
    elif a.command=='exec':
        result,code=diagnostics.execute(a.run,who,a.title,a.args,a.cwd,a.skill,a.parent_step,a.reason,a.expected)
        print(json.dumps(result,ensure_ascii=False,indent=2));return code
    else: result=store.finish_run(a.run,who,a.status,a.summary,Path(a.output_file).read_text() if a.output_file else '',a.evidence)
    if not a.include_references and a.command in {'context', 'read-skill'}:
        result = compact_instructions(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except store.StudioError as exc:
        print(json.dumps({'error':str(exc),'status':exc.status},ensure_ascii=False),file=sys.stderr);sys.exit(1)
