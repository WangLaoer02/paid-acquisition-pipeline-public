#!/usr/bin/env python3
"""Bounded ASR: configured worker -> whisper.cpp -> configured faster-whisper -> Whisper.
No install, model download, listening review or continuous-video perception.
"""
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SLOW_MODELS = {"small", "medium", "large", "large-v1", "large-v2", "large-v3", "turbo"}


class ASRError(RuntimeError):
    def __init__(self, code, attempts=None):
        super().__init__(code)
        self.code, self.attempts = code, attempts or []


def run(cmd, timeout=600):
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def normalize_model(model):
    if os.getenv("ALLOW_SLOW_WHISPER") == "1":
        return model
    return "tiny" if model in SLOW_MODELS else model


def settings():
    path = Path(os.environ.get("DOUYIN_TOOLS_CONFIG", str(Path.home() / ".config/seedance-douyin-video/config.json"))).expanduser()
    if not path.exists():
        if "DOUYIN_TOOLS_CONFIG" in os.environ:
            raise ASRError("DOUYIN_CONFIG_MISSING")
        return {}
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise ASRError("DOUYIN_CONFIG_INVALID") from None


def configured(env, key, default=None):
    return os.environ[env] if env in os.environ else settings().get(key, default)


def executable(value):
    if not isinstance(value, str) or not value:
        return None
    return shutil.which(os.path.expanduser(value))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def extract_audio(input_path, work_dir):
    # Normalize audio inputs too: downloader may hand us MP3, not WAV.
    ffmpeg = executable(configured("FFMPEG_BIN", "ffmpeg_bin", "ffmpeg"))
    if not ffmpeg:
        raise ASRError("FFMPEG_MISSING")
    audio_path = work_dir / "audio.wav"
    try:
        result = run([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(input_path),
                      "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)], timeout=180)
    except subprocess.TimeoutExpired:
        raise ASRError("AUDIO_EXTRACTION_TIMEOUT") from None
    if result.returncode:
        code = "AUDIO_STREAM_MISSING" if "matches no streams" in result.stderr else "AUDIO_DECODE_FAILED"
        raise ASRError(code)
    return audio_path


def worker_urls():
    value = configured("LOCAL_TRANSCRIBE_URL", "transcribe_urls", [])
    if "LOCAL_TRANSCRIBE_URL" in os.environ:
        value = [value] if value else []
    if not isinstance(value, list) or not all(isinstance(u, str) and u.startswith(("http://", "https://")) for u in value):
        raise ASRError("DOUYIN_CONFIG_INVALID")
    return value


def note(attempts, backend, status, **extra):
    attempts.append(dict(backend=backend, status=status, **extra))


def try_worker(audio_path, language, attempts=None):
    attempts = attempts if attempts is not None else []
    urls = worker_urls()
    if not urls:
        note(attempts, "worker", "not_configured")
        return None
    body = audio_path.read_bytes()
    for index, url in enumerate(urls):
        try:
            request = urllib.request.Request(url, data=body, headers={
                "content-type": "audio/wav", "x-audio-filename": audio_path.name,
                "x-audio-language": language}, method="POST")
            with urllib.request.urlopen(request, timeout=int(os.getenv("TRANSCRIBE_WORKER_TIMEOUT_SECONDS", "15"))) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("ok") is False:
                note(attempts, "worker", "invalid_response", index=index)
                continue
            text = payload.get("text") or payload.get("transcript")
            if not isinstance(text, str) or not text.strip():
                note(attempts, "worker", "empty_or_invalid_transcript", index=index)
                continue
            note(attempts, "worker", "ok", index=index)
            # Do not echo arbitrary worker URLs, error bodies or untrusted metadata.
            return {"text": text.strip(), "backend": "local-worker", "model": "unverified-worker-model", "segments": []}
        except urllib.error.HTTPError as e:
            note(attempts, "worker", "permission_denied" if e.code in (401, 403) else "http_error", index=index, http_status=e.code)
        except (TimeoutError, socket.timeout):
            note(attempts, "worker", "timeout", index=index)
        except urllib.error.URLError as e:
            reason = e.reason
            status = "service_offline" if isinstance(reason, ConnectionRefusedError) else "timeout" if isinstance(reason, TimeoutError) else "network_error"
            note(attempts, "worker", status, index=index)
        except (OSError, ValueError, TypeError):
            note(attempts, "worker", "invalid_response_or_io_error", index=index)
    return None


def cpp_paths():
    binary = executable(configured("WHISPER_CPP_BIN", "whisper_cpp_bin", "whisper-cli"))
    model = Path(configured("WHISPER_CPP_MODEL", "whisper_cpp_model", str(Path.home() / ".cache/whisper.cpp/ggml-tiny.bin"))).expanduser()
    return binary, model


def try_whisper_cpp(audio_path, language, work_dir, attempts=None):
    attempts = attempts if attempts is not None else []
    binary, model = cpp_paths()
    if not binary or not model.is_file():
        note(attempts, "whisper.cpp", "dependency_missing", binary_available=bool(binary), model_available=model.is_file())
        return None
    base = work_dir / "whisper_cpp"
    try:
        result = run([binary, "-m", str(model), "-f", str(audio_path), "-l", language, "-t",
                      os.getenv("WHISPER_CPP_THREADS") or os.getenv("WHISPER_THREADS") or "4",
                      "-otxt", "-of", str(base), "-np", "-nt"], timeout=int(os.getenv("WHISPER_TIMEOUT_SECONDS", "600")))
        text_path = Path(str(base) + ".txt")
        if result.returncode == 0 and text_path.is_file() and text_path.read_text().strip():
            note(attempts, "whisper.cpp", "ok")
            return {"text": text_path.read_text().strip(), "backend": "whisper.cpp", "model": model.name,
                    "model_sha256": digest(model), "segments": []}
        note(attempts, "whisper.cpp", "execution_failed", returncode=result.returncode)
    except subprocess.TimeoutExpired:
        note(attempts, "whisper.cpp", "timeout")
    except OSError:
        note(attempts, "whisper.cpp", "execution_unavailable")
    if os.getenv("WHISPER_BACKEND") == "cpp":
        raise ASRError("WHISPER_CPP_FAILED", attempts)
    return None


def faster_paths(model):
    binary = executable(configured("FASTER_WHISPER_PYTHON", "faster_whisper_python"))
    models = settings().get("faster_whisper_models", {})
    if not isinstance(models, dict):
        raise ASRError("DOUYIN_CONFIG_INVALID")
    value = os.environ.get("FASTER_WHISPER_MODEL_DIR") or models.get(model)
    path = Path(value).expanduser() if isinstance(value, str) and value else None
    return binary, path


def faster_ready(path):
    return bool(path and all((path / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")))


def try_faster_whisper(audio_path, language, model, work_dir, attempts):
    binary, model_dir = faster_paths(model)
    if not binary or not faster_ready(model_dir):
        note(attempts, "faster-whisper", "dependency_missing", python_available=bool(binary), model_available=faster_ready(model_dir))
        return None
    output = work_dir / "faster.json"
    try:
        result = run([binary, str(Path(__file__).with_name("faster_whisper_runner.py")), str(audio_path), str(model_dir),
                      str(output), language], timeout=int(os.getenv("WHISPER_TIMEOUT_SECONDS", "600")))
        if result.returncode or not output.is_file():
            status = "execution_failed"
            detail = {}
            try:
                failure = json.loads(result.stdout)
                error = failure.get("error")
                if failure.get("stage") in ("arguments", "model_load", "pcm_decode", "inference", "result_write"):
                    detail["stage"] = failure["stage"]
                if failure.get("exception_type") in ("TypeError", "ValueError", "RuntimeError", "OSError", "PermissionError", "FileNotFoundError", "MemoryError"):
                    detail["exception_type"] = failure["exception_type"]
                if error in ("FASTER_WHISPER_IMPORT_FAILED", "FASTER_WHISPER_EXECUTION_FAILED"):
                    status = error
            except (ValueError, AttributeError):
                pass
            note(attempts, "faster-whisper", status, returncode=result.returncode, **detail)
            return None
        payload = json.loads(output.read_text())
        if not isinstance(payload.get("text"), str) or not payload["text"].strip():
            note(attempts, "faster-whisper", "empty_transcript")
            return None
        note(attempts, "faster-whisper", "ok")
        payload.update(backend="faster-whisper", model=model, model_path=str(model_dir), model_sha256=digest(model_dir / "model.bin"))
        return payload
    except subprocess.TimeoutExpired:
        note(attempts, "faster-whisper", "timeout")
    except (OSError, ValueError, TypeError):
        note(attempts, "faster-whisper", "invalid_response_or_io_error")
    return None


def transcribe_with_python_whisper(audio_path, language, model, work_dir, attempts=None):
    attempts = attempts if attempts is not None else []
    binary = executable(configured("WHISPER_BIN", "whisper_bin", "whisper"))
    # A path, not a model name, prevents Whisper's implicit network download.
    cache = Path(configured("WHISPER_MODEL_DIR", "whisper_model_dir", str(Path.home() / ".cache/whisper"))).expanduser()
    weights = cache / (model + ".pt")
    if not binary or not weights.is_file():
        note(attempts, "python-whisper", "dependency_missing", binary_available=bool(binary), model_available=weights.is_file())
        raise ASRError("ASR_UNAVAILABLE", attempts)
    dest = work_dir / "whisper"
    dest.mkdir(exist_ok=True)
    try:
        result = run([binary, str(audio_path), "--model", str(weights), "--language", language, "--task", "transcribe",
                      "--output_format", "json", "--output_dir", str(dest), "--fp16", "False", "--verbose", "False"],
                     timeout=int(os.getenv("WHISPER_TIMEOUT_SECONDS", "600")))
        output = dest / (audio_path.stem + ".json")
        if result.returncode == 0 and output.exists():
            payload = json.loads(output.read_text())
            if isinstance(payload.get("text"), str) and payload["text"].strip():
                note(attempts, "python-whisper", "ok")
                return {"text": payload["text"], "segments": payload.get("segments", []), "backend": "python-whisper",
                        "model": model, "model_sha256": digest(weights)}
        note(attempts, "python-whisper", "execution_failed", returncode=result.returncode)
    except subprocess.TimeoutExpired:
        note(attempts, "python-whisper", "timeout")
    except (OSError, ValueError):
        note(attempts, "python-whisper", "invalid_response_or_io_error")
    raise ASRError("ASR_UNAVAILABLE", attempts)


def transcribe_audio(audio_path, language, model, work_dir):
    # Public import used by douyin_downloader; keep the four-argument interface.
    attempts = []
    model = normalize_model(model)
    audio_path = extract_audio(Path(audio_path), Path(work_dir)) if Path(audio_path) != Path(work_dir) / "audio.wav" else Path(audio_path)
    result = try_worker(audio_path, language, attempts)
    if result is None:
        result = try_whisper_cpp(audio_path, language, work_dir, attempts)
    if result is None:
        result = try_faster_whisper(audio_path, language, model, work_dir, attempts)
    if result is None:
        result = transcribe_with_python_whisper(audio_path, language, model, work_dir, attempts)
    result.update(attempts=attempts, evidence_type="machine_asr", listening_review=False, continuous_video_review=False)
    return result


def diagnose(model="tiny", probe_workers=False):
    urls = worker_urls()
    binary, cpp_model = cpp_paths()
    python, faster_model = faster_paths(normalize_model(model))
    data = {"ok": True, "mode": "dependency_diagnostic_not_acceptance", "media_uploaded": False,
            "ffmpeg_available": bool(executable(configured("FFMPEG_BIN", "ffmpeg_bin", "ffmpeg"))),
            "workers": [], "whisper_cpp": {"binary_available": bool(binary), "model_available": cpp_model.is_file()},
            "faster_whisper": {"python": python, "model_directory": str(faster_model) if faster_model else None,
                               "model_available": faster_ready(faster_model), "runtime": "not_probed"},
            "python_whisper": {"binary_available": bool(executable(configured("WHISPER_BIN", "whisper_bin", "whisper"))),
                               "model_available": (Path(configured("WHISPER_MODEL_DIR", "whisper_model_dir", str(Path.home()/".cache/whisper"))).expanduser() / (normalize_model(model)+".pt")).is_file()}}
    for index, url in enumerate(urls):
        u = urllib.parse.urlsplit(url)
        local = u.hostname in ("localhost", "127.0.0.1", "::1")
        item = {"index": index, "loopback": local, "status": "not_probed"}
        if probe_workers and local:
            try:
                with socket.create_connection((u.hostname, u.port or (443 if u.scheme=="https" else 80)), timeout=2):
                    pass
                item["status"] = "tcp_reachable_not_asr_verified"
            except ConnectionRefusedError:
                item["status"] = "service_offline"
            except TimeoutError:
                item["status"] = "timeout"
            except OSError:
                item["status"] = "network_error"
        data["workers"].append(item)
    if python:
        try:
            p = run([python, "-c", "import faster_whisper,ctranslate2; print(faster_whisper.__version__)"], timeout=20)
            data["faster_whisper"]["runtime"] = "import_ok" if p.returncode == 0 else "import_failed"
            if p.returncode == 0:
                data["faster_whisper"]["version"] = p.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            data["faster_whisper"]["runtime"] = "unavailable_or_timeout"
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="Local audio or video file")
    parser.add_argument("--out")
    parser.add_argument("--output-dir")
    parser.add_argument("--language", default=os.getenv("DOUYIN_WHISPER_LANGUAGE", "zh"))
    parser.add_argument("--model", default=os.getenv("DOUYIN_WHISPER_MODEL", "tiny"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--diagnose", action="store_true", help="Dependency status, no media POST or model download")
    parser.add_argument("--probe-workers", action="store_true", help="Diagnostic only: TCP probe configured loopback endpoints")
    parser.add_argument("--evidence", help="Write ASR text, timestamps, source/model SHA and attempts as JSON")
    args = parser.parse_args()
    try:
        if args.diagnose:
            print(json.dumps(diagnose(args.model, args.probe_workers), ensure_ascii=False, indent=2))
            return
        if not args.input:
            parser.error("input is required unless --diagnose")
        path = Path(args.input).expanduser().resolve()
        if not path.is_file():
            raise ASRError("INPUT_FILE_MISSING")
        dest = Path(args.output_dir).expanduser().resolve() if args.output_dir else path.parent
        output = Path(args.out).expanduser().resolve() if args.out else dest / (path.stem + ".txt")
        # Refuse overwriting source via an output path or hard/symbolic link.
        evidence = Path(args.evidence).expanduser().resolve() if args.evidence else None
        for target in [output, evidence]:
            if target and (target == path or target.exists() and target.samefile(path)):
                raise ASRError("OUTPUT_EQUALS_INPUT")
        if evidence and (evidence == output or evidence.exists() and output.exists() and evidence.samefile(output)):
            raise ASRError("EVIDENCE_EQUALS_TRANSCRIPT")
        source_sha = digest(path)
        with tempfile.TemporaryDirectory(prefix="fast-transcribe-") as tmp:
            work = Path(tmp)
            audio = extract_audio(path, work)
            import wave
            with wave.open(str(audio)) as wav:
                duration = wav.getnframes() / wav.getframerate()
            result = transcribe_audio(audio, args.language, args.model, work)
            result.update(audio_sha256=digest(audio), source_range_seconds=[0, duration])
        if digest(path) != source_sha:
            raise ASRError("SOURCE_CHANGED_DURING_ASR")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result["text"].strip() + "\n")
        payload = dict(result, ok=True, input=str(path), source_sha256=source_sha, output=str(output),
                       chars=len(result["text"]), language=args.language, requested_model=args.model,
                       normalized_model=normalize_model(args.model), timestamps="ASR estimates; relative to source start, not reviewed")
        if evidence:
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n")
        if args.json:
            print(json.dumps({k:v for k,v in payload.items() if k not in ("text", "segments")}, ensure_ascii=False, indent=2))
        else:
            print(output)
            print("backend=" + result["backend"] + " evidence=machine_asr; not listening review", file=sys.stderr)
    except ASRError as e:
        print(json.dumps({"ok": False, "error": e.code, "attempts": e.attempts}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except (OSError, ValueError, TypeError):
        # Never print raw URL/config/child stderr, which may carry credentials.
        print(json.dumps({"ok": False, "error": "ASR_CONFIG_OR_IO_ERROR"}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
