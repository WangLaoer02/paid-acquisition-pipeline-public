#!/usr/bin/env python3
"""Verify production-order evidence. Integrity is not a substitute for human review."""
import argparse, concurrent.futures, hashlib, json, math, os, re, shutil, subprocess, tempfile, time, uuid
from fractions import Fraction
from pathlib import Path

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path): return json.loads(Path(path).read_text())
def proof(root, ref):
    if not isinstance(ref,dict) or not isinstance(ref.get('path'),str): raise ValueError('EVIDENCE_REQUIRED')
    p=(Path(root)/ref['path']).resolve()
    if not p.is_relative_to(Path(root).resolve()) or not p.is_file() or not p.stat().st_size or sha(p)!=ref.get('sha256'): raise ValueError('STALE_PRODUCTION_EVIDENCE')
    return p
def director(root, record):
    if record.get('schema')!='production-director-v1' or record.get('purpose')!='preproduction' or record.get('scope')!='A_only': raise ValueError('PREPRODUCTION_DIRECTOR_REQUIRED')
    if not record.get('source_ref') or not record.get('revision'): raise ValueError('DIRECTOR_SOURCE_REQUIRED')
    if record.get('final_video') or record.get('actual_video_frames'): raise ValueError('DELIVERY_IN_PREPRODUCTION')
    if record.get('history_status') not in ('before_generation','correction_after_generation'): raise ValueError('DIRECTOR_PROVENANCE_REQUIRED')
    shots=record.get('shots',[]);ids=[s.get('id') for s in shots]
    if not shots or any(not isinstance(i,str) or not i for i in ids) or len(ids)!=len(set(ids)):raise ValueError('SHOT_IDS_REQUIRED')
    total=0
    for s in shots:
        if s.get('segment')!='A':raise ValueError('B_NOT_GENERATION_STORYBOARD')
        for field in ('action','dialogue','original_copy','camera','sound','composition'):
            if not isinstance(s.get(field),str):raise ValueError('DIRECTOR_FIELD_REQUIRED:'+field)
        if not s['action'].strip() or not s['composition'].strip():raise ValueError('ACTION_AND_COMPOSITION_REQUIRED')
        seconds=s.get('planned_seconds')
        if type(seconds) not in (int,float) or not 0<seconds<3600:raise ValueError('PLANNED_DURATION_REQUIRED')
        total+=seconds
        for img in s.get('images',[]):
            if img.get('role') not in ('source_reference','design'):raise ValueError('FINISHED_FRAME_IN_DIRECTOR')
            proof(root,img)
    b=record.get('b_plan',{})
    if b and (b.get('mode')!='reuse_existing' or b.get('generate') is not False):raise ValueError('B_MUST_REUSE')
    reserve=b.get('reserved_seconds',0)
    if type(reserve) not in (int,float) or reserve<0:raise ValueError('B_RESERVATION_REQUIRED')
    if not record.get('duration_override_source') and not 10<=total+reserve<=25:raise ValueError('FINAL_DURATION_OUT_OF_DEFAULT_RANGE')
    return {'ok':True,'shots':len(shots),'planned_final_seconds':total+reserve,'semantic_pass_inferred':False}

def console_operations(root, record, config):
    """Compile a current director into one sparse named-slot batch. Local only.

    This does not read the Sheet, clear unknown fields, mount images, change a
    stage or authorize a write. console_content check/patch remains mandatory.
    """
    import console_template as template
    import console_content as content
    director(root,record)
    if not config.get('project_id') or record.get('project_id')!=config['project_id']:
        raise ValueError('DIRECTOR_PROJECT_MISMATCH')
    contract=template.contract_for(config)
    if contract['template_id']!=template.DIRECTOR_ID:
        raise ValueError('DIRECTOR_TEMPLATE_REQUIRED')
    shots=record['shots']
    expected_ids=config.get('shot_ids') if config.get('layout_profile')=='receiver-compact-2' else [f'SC-{i+1:02}' for i in range(config['shot_count'])]
    if [shot['id'] for shot in shots]!=expected_ids:
        raise ValueError('DIRECTOR_SHOT_MAPPING_MISMATCH: preserve current rows and manual edits')
    operations=[]
    for index,shot in enumerate(shots):
        values={'script':shot['composition']+'\n'+shot['action'],
                'dialogue':shot['dialogue'],'original_copy':shot['original_copy'],
                'camera':shot['camera'],'sound':shot['sound'],
                'duration':format(shot['planned_seconds'],'g')+'秒'}
        if 'shot_scale' in shot:values['shot_scale']=shot['shot_scale']
        for slot,value in values.items():
            if value is None:continue  # Unknown remains absent, never a clearing operation.
            if not isinstance(value,str):raise ValueError('DIRECTOR_FIELD_REQUIRED:'+slot)
            if not value.strip():continue
            payload={'value':value}
            content.preflight(slot,payload)
            template.plan_patch(contract,slot,index,{},payload)
            operations.append({'slot':slot,'index':index,'payload':payload})
    template.batch_targets(contract,operations)
    return operations

