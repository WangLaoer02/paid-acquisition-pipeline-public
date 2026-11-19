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

VERSION = "0.8.0"
ILLEGAL = re.compile(r'[\\/\x00-\x1f:*?"<>|]')
FORMAL = re.compile(r'^(\d{6})([A-Za-z]+)(\d+)(?:-(.+))?$')
# STATE：旧版配置目录，同时存放指向工作台的 workspace.json。HOME：当前生效的配置目录。
STATE = Path(os.environ.get("AB_TOOL_HOME", Path.home() / ".ab-join-name-upload"))
WS_FILE = "工作台.json"


def find_workspace():
    """工作台根目录：AB_WORKSPACE 优先，否则读 STATE/workspace.json；目录里必须有 工作台.json。"""
    env = os.environ.get("AB_WORKSPACE")
    if env:
        root = Path(env).expanduser()
    else:
        ptr = STATE / "workspace.json"
        if not ptr.is_file():
            return None
        try:
            root = Path(json.loads(ptr.read_text(encoding="utf-8"))["root"]).expanduser()
        except (ValueError, KeyError, TypeError):
            return None
    return root if (root / WS_FILE).is_file() else None


WS = find_workspace()
HOME = WS / "配置" if WS else STATE


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
    # Windows 默认代码页不是 UTF-8：FFmpeg 输出统一按 UTF-8 解码，坏字节替换掉，不让解码报错
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 配置
def load_json(path, label):
    p = Path(path).expanduser()
    if not p.is_file():
        raise ToolError(f"缺少{label}：{p}。先运行安装（install.py）或 import-config 导入团队配置")
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
    return WS / "台账" / "上传台账.csv" if WS else HOME / "上传台账.csv"


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
                # 工作台里作废件放到当天目录的 作废/，旧版放在输出目录下的 作废/
                dest_dir = src.parent.parent / "作废" if src.parent.name == DAY_DIRS[2] else src.parent / "作废"
                for f in material_files(src.parent, r["素材名称"]):
                    dest_dir.mkdir(exist_ok=True)
                    f.replace(dest_dir / f.name)
            r["状态"] = reason
    ledger_write(rows)


def material_files(folder, name):
    """某条素材自己的文件（成片、上传清单、核查记录）；不会误带上名称更长的另一条素材。"""
    return [f for f in folder.glob(glob_escape(name) + "*") if f.is_file() and SHEET_SUFFIX.sub("", f.name) == name]


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
    sheet = Path(r["上传文件"]).with_name(r["素材名称"] + ".上传清单.json")
    if sheet.is_file():
        d = json.loads(sheet.read_text(encoding="utf-8"))
        d["upload_status"] = f"已上传：素材 ID {args.record_id}（本人回填）"
        sheet.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    moved_to = None
    src = Path(r["上传文件"]) if r.get("上传文件") else None
    if WS and src and src.parent.name == DAY_DIRS[2] and src.parent.is_dir():
        # 工作台：已上传的成片和清单移到当天的 04_已上传
        done_dir = src.parent.parent / DAY_DIRS[3]
        done_dir.mkdir(exist_ok=True)
        for f in material_files(src.parent, r["素材名称"]):
            target = done_dir / f.name
            if not target.exists():
                f.replace(target)
        moved_to = str(done_dir)
        if (done_dir / src.name).is_file():
            r["上传文件"] = str(done_dir / src.name)
    ledger_write(rows)
    return {"ok": True, "name": r["素材名称"], "record_id": str(args.record_id), "ledger": str(ledger_path()),
            "moved_to": moved_to, "board": write_board()}


# ---------------------------------------------------------------- 选 B 台
def load_library(path=None):
    cfg = load_json(path or HOME / "library.json", "选B台配置 library.json")
    base = cfg.get("base_url") or ""
    if "选B台地址" in base or not base.isascii():
        raise ToolError("还没设置选B台地址：请导入负责人发的团队配置（import-config），或用 set-library 设置")
    if not re.match(r"^https?://", base):
        raise ToolError("library.json 的 base_url 必须是选B台地址，如 https://xxx/pick/")
    cfg["base_url"] = base if base.endswith("/") else base + "/"
    cfg["cache_dir"] = str(Path(cfg.get("cache_dir") or (WS / "B段缓存" if WS else HOME / "b-cache")).expanduser())
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
    # 团队规则：没有需求人时，后台“需求人”选本人（文件名里仍写“原创”）
    if naming["demand_name"]:
        demand_form, demand_from = naming["demand_name"], "需求人代号"
    else:
        own = naming.get("designer_name")
        if not own:
            raise ToolError(f"本人设计师码 {naming['designer']} 不在代号表里，无法确定需求人（没有需求人时填本人）")
        demand_form, demand_from = own, "没有需求人，按团队规则填本人"
    if "demand" in fields_cfg and demand_form not in fields_cfg["demand"]["options"]:
        raise ToolError(f"需求人「{demand_form}」不在后台需求人下拉里，请负责人核对团队配置")
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
        ["需求人", demand_form if naming["demand_name"] else f"{demand_form}（本人；没有需求人，名称里写“原创”）"],
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
                                "region_type": second_value or "", "demand_name": demand_form},
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
             f"- 需求人依据：{demand_from}",
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
    if WS:
        day = ensure_day(resolve_date(args.date)[0])
        out_dir = Path(args.out_dir).expanduser() if args.out_dir else day / DAY_DIRS[2]
        work = day / DAY_DIRS[1]
    else:
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
    link = desktop_link(out_dir) if WS and not args.out_dir else None
    board = write_board()
    return {"ok": all(r.get("ok") for r in results), "out_dir": str(out_dir), "summary": str(summary),
            "workspace": str(WS) if WS else None, "desktop_link": link, "board": board,
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
           "library_json": (HOME / "library.json").is_file(), "version": VERSION,
           "workspace": str(WS) if WS else None}
    res["ok"] = all([res["python_ok"], res["ffmpeg"], res["ffprobe"], res["codes_json"], res["fields_json"]])
    if res["library_json"]:
        try:
            items, generated = lib_items(load_library())
            res["library"] = {"reachable": True, "items": len(items), "generated_at": generated}
        except Exception as e:  # doctor 只报告，绝不因选B台检查崩溃
            res["library"] = {"reachable": False, "error": str(e) if isinstance(e, ToolError) else type(e).__name__}
    return res


