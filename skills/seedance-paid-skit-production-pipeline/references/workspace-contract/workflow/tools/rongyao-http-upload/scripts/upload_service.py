"""Separate writable local service. Auth cookies never cross the RPC boundary."""
import fcntl,hashlib,importlib.util,json,math,os,re,socket,socketserver,sys,threading,time,uuid
from pathlib import Path
from upload_api import Api,CDN,PRECHECK,CHUNK,ReadBackoff,acknowledged
from attribution import intended_designer,acceptance
BASE=Path.home()/'.codex/state/rongyao-upload-http'
SOURCE=Path(__file__).resolve().parent.parent
LOADED_SOURCE = {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in SOURCE.joinpath('scripts').glob('*.py')}

def verify_source():
    m=json.loads((SOURCE/'manifest.json').read_text())
    for name,digest in m['files'].items():
        if hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()!=digest:raise ValueError('HTTP_UPLOAD_SOURCE_CHANGED')
    for name,digest in LOADED_SOURCE.items():
        if hashlib.sha256((SOURCE/'scripts'/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('UPLOAD_SERVICE_RESTART_REQUIRED')
    return m['version']
def operations():
    path=Path.home()/'.codex/skills/rongyao-operations/scripts/rongyao.py'
    spec=importlib.util.spec_from_file_location('existing_rongyao_operations',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def legacy_hold(item):
    path=Path.home()/'.config/rongyao-material-upload/single-current/receipts.sqlite3'
    # Existing generic operations ledger is always shared; the old fixed-plan
    # receipts are checked too when present, without importing that old Plan.
    import sqlite3
    if not path.is_file():return
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        for row in db.execute('SELECT receipt FROM receipts'):
            r=json.loads(row[0])
            if r.get('file_sha256')==item['sha256'] or r.get('upload_name')==item['filename']:raise ValueError('LEGACY_SUBMISSION_NEEDS_RECONCILIATION')

def error_code(exc):
    message=str(exc)
    return message if re.fullmatch('[A-Z0-9_]+',message) else type(exc).__name__

def save_receipt(ops,out,jid,item,receipt):
    # Each file has a stable, independent receipt; no batch item overwrites another.
    key=hashlib.sha256(item['filename'].encode()).hexdigest()[:24]
    ops.save(out/(jid+'-'+key+'-receipt.json'),receipt)

def detail_acceptance(fields,parameters,designer=None,selects=None):
    return acceptance(fields,parameters,designer,selects)

def native_record(api,item,receipt=None,record_id=None):
    receipt=receipt or {};ident=str(record_id or receipt.get('record_id') or '')
    record={'id':ident,'name':item['filename'].removesuffix('.mp4')}
    alias=(item.get('provenance') or {}).get('listed_native_identity') or receipt.get('verified_native_identity')
    if not alias:return record
    if (str(alias.get('record_id'))!=ident or alias.get('ledger_name')!=item['filename']
            or alias.get('sha256')!=item['sha256'] or not alias.get('media')):
        raise ValueError('NATIVE_ALIAS_SNAPSHOT_MISMATCH')
    native=operations().filename(alias.get('native_name')).removesuffix('.mp4')
    expected={'id':ident,'name':native}
    actual=api.lookup(native+'.mp4')
    if actual!=expected:raise ValueError('NATIVE_ALIAS_IDENTITY_MISMATCH')
    return expected


def receipt_designer(item,receipt):
    try:return intended_designer(item)
    except ValueError:
        reference=receipt.get('designer_intent_plan') or {}
        if not reference:return None
        ops=operations();plan=ops.registered_plan(reference['job_id'])
        if ops.plan_digest(plan)!=reference.get('sha256'):raise ValueError('DESIGNER_INTENT_PLAN_CHANGED')
        matches=[x for x in plan['items'] if x['filename']==item['filename'] and x['sha256']==item['sha256'] and x['parameters']==item['parameters']]
        if len(matches)!=1:raise ValueError('DESIGNER_INTENT_FILE_MISMATCH')
        return intended_designer(matches[0])


def inspect_attribution(api,item,receipt):
    designer=receipt_designer(item,receipt)
    options=api.fields().get('selects',{})
    receipt['detail_fields']=api.detail(native_record(api,item,receipt))
    receipt['detail_readback_verified']=True
    receipt['attribution_acceptance']=detail_acceptance(receipt['detail_fields'],item['parameters'],designer,options)
    receipt['attribution_schema']=2
    receipt['metadata_verified']=receipt['attribution_acceptance']['verified']
    receipt.pop('detail_error',None)

def submit(api,args,out):
    version=verify_source();ops=operations();workspace=args['workspace']
    runtime=ops.load_runtime(workspace);value=ops.reviewed_plan(args['plan']);jid=value['job_id']
    if value.get('test_only') or 'native_execution' in value:raise ValueError('PLAN_NOT_HTTP_SUBMITTABLE')
    if any((x.get('provenance') or {}).get('operation') in ('existing_id_designer_reconciliation_only','existing_id_metadata_reconciliation_only') for x in value['items']):raise ValueError('METADATA_ONLY_PLAN_NOT_SUBMITTABLE')
    digest=ops.plan_digest(value);ledger=ops.Ledger();results=[]
    hashes=set();numbers=set()
    for item in value['items']:
        # Designer is an independent, plan-bound intent. It is not the account
        # create_name, requester, or second designer, and is never guessed.
        designer=intended_designer(item)
        held=ledger.existing(item['filename'])
        if held and held['state']!='blocked_before_selection':
            prior=ledger.job(held['owner'])
            prior_item=next(x for x in prior['items'] if x['filename']==item['filename'])
            if intended_designer(prior_item)!=designer:raise ValueError('SAME_FILE_DIFFERENT_DESIGNER')
        if item['sha256'] in hashes:raise ValueError('DUPLICATE_CONTENT_IN_BATCH')
        hashes.add(item['sha256'])
        number=ops.production_number(item['filename'])
        if number and number in numbers:raise ValueError('DUPLICATE_PRODUCTION_NUMBER_IN_BATCH')
        if number:numbers.add(number)
    with runtime.mutation('material_upload',ops.UPLOAD_SCOPE,authorization_ticket=args['authorization_ticket'],input_sha256=digest):
        if ops.registered_plan(jid)!=value:raise ValueError('REGISTERED_PLAN_CHANGED')
        for item in value['items']:
            content=Path(item['file']).read_bytes()
            if hashlib.sha256(content).hexdigest()!=item['sha256']:raise ValueError('PLAN_FILE_CHANGED')
            legacy_hold(item)
            # Cross-chat/cross-transport dedup uses the same authoritative ledger.
            # claim checks SHA and production number inside BEGIN IMMEDIATE.
            try:old=ledger.claim(jid,item)
            except ValueError as e:
                if str(e)!='PRIOR_SUBMISSION_NEEDS_RECONCILIATION':raise
                held=ledger.existing(item['filename'])
                results.append({'filename':item['filename'],'status':'PRIOR_SUBMISSION_NEEDS_RECONCILIATION','job_id':held['owner'],'state':held['state']})
                continue
            if old:
                results.append({'filename':item['filename'],'status':'SKIP_ALREADY_LISTED','record_id':old['record_id']});continue
            sent=False;receipt={'job_id':jid,'filename':item['filename'],'sha256':item['sha256'],'transport':'direct_http_sms','uploader_version':version,'browser_started':False,'browser_connected':False,'phases':[]}
            try:
                hidden=api.validate_fields(item['parameters'],(item.get('provenance') or {}).get('requester_explicit_original_override') is True)
                record=api.lookup(item['filename'])
                if record:
                    receipt.update(status='blocked_before_selection',error='BACKEND_NAME_HELD',record=record)
                    ledger.update(jid,item['filename'],'blocked_before_selection',evidence=receipt)
                    save_receipt(ops,out,jid,item,receipt)
                    results.append({'filename':item['filename'],'status':'BACKEND_NAME_HELD','record':record});continue
                check=api.json(PRECHECK,[('names[]',item['filename'])]);info=check.get('info')
                if not acknowledged(check.get('status')) or not isinstance(info,list) or len(info)!=1 or not isinstance(info[0],dict):raise ValueError('NATIVE_NAME_PRECHECK_INVALID')
                if str(info[0].get('num'))!='0' or not acknowledged(info[0].get('status')):raise ValueError('NATIVE_NUMBER_OR_NAME_CONFLICT')
                total=(len(content)+CHUNK-1)//CHUNK;nonce=str(time.time_ns())
                receipt.update(total_chunks=total,nonce=nonce,submitted_at=time.time(),identity=hidden['create_name'],parameters=item['parameters'])
                # Persist uncertainty before the first upload byte can leave.
                ledger.update(jid,item['filename'],'selection_pending',evidence=receipt);sent=True
                for index in range(total):
                    receipt['last_send_at']=time.time()
                    receipt['phases'].append({'phase':'chunk','index':index+1,'state':'SENDING'})
                    ledger.update(jid,item['filename'],'selection_pending',evidence=receipt)
                    r=api.json(CDN+'?act=upload',[('name',item['filename']),('total',total),('index',index+1),('time',nonce)],content[index*CHUNK:(index+1)*CHUNK])
                    if not acknowledged(r.get('status')):raise ValueError('CHUNK_REJECTED')
                    receipt['phases'][-1]['state']='ACK'
                p=item['parameters'];fields=list(dict(total=total,time=nonce,name=item['filename'],**hidden,tag=','.join(p['role']),category_type=p['category_type'],tmp_flag=1,**{k:p[k] for k in ('ai_source','origin_type','demand_name','is_redbag','region_type')}).items())
                fields += [(k+'[]',v) for k in ('source_ip','source_type','source_direction') for v in p[k]]
                if not p['source_ip']:fields.append(('source_ip',''))
                receipt['last_send_at']=time.time()
                receipt['phases'].append({'phase':'join','state':'SENDING'});ledger.update(jid,item['filename'],'selection_pending',evidence=receipt)
                r=api.json(CDN+'?act=join',fields)
                if not acknowledged(r.get('status')):raise ValueError('JOIN_REJECTED')
                receipt['phases'][-1]['state']='ACK';receipt.update(status='submitted_pending',join_ack=True)
                ledger.update(jid,item['filename'],'submitted_pending',evidence=receipt)
                save_receipt(ops,out,jid,item,receipt)
                results.append({'filename':item['filename'],'status':'submitted_pending','join_ack':True,'reconcile_after_seconds':0,'fallback_processing_seconds':120})
            except Exception as e:
                receipt.update(status='submission_unknown' if sent else 'blocked_before_selection',error=error_code(e))
                ledger.update(jid,item['filename'],receipt['status'],evidence=receipt);save_receipt(ops,out,jid,item,receipt)
                raise
    return {'ok':all(x['status'] in ('submitted_pending','SKIP_ALREADY_LISTED') for x in results),'job_id':jid,'items':results,'browser_started':False,'browser_connected':False,'automatic_retry':False}

def read_deadline(receipt,key):
    value=receipt.get(key)
    if value is None:return 0
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise ValueError('RECONCILE_CHECKPOINT_INVALID')
    return value

def retain_read_backoff(receipt,error):
    if not isinstance(error,ReadBackoff):return 0
    delay=error.retry_after_seconds
    if type(delay) not in (int,float) or not math.isfinite(delay) or delay<0:delay=120
    until=max(read_deadline(receipt,'next_lookup_at'),time.time()+delay)
    receipt.update(next_lookup_at=until,http_read_retry_after_until=until,lookup_http_status=error.status_code)
    return until

def reconcile(api,jid,out,refresh_details=False):
    ops=operations();ledger=ops.Ledger();value=ledger.job(jid);results=[];batch_backoff_until=0
    # A server backoff from this original batch also applies to its other names.
    # Restore it after restart before issuing any more reads to the same endpoint.
    for item in value['items']:
        held=ledger.existing(item['filename'])
        if held and held['sha']==item['sha256'] and ledger.same_parameters(held,item):
            saved=json.loads(held['evidence'] or '{}') or {}
            batch_backoff_until=max(batch_backoff_until,read_deadline(saved,'http_read_retry_after_until'))
    for item in value['items']:
        old=ledger.existing(item['filename'])
        if not old:
            results.append({'filename':item['filename'],'status':'planned','error':'NO_UPLOAD_CHECKPOINT','record_id':None});continue
        if old['sha']!=item['sha256'] or not ledger.same_parameters(old,item):raise ValueError('JOB_RESERVATION_MISMATCH')
        receipt=json.loads(old['evidence'] or '{}') or {}
        if old['record_id']:receipt['record_id']=old['record_id']
        if old['state']=='listed':
            if refresh_details or receipt.get('attribution_schema')!=2 or not receipt.get('metadata_verified'):
                now=time.time()
                if batch_backoff_until>now:
                    receipt.update(detail_readback_verified=False,metadata_verified=False,detail_error='HTTP_BACKOFF_PENDING',next_lookup_at=batch_backoff_until,http_read_retry_after_until=batch_backoff_until)
                else:
                    try:
                        record={'id':old['record_id'],'name':item['filename'].removesuffix('.mp4')}
                        inspect_attribution(api,item,receipt)
                    except Exception as e:
                        receipt['detail_readback_verified']=False;receipt['metadata_verified']=False;receipt['detail_error']=error_code(e)
                        batch_backoff_until=max(batch_backoff_until,retain_read_backoff(receipt,e))
                ledger.update(old['owner'],item['filename'],'listed',old['record_id'],evidence=receipt)
                save_receipt(ops,out,jid,item,receipt)
            results.append({'filename':item['filename'],'status':'listed','record_id':old['record_id'],'detail_readback_verified':receipt.get('detail_readback_verified',False),'metadata_verified':receipt.get('metadata_verified',False),'detail_error':receipt.get('detail_error'),'attribution_acceptance':receipt.get('attribution_acceptance')})
            continue
        if old['owner']!=jid:raise ValueError('JOB_DOES_NOT_OWN_RESERVATION')
        if old['state'] not in {'selection_pending','submitted_pending','submission_unknown'}:
            results.append({'filename':item['filename'],'status':old['state'],'error':'NO_UPLOAD_CHECKPOINT','record_id':None});continue
        if receipt.get('transport')!='direct_http_sms':
            results.append({'filename':item['filename'],'status':old['state'],'error':'RECONCILE_ORIGINAL_TRANSPORT_REQUIRED','record_id':None});continue
        now=time.time();submitted_at=read_deadline(receipt,'submitted_at')
        if not submitted_at:
            results.append({'filename':item['filename'],'status':old['state'],'error':'NO_UPLOAD_CHECKPOINT','record_id':None});continue
        until=max(read_deadline(receipt,'next_lookup_at'),batch_backoff_until)
        if until>now:
            if batch_backoff_until>read_deadline(receipt,'http_read_retry_after_until'):
                receipt.update(next_lookup_at=until,http_read_retry_after_until=batch_backoff_until)
                ledger.update(jid,item['filename'],old['state'],evidence=receipt);save_receipt(ops,out,jid,item,receipt)
            results.append({'filename':item['filename'],'status':old['state'],'error':'HTTP_BACKOFF_PENDING' if batch_backoff_until>now else 'RECONCILE_INTERVAL_PENDING','record_id':None,'next_lookup_at':until,'retry_after_seconds':max(0,until-now),'lookup_attempted':False});continue
        attempts=receipt.get('lookup_attempts',0)
        if type(attempts) is not int or attempts<0:raise ValueError('RECONCILE_CHECKPOINT_INVALID')
        original_due=(read_deadline(receipt,'last_send_at') or submitted_at)+120
        next_at=original_due if attempts==0 and original_due>now else now+120
        # Persist before the read, so timeout, disconnect or restart cannot cause
        # the first immediate lookup to become a busy loop. No lock-held sleep.
        receipt.update(lookup_attempts=attempts+1,last_lookup_at=now,next_lookup_at=next_at)
        ledger.update(jid,item['filename'],old['state'],evidence=receipt);save_receipt(ops,out,jid,item,receipt)
        try:record=api.lookup(item['filename'])
        except Exception as e:
            receipt['reconcile_error']=error_code(e)
            batch_backoff_until=max(batch_backoff_until,retain_read_backoff(receipt,e))
            ledger.update(jid,item['filename'],old['state'],evidence=receipt);save_receipt(ops,out,jid,item,receipt)
            results.append({'filename':item['filename'],'status':old['state'],'error':error_code(e),'record_id':None,'next_lookup_at':receipt['next_lookup_at'],'retry_after_seconds':max(0,receipt['next_lookup_at']-time.time()),'lookup_attempted':True});continue
        receipt.pop('reconcile_error',None)
        if record:
            receipt.update(status='listed',record_id=record['id'],name_verified=True,category_and_class_filtered=False,metadata_verified=False,remote_playback_verified=False)
            try:
                inspect_attribution(api,item,receipt)
            except Exception as e:
                receipt['detail_readback_verified']=False;receipt['detail_error']=error_code(e)
                batch_backoff_until=max(batch_backoff_until,retain_read_backoff(receipt,e))
            ledger.update(jid,item['filename'],'listed',record['id'],evidence=receipt);save_receipt(ops,out,jid,item,receipt)
        else:
            ledger.update(jid,item['filename'],old['state'],evidence=receipt);save_receipt(ops,out,jid,item,receipt)
        result={'filename':item['filename'],'status':'listed' if record else old['state'],'record_id':record['id'] if record else None,'detail_readback_verified':receipt.get('detail_readback_verified',False),'metadata_verified':receipt.get('metadata_verified',False),'attribution_acceptance':receipt.get('attribution_acceptance'),'lookup_attempted':True}
        if not record:result.update(next_lookup_at=receipt['next_lookup_at'],retry_after_seconds=max(0,receipt['next_lookup_at']-time.time()))
        results.append(result)
    return {'ok':not any(x.get('error') for x in results),'job_id':jid,'items':results,'all_listed':bool(results) and all(x['status']=='listed' for x in results),'all_metadata_verified':bool(results) and all(x.get('metadata_verified',False) for x in results),'browser_started':False,'browser_connected':False,'remote_writes_performed':False}

def finalize_attribution(api,args,out):
    """A separately authorized metadata action; never calls upload or join."""
    verify_source();ops=operations();ledger=ops.Ledger();value=ledger.job(args['job_id'])
    if ops.registered_plan(value['job_id'])!=value:raise ValueError('REGISTERED_PLAN_CHANGED')
    digest=ops.plan_digest(value);runtime=ops.load_runtime(args['workspace']);results=[]
    with runtime.mutation('material_upload',ops.UPLOAD_SCOPE,authorization_ticket=args['authorization_ticket'],input_sha256=digest):
        options=api.fields().get('selects',{})
        for item in value['items']:
            old=ledger.existing(item['filename'])
            if not old or old['state']!='listed' or not old['record_id']:raise ValueError('LISTED_RECORD_REQUIRED')
            if old['sha']!=item['sha256'] or not ledger.same_parameters(old,item):raise ValueError('JOB_RESERVATION_MISMATCH')
            name=intended_designer(item);record=native_record(api,item,json.loads(old['evidence'] or '{}'),old['record_id'])
            before=api.detail_snapshot(record);check=detail_acceptance(before['fields'],item['parameters'],name,options)
            if before['record']!=record:raise ValueError('DETAIL_IDENTITY_MISMATCH')
            alias=(item.get('provenance') or {}).get('listed_native_identity')
            if alias and before['media']!=alias['media']:raise ValueError('NATIVE_ALIAS_MEDIA_MISMATCH')
            if any(v['status']!='matched' for k,v in check['checks'].items() if k!='设计师'):raise ValueError('OTHER_METADATA_MISMATCH')
            receipt=json.loads(old['evidence'] or '{}') or {};receipt['record_id']=record['id']
            checkpoint=receipt.get('designer_write') or {};changed=False
            if checkpoint.get('phase') in ('SENDING','ACK','UNKNOWN') and checkpoint.get('before') and before['fields'].get('设计师')==name:
                previous=checkpoint['before']
                if before['fields']!={**previous['fields'],'设计师':name} or before['media']!=previous['media']:raise ValueError('DESIGNER_RECOVERY_METADATA_DRIFT')
            if before['fields'].get('设计师')!=name:
                if checkpoint.get('phase') in ('SENDING','ACK','UNKNOWN'):raise ValueError('DESIGNER_WRITE_UNKNOWN_READONLY_RECONCILE_REQUIRED')
                receipt['designer_write']={'phase':'SENDING','expected':name,'record_id':record['id'],'before':before,'at':time.time(),'automatic_retry':False}
                ledger.update(old['owner'],item['filename'],'listed',record['id'],evidence=receipt);save_receipt(ops,out,value['job_id'],item,receipt)
                try:
                    api.set_designer(record,name);receipt['designer_write']['phase']='ACK';changed=True
                except Exception as exc:
                    receipt['designer_write']['phase']='UNKNOWN';receipt['designer_write']['error']=error_code(exc)
                    ledger.update(old['owner'],item['filename'],'listed',record['id'],evidence=receipt);save_receipt(ops,out,value['job_id'],item,receipt);raise
                after=api.detail_snapshot(record)
            else:after=before
            expected={**before['fields'],'设计师':name}
            if after['record']!=record or after['fields']!=expected or after['media']!=before['media']:raise ValueError('DESIGNER_READBACK_OR_OTHER_FIELDS_CHANGED')
            receipt['designer_write']={**receipt.get('designer_write',{}),'phase':'VERIFIED','expected':name,'record_id':record['id'],'after':after,'other_fields_unchanged':True,'media_unchanged':True,'verified_at':time.time()}
            receipt['designer_intent_plan']={'job_id':value['job_id'],'sha256':digest}
            if alias:receipt['verified_native_identity']={**alias,'verified_at':time.time()}
            receipt['detail_fields']=after['fields'];receipt['detail_readback_verified']=True;receipt['attribution_schema']=2
            receipt['attribution_acceptance']=detail_acceptance(after['fields'],item['parameters'],name,options)
            receipt['metadata_verified']=receipt['attribution_acceptance']['verified'];receipt.pop('detail_error',None)
            ledger.update(old['owner'],item['filename'],'listed',record['id'],evidence=receipt);save_receipt(ops,out,value['job_id'],item,receipt)
            results.append({'filename':item['filename'],'record_id':record['id'],'designer':name,'changed':changed,'metadata_verified':receipt['metadata_verified']})
    return {'ok':all(x['metadata_verified'] for x in results),'items':results,'job_id':value['job_id'],'upload_performed':False,'automatic_retry':False}

def correct_metadata(api,args,out):
    """Keep the mutation entrypoint in the original registered service module."""
    verify_source();ops=operations();plan=ops.registered_plan(args['job_id'])
    runtime=ops.load_runtime(args['workspace'])
    with runtime.mutation('material_upload',ops.UPLOAD_SCOPE,authorization_ticket=args['authorization_ticket'],input_sha256=ops.plan_digest(plan)):
        from metadata_correction import correct_metadata as execute
        return execute(api,args,out)


SESSION_CHECK_INTERVAL = 15 * 60


def refresh_session(api, now=None):
    """Bounded protected GET, also while the production queue is empty."""
    now = time.time() if now is None else now
    state = api.engine.state
    if state.get('status') != 'ready':
        raise ValueError('UPLOAD_HTTP_LOGIN_REQUIRED')
    checked = state.get('last_protected_read_at') or 0
    portal_checked = state.get('last_portal_session_read_at') or 0
    if any(value > now or now - value >= SESSION_CHECK_INTERVAL for value in (checked, portal_checked)):
        api.bind_ad()  # Keep the original portal alive for later detail SSO too.
        state['last_portal_session_read_at'] = now
        api.fields()  # Verify the native protected upload form.
        from session_store import remember
        remember(api.engine, 'upload')


def serve_upload_engine(engine,output_dir,session_id,lifetime=86400):
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(BASE,0o700)
    sock=BASE/(session_id+'.sock');meta=BASE/(session_id+'.json');out=Path(output_dir);api=Api(engine)
    stop=threading.Event();lock=threading.Lock()
    def dispatch(r):
        cmd=r.get('command')
        if cmd=='status':
            version=verify_source()
            with lock:refresh_session(api)
            return {'ok':True,'session_id':session_id,**engine.status(),'service_kind':'http_upload','uploader_version':version}
        if cmd=='stop':stop.set();return {'ok':True,'stopping':True}
        verify_source()
        with lock:
            if cmd=='probe':return api.fields(r.get('gid'),r.get('source_type'),probe=True)
            if cmd=='fields':return api.fields(r.get('gid'),r.get('source_type'))
            if cmd=='prefix':return api.prefix(r['prefix'])
            if cmd=='lookup':return {'ok':True,'record':api.lookup(r['name'])}
            if cmd=='submit':return submit(api,r,out)
            if cmd=='reconcile':return reconcile(api,r['job_id'],out,r.get('refresh_details',False))
            if cmd=='finalize-attribution':return finalize_attribution(api,r,out)
            if cmd=='correct-metadata':return correct_metadata(api,r,out)
            if cmd=='detail':
                record=api.lookup(r['name'])
                if not record or record['id']!=r['record_id']:raise ValueError('DETAIL_IDENTITY_MISMATCH')
                return {'ok':True,**api.detail_snapshot(record),'remote_writes_performed':False}
        raise ValueError('INVALID_UPLOAD_COMMAND')
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                line=self.rfile.readline(16385)
                if len(line)>16384:raise ValueError('RPC_REQUEST_TOO_LARGE')
                request=json.loads(line)
                result=dispatch(request)
                if request.get('command') not in ('status','stop','probe') and result.get('ok'):
                    from session_store import remember
                    with lock:remember(engine,'upload')
            except Exception as e:
                message=str(e);result={'ok':False,'error':message if re.fullmatch('[A-Z0-9_]+',message) else type(e).__name__,'browser_started':False,'automatic_retry':False}
            self.wfile.write((json.dumps(result,ensure_ascii=False)+'\n').encode())
    server=socketserver.ThreadingUnixStreamServer(str(sock),Handler);server.timeout=.5;server.daemon_threads=True;os.chmod(sock,0o600)
    meta.write_text(json.dumps({'session_id':session_id,'pid':os.getpid(),'socket':str(sock),'service_kind':'http_upload','created_at':time.time(),'cookies_persisted':engine.state.get('cookies_persisted',False)}));meta.chmod(0o600)
    deadline=time.monotonic()+lifetime
    try:
        while not stop.is_set() and time.monotonic()<deadline:server.handle_request()
    finally:server.server_close();sock.unlink(missing_ok=True);meta.unlink(missing_ok=True)
