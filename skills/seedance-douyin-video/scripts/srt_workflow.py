#!/usr/bin/env python3
"""Small deterministic SRT formatting helper for a local task directory.

The goal is to keep subtitle timecodes outside the model context window.
Use `remember` after extracting/choosing timecodes, then `make` when the user
says things like "use the previous timecodes" or "give me an SRT file".
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


STATE_DIR = Path.cwd() / ".srt-workflow"
STATE_PATH = STATE_DIR / "latest.json"
OUTBOUND_ROOT = Path.cwd() / "outputs" / "subtitles"


TIME_RE = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d")


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "-", name).strip(" .-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or "subtitle"


def parse_time(value: str) -> float:
    m = TIME_RE.search(value.strip())
    if not m:
        raise ValueError(f"bad SRT time: {value!r}")
    return (
        int(m.group("h")) * 3600
        + int(m.group("m")) * 60
        + int(m.group("s"))
        + int(m.group("ms")) / 1000
    )


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms >= 1000:
        whole += 1
        ms -= 1000
    h = whole // 3600
    m = (whole % 3600) // 60
    s = whole % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def read_text(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()


def split_copy(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if "-->" in line and TIME_RE.search(line):
            continue
        line = re.sub(r"[，,。；;]+$", "", line).strip()
        if line:
            lines.append(line)
    return lines


def parse_srt_timecodes(text: str) -> list[dict[str, float]]:
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: list[dict[str, float]] = []
    for block in blocks:
        for line in block.splitlines():
            if "-->" not in line:
                continue
            left, right = line.split("-->", 1)
            cues.append({"start": parse_time(left), "end": parse_time(right)})
            break
    return cues


def parse_timecodes_arg(value: str | None) -> list[dict[str, float]]:
    if not value:
        return []
    path = Path(value)
    raw = path.read_text(encoding="utf-8") if path.exists() else value
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        data = json.loads(raw)
        return [{"start": float(x["start"]), "end": float(x["end"])} for x in data]
    if "-->" in raw:
        return parse_srt_timecodes(raw)
    cues = []
    for part in re.split(r"[\n;]+", raw):
        part = part.strip()
        if not part:
            continue
        left, right = re.split(r"\s*[-~]\s*", part, maxsplit=1)
        cues.append({"start": float(left), "end": float(right)})
    return cues


def ffprobe_duration(video: str | None) -> float | None:
    if not video:
        return None
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video,
            ],
            text=True,
            timeout=8,
        ).strip()
        return float(out)
    except Exception:
        return None


def even_timecodes(duration: float, count: int) -> list[dict[str, float]]:
    if count <= 0:
        return []
    step = float(duration) / count
    cues = []
    for i in range(count):
        start = i * step
        end = duration if i == count - 1 else (i + 1) * step
        cues.append({"start": round(start, 3), "end": round(end, 3)})
    return cues


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def grouped_text(lines: list[str], cue_count: int) -> list[str]:
    if cue_count <= 0:
        return []
    if len(lines) == cue_count:
        return lines
    groups: list[str] = []
    for i in range(cue_count):
        start = round(i * len(lines) / cue_count)
        end = round((i + 1) * len(lines) / cue_count)
        chunk = lines[start:end] or ([lines[min(i, len(lines) - 1)]] if lines else [""])
        groups.append("，".join(chunk))
    return groups


def render_srt(cues: list[dict[str, float]], texts: list[str]) -> str:
    blocks = []
    for idx, (cue, text) in enumerate(zip(cues, texts), start=1):
        blocks.append(
            f"{idx}\n{fmt_time(cue['start'])} --> {fmt_time(cue['end'])}\n{text}"
        )
    return "\n\n".join(blocks) + "\n"


def cmd_remember(args: argparse.Namespace) -> int:
    cues = parse_timecodes_arg(args.timecodes)
    source_srt_text = read_text(args.source_srt) if args.source_srt else ""
    if source_srt_text:
        cues = parse_srt_timecodes(source_srt_text)
    duration = args.duration or ffprobe_duration(args.video)
    if not cues and duration and args.count:
        cues = even_timecodes(duration, args.count)
    if not cues:
        print("ERROR: no timecodes. Provide --source-srt, --timecodes, or --duration with --count.", file=sys.stderr)
        return 2
    state = {
        "updated_at": now_iso(),
        "title": args.title or "latest",
        "source_video": args.video,
        "duration": duration,
        "timecodes": cues,
        "notes": args.notes,
    }
    save_state(state)
    print(json.dumps({"ok": True, "state": str(STATE_PATH), "segments": len(cues)}, ensure_ascii=False))
    return 0


def cmd_make(args: argparse.Namespace) -> int:
    text = read_text(args.text)
    lines = split_copy(text)
    if not lines:
        print("ERROR: no subtitle text found", file=sys.stderr)
        return 2

    state = load_state() if args.use_state else {}
    cues = parse_timecodes_arg(args.timecodes)
    if args.source_srt:
        cues = parse_srt_timecodes(read_text(args.source_srt))

    duration = args.duration or ffprobe_duration(args.video)
    if not cues and args.use_state:
        cues = state.get("timecodes") or []
        duration = duration or state.get("duration")

    if args.force_even or not cues:
        duration = duration or args.duration
        if not duration:
            print("ERROR: no timecodes or duration. Provide --duration/--video, --source-srt, --timecodes, or use remembered state.", file=sys.stderr)
            return 2
        cues = even_timecodes(float(duration), len(lines))
    elif len(cues) != len(lines):
        lines = grouped_text(lines, len(cues))

    out_dir = Path(args.out_dir) if args.out_dir else OUTBOUND_ROOT / today()
    out_dir.mkdir(parents=True, exist_ok=True)
    title = sanitize_filename(args.title or state.get("title") or "subtitle")
    if not title.endswith("-srt"):
        title = f"{title}-srt"
    out_path = out_dir / f"{title}.srt"
    content = render_srt(cues, lines)
    out_path.write_text(content, encoding="utf-8")

    save_state(
        {
            "updated_at": now_iso(),
            "title": args.title or state.get("title") or "latest",
            "source_video": args.video or state.get("source_video"),
            "duration": duration,
            "timecodes": cues,
            "last_srt": str(out_path),
            "last_line_count": len(lines),
        }
    )
    result = {
        "ok": True,
        "path": str(out_path),
        "segments": len(cues),
        "duration": duration,
        "state": str(STATE_PATH),
        "delivery_rule": "Return a local file link or attachment in the current conversation; external delivery requires explicit authorization.",
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Remember timecodes and generate SRT files in the current task directory.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    remember = sub.add_parser("remember", help="Persist the latest SRT timecodes for follow-up requests.")
    remember.add_argument("--title")
    remember.add_argument("--video")
    remember.add_argument("--duration", type=float)
    remember.add_argument("--count", type=int)
    remember.add_argument("--timecodes", help="JSON/list/file, SRT text/file, or lines like 0-4")
    remember.add_argument("--source-srt", help="Existing SRT file; stdin when omitted is not used for remember.")
    remember.add_argument("--notes")
    remember.set_defaults(func=cmd_remember)

    make = sub.add_parser("make", help="Generate a local SRT from text and explicit or deliberately reused timecodes.")
    make.add_argument("--text", help="Text file. If omitted, reads stdin.")
    make.add_argument("--title")
    make.add_argument("--video")
    make.add_argument("--duration", type=float)
    make.add_argument("--timecodes")
    make.add_argument("--source-srt")
    make.add_argument("--out-dir")
    make.add_argument("--use-state", dest="use_state", action="store_true", default=False, help="Reuse timecodes only after confirming they belong to this task.")
    make.add_argument("--no-state", dest="use_state", action="store_false", help="Do not reuse saved timecodes (the default).")
    make.add_argument("--force-even", action="store_true", help="Ignore remembered timecodes and split duration evenly.")
    make.set_defaults(func=cmd_make)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
