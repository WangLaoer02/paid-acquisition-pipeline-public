"""Story-only body, visible production remarks and protected reference behavior."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import console_content as content
import console_template as template

class StoryCopyStandardTests(unittest.TestCase):
    def test_scene_dialogue_and_game_benefit_remain_usable(self):
        story='【1｜家中】\n动作：甲抬头接电话。\n乙：“我抽到了角色，一口气通关800关。”'
        for slot in ['original_copy','script']:
            content.preflight(slot,{'value':story})

    def test_production_notes_cannot_be_hidden_in_story(self):
        for slot in ['original_copy','script','structure']:
            for text in ['B段\n角色素材和谐版','镜头6｜接对应B段','分支：角色版台词与对应B段配对。','Ｂ段衔接：看片确定接点']:
                with self.subTest(slot=slot,text=text):
                    with self.assertRaisesRegex(ValueError,'A_STORY_BODY_ONLY'):
                        content.preflight(slot,{'value':text})

    def test_rich_text_is_checked_too(self):
        with self.assertRaisesRegex(ValueError,'A_STORY_BODY_ONLY'):
            content.preflight('script',{'rich_text':[{'type':'text','text':'接B段说明'}]})

    def test_actual_dialogue_can_mention_segment_name(self):
        content.preflight('script',{'value':'【1｜剪辑室】\n甲：“我把B段放哪里？”'})

    def test_mindmap_dump_requires_readable_format(self):
        for slot in ['original_copy','script']:
            with self.assertRaisesRegex(ValueError,'STORY_READABLE_FORMAT_REQUIRED'):
                content.preflight(slot,{'value':'标题\n  场景\n    家中\n  A段\n    甲\n      动作\n        接电话'})

    def test_visible_remarks_retain_link_and_template_style(self):
        contract=json.loads(template.CONTRACT.read_text())
        old={'cell_styles':{'font_size':13},'rich_text':[{'type':'link','text':'已有交付','link':'https://example.com/delivery'}]}
        payload={'rich_text':[{'type':'text','text':'备注｜B段衔接与制作说明\nB段候选：待核。'}]+copy.deepcopy(old['rich_text'])}
        content.preflight('remarks',payload)
        coord,after=template.plan_patch(contract,'remarks',None,old,payload)
        self.assertEqual(coord,contract['slots']['nonpaid_delivery'])
        self.assertEqual(after['cell_styles'],old['cell_styles'])
        self.assertEqual(template.reference_set(after),template.reference_set(old))

    def test_cell_note_is_not_the_visible_remarks_box(self):
        with self.assertRaisesRegex(ValueError,'CONSOLE_NOTES_FORBIDDEN'):
            content.preflight('remarks',{'value':'备注','note':'hidden B段 instructions'})

    def test_empty_story_and_unrelated_slots_are_not_reformatted(self):
        content.preflight('original_copy',{'value':''})
        content.preflight('script',{'value':'待准备；按本项目实际输入填写'})
        content.preflight('requirements',{'value':'需交付A段与B段两部分'})

if __name__=='__main__':unittest.main()
