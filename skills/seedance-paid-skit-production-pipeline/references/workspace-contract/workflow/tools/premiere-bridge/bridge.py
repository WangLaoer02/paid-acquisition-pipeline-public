"""On-demand loopback controller. No arbitrary scripts; no task redelivery."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse, datetime, hashlib, json, os, threading, urllib.request, time, subprocess, math, uuid, fcntl
import xml.etree.ElementTree as ET

PORT=47765
VERSION='0.2.1'
HEALTH_MAX_AGE_MS=6000
BLOCKING={'queued','dispatched','accepted','preflight','saving','exporting','unknown','verification_required'}
def blocking(job):
    return job['status'] in BLOCKING or (job.get('request',{}).get('action')=='export-a' and job.get('request',{}).get('protocol')!=2 and not job.get('reconciliation') and job['status'] in {'failed','native_call_returned'})
ACTIONS={'inspect','snapshot-copy','open-copy','export-a','restore-original'}
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');os.replace(temporary,path)
def http(path,data=None):
    req=urllib.request.Request('http://127.0.0.1:'+str(PORT)+path,
        data=None if data is None else json.dumps(data).encode(),
        headers={'X-Premiere-Bridge':'0.1.0','Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
def plugin_health(receipt_dir, challenge):
    """A cached ready file, a listening controller, or a new mtime is not liveness."""
    result={'ready':False,'reason':'MATCHING_PLUGIN_NOT_READY'}
    try:
        ready=json.loads((Path(receipt_dir)/'bridge-ready.json').read_text())
        if not isinstance(ready,dict):return result
        if ready.get('version')!=VERSION:return result
        result['reason']='PLUGIN_SESSION_NOT_LIVE'
        if ready.get('controller_id')!=challenge['controller_id'] or ready.get('mailbox_path')!=challenge['mailbox_path']:return result
        age=time.time()*1000-ready['heartbeat_at_ms']
        result.update(session_id=ready.get('session_id'),age_ms=round(age),busy=ready.get('busy'))
        if not isinstance(ready.get('session_id'),str) or not ready['session_id'] or ready.get('enabled') is not True or not 0<=age<=HEALTH_MAX_AGE_MS:return result
        result.update(ready=True,reason=None)
    except (OSError,ValueError,TypeError,KeyError,OverflowError):pass
    return result

def unclaimed_inspect(job, mailbox, receipt_dir):
    """Fail closed. Absence of receipt alone is never proof of non-acceptance."""
    assert job['request']['action']=='inspect','ONLY_READONLY_INSPECT_RECOVERABLE'
    assert job['status'] in {'queued','dispatched'},'ONLY_UNACCEPTED_INSPECT_RECOVERABLE'
    assert not any(job.get(k) for k in ('events','result','save_permit','export_permit','native_call_possible')),'INSPECT_HAS_EXECUTION_EVIDENCE'
    receipt_dir=Path(receipt_dir);mailbox=Path(mailbox)
    assert not (receipt_dir/('receipt-'+job['id']+'.json')).exists(),'INSPECT_RECEIPT_EXISTS_QUERY_ONLY'
    # Missing/corrupt claim storage is uncertainty, not an empty claim list.
    claims_path=receipt_dir/'claimed-jobs.json'
    claims=json.loads(claims_path.read_text())
    assert isinstance(claims,list) and all(isinstance(x,str) for x in claims),'INVALID_CLAIM_STORAGE'
    assert job['id'] not in claims,'INSPECT_ALREADY_CLAIMED_QUERY_ONLY'
    content=json.loads(mailbox.read_text()) if mailbox.exists() else {}
    if job['status']=='dispatched':assert content==job['request'],'ORIGINAL_INSPECT_MAILBOX_MISMATCH'
    else:
        # The queued request has never been dispatched. Reload may only see an
        # empty mailbox or a previously claimed ID, never another unclaimed job.
        assert isinstance(content,dict) and (not content or (content.get('id')!=job['id'] and content.get('id') in claims)),'QUEUED_INSPECT_MAILBOX_UNSAFE'
    return {'job_id':job['id'],'observed_at':now(),'claims_sha256':sha(claims_path),'mailbox_sha256':sha(mailbox) if mailbox.exists() else None,'receipt_absent':True,'claimed':False,'dispatch_state':job['status']}

def serve(args):
    scope=Path(args.scope).resolve();original=Path(args.original).resolve()
    scope.mkdir(parents=True,exist_ok=True);records=scope/'bridge-jobs';lock=threading.Lock()
    ownership=(scope/'controller.lock').open('a+')
    fcntl.flock(ownership,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state={'started_at':now(),'controller_version':VERSION,'scope':str(scope),'original_path':str(original),'jobs':{}}
    challenge=None
    if args.mailbox and args.receipt_dir:
        challenge={'controller_id':uuid.uuid4().hex,'mailbox_path':str(Path(args.mailbox).resolve()),'version':VERSION}
        state['transport']={'mailbox':challenge['mailbox_path'],'receipt_dir':str(Path(args.receipt_dir).resolve())}
        write(Path(args.mailbox).parent/'bridge-health-request.json',challenge)
    def health():
        return plugin_health(args.receipt_dir,challenge) if challenge else {'ready':False,'reason':'NO_PLUGIN_TRANSPORT'}
    if records.exists():
        for p in records.glob('*.json'):
            job=json.loads(p.read_text())
            if job.get('request',{}).get('action')=='export-a' and job.get('request',{}).get('protocol')!=2 and not job.get('reconciliation') and job['status'] in {'failed','native_call_returned'}:
                job.update(status='unknown',error='LEGACY_EXPORT_REQUIRES_RECONCILIATION');write(p,job)
            state['jobs'][job['id']]=job
    def valid_path(value):
        p=Path(value).resolve();assert p.is_relative_to(scope),'PATH_OUTSIDE_TEST_SCOPE';return p
    def prepare_parent(value):
        # Create only directories anchored to this scope; never traverse a
        # symlink swapped in after valid_path, or replace an existing file.
        relative=Path(value).relative_to(scope)
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
        directory=os.open(scope,flags)
        try:
            for name in relative.parent.parts:
                try:child=os.open(name,flags,dir_fd=directory)
                except FileNotFoundError:
                    try:os.mkdir(name,dir_fd=directory)
                    except FileExistsError:pass
                    child=os.open(name,flags,dir_fd=directory)
                os.close(directory);directory=child
        finally:os.close(directory)
    def record(job): write(records/(job['id']+'.json'),job)
    def check_inputs(data, phase='save'):
        action=data['action']
        if action=='snapshot-copy':
            assert sha(original)==data['expected_original_sha256'],'ORIGINAL_CHANGED_REFRESH_BEFORE_COPY'
            assert not Path(data['copy_path']).exists(),'COPY_TARGET_EXISTS'
        if action=='open-copy':
            assert sha(data['copy_path'])==data['expected_copy_sha256'],'COPY_CHANGED'
        if action=='export-a':
            assert isinstance(data.get('sequence_guid'),str) and data['sequence_guid'].strip(),'SEQUENCE_GUID_REQUIRED'
            assert sha(data['copy_path'])==data['expected_copy_sha256'],'COPY_CHANGED'
            assert sha(original)==data['expected_original_sha256'],'ORIGINAL_CHANGED'
            assert sha(data['preset_path'])==data['preset_sha256'],'PRESET_CHANGED'
            assert not Path(data['output_path']).exists(),'OUTPUT_EXISTS'
            if phase=='save': assert not Path(data['save_path']).exists(),'SAVE_TARGET_EXISTS'
            else: assert Path(data['save_path']).is_file(),'SAVED_COPY_MISSING'
    def guard(job, phase, nonce):
        assert job['request']['action']!='inspect','READONLY_INSPECT_HAS_NO_WRITE_PERMIT'
        assert job['status'] in {'dispatched','accepted','preflight','saving'},'GUARD_NOT_AVAILABLE'
        assert phase in {'save','export'} and isinstance(nonce,str) and nonce,'BAD_GUARD_REQUEST'
        assert (phase=='save' and not job.get('save_permit')) or (phase=='export' and job.get('save_permit') and not job.get('export_permit')),'GUARD_ALREADY_USED'
        if phase=='export': assert job['request']['action']=='export-a','BAD_EXPORT_GUARD'
        check_inputs(job['request'],phase)
        permit={'id':job['id'],'phase':phase,'nonce':nonce,'ok':True,'expires_at_ms':int(time.time()*1000)+3000}
        job[phase+'_permit']=permit
        job.update(status='saving' if phase=='save' else 'exporting',updated_at=now())
        if phase=='export':job['saved_copy_sha256']=sha(job['request']['save_path'])
        record(job)
        return permit
    def receive(job,data):
        # A persisted permit may already have triggered a native side effect.
        # Late, stale, or legacy failure receipts cannot release that reservation.
        status=data['status']; assert status in BLOCKING|{'native_call_returned','failed'},'BAD_STATUS'
        if job['status'] in {'completed','failed'}: return
        events=data.get('events',[data])
        if job.get('export_permit') or any(e.get('status')=='exporting' for e in events):
            job['native_call_possible']=True
        if status=='failed' and (job.get('save_permit') or job.get('native_call_possible')):status='unknown'
        if status=='native_call_returned' and job['request']['action']=='export-a':status='verification_required'
        if job['status'] in {'unknown','verification_required'} and status not in {'unknown','verification_required'}:return
        job.update(status=status,updated_at=now());job['events']=events
        for key in ('result','error'):
            if key in data:job[key]=data[key]
        if status=='native_call_returned':
            action=job['request']['action'];result=data.get('result',{})
            if action in {'open-copy','snapshot-copy'}:
                path=job['request']['copy_path'];info=result.get('after',result)
                if info.get('project_path')==path:
                    observed=sha(path)
                    if action=='open-copy' and observed!=job['request']['expected_copy_sha256']:
                        job.update(status='unknown',error='COPY_CHANGED_DURING_OPEN')
                    else:state['active_copy']={'path':path,'sha256':observed,'project_guid':info.get('project_guid')}
            elif action=='restore-original':state.pop('active_copy',None)
        record(job)
    def verify(job,evidence=None):
        assert job['status'] in {'unknown','verification_required'},'JOB_NOT_AWAITING_VERIFICATION'
        data=job['request']
        native=(job.get('result') or {}).get('native_call_returned') is True
        if evidence:
            assert evidence.get('job_id')==job['id'] and evidence.get('native_terminal_confirmed') is True,'NATIVE_TERMINAL_EVIDENCE_REQUIRED'
            assert evidence.get('observer') and evidence.get('observation'),'TERMINAL_OBSERVATION_REQUIRED'
            evidence_path=Path(evidence['evidence_path']).resolve()
            assert evidence_path.is_file() and sha(evidence_path)==evidence['evidence_sha256'],'TERMINAL_EVIDENCE_CHANGED'
            assert evidence.get('outcome') in {'completed','failed'},'TERMINAL_OUTCOME_REQUIRED'
        else:assert native and job['status']=='verification_required','UNKNOWN_QUERY_OR_NATIVE_TERMINAL_EVIDENCE_REQUIRED'
        if data['action']!='export-a':
            assert evidence,'NATIVE_TERMINAL_EVIDENCE_REQUIRED'
            if data['action']=='snapshot-copy':
                assert sha(original)==data['expected_original_sha256'],'ORIGINAL_CHANGED'
                if evidence['outcome']=='completed':assert Path(data['copy_path']).is_file(),'COPY_MISSING'
            job.update(status=evidence['outcome'],reconciliation=evidence,updated_at=now());record(job);return job
        for path,key in [('copy_path','expected_copy_sha256'),('original_path','expected_original_sha256')]:
            assert sha(data[path])==data[key],'PROTECTED_PROJECT_CHANGED'
        if evidence and evidence['outcome']=='failed':
            assert not Path(data['output_path']).exists(),'OUTPUT_EXISTS_REVIEW_BEFORE_FAILED'
            job.update(status='failed',reconciliation=evidence,updated_at=now());record(job);return job
        output=Path(data['output_path']);assert output.is_file() and output.stat().st_size,'OUTPUT_MISSING'
        assert sha(data['save_path'])==job['saved_copy_sha256'],'SAVED_COPY_CHANGED'
        before=sha(output)
        probe=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)],capture_output=True,text=True,timeout=30)
        assert probe.returncode==0,'FFPROBE_FAILED'
        meta=json.loads(probe.stdout);types={x['codec_type'] for x in meta['streams']}
        assert {'audio','video'}<=types,'AUDIO_VIDEO_REQUIRED'
        assert abs(float(meta['format']['duration'])-(data['out_seconds']-data['in_seconds']))<0.15,'OUTPUT_DURATION_MISMATCH'
        result=subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'],capture_output=True,text=True,timeout=300)
        assert result.returncode==0 and not result.stderr.strip(),'DECODE_FAILED'
        assert sha(output)==before,'OUTPUT_STILL_CHANGING'
        job.update(status='completed',output_sha256=before,technical_verification=meta,reconciliation=evidence,updated_at=now(),content_acceptance=False)
        record(job);return job
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*ignored):pass
        def answer(self,d,status=200):
            raw=json.dumps(d,ensure_ascii=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
        def allowed(self):
            origin=self.headers.get('Origin')
            return self.headers.get('X-Premiere-Bridge')=='0.1.0' and (not origin or origin=='null' or origin.startswith('uxp://'))
        def do_GET(self):
            if not self.allowed():return self.answer({'error':'LOCAL_CLIENT_REQUIRED'},403)
            with lock:
                if self.path=='/status':return self.answer({**state,'plugin_health':health()})
                if self.path=='/health':return self.answer(health())
                if self.path=='/next':
                    if args.mailbox:return self.answer({'error':'MAILBOX_TRANSPORT_ONLY'},409)
                    for job in state['jobs'].values():
                        if job['status']=='queued':
                            job.update(status='dispatched',dispatched_at=now());record(job)
                            return self.answer({'job':job['request']})
                    return self.answer({'job':None})
                if self.path.startswith('/job/'):
                    job=state['jobs'].get(self.path[5:]);return self.answer(job or {'error':'NO_JOB'},200 if job else 404)
            self.answer({'error':'NOT_FOUND'},404)
        def do_POST(self):
            if not self.allowed():return self.answer({'error':'LOCAL_CLIENT_REQUIRED'},403)
            try:
                length=int(self.headers.get('Content-Length','0'));assert 0<length<1000000
                data=json.loads(self.rfile.read(length))
                with lock:
                    if self.path=='/submit':
                        data['protocol']=2;data['bridge_version']=VERSION
                        jid=data['id'];assert isinstance(jid,str) and jid.replace('-','').replace('_','').isalnum(),'BAD_JOB_ID'
                        if jid in state['jobs']:return self.answer({'error':'EXISTING_JOB_QUERY_ONLY','job':state['jobs'][jid]},409)
                        if args.receipt_dir:
                            live=health();assert live['ready'],live['reason']
                        assert data['action'] in ACTIONS,'ACTION_NOT_ALLOWED'
                        data['original_path']=str(original)
                        if data['action']!='inspect':
                            data['copy_path']=str(valid_path(data['copy_path']));assert data['copy_path']!=str(original)
                        if data['action']=='open-copy':data['expected_copy_sha256']=sha(data['copy_path'])
                        if data['action']=='snapshot-copy':
                            assert sha(original)==data['expected_original_sha256'],'ORIGINAL_CHANGED_REFRESH_BEFORE_COPY'
                            assert not Path(data['copy_path']).exists(),'COPY_TARGET_EXISTS'
                        if data['action']=='export-a':
                            assert isinstance(data.get('sequence_guid'),str) and data['sequence_guid'].strip(),'SEQUENCE_GUID_REQUIRED'
                            binding=state.get('active_copy',{})
                            assert binding.get('path')==data['copy_path'] and binding.get('sha256')==data['expected_copy_sha256'],'FRESH_COPY_OPEN_OR_SNAPSHOT_REQUIRED'
                            assert binding.get('project_guid'),'PROJECT_GUID_REQUIRED'
                            data['project_guid']=binding['project_guid']
                            data['expected_original_sha256']=sha(original)
                            data['save_path']=str(scope/('export-copy-'+jid+'-'+uuid.uuid4().hex+'.prproj'))
                            assert sha(data['copy_path'])==data['expected_copy_sha256'],'COPY_CHANGED'
                            data['output_path']=str(valid_path(data['output_path']));assert not Path(data['output_path']).exists(),'OUTPUT_EXISTS'
                            assert all(isinstance(data.get(k),(int,float)) and math.isfinite(data[k]) for k in ['out_seconds','in_seconds']),'FINITE_RANGE_REQUIRED'
                            assert data['out_seconds']>data['in_seconds']>=0
                            assert data.get('preset_path') and not data.get('use_applied_settings'),'EXPLICIT_VALIDATED_EPR_REQUIRED'
                            assert sha(data['preset_path'])==data['preset_sha256'],'PRESET_CHANGED'
                            preset=ET.parse(data['preset_path']).getroot()
                            assert preset.find('AMEPreset') is None and preset.find('ExportParamContainer') is not None,'PROJECT_BLOB_IS_NOT_AN_EPR'
                            assert preset.findtext('DoAudio')=='true' and preset.findtext('DoVideo')=='true','AUDIO_VIDEO_REQUIRED'
                            if data.get('require_captions',True):
                                assert preset.find('CaptionParamContainer') is not None and preset.findtext('DoCaptions')=='true','CURRENT_CAPTION_SCHEMA_REQUIRED'
                                params={n.findtext('ParamIdentifier'):n.findtext('ParamValue') for n in preset.iter('ExporterParam')}
                                assert params.get('ADBECaptionExportOption')=='2','BURN_IN_CAPTIONS_REQUIRED'
                        assert not any(blocking(j) for j in state['jobs'].values()),'ANOTHER_JOB_ACTIVE_QUERY_FIRST'
                        if data['action']=='snapshot-copy':prepare_parent(data['copy_path'])
                        elif data['action']=='export-a':prepare_parent(data['output_path'])
                        job={'id':jid,'status':'queued','created_at':now(),'request':data,'events':[]}
                        state['jobs'][jid]=job;record(job);return self.answer({'id':jid,'status':'queued'})
                    if self.path.startswith('/guard/'):
                        job=state['jobs'][self.path[7:]];return self.answer(guard(job,data['phase'],data['nonce']))
                    if self.path.startswith('/recover-inspect/'):
                        assert challenge,'PLUGIN_TRANSPORT_REQUIRED'
                        job=state['jobs'][self.path[17:]]
                        assert [j['id'] for j in state['jobs'].values() if blocking(j)]==[job['id']],'OTHER_BLOCKING_JOB_QUERY_FIRST'
                        assert not health()['ready'],'PLUGIN_LIVE_QUERY_ORIGINAL_JOB'
                        evidence=unclaimed_inspect(job,args.mailbox,args.receipt_dir)
                        job.setdefault('recovery_checks',[]).append(evidence);record(job)
                        return self.answer({'job_id':job['id'],'status':job['status'],'evidence':evidence,'request_unchanged':True})
                    if self.path.startswith('/verify/'):
                        job=state['jobs'][self.path[8:]];return self.answer(verify(job,data.get('evidence')))
                    if self.path.startswith('/result/'):
                        job=state['jobs'][self.path[8:]];receive(job,data);return self.answer({'ok':True})
            except Exception as error:return self.answer({'error':str(error)},400)
            self.answer({'error':'NOT_FOUND'},404)
    if args.mailbox and args.receipt_dir:
        mailbox=Path(args.mailbox).resolve();receipt_dir=Path(args.receipt_dir).resolve()
        def mailbox_worker():
            while True:
                with lock:
                    active=[j for j in state['jobs'].values() if blocking(j) and j['status']!='queued']
                    for job in active:
                        receipt=receipt_dir/('receipt-'+job['id']+'.json')
                        if receipt.exists():
                            try:
                                incoming=json.loads(receipt.read_text())
                                if incoming.get('id')==job['id']:
                                    if incoming.get('status')=='preflight':
                                        event=incoming['events'][-1];phase,nonce=event['phase'],event['nonce']
                                        permit_path=mailbox.parent/('permit-'+job['id']+'-'+phase+'.json')
                                        if not permit_path.exists():
                                            try: permit=guard(job,phase,nonce)
                                            except Exception as error:
                                                permit={'id':job['id'],'phase':phase,'nonce':nonce,'ok':False,'error':str(error)}
                                            write(permit_path,permit)
                                    else:receive(job,incoming)
                            except (ValueError,OSError): pass
                    if not any(blocking(j) and j['status']!='queued' for j in state['jobs'].values()):
                        for job in state['jobs'].values():
                            if job['status']=='queued' and health()['ready']:
                                job.update(status='dispatched',dispatched_at=now());record(job)
                                write(mailbox,job['request']);break
                time.sleep(0.5)
        threading.Thread(target=mailbox_worker,daemon=True).start()
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    write(scope/'controller.json',{'pid':os.getpid(),'port':PORT,'scope':str(scope),'started_at':now(),'bind':'127.0.0.1'})
    print(json.dumps({'ready':True,'port':PORT,'scope':str(scope)}),flush=True)
    server.serve_forever()
def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('serve');p.add_argument('--scope',required=True);p.add_argument('--original',required=True);p.add_argument('--mailbox');p.add_argument('--receipt-dir')
    p=sub.add_parser('submit');p.add_argument('--request',required=True)
    p=sub.add_parser('verify');p.add_argument('--job',required=True);p.add_argument('--terminal-evidence')
    p=sub.add_parser('status');p.add_argument('--job')
    args=parser.parse_args()
    if args.command=='serve':serve(args)
    elif args.command=='verify':print(json.dumps(http('/verify/'+args.job,{'evidence':json.loads(Path(args.terminal_evidence).read_text()) if args.terminal_evidence else None}),ensure_ascii=False,indent=2))
    elif args.command=='submit':print(json.dumps(http('/submit',json.loads(Path(args.request).read_text())),ensure_ascii=False))
    else:print(json.dumps(http('/job/'+args.job if args.job else '/status'),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
