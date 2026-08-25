#!/usr/bin/env python3
"""Generate cross-channel correlation analysis JSON for APPA."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIO_DIR = ROOT / "web" / "assets" / "audio" / "miuse-27m-33m"
DEFAULT_OUT = ROOT / "web" / "assets" / "analysis" / "miuse-27m-33m" / "correlation.json"
TRACKS = [
    {"id": "track1", "name": "1 서장훈", "color": "#e8c15b"},
    {"id": "track2", "name": "2 박중훈", "color": "#57c1a7"},
    {"id": "track3", "name": "3 신동엽", "color": "#86a8e7"},
    {"id": "track4", "name": "4 희철맘", "color": "#e36b5d"},
]


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def decode_filtered_audio(path: Path, sample_rate: int, highpass_hz: int, lowpass_hz: int) -> np.ndarray:
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
        "-af",
        f"highpass=f={highpass_hz},lowpass=f={lowpass_hz}",
        "-f",
        "f32le",
        "pipe:1",
    ]
    result = subprocess.run(command, check=True, capture_output=True)
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def rms_db(frame: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64) + 1e-12))
    return 20.0 * math.log10(max(rms, 1e-12))


def best_lagged_correlation(ref: np.ndarray, target: np.ndarray, max_lag_samples: int) -> tuple[float | None, float | None, int | None]:
    ref = ref.astype(np.float32, copy=False) - float(np.mean(ref))
    target = target.astype(np.float32, copy=False) - float(np.mean(target))

    best_corr: float | None = None
    best_abs = -1.0
    best_lag = 0
    length = min(len(ref), len(target))

    for lag in range(-max_lag_samples, max_lag_samples + 1):
        if lag >= 0:
            ref_slice = ref[: length - lag] if lag else ref[:length]
            target_slice = target[lag:length] if lag else target[:length]
        else:
            offset = -lag
            ref_slice = ref[offset:length]
            target_slice = target[: length - offset]

        if len(ref_slice) < 2:
            continue

        denom = math.sqrt(float(np.dot(ref_slice, ref_slice)) * float(np.dot(target_slice, target_slice)))
        if denom <= 1e-9:
            continue

        corr = float(np.dot(ref_slice, target_slice) / denom)
        abs_corr = abs(corr)
        if abs_corr > best_abs:
            best_abs = abs_corr
            best_corr = corr
            best_lag = lag

    if best_corr is None:
        return None, None, None

    return abs(best_corr), best_corr, best_lag


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate APPA cross-channel correlation analysis.")
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sample-rate", type=int, default=8000)
    parser.add_argument("--highpass-hz", type=int, default=100)
    parser.add_argument("--lowpass-hz", type=int, default=3800)
    parser.add_argument("--window-seconds", type=float, default=1.0)
    parser.add_argument("--hop-seconds", type=float, default=0.5)
    parser.add_argument("--max-lag-ms", type=float, default=50.0)
    parser.add_argument("--valid-db-above-noise", type=float, default=8.0)
    parser.add_argument("--min-rms-db", type=float, default=-55.0)
    args = parser.parse_args()

    audio_dir = resolve_path(args.audio_dir)
    out = resolve_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    audio: dict[str, np.ndarray] = {}
    for track in TRACKS:
        path = audio_dir / f"{track['id']}.mp3"
        print(f"Decoding {path.name}")
        audio[track["id"]] = decode_filtered_audio(path, args.sample_rate, args.highpass_hz, args.lowpass_hz)

    min_samples = min(len(samples) for samples in audio.values())
    window_samples = int(args.window_seconds * args.sample_rate)
    hop_samples = int(args.hop_seconds * args.sample_rate)
    max_lag_samples = int(args.max_lag_ms * args.sample_rate / 1000.0)
    frame_count = 1 + max(0, (min_samples - window_samples) // hop_samples)
    duration = min_samples / args.sample_rate
    times = [round((index * hop_samples + window_samples / 2) / args.sample_rate, 3) for index in range(frame_count)]
    starts = [round(index * hop_samples / args.sample_rate, 3) for index in range(frame_count)]

    rms_by_track: dict[str, list[float]] = {track["id"]: [] for track in TRACKS}
    frames_by_track: dict[str, list[np.ndarray]] = {track["id"]: [] for track in TRACKS}

    print(f"Framing {frame_count} windows")
    for frame_index in range(frame_count):
        start = frame_index * hop_samples
        end = start + window_samples
        for track in TRACKS:
            track_id = track["id"]
            frame = audio[track_id][start:end]
            frames_by_track[track_id].append(frame)
            rms_by_track[track_id].append(round(rms_db(frame), 2))

    noise_floor = {
        track_id: round(float(np.percentile(values, 20)), 2)
        for track_id, values in rms_by_track.items()
    }
    valid_by_track = {
        track_id: [
            value >= max(noise_floor[track_id] + args.valid_db_above_noise, args.min_rms_db)
            for value in values
        ]
        for track_id, values in rms_by_track.items()
    }

    series: dict[str, dict[str, object]] = {}
    for ref in TRACKS:
        ref_id = ref["id"]
        print(f"Correlating reference {ref_id}")
        targets: dict[str, dict[str, list[float | None]]] = {}
        for target in TRACKS:
            target_id = target["id"]
            if target_id == ref_id:
                continue

            corr_values: list[float | None] = []
            signed_values: list[float | None] = []
            lag_values: list[float | None] = []

            for frame_index in range(frame_count):
                if not valid_by_track[ref_id][frame_index]:
                    corr_values.append(None)
                    signed_values.append(None)
                    lag_values.append(None)
                    continue

                corr, signed_corr, lag_samples = best_lagged_correlation(
                    frames_by_track[ref_id][frame_index],
                    frames_by_track[target_id][frame_index],
                    max_lag_samples,
                )
                corr_values.append(None if corr is None else round(corr, 3))
                signed_values.append(None if signed_corr is None else round(signed_corr, 3))
                lag_values.append(None if lag_samples is None else round(lag_samples / args.sample_rate * 1000.0, 1))

            targets[target_id] = {
                "corr": corr_values,
                "signedCorr": signed_values,
                "lagMs": lag_values,
            }

        series[ref_id] = {
            "rmsDb": rms_by_track[ref_id],
            "valid": valid_by_track[ref_id],
            "targets": targets,
        }

    payload = {
        "version": 1,
        "kind": "cross_channel_correlation",
        "tracks": TRACKS,
        "source": {
            "audioDir": str(audio_dir.relative_to(ROOT)),
            "duration": round(duration, 3),
        },
        "settings": {
            "sampleRate": args.sample_rate,
            "highpassHz": args.highpass_hz,
            "lowpassHz": args.lowpass_hz,
            "windowSeconds": args.window_seconds,
            "hopSeconds": args.hop_seconds,
            "maxLagMs": args.max_lag_ms,
            "validDbAboveNoise": args.valid_db_above_noise,
            "minRmsDb": args.min_rms_db,
        },
        "noiseFloorDb": noise_floor,
        "times": times,
        "starts": starts,
        "series": series,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
