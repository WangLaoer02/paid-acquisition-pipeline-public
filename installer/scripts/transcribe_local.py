#!/usr/bin/env python3
"""Portable faster-whisper adapter; explicit local model only, no downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('--model-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--language', default='zh')
    a = p.parse_args()
    if a.output.exists():
        raise SystemExit('输出已存在，保留原件')
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        if not (a.model_dir / name).is_file():
            raise SystemExit('本地模型缺少：' + name)
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SystemExit('缺少ffmpeg')
    import numpy as np
    from faster_whisper import WhisperModel
    proc = subprocess.run([ffmpeg, '-v', 'error', '-i', str(a.input), '-f', 'f32le', '-ac', '1', '-ar', '16000', '-'], capture_output=True, check=True)
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    model = WhisperModel(str(a.model_dir), device='cpu', compute_type='int8', local_files_only=True)
    segments, info = model.transcribe(audio, language=a.language, beam_size=1)
    result = {'source_sha256': hashlib.sha256(a.input.read_bytes()).hexdigest(),
              'model_bin_sha256': hashlib.sha256((a.model_dir / 'model.bin').read_bytes()).hexdigest(),
              'local_model_only': True, 'language': info.language,
              'segments': [{'start': s.start, 'end': s.end, 'text': s.text} for s in segments],
              'word_for_word_or_subjective_review_passed': False}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({'output': str(a.output), 'segments': len(result['segments'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
