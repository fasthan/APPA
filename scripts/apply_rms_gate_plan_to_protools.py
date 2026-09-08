#!/usr/bin/env python3
"""Apply an APPA RMS gate plan to disposable Pro Tools tracks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from ptsl import open_engine

from appa_ptsl_ops import (
    clear_track,
    create_segment_clips,
    export_track_events,
    find_source_clip,
    find_track,
    get_clip_list,
    intervals_to_segments,
    seconds_to_samples,
    spot_segment_clips,
    verify_events,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "analysis_outputs" / "rms" / "protools_gate_plan.json"
DEFAULT_REPORT = (
    ROOT / "analysis_outputs" / "rms" / "protools_apply_report.json"
)


def parse_track_ids(value: str) -> list[str]:
    if value == "all":
        return ["track1", "track2", "track3", "track4"]
    track_ids = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [item for item in track_ids if item not in {
        "track1", "track2", "track3", "track4"
    }]
    if invalid:
        raise ValueError(f"Invalid track IDs: {', '.join(invalid)}")
    return track_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--tracks", default="all")
    parser.add_argument("--target-prefix", default="APPA_PTSL_ALL")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    selected_track_ids = parse_track_ids(args.tracks)
    print(f"Plan: {args.plan}")
    print(f"Tracks: {', '.join(selected_track_ids)}")
    if not args.apply:
        for track_id in selected_track_ids:
            stats = plan["tracks"][track_id]["stats"]
            print(
                f"{track_id}: {stats['mutedIntervalCount']} mute intervals"
            )
        print("Dry run only. Re-run with --apply to modify Pro Tools.")
        return 0

    if args.report.exists():
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if report.get("plan") != str(args.plan):
            raise RuntimeError(
                f"Existing report uses a different plan: {report.get('plan')}"
            )
    else:
        report = {
            "version": 1,
            "kind": "appa_protools_rms_gate_apply_report",
            "plan": str(args.plan),
            "tracks": {},
        }
    with open_engine(
        company_name="APPA",
        application_name="PTSL RMS Gate Apply",
    ) as engine:
        engine.host_ready_check()
        sample_rate = engine.session_sample_rate()
        if sample_rate is None:
            raise RuntimeError("Could not determine the session sample rate")
        tracks = engine.track_list()
        clips = get_clip_list(engine)
        range_end_samples = seconds_to_samples(
            plan["range"]["end"], sample_rate
        )

        for track_id in selected_track_ids:
            track_index = int(track_id.removeprefix("track"))
            source_track = next(
                track
                for track in tracks
                if track.name.startswith(f"{track_index} ")
            )
            target_name = f"{args.target_prefix}_{track_index:02d}"
            target_track = find_track(tracks, target_name)
            source_clip = find_source_clip(clips, source_track)
            source_end_samples = int(source_clip.src_end_point.position)
            segments = intervals_to_segments(
                plan["tracks"][track_id]["mutedIntervals"],
                range_end_samples,
                source_end_samples,
                sample_rate,
            )
            muted_count = sum(segment["muted"] for segment in segments)
            print(
                f"{track_id} -> {target_name}: {len(segments)} clips, "
                f"{muted_count} muted",
                flush=True,
            )
            started_at = time.monotonic()
            clip_ids = create_segment_clips(
                engine,
                f"T{track_index}",
                source_clip.file_id,
                segments,
                args.batch_size,
            )
            clear_track(engine, target_name)
            target_track = find_track(engine.track_list(), target_name)
            spot_segment_clips(engine, target_track, clip_ids, segments)
            events = export_track_events(engine, target_name)
            verify_events(events, segments)
            elapsed = time.monotonic() - started_at
            report["tracks"][track_id] = {
                "sourceTrack": source_track.name,
                "targetTrack": target_name,
                "eventCount": len(events),
                "mutedEventCount": muted_count,
                "elapsedSeconds": round(elapsed, 3),
            }
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  verified in {elapsed:.1f}s", flush=True)

    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
