#!/usr/bin/env python3
"""Check storyboard revision and frame coverage; never infer visual/audio truth."""
import argparse, hashlib, json, math
from pathlib import Path

FIELDS = ('characters','action','dialogue','camera','sound')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def fingerprint(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def load(p): return json.loads(Path(p).read_text())
def text(x): return isinstance(x,str) and bool(x.strip())
def validate_script(script):
    if script.get('schema')!='storyboard-parity-v1' or not text(script.get('source_ref')) or not text(script.get('revision')):
        raise ValueError('SCRIPT_IDENTITY_REQUIRED')
    shots=script.get('shots',[]);ids=[x.get('id') for x in shots]
    if not shots or any(not text(x) for x in ids) or len(ids)!=len(set(ids)):raise ValueError('SHOT_IDS_REQUIRED_UNIQUE')
    for shot in shots:
        if any(k not in shot or not isinstance(shot[k],str) for k in FIELDS) or not text(shot['action']):raise ValueError('SHOT_CONTENT_REQUIRED')
    return ids
def changes(previous,current):
    a=validate_script(previous);b=validate_script(current)
    before={x['id']:x for x in previous['shots']};after={x['id']:x for x in current['shots']}
    changed=[i for i in b if i in before and before[i]!=after[i]]
    return {'added':[i for i in b if i not in a],'removed':[i for i in a if i not in b], 'changed':changed,'order_changed':[i for i in a if i in b]!=[i for i in b if i in a], 'automatic_regeneration':False,'automatic_sheet_write':False}
def proof(root,entry):
    p=(Path(root)/entry['path']).resolve()
    if not p.is_relative_to(Path(root).resolve()) or not p.is_file() or not p.stat().st_size or sha(p)!=entry.get('sha256'):raise ValueError('STALE_OR_MISSING_PARITY_EVIDENCE')
    return p
def inspect(root,script,review,latest):
    ids=validate_script(script);validate_script(latest)
    if script['source_ref']!=latest['source_ref'] or script['revision']!=latest['revision'] or fingerprint(script['shots'])!=fingerprint(latest['shots']):raise ValueError('STORYBOARD_CHANGED_REVIEW_INVALID')
    if review.get('schema')!='storyboard-review-v1' or review.get('script_sha256')!=fingerprint(script):raise ValueError('REVIEW_SCRIPT_MISMATCH')
    if not text(review.get('observer')) or not text(review.get('observed_at')):raise ValueError('REVIEW_OBSERVER_REQUIRED')
    video=proof(root,review['video']);probe=load(proof(root,review['probe']))
    if probe.get('video_sha256')!=sha(video):raise ValueError('PROBE_VIDEO_MISMATCH')
    frames=probe.get('frames');fps=probe.get('fps')
    if type(frames)!=int or frames<=0 or isinstance(fps,bool) or not isinstance(fps,(float,int)) or not math.isfinite(fps) or fps<=0:raise ValueError('ACTUAL_VIDEO_FRAMES_REQUIRED')
    rows=review.get('shots',[])
    if [x.get('id') for x in rows]!=ids:raise ValueError('MISSING_EXTRA_OR_REORDERED_SHOT')
    cursor=0;pending=[]
    for row,expected in zip(rows,script['shots']):
        first,last=row.get('in_frame'),row.get('out_frame')
        if type(first)!=int or type(last)!=int or first!=cursor or last<=first or last>frames:raise ValueError('FRAME_GAP_OVERLAP_OR_RANGE')
        cursor=last
        if row.get('expected_sha256')!=fingerprint(expected):raise ValueError('SHOT_CHANGED_REVIEW_INVALID')
        proof(root,row['frame_evidence'])
        checks=row.get('checks',{})
        for field in FIELDS:
            c=checks.get(field,{})
            if c.get('status')!='match' or not text(c.get('observation')):pending.append(row['id']+':'+field)
        if row.get('actual_dialogue')!=expected['dialogue']:pending.append(row['id']+':dialogue_text')
    if cursor!=frames:raise ValueError('UNCOVERED_VIDEO_TAIL')
    # B, transitions and title cards must be explicit rows in the delivery script.
    if review.get('complete_audio_reviewed') is not True:pending.append('complete_audio_review')
    return {'ok':True,'coverage_complete':not pending,'missing_or_unverified':pending,'frames':frames,'duration':frames/fps,'script_revision':script['revision'],'video_sha256':sha(video),'semantic_pass_inferred':False,'user_adoption_inferred':False,'side_effects':[]}
def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='cmd',required=True)
    q=s.add_parser('diff');q.add_argument('--previous',required=True);q.add_argument('--current',required=True)
    q=s.add_parser('check');q.add_argument('--root',required=True);q.add_argument('--script',required=True);q.add_argument('--review',required=True);q.add_argument('--latest',required=True)
    a=p.parse_args();r=changes(load(a.previous),load(a.current)) if a.cmd=='diff' else inspect(a.root,load(a.script),load(a.review),load(a.latest))
    print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r.get('coverage_complete') is False else 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError,OSError) as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));raise SystemExit(1)
