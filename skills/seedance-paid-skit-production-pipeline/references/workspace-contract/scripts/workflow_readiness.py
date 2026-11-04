"""Bounded parallel preparation checks; never starts a host, login or media job."""
from concurrent.futures import ThreadPoolExecutor
import datetime,json,os,re,subprocess,sys,time
from pathlib import Path

SCHEMA='workflow-readiness-v1'
TIMEOUT_SECONDS=10

def request(root, value, project_id):
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA:
        raise ValueError('READINESS_REQUEST_REQUIRED')
    if set(value)-{'schema','premiere_scope','upload_session','upload_gid','upload_source_type'}:
        raise ValueError('UNKNOWN_READINESS_FIELD')
    result=dict(value)
    if value.get('premiere_scope'):
        if not isinstance(value['premiere_scope'],str):raise ValueError('INVALID_READINESS_SCOPE')
        relative=Path(value['premiere_scope'])
        scope=(root/relative).resolve()
        if relative.is_absolute() or not project_id or not scope.is_relative_to(root/'projects'/project_id):
            raise ValueError('READINESS_SCOPE_OUTSIDE_CURRENT_PROJECT')
        result['premiere_scope']=str(scope)
    for name in ('upload_session','upload_gid','upload_source_type'):
        if value.get(name) is not None and (not isinstance(value[name],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value[name])):
            raise ValueError('INVALID_READINESS_PARAMETER:'+name)
    return result

def check(root, value, project_id):
    root=Path(root).resolve();value=request(root,value,project_id);started=time.monotonic()
    premiere=root/'workflow/tools/premiere-bridge/manage.py'
    upload=root/'workflow/tools/rongyao-http-upload/scripts/rongyao_upload.py'
    probes=[];results={}
    if premiere.is_file():probes.append(('premiere',[sys.executable,str(premiere),'status','--detail']))
    else:results['premiere']={'state':'hold','error':'CURRENT_WORKSPACE_INTERFACE_MISSING'}
    session=value.get('upload_session')
    if not session:results['upload']={'state':'hold','error':'EXPLICIT_EXISTING_SESSION_REQUIRED','automatic_login':False}
    elif not upload.is_file() or "'probe'" not in upload.read_text():
        results['upload']={'state':'hold','error':'CURRENT_WORKSPACE_PROBE_MISSING'}
    else:
        argv=[sys.executable,str(upload),'probe','--session',session]
        for key,flag in [('upload_gid','--gid'),('upload_source_type','--source-type')]:
            if value.get(key):argv.extend([flag,value[key]])
        probes.append(('upload',argv))
    def run(probe):
        name,argv=probe;begin=time.monotonic()
        try:
            done=subprocess.run(argv,cwd=root,capture_output=True,text=True,timeout=TIMEOUT_SECONDS,
                                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
            try:data=json.loads(done.stdout)
            except (ValueError,TypeError):return name,{'state':'hold','error':'INVALID_PROBE_RESPONSE'}
            if done.returncode or data.get('ok') is False:
                code=data.get('error','PROBE_FAILED')
                return name,{'state':'hold','error':code if isinstance(code,str) and re.fullmatch(r'[A-Z0-9_]+',code) else 'PROBE_FAILED'}
            if name=='premiere':
                expected=value.get('premiere_scope');scope=data.get('scope')
                matches=bool(expected and scope==expected)
                jobs=data.get('jobs',{})
                blocking=[key for key,j in jobs.items() if j.get('status') in {'queued','dispatched','accepted','preflight','saving','exporting','unknown','verification_required'} or
                          (j.get('request',{}).get('action')=='export-a' and j.get('request',{}).get('protocol')!=2 and not j.get('reconciliation') and j.get('status') in {'failed','native_call_returned'})]
                result={'state':'checked' if matches and not blocking else 'hold','controller_connected':bool(scope),
                        'current_project_scope_matches':matches,'blocking_job_ids':blocking,
                        'native_host_verified':False,'reuse_controller_without_restart':matches and not blocking,
                        'next_action':'Inspect the actual active project before native changes; status is controller data, not a live plugin handshake.'}
            else:
                valid=data.get('authenticated') is True and data.get('probe_scope')=='form_only' and data.get('dynamic_enums_verified') is False
                result={'state':'checked' if valid else 'hold','authenticated_form_observed':valid,
                        'probe_scope':'form_only','dynamic_enums_verified':False,'automatic_login':False,
                        'selects':data.get('selects',{}) if valid else {},
                        'target_fields_verified':False,'next_action':'Reuse observed form choices for preparation; validate current ownership and requested dynamic enums at the guarded upload step.'}
            result['elapsed_seconds']=round(time.monotonic()-begin,3)
            return name,result
        except subprocess.TimeoutExpired:return name,{'state':'hold','error':'READINESS_TIMEOUT','elapsed_seconds':TIMEOUT_SECONDS}
        except (OSError,ValueError,TypeError,AttributeError):return name,{'state':'hold','error':'READINESS_CHECK_FAILED'}
    if probes:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for name,result in pool.map(run,probes):results[name]=result
    return {'schema':SCHEMA,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'checks':results,'elapsed_seconds':round(time.monotonic()-started,3),'maximum_parallel_probes':2,
            'per_probe_timeout_seconds':TIMEOUT_SECONDS,'gate_pass_inferred':False,'new_authorization_granted':False,
            'login_started':False,'media_job_started':False,'project_or_sheet_written':False,
            'policy':'A failed check holds its dependent action only. Never restart setup, send a job, relogin or switch accounts from this report.'}
