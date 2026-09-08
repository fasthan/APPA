#!/usr/bin/env python3
"""Shared PTSL (Pro Tools Scripting Language) plumbing: the custom Operation
subclasses and helper functions needed to create/spot/mute audio clips and
verify the result, used by both the fixed 미우새 pipeline
(`apply_rms_gate_plan_to_protools.py`) and the generic Pro Tools UI server
(`serve_ptsl_gate.py`).

These `json_messup`/`json_cleanup` overrides are reactive fixes for specific
PTSL/protobuf JSON-serialization quirks discovered by hitting live server
errors — do not add speculative ones to new Operation subclasses; only add
one after actually seeing the server reject a request.
"""

from __future__ import annotations

import json
import unicodedata

from ptsl import PTSL_pb2 as pt
from ptsl.ops.operation import Operation


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


SOURCE_CHANNEL_BY_LABEL = {
    "mono": pt.SChannel_Mono,
    "left": pt.SChannel_Left,
    "right": pt.SChannel_Right,
}


def infer_source_channel_label(clip_name: str) -> str:
    """Pro Tools auto-splits a stereo/multichannel file's clip-list entry
    into per-channel clips suffixed '.L'/'.R' on import (see
    resolve_track_sources). A plain mono file's clip has no such suffix.
    """
    normalized = normalize_name(clip_name)
    if normalized.endswith(".l"):
        return "left"
    if normalized.endswith(".r"):
        return "right"
    return "mono"


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


