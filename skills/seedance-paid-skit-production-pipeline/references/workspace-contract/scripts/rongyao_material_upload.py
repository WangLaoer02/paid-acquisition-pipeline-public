#!/usr/bin/env python3
"""荣耀素材入库：原生分片协议、私有会话、逐步回读；真实验收单独记录。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import time
import sys
from urllib.parse import urlencode, urlsplit

import requests
from bs4 import BeautifulSoup

from material_upload import (UploadError, atomic_json, canonical, expand_items, fail,
                             frames, ledger, media, private_read, read_json, save_receipt, sha)
from rongyao_upload_preview import SPEC, filename_parameters, protocol_plan
sys.path.insert(0,str(Path(__file__).resolve().parent))
import workflow_runtime as runtime

VERSION = 'rongyao-native-20261010.1'
PRODUCTION_HOSTS = {'demand.backend.example.invalid', 'cdnapk.backend.example.invalid', 'power.houtai.backend.example.invalid'}
ROOT = Path(__file__).resolve().parents[1]

def guarded_input_sha(paths):
    h=hashlib.sha256()
    for raw in sorted({str(Path(x).expanduser().resolve()) for x in paths}):
        q=Path(raw);h.update(q.name.encode()+b'\0');h.update(q.read_bytes())
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate_public(value):
    if isinstance(value, dict):
        for key, v in value.items():
            if key.lower() in {'cookie', 'cookies', 'token', 'authorization', 'password', 'advertiser_id'}:
                fail('SECRET_IN_REQUEST', '认证值只能放在工作区外的0600私有文件。')
            validate_public(v)
    elif isinstance(value, list):
        for v in value:
            validate_public(v)


def build_name(date, creator_sequence, content, tails):
    if not re.fullmatch(r'[A-Z]+[1-9]\d*', creator_sequence or ''):
        fail('CREATOR_REQUIRED', '上传成片须明确制作人代码和序号；不从用户ID或尾码推断。')
    if not isinstance(tails, list) or not tails or any(not isinstance(v, str) or not v.strip() or '-' in v or v != v.strip() for v in [content, *tails]):
        fail('NAME_COMPONENT_INVALID', '内容名和尾标签须是非空独立字段，不含连字符或首尾空格。')
    name = '-'.join([str(date) + creator_sequence, content, *tails]) + '.mp4'
    return filename_parameters(name)['suggested_upload_name']


def prepare(request, spec, output, extract_frames=False):
    """路径及附件共用检查；错误逐条保留，不悄悄改源文件。"""
    validate_public(request)
    output = Path(output).resolve()
    if output.exists():
        fail('OUTPUT_EXISTS', '准备目录已存在，使用新目录保留证据。')
    output.mkdir(parents=True)
    items = expand_items(request)
    plan = {'schema': VERSION, 'spec_sha256': digest(spec), 'user_id': str(request.get('user_id') or ''),
            'user_display_name': request.get('user_display_name'), 'items': [], 'real_upload_success_count': 0}
    names, hashes = set(), set()
    defaults = {k: request.get(k) for k in ('category', 'source_type', 'source_direction', 'roles')}
    for index, item in enumerate(items):
        row = {'input_type': item['input_type'], 'path': str(Path(item['source_path']).expanduser().resolve()),
               'original_name': item['original_name'], 'upload_name': item.get('upload_name') or item['original_name'], 'status': 'FAILED'}
        if item['input_type'] == 'attachment':
            row['attachment_provenance'] = item['attachment']['provenance']
        try:
            checked = media(row['path'])
            row['media'] = checked
            if extract_frames:
                evidence = frames(row['path'], output / f'frames-{index:03d}', checked)
                row['frames_manifest'] = str(output / f'frames-{index:03d}' / 'frames.json')
                row['semantic_review_status'] = evidence['semantic_status']
            if item.get('name_fields'):
                fields = item['name_fields']
                row['suggested_upload_name'] = build_name(fields['date'], fields['creator_sequence'], fields['content'], fields['tails'])
            target = dict(defaults, **{k: item[k] for k in defaults if k in item},
                          user_id=plan['user_id'], user_display_name=plan['user_display_name'], path=row['path'],
                          upload_name=item.get('upload_name') or item['original_name'])
            native = protocol_plan(target, checked, spec)
            name = native['name']['suggested_upload_name']
            if name in names:
                fail('NAME_COLLISION', '本批次重复上传名。')
            if checked['sha256'] in hashes:
                fail('DUPLICATE_INPUT', '本批次存在相同字节视频。')
            names.add(name)
            hashes.add(checked['sha256'])
            row.update(status='READY', media=checked, request=target, native=native,
                       upload_name=name, warnings=native['name']['warnings'],
                       rename_notice=name != row['original_name'])
        except (UploadError, KeyError, TypeError, ValueError) as exc:
            row['error'] = {'code': getattr(exc, 'code', 'INPUT_INVALID'), 'reason': str(exc)}
            if row['error']['code'].startswith(('NAME_', 'DATE_')):
                row['correction'] = {'original_name': row['upload_name'],
                                     'suggested_name': row.get('suggested_upload_name'),
                                     'suggested_format': 'YYMMDD制作人代码序号-内容描述-来源尾标签-其他尾标签.mp4',
                                     'affected_fields': ['join.name', 'join.tag'],
                                     'message': '文件命名不准确；缺少实际语义字段时先看帧再建议，不能凭空生成正式名称。'}
        plan['items'].append(row)
    plan['upload_ready'] = False
    plan['identity_verification'] = '须使用doctor回读私有会话身份；本地准备不表示可提交'
    atomic_json(output / 'plan.json', plan)
    atomic_json(output / 'mapping.json', mapping_manifest(plan))
    return plan


def attach_review(manifest, review):
    """将Codex实际看图结论绑定原片和具体帧，不能把切镜结果当语义识别。"""
    if review.get('source_sha256') != manifest['sha256']:
        fail('REVIEW_STALE', '语义结论与原视频SHA不一致。')
    by_sha = {f['sha256']: f for f in manifest['frames']}
    if review.get('method') != 'codex_visual_review' or not review.get('observations'):
        fail('REVIEW_INVALID', '须记录实际看图的方法和逐项观察。')
    for observation in review['observations']:
        if not observation.get('frame_sha256') or any(s not in by_sha for s in observation['frame_sha256']):
            fail('REVIEW_EVIDENCE_MISSING', '每项语义结论须关联本视频实际帧SHA。')
        for s in observation['frame_sha256']:
            if sha(by_sha[s]['path']) != s:
                fail('REVIEW_STALE', '帧图字节已变化。')
    if sha(manifest['path']) != manifest['sha256']:
        fail('REVIEW_STALE', '实际原片已变化。')
    return dict(review, verified_frame_evidence=True, business_adopted=False,
                cannot_infer=['后台项目ID', '用户ID', '制作日期', '制作人员', '生成平台'])


def mapping_manifest(plan):
    rows = []
    for item in plan['items']:
        if item['status'] != 'READY':
            continue
        target, name = item['native']['target'], item['native']['name']
        rows.append({'upload_name': item['upload_name'], 'file_sha256': item['media']['sha256'],
                     'user_id': plan['user_id'] or None,
                     'native_fields': {'join.name': item['upload_name'], 'join.tag': name['native_filename_tag'],
                                       'join.category_type': target['category_type'],
                                       'saveSourceData.type': {'type': 'type', 'data': target['source_type']},
                                       'saveSourceData.direction': {'type': 'direction', 'data': target['source_direction']},
                                       'saveVideoTag.tag[]': target['roles']},
                     'production_date': name['production_date'], 'creator_code_sequence': name['creator_code_sequence'],
                     'not_encoded_in_filename': ['数字用户ID', '母游戏gid', '上传分类', '一类', '二类', '角色标签']})
    return {'version': VERSION, 'spec_sha256': plan['spec_sha256'], 'rows': rows,
            'note': '按规范上传名＋原片SHA绑定明确元数据；文件名不独立承载后台全部参数。'}


def reverse_record(record, spec):
    parsed = filename_parameters(record['name'] + '.mp4')
    category = record.get('category')
    if category not in spec['categories']:
        fail('CATEGORY_NOT_OBSERVED', '反向回读分类尚未核入字典。')
    if len(record.get('source_type', [])) != 1 or len(record.get('source_direction', [])) > 1:
        fail('CLASS_REVERSE_AMBIGUOUS', '本上传契约采用一类／二类单值，现有多值须明确处理。')
    first = record['source_type'][0]
    direction = (record.get('source_direction') or [None])[0]
    role_values = set(spec['roles'].values())
    if first not in spec['source_type'] or direction and direction not in spec['source_direction_list'].get(first, []):
        fail('CLASS_DIRECTION_CONFLICT', '后台一类／二类未在本契约核到。')
    if any(r not in role_values for r in record['roles']):
        fail('ROLE_NOT_OBSERVED', '反向回读角色尚未核入字典。')
    return {'material_id': record['id'], 'upload_name': parsed['suggested_upload_name'],
            'category': category, 'category_type': spec['categories'][category], 'source_type': first,
            'source_direction': direction, 'roles': record['roles'], 'filename_tag': parsed['native_filename_tag'],
            'user_id': None, 'user_id_inferred': False, 'remote_bytes_sha256_verified': False}


def account_dir(root, user):
    if not re.fullmatch(r'[1-9]\d*', str(user)):
        fail('USER_ID_REQUIRED', '需要明确的数字用户ID，不能用姓名或素材尾码代替。')
    return private_queue_dir(root, str(user))


def private_queue_dir(root, key):
    if not re.fullmatch(r'[1-9]\d*|single-current', key):
        fail('PRIVATE_ROOT_REQUIRED', '只接受数字账号或明确的本次单会话队列。')
    root = Path(root).expanduser().resolve()
    if root == ROOT or ROOT in root.parents:
        fail('PRIVATE_ROOT_REQUIRED', '私有会话和队列须保存在工作区之外。')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    path = root / key
    if path.is_symlink():
        fail('PRIVATE_ROOT_REQUIRED', '账号目录不能为符号链接。')
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def backend_binding(spec):
    return digest({k: spec[k] for k in ('entry', 'readback_url', 'endpoints')})


def reserve_nonce(path, key):
    # CDN分片不携带用户ID；所有账号共用nonce占用表，不能只在账号内去重。
    with ledger(path.parent) as db:
        db.execute('CREATE TABLE IF NOT EXISTS nonces (request_key TEXT PRIMARY KEY, nonce INTEGER UNIQUE)')
        old = db.execute('SELECT nonce FROM nonces WHERE request_key=?', (key,)).fetchone()
        if old:
            return old[0]
        for _ in range(100):
            nonce = secrets.randbelow(1000000) + 1
            try:
                db.execute('INSERT INTO nonces VALUES (?,?)', (key, nonce))
                db.commit()
                return nonce
            except sqlite3.IntegrityError:
                pass
        fail('NONCE_EXHAUSTED', '暂时无法分配跨账号唯一分片编号，未提交。')


class NativeApi:
    def __init__(self, spec, secret):
        self.spec, self.secret = spec, secret
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({'User-Agent': 'RongyaoMaterialUpload/' + VERSION})
        self.test_only = spec.get('test_only') is True
        self.min_interval = max(0, min(2, float(spec.get('min_interval_seconds', 0 if self.test_only else .1))))
        self.last_request = 0
        for origin, cookie in secret.get('cookies_by_origin', {}).items():
            self._allowed(origin)
            if not isinstance(cookie, str) or '\r' in cookie or '\n' in cookie:
                fail('SESSION_INVALID', 'Cookie格式无效。')
        self.checked_identity = False

    def _allowed(self, url):
        p = urlsplit(url)
        if p.username or p.password or p.fragment:
            fail('ORIGIN_INVALID', '认证和接口地址不能含用户信息或片段。')
        if self.test_only:
            if p.scheme != 'http' or p.hostname != '127.0.0.1':
                fail('ORIGIN_INVALID', '模拟服务只接受127.0.0.1。')
        elif p.scheme != 'http' or p.hostname not in PRODUCTION_HOSTS or p.port not in (None, 80):
            fail('ORIGIN_INVALID', '仅允许已观察后台原生HTTP地址；不能更换服务或禁用TLS验证。')
        return f'{p.scheme}://{p.netloc}'

    def request(self, url, method='GET', params=None, file=None, text=False):
        origin = self._allowed(url)
        headers = {'Cookie': self.secret.get('cookies_by_origin', {}).get(origin, '')}
        tries = 3 if method == 'GET' else 1
        for attempt in range(tries):
            try:
                delay = self.min_interval - (time.monotonic() - self.last_request)
                if delay > 0:
                    time.sleep(delay)
                kwargs = {'timeout': (10, 90), 'allow_redirects': False, 'headers': headers}
                if method == 'GET':
                    kwargs['params'] = params
                else:
                    kwargs['data'] = params
                    if file is not None:
                        kwargs['files'] = {'data': ('blob', file, 'application/octet-stream')}
                response = self.session.request(method, url, **kwargs)
                self.last_request = time.monotonic()
                if method == 'GET' and response.status_code in (429, 503) and attempt < tries - 1:
                    time.sleep(.15 * (attempt + 1))
                    continue
                break
            except requests.RequestException:
                if attempt == tries - 1:
                    fail('NETWORK_UNKNOWN' if method != 'GET' else 'NETWORK_READ_FAILED',
                         '请求未取得确定结果；写请求不会自动重试。')
                time.sleep(.15 * (attempt + 1))
        if response.status_code in (301, 302, 303, 307, 308, 401):
            fail('LOGIN_EXPIRED', '后台跳转登录或拒绝认证，需要更新该账号私有会话。')
        if response.status_code == 403:
            fail('PERMISSION_DENIED', '该账号没有此操作权限。')
        if response.status_code == 429:
            fail('RATE_LIMITED', '该账号请求受限；写请求不自动重试，保留受理状态。')
        if response.status_code != 200:
            fail('HTTP_ERROR', '后台返回HTTP ' + str(response.status_code))
        if text:
            response.encoding = response.apparent_encoding or 'utf-8'
            return response.text
        try:
            data = response.json()
        except ValueError:
            fail('RESPONSE_INVALID', '后台未返回预期JSON；响应正文不写日志。')
        if not isinstance(data, dict):
            fail('RESPONSE_INVALID', '后台JSON不是对象。')
        return data

    def identity(self, user, name):
        proof = self.secret.get('identity_proof')
        if not proof or proof.get('observed_evidence') is None:
            fail('IDENTITY_PROOF_MISSING', '尚无实际数字用户ID的只读回读入口；姓名与尾码不算身份核验。')
        data = self.request(proof['url'], text=proof.get('format') == 'html')
        if proof.get('format') == 'html':
            soup = BeautifulSoup(data, 'html.parser')
            uid = soup.select(proof['user_id_selector'])
            labels = soup.select(proof['display_name_selector'])
            if len(uid) != 1 or len(labels) != 1:
                fail('IDENTITY_MISMATCH', '身份回读字段不是唯一节点。')
            actual_user = uid[0].get(proof.get('user_id_attribute')) if proof.get('user_id_attribute') else uid[0].get_text(strip=True)
            actual_name = labels[0].get_text(strip=True)
        elif proof.get('format') == 'json':
            def pick(keys):
                value = data
                for k in keys:
                    value = value[k]
                return value
            try:
                actual_user, actual_name = pick(proof['user_id_path']), pick(proof['display_name_path'])
            except (KeyError, TypeError):
                fail('IDENTITY_MISMATCH', '数字身份回读字段不存在。')
        else:
            fail('IDENTITY_PROOF_MISSING', '身份格式尚未核验。')
        if str(actual_user) != str(user) or actual_name != name:
            fail('IDENTITY_MISMATCH', '登录态实际身份与目标用户不一致。')
        self.checked_identity = True
        return {'user_id': str(actual_user), 'display_name': actual_name, 'verified': True}

    def form(self):
        soup = BeautifulSoup(self.request(self.spec['entry'], text=True), 'html.parser')
        fields = {}
        for key in ('advertiser_id', 'token', 'create_name'):
            matches = soup.select('input[name="' + key + '"]')
            if len(matches) != 1 or not matches[0].get('value'):
                fail('FORM_NOT_READY', '实际上传表单未取得唯一的私有字段：' + key)
            fields[key] = matches[0]['value']
        categories = {o.get_text(strip=True): o.get('value') for o in soup.select('select[name="category_type"] option')}
        return fields, categories

    def lookup(self, name):
        stem = name[:-4]
        url = self.spec['readback_url']
        html = self.request(url, params={'video_name': stem, 'type': 'date'}, text=True)
        record = parse_detail(html)
        if record is None:
            return None
        if record['name'] != stem:
            fail('READBACK_NAME_COLLISION', '后台详情按编号前缀返回了其他素材；尚未取得目标的精确查重结果，不能上传、改标签或认作已有目标。')
        record['link'] = url + ('&' if urlsplit(url).query else '?') + urlencode({'video_name': stem, 'type': 'date'})
        return record


def parse_detail(html):
    soup = BeautifulSoup(html, 'html.parser')
    names = soup.select('.video_title')
    if not names:
        return None
    ids = {x.get('id') for x in soup.select('img[id]') if re.fullmatch(r'[1-9]\d*', x.get('id', ''))}
    # 真实openVideo空结果仍返回完整详情模板，含一个空.video_title。
    # 只有该已观察空模板才视为无记录；后续仍须getVideoName预检。
    labels = {h.get_text(' ', strip=True) for h in soup.select('h6')}
    if len(names) == 1 and not names[0].get_text(strip=True) and not ids and {'分类：', '视频尺寸：/'} <= labels:
        return None
    if len(names) != 1 or len(ids) != 1 or not names[0].get_text(strip=True):
        fail('READBACK_AMBIGUOUS', '素材详情未取得唯一名称和素材ID。')
    record = {'id': next(iter(ids)), 'name': names[0].get_text(strip=True)}
    groups = {'角色/标签': 'roles', '一类': 'source_type', '二类': 'source_direction', '自定义标签': 'owner_tags'}
    for h in soup.select('h6'):
        text = h.get_text(' ', strip=True)
        label, sep, value = text.partition('：')
        if not sep:
            continue
        if label in groups:
            record[groups[label]] = [x['name'] for x in h.select('img[name]')]
        elif label in ('分类', '视频尺寸', '上传时间', '设计师'):
            record[{'分类': 'category', '视频尺寸': 'dimensions', '上传时间': 'uploaded_at', '设计师': 'designer'}[label]] = value.strip()
    for key in groups.values():
        record.setdefault(key, [])
    return record


def verify_record(record, row, require_tags=True):
    target = row['native']['target']
    if record['name'] + '.mp4' != row['upload_name'] or record.get('category') != target['category']:
        fail('READBACK_MISMATCH', '回读名称或上传分类不匹配。')
    checked = row['media']
    if record.get('dimensions') != f'{checked["width"]}/{checked["height"]}':
        fail('READBACK_MISMATCH', '回读视频尺寸不匹配。')
    if require_tags:
        for key, expected in [('source_type', [target['source_type']]),
                              ('source_direction', [target['source_direction']] if target['source_direction'] else []),
                              ('roles', target['roles'])]:
            if sorted(record.get(key, [])) != sorted(expected):
                fail('TAGS_NOT_CONFIRMED', '回读分类／标签与目标不匹配：' + key)
    return dict(record, verification='唯一素材ID、名称、分类、尺寸、分类标签回读；本地原片SHA及分片确认另留',
                remote_bytes_sha256_verified=False)


def load_api(spec, path, user, name):
    secret = private_read(path / 'session.json')
    if (secret.get('bound_user_id') != str(user) or secret.get('bound_display_name') != name
            or secret.get('bound_backend') != backend_binding(spec)):
        fail('IDENTITY_MISMATCH', '账号私有文件绑定不匹配。')
    api = NativeApi(spec, secret)
    api.identity(user, name)
    return api


def import_session(spec, root, source, user, name):
    secret = private_read(source)
    if ROOT == Path(source).resolve() or ROOT in Path(source).resolve().parents:
        fail('PRIVATE_FILE_REQUIRED', '会话源文件须在工作区外。')
    api = NativeApi(spec, secret)
    proof = api.identity(user, name)
    api.form()
    secret.update(bound_user_id=str(user), bound_display_name=name, bound_backend=backend_binding(spec))
    path = account_dir(root, user)
    atomic_json(path / 'session.json', secret, private=True)
    return dict(proof, private_session_file=str(path / 'session.json'), test_only=api.test_only)


def import_har(source, destination):
    """只读私有HAR；不执行复制出的cURL，不把HAR带入项目。"""
    har = private_read(source)
    destination = Path(destination).expanduser().resolve()
    if ROOT == destination or ROOT in destination.parents:
        fail('PRIVATE_FILE_REQUIRED', 'HAR转换结果须位于工作区外。')
    cookies = {}
    for entry in har.get('log', {}).get('entries', []):
        req = entry.get('request', {})
        p = urlsplit(req.get('url', ''))
        if p.scheme != 'http' or p.hostname not in PRODUCTION_HOSTS:
            continue
        values = [x['value'] for x in req.get('headers', []) if x.get('name', '').lower() == 'cookie']
        if not values and req.get('cookies'):
            values = ['; '.join(x['name'] + '=' + x['value'] for x in req['cookies'])]
        if len(values) == 1:
            cookies[f'{p.scheme}://{p.netloc}'] = values[0]
    if not cookies:
        fail('HAR_NO_SESSION', 'HAR没有包含后台请求Cookie；Chrome默认导出可能已脱敏。')
    if destination.exists():
        fail('OUTPUT_EXISTS', '不覆盖既有私有会话。')
    atomic_json(destination, {'cookies_by_origin': cookies, 'identity_proof': None}, private=True)
    return {'private_file': str(destination), 'credential_values_printed': False,
            'identity_verified': False, 'next': '补齐实测数字身份只读证据后session-import'}


def upload(plan, spec, root, reconcile=False, api_override=None):
    if plan.get('schema') != VERSION or plan.get('spec_sha256') != digest(spec):
        fail('PLAN_STALE', '协议或预览版本发生变化，需重新准备。')
    user, name = plan['user_id'], plan['user_display_name']
    if api_override is None:
        path = account_dir(root, user)
    else:
        if (not isinstance(api_override, NativeApi) or not getattr(api_override, 'transient_single_account', False)
                or user is not None or api_override.spec != spec):
            fail('IDENTITY_MISMATCH', '内存认证仅允许明确的单会话模式；不能冒充数字用户ID。')
        path = private_queue_dir(root, 'single-current')
    output = {'schema': VERSION, 'user_id': user, 'user_display_name': name,
              'test_only': spec.get('test_only') is True, 'items': []}
    start = time.monotonic()
    with ledger(path) as db:
        api = api_override or load_api(spec, path, user, name)
        if api_override:
            output['identity'] = api.identity(user, name)
            output['credential_file_saved'] = False
            output['real_numeric_user_id_acceptance'] = False
        for row in plan['items']:
            receipt = {k: row.get(k) for k in ('original_name', 'upload_name', 'rename_notice', 'warnings', 'error', 'correction')}
            receipt.update(status='FAILED', target=row.get('native', {}).get('target'), phases={}, material_id=None)
            if row['status'] != 'READY':
                output['items'].append(receipt)
                continue
            key, registered = None, False
            try:
                validate_public(row['request'])
                if (row['request'].get('user_id') != user or row['request'].get('user_display_name') != name
                        or row['media'] != row['native']['media']):
                    fail('PLAN_STALE', '预览身份或媒体校验信息被编辑。')
                rebuilt = protocol_plan(row['request'], row['media'], spec)
                # 时间提醒允许跨日变化，其余映射和分片不可被编辑。
                for field in ('target', 'chunks', 'spec_content_sha256'):
                    if rebuilt[field] != row['native'][field]:
                        fail('PLAN_STALE', '预览目标／分片被编辑。')
                if rebuilt['name']['suggested_upload_name'] != row['upload_name']:
                    fail('PLAN_STALE', '上传名被编辑。')
                if sha(row['path']) != row['media']['sha256']:
                    fail('INPUT_CHANGED', '预览后源视频已改变。')
                receipt.update(warnings=rebuilt['name']['warnings'], file_sha256=row['media']['sha256'])
                key = digest({'user': user, 'file_sha256': row['media']['sha256'], 'name': row['upload_name'], 'target': rebuilt['target']})
                receipt['request_key'] = key
                prior = db.execute('SELECT receipt FROM receipts WHERE request_key=?', (key,)).fetchone()
                for other in db.execute('SELECT receipt FROM receipts WHERE request_key!=?', (key,)):
                    record = json.loads(other[0])
                    if record.get('file_sha256') == receipt['file_sha256'] or record.get('upload_name') == row['upload_name']:
                        fail('DUPLICATE_PRIOR', '同名或同字节视频有受理记录，先回查原请求，不重复提交。')
                if prior:
                    receipt = json.loads(prior[0])
                    registered = True
                    # 旧回执把明确status=0也留为SENDING；凭原响应迁移，绝不重发。
                    for state in receipt['phases'].values():
                        response_status = state.get('response', {}).get('status')
                        if state['state'] == 'SENDING' and (response_status is False or type(response_status) is int and response_status == 0 or response_status == '0'):
                            state['state'] = 'REJECTED'
                    record = api.lookup(row['upload_name'])
                    if record:
                        verify_record(record, row, require_tags=False)
                    # 写入中断或受理未知只回查；完全未发送的后续步骤可安全继续。
                    if record:
                        for phase, state in receipt['phases'].items():
                            if state['state'] not in ('SENDING', 'REJECTED'):
                                continue
                            target = rebuilt['target']
                            established = (phase == 'join'
                                           or phase in ('source_type', 'source_direction') and target[phase] in record[phase]
                                           or phase == 'roles' and sorted(target['roles']) == sorted(record['roles']))
                            if established:
                                state.update(state='ACK', recovered_by_readback=True)
                    if any(x['state'] == 'REJECTED' for x in receipt['phases'].values()):
                        receipt.update(status='FAILED', error={'code': 'BACKEND_REJECTED', 'reason': '后台明确拒绝已发送步骤；原请求只回查，不自动重放。'})
                        save_receipt(db, key, receipt['status'], receipt)
                        output['items'].append(receipt)
                        continue
                    if any(x['state'] == 'SENDING' for x in receipt['phases'].values()):
                        if record:
                            try:
                                verified = verify_record(record, row)
                                receipt.update(status='CONFIRMED', material_id=verified['id'], readback=verified)
                            except UploadError:
                                receipt.update(status='PENDING', error={'code': 'ACCEPTANCE_UNKNOWN', 'reason': '前一步受理未知，分类未全部核到；只回查，不重放。'})
                        else:
                            receipt.update(status='PENDING', error={'code': 'ACCEPTANCE_UNKNOWN', 'reason': '前一步受理未知，后台尚无唯一记录；只回查，不重放。'})
                        save_receipt(db, key, receipt['status'], receipt)
                        output['items'].append(receipt)
                        continue
                    if receipt['status'] == 'CONFIRMED':
                        verify_record(record or {}, row)
                        receipt['reused'] = True
                        output['items'].append(receipt)
                        continue
                else:
                    existing = api.lookup(row['upload_name'])
                    if existing:
                        verified = verify_record(existing, row, require_tags=False)
                        receipt.update(status='SKIPPED_EXISTING', material_id=verified['id'], readback=verified,
                                       skip_reason='后台已有完全同名、同分类和同尺寸记录；保留其标签，不重复提交，未验证远端字节。')
                        output['items'].append(receipt)
                        continue
                    if reconcile:
                        receipt.update(status='PENDING', error={'code': 'NO_LOCAL_RECORD', 'reason': '没有本机受理记录，只回查不上传。'})
                        output['items'].append(receipt)
                        continue
                    receipt.update(status='PENDING', nonce=reserve_nonce(path, key))
                    save_receipt(db, key, 'PENDING', receipt)
                    registered = True
                if reconcile:
                    record = api.lookup(row['upload_name'])
                    if record:
                        verified = verify_record(record, row)
                        receipt.update(status='CONFIRMED', material_id=verified['id'], readback=verified)
                    output['items'].append(receipt)
                    save_receipt(db, key, receipt['status'], receipt)
                    continue
                # Session及按来源域的Cookie在本次队列中保持不变。每条视频开始
                # 写入前回读一次身份；每个HTTP请求仍检查过期／权限，不为每个
                # 分片和标签重复发送同一个身份查询。
                api.identity(user, name)
                private_form, categories = api.form()
                if categories.get(rebuilt['target']['category']) != rebuilt['target']['category_type']:
                    fail('DICTIONARY_CHANGED', '实际上传分类字典与预览不一致。')
                stage = path / 'staging'
                stage.mkdir(exist_ok=True, mode=0o700)
                staged = stage / (row['media']['sha256'] + '.mp4')
                if not staged.exists():
                    shutil.copyfile(row['path'], staged)
                    os.chmod(staged, 0o400)
                if sha(staged) != row['media']['sha256']:
                    fail('INPUT_CHANGED', '私有提交快照SHA不符。')

                def write_phase(phase, url, params, file=None, boolean=False):
                    if receipt['phases'].get(phase, {}).get('state') == 'ACK':
                        return
                    receipt['phases'][phase] = {'state': 'SENDING'}
                    save_receipt(db, key, 'PENDING', receipt)
                    response = api.request(url, 'POST', params, file)
                    status = response.get('status')
                    # 留最小脱敏协议证据，以免真实返回格式变化只能猜测。
                    summary = {'status_type': type(status).__name__,
                               'status': status if isinstance(status, (bool, int)) or isinstance(status, str) and re.fullmatch(r'-?\d{1,6}', status) else None}
                    message = response.get('message')
                    if isinstance(message, str) and len(message) <= 500:
                        # 合并错误用于定位真实协议问题；先移除本请求及会话私有值。
                        sensitive = list(private_form.values()) + list(api.secret.get('cookies_by_origin', {}).values())
                        for cookie in api.secret.get('cookies_by_origin', {}).values():
                            sensitive += [x.partition('=')[2] for x in cookie.split(';')]
                        for value in sorted((v for v in sensitive if isinstance(v, str) and v), key=len, reverse=True):
                            message = message.replace(value, '[private]')
                        summary['message'] = re.sub(r'https?://\S+|[A-Za-z0-9_=-]{24,}', '[private]', message)
                    receipt['phases'][phase]['response'] = summary
                    save_receipt(db, key, 'PENDING', receipt)
                    # 原生CDN页面按status == 1判断；接受明确的1及其JSON字符串。
                    if not (status is True or type(status) is int and status == 1 or status == '1'):
                        if status is False or type(status) is int and status == 0 or status == '0':
                            receipt['phases'][phase]['state'] = 'REJECTED'
                            save_receipt(db, key, 'FAILED', receipt)
                        # 已得到拒绝也保留为已发；重跑只能回查，不能重复写。
                        fail('BACKEND_REJECTED', '后台未明确确认该步骤：' + phase)
                    receipt['phases'][phase] = {'state': 'ACK', 'response': summary}
                    save_receipt(db, key, 'PENDING', receipt)

                count = len(rebuilt['chunks'])
                endpoints = spec['endpoints']
                write_phase('precheck', endpoints['precheck'], {'name': row['upload_name'], 'num': 0}, boolean=True)
                with staged.open('rb') as handle:
                    for chunk in rebuilt['chunks']:
                        handle.seek(chunk['start'])
                        data = handle.read(chunk['bytes'])
                        if len(data) != chunk['bytes']:
                            fail('INPUT_CHANGED', '提交快照长度不足。')
                        write_phase('chunk_' + str(chunk['index']), endpoints['chunk'],
                                    {'name': row['upload_name'], 'total': count, 'index': chunk['index'], 'time': receipt['nonce']}, file=data)
                fields = dict(private_form, total=count, time=receipt['nonce'], name=row['upload_name'],
                              tag=rebuilt['name']['native_filename_tag'], category_type=rebuilt['target']['category_type'])
                write_phase('join', endpoints['join'], fields)
                record = api.lookup(row['upload_name'])
                if not record:
                    receipt.update(status='PENDING', error={'code': 'INDEXING_PENDING', 'reason': '合并已确认，后台索引尚未出现；稍后续接，不重传分片。'})
                else:
                    verify_record(record, row, require_tags=False)
                    receipt['material_id'] = record['id']
                    target = rebuilt['target']
                    for kind, key_field in [('type', 'source_type'), ('direction', 'source_direction')]:
                        wanted = target[key_field]
                        if wanted and wanted not in record[key_field]:
                            write_phase(key_field, endpoints['source'], {'id': record['id'], 'data': wanted, 'type': kind}, boolean=True)
                    if sorted(record['roles']) != sorted(target['roles']):
                        if target['roles']:
                            write_phase('roles', endpoints['roles'], [('id', record['id'])] + [('tag[]', r) for r in target['roles']], boolean=True)
                        else:
                            fail('TAGS_NOT_CONFIRMED', '后台已有角色标签但目标为空，不能自动删除。')
                    verified = verify_record(api.lookup(row['upload_name']) or {}, row)
                    receipt.pop('error', None)
                    receipt.update(status='CONFIRMED', material_id=verified['id'], readback=verified)
                save_receipt(db, key, receipt['status'], receipt)
            except (UploadError, KeyError, TypeError, OSError, ValueError) as exc:
                rejected = any(x['state'] == 'REJECTED' for x in receipt['phases'].values())
                receipt.update(status='PENDING' if registered and not rejected else 'FAILED',
                               error={'code': getattr(exc, 'code', 'LOCAL_OR_CONTRACT_ERROR'),
                                      'reason': str(exc) if isinstance(exc, UploadError) else '本地数据或已观察接口结构发生变化；未输出响应或私有字段。'})
                if registered:
                    save_receipt(db, key, receipt['status'], receipt)
            output['items'].append(receipt)
    output.update(requested=len(output['items']), confirmed=sum(x['status'] == 'CONFIRMED' for x in output['items']),
                  failed=sum(x['status'] == 'FAILED' for x in output['items']), pending=sum(x['status'] == 'PENDING' for x in output['items']),
                  skipped_existing=sum(x['status'] == 'SKIPPED_EXISTING' for x in output['items']),
                  newly_confirmed=sum(x['status'] == 'CONFIRMED' and not x.get('reused') for x in output['items']),
                  reused_confirmed=sum(x['status'] == 'CONFIRMED' and x.get('reused', False) for x in output['items']),
                  elapsed_seconds=round(time.monotonic() - start, 3))
    return output


def batch(jobs, spec, root, workers=2):
    users = [j['user_id'] for j in jobs]
    if len(users) != len(set(users)):
        fail('QUEUE_CONFLICT', '每个账号只有一个队列；请先合并相同用户的输入。')
    names = [row['upload_name'] for plan in jobs for row in plan['items'] if row['status'] == 'READY']
    if len(names) != len(set(names)):
        fail('CROSS_ACCOUNT_NAME_COLLISION', 'CDN分片不携带用户ID；同批多账号同名视频需明确不同上传名。')
    def run(plan):
        try:
            return upload(plan, spec, root)
        except UploadError as exc:
            return {'user_id': plan['user_id'], 'status': 'ACCOUNT_BLOCKED', 'confirmed': 0,
                    'error': {'code': exc.code, 'reason': str(exc)}}
        except OSError:
            return {'user_id': plan['user_id'], 'status': 'ACCOUNT_BLOCKED', 'confirmed': 0,
                    'error': {'code': 'PRIVATE_SESSION_UNAVAILABLE', 'reason': '该账号私有会话不可读取；其他账号继续。'}}
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 8))) as pool:
        result = list(pool.map(run, jobs))
    return {'accounts': result, 'real_parallel_acceptance': False,
            'note': '并行实现与真实多账号验收分开，真实验收须另留后台证据。'}


def feedback(result):
    lines = ['素材入库回执' + ('（模拟后台，非真实上传）' if result.get('test_only') else ''),
             f'请求 {result["requested"]}｜后台回读成功 {result["confirmed"]}｜失败 {result["failed"]}｜待确认 {result["pending"]}',
             f'本批新增确认 {result.get("newly_confirmed", 0)}｜既有工具回执复核 {result.get("reused_confirmed", 0)}｜后台同名跳过 {result.get("skipped_existing", 0)}',
             f'目标账号：{result["user_display_name"]}｜用户ID：{result["user_id"]}｜协议版本：{VERSION}']
    for row in result['items']:
        target = row.get('target') or {}
        lines.extend([f'{row.get("upload_name") or row["original_name"]}｜{row["status"]}',
                      f'上传项目／分类：{target.get("category", "待核")}（category_type={target.get("category_type", "待核")}）',
                      f'一类：{target.get("source_type", "待核")}｜类标签（分列）：二类={target.get("source_direction") or "无"}；角色标签={"、".join(target.get("roles", [])) or "无"}；自定义标签={"、".join(row.get("readback", {}).get("owner_tags", [])) or "无／未设置"}',
                      f'素材ID：{row.get("material_id") or "未确认"}｜链接：{row.get("readback", {}).get("link") or "未确认"}'])
        if row.get('rename_notice'):
            lines.append(f'名称调整：{row["original_name"]} → {row["upload_name"]}；源文件保留')
        for warning in row.get('warnings', []):
            lines.append('提醒：' + warning['message'] + (f' 制作日期 {warning["production_date"]}；今日 {warning["today"]}' if warning['code'] == 'DATE_MISMATCH' else ''))
        if row.get('error'):
            lines.append('原因：' + row['error']['code'] + ' ' + row['error']['reason'])
        if row.get('skip_reason'):
            lines.append('跳过原因：' + row['skip_reason'])
        if row.get('correction'):
            c = row['correction']
            lines.append('命名纠错：' + c['original_name'] + ' → ' + (c['suggested_name'] or '待实际看帧确认；格式 ' + c['suggested_format']))
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', default=str(SPEC))
    parser.add_argument('--private-root', default='~/.config/rongyao-material-upload')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare'); p.add_argument('--request', required=True); p.add_argument('--output-dir', required=True); p.add_argument('--frames', action='store_true')
    p = commands.add_parser('har-import'); p.add_argument('--source', required=True); p.add_argument('--destination', required=True)
    p = commands.add_parser('session-import'); p.add_argument('--source', required=True); p.add_argument('--user-id', required=True); p.add_argument('--display-name', required=True)
    p = commands.add_parser('doctor'); p.add_argument('--user-id', required=True); p.add_argument('--display-name', required=True)
    for command in ('upload', 'reconcile'):
        p = commands.add_parser(command); p.add_argument('--plan', required=True); p.add_argument('--output', required=True); p.add_argument('--authorization-ticket', required=True)
    p = commands.add_parser('batch'); p.add_argument('--plans', nargs='+', required=True); p.add_argument('--workers', type=int, default=2); p.add_argument('--output', required=True); p.add_argument('--authorization-ticket', required=True)
    p = commands.add_parser('review'); p.add_argument('--frames-manifest', required=True); p.add_argument('--review', required=True); p.add_argument('--output', required=True)
    p = commands.add_parser('feedback'); p.add_argument('--receipt', required=True)
    p = commands.add_parser('reverse'); p.add_argument('--record', required=True)
    args = parser.parse_args()
    spec = read_json(args.spec)
    if args.command == 'prepare':
        result = prepare(read_json(args.request), spec, args.output_dir, args.frames)
        print(json.dumps({'plan': str(Path(args.output_dir).resolve() / 'plan.json'),
                          'local_ready': sum(i['status'] == 'READY' for i in result['items']), 'upload_ready': False,
                          'real_upload_success_count': 0}, ensure_ascii=False)); return
    if args.command == 'har-import':
        result = import_har(args.source, args.destination)
    elif args.command == 'session-import':
        result = import_session(spec, args.private_root, args.source, args.user_id, args.display_name)
    elif args.command == 'doctor':
        api = load_api(spec, account_dir(args.private_root, args.user_id), args.user_id, args.display_name)
        api.form(); result = {'identity_verified': True, 'form_ready': True, 'user_id': args.user_id, 'real_upload_success_count': 0}
    elif args.command == 'review':
        result = attach_review(read_json(args.frames_manifest), read_json(args.review)); atomic_json(args.output, result)
    elif args.command == 'feedback':
        print(feedback(read_json(args.receipt))); return
    elif args.command == 'reverse':
        result = reverse_record(read_json(args.record), spec)
    else:
        if Path(args.output).exists():
            fail('OUTPUT_EXISTS', '不覆盖既有回执。')
        paths=[args.spec]+(args.plans if args.command=='batch' else [args.plan])
        input_sha=guarded_input_sha(paths)
        if args.command=='batch':
            plans=[read_json(x) for x in args.plans]; scope='material-upload:legacy-native-batch:'+input_sha[:16]
            with runtime.mutation('material_upload',scope,authorization_ticket=args.authorization_ticket,input_sha256=input_sha):
                result=batch(plans,spec,args.private_root,args.workers);atomic_json(args.output,result)
        else:
            plan=read_json(args.plan);scope='material-upload:legacy-native:'+str(plan.get('user_display_name') or plan.get('user_id') or input_sha[:16])
            with runtime.mutation('material_upload',scope,authorization_ticket=args.authorization_ticket,input_sha256=input_sha):
                result=upload(plan,spec,args.private_root,args.command=='reconcile');atomic_json(args.output,result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (UploadError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({'error': getattr(exc, 'code', 'LOCAL_OR_CONTRACT_ERROR'),
                          'message': str(exc) if isinstance(exc, UploadError) else '本地文件或合同无效；私有内容不写日志。'}, ensure_ascii=False))
        raise SystemExit(2)
