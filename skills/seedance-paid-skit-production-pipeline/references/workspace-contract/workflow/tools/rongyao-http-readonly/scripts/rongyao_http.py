#!/usr/bin/env python3
"""Rongyao HTTP session with device-local Keychain restore and original bounded query RPC."""
import argparse,hashlib,json,os,re,socket,socketserver,sys,threading,time,uuid,signal
from pathlib import Path
from http_core import Engine,VERSION
BASE=Path.home()/'.codex/state/rongyao-http'
def dump(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def safe_error(e):
 message=str(e)
 return message if re.fullmatch(r'[A-Z0-9_]+',message) else type(e).__name__
def serve_engine(engine,output_dir,session_id=None,lifetime=3600):
 if threading.current_thread() is threading.main_thread():signal.alarm(0)
 BASE.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(BASE,0o700)
 sid=session_id or uuid.uuid4().hex[:10];sock=BASE/(sid+'.sock');meta=BASE/(sid+'.json')
 lock=threading.Lock();stop=threading.Event();out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
 metadata={'session_id':sid,'pid':os.getpid(),'socket':str(sock),'version':VERSION,'cookies_persisted':engine.state.get('cookies_persisted',False),'created_at':time.time()}
 meta.write_text(json.dumps(metadata));os.chmod(meta,0o600)
 def reply(request):
  command=request.get('command')
  if command=='status':return {'ok':True,'session_id':sid,**engine.status()}
  if command=='stop':stop.set();return {'ok':True,'session_id':sid,'stopping':True}
  with lock:
   if command=='video-list':
    result=engine.read_list();(out/'video-list.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return {'session_id':sid,**result}
   if command=='query':
    # Bounded GET-only filtered read. The module is reloaded per call so query
    # or parser fixes never require a new login. No cookie or credential output.
    import importlib,weekly_query
    params=request.get('params')
    if not isinstance(params,dict) or len(params)>30:raise ValueError('INVALID_QUERY_PARAMS')
    if any(not isinstance(k,str) or not isinstance(v,str) for k,v in params.items()):raise ValueError('INVALID_QUERY_PARAMS')
    result=importlib.reload(weekly_query).query_list(engine,params)
    (out/'query-last.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return {'session_id':sid,**result}
   if command=='refresh':
    if engine.state['status']=='ready':return {'ok':True,'session_id':sid,**engine.status()}
    return {'ok':True,'session_id':sid,**engine.start(out)}
  raise ValueError('INVALID_READONLY_COMMAND')
 class Handler(socketserver.StreamRequestHandler):
  def handle(self):
   try:
    line=self.rfile.readline(4097)
    if len(line)>4096:raise ValueError('RPC_REQUEST_TOO_LARGE')
    result=reply(json.loads(line))
   except Exception as e:result={'ok':False,'error':safe_error(e),'browser_started':False}
   self.wfile.write((json.dumps(result,ensure_ascii=False)+'\n').encode())
 server=socketserver.ThreadingUnixStreamServer(str(sock),Handler);os.chmod(sock,0o600);server.timeout=.5;server.daemon_threads=True
 def auth_worker():
  try:
   if engine.state['status']!='ready':
    with lock:state=engine.start(out)
    dump({'event':'qr_ready','session_id':sid,**state})
   last=None
   while not stop.is_set():
    if engine.state['status'] in ('waiting_scan','waiting_confirmation'):
     with lock:state=engine.poll()
     if state['status']!=last:
      last=state['status'];dump({'event':'auth_status','session_id':sid,**state})
      if last=='ready':
       with lock:result=engine.read_list()
       (out/'video-list.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
       dump({'event':'list_verified','session_id':sid,'total':result['total'],'row_count':result['row_count'],'coverage':result['coverage']})
    stop.wait(.5)
  except Exception as e:
   engine.state.update(status='blocked',error=safe_error(e));dump({'event':'blocked','session_id':sid,'error':safe_error(e)})
 thread=threading.Thread(target=auth_worker,daemon=True);thread.start()
 dump({'event':'session_started','session_id':sid,**engine.status()})
 deadline=time.monotonic()+lifetime
 try:
  while not stop.is_set() and time.monotonic()<deadline:server.handle_request()
 finally:
  stop.set();server.server_close();sock.unlink(missing_ok=True);meta.unlink(missing_ok=True)
 return sid

def rpc(command,session_id=None,params=None,_restored=False):
 if session_id and not re.fullmatch(r'[0-9a-f]{10}',session_id):raise ValueError('INVALID_SESSION_ID')
 candidates=[BASE/(session_id+'.json')] if session_id else sorted(BASE.glob('*.json'),key=lambda x:x.stat().st_mtime,reverse=True)
 for path in candidates:
  if not path.is_file() or not re.fullmatch(r'[0-9a-f]{10}\.json',path.name):continue
  metadata=json.loads(path.read_text());sock=Path(metadata['socket'])
  if sock.parent!=BASE or sock.name!=metadata['session_id']+'.sock':raise ValueError('INVALID_SESSION_METADATA')
  try:
   request={'command':command}
   if params is not None:request['params']=params
   with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(180);client.connect(str(sock));client.sendall((json.dumps(request)+'\n').encode())
    f=client.makefile('rb');line=f.readline(4_000_000)
    return json.loads(line)
  except (ConnectionRefusedError,FileNotFoundError):
   if session_id:raise ValueError('HTTP_SESSION_NOT_RUNNING')
 if session_id is None and not _restored and command in ('status','video-list','refresh','query'):
  from session_store import restore_service
  restored=restore_service(BASE/'restored',scope='readonly')
  if restored:return rpc(command,restored['session_id'],params,_restored=True)
 raise ValueError('NO_RUNNING_HTTP_SESSION')
def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 start=sub.add_parser('start');start.add_argument('--output-dir',required=True);start.add_argument('--lifetime',type=int,default=86400);start.add_argument('--method',choices=['sms','feishu-qr'],default='sms');start.add_argument('--new-session',action='store_true')
 bind=sub.add_parser('sms-bind');bind.add_argument('--rowid',type=int,required=True)
 for name in ('status','video-list','refresh','stop'):
  cmd=sub.add_parser(name);cmd.add_argument('--session');
  if name=='video-list':cmd.add_argument('--output')
 query=sub.add_parser('query');query.add_argument('--session');query.add_argument('--filters-json',required=True);query.add_argument('--output');query.add_argument('--summary',action='store_true')
 a=p.parse_args()
 try:
  if a.command=='sms-bind':
   from sms_login import bind_source
   dump(bind_source(a.rowid));return
  if a.command=='start':
   if not a.new_session:
    try:
     existing=rpc('status')
     if existing.get('status')=='ready':
      result=rpc('video-list',existing['session_id']);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True);(out/'video-list.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');dump({'ok':True,'status':'REUSED_HTTP_SESSION','session_id':existing['session_id'],'total':result['total'],'row_count':result['row_count'],'browser_started':False});return
    except ValueError as e:
     if str(e) not in ('NO_RUNNING_HTTP_SESSION','HTTP_SESSION_NOT_RUNNING','LOGIN_EXPIRED'):raise
   if a.method=='sms':
    from sms_login import launch
    sys.exit(launch(a.output_dir,a.lifetime,restore_existing=not a.new_session))
   serve_engine(Engine(),a.output_dir,lifetime=a.lifetime);return
  if a.command=='query':
   try:params=json.loads(a.filters_json)
   except ValueError:raise ValueError('INVALID_FILTERS_JSON')
   result=rpc('query',a.session,params)
   if a.output:
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
   if a.summary:dump({k:result.get(k) for k in ('ok','session_id','query','total','row_count','observed_at','error')})
   else:dump({k:v for k,v in result.items() if k not in ('cards','card_markup_samples','filter_code','date_picker_code')})
   if not result.get('ok'):sys.exit(1)
   return
  result=rpc(a.command,a.session)
  if a.command=='video-list' and a.output:
   path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
  dump(result)
  if not result.get('ok'):sys.exit(1)
 except Exception as e:dump({'ok':False,'error':safe_error(e),'browser_started':False});sys.exit(1)
if __name__=='__main__':main()
