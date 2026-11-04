import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import console_template as ct
import workflow_state as ws
class ReceiverCompactTests(unittest.TestCase):
 def config(self):
  return {'project_id':'SK010','template_id':ct.DIRECTOR_ID,'layout_profile':'receiver-compact-2','shot_count':3,'shot_ids':['SC-01','SC-04','SC-05'],'sheet_name':'SK010｜海上找清静'}
 def test_compact_layout_preserves_shot_identifiers(self):
  c=ct.director_contract(self.config())
  self.assertEqual(c['fixed_labels']['A3'],'SC-01')
  self.assertEqual(c['fixed_labels']['A4'],'SC-04')
  self.assertEqual(c['fixed_labels']['A5'],'SC-05')
  self.assertEqual(c['slots']['script'],['G3','G4','G5'])
  self.assertEqual(c['slots']['current_node'],'J1')
  self.assertEqual(c['state_binding']['cell'],'J1')
  self.assertEqual(c['state_binding']['identity_sheet_name'],'SK010｜海上找清静')
 def test_duplicate_or_missing_shots_fail(self):
  for ids in [['SC-01','SC-01','SC-05'],['SC-01','SC-04']]:
   c=self.config();c['shot_ids']=ids
   with self.assertRaises(ValueError):ct.director_contract(c)
 def test_compact_validation_uses_real_sheet_identity_and_stage(self):
  c=ct.director_contract(self.config());rows=copy.deepcopy(c['styles'])
  for row in rows:
   for cell in row:cell['value']=''
  def put(coord,value):rows[int(coord[1:])-1][ord(coord[0])-65].update(value)
  for pos,value in c['fixed_labels'].items():put(pos,{'value':value})
  put('J1',{'value':'03 粗分镜','data_validation':c['current_node_validation']})
  data={'revision':1,'ranges':[{'row_indices':list(range(1,6)),'col_indices':list('ABCDEFGHIJ'),'cells':rows}]}
  layout=copy.deepcopy(c['layout']);layout['sheet_name']='SK010｜海上找清静'
  self.assertTrue(ct.validate(c,data,layout,'SK010')['ok'])
  layout['sheet_name']='SK011｜其他项目'
  with self.assertRaisesRegex(ValueError,'identity'):ct.validate(c,data,layout,'SK010')
 def test_positive_state_binding_reads_stage_from_shifted_row(self):
  source={'spreadsheet_token':'s','sheet_id':'id','anchor_cell':'I1','anchor_value':'当前阶段','cell':'J1','identity_sheet_name':'SK010｜海上找清静'}
  def fake(command,source,flags,payload=None):
   if command=='+sheet-info':return {'sheet_id':'id','sheet_name':source['identity_sheet_name']}
   return {'has_more':False,'ranges':[{'row_indices':[1],'col_indices':['I','J'],'cells':[[{'value':'当前阶段'},{'value':'03 粗分镜','data_validation':{'type':'list'}}]]}]}
  with patch.object(ws,'call',side_effect=fake):self.assertEqual(ws.read_source(source),('s:id:J1','03 粗分镜'))
 def test_sheet_identity_cannot_be_replaced_by_source_title(self):
  source={'spreadsheet_token':'s','sheet_id':'id','anchor_cell':'I1','anchor_value':'当前阶段','cell':'J1','identity_sheet_name':'SK010｜海上找清静'}
  def fake(command,source,flags,payload=None):
   if command=='+sheet-info':return {'sheet_id':'id','sheet_name':'错误项目'}
   raise AssertionError('must stop on wrong identity')
  with patch.object(ws,'call',side_effect=fake):
   with self.assertRaisesRegex(ValueError,'identity'):ws.read_source(source)
if __name__=='__main__':unittest.main()
