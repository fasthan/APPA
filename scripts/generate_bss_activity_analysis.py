#!/usr/bin/env python3
"""Generate source activity scores for auto-gating original APPA tracks."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bss-root", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss"))
    parser.add_argument("--report", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss/report.json"))
    parser.add_argument("--out", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss/activity.json"))
    parser.add_argument("--window-seconds", type=float, default=0.2)
    parser.add_argument("--hop-seconds", type=float, default=0.1)
    parser.add_argument("--noise-percentile", type=float, default=20.0)
    parser.add_argument("--active-percentile", type=float, default=95.0)
    parser.add_argument("--min-dynamic-range-db", type=float, default=12.0)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def db(value: float) -> float:
    return 20 * math.log10(max(float(value), 1e-12))


def frame_rms(signal: np.ndarray, sample_rate: int, window_seconds: float, hop_seconds: float) -> tuple[list[float], list[float]]:
    window = max(1, int(round(window_seconds * sample_rate)))
    hop = max(1, int(round(hop_seconds * sample_rate)))
    if len(signal) < window:
      rms = float(np.sqrt(np.mean(signal * signal) + 1e-12))
      return [rms], [0.0]

    rms_values: list[float] = []
    starts: list[float] = []
    for start in range(0, len(signal) - window + 1, hop):
        frame = signal[start : start + window]
        rms_values.append(float(np.sqrt(np.mean(frame * frame) + 1e-12)))
        starts.append(start / sample_rate)
    return rms_values, starts


def normalize_activity(rms_values: list[float], noise_percentile: float, active_percentile: float, min_dynamic_range_db: float) -> tuple[list[float], dict]:
    rms_db = np.asarray([db(value) for value in rms_values], dtype=np.float64)
    noise_db = float(np.percentile(rms_db, noise_percentile))
    active_db = float(np.percentile(rms_db, active_percentile))
    dynamic_range_db = max(min_dynamic_range_db, active_db - noise_db)
    scores = np.clip((rms_db - noise_db) / dynamic_range_db, 0.0, 1.0)
    return [round(float(score), 4) for score in scores], {
        "noiseDbfs": round(noise_db, 3),
        "activeDbfs": round(active_db, 3),
        "dynamicRangeDb": round(dynamic_range_db, 3),
    }


def main() -> int:
    args = parse_args()
    bss_root = resolve_path(args.bss_root)
    report_path = resolve_path(args.report)
    out_path = resolve_path(args.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    output = {
        "version": 1,
        "kind": "bss_source_activity",
        "settings": {
            "windowSeconds": args.window_seconds,
            "hopSeconds": args.hop_seconds,
            "noisePercentile": args.noise_percentile,
            "activePercentile": args.active_percentile,
            "minDynamicRangeDb": args.min_dynamic_range_db,
        },
        "duration": report["duration_seconds"],
        "algorithms": {},
    }

    common_starts: list[float] | None = None
    for algorithm in report["algorithms"]:
        algorithm_id = algorithm["name"]
        source_root = bss_root / algorithm_id
        sources = []

        for mapping in algorithm["mapping"]:
            source_index = int(mapping["source"])
            signal, sample_rate = sf.read(source_root / f"source{source_index}.wav", dtype="float64")
            if signal.ndim > 1:
                signal = np.mean(signal, axis=1)

            rms_values, starts = frame_rms(signal, sample_rate, args.window_seconds, args.hop_seconds)
            scores, normalization = normalize_activity(
                rms_values,
                args.noise_percentile,
                args.active_percentile,
                args.min_dynamic_range_db,
            )
            if common_starts is None:
                common_starts = [round(value, 3) for value in starts]

            sources.append(
                {
                    "source": source_index,
                    "matchedTrack": f"track{mapping['best_input']}",
                    "matchedLabel": mapping["best_label"],
                    "matchConfidence": round(float(mapping["envelope_corr"]), 4),
                    "matchMargin": round(float(mapping["margin_to_second"]), 4),
                    "normalization": normalization,
                    "scores": scores,
                }
            )

        output["algorithms"][algorithm_id] = {"sources": sources}

    output["starts"] = common_starts or []
    output["times"] = [round(start + args.window_seconds / 2, 3) for start in output["starts"]]
    out_path.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
