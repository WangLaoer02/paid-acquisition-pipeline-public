"""Normal Rongyao code login; secrets injected by the trusted Keychain helper."""
import json,os,sys,urllib.request,urllib.parse,http.cookiejar,getpass,re,uuid,socket,time
from pathlib import Path
# SOURCE, OUTPUT, KEYRING and PRIVATE are injected as non-secret fixed paths.
ROOT=KEYRING
BACKUP=PRIVATE/'worker-original.py'
(ROOT/'worker.py').write_bytes(BACKUP.read_bytes())
(ROOT/'keyring.py').write_bytes((PRIVATE/'cli-original.py').read_bytes())
sys.path.insert(0,str(SOURCE))
from http_core import Engine,PORTAL
from rongyao_http import serve_engine
from http_transport import PasswordSessionTransport as Transport
def parse_result(b):
 r=json.loads(b)
 if isinstance(r,str):r=json.loads(r)
 return r

def run():
 tty=sys.stderr
 transport=Transport();transport.request(PORTAL)
 sys.path.insert(0,str(SOURCE))
 from sms_receiver import baseline,receive
 after_rowid=baseline();requested_at=time.time()
 # Same sendMessage action as the normal portal's 获取验证码 button, exactly once.
 _,_,b=transport.request(PORTAL+'?_c=login&_a=sendMessage',{'username':os.environ['RONGYAO_USERNAME']})
 r=parse_result(b)
 if r.get('status') not in (True,1,'1'):
  tty.write('后台未受理验证码发送，本次停止。\n');tty.flush()
  (OUTPUT/'login-status.json').write_text(json.dumps({'ok':False,'stage':'send_verification_code','accepted':False,'browser_started':False},ensure_ascii=False,indent=2))
  return {'ok':False,'status':'VERIFICATION_CODE_NOT_SENT','browser_started':False}
 tty.write('验证码已发送，正在从本机信息自动接收。无需手动填写。\n');tty.flush()
 metadata=OUTPUT/'login-status.json'
 metadata.write_text(json.dumps({'stage':'waiting_local_sms','code_sent':True,'created_at':requested_at}));metadata.chmod(0o600)
 code=receive(after_rowid,requested_at)
 metadata.write_text(json.dumps({'stage':'login_submission_pending','code_sent':True,'code_received_locally':True}));metadata.chmod(0o600)
 _,_,b=transport.request(PORTAL+'?_c=login&_a=login',{'username':os.environ['RONGYAO_USERNAME'],'password':os.environ['RONGYAO_PASSWORD'],'code':code,'token':''})
 r=parse_result(b);del code
 metadata.write_text(json.dumps({'stage':'login_accepted' if r.get('status') in (True,1,'1') else 'login_not_accepted','code_sent':True}));metadata.chmod(0o600)
 if r.get('status') not in (True,1,'1'):
  tty.write('后台未接受本次登录，已停止，不自动重试。\n');tty.flush();return {'ok':False,'status':'VERIFICATION_LOGIN_NOT_ACCEPTED'}
 dest=urllib.parse.urljoin(PORTAL,r.get('url') or '/');transport.request(dest)
 engine=Engine(transport=transport,authenticated=False);engine._session_scope=SERVICE_KIND;engine.finish_portal();engine.state.update(feishu_qr_authenticated=False,authentication_method='existing_keychain_password_and_fresh_sms');result=engine.read_list()
 out=OUTPUT;out.mkdir(parents=True,exist_ok=True);(out/'video-list.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 tty.write('认证成功，已读取视频列表首页。认证服务将在本机继续运行。\n');tty.flush()
 from session_store import remember
 remember(engine,SERVICE_KIND)
 # Give the reusable service no credential environment once login finishes.
 os.environ.pop('RONGYAO_USERNAME',None);os.environ.pop('RONGYAO_PASSWORD',None)
 sid=uuid.uuid4().hex[:10]
 engine.state.update(authentication_method='existing_keychain_password_and_fresh_sms',feishu_qr_authenticated=False)
 (out/'login-receipt.json').write_text(json.dumps({'ok':True,'session_id':sid,'authentication_method':'existing_keychain_password_and_fresh_sms','code_received_locally':True,'code_persisted':False,'send_code_count':1,'cookies_persisted':engine.state.get('cookies_persisted',False),'session_storage':engine.state.get('session_storage'),'total':result['total'],'row_count':result['row_count'],'browser_started':False,'browser_connected':False}))
 if engine.state.get('cookies_persisted'):
  from session_store import spawn
  started=spawn(engine,out,LIFETIME,SERVICE_KIND,session_id=sid)
  started['status']='HTTP_UPLOAD_SERVICE_STARTED' if SERVICE_KIND=='upload' else 'HTTP_SERVICE_STARTED'
  return started
 pid=os.fork()
 if pid==0:
  os.setsid()
  fd=os.open('/dev/null',os.O_RDWR)
  for target in (0,1,2):os.dup2(fd,target)
  if fd>2:os.close(fd)
  try:
   if SERVICE_KIND=='upload':
    sys.path.insert(0,str(UPLOAD_SOURCE))
    from upload_service import serve_upload_engine
    serve_upload_engine(engine,out,session_id=sid,lifetime=LIFETIME)
   else:serve_engine(engine,out,session_id=sid,lifetime=LIFETIME)
  finally:os._exit(0)
 tty.write('本机认证服务已启动，会话ID：'+sid+'。可以关闭此输入窗口。\n');tty.flush()
 return {'ok':True,'status':'HTTP_UPLOAD_SERVICE_STARTED' if SERVICE_KIND=='upload' else 'HTTP_SERVICE_STARTED','session_id':sid,'browser_started':False,'cookies_persisted':engine.state.get('cookies_persisted',False)}