# ---------------------------------------------------------------- 跨平台（macOS / Windows）
def _win_folder(*names):
    """Windows 的桌面、下载可能被 OneDrive 重定向：按注册表里的真实位置找。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            for n in names:
                try:
                    p = Path(os.path.expandvars(winreg.QueryValueEx(k, n)[0]))
                    if p.is_dir():
                        return p
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    return None


def desktop_dir():
    if os.environ.get("AB_DESKTOP"):
        return Path(os.environ["AB_DESKTOP"])
    if os.name == "nt":
        return _win_folder("Desktop") or Path.home() / "Desktop"
    return Path.home() / "Desktop"


def downloads_dir():
    if os.environ.get("AB_DOWNLOADS"):
        return Path(os.environ["AB_DOWNLOADS"])
    if os.name == "nt":
        return _win_folder("{374DE290-123F-4565-9164-39C4925E467B}") or Path.home() / "Downloads"
    return Path.home() / "Downloads"


def shortcut_mode():
    m = os.environ.get("AB_SHORTCUT")
    return m if m in ("symlink", "lnk") else ("lnk" if os.name == "nt" else "symlink")


LNK_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] class AbShellLink {}
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
interface IAbShellLinkW {
  void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder f, int c, IntPtr d, int fl);
  void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
  void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder n, int c);
  void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string n);
  void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder d, int c);
  void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string d);
  void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder a, int c);
  void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string a);
  void GetHotkey(out short k); void SetHotkey(short k);
  void GetShowCmd(out int s); void SetShowCmd(int s);
  void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder p, int c, out int i);
  void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string p, int i);
  void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string p, int r);
  void Resolve(IntPtr h, int f);
  void SetPath([MarshalAs(UnmanagedType.LPWStr)] string f);
}
public static class AbLnk {
  public static void Make(string link, string target) {
    var l = (IAbShellLinkW)new AbShellLink();
    l.SetPath(target);
    ((System.Runtime.InteropServices.ComTypes.IPersistFile)l).Save(link, true);
  }
}
'@
[AbLnk]::Make($env:AB_LNK, $env:AB_TARGET)
"""


def make_lnk(link, target):
    """Windows 快捷方式（.lnk）：走 Unicode 的 IShellLinkW（WScript.Shell 在非中文系统上处理不了中文路径）。
    脚本用 -EncodedCommand 传入、路径经环境变量传入：不受引号、编码和脚本执行策略影响。"""
    import base64
    env = {**os.environ, "AB_LNK": str(link), "AB_TARGET": str(target)}
    enc = base64.b64encode(LNK_PS.encode("utf-16-le")).decode("ascii")
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW：不闪黑窗口
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                       env=env, capture_output=True, creationflags=flags)
    if r.returncode != 0 or not Path(link).is_file():
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OSError((err[0] if err else "") or "PowerShell 没有建出快捷方式")


def ws_save_meta(meta):
    tmp = WS / (WS_FILE + ".partial")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(WS / WS_FILE)


def py_cmd():
    """写进 AGENTS.md 的 Python 命令：用安装时实际在用的解释器，macOS、Windows 都能直接照抄。"""
    exe = sys.executable or ("python" if os.name == "nt" else "python3")
    return f'"{exe}"' if " " in exe else exe


# ---------------------------------------------------------------- 管线状态
ACTION_LABEL = {"CONTINUE": "进行中", "FORWARD_REQUEST": "已推进", "ROLLBACK_REWORK": "返工",
                "DEPENDENCY_RECHECK": "依赖复核"}
FAMILY_LABEL = {"a": "A 段", "b": "接 B", "library": "B 段入库"}


def pipeline_roots():
    roots, seen = [], set()
    for p in [WS / "管线"] + [Path(x).expanduser() for x in ws_meta().get("pipelines", [])]:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            roots.append(p)
    return roots


def _show_path(p):
    try:
        return "工作台/" + Path(p).relative_to(WS).as_posix()
    except ValueError:
        try:
            return "~/" + Path(p).relative_to(Path.home()).as_posix()
        except ValueError:
            return str(p)


def pipeline_status():
    """读买量管线工作区的本地检查点（workflow/state_checkpoint.json）。这是管线最近一次同步的结果，不是实时读飞书。"""
    out = []
    for root in pipeline_roots():
        wf = root / "workflow"
        entry = {"root": str(root), "name": _show_path(root), "ok": False, "items": []}
        if not (wf / "node_skills.json").is_file():
            entry["reason"] = "还没初始化买量管线工作区" if root == WS / "管线" else "不是买量管线工作区"
            out.append(entry)
            continue
        try:
            nodes = json.loads((wf / "node_skills.json").read_text(encoding="utf-8"))["nodes"]
            cp_path = wf / "state_checkpoint.json"
            cp = json.loads(cp_path.read_text(encoding="utf-8")) if cp_path.is_file() else {}
            sb_path = wf / "state_bindings.json"
            binds = json.loads(sb_path.read_text(encoding="utf-8")).get("bindings", []) if sb_path.is_file() else []
        except (OSError, ValueError, KeyError) as e:
            entry["reason"] = f"读不了管线状态：{type(e).__name__}"
            out.append(entry)
            continue
        fam = {}
        for v in nodes.values():
            fam.setdefault(v.get("family"), []).append(v)
        for v in fam.values():
            v.sort(key=lambda n: n.get("order", 0))
        bound = {b["id"]: b for b in binds}
        cp_items = cp.get("items") or {}
        for iid in dict.fromkeys(list(bound) + list(cp_items)):
            it, b = cp_items.get(iid) or {}, bound.get(iid) or {}
            family = it.get("family") or b.get("family")
            seq = fam.get(family, [])
            nid = it.get("current_node_id")
            idx = next((i for i, n in enumerate(seq) if n["id"] == nid), None)
            entry["items"].append({
                "id": iid, "project": b.get("project_id") or iid.split("-")[0], "family": family,
                "family_label": FAMILY_LABEL.get(family, family or "—"),
                "node_id": nid, "node": it.get("current_node") or (nodes.get(nid) or {}).get("label"),
                "action": it.get("action"), "action_label": ACTION_LABEL.get(it.get("action"), it.get("action") or "未同步"),
                "required_output": it.get("required_output") or "",
                "index": idx + 1 if idx is not None else None, "total": len(seq),
                "done": bool(seq) and idx == len(seq) - 1})
        entry["labels"] = {k: v.get("label") for k, v in nodes.items()}
        entry["orders"] = {k: v.get("order", 0) for k, v in nodes.items()}
        entry["synced_at"] = (dt.datetime.fromtimestamp(cp_path.stat().st_mtime).strftime("%m-%d %H:%M")
                              if cp_path.is_file() else None)
        entry["ok"] = True
        out.append(entry)
    return out


