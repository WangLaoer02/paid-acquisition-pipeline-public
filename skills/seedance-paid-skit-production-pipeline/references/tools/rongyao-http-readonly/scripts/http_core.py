"""Feishu QR -> existing Rongyao application -> read one video-list page."""
import json,re,time,subprocess,urllib.parse,datetime,hashlib
from pathlib import Path
from html.parser import HTMLParser
from http_transport import Session,VERSION
APP='cli_a19268d41e78d00d'
PORTAL='http://power.houtai.backend.example.invalid/'
LIST='http://adopenplatform.backend.example.invalid/app/data/?_c=jrttList&_a=index&ac=jrttVideoList'
CALLBACK=PORTAL+'api/ApiFeiShuRedirect.php'
OAUTH='https://open.feishu.cn/open-apis/authen/v1/index?'+urllib.parse.urlencode({'app_id':APP,'state':'{"type":"login"}','redirect_uri':CALLBACK})
class Page(HTMLParser):
 def __init__(self):super().__init__();self.links=[];self.inputs=[];self.text=[];self.refresh=None;self.stack=[];self.rows=[]
 def handle_starttag(self,t,a):
  d=dict(a)
  if t=='a' and d.get('href'):self.links.append(d['href'])
  if t=='meta' and d.get('http-equiv','').lower()=='refresh':
   m=re.search(r'url\s*=\s*(.+)',d.get('content',''),re.I)
   if m:self.refresh=m[1].strip(' \"\x27')
  if t in ('input','img','br','hr','meta','link','source','area','wbr','embed'):
   if t=='input':
    self.inputs.append(d)
    for _,c in self.stack:
     if c is not None:c.append(d)
   return
  c=[] if (t=='div' and 'col-sm-2' in d.get('class','').split()) or t=='tr' else None
  self.stack.append((t,c))
 def handle_data(self,d):self.text.append(d)
 def handle_endtag(self,t):
  pos=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==t),None)
  if pos is None:return
  for _,c in self.stack[pos:]:
   if c is None:continue
   ids=[x for x in c if x.get('name')=='id[]'];names=[x for x in c if x.get('type')=='text']
   if len(ids)==len(names)==1:self.rows.append({'record_id':ids[0].get('value'),'name':names[0].get('value')})
  del self.stack[pos:]
