#!/usr/bin/env python3
"""荣耀 AI CLI: validated plans, browser-session requests, and result inspection.

Automatic transport discovers the dedicated session through the fixed keyring.
Paid sends require the published workspace runtime and a single-use ticket.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import http.client
import importlib.util
import json
import mimetypes
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / 'references/models.snapshot.json'
HOST = 'ai.cn.sy.backend.example.invalid'
TERMINAL = {'done', 'failed', 'timeout', 'cancelled', 'canceled'}
GENERATION_SCOPE = 'paid-generation:rongyao-ai-generator'
PUBLISHED_SOURCE = 'implementation/rongyao-tools/skills/rongyao-ai-generator/scripts/ryai.py'


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check_pricing(plan, allow_unpriced):
    if plan.get('estimated_cost') is None and not allow_unpriced:
        raise ValueError('UNPRICED_GENERATION_REQUIRES_EXPLICIT_APPROVAL')


class GenerationLedger:
    """Immutable input identity and durable checkpoint before a potentially paid send."""
    def __init__(self, root=None):
        self.root = Path(root or Path.home()/'.codex/state/rongyao-ai-generator/jobs')

    def path(self, digest):
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('INVALID_INPUT_SHA256')
        return self.root/(digest+'.json')

    def read(self, digest):
        p = self.path(digest)
        return read_json(p) if p.is_file() else None

    def write(self, digest, value):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        p = self.path(digest); temporary = p.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        temporary.replace(p)
        fd = os.open(self.root, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def reserve(self, digest, model):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root/'.ledger.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.read(digest):
                raise ValueError('GENERATION_ALREADY_REGISTERED: query original task/job')
            self.write(digest, {'input_sha256':digest, 'model':model, 'state':'submission_pending', 'created_at':now()})

    def update(self, digest, **fields):
        value = self.read(digest)
        if not value: raise ValueError('GENERATION_JOB_NOT_FOUND')
        value.update(fields, updated_at=now()); self.write(digest, value)


def persist_native_receipt(ledger, digest, receipt, evidence_text):
    """Persist only a task ID visibly labeled in this submission's evidence."""
    existing = ledger.read(digest)
    if not existing:
        raise ValueError('GENERATION_JOB_NOT_FOUND')
    task_id = receipt.get('task_id') if receipt.get('state') == 'submitted' else None
    if task_id is not None:
        if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,128}', task_id):
            raise ValueError('NATIVE_TASK_ID_INVALID')
        pattern = r'(?:task[_ -]?id|任务(?:id|编号))\s*[:：]\s*' + re.escape(task_id) + r'(?![A-Za-z0-9_-])'
        if not re.search(pattern, evidence_text, re.IGNORECASE):
            raise ValueError('NATIVE_TASK_ID_NOT_IN_EVIDENCE')
    if existing.get('task_id') and existing['task_id'] != task_id:
        raise ValueError('ORIGINAL_TASK_ID_CONFLICT')
    ledger.update(digest, state=receipt['state'], native_receipt=receipt, task_id=task_id,
                  task_id_status='verified_in_evidence' if task_id else 'unavailable')


def resolve_session(args):
    """Use current dedicated-session metadata, never remembered ports or front-window state."""
    if args.transport != 'auto': return
    state_dir = Path.home()/'.codex/state'
    if (state_dir/'rongyao-keyring/disabled').exists():
        raise ValueError('ACCESS_REVOKED')
    state = state_dir/'rongyao-active-session/session.json'
    if state.is_file():
        saved = read_json(state); port = saved.get('port')
        if isinstance(port, int) and 0 < port < 65536:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=4) as response:
                    tabs = json.load(response)
                matches = [x for x in tabs if x.get('type') == 'page' and urlparse(x.get('url','')).netloc == HOST and urlparse(x.get('url','')).scheme == 'http']
                if len(matches) == 1:
                    args.transport = 'cdp'; args.cdp_url = f'http://127.0.0.1:{port}'; args.target_id = matches[0]['id']; return
                if len(matches) > 1:
                    raise ValueError('MULTIPLE_AI_TABS: resolve original session target explicitly')
            except ValueError: raise
            except (OSError, TimeoutError):
                # Only the fixed helper decides whether a missing process may restart.
                pass
    keyring = ROOT.parent/'rongyao-keyring/scripts/keyring.py'
    if not keyring.is_file(): raise ValueError('KEYRING_CLI_MISSING')
    result = subprocess.run([sys.executable, str(keyring), 'ensure-ai'], capture_output=True, text=True, timeout=220)
    try: session = json.loads(result.stdout)
    except ValueError: raise ValueError('AI_SESSION_HELPER_OUTPUT_INVALID') from None
    if result.returncode or not session.get('authenticated') or not session.get('ok'):
        raise ValueError('AI_SESSION_REQUIRED: '+str(session.get('status','UNVERIFIED')))
    args.transport='cdp'; args.cdp_url=f"http://127.0.0.1:{session['port']}"; args.target_id=session['target_id']


def generation_runtime(workspace):
    if not workspace: raise ValueError('WORKSPACE_REQUIRED')
    root = Path(workspace).expanduser().resolve()
    runtime_path = root/'scripts/workflow_runtime.py'
    if not runtime_path.is_file(): raise ValueError('WORKSPACE_RUNTIME_REQUIRED')
    manifest = read_json(root/'workflow/rules/manifest.json')
    expected = manifest.get('implementation_files',{}).get(PUBLISHED_SOURCE)
    if expected != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('GENERATION_CLI_RELEASE_MISMATCH')
    spec = importlib.util.spec_from_file_location('ryai_pipeline_runtime', runtime_path)
    runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
    return runtime


