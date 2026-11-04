import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import console_template as ct
import console_content as cc
class DirectorStoryboardTests(unittest.TestCase):
 def setUp(self):self.c=ct.contract_for({'template_id':ct.DIRECTOR_ID,'shot_count':4})
 def fixture(self):
  rows=copy.deepcopy(self.c['styles'])
  for row in rows:
   for c in row:c['value']=''
  def put(coord,p):rows[int(coord[1:])-1][ord(coord[0])-65].update(p)
  for k,v in self.c['fixed_labels'].items():put(k,{'value':v})
  put('A1',{'value':'TEST｜导演稿'});put('J2',{'value':'03 粗分镜','data_validation':self.c['current_node_validation']})
  return {'revision':1,'ranges':[{'row_indices':list(range(1,9)),'col_indices':list('ABCDEFGHIJ'),'cells':rows}]},copy.deepcopy(self.c['layout'])
 def test_dynamic_shot_rows_and_identity(self):
  d,l=self.fixture();self.assertEqual(ct.validate(self.c,d,l,'TEST')['styles_checked'],80)
  self.assertEqual(self.c['range'],'A1:J8');self.assertEqual(self.c['slots']['original_copy'],['F5','F6','F7','F8'])
 def test_color_and_stage_are_required(self):
  for rc,key in [((4,5),'background_color'),((1,9),'data_validation')]:
   d,l=self.fixture();cell=d['ranges'][0]['cells'][rc[0]][rc[1]]
   if key=='background_color':cell['cell_styles'][key]='#FFFFFF'
   else:cell.pop(key)
   with self.assertRaisesRegex(ValueError,'CONSOLE_FORMAT_MISMATCH'):ct.validate(self.c,d,l,'TEST')
 def test_no_management_slots_or_invalid_shot_counts(self):
  for slot in ['structure','video_prompt','task_cost','threads','actual_ai']:
   with self.assertRaisesRegex(ValueError,'SLOT_NOT_DISPLAYED'):ct.slot_coordinate(self.c,slot,None)
  for n in [None,0,101,True,2.5]:
   with self.assertRaises(ValueError):ct.contract_for({'template_id':ct.DIRECTOR_ID,'shot_count':n})
 def test_image_reference_retained_and_distinct_shot_columns(self):
  old={'rich_text':[{'type':'link','text':'来源','link':'https://example.com/a'}]}
  with self.assertRaisesRegex(ValueError,'drop existing'):ct.plan_patch(self.c,'source_screenshots',0,old,{'value':'new'})
  self.assertEqual(ct.slot_coordinate(self.c,'storyboard_images',1),'C6')
  with self.assertRaises(ValueError):ct.slot_coordinate(self.c,'script',4)
 def test_dialogue_guard_and_original_preservation(self):
  with self.assertRaisesRegex(ValueError,'A_STORY_BODY_ONLY'):cc.preflight('dialogue',{'value':'B段接点说明'})
  with self.assertRaisesRegex(ValueError,'original_copy'):cc.preflight('original_copy',{'value':'改编方向：增加一句'})
  cc.preflight('dialogue',{'value':'带土：卡卡西，你给我等着'})
 def test_native_feishu_style_roundtrip(self):
  # Observed in SK008: normal weight is absent and equal B/C widths coalesce.
  d,l=self.fixture()
  for ri,row in enumerate(d['ranges'][0]['cells'],1):
   if ri not in (1,4):
    for cell in row:cell['cell_styles'].pop('font_weight',None)
  l['column_widths']=[{'cols':a,'type':t,'width':w} for a,t,w in [('A:A','custom',70),('B:C','custom',220),('D:D','custom',70),('E:E','custom',85),('F:F','custom',210),('G:G','custom',260),('H:H','custom',180),('I:I','custom',140),('J:J','custom',90),('K:T','default',105)]]
  self.assertTrue(ct.validate(self.c,d,l,'TEST')['ok'])
  d['ranges'][0]['cells'][4][1]['cell_styles']['font_weight']='bold'
  with self.assertRaisesRegex(ValueError,'CONSOLE_FORMAT_MISMATCH'):ct.validate(self.c,d,l,'TEST')
if __name__=='__main__':unittest.main()
