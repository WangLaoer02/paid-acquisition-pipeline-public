"""Native HTTP upload operations over the authenticated in-memory opener."""
import hashlib,json,math,re,time,urllib.error,urllib.parse,urllib.request
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from upload_page import Page,Stop,multipart
BASE='http://adopenplatform.backend.example.invalid'
ENTRY=BASE+'/app/data/?_c=jrttList&_a=index&ac=toImgInfo&do=video'
LIST=BASE+'/app/data/?_c=jrttList&_a=index&ac=jrttVideoList'
PRECHECK=BASE+'/app/data/?_c=jrttList&_a=index&ac=getVideoNames'
DIRECTIONS=BASE+'/app/data/?_c=videoSourceCategory&_a=index&ac=getCategoryInfo'
ROLES=BASE+'/app/data/?_c=jrttList&_a=index&ac=getRoleList'
DETAIL='http://demand.backend.example.invalid/data/?_c=creativeVideoList&_a=index&ac=openVideo'
CDN='http://cdnapk.backend.example.invalid/api/controller/ApiUploadVideo.php'
PORTAL='http://power.houtai.backend.example.invalid/'
SAVE_DESIGNER='http://demand.backend.example.invalid/data/?_c=creativeVideoList&_a=index&ac=saveDesignName'
SAVE_DEMAND=DETAIL.replace('ac=openVideo','ac=saveDemandName')
SAVE_SECOND=DETAIL.replace('ac=openVideo','ac=saveSecondDesignName')
SAVE_TAG=DETAIL.replace('ac=openVideo','ac=saveVideoTag')
METADATA_ENDPOINTS=(SAVE_DESIGNER,SAVE_DEMAND,SAVE_SECOND,SAVE_TAG)
CHUNK=20971520

class PortalRedirect(Stop):pass

class ReadBackoff(Stop):
    def __init__(self,status_code,retry_after_seconds=None):
        super().__init__('HTTP_READ_BACKOFF')
        self.status_code=status_code
        self.retry_after_seconds=retry_after_seconds

def retry_after_seconds(value):
    """Keep only a safe numeric delay; never expose response headers or URLs."""
    if not isinstance(value,str) or not value.strip():return None
    try:
        value=value.strip()
        if re.fullmatch('[0-9]+',value):seconds=int(value)
        else:
            when=parsedate_to_datetime(value)
            if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
            seconds=max(0,when.timestamp()-time.time())
        return seconds if math.isfinite(seconds) else None
    except (ValueError,TypeError,OverflowError):return None

def acknowledged(v):return v is True or type(v) is int and v==1 or v=='1'
def validate_url(url,post=False):
    u=urllib.parse.urlsplit(url)
    if u.scheme!='http' or u.port not in (None,80) or u.username or u.password or u.fragment:raise Stop('ORIGIN_REJECTED')
    if post:
        if url not in (PRECHECK,DIRECTIONS,ROLES,CDN+'?act=upload',CDN+'?act=join',*METADATA_ENDPOINTS):raise Stop('POST_ENDPOINT_REJECTED')
    elif not (url==PORTAL or url==ENTRY or url.startswith(LIST+'&') or url==LIST or url.startswith(DETAIL+'&')):raise Stop('GET_ENDPOINT_REJECTED')

