#!/usr/bin/env python3
"""Shared RMS-activity gate-plan math.

Pure functions used by both the offline CLI (`build_rms_gate_plan.py`) and the
generic Pro Tools UI server (`serve_ptsl_gate.py`) so both paths compute
gate plans identically.
"""

from __future__ import annotations

import numpy as np


DEFAULT_NOISE_PERCENTILE = 20.0
DEFAULT_ACTIVE_PERCENTILE = 95.0
DEFAULT_MIN_DYNAMIC_RANGE_DB = 12.0
DEFAULT_ACTIVITY_THRESHOLD = 0.7
DEFAULT_DOMINANCE_MARGIN = 0.15
DEFAULT_FALLBACK_MIN_SCORE = 0.0
DEFAULT_RMS_GATE_DBFS = -55.0
DEFAULT_OFF_GAP_FILL_SECONDS = 2.0
DEFAULT_MIN_ON_SECONDS = 0.6
DEFAULT_PRE_ROLL_SECONDS = 0.1
DEFAULT_RELEASE_SECONDS = 0.25
DEFAULT_CHUNK_MINUTES = 20.0
DEFAULT_RMS_GATE_MODE = "post"

DEFAULT_PARAMS = {
    "noisePercentile": DEFAULT_NOISE_PERCENTILE,
    "activePercentile": DEFAULT_ACTIVE_PERCENTILE,
    "minDynamicRangeDb": DEFAULT_MIN_DYNAMIC_RANGE_DB,
    "activityThreshold": DEFAULT_ACTIVITY_THRESHOLD,
    "dominanceMargin": DEFAULT_DOMINANCE_MARGIN,
    "fallbackMinScore": DEFAULT_FALLBACK_MIN_SCORE,
    "rmsGateDbfs": DEFAULT_RMS_GATE_DBFS,
    "offGapFillSeconds": DEFAULT_OFF_GAP_FILL_SECONDS,
    "minOnSeconds": DEFAULT_MIN_ON_SECONDS,
    "preRollSeconds": DEFAULT_PRE_ROLL_SECONDS,
    "releaseSeconds": DEFAULT_RELEASE_SECONDS,
    "chunkMinutes": DEFAULT_CHUNK_MINUTES,
    # "post" (default) ANDs the RMS floor onto the decision mask after
    # threshold/dominance/fallback, matching the original pipeline. "pre"
    # excludes below-floor frames before normalization instead, so long
    # silent stretches don't skew each track's noise/active percentiles.
    "rmsGateMode": DEFAULT_RMS_GATE_MODE,
}

EPSILON = 0.001


def percentile(values: np.ndarray, value: float) -> float:
    return float(np.percentile(values, value))


