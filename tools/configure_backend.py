#!/usr/bin/env python3
"""Prepare a new receiver-owned enterprise endpoint build. No network/auth/submission."""
from pathlib import Path
import argparse,json,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import public_release

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--release-id',required=True);a=p.parse_args()
 cfg=json.loads(a.config.read_text());mapping=cfg.get('backend_hosts',{})
 # Inventory literal placeholders in active source, do not accept arbitrary replacement strings.
 hosts=set()
 for path in ROOT.rglob('*'):
  if path.is_file() and path.suffix not in ('.zip','.pyc'):
   hosts.update(re.findall(r'(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9_-]+\.)*backend\.example\.invalid',path.read_text(errors='ignore')))
 if set(mapping)!=hosts:raise ValueError('EXACT_BACKEND_HOST_MAP_REQUIRED: '+', '.join(sorted(hosts)))
 for dest in mapping.values():
  if not isinstance(dest,str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',dest) or dest.endswith('.invalid'):raise ValueError('VALID_RECEIVER_HOSTNAME_REQUIRED')
 public_release.init(a)
 target=a.workspace.expanduser().resolve()
 for path in target.rglob('*'):
  if not path.is_file() or path.suffix in ('.zip','.pyc') or path.name=='receiver.local.json':continue
  text=path.read_text()
  for source,dest in sorted(mapping.items(),key=lambda x:-len(x[0])):text=text.replace(source,dest)
  path.write_text(text)
 result=subprocess.run([sys.executable,str(target/'tools/rebuild_release.py'),'--release-id',a.release_id],cwd=target)
 if result.returncode:raise ValueError('RECIPIENT_BUILD_FAILED')
 print(json.dumps({'ok':True,'network_called':False,'published':False,'next':'Review the derived source and run checks before publishing its marker to your own center. Endpoint configuration does not confer service access.'}))
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,KeyError) as e:print(json.dumps({'ok':False,'error':str(e)}));sys.exit(1)
