"""Native portal SSO and bounded read-only new-material queries in one service.

No cookie/credential output or storage. POST is limited to the native report
query endpoint; one submitted query is never automatically repeated.
"""
import csv, datetime, hashlib, importlib.util, io, json, re, sys, time
import urllib.parse as U
import urllib.request as R
from html.parser import HTMLParser
from pathlib import Path

HOST='data.houtai.cn.sy.backend.example.invalid'
ORIGIN='http://'+HOST
PORTAL='http://power.houtai.backend.example.invalid/'
MARKET='/marketng/?_c=adopenplatformSource&_a=index'
STACK=Path.home()/'.codex/skills/rongyao-data-stack/scripts'

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.current=None
    def handle_starttag(self,t,a):
        if t=='a':self.current={'href':dict(a).get('href',''),'text':''};self.links.append(self.current)
    def handle_endtag(self,t):
        if t=='a':self.current=None
    def handle_data(self,d):
        if self.current is not None:self.current['text']+=d

def validate_url(url, method='GET', query_url=None):
    global LAST_BOUNDARY
    u=U.urlsplit(url);q=U.parse_qs(u.query)
    LAST_BOUNDARY={'host':u.hostname,'path':u.path,'method':method}
    if u.scheme!='http' or u.username or u.password or u.port:raise ValueError('INVALID_MARKET_ORIGIN')
    if u.hostname=='power.houtai.backend.example.invalid':
        if method!='GET' or u.path!='/':raise ValueError('PORTAL_READ_ONLY')
        if q.get('_c')==['login']:raise ValueError('MARKET_LOGIN_REQUIRED')
        return
    if u.hostname!=HOST:raise ValueError('UNEXPECTED_MARKET_HOST')
    if method=='POST':
        if not query_url or url!=query_url:raise ValueError('MARKET_POST_NOT_QUERY')
    elif u.path not in ('/','/market','/market/','/marketng/','/market/api/ApiGetCategory.php','/market/api/ApiGetAllPkList.php','/marketng/api/ApiGetPcidList.php'):
        raise ValueError('MARKET_GET_NOT_READONLY')
    if u.path=='/marketng/' and (q.get('_c')!=['adopenplatformSource'] or q.get('_a')!=['index'] or q.get('ac',[''])[0] not in ('','getData','export')):raise ValueError('MARKET_ACTION_NOT_READONLY')

class Redirect(R.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,h,url):
        validate_url(url)
        return super().redirect_request(req,fp,code,msg,h,url)

def client(engine):
    # Share the existing in-process CookieJar with the native report service.
    # Never return cookie headers through RPC or copy them to another process.
    if not hasattr(engine,'market_client'):
        engine.market_client=R.build_opener(Redirect(),R.HTTPCookieProcessor(engine.http.jar))
    return engine.market_client

def request(engine,url,data=None,query_url=None):
    validate_url(url,'POST' if data is not None else 'GET',query_url)
    body=U.urlencode(data).encode() if data is not None else None
    headers={'User-Agent':'Mozilla/5.0','Referer':ORIGIN+MARKET}
    if body is not None:headers.update({'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'})
    with client(engine).open(R.Request(url,data=body,headers=headers),timeout=180) as res:
        raw=res.read(32*1024*1024+1)
        if len(raw)>32*1024*1024:raise ValueError('MARKET_RESPONSE_TOO_LARGE')
        validate_url(res.url)
        return raw,dict(res.headers)

def module():
    spec=importlib.util.spec_from_file_location('http_market_backend_helper',STACK/'backend_export_cli.py')
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m

def parse_market_config(raw):
    helper=module()
    try:page=helper.parse_backend_page_config(raw.decode('utf-8'))
    except (SystemExit,UnicodeError):raise ValueError('MARKET_LOGIN_OR_PAGE_CONFIG_REQUIRED') from None
    query_url=U.urljoin(ORIGIN,page['getDataUrl'])
    u=U.urlsplit(query_url);q=U.parse_qs(u.query)
    if u.scheme!='http' or u.username or u.password or u.port or u.hostname!=HOST or u.path!='/marketng/' or q.get('_c')!=['adopenplatformSource'] or q.get('_a')!=['index'] or q.get('ac')!=['getData']:
        raise ValueError('UNEXPECTED_NATIVE_QUERY_ENDPOINT')
    return helper,page,query_url

def prepare(engine):
    # A saved market session can remain valid even when the portal no longer
    # renders its SSO links. Verify the protected page before requesting SSO.
    try:
        raw,_=request(engine,ORIGIN+MARKET)
        return parse_market_config(raw)
    except ValueError as exc:
        if str(exc) not in ('MARKET_LOGIN_REQUIRED','MARKET_LOGIN_OR_PAGE_CONFIG_REQUIRED'):
            raise
    # Follow only the genuine portal link; opaque SSO tickets stay in process.
    code,_,html=engine.http.request(PORTAL)
    p=Links();p.feed(html)
    engine.market_prepare_diagnostics={'portal_status':code,'portal_host':U.urlsplit(engine.http.last_url).hostname,'anchor_count':len(p.links),'market_host_mentions':html.count(HOST),'password_input':bool(re.search(r'<input[^>]+type=[\"\']password',html,re.I)),'login_controller':U.parse_qs(U.urlsplit(engine.http.last_url).query).get('_c')==['login'],'link_hosts':sorted({U.urlsplit(U.urljoin(PORTAL,x['href'])).hostname or '' for x in p.links})}
    candidates=[x for x in p.links if U.urlsplit(U.urljoin(PORTAL,x['href'])).hostname==HOST]
    if not candidates:
        if engine.market_prepare_diagnostics['password_input'] and engine.market_prepare_diagnostics['login_controller']:
            raise ValueError('MARKET_PORTAL_LOGIN_REQUIRED')
        raise ValueError('NATIVE_MARKET_LINK_NOT_FOUND')
    selected=next((x for x in candidates if '手游' in x['text']),candidates[0])
    request(engine,U.urljoin(PORTAL,selected['href']))
    raw,_=request(engine,ORIGIN+MARKET)
    return parse_market_config(raw)

