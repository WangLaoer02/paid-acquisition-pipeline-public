#!/usr/bin/env python3
"""Fast audio probe for local video/audio BGM and sound-effect tasks.

This script intentionally avoids online recognition and heavy model installs.
It extracts a mono WAV, produces waveform/spectrum previews, detects loud
short events, and exports small clips around likely sound effects.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import wave
from pathlib import Path


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def require_bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"missing required binary: {name}")
    return path


def ffprobe_duration(path: Path) -> float:
    ffprobe = require_bin("ffprobe")
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return float((result.stdout or "0").strip() or 0)


def extract_audio(input_path: Path, out_dir: Path) -> Path:
    ffmpeg = require_bin("ffmpeg")
    audio_path = out_dir / "audio_16k_mono.wav"
    result = run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(audio_path),
        ],
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg audio extraction failed")
    return audio_path


def read_wav_samples(path: Path) -> tuple[int, list[int]]:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise RuntimeError("expected 16-bit mono WAV")
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    samples = [int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw), 2)]
    return rate, samples


def rms_windows(samples: list[int], rate: int, window_sec: float) -> list[dict[str, float]]:
    size = max(1, int(rate * window_sec))
    rows: list[dict[str, float]] = []
    for start in range(0, len(samples), size):
        chunk = samples[start : start + size]
        if not chunk:
            continue
        rms = math.sqrt(sum(x * x for x in chunk) / len(chunk)) / 32768.0
        peak = max(abs(x) for x in chunk) / 32768.0
        rows.append({"start": start / rate, "end": (start + len(chunk)) / rate, "rms": rms, "peak": peak})
    return rows


def find_events(rows: list[dict[str, float]], max_events: int) -> list[dict[str, float]]:
    if not rows:
        return []
    values = sorted(row["rms"] for row in rows)
    median = values[len(values) // 2]
    threshold = max(median * 2.4, 0.035)
    candidates = [row for row in rows if row["rms"] >= threshold or row["peak"] >= max(0.22, threshold * 3.0)]
    candidates.sort(key=lambda row: (row["peak"], row["rms"]), reverse=True)

    selected: list[dict[str, float]] = []
    for row in candidates:
        center = (row["start"] + row["end"]) / 2
        if any(abs(center - ((old["start"] + old["end"]) / 2)) < 1.0 for old in selected):
            continue
        selected.append(row)
        if len(selected) >= max_events:
            break
    return sorted(selected, key=lambda row: row["start"])


def export_clip(audio_path: Path, out_path: Path, start: float, duration: float) -> None:
    ffmpeg = require_bin("ffmpeg")
    result = run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0, start):.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(audio_path),
            "-c:a",
            "pcm_s16le",
            str(out_path),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to export {out_path.name}")


def export_previews(audio_path: Path, out_dir: Path) -> dict[str, str]:
    ffmpeg = require_bin("ffmpeg")
    previews: dict[str, str] = {}
    waveform = out_dir / "waveform.png"
    spectrum = out_dir / "spectrum.png"
    commands = [
        (waveform, ["-filter_complex", "showwavespic=s=1600x360:colors=#2B8CFF", "-frames:v", "1"]),
        (spectrum, ["-lavfi", "showspectrumpic=s=1600x540:legend=disabled", "-frames:v", "1"]),
    ]
    for path, args in commands:
        result = run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(audio_path), *args, str(path)],
            timeout=60,
        )
        if result.returncode == 0 and path.exists():
            previews[path.stem] = str(path)
    return previews


def write_csv(rows: list[dict[str, float]], out_path: Path) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["start", "end", "rms", "peak"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast local audio probe for BGM/effect extraction")
    parser.add_argument("input", help="Local audio or video file")
    parser.add_argument("--out-dir", default="", help="Output directory")
    parser.add_argument("--window-sec", type=float, default=0.25, help="Analysis window size")
    parser.add_argument("--max-events", type=int, default=8, help="Max candidate sound-effect clips")
    parser.add_argument("--clip-pad", type=float, default=0.6, help="Seconds before/after each event")
    parser.add_argument("--json", action="store_true", help="Print JSON summary only")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"file not found: {input_path}")

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else input_path.parent / f"{input_path.stem}-audio-probe"
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = ffprobe_duration(input_path)
    audio_path = extract_audio(input_path, out_dir)
    rate, samples = read_wav_samples(audio_path)
    rows = rms_windows(samples, rate, args.window_sec)
    events = find_events(rows, args.max_events)
    write_csv(rows, out_dir / "energy_windows.csv")
    previews = export_previews(audio_path, out_dir)

    clips = []
    for index, event in enumerate(events, start=1):
        center = (event["start"] + event["end"]) / 2
        clip_start = max(0, center - args.clip_pad)
        clip_duration = min(duration - clip_start, args.clip_pad * 2)
        clip_path = out_dir / f"event_{index:02d}_{clip_start:.2f}s.wav"
        export_clip(audio_path, clip_path, clip_start, clip_duration)
        clips.append({**event, "clip": str(clip_path)})

    payload = {
        "ok": True,
        "input": str(input_path),
        "out_dir": str(out_dir),
        "duration_sec": duration,
        "audio": str(audio_path),
        "previews": previews,
        "events": clips,
        "notes": [
            "This is deterministic local audio analysis, not song-name recognition.",
            "Use Douyin metadata for Douyin links; use external recognition only outside the live queue.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"out_dir={out_dir}")
        print(f"duration_sec={duration:.2f}")
        print(f"events={len(clips)}")
        for clip in clips:
            print(f"{clip['start']:.2f}-{clip['end']:.2f}s peak={clip['peak']:.3f} clip={clip['clip']}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as exc:
        print(f"timeout: {' '.join(exc.cmd) if isinstance(exc.cmd, list) else exc.cmd}", file=sys.stderr)
        sys.exit(124)
