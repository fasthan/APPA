#!/usr/bin/env python3
"""Shared ffmpeg-based audio decoding helpers: RMS activity streaming and
lightweight waveform envelopes, used by both the 미우새 asset pipeline
(`prepare_session_assets.py`) and the generic Pro Tools UI server
(`serve_ptsl_gate.py`).
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np


ACTIVITY_SAMPLE_RATE = 8000
ACTIVITY_WINDOW_SECONDS = 0.2
ACTIVITY_HOP_SECONDS = 0.1
INT16_MAX = 32768


def dbfs(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-12))


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def stream_rms_db(
    path: Path,
    sample_rate: int = ACTIVITY_SAMPLE_RATE,
    window_seconds: float = ACTIVITY_WINDOW_SECONDS,
    hop_seconds: float = ACTIVITY_HOP_SECONDS,
) -> tuple[list[float], list[float]]:
    """Decode `path` to mono PCM at `sample_rate` and compute a sliding-window
    RMS-in-dBFS series. Returns (rms_values, starts) where starts[i] is the
    start time in seconds of rms_values[i]'s window.
    """
    window_samples = max(1, int(round(window_seconds * sample_rate)))
    hop_samples = max(1, int(round(hop_seconds * sample_rate)))
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("ffmpeg stdout was not available")

    rms_values: list[float] = []
    starts: list[float] = []
    buffer = np.empty(0, dtype=np.float32)
    absolute_start = 0
    chunk_bytes = sample_rate * 20 * 4

    while True:
        chunk = process.stdout.read(chunk_bytes)
        if not chunk:
            break
        chunk_samples = np.frombuffer(chunk, dtype=np.float32)
        if chunk_samples.size == 0:
            continue
        buffer = np.concatenate((buffer, chunk_samples))
        offset = 0
        while offset + window_samples <= buffer.size:
            frame = buffer[offset : offset + window_samples]
            rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)) + 1e-12))
            rms_values.append(round(dbfs(rms), 2))
            starts.append(round((absolute_start + offset) / sample_rate, 3))
            offset += hop_samples
        if offset > 0:
            buffer = buffer[offset:]
            absolute_start += offset

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg failed for {path} with exit code {return_code}")
    return rms_values, starts


def stream_waveform_minmax(
    path: Path,
    sample_rate: int,
    window_seconds: float,
) -> tuple[list[float], list[float]]:
    """Decode `path` to mono PCM at `sample_rate` and compute per-window
    min/max envelope values (each in [-1, 1]) for lightweight waveform
    rendering. Returns (mins, maxs).
    """
    window_samples = max(1, int(sample_rate * window_seconds))
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("ffmpeg stdout was not available")

    mins: list[float] = []
    maxs: list[float] = []
    window_bytes = window_samples * 2
    while True:
        chunk = process.stdout.read(window_bytes)
        if not chunk:
            break
        samples = np.frombuffer(chunk, dtype=np.int16)
        if samples.size == 0:
            continue
        mins.append(round(max(-1.0, float(np.min(samples)) / INT16_MAX), 4))
        maxs.append(round(min(1.0, float(np.max(samples)) / INT16_MAX), 4))

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg failed for {path} with exit code {return_code}")
    return mins, maxs
