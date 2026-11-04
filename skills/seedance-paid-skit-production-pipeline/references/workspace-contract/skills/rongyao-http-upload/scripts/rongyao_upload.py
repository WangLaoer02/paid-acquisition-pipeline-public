#!/usr/bin/env python3
import argparse,json,socket,sys,time
from pathlib import Path
BASE=Path.home()/'.codex/state/rongyao-upload-http'
def rpc(command,session=None,_restored=False,**kwargs):
    if command=='probe' and not session:raise ValueError('PROBE_REQUIRES_EXPLICIT_EXISTING_SESSION')
    candidates=[BASE/(session+'.json')] if session else sorted(BASE.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for p in candidates:
        m=json.loads(p.read_text());sock=Path(m['socket'])
        if sock.parent!=BASE or sock.name!=m['session_id']+'.sock':raise ValueError('INVALID_SESSION_METADATA')
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as c:
                c.settimeout(10 if command=='probe' else 240);c.connect(str(sock));c.sendall((json.dumps({'command':command,**kwargs})+'\n').encode());line=c.makefile('rb').readline(4_000_000)
                if not line:raise ValueError('UPLOAD_SERVICE_CONNECTION_CLOSED_RECONCILE_BEFORE_RETRY')
                return json.loads(line)
        except (FileNotFoundError,ConnectionRefusedError):continue
    if session is None and not _restored and command not in ('stop','probe'):
        sys.path.insert(0,str(Path.home()/'.codex/skills/rongyao-http-readonly/scripts'))
        from session_store import restore_service
        restored=restore_service(BASE/'restored',scope='upload')
        if restored:return rpc(command,restored['session_id'],_restored=True,**kwargs)
    raise ValueError('NO_RUNNING_UPLOAD_HTTP_SESSION')
def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('start');q.add_argument('--output-dir',required=True);q.add_argument('--new-session',action='store_true')
    for name in ('status','stop','fields','probe','prefix','lookup','submit','reconcile','detail','finalize-attribution','correct-metadata'):
        q=sub.add_parser(name);q.add_argument('--session',required=name=='probe')
        if name in ('fields','probe'):q.add_argument('--gid');q.add_argument('--source-type')
        if name=='prefix':q.add_argument('--prefix',required=True)
        if name=='lookup':q.add_argument('--name',required=True)
        if name=='submit':
            for key in ('plan','workspace','authorization-ticket'):q.add_argument('--'+key,required=True)
        if name=='reconcile':q.add_argument('--job-id',required=True);q.add_argument('--refresh-details',action='store_true')
        if name=='detail':q.add_argument('--name',required=True);q.add_argument('--record-id',required=True)
        if name in ('finalize-attribution','correct-metadata'):
            for key in ('job-id','workspace','authorization-ticket'):q.add_argument('--'+key,required=True)
    a=p.parse_args()
    try:
        if a.command=='start':
            if not a.new_session:
                try:
                    r=rpc('status')
                    if r.get('status')=='ready':print(json.dumps(r));return
                except ValueError as e:
                    if str(e)!='NO_RUNNING_UPLOAD_HTTP_SESSION':raise
            sys.path.insert(0,str(Path.home()/'.codex/skills/rongyao-http-readonly/scripts'))
            from sms_login import launch
            sys.exit(launch(a.output_dir,service='upload',restore_existing=not a.new_session))
        args=vars(a).copy();cmd=args.pop('command');session=args.pop('session');r=rpc(cmd,session,**args);print(json.dumps(r,ensure_ascii=False));sys.exit(0 if r.get('ok') else 1)
    except Exception as e:
        message=str(e);print(json.dumps({'ok':False,'error':message if message.replace('_','').isalnum() else type(e).__name__,'browser_started':False,'automatic_retry':False}));sys.exit(1)
if __name__=='__main__':main()
