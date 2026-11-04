#!/usr/bin/env python3
"""Machine-enforced workflow mutation guard: writer host, locks, release, authorization, circuits and JSONL events."""
from __future__ import annotations
import argparse,contextlib,datetime,fcntl,hashlib,importlib.util,json,os,shutil,socket,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
POLICY_PATH=ROOT/'workflow/runtime-policy.json'
RUNTIME=ROOT/'workflow/runtime'
LOCKS=RUNTIME/'locks'
CIRCUITS=RUNTIME/'circuits.json'
AUTH_LEDGER=RUNTIME/'authorization-ledger.json'
class GuardError(ValueError):pass

def load(path):return json.loads(Path(path).read_text())
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(temp,path)
def policy():
    result=load(POLICY_PATH)
    import receiver_config
    cfg=receiver_config.load()
    result['writer_hosts']=[cfg['writer_host']] if cfg.get('writer_host') else []
    result['action_writer_hosts']={}
    return result
def now():return datetime.datetime.now(datetime.timezone.utc)
def stamp():return now().isoformat()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v):
    if isinstance(v,(bytes,bytearray)):return hashlib.sha256(v).hexdigest()
    return hashlib.sha256(canonical(v).encode()).hexdigest()
def host():return socket.gethostname()
def scrub(v):
    secrets={'cookie','cookies','token','authorization','password','secret','app_secret','tenant_token'}
    if isinstance(v,dict):return {k:('[REDACTED]' if k.lower() in secrets else scrub(x)) for k,x in v.items()}
    if isinstance(v,list):return [scrub(x) for x in v]
    if isinstance(v,str) and len(v)>2000:return v[:2000]+'…'
    return v
def event(action,phase,scope,**details):
    cfg=policy()['event_log'];folder=ROOT/cfg['directory'];folder.mkdir(parents=True,exist_ok=True)
    p=folder/(now().date().isoformat()+'.jsonl')
    row={'ts':stamp(),'release_id':policy()['release_id'],'host':host(),'pid':os.getpid(),'action':action,'phase':phase,'scope':scope,'details':scrub(details)}
    with p.open('a+',encoding='utf-8') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.write(canonical(row)+'\n');f.flush();os.fsync(f.fileno());fcntl.flock(f,fcntl.LOCK_UN)
    return row
def ensure_writer(action):
    cfg=policy()
    allowed=set(cfg['writer_hosts']) | set(cfg.get('action_writer_hosts',{}).get(action,[]))
    if host() not in allowed:
        raise GuardError(f'WRITER_HOST_REQUIRED: {action} is read-only on {host()}; allowed={sorted(allowed)}')
def ensure_release(live=True):
    manifest=load(ROOT/'workflow/rules/manifest.json')
    if manifest.get('release_id')!=policy().get('release_id'):raise GuardError('RUNTIME_RELEASE_MISMATCH: runtime policy and manifest differ.')
    if not live:return {'release_id':manifest['release_id'],'live_center_verified':False}
    r=subprocess.run([sys.executable,str(ROOT/'scripts/workflow_rules.py'),'check'],cwd=ROOT,capture_output=True,text=True,timeout=60)
    try:d=json.loads(r.stdout or r.stderr)
    except Exception:raise GuardError('LIVE_RELEASE_UNAVAILABLE')
    if r.returncode or not d.get('ok') or not d.get('live_center_verified'):raise GuardError('LIVE_RELEASE_MISMATCH: '+str(d.get('error') or d))
    return d
def dependencies(action,scope=None):
    cfg=policy()
    scoped=cfg.get('scope_dependency_profiles',{}).get(scope,{})
    profile=scoped if scoped.get('action')==action else cfg['dependency_profiles'].get(action,{})
    if profile.get('unsupported'):raise GuardError('ACTION_UNSUPPORTED: no reviewed runtime implementation exists for '+action)
    missing=[]
    for exe in profile.get('executables',[]):
        if not shutil.which(exe):missing.append('exe:'+exe)
    for mod in profile.get('python_imports',[]):
        if importlib.util.find_spec(mod) is None:missing.append('python:'+mod)
    for name in profile.get('workspace_files',[]):
        file=(ROOT/name).resolve()
        if not file.is_relative_to(ROOT.resolve()) or not file.is_file():missing.append('workspace:'+name)
    for name in profile.get('required_paths',[]):
        if not Path(name).expanduser().is_file():missing.append('path:'+name)
    if missing:raise GuardError('DEPENDENCY_MISSING: '+', '.join(missing))
    return {'checked':profile,'missing':[]}
def _circuits():return load(CIRCUITS) if CIRCUITS.exists() else {'schema_version':1,'entries':{}}
def _save_circuits(v):atomic(CIRCUITS,v)
def circuit_key(action,scope):return action+':'+digest(scope)[:20]
def check_circuit(action,scope):
    row=_circuits()['entries'].get(circuit_key(action,scope))
    if row and row.get('open_until') and datetime.datetime.fromisoformat(row['open_until'])>now():
        raise GuardError('CIRCUIT_OPEN: repeated dependency failure; wait for cooldown or new evidence.')
