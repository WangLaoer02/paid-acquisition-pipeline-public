"""Device-local Keychain session persistence; public output is always secret-free."""
import argparse
import fcntl
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

BASE = Path.home() / '.codex/state/rongyao-http'
BINARY = BASE / 'bin/rongyao-session-vault'
SOURCE = Path(__file__).resolve().parent
COOKIE_FIELDS = ('version','name','value','port','port_specified','domain','domain_specified',
                 'domain_initial_dot','path','path_specified','secure','expires','discard',
                 'comment','comment_url','rfc2109')
DOMAINS = {'backend.example.invalid','power.houtai.backend.example.invalid','adopenplatform.backend.example.invalid',
           'demand.backend.example.invalid','data.houtai.cn.sy.backend.example.invalid'}


def permitted():
    if (Path.home()/'.codex/state/rongyao-keyring/disabled').exists():
        raise ValueError('ACCESS_REVOKED')


def vault(command, scope, value=None):
    permitted()
    if scope not in ('readonly','upload'): raise ValueError('UNKNOWN_HTTP_SERVICE')
    if not BINARY.is_file(): raise ValueError('SESSION_VAULT_NOT_BUILT')
    payload = json.dumps(value,separators=(',',':')).encode() if value is not None else None
    environment={k:v for k,v in os.environ.items() if k not in ('RONGYAO_USERNAME','RONGYAO_PASSWORD')}
    result = subprocess.run([str(BINARY),command,scope],input=payload,capture_output=True,timeout=10,env=environment)
    try: data=json.loads(result.stdout)
    except (ValueError,UnicodeError): raise ValueError('SESSION_VAULT_OUTPUT_INVALID') from None
    if result.returncode or data.get('ok') is False:
        status=data.get('status')
        raise ValueError(status if status in ('SESSION_VAULT_ACCESS_REQUIRED','INVALID_SESSION_PAYLOAD')
                         else 'SESSION_VAULT_FAILED')
    return data


def build():
    if BINARY.exists(): return {'ok':True,'status':'SESSION_VAULT_ALREADY_BUILT'}
    BINARY.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(BINARY.parent,0o700)
    result=subprocess.run(['/usr/bin/swiftc',str(SOURCE/'session_vault.swift'),'-o',str(BINARY),
                           '-framework','Security'],capture_output=True,timeout=60)
    if result.returncode: raise ValueError('SESSION_VAULT_BUILD_FAILED')
    BINARY.chmod(0o700)
    return {'ok':True,'status':'SESSION_VAULT_BUILT','existing_password_helper_changed':False}


def save(engine,scope,force=False):
    cookies=[]
    for cookie in engine.http.jar:
        if cookie.domain.lstrip('.') not in DOMAINS: continue
        item={key:getattr(cookie,key) for key in COOKIE_FIELDS}
        item['rest']=cookie._rest
        cookies.append(item)
    if not cookies: raise ValueError('NO_RONGYAO_SESSION_COOKIES')
    value={'version':1,'scope':scope,'cookies':cookies,
           'authentication_method':engine.state.get('authentication_method','existing_session')}
    fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    if not force and getattr(engine,'_saved_session_fingerprint',None)==fingerprint:return
    value['saved_at']=time.time()
    vault('save',scope,value)
    engine._saved_session_fingerprint=fingerprint
    engine.state.update(cookies_persisted=True,session_storage='macos_keychain',session_persistence_error=None)


def remember(engine,scope):
    # Persistence failure does not replay or fail a completed remote operation.
    try:
        if engine.state.get('status')!='ready':return
        save(engine,scope)
    except Exception as error:
        status=str(error)
        engine.state.update(cookies_persisted=False,session_persistence_error=(status if status.isupper()
                            and status.replace('_','').isalnum() else 'SESSION_SAVE_FAILED'))


