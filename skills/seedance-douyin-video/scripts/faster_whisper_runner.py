#!/usr/bin/env python3
"""Isolated, configured faster-whisper runtime. Local weights only; no downloads."""
import json
import sys
from pathlib import Path


def main():
    try:
        from faster_whisper import WhisperModel
        import importlib.metadata as metadata
    except ImportError:
        print(json.dumps({"error": "FASTER_WHISPER_IMPORT_FAILED"}))
        return 2
    try:
        phase = "arguments"
        audio, model_dir, output, language = sys.argv[1:]
        phase = "model_load"
        model = WhisperModel(model_dir, device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
        # FFmpeg already produced mono 16 kHz s16 WAV. Avoid PyAV API drift
        # (PyAV 19 removed metadata_errors used by faster-whisper 1.2.1).
        phase = "pcm_decode"
        import wave
        import numpy as np
        with wave.open(audio, "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise ValueError("Expected normalized PCM WAV")
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        phase = "inference"
        segments, info = model.transcribe(samples, language=language, beam_size=5,
                                          condition_on_previous_text=False, vad_filter=False)
        rows = [{"start": s.start, "end": s.end, "text": s.text,
                 "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob} for s in segments]
        result = {"text": "".join(s["text"] for s in rows).strip(), "segments": rows,
                  "duration": info.duration, "offline": True, "compute_type": "int8", "device": "cpu",
                  "parameters": {"beam_size": 5, "condition_on_previous_text": False, "vad_filter": False},
                  "versions": {k: metadata.version(k) for k in ("faster-whisper", "ctranslate2", "av")}}
        phase = "result_write"
        Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": "FASTER_WHISPER_EXECUTION_FAILED", "stage": phase, "exception_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