def guarded_submit(plan, body, args):
    runtime = generation_runtime(args.workspace)
    runtime.ensure_writer('paid_generation')
    if not args.authorization_ticket: raise ValueError('AUTHORIZATION_TICKET_REQUIRED')
    if args.transport == 'browser': raise ValueError('GENERATION_REQUIRES_AUTOMATIC_TRANSPORT')
    check_pricing(plan, args.allow_unpriced)
    digest = plan_digest(plan); ledger = GenerationLedger()
    if ledger.read(digest): raise ValueError('GENERATION_ALREADY_REGISTERED: query original task/job')
    # Validate output destination before any remote send.
    if args.output and Path(args.output).expanduser().exists(): raise ValueError('OUTPUT_ALREADY_EXISTS')
    with runtime.mutation('paid_generation', GENERATION_SCOPE,
                          authorization_ticket=args.authorization_ticket, input_sha256=digest):
        resolve_session(args)  # Authentication failure is before the paid-send checkpoint.
        ledger.reserve(digest, body['model'])
        try:
            args.return_result = True
            value = dispatch({'command':'submit','operation':'request','action':'send','execute':True,'body':body}, args)
        except Exception:
            ledger.update(digest, state='submission_unknown')
            raise
        payload = value.get('response',{}); data = payload.get('data') or {}
        task_id = data.get('task_id') or (data.get('generation') or {}).get('task_id')
        ledger.update(digest, state=('submitted' if task_id else 'submission_unknown') if value.get('ok') else 'rejected',
                      task_id=task_id, chatid=data.get('chatid'), request_id=data.get('request_id'))
        value['input_sha256'] = digest
        emit(value, args.output)
        return 0 if value.get('ok') else 1


def validate_native_plan(plan, workspace):
    """Validate visible native-UI inputs without fabricating API attachment IDs."""
    import math
    root = Path(workspace).resolve()
    if plan.get('schema') != 'rongyao-native-ui-v1':
        raise ValueError('NATIVE_PLAN_SCHEMA_REQUIRED')
    body = validate_plan(plan['generation_plan'])
    if body.get('attachments') or body.get('attachment_ids') or body.get('subject_refs'):
        raise ValueError('NATIVE_REFERENCES_USE_FILE_MANIFEST')
    if plan.get('page_url') != 'http://ai.cn.sy.backend.example.invalid/data/':
        raise ValueError('NATIVE_TARGET_MISMATCH')
    if plan.get('reference_files') is None:
        raise ValueError('NATIVE_REFERENCES_REQUIRED')
    for row in plan['reference_files']:
        p = Path(row['path']).resolve()
        if not p.is_relative_to(root) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('NATIVE_REFERENCE_CHANGED')
        if row['visible_name'] != p.name:
            raise ValueError('NATIVE_REFERENCE_NAME_MISMATCH')
    evidence = Path(plan['ui_evidence']['path']).resolve()
    if not evidence.is_relative_to(root) or hashlib.sha256(evidence.read_bytes()).hexdigest() != plan['ui_evidence']['sha256']:
        raise ValueError('NATIVE_UI_EVIDENCE_CHANGED')
    visible = evidence.read_text()
    expected_labels = [model_config(body['model'])['label'], '比例 '+body['ratio'], '时长 '+str(body['duration'])+'秒', '清晰度 '+body['resolution'], ('' if body['generate_audio'] else '')+' 音频', ('' if body['prompt_optimize'] else '')+' 提示词优化']
    if any(x not in visible for x in expected_labels):
        raise ValueError('NATIVE_PARAMETERS_MISMATCH')
    if body['type'] != 'Video' or body['video_mode'] != 'full' or body['chatid'] or body['parent_ids']:
        raise ValueError('NATIVE_NEW_FULL_VIDEO_ONLY')
    for text in [body['prompt'], *plan['required_visible_labels'], *[r['visible_name'] for r in plan['reference_files']]]:
        if not text or text not in visible:
            raise ValueError('NATIVE_UI_INPUT_MISMATCH')
    quote = plan.get('quoted_points'); reserve = plan.get('reserve_points')
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or x <= 0 for x in [quote, reserve]) or reserve < quote:
        raise ValueError('NATIVE_VALID_PRICE_REQUIRED')
    if plan.get('quote_label') not in visible or str(quote) not in plan['quote_label']:
        raise ValueError('NATIVE_QUOTE_EVIDENCE_REQUIRED')
    return body


def guarded_native_submit(plan, args):
    """Hold the published guard across one CUA send; EOF/timeout remains unknown."""
    import select
    runtime = generation_runtime(args.workspace)
    body = validate_native_plan(plan, args.workspace)
    digest = plan_digest(plan); ledger = GenerationLedger()
    budget_path = Path(args.budget_ledger).resolve()
    if not budget_path.is_relative_to(Path(args.workspace).resolve()):
        raise ValueError('WORKSPACE_BUDGET_REQUIRED')
    with runtime.mutation('paid_generation', GENERATION_SCOPE,
                          authorization_ticket=args.authorization_ticket, input_sha256=digest):
        budget = read_json(budget_path)
        if budget.get('unknown_outcome_jobs'):
            raise ValueError('RECONCILE_UNKNOWN_BUDGET_FIRST')
        reserve = plan['reserve_points']
        if budget['settled_points'] + budget['reserved_points'] + reserve > budget['total_cap']:
            raise ValueError('PROJECT_BUDGET_EXCEEDED')
        # Every file is rechecked inside the lock, before the paid-send checkpoint.
        validate_native_plan(plan, args.workspace)
        ledger.reserve(digest, body['model'])
        budget['reserved_points'] += reserve
        budget['submitted_jobs'].append({'input_sha256': digest, 'state': 'submission_pending', 'reserved_points': reserve, 'transport': 'native_ui'})
        budget['status'] = 'native_submission_pending'
        runtime.atomic(budget_path, budget)
        print(json.dumps({'ok': True, 'state': 'READY_FOR_ONE_NATIVE_SEND', 'input_sha256': digest, 'expires_in_seconds': 90}), flush=True)
        try:
            if not select.select([sys.stdin], [], [], 90)[0]:
                raise ValueError('NATIVE_RECEIPT_TIMEOUT')
            receipt = json.loads(sys.stdin.readline())
            if receipt.get('input_sha256') != digest or receipt.get('state') not in {'submitted', 'rejected', 'not_sent'}:
                raise ValueError('NATIVE_RECEIPT_INVALID')
            evidence = Path(receipt['evidence_path']).resolve()
            if not evidence.is_relative_to(Path(args.workspace).resolve()) or not evidence.is_file() or hashlib.sha256(evidence.read_bytes()).hexdigest() != receipt['evidence_sha256']:
                raise ValueError('NATIVE_RECEIPT_EVIDENCE_REQUIRED')
            if receipt['state'] == 'submitted' and not receipt.get('observable_reference'):
                raise ValueError('NATIVE_RESULT_REFERENCE_REQUIRED')
            persist_native_receipt(ledger, digest, receipt, evidence.read_text())
            task_id = ledger.read(digest).get('task_id')
            budget['submitted_jobs'][-1].update(state=receipt['state'], observable_reference=receipt.get('observable_reference'), task_id=task_id)
            # No automatic release/refund: settle only from observable billing evidence.
            budget['status'] = 'native_' + receipt['state']
            runtime.atomic(budget_path, budget)
            runtime.event('paid_generation', receipt['state'], GENERATION_SCOPE, input_sha256=digest, receipt=receipt)
            print(json.dumps({'ok': True, 'state': receipt['state'], 'input_sha256': digest, 'task_id': task_id}), flush=True)
        except BaseException:
            ledger.update(digest, state='submission_unknown')
            budget['submitted_jobs'][-1]['state'] = 'submission_unknown'
            budget['unknown_outcome_jobs'].append(digest)
            budget['status'] = 'reconcile_native_submission'
            runtime.atomic(budget_path, budget)
            raise


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).expanduser().read_text(encoding='utf-8'))


