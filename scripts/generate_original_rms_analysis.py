#!/usr/bin/env python3
"""Generate original-track RMS analysis JSON for APPA auto-gating."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIO_DIR = ROOT / "web" / "assets" / "audio" / "miuse-27m-33m"
DEFAULT_OUT = ROOT / "web" / "assets" / "analysis" / "miuse-27m-33m" / "original_rms.json"
TRACKS = [
    {"id": "track1", "name": "1 서장훈", "color": "#e8c15b"},
    {"id": "track2", "name": "2 박중훈", "color": "#57c1a7"},
    {"id": "track3", "name": "3 신동엽", "color": "#86a8e7"},
    {"id": "track4", "name": "4 희철맘", "color": "#e36b5d"},
]


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def decode_audio(path: Path, sample_rate: int) -> np.ndarray:
    command = [
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
    ]
    result = subprocess.run(command, check=True, capture_output=True)
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def rms_db(frame: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64) + 1e-12))
    return 20.0 * math.log10(max(rms, 1e-12))


def frame_rms_db(signal: np.ndarray, sample_rate: int, window_seconds: float, hop_seconds: float) -> tuple[list[float], list[float]]:
    window = max(1, int(round(window_seconds * sample_rate)))
    hop = max(1, int(round(hop_seconds * sample_rate)))
    if len(signal) < window:
        return [round(rms_db(signal), 2)], [0.0]

    values: list[float] = []
    starts: list[float] = []
    for start in range(0, len(signal) - window + 1, hop):
        frame = signal[start : start + window]
        values.append(round(rms_db(frame), 2))
        starts.append(round(start / sample_rate, 3))
    return values, starts


def summarize(values: list[float]) -> dict[str, float]:
    data = np.asarray(values, dtype=np.float64)
    return {
        "minDbfs": round(float(np.min(data)), 2),
        "p10Dbfs": round(float(np.percentile(data, 10)), 2),
        "p20Dbfs": round(float(np.percentile(data, 20)), 2),
        "p50Dbfs": round(float(np.percentile(data, 50)), 2),
        "p80Dbfs": round(float(np.percentile(data, 80)), 2),
        "p90Dbfs": round(float(np.percentile(data, 90)), 2),
        "maxDbfs": round(float(np.max(data)), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate APPA original-track RMS analysis.")
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sample-rate", type=int, default=8000)
    parser.add_argument("--window-seconds", type=float, default=0.2)
    parser.add_argument("--hop-seconds", type=float, default=0.1)
    args = parser.parse_args()

    audio_dir = resolve_path(args.audio_dir)
    out = resolve_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    common_starts: list[float] | None = None
    series: dict[str, dict[str, object]] = {}
    durations: list[float] = []

    for track in TRACKS:
        path = audio_dir / f"{track['id']}.mp3"
        print(f"Decoding {path.name}")
        signal = decode_audio(path, args.sample_rate)
        durations.append(len(signal) / args.sample_rate)
        values, starts = frame_rms_db(signal, args.sample_rate, args.window_seconds, args.hop_seconds)
        if common_starts is None:
            common_starts = starts

        series[track["id"]] = {
            "trackId": track["id"],
            "name": track["name"],
            "rmsDbfs": values,
            "summary": summarize(values),
        }
        print(f"  {track['id']}: {len(values)} frames, p20={series[track['id']]['summary']['p20Dbfs']} dBFS")

    starts = common_starts or []
    payload = {
        "version": 1,
        "kind": "original_track_rms",
        "tracks": TRACKS,
        "source": {
            "audioDir": str(audio_dir.relative_to(ROOT)),
            "duration": round(min(durations) if durations else 0.0, 3),
        },
        "settings": {
            "sampleRate": args.sample_rate,
            "windowSeconds": args.window_seconds,
            "hopSeconds": args.hop_seconds,
        },
        "duration": round(min(durations) if durations else 0.0, 3),
        "starts": starts,
        "times": [round(start + args.window_seconds / 2, 3) for start in starts],
        "series": series,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
