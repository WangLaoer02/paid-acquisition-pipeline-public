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
        self.assertEqual(form["第二设计师"], "测试丙")
        self.assertEqual(form["角色标签"], "带土")
        self.assertEqual(r["pending_fields"], [])
        vals = json.loads(Path(r["sheet_json"]).read_text(encoding="utf-8"))["backend_values"]
        self.assertEqual(vals, {"category_type": "117", "gid": "193", "region_type": "1256"})

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
