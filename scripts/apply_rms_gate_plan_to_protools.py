#!/usr/bin/env python3
"""Apply an APPA RMS gate plan to disposable Pro Tools tracks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import unicodedata

from ptsl import PTSL_pb2 as pt
from ptsl import open_engine
from ptsl.ops.operation import Operation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "analysis_outputs" / "rms" / "protools_gate_plan.json"
DEFAULT_REPORT = (
    ROOT / "analysis_outputs" / "rms" / "protools_apply_report.json"
)


class CId_GetClipList(Operation):
    def json_cleanup(self, response_json: str) -> str:
        return response_json.replace('"clip_list"', '"clips"')


class CId_CreateAudioClips(Operation):
    def json_messup(self, request_json: str) -> str:
        payload = json.loads(request_json)
        point_names = (
            "src_start_point",
            "src_end_point",
            "src_sync_point",
            "start_point",
            "end_point",
        )
        for entry in payload.get("clip_list", []):
            for clip_info in entry.get("clip_info", []):
                for point_name in point_names:
                    point = clip_info.get(point_name)
                    if point and "position" in point:
                        point["position"] = int(point["position"])
        return json.dumps(payload)


class CId_SpotClipsByID(Operation):
    def json_messup(self, request_json: str) -> str:
        payload = json.loads(request_json)
        attributes = payload.get("clip_instance_attributes")
        if attributes:
            if attributes.get("color_index") == 0:
                attributes.pop("color_index")
            if not attributes.get("locked_states"):
                attributes.pop("locked_states", None)
        return json.dumps(payload)


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def seconds_to_samples(seconds: float, sample_rate: int) -> int:
    return int(round(seconds * sample_rate))


def media_position(samples: int):
    return pt.MediaTimePosition(
        position=samples,
        time_type=pt.BTType_Samples,
    )


def timeline_location(samples: int):
    return pt.TimelineLocation(
        location=str(samples),
        time_type=pt.TLType_Samples,
    )


def get_clip_list(engine):
    operation = CId_GetClipList(
        pagination_request=pt.PaginationRequest(limit=10000, offset=0)
    )
    engine.client.run(operation)
    return operation.response.clips


def find_track(tracks, name: str):
    matches = [
        track
        for track in tracks
        if normalize_name(track.name) == normalize_name(name)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one Pro Tools track named {name!r}, found "
            f"{len(matches)}"
        )
    return matches[0]


def find_source_clip(clips, source_track):
    source_name = normalize_name(source_track.name)
    matches = [
        clip
        for clip in clips
        if normalize_name(clip.clip_full_name) == source_name
        and clip.clip_type == pt.ClipType_Audio
    ]
    if len(matches) != 1:
        names = ", ".join(clip.clip_full_name for clip in matches) or "none"
        raise RuntimeError(
            f"Expected one full source clip for {source_track.name!r}, found "
            f"{len(matches)}: {names}"
        )
    return matches[0]


def intervals_to_segments(
    muted_intervals: list[dict],
    range_end_samples: int,
    source_end_samples: int,
    sample_rate: int,
) -> list[dict]:
    segments = []
    cursor = 0
    for interval in muted_intervals:
        start = seconds_to_samples(interval["start"], sample_rate)
        end = seconds_to_samples(interval["end"], sample_rate)
        start = max(cursor, min(range_end_samples, start))
        end = max(start, min(range_end_samples, end))
        if start > cursor:
            segments.append({"start": cursor, "end": start, "muted": False})
        if end > start:
            segments.append({"start": start, "end": end, "muted": True})
        cursor = end
    if cursor < range_end_samples:
        segments.append(
            {"start": cursor, "end": range_end_samples, "muted": False}
        )
    if range_end_samples < source_end_samples:
        if segments and not segments[-1]["muted"]:
            segments[-1]["end"] = source_end_samples
        else:
            segments.append(
                {
                    "start": range_end_samples,
                    "end": source_end_samples,
                    "muted": False,
                }
            )
    return [
        segment
        for segment in segments
        if segment["end"] > segment["start"]
    ]


def create_clip_entry(
    name: str,
    file_id: str,
    start_samples: int,
    end_samples: int,
):
    source_channel = pt.StemChannelId(name=pt.SChannel_Mono, index=0)
    clip_info = pt.CreateAudioClipRequestEntryClipInfo(
        file_id=file_id,
        src_start_point=media_position(start_samples),
        src_end_point=media_position(end_samples),
        src_sync_point=media_position(start_samples),
        src_channel=source_channel,
        dst_channel=source_channel,
        start_point=media_position(start_samples),
        end_point=media_position(end_samples),
    )
    timestamp = timeline_location(start_samples)
    return pt.CreateAudioClipRequestEntry(
        name=name,
        channel_format=pt.SFormat_Mono,
        original_timestamp=timestamp,
        user_timestamp=timestamp,
        clip_info=[clip_info],
    )


def create_segment_clips(
    engine,
    track_index: int,
    file_id: str,
    segments: list[dict],
    batch_size: int,
) -> list[str]:
    clip_ids = []
    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start:batch_start + batch_size]
        entries = [
            create_clip_entry(
                f"APPA_RMS_T{track_index}_{batch_start + offset + 1:04d}",
                file_id,
                segment["start"],
                segment["end"],
            )
            for offset, segment in enumerate(batch)
        ]
        operation = CId_CreateAudioClips(clip_list=entries)
        engine.client.run(operation)
        responses = operation.response.clip_list
        if len(responses) != len(batch):
            raise RuntimeError(
                f"Created {len(responses)} clip responses for "
                f"{len(batch)} requests"
            )
        for response in responses:
            if len(response.clip_ids) != 1:
                raise RuntimeError(
                    "Expected one mono clip ID per CreateAudioClips response"
                )
            clip_ids.append(response.clip_ids[0])
        print(
            f"  created clips {batch_start + 1}-{batch_start + len(batch)} "
            f"of {len(segments)}",
            flush=True,
        )
    return clip_ids


def clear_track(engine, track_name: str) -> None:
    track = find_track(engine.track_list(), track_name)
    if track.track_attributes.contains_clips:
        engine.select_all_clips_on_track(track.name)
        engine.clear()


def spot_segment(
    engine,
    track,
    clip_id: str,
    segment: dict,
) -> None:
    kwargs = {
        "src_clips": [clip_id],
        "dst_track_id": track.id,
        "dst_location_data": pt.SpotLocationData(
            location=timeline_location(segment["start"])
        ),
    }
    if segment["muted"]:
        kwargs["clip_instance_attributes"] = pt.ClipInstanceAttributes(
            is_muted=pt.TB_True
        )
    operation = CId_SpotClipsByID(**kwargs)
    engine.client.run(operation)


def spot_segment_clips(
    engine,
    track,
    clip_ids: list[str],
    segments: list[dict],
) -> None:
    pairs = enumerate(zip(clip_ids, segments), start=1)
    for index, (clip_id, segment) in pairs:
        spot_segment(engine, track, clip_id, segment)
        if index % 100 == 0 or index == len(segments):
            print(f"  spotted clips {index} of {len(segments)}", flush=True)


def export_track_events(engine, track_name: str) -> list[dict]:
    engine.select_tracks_by_name([track_name], mode=pt.SM_Replace)
    export = engine.export_session_as_text()
    export.include_track_edls()
    export.selected_tracks_only()
    export.time_type("samples")
    events = []
    for line in export.export_string().splitlines():
        if not line.rstrip().endswith(("Muted", "Unmuted")):
            continue
        columns = [column.strip() for column in line.split("\t")]
        events.append(
            {
                "start": int(columns[-4]),
                "end": int(columns[-3]),
                "muted": columns[-1] == "Muted",
            }
        )
    return events


def verify_events(events: list[dict], segments: list[dict]) -> None:
    if len(events) != len(segments):
        raise RuntimeError(
            f"EDL has {len(events)} events; expected {len(segments)}"
        )
    for index, (event, segment) in enumerate(zip(events, segments), start=1):
        if event != segment:
            raise RuntimeError(
                f"EDL event {index} mismatch: {event!r} != {segment!r}"
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
                track_index,
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
