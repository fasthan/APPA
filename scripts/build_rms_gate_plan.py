#!/usr/bin/env python3
"""Build Pro Tools-ready gate intervals from APPA original RMS analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS = (
    ROOT / "web" / "assets" / "analysis" / "miuse-full" / "original_rms.json"
)
DEFAULT_OUTPUT = ROOT / "analysis_outputs" / "rms" / "protools_gate_plan.json"
EPSILON = 0.001


def percentile(values: np.ndarray, value: float) -> float:
    return float(np.percentile(values, value))


def normalize_scores(
    rms_dbfs: np.ndarray,
    noise_percentile: float,
    active_percentile: float,
    min_dynamic_range_db: float,
) -> tuple[np.ndarray, dict[str, float]]:
    noise_db = percentile(rms_dbfs, noise_percentile)
    active_db = percentile(rms_dbfs, active_percentile)
    dynamic_range_db = max(min_dynamic_range_db, active_db - noise_db)
    scores = np.clip((rms_dbfs - noise_db) / dynamic_range_db, 0.0, 1.0)
    return scores, {
        "noiseDbfs": round(noise_db, 3),
        "activeDbfs": round(active_db, 3),
        "dynamicRangeDb": round(dynamic_range_db, 3),
    }


def boolean_runs(mask: np.ndarray):
    start = 0
    while start < len(mask):
        value = bool(mask[start])
        end = start + 1
        while end < len(mask) and bool(mask[end]) == value:
            end += 1
        yield start, end, value
        start = end


def fill_short_off_gaps(
    mask: np.ndarray,
    hop_seconds: float,
    max_gap_seconds: float,
) -> np.ndarray:
    result = mask.copy()
    for start, end, value in boolean_runs(mask):
        has_on_before = start > 0 and bool(mask[start - 1])
        has_on_after = end < len(mask) and bool(mask[end])
        duration = (end - start) * hop_seconds
        if (
            not value
            and has_on_before
            and has_on_after
            and duration <= max_gap_seconds + EPSILON
        ):
            result[start:end] = True
    return result


def remove_short_on_runs(
    mask: np.ndarray,
    hop_seconds: float,
    min_on_seconds: float,
) -> np.ndarray:
    result = mask.copy()
    for start, end, value in boolean_runs(mask):
        duration = (end - start) * hop_seconds
        if value and duration < min_on_seconds - EPSILON:
            result[start:end] = False
    return result


def smooth_track_mask(
    mask: np.ndarray,
    hop_seconds: float,
    off_gap_fill_seconds: float,
    min_on_seconds: float,
) -> np.ndarray:
    result = fill_short_off_gaps(mask, hop_seconds, off_gap_fill_seconds)
    result = remove_short_on_runs(result, hop_seconds, min_on_seconds)
    return fill_short_off_gaps(result, hop_seconds, off_gap_fill_seconds)


def mask_to_intervals(
    mask: np.ndarray,
    starts: np.ndarray,
    hop_seconds: float,
) -> list[dict[str, float]]:
    intervals = []
    for start, end, value in boolean_runs(mask):
        if not value:
            continue
        intervals.append(
            {
                "start": float(starts[start]),
                "end": float(starts[end - 1] + hop_seconds),
            }
        )
    return intervals


def merge_intervals(
    intervals: list[dict[str, float]],
) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for interval in sorted(intervals, key=lambda item: item["start"]):
        if merged and interval["start"] <= merged[-1]["end"] + EPSILON:
            merged[-1]["end"] = max(merged[-1]["end"], interval["end"])
        else:
            merged.append(dict(interval))
    return merged


def pad_intervals(
    intervals: list[dict[str, float]],
    duration: float,
    pre_roll_seconds: float,
    release_seconds: float,
) -> list[dict[str, float]]:
    padded = [
        {
            "start": max(0.0, item["start"] - pre_roll_seconds),
            "end": min(duration, item["end"] + release_seconds),
        }
        for item in intervals
    ]
    return merge_intervals(padded)


def complement_intervals(
    intervals: list[dict[str, float]],
    range_start: float,
    range_end: float,
) -> list[dict[str, float]]:
    muted = []
    cursor = range_start
    for interval in intervals:
        start = max(range_start, interval["start"])
        end = min(range_end, interval["end"])
        if start > cursor + EPSILON:
            muted.append({"start": cursor, "end": start})
        cursor = max(cursor, end)
    if cursor < range_end - EPSILON:
        muted.append({"start": cursor, "end": range_end})
    return muted


def round_intervals(
    intervals: list[dict[str, float]],
) -> list[dict[str, float]]:
    return [
        {"start": round(item["start"], 3), "end": round(item["end"], 3)}
        for item in intervals
    ]


def build_plan(payload: dict, args: argparse.Namespace) -> dict:
    track_ids = sorted(payload["series"])
    starts = np.asarray(payload["starts"], dtype=np.float64)
    hop_seconds = float(payload["settings"]["hopSeconds"])
    duration = float(payload["duration"])
    range_end = min(duration, float(starts[-1] + hop_seconds))

    rms_by_track = np.vstack([
        np.asarray(payload["series"][track_id]["rmsDbfs"])
        for track_id in track_ids
    ])
    scores = []
    normalizations = []
    for values in rms_by_track:
        track_scores, normalization = normalize_scores(
            values,
            args.noise_percentile,
            args.active_percentile,
            args.min_dynamic_range_db,
        )
        scores.append(track_scores)
        normalizations.append(normalization)
    score_matrix = np.vstack(scores)

    max_scores = np.max(score_matrix, axis=0)
    decisions = (score_matrix >= args.activity_threshold) & (
        score_matrix >= max_scores - args.dominance_margin
    )
    no_candidate = ~np.any(decisions, axis=0)
    fallback_indices = np.argmax(score_matrix, axis=0)
    fallback_frames = np.flatnonzero(
        no_candidate & (max_scores >= args.fallback_min_score)
    )
    decisions[fallback_indices[fallback_frames], fallback_frames] = True
    decisions &= rms_by_track >= args.rms_gate_dbfs

    smoothed = np.vstack(
        [
            smooth_track_mask(
                track_mask,
                hop_seconds,
                args.off_gap_fill_seconds,
                args.min_on_seconds,
            )
            for track_mask in decisions
        ]
    )
    no_smoothed_track = ~np.any(smoothed, axis=0)
    smoothed[:, no_smoothed_track] = decisions[:, no_smoothed_track]

    tracks = {}
    for index, track_id in enumerate(track_ids):
        active = mask_to_intervals(smoothed[index], starts, hop_seconds)
        enabled = pad_intervals(
            active,
            duration,
            args.pre_roll_seconds,
            args.release_seconds,
        )
        muted = complement_intervals(enabled, 0.0, range_end)
        enabled_seconds = sum(item["end"] - item["start"] for item in enabled)
        muted_seconds = sum(item["end"] - item["start"] for item in muted)
        tracks[track_id] = {
            "normalization": normalizations[index],
            "enabledIntervals": round_intervals(enabled),
            "mutedIntervals": round_intervals(muted),
            "stats": {
                "enabledIntervalCount": len(enabled),
                "mutedIntervalCount": len(muted),
                "enabledSeconds": round(enabled_seconds, 3),
                "mutedSeconds": round(muted_seconds, 3),
            },
        }

    return {
        "version": 1,
        "kind": "appa_protools_rms_gate_plan",
        "sourceAnalysis": str(args.analysis),
        "duration": duration,
        "range": {"start": 0.0, "end": round(range_end, 3)},
        "settings": {
            "windowSeconds": payload["settings"]["windowSeconds"],
            "hopSeconds": hop_seconds,
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
        },
        "tracks": tracks,
    }


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.analysis.read_text(encoding="utf-8"))
    plan = build_plan(payload, args)
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
