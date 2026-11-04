import json
import copy,unittest
from unittest import mock
from pathlib import Path
import upload_service as service
import rongyao_upload
class AliasTests(unittest.TestCase):
 def setUp(self):
  self.item={'filename':'261020DXX11-video-TM.mp4','sha256':'a'*64,'parameters':{},'provenance':{}}
  self.alias={'record_id':'123','ledger_name':self.item['filename'],'native_name':'261020DXX11-video-TM-37.mp4','sha256':'a'*64,'media':['http://market-sy-ad-static.backend.example.invalid/video/example.mp4']}
  self.api=mock.Mock();self.api.lookup.return_value={'id':'123','name':self.alias['native_name'].removesuffix('.mp4')}
  self.ops=mock.Mock();self.ops.filename.side_effect=lambda x:x
  patch=mock.patch.object(service,'operations',return_value=self.ops);patch.start();self.addCleanup(patch.stop)
 def test_ordinary_records_do_not_infer_or_lookup_alias(self):
  self.assertEqual(service.native_record(self.api,self.item,record_id='123'),{'id':'123','name':self.item['filename'][:-4]});self.api.lookup.assert_not_called()
 def test_explicit_alias_pins_original_id_sha_and_current_exact_name(self):
  self.item['provenance']['listed_native_identity']=self.alias
  self.assertEqual(service.native_record(self.api,self.item,record_id='123'),self.api.lookup.return_value)
  for field,value in [('record_id','999'),('ledger_name','other.mp4'),('sha256','wrong'),('media',[])]:
   row=copy.deepcopy(self.item);row['provenance']['listed_native_identity'][field]=value
   with self.assertRaisesRegex(ValueError,'SNAPSHOT'):service.native_record(self.api,row,record_id='123')
 def test_same_name_other_id_never_adopted(self):
  self.item['provenance']['listed_native_identity']=self.alias;self.api.lookup.return_value={'id':'999','name':self.alias['native_name'][:-4]}
  with self.assertRaisesRegex(ValueError,'IDENTITY'):service.native_record(self.api,self.item,record_id='123')
 def test_verified_receipt_alias_can_be_read_without_editing_original_plan(self):
  record=service.native_record(self.api,self.item,{'record_id':'123','verified_native_identity':self.alias});self.assertEqual(record['id'],'123');self.assertNotIn('listed_native_identity',self.item['provenance'])
 def test_legacy_designer_requires_registered_immutable_enriched_plan(self):
  enriched={**self.item,'provenance':{'source_native_fields':{'设计师':'来源设计师'}}};plan={'items':[enriched]};self.ops.registered_plan.return_value=plan;self.ops.plan_digest.return_value='bound-digest'
  self.assertEqual(service.receipt_designer(self.item,{'designer_intent_plan':{'job_id':'real-job','sha256':'bound-digest'}}),'来源设计师')
  with self.assertRaisesRegex(ValueError,'PLAN_CHANGED'):service.receipt_designer(self.item,{'designer_intent_plan':{'job_id':'real-job','sha256':'wrong'}})
  self.assertIsNone(service.receipt_designer(self.item,{}))
if __name__=='__main__':unittest.main()

import test_designer as _designer
class AliasFinalizeTests(_designer.FinalizeTests):
 def prepare_alias(self):
  proxy=service.operations();proxy.filename=self.ops.filename;proxy.registered_plan=lambda jid:self.ledger.job(jid)
  item=copy.deepcopy(self.item);item['provenance'].update(operation='existing_id_designer_reconciliation_only',listed_native_identity={'record_id':'123','ledger_name':item['filename'],'native_name':item['filename'].replace('.mp4','-37.mp4'),'sha256':item['sha256'],'media':self.good['media']})
  self.ledger.create({'job_id':'metadata','items':[item]});self.args['job_id']='metadata';record={'id':'123','name':item['provenance']['listed_native_identity']['native_name'][:-4]};self.api.lookup.return_value=record;self.good['record']=record;self.bad['record']=record;return record
 def test_alias_finalization_preserves_original_ledger_plan_and_id(self):
  record=self.prepare_alias();original=self.ledger.job('job');self.api.detail_snapshot.side_effect=[self.bad,self.good]
  result=service.finalize_attribution(self.api,self.args,self.root);self.assertTrue(result['ok']);self.api.set_designer.assert_called_once_with(record,'原设计师');self.assertEqual(self.ledger.job('job'),original)
  row=self.ledger.existing(self.item['filename']);self.assertEqual((row['owner'],row['record_id']),('job','123'));receipt=json.loads(row['evidence']);self.assertEqual(receipt['verified_native_identity']['native_name'],record['name']+'.mp4');self.assertEqual(receipt['designer_intent_plan']['job_id'],'metadata');self.api.json.assert_not_called()
 def test_alias_media_mismatch_stops_before_designer_write(self):
  self.prepare_alias();self.api.detail_snapshot.return_value={**self.bad,'media':['different']}
  with self.assertRaisesRegex(ValueError,'ALIAS_MEDIA_MISMATCH'):service.finalize_attribution(self.api,self.args,self.root)
  self.api.set_designer.assert_not_called()
