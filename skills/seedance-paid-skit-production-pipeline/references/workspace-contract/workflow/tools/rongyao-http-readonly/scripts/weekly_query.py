"""Bounded GET-only video-list query; never returns cookies or hidden auth fields."""
import re, urllib.parse
from http_core import LIST, list_result
from weekly_page_parser import Page

def query_list(engine, params):
    # Explicit RPC extension for older in-memory services. Cookies remain in
    # the existing service; the extension performs native portal SSO only.
    if isinstance(params, dict) and params.get('_operation') == 'market-readonly':
        import importlib, market_readonly
        result=importlib.reload(market_readonly).dispatch(engine, params)
        if result.get("ok"):
            from session_store import remember
            remember(engine,"readonly")
            result["cookies_persisted"]=engine.state.get("cookies_persisted",False)
        return result
    if not isinstance(params,dict) or len(params)>30:raise ValueError('INVALID_LIST_PARAMS')
    # Discover valid filter names from the actual list form before accepting filters.
    if not hasattr(engine,'weekly_filter_names'):
        code,headers,body=engine.http.request(LIST)
        list_result(body,code,urllib.parse.urlsplit(engine.http.last_url).hostname)
        page=Page(body)
        engine.weekly_filter_names={x.get('name') for x in page.inputs if x.get('type') not in ('hidden','password') or x.get('name') in {'category_type','name','ad_id','date_ranges','date_ranges_picker','createtime_start','createtime_end'}}
        engine.weekly_filter_names.update(v['attrs'].get('name') for v in page.selects.values())
        engine.weekly_filter_names.add('page')
        # Native list buttons and JS construct these GET fields instead of named inputs.
        for key in ('category_type','date_ranges','date_ranges_picker','name','ad_id','createtime_start','createtime_end'):
            if re.search(r'\b'+re.escape(key)+r'\b',body):engine.weekly_filter_names.add(key)
    if set(params)-engine.weekly_filter_names:raise ValueError('UNOBSERVED_LIST_FILTER')
    if any(not isinstance(v,str) or len(v)>150 for v in params.values()):raise ValueError('INVALID_LIST_FILTER_VALUE')
    url=LIST+('&'+urllib.parse.urlencode(params) if params else '')
    code,headers,body=engine.http.request(url)
    result=list_result(body,code,urllib.parse.urlsplit(engine.http.last_url).hostname)
    page=Page(body)
    cards=[]
    def safe_text(n):
        if n.tag in ('script','style'):return ''
        return ' '.join(n.data+[safe_text(c) for c in n.children]).strip()
    for node in page.root.all('div'):
        if 'col-sm-2' not in node.attrs.get('class','').split():continue
        ids=[x.attrs.get('value') for x in node.all('input') if x.attrs.get('name')=='id[]']
        if len(ids)==1:
            parents=[];parent=node
            for _ in range(3):
                if parent is None:break
                parents.append({'tag':parent.tag,'class':parent.attrs.get('class'),'text':safe_text(parent)[:12000]})
                parent=parent.parent
            cards.append({'record_id':ids[0],'text':safe_text(node),'ancestors':parents,
                          'labels':[safe_text(n) for n in node.all() if n.tag in ('h6','h5','p','span')],
                          'data_attrs':[{k:v for k,v in n.attrs.items() if k.startswith('data-') and not any(w in k.lower() for w in ('token','auth','secret'))} for n in node.all() if any(k.startswith('data-') for k in n.attrs)]})
    result.update(query=params,cards=cards,
        filters=[{k:x.get(k) for k in ('name','id','type','value','placeholder')} for x in page.inputs if x.get('name') and x.get('name')!='id[]' and (x.get('type') not in ('hidden','password') or x.get('name') in engine.weekly_filter_names)],
        selects={k:{'name':v['attrs'].get('name'),'options':v['options']} for k,v in page.selects.items()},
        pagination=[{'text':n.text(),'page':urllib.parse.parse_qs(urllib.parse.urlsplit(n.attrs['href']).query).get('page',[])} for n in page.root.all('a') if 'page=' in n.attrs.get('href','')],
        date_labels=[n.text() for n in page.root.all('label')])
    result['observed_filter_names']=sorted(x for x in engine.weekly_filter_names if x)
    # Native category buttons: expose only their public label and numeric ID.
    result['category_options'] = [
        {'value': n.attrs['id'], 'text': n.attrs.get('value') or safe_text(n)}
        for n in page.root.all()
        if n.attrs.get('id', '').isdigit()
        and re.search(r'\bcategorySubmit\s*\(', n.attrs.get('onclick', ''))
    ]
    result['date_picker_code']=[s for s in page.inline if 'var $dateRange' in s and not re.search(r'password|secret|token',s,re.I)]
    snippets=[]
    for row in result['rows'][:2]:
        match=re.search(r'<input\b[^>]*\bvalue=["\x27]'+re.escape(row['record_id'])+r'["\x27][^>]*>',body)
        if match:
            snippet=body[max(0,match.start()-1200):match.end()+4500]
            snippet=re.sub(r'<script\b.*?</script>','',snippet,flags=re.S|re.I)
            snippet=re.sub(r'\b(?:src|href|on\w+)\s*=\s*(["\x27]).*?\1','',snippet,flags=re.S|re.I)
            snippet=re.sub(r'<input\b[^>]*(?:password|token|secret)[^>]*>','',snippet,flags=re.I)
            snippets.append({'record_id':row['record_id'],'markup':snippet})
    result['card_markup_samples']=snippets
    result['filter_code']=[s[max(0,m.start()-160):m.end()+250] for s in page.inline for m in re.finditer(r'category_type|date_ranges|createtime_start|createtime_end',s) if not re.search(r'token|secret|password',s[max(0,m.start()-160):m.end()+250],re.I)][:30]
    from session_store import remember
    remember(engine,"readonly")
    result["cookies_persisted"]=engine.state.get("cookies_persisted",False)
    return result