def _cn_now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def record_pipeline_changes(status, record=True):
    """看板每次刷新时记下各项目当前节点；和上次不同就写进 日志/管线进度.jsonl。返回今天记到的变化。"""
    log = WS / "日志" / "管线进度.jsonl"
    snap_p = WS / "日志" / "管线快照.json"
    if record:
        try:
            snap = json.loads(snap_p.read_text(encoding="utf-8")) if snap_p.is_file() else {}
        except ValueError:
            snap = {}
        now, cur, events = _cn_now(), {}, []
        for p in status:
            for it in p["items"] if p["ok"] else []:
                if not it["node_id"]:
                    continue
                key = f"{p['name']}|{it['id']}"
                cur[key] = it["node_id"]
                old = snap.get(key)
                if old and old != it["node_id"]:
                    o, n = p["orders"].get(old, 0), p["orders"].get(it["node_id"], 0)
                    events.append({"time": now.strftime("%Y-%m-%d %H:%M"), "pipeline": p["name"], "item": it["id"],
                                   "from": p["labels"].get(old, old), "to": p["labels"].get(it["node_id"], it["node_id"]),
                                   "kind": "推进" if n > o else "返工", "finished": it["done"]})
        (WS / "日志").mkdir(exist_ok=True)
        if events:
            with log.open("a", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        if cur != snap:
            snap_p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    today = _cn_now().strftime("%Y-%m-%d")
    got = []
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("time", "").startswith(today):
                got.append(e)
    return got


# ---------------------------------------------------------------- 工作台
DAY_DIRS = ("01_A段", "02_接片", "03_待上传", "04_已上传")
WS_DIRS = ("程序", "配置", "台账", "B段缓存", "每日", "日志")
# 工作台根目录里允许预先存在的条目（Agent 会先把源码克隆到 程序/源码，再运行 init）
WS_KNOWN = set(WS_DIRS) | {"管线", WS_FILE, "AGENTS.md", "开始使用.md", "AGENTS.新版.md", "开始使用.新版.md", "看板.html"}
DEFAULT_ROOT = Path.home() / "买量工作台"


def skill_abtool():
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills" / "ab-join-name-upload" / "scripts" / "abtool.py"


def ensure_day(date):
    day = WS / "每日" / date
    for d in DAY_DIRS:
        (day / d).mkdir(parents=True, exist_ok=True)
    return day


def ws_meta():
    p = WS / WS_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def desktop_link(target, name="今日待上传"):
    """桌面快捷方式（今日待上传、买量看板）。macOS 用符号链接，Windows 用 .lnk。
    桌面上同名、但不是工作台建的文件或文件夹绝不改动。"""
    if not WS or ws_meta().get("desktop_link") is False:
        return None
    desk = desktop_dir()
    if not desk.is_dir():
        return {"ok": False, "reason": f"没有桌面目录：{desk}"}
    if shortcut_mode() == "lnk":
        link = desk / (Path(name).stem + ".lnk")
        meta = ws_meta()
        made = meta.setdefault("shortcuts", {})
        if link.exists() and str(link) not in made:
            return {"ok": False, "reason": f"桌面上已有同名快捷方式，不是工作台建的，没有改动：{link}"}
        if link.exists() and made.get(str(link)) == str(target):
            return {"ok": True, "path": str(link), "target": str(target)}
        try:
            make_lnk(link, target)
        except OSError as e:
            return {"ok": False, "reason": f"建快捷方式失败：{e}"}
        made[str(link)] = str(target)
        ws_save_meta(meta)
        return {"ok": True, "path": str(link), "target": str(target)}
    link = desk / name
    if link.exists() and not link.is_symlink():
        return {"ok": False, "reason": f"桌面上已有同名的真实文件或文件夹，没有改动：{link}"}
    if link.is_symlink():
        if link.resolve() == Path(target).resolve():
            return {"ok": True, "path": str(link), "target": str(target)}
        link.unlink()
    try:
        link.symlink_to(target, target_is_directory=Path(target).is_dir())
    except OSError as e:
        return {"ok": False, "reason": f"建快捷方式失败：{e}"}
    return {"ok": True, "path": str(link), "target": str(target)}


def render_agents(root, designer):
    ab = skill_abtool()
    who = f"设计师码 {designer}" if designer else "本人（设计师码首次使用时问一次，写进 工作台.json 的 designer）"
    return f"""# 买量工作台 · 给 Agent 的规则

<!-- 由 abtool workspace init 生成。没改过时，以后升级会自动更新；改过就保留你的版本，新版另存为 AGENTS.新版.md。 -->

这是 {who} 的买量工作台，根目录 `{root}`。这台电脑上的买量工作都在这里进行，不要把产物写到别处。

接B工具：`{py_cmd()} "{ab}"`（下面简写 `abtool`），输出 JSON；`ok:false` 时把 `error` 原话告诉用户，不要猜着补。macOS 和 Windows 都用这一条；在 Windows 的 PowerShell 里前面加 `& `。

## 目录

| 目录 | 放什么 | 怎么写 |
|---|---|---|
| `程序/源码/` | 公开仓库克隆 | 只 `git pull --ff-only`，不改、不提交 |
| `程序/skills/`、`程序/tools/` | 买量管线隔离安装的 Skill 和工具 | 只由安装器写 |
| `管线/` | 买量管线工作区（A 段制作节点） | 按 `管线/AGENTS.md` 和节点合同 |
| `配置/` | 团队配置：代号表、字段表、选B台地址 | 只用 `abtool import-config`／`set-library` 写；不外传、不提交、不发到群里 |
| `台账/上传台账.csv` | 每个序号出过什么、素材 ID | 只由 `abtool` 写，不要手改 |
| `B段缓存/` | 选B台下载的 B 段（已校验 SHA256） | 可以整个删，下次会重下 |
| `每日/YYMMDD/` | 当天的全部产物，见下表 | 由 `abtool run`／`record` 写 |
| `日志/` | 需要留底的命令输出 | 可选 |

每天的目录（日期是北京时间 YYMMDD，序号也按天重置）：

| 子目录 | 节点 | 内容 |
|---|---|---|
| `01_A段/` | B01 | 用户把今天的 A 段 MP4 放这里 |
| `02_接片/` | B02 | 接好的中间成片，`run` 重跑时复用 |
| `03_待上传/` | B04 | 正式命名的成片＋每条 `上传清单.md`＋`本次待上传_*.md` 总表 |
| `04_已上传/` | B04 | 用户回填素材 ID 后，`record` 自动移过来 |
| `作废/` | — | 序号被改用后退下来的旧版本，不要上传 |

桌面上的「今日待上传」是指向当天 `03_待上传/` 的快捷方式；「买量看板」打开根目录的 `看板.html`：今天进行到哪一步、今日完成、每条素材的状态、还没回填素材 ID 的条目、各买量管线项目当前节点（来自管线本地检查点 `workflow/state_checkpoint.json`，不是实时读取项目表）。另有管线工作区要显示时：`abtool workspace init --pipeline <工作区路径>`。`run`、`record`、`workspace today` 后会自动刷新；用户说“刷新看板”或“现在进行到哪了”时运行 `abtool workspace board`，并把输出里的 `next` 告诉用户。

## 每次开工

1. `abtool workspace today`：建好今天的目录，更新桌面快捷方式。
2. `abtool workspace status`：看有没有已出清单、还没回填素材 ID 的条目，有就先提醒用户。
3. 按 B01 → B02 → B04 做，规则以 ab-join-name-upload Skill 的 SKILL.md 为准：
   - **B01 选B**：问 A 段（默认找 `01_A段/` 里最新的 MP4）、A 段标题、主推角色、今天第一个可用序号（用户在后台搜「YYMMDD+设计师码」看最大序号＋1）、需求人（没有就是原创，后台需求人填本人）。
   - **B02 接片**、**B04 命名出清单**：一条 `abtool run …` 做完，不加 `--out-dir`，产物自动进今天的目录。
   - 用户说出素材 ID：`abtool record --name <素材名称> --record-id <ID>`。

## 边界

- 不登录后台、不读取或保存密码、Cookie、验证码，不替用户上传、提审或投放。上传由本人在自己的后台账号完成。
- 不删除 `每日/`、`台账/`、`配置/` 里的任何东西；需要清理时只建议，由用户决定。
- 团队配置只来自负责人发的「团队配置*.zip」（通常在「下载」文件夹），不要从别处拼凑名单或选B台地址。
- 买量管线是源码版：不能说“生成、导出、上传都已经能用”。

## 更新（用户说“更新交付包”时）

1. `git -C 程序/源码 pull --ff-only`；失败就停下报告，不要强制。
2. `{py_cmd()} 程序/源码/ab-join-name-upload/install.py`（升级技能；本机团队配置保留，不会被示例覆盖）。
3. 「下载」里有比当前更新的团队配置 zip 时：`abtool import-config --from <zip>`（旧配置会自动备份）。
4. `abtool workspace init --root {root}`：补齐目录、更新本文件（改过的不覆盖）。
5. `abtool doctor`，逐项报告结果。
"""


def render_start(root, designer):
    return f"""# 买量工作台 · 开始使用

<!-- 由 abtool workspace init 生成 -->

这个文件夹是你的买量工作台：`{root}`

**每天怎么用**

1. 把做好的 A 段 MP4 放进 `每日/今天日期/01_A段/`（不放也行，直接告诉 Codex 路径）。
2. 在后台搜「今天日期＋你的设计师码」{f"（如 {dt.datetime.now().strftime('%y%m%d')}{designer}）" if designer else ""}，看今天最大序号，＋1。
3. 在这个文件夹里打开 Codex，说一句：
   `用 ab-join-name-upload 帮我接B出清单：A 段标题「…」，主推角色…，今天从序号 N 开始，需求人原创。`
4. 打开桌面上的 **今日待上传**：看一遍成片，照每条的 `上传清单.md` 在后台上传（先填名称和字段，最后选文件）。
5. 把素材 ID 告诉 Codex，它会记进台账，并把这条移到 `04_已上传/`。

**想知道进行到哪了**：双击桌面上的 **买量看板**（就是工作台里的 `看板.html`）。它显示今天在哪一步、下一步做什么、今日完成了什么、每条素材是待上传还是已上传、还有哪些没回填素材 ID，以及买量管线各项目走到了哪个节点。

**不要动的**：`台账/`、`配置/`、`程序/`。账号、密码、验证码只在你自己的浏览器里输入，不要发给 Codex。
"""


def write_generated(name, content, meta, report):
    """生成文件：不存在就写；存在且没被改过就更新；被改过就保留，新版另存。"""
    p = WS / name
    new_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    gen = meta.setdefault("generated", {})
    data = content.encode("utf-8")  # 按字节写：Windows 文本模式会把换行改成 CRLF，哈希就对不上了
    if not p.exists():
        p.write_bytes(data)
        report.append({"file": name, "action": "created"})
    else:
        cur = sha256(p)
        if cur == new_sha:
            report.append({"file": name, "action": "unchanged"})
        elif cur == gen.get(name):
            p.write_bytes(data)
            report.append({"file": name, "action": "updated"})
        else:
            alt = WS / name.replace(".md", ".新版.md")
            alt.write_bytes(data)
            report.append({"file": name, "action": "kept_user_edits", "new_version": str(alt)})
            return
    gen[name] = new_sha


def legacy_leftovers():
    found = []
    for n in CONFIG_FILES + ("上传台账.csv",):
        if (STATE / n).is_file():
            found.append(str(STATE / n))
    for d in (STATE / "b-cache", desktop_dir() / "待上传"):
        if d.is_dir() and any(d.iterdir()):
            found.append(str(d))
    return found


def merge_pipelines(old, new):
    out = list(old or [])
    for p in new or []:
        root = Path(os.path.abspath(Path(p).expanduser()))
        if not (root / "workflow" / "node_skills.json").is_file():
            raise ToolError(f"{root} 不是买量管线工作区（没有 workflow/node_skills.json）")
        if str(root) not in out:
            out.append(str(root))
    return out


def cmd_ws_init(args):
    global WS, HOME
    root = Path(os.path.abspath(Path(args.root or WS or DEFAULT_ROOT).expanduser()))  # 不给位置时沿用已有工作台
    ptr = STATE / "workspace.json"
    if WS and Path(WS) != root and not args.force:
        raise ToolError(f"这台电脑已有工作台：{WS}。要换位置请加 --force（旧工作台不会被删除或移动）")
    if root.exists() and not root.is_dir():
        raise ToolError(f"{root} 是文件，不能作为工作台")
    if root.is_dir() and not (root / WS_FILE).is_file():
        extra = [x.name for x in root.iterdir() if x.name not in WS_KNOWN and not x.name.startswith(".")]
        if extra:
            raise ToolError(f"{root} 里已有其他东西（{'、'.join(sorted(extra)[:5])}），不在这里建工作台；换一个空目录或新目录")
    for d in WS_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    WS, HOME = root, root / "配置"
    meta = ws_meta()
    created = not meta
    designer = (args.designer or meta.get("designer") or "").strip() or None
    if designer and not re.fullmatch(r"[A-Za-z]+", designer):
        raise ToolError("设计师码只能是字母，如 D、LW")
    meta.update({
        "kind": "买量工作台", "root": str(root), "abtool": VERSION,
        "created": meta.get("created") or dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "designer": designer.upper() if designer else None,
        "desktop_link": meta.get("desktop_link", True) if args.desktop_link is None else args.desktop_link,
        "pipelines": merge_pipelines(meta.get("pipelines", []), getattr(args, "pipeline", None)),
        "paths": {"源码": "程序/源码", "skills": "程序/skills", "tools": "程序/tools", "管线": "管线",
                  "配置": "配置", "台账": "台账/上传台账.csv", "B段缓存": "B段缓存", "每日": "每日", "日志": "日志"},
    })
    files = []
    write_generated("AGENTS.md", render_agents(root, meta["designer"]), meta, files)
    write_generated("开始使用.md", render_start(root, meta["designer"]), meta, files)
    tmp = root / (WS_FILE + ".partial")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(root / WS_FILE)
    STATE.mkdir(parents=True, exist_ok=True)
    ptr.write_text(json.dumps({"root": str(root)}, ensure_ascii=False) + "\n", encoding="utf-8")
    today = ensure_day(resolve_date("today")[0])
    leftovers = legacy_leftovers()
    return {"ok": True, "workspace": str(root), "created": created, "designer": meta["designer"],
            "files": files, "today": str(today), "desktop_link": desktop_link(today / DAY_DIRS[2]),
            "config_dir": str(HOME), "config_files": {n: (HOME / n).is_file() for n in CONFIG_FILES},
            "legacy_found": leftovers, "board": write_board(),
            "next": (["有旧版数据：运行 workspace migrate 搬进工作台"] if leftovers else []) +
                    ([] if all((HOME / n).is_file() for n in CONFIG_FILES) else ["还没有团队配置：import-config --from <团队配置 zip>"])}


def need_ws():
    if not WS:
        raise ToolError("还没有工作台：先运行 workspace init（默认建在 ~/买量工作台）")


def cmd_ws_today(_args):
    need_ws()
    day = ensure_day(resolve_date("today")[0])
    return {"ok": True, "today": str(day), "dirs": {d: str(day / d) for d in DAY_DIRS},
            "desktop_link": desktop_link(day / DAY_DIRS[2]), "board": write_board()}


def cmd_ws_status(_args):
    need_ws()
    rows = ledger_rows()
    pending = [r["素材名称"] for r in rows if r.get("状态") == "已出清单" and not r.get("素材ID")]
    day = WS / "每日" / resolve_date("today")[0]
    count = lambda d: len([f for f in d.glob("*.mp4")]) if d.is_dir() else 0
    return {"ok": True, "workspace": str(WS), "version": VERSION, "designer": ws_meta().get("designer"),
            "config_files": {n: (HOME / n).is_file() for n in CONFIG_FILES},
            "ledger": str(ledger_path()), "ledger_rows": len(rows),
            "pending_upload": pending,
            "today": {"dir": str(day), **{d: count(day / d) for d in DAY_DIRS[1:]}},
            "pipeline_workspace": (WS / "管线").is_dir(), "source_clone": (WS / "程序" / "源码" / ".git").exists(),
            "legacy_found": legacy_leftovers()}


def same_file(a, b):
    return a.stat().st_size == b.stat().st_size and sha256(a) == sha256(b)


def safe_move(src, dest, report, dry):
    """搬文件：同盘直接改名；跨盘先复制、核对 SHA256 一致后才删原件。目标已存在且不同就跳过。"""
    if dest.exists():
        if same_file(src, dest):
            if not dry:
                src.unlink()
            report.append({"from": str(src), "to": str(dest), "action": "duplicate_removed"})
        else:
            report.append({"from": str(src), "to": str(dest), "action": "conflict_skipped"})
            return False
        return True
    report.append({"from": str(src), "to": str(dest), "action": "moved"})
    if dry:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.stat().st_dev == dest.parent.stat().st_dev:
        src.replace(dest)
    else:
        tmp = dest.with_name(dest.name + ".partial")
        shutil.copy2(src, tmp)
        if not same_file(src, tmp):
            tmp.unlink()
            raise ToolError(f"复制后 SHA256 不一致，已停止，原件未动：{src}")
        tmp.replace(dest)
        src.unlink()
    return True


SHEET_SUFFIX = re.compile(r"(\.上传清单\.(?:md|json)|\.check\.json|\.mp4)$")


def cmd_ws_migrate(args):
    """把旧版数据（~/.ab-join-name-upload 和 桌面/待上传）搬进工作台。默认执行；--dry-run 只列出动作。"""
    need_ws()
    dry, ts = args.dry_run, dt.datetime.now().strftime("%Y%m%d%H%M%S")
    report = {"config": [], "ledger": {}, "files": [], "cache": [], "left_alone": []}
    if Path(STATE) == Path(HOME):
        raise ToolError("配置目录和旧版目录相同，无需迁移")
    # 1. 配置
    for n in CONFIG_FILES:
        src, dest = STATE / n, HOME / n
        if not src.is_file():
            continue
        if not dest.exists():
            act = "copied"
            if not dry:
                shutil.copy2(src, dest)
        elif dest.read_bytes() == src.read_bytes():
            act = "same"
        else:
            act = "workspace_kept_old_saved"
            if not dry:
                bk = HOME / f"迁移前旧配置-{ts}"
                bk.mkdir(exist_ok=True)
                shutil.copy2(src, bk / n)
        if not dry:
            src.replace(STATE / f"{n}.migrated-{ts}")
        report["config"].append({"file": n, "action": act})
    # 2. 台账：先读，文件搬完再写（上传文件路径要改成新位置）
    old_ledger = STATE / "上传台账.csv"
    old_rows = []
    if old_ledger.is_file():
        import csv
        with old_ledger.open(encoding="utf-8-sig", newline="") as f:
            old_rows = list(csv.DictReader(f))
    ids = {r["素材名称"]: r.get("素材ID") for r in old_rows + ledger_rows() if r.get("素材ID")}
    # 3. 桌面/待上传
    moved = {}
    src_root = desktop_dir() / "待上传"
    if src_root.is_dir():
        for f in sorted(src_root.rglob("*")):
            if not f.is_file() or f.name == ".DS_Store":
                continue
            stem = SHEET_SUFFIX.sub("", f.name)
            m = FORMAL.match(stem)
            if m:
                date = m.group(1)
            elif f.name.startswith("本次待上传_"):
                date = dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%y%m%d")
            else:
                date = None
            if date is None:
                dest = WS / "每日" / "未归类" / f.relative_to(src_root)
            elif "作废" in f.relative_to(src_root).parts[:-1]:
                dest = WS / "每日" / date / "作废" / f.name
            else:
                dest = WS / "每日" / date / (DAY_DIRS[3] if ids.get(stem) else DAY_DIRS[2]) / f.name
            if safe_move(f, dest, report["files"], dry):
                moved[str(f)] = str(dest)
        if not dry:
            for d in sorted((x for x in src_root.rglob("*") if x.is_dir()), reverse=True) + [src_root]:
                ds = d / ".DS_Store"
                if ds.is_file() and len(list(d.iterdir())) == 1:
                    ds.unlink()
                try:
                    d.rmdir()
                except OSError:
                    pass
    # 4. 台账合并：工作台已有的行优先，旧行补上素材 ID；上传文件改成新路径
    if old_rows:
        rows = ledger_rows()
        by = {r["素材名称"]: r for r in rows}
        added = filled = 0
        for r in old_rows:
            if r.get("上传文件") in moved:
                r["上传文件"] = moved[r["上传文件"]]
            cur = by.get(r["素材名称"])
            if cur is None:
                rows.append(r); by[r["素材名称"]] = r; added += 1
            elif r.get("素材ID") and not cur.get("素材ID"):
                cur.update({"素材ID": r["素材ID"], "状态": r.get("状态") or "已上传"}); filled += 1
        if not dry:
            ledger_write(rows)
            old_ledger.replace(STATE / f"上传台账.csv.migrated-{ts}")
        report["ledger"] = {"rows_added": added, "material_ids_filled": filled}
    if not dry:  # 工作台台账里指向已搬走文件的路径也更新
        rows = ledger_rows()
        if any(r.get("上传文件") in moved for r in rows):
            for r in rows:
                r["上传文件"] = moved.get(r.get("上传文件"), r.get("上传文件"))
            ledger_write(rows)
    # 5. B 段缓存
    cache = STATE / "b-cache"
    if cache.is_dir():
        for f in sorted(cache.rglob("*")):
            if f.is_file() and f.name != ".DS_Store":
                safe_move(f, WS / "B段缓存" / f.relative_to(cache), report["cache"], dry)
    if (STATE / "work").is_dir():
        report["left_alone"].append({"path": str(STATE / "work"), "why": "旧版接片中间文件，可以删除；工具不自动删"})
    conflicts = [x for x in report["files"] + report["cache"] if x["action"] == "conflict_skipped"]
    board = write_board() if not dry else None
    return {"ok": not conflicts, "dry_run": dry, "workspace": str(WS), **report, "board": board,
            "conflicts": conflicts, "legacy_remaining": legacy_leftovers() if not dry else None}



# ---------------------------------------------------------------- 看板
def _esc(v):
    import html
    return html.escape("" if v is None else str(v))


def _rel(path):
    """看板里的链接用相对工作台根目录的路径，双击 看板.html 就能打开。"""
    try:
        return urllib.parse.quote(Path(path).relative_to(WS).as_posix())  # Windows 也用 /，链接才能点开
    except ValueError:
        return "file://" + urllib.parse.quote(str(path))


def _sheet_info(row):
    f = Path(row.get("上传文件") or "")
    js = f.with_name(row["素材名称"] + ".上传清单.json") if row.get("上传文件") else None
    info = {"b": "", "role": "", "md": None}
    if js and js.is_file():
        try:
            d = json.loads(js.read_text(encoding="utf-8"))
            n = d.get("naming", {})
            src = (n.get("b_source_name") or "").split("（")[0]
            info["b"] = f'{n["b_title"]}（{src}）' if n.get("b_title") and src else (n.get("b_title") or src)
            info["role"] = d.get("form", {}).get("角色标签") or ""
        except ValueError:
            pass
        md = js.with_name(row["素材名称"] + ".上传清单.md")
        info["md"] = md if md.is_file() else None
    return info


def board_state(today=None, record=True):
    """看板数据：今天进行到哪一步、每条素材的状态、各天汇总、待回填。只读本机文件，不联网。"""
    today = today or resolve_date("today")[0]
    rows = ledger_rows()
    day = WS / "每日" / today
    a_files = sorted(p.name for p in (day / DAY_DIRS[0]).glob("*.mp4")) if (day / DAY_DIRS[0]).is_dir() else []
    joined = len(list((day / DAY_DIRS[1]).glob("*.mp4"))) if (day / DAY_DIRS[1]).is_dir() else 0
    mine = [r for r in rows if r.get("日期") == today]
    def kind(r):
        if (r.get("状态") or "").startswith("作废"):
            return "void"
        return "done" if r.get("素材ID") else "todo"
    todo = [r for r in mine if kind(r) == "todo"]
    done = [r for r in mine if kind(r) == "done"]
    void = [r for r in mine if kind(r) == "void"]
    # step＝当前卡片序号：0 B01 选B，1 B02 接片，2 看片上传／回填，4＝今天全部完成
    if todo:
        step, nxt = 2, f"看片并上传 {len(todo)} 条，上传后把素材 ID 告诉 Codex"
    elif done:
        step, nxt = 4, f"今天已上传 {len(done)} 条。还有新的 A 段就放进 01_A段，再找 Codex 接B"
    elif joined:
        step, nxt = 1, "接片已开始，等 Codex 出上传清单"
    elif a_files:
        step, nxt = 0, f"01_A段 里有 {len(a_files)} 个 A 段：对 Codex 说 A 段标题、主推角色和今天第一个序号"
    else:
        step, nxt = 0, "把今天的 A 段放进 01_A段，或直接告诉 Codex A 段在哪"
    older = [r for r in rows if kind(r) == "todo" and r.get("日期") != today]
    days = {}
    for r in rows:
        d = days.setdefault(r.get("日期") or "?", {"todo": 0, "done": 0, "void": 0})
        d[kind(r)] += 1
    pipes = pipeline_status()
    changes = record_pipeline_changes(pipes, record)
    lib = {}
    try:
        lib = json.loads((HOME / "library.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    base = lib.get("base_url") or ""
    return {"today": today, "step": step, "next": nxt, "a_files": a_files, "joined": joined,
            "todo": todo, "done": done, "void": void, "older_todo": older,
            "days": sorted(days.items(), reverse=True)[:7], "pipelines": pipes, "pipeline_today": changes,
            "health": {"配置": all((HOME / n).is_file() for n in CONFIG_FILES),
                       "选B台地址": bool(base) and base.isascii() and "选B台地址" not in base,
                       "FFmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))},
            "designer": ws_meta().get("designer"), "version": VERSION}


BOARD_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1f2329;--mute:#646a73;--line:#e3e5e8;--acc:#3370ff;--ok:#2ea121;--warn:#de7802;--bad:#d83931}
@media (prefers-color-scheme:dark){:root{--bg:#17181a;--card:#222326;--ink:#e8e9eb;--mute:#9a9ea6;--line:#34363a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,"PingFang SC",sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 20px 48px}
header{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:28px 0 10px}.mute{color:var(--mute);font-size:12px}
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:16px}
.step{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.step b{display:block;font-size:13px}.step span{font-size:12px;color:var(--mute)}
.step.done{border-color:var(--ok)}.step.done b::before{content:"✓ ";color:var(--ok)}
.step.now{border-color:var(--acc);box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 25%,transparent)}.step.now b{color:var(--acc)}
.next{margin-top:12px;background:var(--card);border-left:4px solid var(--acc);border-radius:8px;padding:12px 14px;font-size:15px}
.cols{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media (max-width:760px){.cols,.steps{grid-template-columns:1fr}}
.col{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;min-height:80px}
.col h3{margin:0 0 8px;font-size:13px;display:flex;justify-content:space-between}
.item{border-top:1px solid var(--line);padding:8px 0;font-size:13px;word-break:break-all}
.item:first-of-type{border-top:0}.item a{color:var(--acc);text-decoration:none}.item .meta{color:var(--mute);font-size:12px}
.pill{display:inline-block;border-radius:99px;padding:0 8px;font-size:12px;background:var(--line)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}
th,td{text-align:left;padding:8px 12px;border-top:1px solid var(--line)}th{color:var(--mute);font-weight:500;border-top:0}
.bar{display:inline-block;vertical-align:middle;width:90px;height:6px;border-radius:3px;background:var(--line);margin-right:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--acc)}td.prog{white-space:nowrap}
ul.done{margin:0;padding:12px 16px 12px 32px;background:var(--card);border:1px solid var(--line);border-radius:10px}ul.done li{margin:4px 0}
.scroll{overflow-x:auto;border-radius:10px}.scroll table{min-width:560px}
.alert{background:color-mix(in srgb,var(--warn) 12%,var(--card));border:1px solid var(--warn);border-radius:10px;padding:10px 14px}
"""


def render_board(st):
    e = _esc
    names = [("B01 选B", "放 A 段，说标题、角色和序号"), ("B02 接片", "Codex 选 B、接片、出清单"),
             ("B04 看片上传", "本人看片，在后台上传，回填素材 ID"), ("今天完成", "出过的清单都已回填")]
    steps = "".join(
        f'<div class="step {"done" if i < st["step"] else "now" if i == st["step"] else ""}"><b>{e(n)}</b><span>{e(d)}</span></div>'
        for i, (n, d) in enumerate(names))

    def item(r, show_id=False):
        info = _sheet_info(r)
        f = r.get("上传文件")
        title = f'<a href="{_rel(f)}">{e(r["素材名称"])}</a>' if f and Path(f).is_file() else e(r["素材名称"])
        meta = []
        if info["b"]:
            meta.append("B：" + e(info["b"]))
        meta.append("第二设计师：" + e(r.get("第二设计师") or "原创"))
        if info["role"]:
            meta.append("角色：" + e(info["role"]))
        links = f' · <a href="{_rel(info["md"])}">上传清单</a>' if info["md"] else ""
        sid = f' <span class="pill ok">素材 ID {e(r["素材ID"])}</span>' if show_id and r.get("素材ID") else ""
        return f'<div class="item">{title}{sid}<div class="meta">{" · ".join(meta)}{links}</div></div>'

    def col(title, rows, cls, show_id=False, empty="—"):
        body = "".join(item(r, show_id) for r in rows) or f'<div class="mute">{empty}</div>'
        return f'<div class="col"><h3><span class="{cls}">{e(title)}</span><span class="pill">{len(rows)}</span></h3>{body}</div>'

    day = WS / "每日" / st["today"]
    a_list = "、".join(f'<a href="{_rel(day / DAY_DIRS[0] / n)}">{e(n)}</a>' for n in st["a_files"]) or "还没有"
    older = ""
    if st["older_todo"]:
        older = ('<h2 class="warn">之前出了清单、还没回填素材 ID</h2><div class="alert">' +
                 "".join(item(r) for r in st["older_todo"][:20]) +
                 '<div class="mute">已经上传了就把素材 ID 告诉 Codex；不打算上传的可以不管。</div></div>')
    days = "".join(f'<tr><td>{e(d)}</td><td>{c["todo"]}</td><td class="ok">{c["done"]}</td><td class="mute">{c["void"]}</td>'
                   f'<td><a href="{_rel(WS / "每日" / d)}">打开</a></td></tr>' for d, c in st["days"]) \
        or '<tr><td colspan="5" class="mute">还没有记录</td></tr>'
    # 今日完成：接B侧（出清单、上传）＋管线侧（看板记到的节点变化）
    done_today = []
    for r in st["done"]:
        done_today.append(f'<li><span class="pill ok">已上传</span> {e(r["素材名称"])} <span class="mute">素材 ID {e(r.get("素材ID"))}</span></li>')
    if st["todo"]:
        done_today.append(f'<li><span class="pill">已出清单</span> {len(st["todo"])} 条，等待上传</li>')
    for c in st["pipeline_today"]:
        tag = "ok" if c["kind"] == "推进" else "warn"
        fin = "（已完成）" if c.get("finished") else ""
        done_today.append(f'<li><span class="pill {tag}">管线{e(c["kind"])}</span> {e(c["item"])}：{e(c["from"])} → {e(c["to"])}{fin}'
                          f' <span class="mute">{e(c["time"][-5:])} · {e(c["pipeline"])}</span></li>')
    done_html = "<ul class='done'>" + "".join(done_today) + "</ul>" if done_today else \
        '<p class="mute">今天还没有完成的任务。</p>'

    def pipe_block(p):
        if not p["ok"]:
            return f'<p class="mute">{e(p["name"])}：{e(p.get("reason"))}</p>'
        if not p["items"]:
            return f'<p class="mute">{e(p["name"])}：还没有登记项目（新项目从 A01 开始，绑定项目表后会出现在这里）</p>'
        rows = []
        # 已同步的在前（返工、进行中优先看），已完成和未同步的放后面
        for it in sorted(p["items"], key=lambda x: (x["index"] is None, x["done"], x["project"], x["id"])):
            pct = round(100 * it["index"] / it["total"]) if it["index"] and it["total"] else 0
            cls = {"返工": "bad", "依赖复核": "warn", "已推进": "ok"}.get(it["action_label"], "")
            bar = (f'<div class="bar"><i style="width:{pct}%"></i></div><span class="mute">{it["index"]}/{it["total"]}</span>'
                   if it["index"] else '<span class="mute">未同步</span>')
            need = it["required_output"]
            short = need[:46] + ("…" if len(need) > 46 else "")
            rows.append(f'<tr><td><b>{e(it["id"])}</b><div class="mute">{e(it["family_label"])}</div></td>'
                        f'<td>{e(it["node"] or "—")}</td><td class="prog">{bar}</td>'
                        f'<td class="{cls}">{"✓ 已完成" if it["done"] else e(it["action_label"])}</td>'
                        f'<td class="mute" title="{e(need)}">{e(short)}</td></tr>')
        return (f'<p class="mute">{e(p["name"])} · 状态同步于 {e(p.get("synced_at") or "—")}（管线最近一次同步项目表的结果，不是实时读取）</p>'
                '<div class="scroll"><table><tr><th>项目</th><th>当前节点</th><th>进度</th><th>状态</th><th>这一步要交付</th></tr>' + "".join(rows) + "</table></div>")
    pipes_html = "".join(pipe_block(p) for p in st["pipelines"])
    health = " · ".join(f'{e(k)} <b class="{"ok" if v else "bad"}">{"正常" if v else "缺"}</b>' for k, v in st["health"].items())
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    who = f"设计师 {e(st['designer'])} · " if st["designer"] else ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>买量看板 · {e(st['today'])}</title>
<style>{BOARD_CSS}</style></head><body><main>
<header><h1>买量看板 · {e(st['today'])}</h1><span class="mute">{who}更新于 {now} · 对 Codex 说“刷新看板”可立即更新</span></header>
<h2>今天进行到哪</h2><div class="steps">{steps}</div>
<div class="next"><b>下一步：</b>{e(st['next'])}</div>
<h2>今日完成</h2>{done_html}
<p class="mute">今天的 A 段：{a_list} · 已接好 {st['joined']} 条 · <a href="{_rel(day / DAY_DIRS[2])}">打开今日待上传</a></p>
<h2>今天的素材</h2><div class="cols">
{col("待上传（已出清单）", st["todo"], "warn", empty="还没有")}{col("已上传", st["done"], "ok", True, empty="还没有")}{col("作废（不要上传）", st["void"], "mute", empty="没有")}
</div>{older}
<h2>最近 7 天</h2><table><tr><th>日期</th><th>待上传</th><th>已上传</th><th>作废</th><th></th></tr>{days}</table>
<h2>管线状态</h2>{pipes_html}
<h2>环境</h2><p>{health} · 接B技能 {e(st['version'])}</p>
</main></body></html>
"""


def write_board():
    """生成 工作台/看板.html。只在有工作台时生成；任何错误都不影响主命令。"""
    if not WS:
        return None
    try:
        p = WS / "看板.html"
        tmp = p.with_name(p.name + ".partial")
        tmp.write_text(render_board(board_state()), encoding="utf-8")
        tmp.replace(p)
        link = desktop_link(p, "买量看板.html")
        return {"ok": True, "path": str(p), "desktop_link": link}
    except Exception as e:  # 看板只是展示，绝不让接片、回填失败
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def cmd_ws_board(_args):
    need_ws()
    r = write_board()
    st = board_state()
    return {**r, "today": st["today"], "next": st["next"], "todo": len(st["todo"]), "done": len(st["done"]),
            "older_todo": len(st["older_todo"])}



def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Windows 控制台默认不是 UTF-8，中文 JSON 会报错
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="abtool", description="接B·命名·上传准备（本地，不上传）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="检查 Python、FFmpeg 和配置")
    s = sub.add_parser("probe", help="读取媒体规格"); s.add_argument("file")
    s = sub.add_parser("lib-list", help="列出选B台里的 B 段（可按关键词或角色筛）")
    s.add_argument("--q", help="标题／库ID／来源编号关键词"); s.add_argument("--role", help="主推角色")
    s.add_argument("--library", help="选B台配置，默认 工作台/配置/library.json")
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
        s.add_argument("--library", help="选B台配置，默认 工作台/配置/library.json")
        s.add_argument("--b-title", help="不填则取 B 段名称的标题段")
        s.add_argument("--demand", default="原创", help="需求人代号；没有就是 原创")
        s.add_argument("--intern", help="实习生代号；没有不填")
        s.add_argument("--role-token", help="名称里必须出现的主推角色词，如 鼬")
        s.add_argument("--codes", help="代号表路径，默认 工作台/配置/codes.json")

    s = sub.add_parser("name", help="按公司规则生成正式名称"); naming_args(s)
    s = sub.add_parser("package", help="核查成片、按正式名复制、生成上传清单"); naming_args(s)
    s.add_argument("--file", required=True); s.add_argument("--out-dir", required=True)
    s.add_argument("--fields", help="上传字段表，默认 工作台/配置/fields.json")
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
    s.add_argument("--out-dir", help="默认 工作台/每日/今天/03_待上传（没有工作台时为 桌面/待上传）")
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
    s = sub.add_parser("workspace", help="工作台：init 建立／补齐，today 今天目录，status 状态，migrate 搬入旧数据")
    wsub = s.add_subparsers(dest="ws_cmd", required=True)
    w = wsub.add_parser("init", help="建立或补齐工作台（默认 ~/买量工作台），可重复运行")
    w.add_argument("--root", help="工作台位置，默认 ~/买量工作台")
    w.add_argument("--designer", help="本人设计师码，如 D")
    w.add_argument("--no-desktop-link", dest="desktop_link", action="store_false", default=None,
                   help="不在桌面放「今日待上传」快捷方式")
    w.add_argument("--force", action="store_true", help="这台电脑已有别处的工作台时，改指向新位置（旧的不删）")
    w.add_argument("--pipeline", action="append", help="另外要在看板上显示状态的买量管线工作区（可多次）；工作台/管线 默认就有")
    wsub.add_parser("today", help="建好今天的目录并更新桌面快捷方式")
    wsub.add_parser("status", help="工作台状态：配置、台账、今天的产物、待回填素材ID")
    w = wsub.add_parser("migrate", help="把旧版 ~/.ab-join-name-upload 和 桌面/待上传 搬进工作台")
    w.add_argument("--dry-run", action="store_true", help="只列出要做的动作，不搬")
    wsub.add_parser("config-dir", help="打印当前生效的配置目录（给 install.sh 用）")
    wsub.add_parser("board", help="刷新 工作台/看板.html：今天进行到哪、每条素材状态、待回填")
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
        if a.cmd == "workspace":
            if a.ws_cmd == "config-dir":
                print(HOME); return
            r = {"init": cmd_ws_init, "today": cmd_ws_today, "status": cmd_ws_status,
                 "migrate": cmd_ws_migrate, "board": cmd_ws_board}[a.ws_cmd](a)
            out(r, 0 if r["ok"] else 1)
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