def record_failure(action,scope,category,signature):
    cfg=policy()['circuit'];db=_circuits();key=circuit_key(action,scope);row=db['entries'].get(key,{'failures':[]})
    cutoff=now()-datetime.timedelta(seconds=cfg['window_seconds'])
    failures=[x for x in row.get('failures',[]) if datetime.datetime.fromisoformat(x['ts'])>=cutoff]
    failures.append({'ts':stamp(),'category':category,'signature':digest(signature)[:24]})
    row={'failures':failures,'last_category':category}
    if len(failures)>=cfg['failure_threshold']:row['open_until']=(now()+datetime.timedelta(seconds=cfg['cooldown_seconds'])).isoformat()
    db['entries'][key]=row;_save_circuits(db);event(action,'dependency_failure',scope,category=category,signature_sha256=digest(signature),circuit_open_until=row.get('open_until'));return row
def reset_circuit(action,scope):
    db=_circuits();db['entries'].pop(circuit_key(action,scope),None);_save_circuits(db)
def _auth_dir():
    d=(ROOT/policy()['authorization']['directory']).resolve()
    if not d.is_relative_to(ROOT):raise GuardError('Invalid authorization directory.')
    return d
def authorization(path,action,scope,input_sha256=None,reserve=True):
    if action not in policy()['authorization']['high_risk_actions']:return None
    if not path:raise GuardError('AUTHORIZATION_TICKET_REQUIRED: '+action)
    p=Path(path).resolve();base=_auth_dir()
    if not p.is_relative_to(base) or not p.is_file():raise GuardError('Authorization ticket must be a workspace authorization artifact.')
    t=load(p)
    for k,v in {'schema_version':1,'release_id':policy()['release_id'],'action':action,'scope':scope,'approved':True}.items():
        if t.get(k)!=v:raise GuardError('Authorization ticket mismatch: '+k)
    if not t.get('approval_ref') or not t.get('ticket_id'):raise GuardError('Authorization ticket lacks approval_ref/ticket_id.')
    issued=datetime.datetime.fromisoformat(t.get('issued_at',''));expiry=datetime.datetime.fromisoformat(t.get('expires_at',''))
    if issued.tzinfo is None or expiry.tzinfo is None or expiry<=now():raise GuardError('Authorization ticket expired.')
    lifetime=(expiry-issued).total_seconds()/60
    if lifetime<=0 or lifetime>policy()['authorization']['max_lifetime_minutes']:raise GuardError('Authorization ticket lifetime exceeds policy.')
    if input_sha256 and t.get('input_sha256')!=input_sha256:raise GuardError('Authorization ticket input hash differs.')
    ledger=load(AUTH_LEDGER) if AUTH_LEDGER.exists() else {'schema_version':1,'tickets':{}}
    if t['ticket_id'] in ledger['tickets']:raise GuardError('Authorization ticket already reserved; reconcile original operation.')
    if reserve:
        ledger['tickets'][t['ticket_id']]={'reserved_at':stamp(),'action':action,'scope':scope,'input_sha256':input_sha256,'ticket_path':str(p.relative_to(ROOT))}
        atomic(AUTH_LEDGER,ledger)
    return t
def create_ticket(action,scope,input_sha256,approval_ref,minutes):
    if action not in policy()['authorization']['high_risk_actions']:raise GuardError('Tickets only support high-risk actions.')
    if not approval_ref.strip():raise GuardError('approval_ref is required.')
    if not input_sha256 or len(input_sha256)!=64:raise GuardError('A reviewed 64-character SHA-256 is required.')
    if minutes<=0 or minutes>policy()['authorization']['max_lifetime_minutes']:raise GuardError('Invalid ticket lifetime.')
    issued=now();payload={'schema_version':1,'ticket_id':hashlib.sha256(os.urandom(32)).hexdigest()[:32],'release_id':policy()['release_id'],'action':action,'scope':scope,'approved':True,'approval_ref':approval_ref,'input_sha256':input_sha256,'issued_at':issued.isoformat(),'expires_at':(issued+datetime.timedelta(minutes=minutes)).isoformat()}
    base=_auth_dir();base.mkdir(parents=True,exist_ok=True);p=base/(payload['ticket_id']+'.json');p.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n');return p,payload
@contextlib.contextmanager
def lock(scope,action):
    ensure_writer(action);LOCKS.mkdir(parents=True,exist_ok=True);p=LOCKS/(digest(scope)[:32]+'.lock');f=p.open('a+',encoding='utf-8')
    try:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise GuardError('WORKFLOW_LOCKED: another session on writer host owns '+scope)
        f.seek(0);f.truncate();f.write(canonical({'host':host(),'pid':os.getpid(),'scope':scope,'action':action,'acquired_at':stamp()}));f.flush();os.fsync(f.fileno())
        yield
    finally:
        try:fcntl.flock(f,fcntl.LOCK_UN)
        finally:f.close()
