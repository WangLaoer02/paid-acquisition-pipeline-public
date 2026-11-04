"""No remote writes. Tests receipt integrity and duplicate protection."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import rongyao as ry

PARAMS = {'category_type':'117','ai_source':'SD非拼框','origin_type':'1','demand_name':'示例人员4',
          'source_ip':[],'source_type':['小剧场'],'source_direction':['AI'],'gid':'193',
          'role':['宇智波鼬'],'region_type':'','is_redbag':'0'}

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.file = self.state/'sample.mp4'
        self.file.write_bytes(b'isolated local fixture, never upload')
        self.item = {'file':str(self.file),'filename':self.file.name,'sha256':ry.sha256(self.file),
                     'parameters':copy.deepcopy(PARAMS)}
        self.plan = {'job_id':'job1','items':[self.item]}
        self.ledger = ry.Ledger(self.state)
        self.ledger.create(self.plan)
    def tearDown(self):
        self.ledger.db.close()
        self.tmp.cleanup()
    def test_all_fields_explicit(self):
        p=copy.deepcopy(PARAMS);p.pop('demand_name')
        with self.assertRaisesRegex(ValueError,'ALL_FORM_FIELDS_REQUIRED'):ry.params(p)
    def test_multi_values_canonical(self):
        p=copy.deepcopy(PARAMS);p['role']=['佐助','宇智波鼬','佐助']
        self.assertEqual(ry.params(p)['role'],sorted({'佐助','宇智波鼬'}))
    def test_role_required_for_193(self):
        p=copy.deepcopy(PARAMS);p['role']=[]
        with self.assertRaisesRegex(ValueError,'MAIN_ROLE_REQUIRED'):ry.params(p)
    def test_no_path_in_filename(self):
        with self.assertRaisesRegex(ValueError,'INVALID_FILENAME'):ry.filename('../escape.mp4')
    def test_pending_submission_cannot_retry(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'selection_pending')
        with self.assertRaisesRegex(ValueError,'PRIOR_SUBMISSION'):self.ledger.claim('job1',self.item)
    def test_concurrent_job_cannot_claim(self):
        self.ledger.create({'job_id':'job2','items':[self.item]})
        self.ledger.claim('job1',self.item)
        second=ry.Ledger(self.state)
        try:
            with self.assertRaisesRegex(ValueError,'PRIOR_SUBMISSION'):second.claim('job2',self.item)
        finally:second.db.close()
    def test_same_name_different_hash_blocked(self):
        self.ledger.claim('job1',self.item)
        other={**self.item,'sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'DIFFERENT_SHA'):self.ledger.claim('job1',other)
    def test_listed_identical_file_skipped(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'listed','123')
        self.assertEqual(self.ledger.claim('job1',self.item)['record_id'],'123')
    def test_identical_file_changed_attribution_blocked(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'listed','123')
        other=copy.deepcopy(self.item);other['parameters']['region_type']='1149'
        with self.assertRaisesRegex(ValueError,'DIFFERENT_PARAMETERS'):self.ledger.claim('job1',other)
    def test_blocked_before_selection_can_retry(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'blocked_before_selection')
        self.assertIsNone(self.ledger.claim('job1',self.item))
    def test_presend_attribution_correction_can_claim_new_plan(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'blocked_before_selection')
        corrected=copy.deepcopy(self.item);corrected['parameters']['demand_name']='当前有效需求人'
        self.ledger.create({'job_id':'corrected','items':[corrected]})
        self.assertIsNone(self.ledger.claim('corrected',corrected))
        self.assertEqual(self.ledger.existing(self.item['filename'])['owner'],'corrected')
    def test_unknown_attribution_correction_still_cannot_claim(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'submission_unknown')
        corrected=copy.deepcopy(self.item);corrected['parameters']['demand_name']='当前有效需求人'
        self.ledger.create({'job_id':'corrected','items':[corrected]})
        with self.assertRaisesRegex(ValueError,'SAME_FILE_DIFFERENT_PARAMETERS'):
            self.ledger.claim('corrected',corrected)
        self.assertEqual(self.ledger.existing(self.item['filename'])['state'],'submission_unknown')
    def test_listed_attribution_correction_still_cannot_claim(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'listed','123')
        corrected=copy.deepcopy(self.item);corrected['parameters']['demand_name']='当前有效需求人'
        self.ledger.create({'job_id':'corrected','items':[corrected]})
        with self.assertRaisesRegex(ValueError,'SAME_FILE_DIFFERENT_PARAMETERS'):
            self.ledger.claim('corrected',corrected)
        self.assertEqual(self.ledger.existing(self.item['filename'])['record_id'],'123')
    def test_presend_state_still_rejects_same_name_changed_sha(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'blocked_before_selection')
        with self.assertRaisesRegex(ValueError,'SAME_NAME_DIFFERENT_SHA'):
            self.ledger.claim('job1',{**self.item,'sha256':'b'*64})
    def test_renamed_content_cannot_escape_pending_ledger(self):
        self.ledger.claim('job1',self.item)
        other={**self.item,'filename':'renamed.mp4'}
        with self.assertRaisesRegex(ValueError,'SAME_FILE_OTHER_NAME_HELD'):self.ledger.claim('job1',other)
    def test_concurrent_renamed_content_has_only_one_claim(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        barrier=threading.Barrier(2)
        def claim(name):
            ledger=ry.Ledger(self.state)
            try:
                barrier.wait()
                ledger.claim('job1',{**self.item,'filename':name})
                return 'claimed'
            except ValueError as e:return str(e)
            finally:ledger.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(claim,['a.mp4','b.mp4']))
        self.assertCountEqual(results,['claimed','SAME_FILE_OTHER_NAME_HELD'])
    def test_number_conflict_across_different_content(self):
        a={**self.item,'filename':'261020D1-first-原创-37.mp4'}
        self.ledger.claim('job1',a)
        b={**self.item,'filename':'261020D1-second-原创-37.mp4','sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'PRODUCTION_NUMBER_HELD'):self.ledger.claim('job1',b)
    def test_corrected_presend_failure_may_use_new_name(self):
        self.ledger.claim('job1',self.item)
        self.ledger.update('job1',self.item['filename'],'blocked_before_selection')
        self.assertIsNone(self.ledger.claim('job1',{**self.item,'filename':'corrected.mp4'}))
    def test_inheritance_precedence_and_empty_explicit_value(self):
        request={'shared_parameters':{'demand_name':'批次需求人','ai_source':''},
                 'shared_provenance':{'source':'reviewed batch'}}
        item={'inherit_from':{'job_id':'job1','filename':self.file.name},
              'parameters':{'demand_name':'当前需求人'}}
        values,provenance=ry.inherited_parameters(request,item,self.ledger)
        self.assertEqual(values['demand_name'],'当前需求人')
        self.assertEqual(values['ai_source'],'')
        self.assertEqual(values['role'],PARAMS['role'])
        self.assertEqual(provenance['inherited_from']['plan_sha256'],ry.plan_digest(self.plan))
    def test_original_default_does_not_replace_explicit_source(self):
        values,_=ry.inherited_parameters({}, {'inherit_from':{'job_id':'job1','filename':self.file.name}},self.ledger)
        self.assertEqual(values['demand_name'],PARAMS['demand_name'])
        p=copy.deepcopy(PARAMS);p.pop('demand_name')
        values,provenance=ry.inherited_parameters({}, {'parameters':p},self.ledger)
        self.assertEqual(values['demand_name'],'原创')
        self.assertNotIn('requester_explicit_original_override',provenance)
    def test_unknown_inheritance_source_is_not_guessed(self):
        with self.assertRaisesRegex(ValueError,'PARAMETER_SOURCE_NOT_UNIQUE'):
            ry.inherited_parameters({}, {'inherit_from':{'job_id':'job1','filename':'missing.mp4'}},self.ledger)
    def test_batch_same_content_is_rejected_before_copy(self):
        request={'shared_parameters':PARAMS,'items':[
            {'file':str(self.file),'filename':'261020D1-one-原创-37.mp4'},
            {'file':str(self.file),'filename':'261020D2-two-原创-37.mp4'}]}
        ry.save(self.state/'input.json',request)
        with patch.object(ry,'media',return_value={}):
            with self.assertRaisesRegex(ValueError,'DUPLICATE_CONTENT_IN_BATCH'):
                ry.plan(self.state/'input.json',self.state/'result.json',copy_dir=self.state/'copies',state=self.state)
        self.assertFalse((self.state/'copies').exists())
    def test_uncertain_owner_cannot_be_overwritten(self):
        self.ledger.claim('job1',self.item)
        with self.assertRaisesRegex(ValueError,'DOES_NOT_OWN'):self.ledger.update('other',self.item['filename'],'listed','123')
    def test_changed_file_blocks_before_transport(self):
        self.file.write_bytes(b'changed after plan')
        with patch.object(ry,'transport') as external:
            with self.assertRaisesRegex(ValueError,'PLAN_FILE_CHANGED'):ry._upload_registered('job1',self.state)
            external.assert_not_called()
    def test_browser_block_never_retried(self):
        ry.save(self.state/'upload-block.json',{'status':'UPLOAD_CLIENT_BLOCKED'})
        with patch.object(ry,'auth') as auth:
            r=ry.transport('upload',self.item,self.state)
            self.assertEqual(r['status'],'UPLOAD_CLIENT_BLOCKED');auth.assert_not_called()
    def test_explicit_recheck_clears_only_after_verified_list(self):
        old={'status':'UPLOAD_CLIENT_BLOCKED','observed_at':'old'}
        ry.save(self.state/'upload-block.json',old)
        def probe(action,payload,state,**kwargs):
            self.assertEqual(action,'probe-list');self.assertTrue(kwargs['explicit_recheck'])
            self.assertEqual(ry.read(state/'upload-block.json'),old)
            return {'ok':True,'authenticated':True,'entry':'video-list','source':'live_official_video_list'}
        result=ry.recheck_video_list(self.state,probe)
        self.assertTrue(result['block_cleared']);self.assertFalse((self.state/'upload-block.json').exists())
        self.assertEqual(ry.read(result['history_file'])['previous_block'],old)
    def test_failed_recheck_preserves_block(self):
        old={'status':'UPLOAD_CLIENT_BLOCKED'};ry.save(self.state/'upload-block.json',old)
        result=ry.recheck_video_list(self.state,lambda *a,**k:{'ok':False,'status':'UPLOAD_CLIENT_BLOCKED'})
        self.assertFalse(result['block_cleared']);self.assertEqual(ry.read(self.state/'upload-block.json'),old)
    def test_recheck_cannot_be_used_for_upload(self):
        with patch.object(ry,'auth') as auth:
            with self.assertRaisesRegex(ValueError,'RECHECK_IS_READ_ONLY'):
                ry.transport('upload',{},self.state,explicit_recheck=True)
            auth.assert_not_called()
    def test_recheck_does_not_erase_newer_concurrent_block(self):
        ry.save(self.state/'upload-block.json',{'status':'UPLOAD_CLIENT_BLOCKED','observed_at':'old'})
        newer={'status':'UPLOAD_CLIENT_BLOCKED','observed_at':'new'}
        def probe(*a,**k):
            ry.save(self.state/'upload-block.json',newer)
            return {'ok':True,'authenticated':True,'entry':'video-list','source':'live_official_video_list'}
        result=ry.recheck_video_list(self.state,probe)
        self.assertEqual(result['status'],'BLOCK_RECORD_CHANGED');self.assertFalse(result['block_cleared'])
        self.assertEqual(ry.read(self.state/'upload-block.json'),newer)
    def test_auth_only_success_does_not_clear_block(self):
        ry.save(self.state/'upload-block.json',{'status':'UPLOAD_CLIENT_BLOCKED'})
        result=ry.recheck_video_list(self.state,lambda *a,**k:{'ok':True,'authenticated':True})
        self.assertFalse(result['block_cleared']);self.assertTrue((self.state/'upload-block.json').exists())
    def test_upload_failure_after_checkpoint_is_unknown(self):
        def failed(action,payload,state,authorize):
            authorize();return {'ok':False,'status':'CONNECTION_LOST'}
        with patch.object(ry,'transport',side_effect=failed):ry._upload_registered('job1',self.state)
        self.assertEqual(self.ledger.existing(self.file.name)['state'],'submission_unknown')
        with self.assertRaisesRegex(ValueError,'PRIOR_SUBMISSION'):self.ledger.claim('job1',self.item)
    def test_backend_failure_before_selection_has_no_upload(self):
        with patch.object(ry,'transport',return_value={'ok':False,'status':'FORM_STRUCTURE_CHANGED'}):
            ry._upload_registered('job1',self.state)
        self.assertEqual(self.ledger.existing(self.file.name)['state'],'blocked_before_selection')
    def test_selection_does_not_mean_listed(self):
        def selected(action,payload,state,authorize):
            authorize();return {'ok':True,'status':'FILE_SELECTED_PENDING_BACKEND'}
        with patch.object(ry,'transport',side_effect=selected):r=ry._upload_registered('job1',self.state)
        self.assertFalse(r['receipt']['all_listed'])
    def test_reconcile_exact_unique_record(self):
        self.ledger.claim('job1',self.item);self.ledger.update('job1',self.file.name,'submitted_pending')
        with patch.object(ry,'transport',return_value={'ok':True,'rows':[{'name':'sample','record_id':'999'}]}):
            r=ry.reconcile('job1',self.state)
        self.assertTrue(r['receipt']['all_listed']);self.assertFalse(r['receipt']['metadata_verified'])
    def test_ambiguous_reconcile_does_not_mark_success(self):
        self.ledger.claim('job1',self.item);self.ledger.update('job1',self.file.name,'submission_unknown')
        rows=[{'name':'sample','record_id':'1'},{'name':'sample','record_id':'2'}]
        with patch.object(ry,'transport',return_value={'ok':True,'rows':rows}):r=ry.reconcile('job1',self.state)
        self.assertFalse(r['receipt']['all_listed'])
    def test_no_selection_checkpoint_cannot_infer_upload(self):
        self.ledger.claim('job1',self.item)
        with patch.object(ry,'transport') as external:
            r=ry.reconcile('job1',self.state);external.assert_not_called()
        self.assertFalse(r['receipt']['all_listed'])
    def test_plan_separates_generic_video_from_ab_production(self):
        request={'items':[{'file':str(self.file),'parameters':PARAMS}]}
        ry.save(self.state/'manifest.json',request)
        with patch.object(ry,'media',return_value={'full_decode_passed':True}):
            r=ry.plan(self.state/'manifest.json',self.state/'plan.json',state=self.state)
        self.assertTrue(r['ok']);self.assertFalse(r['upload_performed'])
        self.assertNotIn('b_source',ry.read(self.state/'plan.json')['items'][0])
    def test_offline_fixture_can_never_upload(self):
        self.ledger.create({'job_id':'offline','test_only':True,'items':[self.item]})
        with patch.object(ry,'transport') as external:
            r=ry._upload_registered('offline',self.state);external.assert_not_called()
        self.assertEqual(r['status'],'OFFLINE_TEST_PLAN_CANNOT_UPLOAD')
    def test_late_worker_cannot_erase_listed_id(self):
        self.ledger.claim('job1',self.item);self.ledger.update('job1',self.file.name,'listed','123')
        self.ledger.update('job1',self.file.name,'submitted_pending')
        self.assertEqual(self.ledger.existing(self.file.name)['record_id'],'123')
    def test_legacy_failed_plan_rejected(self):
        ry.save(self.state/'legacy.json',{'scope':'local_preparation_only','can_proceed_to_ui':False})
        with self.assertRaisesRegex(ValueError,'LEGACY_PREPARATION_NOT_READY'):
            ry.plan(self.state/'legacy.json',self.state/'new.json',state=self.state)
    def test_legacy_plan_hash_cannot_drift(self):
        source={'scope':'local_preparation_only','can_proceed_to_ui':True,'blocked':[],
                'items':[{'state':'ready_for_ui','upload_file':str(self.file),'filename':self.file.name,
                          'sha256':'0'*64,'form_values':PARAMS}]}
        ry.save(self.state/'legacy.json',source)
        with self.assertRaisesRegex(ValueError,'LEGACY_PLAN_FILE_CHANGED'):
            ry.plan(self.state/'legacy.json',self.state/'new.json',state=self.state)
    def test_real_process_handshake_commits_before_select(self):
        # Standalone local Node fixture; no Chrome, credentials or remote requests.
        bridge=self.state/'upload_bridge.mjs'
        bridge.write_text('''import fs from 'node:fs';import readline from 'node:readline';
const input=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
const rl=readline.createInterface({input:process.stdin});
console.log(JSON.stringify({event:'before_file_selection'}));
rl.on('line',line=>{console.log(JSON.stringify({event:'result',result:{ok:line==='SELECT'&&fs.existsSync(input.marker)}}));rl.close();});
process.stdin.on('end',()=>process.exit(0));
''')
        marker=self.state/'committed'
        def commit():marker.write_text('durable checkpoint')
        with patch.object(ry,'ROOT',self.state),patch.object(ry,'command_json',return_value={'ok':True}):
            r=ry.transport('upload',{'marker':str(marker)},self.state,commit)
        self.assertTrue(r['ok']);self.assertTrue(marker.exists())
        self.assertEqual(list(self.state.glob('request-*.json')),[])
    def test_checkpoint_failure_never_sends_select(self):
        bridge=self.state/'upload_bridge.mjs'
        marker=self.state/'selected'
        bridge.write_text('''import fs from 'node:fs';import readline from 'node:readline';
const input=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
const rl=readline.createInterface({input:process.stdin});
console.log(JSON.stringify({event:'before_file_selection'}));
rl.on('line',line=>{if(line==='SELECT')fs.writeFileSync(input.marker,'unexpected');});
''')
        def fail():raise ValueError('LOCAL_CHECKPOINT_FAILED')
        with patch.object(ry,'ROOT',self.state),patch.object(ry,'command_json',return_value={'ok':True}):
            with self.assertRaisesRegex(ValueError,'LOCAL_CHECKPOINT_FAILED'):
                ry.transport('upload',{'marker':str(marker)},self.state,fail)
        self.assertFalse(marker.exists());self.assertEqual(list(self.state.glob('request-*.json')),[])

if __name__=='__main__':unittest.main()
