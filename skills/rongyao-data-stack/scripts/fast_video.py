#!/usr/bin/env python3
"""Search new-material 2.0, resolve CDN links, and return sampled video frames."""
import argparse
import datetime as dt
import hashlib
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

import active_session_cli as session
import readonly_capture as capture

ROOT = Path(__file__).resolve().parent
STATE = session.DEFAULT_STATE
CACHE = Path(os.environ.get('RONGYAO_VIDEO_CACHE', str(Path.home()/'.cache/codex/rongyao-video')))
CDN = 'market-sy-ad-static.backend.example.invalid'
LOGIN = STATE.parent/'login.json'
KEYRING_STATE = Path.home()/'.codex/state/rongyao-keyring'
KEYRING_HELPER = KEYRING_STATE/'bin/rongyao-keychain'

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with tmp.open('x', encoding='utf-8') as f:
        os.chmod(tmp,0o600);json.dump(value,f,ensure_ascii=False,indent=2)
    tmp.replace(path)

def bridge(command, url=None):
    args=[str(session.node_bin()),str(ROOT/'video_bridge.mjs'),command,str(STATE)]
    if url: args.append(url)
    env=os.environ.copy()
    if (KEYRING_STATE/'disabled').exists():raise RuntimeError('ACCESS_REVOKED')
    if LOGIN.exists() and not (KEYRING_STATE/'provider.json').exists() and not (env.get('RONGYAO_USERNAME') and env.get('RONGYAO_PASSWORD')):
        if os.name!='nt' and LOGIN.stat().st_mode & 0o077:raise RuntimeError('LOGIN_FILE_PERMISSIONS: chmod 600 required')
        stored=json.loads(LOGIN.read_text())
        env['RONGYAO_USERNAME']=stored['username'];env['RONGYAO_PASSWORD']=stored['password']
    p=subprocess.run(args,capture_output=True,text=True,timeout=70,env=env)
    try:r=json.loads(p.stdout)
    except ValueError:raise RuntimeError('VIDEO_BRIDGE_FAILED') from None
    if not r.get('ok'):raise RuntimeError(r.get('status','VIDEO_BRIDGE_FAILED'))
    return r

def prepare():
    if (KEYRING_STATE/'disabled').exists():raise RuntimeError('ACCESS_REVOKED')
    if (KEYRING_STATE/'provider.json').exists() and not (os.environ.get('RONGYAO_USERNAME') and os.environ.get('RONGYAO_PASSWORD')):
        if not KEYRING_HELPER.is_file():raise RuntimeError('KEYRING_HELPER_MISSING')
        result=subprocess.run([str(KEYRING_HELPER),'ensure-query'],capture_output=True,text=True,timeout=90)
        try:r=json.loads(result.stdout)
        except ValueError:raise RuntimeError('KEYRING_OUTPUT_INVALID') from None
        if not r.get('ok'):raise RuntimeError(r.get('status','KEYRING_AUTH_FAILED'))
        return r
    session.ensure_active_session(STATE,session.DEFAULT_PROFILE)
    return bridge('prepare')

def configure_login():
    if (KEYRING_STATE/'provider.json').exists():raise RuntimeError('KEYCHAIN_PRIMARY: update the fixed Keychain item; do not create a divergent login file')
    if not sys.stdin.isatty():raise RuntimeError('Run configure-login yourself in a terminal; do not send credentials in chat')
    username=input('荣耀用户名（只保存本机）: ').strip()
    password=getpass.getpass('荣耀密码（不显示）: ')
    if not username or not password:raise ValueError('Empty credentials not saved')
    save(LOGIN,{'username':username,'password':password})
    return {'ok':True,'credentialConfigured':True,'login_verified':False}

def relogin():
    session.ensure_active_session(STATE,session.DEFAULT_PROFILE)
    # A changed account must not receive results or material IDs from the old account.
    for folder in ('queries','materials'):
        for path in (CACHE/folder).glob('*.json'):
            path.unlink()
    return bridge('relogin')

def material_id(url):return hashlib.sha256(url.encode()).hexdigest()[:24]

def normalize_rows(result):
    items=[]
    for row in result.get('rows') or []:
        url=row.get('demand_url')
        if not url:continue
        parsed=urllib.parse.urlsplit(url)
        if parsed.hostname!='demand.backend.example.invalid':continue
        item={'id':material_id(url),'name':row.get('video_name') or row.get('orgin_video_name'),
              'demand_url':url,'gid':row.get('gid'),'created_at':row.get('createDate'),
              'role':row.get('role'),'source_type':row.get('source_type'),'source_direction':row.get('source_direction'),
              'cost':row.get('cost'),'roi1':row.get('roi1'),'roi2':row.get('roi2'),
              'video_url':None,'video_playable':None,'transcript':None,'evidence_type':'backend_metadata'}
        if not any(x['id']==item['id'] for x in items):items.append(item)
    return items

