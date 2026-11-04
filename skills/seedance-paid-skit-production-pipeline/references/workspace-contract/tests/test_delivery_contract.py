"""Requirement omissions, semantic mapping, revision loss and deployed-copy drift."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import delivery_contract as d
import workflow_deployment as deploy
import workflow_node as node
import workflow_state as state
import storyboard_parity as sp
import reference_scope as rs

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for n in ['out.mp4','visual.txt']: (self.root/n).write_text('synthetic-'+n)
        self.requirements={'schema_version':1,'source_ref':'synthetic:user-request','requirements':[{'id':k,'scope':'A+B','criterion':'check '+k,'source_ref':'synthetic:rule','allow_not_applicable':False} for k in sorted(d.BASE_REQUIREMENTS)]}
        next(r for r in self.requirements['requirements'] if r['id']=='watermark')['expected']={'angle':90}
        self.review={'schema_version':1,'requirements_sha256':self.reqsha(),'outputs':[dict(self.proof('out.mp4'),checks=[{'id':r['id'],'status':'recorded','source_ref':'synthetic:observer','output_sha256':d.digest(self.root/'out.mp4'),'evidence':[self.proof('visual.txt')],'observed':{'angle':90}} for r in self.requirements['requirements']])]}
    def tearDown(self):self.tmp.cleanup()
    def proof(self,n):return {'path':n,'sha256':d.digest(self.root/n)}
    def reqsha(self):return hashlib.sha256(json.dumps(self.requirements,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    def test_complete_is_only_ready_for_semantic_review(self):
        r=d.inspect(self.root,self.requirements,self.review);self.assertTrue(r['coverage_complete']);self.assertFalse(r['semantic_pass_inferred']);self.assertFalse(r['listening_inferred']);self.assertFalse(r['user_adoption_inferred'])
    def test_missing_disclaimer_check_fails(self):
        self.review['outputs'][0]['checks']=[x for x in self.review['outputs'][0]['checks'] if x['id']!='disclaimer']
        self.assertFalse(d.inspect(self.root,self.requirements,self.review)['coverage_complete'])
    def test_omitting_watermark_from_requirements_fails(self):
        self.requirements['requirements']=[x for x in self.requirements['requirements'] if x['id']!='watermark']
        with self.assertRaises(ValueError):d.inspect(self.root,self.requirements,self.review)
    def test_wrong_project_angle_fails(self):
        next(x for x in self.review['outputs'][0]['checks'] if x['id']=='watermark')['observed']['angle']=0
        self.assertFalse(d.inspect(self.root,self.requirements,self.review)['coverage_complete'])
    def test_updated_user_angle_invalidates_old_review(self):
        next(x for x in self.requirements['requirements'] if x['id']=='watermark')['expected']['angle']=180
        with self.assertRaises(ValueError):d.inspect(self.root,self.requirements,self.review)
    def test_stale_output_and_evidence_fails(self):
        for n in ['out.mp4','visual.txt']:
            old=(self.root/n).read_bytes();(self.root/n).write_bytes(b'new')
            with self.assertRaises(ValueError):d.inspect(self.root,self.requirements,self.review)
            (self.root/n).write_bytes(old)
    def test_baked_b_not_applicable_needs_real_source(self):
        req=next(x for x in self.requirements['requirements'] if x['id']=='disclaimer');req['allow_not_applicable']=True;self.review['requirements_sha256']=self.reqsha()
        chk=next(x for x in self.review['outputs'][0]['checks'] if x['id']=='disclaimer');chk.update(status='not_applicable',reason='B baked in actual source',source_ref='synthetic:b-frame')
        self.assertTrue(d.inspect(self.root,self.requirements,self.review)['coverage_complete']);del chk['reason'];self.assertFalse(d.inspect(self.root,self.requirements,self.review)['coverage_complete'])
    def test_requirements_reject_blank_or_nontext_fields(self):
        for value in (' \n\t', ['synthetic:source'], {'text':'check'}, 1):
            for field in ('source_ref','scope','criterion'):
                with self.subTest(value=value,field=field):
                    requirements=copy.deepcopy(self.requirements)
                    requirements['requirements'][0][field]=value
                    review=copy.deepcopy(self.review)
                    review['requirements_sha256']=hashlib.sha256(json.dumps(requirements,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                    self.assertRaises(ValueError,d.inspect,self.root,requirements,review)
            with self.subTest(value=value,field='requirements.source_ref'):
                requirements=copy.deepcopy(self.requirements);requirements['source_ref']=value
                review=copy.deepcopy(self.review)
                review['requirements_sha256']=hashlib.sha256(json.dumps(requirements,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                self.assertRaises(ValueError,d.inspect,self.root,requirements,review)
    def test_recorded_check_needs_nonblank_text_source(self):
        for value in (' \n\t',['synthetic:source'],{'source':'synthetic'},1):
            with self.subTest(value=value):
                review=copy.deepcopy(self.review)
                review['outputs'][0]['checks'][0]['source_ref']=value
                self.assertFalse(d.inspect(self.root,self.requirements,review)['coverage_complete'])
    def test_not_applicable_requires_true_boolean_and_text_explanation(self):
        for value in ('false','true',1,['true'],{'allowed':True}):
            with self.subTest(value=value,field='allow_not_applicable'):
                requirements=copy.deepcopy(self.requirements)
                requirements['requirements'][0]['allow_not_applicable']=value
                review=copy.deepcopy(self.review)
                review['requirements_sha256']=hashlib.sha256(json.dumps(requirements,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                review['outputs'][0]['checks'][0].update(status='not_applicable',reason='synthetic exception',source_ref='synthetic:rule',evidence=[])
                self.assertFalse(d.inspect(self.root,requirements,review)['coverage_complete'])
        self.requirements['requirements'][0]['allow_not_applicable']=True
        self.review['requirements_sha256']=self.reqsha()
        for field in ('reason','source_ref'):
            for value in (' \n\t',['synthetic:source'],{'text':'exception'},1):
                with self.subTest(value=value,field=field):
                    review=copy.deepcopy(self.review)
                    review['outputs'][0]['checks'][0].update(status='not_applicable',reason='synthetic exception',source_ref='synthetic:rule')
                    review['outputs'][0]['checks'][0][field]=value
                    self.assertFalse(d.inspect(self.root,self.requirements,review)['coverage_complete'])
    def test_current_user_original_choice_is_valid_if_in_real_enum(self):
        m={'requester':{'value':'原创','source_ref':'synthetic:latest-user'},'designer':{'value':'D','source_ref':'synthetic:designer'},'filename_sha256':hashlib.sha256(b'actual.mp4').hexdigest()}
        f={'source_ref':'synthetic:current-fields','requester':['原创'],'designer':['D']}
        self.assertTrue(d.verify_mapping(m,f,'actual.mp4')['mapping_verified']);self.assertFalse(d.verify_mapping(m,f,'actual.mp4')['upload_authorized'])
        m['designer']['value']='guessed';self.assertRaises(ValueError,d.verify_mapping,m,f,'actual.mp4')
    def test_suffix_without_mapping_source_is_rejected(self):
        self.assertRaises(ValueError,d.verify_mapping,{'requester':{'value':'原创'},'designer':{'value':'D'},'filename_sha256':hashlib.sha256(b'actual.mp4').hexdigest()},{'requester':['原创'],'designer':['D'],'source_ref':'synthetic:fields'},'actual.mp4')
    def test_revision_is_idempotent_and_cannot_overwrite(self):
        p=self.root/'out.mp4';r=d.store_revision(p,self.root/'store','V001',d.digest(p));self.assertEqual(r,d.store_revision(p,self.root/'store','V001',d.digest(p)))
        p.write_text('new bytes');self.assertRaises(ValueError,d.store_revision,p,self.root/'store','V001',d.digest(p))
        r2=d.store_revision(p,self.root/'store','V002',d.digest(p));self.assertNotEqual(r['sha256'],r2['sha256']);self.assertEqual(d.digest(r['path']),r['sha256'])
    def test_business_alias_backs_up_old_and_protects_user_change(self):
        src=self.root/'out.mp4';r=d.store_revision(src,self.root/'store','V002',d.digest(src));alias=self.root/'business.mp4';alias.write_text('old');old=d.digest(alias)
        d.promote_alias(r['path'],alias,self.root/'store',old);self.assertEqual(d.digest(self.root/'store/previous'/old/alias.name),old)
        alias.write_text('user edit');self.assertRaises(ValueError,d.promote_alias,r['path'],alias,self.root/'store',old);self.assertEqual(alias.read_text(),'user edit')
    def test_node_gate_requires_delivery_even_if_generic_checks_all_pass(self):
        c=node.get_contract('B04');record={'node':'B04','release_id':c['release_id'],'checks':[{'id':g['id'],'status':'pass','evidence':[self.proof('visual.txt')]} for g in c['gate']]};p=self.root/'gate.json';p.write_text(json.dumps(record))
        with patch.object(node,'ROOT',self.root),patch.object(node,'get_contract',return_value=c):r=node.inspect_evidence('B04',p)
        self.assertFalse(r['ready_for_semantic_review']);self.assertIn('DELIVERY_CONTRACT_MISSING',r['missing_or_not_passed']);self.assertIn('STORYBOARD_CONTRACT_MISSING',r['missing_or_not_passed'])
    def test_node_accepts_complete_pinned_delivery_for_semantic_review_only(self):
        c=node.get_contract('B04')
        unit={'id':'source-1','start':0,'end':2,**{k:'synthetic source observation' for k in rs.CONTENT},'evidence':[self.proof('visual.txt')]}
        source={'schema':'reference-source-v1','source_id':'synthetic','duration_seconds':2,'video':self.proof('out.mp4'),'units':[unit]}
        (self.root/'reference-source.json').write_text(json.dumps(source))
        selection={'schema':'reference-selection-v1','project_id':'synthetic-project','revision':'1','authority':{'source_ref':'fixture:current-user','revision':'1'},'source':self.proof('reference-source.json'),'range':{'start':0,'end':2},'context_exceptions':[]}
        (self.root/'selection.json').write_text(json.dumps(selection))
        scope=rs.binding(rs.packet(self.root,'selection.json'))
        self.requirements['reference_scope']=scope;self.review['reference_scope']=scope
        self.review['requirements_sha256']=self.reqsha()
        req=self.root/'requirements.json';rev=self.root/'review.json';req.write_text(json.dumps(self.requirements));rev.write_text(json.dumps(self.review))
        record={'node':'B04','release_id':c['release_id'],'checks':[{'id':g['id'],'status':'pass','evidence':[self.proof('visual.txt')]} for g in c['gate']],'delivery_contract':{'requirements_path':req.name,'review_path':rev.name,'requirements_file_sha256':d.digest(req),'review_file_sha256':d.digest(rev)}}
        shot={'id':'SC-01','characters':'fixture','action':'turn','dialogue':'hello','camera':'wide','sound':'voice'}
        record['reference_scope']=scope
        script={'schema':'storyboard-parity-v1','source_ref':'synthetic:script','revision':'1','shots':[shot]}
        script['reference_scope']=scope
        (self.root/'probe.json').write_text(json.dumps({'video_sha256':d.digest(self.root/'out.mp4'),'frames':20,'fps':10}))
        parity={'schema':'storyboard-review-v1','script_sha256':sp.fingerprint(script),'observer':'test','observed_at':'2026-10-29','video':self.proof('out.mp4'),'probe':self.proof('probe.json'),'complete_audio_reviewed':True,'shots':[{'id':'SC-01','in_frame':0,'out_frame':20,'expected_sha256':sp.fingerprint(shot),'actual_dialogue':'hello','frame_evidence':self.proof('visual.txt'),'checks':{f:{'status':'match','observation':'isolated fixture'} for f in sp.FIELDS}}]}
        record['storyboard_contract']={}
        for key,value in [('script',script),('review',parity),('latest',script)]:
            name='parity-'+key+'.json';(self.root/name).write_text(json.dumps(value));record['storyboard_contract'][key]=self.proof(name)
        p=self.root/'gate.json';p.write_text(json.dumps(record))
        with patch.object(node,'ROOT',self.root),patch.object(node,'get_contract',return_value=c):
            r=node.inspect_evidence('B04',p,'selection.json');self.assertTrue(r['ready_for_semantic_review']);self.assertFalse(r['gate_pass_inferred'])
            (self.root/'other.mp4').write_text('different output');parity['video']=self.proof('other.mp4')
            (self.root/'probe.json').write_text(json.dumps({'video_sha256':parity['video']['sha256'],'frames':20,'fps':10}));parity['probe']=self.proof('probe.json')
            (self.root/'parity-review.json').write_text(json.dumps(parity));record['storyboard_contract']['review']=self.proof('parity-review.json');p.write_text(json.dumps(record))
            mismatch=node.inspect_evidence('B04',p,'selection.json');self.assertIn('STORYBOARD_DELIVERY_VIDEO_MISMATCH',mismatch['missing_or_not_passed']);self.assertFalse(mismatch['ready_for_semantic_review'])
            # Updating only the Gate wrapper cannot revalidate old nested scripts.
            selection['revision']='2';(self.root/'selection.json').write_text(json.dumps(selection))
            record['reference_scope']=rs.binding(rs.packet(self.root,'selection.json'));p.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'REFERENCE_SCOPE_CHANGED'):
                node.inspect_evidence('B04',p,'selection.json')
            # Even if the current script is rebound, old delivery evidence rejects.
            for key in ('script','latest'):
                script['reference_scope']=record['reference_scope'];name='parity-'+key+'.json'
                (self.root/name).write_text(json.dumps(script));record['storyboard_contract'][key]=self.proof(name)
            parity['script_sha256']=sp.fingerprint(script)
            (self.root/'parity-review.json').write_text(json.dumps(parity));record['storyboard_contract']['review']=self.proof('parity-review.json');p.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'REFERENCE_SCOPE_CHANGED'):
                node.inspect_evidence('B04',p,'selection.json')
            req.write_text('changed');self.assertRaises(ValueError,node.inspect_evidence,'B04',p)

    def test_a14_b04_reject_invalid_delivery_before_semantic_review(self):
        req=self.root/'requirements.json';rev=self.root/'review.json';p=self.root/'gate.json'
        for node_id in ('A14','B04'):
            c=node.get_contract(node_id)
            for invalid in ('blank_criterion','string_false_not_applicable','blank_check_source'):
                with self.subTest(node=node_id,invalid=invalid):
                    requirements=copy.deepcopy(self.requirements);review=copy.deepcopy(self.review)
                    if invalid=='blank_criterion':requirements['requirements'][0]['criterion']=' \n\t'
                    elif invalid=='string_false_not_applicable':
                        requirements['requirements'][0]['allow_not_applicable']='false'
                        review['outputs'][0]['checks'][0].update(status='not_applicable',reason='synthetic exception',source_ref='synthetic:rule',evidence=[])
                    else:review['outputs'][0]['checks'][0]['source_ref']=' \n\t'
                    review['requirements_sha256']=hashlib.sha256(json.dumps(requirements,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                    req.write_text(json.dumps(requirements));rev.write_text(json.dumps(review))
                    record={'node':node_id,'release_id':c['release_id'],'checks':[{'id':g['id'],'status':'pass','evidence':[self.proof('visual.txt')]} for g in c['gate']],'delivery_contract':{'requirements_path':req.name,'review_path':rev.name,'requirements_file_sha256':d.digest(req),'review_file_sha256':d.digest(rev)}}
                    p.write_text(json.dumps(record))
                    with patch.object(node,'ROOT',self.root),patch.object(node,'get_contract',return_value=c):
                        if invalid=='blank_criterion':self.assertRaises(ValueError,node.inspect_evidence,node_id,p)
                        else:
                            result=node.inspect_evidence(node_id,p)
                            self.assertFalse(result['ready_for_semantic_review']);self.assertFalse(result['gate_pass_inferred']);self.assertFalse(result['user_authorization_verified'])
    def test_deleted_sheet_identity_does_not_restore_state(self):
        src={'spreadsheet_token':'synthetic','sheet_id':'s','anchor_cell':'A1','cell':'D1','anchor_value':'real'}
        value={'ranges':[{'row_indices':[1],'col_indices':['A','D'],'cells':[[{'value':''},{'value':''}]]}]}
        with patch.object(state,'call',return_value=value),patch.object(state,'save') as save:
            with self.assertRaisesRegex(ValueError,'STATE_SOURCE_MISSING'):state.read_source(src)
            save.assert_not_called()

class DeploymentTests(unittest.TestCase):
    def test_modified_actual_skill_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'SKILL.md';p.write_text('new CLI contract');files={'SKILL.md':deploy.sha(p)}
            self.assertEqual(deploy.verify_files(root,files),1);p.write_text('old fixed plan');self.assertRaises(ValueError,deploy.verify_files,root,files)
    def test_missing_or_unpinned_installer_fails(self):
        with tempfile.TemporaryDirectory() as folder:self.assertRaises(ValueError,deploy.verify,{'release_id':'test'},[folder])

if __name__=='__main__':unittest.main()
