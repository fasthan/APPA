#!/usr/bin/env python3
"""Build Pro Tools-ready gate intervals from APPA original RMS analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from appa_gate_math import compute_gate_plan


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS = (
    ROOT / "web" / "assets" / "analysis" / "miuse-full" / "original_rms.json"
)
DEFAULT_OUTPUT = ROOT / "analysis_outputs" / "rms" / "protools_gate_plan.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--noise-percentile", type=float, default=20.0)
    parser.add_argument("--active-percentile", type=float, default=95.0)
    parser.add_argument("--min-dynamic-range-db", type=float, default=12.0)
    parser.add_argument("--activity-threshold", type=float, default=0.7)
    parser.add_argument("--dominance-margin", type=float, default=0.15)
    parser.add_argument("--fallback-min-score", type=float, default=0.0)
    parser.add_argument("--rms-gate-dbfs", type=float, default=-55.0)
    parser.add_argument("--off-gap-fill-seconds", type=float, default=2.0)
    parser.add_argument("--min-on-seconds", type=float, default=0.6)
    parser.add_argument("--pre-roll-seconds", type=float, default=0.1)
    parser.add_argument("--release-seconds", type=float, default=0.25)
    parser.add_argument(
        "--chunk-minutes",
        type=float,
        default=20.0,
        help=(
            "Recompute noise/active percentile normalization independently "
            "every N minutes instead of once over the whole file. Decision, "
            "smoothing, and padding still run continuously over the full "
            "timeline. Pass 0 to disable chunking (one global percentile)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.analysis.read_text(encoding="utf-8"))

    track_ids = sorted(payload["series"])
    starts = np.asarray(payload["starts"], dtype=np.float64)
    hop_seconds = float(payload["settings"]["hopSeconds"])
    duration = float(payload["duration"])
    rms_by_track = np.vstack(
        [np.asarray(payload["series"][track_id]["rmsDbfs"]) for track_id in track_ids]
    )

    settings = {
        "noisePercentile": args.noise_percentile,
        "activePercentile": args.active_percentile,
        "minDynamicRangeDb": args.min_dynamic_range_db,
        "activityThreshold": args.activity_threshold,
        "dominanceMargin": args.dominance_margin,
        "fallbackMinScore": args.fallback_min_score,
        "rmsGateDbfs": args.rms_gate_dbfs,
        "offGapFillSeconds": args.off_gap_fill_seconds,
        "minOnSeconds": args.min_on_seconds,
        "preRollSeconds": args.pre_roll_seconds,
        "releaseSeconds": args.release_seconds,
        "chunkMinutes": args.chunk_minutes,
    }

    result = compute_gate_plan(track_ids, rms_by_track, starts, hop_seconds, duration, settings)
    result["settings"] = {
        "windowSeconds": payload["settings"]["windowSeconds"],
        "hopSeconds": hop_seconds,
        **result["settings"],
    }

    plan = {
        "version": 1,
        "kind": "appa_protools_rms_gate_plan",
        "sourceAnalysis": str(args.analysis),
        **result,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Plan: {args.output}")
    for track_id, track in plan["tracks"].items():
        stats = track["stats"]
        print(
            f"{track_id}: {stats['mutedIntervalCount']} muted intervals, "
            f"{stats['mutedSeconds']:.1f}s muted"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