def search(date_range, material_range, gid, keyword='', limit=20, refresh=False):
    if not 1<=int(limit)<=50:raise ValueError('limit must be 1..50')
    request={'date':date_range,'date2':material_range,'gid':str(gid),'include':'rows',
             'all_pages':False,'max_rows':5000,'max_pages':1,'search':{'keyword':keyword}}
    capture.normalized_request(request)  # Reject malformed parameters before accessing browser.
    key=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    cp=CACHE/'queries'/f'{key}.json'
    hit=not refresh and cp.exists() and time.time()-cp.stat().st_mtime<1800
    if hit: result=json.loads(cp.read_text())
    else:
        prepare()
        response=capture.run_batch([request],transport='active',concurrency=1,retries=0)
        result=response['results'][0]
        if not result.get('ok'):raise RuntimeError(result.get('error','QUERY_FAILED'))
        result['fetched_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        save(cp,result)
    items=normalize_rows(result)
    for item in items:save(CACHE/'materials'/f"{item['id']}.json",item)
    q=result.get('query',{})
    return {'ok':True,'cache_hit':hit,'fetched_at':result.get('fetched_at'),
            'identity':result.get('identity'),'query':q,'backend_total':result.get('summary'),
            'returned':len(items[:limit]),'has_more':len(items)>limit or q.get('totalpage',1)>q.get('pages_completed',1),
            'coverage':'first_page_only','items':items[:limit]}

def get_item(identifier):
    if len(identifier)!=24 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError('INVALID_MATERIAL_ID')
    p=CACHE/'materials'/f'{identifier}.json'
    if not p.exists():raise ValueError('MATERIAL_NOT_FOUND: search first')
    return json.loads(p.read_text())

def resolve(identifier):
    item=get_item(identifier)
    prepare()
    result=bridge('resolve',item['demand_url'])
    return {**result,'id':identifier,'name':item['name'],'video_url':result['media'][0]['url']}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('MEDIA_REDIRECT_BLOCKED')

def download(url,target):
    p=urllib.parse.urlsplit(url)
    if p.scheme not in ('http','https') or p.hostname!=CDN or p.port or p.username or p.password or not p.path.endswith('.mp4'):
        raise ValueError('UNSUPPORTED_MEDIA_URL')
    opener=urllib.request.build_opener(NoRedirect)
    temporary=target.with_suffix('.partial')
    try:
        with opener.open(url,timeout=30) as r,temporary.open('wb') as f:
            os.chmod(temporary,0o600)
            if not r.headers.get('Content-Type','').lower().startswith(('video/','application/octet-stream')):raise ValueError('NOT_VIDEO_RESPONSE')
            size=0
            while True:
                chunk=r.read(1024*1024)
                if not chunk:break
                size+=len(chunk)
                if size>250*1024*1024:raise ValueError('VIDEO_EXCEEDS_250_MB')
                f.write(chunk)
        temporary.replace(target)
    finally:temporary.unlink(missing_ok=True)

def binary(name):
    p=shutil.which(name) or str(Path.home()/'.local/bin'/name)
    if not Path(p).is_file():raise RuntimeError(f'{name.upper()}_REQUIRED')
    return p

def frames(identifier, count=8):
    if not 2<=int(count)<=12:raise ValueError('frame count must be 2..12')
    item=get_item(identifier)
    folder=CACHE/'media'/identifier;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    media=folder/'video.mp4';meta=folder/'source.json'
    if media.exists() and meta.exists():source=json.loads(meta.read_text())
    else:
        source=resolve(identifier);download(source['video_url'],media);save(meta,source)
    probe=subprocess.run([binary('ffprobe'),'-v','error','-show_format','-show_streams','-of','json',str(media)],capture_output=True,text=True,timeout=30)
    if probe.returncode:raise RuntimeError('VIDEO_DECODE_FAILED')
    info=json.loads(probe.stdout);duration=float(info['format']['duration'])
    video_stream=next((s for s in info['streams'] if s.get('codec_type')=='video'),None)
    if not video_stream:raise RuntimeError('VIDEO_STREAM_MISSING')
    visual_duration=min(duration,float(video_stream.get('duration') or duration))
    if not 0<duration<=3600:raise ValueError('UNSUPPORTED_DURATION')
    samples=[]
    for i in range(count):
        seconds=round(max(0,visual_duration-0.2)*i/(count-1),3)
        target=folder/f'frame-{count}-{seconds:.3f}.jpg'
        if not target.exists():
            p=subprocess.run([binary('ffmpeg'),'-nostdin','-v','error','-ss',str(seconds),'-i',str(media),'-frames:v','1','-vf','scale=640:-2','-q:v','3','-y',str(target)],capture_output=True,timeout=30)
            if p.returncode or not target.exists():raise RuntimeError('FRAME_EXTRACTION_FAILED')
            os.chmod(target,0o600)
        samples.append({'seconds':seconds,'path':str(target)})
    return {'ok':True,'id':identifier,'name':item['name'],'video_url':source['video_url'],
            'demand_url':item['demand_url'],'duration_seconds':duration,'video_decodable':True,
            'video_playable':None,'has_audio':any(s.get('codec_type')=='audio' for s in info['streams']),
            'evidence_type':'sampled_frames','coverage':'sampled_frames_only',
            'transcript':None,'audio_reviewed':False,'content_summary':None,'frames':samples}

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    sub.add_parser('configure-login')
    sub.add_parser('relogin')
    q=sub.add_parser('search');q.add_argument('--date-range',required=True);q.add_argument('--material-range',required=True);q.add_argument('--gid',required=True);q.add_argument('--keyword',default='');q.add_argument('--limit',type=int,default=20);q.add_argument('--refresh',action='store_true')
    for name in ['resolve','frames']:
        s=sub.add_parser(name);s.add_argument('--id',required=True)
        if name=='frames':s.add_argument('--count',type=int,default=8)
    a=vars(p.parse_args());command=a.pop('command')
    if 'id' in a:a['identifier']=a.pop('id')
    try:out=prepare() if command=='status' else configure_login() if command=='configure-login' else globals()[command](**a)
    except Exception as e:out={'ok':False,'error':str(e)[:400]}
    print(json.dumps(out,ensure_ascii=False,indent=2));return 0 if out.get('ok') else 1
if __name__=='__main__':sys.exit(main())