POST_ITEMS=('rhythm','subtitles','audio_sources','mix','packaging')
def postproduction(root, record):
    if record.get('schema')!='pr-postproduction-v1':raise ValueError('PR_POSTPRODUCTION_REQUIRED')
    script=load(proof(root,record.get('director')));director(root,script)
    proof(root,record.get('project'));proof(root,record.get('a_video'))
    native=load(proof(root,record.get('native_export')))
    if native.get('output_sha256')!=record['a_video']['sha256'] or native.get('saved_copy_sha256')!=record['project']['sha256']:raise ValueError('NATIVE_EXPORT_BINDING_MISMATCH')
    result=native.get('result',{})
    if result.get('native_call_returned') is not True or result.get('export_backend') not in ('Premiere UXP IMMEDIATELY','Premiere native UI'):raise ValueError('NATIVE_EXPORT_NOT_VERIFIED')
    if result.get('export_backend')=='Premiere native UI':proof(root,record.get('native_ui_evidence'))
    checks=record.get('checks',{})
    for name in POST_ITEMS:
        c=checks.get(name,{})
        if c.get('status') not in ('done','not_required') or not c.get('observation'):raise ValueError('POSTPRODUCTION_INCOMPLETE:'+name)
        proof(root,c.get('evidence'))
        if c['status']=='not_required' and not c.get('requirement_source'):raise ValueError('EXCEPTION_SOURCE_REQUIRED:'+name)
    return {'ok':True,'a_sha256':record['a_video']['sha256'],'semantic_pass_inferred':False}

def join_ready(root, record, *, candidate=False):
    if record.get('schema')!='b-join-input-v1':raise ValueError('JOIN_INPUT_REQUIRED')
    post=load(proof(root,record.get('postproduction')));postproduction(root,post)
    a=record.get('a_video');proof(root,a)
    if a['sha256']!=post['a_video']['sha256']:raise ValueError('A_CHANGED_AFTER_POSTPRODUCTION')
    acceptance=load(proof(root,record.get('a_acceptance')))
    if acceptance.get('schema')!='a-acceptance-v1' or acceptance.get('a_sha256')!=a['sha256'] or acceptance.get('postproduction_sha256')!=record['postproduction']['sha256']:raise ValueError('A_ACCEPTANCE_BINDING_MISMATCH')
    # A preview may defer listening to the single final A+B review. The existing
    # postproduction check still requires audio-source and mix evidence.
    audio_pending=candidate and acceptance.get('complete_audio',{}).get('status') in ('pending','not_reviewed')
    required_reviews=('visual',) if audio_pending else ('visual','complete_audio')
    if not candidate:required_reviews+=('user_adoption',)
    for name in required_reviews:
        check=acceptance.get(name,{})
        if check.get('status')!='pass' or not check.get('reviewer') or not check.get('observed_at'):raise ValueError('A_NOT_ACCEPTED:'+name)
        proof(root,check.get('evidence'))
    if candidate and acceptance.get('user_adoption',{}).get('status') not in (None,'pending','not_reviewed','pass'):
        raise ValueError('A_USER_REJECTION_REQUIRES_REWORK')
    proof(root,record.get('b_source'))
    if record.get('b_mode')!='reuse_existing' or record.get('b_generate') is not False:raise ValueError('B_MUST_REUSE')
    return {'ok':True,'a_sha256':a['sha256'],'semantic_pass_inferred':False,'automatic_join':False,
            'candidate_only':candidate,'upload_authorized':False,
            'final_review_required':candidate,'final_complete_audio_review_required':candidate,
            'a_complete_audio_review_pending':audio_pending,'production_contract_override':False}