def load(scope):
    value=vault('load',scope)
    if value.get('status')=='NO_SAVED_SESSION':return None
    if value.get('version')!=1 or value.get('scope')!=scope or not isinstance(value.get('cookies'),list):
        raise ValueError('INVALID_SAVED_SESSION')
    from http_transport import PasswordSessionTransport
    from http_core import Engine
    transport=PasswordSessionTransport()
    for item in value['cookies']:
        if not isinstance(item,dict) or item.get('domain','').lstrip('.') not in DOMAINS:
            raise ValueError('INVALID_SAVED_SESSION')
        try:cookie=http.cookiejar.Cookie(**{key:item[key] for key in (*COOKIE_FIELDS,'rest')})
        except (KeyError,TypeError,ValueError):raise ValueError('INVALID_SAVED_SESSION') from None
        # Session cookies intentionally survive process restarts; platform validity still applies.
        if cookie.expires is None or cookie.expires>time.time():transport.jar.set_cookie(cookie)
    if not list(transport.jar):return None
    engine=Engine(transport=transport,authenticated=True)
    engine._session_scope=scope
    engine.state.update(authentication_method=value.get('authentication_method','existing_session'),
                        cookies_persisted=True,session_storage='macos_keychain',restored_from_keychain=True)
    return engine


def verify(engine,scope):
    if scope=='upload':
        sys.path.insert(0,str(Path.home()/'.codex/skills/rongyao-http-upload/scripts'))
        from upload_service import verify_source
        verify_source()
        from upload_api import Api
        Api(engine).fields()
    else:engine.read_list()


def spawn(engine,output_dir,lifetime,scope,session_id=None):
    output_dir=Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    sid=session_id or uuid.uuid4().hex[:10]
    target=Path.home()/('.codex/state/rongyao-upload-http' if scope=='upload' else '.codex/state/rongyao-http')
    error_file=BASE/('start-'+sid+'.json')
    environment={k:v for k,v in os.environ.items() if k not in ('RONGYAO_USERNAME','RONGYAO_PASSWORD')}
    # Start a clean interpreter; never inherit macOS networking threads via os.fork().
    process=subprocess.Popen([sys.executable,str(SOURCE/'session_store.py'),'_serve',
        '--service',scope,'--output-dir',str(output_dir),'--session-id',sid,'--lifetime',str(lifetime)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        start_new_session=True,close_fds=True,env=environment)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if error_file.exists():
            error=json.loads(error_file.read_text());error_file.unlink()
            raise ValueError(error.get('status','RESTORED_SERVICE_START_FAILED'))
        if (target/(sid+'.sock')).exists() and (target/(sid+'.json')).exists():
            return {'ok':True,'status':'SAVED_HTTP_SESSION_RESTORED','session_id':sid,
                    'service_kind':scope,'cookies_persisted':True,'session_storage':'macos_keychain',
                    'authenticated':True,'password_submitted':False,'sms_sent':False,'browser_started':False}
        if process.poll() is not None:raise ValueError('RESTORED_SERVICE_START_FAILED')
        time.sleep(.05)
    process.terminate()
    raise ValueError('RESTORED_SERVICE_START_TIMEOUT')


def serve_saved(scope,output_dir,sid,lifetime):
    if len(sid)!=10 or any(c not in '0123456789abcdef' for c in sid):raise ValueError('INVALID_SESSION_ID')
    error_file=BASE/('start-'+sid+'.json')
    try:
        engine=load(scope)
        if engine is None:raise ValueError('NO_VALID_SAVED_SESSION')
        verify(engine,scope);save(engine,scope,force=True)
        if scope=='upload':
            from upload_service import serve_upload_engine
            serve_upload_engine(engine,output_dir,session_id=sid,lifetime=lifetime)
        else:
            from rongyao_http import serve_engine
            serve_engine(engine,output_dir,session_id=sid,lifetime=lifetime)
    except Exception as error:
        code=str(error)
        error_file.write_text(json.dumps({'status':code if code.isupper() and code.replace('_','').isalnum()
                                         else 'RESTORED_SERVICE_START_FAILED'}))
        error_file.chmod(0o600)


def recovery_status(scope, status, **facts):
    """Keep one sanitized diagnostic, never cookie values or response bodies."""
    value = {'scope': scope, 'status': status, 'checked_at': time.time(),
             'sms_sent': False, **facts}
    target = BASE / ('restore-' + scope + '-status.json')
    previous = json.loads(target.read_text()) if target.is_file() else {}
    last_failure = previous.get('last_authentication_failure')
    if status in ('LOGIN_EXPIRED', 'RONGYAO_LOGIN_UNVERIFIED'):
        last_failure = dict(value)
    if last_failure:
        value['last_authentication_failure'] = last_failure
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True))
    temporary.chmod(0o600)
    temporary.replace(target)


