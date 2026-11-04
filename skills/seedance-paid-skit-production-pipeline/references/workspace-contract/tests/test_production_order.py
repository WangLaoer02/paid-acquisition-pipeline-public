import array,contextlib,copy,io,json,math,shutil,subprocess,sys,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import production_order as p
from workflow_step import boundary,timing_report
import workflow_step as step

class ProductionOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.e=self.put('observation.txt','Synthetic observation, not production approval')
        self.a=self.put('a.mp4','synthetic A');self.pr=self.put('project.prproj','synthetic PR')
        self.d={'schema':'production-director-v1','purpose':'preproduction','scope':'A_only','source_ref':'fixture','revision':'r1','history_status':'before_generation','shots':[{'id':'SC-01','segment':'A','action':'raises hand','dialogue':'hello','original_copy':'hello','camera':'fixed','sound':'dialogue','composition':'center','planned_seconds':15}],'b_plan':{'mode':'reuse_existing','generate':False,'reserved_seconds':5}}
        self.dr=self.put('director.json',self.d)
        self.native=self.put('export.json',{'output_sha256':self.a['sha256'],'saved_copy_sha256':self.pr['sha256'],'result':{'native_call_returned':True,'export_backend':'Premiere UXP IMMEDIATELY'}})
        self.post={'schema':'pr-postproduction-v1','director':self.dr,'project':self.pr,'a_video':self.a,'native_export':self.native,'checks':{k:{'status':'done','observation':'synthetic checked','evidence':self.e} for k in p.POST_ITEMS}}
        self.postref=self.put('post.json',self.post)
        self.accept={'schema':'a-acceptance-v1','a_sha256':self.a['sha256'],'postproduction_sha256':self.postref['sha256'],**{k:{'status':'pass','reviewer':'fixture','observed_at':'2026-10-29','evidence':self.e} for k in ['visual','complete_audio','user_adoption']}}
        self.join={'schema':'b-join-input-v1','postproduction':self.postref,'a_video':self.a,'a_acceptance':self.put('accept.json',self.accept),'b_source':self.put('b.mp4','synthetic B'),'b_mode':'reuse_existing','b_generate':False}
    def put(self,name,data):
        f=self.root/name;f.write_text(json.dumps(data) if isinstance(data,dict) else data);return {'path':name,'sha256':p.sha(f)}
    def test_valid_order(self):self.assertTrue(p.join_ready(self.root,self.join)['ok'])
    def test_preproduction_rejects_final_frame(self):
        self.d['shots'][0]['images']=[{**self.e,'role':'finished_frame'}]
        with self.assertRaisesRegex(ValueError,'FINISHED_FRAME'):p.director(self.root,self.d)
    def test_preproduction_cannot_embed_movie(self):
        self.d['final_video']=self.a
        with self.assertRaisesRegex(ValueError,'DELIVERY_IN'):p.director(self.root,self.d)
    def test_b_cannot_be_generated(self):
        self.join['b_generate']=True
        with self.assertRaisesRegex(ValueError,'B_MUST_REUSE'):p.join_ready(self.root,self.join)
    def test_export_alone_not_postproduction(self):
        self.post['checks']={}
        with self.assertRaisesRegex(ValueError,'POSTPRODUCTION_INCOMPLETE'):p.postproduction(self.root,self.post)
    def test_skip_subtitles_needs_requirement_source(self):
        self.post['checks']['subtitles']['status']='not_required'
        with self.assertRaisesRegex(ValueError,'EXCEPTION_SOURCE_REQUIRED'):p.postproduction(self.root,self.post)
    def test_no_audio_approval_no_join(self):
        self.accept['complete_audio']['status']='pending';self.join['a_acceptance']=self.put('accept.json',self.accept)
        with self.assertRaisesRegex(ValueError,'A_NOT_ACCEPTED'):p.join_ready(self.root,self.join)
    def test_changed_a_does_not_reuse_acceptance(self):
        self.join['a_video']=self.put('other.mp4','different A')
        with self.assertRaisesRegex(ValueError,'A_CHANGED'):p.join_ready(self.root,self.join)
    def test_changed_director_invalidates_post(self):
        self.put('director.json',{**self.d,'revision':'r2'})
        with self.assertRaisesRegex(ValueError,'STALE'):p.postproduction(self.root,self.post)
    def test_missing_image_and_outside_root(self):
        for ref in [{'path':'missing','sha256':'0'*64},{'path':'../outside','sha256':'0'*64}]:
            with self.assertRaises(ValueError):p.proof(self.root,ref)
    def test_new_session_cannot_run_different_node(self):
        with self.assertRaisesRegex(ValueError,'NODE_MISMATCH'):boundary('A01','A12')
        self.assertFalse(boundary('A01','A01')['auto_advance'])
    def test_three_review_boundaries_allow_other_verified_nodes_to_continue(self):
        for route,final in [('a','A14'),('ab','B04')]:
            stopped=[]
            nodes=[f'A{i:02}' for i in range(1,16)]
            if route=='ab':nodes += [f'B{i:02}' for i in range(1,6)]
            for node in nodes:
                b=boundary(node,node,route)
                if b['stop_after_current_node']:stopped.append(node)
                self.assertFalse(b['auto_advance'])
                self.assertTrue(b['gate_pass_required_before_continuation'])
                self.assertTrue(b['read_live_context_before_each_node'])
                self.assertTrue(b['high_risk_actions_require_current_runtime_guard'])
                self.assertFalse(b['internal_checks_require_user_confirmation'])
            self.assertEqual(stopped,['A03','A09',final])
        self.assertFalse(boundary('A13','A13')['next_node_requires_user_request'])
    def test_unknown_node_cannot_be_selected_as_unrestricted_step(self):
        with self.assertRaisesRegex(ValueError,'UNKNOWN_NODE'):boundary('A99','A99')
    def test_b_context_infers_final_ab_review_without_new_route_flag(self):
        self.assertEqual(boundary('B04','B04')['route'],'ab')
        self.assertTrue(boundary('B04','B04')['stop_after_current_node'])
        with self.assertRaisesRegex(ValueError,'B_NODE_REQUIRES_AB_ROUTE'):
            boundary('B04','B04','a')
    def test_preview_can_join_before_user_adoption_but_cannot_upload(self):
        self.accept['user_adoption']={'status':'pending'}
        self.join['a_acceptance']=self.put('accept.json',self.accept)
        with self.assertRaisesRegex(ValueError,'A_NOT_ACCEPTED:user_adoption'):p.join_ready(self.root,self.join)
        preview=p.inspect(self.root,'join-preview',self.join)
        self.assertTrue(preview['candidate_only']);self.assertTrue(preview['final_review_required'])
        self.assertFalse(preview['upload_authorized']);self.assertFalse(preview['production_contract_override'])
    def test_preview_defers_pending_audio_to_final_ab_but_rejects_failed_audio(self):
        self.accept['complete_audio']['status']='pending'
        self.join['a_acceptance']=self.put('accept.json',self.accept)
        preview=p.join_ready(self.root,self.join,candidate=True)
        self.assertTrue(preview['final_complete_audio_review_required'])
        self.assertTrue(preview['a_complete_audio_review_pending'])
        self.assertFalse(preview['upload_authorized'])
        with self.assertRaisesRegex(ValueError,'A_NOT_ACCEPTED:complete_audio'):p.join_ready(self.root,self.join)
        for status in ['failed','rejected',None]:
            self.accept['complete_audio']['status']=status
            self.join['a_acceptance']=self.put('accept.json',self.accept)
            with self.assertRaisesRegex(ValueError,'A_NOT_ACCEPTED:complete_audio'):
                p.join_ready(self.root,self.join,candidate=True)
        self.join['a_video']=self.put('other.mp4','changed')
        with self.assertRaisesRegex(ValueError,'A_CHANGED'):p.join_ready(self.root,self.join,candidate=True)
    def test_pending_audio_preview_still_requires_mix_and_source_evidence(self):
        self.accept['complete_audio']['status']='pending'
        for name in ('audio_sources','mix'):
            with self.subTest(name=name):
                post=copy.deepcopy(self.post);post['checks'][name]['status']='pending'
                self.join['postproduction']=self.put('post.json',post)
                with self.assertRaisesRegex(ValueError,'POSTPRODUCTION_INCOMPLETE:'+name):
                    p.join_ready(self.root,self.join,candidate=True)
    def test_preview_does_not_ignore_explicit_user_rejection(self):
        self.accept['user_adoption']={'status':'rejected'}
        self.join['a_acceptance']=self.put('accept.json',self.accept)
        with self.assertRaisesRegex(ValueError,'A_USER_REJECTION'):p.join_ready(self.root,self.join,candidate=True)
    def timing(self):
        return {'schema':'workflow-timing-v1','started_at':'2026-11-01T00:00:00+08:00',
                'finished_at':'2026-11-01T00:05:10+08:00',
                'spans':[{'kind':'external_wait','started_at':'2026-11-01T00:00:00+08:00','ended_at':'2026-11-01T00:04:00+08:00'},
                         {'kind':'active','started_at':'2026-11-01T00:03:00+08:00','ended_at':'2026-11-01T00:05:00+08:00'},
                         {'kind':'user_review','started_at':'2026-11-01T00:04:30+08:00','ended_at':'2026-11-01T00:05:10+08:00'}]}
    def test_wall_clock_includes_review_external_wait_and_parallel_work(self):
        r=timing_report(self.timing(),self.root)
        self.assertEqual(r['elapsed_seconds'],310);self.assertFalse(r['elapsed_within_target'])
        self.assertEqual(r['category_seconds'],{'active':120,'external_wait':240,'user_review':40})
        self.assertFalse(r['five_minute_pass_inferred']);self.assertEqual(r['side_effects'],[])
        self.assertEqual(r['overrun_action'],'continue querying original task; never resubmit to meet deadline')
    def test_fast_receipt_without_upload_never_implies_whole_workflow_pass(self):
        t=self.timing();t['finished_at']='2026-11-01T00:01:00+08:00';t['spans']=[]
        r=timing_report(t,self.root)
        self.assertTrue(r['elapsed_within_target']);self.assertFalse(r['required_timing_endpoints_present'])
        self.assertFalse(r['five_minute_pass_inferred'])
    def test_upload_endpoint_is_bound_to_current_output_and_readback_time(self):
        t=self.timing();t['final_delivery']=self.a
        t['upload_readback']={'status':'verified','material_id':'synthetic-123','source_ref':'synthetic-readback',
                              'file_sha256':self.a['sha256'],'observed_at':t['finished_at']}
        self.assertTrue(timing_report(t,self.root)['required_timing_endpoints_present'])
        t['upload_readback']['file_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'UPLOAD_TIMING_BINDING'):timing_report(t,self.root)
        t['upload_readback']['file_sha256']=self.a['sha256'];t['finished_at']='2026-11-01T00:05:05+08:00';t['spans']=[]
        with self.assertRaisesRegex(ValueError,'FINISH_MUST_MATCH'):timing_report(t,self.root)
    def test_invalid_timing_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'TIMING_RECORD_REQUIRED'):timing_report([],self.root)
        t=self.timing();t['spans']=[None]
        with self.assertRaisesRegex(ValueError,'TIMING_SPAN_REQUIRED'):timing_report(t,self.root)
    def test_bad_times_cannot_make_an_overrun_look_fast(self):
        t=self.timing();t['finished_at']='2026-10-31T23:59:00+08:00'
        with self.assertRaisesRegex(ValueError,'INVALID_TIMING_RANGE'):timing_report(t,self.root)
        t=self.timing();t['started_at']='2026-11-01T00:00:00'
        with self.assertRaisesRegex(ValueError,'TIMESTAMP_TIMEZONE'):timing_report(t,self.root)
        t=self.timing();t['spans'][0]['ended_at']='2026-11-01T00:06:00+08:00'
        with self.assertRaisesRegex(ValueError,'SPAN_OUTSIDE'):timing_report(t,self.root)
    def test_compatibility_step_delegates_route_and_uses_original_context_boundary(self):
        original={'ok':True,'node':'A14','execution_boundary':{'route':'ab','source':'original context','stop_after_current_node':False}}
        output=io.StringIO()
        with patch.object(sys,'argv',['workflow_step.py','--item','fixture-A','--node','A14','--route','ab']), \
             patch.object(step.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(original))) as invoke, \
             contextlib.redirect_stdout(output):
            self.assertEqual(step.main(),0)
        command=invoke.call_args.args[0]
        self.assertEqual(command[command.index('--route')+1],'ab')
        self.assertEqual(json.loads(output.getvalue())['execution_boundary'],original['execution_boundary'])
    def test_compatibility_step_still_rejects_mismatched_live_node(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['workflow_step.py','--item','fixture-A','--node','A14']), \
             patch.object(step.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'node':'A13','execution_boundary':{}}))), \
             contextlib.redirect_stdout(output):
            self.assertEqual(step.main(),1)
        self.assertIn('NODE_MISMATCH',json.loads(output.getvalue())['error'])
    def test_console_plan_compiles_one_sparse_batch_without_remote_calls(self):
        import console_template as ct
        config={'project_id':'FIX','template_id':ct.DIRECTOR_ID,'shot_count':1}
        self.d['project_id']='FIX'
        self.d['shots'][0]['original_copy']=''
        with patch.object(ct,'cli',side_effect=AssertionError('planning must not read/write Feishu')):
            ops=p.console_operations(self.root,self.d,config)
        values={op['slot']:op['payload']['value'] for op in ops}
        self.assertEqual(values['script'],'center\nraises hand')
        self.assertEqual(values['duration'],'15秒')
        self.assertNotIn('original_copy',values)  # Unknown source stays absent; never clears manual text.
        self.assertEqual(values['dialogue'],'hello')
        self.assertNotIn('current_node',values)
        self.assertEqual(len(ops),5)
        self.assertTrue(all(op['index']==0 for op in ops))
    def test_console_plan_cli_outputs_directly_usable_operations_array(self):
        import subprocess
        import console_template as ct
        config=self.root/'projects/FIX/console.json';config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'project_id':'FIX','template_id':ct.DIRECTOR_ID,'shot_count':1}))
        self.d['project_id']='FIX';self.put('director.json',self.d)
        command=[sys.executable,str(Path(p.__file__)),'console-plan','--root',str(self.root),'--project','FIX','--record',str(self.root/'director.json')]
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        operations=json.loads(result.stdout)
        self.assertIsInstance(operations,list)
        self.assertEqual(len(operations),6)
        self.assertTrue(all(set(op)=={'slot','index','payload'} for op in operations))
        self.assertEqual(list((self.root/'projects/FIX').iterdir()),[config])
    def test_console_plan_rejects_wrong_project_or_shot_mapping(self):
        import console_template as ct
        config={'project_id':'FIX','template_id':ct.DIRECTOR_ID,'shot_count':1}
        with self.assertRaisesRegex(ValueError,'DIRECTOR_PROJECT_MISMATCH'):
            p.console_operations(self.root,self.d,config)
        self.d['project_id']='OTHER'
        with self.assertRaisesRegex(ValueError,'DIRECTOR_PROJECT_MISMATCH'):
            p.console_operations(self.root,self.d,config)
        self.d['project_id']='FIX';self.d['shots'][0]['id']='SC-02'
        with self.assertRaisesRegex(ValueError,'DIRECTOR_SHOT_MAPPING_MISMATCH'):
            p.console_operations(self.root,self.d,config)
        self.d['shots'][0]['id']='SC-01';config['shot_count']=2
        with self.assertRaisesRegex(ValueError,'DIRECTOR_SHOT_MAPPING_MISMATCH'):
            p.console_operations(self.root,self.d,config)
    def test_console_plan_preserves_source_words_and_applies_original_content_checks(self):
        import console_template as ct
        config={'project_id':'FIX','template_id':ct.DIRECTOR_ID,'shot_count':1}
        self.d['project_id']='FIX'
        self.d['shots'][0]['original_copy']='原句：住在这还挑三拣四'
        ops=p.console_operations(self.root,self.d,config)
        self.assertEqual(next(op for op in ops if op['slot']=='original_copy')['payload']['value'],self.d['shots'][0]['original_copy'])
        self.d['shots'][0]['action']='B段接点说明'
        with self.assertRaisesRegex(ValueError,'A_STORY_BODY_ONLY'):
            p.console_operations(self.root,self.d,config)
    def test_long_reference_does_not_expand_final(self):
        self.d['shots'][0]['planned_seconds']=257
        with self.assertRaisesRegex(ValueError,'FINAL_DURATION'):p.director(self.root,self.d)
