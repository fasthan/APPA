#!/usr/bin/env python3
"""Create a disposable Pro Tools track and mute a clip via the Edit menu."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import time
import unicodedata

from ptsl import PTSL_pb2 as pt
from ptsl import open_engine
from ptsl.ops.operation import Operation


class CId_GetClipList(Operation):
    def json_cleanup(self, response_json: str) -> str:
        return response_json.replace('"clip_list"', '"clips"')


class CId_SpotClipsByID(Operation):
    pass


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def find_source_track(tracks, query: str):
    audio_tracks = [track for track in tracks if track.type == pt.TT_Audio]
    if not audio_tracks:
        raise RuntimeError("The open Pro Tools session has no audio tracks")
    if not query:
        return audio_tracks[0]

    normalized_query = normalize_name(query)
    matches = [
        track
        for track in audio_tracks
        if normalized_query in normalize_name(track.name)
    ]
    if len(matches) != 1:
        names = ", ".join(track.name for track in audio_tracks)
        raise RuntimeError(
            f"Expected one audio track matching {query!r}, found "
            f"{len(matches)}. "
            f"Available tracks: {names}"
        )
    return matches[0]


def find_source_file(engine, source_track):
    source_name = normalize_name(source_track.name)
    matches = [
        location
        for location in engine.get_file_location()
        if location.info.is_online
        and normalize_name(Path(location.path).stem) == source_name
    ]
    if len(matches) != 1:
        paths = ", ".join(location.path for location in matches) or "none"
        raise RuntimeError(
            f"Expected one online media file for {source_track.name!r}, found "
            f"{len(matches)}: {paths}"
        )
    return matches[0]


def wait_for_created_track(
    engine,
    previous_track_ids: set[str],
    timeout: float = 5.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        imported = [
            track
            for track in engine.track_list()
            if track.id not in previous_track_ids and track.type == pt.TT_Audio
        ]
        if len(imported) == 1:
            return imported[0]
        if len(imported) > 1:
            names = ", ".join(track.name for track in imported)
            raise RuntimeError(
                f"Unexpectedly created multiple tracks: {names}"
            )
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for the created Pro Tools track")


def find_source_clip(engine, source_track, source_file):
    operation = CId_GetClipList(
        pagination_request=pt.PaginationRequest(limit=1000, offset=0)
    )
    engine.client.run(operation)
    source_name = normalize_name(source_track.name)
    matches = [
        clip
        for clip in operation.response.clips
        if clip.file_id == source_file.file_id
        and normalize_name(clip.clip_full_name) == source_name
    ]
    if len(matches) != 1:
        names = ", ".join(clip.clip_full_name for clip in matches) or "none"
        raise RuntimeError(
            f"Expected one source clip for {source_track.name!r}, found "
            f"{len(matches)}: {names}"
        )
    return matches[0]


def wait_for_track_clips(engine, track_id: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        track = next(
            track for track in engine.track_list() if track.id == track_id
        )
        if track.track_attributes.contains_clips:
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for the spotted clip")


def spot_clip_on_track(engine, clip_id: str, track) -> None:
    location = pt.SpotLocationData(
        location=pt.TimelineLocation(
            location="0",
            time_type=pt.TLType_Samples,
        )
    )
    operation = CId_SpotClipsByID(
        src_clips=[clip_id],
        dst_track_id=track.id,
        dst_location_data=location,
    )
    engine.client.run(operation)
    wait_for_track_clips(engine, track.id)


def spot_source_clip_on_new_track(
    engine,
    source_track,
    source_file,
    test_track_name: str,
) -> None:
    source_clip = find_source_clip(engine, source_track, source_file)
    previous_track_ids = {track.id for track in engine.track_list()}
    engine.create_new_tracks(
        number_of_tracks=1,
        track_name=test_track_name,
        track_format=source_track.format,
        track_type=pt.TT_Audio,
        track_timebase=source_track.timebase,
    )
    test_track = wait_for_created_track(engine, previous_track_ids)
    spot_clip_on_track(engine, source_clip.clip_id, test_track)


def verify_muted_clip(engine, track_name: str) -> list[str]:
    track = next(
        track
        for track in engine.track_list()
        if normalize_name(track.name) == normalize_name(track_name)
    )
    if not track.track_attributes.contains_clips:
        raise RuntimeError(
            f"Verification failed: {track_name!r} contains no clips"
        )

    engine.select_tracks_by_name([track_name], mode=pt.SM_Replace)
    export = engine.export_session_as_text()
    export.include_track_edls()
    export.selected_tracks_only()
    export.time_type("samples")
    session_text = export.export_string()
    event_lines = [
        line
        for line in session_text.splitlines()
        if line.rstrip().endswith(("Muted", "Unmuted"))
    ]
    if not any(line.rstrip().endswith("Muted") for line in event_lines):
        raise RuntimeError(
            "Verification failed: no muted clip appears in the track EDL"
        )
    return event_lines


def invoke_separate_and_mute_menu(delay_seconds: float) -> None:
    script = f'''
tell application "Pro Tools" to activate
delay {delay_seconds}
tell application "System Events"
    tell process "Pro Tools"
        set frontmost to true
        tell menu bar 1
            tell menu bar item "Edit"
                tell menu 1
                    tell menu item "Separate Clip"
                        click menu item "At Selection" of menu 1
                    end tell
                end tell
            end tell
        end tell
        delay {delay_seconds}
        set editMenu to menu 1 of menu bar item "Edit" of menu bar 1
        if exists menu item "Mute Clips" of editMenu then
            click menu item "Mute Clips" of editMenu
        else if exists menu item "Mute" of editMenu then
            click menu item "Mute" of editMenu
        else
            error "Pro Tools Mute Clips command is unavailable"
        end if
    end tell
end tell
'''
    subprocess.run(["osascript", "-e", script], check=True)


def seconds_to_samples(seconds: float, sample_rate: int) -> int:
    return int(round(seconds * sample_rate))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reference source media on a disposable Pro Tools track, "
            "split the "
            "configured range, and clip-mute it through the Edit menu."
        )
    )
    parser.add_argument(
        "--source-track",
        default="",
        help=(
            "Unique substring of the source track name; defaults to the first "
            "audio track."
        ),
    )
    parser.add_argument("--test-track", default="APPA_PTSL_MUTE_TEST")
    parser.add_argument("--mute-start", type=float, default=2.0)
    parser.add_argument("--mute-end", type=float, default=4.0)
    parser.add_argument("--shortcut-delay", type=float, default=0.35)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Required to modify the open Pro Tools session.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 <= args.mute_start < args.mute_end:
        raise ValueError(
            "mute-start must be >= 0 and mute-end must be greater"
        )

    with open_engine(
        company_name="APPA",
        application_name="PTSL Clip Mute Test",
    ) as engine:
        engine.host_ready_check()
        sample_rate = engine.session_sample_rate()
        if sample_rate is None:
            raise RuntimeError(
                "Could not determine the Pro Tools session sample rate"
            )

        tracks = engine.track_list()
        source_track = find_source_track(tracks, args.source_track)
        source_file = find_source_file(engine, source_track)
        test_track_exists = any(
            normalize_name(track.name) == normalize_name(args.test_track)
            for track in tracks
        )
        if test_track_exists:
            raise RuntimeError(
                f"Track {args.test_track!r} already exists. Delete it or "
                "choose "
                "--test-track."
            )

        mute_start = seconds_to_samples(args.mute_start, sample_rate)
        mute_end = seconds_to_samples(args.mute_end, sample_rate)

        print(f"Session: {engine.session_name()} ({sample_rate} Hz)")
        print(f"Source: {source_track.name}")
        print(f"Source media: {source_file.path}")
        print(f"Test track: {args.test_track}")
        print(f"Mute samples: {mute_start} - {mute_end}")
        if not args.apply:
            print("Dry run only. Re-run with --apply to modify Pro Tools.")
            return 0

        engine.set_edit_mode(pt.EMode_Slip)
        spot_source_clip_on_new_track(
            engine,
            source_track,
            source_file,
            args.test_track,
        )

        # This command establishes the edit-selection lane even when Pro Tools'
        # Link Track and Edit Selection option is disabled.
        engine.select_all_clips_on_track(args.test_track)
        engine.set_timeline_selection(
            in_time=str(mute_start),
            out_time=str(mute_end),
            location_type=pt.TLType_Samples,
        )
        invoke_separate_and_mute_menu(args.shortcut_delay)
        event_lines = verify_muted_clip(engine, args.test_track)
        print("Verified track EDL:")
        for line in event_lines:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
