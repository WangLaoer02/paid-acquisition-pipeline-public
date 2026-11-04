"""No network: invalid clear representation rejected before any Sheet write."""
import unittest,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import console_content as content
import console_template as template
class EmptyContentTests(unittest.TestCase):
    def setUp(self):self.contract=json.loads(template.CONTRACT.read_text())
    def test_business_preflight_rejects_empty_rich_text(self):
        with self.assertRaisesRegex(ValueError,'EMPTY_RICH_TEXT_UNSUPPORTED'):content.preflight('characters',{'rich_text':[]})
    def test_direct_slot_helper_also_rejects_empty_rich_text(self):
        with self.assertRaisesRegex(ValueError,'EMPTY_RICH_TEXT_UNSUPPORTED'):template.plan_patch(self.contract,'characters',0,{'value':'existing user text'},{'rich_text':[]})
    def test_explicit_empty_value_preserves_style(self):
        old={'value':'placeholder','cell_styles':{'font_size':13}}
        _,after=template.plan_patch(self.contract,'script',None,old,{'value':''})
        self.assertEqual(after,{'value':'','cell_styles':{'font_size':13}})
    def test_explicit_clear_cannot_delete_attachment(self):
        old={'rich_text':[{'type':'embed-image','image_token':'fixture-image'}]}
        with self.assertRaisesRegex(ValueError,'drop existing'):template.plan_patch(self.contract,'characters',0,old,{'value':''})
if __name__=='__main__':unittest.main()
