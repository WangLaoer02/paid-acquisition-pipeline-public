#!/usr/bin/env python3
"""Safely replace one Feishu paragraph by a fresh text anchor; never reuse a stale block id."""
import argparse,html,hashlib,json,re,subprocess,sys
def cli(args):
    r=subprocess.run(['lark-cli',*args,'--as','user'],capture_output=True,text=True,timeout=55);d=json.loads(r.stdout or r.stderr)
    if r.returncode or not d.get('ok'):raise ValueError(str(d.get('error') or d))
    return d['data']
def paras(c):
    return [(m.group(1),html.unescape(re.sub(r'<[^>]+>','',m.group(2)))) for m in re.finditer(r'<p id="([^"]+)">(.*?)</p>',c,re.S)]
def main():
    p=argparse.ArgumentParser();p.add_argument('--doc',required=True);p.add_argument('--starts-with',required=True);p.add_argument('--content-xml',required=True);p.add_argument('--expected-old-sha256',required=True);a=p.parse_args()
    before=cli(['docs','+fetch','--doc',a.doc,'--detail','with-ids'])['document'];m=[x for x in paras(before['content']) if x[1].startswith(a.starts_with)]
    if len(m)!=1:raise ValueError('ANCHOR_NOT_UNIQUE')
    bid,old=m[0]
    if hashlib.sha256(old.encode()).hexdigest()!=a.expected_old_sha256:raise ValueError('ANCHOR_CHANGED')
    cli(['docs','+update','--doc',a.doc,'--command','block_replace','--block-id',bid,'--content',a.content_xml,'--revision-id',str(before['revision_id'])])
    after=cli(['docs','+fetch','--doc',a.doc,'--detail','with-ids'])['document'];expected=html.unescape(re.sub(r'<[^>]+>','',a.content_xml));m2=[x for x in paras(after['content']) if x[1]==expected]
    if len(m2)!=1:raise ValueError('READBACK_MISMATCH')
    print(json.dumps({'ok':True,'before_revision':before['revision_id'],'after_revision':after['revision_id'],'new_block_id':m2[0][0]},ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,subprocess.SubprocessError) as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr);raise SystemExit(1)