@contextlib.contextmanager
def mutation(action,scope,authorization_ticket=None,input_sha256=None,live_release=True):
    if action == 'paid_generation' and scope == 'paid-generation:rongyao-ai-generator':
        import inspect
        caller = Path(inspect.currentframe().f_back.f_back.f_code.co_filename).resolve()
        allowed = ROOT/'workflow/rules/implementation/rongyao-tools/skills/rongyao-ai-generator/scripts/ryai.py'
        if caller != allowed.resolve():
            raise GuardError('UNREGISTERED_GENERATION_ENTRYPOINT: use workspace scripts/ryai.py')
    if action == 'paid_generation' and scope == 'paid-generation:dreamina-canvas-cli':
        import inspect
        caller = Path(inspect.currentframe().f_back.f_back.f_code.co_filename).resolve()
        if caller != (ROOT/'scripts/dreamina_workflow.py').resolve():
            raise GuardError('UNREGISTERED_GENERATION_ENTRYPOINT: use workspace scripts/dreamina_workflow.py')
    if action == 'material_upload' and scope == 'material-upload:rongyao-operations':
        import inspect
        caller = Path(inspect.currentframe().f_back.f_back.f_code.co_filename).resolve()
        published_root = Path(__file__).resolve().parents[1]
        allowed = [published_root/'scripts/native_upload_controller.py', published_root/'workflow/rules/implementation/rongyao-tools/skills/rongyao-operations/scripts/rongyao.py', published_root/'workflow/tools/rongyao-http-upload/scripts/upload_service.py']
        http_relative='workflow/tools/rongyao-http-upload/scripts/upload_service.py'
        http_sources=[published_root/http_relative,Path.home()/'.codex/skills/rongyao-http-upload/scripts/upload_service.py',Path.home()/'.agents/skills/rongyao-http-upload/scripts/upload_service.py']
        if caller in [p.resolve() for p in http_sources]:
            expected=load(ROOT/'workflow/rules/manifest.json').get('workspace_contract_files',{}).get(http_relative)
            if not expected or hashlib.sha256(caller.read_bytes()).hexdigest()!=expected:
                raise GuardError('HTTP_UPLOAD_DEPLOYMENT_MISMATCH: registered source SHA differs')
            allowed.append(caller)
        if caller not in [p.resolve() for p in allowed]:
            raise GuardError('UNREGISTERED_UPLOAD_ENTRYPOINT: use current published CLI')
    ensure_writer(action);check_circuit(action,scope);dependencies(action,scope);release=ensure_release(live_release)
    with lock(scope,action):
        ticket=authorization(authorization_ticket,action,scope,input_sha256,True)
        event(action,'start',scope,input_sha256=input_sha256,authorization_ticket_id=ticket.get('ticket_id') if ticket else None,live_release=release.get('release_id'))
        try:yield {'release':release,'ticket':ticket}
        except Exception as exc:event(action,'failed',scope,error_type=type(exc).__name__,error=str(exc));raise
        else:event(action,'completed',scope,input_sha256=input_sha256)
def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    q=sub.add_parser('check');q.add_argument('--action',required=True);q.add_argument('--scope',required=True);q.add_argument('--authorization-ticket');q.add_argument('--input-sha256');q.add_argument('--offline',action='store_true')
    t=sub.add_parser('ticket');t.add_argument('--action',required=True);t.add_argument('--scope',required=True);t.add_argument('--input-sha256',required=True);t.add_argument('--approval-ref',required=True);t.add_argument('--minutes',type=int,default=30)
    f=sub.add_parser('failure');f.add_argument('--action',required=True);f.add_argument('--scope',required=True);f.add_argument('--category',required=True);f.add_argument('--signature',required=True)
    a=p.parse_args()
    try:
        if a.cmd=='ticket':
            path,ticket=create_ticket(a.action,a.scope,a.input_sha256,a.approval_ref,a.minutes);print(json.dumps({'ok':True,'path':str(path.relative_to(ROOT)),'ticket':ticket},ensure_ascii=False,indent=2));return
        if a.cmd=='failure':print(json.dumps({'ok':True,'circuit':record_failure(a.action,a.scope,a.category,a.signature)},ensure_ascii=False,indent=2));return
        ensure_writer(a.action);check_circuit(a.action,a.scope);dep=dependencies(a.action,a.scope);rel=ensure_release(not a.offline);authorization(a.authorization_ticket,a.action,a.scope,a.input_sha256,False);print(json.dumps({'ok':True,'release':rel,'dependencies':dep,'writer_host':host(),'side_effects':[]},ensure_ascii=False,indent=2))
    except (GuardError,ValueError,OSError,subprocess.SubprocessError) as exc:
        print(json.dumps({'ok':False,'error':str(exc),'side_effects':[]},ensure_ascii=False),file=sys.stderr);raise SystemExit(1)
if __name__=='__main__':main()
