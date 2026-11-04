import json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class PublicPromptEntryTests(unittest.TestCase):
    def test_prompt_without_current_review_stops_before_online_write(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'payload.json';p.write_text(json.dumps({'value':'creative text only'}))
            r=subprocess.run([sys.executable,str(ROOT/'scripts/console_content.py'),'patch','--project','fictional','--slot','video_prompt','--payload',str(p),'--receipt','must-not-exist.json'],capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode,1);self.assertIn('PROMPT_REVIEW_REQUIRED',r.stderr);self.assertFalse((ROOT/'must-not-exist.json').exists())
    def test_empty_rich_text_stops_before_reading_project(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'payload.json';p.write_text(json.dumps({'rich_text':[]}))
            r=subprocess.run([sys.executable,str(ROOT/'scripts/console_content.py'),'patch','--project','fictional','--slot','characters','--index','0','--payload',str(p),'--receipt','must-not-exist.json'],capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode,1);self.assertIn('EMPTY_RICH_TEXT_UNSUPPORTED',r.stderr);self.assertFalse((ROOT/'must-not-exist.json').exists())
if __name__=='__main__':unittest.main()
