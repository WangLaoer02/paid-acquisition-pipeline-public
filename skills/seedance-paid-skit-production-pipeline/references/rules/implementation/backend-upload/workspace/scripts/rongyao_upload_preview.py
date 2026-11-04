#!/usr/bin/env python3
"""已观察荣耀原生协议的离线预览。此入口不联网、不保存凭据、不提交。"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys

from material_upload import UploadError, atomic_json, canonical, fail, media, today

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'workflow/maintenance/upload-acceptance/config/rongyao-observed-protocol.json'


def filename_parameters(name, current=None):
    if Path(name).name != name or re.search(r'[\x00-\x1f/\\]', name):
        fail('NAME_INVALID', '上传名只能是文件名，不含控制符或路径。')
    m = re.fullmatch(r'(\d{6})([A-Za-z]+[1-9]\d*)?-(.+)\.(mp4)', name, re.I)
    if not m:
        fail('NAME_INVALID', '候选原生格式：YYMMDD制作人代码序号-内容名-尾标签.mp4；A根可不含代码序号。')
    date, code, text, ext = m.groups()
    try:
        production_date = dt.date(2000 + int(date[:2]), int(date[2:4]), int(date[4:6]))
    except ValueError:
        fail('DATE_INVALID', '命名中的制作日期不是有效日历日期。')
    if any(not x.strip() for x in text.split('-')):
        fail('NAME_EMPTY_SEGMENT', '文件名存在空标签段；请核对重复连字符。')
    if len(name.encode('utf-8')) > 255:
        fail('NAME_TOO_LONG', '上传名超过本机文件名的255字节限制，需明确缩短。')
    suggestion = name[:-len(ext)] + ext.lower()
    warnings = []
    if suggestion != name:
        warnings.append({'code': 'EXTENSION_CASE', 'original': name, 'suggested_name': suggestion,
                         'message': '页面只移除小写.mp4，建议上传名使用小写扩展名；原文件不改。'})
    current = current or today()
    if production_date != current:
        warnings.append({'code': 'DATE_MISMATCH', 'production_date': production_date.isoformat(),
                         'today': current.isoformat(), 'message': '制作日期与今日不同；历史补传保留真实制作日期，若误写再修正。'})
    if not code:
        warnings.append({'code': 'A_ROOT_WITHOUT_CREATOR_CODE',
                         'message': '这是不含制作人代码序号的A根形式；上传成片命名需用户明确采用。'})
    # 与实测页面img(file,count)的replace/split/拼空格算法一致；不解释尾码为人员ID。
    native_tag = ''.join(x + ' ' for x in suggestion.replace('.mp4', '', 1).split('-')[1:])
    return {'original_upload_name': name, 'suggested_upload_name': suggestion,
            'production_date': production_date.isoformat(), 'creator_code_sequence': code,
            'content_segments': text.split('-'), 'native_filename_tag': native_tag,
            'warnings': warnings, 'creator_identity_inferred': False,
            'validation_scope': 'filename_syntax_only', 'requester_mapping_verified': False,
            'designer_mapping_verified': False}


def protocol_plan(request, checked_media, spec, current=None):
    if spec.get('schema') != 'rongyao-observed-upload-1':
        fail('SPEC_INVALID', '必须使用实测原生协议描述，不能复用单步JSON合同。')
    forbidden = {'token', 'cookie', 'cookies', 'authorization', 'password', 'advertiser_id'}
    if forbidden.intersection(k.lower() for k in request):
        fail('SECRET_IN_REQUEST', '公开预览请求不接受认证值；认证只通过私有会话接入。')
    category = request.get('category')
    category_id = spec['categories'].get(category)
    if not category_id or category_id == 'all':
        fail('CATEGORY_NOT_OBSERVED', '分类未在本专项字典中核到，须补读页面；不能视为后台无此分类。')
    first = request.get('source_type')
    direction = request.get('source_direction')
    if first not in spec['source_type']:
        fail('CLASS_NOT_OBSERVED', '一类必须使用详情页已核的文字枚举。')
    if direction and direction not in spec['source_direction_list'].get(first, []):
        fail('CLASS_DIRECTION_CONFLICT', '二类与已观察一类的对应列表不匹配。')
    roles = request.get('roles', [])
    if not isinstance(roles, list) or len(roles) != len(set(roles)):
        fail('ROLE_INVALID', '角色标签必须是无重复列表。')
    if any(x not in spec['roles'] for x in roles):
        fail('ROLE_NOT_OBSERVED', '角色未在专项字典中核到，须补读真实字典。')
    role_values = [spec['roles'][x] for x in roles]
    if len(role_values) != len(set(role_values)):
        fail('ROLE_ALIAS_DUPLICATE', '多个角色别名对应同一原生值，请合并。')
    parsed = filename_parameters(request['upload_name'], current)
    upload_name = parsed['suggested_upload_name']
    size = checked_media['bytes']
    chunk_bytes = spec['chunk_bytes']
    count = (size + chunk_bytes - 1) // chunk_bytes
    if count <= 0:
        fail('EMPTY_FILE', '文件不能为空。')
    nonce = '{persisted_upload_nonce}'
    chunks = [{'index': i + 1, 'start': i * chunk_bytes, 'end_exclusive': min(size, (i + 1) * chunk_bytes),
               'bytes': min(chunk_bytes, size - i * chunk_bytes)} for i in range(count)]
    requests = [
        {'phase': 'name_precheck', 'method': 'POST', 'url': spec['endpoints']['precheck'],
         'fields': {'name': upload_name, 'num': 0}, 'side_effect_semantics_verified': False},
        {'phase': 'chunk_upload', 'method': 'POST', 'url': spec['endpoints']['chunk'],
         'encoding': 'multipart/form-data', 'fields': {'data': '{actual_chunk_bytes}', 'name': upload_name,
                                                     'total': count, 'index': '{chunk_index}', 'time': nonce}},
        {'phase': 'join_register', 'method': 'POST', 'url': spec['endpoints']['join'],
         'fields': {'total': count, 'time': nonce, 'name': upload_name, 'category_type': category_id,
                    'tag': parsed['native_filename_tag'], 'advertiser_id': '{private_form_advertiser_id}',
                    'token': '{private_form_token}', 'create_name': '{private_form_creator}'}},
        {'phase': 'one_class_after_unique_readback', 'method': 'POST', 'url': spec['endpoints']['source'],
         'fields': {'id': '{confirmed_material_id}', 'data': first, 'type': 'type'}}
    ]
    if direction:
        requests.append({'phase': 'direction_after_unique_readback', 'method': 'POST', 'url': spec['endpoints']['source'],
                         'fields': {'id': '{confirmed_material_id}', 'data': direction, 'type': 'direction'}})
    if role_values:
        requests.append({'phase': 'roles_after_unique_readback', 'method': 'POST', 'url': spec['endpoints']['roles'],
                         'fields': {'id': '{confirmed_material_id}', 'tag': role_values},
                         'array_encoding': 'native_jquery_style_tag[]; transport_pending'})
    return {'schema': 'rongyao-offline-preview-1', 'production_ready': False, 'network_requests_sent': 0,
            'real_upload_success_count': 0, 'spec_content_sha256': hashlib.sha256(canonical(spec).encode()).hexdigest(), 'media': checked_media,
            'name': parsed, 'target': {'category': category, 'category_type': category_id,
                                     'user_display_name': request.get('user_display_name'), 'user_id': request.get('user_id'),
                                     'source_type': first, 'source_direction': direction, 'roles': role_values,
                                     'mother_game_gid': None, 'class_tag_semantics': '分列二类和角色标签，待用户采用'},
            'chunks': chunks, 'request_sequence': requests,
            'pending': ['用户明确采用此视频和上传目标', '私有API会话与真实账号身份核验',
                        '原生分片传输适配与未知受理恢复', '唯一素材ID和实际文件回读',
                        '所有标签写后回读', '真实多用户并行与真实会话附件验收']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, help='公开请求JSON，不能含凭据')
    parser.add_argument('--output', required=True, help='新的离线预览JSON路径')
    args = parser.parse_args()
    if Path(args.output).exists():
        fail('OUTPUT_EXISTS', '请使用新的预览文件以保留证据。')
    request = json.loads(Path(args.request).read_text())
    spec = json.loads(SPEC.read_text())
    checked = media(request['path'])
    result = protocol_plan(request, checked, spec)
    atomic_json(args.output, result)
    print(json.dumps({'status': 'offline_preview_only', 'output': str(Path(args.output).resolve()),
                      'category': result['target']['category'], 'category_type': result['target']['category_type'],
                      'source_type': result['target']['source_type'], 'source_direction': result['target']['source_direction'],
                      'roles': result['target']['roles'], 'chunk_count': len(result['chunks']),
                      'warnings': result['name']['warnings'], 'real_upload_success_count': 0}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (UploadError, KeyError, ValueError) as exc:
        print(json.dumps({'error': getattr(exc, 'code', 'INPUT_INVALID'), 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
