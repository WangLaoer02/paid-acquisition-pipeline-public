import importlib.util,json,subprocess,sys,tempfile,unittest,shutil
from unittest import mock
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import receiver_config
class PublicPortability(unittest.TestCase):
 def run_cli(self,*args,cwd=ROOT):
  p=subprocess.run([sys.executable,*map(str,args)],cwd=cwd,capture_output=True,text=True)
  return p,json.loads(p.stdout or p.stderr)
 def test_empty_workspace_and_no_author_account(self):
  with tempfile.TemporaryDirectory() as tmp:
   target=Path(tmp)/'new'
   p,d=self.run_cli(ROOT/'tools/public_release.py','init','--workspace',target);self.assertEqual(p.returncode,0,d)
   cfg=json.loads((target/'receiver.local.json').read_text());self.assertIsNone(cfg['writer_host']);self.assertIsNone(cfg['rules_center'])
   p,d=self.run_cli(target/'scripts/workflow_node.py','list');self.assertEqual(d['items'],[])
   for n in ('A01','A02','A03','A09','A14','B04','LIBRARY01'):
    p,d=self.run_cli(target/'scripts/workflow_node.py','context','--node',n,'--offline-preparation','--format','json');self.assertEqual(p.returncode,0,d);self.assertFalse(d['paid_generation_authorized'])
   p,d=self.run_cli(target/'scripts/workflow_rules.py','check');self.assertNotEqual(p.returncode,0);self.assertIn('RECEIVER_CONFIG_INCOMPLETE',d['error'])
   p,d=self.run_cli(ROOT/'tools/public_release.py','init','--workspace',target);self.assertNotEqual(p.returncode,0);self.assertIn('WORKSPACE_MUST_NOT_EXIST',d['error'])
 def test_mutable_config_is_separate_and_production_detects_tampering(self):
  import workflow_rules,workflow_deployment
  with tempfile.TemporaryDirectory() as tmp:
   target=Path(tmp)/'new'
   p,d=self.run_cli(ROOT/'tools/public_release.py','init','--workspace',target);self.assertEqual(p.returncode,0,d)
   cfg=json.loads((target/'receiver.local.json').read_text());cfg.update(writer_host='recipient-test-host',rules_center='ReceiverDocument',feishu_origin='https://recipient.feishu.cn',account_label='synthetic-test')
   (target/'receiver.local.json').write_text(json.dumps(cfg));(target/'workflow/state_bindings.json').write_text('{"bindings":[]}')
   p,d=self.run_cli(target/'tools/public_release.py','verify');self.assertEqual(p.returncode,0,d)
   from hashlib import sha256
   marker={'release_id':json.loads((target/'workflow/rules/manifest.json').read_text())['release_id'],'manifest_sha256':sha256((target/'workflow/rules/manifest.json').read_bytes()).hexdigest(),'skills_manifest_sha256':sha256((target/'SKILLS-MANIFEST.json').read_bytes()).hexdigest(),'receiver_config_sha256':receiver_config.security_digest(cfg)}
   response={'ok':True,'data':{'document':{'content':'<p>WF_RELEASE_JSON='+json.dumps(marker)+'</p>','revision_id':'synthetic'}}}
   with mock.patch.multiple(workflow_rules,ROOT=target,RULES=target/'workflow/rules'),mock.patch.object(receiver_config,'ROOT',target),mock.patch.object(workflow_rules.subprocess,'run',return_value=type('R',(),{'returncode':0,'stdout':json.dumps(response)})()):
    self.assertTrue(workflow_rules.check()['live_center_verified'])
    changed=dict(cfg,writer_host='another-test-host');(target/'receiver.local.json').write_text(json.dumps(changed))
    with self.assertRaisesRegex(ValueError,'RECEIVER_SECURITY_CONFIG_NOT_PUBLISHED'):workflow_rules.check()
    (target/'receiver.local.json').write_text(json.dumps(cfg))
    code=target/'scripts/prompt_contract.py';before=code.read_bytes();code.write_bytes(before+b'\n# changed\n')
    with self.assertRaisesRegex(ValueError,'LOCAL_INTEGRITY_MISMATCH'):workflow_rules.check()
    code.write_bytes(before)
    skill=target/'skills/seedance-prompts/SKILL.md';skill.write_text(skill.read_text()+'\nchanged\n')
    with self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISMATCH'):workflow_rules.check()
 def test_installed_snapshot_has_every_hashed_dependency(self):
  with tempfile.TemporaryDirectory() as tmp:
   p,d=self.run_cli(ROOT/'skills/seedance-paid-skit-production-pipeline/scripts/deploy_workspace.py','--workspace',Path(tmp)/'new')
   self.assertEqual(p.returncode,0,d);self.assertFalse(d['business_actions_authorized'])
 def test_credentials_and_foreign_origin_rejected(self):
  cfg=json.loads((ROOT/'receiver.example.json').read_text())
  for extra in ({'token':'synthetic-value'},{'feishu_origin':'https://evil.example/'}):
   with self.assertRaises(ValueError):receiver_config.validate(dict(cfg,**extra))
 def test_live_marker_mismatch_still_denied(self):
  import workflow_rules
  m,d=workflow_rules._manifest()
  with self.assertRaises(ValueError):workflow_rules.verify_marker('<p>WF_RELEASE_JSON={"release_id":"wrong","manifest_sha256":"wrong"}</p>',m,d)
 def test_writer_requires_own_host(self):
  import workflow_runtime
  with self.assertRaises(workflow_runtime.GuardError):workflow_runtime.ensure_writer('paid_generation')
 def test_skill_install_preserves_manual_change_and_external_gap(self):
  with tempfile.TemporaryDirectory() as tmp:
   dest=Path(tmp)/'skills';tool=Path(tmp)/'tools';cli=ROOT/'installer/scripts/progressive_install.py';args=(cli,'--skills-dir',dest,'--tool-root',tool,'install','--phase','0')
   p,d=self.run_cli(*args);self.assertEqual(p.returncode,2,d);self.assertFalse(d['files_ready']);self.assertEqual(d['external_dependencies']['lark-doc'],'external_missing')
   changed=dest/'universal-skit-orchestrator/SKILL.md';changed.write_text('manual edit')
   p,d=self.run_cli(*args);self.assertNotEqual(p.returncode,0);self.assertEqual(changed.read_text(),'manual edit')
if __name__=='__main__':unittest.main()