def _join_probe(path):
    """Only local media; a playlist cannot open an HTTP source through ffprobe."""
    command=['ffprobe','-v','error','-protocol_whitelist','file,pipe','-count_frames','-show_entries',
             'stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration,nb_frames,nb_read_frames,sample_rate,channels:format=duration',
             '-of','json',str(path)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=30)
    if result.returncode or result.stderr.strip():raise ValueError('JOIN_BATCH_PROBE_FAILED: '+str(path))
    data=json.loads(result.stdout);streams=data.get('streams',[])
    audio=any(s.get('codec_type')=='audio' for s in streams)
    videos=[s for s in streams if s.get('codec_type')=='video']
    if not videos:
        duration=float(data.get('format',{}).get('duration',0))
        if not audio or not math.isfinite(duration) or duration<=0:raise ValueError('JOIN_BATCH_AUDIO_REQUIRED')
        return {'duration':duration,'audio':True}
    v=videos[0]
    try:
        fps=Fraction(v.get('avg_frame_rate') or v['r_frame_rate']);duration=float(v['duration'])
        frames=int(v['nb_frames']);read_frames=int(v['nb_read_frames']);width=int(v['width']);height=int(v['height'])
    except (KeyError,ValueError,ZeroDivisionError,TypeError):raise ValueError('JOIN_BATCH_VIDEO_TIMING_REQUIRED') from None
    if not audio or not 0<fps<=240 or not math.isfinite(duration) or duration<=0 or frames<=0 or not 2<=width<=8192 or not 2<=height<=8192:
        raise ValueError('JOIN_BATCH_AUDIO_VIDEO_REQUIRED')
    if read_frames!=frames:raise ValueError('JOIN_BATCH_INCOMPLETE_VIDEO_READ')
    if abs(duration-frames/float(fps))>1/float(fps):raise ValueError('JOIN_BATCH_CFR_REQUIRED')
    sound=next(s for s in streams if s.get('codec_type')=='audio')
    return {'width':width,'height':height,'fps':str(fps),'frames':frames,'frames_read':read_frames,
            'duration':frames/float(fps),'audio':True,'video_codec':v.get('codec_name'),
            'audio_codec':sound.get('codec_name'),'sample_rate':sound.get('sample_rate'),'channels':sound.get('channels')}

def _join_destination(root, value, project, *, receipt=False):
    if not isinstance(value,str) or not value:raise ValueError('JOIN_BATCH_OUTPUT_PATH_REQUIRED')
    relative=Path(value)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('JOIN_BATCH_RELATIVE_PATH_REQUIRED')
    raw=root/relative;path=raw.resolve();base=project/('evidence' if receipt else '交付')
    if not path.is_relative_to(base) or path==base:raise ValueError('JOIN_BATCH_PATH_OUTSIDE_PROJECT_OUTPUT_SCOPE')
    if path.is_dir() or path.suffix.lower()!=('.json' if receipt else '.mp4'):raise ValueError('JOIN_BATCH_RECEIPT_JSON_REQUIRED' if receipt else 'JOIN_BATCH_MP4_REQUIRED')
    for parent in [raw,*raw.parents]:
        if parent.is_symlink():raise ValueError('JOIN_BATCH_OUTPUT_PATH_SYMLINK')
        if parent==root:break
    return path

def _join_inputs(root, plan, variant):
    record={key:plan[key] for key in ('postproduction','a_video','a_acceptance')}
    record.update(schema='b-join-input-v1',b_source=variant['b_source'],b_mode='reuse_existing',b_generate=False)
    result=join_ready(root,record,candidate=True)
    proof(root,plan['subtitles']);proof(root,plan['bgm'])
    return result

def _join_directory(root, parent):
    """Open/create an approved relative directory without following any links."""
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW;fd=os.open(root,flags)
    try:
        for part in parent.relative_to(root).parts:
            try:os.mkdir(part,dir_fd=fd)
            except FileExistsError:pass
            child=os.open(part,flags,dir_fd=fd);os.close(fd);fd=child
        return fd
    except BaseException:os.close(fd);raise

