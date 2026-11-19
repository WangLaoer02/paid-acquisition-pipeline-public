#!/usr/bin/env python3
"""接B · 命名 · 上传准备 —— 给同事电脑上的 Codex 调用的本地工具。

只做本地处理：FFmpeg 接片、按公司规则命名、技术核查、生成上传清单。
不登录、不读取账号或密码、不访问后台、不上传。上传由本人在自己的后台账号完成。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "0.6.1"
ILLEGAL = re.compile(r'[\\/\x00-\x1f:*?"<>|]')
FORMAL = re.compile(r'^(\d{6})([A-Za-z]+)(\d+)(?:-(.+))?$')
HOME = Path(os.environ.get("AB_TOOL_HOME", Path.home() / ".ab-join-name-upload"))


class ToolError(Exception):
    pass


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tool(name):
    found = shutil.which(name)
    if not found:
        raise ToolError(f"找不到 {name}，请先安装 FFmpeg（含 ffprobe）")
    return found


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------- 配置
def load_json(path, label):
    p = Path(path).expanduser()
    if not p.is_file():
        raise ToolError(f"缺少{label}：{p}。先运行 install.sh 或从飞书同步配置")
    return json.loads(p.read_text(encoding="utf-8"))


def load_people(path=None):
    data = load_json(path or HOME / "codes.json", "代号表 codes.json")
    people = data.get("people") or {}
    if not isinstance(people, dict):
        raise ToolError("codes.json 的 people 必须是 {代号: 后台姓名}")
    return people


# ---------------------------------------------------------------- 本机上传台账
LEDGER_COLS = ["时间", "素材名称", "日期", "设计师码", "序号", "第二设计师", "B库ID", "SHA256", "上传文件", "状态", "素材ID"]


def ledger_path():
    return HOME / "上传台账.csv"


def ledger_rows():
    import csv
    p = ledger_path()
    if not p.is_file():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def ledger_write(rows):
    import csv
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".partial")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LEDGER_COLS})
    tmp.replace(p)


def ledger_upsert(row):
    rows = ledger_rows()
    row = {**row, "时间": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    for r in rows:
        if r["素材名称"] == row["素材名称"]:
            if r.get("素材ID"):  # 已回填素材ID的记录不被覆盖
                return
            r.update(row)
            break
    else:
        rows.append(row)
    ledger_write(rows)


def retire(row, reason):
    rows = ledger_rows()
    for r in rows:
        if r["素材名称"] == row["素材名称"] and not r.get("素材ID"):
            src = Path(r["上传文件"]) if r.get("上传文件") else None
            if src and src.parent.is_dir():
                dest_dir = src.parent / "作废"
                for f in src.parent.glob(glob_escape(r["素材名称"]) + "*"):
                    dest_dir.mkdir(exist_ok=True)
                    f.replace(dest_dir / f.name)
            r["状态"] = reason
    ledger_write(rows)


def glob_escape(s):
    import glob
    return glob.escape(s)


def cmd_record(args):
    if not re.fullmatch(r"\d+", str(args.record_id)):
        raise ToolError("素材 ID 应是后台显示的数字")
    rows = ledger_rows()
    hit = [r for r in rows if r["素材名称"] in (args.name, Path(args.name).stem)]
    if not hit:
        raise ToolError(f"本机台账里没有「{args.name}」：先用 package / run 出清单")
    r = hit[0]
    if r.get("素材ID") and r["素材ID"] != str(args.record_id):
        raise ToolError(f"「{r['素材名称']}」已记过素材 ID {r['素材ID']}，与本次 {args.record_id} 不同，请核对后台")
    r.update({"素材ID": str(args.record_id), "状态": "已上传", "时间": dt.datetime.now().strftime("%Y-%m-%d %H:%M")})
    ledger_write(rows)
    sheet = Path(r["上传文件"]).with_name(r["素材名称"] + ".上传清单.json")
    if sheet.is_file():
        d = json.loads(sheet.read_text(encoding="utf-8"))
        d["upload_status"] = f"已上传：素材 ID {args.record_id}（本人回填）"
        sheet.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "name": r["素材名称"], "record_id": str(args.record_id), "ledger": str(ledger_path())}


# ---------------------------------------------------------------- 选 B 台
def load_library(path=None):
    cfg = load_json(path or HOME / "library.json", "选B台配置 library.json")
    base = cfg.get("base_url") or ""
    if "选B台地址" in base or not base.isascii():
        raise ToolError("还没设置选B台地址：请导入负责人发的团队配置（import-config），或用 set-library 设置")
    if not re.match(r"^https?://", base):
        raise ToolError("library.json 的 base_url 必须是选B台地址，如 https://xxx/pick/")
    cfg["base_url"] = base if base.endswith("/") else base + "/"
    cfg["cache_dir"] = str(Path(cfg.get("cache_dir") or HOME / "b-cache").expanduser())
    return cfg


def ssl_context():
    """始终校验证书。python.org 版 Python 可能没装根证书，此时改用 certifi 或系统证书包。"""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca"):
        return ctx
    candidates = [os.environ.get("AB_CA_BUNDLE")]
    try:
        import certifi
        candidates.append(certifi.where())
    except ImportError:
        pass
    candidates += ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"]
    for ca in candidates:
        if ca and Path(ca).is_file():
            return ssl.create_default_context(cafile=ca)
    return ctx


def http_get(url, dest=None, timeout=120, attempts=3):
    """GET；断流、超时等临时错误自动重试，HTTP 4xx/5xx 不重试。"""
    import http.client
    import time
    req = urllib.request.Request(url, headers={"User-Agent": f"abtool/{VERSION}"})
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
                if dest is None:
                    return r.read()
                with open(dest, "wb") as f:
                    shutil.copyfileobj(r, f, 1 << 20)
                return None
        except urllib.error.HTTPError as e:
            raise ToolError(f"选B台返回 HTTP {e.code}：{url}") from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
            last = e
            if i + 1 < attempts:
                time.sleep(1.5 * (i + 1))
        except (UnicodeError, ValueError) as e:
            raise ToolError(f"选B台地址无效：{url}（{type(e).__name__}）") from None
    raise ToolError(f"连不上选B台或传输中断（已重试 {attempts} 次；地址可能已变或服务不稳）：{url}：{type(last).__name__}") from None


def lib_items(cfg):
    raw = http_get(cfg["base_url"] + "data/fact.json?t=" + str(int(dt.datetime.now().timestamp())))
    try:
        data = json.loads(raw)
    except ValueError:
        raise ToolError("选B台数据不是有效 JSON") from None
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ToolError("选B台数据里没有 B 段条目")
    usable, uncut = [], []
    for it in items:
        if not it.get("lib_id") or not it.get("title"):
            continue
        # 只有截好、有文件和校验值、有来源编号的才能接；其余（如 VB- 虚拟条目）只做截取建议
        if all(it.get(k) for k in ("clip", "clip_sha256", "source_code")):
            usable.append(it)
        else:
            uncut.append(it)
    LAST_UNCUT[:] = uncut
    if not usable:
        raise ToolError("选B台里没有已截好、可下载的 B 段")
    return usable, data.get("generated_at")


LAST_UNCUT = []


def uncut_suggestions(a_role=None, limit=3):
    """还没截成 B 段、但效果够格的标题：建议负责人截取入库。"""
    pay = lambda it: it.get("pay_effective_count") or 0
    spend = lambda it: it.get("spend_effective_count") or 0
    good = [it for it in LAST_UNCUT if pay(it) >= 1 and spend(it) >= 1]
    good.sort(key=lambda it: (-int(role_match(a_role, it.get("main_role"))), -pay(it), -spend(it)))
    return [{"title": it["title"], "main_role": it.get("main_role"), "pay_effective_count": pay(it),
             "spend_effective_count": spend(it), "footage_count": it.get("footage_count")} for it in good[:limit]]


def lib_find(items, query):
    q = (query or "").strip()
    if not q:
        raise ToolError("请给出选B台里的库 ID（NB-…）或 B 段标题")
    exact = [it for it in items if q in (it["lib_id"], it["title"], it["source_code"])]
    hits = exact or [it for it in items if q in it["title"]]
    if not hits and any(q in (it["lib_id"], it["title"]) or q in it["title"] for it in LAST_UNCUT):
        raise ToolError(f"「{q}」在选B台里还没截成可下载的 B 段，请负责人截取入库后再用")
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ToolError(f"选B台里找不到「{q}」")
    raise ToolError(f"「{q}」匹配到 {len(hits)} 条，请用库 ID 指定：" +
                    "；".join(f"{it['lib_id']} {it['title']}" for it in hits))


def lib_fetch(cfg, item):
    cache = Path(cfg["cache_dir"])
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / Path(item["clip"]).name
    if dest.is_file() and sha256(dest) == item["clip_sha256"]:
        return dest, "cache"
    url = cfg["base_url"] + urllib.parse.quote(item["clip"])
    part = dest.with_name(dest.name + ".partial")
    try:
        http_get(url, part)
    except ToolError as e:
        part.unlink(missing_ok=True)
        if "HTTP 404" in str(e):
            raise ToolError("选B台服务没有开放 B 段下载（HTTP 404）：请维护者开放 B段/*.mp4") from None
        raise
    got = sha256(part)
    if got != item["clip_sha256"]:
        part.unlink(missing_ok=True)
        raise ToolError(f"下载的 B 段 SHA256 与选B台登记不符（{got[:12]}… ≠ {item['clip_sha256'][:12]}…），已丢弃")
    part.replace(dest)
    return dest, "downloaded"


PICK_DEFAULTS = {"effective": 2, "new": 1, "new_max_uses": 30}


def role_match(a_role, b_role):
    """A 段角色与 B 段主推角色是否一致：互相包含即算（如 鼬／宇智波鼬；佐助／佐助、小樱）。"""
    a, b = (a_role or "").strip(), (b_role or "").strip()
    return bool(a and b and (a in b or b in a))


def lib_pick(items, *, rules=None, a_role=None):
    """按公司选 B 规则自动挑 B（同角色优先）：
    1) 有效素材（付费有效≥1 且 消耗有效≥1）取 N 条：先在与 A 段同角色的有效素材里按 付费有效 → 消耗有效 挑；
       同角色不够，才用不同角色的有效素材补，不拿不合格的同角色素材凑数；
    2) 新素材（接用次数 ≤ new_max_uses）取 M 条：先在同角色新素材里挑（有付费有效的优先，都没有选产出最新的）；
       同角色一条新素材都没有，才放宽到所有角色；
    第二设计师未登记的条目跳过并列出。没给 A 段角色时不按角色区分。"""
    r = {**PICK_DEFAULTS, **(rules or {})}
    pay = lambda it: it.get("pay_effective_count") or 0
    spend = lambda it: it.get("spend_effective_count") or 0
    uses = lambda it: it.get("footage_count") or 0
    same = lambda it: role_match(a_role, it.get("main_role"))
    tag = lambda it: ("同角色" if same(it) else "不同角色") if a_role else None

    def note(it, text):
        t = tag(it)
        return f"{t}（{it.get('main_role') or '角色未知'}）；{text}" if t else text

    ok, skipped = [], []
    for it in items:
        (ok if it.get("second_designer") else skipped).append(it)
    picks, used = [], set()

    eff = [it for it in ok if pay(it) >= 1 and spend(it) >= 1]
    eff.sort(key=lambda it: (-pay(it), -spend(it), -uses(it), it["lib_id"]))
    if a_role:
        eff = [it for it in eff if same(it)] + [it for it in eff if not same(it)]
    for it in eff[: r["effective"]]:
        used.add(it["lib_id"])
        picks.append({"slot": "有效素材", "same_role": same(it) if a_role else None,
                      "reason": note(it, f"付费有效 {pay(it)} 次、消耗有效 {spend(it)} 次"), "item": it})

    def best_new(pool):
        with_pay = sorted([it for it in pool if pay(it) >= 1],
                          key=lambda it: (-pay(it), -spend(it), uses(it), it["lib_id"]))
        if with_pay:
            return with_pay, True
        return sorted(pool, key=lambda it: (it.get("produced_at") or "", spend(it), -uses(it)), reverse=True), False

    new = [it for it in ok if uses(it) <= r["new_max_uses"] and it["lib_id"] not in used]
    same_new = [it for it in new if same(it)] if a_role else []
    ranked, has_pay = best_new(same_new or new)
    for it in ranked[: r["new"]]:
        used.add(it["lib_id"])
        text = (f"接用 {uses(it)} 次（新素材），付费有效 {pay(it)} 次" if has_pay else
                f"接用 {uses(it)} 次（新素材），暂无付费数据，按产出日期最新（{it.get('produced_at') or '未知'}）")
        if a_role and not same_new:
            text += "；同角色没有新素材，放宽到其他角色"
        picks.append({"slot": "新素材", "same_role": same(it) if a_role else None,
                      "reason": note(it, text), "item": it})

    shortfall = []
    got = {"有效素材": sum(p["slot"] == "有效素材" for p in picks), "新素材": sum(p["slot"] == "新素材" for p in picks)}
    if got["有效素材"] < r["effective"]:
        shortfall.append(f"有效素材只有 {got['有效素材']} 条，少 {r['effective'] - got['有效素材']} 条")
    if got["新素材"] < r["new"]:
        shortfall.append(f"接用 ≤{r['new_max_uses']} 次的新素材不足 {r['new']} 条")
    missed = [it for it in skipped if (pay(it) >= 1 and spend(it) >= 1) or uses(it) <= r["new_max_uses"]]
    notes = []
    if a_role:
        n_eff_same = sum(1 for p in picks if p["slot"] == "有效素材" and p["same_role"])
        if n_eff_same < r["effective"]:
            notes.append(f"与 A 段同角色（{a_role}）的有效素材只有 {n_eff_same} 条，其余用不同角色的有效素材补")
        if any(p["slot"] == "新素材" and not p["same_role"] for p in picks):
            notes.append(f"与 A 段同角色（{a_role}）没有新素材，新素材名额放宽到其他角色")
    return {"rules": r, "picks": picks, "shortfall": shortfall, "notes": notes, "a_role": a_role,
            "skipped_unregistered": skipped, "skipped_but_would_qualify": missed}


def lib_summary(it):
    return {k: it.get(k) for k in ("lib_id", "title", "main_role", "duration", "second_designer",
                                   "source_code", "produced_at", "adopted", "listened", "spend_effective_count",
                                   "pay_effective_count", "footage_count") if k in it}


# ---------------------------------------------------------------- 命名
def clean(value, label, allow_dash=False):
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{label}不能为空")
    if value != value.strip():
        raise ToolError(f"{label}首尾不能有空格")
    if ILLEGAL.search(value):
        raise ToolError(f'{label}含文件名非法字符（\\ / : * ? " < > |）')
    if not allow_dash and "-" in value:
        raise ToolError(f'{label}不能包含"-"，它是段分隔符')
    return value


def parse_formal(name):
    """解析一个按公司规则命名的素材名，返回日期、设计师码、序号与标题段。"""
    stem = Path(name).stem if name.lower().endswith(".mp4") else name
    m = FORMAL.match(stem)
    if not m:
        raise ToolError(f"无法从「{name}」解析设计师码：应以 YYMMDD+设计师码+序号- 开头")
    date, code, serial, rest = m.groups()
    segs = rest.split("-") if rest else [None]
    return {"date": date, "designer": code.upper(), "serial": int(serial),
            "title": segs[0], "tail": segs[1:]}


def resolve_date(value):
    if value in (None, "", "today"):
        tz = dt.timezone(dt.timedelta(hours=8))  # Asia/Shanghai
        return dt.datetime.now(tz).strftime("%y%m%d"), True
    if not re.fullmatch(r"\d{6}", value):
        raise ToolError("日期必须是 YYMMDD")
    try:
        dt.datetime.strptime(value, "%y%m%d")
    except ValueError:
        raise ToolError(f"日期 {value} 不是有效的 YYMMDD") from None
    return value, False


def build_name(*, date, designer, serial, a_title, b_name=None, demand, intern=None,
               b_title=None, role_token=None, people=None, b_lib=None):
    """b_name：按公司规则命名的 B 段正式名，第二设计师取其开头设计师码。
    b_lib：选B台条目，第二设计师取库里登记值（源成片后台登记的实际 B 段制作者）。"""
    date, date_is_today = resolve_date(date)
    designer = clean(designer, "设计师码").upper()
    if not re.fullmatch(r"[A-Z]+", designer):
        raise ToolError("设计师码只能是字母")
    if isinstance(serial, bool) or not isinstance(serial, int) or serial < 1:
        raise ToolError("序号必须是正整数（当天该设计师已有最大序号＋1）")
    a_title = clean(a_title, "A段标题")
    if (b_name is None) == (b_lib is None):
        raise ToolError("B 段要么给后台正式名称，要么给选B台库 ID，二选一")
    demand = clean(demand or "原创", "需求人代号")
    if intern is not None and intern != "":
        intern = clean(intern, "实习生代号")
    else:
        intern = None
    people = people if people is not None else {}

    if b_lib is not None:
        b = parse_formal(b_lib["source_code"])
        b_title = clean(b_title or b_lib["title"], "B段标题")
        b_name = f"{b_lib['source_code']}（选B台 {b_lib['lib_id']}）"
        second = b_lib.get("second_designer") or None
        if not second:
            raise ToolError(f"选B台 {b_lib['lib_id']}「{b_lib['title']}」的第二设计师未登记，待核：先在库里补齐再接")
        own = people.get(designer)
        if not own:
            raise ToolError(f"本人设计师码 {designer} 不在代号表里，无法判断这段 B 是否本人所做")
        split = second != own
        if not split:
            second = None
        attribution = "选B台登记"
    else:
        b = parse_formal(clean(b_name, "B段完整名称", allow_dash=True))
        if not (b_title or b["title"]):
            raise ToolError("B段名称里没有标题段，请用 --b-title 给出 B 段标题")
        b_title = clean(b_title or b["title"], "B段标题")
        split = b["designer"] != designer
        second = None
        if split:
            second = people.get(b["designer"])
            if not second:
                raise ToolError(f"B段设计师码 {b['designer']} 不在代号表里，第二设计师待核，先补代号表")
        attribution = "B段名称开头设计师码"
    demand_name = None
    if demand != "原创":
        demand_name = people.get(demand.upper()) or people.get(demand)
        if not demand_name:
            raise ToolError(f"需求人代号 {demand} 不在代号表里，先补代号表")

    title = f"{a_title}接{b_title}"
    if role_token and role_token not in title:
        raise ToolError(f"正式名称缺少主推角色词「{role_token}」")
    parts = [f"{date}{designer}{serial}", title, demand]
    if intern:
        parts.append(intern)
    if split:
        parts.append("37")
    name = "-".join(parts)
    return {
        "name": name,
        "filename": name + ".mp4",
        "date": date,
        "date_defaulted_to_today": date_is_today,
        "designer": designer,
        "designer_name": people.get(designer),
        "serial": serial,
        "a_title": a_title,
        "b_title": b_title,
        "b_source_name": b_name,
        "b_designer": b["designer"],
        "demand": demand,
        "demand_name": demand_name,
        "intern": intern,
        "split_37": split,
        "second_designer": second,
        "second_designer_source": attribution,
        "b_lib_id": b_lib["lib_id"] if b_lib else None,
        "b_main_role": (b_lib.get("main_role") or None) if b_lib else None,
        "rule": "{YYMMDD}{设计师码}{序号}-{A段标题}接{B段标题}-{需求人代号|原创}[-{实习生代号}][-37]",
    }


# ---------------------------------------------------------------- 媒体
def probe(path):
    p = Path(path).expanduser()
    if not p.is_file():
        raise ToolError(f"文件不存在：{p}")
    r = run([tool("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(p)])
    if r.returncode:
        raise ToolError(f"读取媒体失败：{p.name}：{r.stderr[:300]}")
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        raise ToolError(f"{p.name} 没有视频流")
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den or 1)
    return {"path": str(p), "duration": float(d["format"]["duration"]),
            "width": int(v["width"]), "height": int(v["height"]), "fps": round(fps, 3),
            "fps_expr": v.get("r_frame_rate"), "vcodec": v["codec_name"],
            "acodec": a["codec_name"] if a else None,
            "sample_rate": int(a["sample_rate"]) if a else None}


def loudness(path, start=None, end=None):
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += ["-i", str(path), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"]
    r = run(cmd)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if r.returncode or not m:
        raise ToolError(f"响度测量失败：{Path(path).name}")
    i = float(json.loads(m[-1])["input_i"])
    return None if i == float("-inf") or i < -70 else i


def resolve_lib_b(args):
    cfg = load_library(getattr(args, "library", None))
    items, generated = lib_items(cfg)
    item = lib_find(items, args.b_id)
    return cfg, item, generated


def cmd_join(args):
    b_lib = None
    if (args.b is None) == (args.b_id is None):
        raise ToolError("B 段要么给本机文件 --b，要么给选B台 --b-id，二选一")
    if args.b_id:
        cfg, b_lib, _ = resolve_lib_b(args)
        path, how = lib_fetch(cfg, b_lib)
        args.b = str(path)
        b_lib = {**lib_summary(b_lib), "clip_sha256": b_lib["clip_sha256"], "fetched": how}
    a, b = probe(args.a), probe(args.b)
    if not a["acodec"]:
        raise ToolError("A 段没有音轨：按已确认的声音方案处理后再接，工具不会自行补配音或音乐")
    if not b["acodec"]:
        raise ToolError("B 段没有音轨，先确认 B 素材")
    outp = Path(args.out).expanduser()
    if outp.exists():
        raise ToolError(f"输出已存在，不覆盖：{outp}")
    bs = args.b_start or 0.0
    be = args.b_end if args.b_end is not None else b["duration"]
    if not 0 <= bs < be <= b["duration"] + 0.01:
        raise ToolError(f"B 段切点无效：{bs}–{be}（B 全长 {b['duration']:.3f} 秒）")
    total = a["duration"] + (be - bs)

    a_i = loudness(a["path"])
    b_i = loudness(b["path"], bs, be)
    gain = 0.0
    if a_i is not None and b_i is not None:
        gain = max(-15.0, min(15.0, round(a_i - b_i, 2)))

    W, H, fps = a["width"], a["height"], a["fps_expr"] or str(a["fps"])
    same_aspect = abs(b["width"] / b["height"] - W / H) < 0.01
    blur = max(1, min(20, min(W, H) // 4 - 1))  # 色度半径不能超过画面短边的 1/4
    if same_aspect:
        bv = f"[1:v]trim={bs}:{be},setpts=PTS-STARTPTS,scale={W}:{H},fps={fps},setsar=1,format=yuv420p[vb]"
    else:  # 不裁关键画面：完整居中 + 同画面模糊铺底
        bv = (f"[1:v]trim={bs}:{be},setpts=PTS-STARTPTS,fps={fps},split[b1][b2];"
              f"[b1]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur={blur}:2[bg];"
              f"[b2]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[vb]")
    fc = [f"[0:v]fps={fps},setsar=1,format=yuv420p[va]", bv,
          "[0:a]aresample=48000,aformat=channel_layouts=stereo[aa]",
          f"[1:a]atrim={bs}:{be},asetpts=PTS-STARTPTS,volume={gain}dB,aresample=48000,aformat=channel_layouts=stereo[ab]",
          "[va][aa][vb][ab]concat=n=2:v=1:a=1[cv][ca]"]
    inputs = ["-i", a["path"], "-i", b["path"]]
    last = "cv"
    idx = 2
    if args.overlay:
        inputs += ["-loop", "1", "-i", str(Path(args.overlay).expanduser())]
        fc.append(f"[{idx}:v]scale={W}:{H}[ov];[{last}][ov]overlay=0:0:shortest=1[cv{idx}]")
        last, idx = f"cv{idx}", idx + 1
    if args.watermark:
        inputs += ["-stream_loop", "-1", "-i", str(Path(args.watermark).expanduser())]
        fc.append(f"[{idx}:v]scale={W}:-1[wm];[{last}][wm]overlay=0:0:shortest=1[cv{idx}]")
        last, idx = f"cv{idx}", idx + 1
    outp.parent.mkdir(parents=True, exist_ok=True)
    tmp = outp.with_name(outp.stem + ".partial.mp4")
    cmd = [tool("ffmpeg"), "-hide_banner", "-y", *inputs, "-filter_complex", ";".join(fc),
           "-map", f"[{last}]", "-map", "[ca]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(tmp)]
    r = run(cmd)
    if r.returncode:
        tmp.unlink(missing_ok=True)
        raise ToolError("FFmpeg 接片失败：" + r.stderr[-800:])
    tmp.rename(outp)
    record = {"tool": f"abtool {VERSION}", "kind": "FFmpeg接片成片",
              "a": {**a, "sha256": sha256(a["path"]), "loudness_lufs": a_i},
              "b": {**b, "sha256": sha256(b["path"]), "start": bs, "end": be, "loudness_lufs": b_i},
              "b_gain_db": gain, "a_length_note": a_length_note(a["duration"]), "b_layout": "same-aspect-scale" if same_aspect else "fit+blur-background",
              "b_library": b_lib,
              "overlay": args.overlay, "watermark": args.watermark,
              "output": str(outp), "output_sha256": sha256(outp), "expected_duration": round(total, 3)}
    outp.with_suffix(".join.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


A_MIN, A_MAX = 10.0, 25.0  # 时长规则只管 A 段；成片总时长（A+B）不设上限


def a_length_note(seconds):
    if seconds is None or A_MIN <= seconds <= A_MAX:
        return None
    return f"A 段 {seconds:.3f} 秒，不在 A 段默认 {A_MIN:g}–{A_MAX:g} 秒内；有明确要求时以要求为准"


def check_file(path):
    """成片技术核查。不检查总时长：时长规则只针对 A 段。"""
    info = probe(path)
    r = run([tool("ffmpeg"), "-v", "error", "-i", info["path"], "-f", "null", "-"])
    problems, warnings = [], []
    if r.returncode or r.stderr.strip():
        problems.append("完整解码有错误")
    if Path(info["path"]).suffix.lower() != ".mp4":
        problems.append("不是 .mp4 文件")
    if info["vcodec"] != "h264":
        problems.append(f"视频编码是 {info['vcodec']}，需要 h264")
    if info["acodec"] != "aac":
        problems.append(f"音频编码是 {info['acodec']}，需要 aac（且必须有音轨）")
    return {**info, "sha256": sha256(info["path"]), "full_decode_exit": r.returncode,
            "full_decode_errors": r.stderr.strip()[:2000], "technical_ok": not problems,
            "problems": problems, "warnings": warnings,
            "not_covered": "技术核查不代替人工看听：接点、片尾、字幕、标语和水印需本人确认"}


# ---------------------------------------------------------------- 上传清单
def naming_from_args(args, people):
    b_lib = None
    if getattr(args, "b_id", None):
        if args.b_name:
            raise ToolError("--b-name 和 --b-id 只能给一个")
        _cfg, b_lib, _ = resolve_lib_b(args)
    return build_name(date=args.date, designer=args.designer, serial=args.serial,
                      a_title=args.a_title, b_name=args.b_name if not b_lib else None,
                      demand=args.demand, intern=args.intern, b_title=args.b_title,
                      role_token=args.role_token, people=people, b_lib=b_lib)


def cmd_package(args):
    people = load_people(args.codes)
    fields_cfg = load_json(args.fields or HOME / "fields.json", "上传字段表 fields.json")
    naming = naming_from_args(args, people)
    chk = check_file(args.file)
    if not chk["technical_ok"]:
        raise ToolError("技术核查未通过：" + "；".join(chk["problems"]))
    outdir = Path(args.out_dir).expanduser()
    dest = outdir / naming["filename"]
    if dest.exists() and sha256(dest) != chk["sha256"]:
        raise ToolError(f"同名文件已存在且内容不同，不覆盖：{dest}")

    def pick(key, value):
        opts = fields_cfg.get(key, {}).get("options")
        if value in (None, ""):
            return None
        vals = value if isinstance(value, list) else [value]
        if opts is not None:
            bad = [x for x in vals if x not in opts]
            if bad:
                raise ToolError(f"{fields_cfg[key]['label']}不在可选项里：{bad}；可选：{list(opts)}")
        return vals if isinstance(value, list) else value

    dflt = fields_cfg.get("defaults") or {}
    use = lambda v, k: v if v not in (None, [], "") else dflt.get(k)
    category = pick("category", use(args.category, "category"))
    game = pick("game", use(getattr(args, "game", None), "game")) if "game" in fields_cfg else None
    source_type = pick("source_type", use(args.source_type, "source_type"))
    source_direction = pick("source_direction", use(args.source_direction, "source_direction"))
    ai = pick("ai", use(args.ai, "ai")) if "ai" in fields_cfg else (args.ai or None)
    # 需求人、第二设计师必须是后台下拉里真实存在的人（字段表有该项时校验）
    if naming["demand_name"] and "demand" in fields_cfg and naming["demand_name"] not in fields_cfg["demand"]["options"]:
        raise ToolError(f"需求人「{naming['demand_name']}」不在后台需求人下拉里，请负责人核对代号表")
    second_value = None
    if naming["second_designer"] and "second_designer" in fields_cfg:
        second_value = fields_cfg["second_designer"]["options"].get(naming["second_designer"])
        if not second_value:
            raise ToolError(f"第二设计师「{naming['second_designer']}」不在后台第二设计师下拉里，请负责人核对")
    clash = [r for r in ledger_rows() if r["日期"] == naming["date"] and r["设计师码"] == naming["designer"]
             and r["序号"] == str(naming["serial"]) and r["素材名称"] != naming["name"]
             and not r["状态"].startswith("作废")]
    used = [r for r in clash if r.get("素材ID")]
    if used:
        raise ToolError(f"序号 {naming['date']}{naming['designer']}{naming['serial']} 已上传为「{used[-1]['素材名称']}」"
                        f"（素材ID {used[-1]['素材ID']}），请换下一个序号")
    # 角色标签：手动指定优先；否则默认取 B 段主推角色（A、B 角色可以不一致）
    if args.role:
        roles, role_from = pick("role", args.role), "手动指定"
    elif naming.get("b_main_role"):
        try:
            roles = pick("role", [naming["b_main_role"]])
        except ToolError:
            raise ToolError(f"B 段主推角色「{naming['b_main_role']}」不在角色标签可选项里："
                            f"请负责人补字段表，或用 --role 指定后台里的角色") from None
        role_from = "默认取 B 段主推角色"
    else:
        roles, role_from = None, None
    form = [
        ["素材名称", naming["name"]],
        ["项目分类", category or "待填"],
        ["游戏", game or ("待填" if "game" in fields_cfg else "按项目")],
        ["角色标签", "、".join(roles or []) or "待填（必填）"],
        ["一类", "、".join(source_type or []) or "待填"],
        ["二类", "、".join(source_direction or []) or "待填"],
        ["AI 方式", ai if ai and ai != "无" else "无（非 AI）"],
        ["需求人", naming["demand_name"] or "原创（无需求人）"],
        ["第二设计师", naming["second_designer"] or "原创（B 段是自己做的，留空）"],
        ["是否红包", dflt.get("is_redbag", "否")],
    ]
    pending = [k for k, v in form if v.startswith("待填")]
    # 所有校验通过后才落盘，避免留下没有清单的正式名文件
    outdir.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_name(dest.name + ".partial")
        shutil.copy2(chk["path"], tmp)
        tmp.rename(dest)
    sheet = {"tool": f"abtool {VERSION}", "upload_file": str(dest), "naming": naming,
             "check": chk, "form": dict(form), "role_source": role_from, "pending_fields": pending,
             "backend_values": {"category_type": (fields_cfg.get("category", {}).get("options") or {}).get(category),
                                "gid": (fields_cfg.get("game", {}).get("options") or {}).get(game),
                                "region_type": second_value or ""},
             "upload_status": "未上传：由本人登录自己的后台账号上传，上传后用 record 回填素材ID"}
    for r in clash:  # 同序号、还没上传的旧清单作废，文件移走，避免误传
        retire(r, f"作废：序号改给 {naming['name']}")
    ledger_upsert({"素材名称": naming["name"], "日期": naming["date"], "设计师码": naming["designer"],
                   "序号": str(naming["serial"]), "第二设计师": naming["second_designer"] or "",
                   "B库ID": naming.get("b_lib_id") or "", "SHA256": chk["sha256"],
                   "上传文件": str(dest), "状态": "已出清单", "素材ID": ""})
    js = outdir / (naming["name"] + ".上传清单.json")
    md = outdir / (naming["name"] + ".上传清单.md")
    js.write_text(json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# 上传清单：{naming['name']}", "",
             f"- 上传文件：`{dest}`", f"- SHA256：`{chk['sha256']}`",
             f"- 时长：{chk['duration']:.3f} 秒 · {chk['width']}×{chk['height']} · {chk['vcodec']}/{chk['acodec']}",
             f"- 分成：{'有第二设计师，名称带 -37（编号设计师 3 份，第二设计师 7 份）' if naming['split_37'] else '无第二设计师，不带 -37'}",
             f"- B 段：{naming['b_source_name']}；第二设计师依据：{naming['second_designer_source']}",
             f"- 角色标签依据：{role_from or '未提供，需补'}",
             "", "| 后台表单 | 填写 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in form]
    lines += ["", "## 上传步骤",
              "1. 本人完整看一遍成片（接点、片尾、字幕、标语、水印）。",
              f"2. 在后台视频列表搜索「{naming['date']}{naming['designer']}」，确认 {naming['date']}{naming['designer']}{naming['serial']} 还没被用；被用了就让 Codex 换下一个序号重出。",
              "3. 打开『新增视频』，按上表先填名称和全部字段，**最后**再选择文件（选文件会立刻开始上传）。",
              "4. 入库后把素材 ID 告诉 Codex，它会记到本机上传台账。"]
    if chk["warnings"]:
        lines += ["", "注意：" + "；".join(chk["warnings"])]
    if pending:
        lines += ["", "仍需补充：" + "、".join(pending)]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "upload_file": str(dest), "sheet_md": str(md), "sheet_json": str(js),
            "name": naming["name"], "second_designer": naming["second_designer"],
            "pending_fields": pending, "warnings": chk["warnings"]}


def cmd_run(args):
    """一条命令：自动选 B → 下载校验 → 接片 → 核查 → 按连续序号命名出清单。"""
    cfg = load_library(args.library)
    items, generated = lib_items(cfg)
    a_info = probe(args.a)
    picked = lib_pick(items, rules=cfg.get("pick"), a_role=args.a_role)
    if not picked["picks"]:
        raise ToolError("选B台里没有可用的 B（可能都缺第二设计师登记）")
    out_dir = Path(args.out_dir or (Path.home() / "Desktop" / "待上传")).expanduser()
    work = HOME / "work"
    results, serial = [], args.serial
    for p in picked["picks"]:
        it = p["item"]
        row = {"slot": p["slot"], "same_role": p["same_role"], "reason": p["reason"], "lib_id": it["lib_id"],
               "title": it["title"]}
        try:
            joined = work / f"{it['lib_id']}_{sha256(args.a)[:8]}.mp4"
            if not joined.is_file():
                cmd_join(argparse.Namespace(a=args.a, b=None, b_id=it["lib_id"], library=args.library,
                                            b_start=None, b_end=None, overlay=args.overlay,
                                            watermark=args.watermark, out=str(joined)))
            pkg = cmd_package(argparse.Namespace(
                file=str(joined), out_dir=str(out_dir), date=args.date, designer=args.designer, serial=serial,
                a_title=args.a_title, b_name=None, b_id=it["lib_id"], b_title=None, library=args.library,
                demand=args.demand, intern=args.intern, role_token=None, codes=args.codes, fields=args.fields,
                category=None, game=None, source_type=None, source_direction=None, role=None, ai=args.ai))
            row.update(ok=True, serial=serial, name=pkg["name"], second_designer=pkg["second_designer"],
                       sheet=pkg["sheet_md"], file=pkg["upload_file"])
            serial += 1
        except ToolError as e:
            row.update(ok=False, error=str(e))
        results.append(row)
    summary = out_dir / f"本次待上传_{dt.datetime.now().strftime('%m%d_%H%M')}.md"
    lines = [f"# 本次待上传（A 段：{Path(args.a).name}，{a_info['duration']:.1f} 秒）", ""]
    if a_length_note(a_info["duration"]):
        lines += [f"> {a_length_note(a_info['duration'])}", ""]
    lines += [f"> {n}" for n in picked["notes"]] + ([""] if picked["notes"] else [])
    lines += ["| # | 素材名称 | B 段 | 入选理由 | 第二设计师 |", "|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | {r.get('name') or '❌ ' + r.get('error', '')} | {r['title']} | {r['reason']} | "
                     f"{r.get('second_designer') or '—'} |")
    lines += ["", "每条的后台字段见同目录下的 `<素材名称>.上传清单.md`。上传顺序：先填名称和字段，最后选文件。"]
    if picked["skipped_but_would_qualify"]:
        lines += ["", "以下 B 段本可入选，但第二设计师未登记，已跳过（请负责人补登记）：" +
                  "、".join(it["title"] for it in picked["skipped_but_would_qualify"])]
    uncut = uncut_suggestions(args.a_role)
    if uncut:
        lines += ["", "选B台里还有效果好但没截成 B 段的标题（建议负责人截取入库）：" +
                  "、".join(f"{u['title']}（付费有效 {u['pay_effective_count']}、消耗有效 {u['spend_effective_count']}）" for u in uncut)]
    out_dir.mkdir(parents=True, exist_ok=True)
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": all(r.get("ok") for r in results), "out_dir": str(out_dir), "summary": str(summary),
            "generated_at": generated, "notes": picked["notes"], "shortfall": picked["shortfall"],
            "a_length_note": a_length_note(a_info["duration"]), "versions": results,
            "uncut_suggestions": uncut,
            "next_serial": serial}


CONFIG_FILES = ("codes.json", "fields.json", "library.json")


def cmd_import_config(args):
    """导入负责人发的团队配置（zip 或文件夹），旧配置先备份。团队配置不放进公开仓库。"""
    import tempfile
    import zipfile
    src = Path(args.source).expanduser()
    if not src.exists():
        raise ToolError(f"找不到团队配置：{src}")
    tmp = None
    if src.is_file() and zipfile.is_zipfile(src):
        tmp = Path(tempfile.mkdtemp(prefix="ab-config-"))
        with zipfile.ZipFile(src) as z:
            for m in z.namelist():
                if Path(m).name in CONFIG_FILES and not m.endswith("/"):
                    (tmp / Path(m).name).write_bytes(z.read(m))
        src = tmp
    found = {n: src / n for n in CONFIG_FILES if (src / n).is_file()}
    if not found:
        raise ToolError("团队配置里没有 codes.json / fields.json / library.json")
    for n, p in found.items():
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            raise ToolError(f"团队配置 {n} 不是有效 JSON") from None
    HOME.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    done = []
    for n, p in found.items():
        dest = HOME / n
        if dest.is_file():
            if dest.read_bytes() == p.read_bytes():
                done.append({"file": n, "action": "unchanged"})
                continue
            dest.replace(HOME / f"{n}.bak-{ts}")
        shutil.copy2(p, dest)
        done.append({"file": n, "action": "imported"})
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    missing = [n for n in CONFIG_FILES if n not in found]
    return {"ok": not missing, "config_home": str(HOME), "files": done, "missing": missing}


def cmd_set_library(args):
    p = HOME / "library.json"
    d = load_json(p, "选B台配置 library.json") if p.is_file() else {}
    if not re.match(r"^https?://", args.url):
        raise ToolError("选B台地址应以 http(s):// 开头，如 https://选B台地址/pick/")
    d["base_url"] = args.url if args.url.endswith("/") else args.url + "/"
    HOME.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    items, generated = lib_items(load_library(p))
    return {"ok": True, "base_url": d["base_url"], "items": len(items), "generated_at": generated}


def cmd_doctor(_args):
    res = {"python": sys.version.split()[0], "python_ok": sys.version_info >= (3, 9),
           "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
           "config_home": str(HOME),
           "codes_json": (HOME / "codes.json").is_file(), "fields_json": (HOME / "fields.json").is_file(),
           "library_json": (HOME / "library.json").is_file(), "version": VERSION}
    res["ok"] = all([res["python_ok"], res["ffmpeg"], res["ffprobe"], res["codes_json"], res["fields_json"]])
    if res["library_json"]:
        try:
            items, generated = lib_items(load_library())
            res["library"] = {"reachable": True, "items": len(items), "generated_at": generated}
        except Exception as e:  # doctor 只报告，绝不因选B台检查崩溃
            res["library"] = {"reachable": False, "error": str(e) if isinstance(e, ToolError) else type(e).__name__}
    return res


def main(argv=None):
    p = argparse.ArgumentParser(prog="abtool", description="接B·命名·上传准备（本地，不上传）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="检查 Python、FFmpeg 和配置")
    s = sub.add_parser("probe", help="读取媒体规格"); s.add_argument("file")
    s = sub.add_parser("lib-list", help="列出选B台里的 B 段（可按关键词或角色筛）")
    s.add_argument("--q", help="标题／库ID／来源编号关键词"); s.add_argument("--role", help="主推角色")
    s.add_argument("--library", help="选B台配置，默认 ~/.ab-join-name-upload/library.json")
    s = sub.add_parser("lib-pick", help="按公司规则自动挑 B：2 条有效素材（先保证付费）＋1 条新素材")
    s.add_argument("--a", help="A 段文件，用来核对 A 段时长（10–25 秒）")
    s.add_argument("--a-role", help="A 段主推角色：优先选同角色的 B，没有优秀素材才选不同角色")
    s.add_argument("--effective", type=int, help="有效素材条数，默认 2")
    s.add_argument("--new", type=int, help="新素材条数，默认 1")
    s.add_argument("--new-max-uses", type=int, help="接用次数不超过多少算新素材，默认 30")
    s.add_argument("--library")
    s = sub.add_parser("lib-fetch", help="从选B台下载一条 B 段并校验 SHA256")
    s.add_argument("--b-id", required=True, help="库 ID（NB-…）或唯一的 B 段标题")
    s.add_argument("--library")
    s = sub.add_parser("join", help="FFmpeg 把完整 A 接到 B")
    s.add_argument("--a", required=True); s.add_argument("--b", help="本机 B 段文件")
    s.add_argument("--b-id", help="选B台库 ID 或唯一标题（自动下载并校验）"); s.add_argument("--library")
    s.add_argument("--b-start", type=float); s.add_argument("--b-end", type=float)
    s.add_argument("--overlay", help="全画面透明 PNG 标语（只在成片缺标语时使用）")
    s.add_argument("--watermark", help="透明运动水印 MOV（只在成片缺水印时使用）")
    s.add_argument("--out", required=True)
    s = sub.add_parser("check", help="技术核查：完整解码、编码、时长、SHA256")
    s.add_argument("file")

    def naming_args(s):
        s.add_argument("--date", default="today", help="YYMMDD，默认今天（北京时间）")
        s.add_argument("--designer", required=True, help="本人设计师码，如 LW")
        s.add_argument("--serial", required=True, type=int, help="当天该设计师已有最大序号＋1")
        s.add_argument("--a-title", required=True)
        s.add_argument("--b-name", help="B 段在后台的完整正式名称（第二设计师按开头设计师码）")
        s.add_argument("--b-id", help="选B台库 ID 或唯一标题（第二设计师按库里登记）")
        s.add_argument("--library", help="选B台配置，默认 ~/.ab-join-name-upload/library.json")
        s.add_argument("--b-title", help="不填则取 B 段名称的标题段")
        s.add_argument("--demand", default="原创", help="需求人代号；没有就是 原创")
        s.add_argument("--intern", help="实习生代号；没有不填")
        s.add_argument("--role-token", help="名称里必须出现的主推角色词，如 鼬")
        s.add_argument("--codes", help="代号表路径，默认 ~/.ab-join-name-upload/codes.json")

    s = sub.add_parser("name", help="按公司规则生成正式名称"); naming_args(s)
    s = sub.add_parser("package", help="核查成片、按正式名复制、生成上传清单"); naming_args(s)
    s.add_argument("--file", required=True); s.add_argument("--out-dir", required=True)
    s.add_argument("--fields", help="上传字段表，默认 ~/.ab-join-name-upload/fields.json")
    s.add_argument("--category", help="不填用团队默认"); s.add_argument("--game", help="不填用团队默认")
    s.add_argument("--source-type", nargs="*"); s.add_argument("--source-direction", nargs="*")
    s.add_argument("--role", nargs="*", help="不填默认取 B 段主推角色")
    s.add_argument("--ai", help="不填用团队默认；非 AI 写 无")

    s = sub.add_parser("run", help="一条命令：自动选 B → 下载 → 接片 → 核查 → 按连续序号命名出清单")
    s.add_argument("--a", required=True, help="A 段 MP4（PR 原生导出）")
    s.add_argument("--a-role", required=True, help="A 段主推角色")
    s.add_argument("--a-title", required=True, help="A 段标题（不含“-”）")
    s.add_argument("--designer", required=True, help="本人设计师码")
    s.add_argument("--serial", required=True, type=int, help="第 1 个版本的序号：后台当天本人最大序号＋1")
    s.add_argument("--date", default="today"); s.add_argument("--demand", default="原创")
    s.add_argument("--intern"); s.add_argument("--ai", help="不填用团队默认")
    s.add_argument("--out-dir", help="默认 桌面/待上传")
    s.add_argument("--overlay"); s.add_argument("--watermark")
    s.add_argument("--codes"); s.add_argument("--fields"); s.add_argument("--library")

    s = sub.add_parser("record", help="上传后回填素材 ID 到本机台账")
    s.add_argument("--name", required=True, help="素材名称（可带 .mp4）")
    s.add_argument("--record-id", required=True, help="后台显示的素材 ID")
    sub.add_parser("ledger", help="查看本机上传台账")
    s = sub.add_parser("import-config", help="导入负责人发的团队配置（zip 或文件夹）")
    s.add_argument("--from", dest="source", required=True)
    s = sub.add_parser("set-library", help="选B台地址变了时更新")
    s.add_argument("--url", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "doctor":
            r = cmd_doctor(a); out(r, 0 if r["ok"] else 2)
        if a.cmd == "run":
            r = cmd_run(a); out(r, 0 if r["ok"] else 1)
        if a.cmd == "record":
            out(cmd_record(a))
        if a.cmd == "ledger":
            rows = ledger_rows()
            out({"ok": True, "ledger": str(ledger_path()), "count": len(rows), "rows": rows[-30:]})
        if a.cmd == "import-config":
            r = cmd_import_config(a); out(r, 0 if r["ok"] else 1)
        if a.cmd == "set-library":
            out(cmd_set_library(a))
        if a.cmd == "probe":
            out(probe(a.file))
        if a.cmd == "join":
            out({"ok": True, **cmd_join(a)})
        if a.cmd == "check":
            r = check_file(a.file)
            Path(r["path"]).with_suffix(".check.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            out(r, 0 if r["technical_ok"] else 1)
        if a.cmd == "lib-list":
            items, generated = lib_items(load_library(a.library))
            sel = [it for it in items
                   if (not a.q or a.q in it["title"] or a.q in it["lib_id"] or a.q in it["source_code"])
                   and (not a.role or a.role == it.get("main_role"))]
            out({"ok": True, "generated_at": generated, "count": len(sel), "items": [lib_summary(it) for it in sel]})
        if a.cmd == "lib-pick":
            cfg = load_library(a.library)
            items, generated = lib_items(cfg)
            rules = {**(cfg.get("pick") or {})}
            for k, v in (("effective", a.effective), ("new", a.new), ("new_max_uses", a.new_max_uses)):
                if v is not None:
                    rules[k] = v
            res = lib_pick(items, rules=rules, a_role=a.a_role)
            a_dur = probe(a.a)["duration"] if a.a else None
            picks = [{"rank": i, "slot": p["slot"], "same_role": p["same_role"], "reason": p["reason"], **lib_summary(p["item"])}
                     for i, p in enumerate(res["picks"], 1)]
            out({"ok": bool(picks), "generated_at": generated, "rules": res["rules"], "picks": picks,
                 "a_duration": a_dur, "a_length_note": a_length_note(a_dur),
                 "shortfall": res["shortfall"], "notes": res["notes"], "a_role": res["a_role"],
                 "skipped_unregistered_count": len(res["skipped_unregistered"]),
                 "skipped_but_would_qualify": [
                     {**lib_summary(it), "why": "第二设计师未登记，补登记后才能选"} for it in res["skipped_but_would_qualify"]]},
                0 if picks else 1)
        if a.cmd == "lib-fetch":
            cfg, item, _ = resolve_lib_b(a)
            path, how = lib_fetch(cfg, item)
            out({"ok": True, "file": str(path), "fetched": how, **lib_summary(item), "clip_sha256": item["clip_sha256"]})
        if a.cmd == "name":
            out({"ok": True, **naming_from_args(a, load_people(a.codes))})
        if a.cmd == "package":
            out(cmd_package(a))
    except ToolError as e:
        out({"ok": False, "error": str(e)}, 1)


if __name__ == "__main__":
    main()
