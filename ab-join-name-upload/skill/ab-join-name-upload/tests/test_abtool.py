import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import os  # noqa: E402

# 测试绝不写真实的 ~/.ab-join-name-upload：整套测试用独立临时目录
_TEST_HOME = tempfile.mkdtemp(prefix="abtool-test-home-")
os.environ["AB_TOOL_HOME"] = _TEST_HOME
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import abtool  # noqa: E402

assert str(abtool.HOME) == _TEST_HOME, "测试必须隔离 AB_TOOL_HOME"


def setUpModule():
    abtool.HOME = Path(_TEST_HOME)


def tearDownModule():
    shutil.rmtree(_TEST_HOME, ignore_errors=True)


class FreshLedger:
    """每个用到台账的测试都从空台账开始。"""

    def setUp(self):
        super().setUp()
        abtool.ledger_path().unlink(missing_ok=True)

PEOPLE = {"LW": "测试乙", "ZS": "测试甲"}


def name(**kw):
    base = dict(date="261118", designer="ZS", serial=3, a_title="AI偏心生日被毁鼬",
                b_name="261110LW2-首充开鼬-原创", demand="LW", people=PEOPLE)
    base.update(kw)
    return abtool.build_name(**base)


class NamingRule(unittest.TestCase):
    def test_real_sample_shape(self):
        r = name(designer="QQ", people={**PEOPLE, "QQ": "某人"})
        self.assertEqual(r["name"], "261118QQ3-AI偏心生日被毁鼬接首充开鼬-LW-37")
        self.assertEqual(r["second_designer"], "测试乙")

    def test_own_b_has_no_37_and_no_second_designer(self):
        r = name(designer="LW")
        self.assertEqual(r["name"], "261118LW3-AI偏心生日被毁鼬接首充开鼬-LW")
        self.assertFalse(r["split_37"])
        self.assertIsNone(r["second_designer"])

    def test_no_demand_writes_yuanchuang(self):
        self.assertEqual(name(demand="原创")["name"], "261118ZS3-AI偏心生日被毁鼬接首充开鼬-原创-37")

    def test_intern_between_demand_and_37(self):
        self.assertEqual(name(intern="HP")["name"], "261118ZS3-AI偏心生日被毁鼬接首充开鼬-LW-HP-37")

    def test_intern_omitted_when_empty(self):
        self.assertEqual(name(intern="")["name"], "261118ZS3-AI偏心生日被毁鼬接首充开鼬-LW-37")

    def test_unknown_b_designer_stops(self):
        with self.assertRaisesRegex(abtool.ToolError, "第二设计师待核"):
            name(b_name="261110XY2-首充开鼬-原创")

    def test_unknown_demand_stops(self):
        with self.assertRaisesRegex(abtool.ToolError, "需求人代号"):
            name(demand="XX")

    def test_dash_in_title_rejected(self):
        with self.assertRaisesRegex(abtool.ToolError, "分隔符"):
            name(a_title="AI-偏心")

    def test_illegal_chars_rejected(self):
        with self.assertRaisesRegex(abtool.ToolError, "非法字符"):
            name(a_title="AI/偏心")

    def test_bad_b_name_rejected(self):
        with self.assertRaisesRegex(abtool.ToolError, "无法从"):
            name(b_name="D1_NB-885017632bd1")

    def test_serial_must_be_positive_int(self):
        for bad in (0, -1, True):
            with self.assertRaises(abtool.ToolError):
                name(serial=bad)

    def test_role_token_enforced(self):
        with self.assertRaisesRegex(abtool.ToolError, "主推角色"):
            name(role_token="佐助")
        self.assertTrue(name(role_token="鼬")["name"])

    def test_b_title_override(self):
        self.assertIn("接首充开佐助-", name(b_title="首充开佐助")["name"])

    def test_bad_date(self):
        for bad in ("2611", "261332", "abcdef"):
            with self.assertRaises(abtool.ToolError):
                name(date=bad)

    def test_today_date(self):
        r = name(date="today")
        self.assertRegex(r["date"], r"^\d{6}$")
        self.assertTrue(r["date_defaulted_to_today"])

    def test_parse_formal_with_mp4(self):
        p = abtool.parse_formal("261118LW3-AI偏心生日被毁鼬接首充开鼬-LW-37.mp4")
        self.assertEqual((p["date"], p["designer"], p["serial"]), ("261118", "LW", 3))
        self.assertEqual(p["tail"], ["LW", "37"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 FFmpeg")
class Package(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.clip = self.tmp / "成片.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=72x128:rate=24:duration=11",
                        "-f", "lavfi", "-i", "sine=duration=11", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(self.clip)], check=True)
        (self.tmp / "codes.json").write_text(json.dumps({"people": PEOPLE}), encoding="utf-8")
        cfg = Path(__file__).resolve().parents[1] / "config" / "fields.example.json"
        shutil.copy(cfg, self.tmp / "fields.json")
        self.out = self.tmp / "待上传"
        abtool.ledger_path().unlink(missing_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def args(self, **kw):
        base = dict(file=str(self.clip), out_dir=str(self.out), date="261118", designer="ZS", serial=3,
                    a_title="AI偏心生日被毁鼬", b_name="261110LW2-首充开鼬-原创", b_title=None, demand="LW",
                    intern=None, role_token=None, codes=str(self.tmp / "codes.json"),
                    fields=str(self.tmp / "fields.json"), category="火影", source_type=["小剧场"],
                    source_direction=["AI"], role=["宇智波鼬"], ai="")
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_bad_field_leaves_nothing(self):
        with self.assertRaisesRegex(abtool.ToolError, "不在可选项里"):
            abtool.cmd_package(self.args(category="海贼"))
        self.assertFalse(self.out.exists() and any(self.out.iterdir()))

    def test_good_package_writes_file_and_sheets(self):
        r = abtool.cmd_package(self.args())
        self.assertEqual(r["name"], "261118ZS3-AI偏心生日被毁鼬接首充开鼬-LW-37")
        self.assertEqual(r["second_designer"], "测试乙")
        files = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(files, [r["name"] + s for s in (".mp4", ".上传清单.json", ".上传清单.md")])
        self.assertEqual(abtool.sha256(self.out / (r["name"] + ".mp4")), abtool.sha256(self.clip))

    def lib_args(self, item, **kw):
        orig = abtool.resolve_lib_b
        abtool.resolve_lib_b = lambda args: ({}, item, "test")
        self.addCleanup(setattr, abtool, "resolve_lib_b", orig)
        return self.args(b_name=None, b_id=item["lib_id"], library=None, **kw)

    def test_role_tag_defaults_to_b_main_role(self):
        item = dict(LIB_ITEMS[0], main_role="带土")
        r = abtool.cmd_package(self.lib_args(item, role=None, a_title="AI偏心生日被毁鸣人"))
        sheet = json.loads(Path(r["sheet_json"]).read_text(encoding="utf-8"))
        self.assertEqual(sheet["form"]["角色标签"], "带土")
        self.assertEqual(sheet["role_source"], "默认取 B 段主推角色")

    def test_explicit_role_overrides_default(self):
        item = dict(LIB_ITEMS[0], main_role="带土")
        r = abtool.cmd_package(self.lib_args(item, role=["宇智波鼬"]))
        sheet = json.loads(Path(r["sheet_json"]).read_text(encoding="utf-8"))
        self.assertEqual(sheet["form"]["角色标签"], "宇智波鼬")
        self.assertEqual(sheet["role_source"], "手动指定")

    def test_b_role_not_in_options_stops_without_files(self):
        item = dict(LIB_ITEMS[0], main_role="佐助、小樱（混合展示）")
        with self.assertRaisesRegex(abtool.ToolError, "不在角色标签可选项里"):
            abtool.cmd_package(self.lib_args(item, role=None))
        self.assertFalse(self.out.exists() and any(self.out.iterdir()))

    def test_rerun_same_file_is_idempotent(self):
        abtool.cmd_package(self.args())
        abtool.cmd_package(self.args())
        self.assertEqual(len(list(self.out.glob("*.mp4"))), 1)


LIB_ITEMS = [
    {"lib_id": "NB-0001", "title": "带土抽卡攻略", "source_code": "261008LW2", "main_role": "带土",
     "second_designer": "测试丙", "clip": "B段/NB-0001_261008LW2.mp4", "clip_sha256": ""},
    {"lib_id": "NB-0002", "title": "首充六元鼬", "source_code": "261009DXX2", "main_role": "鼬",
     "second_designer": None, "clip": "B段/NB-0002_261009DXX2.mp4", "clip_sha256": ""},
    {"lib_id": "NB-0003", "title": "首充6元鼬", "source_code": "260930HR9", "main_role": "鼬",
     "second_designer": "测试乙", "clip": "B段/NB-0003_260930HR9.mp4", "clip_sha256": ""},
]
LIB_PEOPLE = {"LW": "测试乙", "ZS": "测试甲", "HR": "测试戊"}


class LibraryNaming(unittest.TestCase):
    def name(self, item, **kw):
        base = dict(date="261118", designer="LW", serial=3, a_title="AI偏心生日被毁鼬", demand="LW",
                    people=LIB_PEOPLE, b_lib=item)
        base.update(kw)
        return abtool.build_name(**base)

    def test_registered_second_designer_wins_over_name_code(self):
        # 名称码 LW＝测试乙，但这段 B 实际由测试丙制作：按库里登记算，本人 LW 也要 -37
        r = self.name(LIB_ITEMS[0])
        self.assertEqual(r["name"], "261118LW3-AI偏心生日被毁鼬接带土抽卡攻略-LW-37")
        self.assertEqual(r["second_designer"], "测试丙")
        self.assertEqual(r["second_designer_source"], "选B台登记")
        self.assertEqual(r["b_lib_id"], "NB-0001")

    def test_own_b_by_registration_has_no_37(self):
        r = self.name(LIB_ITEMS[2])  # 名称码 HR，但库里登记是测试乙＝本人
        self.assertFalse(r["split_37"])
        self.assertIsNone(r["second_designer"])
        self.assertTrue(r["name"].endswith("-LW"))

    def test_unregistered_second_designer_stops(self):
        with self.assertRaisesRegex(abtool.ToolError, "第二设计师未登记"):
            self.name(LIB_ITEMS[1])

    def test_own_code_must_be_in_people(self):
        with self.assertRaisesRegex(abtool.ToolError, "本人设计师码"):
            self.name(LIB_ITEMS[0], designer="QQ")

    def test_b_name_and_b_lib_exclusive(self):
        with self.assertRaisesRegex(abtool.ToolError, "二选一"):
            self.name(LIB_ITEMS[0], b_name="261110LW2-首充开鼬-原创")

    def test_find(self):
        self.assertEqual(abtool.lib_find(LIB_ITEMS, "NB-0002")["title"], "首充六元鼬")
        self.assertEqual(abtool.lib_find(LIB_ITEMS, "首充6元鼬")["lib_id"], "NB-0003")
        self.assertEqual(abtool.lib_find(LIB_ITEMS, "抽卡")["lib_id"], "NB-0001")
        self.assertEqual(abtool.lib_find(LIB_ITEMS, "260930HR9")["lib_id"], "NB-0003")
        with self.assertRaisesRegex(abtool.ToolError, "匹配到 2 条"):
            abtool.lib_find(LIB_ITEMS, "首充")
        with self.assertRaisesRegex(abtool.ToolError, "找不到"):
            abtool.lib_find(LIB_ITEMS, "斑")


def B(lib_id, pay, spend, uses, produced="2026-10-09", role="鼬", second="测试丙"):
    return {"lib_id": lib_id, "title": lib_id, "main_role": role, "second_designer": second,
            "pay_effective_count": pay, "spend_effective_count": spend, "footage_count": uses,
            "produced_at": produced}


class DurationRule(unittest.TestCase):
    def test_only_a_segment_is_limited(self):
        self.assertIsNone(abtool.a_length_note(12.625))
        self.assertIsNone(abtool.a_length_note(10))
        self.assertIsNone(abtool.a_length_note(25))
        self.assertIn("A 段", abtool.a_length_note(9.5))
        self.assertIn("A 段", abtool.a_length_note(30))

    @unittest.skipUnless(shutil.which("ffmpeg"), "需要 FFmpeg")
    def test_long_final_video_not_flagged(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            clip = tmp / "长成片.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=72x128:rate=12:duration=40",
                            "-f", "lavfi", "-i", "sine=duration=40", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", str(clip)], check=True)
            r = abtool.check_file(clip)
            self.assertTrue(r["technical_ok"])
            self.assertEqual(r["warnings"], [])
        finally:
            shutil.rmtree(tmp)


class Pick(unittest.TestCase):
    def ids(self, res, slot=None):
        return [p["item"]["lib_id"] for p in res["picks"] if slot in (None, p["slot"])]

    def test_effective_sorted_pay_first(self):
        items = [B("吸量多付费少", 1, 9, 100), B("付费多", 6, 3, 100), B("付费中", 4, 3, 100), B("只吸量", 0, 9, 100)]
        res = abtool.lib_pick(items)
        self.assertEqual(self.ids(res, "有效素材"), ["付费多", "付费中"])

    def test_effective_needs_both_pay_and_spend(self):
        items = [B("只付费", 5, 0, 100), B("只吸量", 0, 5, 100), B("都有", 1, 1, 100)]
        self.assertEqual(self.ids(abtool.lib_pick(items), "有效素材"), ["都有"])

    def test_new_prefers_pay_then_newest(self):
        items = [B("E1", 5, 5, 100), B("E2", 4, 4, 100),
                 B("新无付费最新", 0, 0, 3, "2026-10-11"), B("新有付费", 1, 0, 20, "2026-10-01")]
        self.assertEqual(self.ids(abtool.lib_pick(items), "新素材"), ["新有付费"])
        items = [B("E1", 5, 5, 100), B("E2", 4, 4, 100),
                 B("新旧", 0, 0, 3, "2026-10-01"), B("新最新", 0, 0, 5, "2026-10-11")]
        res = abtool.lib_pick(items)
        self.assertEqual(self.ids(res, "新素材"), ["新最新"])
        self.assertIn("产出日期最新", res["picks"][-1]["reason"])

    def test_new_threshold_and_no_duplicates(self):
        items = [B("有效且少用", 3, 3, 10), B("E2", 2, 2, 100), B("用多", 0, 0, 31), B("少用", 0, 0, 30)]
        res = abtool.lib_pick(items)
        self.assertEqual(self.ids(res), ["有效且少用", "E2", "少用"])
        res = abtool.lib_pick(items, rules={"new_max_uses": 5})
        self.assertEqual(self.ids(res, "新素材"), [])
        self.assertTrue(any("新素材不足" in s for s in res["shortfall"]))

    def test_unregistered_skipped_and_reported(self):
        items = [B("没登记但最好", 9, 9, 100, second=None), B("E1", 2, 2, 100), B("E2", 1, 1, 100),
                 B("N", 0, 0, 3)]
        res = abtool.lib_pick(items)
        self.assertNotIn("没登记但最好", self.ids(res))
        self.assertEqual([it["lib_id"] for it in res["skipped_but_would_qualify"]], ["没登记但最好"])

    def test_same_role_effective_first_even_if_lower_pay(self):
        items = [B("带土付费6", 6, 3, 100, role="带土"), B("佐助付费2", 2, 1, 100, role="佐助"),
                 B("佐助付费1", 1, 5, 100, role="佐助")]
        res = abtool.lib_pick(items, a_role="佐助")
        self.assertEqual(self.ids(res, "有效素材"), ["佐助付费2", "佐助付费1"])
        self.assertEqual(res["notes"], [])

    def test_fill_with_other_role_only_when_no_same_role_effective(self):
        items = [B("佐助有效", 1, 1, 100, role="佐助"), B("佐助不合格", 0, 9, 100, role="佐助"),
                 B("带土有效", 6, 3, 100, role="带土"), B("鼬有效", 2, 2, 100, role="宇智波鼬")]
        res = abtool.lib_pick(items, a_role="佐助")
        self.assertEqual(self.ids(res, "有效素材"), ["佐助有效", "带土有效"])
        self.assertNotIn("佐助不合格", self.ids(res))
        self.assertTrue(any("同角色（佐助）的有效素材只有 1 条" in n for n in res["notes"]))
        self.assertEqual([p["same_role"] for p in res["picks"] if p["slot"] == "有效素材"], [True, False])

    def test_new_slot_same_role_first_then_any(self):
        items = [B("E1", 5, 5, 100, role="带土"), B("E2", 4, 4, 100, role="带土"),
                 B("新鼬有付费", 2, 0, 10, role="宇智波鼬"), B("新佐助无付费", 0, 0, 10, "2026-10-01", role="佐助")]
        res = abtool.lib_pick(items, a_role="佐助")
        self.assertEqual(self.ids(res, "新素材"), ["新佐助无付费"])
        items[3]["main_role"] = "凯"
        res = abtool.lib_pick(items, a_role="佐助")
        self.assertEqual(self.ids(res, "新素材"), ["新鼬有付费"])
        self.assertTrue(any("没有新素材" in n for n in res["notes"]))

    def test_no_a_role_ignores_roles(self):
        items = [B("带土", 6, 3, 100, role="带土"), B("佐助", 2, 1, 100, role="佐助"), B("鼬", 1, 1, 100, role="鼬")]
        res = abtool.lib_pick(items)
        self.assertEqual(self.ids(res, "有效素材"), ["带土", "佐助"])
        self.assertEqual(res["notes"], [])

    def test_role_match(self):
        self.assertTrue(abtool.role_match("鼬", "宇智波鼬"))
        self.assertTrue(abtool.role_match("宇智波鼬", "鼬"))
        self.assertTrue(abtool.role_match("佐助", "佐助、小樱（混合展示）"))
        self.assertFalse(abtool.role_match("鸣人", "带土"))
        self.assertFalse(abtool.role_match("", "带土"))
        self.assertFalse(abtool.role_match("佐助", None))

    def test_shortfall_effective(self):
        res = abtool.lib_pick([B("E1", 1, 1, 100), B("N", 0, 0, 1)])
        self.assertTrue(any("有效素材只有 1 条" in s for s in res["shortfall"]))


class LibraryFetch(unittest.TestCase):
    """用本机临时 HTTP 服务模拟选B台。"""

    @classmethod
    def setUpClass(cls):
        import functools
        import http.server
        import threading
        cls.root = Path(tempfile.mkdtemp())
        (cls.root / "B段").mkdir()
        (cls.root / "data").mkdir()
        clip = cls.root / "B段" / "NB-0001_261008LW2.mp4"
        clip.write_bytes(b"fake-b-clip" * 1000)
        item = dict(LIB_ITEMS[0], clip_sha256=abtool.sha256(clip))
        bad = dict(LIB_ITEMS[2], clip="B段/NB-0001_261008LW2.mp4", clip_sha256="0" * 64, lib_id="NB-BAD")
        gone = dict(LIB_ITEMS[2], clip="B段/不存在.mp4", clip_sha256="1" * 64, lib_id="NB-GONE")
        (cls.root / "data" / "fact.json").write_text(json.dumps(
            {"generated_at": "test", "items": [item, bad, gone]}, ensure_ascii=False), encoding="utf-8")
        handler = functools.partial(QuietHandler, directory=str(cls.root))
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.cfg = {"base_url": f"http://127.0.0.1:{cls.srv.server_address[1]}/",
                   "cache_dir": str(cls.root / "cache")}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.root)

    def test_download_verify_then_cache(self):
        items, gen = abtool.lib_items(self.cfg)
        self.assertEqual(gen, "test")
        path, how = abtool.lib_fetch(self.cfg, abtool.lib_find(items, "NB-0001"))
        self.assertEqual(how, "downloaded")
        self.assertEqual(abtool.sha256(path), items[0]["clip_sha256"])
        self.assertEqual(abtool.lib_fetch(self.cfg, items[0])[1], "cache")

    def test_sha_mismatch_discarded(self):
        items, _ = abtool.lib_items(self.cfg)
        with self.assertRaisesRegex(abtool.ToolError, "SHA256 与选B台登记不符"):
            abtool.lib_fetch(self.cfg, abtool.lib_find(items, "NB-BAD"))
        self.assertFalse(list(Path(self.cfg["cache_dir"]).glob("*.partial")))

    def test_404_explains(self):
        items, _ = abtool.lib_items(self.cfg)
        with self.assertRaisesRegex(abtool.ToolError, "没有开放 B 段下载"):
            abtool.lib_fetch(self.cfg, abtool.lib_find(items, "NB-GONE"))

    def test_unreachable(self):
        with self.assertRaisesRegex(abtool.ToolError, "连不上选B台"):
            abtool.lib_items({"base_url": "http://127.0.0.1:9/", "cache_dir": str(self.root / "c2")})


try:
    import http.server as _hs

    class QuietHandler(_hs.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
except ImportError:  # pragma: no cover
    pass


if __name__ == "__main__":
    unittest.main()


TEAM = Path(__file__).resolve().parent / "fixtures" / "team-config"


@unittest.skipUnless(shutil.which("ffmpeg"), "需要 FFmpeg")
class V05Features(unittest.TestCase):
    """团队默认值、真实字段校验、台账序号、回填素材ID、一条命令 run。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

        def clip(name, size, secs, rate=24):
            p = cls.tmp / name
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={secs}",
                            "-f", "lavfi", "-i", f"sine=duration={secs}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", str(p)], check=True)
            return p
        cls.a = clip("A.mp4", "72x128", 11)
        cls.b = clip("B.mp4", "128x72", 4, 30)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def setUp(self):
        abtool.ledger_path().unlink(missing_ok=True)
        self.out = Path(tempfile.mkdtemp(dir=self.tmp))
        self.item = dict(LIB_ITEMS[0], main_role="带土", pay_effective_count=4, spend_effective_count=3,
                         footage_count=100, clip_sha256=abtool.sha256(self.b), duration=4.0)
        orig = abtool.resolve_lib_b
        abtool.resolve_lib_b = lambda args: ({}, self.item, "test")
        self.addCleanup(setattr, abtool, "resolve_lib_b", orig)

    def pkg(self, **kw):
        base = dict(file=str(self.a), out_dir=str(self.out), date="261118", designer="D", serial=5,
                    a_title="AI海上找清静鸣人", b_name=None, b_id="NB-0001", b_title=None, library=None,
                    demand="原创", intern=None, role_token=None, codes=str(TEAM / "codes.json"),
                    fields=str(TEAM / "fields.json"), category=None, game=None, source_type=None,
                    source_direction=None, role=None, ai=None)
        base.update(kw)
        return abtool.cmd_package(types.SimpleNamespace(**base))

    def test_team_defaults_fill_form(self):
        r = self.pkg()
        form = json.loads(Path(r["sheet_json"]).read_text(encoding="utf-8"))["form"]
        self.assertEqual(r["name"], "261118D5-AI海上找清静鸣人接带土抽卡攻略-原创-37")
        self.assertEqual((form["项目分类"], form["游戏"], form["一类"], form["二类"], form["AI 方式"]),
                         ("火影", "忍界大战", "小剧场", "AI", "SD2拼框"))
        self.assertTrue(form["需求人"].startswith(json.loads((TEAM / "codes.json").read_text(encoding="utf-8"))["people"]["D"]))
        self.assertIn("本人", form["需求人"])
        self.assertEqual(form["第二设计师"], "测试丙")
        self.assertEqual(form["角色标签"], "带土")
        self.assertEqual(r["pending_fields"], [])
        vals = json.loads(Path(r["sheet_json"]).read_text(encoding="utf-8"))["backend_values"]
        own = json.loads((TEAM / "codes.json").read_text(encoding="utf-8"))["people"]["D"]
        self.assertEqual(vals, {"category_type": "117", "gid": "193", "region_type": "1256", "demand_name": own})

    def test_own_name_must_be_in_demand_dropdown_when_no_demand(self):
        cfg = json.loads((TEAM / "fields.json").read_text(encoding="utf-8"))
        cfg["demand"]["options"] = ["别人"]
        f = self.tmp / "fields-no-self.json"
        f.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(abtool.ToolError, "不在后台需求人下拉里"):
            self.pkg(fields=str(f))

    def test_second_designer_must_exist_in_backend(self):
        self.item["second_designer"] = "不存在的人"
        with self.assertRaisesRegex(abtool.ToolError, "不在后台第二设计师下拉里"):
            self.pkg()

    def test_non_ai(self):
        r = self.pkg(ai="无")
        form = json.loads(Path(r["sheet_json"]).read_text(encoding="utf-8"))["form"]
        self.assertEqual(form["AI 方式"], "无（非 AI）")

    def test_reused_serial_retires_unuploaded_old_version(self):
        old = self.pkg()
        self.item = dict(self.item, title="另一条B")
        new = self.pkg()
        self.assertNotEqual(old["name"], new["name"])
        self.assertFalse(Path(old["upload_file"]).exists())
        self.assertTrue((self.out / "作废" / Path(old["upload_file"]).name).exists())
        self.assertTrue(Path(new["upload_file"]).exists())
        st = {r["素材名称"]: r["状态"] for r in abtool.ledger_rows()}
        self.assertTrue(st[old["name"]].startswith("作废"))
        self.assertEqual(st[new["name"]], "已出清单")

    def test_uploaded_serial_blocks_reuse(self):
        old = self.pkg()
        abtool.cmd_record(types.SimpleNamespace(name=old["name"], record_id="124887"))
        self.item = dict(self.item, title="另一条B")
        with self.assertRaisesRegex(abtool.ToolError, "已上传为"):
            self.pkg()

    def test_record_material_id(self):
        r = self.pkg()
        res = abtool.cmd_record(types.SimpleNamespace(name=r["name"] + ".mp4", record_id="124887"))
        self.assertEqual(res["record_id"], "124887")
        row = abtool.ledger_rows()[0]
        self.assertEqual((row["状态"], row["素材ID"]), ("已上传", "124887"))
        self.assertIn("124887", json.loads(Path(r["sheet_json"]).read_text(encoding="utf-8"))["upload_status"])
        with self.assertRaisesRegex(abtool.ToolError, "已记过素材 ID"):
            abtool.cmd_record(types.SimpleNamespace(name=r["name"], record_id="999"))
        with self.assertRaisesRegex(abtool.ToolError, "数字"):
            abtool.cmd_record(types.SimpleNamespace(name=r["name"], record_id="abc"))

    def test_run_three_versions_consecutive_serials(self):
        items = [dict(self.item, lib_id=f"NB-{i}", title=t, main_role=role, pay_effective_count=p,
                      spend_effective_count=s, footage_count=u, second_designer=sd)
                 for i, (t, role, p, s, u, sd) in enumerate([
                     ("传奇王鼬", "宇智波鼬", 6, 3, 128, "测试丙"), ("带土抽卡攻略", "带土", 4, 3, 143, "测试丙"),
                     ("再选一次", "带土", 0, 1, 26, "测试丁"), ("没登记", "带土", 9, 9, 100, None)])]
        by_id = {it["lib_id"]: it for it in items}
        patches = {"load_library": lambda p=None: {"base_url": "http://x/", "cache_dir": str(self.tmp / "c")},
                   "lib_items": lambda cfg: (items, "test"),
                   "lib_fetch": lambda cfg, it: (self.b, "cache"),
                   "resolve_lib_b": lambda args: ({}, by_id[args.b_id], "test")}
        for k, v in patches.items():
            orig = getattr(abtool, k)
            setattr(abtool, k, v)
            self.addCleanup(setattr, abtool, k, orig)
        r = abtool.cmd_run(types.SimpleNamespace(
            a=str(self.a), a_role="鸣人", a_title="AI海上找清静鸣人", designer="D", serial=5, date="261118",
            demand="原创", intern=None, ai=None, out_dir=str(self.out), overlay=None, watermark=None,
            codes=str(TEAM / "codes.json"), fields=str(TEAM / "fields.json"), library=None))
        self.assertTrue(r["ok"], r)
        self.assertEqual([v["name"] for v in r["versions"]], [
            "261118D5-AI海上找清静鸣人接传奇王鼬-原创-37",
            "261118D6-AI海上找清静鸣人接带土抽卡攻略-原创-37",
            "261118D7-AI海上找清静鸣人接再选一次-原创-37"])
        self.assertEqual(r["next_serial"], 8)
        summary = Path(r["summary"]).read_text(encoding="utf-8")
        self.assertIn("没登记", summary)
        self.assertEqual(len(list(self.out.glob("*.mp4"))), 3)
        self.assertEqual(len(abtool.ledger_rows()), 3)

    def test_set_library_rejects_bad_url(self):
        with self.assertRaisesRegex(abtool.ToolError, "http"):
            abtool.cmd_set_library(types.SimpleNamespace(url="example.com/pick/"))


class UncutItems(unittest.TestCase):
    def test_virtual_items_skipped_and_suggested(self):
        import http.server, functools, threading
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "data").mkdir()
        good = dict(LIB_ITEMS[0], clip_sha256="a" * 64)
        virtual = {"lib_id": "VB-1", "title": "首充6元", "kind": "virtual", "clip": None, "clip_sha256": None,
                   "source_code": "", "main_role": None, "pay_effective_count": 6, "spend_effective_count": 6}
        weak = {"lib_id": "VB-2", "title": "没效果", "clip": None, "pay_effective_count": 0, "spend_effective_count": 3}
        (root / "data" / "fact.json").write_text(json.dumps({"generated_at": "t", "items": [good, virtual, weak]},
                                                            ensure_ascii=False), encoding="utf-8")
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        items, _ = abtool.lib_items({"base_url": f"http://127.0.0.1:{srv.server_address[1]}/"})
        self.assertEqual([it["lib_id"] for it in items], ["NB-0001"])
        self.assertEqual([u["title"] for u in abtool.uncut_suggestions()], ["首充6元"])
        with self.assertRaisesRegex(abtool.ToolError, "还没截成"):
            abtool.lib_find(items, "首充6元")


class ImportConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = self.tmp / "团队配置"
        self.src.mkdir()
        for n in abtool.CONFIG_FILES:
            (self.src / n).write_text(json.dumps({"version": "t", "people": {"ZS": "测试甲"}}), encoding="utf-8")
        for n in abtool.CONFIG_FILES:
            (abtool.HOME / n).unlink(missing_ok=True)

    def test_import_from_zip_with_backup(self):
        import zipfile
        z = self.tmp / "团队配置.zip"
        with zipfile.ZipFile(z, "w") as f:
            for n in abtool.CONFIG_FILES:
                f.write(self.src / n, f"团队配置/{n}")
        (abtool.HOME / "codes.json").write_text("{}", encoding="utf-8")
        r = abtool.cmd_import_config(types.SimpleNamespace(source=str(z)))
        self.assertTrue(r["ok"])
        self.assertTrue(list(abtool.HOME.glob("codes.json.bak-*")))
        self.assertEqual(json.loads((abtool.HOME / "codes.json").read_text(encoding="utf-8"))["people"]["ZS"], "测试甲")
        r2 = abtool.cmd_import_config(types.SimpleNamespace(source=str(z)))
        self.assertEqual({f["action"] for f in r2["files"]}, {"unchanged"})

    def test_bad_json_rejected(self):
        (self.src / "fields.json").write_text("{坏", encoding="utf-8")
        with self.assertRaisesRegex(abtool.ToolError, "不是有效 JSON"):
            abtool.cmd_import_config(types.SimpleNamespace(source=str(self.src)))


class PlaceholderLibrary(unittest.TestCase):
    def test_placeholder_address_gives_clear_error(self):
        p = abtool.HOME / "lib-placeholder.json"
        p.write_text(json.dumps({"base_url": "https://选B台地址/pick/"}, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(abtool.ToolError, "还没设置选B台地址"):
            abtool.load_library(p)

    def test_doctor_never_crashes_on_library(self):
        for n in ("codes.json", "fields.json"):
            (abtool.HOME / n).write_text("{}", encoding="utf-8")
        (abtool.HOME / "library.json").write_text(json.dumps({"base_url": "https://选B台地址/pick/"},
                                                             ensure_ascii=False), encoding="utf-8")
        r = abtool.cmd_doctor(None)
        self.assertFalse(r["library"]["reachable"])
        self.assertIn("还没设置选B台地址", r["library"]["error"])
        for n in ("codes.json", "fields.json", "library.json"):
            (abtool.HOME / n).unlink(missing_ok=True)


class TempState:
    """每个工作台测试用独立的旧版目录、桌面和工作台，结束后恢复模块状态。"""

    def setUp(self):
        super().setUp()
        self.base = Path(tempfile.mkdtemp(prefix="abtool-ws-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        saved = (abtool.STATE, abtool.WS, abtool.HOME)
        self.addCleanup(self._restore, saved)
        self.desk = self.base / "Desktop"
        self.desk.mkdir()
        env = unittest.mock.patch.dict(os.environ, {"AB_DESKTOP": str(self.desk), "CODEX_HOME": str(self.base / "codex"),
                                                    "AB_SHORTCUT": "symlink"})
        env.start()
        self.addCleanup(env.stop)
        abtool.STATE = self.base / "state"
        abtool.WS, abtool.HOME = None, abtool.STATE
        self.root = self.base / "买量工作台"

    @staticmethod
    def _restore(saved):
        abtool.STATE, abtool.WS, abtool.HOME = saved

    def init(self, **kw):
        a = dict(root=str(self.root), designer="d", desktop_link=None, force=False)
        a.update(kw)
        return abtool.cmd_ws_init(types.SimpleNamespace(**a))


import unittest.mock  # noqa: E402


class WorkspaceInit(TempState, unittest.TestCase):
    def test_init_builds_layout_pointer_and_link(self):
        r = self.init()
        self.assertTrue(r["ok"] and r["created"])
        for d in abtool.WS_DIRS:
            self.assertTrue((self.root / d).is_dir(), d)
        today = abtool.resolve_date("today")[0]
        for d in abtool.DAY_DIRS:
            self.assertTrue((self.root / "每日" / today / d).is_dir())
        self.assertEqual(json.loads((abtool.STATE / "workspace.json").read_text(encoding="utf-8"))["root"], str(self.root))
        meta = json.loads((self.root / "工作台.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["designer"], "D")
        self.assertIn("03_待上传", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        link = self.desk / "今日待上传"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.root / "每日" / today / "03_待上传").resolve())
        self.assertEqual(abtool.HOME, self.root / "配置")
        self.assertEqual(abtool.ledger_path(), self.root / "台账" / "上传台账.csv")

    def test_rerun_is_idempotent_and_keeps_user_edits(self):
        self.init()
        r = self.init(designer=None)
        self.assertEqual({f["action"] for f in r["files"]}, {"unchanged"})
        self.assertEqual(r["designer"], "D")
        (self.root / "AGENTS.md").write_text("# 我改过\n", encoding="utf-8")
        r = self.init(designer="LW")  # 设计师码变了，生成内容也变
        acts = {f["file"]: f["action"] for f in r["files"]}
        self.assertEqual(acts["AGENTS.md"], "kept_user_edits")
        self.assertEqual(acts["开始使用.md"], "updated")
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"), "# 我改过\n")
        self.assertIn("LW", (self.root / "AGENTS.新版.md").read_text(encoding="utf-8"))

    def test_allows_preexisting_source_clone_but_not_foreign_dir(self):
        (self.root / "程序" / "源码").mkdir(parents=True)
        self.assertTrue(self.init()["ok"])
        other = self.base / "别的"
        other.mkdir()
        (other / "我的文件.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(abtool.ToolError, "已有工作台"):
            self.init(root=str(other))
        with self.assertRaisesRegex(abtool.ToolError, "其他东西"):
            self.init(root=str(other), force=True)

    def test_real_desktop_folder_never_replaced(self):
        (self.desk / "今日待上传").mkdir()
        r = self.init()
        self.assertFalse(r["desktop_link"]["ok"])
        self.assertTrue((self.desk / "今日待上传").is_dir() and not (self.desk / "今日待上传").is_symlink())

    def test_no_desktop_link_option(self):
        r = self.init(desktop_link=False)
        self.assertIsNone(r["desktop_link"])
        self.assertFalse((self.desk / "今日待上传").exists())

    def test_rerun_without_root_reuses_existing_workspace(self):
        self.init()
        r = self.init(root=None, designer=None)
        self.assertEqual(r["workspace"], str(self.root))
        self.assertFalse(r["created"])

    def test_bad_designer_rejected(self):
        with self.assertRaisesRegex(abtool.ToolError, "字母"):
            self.init(designer="D-1")

    def test_find_workspace_via_pointer(self):
        self.init()
        self.assertEqual(abtool.find_workspace(), self.root)
        (self.root / "工作台.json").unlink()
        self.assertIsNone(abtool.find_workspace())

    def test_status_and_today_need_workspace(self):
        with self.assertRaisesRegex(abtool.ToolError, "workspace init"):
            abtool.cmd_ws_status(None)
        self.init()
        st = abtool.cmd_ws_status(None)
        self.assertEqual(st["pending_upload"], [])
        self.assertFalse(st["config_files"]["codes.json"])
        self.assertTrue(abtool.cmd_ws_today(None)["ok"])


@unittest.skipUnless(shutil.which("ffmpeg"), "需要 FFmpeg")
class WorkspaceFlow(TempState, V05Features):
    """在工作台里出清单、作废、回填：产物落在 每日/日期/ 下对应的子目录。"""

    def setUp(self):
        super().setUp()
        self.init()
        self.day = self.root / "每日" / "261118"
        abtool.ensure_day("261118")
        self.out = self.day / "03_待上传"

    def test_record_moves_to_uploaded_without_touching_longer_names(self):
        r = self.pkg(demand="原创")
        # 名称更长的另一条（同前缀）不能被一起移走
        longer = self.out / (r["name"] + "-HP.mp4")
        longer.write_bytes(b"x")
        res = abtool.cmd_record(types.SimpleNamespace(name=r["name"], record_id="127598"))
        done = self.day / "04_已上传"
        self.assertEqual(res["moved_to"], str(done))
        self.assertTrue((done / (r["name"] + ".mp4")).is_file())
        self.assertTrue((done / (r["name"] + ".上传清单.md")).is_file())
        self.assertFalse(Path(r["upload_file"]).exists())
        self.assertTrue(longer.is_file())
        row = abtool.ledger_rows()[0]
        self.assertEqual(row["上传文件"], str(done / (r["name"] + ".mp4")))
        self.assertIn("127598", json.loads((done / (r["name"] + ".上传清单.json")).read_text(encoding="utf-8"))["upload_status"])

    def test_retired_version_goes_to_day_void_dir(self):
        old = self.pkg()
        self.item = dict(self.item, title="另一条B")
        self.pkg()
        self.assertTrue((self.day / "作废" / Path(old["upload_file"]).name).is_file())

    def test_reused_serial_retires_unuploaded_old_version(self):  # 父类断言的是旧版目录结构
        old = self.pkg()
        self.item = dict(self.item, title="另一条B")
        self.pkg()
        self.assertFalse(Path(old["upload_file"]).exists())

    def test_record_material_id(self):  # 父类读的是旧位置；工作台里清单已移到 04_已上传
        r = self.pkg()
        abtool.cmd_record(types.SimpleNamespace(name=r["name"] + ".mp4", record_id="124887"))
        moved = self.day / "04_已上传" / Path(r["sheet_json"]).name
        self.assertIn("124887", json.loads(moved.read_text(encoding="utf-8"))["upload_status"])
        with self.assertRaisesRegex(abtool.ToolError, "已记过素材 ID"):
            abtool.cmd_record(types.SimpleNamespace(name=r["name"], record_id="999"))

    def test_run_defaults_into_today_dirs(self):
        items = [dict(self.item, lib_id=f"NB-{i}", title=t, pay_effective_count=p, spend_effective_count=1,
                      footage_count=u) for i, (t, p, u) in enumerate(
                          [("甲B", 5, 100), ("乙B", 4, 90), ("丙B", 0, 3)])]
        by_id = {it["lib_id"]: it for it in items}
        for k, v in {"load_library": lambda p=None: {"base_url": "http://x/"},
                     "lib_items": lambda cfg: (items, "test"),
                     "lib_fetch": lambda cfg, it: (self.b, "cache"),
                     "resolve_lib_b": lambda args: ({}, by_id[args.b_id], "test")}.items():
            orig = getattr(abtool, k)
            setattr(abtool, k, v)
            self.addCleanup(setattr, abtool, k, orig)
        r = abtool.cmd_run(types.SimpleNamespace(
            a=str(self.a), a_role="带土", a_title="AI海上找清静鸣人", designer="D", serial=1, date="261118",
            demand="原创", intern=None, ai=None, out_dir=None, overlay=None, watermark=None,
            codes=str(TEAM / "codes.json"), fields=str(TEAM / "fields.json"), library=None))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["out_dir"], str(self.out))
        self.assertEqual(len(list(self.out.glob("*.mp4"))), 3)
        self.assertEqual(len(list((self.day / "02_接片").glob("*.mp4"))), 3)
        self.assertTrue(r["desktop_link"]["ok"])
        self.assertEqual(abtool.cmd_ws_status(None)["pending_upload"].__len__(), 3)


class WorkspaceMigrate(TempState, unittest.TestCase):
    def legacy(self):
        st = abtool.STATE
        st.mkdir(parents=True)
        for n in abtool.CONFIG_FILES:
            (st / n).write_text(json.dumps({"n": n}), encoding="utf-8")
        old = self.desk / "待上传"
        (old / "作废").mkdir(parents=True)
        files = {
            "up": old / "261118D6-甲接乙-原创-37.mp4",
            "up_md": old / "261118D6-甲接乙-原创-37.上传清单.md",
            "todo": old / "261119D1-丙接丁-原创.mp4",
            "void": old / "作废" / "261118D5-戊接己-原创.mp4",
            "sum": old / "本次待上传_1118_2010.md",
            "odd": old / "随手.txt",
        }
        for f in files.values():
            f.write_bytes(f.name.encode())
        os.utime(files["sum"], (1795000000, 1795000000))
        rows = [{"素材名称": "261118D6-甲接乙-原创-37", "日期": "261118", "设计师码": "D", "序号": "6",
                 "上传文件": str(files["up"]), "状态": "已上传", "素材ID": "127598"},
                {"素材名称": "261119D1-丙接丁-原创", "日期": "261119", "设计师码": "D", "序号": "1",
                 "上传文件": str(files["todo"]), "状态": "已出清单", "素材ID": ""}]
        import csv
        with (st / "上传台账.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=abtool.LEDGER_COLS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in abtool.LEDGER_COLS})
        (st / "b-cache").mkdir()
        (st / "b-cache" / "NB-1.mp4").write_bytes(b"b")
        return files

    def migrate(self, dry=False):
        return abtool.cmd_ws_migrate(types.SimpleNamespace(dry_run=dry))

    def test_dry_run_moves_nothing(self):
        files = self.legacy()
        self.init()
        r = self.migrate(dry=True)
        self.assertTrue(r["dry_run"])
        self.assertTrue(all(f.exists() for f in files.values()))
        self.assertFalse((self.root / "配置" / "codes.json").exists())

    def test_migrate_puts_everything_in_place(self):
        files = self.legacy()
        init = self.init()
        self.assertTrue(init["legacy_found"])
        r = self.migrate()
        self.assertTrue(r["ok"], r)
        W = self.root / "每日"
        self.assertTrue((W / "261118" / "04_已上传" / files["up"].name).is_file())
        self.assertTrue((W / "261118" / "04_已上传" / files["up_md"].name).is_file())
        self.assertTrue((W / "261119" / "03_待上传" / files["todo"].name).is_file())
        self.assertTrue((W / "261118" / "作废" / files["void"].name).is_file())
        self.assertTrue((W / "未归类" / "随手.txt").is_file())
        self.assertEqual(len(list(W.glob("*/03_待上传/本次待上传_*.md"))), 1)
        self.assertFalse((self.desk / "待上传").exists())
        for n in abtool.CONFIG_FILES:
            self.assertTrue((self.root / "配置" / n).is_file())
            self.assertFalse((abtool.STATE / n).exists())
        self.assertTrue((self.root / "B段缓存" / "NB-1.mp4").is_file())
        rows = {r["素材名称"]: r for r in abtool.ledger_rows()}
        self.assertEqual(rows["261118D6-甲接乙-原创-37"]["素材ID"], "127598")
        self.assertEqual(rows["261119D1-丙接丁-原创"]["上传文件"], str(W / "261119" / "03_待上传" / files["todo"].name))
        self.assertFalse((abtool.STATE / "上传台账.csv").exists())
        self.assertEqual(r["legacy_remaining"], [])
        # 再跑一次什么也不做
        r2 = self.migrate()
        self.assertEqual((r2["files"], r2["config"]), ([], []))

    def test_conflict_is_skipped_and_reported(self):
        files = self.legacy()
        self.init()
        clash = self.root / "每日" / "261119" / "03_待上传" / files["todo"].name
        clash.parent.mkdir(parents=True, exist_ok=True)
        clash.write_bytes(b"different")
        r = self.migrate()
        self.assertFalse(r["ok"])
        self.assertEqual([c["from"] for c in r["conflicts"]], [str(files["todo"])])
        self.assertTrue(files["todo"].is_file())
        self.assertEqual(clash.read_bytes(), b"different")

    def test_existing_workspace_config_wins(self):
        self.legacy()
        self.init()
        (self.root / "配置" / "codes.json").write_text('{"new": 1}', encoding="utf-8")
        r = self.migrate()
        acts = {c["file"]: c["action"] for c in r["config"]}
        self.assertEqual(acts["codes.json"], "workspace_kept_old_saved")
        self.assertEqual((self.root / "配置" / "codes.json").read_text(encoding="utf-8"), '{"new": 1}')
        self.assertTrue(list((self.root / "配置").glob("迁移前旧配置-*/codes.json")))


class Board(TempState, unittest.TestCase):
    def row(self, name, date, status="已出清单", sid=""):
        return {"素材名称": name, "日期": date, "设计师码": "D", "序号": "1", "状态": status, "素材ID": sid, "上传文件": ""}

    def test_steps_follow_today_progress(self):
        self.init()
        today = abtool.resolve_date("today")[0]
        day = self.root / "每日" / today
        self.assertEqual(abtool.board_state()["step"], 0)
        (day / "01_A段" / "A.mp4").write_bytes(b"a")
        self.assertEqual(abtool.board_state()["step"], 0)
        self.assertIn("01_A段 里有 1 个", abtool.board_state()["next"])
        (day / "02_接片" / "j.mp4").write_bytes(b"j")
        self.assertEqual(abtool.board_state()["step"], 1)
        abtool.ledger_write([self.row(f"{today}D1-甲接乙-原创", today)])
        st = abtool.board_state()
        self.assertEqual((st["step"], len(st["todo"])), (2, 1))
        abtool.ledger_write([self.row(f"{today}D1-甲接乙-原创", today, "已上传", "127598")])
        self.assertEqual(abtool.board_state()["step"], 4)

    def test_older_pending_and_void_and_escape(self):
        self.init()
        today = abtool.resolve_date("today")[0]
        abtool.ledger_write([self.row("261101D3-<b>坏</b>接乙-原创", "261101"),
                             self.row(f"{today}D2-丙接丁-原创", today, "作废：序号改给 X")])
        st = abtool.board_state()
        self.assertEqual(len(st["older_todo"]), 1)
        self.assertEqual(len(st["void"]), 1)
        html = abtool.render_board(st)
        self.assertNotIn("<b>坏</b>", html)
        self.assertIn("&lt;b&gt;坏&lt;/b&gt;", html)
        self.assertIn("还没回填素材 ID", html)

    def test_board_file_and_desktop_link(self):
        r = self.init()
        self.assertTrue(r["board"]["ok"], r["board"])
        self.assertTrue((self.root / "看板.html").is_file())
        link = self.desk / "买量看板.html"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.root / "看板.html").resolve())
        res = abtool.cmd_ws_board(None)
        self.assertTrue(res["ok"])
        self.assertIn("next", res)

    def test_board_never_breaks_commands(self):
        self.init()
        orig = abtool.board_state
        abtool.board_state = lambda today=None: 1 / 0
        self.addCleanup(setattr, abtool, "board_state", orig)
        r = abtool.write_board()
        self.assertFalse(r["ok"])
        self.assertIn("ZeroDivisionError", r["error"])

    def test_no_board_without_workspace(self):
        self.assertIsNone(abtool.write_board())


@unittest.skipUnless(shutil.which("ffmpeg"), "需要 FFmpeg")
class BoardFlow(TempState, V05Features):
    def setUp(self):
        super().setUp()
        self.init()
        self.day = self.root / "每日" / "261118"
        abtool.ensure_day("261118")
        self.out = self.day / "03_待上传"

    def test_record_refreshes_board_with_links(self):
        r = self.pkg()
        st = abtool.board_state("261118")
        self.assertEqual(len(st["todo"]), 1)
        html = abtool.render_board(st)
        self.assertIn("上传清单", html)
        self.assertIn(urllib.parse.quote("每日/261118/03_待上传/"), html)
        res = abtool.cmd_record(types.SimpleNamespace(name=r["name"], record_id="127598"))
        self.assertTrue(res["board"]["ok"])
        st = abtool.board_state("261118")
        self.assertEqual((len(st["todo"]), len(st["done"])), (0, 1))
        self.assertIn("素材 ID 127598", abtool.render_board(st))

    # 父类里断言旧目录结构的测试在工作台里不适用
    def test_reused_serial_retires_unuploaded_old_version(self):
        pass

    def test_record_material_id(self):
        pass

    def test_run_three_versions_consecutive_serials(self):
        pass


import urllib.parse  # noqa: E402


PKG = Path(__file__).resolve().parents[3]



def run_install(tmp, *extra):
    env = {k: v for k, v in os.environ.items() if k not in ("AB_WORKSPACE", "AB_TOOL_HOME", "AB_DESKTOP", "AB_DOWNLOADS")}
    (tmp / "Desktop").mkdir(exist_ok=True)
    (tmp / "Downloads").mkdir(exist_ok=True)
    env.update(AB_TOOL_HOME=str(tmp / "state"), CODEX_HOME=str(tmp / "codex"), HOME=str(tmp), USERPROFILE=str(tmp),
               AB_DESKTOP=str(tmp / "Desktop"), AB_DOWNLOADS=str(tmp / "Downloads"), AB_SHORTCUT="symlink" if os.name != "nt" else "lnk")
    return subprocess.run([sys.executable, str(PKG / "install.py"), *extra], env=env, capture_output=True)


@unittest.skipIf((PKG / "team-config").is_dir(), "只在不带团队配置的公开版里检查")
class InstallKeepsConfig(unittest.TestCase):
    """回归：公开版升级曾用示例配置覆盖本机已导入的团队配置。"""

    def test_reinstall_never_overwrites_imported_config_with_examples(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        src = tmp / "团队配置"
        src.mkdir()
        real = {n: json.dumps({"real": n, "people": {"ZS": "测试甲"}, "base_url": "https://example.invalid/pick/"})
                for n in ("codes", "fields", "library")}
        for n, v in real.items():
            (src / f"{n}.json").write_text(v, encoding="utf-8")
        run_install(tmp, "--config", str(src))
        run_install(tmp)  # 再装一次：“下载”里没有团队配置
        conf = tmp / "买量工作台" / "配置"
        for n, v in real.items():
            self.assertEqual((conf / f"{n}.json").read_bytes(), v.encode("utf-8"), f"{n}.json 被改动")
        self.assertTrue((tmp / "买量工作台" / "看板.html").is_file())
        self.assertTrue((tmp / "codex" / "skills" / "ab-join-name-upload" / "scripts" / "abtool.py").is_file())


class CrossPlatform(TempState, unittest.TestCase):
    def test_lnk_mode_records_and_respects_foreign_shortcuts(self):
        made = []
        orig = abtool.make_lnk
        abtool.make_lnk = lambda link, target: (Path(link).write_text(str(target), encoding="utf-8"), made.append(str(link)))
        self.addCleanup(setattr, abtool, "make_lnk", orig)
        with unittest.mock.patch.dict(os.environ, {"AB_SHORTCUT": "lnk"}):
            r = self.init()
            self.assertTrue(r["desktop_link"]["ok"], r["desktop_link"])
            self.assertTrue((self.desk / "今日待上传.lnk").is_file())
            self.assertTrue((self.desk / "买量看板.lnk").is_file())
            n = len(made)
            abtool.cmd_ws_today(None)  # 目标没变就不重建
            self.assertEqual(len(made), n)
            meta = json.loads((self.root / "工作台.json").read_text(encoding="utf-8"))
            self.assertIn(str(self.desk / "今日待上传.lnk"), meta["shortcuts"])
            (self.desk / "买量看板.lnk").unlink()
            (self.desk / "买量看板.lnk").write_text("别人的", encoding="utf-8")
            meta["shortcuts"].pop(str(self.desk / "买量看板.lnk"))
            abtool.ws_save_meta(meta)
            r = abtool.write_board()
            self.assertFalse(r["desktop_link"]["ok"])
            self.assertEqual((self.desk / "买量看板.lnk").read_text(encoding="utf-8"), "别人的")

    def test_lnk_failure_is_reported_not_raised(self):
        def boom(link, target):
            raise OSError("没有 PowerShell")
        orig = abtool.make_lnk
        abtool.make_lnk = boom
        self.addCleanup(setattr, abtool, "make_lnk", orig)
        with unittest.mock.patch.dict(os.environ, {"AB_SHORTCUT": "lnk"}):
            r = self.init()
        self.assertTrue(r["ok"])
        self.assertIn("没有 PowerShell", r["desktop_link"]["reason"])

    def test_folders_from_env(self):
        with unittest.mock.patch.dict(os.environ, {"AB_DOWNLOADS": str(self.base)}):
            self.assertEqual(abtool.downloads_dir(), self.base)
        self.assertEqual(abtool.desktop_dir(), self.desk)

    def test_agents_uses_current_python(self):
        self.init()
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(Path(sys.executable).name, text)
        self.assertIn("install.py", text)
        self.assertNotIn("bash ", text)


def make_pipeline(root, items, nodes=None):
    wf = root / "workflow"
    wf.mkdir(parents=True, exist_ok=True)
    nodes = nodes or {f"A{i:02d}": {"id": f"A{i:02d}", "label": f"{i:02d} 节点{i}", "order": i, "family": "a",
                                    "required_output": f"产出{i}"} for i in range(1, 16)}
    (wf / "node_skills.json").write_text(json.dumps({"nodes": nodes}, ensure_ascii=False), encoding="utf-8")
    (wf / "state_bindings.json").write_text(json.dumps({"bindings": [
        {"id": k, "project_id": k.split("-")[0], "family": "a"} for k in items]}), encoding="utf-8")
    (wf / "state_checkpoint.json").write_text(json.dumps({"items": {
        k: {"id": k, "family": "a", "current_node_id": v[0], "current_node": nodes[v[0]]["label"], "action": v[1],
            "required_output": nodes[v[0]]["required_output"]} for k, v in items.items()}}, ensure_ascii=False),
        encoding="utf-8")


class PipelineBoard(TempState, unittest.TestCase):
    def test_status_progress_and_today_changes(self):
        self.init()
        extra = self.base / "外部管线"
        make_pipeline(extra, {"SK008-A": ("A13", "ROLLBACK_REWORK"), "SK005-A": ("A15", "FORWARD_REQUEST")})
        abtool.cmd_ws_init(types.SimpleNamespace(root=None, designer=None, desktop_link=None, force=False,
                                                 pipeline=[str(extra)]))
        st = abtool.board_state()
        pipes = {p["name"]: p for p in st["pipelines"]}
        self.assertFalse(pipes["工作台/管线"]["ok"])  # 还没初始化
        ext = [p for p in st["pipelines"] if p["ok"]][0]
        by = {i["id"]: i for i in ext["items"]}
        self.assertEqual((by["SK008-A"]["index"], by["SK008-A"]["total"], by["SK008-A"]["action_label"]), (13, 15, "返工"))
        self.assertTrue(by["SK005-A"]["done"])
        self.assertEqual(st["pipeline_today"], [])  # 第一次只记快照
        make_pipeline(extra, {"SK008-A": ("A14", "FORWARD_REQUEST"), "SK005-A": ("A15", "CONTINUE")})
        st = abtool.board_state()
        self.assertEqual([(c["item"], c["from"], c["to"], c["kind"]) for c in st["pipeline_today"]],
                         [("SK008-A", "13 节点13", "14 节点14", "推进")])
        html = abtool.render_board(st)
        self.assertIn("今日完成", html)
        self.assertIn("13 节点13 → 14 节点14", html)
        self.assertIn("管线状态", html)
        self.assertIn("不是实时读取", html)
        abtool.board_state()  # 没变化不重复记
        self.assertEqual(len(abtool.board_state()["pipeline_today"]), 1)

    def test_bad_pipeline_path_rejected(self):
        self.init()
        with self.assertRaisesRegex(abtool.ToolError, "不是买量管线工作区"):
            abtool.cmd_ws_init(types.SimpleNamespace(root=None, designer=None, desktop_link=None, force=False,
                                                     pipeline=[str(self.base)]))

    def test_corrupt_checkpoint_does_not_break_board(self):
        self.init()
        make_pipeline(self.root / "管线", {"SK1-A": ("A02", "CONTINUE")})
        (self.root / "管线" / "workflow" / "state_checkpoint.json").write_text("{坏", encoding="utf-8")
        st = abtool.board_state()
        self.assertFalse(st["pipelines"][0]["ok"])
        self.assertIn("读不了", st["pipelines"][0]["reason"])
        self.assertTrue(abtool.write_board()["ok"])



@unittest.skipUnless(os.name == "nt", "只在 Windows 上检查真实 .lnk")
class RealWindowsShortcut(TempState, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.desk = self.base / "桌面 测试"
        self.desk.mkdir()

    def test_real_lnk(self):
        target = self.base / "目标 文件夹"
        target.mkdir()
        link = self.desk / "今日待上传.lnk"
        abtool.make_lnk(link, target)
        self.assertTrue(link.is_file() and link.stat().st_size > 0)
        # 读回快捷方式的目标，确认中文路径原样保存
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8;(New-Object -ComObject Shell.Application).NameSpace($env:D).ParseName($env:N).GetLink.Path"],
                           env={**os.environ, "D": str(self.desk), "N": link.name}, capture_output=True)
        got = r.stdout.decode("utf-8", "replace").strip()
        same = lambda x: os.path.normcase(str(Path(x).resolve()))  # 统一 8.3 短名（RUNNER~1）和长名
        self.assertEqual(same(got), same(target))

    def test_generated_files_stable_across_reruns(self):
        self.init()
        r = self.init(designer=None)
        self.assertEqual({f["action"] for f in r["files"]}, {"unchanged"})
        self.assertFalse((self.root / "AGENTS.新版.md").exists())
