#!/usr/bin/env python3
"""Register a receiver-owned existing Sheet locally, without cloud writes."""
import argparse,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--console',type=Path,required=True);p.add_argument('--binding',type=Path,required=True);a=p.parse_args()
 c=json.loads(a.console.read_text());b=json.loads(a.binding.read_text());pid=c.get('project_id')
 if not pid or not re.fullmatch(r'[A-Za-z0-9_-]+',pid):raise ValueError('EXPLICIT_PROJECT_ID_REQUIRED')
 for key in ('name','spreadsheet_token','sheet_id','template_id'):
  if not c.get(key):raise ValueError('CONSOLE_FIELD_REQUIRED: '+key)
 if c['template_id']!='DIRECTOR-STORYBOARD-1' or type(c.get('shot_count')) is not int or c['shot_count']<1:raise ValueError('ACTUAL_DIRECTOR_SHOT_COUNT_REQUIRED')
 if b.get('project_id')!=pid or not b.get('id') or b.get('family') not in ('a','b'):raise ValueError('BINDING_PROJECT_MISMATCH')
 if not b.get('sources'):raise ValueError('LIVE_SHEET_SOURCES_REQUIRED')
 for s in b['sources']:
  for k in ('spreadsheet_token','sheet_id','cell','anchor_cell','anchor_value'):
   if not s.get(k):raise ValueError('SOURCE_FIELD_REQUIRED: '+k)
  if s['spreadsheet_token']!=c['spreadsheet_token'] or s['sheet_id']!=c['sheet_id']:raise ValueError('SOURCE_SHEET_MISMATCH')
 path=ROOT/'workflow/state_bindings.json';db=json.loads(path.read_text()) if path.exists() else {'bindings':[]};dest=ROOT/'projects'/pid/'console.json'
 if dest.exists() or any(x.get('id')==b['id'] or x.get('project_id')==pid for x in db['bindings']):raise ValueError('EXISTING_PROJECT_PRESERVED')
 dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n');db['bindings'].append(b);path.write_text(json.dumps(db,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'ok':True,'project':pid,'live_node_verified':False,'cloud_write_performed':False,'next':'Run scripts/console_content.py check then workflow_node.py context --item with your actual binding.'}))
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,KeyError) as e:print(json.dumps({'ok':False,'error':str(e)}));sys.exit(1)