def dispatch(engine,params):
    if params.get('action') not in ('probe','export'):raise ValueError('INVALID_MARKET_ACTION')
    if params['action']=='export':
        for key in ('date_range','material_range'):
            value=params.get(key,'')
            if not re.fullmatch(r'\d{4}/\d{2}/\d{2}-\d{4}/\d{2}/\d{2}',value):raise ValueError('INVALID_MARKET_DATE_RANGE')
            left,right=value.split('-');start=datetime.datetime.strptime(left,'%Y/%m/%d');end=datetime.datetime.strptime(right,'%Y/%m/%d')
            if start>end:raise ValueError('REVERSED_MARKET_DATE_RANGE')
        out=Path(params['output']).expanduser().resolve()
        if out.exists():raise ValueError('MARKET_OUTPUT_ALREADY_EXISTS')
        if str(params.get('gid'))!='193':raise ValueError('UNSUPPORTED_MARKET_GID')
        if params.get('date_group','tenyear')!='tenyear' or params.get('group','mid')!='mid':raise ValueError('UNSUPPORTED_MARKET_GROUP')
    try:helper,page,query_url=prepare(engine)
    except ValueError as e:
        return {'ok':False,'error':str(e) if re.fullmatch('[A-Z0-9_]+',str(e)) else type(e).__name__,'boundary':globals().get('LAST_BOUNDARY'),'business_query_performed':False,'diagnostics':getattr(engine,'market_prepare_diagnostics',None)}
    if params['action']=='probe':return {'ok':True,'market_authenticated':True,'business_query_performed':False,'browser_started':False,'cookies_persisted':False,'native_query_endpoint_verified':True}
    search=helper.backend_default_search(page['config'],page['initRand'])
    gids=['193']
    for field,path in [('category','/market/api/ApiGetCategory.php?gid=193'),('pkid','/market/api/ApiGetAllPkList.php?gid=193')]:
        raw,_=request(engine,ORIGIN+path);result=json.loads(raw)
        info=result.get('info',result);info=info.get('category_list',info.get('pkid_list',info)) if isinstance(info,dict) else {}
        search[field]=[str(k) for k in info if str(k).isdigit()]
    if search.get('operation_client'):
        values=search['operation_client'];value=','.join(map(str,values)) if isinstance(values,list) else str(values)
        raw,_=request(engine,ORIGIN+'/marketng/api/ApiGetPcidList.php?operation_client='+U.quote(value));r=json.loads(raw);info=r.get('info',r);info=info.get('pcid_list',info) if isinstance(info,dict) else {};search['pcid']=[str(k) for k in info if str(k).isdigit()]
    search.update(date=params['date_range'],date2=params['material_range'],gid=gids,date_group='tenyear',group='mid',source_video_type='1',record_type='3',filter='1',page=1)
    payload={f'search[{k}]':','.join(map(str,v)) if isinstance(v,list) else v for k,v in search.items()};payload.update({'search[page_component_version]':1,'search[submit]':1})
    # Checkpoint before the only heavy POST; an unknown result blocks replay.
    signature=hashlib.sha256(json.dumps({k:params.get(k) for k in ('date_range','material_range','gid','date_group','group')},sort_keys=True).encode()).hexdigest()
    attempts=getattr(engine,'market_attempts',{});engine.market_attempts=attempts
    if signature in attempts:raise ValueError('MARKET_QUERY_ALREADY_SUBMITTED')
    journal=Path.home()/'.codex/state/rongyao-http/market-requests'/str(datetime.date.today())/(signature+'.json')
    if journal.exists():raise ValueError('MARKET_REQUEST_REQUIRES_READBACK')
    journal.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    def checkpoint(state):
        with journal.open('w') as f:
            import os
            os.chmod(journal,0o600);json.dump({'state':state,'submitted_at':time.time(),'signature':signature,'output':str(out)},f)
    checkpoint('submitted')
    attempts[signature]={'state':'submitted','time':time.time()}
    raw,_=request(engine,query_url,payload,query_url)
    response=json.loads(raw)
    if not response.get('status'):attempts[signature]['state']='rejected';raise ValueError('MARKET_QUERY_REJECTED')
    info=response.get('info') or {};rand=info.get('rand')
    if not rand:raise ValueError('MARKET_QUERY_MISSING_RESULT_ID')
    attempts[signature].update(state='query_complete',rand=rand)
    raw,headers=request(engine,ORIGIN+MARKET+'&ac=export&rand='+U.quote(str(rand)))
    if b'<html' in raw[:300].lower():raise ValueError('MARKET_EXPORT_HTML')
    out=Path(params['output']).expanduser().resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():raise ValueError('MARKET_OUTPUT_ALREADY_EXISTS')
    out.write_bytes(raw);out.chmod(0o600);attempts[signature]['state']='exported';checkpoint('exported')
    return {'ok':True,'file':str(out),'bytes':len(raw),'contentType':headers.get('Content-Type',''),'transport':'existing_http_session_native_market_sso','browser_started':False,'cookies_persisted':False,'filters':{'entry':'新素材2.0','gid':'193','gidCount':1,'game':'忍界大战','dateRange':params['date_range'],'materialRange':params['material_range'],'dateGroup':'tenyear','group':'mid','sourceVideoType':'视频','recordType':'新注册','filter':'是'},'query':{k:info.get(k) for k in ('count','totalpage','pagesize')},'fileSummary':helper.backend_export_summary(out)}
