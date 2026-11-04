#!/usr/bin/env python3
"""Local naming, review, batching and duplicate checks. No website calls."""
import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
FIELDS = {'category_type', 'ai_source', 'origin_type', 'demand_name', 'source_ip',
          'source_type', 'source_direction', 'gid', 'role', 'region_type', 'is_redbag'}
MULTI = {'source_ip', 'source_type', 'source_direction', 'role'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def component(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label}必须是明确文字')
    if re.search(r'[\\/\x00-\x1f:*?"<>|]', value) or value != value.strip():
        raise ValueError(f'{label}含文件名非法字符或首尾空格')
    return value


def canonical_params(params):
    if set(params) != FIELDS:
        raise ValueError(f'表单字段不完整或未知：缺{sorted(FIELDS-set(params))}，多{sorted(set(params)-FIELDS)}')
    result = {}
    for key, value in params.items():
        if key in MULTI:
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ValueError(f'{key}必须是字符串列表')
            result[key] = sorted(set(value))
        else:
            if not isinstance(value, str):
                raise ValueError(f'{key}必须是页面真实字符串值')
            result[key] = value
    for key in ['category_type', 'origin_type', 'demand_name', 'gid']:
        if not result[key]:
            raise ValueError(f'{key}不能为空')
    if not result['role']:
        raise ValueError('必须有主推角色标签')
    return result


def probe(path, executable):
    proc = subprocess.run([executable, '-v', 'error', '-show_format', '-show_streams',
                           '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
    if proc.returncode:
        raise ValueError(f'媒体读取失败：{path.name}：{proc.stderr[:300]}')
    data = json.loads(proc.stdout)
    videos = [s for s in data['streams'] if s.get('codec_type') == 'video']
    audios = [s for s in data['streams'] if s.get('codec_type') == 'audio']
    if not videos or not audios:
        raise ValueError(f'{path.name}缺视频或音轨，须先核对加工')
    v, a = videos[0], audios[0]
    if path.suffix.lower() != '.mp4' or v['codec_name'] != 'h264' or a['codec_name'] != 'aac':
        raise ValueError(f'{path.name}须先转为已验证兼容的H.264/AAC MP4')
    return {'duration': float(data['format']['duration']), 'bytes': path.stat().st_size,
            'video': {k: v.get(k) for k in ['codec_name', 'profile', 'width', 'height',
                                          'pix_fmt', 'avg_frame_rate', 'nb_frames']},
            'audio': {k: a.get(k) for k in ['codec_name', 'sample_rate', 'channels']}}


def inspect_item(item, request, presets, profile, ffprobe, source_hashes):
    source_path = Path(item['file']).expanduser()
    if not source_path.is_absolute() or not source_path.is_file():
        raise ValueError('成品必须是存在的绝对文件路径')
    code = component(request.get('designer_code', profile['designer_code']), '设计师代码')
    if code not in presets['registered_codes']:
        raise ValueError(f'设计师代码{code}未登记，先核对真实映射')
    date = request.get('date_prefix')
    if not isinstance(date, str) or not re.fullmatch(r'\d{6}', date):
        raise ValueError('本次date_prefix必须是已确定的YYMMDD，不能复用旧日期')
    dt.datetime.strptime(date, '%y%m%d')
    serial = item.get('serial')
    if isinstance(serial, bool) or not isinstance(serial, int) or serial < 1:
        raise ValueError('serial必须是本次已分配的正整数')
    b = item.get('b_source')
    if b is None:
        key = item.get('b_key')
        if key not in presets['b_library']:
            raise ValueError(f'未知B段{key}，先核对准确来源')
        b = presets['b_library'][key]
    required = ['name', 'record_id', 'source_file', 'source_sha256', 'role', 'role_token',
                'b_description', 'second_designer_name', 'second_designer_value', 'b_start', 'b_end']
    if any(k not in b for k in required):
        raise ValueError('B段来源、切点、角色或归属不完整')
    if not b['second_designer_name'] or not b['second_designer_value']:
        raise ValueError('自己A接他人B必须有已核对的第二设计师，不能沿用原创空值')
    if item.get('expected_b_name') != b['name']:
        raise ValueError('B段完整名称与本次锁定来源不一致')
    original = Path(b['source_file']).expanduser()
    if not original.is_absolute() or not original.is_file():
        raise ValueError('B源片缓存缺失，需恢复准确原文件')
    if str(original) not in source_hashes:
        source_hashes[str(original)] = digest(original)
    if source_hashes[str(original)] != b['source_sha256']:
        raise ValueError('B源片SHA256变化，不可复用旧切点/归属核查')
    if not 0 <= b['b_start'] < b['b_end']:
        raise ValueError('B段切点无效')
    description = component(item['a_description'], 'A描述') + '接' + component(b['b_description'], 'B描述')
    if b['role_token'] not in description:
        raise ValueError('正式名缺少主推角色')
    tail = component(request.get('requester_tail', profile['requester_tail']), '需求/来源尾标')
    parts = [f'{date}{code}{serial}', description, tail]
    intern = item.get('intern_marker')
    if intern:
        parts.append(component(intern, '当前组合实习生制作编号'))
    if item.get('split_37') is not True:
        raise ValueError('本助手针对自己A接他人B，需确认37约定；其他模式先调整规则')
    parts.append('37')
    name = '-'.join(parts)
    sha = digest(source_path)
    q = item.get('quality_review', {})
    if q.get('media_sha256') != sha or q.get('full_decode_exit') != 0 or q.get('full_decode_errors') != '':
        raise ValueError('成品完整解码核查缺失或SHA已变化')
    for key in ['disclaimer_verified', 'moving_watermark_verified', 'role_verified', 'splice_verified']:
        if q.get(key) is not True:
            raise ValueError(f'成品核查未完成：{key}')
    evidence = q.get('evidence', [])
    if not evidence or any(not Path(p).is_absolute() or not Path(p).is_file() for p in evidence):
        raise ValueError('核查证据必须是存在的绝对路径')
    params = dict(profile['parameters'])
    params.update(request.get('shared_parameters', {}))
    params.update(item.get('parameters', {}))
    # Per-B role and credit are protected from accidentally inherited defaults.
    expected = {'role': [b['role']], 'region_type': b['second_designer_value']}
    for key, value in expected.items():
        explicit = item.get('parameters', {}).get(key, request.get('shared_parameters', {}).get(key))
        if explicit is not None and explicit != value:
            raise ValueError(f'{key}与锁定B段的角色/第二设计师不一致')
        params[key] = value
    params = canonical_params(params)
    result = {'name': name, 'filename': name + '.mp4', 'source_file': str(source_path),
            'upload_file': str(source_path), 'sha256': sha, 'serial': serial,
            'designer': presets['registered_codes'][code], 'designer_code': code,
            'date_prefix': date, 'requester_tail': tail, 'intern_marker': intern,
            'b_source': b, 'second_designer': b['second_designer_name'],
            'form_values': params, 'quality_review': q, 'media': probe(source_path, ffprobe),
            'provenance': {**(request.get('shared_provenance') or {}),
                           **(item.get('provenance') or {})}}
    if item.get('inherit_from') is not None:
        result['inherit_from'] = item['inherit_from']
    return result


def prepare(request, presets, ffprobe, copy_dir=None):
    key = request.get('profile')
    if key not in presets['profiles']:
        raise ValueError('必须明确选择已确认工作档案profile')
    profile = presets['profiles'][key]
    if not request.get('items'):
        raise ValueError('没有成品items')
    ledger = request.get('uploaded_records', [])
    items, blocked, groups, seen, source_hashes = [], [], {}, set(), {}
    for n, item in enumerate(request['items'], 1):
        try:
            r = inspect_item(item, request, presets, profile, ffprobe, source_hashes)
            if r['name'] in seen:
                raise ValueError('本批出现重复正式名称')
            seen.add(r['name'])
            matches = [e for e in ledger if e.get('name') == r['name']]
            if any(e.get('sha256') != r['sha256'] for e in matches):
                raise ValueError('已有同名不同SHA记录，先核对/区分版本，不能覆盖重传')
            saved = [e for e in matches if e.get('status') in {'listed', 'metadata_verified'} and e.get('record_id')]
            if saved:
                r.update(state='skip_already_listed', backend_record_id=saved[0]['record_id'])
                items.append(r)
                continue
            if matches:
                raise ValueError('同名提交状态待核对，不能自动重传')
            destination = Path(copy_dir).expanduser() / r['filename'] if copy_dir else Path(r['source_file'])
            if not copy_dir and destination.name != r['filename']:
                raise ValueError('成品名尚未正式命名；使用--copy-dir生成正式副本')
            if copy_dir:
                if not destination.is_absolute():
                    raise ValueError('--copy-dir必须是绝对路径')
                if destination.exists() and digest(destination) != r['sha256']:
                    raise ValueError('本地同名文件内容不同，禁止覆盖')
            r.update(upload_file=str(destination), state='ready_for_ui')
            items.append(r)
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as e:
            blocked.append({'item': n, 'file': item.get('file'), 'reason': str(e)})
    # Avoid partially copying a batch that fails validation.
    if not blocked:
        for r in items:
            if r['state'] != 'ready_for_ui':
                continue
            destination = Path(r['upload_file'])
            if copy_dir and not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with Path(r['source_file']).open('rb') as src, destination.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                if digest(destination) != r['sha256']:
                    raise ValueError('正式副本SHA不一致，禁止提交')
            group_key = json.dumps(r['form_values'], sort_keys=True, ensure_ascii=False)
            group = groups.setdefault(group_key, {'form_values': r['form_values'], 'files': [], 'names': []})
            group['files'].append(r['upload_file'])
            group['names'].append(r['name'])
    return {'scope': 'local_preparation_only', 'profile': key, 'can_proceed_to_ui': not blocked,
            'test_only': request.get('test_only') is True,
            'shared_provenance': request.get('shared_provenance') or {},
            'upload_performed': False, 'items': items, 'blocked': blocked,
            'upload_batches': list(groups.values()), 'skip_count': sum(r['state']=='skip_already_listed' for r in items),
            'batch_count': len(groups), 'note': '默认交给rongyao-http-upload；计划不是上传授权、网站成功或审核证据'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--copy-dir')
    parser.add_argument('--presets', default=str(SKILL/'references'/'verified-presets.json'))
    parser.add_argument('--ffprobe', default=shutil.which('ffprobe') or '<receiver-configured-path>')
    args = parser.parse_args()
    try:
        result = prepare(load(args.request), load(args.presets), args.ffprobe, args.copy_dir)
    except (ValueError, OSError, KeyError, TypeError) as e:
        result = {'scope':'local_preparation_only', 'can_proceed_to_ui':False,
                  'upload_performed':False, 'blocked':[{'reason':str(e)}], 'upload_batches':[]}
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        parser.error('--output必须是绝对路径')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:result.get(k) for k in ['can_proceed_to_ui','batch_count','skip_count','blocked','upload_performed']}, ensure_ascii=False))
    return 0 if result['can_proceed_to_ui'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