def normalize_scores(
    rms_dbfs: np.ndarray,
    noise_percentile: float,
    active_percentile: float,
    min_dynamic_range_db: float,
    mask: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    """Compute noise/active percentiles from `rms_dbfs`, or from just the
    `mask`-selected subset when given (e.g. excluding below-floor silence
    from the calibration), then score every frame in `rms_dbfs` against
    that calibration regardless of mask.
    """
    reference = rms_dbfs if mask is None or not np.any(mask) else rms_dbfs[mask]
    noise_db = percentile(reference, noise_percentile)
    active_db = percentile(reference, active_percentile)
    dynamic_range_db = max(min_dynamic_range_db, active_db - noise_db)
    scores = np.clip((rms_dbfs - noise_db) / dynamic_range_db, 0.0, 1.0)
    return scores, {
        "noiseDbfs": round(noise_db, 3),
        "activeDbfs": round(active_db, 3),
        "dynamicRangeDb": round(dynamic_range_db, 3),
    }


def chunk_frame_ranges(
    frame_count: int, hop_seconds: float, chunk_minutes: float
) -> list[tuple[int, int]]:
    """Split [0, frame_count) into contiguous chunks of chunk_minutes each.

    chunk_minutes <= 0 means "no chunking" (one chunk spanning everything,
    equivalent to the old single-global-percentile behavior). A trailing
    remainder shorter than half a chunk is folded into the previous chunk
    instead of computing percentiles over too few frames.
    """
    if frame_count <= 0:
        return []
    if chunk_minutes <= 0:
        return [(0, frame_count)]

    chunk_frames = max(1, int(round(chunk_minutes * 60.0 / hop_seconds)))
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < frame_count:
        ranges.append((start, min(frame_count, start + chunk_frames)))
        start += chunk_frames

    if len(ranges) >= 2 and (ranges[-1][1] - ranges[-1][0]) < chunk_frames / 2:
        last_start, last_end = ranges.pop()
        ranges[-1] = (ranges[-1][0], last_end)

    return ranges


def normalize_scores_chunked(
    rms_dbfs: np.ndarray,
    starts: np.ndarray,
    hop_seconds: float,
    chunk_minutes: float,
    noise_percentile: float,
    active_percentile: float,
    min_dynamic_range_db: float,
    mask: np.ndarray | None = None,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    """Normalize dBFS to a 0..1 activity score, re-deriving noise/active
    percentiles independently within each chunk_minutes-wide window instead
    of once globally. Everything downstream (decision, fallback, hard gate,
    smoothing, safety net, padding) still operates on the full continuous
    array this returns — only the percentile statistics are chunked.

    When `mask` is given, each chunk's percentiles are calibrated from only
    the mask-selected (e.g. above-floor) frames in that chunk.
    """
    scores = np.empty_like(rms_dbfs, dtype=np.float64)
    chunks: list[dict[str, float]] = []
    for start, end in chunk_frame_ranges(len(rms_dbfs), hop_seconds, chunk_minutes):
        chunk_mask = mask[start:end] if mask is not None else None
        chunk_scores, normalization = normalize_scores(
            rms_dbfs[start:end], noise_percentile, active_percentile, min_dynamic_range_db, chunk_mask
        )
        scores[start:end] = chunk_scores
        chunks.append(
            {
                "startSeconds": round(float(starts[start]), 3),
                "endSeconds": round(float(starts[end - 1] + hop_seconds), 3),
                **normalization,
            }
        )
    return scores, chunks


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


def compute_gate_plan(
    track_ids: list[str],
    rms_by_track: np.ndarray,
    starts: np.ndarray,
    hop_seconds: float,
    duration: float,
    settings: dict[str, float],
) -> dict[str, object]:
    """Run the full gate-plan pipeline over plain arrays.

    `settings` accepts any subset of DEFAULT_PARAMS' keys; missing keys fall
    back to the defaults above. Returns a dict keyed by track_id with
    enabledIntervals/mutedIntervals/stats/normalization, plus the resolved
    settings and range actually used.
    """
    resolved = {**DEFAULT_PARAMS, **settings}
    range_end = min(duration, float(starts[-1] + hop_seconds))
    rms_first = resolved.get("rmsGateMode") == "pre"

    # In "pre" mode, frames below the RMS floor are excluded from each
    # track's own normalization instead of being filtered out afterward —
    # long silent stretches no longer drag down that track's noise/active
    # percentile calibration.
    valid_mask = rms_by_track >= resolved["rmsGateDbfs"] if rms_first else None

    scores = []
    normalizations = []
    for index, values in enumerate(rms_by_track):
        track_scores, chunks = normalize_scores_chunked(
            values,
            starts,
            hop_seconds,
            resolved["chunkMinutes"],
            resolved["noisePercentile"],
            resolved["activePercentile"],
            resolved["minDynamicRangeDb"],
            mask=valid_mask[index] if valid_mask is not None else None,
        )
        scores.append(track_scores)
        normalizations.append(chunks)
    score_matrix = np.vstack(scores)

    if rms_first:
        # Excluded frames never compete for dominance or clear the
        # threshold, regardless of what score their (now-irrelevant)
        # calibration would have assigned them.
        score_matrix = np.where(valid_mask, score_matrix, 0.0)

    max_scores = np.max(score_matrix, axis=0)
    decisions = (score_matrix >= resolved["activityThreshold"]) & (
        score_matrix >= max_scores - resolved["dominanceMargin"]
    )
    if rms_first:
        decisions &= valid_mask

    no_candidate = ~np.any(decisions, axis=0)
    if rms_first:
        # Tie-break fallback selection strictly toward non-excluded tracks
        # (two tracks can otherwise tie at a forced 0.0 score).
        fallback_scores = np.where(valid_mask, score_matrix, -1.0)
        any_valid = np.any(valid_mask, axis=0)
        fallback_frames = np.flatnonzero(
            no_candidate & any_valid & (max_scores >= resolved["fallbackMinScore"])
        )
    else:
        fallback_scores = score_matrix
        fallback_frames = np.flatnonzero(
            no_candidate & (max_scores >= resolved["fallbackMinScore"])
        )
    fallback_indices = np.argmax(fallback_scores, axis=0)
    decisions[fallback_indices[fallback_frames], fallback_frames] = True

    if not rms_first:
        decisions &= rms_by_track >= resolved["rmsGateDbfs"]

    smoothed = np.vstack(
        [
            smooth_track_mask(
                track_mask,
                hop_seconds,
                resolved["offGapFillSeconds"],
                resolved["minOnSeconds"],
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
            resolved["preRollSeconds"],
            resolved["releaseSeconds"],
        )
        muted = complement_intervals(enabled, 0.0, range_end)
        enabled_seconds = sum(item["end"] - item["start"] for item in enabled)
        muted_seconds = sum(item["end"] - item["start"] for item in muted)
        tracks[track_id] = {
            "normalization": {
                "chunkMinutes": resolved["chunkMinutes"],
                "chunks": normalizations[index],
            },
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
        "duration": duration,
        "range": {"start": 0.0, "end": round(range_end, 3)},
        "settings": resolved,
        "tracks": tracks,
    }