def restore_service(output_dir,lifetime=86400,scope='readonly'):
    if not BINARY.exists():return None  # Existing machines remain on their original login path.
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(BASE/('restore-'+scope+'.lock'),'a') as lock:
        os.chmod(lock.name,0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('SESSION_RESTORE_IN_PROGRESS') from None
        existing=running_saved_service(scope)
        if existing:return existing
        engine=load(scope)
        if engine is None:
            recovery_status(scope, 'NO_VALID_SAVED_SESSION', keychain_cleared=False)
            return None
        try:verify(engine,scope)
        except ValueError as error:
            reason = str(error)
            if reason in ('LOGIN_EXPIRED', 'RONGYAO_LOGIN_UNVERIFIED'):
                vault('clear', scope)
                recovery_status(scope, reason, keychain_cleared=True)
                return None
            recovery_status(scope, reason if reason.isupper() and reason.replace('_','').isalnum() else 'SESSION_VERIFICATION_FAILED', keychain_cleared=False)
            raise
        save(engine,scope,force=True)
        result = spawn(engine,output_dir,lifetime,scope)
        recovery_status(scope, 'RESTORED_AND_PROTECTED_READ_VERIFIED', keychain_cleared=False)
        return result


def running_saved_service(scope):
    try:
        if scope=='upload':
            sys.path.insert(0,str(Path.home()/'.codex/skills/rongyao-http-upload/scripts'))
            from rongyao_upload import rpc
            result=rpc('status',_restored=True)
        else:
            from rongyao_http import rpc
            result=rpc('status',_restored=True)
        if result.get('ok') and result.get('status')=='ready' and result.get('cookies_persisted'):
            return result
    except (ValueError,OSError):pass
    return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build','status','forget','restore','initialize','_serve'])
    parser.add_argument('--service',choices=['readonly','upload'],default='upload')
    parser.add_argument('--output-dir')
    parser.add_argument('--session-id')
    parser.add_argument('--lifetime',type=int,default=86400)
    args=parser.parse_args()
    try:
        if args.command=='_serve':
            if not args.session_id or not args.output_dir:parser.error('_serve requires session-id and output-dir')
            serve_saved(args.service,args.output_dir,args.session_id,args.lifetime);return 0
        if args.command=='build':result=build()
        elif args.command=='status':result=vault('status',args.service)
        elif args.command=='forget':result=vault('clear',args.service)
        elif args.command=='initialize':
            if not args.output_dir:parser.error('initialize requires --output-dir')
            from initialize_session import initialize
            return initialize(args.output_dir,args.service)
        else:
            if not args.output_dir:parser.error('restore requires --output-dir')
            result=restore_service(args.output_dir,scope=args.service) or {
                'ok':False,'status':'NO_VALID_SAVED_SESSION','sms_sent':False}
        print(json.dumps(result,ensure_ascii=False));return 0 if result.get('ok') else 1
    except Exception as error:
        code=str(error)
        print(json.dumps({'ok':False,'status':code if code.isupper() and code.replace('_','').isalnum()
                          else 'SESSION_STORE_FAILED','sms_sent':None if args.command=='initialize' else False}));return 1


if __name__=='__main__':sys.exit(main())