class JoinBatchTests(unittest.TestCase):
    def setUp(self):
        self.f=ProductionOrderTests('test_valid_order');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root;self.project=self.root/'projects/TEST';self.project.mkdir(parents=True)
        self.f.d['project_id']='TEST';self.f.dr=self.f.put('director.json',self.f.d)
        self.f.post['director']=self.f.dr;self.f.postref=self.f.put('post.json',self.f.post)
        self.f.accept['postproduction_sha256']=self.f.postref['sha256']
        self.f.accept['complete_audio']={'status':'pending'}
        self.f.accept['user_adoption']={'status':'pending'}
        self.plan={'schema':'b-join-batch-v1','project_id':'TEST','a_video':self.f.a,
                   'postproduction':self.f.postref,'a_acceptance':self.f.put('accept.json',self.f.accept),
                   'subtitles':self.f.put('captions.ass','Synthetic subtitle fixture'),
                   'bgm':self.f.put('music.wav','Synthetic music fixture'),'bgm_gain':.4,
                   'variants':[{'id':'D1','b_source':self.f.join['b_source'],'output':'projects/TEST/交付/D1.mp4'}]}
        self.receipt='projects/TEST/evidence/batch-receipt.json';self.receipt_path=self.root/self.receipt
        self.media={'width':64,'height':96,'fps':'24/1','frames':192,'duration':8.,'audio':True}
    def probe(self,path):
        if Path(path).name=='music.wav':return {'duration':25.,'audio':True}
        return dict(self.media)
    def test_check_validates_each_candidate_without_rendering_or_writing(self):
        self.plan['variants'].append({**self.plan['variants'][0],'id':'D2','output':'projects/TEST/交付/D2.mp4'})
        with patch.object(p,'_join_probe',side_effect=self.probe),patch.object(p,'join_ready',wraps=p.join_ready) as guard:
            result=p.join_batch(self.root,self.plan)
        self.assertTrue(result['ok']);self.assertFalse(result['render_performed'])
        self.assertEqual(guard.call_count,2)
        self.assertTrue(all(call.kwargs=={'candidate':True} for call in guard.call_args_list))
        self.assertFalse(result['upload_authorized']);self.assertTrue(result['final_complete_audio_review_required'])
        self.assertEqual(list(self.project.iterdir()),[])
    def test_existing_output_is_preserved_before_any_render(self):
        target=self.project/'交付/D1.mp4';target.parent.mkdir();target.write_bytes(b'user-owned output')
        with patch.object(p,'_join_probe',side_effect=self.probe),patch.object(p.subprocess,'run') as process:
            with self.assertRaisesRegex(ValueError,'JOIN_BATCH_OUTPUT_EXISTS'):
                p.join_batch(self.root,self.plan,self.receipt,execute=True)
        process.assert_not_called();self.assertEqual(target.read_bytes(),b'user-owned output')
        self.assertFalse(self.receipt_path.exists())
    def test_only_relative_delivery_mp4_and_evidence_json_are_allowed(self):
        for output in ['/tmp/D1.mp4',str(self.project/'交付/D1.mp4'),'projects/TEST/剪辑/project.mp4',
                       'projects/TEST/交付/../剪辑/D1.mp4','projects/OTHER/交付/D1.mp4','projects/TEST/交付/not-video.prproj']:
            with self.subTest(output=output):
                self.plan['variants'][0]['output']=output
                with self.assertRaisesRegex(ValueError,'JOIN_BATCH_'):
                    p.join_batch(self.root,self.plan,self.receipt,execute=True)
        self.plan['variants'][0]['output']='projects/TEST/交付/D1.mp4'
        for receipt in [str(self.receipt_path),'projects/TEST/剪辑/receipt.json','projects/TEST/evidence/receipt.mp4']:
            with self.subTest(receipt=receipt):
                with self.assertRaisesRegex(ValueError,'JOIN_BATCH_'):
                    p.join_batch(self.root,self.plan,receipt,execute=True)
        self.assertEqual(list(self.project.iterdir()),[])
    def test_all_candidate_guards_and_current_proofs_fail_before_render(self):
        for kind in ['rejected','failed_audio','b_changed','subtitles_changed','native_changed']:
            with self.subTest(kind=kind):
                original=copy.deepcopy(self.plan);accept=copy.deepcopy(self.f.accept)
                if kind=='rejected':
                    accept['user_adoption']={'status':'rejected'}
                    self.plan['a_acceptance']=self.f.put('reject.json',accept)
                elif kind=='failed_audio':
                    accept['complete_audio']={'status':'fail'}
                    self.plan['a_acceptance']=self.f.put('fail-audio.json',accept)
                elif kind=='b_changed':self.plan['variants'][0]['b_source']={**self.f.join['b_source'],'sha256':'0'*64}
                elif kind=='subtitles_changed':self.plan['subtitles']={**self.plan['subtitles'],'sha256':'0'*64}
                elif kind=='native_changed':
                    self.f.put('export.json',{'result':{'native_call_returned':False}})
                with patch.object(p.subprocess,'run') as process:
                    with self.assertRaises(ValueError):p.join_batch(self.root,self.plan,self.receipt,execute=True)
                process.assert_not_called();self.assertFalse(self.receipt_path.exists());self.plan=original
    def test_limits_duplicate_targets_and_incomplete_music_are_rejected(self):
        original=copy.deepcopy(self.plan)
        for variants in [[],[original['variants'][0]]*4,[original['variants'][0]]*2]:
            self.plan['variants']=variants
            with self.assertRaisesRegex(ValueError,'JOIN_BATCH_'):p.join_batch(self.root,self.plan)
        self.plan=original
        with patch.object(p,'_join_probe',side_effect=lambda path:{'duration':8.,'audio':True} if Path(path).name=='music.wav' else dict(self.media)):
            with self.assertRaisesRegex(ValueError,'CONTINUOUS_BGM_TOO_SHORT'):p.join_batch(self.root,self.plan)
        for gain in [True,-1,float('nan'),2]:
            self.plan['bgm_gain']=gain
            with self.assertRaisesRegex(ValueError,'GAIN_REQUIRED'):p.join_batch(self.root,self.plan)
    def test_missing_or_other_director_project_is_rejected_with_valid_proofs(self):
        for project_id in [None,'SOURCE_PROJECT']:
            with self.subTest(project_id=project_id):
                director=copy.deepcopy(self.f.d)
                if project_id is None:director.pop('project_id')
                else:director['project_id']=project_id
                post=copy.deepcopy(self.f.post);post['director']=self.f.put('other-director.json',director)
                self.plan['postproduction']=self.f.put('other-post.json',post)
                accept=copy.deepcopy(self.f.accept);accept['postproduction_sha256']=self.plan['postproduction']['sha256']
                self.plan['a_acceptance']=self.f.put('other-accept.json',accept)
                with patch.object(p.subprocess,'run') as process:
                    with self.assertRaisesRegex(ValueError,'JOIN_BATCH_PROJECT_MISMATCH'):
                        p.join_batch(self.root,self.plan,self.receipt,execute=True)
                process.assert_not_called();self.assertFalse(self.receipt_path.exists())
    def real_plan(self):
        """Small synthetic media only; its native-export labels are test fixtures."""
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):self.skipTest('ffmpeg/ffprobe unavailable')
        if not hasattr(type(self),'assets'):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                commands=[
                    ['-f','lavfi','-i','color=c=white:s=64x96:r=6:d=6','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=6',
                     '-c:v','libx264','-preset','ultrafast','-threads','1','-c:a','aac','-shortest',str(root/'a.mp4')],
                    ['-f','lavfi','-i','color=c=green:s=128x72:r=12:d=4','-f','lavfi','-i','aevalsrc=0.1*sin(2*PI*440*t):s=48000:d=4',
                     '-vf','drawbox=x=0:y=0:w=8:h=ih:color=red:t=fill,drawbox=x=iw-8:y=0:w=8:h=ih:color=blue:t=fill',
                     '-c:v','libx264','-preset','ultrafast','-threads','1','-c:a','aac','-shortest',str(root/'b.mp4')],
                    ['-f','lavfi','-i','aevalsrc=0.05*sin(2*PI*220*t)*(1+t/20):s=48000:d=12','-c:a','pcm_s16le',str(root/'music.wav')]]
                for command in commands:subprocess.run(['ffmpeg','-hide_banner','-loglevel','error',*command],capture_output=True,check=True)
                type(self).assets={name:(root/name).read_bytes() for name in ['a.mp4','b.mp4','music.wav']}
        for name,data in self.assets.items():(self.root/name).write_bytes(data)
        self.f.a={'path':'a.mp4','sha256':p.sha(self.root/'a.mp4')}
        self.f.d['shots'][0]['planned_seconds']=6;self.f.d['b_plan']['reserved_seconds']=4
        self.f.dr=self.f.put('director.json',self.f.d)
        native=self.f.put('export.json',{'output_sha256':self.f.a['sha256'],'saved_copy_sha256':self.f.pr['sha256'],
                                      'result':{'native_call_returned':True,'export_backend':'Premiere UXP IMMEDIATELY'}})
        self.f.post.update(director=self.f.dr,a_video=self.f.a,native_export=native)
        post=self.f.put('post.json',self.f.post)
        self.f.accept.update(a_sha256=self.f.a['sha256'],postproduction_sha256=post['sha256'])
        self.plan.update(a_video=self.f.a,postproduction=post,a_acceptance=self.f.put('accept.json',self.f.accept),
                         bgm={'path':'music.wav','sha256':p.sha(self.root/'music.wav')})
        ass='[Script Info]\nScriptType: v4.00+\nPlayResX: 64\nPlayResY: 96\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Default,Arial,10,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,2,2,2,1\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,fixture\nDialogue: 0,0:00:07.00,0:00:08.00,Default,,0,0,0,,MUST NOT B\n'
        self.plan['subtitles']=self.f.put('captions.ass',ass)
        self.plan['variants']=[{'id':f'D{i}','b_source':{'path':'b.mp4','sha256':p.sha(self.root/'b.mp4')},
                                'output':f'projects/TEST/交付/D{i}.mp4'} for i in range(1,4)]
    def test_real_execute_three_outputs_preserves_full_B_and_continuous_music(self):
        self.real_plan();result=p.join_batch(self.root,self.plan,self.receipt,execute=True)
        self.assertTrue(result['ok'],result);self.assertEqual(result['parallel_workers'],3)
        self.assertEqual(result['b_music_start_seconds'],6.)
        for item in result['results']:
            self.assertEqual(item['state'],'rendered');self.assertEqual(item['media']['frames'],60)
            self.assertEqual(item['media']['frames_read'],60);self.assertEqual(item['media']['fps'],'6')
            self.assertEqual(item['media']['duration'],10.);self.assertEqual(item['full_decode_exit'],0)
            self.assertFalse(item['user_adoption']);self.assertFalse(item['uploaded'])
            self.assertEqual(p.sha(item['output']),item['sha256'])
        out=Path(result['results'][0]['output'])
        frame=subprocess.run(['ffmpeg','-v','error','-ss','7','-i',str(out),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
        def pixel(x,y):return tuple(frame[(y*64+x)*3:(y*64+x+1)*3])
        self.assertGreater(pixel(1,48)[0],150);self.assertLess(pixel(1,48)[2],60)
        self.assertGreater(pixel(62,48)[2],150);self.assertLess(pixel(62,48)[0],60)
        self.assertFalse(any(all(c>220 for c in pixel(x,y)) for x in range(64) for y in range(75,96)))
        def amplitude(path,start,frequency,gain=None,stereo=False):
            cmd=['ffmpeg','-v','error','-ss',str(start),'-i',str(path),'-t','0.5','-vn']
            filters=[]
            if gain is not None:filters.append('volume='+str(gain))
            if stereo:filters.append('aformat=sample_fmts=fltp:channel_layouts=stereo')
            if filters:cmd+=['-af',','.join(filters)]
            raw=subprocess.run(cmd+['-ac','1','-ar','48000','-f','s16le','-'],capture_output=True,check=True).stdout
            samples=array.array('h');samples.frombytes(raw);n=len(samples)
            re_part=sum(v*math.cos(2*math.pi*frequency*i/48000) for i,v in enumerate(samples))
            im_part=sum(v*math.sin(2*math.pi*frequency*i/48000) for i,v in enumerate(samples))
            return 2*math.hypot(re_part,im_part)/n/32768
        actual=amplitude(out,7,220);expected=amplitude(self.root/'music.wav',7,220,.4,stereo=True)
        self.assertAlmostEqual(actual/expected,1,delta=.15)
        self.assertAlmostEqual(amplitude(out,7,440)/amplitude(self.root/'b.mp4',1,440,stereo=True),1,delta=.15)
        self.assertLess(amplitude(out,2,220),.002)  # A is already mixed; never add the common music again.
    def test_real_partial_failure_keeps_successes_and_does_not_retry(self):
        self.real_plan();real_run=subprocess.run;renders=[]
        def process(args,**kwargs):
            if args[0]=='ffmpeg' and '-filter_complex' in args:
                renders.append(list(args))
                if Path(args[-1]).name=='render-1.mp4':return subprocess.CompletedProcess(args,1,'','Synthetic render failure')
            return real_run(args,**kwargs)
        with patch.object(p.subprocess,'run',side_effect=process):
            result=p.join_batch(self.root,self.plan,self.receipt,execute=True)
        self.assertFalse(result['ok']);self.assertEqual(result['state'],'partial');self.assertEqual(len(renders),3)
        self.assertEqual([x['state'] for x in result['results']],['rendered','failed','rendered'])
        hashes={x['output']:p.sha(x['output']) for x in result['results'] if x['state']=='rendered'}
        with patch.object(p.subprocess,'run') as process:
            with self.assertRaisesRegex(ValueError,'JOIN_BATCH_OUTPUT_EXISTS|JOIN_BATCH_ALREADY_ATTEMPTED'):
                p.join_batch(self.root,self.plan,self.receipt,execute=True)
        process.assert_not_called();self.assertEqual(hashes,{path:p.sha(path) for path in hashes})
        self.assertFalse(json.loads(self.receipt_path.read_text())['automatic_retry'])
    def test_output_created_during_render_is_not_replaced(self):
        self.real_plan();self.plan['variants']=self.plan['variants'][:1];real_run=subprocess.run
        target=self.root/self.plan['variants'][0]['output']
        def process(args,**kwargs):
            if args[0]=='ffmpeg' and '-filter_complex' in args:
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'user-created-during-render')
            return real_run(args,**kwargs)
        with patch.object(p.subprocess,'run',side_effect=process):
            result=p.join_batch(self.root,self.plan,self.receipt,execute=True)
        self.assertFalse(result['ok']);self.assertEqual(target.read_bytes(),b'user-created-during-render')
    def test_acceptance_change_during_render_cannot_publish_a_candidate(self):
        self.real_plan();self.plan['variants']=self.plan['variants'][:1];real_run=subprocess.run
        def process(args,**kwargs):
            result=real_run(args,**kwargs)
            if args[0]=='ffmpeg' and '-filter_complex' in args:
                self.f.put('accept.json',{'user_adoption':{'status':'rejected'}})
            return result
        with patch.object(p.subprocess,'run',side_effect=process):
            result=p.join_batch(self.root,self.plan,self.receipt,execute=True)
        self.assertFalse(result['ok']);self.assertFalse((self.root/self.plan['variants'][0]['output']).exists())
    def test_published_output_hand_edit_cannot_inherit_decoded_media_receipt(self):
        self.real_plan();self.plan['variants']=self.plan['variants'][:1];real_link=p.os.link
        target=self.root/self.plan['variants'][0]['output']
        def publish(src,dst,*args,**kwargs):
            real_link(src,dst,*args,**kwargs)
            target.write_bytes(b'user edit after the no-clobber publish')
        with patch.object(p.os,'link',side_effect=publish):
            result=p.join_batch(self.root,self.plan,self.receipt,execute=True)
        item=result['results'][0]
        self.assertFalse(result['ok']);self.assertEqual(item['state'],'failed')
        self.assertIn('OUTPUT_CHANGED_AFTER_PUBLICATION',item['error'])
        self.assertNotIn('media',item);self.assertNotIn('sha256',item)
        self.assertEqual(target.read_bytes(),b'user edit after the no-clobber publish')
    def test_delivery_parent_symlink_created_during_render_is_rejected(self):
        self.real_plan();self.plan['variants']=self.plan['variants'][:1];real_run=subprocess.run
        outside=self.root/'outside-project';outside.mkdir();delivery=self.project/'交付'
        def process(args,**kwargs):
            result=real_run(args,**kwargs)
            if args[0]=='ffmpeg' and '-filter_complex' in args:delivery.symlink_to(outside,target_is_directory=True)
            return result
        with patch.object(p.subprocess,'run',side_effect=process):
            result=p.join_batch(self.root,self.plan,self.receipt,execute=True)
        self.assertFalse(result['ok']);self.assertEqual(list(outside.iterdir()),[])
    def test_receipt_parent_redirect_during_render_never_writes_outside_evidence(self):
        self.real_plan();self.plan['variants']=self.plan['variants'][:1];real_run=subprocess.run
        outside=self.root/'outside-evidence';outside.mkdir();evidence=self.project/'evidence'
        def process(args,**kwargs):
            result=real_run(args,**kwargs)
            if args[0]=='ffmpeg' and '-filter_complex' in args:
                evidence.rename(self.project/'preserved-evidence');evidence.symlink_to(outside,target_is_directory=True)
            return result
        with patch.object(p.subprocess,'run',side_effect=process):
            with self.assertRaisesRegex(ValueError,'JOIN_BATCH_RECEIPT_PATH_CHANGED'):
                p.join_batch(self.root,self.plan,self.receipt,execute=True)
        self.assertEqual(list(outside.iterdir()),[])
        self.assertTrue((self.project/'preserved-evidence/batch-receipt.json').is_file())

if __name__=='__main__':unittest.main()
