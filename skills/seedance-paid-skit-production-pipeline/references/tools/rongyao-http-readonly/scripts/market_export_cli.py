#!/usr/bin/env python3
"""Material-performance compatible export via the existing HTTP service."""
import argparse,json,subprocess,sys
from pathlib import Path
from rongyao_http import rpc

def ensure_market_session(output_dir):
    """Validate the report entry, renewing only a positively expired login."""
    try:status=rpc('status')
    except ValueError as exc:
        if str(exc) not in ('NO_RUNNING_HTTP_SESSION','HTTP_SESSION_NOT_RUNNING'):raise
        status={}
    expired=False
    if status.get('status')=='ready':
        probe=rpc('query',status['session_id'],{'_operation':'market-readonly','action':'probe'})
        if probe.get('ok'):return status
        if probe.get('business_query_performed') is not False:
            raise ValueError('MARKET_AUTH_STATE_UNKNOWN_NO_RETRY')
        if probe.get('error')!='MARKET_PORTAL_LOGIN_REQUIRED':
            raise ValueError(probe.get('error') or 'MARKET_ENTRY_UNVERIFIED')
        expired=True
    command=[sys.executable,str(Path(__file__).with_name('rongyao_http.py')),
             'start','--output-dir',str(Path(output_dir).resolve()/'http-auth')]
    if expired:command.append('--new-session')
    result=subprocess.run(command,capture_output=True,text=True,timeout=215)
    if result.returncode:
        # The original login worker persists only non-secret status receipts.
        # Do not relay raw subprocess output or attempt another authentication.
        raise ValueError('HTTP_AUTH_RECOVERY_FAILED')
    status=rpc('status')
    if status.get('status')!='ready':raise ValueError('HTTP_SESSION_NOT_READY_AFTER_AUTH')
    probe=rpc('query',status['session_id'],{'_operation':'market-readonly','action':'probe'})
    if not probe.get('ok'):raise ValueError(probe.get('error') or 'MARKET_ENTRY_UNVERIFIED_AFTER_AUTH')
    return status

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    s.add_parser('status')
    e=s.add_parser('backend-export')
    for name in ('date-range','material-range','gid','output'):e.add_argument('--'+name,required=True)
    e.add_argument('--date-group',choices=['tenyear'],default='tenyear');e.add_argument('--group',choices=['mid'],default='mid');e.add_argument('--format',choices=['json','text'],default='json')
    a=p.parse_args()
    try:
        if a.command=='status':
            result=rpc('status');print(json.dumps(result,ensure_ascii=False));return 0 if result.get('status')=='ready' else 1
        if a.gid!='193':raise ValueError('UNSUPPORTED_MARKET_GID')
        status=ensure_market_session(Path(a.output).resolve().parent)
        params={'_operation':'market-readonly','action':'export','date_range':a.date_range,'material_range':a.material_range,'gid':a.gid,'date_group':a.date_group,'group':a.group,'output':str(Path(a.output).resolve())}
        result=rpc('query',status['session_id'],params=params)
        print(json.dumps(result,ensure_ascii=False));return 0 if result.get('ok') else 1
    except Exception as exc:
        from rongyao_http import safe_error
        print(json.dumps({'ok':False,'error':safe_error(exc),'auto_retry':False,'browser_started':False},ensure_ascii=False));return 1
if __name__=='__main__':sys.exit(main())
