#!/usr/bin/env python3
"""复用已验视频清单：排除既存／查重冲突，首条回读通过后再上传余量。"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import time
import sys
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

from material_upload import UploadError, atomic_json, fail, read_json
import rongyao_material_upload as native
from rongyao_upload_preview import SPEC, protocol_plan
sys.path.insert(0,str(Path(__file__).resolve().parent))
import workflow_runtime as runtime

VERSION = 'rongyao-checked-upload-20261010.1'
SINGLE_IDENTITY_URL = 'http://demand.backend.example.invalid/data/?_c=index&_a=top'

def guarded_input_sha(paths):
    h=hashlib.sha256()
    for raw in sorted({str(Path(x).expanduser().resolve()) for x in paths}):
        q=Path(raw);h.update(q.name.encode()+b'\0');h.update(q.read_bytes())
    return h.hexdigest()


def parse_copied_request(text, spec):
    """解析Chrome复制的单条GET，只取Cookie；绝不执行cURL文本。"""
    try:
        parts = shlex.split(text.replace('\\\r\n', '').replace('\\\n', ''))
    except ValueError:
        fail('REQUEST_COPY_INVALID', '复制的请求不是有效文本。')
    if not parts or parts.pop(0) != 'curl':
        fail('REQUEST_COPY_INVALID', '需要Chrome复制的单条cURL请求。')
    urls, cookies = [], []
    index = 0
    while index < len(parts):
        value = parts[index]
        if value.startswith(('http://', 'https://')):
            urls.append(value)
        elif value in ('--url', '-b', '--cookie', '-H', '--header', '-X', '--request'):
            index += 1
            if index >= len(parts):
                fail('REQUEST_COPY_INVALID', '请求参数缺少值。')
            parameter = parts[index]
            if value == '--url':
                urls.append(parameter)
            elif value in ('-b', '--cookie'):
                if '=' not in parameter or '\r' in parameter or '\n' in parameter:
                    fail('REQUEST_COPY_INVALID', '只接受请求Cookie文本，不读其他Cookie文件。')
                cookies.append(parameter)
            elif value in ('-H', '--header') and parameter.lower().startswith('cookie:'):
                cookies.append(parameter.partition(':')[2].strip())
            elif value in ('-X', '--request') and parameter != 'GET':
                fail('REQUEST_COPY_INVALID', '只接受已观察的只读GET请求。')
        elif value not in ('--compressed', '--insecure'):
            fail('REQUEST_COPY_INVALID', '请求包含不需要的选项；不执行请求文本。')
        # Chrome附带的--insecure只作为文本忽略；从不传给HTTP客户端。
        # 认证只绑定已观察的HTTP入口，既不执行cURL也不关闭TLS校验。
        index += 1
    if urls != [spec['entry']] or len(set(cookies)) != 1:
        fail('REQUEST_COPY_INVALID', '请求必须是本轮已观察上传入口且包含唯一Cookie。')
    p = urlsplit(spec['entry'])
    origin = p.scheme + '://' + p.netloc
    return {'cookies_by_origin': {origin: cookies[0]}, 'identity_proof': None}


def consume_request_file(path, spec):
    path = Path(path).expanduser()
    if (path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid()
            or native.ROOT in path.resolve().parents or path.stat().st_size > 1024 * 1024):
        fail('PRIVATE_FILE_REQUIRED', '一次性请求须是工作区外当前用户的0600私有文件。')
    text = path.read_text()
    secret = parse_copied_request(text, spec)
    path.unlink()
    return secret


class TransientSingleApi(native.NativeApi):
    """单次内存会话核对实际登录名；数字UID未核到时明确保留为空。"""
    transient_single_account = True

    def identity(self, user, name):
        if user is not None:
            fail('IDENTITY_MISMATCH', '单会话模式不接受推断的数字UID。')
        url = self.spec.get('single_identity_test_url') if self.test_only else SINGLE_IDENTITY_URL
        soup = BeautifulSoup(self.request(url, text=True), 'html.parser')
        matches = [m.group(1).strip() for a in soup.select('a')
                   if (m := re.fullmatch(r'用户[：:]\s*(.+)', a.get_text(strip=True)))]
        if matches != [name]:
            fail('IDENTITY_MISMATCH', '当前登录名不是队列指定账号，或账号节点不唯一。')
        self.checked_identity = True
        return {'display_name': name, 'display_name_verified': True, 'user_id': None,
                'numeric_user_id_verified': False, 'scope': 'single_current_session',
                'identity_url': url, 'real_multi_user_acceptance': False}


def checked_queue(plan, spec, readbacks, canary_name):
    """这里只筛选证据，不把空详情视为已完成全库查重。提交时仍在线预检。"""
    if plan.get('schema') != native.VERSION or plan.get('spec_sha256') != native.digest(spec):
        fail('PLAN_STALE', '已验清单与当前协议不一致。')
    records = {}
    for record in readbacks['records']:
        name = record.get('requested_name') or record.get('name')
        if not name or name in records:
            fail('READBACK_AMBIGUOUS', '每个输入名须只有一条查重证据。')
        records[name] = record
    candidates, skipped, held = [], [], []
    for row in plan['items']:
        summary = {'upload_name': row['upload_name'], 'file_sha256': row.get('media', {}).get('sha256'),
                   'target': row.get('native', {}).get('target')}
        if row['status'] != 'READY' or not row.get('media', {}).get('full_decode'):
            held.append(dict(summary, reason='LOCAL_CHECK_NOT_PASSED'))
            continue
        record = records.get(row['upload_name'][:-4])
        if record is None:
            held.append(dict(summary, reason='READBACK_EVIDENCE_MISSING'))
        elif record.get('id') and record.get('name') == row['upload_name'][:-4]:
            native.verify_record(record, row, require_tags=False)
            skipped.append(dict(summary, material_id=record['id'], reason='EXISTING_EXACT_NAME',
                                remote_bytes_sha256_verified=False))
        elif record.get('id'):
            held.append(dict(summary, reason='READBACK_NAME_COLLISION', returned_material_id=record['id']))
        elif record.get('result') == 'NO_RECORD_RETURNED_NAME_PRECHECK_PENDING':
            candidates.append(copy.deepcopy(row))
        else:
            held.append(dict(summary, reason='EXACT_LOOKUP_UNRESOLVED'))
    canaries = [r for r in candidates if r['upload_name'] == canary_name]
    if len(canaries) != 1:
        fail('CANARY_NOT_ELIGIBLE', '首条须是已验清单中尚待接口预检的唯一候选。')
    return {'schema': VERSION, 'spec_sha256': native.digest(spec), 'source_plan_sha256': native.digest(plan),
            'user_display_name': plan['user_display_name'], 'requested': len(plan['items']),
            'skipped_existing': skipped, 'held': held, 'canary': canaries[0],
            'remaining': [r for r in candidates if r['upload_name'] != canary_name],
            'candidates': len(candidates), 'upload_ready': False, 'real_upload_success_count': 0,
            'checks_reused': ['完整解码', '媒体规格', '已有采样帧命名核对（如有）', '命名与分类映射'],
            'checks_at_submission': ['API真实身份', '当前原片SHA', '精确名称查重／接口预检',
                                     '私有发送快照SHA', '唯一素材ID及分类标签回读'],
            'canary_gate': 'CONFIRMED后才发送剩余视频；未知受理只续接原请求，不重传。'}


def bind_plan(queue, rows, spec, user_id, display_name):
    if queue.get('schema') != VERSION or queue.get('spec_sha256') != native.digest(spec):
        fail('PLAN_STALE', '待上传队列协议已变化。')
    if display_name != queue['user_display_name']:
        fail('IDENTITY_MISMATCH', '目标姓名与已验队列不一致。')
    user_id = str(user_id) if user_id is not None else None
    result = {'schema': native.VERSION, 'spec_sha256': native.digest(spec), 'user_id': user_id,
              'user_display_name': display_name, 'items': copy.deepcopy(rows)}
    for row in result['items']:
        old_target = dict(row['native']['target'], user_id=user_id, user_display_name=display_name)
        old_chunks = row['native']['chunks']
        if row['native']['media'] != row['media']:
            fail('PLAN_STALE', '已有媒体证据被编辑，不能在身份绑定时覆盖。')
        row['request'].update(user_id=user_id, user_display_name=display_name)
        rebuilt = protocol_plan(row['request'], row['media'], spec)
        if rebuilt['target'] != old_target or rebuilt['chunks'] != old_chunks:
            fail('PLAN_STALE', '身份绑定只能补真实账号，不能改变已验分类标签或分片。')
        row['native'] = rebuilt
    return result


def execute(queue, spec, private_root, user_id, display_name, output_dir, api_override=None):
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        fail('OUTPUT_EXISTS', '使用新的执行目录保留真实受理证据。')
    output_dir.mkdir(parents=True)
    result = {'schema': VERSION, 'requested': queue['requested'], 'user_display_name': display_name,
              'user_id': str(user_id) if user_id is not None else None, 'skipped_existing': len(queue['skipped_existing']),
              'held': len(queue['held']), 'newly_confirmed': 0, 'confirmed': 0,
              'remaining_not_sent': len(queue['remaining']), 'canary_passed': False,
              'test_only': spec.get('test_only') is True, 'status': 'BLOCKED_BEFORE_UPLOAD'}
    try:
        def submit(rows, label):
            plan = bind_plan(queue, rows, spec, user_id, display_name)
            receipt = native.upload(plan, spec, private_root, api_override=api_override)
            atomic_json(output_dir / (label + '-attempt-0.json'), receipt)
            for attempt in range(1, 7):
                pending = [row for row, item in zip(rows, receipt['items'])
                           if item.get('error', {}).get('code') == 'INDEXING_PENDING']
                if not pending:
                    break
                print(json.dumps({'phase': 'waiting_for_index', 'items': len(pending), 'attempt': attempt,
                                  'new_video_bytes_retransmitted': False}), flush=True)
                time.sleep(30)
                resumed = native.upload(bind_plan(queue, pending, spec, user_id, display_name), spec,
                                        private_root, api_override=api_override)
                atomic_json(output_dir / f'{label}-attempt-{attempt}.json', resumed)
                updates = {r['upload_name']: r for r in resumed['items']}
                receipt['items'] = [updates.get(r['upload_name'], r) for r in receipt['items']]
                for key, status in [('confirmed', 'CONFIRMED'), ('pending', 'PENDING'), ('failed', 'FAILED'),
                                    ('skipped_existing', 'SKIPPED_EXISTING')]:
                    receipt[key] = sum(r['status'] == status for r in receipt['items'])
                receipt['newly_confirmed'] = sum(r['status'] == 'CONFIRMED' and not r.get('reused') for r in receipt['items'])
                receipt['reused_confirmed'] = sum(r['status'] == 'CONFIRMED' and r.get('reused', False) for r in receipt['items'])
            return receipt
        canary = submit([queue['canary']], 'canary')
        atomic_json(output_dir / 'canary-receipt.json', canary)
        result['canary'] = canary
        result['newly_confirmed'] = canary['newly_confirmed']
        result['confirmed'] = canary['confirmed']
        if canary['confirmed'] == 1:
            result.update(canary_passed=True, status='CANARY_CONFIRMED')
            remaining = submit(queue['remaining'], 'remaining')
            atomic_json(output_dir / 'remaining-receipt.json', remaining)
            result.update(remaining=remaining, remaining_not_sent=0,
                          newly_confirmed=result['newly_confirmed'] + remaining['newly_confirmed'],
                          confirmed=result['confirmed'] + remaining['confirmed'],
                          status='EXECUTED_WITH_UNRESOLVED_ITEMS' if remaining['pending'] or remaining.get('failed', 0) else 'ELIGIBLE_QUEUE_CONFIRMED')
        else:
            result['status'] = 'CANARY_NOT_CONFIRMED_REMAINING_NOT_SENT'
    except (UploadError, OSError) as exc:
        result['status'] = 'REMAINING_BLOCKED_AFTER_CANARY' if result['canary_passed'] else 'BLOCKED_BEFORE_UPLOAD'
        result['error'] = {'code': getattr(exc, 'code', 'PRIVATE_SESSION_UNAVAILABLE'),
                           'reason': str(exc) if isinstance(exc, UploadError) else '私有登录态文件无法读取。'}
    atomic_json(output_dir / 'run-receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', default=str(SPEC))
    parser.add_argument('--private-root', default='~/.config/rongyao-material-upload')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('queue')
    p.add_argument('--plan', required=True); p.add_argument('--readbacks', required=True)
    p.add_argument('--canary-name', required=True); p.add_argument('--output', required=True)
    p = sub.add_parser('execute')
    p.add_argument('--queue', required=True); p.add_argument('--user-id', required=True)
    p.add_argument('--display-name', required=True); p.add_argument('--output-dir', required=True); p.add_argument('--authorization-ticket', required=True)
    p = sub.add_parser('execute-single')
    p.add_argument('--queue', required=True); p.add_argument('--request-file', required=True)
    p.add_argument('--display-name', required=True); p.add_argument('--output-dir', required=True); p.add_argument('--authorization-ticket', required=True)
    args = parser.parse_args()
    spec = read_json(args.spec)
    if args.command == 'queue':
        if Path(args.output).exists():
            fail('OUTPUT_EXISTS', '不覆盖已验队列。')
        result = checked_queue(read_json(args.plan), spec, read_json(args.readbacks), args.canary_name)
        atomic_json(args.output, result)
        print(json.dumps({'requested': result['requested'], 'skipped_existing': len(result['skipped_existing']),
                          'held': len(result['held']), 'candidates': result['candidates'],
                          'canary': result['canary']['upload_name'], 'real_upload_success_count': 0}, ensure_ascii=False))
    elif args.command == 'execute-single':
        input_sha=guarded_input_sha([args.spec,args.queue,args.request_file]);scope='material-upload:legacy-checked-single:'+args.display_name
        runtime.ensure_writer('material_upload');runtime.check_circuit('material_upload',scope);runtime.dependencies('material_upload');runtime.ensure_release(True);runtime.authorization(args.authorization_ticket,'material_upload',scope,input_sha,False)
        with runtime.mutation('material_upload',scope,authorization_ticket=args.authorization_ticket,input_sha256=input_sha):
            api = TransientSingleApi(spec, consume_request_file(args.request_file, spec))
            api.identity(None, args.display_name);api.form()
            result = execute(read_json(args.queue), spec, args.private_root, None, args.display_name, args.output_dir, api)
            result.update(credential_mode='one_time_file_consumed_into_memory', temporary_request_file_deleted=True,numeric_user_id_verified=False, real_multi_user_acceptance=False)
            atomic_json(Path(args.output_dir) / 'run-receipt.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        input_sha=guarded_input_sha([args.spec,args.queue]);scope='material-upload:legacy-checked:'+str(args.user_id)
        with runtime.mutation('material_upload',scope,authorization_ticket=args.authorization_ticket,input_sha256=input_sha):
            result=execute(read_json(args.queue), spec, args.private_root, args.user_id,args.display_name,args.output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (UploadError, KeyError, TypeError, OSError, ValueError) as exc:
        print(json.dumps({'error': getattr(exc, 'code', 'LOCAL_OR_CONTRACT_ERROR'),
                          'message': str(exc) if isinstance(exc, UploadError) else '本地清单无效，未输出私有内容。'}, ensure_ascii=False))
        raise SystemExit(2)
