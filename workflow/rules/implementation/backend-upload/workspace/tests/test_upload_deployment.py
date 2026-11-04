"""Installed upload dependencies, including keyring changes, must match the release."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow_deployment as d

class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'skills';self.root.mkdir()
        packages={}
        for name,files in {
            'paid-skit-production-pipeline':{'SKILL.md':'current pipeline'},
            'seedance-paid-skit-production-pipeline':{'SKILL.md':'current canonical pipeline'},
            'rongyao-operations':{'scripts/rongyao.py':'current CLI'},
            'rongyao-keyring':{'scripts/worker.py':'preserved local worker','scripts/ai_probe.mjs':'preserved AI login'},
            'rongyao-data-stack':{'scripts/fast_video.py':'current data bridge'},
        }.items():
            hashes={}
            for rel,text in files.items():
                p=self.root/name/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);hashes[rel]=d.sha(p)
            packages[name]={'files':hashes}
        for part in ('references','scripts'):
            (self.root/'seedance-paid-skit-production-pipeline'/part).mkdir()
            (self.root/'paid-skit-production-pipeline'/part).symlink_to(Path('..')/'seedance-paid-skit-production-pipeline'/part,target_is_directory=True)
        setup=self.root/'paid-skit-progressive-setup';setup.mkdir();m=setup/'manifest.json'
        m.write_text(json.dumps({'version':'V-test-WF-test','files':[],'packages':packages}))
        self.marker={'release_id':'WF-test','installer_manifest_sha256':d.sha(m)}
    def verify(self,*roots):return d.verify(self.marker,list(roots) or [self.root])
    def test_preserved_keyring_matches_published_package(self):
        self.assertTrue(self.verify()['ok']);self.assertEqual(self.verify()['files_verified'],6)
    def test_alias_cannot_select_an_unreviewed_canonical_directory(self):
        link=self.root/'paid-skit-production-pipeline/references';link.unlink()
        link.symlink_to(self.root/'rongyao-keyring',target_is_directory=True)
        self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISMATCH',self.verify)
    def test_worker_drift_is_detected(self):
        (self.root/'rongyao-keyring/scripts/worker.py').write_text('unpublished update')
        self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISMATCH',self.verify)
    def test_new_ai_helper_is_required(self):
        (self.root/'rongyao-keyring/scripts/ai_probe.mjs').unlink()
        self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISMATCH',self.verify)
    def test_data_bridge_drift_is_detected(self):
        (self.root/'rongyao-data-stack/scripts/fast_video.py').write_text('old bridge')
        self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISMATCH',self.verify)
    def test_keyring_required_for_installed_operations(self):
        shutil.rmtree(self.root/'rongyao-keyring')
        self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISSING',self.verify)
    def test_other_root_dependency_does_not_cover_actual_runtime_root(self):
        second=self.root.parent/'other';second.mkdir()
        shutil.move(self.root/'rongyao-keyring',second/'rongyao-keyring')
        self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISSING',self.verify,self.root,second)
    def test_fixed_keychain_worker_copy_is_also_checked(self):
        second=self.root.parent/'codex';second.mkdir()
        for name in ['rongyao-keyring','rongyao-data-stack','rongyao-operations']:shutil.copytree(self.root/name,second/name)
        (second/'rongyao-keyring/scripts/worker.py').write_text('stale fixed helper target')
        self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISMATCH',self.verify,self.root,second)
    def test_keyring_alone_still_requires_data_stack(self):
        shutil.rmtree(self.root/'rongyao-operations');shutil.rmtree(self.root/'rongyao-data-stack')
        self.assertRaisesRegex(ValueError,'SKILL_DEPLOYMENT_MISSING',self.verify)

if __name__=='__main__':unittest.main()
