"""Explicit existing-record metadata corrections, independent of upload receipts."""
import hashlib,json,re,time
from pathlib import Path
from attribution import intended_designer,acceptance
ALLOWED={'需求人','第二设计师','角色/标签'}
OPERATION='existing_id_metadata_reconciliation_only'

def equivalent(label,left,right):
    if label=='角色/标签':
        return sorted(left if isinstance(left,list) else [left] if left else [])==sorted(right if isinstance(right,list) else [right] if right else [])
    return left==right

def same_fields(left,right):
    return set(left)==set(right) and all(equivalent(k,left[k],right[k]) for k in left)

def correct_metadata(api,args,out):
    from upload_service import verify_source,operations,error_code
    version=verify_source();ops=operations();plan=ops.registered_plan(args['job_id'])
    # Existing plan registration, actual file bytes and user evidence are required.
    for item in plan['items']:
        if ops.sha256(Path(item['file']))!=item['sha256']:raise ValueError('PLAN_FILE_CHANGED')
        p=item.get('provenance') or {};spec=p.get('metadata_correction') or {}
        if p.get('operation')!=OPERATION or not spec.get('changes') or set(spec['changes'])-ALLOWED:raise ValueError('METADATA_CORRECTION_SCOPE_REQUIRED')
        auth=spec.get('authorization') or {}
        if not auth.get('evidence_file') or ops.sha256(Path(auth['evidence_file']))!=auth.get('sha256'):raise ValueError('METADATA_AUTHORIZATION_CHANGED')
        record=spec.get('record') or {}
        if not re.fullmatch('[1-9][0-9]*',str(record.get('id',''))) or record.get('name')!=item['filename'].removesuffix('.mp4') or not spec.get('media') or not spec.get('before_fields'):raise ValueError('METADATA_IDENTITY_REQUIRED')
        for label,change in spec['changes'].items():
            if set(change)!={'before','after'} or not equivalent(label,change['before'],spec['before_fields'].get(label)):raise ValueError('METADATA_PLAN_BEFORE_MISMATCH')
        expected={**spec['before_fields'],**{k:v['after'] for k,v in spec['changes'].items()}}
        check=acceptance(expected,item['parameters'],intended_designer(item),api.fields().get('selects',{}))
        if not check['verified']:raise ValueError('METADATA_PLAN_INTENT_MISMATCH')
    results=[]
    if ops.registered_plan(plan['job_id'])!=plan:raise ValueError('REGISTERED_PLAN_CHANGED')
    for item in plan['items']:
        spec=item['provenance']['metadata_correction'];record=spec['record']
        key=hashlib.sha256(item['filename'].encode()).hexdigest()[:24]
        path=Path(out)/(plan['job_id']+'-'+key+'-metadata-correction.json')
        receipt=json.loads(path.read_text()) if path.exists() else {'job_id':plan['job_id'],'filename':item['filename'],'record':record,'plan_sha256':ops.plan_digest(plan),'version':version,'writes':{},'upload_performed':False}
        if receipt.get('plan_sha256')!=ops.plan_digest(plan) or receipt.get('record')!=record:raise ValueError('METADATA_CHECKPOINT_MISMATCH')
        if api.lookup(item['filename'])!=record:raise ValueError('METADATA_NATIVE_ID_CHANGED')
        def snapshot():
            live=api.detail_snapshot(record)
            if live['record']!=record or live['media']!=spec['media']:raise ValueError('METADATA_NATIVE_MEDIA_CHANGED')
            for k,v in spec['before_fields'].items():
                if k not in spec['changes'] and not equivalent(k,live['fields'].get(k),v):raise ValueError('METADATA_UNCHANGED_FIELD_DRIFT')
            if set(live['fields'])!=set(spec['before_fields']):raise ValueError('METADATA_FIELD_SET_CHANGED')
            return live
        before=snapshot();receipt['before']=before;ops.save(path,receipt)
        for label,change in spec['changes'].items():
            live=snapshot();actual=live['fields'][label];checkpoint=receipt['writes'].get(label,{})
            if equivalent(label,actual,change['after']):
                receipt['writes'][label]={**checkpoint,'phase':'VERIFIED','after':actual,'readback_at':time.time()};ops.save(path,receipt);continue
            if checkpoint.get('phase') in ('SENDING','ACK','UNKNOWN','VERIFIED'):raise ValueError('METADATA_WRITE_UNKNOWN_READBACK_ONLY')
            if not equivalent(label,actual,change['before']):raise ValueError('METADATA_EXPECTED_BEFORE_CHANGED')
            # Other mutable fields must remain at either the approved before
            # or approved after value; concurrent unapproved changes stop.
            for other,c in spec['changes'].items():
                if not any(equivalent(other,live['fields'].get(other),c[state]) for state in ('before','after')):raise ValueError('METADATA_CONCURRENT_CHANGE')
            receipt['writes'][label]={'phase':'SENDING','before':actual,'intended':change['after'],'at':time.time()};ops.save(path,receipt)
            try:
                api.set_metadata(record,label,change['after']);receipt['writes'][label]['phase']='ACK';ops.save(path,receipt)
                after=snapshot();target={**live['fields'],label:change['after']}
                if not same_fields(after['fields'],target):raise ValueError('METADATA_READBACK_MISMATCH')
                receipt['writes'][label].update(phase='VERIFIED',after=after['fields'][label],readback_at=time.time());ops.save(path,receipt)
            except Exception as exc:
                receipt['writes'][label].update(phase='UNKNOWN',error=error_code(exc));ops.save(path,receipt);raise
        after=snapshot();check=acceptance(after['fields'],item['parameters'],intended_designer(item),api.fields().get('selects',{}))
        if not check['verified']:raise ValueError('METADATA_FINAL_ACCEPTANCE_FAILED')
        receipt.update(after=after,acceptance=check,status='verified',verified_at=time.time());ops.save(path,receipt)
        results.append({'filename':item['filename'],'record_id':record['id'],'metadata_verified':True,'evidence_file':str(path)})
    return {'ok':True,'items':results,'upload_performed':False,'automatic_retry':False}
