"""System curl TLS trust; cookies stay in the calling process's CookieJar."""
VERSION='1.3.1'
HOSTS={'open.feishu.cn','accounts.feishu.cn','login.feishu.cn','passport.feishu.cn','www.feishu.cn','power.houtai.backend.example.invalid','adopenplatform.backend.example.invalid'}
POST_PATHS={'/accounts/qrlogin/init','/accounts/qrlogin/polling','/open-apis/authen/v1/confirm'}
def validate_url(url,post=False):
 u=urllib.parse.urlsplit(url)
 if u.scheme not in ('http','https') or u.hostname not in HOSTS or u.port or u.username or u.password:raise ValueError('UNEXPECTED_AUTH_HOST')
 if post and (u.hostname!='accounts.feishu.cn' or u.path not in POST_PATHS):raise ValueError('POST_OUTSIDE_AUTH_FLOW')
 if u.hostname=='adopenplatform.backend.example.invalid':
  q=urllib.parse.parse_qs(u.query)
  if u.path not in ('/','/app/data/'):raise ValueError('NON_READONLY_AD_PATH')
  if u.path=='/app/data/' and not(q.get('_c')==['jrttList'] and q.get('_a')==['index'] and q.get('ac')==['jrttVideoList']):raise ValueError('NON_READONLY_AD_QUERY')
import subprocess,json,urllib.request,urllib.parse,http.cookiejar,email.parser

class PasswordSessionTransport:
 """Original password/SMS portal transport, also used for saved-session restore."""
 HOSTS={'power.houtai.backend.example.invalid','adopenplatform.backend.example.invalid'}
 def __init__(self):
  allowed=self.HOSTS
  class Redirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,req,fp,code,msg,headers,url):
    u=urllib.parse.urlsplit(url)
    if u.hostname not in allowed or u.scheme!='http' or u.port not in (None,80) or u.username or u.password:
     raise ValueError('UNEXPECTED_LOGIN_REDIRECT')
    return super().redirect_request(req,fp,code,msg,headers,url)
  self.jar=http.cookiejar.CookieJar()
  self.client=urllib.request.build_opener(urllib.request.ProxyHandler({}),Redirect(),urllib.request.HTTPCookieProcessor(self.jar))
  self.last_url=None
 def request(self,url,payload=None,extra=None,depth=0):
  u=urllib.parse.urlsplit(url)
  if u.hostname not in self.HOSTS or u.scheme!='http' or u.port not in (None,80) or u.username or u.password:
   raise ValueError('UNEXPECTED_BACKEND_HOST')
  if payload is not None and (u.hostname!='power.houtai.backend.example.invalid' or u.path!='/' or u.query not in ('_c=login&_a=sendMessage','_c=login&_a=login')):
   raise ValueError('LOGIN_POST_NOT_ALLOWED')
  data=urllib.parse.urlencode(payload).encode() if payload is not None else None
  headers={'User-Agent':'Mozilla/5.0','Referer':'http://power.houtai.backend.example.invalid/',**(extra or {})}
  if data is not None:headers.update({'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'})
  with self.client.open(urllib.request.Request(url,data=data,headers=headers),timeout=25) as response:
   self.last_url=response.url
   return response.status,response.headers,response.read(4000000).decode('utf-8','replace')

class Session:
 def __init__(self):self.jar=http.cookiejar.CookieJar();self.last_url=None
 def request(self,url,payload=None,extra=None,depth=0):
  if depth>8:raise RuntimeError('TOO_MANY_REDIRECTS')
  u=urllib.parse.urlsplit(url)
  validate_url(url, payload is not None)
  req=urllib.request.Request(url);self.jar.add_cookie_header(req)
  headers={'User-Agent':'Mozilla/5.0',**dict(req.header_items()),**(extra or {})}
  def quote(v):return '"'+str(v).replace('\\','\\\\').replace('"','\\"').replace('\r','\\r').replace('\n','\\n')+'"'
  cfg=['silent','show-error','max-time = 25','dump-header = "/dev/stderr"','url = '+quote(url)]
  for k,v in headers.items():cfg.append('header = '+quote(k+': '+v))
  if payload is not None:cfg.extend(['header = "Content-Type: application/json"','data = '+quote(json.dumps(payload))])
  r=subprocess.run(['/usr/bin/curl','--config','-'],input='\n'.join(cfg)+'\n',text=True,capture_output=True,timeout=30)
  if r.returncode:raise RuntimeError('CURL_TRANSPORT_ERROR_'+str(r.returncode))
  blocks=[x for x in r.stderr.replace('\r\n','\n').split('\n\n') if x.startswith('HTTP/')]
  block=blocks[-1];code=int(block.splitlines()[0].split()[1]);h=email.parser.Parser().parsestr('\n'.join(block.splitlines()[1:]))
  class Resp:
   def info(self):return h
  self.jar.extract_cookies(Resp(),req);self.last_url=url
  if code in (301,302,303,307,308) and h.get('Location'):
   return self.request(urllib.parse.urljoin(url,h['Location']),payload if code in (307,308) else None,depth=depth+1)
  return code,h,r.stdout