class Api:
    def __init__(self,engine):
        self.engine=engine;self.client=engine.http.client;self.private=[]
    def request(self,url,fields=None,content=None,_rebind=True,_timeout=45,_probe=False):
        validate_url(url,fields is not None or content is not None)
        if _probe:_rebind=False;_timeout=min(_timeout,10)
        headers={'User-Agent':'Mozilla/5.0','Referer':getattr(self,'_detail_url',DETAIL) if url in METADATA_ENDPOINTS else ENTRY}
        body=None
        if content is not None:body,ct=multipart(fields,content);headers['Content-Type']=ct
        elif fields is not None:body=urllib.parse.urlencode(fields).encode();headers['Content-Type']='application/x-www-form-urlencoded'
        if body is not None:headers.update(Origin='http://demand.backend.example.invalid' if url in METADATA_ENDPOINTS else BASE,**{'X-Requested-With':'XMLHttpRequest'})
        # No write is redirected or retried. The cookie jar stays in this process.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,response_headers,target):
                parsed=urllib.parse.urlsplit(target)
                if (body is None and urllib.parse.urlsplit(url).hostname=='adopenplatform.backend.example.invalid'
                    and parsed.scheme=='http' and parsed.hostname=='power.houtai.backend.example.invalid'
                    and parsed.port in (None,80) and parsed.path=='/' and not parsed.username
                    and not parsed.password and not parsed.fragment):
                    raise PortalRedirect('AD_PORTAL_REBIND_REQUIRED')
                raise Stop('HTTP_REDIRECT_STOPPED')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPCookieProcessor(self.engine.http.jar))
        try:
            with opener.open(urllib.request.Request(url,data=body,headers=headers),timeout=_timeout) as r:
                raw=r.read(4_000_000).decode(r.headers.get_content_charset() or 'utf-8','replace')
                if r.status!=200:raise Stop('HTTP_STATUS_CHANGED')
        except PortalRedirect:
            if not _rebind:
                if not _probe:self.mark_login_required()
                raise Stop('LOGIN_EXPIRED') from None
            self.bind_ad()
            return self.request(url,_rebind=False)
        except urllib.error.HTTPError as error:
            if body is None and error.code in (429,503):
                raise ReadBackoff(error.code,retry_after_seconds(error.headers.get('Retry-After') if error.headers else None)) from None
            raise Stop('ACCEPTANCE_UNKNOWN' if body is not None else 'HTTP_READ_FAILED') from None
        except (OSError,TimeoutError):raise Stop('ACCEPTANCE_UNKNOWN' if body is not None else 'HTTP_READ_FAILED') from None
        if '<input' in raw and re.search(r'type=[\"\']password',raw,re.I):
            if not _probe:self.mark_login_required()
            raise Stop('LOGIN_EXPIRED')
        return raw
    def mark_login_required(self):
        self.engine.state.update(status='login_required',authenticated=False)
    def bind_ad(self):
        # Reuse this process's original portal session. No password/code login.
        _,_,body=self.engine.http.request(PORTAL)
        page=Page(body)
        if any(x.get('type')=='password' for x in page.inputs):
            self.mark_login_required()
            raise Stop('LOGIN_EXPIRED')
        links=[]
        for href in page.links:
            target=urllib.parse.urljoin(PORTAL,href);u=urllib.parse.urlsplit(target)
            if (u.hostname=='adopenplatform.backend.example.invalid' and u.scheme=='http'
                and u.port in (None,80) and not u.username and not u.password and not u.fragment):
                links.append(target)
        links=list(dict.fromkeys(links))
        if len(links)!=1:raise Stop('AD_PORTAL_ENTRY_UNVERIFIED')
        _,_,body=self.engine.http.request(links[0])
        if any(x.get('type')=='password' for x in Page(body).inputs):
            self.mark_login_required()
            raise Stop('LOGIN_EXPIRED')
    def json(self,url,fields=None,content=None):
        try:r=json.loads(self.request(url,fields,content))
        except json.JSONDecodeError:raise Stop('INVALID_JSON_RESPONSE') from None
        if isinstance(r,str):r=json.loads(r)
        if not isinstance(r,dict):raise Stop('JSON_STRUCTURE_CHANGED')
        return r
    def form(self,*,probe=False):
        page=Page(self.request(ENTRY,_rebind=False,_timeout=10,_probe=True) if probe else self.request(ENTRY));code='\n'.join(page.inline)
        for marker in ('20971520','act=upload','act=join','tag:roleTag','tmp_flag:1','ac=getVideoNames'):
            if marker not in code:raise Stop('NATIVE_UPLOAD_PROTOCOL_CHANGED')
        hidden={k:page.field(k) for k in ('advertiser_id','token','create_name')}
        if not all(hidden.values()):raise Stop('UPLOAD_IDENTITY_UNVERIFIED')
        if not probe:
            self.private=list(hidden.values())
            self.engine.state.update(status='ready',authenticated=True,last_protected_read_at=time.time())
        return page,hidden
    def fields(self,gid=None,source_type=None,*,probe=False):
        page,hidden=self.form(probe=True) if probe else self.form()
        public={'ok':True,'authenticated':True,'display_name':hidden['create_name'],'selects':page.selects,'origin_type':[{'value':x.get('value'),'checked':'checked' in x} for x in page.inputs if x.get('name')=='origin_type'],'browser_started':False}
        if probe:
            return {**public,'probe_scope':'form_only','dynamic_enums_verified':False,'requested_gid':gid,'requested_source_type':source_type}
        public.update(self._current_enums(gid,source_type))
        return public
    def _current_enums(self,gid=None,source_type=None):
        # Read each requested enum now; reuse only the caller's already-read form.
        public={}
        if gid:
            r=self.json(ROLES,[('gid',gid)])
            if not acknowledged(r.get('status')):raise Stop('ROLE_ENUM_REJECTED')
            public['roles']=r.get('info')
        if source_type:
            r=self.json(DIRECTIONS,[('pid[]',source_type)])
            if not acknowledged(r.get('status')):raise Stop('DIRECTION_ENUM_REJECTED')
            public['directions']=r.get('info')
        return public
    def lookup(self,name,parameters=None):
        # Never filter by intended attribution: an incorrectly attributed record
        # must still hold its name, and duplicates in other categories count too.
        query={'name':name.removesuffix('.mp4')}
        page=Page(self.request(LIST+'&'+urllib.parse.urlencode(query)))
        records=self.list_records(page)
        matches=[r for r in records if r['name']==name.removesuffix('.mp4')]
        if len(matches)>1:raise Stop('AMBIGUOUS_NAME')
        return matches[0] if matches else None
    def list_records(self,page):
        totals=re.findall(r'视频数量为\s*[:：]\s*([\d,]+)',page.root.text())
        if len(totals)!=1:raise Stop('LIST_TOTAL_UNVERIFIED')
        records=[]
        for box in page.root.all('input'):
            if box.attrs.get('name')!='id[]':continue
            titles=[x.attrs.get('value') for x in box.parent.all('input') if x.attrs.get('type')=='text' and x.attrs.get('onchange','').startswith('saveName')]
            if len(titles)!=1:raise Stop('LIST_CARD_STRUCTURE_CHANGED')
            ident=box.attrs.get('value','')
            if not re.fullmatch('[1-9][0-9]*',ident):raise Stop('LIST_ID_INVALID')
            records.append({'id':ident,'name':titles[0]})
        if len({r['id'] for r in records})!=len(records):raise Stop('LIST_DUPLICATE_ID')
        total=int(totals[0].replace(',',''))
        if total>len(records):raise Stop('LIST_REQUIRES_PAGINATION')
        if total!=len(records):raise Stop('LIST_TOTAL_MISMATCH')
        return records
    def prefix(self,prefix):
        if not re.fullmatch(r'\d{6}[A-Z]+',prefix):raise Stop('INVALID_PREFIX')
        page=Page(self.request(LIST+'&'+urllib.parse.urlencode({'name':prefix})))
        titles=[r['name'] for r in self.list_records(page)]
        nums=[int(m[1]) for x in titles if (m:=re.match(re.escape(prefix)+r'([1-9]\d*)-',x))]
        return {'ok':True,'prefix':prefix,'next_number':max(nums,default=0)+1,'matched_count':len(nums),'reservation':False,'native_precheck_required':True}
    def validate_fields(self,p,explicit_original_requester=False):
        page,hidden=self.form()
        for key in ('category_type','ai_source','demand_name','gid','region_type','is_redbag'):
            values={x.get('value','') for x in page.selects.get(key,{}).get('options',[])}
            if p[key] not in values:
                if key=='demand_name' and p[key]=='原创' and explicit_original_requester:continue
                raise Stop('FORM_OPTION_MISSING_'+key.upper())
        if p['origin_type'] not in {x.get('value') for x in page.inputs if x.get('name')=='origin_type'}:raise Stop('ORIGIN_OPTION_MISSING')
        for key in ('source_type','source_ip'):
            options={x.get('value','') for x in page.selects.get(key,{}).get('options',[])}
            if set(p[key])-options:raise Stop('FORM_OPTION_MISSING_'+key.upper())
        if len(p['source_type'])!=1 or len(p['source_direction'])!=1:raise Stop('SINGLE_CLASS_REQUIRED')
        enums=self._current_enums(p['gid'],p['source_type'][0])
        dirs=enums['directions'];dirs=list(dirs.values()) if isinstance(dirs,dict) else dirs
        if set(p['source_direction'])-set(dirs):raise Stop('DIRECTION_OPTION_MISSING')
        roles=enums['roles'];roles=list(roles.values()) if isinstance(roles,dict) else roles
        role_names={x.get('name') for x in roles if isinstance(x,dict)}
        if set(p['role'])-role_names:raise Stop('ROLE_OPTION_MISSING')
        return hidden
    def bind_demand(self):
        # Follow only the actual same-account portal link. No credentials or
        # SSO URLs leave this process; upload authentication is independent.
        try:
            # Preserve the authenticated portal transport and its native identity.
            _,_,body=self.engine.http.request(PORTAL);page=Page(body)
        except (Stop,OSError,ValueError):raise Stop('DEMAND_PORTAL_READ_FAILED') from None
        if any(x.get('type')=='password' for x in page.inputs):raise Stop('DEMAND_PORTAL_LOGIN_REQUIRED')
        links=[urllib.parse.urljoin(PORTAL,x) for x in page.links]
        links=[x for x in links if urllib.parse.urlsplit(x).hostname=='demand.backend.example.invalid']
        if len(links)!=1:raise Stop('DEMAND_PORTAL_ENTRY_UNVERIFIED')
        class NativeEntryRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,headers,url):
                u=urllib.parse.urlsplit(url)
                if u.scheme not in ('http','https') or u.hostname not in ('power.houtai.backend.example.invalid','adopenplatform.backend.example.invalid','demand.backend.example.invalid') or u.port not in (None,80 if u.scheme=='http' else 443) or u.username or u.password:
                    raise Stop('DEMAND_ENTRY_REDIRECT_REJECTED_'+re.sub('[^A-Z0-9]','_',((u.scheme or '')+'_'+(u.hostname or '')).upper()))
                return super().redirect_request(req,fp,code,msg,headers,url)
        u=urllib.parse.urlsplit(links[0])
        if u.scheme!='http' or u.port not in (None,80) or u.username or u.password:raise Stop('DEMAND_PORTAL_ENTRY_UNVERIFIED')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NativeEntryRedirect(),urllib.request.HTTPCookieProcessor(self.engine.http.jar))
        with opener.open(urllib.request.Request(links[0],headers={'Referer':PORTAL,'User-Agent':'Mozilla/5.0'}),timeout=30) as response:
            body=response.read(4_000_000).decode('utf-8','replace')
            if response.status!=200 or urllib.parse.urlsplit(response.url).hostname!='demand.backend.example.invalid' or any(x.get('type')=='password' for x in Page(body).inputs):raise Stop('DEMAND_LOGIN_REQUIRED')
    def detail_page(self,record):
        if not re.fullmatch('[1-9][0-9]*',str(record.get('id',''))) or not isinstance(record.get('name'),str) or not record['name']:raise Stop('DETAIL_RECORD_REQUIRED')
        url=DETAIL+'&'+urllib.parse.urlencode({'video_name':record['name'],'type':'date'})
        self._detail_url=url
        try:body=self.request(url)
        except Stop as exc:
            if str(exc) not in ('HTTP_REDIRECT_STOPPED','LOGIN_EXPIRED'):raise
            self.bind_demand();body=self.request(url)
        page=Page(body)
        names=[x.text() for x in page.root.all() if 'video_title' in x.attrs.get('class','').split()]
        ids={x.attrs.get('id') for x in page.root.all('img') if re.fullmatch('[1-9][0-9]*',x.attrs.get('id',''))}
        if names!=[record['name']] or ids!={record['id']}:raise Stop('DETAIL_IDENTITY_MISMATCH')
        return page
    def detail_snapshot(self,record):
        page=self.detail_page(record);fields={}
        for node in page.root.all('h6'):
            label,sep,value=node.text().partition('：')
            if sep:fields[label.strip()]=[x.attrs['name'] for x in node.all('img') if x.attrs.get('name')] or value.strip()
        media=[]
        for node in page.root.all():
            if 'video' in node.attrs.get('class','').split():
                media.extend(x.attrs['name'] for x in node.all('img') if x.attrs.get('name'))
        return {'record':record,'fields':fields,'media':sorted(set(media))}
    def detail(self,record):return self.detail_snapshot(record)['fields']
    def set_designer(self,record,name):
        if not isinstance(name,str) or not name.strip() or name!=name.strip():raise Stop('DESIGNER_REQUIRED')
        page=self.detail_page(record);code='\n'.join(page.inline)
        match=re.search(r'function\s+changeDesignName\s*\([^)]*\)(.*?)(?=function\s+changeSecondDesignName)',code,re.S)
        if not match or 'ac=saveDesignName' not in match[1] or 'design_name:username' not in match[1]:raise Stop('DESIGNER_NATIVE_CONTRACT_CHANGED')
        enum=re.search(r"var\s+arr\s*=\s*'([^']+)'",match[1])
        if not enum or name not in json.loads(enum[1]).values():raise Stop('DESIGNER_OPTION_MISSING')
        # Exactly the observed native metadata action. Never sends video bytes.
        value=self.json(SAVE_DESIGNER,[('id',record['id']),('design_name',name)])
        if not acknowledged(value.get('status')):raise Stop('DESIGNER_WRITE_REJECTED')
        return {'acknowledged':True}

    def set_metadata(self,record,label,value):
        """Only observed native actions; no bulk edit, media upload or retries."""
        contracts={'需求人':('changeDemandName',SAVE_DEMAND,'demand_name'),
                   '第二设计师':('changeSecondDesignName',SAVE_SECOND,'region_type'),
                   '角色/标签':('addTag',SAVE_TAG,'tag')}
        if label not in contracts:raise Stop('METADATA_FIELD_REJECTED')
        function,url,key=contracts[label]
        code='\n'.join(self.detail_page(record).inline)
        match=re.search(r'function\s+'+function+r'\s*\([^)]*\)(.*?)(?=\n\s*function |\Z)',code,re.S)
        if not match:raise Stop('METADATA_NATIVE_CONTRACT_CHANGED')
        body=match[1];endpoint=urllib.parse.urlsplit(url).query.split('ac=',1)[1]
        expected={'需求人':'{id:e.id,demand_name:username}',
                  '第二设计师':'{id:e.id,region_type:second_design_id}',
                  '角色/标签':'{id:e.id,tag:tag_arr}'}[label]
        if 'ac='+endpoint not in body or expected not in re.sub(r'\s+','',body):raise Stop('METADATA_NATIVE_CONTRACT_CHANGED')
        enum=re.search(r"var\s+arr\s*=\s*'([^']+)'",body)
        if not enum:raise Stop('METADATA_ENUM_MISSING')
        options=json.loads(enum[1]);fields=[('id',record['id'])]
        if label=='角色/标签':
            options=options.get('tag',{})
            if not isinstance(value,list) or not value or len(value)!=len(set(value)) or any(not isinstance(x,str) or x not in options.values() for x in value):raise Stop('METADATA_OPTION_MISSING')
            # jQuery serializes the observed tag array as repeated tag[] keys.
            fields.extend(('tag[]',x) for x in value)
        else:
            if not isinstance(value,str) or not value or value not in options.values():raise Stop('METADATA_OPTION_MISSING')
            encoded=value
            if label=='第二设计师':
                matches=[k for k,v in options.items() if v==value]
                if len(matches)!=1:raise Stop('METADATA_ENUM_AMBIGUOUS')
                encoded=matches[0]
            fields.append((key,encoded))
        response=self.json(url,fields)
        if not acknowledged(response.get('status')):raise Stop('METADATA_WRITE_REJECTED')
        return {'acknowledged':True}
