"""Contract regression using dummy bytes and mocked media checks only."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
CANDIDATE = ROOT.parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


prep = load_module("candidate_preparation", CANDIDATE / "rongyao-video-upload/scripts/prepare_upload.py")
ops = load_module("candidate_operations", CANDIDATE / "rongyao-operations/scripts/rongyao.py")


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix="test-")
        self.root = Path(self.tmp.name)
        self.ledgers = []
        real_ledger = ops.Ledger

        def tracked_ledger(*args, **kwargs):
            ledger = real_ledger(*args, **kwargs)
            self.ledgers.append(ledger)
            return ledger

        self.ledger_patch = patch.object(ops, "Ledger", side_effect=tracked_ledger)
        self.ledger_patch.start()
        self.source_b = self.root / "b.mp4"
        self.source_b.write_bytes(b"not real media: B fixture")
        self.final = self.root / "261020D1-AI小剧场接首充6元鼬-原创-37.mp4"
        self.final.write_bytes(b"not real media: final fixture")
        self.evidence = self.root / "review.json"
        self.evidence.write_text('{"fixture_only": true}')
        self.presets = prep.load(CANDIDATE / "rongyao-video-upload/references/verified-presets.json")
        self.b = copy.deepcopy(self.presets["b_library"]["itachi-six-yuan"])
        self.b.update(source_file=str(self.source_b), source_sha256=prep.digest(self.source_b))
        self.review = {
            "media_sha256": prep.digest(self.final), "full_decode_exit": 0, "full_decode_errors": "",
            "disclaimer_verified": True, "moving_watermark_verified": True,
            "role_verified": True, "splice_verified": True, "evidence": [str(self.evidence)]
        }
        self.request = {
            "profile": "naruto-skit-d", "date_prefix": "261020", "designer_code": "D",
            "requester_tail": "原创", "test_only": True,
            "shared_parameters": {"ai_source": "", "demand_name": "原创"},
            "shared_provenance": {
                "requester_explicit_original_override": True, "batch_fact": "shared", "priority": "shared"
            },
            "items": [{
                "file": str(self.final), "serial": 1, "a_description": "AI小剧场",
                "b_source": self.b, "expected_b_name": self.b["name"], "split_37": True,
                "quality_review": self.review,
                "provenance": {"a_export_sha256": "a" * 64, "priority": "item"}
            }]
        }
        self.state = self.root / "ledger"

    def tearDown(self):
        self.ledger_patch.stop()
        for ledger in self.ledgers:
            ledger.db.close()
        self.tmp.cleanup()

    def prepare(self, request=None):
        with patch.object(prep, "probe", return_value={"fixture_only": True}):
            value = prep.prepare(request or self.request, self.presets, "never-executed")
        self.assertTrue(value["can_proceed_to_ui"], value.get("blocked"))
        return value

    def convert(self, legacy):
        source = self.root / "legacy.json"
        output = self.root / "plan.json"
        ops.save(source, legacy)
        with patch.object(ops, "media", return_value={"fixture_only": True}):
            ops.plan(source, output, state=self.state)
        result = ops.read(output)
        self.assertEqual(result["source_plan"]["sha256"], ops.sha256(source))
        return result

    def test_test_only_survives_both_boundaries_and_cannot_submit(self):
        prepared = self.prepare()
        self.assertTrue(prepared["test_only"])
        plan = self.convert(prepared)
        self.assertTrue(plan["test_only"])
        with patch.object(ops, "transport") as external:
            result = ops._upload_registered(plan["job_id"], self.state)
        external.assert_not_called()
        self.assertEqual(result["status"], "OFFLINE_TEST_PLAN_CANNOT_UPLOAD")

    def test_original_override_and_item_priority_reach_operation(self):
        plan = self.convert(self.prepare())
        provenance = plan["items"][0]["provenance"]
        self.assertTrue(provenance["requester_explicit_original_override"])
        self.assertEqual(provenance["batch_fact"], "shared")
        self.assertEqual(provenance["priority"], "item")
        self.assertEqual(provenance["a_export_sha256"], "a" * 64)
        self.assertEqual(provenance["b_source"], self.b)

    def test_legacy_root_provenance_also_survives_without_prepare_merge(self):
        legacy = self.prepare()
        legacy["items"][0]["provenance"] = {"priority": "item", "item_fact": "item"}
        provenance = self.convert(legacy)["items"][0]["provenance"]
        self.assertTrue(provenance["requester_explicit_original_override"])
        self.assertEqual(provenance["batch_fact"], "shared")
        self.assertEqual(provenance["priority"], "item")
        self.assertEqual(provenance["item_fact"], "item")

    def test_no_original_override_is_invented(self):
        self.request["shared_provenance"].pop("requester_explicit_original_override")
        plan = self.convert(self.prepare())
        self.assertNotIn("requester_explicit_original_override", plan["items"][0]["provenance"])

    def test_override_is_removed_for_other_requester(self):
        self.request["items"][0]["parameters"] = {"demand_name": "示例人员4"}
        plan = self.convert(self.prepare())
        self.assertNotIn("requester_explicit_original_override", plan["items"][0]["provenance"])

    def test_explicit_empty_ai_review_and_second_designer_survive(self):
        plan = self.convert(self.prepare())
        item = plan["items"][0]
        self.assertEqual(item["parameters"]["ai_source"], "")
        self.assertEqual(item["parameters"]["region_type"], self.b["second_designer_value"])
        self.assertEqual(item["review"], self.review)

    def test_inherit_from_keeps_registered_source_hash_and_explicit_form(self):
        ledger = ops.Ledger(self.state)
        prior = {
            "job_id": "prior", "items": [{
                "filename": "source.mp4", "parameters": self.presets["profiles"]["naruto-skit-d"]["parameters"],
                "provenance": {"original_source": "known source"}
            }]
        }
        ledger.create(prior)
        ledger.db.close()
        source = {"job_id": "prior", "filename": "source.mp4"}
        self.request["items"][0]["inherit_from"] = source
        prepared = self.prepare()
        self.assertEqual(prepared["items"][0]["inherit_from"], source)
        item = self.convert(prepared)["items"][0]
        self.assertEqual(item["provenance"]["inherited_from"], {**source, "plan_sha256": ops.plan_digest(prior)})
        self.assertEqual(item["provenance"]["original_source"], "known source")
        self.assertEqual(item["parameters"]["region_type"], self.b["second_designer_value"])
        self.assertEqual(item["parameters"]["ai_source"], "")

    def test_unknown_inherit_from_is_rejected(self):
        self.request["items"][0]["inherit_from"] = {"job_id": "missing", "filename": "source.mp4"}
        with self.assertRaisesRegex(ValueError, "JOB_NOT_FOUND"):
            self.convert(self.prepare())

    def test_file_changed_after_preparation_is_rejected(self):
        prepared = self.prepare()
        self.final.write_bytes(b"changed fixture")
        with self.assertRaisesRegex(ValueError, "LEGACY_PLAN_FILE_CHANGED"):
            self.convert(prepared)

    def test_bad_second_designer_is_rejected_before_handoff(self):
        self.request["items"][0]["parameters"] = {"region_type": "wrong"}
        with patch.object(prep, "probe", return_value={"fixture_only": True}):
            result = prep.prepare(self.request, self.presets, "never-executed")
        self.assertFalse(result["can_proceed_to_ui"])

    def test_stale_review_is_rejected_before_handoff(self):
        self.request["items"][0]["quality_review"]["media_sha256"] = "stale"
        with patch.object(prep, "probe", return_value={"fixture_only": True}):
            result = prep.prepare(self.request, self.presets, "never-executed")
        self.assertFalse(result["can_proceed_to_ui"])

    def test_skipped_old_files_do_not_become_uploadable(self):
        legacy = self.prepare()
        legacy["items"][0]["state"] = "skip_already_listed"
        source = self.root / "legacy.json"
        output = self.root / "plan.json"
        ops.save(source, legacy)
        result = ops.plan(source, output, state=self.state)
        self.assertEqual(result["status"], "NO_PENDING_LEGACY_FILES")
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