def emit(value, output=None):
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if output:
        path = Path(output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            stream.write(text)
        print(json.dumps({'ok': True, 'output': str(path)}, ensure_ascii=False))
    else:
        print(text, end='')


def catalog():
    return read_json(SNAPSHOT)


def model_config(key):
    for group in catalog().values():
        if key in group['models']:
            return group['models'][key]
    raise ValueError('未知模型键；用 models 查看后台配置快照')


def choice(value, limits, options_key, default_key):
    values = limits.get(options_key, [])
    selected = value if value is not None else limits.get(default_key, '')
    if value is not None and not values:
        raise ValueError(f'当前模型不支持 {options_key}')
    if values and str(selected) not in {str(x) for x in values}:
        raise ValueError(f'{options_key}={selected} 不支持；允许值：{values}')
    return str(selected)


def media_kind(item):
    value = str(item.get('type', '')).lower()
    extension = str(item.get('ext', '')).lower().lstrip('.')
    if value.startswith('image') or extension in {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'}:
        return 'image'
    if value.startswith('video') or extension in {'mp4', 'mov', 'webm', 'mkv'}:
        return 'video'
    if value.startswith('audio') or extension in {'mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac'}:
        return 'audio'
    return 'other'


def file_data(path, expected_type=list):
    value = read_json(path) if path else expected_type()
    if not isinstance(value, expected_type):
        raise ValueError(f'{path} 必须是 JSON {expected_type.__name__}')
    return value


def normalize_subject_refs(items):
    if not isinstance(items, list):
        raise ValueError('subject_refs 必须为 JSON 列表')
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('主体引用必须是主体库对象')
        images = list(item.get('images', []))
        for key in ['img1', 'img2', 'img3', 'img4']:
            if item.get(key) and item[key] not in images:
                images.append(item[key])
        images = list(dict.fromkeys(images))[:4]
        if not item.get('subject_name') or not images:
            raise ValueError('主体引用需要实际 subject_name 与 images/img1 等图片字段')
        for url in images:
            parsed = urlparse(url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
                raise ValueError('主体图片必须使用主体库实际返回的媒体 URL')
        result.append({'id': int(item.get('id', 0)), 'subject_name': item['subject_name'], 'subject_desc': item.get('subject_desc', ''), 'images': images})
    return result


def validate_attachments(items, limits, kind, mode=''):
    if not isinstance(items, list) or any(not isinstance(x, dict) or not x.get('attachment_id') for x in items):
        raise ValueError('attachments 必须包含后台 upload 返回的 attachment_id 与媒体元数据')
    counts = {key: 0 for key in ['image', 'video', 'audio', 'other']}
    maxima = {'image': limits.get('max_image_attachments', 0), 'video': limits.get('max_video_attachments', 0), 'audio': limits.get('max_audio_attachments', 0)}
    if kind == 'Video':
        if mode == 'text':
            maxima = dict.fromkeys(maxima, 0)
        elif mode in {'first_frame', 'first_last'}:
            maxima = {'image': min(maxima['image'], 1 if mode == 'first_frame' else 2), 'video': 0, 'audio': 0}
    for item in items:
        media = media_kind(item)
        counts[media] += 1
        if kind != 'Chat' and media == 'other':
            raise ValueError('生成图片或视频时引用素材必须标明 Image/Video/Audio 类型或扩展名')
        limit = limits.get(f'max_{media}_attachment_bytes')
        if limit and int(item.get('size', 0)) > limit:
            raise ValueError(f'{media} 素材超过当前模型大小上限')
    for media, maximum in maxima.items():
        if counts[media] > maximum:
            raise ValueError(f'{mode or kind} 模式最多 {maximum} 个 {media} 附件，实际 {counts[media]}')
    if mode == 'first_frame' and counts['image'] != 1:
        raise ValueError('首帧模式需要 1 张实际上传图片')
    if mode == 'first_last' and counts['image'] != 2:
        raise ValueError('首尾帧模式需要按首帧、尾帧顺序提供 2 张实际上传图片')


def build_plan(args):
    kind = args.type.capitalize()
    group = catalog()[kind]
    key = args.model or group['default_model']
    config = model_config(key)
    if config['type'] != kind or config.get('hide_in_selector'):
        raise ValueError('模型不属于所选生成类型，或属于专用工具；请使用 models 中可选模型')
    limits = config['limits']
    prompt = Path(args.prompt_file).read_text(encoding='utf-8').strip() if args.prompt_file else (args.prompt or '').strip()
    if not prompt:
        raise ValueError('需要 --prompt 或 --prompt-file')
    attachments = file_data(args.attachments)
    subject_refs = normalize_subject_refs(file_data(args.subject_refs))
    parent_ids = file_data(args.parent_ids)
    if args.chatid and not args.parent_ids:
        raise ValueError('续接历史会话需要明确 --parent-ids；默认创建新会话')
    body = {'type': kind, 'mode': kind.lower(), 'model': key, 'chatid': args.chatid or '', 'parent_ids': parent_ids,
            'message': prompt, 'attachments': attachments, 'attachment_ids': [x.get('attachment_id') for x in attachments if isinstance(x, dict)]}
    if kind != 'Chat':
        body.update(prompt=prompt, subject_refs=subject_refs, prompt_optimize=not args.no_optimize)
    if kind == 'Image':
        if any(x is not None for x in [args.duration, args.video_mode, args.audio]):
            raise ValueError('图片生成不接受视频参数')
        body.update(size=choice(args.size, limits, 'image_sizes', 'default_size'), ratio=choice(args.ratio, limits, 'image_ratios', 'default_ratio'),
                    resolution=choice(args.resolution, limits, 'image_resolutions', 'default_resolution'),
                    n=choice(args.count, limits, 'image_counts', 'default_output_images'),
                    quality=choice(args.quality, limits, 'image_qualities', 'default_quality'),
                    output_format=choice(args.format, limits, 'image_output_formats', 'default_output_format'),
                    background=choice(args.background, limits, 'image_backgrounds', 'default_background'),
                    image_ratio='', intelligent_ratio=False)
    elif kind == 'Video':
        if any(x is not None for x in [args.size, args.quality, args.format, args.background]):
            raise ValueError('视频生成不接受图片专用参数')
        mode = choice(args.video_mode, limits, 'video_modes', 'default_video_mode')
        body.update(video_mode=mode, seedance2_mode=mode, ratio=choice(args.ratio, limits, 'video_ratios', 'default_ratio'),
                    resolution=choice(args.resolution, limits, 'video_resolutions', 'default_resolution'),
                    duration=choice(args.duration, limits, 'video_durations', 'default_duration'),
                    n=choice(args.count, limits, 'video_counts', 'default_output_videos'),
                    generate_audio=args.audio if args.audio is not None else limits.get('generate_audio', False))
        mode_resolutions = limits.get('video_mode_resolutions', {}).get(mode)
        if mode_resolutions and body['resolution'] not in mode_resolutions:
            raise ValueError('当前视频模式不支持所选清晰度')
        if body['generate_audio'] and not limits.get('supports_generate_audio'):
            raise ValueError('当前模型不支持生成音频')
        validate_attachments(attachments, limits, kind, mode)
    else:
        if subject_refs or any(x is not None for x in [args.size, args.ratio, args.resolution, args.count, args.quality, args.format, args.background, args.duration, args.video_mode, args.audio]):
            raise ValueError('聊天请求不接受图片/视频参数或主体引用')
    if kind != 'Video':
        validate_attachments(attachments, limits, kind)
    return {'schema': 'ryai-plan-v1', 'prepared_at': now(), 'execution_state': 'planned', 'endpoint': '/data/?_c=aiModel&_a=send',
            'model_label': config['label'], 'model_config_source': 'authenticated_page_snapshot_2026-10-05',
            'estimated_cost': None, 'quota_unit': {'Chat': '元', 'Image': '次', 'Video': '秒'}[kind], 'body': body}


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get('schema') != 'ryai-plan-v1' or plan.get('endpoint') != '/data/?_c=aiModel&_a=send':
        raise ValueError('不支持的计划格式或提交地址')
    body = plan.get('body', {})
    config = model_config(body.get('model'))
    kind = config['type']
    if config.get('hide_in_selector') or body.get('type') != kind or body.get('mode') != kind.lower():
        raise ValueError('提交计划类型和模型不一致')
    if not str(body.get('message', '')).strip() or kind != 'Chat' and body.get('prompt') != body.get('message'):
        raise ValueError('计划提示词为空或 prompt/message 不一致')
    limits = config['limits']
    mappings = {'Image': {'size': 'image_sizes', 'ratio': 'image_ratios', 'resolution': 'image_resolutions', 'n': 'image_counts', 'quality': 'image_qualities', 'output_format': 'image_output_formats', 'background': 'image_backgrounds'},
                'Video': {'video_mode': 'video_modes', 'ratio': 'video_ratios', 'resolution': 'video_resolutions', 'duration': 'video_durations', 'n': 'video_counts'}}
    allowed = {'type', 'mode', 'model', 'chatid', 'parent_ids', 'message', 'attachments', 'attachment_ids'}
    if kind != 'Chat':
        allowed |= {'prompt', 'subject_refs', 'prompt_optimize'} | set(mappings[kind])
        allowed |= {'image_ratio', 'intelligent_ratio'} if kind == 'Image' else {'seedance2_mode', 'generate_audio'}
    if set(body) - allowed:
        raise ValueError('计划包含未实现的提交字段：' + ', '.join(sorted(set(body) - allowed)))
    for field, key in mappings.get(kind, {}).items():
        values = limits.get(key, [])
        value = body.get(field, '')
        if values and str(value) not in {str(x) for x in values} or not values and value not in ['', None]:
            raise ValueError(f'计划参数 {field} 不支持')
    for field in ['prompt_optimize', 'generate_audio', 'intelligent_ratio']:
        if field in body and not isinstance(body[field], bool):
            raise ValueError(f'{field} 必须是布尔值')
    if kind == 'Video':
        if body.get('seedance2_mode') != body.get('video_mode'):
            raise ValueError('seedance2_mode/video_mode 不一致')
        if body.get('generate_audio') and not limits.get('supports_generate_audio'):
            raise ValueError('模型不支持音频')
        mode_resolutions = limits.get('video_mode_resolutions', {}).get(body.get('video_mode'))
        if mode_resolutions and body.get('resolution') not in mode_resolutions:
            raise ValueError('当前视频模式不支持所选清晰度')
    if not isinstance(body.get('parent_ids'), list) or not isinstance(body.get('subject_refs', []), list):
        raise ValueError('上下文和主体引用必须为列表')
    if kind != 'Chat' and normalize_subject_refs(body.get('subject_refs', [])) != body.get('subject_refs', []):
        raise ValueError('主体引用应保留 id、subject_name、subject_desc、images 四个请求字段')
    attachments = body.get('attachments', [])
    validate_attachments(attachments, limits, kind, body.get('video_mode', ''))
    if body.get('attachment_ids') != [x['attachment_id'] for x in attachments]:
        raise ValueError('附件元数据和 attachment_ids 不一致')
    return body


def browser_expression(spec):
    adapter = (ROOT / 'scripts/browser_adapter.js').read_text(encoding='utf-8')
    return '(async()=>{\n' + adapter + '\nreturn await runRyai(' + json.dumps(spec, ensure_ascii=False) + ');\n})()'


def dispatch(spec, args):
    resolve_session(args)
    expression = browser_expression(spec)
    if args.transport == 'cdp':
        if not args.cdp_url:
            raise ValueError('需要 --cdp-url；只连接现有调试会话，不会启动 Chrome')
        node = os.environ.get('NODE_BIN') or shutil.which('node')
        if not node:
            candidate = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
            node = str(candidate) if candidate.is_file() else None
        if not node:
            raise ValueError('CDP 模式需要 Node.js 22+（全局 WebSocket）')
        process = subprocess.run([node, str(ROOT / 'scripts/cdp_bridge.mjs')],
                                 input=json.dumps({'endpoint': args.cdp_url, 'target_id': args.target_id, 'expression': expression}),
                                 capture_output=True, text=True, timeout=135)
        if process.returncode:
            raise RuntimeError(process.stderr.strip().splitlines()[-1] if process.stderr.strip() else 'CDP 请求失败；提交结果未知时不得重放')
        value = json.loads(process.stdout)
        if getattr(args, 'return_result', False): return value
        emit(value, args.output)
        return 0 if value.get('ok') else 1
    result_name = 'ryai-' + spec['command'] + '-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json'
    script = expression + '.then(result=>{const a=document.createElement("a");const u=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:"application/json"}));a.href=u;a.download=' + json.dumps(result_name) + ';a.click();setTimeout(()=>URL.revokeObjectURL(u),3000);console.log("RYAI_RESULT",{ok:result.ok,execution_state:result.execution_state,command:result.command});}).catch(error=>console.error("RYAI_ERROR",error.message));\n'
    if args.script_out:
        path = Path(args.script_out).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            stream.write(script)
        emit({'ok': True, 'execution_state': 'prepared', 'script': str(path), 'result_filename': result_name, 'executed': False,
              'instructions': '在已登录荣耀 AI 标签页控制台运行脚本。安全警告由用户处理；不自动允许粘贴。'}, args.output)
    else:
        print(script, end='')
    return 0


def read_spec(args):
    command = args.command
    action, query = 'sessions', {}
    if command == 'quota':
        action, query = 'quotaSummary', {'mode': args.mode}
        if args.detail:
            query = {'detail': 1}
    elif command == 'session':
        action, query = 'sessionDetail', {'chatid': args.chatid}
    elif command == 'messages':
        action, query = 'sessionMessages', {'chatid': args.chatid, 'before_id': args.before_id, 'limit': args.limit}
    elif command == 'task':
        action, query = 'taskStatus', {'task_id': args.task_id}
    elif command == 'assets':
        action, query = 'assetList', {'favorite_filter': args.favorite, 'media_type': args.media_type, 'model_key': args.model or 'all',
                                      'day_window': 1, 'day_offset': args.day_offset, 'day_size': args.day_size, 'owner_scope': args.scope}
    elif command == 'subjects':
        action, query = 'subjectList', {'scope': args.scope, 'keyword': args.keyword, 'page': args.page, 'page_size': args.page_size}
    elif command == 'voices':
        action, query = 'audioCloneList', {'page': args.page, 'page_size': args.page_size, 'keyword': args.keyword, 'status': 'all', 'visibility': 'all'}
    elif command == 'tts-history':
        action, query = 'audioTtsHistory', {'page': args.page, 'page_size': args.page_size}
    return {'command': command, 'operation': 'request', 'action': action, 'query': query}


def inspect_result(value):
    payload = value.get('response', value)
    data = payload.get('data') or {}
    if not isinstance(data, dict):
        data = {}
    generation = data.get('generation') or data
    status = str(generation.get('status', data.get('status', ''))).lower()
    media = []
    for key in ['images', 'videos', 'audios']:
        if isinstance(generation.get(key), list):
            media.extend(generation[key])
    return {'ok': payload.get('ok'), 'checked_at': value.get('checked_at'), 'task_id': data.get('task_id') or generation.get('task_id'),
            'chatid': data.get('chatid'), 'status': status or None, 'terminal': status in TERMINAL,
            'generation_done': payload.get('ok') is True and status == 'done', 'media_count': len(media), 'media': media,
            'download_verified': False, 'visual_acceptance': None,
            'session_count': len(data['sessions']) if isinstance(data.get('sessions'), list) else None,
            'row_count': len(data['rows']) if isinstance(data.get('rows'), list) else None,
            'has_more': data.get('has_more'), 'error': payload.get('error') or data.get('error')}


def media_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('INVALID_MEDIA_URL: 需要后台结果中的无账号信息 http/https 媒体 URL')
    return url


def recover_original_result(args):
    """Read the one original task, then retrieve its single unambiguous result once."""
    job = GenerationLedger().read(args.input_sha256)
    if not job or job.get('input_sha256') != args.input_sha256:
        raise ValueError('ORIGINAL_JOB_NOT_FOUND')
    if job.get('state') not in {'submitted', 'submission_unknown'}:
        raise ValueError('ORIGINAL_JOB_NOT_RECOVERABLE')
    task_id = job.get('task_id')
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,128}', task_id):
        raise ValueError('ORIGINAL_TASK_ID_UNAVAILABLE')
    if getattr(args, 'transport', 'auto') == 'browser':
        raise ValueError('LIVE_ORIGINAL_RESULT_UNAVAILABLE')
    output = getattr(args, 'output', None)
    if output and (Path(output).expanduser().exists() or
                   Path(output).expanduser().resolve() == Path(args.destination).expanduser().resolve()):
        raise ValueError('DOWNLOAD_OUTPUT_PATH_CONFLICT')
    args.return_result = True
    value = dispatch({'command': 'task', 'operation': 'request', 'action': 'taskStatus',
                      'query': {'task_id': task_id}}, args)
    if not isinstance(value, dict):
        raise ValueError('LIVE_ORIGINAL_RESULT_UNAVAILABLE')
    result = inspect_result(value)
    if result['task_id'] != task_id:
        raise ValueError('ORIGINAL_TASK_ID_MISMATCH')
    if not result['generation_done']:
        raise ValueError('ORIGINAL_TASK_NOT_DONE')
    if result['media_count'] != 1 or not isinstance(result['media'][0], dict):
        raise ValueError('ORIGINAL_RESULT_AMBIGUOUS')
    url = result['media'][0].get('url')
    if not isinstance(url, str):
        raise ValueError('ORIGINAL_RESULT_URL_MISSING')
    media_url(url)
    if not args.execute:
        return {'ok': True, 'task_id': task_id, 'download_attempted': False,
                'execution_state': 'read_only_ready', 'user_adoption': False}
    receipt = download_to_destination(url, args.destination, args.expected_sha256)
    return {**receipt, 'task_id': task_id, 'download_attempted': True,
            'user_adoption': False}


def local_media_receipt(path):
    """Verify local bytes, readable streams and full decode; never asserts content acceptance."""
    try:
        initial = path.lstat()
    except OSError:
        raise ValueError('MEDIA_FILE_REQUIRED') from None
    if not stat.S_ISREG(initial.st_mode) or not initial.st_size:
        raise ValueError('MEDIA_FILE_REQUIRED')
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns)
    baseline = identity(initial)
    def unchanged():
        try:
            current = path.lstat()
        except OSError:
            raise ValueError('MEDIA_CHANGED_DURING_VALIDATION') from None
        if identity(current) != baseline:
            raise ValueError('MEDIA_CHANGED_DURING_VALIDATION')
    def digest_file():
        unchanged()
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            if identity(os.fstat(stream.fileno())) != baseline:
                raise ValueError('MEDIA_CHANGED_DURING_VALIDATION')
            head = stream.read(256)
            if head.lstrip().lower().startswith((b'<html', b'<!doctype html')):
                raise ValueError('MEDIA_RESPONSE_IS_HTML')
            digest.update(head)
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            if identity(os.fstat(stream.fileno())) != baseline:
                raise ValueError('MEDIA_CHANGED_DURING_VALIDATION')
        unchanged()
        return digest.hexdigest()
    ffprobe, ffmpeg = shutil.which('ffprobe'), shutil.which('ffmpeg')
    if not ffprobe or not ffmpeg:
        raise ValueError('MEDIA_VALIDATOR_REQUIRED: ffprobe and ffmpeg')
    digest = digest_file()
    probe = subprocess.run([ffprobe, '-v', 'error', '-show_entries',
                            'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=30)
    unchanged()
    if probe.returncode:
        raise ValueError('MEDIA_NOT_READABLE')
    data = json.loads(probe.stdout)
    if not any(s.get('codec_type') in {'video', 'audio'} for s in data.get('streams', [])):
        raise ValueError('MEDIA_STREAM_REQUIRED')
    decoded = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
                              '-map', '0:v?', '-map', '0:a?', '-f', 'null', '-'],
                             capture_output=True, timeout=120)
    unchanged()
    if decoded.returncode:
        raise ValueError('MEDIA_DECODE_FAILED')
    if digest_file() != digest:
        raise ValueError('MEDIA_CHANGED_DURING_VALIDATION')
    return {'file': str(path), 'bytes': initial.st_size, 'sha256': digest,
            'bytes_verified': True, 'download_verified': True, 'media_metadata_verified': True,
            'full_decode_verified': True, 'media': data, 'playback_verified': False,
            'visual_acceptance': None}


def download_to_destination(url, destination, expected_sha256=None):
    """Read an existing result URL without cookies; commit verified bytes without overwriting."""
    media_url(url)
    if expected_sha256 is not None and (len(expected_sha256) != 64 or
            any(c not in '0123456789abcdef' for c in expected_sha256)):
        raise ValueError('INVALID_EXPECTED_SHA256')
    target = Path(destination).expanduser().absolute()
    if (target.suffix.lower() in {'.part', '.crdownload'} or target.is_symlink() or
            (target.exists() and not target.is_file())):
        raise ValueError('INVALID_MEDIA_DESTINATION')
    if target.exists() and expected_sha256 is not None:
        existing = local_media_receipt(target)
        if existing['sha256'] != expected_sha256:
            raise ValueError('MEDIA_DESTINATION_CONFLICT: existing SHA differs; preserved')
        return {**existing, 'ok': True, 'execution_state': 'download_reused', 'reused': True}
    if not shutil.which('ffprobe') or not shutil.which('ffmpeg'):
        raise ValueError('MEDIA_VALIDATOR_REQUIRED: ffprobe and ffmpeg')

    class MediaRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            media_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.' + target.name + '-', suffix='.part',
                                         dir=target.parent, delete=False) as stream:
            partial = Path(stream.name)
            request = urllib.request.Request(url, headers={'Accept': 'video/*, audio/*, image/*, application/octet-stream'})
            opener = urllib.request.build_opener(MediaRedirect())
            with opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError('MEDIA_DOWNLOAD_HTTP_STATUS: ' + str(response.status))
                kind = response.headers.get_content_type() if response.headers.get('Content-Type') else None
                if kind and (kind.startswith('text/') or kind in {'application/json', 'application/xhtml+xml'}):
                    raise ValueError('MEDIA_RESPONSE_NOT_MEDIA')
                length = response.headers.get('Content-Length')
                expected_bytes = int(length) if length is not None else None
                total = 0
                deadline = time.monotonic() + 120
                while chunk := response.read(1024 * 1024):
                    if time.monotonic() > deadline:
                        raise ValueError('MEDIA_DOWNLOAD_TIMEOUT')
                    stream.write(chunk)
                    total += len(chunk)
                if expected_bytes is not None and total != expected_bytes:
                    raise ValueError('MEDIA_DOWNLOAD_INCOMPLETE')
            stream.flush()
            os.fsync(stream.fileno())
        receipt = local_media_receipt(partial)
        if expected_sha256 is not None and receipt['sha256'] != expected_sha256:
            raise ValueError('MEDIA_DOWNLOAD_SHA_MISMATCH')
        try:
            os.link(partial, target)  # Atomic create; even a concurrent writer cannot be overwritten.
        except FileExistsError:
            existing = local_media_receipt(target)
            if existing['sha256'] != receipt['sha256']:
                raise ValueError('MEDIA_DESTINATION_CONFLICT: existing SHA differs; preserved')
            return {**existing, 'ok': True, 'execution_state': 'download_reused', 'reused': True}
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {**receipt, 'file': str(target), 'ok': True, 'execution_state': 'download_completed', 'reused': False}
    except urllib.error.HTTPError as error:
        raise ValueError('MEDIA_DOWNLOAD_HTTP_ERROR: ' + str(error.code)) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
        raise ValueError('MEDIA_DOWNLOAD_NETWORK_ERROR') from None
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport', choices=['auto', 'browser', 'cdp'], default='auto')
    parser.add_argument('--cdp-url', default=os.environ.get('RONGYAO_AI_CDP_URL'))
    parser.add_argument('--target-id')
    parser.add_argument('--script-out', help='浏览器模式：将待运行脚本保存到新文件')
    parser.add_argument('--output', help='JSON 输出文件（拒绝覆盖）')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='查询会话以验证登录；browser 模式仅生成核验脚本')
    models = sub.add_parser('models', help='读取已登录页面的模型快照，无网络请求')
    models.add_argument('--type', choices=['chat', 'image', 'video'])
    models.add_argument('--all', action='store_true', help='包含隐藏专用工具')
    models.add_argument('--key', help='返回一个模型完整配置')
    sub.add_parser('refresh-models', help='从现有已登录页面导出实时模型配置')
    sub.add_parser('sessions', help='会话列表')
    quota = sub.add_parser('quota', help='额度与使用量；聊天为元、图片为次、视频为秒')
    quota.add_argument('--mode', choices=['chat', 'image', 'video'], default='image')
    quota.add_argument('--detail', action='store_true')
    session = sub.add_parser('session', help='读取指定会话及其分页元数据')
    session.add_argument('--chatid', required=True)
    messages = sub.add_parser('messages', help='按 before_id 读取更早消息')
    messages.add_argument('--chatid', required=True); messages.add_argument('--before-id', required=True)
    messages.add_argument('--limit', type=int, choices=range(1, 101), default=20)
    task = sub.add_parser('task', help='只查询同一个 task_id，不重新生成')
    task.add_argument('--task-id', required=True)
    assets = sub.add_parser('assets', help='按天窗口查看素材，has_more 不代表已取完')
    assets.add_argument('--scope', choices=['self', 'all', 'department', 'group'], default='self')
    assets.add_argument('--favorite', choices=['all', 'favorited', 'unfavorited'], default='all')
    assets.add_argument('--media-type', choices=['all', 'image', 'video', 'audio'], default='all')
    assets.add_argument('--model'); assets.add_argument('--day-offset', type=int, default=0); assets.add_argument('--day-size', type=int, default=3)
    subjects = sub.add_parser('subjects', help='主体库名称和引用素材')
    subjects.add_argument('--scope', choices=['self', 'public'], default='self'); subjects.add_argument('--keyword', default='')
    voices = sub.add_parser('voices'); voices.add_argument('--keyword', default='')
    for listing in [subjects, voices, sub.add_parser('tts-history')]:
        listing.add_argument('--page', type=int, default=1); listing.add_argument('--page-size', type=int, default=20)
    plan = sub.add_parser('plan', help='生成校验后的 JSON 计划；不上传、不扣费')
    plan.add_argument('--type', choices=['chat', 'image', 'video'], required=True); plan.add_argument('--model')
    prompt = plan.add_mutually_exclusive_group(required=True); prompt.add_argument('--prompt'); prompt.add_argument('--prompt-file')
    for flag in ['chatid', 'parent-ids', 'attachments', 'subject-refs', 'size', 'ratio', 'resolution', 'quality', 'format', 'background', 'video-mode']:
        plan.add_argument('--' + flag)
    plan.add_argument('--count', type=int); plan.add_argument('--duration', type=int)
    plan.add_argument('--audio', action=argparse.BooleanOptionalAction, default=None)
    plan.add_argument('--no-optimize', action='store_true')
    submit = sub.add_parser('submit', help='显式提交已准备的计划；不会自动重试')
    submit.add_argument('--plan', required=True); submit.add_argument('--execute', action='store_true')
    submit.add_argument('--workspace'); submit.add_argument('--authorization-ticket')
    submit.add_argument('--allow-unpriced', action='store_true', help='仅用于本次已明确授权的未知计价例外；不是免费')
    native = sub.add_parser('native-submit', help='Hold registered runtime guard for one observed native UI send; never sends API or copies credentials')
    native.add_argument('--plan', required=True); native.add_argument('--workspace', required=True)
    native.add_argument('--authorization-ticket'); native.add_argument('--budget-ledger')
    native.add_argument('--execute', action='store_true')
    preflight = sub.add_parser('inspect-plan', help='只读校验完整计划并返回授权所需输入SHA')
    preflight.add_argument('--plan', required=True)
    job = sub.add_parser('job-status', help='只读原生成作业，不重新提交')
    job.add_argument('--input-sha256', required=True)
    upload = sub.add_parser('upload', help='上传素材；默认只列出大小和模型上限')
    upload.add_argument('--file', required=True); upload.add_argument('--type', choices=['chat', 'image', 'video'], required=True)
    upload.add_argument('--model', required=True); upload.add_argument('--execute', action='store_true')
    download = sub.add_parser('download', help='下载已有媒体；--destination校验实际落盘，省略时仅请求浏览器')
    download.add_argument('--url', required=True); download.add_argument('--name', required=True)
    download.add_argument('--destination', help='完整本地文件路径；直接下载并校验落盘，不调用浏览器')
    download.add_argument('--expected-sha256', help='已有结果的预期SHA256；仅与--destination一起使用')
    recovery = sub.add_parser('recover-original', help='只读原任务并在明确指定时取回唯一结果；不重新生成')
    recovery.add_argument('--input-sha256', required=True)
    recovery.add_argument('--destination', required=True)
    recovery.add_argument('--expected-sha256')
    recovery.add_argument('--execute', action='store_true')
    inspect = sub.add_parser('inspect', help='解读实际返回 JSON，区分提交、完成、下载和验收')
    inspect.add_argument('--file', required=True)
    verify = sub.add_parser('verify-download', help='校验本地真实下载文件并计算 SHA256')
    verify.add_argument('--file', required=True)
    args = parser.parse_args()
    if args.command in {'submit', 'native-submit'} and args.execute and args.workspace:
        runtime = generation_runtime(args.workspace)
        runtime.ensure_writer('paid_generation')
        workspace = Path(args.workspace).expanduser().resolve()
        published = workspace/'workflow/rules'/PUBLISHED_SOURCE
        if Path(__file__).resolve() != published.resolve():
            wrapper = workspace/'scripts/ryai.py'
            expected = read_json(workspace/'workflow/rules/manifest.json').get('workspace_contract_files',{}).get('scripts/ryai.py')
            if not expected or not wrapper.is_file() or hashlib.sha256(wrapper.read_bytes()).hexdigest() != expected:
                raise ValueError('REGISTERED_GENERATION_WRAPPER_CHANGED')
            os.execv(sys.executable, [sys.executable, str(wrapper), *sys.argv[1:]])
    if args.command == 'models':
        if args.key:
            emit({'source': 'page_snapshot_2026-10-05', 'live': False, 'model': model_config(args.key)}, args.output)
        else:
            rows = [config for kind, group in catalog().items() if not args.type or kind.lower() == args.type for config in group['models'].values() if args.all or not config.get('hide_in_selector')]
            emit({'source': 'page_snapshot_2026-10-05', 'live': False, 'count': len(rows), 'models': rows}, args.output)
    elif args.command == 'plan':
        emit(build_plan(args), args.output)
    elif args.command == 'submit':
        plan = read_json(args.plan); body = validate_plan(plan)
        if not args.execute:
            emit({'ok': True, 'execution_state': 'planned', 'submitted': False, 'body': body, 'next': '授权生成后加 --execute'}, args.output)
        else:
            return guarded_submit(plan, body, args)
    elif args.command == 'native-submit':
        plan = read_json(args.plan); validate_native_plan(plan, args.workspace)
        if not args.execute:
            emit({'ok': True, 'submitted': False, 'input_sha256': plan_digest(plan), 'scope': GENERATION_SCOPE}, args.output)
        else:
            if not args.budget_ledger: raise ValueError('BUDGET_LEDGER_REQUIRED')
            return guarded_native_submit(plan, args)
    elif args.command == 'inspect-plan':
        plan = read_json(args.plan); validate_plan(plan)
        emit({'ok':True,'input_sha256':plan_digest(plan),'scope':GENERATION_SCOPE,
              'model':plan['body']['model'],'estimated_cost':plan.get('estimated_cost'),
              'pricing_known':plan.get('estimated_cost') is not None,'submitted':False}, args.output)
    elif args.command == 'job-status':
        value = GenerationLedger().read(args.input_sha256)
        if value is None: raise ValueError('GENERATION_JOB_NOT_FOUND')
        emit({'ok':True,'job':value,'submitted':False}, args.output)
    elif args.command == 'upload':
        path = Path(args.file).expanduser().resolve()
        config = model_config(args.model)
        if config['type'].lower() != args.type:
            raise ValueError('上传类型与模型不一致')
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        kind = media_kind({'type': mime, 'ext': path.suffix})
        limits = config['limits']
        maximum = limits.get(f'max_{kind}_attachment_bytes', 100 * 1024 * 1024)
        if not path.is_file() or path.stat().st_size > maximum:
            raise ValueError('文件不存在或超过上传大小上限')
        if kind in {'image', 'video', 'audio'} and not limits.get(f'max_{kind}_attachments', 0):
            raise ValueError('当前模型不支持此类上传附件')
        if not args.execute:
            emit({'ok': True, 'execution_state': 'planned', 'uploaded': False, 'file': str(path), 'bytes': path.stat().st_size, 'max_bytes': maximum, 'model': args.model}, args.output)
        else:
            return dispatch({'command': 'upload', 'operation': 'request', 'action': 'upload', 'execute': True,
                             'upload': {'name': path.name, 'mime': mime, 'type': args.type.capitalize(), 'model': args.model, 'base64': base64.b64encode(path.read_bytes()).decode()}}, args)
    elif args.command == 'recover-original':
        emit(recover_original_result(args), args.output)
    elif args.command == 'download':
        media_url(args.url)
        if Path(args.name).name != args.name or args.name in {'.', '..'}:
            raise ValueError('下载文件名不得包含路径')
        if args.destination:
            if args.output and Path(args.output).expanduser().exists():
                raise ValueError('OUTPUT_ALREADY_EXISTS')
            if args.output and Path(args.output).expanduser().resolve() == Path(args.destination).expanduser().resolve():
                raise ValueError('DOWNLOAD_OUTPUT_PATH_CONFLICT')
            emit(download_to_destination(args.url, args.destination, args.expected_sha256), args.output)
            return 0
        if args.expected_sha256:
            raise ValueError('EXPECTED_SHA256_REQUIRES_DESTINATION')
        return dispatch({'command': 'download', 'operation': 'download', 'url': args.url, 'name': args.name}, args)
    elif args.command == 'inspect':
        emit(inspect_result(read_json(args.file)), args.output)
    elif args.command == 'verify-download':
        path = Path(args.file).expanduser().resolve()
        if not path.is_file() or path.stat().st_size == 0 or path.suffix in {'.crdownload', '.part'}:
            raise ValueError('文件未完整落盘')
        hasher = hashlib.sha256()
        with path.open('rb') as stream:
            head = stream.read(256)
            if b'<html' in head.lower() or b'<!doctype html' in head.lower():
                raise ValueError('下载实际是 HTML 页面，可能是登录页')
            hasher.update(head)
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        ffprobe = shutil.which('ffprobe')
        probe_data = None
        if ffprobe:
            probe = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
            if probe.returncode:
                raise ValueError('文件已落盘但 ffprobe 无法识别媒体；不标记下载验收通过')
            probe_data = json.loads(probe.stdout)
            if not probe_data.get('streams'):
                raise ValueError('文件不含可识别的媒体流')
        emit({'file': str(path), 'bytes': path.stat().st_size, 'sha256': hasher.hexdigest(), 'bytes_verified': True,
              'download_verified': probe_data is not None, 'media_metadata_verified': probe_data is not None,
              'media': probe_data, 'playback_verified': False, 'source_hash_matched': None, 'visual_acceptance': None}, args.output)
    elif args.command == 'refresh-models':
        return dispatch({'command': 'refresh-models', 'operation': 'models'}, args)
    else:
        for field in ['day_offset', 'day_size', 'page', 'page_size']:
            value = getattr(args, field, None)
            if value is not None and (value < (0 if field == 'day_offset' else 1) or value > 1000):
                raise ValueError(f'{field} 超出合理分页范围')
        return dispatch(read_spec(args), args)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'ok': False, 'error': str(error), 'automatic_retry': False}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
