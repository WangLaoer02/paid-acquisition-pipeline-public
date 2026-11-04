#!/usr/bin/env python3
"""素材入库专项候选实现；真实接口与枚举核验前禁止生产提交。"""
import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import fcntl
import hashlib
import http.client
import http.cookiejar
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import shutil
import sqlite3
import ssl
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit
import uuid
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parent))
import workflow_runtime as runtime

TZ = ZoneInfo('Asia/Shanghai')
SCHEMA = 'upload-candidate-1'
FIELDS = ['date', 'project', 'story', 'delivery', 'version', 'class', 'tags']
NAME = re.compile(r'^(\d{6})__([^_]+)__([^_]+)__(A|D[1-9]\d*)__(V\d{3})__([^_]+)__([^_]+)\.(mp4|mov|m4v)$', re.I)

def sha_files(paths):
    h=hashlib.sha256()
    for raw in sorted({str(Path(x).expanduser().resolve()) for x in paths}):
        q=Path(raw);h.update(q.name.encode()+b'\0');h.update(q.read_bytes())
    return h.hexdigest()



class UploadError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def fail(code, message):
    raise UploadError(code, message)


def read_json(path):
    return json.loads(Path(path).read_text())


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def today():
    return dt.datetime.now(TZ).date()


def atomic_json(path, data, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x') as f:
            os.chmod(temp, 0o600 if private else 0o644)
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def parse_name(name, current=None):
    if Path(name).name != name:
        fail('NAME_INVALID', '上传名必须是文件名，不含路径。')
    m = NAME.fullmatch(name)
    if not m:
        fail('NAME_INVALID', '候选语法：YYMMDD__项目别名__剧情名__A或D序号__V三位版本__一类别名__标签别名+标签别名.mp4')
    date, project, story, delivery, version, cls, tags, ext = m.groups()
    try:
        business_date = dt.date(2000 + int(date[:2]), int(date[2:4]), int(date[4:6]))
    except ValueError:
        fail('DATE_INVALID', '命名日期不是有效制作日期。')
    values = dict(zip(FIELDS, [date, project, story, delivery.upper(), version.upper(), cls, tags]))
    if any(re.search(r'[\x00-\x1f/\\]', v) for v in values.values()):
        fail('NAME_INVALID', '命名字段含控制字符或路径分隔符。')
    tag_list = [] if tags == '-' else tags.split('+')
    if any(not t for t in tag_list) or len(tag_list) != len(set(tag_list)):
        fail('NAME_INVALID', '标签为空或重复。')
    values.update(tags=tag_list, production_date=business_date.isoformat(), extension=ext.lower())
    current = current or today()
    warnings = []
    if business_date != current:
        warnings.append({'code': 'DATE_MISMATCH', 'production_date': business_date.isoformat(), 'today': current.isoformat(),
                         'message': '制作日期与运行日不同；历史／补传保留真实日期，若误写请给正确制作日期。'})
    return values, warnings


def render_name(values):
    tags = '+'.join(values['tags']) or '-'
    name = '__'.join([values['date'], values['project'], values['story'], values['delivery'], values['version'], values['class'], tags])
    return name + '.' + values.get('extension', 'mp4')


def media(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        fail('INPUT_UNAVAILABLE', '本地文件／附件尚不可访问：' + str(path))
    if path.suffix.lower() not in ('.mp4', '.mov', '.m4v'):
        fail('FORMAT_UNSUPPORTED', '仅接受MP4／MOV／M4V；不自动转码。')
    before = path.stat()
    p = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, text=True, timeout=60)
    if p.returncode:
        fail('MEDIA_INVALID', 'ffprobe无法读取实际媒体。')
    info = json.loads(p.stdout)
    videos = [s for s in info['streams'] if s['codec_type'] == 'video']
    if not videos:
        fail('MEDIA_INVALID', '文件没有视频轨。')
    duration = float(info['format'].get('duration', 0))
    if duration <= 0:
        fail('MEDIA_INVALID', '无法确认有效视频时长。')
    p = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], capture_output=True, timeout=max(120, int(duration * 6)))
    if p.returncode:
        fail('DECODE_FAILED', '完整音视频解码未通过；请核对实际文件。')
    digest = sha(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        fail('INPUT_CHANGED', '检查期间文件发生变化。')
    v = videos[0]
    return {'path': str(path), 'sha256': digest, 'bytes': after.st_size, 'duration': duration,
            'width': v['width'], 'height': v['height'], 'fps': v.get('avg_frame_rate'),
            'video_codec': v['codec_name'], 'audio_codecs': [s['codec_name'] for s in info['streams'] if s['codec_type'] == 'audio'], 'full_decode': True}


def frames(path, output, checked_media=None, extra_times=None):
    """代表帧＋候选切镜；画面语义需实际看图，不将scene分数当动作识别。"""
    result = dict(checked_media) if checked_media else media(path)
    output = Path(output)
    if output.exists():
        fail('OUTPUT_EXISTS', '帧证据目录已存在；选新目录以保留历史。')
    output.mkdir(parents=True)
    duration = result['duration']
    p = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', result['path'], '-vf', "scale=320:-2,select='gt(scene,0.30)',showinfo", '-an', '-f', 'null', '-'], capture_output=True, text=True, timeout=max(120, int(duration * 6)))
    if p.returncode:
        fail('FRAME_FAILED', '切镜候选提取失败。')
    cuts = [float(s) for s in re.findall(r'pts_time:([0-9.]+)', p.stderr)]
    times = [0, duration * .2, duration * .4, duration * .6, duration * .8, max(0, duration - .1)]
    extra_times = extra_times or []
    if any(not 0 <= t < duration for t in extra_times):
        fail('FRAME_TIME_INVALID', '关键动作候选时间必须处于真实视频范围内。')
    times += extra_times
    # 上限仅用于粗览；保留全部切镜时间，不宣称动作或全剧情已核对。
    times += cuts if len(cuts) <= 18 else [cuts[int(i * (len(cuts)-1) / 17)] for i in range(18)]
    times = sorted(set(round(t, 3) for t in times if t < duration))
    files = []
    for i, t in enumerate(times):
        dest = output / f'frame-{i:03d}.jpg'
        p = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(t), '-i', result['path'], '-frames:v', '1', '-vf', 'scale=480:-2', str(dest)], capture_output=True, timeout=60)
        if p.returncode or not dest.exists():
            fail('FRAME_FAILED', '指定时间代表帧提取失败。')
        files.append({'seconds': t, 'path': str(dest.resolve()), 'sha256': sha(dest)})
    from PIL import Image, ImageDraw
    images = [Image.open(f['path']).convert('RGB') for f in files]
    cell_w = 480
    cell_h = max(im.height for im in images) + 30
    sheet = Image.new('RGB', (cell_w * 4, cell_h * ((len(images)+3)//4)), '#202020')
    draw = ImageDraw.Draw(sheet)
    for i, im in enumerate(images):
        x, y = (i % 4) * cell_w, (i // 4) * cell_h
        sheet.paste(im, (x, y))
        draw.text((x+5, y+cell_h-24), f'{files[i]["seconds"]:.3f}s', fill='white')
        im.close()
    sheet.save(output/'contact.jpg')
    if sha(result['path']) != result['sha256']:
        fail('INPUT_CHANGED', '抽帧期间原视频改变；帧证据不可用于当前文件。')
    result.update(frames=files, scene_candidates=cuts, scene_threshold=.30,
                  explicit_keyframe_candidates=extra_times,
                  semantic_status='待实际看图；代表帧与切镜不证明关键动作完整',
                  cannot_infer=['后台项目ID', '账号／用户ID', '制作日期', '人员', '一类ID', '类标签ID'])
    atomic_json(output/'frames.json', result)
    return result


def resolve_enum(mapping, group, alias):
    rows = mapping.get('enums', {}).get(group, {})
    row = rows.get(alias)
    if not row or row.get('active') is not True or row.get('id') is None or not row.get('name'):
        fail('MAPPING_UNKNOWN', f'{group}别名未核验、失效或缺真实ID：{alias}')
    ids = [str(r.get('id')) for r in rows.values() if r.get('active')]
    if len(ids) != len(set(ids)):
        fail('MAPPING_CONFLICT', f'{group}多个别名绑定同一ID，须明确唯一规范别名。')
    return {'id': str(row['id']), 'name': row['name'], 'alias': alias}


def mapped(values, mapping, user_id):
    keys = mapping.get('field_keys', {})
    required = ['name', 'production_date', 'project_id', 'user_id', 'class_id', 'tag_ids', 'sha256', 'story', 'delivery', 'version']
    if any(not isinstance(keys.get(k), str) or not keys[k] for k in required):
        fail('FIELD_UNVERIFIED', '上传字段key尚未完整核验；不能沿用数据导出字段。')
    if len(set(keys.values())) != len(keys):
        fail('MAPPING_CONFLICT', '多个命名字段映射到同一后台key。')
    project = resolve_enum(mapping, 'projects', values['project'])
    cls = resolve_enum(mapping, 'classes', values['class'])
    tags = [resolve_enum(mapping, 'tags', t) for t in values['tags']]
    for row in [cls, *tags]:
        source = mapping['enums']['classes' if row is cls else 'tags'][row['alias']]
        if 'project_ids' in source and project['id'] not in [str(v) for v in source['project_ids']]:
            fail('MAPPING_CONFLICT', '类别／标签不属于该项目。')
    semantics = {'name': render_name(values), 'production_date': values['production_date'], 'project_id': project['id'],
                 'user_id': str(user_id), 'class_id': cls['id'], 'tag_ids': [r['id'] for r in tags],
                 'story': values['story'], 'delivery': values['delivery'], 'version': values['version']}
    return semantics, {'project': project, 'class': cls, 'tags': tags}


def expand_items(request):
    items = []
    for item in request.get('items', []):
        if ('path' in item) == ('attachment' in item):
            fail('INPUT_INVALID', '每项必须且只能提供path或attachment。')
        if 'attachment' in item:
            a = item['attachment']
            if not a.get('local_path') or not a.get('provenance'):
                fail('ATTACHMENT_UNAVAILABLE', '附件须有会话实际可访问路径及来源记录，不能编造落盘。')
            items.append(dict(item, source_path=a['local_path'], original_name=a.get('original_name') or Path(a['local_path']).name, input_type='attachment'))
        else:
            path = Path(item['path']).expanduser()
            if path.is_dir():
                paths = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in ('.mp4', '.mov', '.m4v'))
                if not paths:
                    fail('INPUT_UNAVAILABLE', '目录没有支持的视频。')
                if item.get('upload_name'):
                    fail('INPUT_INVALID', '目录输入不能共用一个upload_name。')
                items.extend(dict(item, source_path=str(p), original_name=p.name, input_type='path') for p in paths)
            else:
                items.append(dict(item, source_path=str(path), original_name=path.name, input_type='path'))
    if not items:
        fail('INPUT_UNAVAILABLE', '请求没有实际文件或可访问附件。')
    return items


def preview(request, mapping, frame_root=None):
    started = time.monotonic()
    user_id = str(request.get('user_id') or '')
    if not user_id:
        fail('IDENTITY_MISSING', '请指定目标真实用户ID。')
    plan = {'schema': SCHEMA, 'mapping_version': mapping['version'], 'mapping_sha256': hashlib.sha256(canonical(mapping).encode()).hexdigest(),
            'user_id': user_id, 'created_at': dt.datetime.now(TZ).isoformat(), 'items': [], 'ready': False}
    names, digests = {}, {}
    for item in expand_items(request):
        row = {k: item[k] for k in ('source_path', 'original_name', 'input_type')}
        row.update(status='BLOCKED', warnings=[])
        if 'attachment' in item:
            row['attachment_provenance'] = item['attachment']['provenance']
        candidate = item.get('upload_name') or row['original_name']
        row['upload_name'] = candidate
        try:
            row['media'] = media(item['source_path'])
            if frame_root:
                dest = Path(frame_root)/row['media']['sha256']
                if dest.exists():
                    evidence = read_json(dest/'frames.json')
                    if evidence['sha256'] != row['media']['sha256'] or any(sha(f['path']) != f['sha256'] for f in evidence['frames']):
                        fail('FRAME_CHANGED', '已有帧证据与原视频不一致。')
                else:
                    evidence = frames(item['source_path'], dest, row['media'])
                row['frame_evidence'] = str((dest/'frames.json').resolve())
            values, warnings = parse_name(candidate)
            row.update(name_fields=values, warnings=warnings)
            if candidate != render_name(values):
                fail('NAME_NONCANONICAL', '版本、交付编号和扩展名大小写须按规范；给出建议，不改源文件。')
            semantic, labels = mapped(values, mapping, user_id)
            semantic['sha256'] = row['media']['sha256']
            row.update(semantic=semantic, labels=labels, payload={mapping['field_keys'][k]: v for k, v in semantic.items()})
            if candidate in names or semantic['sha256'] in digests:
                fail('DUPLICATE_INPUT', '同批重名或同字节视频；只保留明确的一条请求。')
            names[candidate] = semantic['sha256']
            digests[semantic['sha256']] = candidate
            if row['original_name'] != candidate:
                row['rename_notice'] = {'original': row['original_name'], 'suggested': candidate, 'source_file_renamed': False, 'affected_parameters': list(semantic)}
            if warnings and not item.get('date_reason'):
                fail('DATE_REVIEW_REQUIRED', '请在date_reason说明历史／补传或纠正真实制作日期，不能自动改为今天。')
            row['date_reason'] = item.get('date_reason')
            row['status'] = 'READY'
        except UploadError as exc:
            row['error'] = {'code': exc.code, 'reason': str(exc), 'original_name': row['original_name'],
                            'suggested_name': (render_name(row['name_fields']) if exc.code=='NAME_NONCANONICAL' else render_name(item['suggest_fields']) if item.get('suggest_fields') else None),
                            'affected_parameters': FIELDS if exc.code in ('NAME_INVALID', 'DATE_INVALID') else []}
        plan['items'].append(row)
    plan['ready'] = all(i['status'] == 'READY' for i in plan['items'])
    plan['elapsed_seconds'] = round(time.monotonic()-started, 3)
    return plan


def at(data, path):
    for key in path.split('.'):
        if not isinstance(data, dict) or key not in data:
            fail('RESPONSE_INVALID', '响应字段缺失：' + path)
        data = data[key]
    return data


class Api:
    """受核验合同驱动的HTTP适配器；没有任何猜测的生产路由。"""
    def __init__(self, contract, secret):
        self.c = contract
        self.secret = secret
        u = urlsplit(contract.get('base_url') or '')
        if u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
            fail('CONTRACT_INVALID', 'base_url只能是无凭据的固定origin。')
        if u.scheme != 'https' and not (contract.get('test_only') is True and u.scheme == 'http' and u.hostname in ('127.0.0.1', 'localhost', '::1')):
            fail('TLS_REQUIRED', '生产只允许HTTPS；不降级、不关闭证书校验。')
        if not u.hostname or not contract.get('verified') or not contract.get('evidence'):
            fail('CONTRACT_UNVERIFIED', '必须先核对真实上传／回读接口合同与证据。')
        self.url = u
        self.jar = http.cookiejar.CookieJar()
        for raw in secret.get('cookies', []):
            domain = raw.get('domain')
            if not domain or not (u.hostname == domain.lstrip('.') or u.hostname.endswith('.' + domain.lstrip('.'))):
                fail('SESSION_INVALID', 'Cookie域与后台不匹配。')
            self.jar.set_cookie(http.cookiejar.Cookie(0, raw['name'], raw['value'], None, False, domain, domain.startswith('.'), domain.startswith('.'), raw.get('path', '/'), True, raw.get('secure', True), raw.get('expires'), False, None, None, {}, False))

    def request(self, endpoint, params=None, file=None):
        attempts = 1 if endpoint == 'upload' else int(self.c.get('read_attempts', 2))
        for attempt in range(max(1, min(attempts, 3))):
            try:
                return self._request(endpoint, params, file)
            except UploadError as exc:
                if endpoint == 'upload' or exc.code not in ('NETWORK_UNKNOWN', 'RATE_LIMITED') or attempt + 1 >= attempts:
                    raise
                time.sleep(min(2, .25 * (2 ** attempt)))

    def _request(self, endpoint, params=None, file=None):
        import urllib.request
        spec = self.c['endpoints'][endpoint]
        path = spec['path']
        if not path.startswith('/') or path.startswith('//') or urlsplit(path).scheme or urlsplit(path).fragment:
            fail('CONTRACT_INVALID', '接口只允许固定origin下的相对路径。')
        method = spec['method']
        if endpoint != 'upload' and method != 'GET':
            fail('CONTRACT_INVALID', '身份、字典和结果核对必须是只读GET。')
        if endpoint == 'upload' and method != 'POST':
            fail('CONTRACT_INVALID', '入库合同必须是明确的POST。')
        headers = dict(self.secret.get('headers', {}))
        if any(k.lower() in ('host', 'content-length', 'content-type', 'cookie') or '\n' in str(v) or '\r' in str(v) for k, v in headers.items()):
            fail('SESSION_INVALID', '私有认证header格式无效。Cookie请使用带域和路径的cookie列表。')
        if file is None:
            if params:
                path += ('&' if '?' in path else '?') + urlencode(params)
            body = None
        else:
            boundary = 'upload-' + uuid.uuid4().hex
            fields = b''
            for key, value in params.items():
                if re.search(r'[\r\n"\\]', key):
                    fail('CONTRACT_INVALID', '字段key不能进入multipart边界。')
                fields += (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n' + (canonical(value) if isinstance(value, (list, dict)) else str(value)) + '\r\n').encode()
            name = file['upload_name']
            field = self.c['file_field']
            if re.search(r'[\r\n"\\]', name + field):
                fail('NAME_INVALID', '上传名不能进入multipart边界。')
            # UTF-8文件名编码必须由真实后台合同确认；测试服务也检查此编码。
            head = fields + f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\nContent-Type: {mimetypes.guess_type(name)[0] or "application/octet-stream"}\r\n\r\n'.encode()
            tail = f'\r\n--{boundary}--\r\n'.encode()
            headers.update({'Content-Type': 'multipart/form-data; boundary=' + boundary, 'Content-Length': str(len(head)+Path(file['source_path']).stat().st_size+len(tail))})
            body = (head, tail)
        req = urllib.request.Request(self.c['base_url'].rstrip('/')+path)
        self.jar.add_cookie_header(req)
        if req.has_header('Cookie'):
            headers['Cookie'] = req.get_header('Cookie')
        timeout = self.c.get('timeout_seconds', 20)
        conn = http.client.HTTPSConnection(self.url.hostname, self.url.port, timeout=timeout, context=ssl.create_default_context()) if self.url.scheme == 'https' else http.client.HTTPConnection(self.url.hostname, self.url.port, timeout=timeout)
        try:
            conn.putrequest(method, path)
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders()
            if body:
                conn.send(body[0])
                with Path(file['source_path']).open('rb') as f:
                    for block in iter(lambda: f.read(1024*1024), b''):
                        conn.send(block)
                conn.send(body[1])
            r = conn.getresponse()
            if r.status == 401 or 300 <= r.status < 400:
                fail('LOGIN_EXPIRED', '登录过期或跳转；不跟随到其他origin。')
            if r.status == 403:
                fail('PERMISSION_DENIED', '当前账号没有此接口权限。')
            if r.status == 429:
                fail('RATE_LIMITED', '当前账号受限流；不自动重放上传。')
            if r.status < 200 or r.status >= 300:
                fail('HTTP_ERROR', f'后台HTTP {r.status}；上传受理状态需先回查。')
            raw = r.read(4*1024*1024+1)
            if len(raw) > 4*1024*1024:
                fail('RESPONSE_INVALID', '响应超过限制。')
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                fail('RESPONSE_INVALID', '响应不是JSON；不将登录页面或HTTP200记作成功。')
            check = spec.get('ok')
            if not check or at(data, check['path']) != check['value']:
                fail('BUSINESS_REJECTED', '后台业务响应未满足已核验合同。')
            return data
        except (socket.timeout, TimeoutError, OSError, http.client.HTTPException):
            fail('NETWORK_UNKNOWN', '请求中断／超时；先核对真实结果，不重传。')
        finally:
            conn.close()

    def identity(self, expected):
        actual = str(at(self.request('identity'), self.c['identity_user_path']))
        if actual != str(expected):
            fail('IDENTITY_MISMATCH', '登录身份与目标用户ID不一致。')
        return actual

    def dictionary(self, mapping):
        data = at(self.request('dictionary'), self.c['dictionary_path'])
        # 合同须将真实响应映射成固定分组，绝不把文字列当ID。
        if data != mapping['enums']:
            fail('DICTIONARY_CHANGED', '后台实时项目／一类／类标签字典与版本映射不同，需核对更新。')

    def lookup(self, key):
        data = self.request('lookup', {self.c['lookup_key']: key})
        rows = at(data, self.c['lookup_items_path'])
        if not isinstance(rows, list):
            fail('RESPONSE_INVALID', '回读必须为明确的结果列表。')
        return rows


def verify_record(record, row, contract):
    paths = contract['record_paths']
    for key, expected in row['semantic'].items():
        actual = at(record, paths[key])
        if key == 'tag_ids':
            if not isinstance(actual, list) or sorted(map(str, actual)) != sorted(map(str, expected)):
                fail('READBACK_MISMATCH', '后台标签与映射不一致。')
        elif str(actual) != str(expected):
            fail('READBACK_MISMATCH', '后台字段与映射不一致：' + key)
    material_id = str(at(record, contract['record_id_path']) or '')
    if not material_id:
        fail('READBACK_MISMATCH', '没有真实素材ID。')
    link = at(record, contract['record_link_path']) if contract.get('record_link_path') else None
    if link and (urlsplit(link).scheme != 'https' and not contract.get('test_only')):
        fail('READBACK_MISMATCH', '后台素材链接不符合已核验协议。')
    return {'material_id': material_id, 'link': link}


def name_from_record(record, mapping, contract):
    """真实ID反查规范别名，再核对后台名；不允许从展示文本猜ID。"""
    paths = contract['record_paths']
    def alias(group, value):
        matches = [a for a, row in mapping['enums'][group].items() if row.get('active') is True and str(row.get('id')) == str(value)]
        if len(matches) != 1:
            fail('MAPPING_UNKNOWN', '后台ID无法唯一反查规范别名：' + group)
        return matches[0]
    date = dt.date.fromisoformat(at(record, paths['production_date']))
    if date.year < 2000 or date.year > 2099:
        fail('DATE_INVALID', 'YYMMDD候选规范仅适用2000—2099年。')
    values = {'date': date.strftime('%y%m%d'), 'project': alias('projects', at(record, paths['project_id'])),
              'story': at(record, paths['story']), 'delivery': at(record, paths['delivery']), 'version': at(record, paths['version']),
              'class': alias('classes', at(record, paths['class_id'])), 'tags': [alias('tags', v) for v in at(record, paths['tag_ids'])],
              'extension': Path(at(record, paths['name'])).suffix.lstrip('.').lower()}
    name = render_name(values)
    parse_name(name)
    if name != at(record, paths['name']):
        fail('READBACK_MISMATCH', '后台名称无法按当前枚举反向还原；核对实际标签顺序或命名。')
    return {'name': name, 'name_fields': values}


def account_dir(root, contract, user_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', str(user_id)):
        fail('IDENTITY_INVALID', '用户ID不适合独立账户目录。')
    backend = hashlib.sha256((contract.get('base_url') or '').encode()).hexdigest()[:24]
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    path = root/backend/str(user_id)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for p in (path.parent, path):
        os.chmod(p, 0o700)
    return path


def private_read(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid():
        fail('PRIVATE_FILE_REQUIRED', '凭据须为当前用户所有的0600私有文件，且不能是符号链接。')
    return read_json(path)


def import_session(root, contract, user_id, source):
    secret = private_read(source)
    Api(contract, secret).identity(user_id)
    path = account_dir(root, contract, user_id)/'session.json'
    secret.update(verified_user_id=str(user_id), base_url=contract['base_url'], verified_at=dt.datetime.now(TZ).isoformat())
    atomic_json(path, secret, private=True)
    return {'user_id': str(user_id), 'identity_verified': True, 'private_session_file': str(path), 'test_only': bool(contract.get('test_only'))}


def load_api(path, contract, user_id):
    if not (path/'session.json').exists():
        fail('LOGIN_NOT_IMPORTED', '该后台／用户没有经身份回读的私有登录态。')
    secret = private_read(path/'session.json')
    if secret.get('verified_user_id') != str(user_id) or secret.get('base_url') != contract['base_url']:
        fail('IDENTITY_MISMATCH', '私有登录态身份或后台发生变化。')
    return Api(contract, secret)


@contextlib.contextmanager
def ledger(path):
    lock = path/'queue.lock'
    with lock.open('a') as f:
        os.chmod(lock, 0o600)
        # 同账号跨进程互斥；不同账号完全独立。
        fcntl.flock(f, fcntl.LOCK_EX)
        db = sqlite3.connect(path/'receipts.sqlite3')
        os.chmod(path/'receipts.sqlite3', 0o600)
        db.execute('CREATE TABLE IF NOT EXISTS receipts (request_key TEXT PRIMARY KEY, status TEXT, receipt TEXT)')
        db.commit()
        try:
            yield db
        finally:
            db.close()
            fcntl.flock(f, fcntl.LOCK_UN)


def save_receipt(db, key, status, receipt):
    db.execute('INSERT OR REPLACE INTO receipts VALUES (?,?,?)', (key, status, canonical(receipt)))
    db.commit()


def upload(plan, mapping, contract, root, reconcile_only=False):
    started = time.monotonic()
    if plan.get('schema') != SCHEMA or plan.get('mapping_sha256') != hashlib.sha256(canonical(mapping).encode()).hexdigest():
        fail('PLAN_STALE', '预览与映射版本不一致，重新预览。')
    if mapping.get('status') != 'verified' or not mapping.get('evidence'):
        fail('MAPPING_UNVERIFIED', '生产枚举映射未经核验。')
    user_id = str(plan['user_id'])
    path = account_dir(root, contract, user_id)
    output = {'schema': SCHEMA, 'user_id': user_id, 'mapping_version': mapping['version'],
              'test_only': bool(contract.get('test_only')), 'items': []}
    with ledger(path) as db:
        api = load_api(path, contract, user_id)
        api.identity(user_id)
        api.dictionary(mapping)
        for row in plan['items']:
            receipt = {k: row.get(k) for k in ('original_name', 'upload_name', 'labels', 'warnings', 'rename_notice', 'date_reason', 'error')}
            receipt.update(status='FAILED', material_id=None, link=None)
            if row['status'] != 'READY':
                output['items'].append(receipt)
                continue
            key = None
            try:
                # 每次提交前重建双向映射，不能相信编辑后的预览JSON。
                values, warnings = parse_name(row['upload_name'])
                semantic, labels = mapped(values, mapping, user_id)
                semantic['sha256'] = row['media']['sha256']
                if render_name(values) != row['upload_name'] or semantic != row['semantic'] or labels != row['labels']:
                    fail('PLAN_STALE', '预览命名或目标被修改，请重建预览。')
                if warnings and not row.get('date_reason'):
                    fail('DATE_REVIEW_REQUIRED', '运行日变化，请核对真实制作日期并说明补传。')
                if sha(row['source_path']) != semantic['sha256']:
                    fail('INPUT_CHANGED', '预览后原文件字节改变。')
                receipt['warnings'] = warnings
                key = hashlib.sha256(canonical({'backend': contract['base_url'], 'user': user_id, 'semantic': semantic}).encode()).hexdigest()
                receipt['request_key'] = key
                receipt['file_sha256'] = semantic['sha256']
                prev = db.execute('SELECT status, receipt FROM receipts WHERE request_key=?', (key,)).fetchone()
                prior_rows = [json.loads(r[0]) for r in db.execute('SELECT receipt FROM receipts WHERE request_key!=?', (key,))]
                for prior in prior_rows:
                    if prior.get('file_sha256') == semantic['sha256']:
                        fail('DUPLICATE_PRIOR', '同字节素材已有其他名称／参数的受理记录；先回查原request_key，不再上传。')
                    if prior.get('upload_name') == row['upload_name']:
                        fail('NAME_COLLISION', '同一上传名已对应其他视频字节；请核对正式版本。')
                records = api.lookup(key)
                if records:
                    if len(records) != 1:
                        fail('READBACK_AMBIGUOUS', '回读发现多条相同请求；不可自动选择。')
                    receipt.update(verify_record(records[0], row, contract), status='CONFIRMED', reused=True)
                elif prev or reconcile_only:
                    receipt.update(status='PENDING', error={'code': 'ACCEPTANCE_UNKNOWN', 'reason': '无可确认回读结果；保留受理未知，不重传。'})
                else:
                    api.identity(user_id)
                    stage = path/'staging'
                    stage.mkdir(mode=0o700, exist_ok=True)
                    staged = stage/(semantic['sha256']+Path(row['source_path']).suffix.lower())
                    if not staged.exists():
                        temp = stage/(uuid.uuid4().hex+'.tmp')
                        try:
                            shutil.copyfile(row['source_path'], temp)
                            os.chmod(temp, 0o400)
                            if sha(temp) != semantic['sha256']:
                                fail('INPUT_CHANGED', '复制提交快照时视频发生变化。')
                            os.replace(temp, staged)
                        finally:
                            temp.unlink(missing_ok=True)
                    if sha(staged) != semantic['sha256']:
                        fail('INPUT_CHANGED', '私有提交快照字节不一致。')
                    # 在发送前持久保存UNKNOWN，崩溃或超时续接也不会重复写入。
                    save_receipt(db, key, 'PENDING', dict(receipt, status='PENDING'))
                    payload = {mapping['field_keys'][k]: v for k, v in semantic.items()}
                    payload[contract['request_key_field']] = key
                    api.request('upload', payload, dict(row, source_path=str(staged)))
                    records = api.lookup(key)
                    if len(records) == 1:
                        receipt.update(verify_record(records[0], row, contract), status='CONFIRMED', reused=False)
                    else:
                        receipt.update(status='PENDING', error={'code': 'ACCEPTANCE_UNKNOWN', 'reason': '传输返回后未得到唯一可核验素材，需继续回查。'})
                save_receipt(db, key, receipt['status'], receipt)
            except UploadError as exc:
                sent = key and db.execute('SELECT 1 FROM receipts WHERE request_key=?', (key,)).fetchone()
                receipt.update(status='PENDING' if sent else 'FAILED', error={'code': exc.code, 'reason': str(exc)})
                if key and sent:
                    save_receipt(db, key, receipt['status'], receipt)
            output['items'].append(receipt)
            time.sleep(max(0, float(contract.get('min_interval_seconds', .2))))
    output.update(requested=len(output['items']), confirmed=sum(i['status']=='CONFIRMED' for i in output['items']),
                  failed=sum(i['status']=='FAILED' for i in output['items']), pending=sum(i['status']=='PENDING' for i in output['items']),
                  elapsed_seconds=round(time.monotonic()-started, 3))
    return output


def batch(jobs, root, workers):
    """显式多账号队列；一个批次每个后台／用户仅一项，账号内由ledger串行。"""
    identities = set()
    for job in jobs:
        identity = (job['contract']['base_url'], job['plan']['user_id'])
        if identity in identities:
            fail('QUEUE_CONFLICT', '同批次相同后台用户重复；请合并该账号队列。')
        identities.add(identity)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        futures = {pool.submit(upload, j['plan'], j['mapping'], j['contract'], root): j for j in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                results.append(future.result())
            except UploadError as exc:
                results.append({'user_id': job['plan']['user_id'], 'ok': False, 'error': {'code': exc.code, 'reason': str(exc)}})
            except (OSError, ValueError, KeyError, TypeError):
                results.append({'user_id': job['plan']['user_id'], 'ok': False, 'error': {'code': 'LOCAL_ERROR', 'reason': '该账号本地文件或合同结构无效；其他账号结果单独保留。'}})
    return {'accounts': sorted(results, key=lambda x: x['user_id']), 'real_parallel_acceptance': False,
            'note': '真实并行验收须由真实多账号回读证据确认；本字段不按任务返回自动升级。'}


def feedback(result):
    lines = [f'素材入库回执{"（本地测试服务，非真实后台）" if result.get("test_only") else ""}',
             f'请求 {result["requested"]}｜后台回读成功 {result["confirmed"]}｜失败 {result["failed"]}｜待确认 {result["pending"]}',
             f'目标用户ID：{result["user_id"]}｜映射版本：{result["mapping_version"]}']
    for i, row in enumerate(result['items'], 1):
        labels = row.get('labels') or {}
        p, c = labels.get('project', {}), labels.get('class', {})
        tags = '、'.join(f'{t["name"]}（{t["id"]}）' for t in labels.get('tags', [])) or '无／待核'
        lines += [f'{i}. {row["upload_name"]}｜{row["status"]}', f'项目：{p.get("name", "待核")}（{p.get("id", "待核")}）｜一类：{c.get("name", "待核")}（{c.get("id", "待核")}）｜类标签：{tags}',
                  f'素材ID：{row.get("material_id") or "未确认"}｜链接：{row.get("link") or "无可用链接"}']
        if row.get('error'):
            lines.append('原因：' + row['error']['code'] + ' ' + row['error']['reason'])
        if row.get('rename_notice'):
            lines.append('名称调整：' + row['original_name'] + ' → ' + row['upload_name'] + '（源文件保留）')
        for w in row.get('warnings', []):
            lines.append('日期提醒：' + w['production_date'] + '；今日 ' + w['today'] + '；说明 ' + str(row.get('date_reason') or '待核'))
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--private-root', default='~/.config/material-upload')
    sub = p.add_subparsers(dest='command', required=True)
    f = sub.add_parser('inspect'); f.add_argument('--path', required=True); f.add_argument('--output', required=True); f.add_argument('--at', action='append', type=float, default=[])
    f = sub.add_parser('preview'); f.add_argument('--request', required=True); f.add_argument('--mapping', required=True); f.add_argument('--output', required=True); f.add_argument('--frames-dir')
    f = sub.add_parser('session-import'); f.add_argument('--contract', required=True); f.add_argument('--user-id', required=True); f.add_argument('--secret-file', required=True)
    f = sub.add_parser('doctor'); f.add_argument('--contract', required=True); f.add_argument('--mapping', required=True); f.add_argument('--user-id', required=True)
    for command in ('upload', 'reconcile'):
        f = sub.add_parser(command); f.add_argument('--contract', required=True); f.add_argument('--mapping', required=True); f.add_argument('--plan', required=True); f.add_argument('--output', required=True); f.add_argument('--authorization-ticket', required=True)
    f = sub.add_parser('feedback'); f.add_argument('--receipt', required=True)
    f = sub.add_parser('batch'); f.add_argument('--jobs', required=True); f.add_argument('--workers', type=int, default=2); f.add_argument('--output', required=True); f.add_argument('--authorization-ticket', required=True)
    f = sub.add_parser('reverse'); f.add_argument('--record', required=True); f.add_argument('--mapping', required=True); f.add_argument('--contract', required=True)
    args = p.parse_args()
    if args.command == 'inspect':
        result = frames(args.path, args.output, extra_times=args.at)
    elif args.command == 'preview':
        result = preview(read_json(args.request), read_json(args.mapping), args.frames_dir or str(Path(args.output).with_suffix(''))+'-frames'); atomic_json(args.output, result)
    elif args.command == 'session-import':
        result = import_session(args.private_root, read_json(args.contract), args.user_id, args.secret_file)
    elif args.command == 'doctor':
        c, m = read_json(args.contract), read_json(args.mapping)
        api = load_api(account_dir(args.private_root, c, args.user_id), c, args.user_id)
        api.identity(args.user_id); api.dictionary(m)
        result = {'identity_verified': True, 'dictionary_verified': True, 'user_id': args.user_id, 'test_only': bool(c.get('test_only')), 'upload_ready': m.get('status')=='verified'}
    elif args.command in ('upload', 'reconcile'):
        paths=[args.plan,args.mapping,args.contract]; input_sha=sha_files(paths)
        plan=read_json(args.plan); scope='material-upload:legacy-material:'+str(plan.get('user_id') or input_sha[:16])
        with runtime.mutation('material_upload',scope,authorization_ticket=args.authorization_ticket,input_sha256=input_sha):
            result = upload(plan, read_json(args.mapping), read_json(args.contract), args.private_root, args.command == 'reconcile')
            atomic_json(args.output, result)
        print(feedback(result)); return
    elif args.command == 'batch':
        index=read_json(args.jobs); refs=[args.jobs]; jobs=[]
        for j in index['jobs']:
            refs.extend(j[k] for k in ('plan','mapping','contract'))
            jobs.append({k: read_json(j[k]) for k in ('plan', 'mapping', 'contract')})
        input_sha=sha_files(refs); scope='material-upload:legacy-material-batch:'+input_sha[:16]
        with runtime.mutation('material_upload',scope,authorization_ticket=args.authorization_ticket,input_sha256=input_sha):
            result = batch(jobs, args.private_root, args.workers); atomic_json(args.output, result)
    elif args.command == 'reverse':
        result = name_from_record(read_json(args.record), read_json(args.mapping), read_json(args.contract))
    else:
        print(feedback(read_json(args.receipt))); return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except UploadError as exc:
        print(json.dumps({'ok': False, 'code': exc.code, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr); sys.exit(1)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # 不输出原响应、secret值或traceback，避免凭据进入日志。
        print(json.dumps({'ok': False, 'code': 'LOCAL_ERROR', 'error': '本地文件、媒体工具或合同结构无效；核对配置与输入。'}, ensure_ascii=False), file=sys.stderr); sys.exit(1)