def _join_save(path, record, directory_fd, *, first=False):
    parent=path.parent.stat(follow_symlinks=False);bound=os.fstat(directory_fd)
    if (parent.st_dev,parent.st_ino)!=(bound.st_dev,bound.st_ino):raise ValueError('JOIN_BATCH_RECEIPT_PATH_CHANGED')
    if not first and os.stat(path.name,dir_fd=directory_fd,follow_symlinks=False).st_mode&0o170000!=0o100000:
        raise ValueError('JOIN_BATCH_RECEIPT_PATH_CHANGED')
    name=path.name if first else '.'+path.name+'.'+uuid.uuid4().hex+'.tmp'
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory_fd)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(record,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        if not first:os.replace(name,path.name,src_dir_fd=directory_fd,dst_dir_fd=directory_fd)
    finally:
        if not first:
            try:os.unlink(name,dir_fd=directory_fd)
            except FileNotFoundError:pass

def join_batch(root, plan, receipt=None, *, execute=False):
    """Render at most three reviewed local candidates; never adopts or uploads."""
    root=Path(root).resolve()
    allowed={'schema','project_id','a_video','postproduction','a_acceptance','subtitles','bgm','bgm_gain','variants'}
    if not isinstance(plan,dict) or plan.get('schema')!='b-join-batch-v1' or set(plan)-allowed:raise ValueError('JOIN_BATCH_PLAN_REQUIRED')
    project_id=plan.get('project_id')
    if not isinstance(project_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',project_id):raise ValueError('JOIN_BATCH_PROJECT_REQUIRED')
    project=(root/'projects'/project_id).resolve()
    if not project.is_relative_to(root/'projects'):raise ValueError('JOIN_BATCH_PATH_OUTSIDE_PROJECT')
    variants=plan.get('variants')
    if not isinstance(variants,list) or not 1<=len(variants)<=3:raise ValueError('JOIN_BATCH_VARIANTS_1_TO_3_REQUIRED')
    gain=plan.get('bgm_gain')
    if type(gain) not in (int,float) or not math.isfinite(gain) or not 0<=gain<=1:raise ValueError('JOIN_BATCH_GAIN_REQUIRED')
    paths=[];ids=[]
    for v in variants:
        if not isinstance(v,dict) or set(v)!={'id','b_source','output'} or not isinstance(v['id'],str) or not v['id'].strip():raise ValueError('JOIN_BATCH_VARIANT_REQUIRED')
        output=_join_destination(root,v['output'],project)
        if output.suffix.lower()!='.mp4':raise ValueError('JOIN_BATCH_MP4_REQUIRED')
        if output.exists():raise ValueError('JOIN_BATCH_OUTPUT_EXISTS: '+str(output))
        paths.append(output);ids.append(v['id'])
    if len(set(paths))!=len(paths) or len(set(ids))!=len(ids):raise ValueError('JOIN_BATCH_DUPLICATE_TARGET')
    receipt_path=_join_destination(root,str(receipt),project,receipt=True) if receipt is not None else None
    if receipt_path in paths:raise ValueError('JOIN_BATCH_DUPLICATE_TARGET')
    if receipt_path is not None and receipt_path.exists():raise ValueError('JOIN_BATCH_ALREADY_ATTEMPTED: read the existing receipt; no retry performed')
    if execute and receipt_path is None:raise ValueError('JOIN_BATCH_RECEIPT_REQUIRED')
    guards=[_join_inputs(root,plan,v) for v in variants]
    a=proof(root,plan['a_video']);subtitles=proof(root,plan['subtitles']);bgm=proof(root,plan['bgm'])
    if subtitles.suffix.lower()!='.ass':raise ValueError('JOIN_BATCH_ASS_REQUIRED')
    post=load(proof(root,plan['postproduction']));script=load(proof(root,post['director']))
    if script.get('project_id')!=project_id:raise ValueError('JOIN_BATCH_PROJECT_MISMATCH')
    am=_join_probe(a);music=_join_probe(bgm)
    if not {'width','height','fps','frames'}<=set(am) or am['width']%2 or am['height']%2:raise ValueError('JOIN_BATCH_A_SPEC_REQUIRED')
    fps=Fraction(am['fps']);ad=am['duration'];prepared=[]
    for v,output in zip(variants,paths):
        bm=_join_probe(proof(root,v['b_source']))
        if 'frames' not in bm:raise ValueError('JOIN_BATCH_B_VIDEO_REQUIRED')
        frames=max(1,round(bm['duration']*float(fps)));duration=frames/float(fps)
        if not script.get('duration_override_source') and not 10<=ad+duration<=25:raise ValueError('JOIN_BATCH_FINAL_DURATION_OUT_OF_RANGE')
        if music['duration']+1e-6<ad+duration:raise ValueError('JOIN_BATCH_CONTINUOUS_BGM_TOO_SHORT')
        prepared.append({'variant':v,'output':output,'b_frames':frames,'b_duration':duration})
    common={'schema':'b-join-batch-receipt-v1','project_id':project_id,'candidate_only':True,'upload_authorized':False,
            'final_review_required':True,'final_complete_audio_review_required':True,'user_adoption':False,
            'automatic_retry':False,'plan_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            'a_video':plan['a_video'],'a_media':am,'subtitles':plan['subtitles'],'bgm':plan['bgm'],'bgm_gain':gain,
            'b_music_start_seconds':ad,'parallel_workers':len(prepared),'guards':guards}
    if not execute:return {**common,'ok':True,'render_performed':False,'state':'checked','variants':len(prepared)}
    record={**common,'ok':False,'render_performed':True,'state':'rendering','results':[]}
    # A durable one-attempt receipt is claimed before any process can render.
    receipt_fd=_join_directory(root,receipt_path.parent)
    try:_join_save(receipt_path,record,receipt_fd,first=True)
    except BaseException:os.close(receipt_fd);raise
    started=time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='join-batch-') as folder:
            work=Path(folder)
            # Fixed, private snapshots avoid changing-file reads and ASS filter-path escaping.
            for name,ref in [('a.mp4',plan['a_video']),('captions.ass',plan['subtitles']),('music',plan['bgm'])]:
                shutil.copyfile(proof(root,ref),work/name)
                if sha(work/name)!=ref['sha256']:raise ValueError('JOIN_BATCH_INPUT_CHANGED')
            def render(item):
                v=item['variant'];output=item['output'];bd=item['b_duration'];bf=item['b_frames']
                result={'id':v['id'],'output':str(output),'b_source':v['b_source'],'state':'failed','automatic_retry':False}
                try:
                    _join_inputs(root,plan,v)
                    source=work/('b-'+str(ids.index(v['id']))+'.mp4');shutil.copyfile(proof(root,v['b_source']),source)
                    if sha(source)!=v['b_source']['sha256']:raise ValueError('JOIN_BATCH_INPUT_CHANGED')
                    temp=work/('render-'+str(ids.index(v['id']))+'.mp4');w,h=am['width'],am['height'];rate=str(fps)
                    blur=min(20,min(w,h)//4)  # Chroma planes bound the radius for tiny test/preview media.
                    graph=(f'[0:v]ass=filename=captions.ass,setsar=1,fps={rate},trim=end_frame={am["frames"]},setpts=PTS-STARTPTS,format=yuv420p[v0];'
                           f'[1:v]split=2[bg0][fg0];[bg0]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur={blur}:2,eq=brightness=-0.2[bg];'
                           f'[fg0]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];'
                           f'[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={rate},tpad=stop_mode=clone:stop_duration={1/float(fps):.12f},trim=end_frame={bf},setpts=PTS-STARTPTS,format=yuv420p[v1];'
                           f'[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad=whole_dur={ad:.12f},atrim=end={ad:.12f},asetpts=PTS-STARTPTS[a0];'
                           f'[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad=whole_dur={bd:.12f},atrim=end={bd:.12f},asetpts=PTS-STARTPTS[ba];'
                           f'[2:a]atrim=start={ad:.12f}:duration={bd:.12f},asetpts=PTS-STARTPTS,volume={gain},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[m];'
                           '[ba][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=0[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]')
                    command=['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-xerror','-threads','2']
                    for path in [work/'a.mp4',source,work/'music']:command+=['-protocol_whitelist','file,pipe','-i',str(path)]
                    command+=['-filter_complex_threads','1','-filter_complex',graph,'-map','[v]','-map','[a]',
                              '-frames:v',str(am['frames']+bf),'-c:v','libx264','-threads','2','-preset','veryfast','-crf','18',
                              '-pix_fmt','yuv420p','-r',rate,'-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-movflags','+faststart','-n',str(temp)]
                    run=subprocess.run(command,cwd=work,capture_output=True,text=True,timeout=180)
                    if run.returncode:raise ValueError('JOIN_BATCH_RENDER_FAILED: '+run.stderr[-1000:])
                    media=_join_probe(temp)
                    if (media.get('width'),media.get('height'),Fraction(media.get('fps','0')),media.get('frames'))!=(w,h,fps,am['frames']+bf):raise ValueError('JOIN_BATCH_OUTPUT_SPEC_MISMATCH')
                    decoded=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-v','error','-xerror','-protocol_whitelist','file,pipe','-i',str(temp),'-f','null','-'],capture_output=True,text=True,timeout=180)
                    if decoded.returncode or decoded.stderr.strip():raise ValueError('JOIN_BATCH_DECODE_FAILED')
                    verified_sha=sha(temp);verified_stat=temp.stat()
                    _join_inputs(root,plan,v)
                    if _join_destination(root,v['output'],project)!=output:raise ValueError('JOIN_BATCH_OUTPUT_PATH_CHANGED')
                    # Publish without replacing a path another writer created during rendering.
                    directory_fd=_join_directory(root,output.parent)
                    try:
                        os.link(temp,output.name,dst_dir_fd=directory_fd)
                        fd=os.open(output.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
                        with os.fdopen(fd,'rb') as stream:
                            published=os.fstat(stream.fileno());published_sha=hashlib.sha256(stream.read()).hexdigest();stable=os.fstat(stream.fileno())
                        current=os.stat(output.name,dir_fd=directory_fd,follow_symlinks=False)
                        signature=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
                        if (signature(published)!=signature(verified_stat) or signature(stable)!=signature(published)
                                or signature(current)!=signature(published) or published_sha!=verified_sha):
                            raise ValueError('JOIN_BATCH_OUTPUT_CHANGED_AFTER_PUBLICATION: preserve the changed file')
                        if _join_destination(root,v['output'],project)!=output or output.parent.stat().st_ino!=os.fstat(directory_fd).st_ino:
                            raise ValueError('JOIN_BATCH_OUTPUT_PATH_CHANGED')
                    finally:os.close(directory_fd)
                    result.update(state='rendered',sha256=verified_sha,bytes=verified_stat.st_size,media=media,
                                  full_decode_exit=0,full_decode_errors='',a_frames=am['frames'],b_output_frames=bf,
                                  b_music_start_seconds=ad,actual_listening='pending CP3',user_adoption=False,uploaded=False)
                except Exception as error:result.update(error=str(error),error_type=type(error).__name__)
                return result
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(prepared)) as pool:
                futures=[pool.submit(render,item) for item in prepared]
                for future in concurrent.futures.as_completed(futures):
                    record['results'].append(future.result());_join_save(receipt_path,record,receipt_fd)
    except Exception as error:record.update(error=str(error),error_type=type(error).__name__)
    record['results'].sort(key=lambda item:ids.index(item['id']))
    count=sum(r['state']=='rendered' for r in record['results'])
    record.update(ok=count==len(prepared),state='completed' if count==len(prepared) else ('partial' if count else 'failed'),wall_seconds=round(time.monotonic()-started,3))
    try:_join_save(receipt_path,record,receipt_fd)
    finally:os.close(receipt_fd)
    return {**record,'receipt':str(receipt_path)}

def inspect(root,kind,record):
    if kind=='join-preview':return join_ready(root,record,candidate=True)
    return {'director':director,'postproduction':postproduction,'join':join_ready}[kind](root,record)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kind',choices=['director','postproduction','join','join-preview','console-plan','join-batch']);p.add_argument('--root',default='.');p.add_argument('--record',required=True);p.add_argument('--project');p.add_argument('--receipt');p.add_argument('--execute',action='store_true');a=p.parse_args()
    try:
        if a.kind!='join-batch' and (a.receipt is not None or a.execute):raise ValueError('--receipt/--execute apply only to join-batch')
        if a.kind=='console-plan':
            if not a.project:raise ValueError('console-plan requires --project')
            base=Path(a.root).resolve();config_path=(base/'projects'/a.project/'console.json').resolve()
            if not config_path.is_relative_to(base/'projects'):raise ValueError('Invalid project')
            config=load(config_path)
            if config.get('project_id')!=a.project:raise ValueError('DIRECTOR_PROJECT_MISMATCH')
            result=console_operations(base,load(a.record),config)
        elif a.kind=='join-batch':
            if a.project:raise ValueError('join-batch uses its plan project_id')
            result=join_batch(a.root,load(a.record),a.receipt,execute=a.execute)
        else:
            if a.project:raise ValueError('--project applies only to console-plan')
            result=inspect(a.root,a.kind,load(a.record))
    except (ValueError,KeyError,TypeError,OSError) as e:print(json.dumps({'ok':False,'error':str(e)}));return 1
    print(json.dumps(result,ensure_ascii=False));return 1 if a.kind=='join-batch' and not result['ok'] else 0
if __name__=='__main__':raise SystemExit(main())
