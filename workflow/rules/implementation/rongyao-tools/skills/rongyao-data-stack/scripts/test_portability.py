#!/usr/bin/env python3
"""Offline cross-platform regression tests for the portable 荣耀 Skill stack."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_ROOT = SCRIPT_DIR.parent.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backend = load_module("rongyao_backend_portability_test", SCRIPT_DIR / "backend_export_cli.py")
active_session = load_module(
    "rongyao_active_session_portability_test", SCRIPT_DIR / "active_session_cli.py"
)
preflight = load_module("rongyao_preflight_portability_test", SCRIPT_DIR / "preflight.py")
packager = load_module("rongyao_packager_portability_test", SCRIPT_DIR / "package_bundle.py")
capture_path = (
    SKILLS_ROOT
    / "rongyao-dashboard-filter-finder"
    / "scripts"
    / "capture_original_materials.py"
)
capture = load_module("rongyao_original_capture_portability_test", capture_path)


class PortabilityRegressionTest(unittest.TestCase):
    def test_active_session_state_never_contains_credentials(self) -> None:
        payload = active_session.safe_state_payload(9222, 1234, Path("synthetic-profile"))
        self.assertEqual(set(payload), {"version", "port", "pid", "profileDir"})
        rendered = json.dumps(payload).lower()
        for forbidden in ("cookie", "token", "password", "authorization"):
            self.assertNotIn(forbidden, rendered)

    def test_archive_names_are_posix_and_ds_store_is_excluded(self) -> None:
        sample = SKILLS_ROOT / "rongyao-data-stack" / "scripts" / "preflight.py"
        name = packager.archive_name(SKILLS_ROOT, "rongyao-data-stack", sample)
        self.assertEqual(name, "skills/rongyao-data-stack/scripts/preflight.py")
        eligible = list(packager.eligible_files(SKILLS_ROOT))
        self.assertFalse(any(path.name == ".DS_Store" for _, path in eligible))

    @unittest.skipUnless(
        importlib.util.find_spec("cryptography") is not None,
        "cryptography is not installed",
    )
    def test_windows_v10_aes_gcm_cookie(self) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        host = "data.houtai.cn.sy.backend.example.invalid"
        key = bytes(range(32))
        nonce = bytes(range(12))
        plaintext = hashlib.sha256(host.encode("utf-8")).digest() + b"session-value"
        encrypted = b"v10" + nonce + AESGCM(key).encrypt(nonce, plaintext, None)
        with patch.object(backend.platform, "system", return_value="Windows"):
            with patch.object(backend, "_windows_chrome_master_key", return_value=key):
                value = backend.backend_decrypt_chrome_cookie(
                    host, encrypted, Path("synthetic-cookies.sqlite")
                )
        self.assertEqual(value, "session-value")

    def test_windows_v20_stops_without_bypass(self) -> None:
        with patch.object(backend.platform, "system", return_value="Windows"):
            with self.assertRaisesRegex(SystemExit, "App-Bound Encryption"):
                backend.backend_decrypt_chrome_cookie("example.test", b"v20synthetic")

    def test_preflight_detects_v20_prefix_without_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "Cookies"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE cookies (host_key TEXT, value TEXT, encrypted_value BLOB)"
            )
            connection.execute(
                "INSERT INTO cookies VALUES (?, ?, ?)",
                (".backend.example.invalid", "", sqlite3.Binary(b"v20synthetic")),
            )
            connection.commit()
            connection.close()
            self.assertEqual(preflight.chrome_cookie_encryption(database), "v20")

    def test_parent_domain_plaintext_cookie_applies_to_backend_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "Cookies"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
            )
            connection.execute(
                "INSERT INTO cookies VALUES (?, ?, ?, ?)",
                (".backend.example.invalid", "session", "synthetic", sqlite3.Binary(b"")),
            )
            connection.commit()
            connection.close()
            with patch.object(backend, "backend_chrome_cookie_db", return_value=database):
                header = backend.backend_cookie_header_from_chrome(
                    host="data.houtai.cn.sy.backend.example.invalid"
                )
            self.assertEqual(header, "session=synthetic")

    def test_empty_disk_cookie_database_points_to_active_chrome_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "Cookies"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
            )
            connection.commit()
            connection.close()
            with patch.object(backend, "backend_chrome_cookie_db", return_value=database):
                with self.assertRaisesRegex(SystemExit, "会话 Cookie"):
                    backend.backend_cookie_header_from_chrome(
                        host="data.houtai.cn.sy.backend.example.invalid"
                    )

    def test_dynamic_option_keys_accept_direct_and_nested_shapes(self) -> None:
        self.assertEqual(backend.backend_option_keys({"133": "A", "145": "B"}), ["133", "145"])
        self.assertEqual(
            backend.backend_option_keys({"status": True, "info": {"pkid_list": {"1": "P"}}}),
            ["1"],
        )

    def test_gid_dependencies_are_deduplicated(self) -> None:
        responses = {
            "ApiGetCategory.php?gid=193": {"133": "A"},
            "ApiGetAllPkList.php?gid=193": {"1": "P"},
            "ApiGetCategory.php?gid=197": {"133": "A", "145": "B"},
            "ApiGetAllPkList.php?gid=197": {"2": "Q"},
        }

        def fake_json(host, path, cookie, timeout):
            return next(value for suffix, value in responses.items() if path.endswith(suffix))

        with patch.object(backend, "backend_json", side_effect=fake_json):
            categories, subgames = backend.backend_gid_dependencies(
                "example", "synthetic", ["193", "197"], timeout=1
            )
        self.assertEqual(categories, ["133", "145"])
        self.assertEqual(subgames, ["1", "2"])

    def test_single_instance_lock_blocks_second_process(self) -> None:
        lock = capture.acquire_lock()
        code = f"""
