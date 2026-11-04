import hashlib,json,sys,tempfile,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prompt_contract as p
class PromptContractTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.source=self.root/'current-user.txt';self.source.write_text('isolated latest request: preserve reference motion; five modules')
        self.proof={'path':self.source.name,'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest()}
        self.body='\n'.join('## '+h+'\nvisible creative instructions' for h in p.HEADS);self.payload={'value':self.body};self.review={'schema_version':1,'prompt_sha256':p.sha_text(self.body),'format':'five_modules','mode':'video_replacement','current_user_requirement':self.proof,'reference_video':self.proof,'scope_review':self.proof,'reviewed_prompt_sha256':p.sha_text(self.body),'facets':{n:'explicitly reviewed and retained' for n in p.FACETS},'additions':[]}
    def tearDown(self):self.t.cleanup()
    def test_five_modules_and_review_bound(self):self.assertFalse(p.check(self.payload,self.review,self.root)['creative_accuracy_inferred'])
    def test_missing_module_rejected(self):
        payload={'value':self.body.split('## 全局限制')[0]};self.review['prompt_sha256']=p.sha_text(payload['value'])
        with self.assertRaisesRegex(ValueError,'FIVE_MODULES'):p.check(payload,self.review,self.root)
    def test_zero_content_section_rejected(self):
        self.payload['value']=self.body.replace('## 全局限制\nvisible creative instructions','## 全局限制');self.review['prompt_sha256']=p.sha_text(self.payload['value'])
        with self.assertRaisesRegex(ValueError,'SECTION_EMPTY'):p.check(self.payload,self.review,self.root)
    def test_user_edit_makes_review_stale(self):
        with self.assertRaisesRegex(ValueError,'STALE'):p.check({'value':self.body+' new direction'},self.review,self.root)
    def test_new_action_without_user_source_rejected(self):
        self.review['additions']=[{'description':'invented invitation'}]
        with self.assertRaisesRegex(ValueError,'SOURCE_REQUIRED'):p.check(self.payload,self.review,self.root)
    def test_background_people_separate_from_main_roles(self):
        self.review['facets'].pop('background_people')
        with self.assertRaisesRegex(ValueError,'SCOPE_INCOMPLETE'):p.check(self.payload,self.review,self.root)
    def test_reviewed_text_must_match(self):
        self.review['reviewed_prompt_sha256']='old'
        with self.assertRaisesRegex(ValueError,'SCOPE_REVIEW_STALE'):p.check(self.payload,self.review,self.root)
    def test_latest_adopted_compact_not_forced_to_five_modules(self):
        body='user selected compact motion instructions';review={**self.review,'format':'user_adopted_compact','prompt_sha256':p.sha_text(body),'adopted_prompt_sha256':p.sha_text(body),'reviewed_prompt_sha256':p.sha_text(body),'user_adoption':self.proof}
        self.assertTrue(p.check({'value':body},review,self.root)['ok'])
    def test_compact_requires_actual_adoption_source(self):
        self.review['format']='user_adopted_compact'
        with self.assertRaisesRegex(ValueError,'SOURCE_REQUIRED'):p.check(self.payload,self.review,self.root)
    def test_original_task_does_not_require_replacement_facets(self):
        self.review['mode']='original';self.review.pop('facets');self.review.pop('reference_video');self.assertTrue(p.check(self.payload,self.review,self.root)['ok'])
    def test_changed_source_rejected(self):
        self.source.write_text('new user edit')
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):p.check(self.payload,self.review,self.root)
if __name__=='__main__':unittest.main()
