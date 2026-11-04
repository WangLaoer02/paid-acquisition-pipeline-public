"""Completion/conflict regression tests; official network acceptance is recorded separately."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'installer/scripts'))
import progressive_install as install
import official_dependencies as official


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.args = types.SimpleNamespace(skills_dir=Path(self.tmp.name)/'skills', tool_root=Path(self.tmp.name)/'tools',
                                         phases='0', phase='0', backend='dreamina', dreamina_region='cn',
                                         with_official_skills=False, provider='lark', with_cli=False, ca_bundle=None)
        self.manifest = install.verify()

    def capture(self, fn, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = fn(*args)
        return rc, json.loads(out.getvalue())

    @unittest.skipIf(os.name == 'nt', 'POSIX executable fixtures; Windows remains unverified')
    def test_feishu_cli_process_exit_and_existing_files_preserved(self):
        # Invoke the real entry point in a child process: function-only tests cannot
        # catch main() accidentally discarding the tool-install-feishu return code.
        for case, exit_code, executable, on_path in [
            ('version_failure', 9, True, False),
            ('not_executable', 0, False, False),
            ('version_success', 0, True, False),
            ('path_version_failure', 9, True, True),
        ]:
            with self.subTest(case=case):
                root = Path(self.tmp.name) / case
                tool_root = root / 'tools'
                path_dir = root / 'path'
                path_dir.mkdir(parents=True)
                if on_path:
                    binary = path_dir / 'lark-cli'
                else:
                    package = tool_root / 'npm/node_modules/@larksuite/cli/package.json'
                    package.parent.mkdir(parents=True)
                    package.write_text('{"version":"existing-manual-version","manual":"preserve"}')
                    binary = tool_root / 'npm/node_modules/.bin/lark-cli'
                    binary.parent.mkdir(parents=True)
                binary.write_text('#!/bin/sh\nexit ' + str(exit_code) + '\n')
                binary.chmod(0o755 if executable else 0o644)
                def snapshot():
                    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mode)
                            for p in root.rglob('*') if p.is_file()}
                before = snapshot()
                environment = dict(os.environ, PATH=str(path_dir))
                result = subprocess.run([
                    sys.executable, str(ROOT / 'installer/scripts/progressive_install.py'),
                    '--skills-dir', str(root / 'skills'), '--tool-root', str(tool_root),
                    'tool-install-feishu',
                ], capture_output=True, text=True, env=environment, timeout=25)
                output = json.loads(result.stdout)
                expected = 0 if executable and exit_code == 0 else 2
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertEqual(output['version_probe_passed'], expected == 0)
                self.assertTrue(output['existing_cli_preserved'])
                self.assertFalse(output['compatibility_verified'])
                self.assertEqual(snapshot(), before)
                self.assertFalse((root / 'skills').exists())

    def test_stage_missing_external_is_nonzero(self):
        rc, result = self.capture(install.install, self.args, self.manifest)
        self.assertEqual(rc, 2)
        self.assertFalse(result['files_ready'])
        self.assertFalse(result['installation_complete'])

    def test_setup_does_not_mask_doctor_or_external_failure(self):
        with mock.patch.object(install, 'probe_binary', return_value=True):
            rc, result = self.capture(install.setup, self.args, self.manifest)
        self.assertEqual(rc, 2)
        self.assertFalse(result['installation_complete'])
        self.assertTrue(any(s['action']=='doctor' and s['exit_code']==2 for s in result['steps']))

    def test_empty_skill_does_not_count_as_official_install(self):
        for name in official.lock()['providers']['lark']['skills']:
            p = self.args.skills_dir/name/'SKILL.md'
            p.parent.mkdir(parents=True);p.write_text('')
        rc, result = self.capture(install.doctor, self.args, self.manifest)
        self.assertEqual(rc, 2)
        self.assertFalse(result['files_ready'])
        self.assertEqual(result['skills']['lark-doc'], 'external_present_unverified_or_modified')
        with self.assertRaisesRegex(ValueError, 'EXTERNAL_CONFLICT_PRESERVED'):
            official.install(self.args)

    def test_bundled_manual_change_preserved_and_recoverable(self):
        self.args.phase='2';self.args.phases='2'
        self.capture(install.install, self.args, self.manifest)
        p=self.args.skills_dir/'seedance-prompts/SKILL.md';before=p.read_bytes();p.write_bytes(b'manual')
        rc, result=self.capture(install.setup,self.args,self.manifest)
        self.assertEqual(rc,2);self.assertEqual(p.read_bytes(),b'manual')
        p.write_bytes(before)
        rc,result=self.capture(install.setup,self.args,self.manifest)
        self.assertEqual(rc,0);self.assertTrue(result['installation_complete'])
        self.assertFalse(result['runtime_ready']);self.assertFalse(result['business_ready'])

    def source_fixture(self):
        files={'SKILL.md':b'official fixture', 'references/detail.md':b'required reference'}
        blob=io.BytesIO()
        with tarfile.open(fileobj=blob,mode='w:gz') as archive:
            for name,data in files.items():
                member=tarfile.TarInfo('root/lark-doc/'+name);member.size=len(data);archive.addfile(member,io.BytesIO(data))
        source={'version':'fixture','source':'https://example.invalid','archive':{'url':'https://example.invalid','sha256':official.digest(blob.getvalue())},
                'skills':{'lark-doc':{'prefix':'root/lark-doc/','tree_sha256':official.tree_hash(files)}}}
        return {'providers':{'lark':source}},blob.getvalue()

    def test_network_failure_recovery_repeat_and_reference_edit(self):
        lock,blob=self.source_fixture()
        with mock.patch.object(official,'lock',return_value=lock):
            with mock.patch.object(official,'download',side_effect=ValueError('OFFICIAL_DOWNLOAD_FAILED')):
                with self.assertRaisesRegex(ValueError,'OFFICIAL_DOWNLOAD_FAILED'):official.install(self.args)
            self.assertFalse((self.args.skills_dir/'lark-doc').exists())
            with mock.patch.object(official,'download',return_value=blob):
                self.assertEqual(official.install(self.args)['skills']['lark-doc'],'external_verified')
            with mock.patch.object(official,'download',side_effect=AssertionError('repeat downloaded')):
                self.assertEqual(official.install(self.args)['files_installed'],[])
            p=self.args.skills_dir/'lark-doc/references/detail.md';p.write_bytes(b'hand edit')
            with self.assertRaisesRegex(ValueError,'EXTERNAL_CONFLICT_PRESERVED'):official.install(self.args)
            self.assertEqual(p.read_bytes(),b'hand edit')

    def test_symlink_external_preserved(self):
        target=Path(self.tmp.name)/'manual';target.mkdir();self.args.skills_dir.mkdir()
        (self.args.skills_dir/'lark-doc').symlink_to(target)
        with self.assertRaisesRegex(ValueError,'EXTERNAL_CONFLICT_PRESERVED'):official.install(self.args)
        self.assertTrue((self.args.skills_dir/'lark-doc').is_symlink())

    def test_cn_never_silently_installs_international(self):
        self.args.provider='dreamina'
        with mock.patch.object(official,'download',side_effect=AssertionError('should not download')):
            with self.assertRaisesRegex(ValueError,'DREAMINA_CN_SOURCE_UNVERIFIED'):official.install(self.args)

    def test_unknown_platform_does_not_install_binary(self):
        self.args.provider='dreamina';self.args.dreamina_region='international';self.args.with_cli=True
        with mock.patch.object(official.platform,'system',return_value='UnverifiedOS'):
            with self.assertRaisesRegex(ValueError,'PLATFORM_UNVERIFIED'):official.install(self.args)

    def test_hash_mismatch_and_unsafe_archive_rejected(self):
        lock,blob=self.source_fixture()
        lock['providers']['lark']['skills']['lark-doc']['tree_sha256']='0'*64
        with mock.patch.object(official,'lock',return_value=lock),mock.patch.object(official,'download',return_value=blob):
            with self.assertRaisesRegex(ValueError,'TREE_MISMATCH'):official.install(self.args)
        self.assertFalse((self.args.skills_dir/'lark-doc').exists())
        blob=io.BytesIO()
        with tarfile.open(fileobj=blob,mode='w:gz') as archive:
            member=tarfile.TarInfo('../escape');member.size=1;archive.addfile(member,io.BytesIO(b'x'))
        with self.assertRaisesRegex(ValueError,'UNSAFE'):official.archive_files(blob.getvalue())

if __name__=='__main__':unittest.main()
