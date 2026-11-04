"""Start, query, or stop the installed local Premiere bridge; never update Adobe."""
from pathlib import Path
import argparse, json, os, plistlib, signal, socket, subprocess, sys, time
import bridge

ROOT=Path(__file__).resolve().parent
NODE=ROOT/'tooling/node-v24.21.0-darwin-x64/bin/node'
CLI=ROOT/'tooling/node_modules/@adobe/uxp-devtools-cli/src/uxp.js'
PLUGIN=ROOT/'plugin'
SETTINGS=Path('/Library/Application Support/Adobe/UXP/Developer/settings.json')
APP=Path('/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app')

def available(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=.5):return True
    except OSError:return False

def cli(*args):
    result=subprocess.run([str(NODE),str(CLI),*args],cwd=PLUGIN,text=True,capture_output=True,timeout=40)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return result.stdout

def own_process(pid,needle):
    p=subprocess.run(['ps','-p',str(pid),'-o','command='],text=True,capture_output=True)
    return p.returncode==0 and needle in p.stdout

def recover_inspect(job_id,scope):
    """Reload only the original, unclaimed read-only mailbox; never resubmit."""
    current=bridge.http('/status')
    assert current.get('controller_version')==bridge.VERSION,'CONTROLLER_UPGRADE_REQUIRES_RELEASE_MIGRATION'
    assert current['scope']==str(scope),'Another bridge scope is active'
    transport=current.get('transport',{})
    assert transport.get('mailbox')==str((PLUGIN/'bridge-job.json').resolve()),'INSTALLED_PLUGIN_MAILBOX_MISMATCH'
    job=current['jobs'][job_id]
    assert [j['id'] for j in current['jobs'].values() if bridge.blocking(j)]==[job_id],'OTHER_BLOCKING_JOB_QUERY_FIRST'
    assert not current['plugin_health']['ready'],'PLUGIN_LIVE_QUERY_ORIGINAL_JOB'
    assert SETTINGS.exists() and json.loads(SETTINGS.read_text()).get('developer') is True,'Enable developer mode with owner approval first'
    assert available(14001),'UXP service unavailable; do not change services during recovery'
    assert NODE.is_file() and CLI.is_file(),'Official local toolchain missing; see README'
    with (APP/'Contents/Info.plist').open('rb') as f:version=plistlib.load(f)['CFBundleShortVersionString']
    apps=cli('apps','list');assert 'premierepro' in apps and version in apps,'Current Premiere is not running or developer mode needs a restart'
    bridge.http('/recover-inspect/'+job_id,{})
    # Recheck immediately before load. A claim racing this check is still kept:
    # the plugin itself refuses every claimed ID, so reload never replays it.
    bridge.unclaimed_inspect(job,transport['mailbox'],transport['receipt_dir'])
    cli('plugin','load','--manifest',str(PLUGIN/'manifest.json'),'--apps','premierepro@'+version)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        result=bridge.http('/job/'+job_id)
        if result['status'] in {'native_call_returned','failed'}:
            return {'job':result,'native_inspect_returned':result['status']=='native_call_returned','request_resubmitted':False}
        time.sleep(.25)
    return {'job':bridge.http('/job/'+job_id),'native_inspect_returned':False,'request_resubmitted':False,'next':'Query this same ID; do not retry load if now claimed or receipted.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('start');a.add_argument('--scope',required=True);a.add_argument('--original',required=True)
    a=sub.add_parser('status');a.add_argument('--job');a.add_argument('--detail',action='store_true')
    a=sub.add_parser('stop');a.add_argument('--scope',required=True)
    a=sub.add_parser('recover-inspect');a.add_argument('--scope',required=True);a.add_argument('--job',required=True)
    args=p.parse_args()
    if args.action=='recover-inspect':
        print(json.dumps(recover_inspect(args.job,Path(args.scope).resolve()),ensure_ascii=False,indent=2));return
    if args.action=='status':
        data=bridge.http('/job/'+args.job if args.job else '/status')
        if not args.detail:
            if args.job:
                data={k:data.get(k) for k in ('id','status','error','saved_copy_sha256','original_sha256_observed')}
            else:data={'scope':data['scope'],'plugin_health':data.get('plugin_health',{'ready':False,'reason':'LEGACY_CONTROLLER_HEALTH_UNKNOWN'}),'jobs':{k:j['status'] for k,j in data['jobs'].items()}}
        print(json.dumps(data,ensure_ascii=False,indent=2));return
    if args.action=='stop':
        scope=Path(args.scope).resolve();marker=scope/'controller.json'
        if available(47765):
            current=bridge.http('/status')
            assert current['scope']==str(scope),'Another bridge scope is active'
            assert not any(bridge.blocking(j) for j in current['jobs'].values()),'Active or unknown native job: query it before stopping'
        if (scope/'bridge-jobs').exists():
            assert not any(bridge.blocking(json.loads(p.read_text())) for p in (scope/'bridge-jobs').glob('*.json')),'Persisted active or unknown native job: reconcile before unloading'
        if marker.exists():
            pid=json.loads(marker.read_text())['pid']
            if own_process(pid,'premiere-bridge/bridge.py serve'):os.kill(pid,signal.SIGTERM)
        if available(14001):
            try:cli('plugin','unload')
            except (RuntimeError,subprocess.TimeoutExpired):pass
        own=scope/'developer-service.json'
        if own.exists():
            pid=json.loads(own.read_text())['pid']
            if own_process(pid,'uxp.js service start'):os.kill(pid,signal.SIGTERM)
        print(json.dumps({'stopped':True,'adobe_application_changed':False}));return
    scope=Path(args.scope).resolve();original=Path(args.original).resolve()
    assert original.is_file(),'Original project missing'
    assert NODE.is_file() and CLI.is_file(),'Official local toolchain missing; see README'
    assert SETTINGS.exists() and json.loads(SETTINGS.read_text()).get('developer') is True,'Enable developer mode with owner approval first'
    scope.mkdir(parents=True,exist_ok=True)
    if not available(47765) and (scope/'bridge-jobs').exists():
        prior=[json.loads(p.read_text()) for p in (scope/'bridge-jobs').glob('*.json')]
        assert not any(bridge.blocking(j) for j in prior),'Persisted active or unknown job: start controller only to query/reconcile, do not reload plugin'
    if available(47765):
        state=bridge.http('/status')
        assert state['scope']==str(scope) and state['original_path']==str(original),'Another bridge scope is active; query/stop it first'
        assert state.get('controller_version')==bridge.VERSION,'CONTROLLER_UPGRADE_REQUIRES_RELEASE_MIGRATION'
        assert state.get('transport',{}).get('mailbox')==str((PLUGIN/'bridge-job.json').resolve()),'INSTALLED_PLUGIN_MAILBOX_MISMATCH'
        assert not any(bridge.blocking(j) for j in state['jobs'].values()),'Active or unknown native job: query it before reloading'
    if not available(14001):
        with (scope/'developer-service.log').open('a') as log:
            proc=subprocess.Popen([str(NODE),str(CLI),'service','start','--port','14001'],cwd=PLUGIN,stdout=log,stderr=log,start_new_session=True)
        bridge.write(scope/'developer-service.json',{'pid':proc.pid,'owned_by_this_scope':True})
        for _ in range(40):
            if available(14001):break
            time.sleep(.25)
        assert available(14001),'UXP service did not start; inspect developer-service.log'
    with (APP/'Contents/Info.plist').open('rb') as f:version=plistlib.load(f)['CFBundleShortVersionString']
    apps=cli('apps','list');assert 'premierepro' in apps and version in apps,'Current Premiere is not running or developer mode needs a restart'
    bridge.write(PLUGIN/'bridge-job.json',{})
    cli('plugin','load','--manifest',str(PLUGIN/'manifest.json'),'--apps','premierepro@'+version)
    # UXP writes its own sandbox path; derive this versioned location from the host.
    receipts=Path.home()/f'Library/Application Support/Adobe/UXP/PluginsStorage/PPRO/{version.split(".")[0]}/Developer/com.yue.paidskit.premierebridge/PluginData'
    if not available(47765):
        with (scope/'controller.log').open('a') as log:
            subprocess.Popen([sys.executable,str(ROOT/'bridge.py'),'serve','--scope',str(scope),'--original',str(original),'--mailbox',str(PLUGIN/'bridge-job.json'),'--receipt-dir',str(receipts)],stdout=log,stderr=log,start_new_session=True)
        for _ in range(40):
            if available(47765):break
            time.sleep(.25)
        assert available(47765),'Bridge controller did not start'
    for _ in range(40):
        if bridge.http('/health')['ready']:break
        time.sleep(.25)
    assert bridge.http('/health')['ready'],'Matching live plugin not ready; query status before submitting'
    print(json.dumps({'bridge_version':bridge.VERSION,'ready':True,'host_version':version,'transport':'plugin sandbox files','scope':str(scope),'adobe_update':False},ensure_ascii=False))

if __name__=='__main__':main()