import importlib.util, sys
path = {str(capture_path)!r}
spec = importlib.util.spec_from_file_location('lock_child', path)
module = importlib.util.module_from_spec(spec)
sys.modules['lock_child'] = module
spec.loader.exec_module(module)
try:
    child_lock = module.acquire_lock()
except module.CaptureError:
    raise SystemExit(0)
else:
    module.release_lock(child_lock)
    raise SystemExit(2)
"""
        try:
            completed = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, check=False
            )
        finally:
            capture.release_lock(lock)
        self.assertEqual(completed.returncode, 0, completed.stderr)


class ConsolidatedSourceTests(unittest.TestCase):
    def test_directory_alias_exports_one_source_and_optional_keyring_is_explicit(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'installed';root.mkdir();source=base/'source';source.mkdir()
            for skill in packager.SKILLS:
                shutil.copytree(SKILLS_ROOT/skill,source/skill,ignore=shutil.ignore_patterns('__pycache__'))
                try:
                    (root/skill).symlink_to(source/skill,target_is_directory=True)
                except OSError as error:
                    self.skipTest('Directory aliases unavailable on this host: '+str(error))
            files=list(packager.eligible_files(root))
            self.assertEqual({s for s,_ in files},set(packager.SKILLS))
            manifest=json.loads((source/'rongyao-data-stack/references/bundle-files.json').read_text())
            optional=source/'rongyao-keyring';optional.mkdir();(root/'rongyao-keyring').symlink_to(optional,target_is_directory=True)
            for name in manifest['optionalFiles']['rongyao-keyring']:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('---\nname: rongyao-keyring\ndescription: synthetic\n---\n' if target.name=='SKILL.md' else 'synthetic')
            self.assertIn('rongyao-keyring',{s for s,_ in packager.eligible_files(root)})
            path=source/'rongyao-data-stack/scripts/preflight.py';path.unlink();outside=base/'outside.py';outside.write_text('outside');path.symlink_to(outside)
            with self.assertRaises(SystemExit):list(packager.eligible_files(root))


if __name__ == "__main__":
    unittest.main()
