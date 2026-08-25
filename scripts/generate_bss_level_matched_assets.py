#!/usr/bin/env python3
"""Create active-RMS level matched BSS assets for the browser UI."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
TRACK_LABELS = ["1 서장훈", "2 박중훈", "3 신동엽", "4 희철맘"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", type=Path, default=Path("web/assets/audio/miuse-27m-33m"))
    parser.add_argument("--bss-root", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss"))
    parser.add_argument("--out-root", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss/active-rms"))
    parser.add_argument("--report", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss/report.json"))
    parser.add_argument("--sample-rate", type=int, default=8000)
    parser.add_argument("--window-seconds", type=float, default=0.4)
    parser.add_argument("--hop-seconds", type=float, default=0.1)
    parser.add_argument("--active-percentile", type=float, default=80.0)
    parser.add_argument("--max-gain-db", type=float, default=24.0)
    parser.add_argument("--peak-headroom-dbfs", type=float, default=-1.0)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def decode_original(path: Path, sample_rate: int) -> np.ndarray:
    raw = subprocess.check_output(
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
            "-af",
            "highpass=f=80,lowpass=f=3800",
            "-f",
            "f32le",
            "pipe:1",
        ]
    )
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def db(value: float) -> float:
    return 20 * math.log10(max(float(value), 1e-12))


def gain_from_db(gain_db: float) -> float:
    return 10 ** (gain_db / 20)


def active_rms(signal: np.ndarray, sample_rate: int, window_seconds: float, hop_seconds: float, percentile: float) -> float:
    window = max(1, int(round(window_seconds * sample_rate)))
    hop = max(1, int(round(hop_seconds * sample_rate)))
    if len(signal) < window:
        return float(np.sqrt(np.mean(signal * signal) + 1e-12))

    values = []
    for start in range(0, len(signal) - window + 1, hop):
        frame = signal[start : start + window]
        values.append(float(np.sqrt(np.mean(frame * frame) + 1e-12)))

    return float(np.percentile(np.asarray(values), percentile))


def load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    audio_dir = resolve_path(args.audio_dir)
    bss_root = resolve_path(args.bss_root)
    out_root = resolve_path(args.out_root)
    report = load_report(resolve_path(args.report))
    out_root.mkdir(parents=True, exist_ok=True)

    original_tracks = [
        decode_original(audio_dir / f"track{index}.mp3", sample_rate=args.sample_rate)
        for index in range(1, 5)
    ]
    original_active = [
        active_rms(track, args.sample_rate, args.window_seconds, args.hop_seconds, args.active_percentile)
        for track in original_tracks
    ]

    peak_ceiling = gain_from_db(args.peak_headroom_dbfs)
    manifest = {
        "version": 1,
        "kind": "bss_active_rms_level_match",
        "settings": {
            "sampleRate": args.sample_rate,
            "windowSeconds": args.window_seconds,
            "hopSeconds": args.hop_seconds,
            "activePercentile": args.active_percentile,
            "maxGainDb": args.max_gain_db,
            "peakHeadroomDbfs": args.peak_headroom_dbfs,
        },
        "original": {
            "tracks": [
                {
                    "track": index,
                    "label": TRACK_LABELS[index - 1],
                    "activeRmsDbfs": db(value),
                }
                for index, value in enumerate(original_active, start=1)
            ]
        },
        "algorithms": {},
    }

    for algorithm in report["algorithms"]:
        algorithm_id = algorithm["name"]
        source_root = bss_root / algorithm_id
        algorithm_out = out_root / algorithm_id
        algorithm_out.mkdir(parents=True, exist_ok=True)
        sources = []

        for mapping in algorithm["mapping"]:
            source_index = int(mapping["source"])
            target_track = int(mapping["best_input"])
            target_active = original_active[target_track - 1]
            source_path = source_root / f"source{source_index}.wav"
            signal, sample_rate = sf.read(source_path, dtype="float64")
            if sample_rate != args.sample_rate:
                raise RuntimeError(f"Unexpected sample rate for {source_path}: {sample_rate}")
            if signal.ndim > 1:
                signal = np.mean(signal, axis=1)

            source_active = active_rms(
                signal,
                args.sample_rate,
                args.window_seconds,
                args.hop_seconds,
                args.active_percentile,
            )
            desired_gain_db = db(target_active) - db(source_active)
            desired_gain_db = min(desired_gain_db, args.max_gain_db)
            desired_gain = gain_from_db(desired_gain_db)

            peak = float(np.max(np.abs(signal)))
            peak_limited_gain = desired_gain
            peak_limited = False
            if peak * desired_gain > peak_ceiling:
                peak_limited_gain = peak_ceiling / max(peak, 1e-12)
                peak_limited = True

            adjusted = signal * peak_limited_gain
            adjusted_active = active_rms(
                adjusted,
                args.sample_rate,
                args.window_seconds,
                args.hop_seconds,
                args.active_percentile,
            )
            adjusted_peak = float(np.max(np.abs(adjusted)))
            sf.write(algorithm_out / f"source{source_index}.wav", adjusted, args.sample_rate)

            sources.append(
                {
                    "source": source_index,
                    "targetTrack": target_track,
                    "targetLabel": TRACK_LABELS[target_track - 1],
                    "sourceActiveRmsDbfs": db(source_active),
                    "targetActiveRmsDbfs": db(target_active),
                    "adjustedActiveRmsDbfs": db(adjusted_active),
                    "sourcePeakDbfs": db(peak),
                    "adjustedPeakDbfs": db(adjusted_peak),
                    "desiredGainDb": desired_gain_db,
                    "appliedGainDb": db(peak_limited_gain),
                    "peakLimited": peak_limited,
                }
            )

        manifest["algorithms"][algorithm_id] = {"sources": sources}

    (bss_root / "level_match.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {bss_root / 'level_match.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
