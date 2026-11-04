"""Offline regressions: only synthetic files under TemporaryDirectory."""
import tempfile
import unittest
from pathlib import Path
import static_reference_check as checker


class ReferenceCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'skills'
        for name in checker.TARGETS:
            self.put(f'{name}/SKILL.md', '本 Skill 不抓取后台\n')
        self.put('rongyao-data-stack/scripts/active_chrome_bridge.mjs', '// safe\n')

    def put(self, relative, text='fixture'):
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def check_ref(self, text):
        self.put('rongyao-data-stack/SKILL.md', text)
        return checker.check(self.root)

    def test_valid_local_reference(self):
        self.put('rongyao-data-stack/scripts/local.py')
        self.assertTrue(self.check_ref('Run `scripts/local.py`.')['ok'])

    def test_cross_skill_complete_path(self):
        self.put('adapter/scripts/export.py')
        result = self.check_ref('Run `../adapter/scripts/export.py`.')
        self.assertTrue(result['ok'], result['errors'])
        self.assertEqual(result['resolved_references'][0]['target'], str(self.root / 'adapter/scripts/export.py'))

    def test_missing_and_unrelated_same_suffix_rejected(self):
        self.put('rongyao-dashboard-filter-finder/scripts/shared.py')
        result = self.check_ref('Run `../missing-skill/scripts/shared.py`.')
        self.assertFalse(result['ok'])
        self.assertIn('../missing-skill/scripts/shared.py', result['errors'][0])

    def test_bare_skill_root_and_bundle_prefix(self):
        self.put('rongyao-material-analysis/references/a.md')
        self.assertTrue(self.check_ref('`rongyao-material-analysis/references/a.md`\n`skills/rongyao-material-analysis/references/a.md`')['ok'])

    def test_nested_markdown_relative_link_and_anchor(self):
        self.put('rongyao-data-stack/references/a.md', '[b](b.md#one) [local](#one) [remote](https://example.org/x.md)')
        self.put('rongyao-data-stack/references/b.md', '# One')
        self.assertTrue(checker.check(self.root)['ok'])
        (self.root / 'rongyao-data-stack/references/b.md').unlink()
        self.assertFalse(checker.check(self.root)['ok'])

    def test_nested_code_uses_own_skill_root(self):
        self.put('rongyao-data-stack/references/a.md', '`scripts/a.py`')
        self.put('rongyao-data-stack/scripts/a.py')
        self.assertTrue(checker.check(self.root)['ok'])

    def test_linked_skill_uses_logical_installation_namespace(self):
        physical = Path(self.temp.name) / 'source/linked'
        logical = self.root / 'rongyao-material-performance'
        logical.rename(self.root / 'old-performance')
        physical.mkdir(parents=True)
        (physical / 'SKILL.md').write_text('`../adapter/scripts/a.py`')
        logical.symlink_to(physical, target_is_directory=True)
        self.put('adapter/scripts/a.py')
        result = checker.check(self.root)
        self.assertTrue(result['ok'], result['errors'])
        self.assertEqual(result['resolved_references'][0]['target'], str(self.root / 'adapter/scripts/a.py'))
        (self.root / 'adapter/scripts/a.py').unlink()
        # A physical sibling must not hide a missing installation dependency.
        (physical.parent / 'adapter/scripts').mkdir(parents=True)
        (physical.parent / 'adapter/scripts/a.py').write_text('unrelated')
        self.assertFalse(checker.check(self.root)['ok'])

    def test_template_is_reported_not_checked(self):
        result = self.check_ref('`scripts/<task>.py` `$STACK_DIR/scripts/a.py`')
        self.assertTrue(result['ok'])
        self.assertEqual([x['reason'] for x in result['skipped_references']], ['template', 'template'])

    def test_optional_external_is_exact_and_scoped(self):
        self.put('rongyao-data-stack/references/portability.md', '`$HOME/Documents/荣耀统计后台/scripts/weekly_report_cli.py`')
        result = checker.check(self.root)
        self.assertTrue(result['ok'])
        self.assertEqual(result['skipped_references'][0]['reason'], 'optional_external')
        self.assertFalse(self.check_ref('`scripts/weekly_report_cli.py`')['ok'])

    def test_layer_boundaries_still_reject(self):
        self.put('rongyao-dashboard-filter-finder/scripts/capture_bad.py', 'backend_http_request(')
        self.put('rongyao-material-analysis/SKILL.md', 'collect data')
        self.put('rongyao-data-stack/scripts/active_chrome_bridge.mjs', 'document.cookie')
        result = checker.check(self.root)
        self.assertTrue(any('dashboard_bypasses' in e for e in result['errors']))
        self.assertIn('analysis_capture_boundary_missing', result['errors'])
        self.assertTrue(any('active_bridge_reads_credentials' in e for e in result['errors']))

    def test_child_directory_symlink_scans_nested_links(self):
        shared = Path(self.temp.name) / 'shared'
        shared.mkdir()
        (shared / 'index.md').write_text('[dependency](missing.md)')
        self.put('rongyao-data-stack/references/.keep')
        (self.root / 'rongyao-data-stack/references/shared').symlink_to(shared, target_is_directory=True)
        result = self.check_ref('[rules](references/shared/index.md)')
        self.assertFalse(result['ok'])
        self.assertTrue(any('missing.md' in e for e in result['errors']))
        (shared / 'missing.md').write_text('valid now')
        self.assertTrue(checker.check(self.root)['ok'])

    def test_symlink_cycle_is_reported_without_looping(self):
        refs = self.root / 'rongyao-data-stack/references'
        refs.mkdir()
        (refs / 'loop').symlink_to(refs, target_is_directory=True)
        result = checker.check(self.root)
        self.assertFalse(result['ok'])
        self.assertTrue(any('reference_scan_cycle' in e for e in result['errors']))

    def test_reference_style_missing_file_is_checked(self):
        result = self.check_ref('Read [rules][gate].\n\n[gate]: missing.md\n')
        self.assertFalse(result['ok'])
        self.assertEqual(result['references_checked'], 1)

    def test_reference_style_nested_and_label_variants(self):
        self.put('rongyao-data-stack/references/a.md', '[One][MY Gate] [my gate][] [my gate]\n\n[my gate]: b.md#part "title"\n')
        self.put('rongyao-data-stack/references/b.md', '# Part')
        result = checker.check(self.root)
        self.assertTrue(result['ok'], result['errors'])
        self.assertEqual(result['references_checked'], 1)

    def test_reference_style_first_definition_wins(self):
        self.put('rongyao-data-stack/existing.md')
        result = self.check_ref('[x][gate]\n[gate]: missing.md\n[gate]: existing.md\n')
        self.assertFalse(result['ok'])
        self.assertIn('missing.md', result['errors'][0])

    def test_missing_target_returns_result_not_crash(self):
        (self.root / 'rongyao-material-analysis/SKILL.md').unlink()
        self.assertFalse(checker.check(self.root)['ok'])

if __name__ == '__main__':
    unittest.main()
