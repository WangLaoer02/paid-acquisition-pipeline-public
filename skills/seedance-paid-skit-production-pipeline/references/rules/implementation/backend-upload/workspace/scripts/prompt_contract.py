#!/usr/bin/env python3
"""Check explicit prompt format and evidence binding; never certifies creative accuracy."""
import argparse,hashlib,json,re
from pathlib import Path
HEADS=['全局视觉风格锁定','角色锁定','场景锁定','分段剧情','全局限制']
FACETS={'actions','composition','camera','rhythm','role_mapping','background_people','sound'}
def text(payload):
    if 'value' in payload:return str(payload['value'])
    return ''.join(str(v.get('text','')) for v in payload.get('rich_text',[]))
def sha_text(value):return hashlib.sha256(value.encode()).hexdigest()
def proof(root,entry):
    if not isinstance(entry,dict) or not entry.get('path') or not entry.get('sha256'):raise ValueError('PROMPT_REVIEW_SOURCE_REQUIRED')
    root=Path(root).resolve();p=(root/entry['path']).resolve()
    if not p.is_relative_to(root) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('PROMPT_REVIEW_SOURCE_CHANGED')
    return p

def check(payload,review,root):
    body=text(payload)
    if not body.strip() or review.get('schema_version')!=1 or review.get('prompt_sha256')!=sha_text(body):raise ValueError('PROMPT_REVIEW_STALE_OR_EMPTY')
    proof(root,review.get('current_user_requirement'))
    if review.get('format')=='five_modules':
        heads=re.findall(r'^##\s+(.+?)\s*$',body,re.M)
        segments=review.get('segments',1)
        if type(segments)!=int or segments<1 or heads!=HEADS*segments:raise ValueError('PROMPT_FIVE_MODULES_REQUIRED')
        for section in re.split(r'^##\s+.+?\s*$',body,flags=re.M)[1:]:
            if not section.strip():raise ValueError('PROMPT_SECTION_EMPTY')
    elif review.get('format')=='user_adopted_compact':
        proof(root,review.get('user_adoption'))
        if review.get('adopted_prompt_sha256')!=sha_text(body):raise ValueError('PROMPT_ADOPTION_DOES_NOT_MATCH')
    else:raise ValueError('PROMPT_CURRENT_FORMAT_REQUIRED')
    mode=review.get('mode')
    if mode=='video_replacement':
        proof(root,review.get('reference_video'));proof(root,review.get('scope_review'))
        facets=review.get('facets',{})
        if set(facets)!=FACETS or any(not isinstance(v,str) or not v.strip() for v in facets.values()):raise ValueError('PROMPT_LOCKED_SCOPE_INCOMPLETE')
        for item in review.get('additions',[]):
            if not item.get('description'):raise ValueError('PROMPT_ADDITION_REQUIRED')
            proof(root,item.get('user_authorization'))
        if review.get('reviewed_prompt_sha256')!=sha_text(body):raise ValueError('PROMPT_SCOPE_REVIEW_STALE')
    elif mode!='original':raise ValueError('PROMPT_MODE_REQUIRED')
    return {'ok':True,'prompt_sha256':sha_text(body),'format':review['format'],'mode':mode,
            'contract_and_source_binding_verified':True,'creative_accuracy_inferred':False,
            'platform_binding_verified':False,'generation_authorized':False}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--payload',required=True);p.add_argument('--review',required=True);p.add_argument('--root',required=True);a=p.parse_args()
    print(json.dumps(check(json.loads(Path(a.payload).read_text()),json.loads(Path(a.review).read_text()),a.root),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