def get_clip_list(engine, page_size: int = 1000):
    """Fetch every clip in the session, paginating so no single gRPC
    response exceeds the channel's default 4MB message-size limit (a real
    limit hit live once a session accumulates a few thousand clips).

    `pagination_response.total` is not reliable for detecting the last page
    (observed live to just echo back the current page's own size, not the
    session's grand total clip count), so pagination stops instead once a
    page comes back shorter than the requested page_size.
    """
    all_clips = []
    offset = 0
    while True:
        operation = CId_GetClipList(
            pagination_request=pt.PaginationRequest(limit=page_size, offset=offset)
        )
        engine.client.run(operation)
        page = list(operation.response.clips)
        all_clips.extend(page)
        offset += len(page)
        if len(page) < page_size:
            break
    return all_clips


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
    src_channel_name: int = pt.SChannel_Mono,
):
    """`src_channel_name` must match the actual channel layout of the file
    behind `file_id` (e.g. SChannel_Left/Right for one channel of a stereo
    file that was imported and reduced to a mono track) — Pro Tools rejects
    SChannel_Mono against a non-mono file with PT_InvalidParameter. The
    destination is always mono: these RMS-gate clips are always spotted onto
    a mono track regardless of the source file's own channel layout.
    """
    source_channel = pt.StemChannelId(name=src_channel_name, index=0)
    dest_channel = pt.StemChannelId(name=pt.SChannel_Mono, index=0)
    clip_info = pt.CreateAudioClipRequestEntryClipInfo(
        file_id=file_id,
        src_start_point=media_position(start_samples),
        src_end_point=media_position(end_samples),
        src_sync_point=media_position(start_samples),
        src_channel=source_channel,
        dst_channel=dest_channel,
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
    label: str,
    file_id: str,
    segments: list[dict],
    batch_size: int,
    src_channel_name: int = pt.SChannel_Mono,
) -> list[str]:
    clip_ids = []
    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start:batch_start + batch_size]
        entries = [
            create_clip_entry(
                f"APPA_RMS_{label}_{batch_start + offset + 1:04d}",
                file_id,
                segment["start"],
                segment["end"],
                src_channel_name,
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


def parse_track_edls(text: str) -> dict[str, list[dict]]:
    """Parse the per-track EDL section of `export_session_as_text()` output
    (built with `.include_track_edls()`) into {track_name: [event, ...]}.

    PTSL exposes no API mapping a Track to its Clips directly, so this text
    export (already used for post-apply verification in `export_track_events`)
    is the only mechanism available for discovering which clip(s) sit on
    which track. Column layout confirmed live: CHANNEL / EVENT / CLIP NAME /
    START TIME / END TIME / DURATION / STATE, tab-separated.
    """
    events_by_track: dict[str, list[dict]] = {}
    current_track: str | None = None
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.startswith("TRACK NAME:"):
            _, _, name = stripped.partition("\t")
            current_track = name.strip()
            events_by_track.setdefault(current_track, [])
            continue
        if current_track is None or not stripped.endswith(("Muted", "Unmuted")):
            continue
        columns = [column.strip() for column in stripped.split("\t")]
        if len(columns) < 7:
            continue
        events_by_track[current_track].append(
            {
                "clipName": columns[2],
                "start": int(columns[-4]),
                "end": int(columns[-3]),
                "muted": columns[-1] == "Muted",
            }
        )
    return events_by_track


def resolve_track_sources(engine) -> dict[str, dict]:
    """For every track with clips, resolve the underlying on-disk source
    media file via Clip.file_id -> FileLocation.file_id (no name-matching
    against the track's own name required). Returns {track_name: {status,
    reason, filePath, clipCount}}; status is one of "ok" (single clip, single
    file, safe to decode as-is), "flagged" (multiple clips/segments but a
    single dominant file could still be resolved), "empty" (no clips or no
    resolvable clip-list entry), or "offline" (file not online).
    """
    clips = get_clip_list(engine)
    clip_by_name: dict[str, list] = {}
    for clip in clips:
        clip_by_name.setdefault(normalize_name(clip.clip_full_name), []).append(clip)

    file_by_id = {location.file_id: location for location in engine.get_file_location()}

    export = engine.export_session_as_text()
    export.include_track_edls()
    export.time_type("samples")
    events_by_track = parse_track_edls(export.export_string())

    results: dict[str, dict] = {}
    for track_name, events in events_by_track.items():
        if not events:
            results[track_name] = {"status": "empty", "reason": "no clips on this track"}
            continue

        coverage: dict[str, int] = {}
        channel_coverage: dict[str, dict[str, int]] = {}
        unresolved = 0
        for event in events:
            matches = clip_by_name.get(normalize_name(event["clipName"]), [])
            if not matches:
                unresolved += 1
                continue
            file_id = matches[0].file_id
            duration = event["end"] - event["start"]
            coverage[file_id] = coverage.get(file_id, 0) + duration
            channel_label = infer_source_channel_label(event["clipName"])
            per_file_channels = channel_coverage.setdefault(file_id, {})
            per_file_channels[channel_label] = per_file_channels.get(channel_label, 0) + duration

        if not coverage:
            results[track_name] = {
                "status": "empty",
                "reason": "no clip-list entry matched this track's EDL events",
            }
            continue

        best_file_id = max(coverage, key=coverage.get)
        location = file_by_id.get(best_file_id)
        if location is None:
            results[track_name] = {
                "status": "empty",
                "reason": "resolved file has no on-disk location",
            }
            continue
        if not location.info.is_online:
            results[track_name] = {
                "status": "offline",
                "reason": "source media is offline",
                "filePath": location.path,
                "clipCount": len(events),
            }
            continue

        best_channel_coverage = channel_coverage[best_file_id]
        best_channel_label = max(best_channel_coverage, key=best_channel_coverage.get)

        is_single_clip = len(events) == 1 and unresolved == 0 and len(coverage) == 1
        results[track_name] = {
            "status": "ok" if is_single_clip else "flagged",
            "reason": None
            if is_single_clip
            else f"{len(events)} clip segment(s) across {len(coverage)} file(s) on this track",
            "filePath": location.path,
            "fileId": best_file_id,
            "sourceChannel": best_channel_label,
            "clipCount": len(events),
        }

    return results
