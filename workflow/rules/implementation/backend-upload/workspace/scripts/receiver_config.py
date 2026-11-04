"""Recipient-owned configuration. This module never reads an author's home/login."""
import json,re,socket
from pathlib import Path
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
def load(required=False):
 p=ROOT/'receiver.local.json'
 if not p.is_file():
  if required:raise ValueError('RECEIVER_CONFIG_REQUIRED: copy receiver.example.json and configure your own workspace')
  return {}
 d=json.loads(p.read_text())
 if d.get('schema_version')!=1:raise ValueError('RECEIVER_CONFIG_SCHEMA')
 return d
def validate(d,production=False):
 if d.get('schema_version')!=1:raise ValueError('RECEIVER_CONFIG_SCHEMA')
 forbidden={'token','password','cookie','secret','authorization','app_secret','access_token'}
 def walk(v):
  if isinstance(v,dict):
   for k,x in v.items():
    if k.lower() in forbidden:raise ValueError('STORE_SECRETS_IN_SERVICE_LOGIN_ONLY')
    walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 walk(d)
 if d.get('backend') not in ('dreamina', 'rongyao',None):raise ValueError('UNKNOWN_BACKEND')
 missing=[k for k in ('writer_host','rules_center','feishu_origin','account_label') if not d.get(k)]
 if d.get('rules_center') and not re.fullmatch(r'[A-Za-z0-9_-]+',d['rules_center']):raise ValueError('RULE_CENTER_MUST_BE_DOCUMENT_ID')
 if d.get('feishu_origin'):
  u=urlparse(d['feishu_origin'])
  if u.scheme!='https' or u.username or u.password or u.path not in ('','/') or not u.hostname or not u.hostname.endswith(('.feishu.cn','.larksuite.com')):raise ValueError('INVALID_FEISHU_ORIGIN')
 if production and missing:raise ValueError('RECEIVER_CONFIG_INCOMPLETE: '+', '.join(missing))
 return {'valid':True,'production_fields_missing':missing,'account_verified':False,'production_authorized':False}
def skills_root():
 # Distributed sources are immutable relative to this workspace; installed copies are separate.
 return ROOT/'skills'
def configured_origin(url):
 origin=load(True).get('feishu_origin')
 if not origin:raise ValueError('FEISHU_ORIGIN_REQUIRED')
 return url.startswith(origin.rstrip('/')+'/')

def security_digest(config):
 import hashlib
 keys=('writer_host','rules_center','feishu_origin','account_label','backend','dreamina_cli','backend_hosts')
 value={key:config.get(key) for key in keys}
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
