"""A trimmed console is valid without restoring its removed management footer."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import console_template as ct
import workflow_state as state

class CompactConsoleTests(unittest.TestCase):
    def setUp(self):
        self.contract=json.loads((ct.ROOT/'workflow/console-compact-template.json').read_text())
    def fixture(self):
        c=self.contract;rows=copy.deepcopy(c['styles'])
        for row in rows:
            for cell in row:cell['value']=''
        def setv(coord,payload):rows[int(coord[1:])-1][ord(coord[0])-65].update(payload)
        for coord,value in c['fixed_labels'].items():setv(coord,{'value':value})
        setv('A1',{'value':'TEST｜样例 · 项目控制台'})
        setv('E15',{'value':'01 来源分析','data_validation':copy.deepcopy(c['current_node_validation'])})
        data={'revision':1,'has_more':False,'ranges':[{'row_indices':list(range(1,17)),'col_indices':list('ABCDE'),'cells':rows,'truncated':False}]}
        return data,copy.deepcopy(c['layout'])
    def test_trimmed_page_is_valid_with_no_footer(self):
        data,layout=self.fixture();r=ct.validate(self.contract,data,layout,'TEST')
        self.assertEqual(r['styles_checked'],80)
        self.assertNotIn('D42',ct.cells_by_coordinate(data))
    def test_blank_tail_row_count_does_not_require_old_footer(self):
        data,layout=self.fixture();layout['row_heights'].append({'rows':'17:164','type':'auto','height':27})
        ct.validate(self.contract,data,layout,'TEST')
    def test_missing_stage_still_fails_closed(self):
        data,layout=self.fixture();data['ranges'][0]['cells'][14][4].pop('data_validation')
        with self.assertRaisesRegex(ValueError,'single_node:E15'):ct.validate(self.contract,data,layout,'TEST')
    def test_wrong_title_identity_is_rejected(self):
        data,layout=self.fixture();data['ranges'][0]['cells'][0][0]['value']='OTHER｜样例'
        with self.assertRaisesRegex(ValueError,'identity:A1'):ct.validate(self.contract,data,layout,'TEST')
    def test_visible_layout_is_still_checked(self):
        data,layout=self.fixture();layout['row_heights'][0]['height']=1
        with self.assertRaisesRegex(ValueError,'layout:row_heights'):ct.validate(self.contract,data,layout,'TEST')
    def test_removed_slots_cannot_repopulate_the_footer(self):
        for slot in ['requirements','authorization','threads','raw_inputs','checkpoint','nonpaid_delivery']:
            with self.subTest(slot=slot):
                with self.assertRaisesRegex(ValueError,'SLOT_NOT_DISPLAYED'):
                    ct.plan_patch(self.contract,slot,None,{}, {'value':'old footer'})
    def test_remarks_are_separate_and_keep_existing_refs(self):
        old={'rich_text':[{'type':'link','text':'原B段','link':'https://example.com/b'}]}
        payload={'rich_text':[{'type':'text','text':'五条悟版B段候选。'}]+old['rich_text']}
        coord,out=ct.plan_patch(self.contract,'remarks',None,old,payload)
        self.assertEqual(coord,'B16');self.assertEqual(ct.reference_set(out),ct.reference_set(old))
    def test_empty_legacy_page_is_not_misclassified_as_compact(self):
        data,layout=self.fixture();legacy=json.loads(ct.CONTRACT.read_text())
        with self.assertRaisesRegex(ValueError,'CONSOLE_FORMAT_MISMATCH'):ct.validate(legacy,data,layout,'TEST')

class CompactAuthorityTests(unittest.TestCase):
    def source(self):
        return {'spreadsheet_token':'book','sheet_id':'sheet','anchor_cell':'D15','anchor_value':'当前阶段检查点','cell':'E15','identity_cell':'A1','identity_value':'TEST｜样例 · 项目控制台'}
    def response(self,title='TEST｜样例 · 项目控制台'):
        identity={'ranges':[{'cells':[[{'value':title}]],'row_indices':[1],'col_indices':['A']}]}
        stage={'ranges':[{'cells':[[{'value':'当前阶段检查点'},{'value':'01 来源分析','data_validation':{'type':'list'}}]],'row_indices':[15],'col_indices':['D','E']}]}
        return [identity,stage]
    def test_authority_uses_live_title_and_native_stage(self):
        with patch.object(state,'call',side_effect=self.response()):
            self.assertEqual(state.read_source(self.source())[1],'01 来源分析')
    def test_other_project_title_never_reads_or_writes_stage(self):
        with patch.object(state,'call',side_effect=self.response('OTHER｜样例')) as call:
            with self.assertRaisesRegex(ValueError,'identity changed'):state.read_source(self.source())
            self.assertEqual(call.call_count,1)
    def test_identity_is_explicit_not_derived_from_mirror(self):
        source=self.source();source.pop('identity_value')
        with patch.object(state,'call') as call:
            with self.assertRaisesRegex(ValueError,'Explicit project identity'):state.read_source(source)
            call.assert_not_called()

if __name__=='__main__':unittest.main()