def parse(b):p=Page();p.feed(b);return p
def emit(r):print(json.dumps(r,ensure_ascii=False),flush=True)
def list_result(body,http_status=200,host='adopenplatform.backend.example.invalid'):
 p=parse(body);text=' '.join(p.text);m=re.search(r'视频数量为\s*[:：]\s*([\d,]+)',text)
 total=int(m[1].replace(',','')) if m else None
 ids=[x.get('value') for x in p.inputs if x.get('name')=='id[]'];rows=p.rows
 valid=http_status==200 and host=='adopenplatform.backend.example.invalid' and total is not None and len(rows)==len(ids) and len(set(x['record_id'] for x in rows))==len(rows) and all(x['record_id'] and x['record_id'].isdigit() and x['name'] for x in rows) and ((total==0 and not rows) or 0<len(rows)<=total)
 if any(x.get('type')=='password' for x in p.inputs):raise ValueError('LOGIN_EXPIRED')
 if not valid:raise ValueError('LIST_STRUCTURE_CHANGED')
 return {'ok':True,'observed_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'version':VERSION,'transport':'direct_http_server_rendered_html','browser_started':False,'browser_connected':False,'cookies_persisted':False,'source':LIST,'coverage':'first_page_only','total':total,'row_count':len(rows),'rows':rows,'upload_performed':False}
class Engine:
 def __init__(self,transport=None,authenticated=False):
  self.http=transport or Session();self.state={'status':'ready' if authenticated else 'new','browser_started':False,'browser_connected':False,'cookies_persisted':False,'version':VERSION}
  self.headers={};self.flow={};self.confirmation_submitted=False;self.callback_uri=None;self.cross_followed=False;self.qr_created=None;self.last_result=None
 def status(self):
  result=dict(self.state)
  if self.qr_created:result['qr_age_seconds']=round(time.monotonic()-self.qr_created,1)
  return result
 def auth_request(self,path,payload):
  for c in self.http.jar:
   if c.name=='swp_csrf_token':self.headers['X-Csrf-Token']=c.value
  code,h,b=self.http.request('https://accounts.feishu.cn'+path,payload,self.headers)
  if h.get('X-Flow-Key'):self.headers['X-Flow-Key']=h.get('X-Flow-Key')
  try:r=json.loads(b)
  except ValueError:raise ValueError('AUTH_RESPONSE_NOT_JSON_HTTP_'+str(code))
  if code!=200 or r.get('code')!=0:raise ValueError('AUTH_REQUEST_FAILED_HTTP_'+str(code)+'_CODE_'+str(r.get('code')))
  return r.get('data',{})
 def start(self,output_dir):
  if self.state['status']=='ready':return self.status()
  _,_,body=self.http.request(PORTAL)
  m=re.search(r'var\s+appid\s*=\s*["\x27]([^"\x27]+)',body)
  if not m or m[1]!=APP:raise ValueError('RONGYAO_APP_CHANGED')
  self.http.request(OAUTH)
  self.headers={'Origin':'https://accounts.feishu.cn','Referer':self.http.last_url,'X-App-Id':'12','X-Api-Version':'1.0.31','X-Device-Info':'device_id=0;device_name=Codex%20HTTP%20client;device_os=macOS;device_model=Mac;lark_version=;channel=Release;package_name=feishu;tt_app_id=12;is_dpop_support=false;is_iframe=false','X-Terminal-Type':'2'}
  self.flow=self.auth_request('/accounts/qrlogin/init',{'redirect_uri':OAUTH});token=self.flow.get('step_info',{}).get('token')
  if not token:raise ValueError('QR_TOKEN_MISSING')
  self.qr_created=time.monotonic();directory=Path(output_dir).expanduser().resolve();directory.mkdir(parents=True,exist_ok=True)
  image=directory/('rongyao-feishu-'+str(time.time_ns())+'.png')
  payload=json.dumps({'qrlogin':{'token':token}},separators=(',',':'))
  p=subprocess.run(['lark-cli','auth','qrcode',payload,'--output',image.name,'--size','384'],capture_output=True,text=True,timeout=20,cwd=image.parent)
  if p.returncode:raise ValueError('LOCAL_QR_RENDER_FAILED')
  self.state.update(status='waiting_scan',qr_image=str(image),expected_validity_seconds=60)
  self.confirmation_submitted=False;self.cross_followed=False;self.callback_uri=None
  return self.status()
 def poll(self):
  if self.state['status'] not in ('waiting_scan','waiting_confirmation'):return self.status()
  self.flow=self.auth_request('/accounts/qrlogin/polling',{})
  step=self.flow.get('step_info',{});next_step=self.flow.get('next_step')
  if next_step=='enter_app':
   self.state['status']='finishing_login';self.complete();return self.status()
  if next_step!='qr_login_polling':raise ValueError('UNSUPPORTED_AUTH_STEP')
  status=step.get('status')
  self.state['status']={0:'waiting_scan',1:'waiting_scan',2:'waiting_confirmation',3:'cancelled',4:'auth_error',5:'expired'}.get(status,'auth_error')
  return self.status()
 def complete(self):
  step=self.flow.get('step_info',{})
  if not self.cross_followed:
   cross=step.get('cross_login_uri');local=step.get('local_login_uri');mode=step.get('mode')
   if mode=='redirect' and cross:self.http.request(cross)
   elif mode in ('proxy','dual_domain_sync'):
    if local:self.http.request(local)
    if cross:self.http.request(cross)
   else:raise ValueError('UNSUPPORTED_CROSS_DOMAIN_MODE')
   self.cross_followed=True
  code,h,b=self.http.request(OAUTH)
  if urllib.parse.urlsplit(self.http.last_url).hostname=='power.houtai.backend.example.invalid':return self.finish_portal()
  config=None
  for m in re.finditer(r'window\.serverInjectRes\s*=\s*',b):
   try:obj,_=json.JSONDecoder().raw_decode(b[m.end():])
   except ValueError:continue
   if isinstance(obj,dict):config=obj;break
  if not config:raise ValueError('AUTHORIZATION_PAGE_CHANGED')
  d=config.get('authZData',config.get('data',{}));app=d.get('app_info',{});user=d.get('current_user',{})
  if app.get('app_id')!=APP:raise ValueError('AUTHORIZATION_APP_CHANGED')
  scopes=user.get('all_scope_key_list',[])
  if set(scopes)-{'auth:user.id:read'} or user.get('requested_scope_list') or user.get('blocked_scope_list') or user.get('reject_scope_list'):raise ValueError('AUTHORIZATION_SCOPE_REVIEW_REQUIRED')
  if config.get('version')!='v1':raise ValueError('AUTHORIZATION_VERSION_CHANGED')
  if self.confirmation_submitted:raise ValueError('AUTH_CONFIRMATION_UNKNOWN_NO_REPLAY')
  csrf=next((x.value for x in self.http.jar if x.name=='open_csrf_token'),None)
  if not csrf or not config.get('X-Auth-Flow-Key'):raise ValueError('AUTHORIZATION_CONTEXT_MISSING')
  extra={'Origin':'https://accounts.feishu.cn','Referer':self.http.last_url,'open-csrf-token':csrf,'X-Auth-Flow-Key':config['X-Auth-Flow-Key']}
  self.confirmation_submitted=True
  code,h,b=self.http.request('https://accounts.feishu.cn/open-apis/authen/v1/confirm',{'app_id':APP,'user_id':user['user_id'],'scope':' '.join(scopes)},extra)
  try:r=json.loads(b)
  except ValueError:raise ValueError('AUTH_CONFIRMATION_UNKNOWN_NO_REPLAY')
  if code!=200 or r.get('code')!=0:raise ValueError('AUTH_CONFIRMATION_FAILED_CODE_'+str(r.get('code')))
  self.callback_uri=r.get('data',{}).get('redirect_uri')
  if not self.callback_uri:raise ValueError('CALLBACK_NOT_RETURNED')
  self.http.request(self.callback_uri)
  if urllib.parse.urlsplit(self.http.last_url).hostname!='power.houtai.backend.example.invalid':raise ValueError('CALLBACK_NOT_AT_RONGYAO')
  self.finish_portal()
 def finish_portal(self):
  _,_,b=self.http.request(PORTAL);p=parse(b)
  if any(x.get('type')=='password' for x in p.inputs):raise ValueError('RONGYAO_LOGIN_UNVERIFIED')
  links=[urllib.parse.urljoin(self.http.last_url,x) for x in p.links]
  adlinks=[x for x in links if urllib.parse.urlsplit(x).hostname=='adopenplatform.backend.example.invalid']
  if not adlinks:raise ValueError('AD_PLATFORM_LINK_MISSING')
  self.http.request(adlinks[0]);self.state['status']='ready'
  self.state['feishu_qr_authenticated']=self.qr_created is not None;self.state['rongyao_portal_authenticated']=True
 def read_list(self):
  if self.state['status']!='ready':raise ValueError('HTTP_SESSION_NOT_READY')
  code,h,b=self.http.request(LIST)
  self.last_result=list_result(b,code,urllib.parse.urlsplit(self.http.last_url).hostname)
  from session_store import remember
  remember(self,getattr(self,'_session_scope','readonly'))
  self.last_result['cookies_persisted']=self.state.get('cookies_persisted',False)
  return self.last_result
