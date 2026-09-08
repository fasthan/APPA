#!/usr/bin/env python3
"""Serve the generic Pro Tools RMS gate UI (web_gate/) and its PTSL-backed
API. Works against whatever session is currently open in Pro Tools, unlike
the 미우새-specific pipeline (serve_web.py + build_rms_gate_plan.py +
apply_rms_gate_plan_to_protools.py)."""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from ptsl import PTSL_pb2 as pt
from ptsl import open_engine

from appa_gate_math import DEFAULT_PARAMS, compute_gate_plan
from appa_ptsl_ops import (
    SOURCE_CHANNEL_BY_LABEL,
    clear_track,
    create_segment_clips,
    export_track_events,
    find_track,
    intervals_to_segments,
    normalize_name,
    resolve_track_sources,
    seconds_to_samples,
    spot_segment_clips,
    verify_events,
)
from appa_rms_decode import probe_duration, stream_rms_db, stream_waveform_minmax


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_GATE_ROOT = PROJECT_ROOT / "web_gate"
GENERIC_PLAN_OUTPUT = (
    PROJECT_ROOT / "analysis_outputs" / "rms" / "protools_gate_plan_generic.json"
)
WAVEFORM_SAMPLE_RATE = 800
WAVEFORM_POINT_TARGET = 1600
DEFAULT_TARGET_SUFFIX = "_APPA_GATE"

# Pro Tools' local PTSL connection is not known to be safe for concurrent
# requests from one client process; serialize every PTSL-touching handler.
PTSL_LOCK = threading.Lock()


def sanitize_label(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name)[:40] or "TRACK"


def json_response(handler: SimpleHTTPRequestHandler, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length) if length else b"{}"
    return json.loads(body.decode("utf-8"))


def classify_track_format(track) -> str:
    return "mono" if track.format == pt.SFormat_Mono else "other"


def handle_get_tracks(handler: SimpleHTTPRequestHandler) -> None:
    with PTSL_LOCK:
        with open_engine(company_name="APPA", application_name="PTSL Gate UI") as engine:
            engine.host_ready_check()
            session_name = engine.session_name()
            sample_rate = engine.session_sample_rate()
            tracks = [track for track in engine.track_list() if track.type == pt.TT_Audio]
            sources = resolve_track_sources(engine)

    track_payloads = []
    for track in tracks:
        source = sources.get(track.name, {"status": "empty", "reason": "no clips on this track"})
        track_format = classify_track_format(track)
        selectable = track_format == "mono" and source["status"] in ("ok", "flagged")
        if track_format != "mono":
            source = {**source, "status": "unsupported", "reason": "non-mono tracks are not supported yet"}
        track_payloads.append(
            {
                "name": track.name,
                "format": track_format,
                "selectable": selectable,
                "source": source,
            }
        )

    json_response(
        handler,
        {
            "sessionName": session_name,
            "sampleRate": sample_rate,
            "defaultParams": DEFAULT_PARAMS,
            "tracks": track_payloads,
        },
    )


def decode_track(name: str, file_path: str) -> dict:
    rms_values, starts = stream_rms_db(Path(file_path))
    duration = probe_duration(Path(file_path))
    window_seconds = max(0.05, duration / WAVEFORM_POINT_TARGET)
    mins, maxs = stream_waveform_minmax(Path(file_path), WAVEFORM_SAMPLE_RATE, window_seconds)
    return {
        "name": name,
        "rmsValues": rms_values,
        "starts": starts,
        "duration": duration,
        "waveform": {"mins": mins, "maxs": maxs, "windowSeconds": window_seconds},
    }


def handle_post_extract(handler: SimpleHTTPRequestHandler) -> None:
    body = read_json_body(handler)
    requested_names = list(body.get("trackNames") or [])
    if not requested_names:
        json_response(handler, {"error": "trackNames must be a non-empty list"}, HTTPStatus.BAD_REQUEST)
        return

    with PTSL_LOCK:
        with open_engine(company_name="APPA", application_name="PTSL Gate UI") as engine:
            engine.host_ready_check()
            sources = resolve_track_sources(engine)

    resolvable = []
    skipped = []
    for name in requested_names:
        source = sources.get(name)
        if not source or source["status"] not in ("ok", "flagged"):
            skipped.append({"name": name, "reason": (source or {}).get("reason", "track not found")})
            continue
        resolvable.append((name, source["filePath"]))

    if not resolvable:
        json_response(handler, {"error": "No requested tracks were resolvable", "skipped": skipped}, HTTPStatus.BAD_REQUEST)
        return

    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(4, len(resolvable))) as pool:
        decoded = list(pool.map(lambda pair: decode_track(*pair), resolvable))
    extract_seconds = round(time.monotonic() - started_at, 1)

    min_frame_count = min(len(item["rmsValues"]) for item in decoded)
    starts = decoded[0]["starts"][:min_frame_count]
    hop_seconds = round(starts[1] - starts[0], 6) if min_frame_count > 1 else 0.1
    duration = min(item["duration"] for item in decoded)

    file_path_by_name = dict(resolvable)
    tracks = {}
    for item in decoded:
        tracks[item["name"]] = {
            "rmsValues": item["rmsValues"][:min_frame_count],
            "filePath": file_path_by_name[item["name"]],
            "durationSeconds": item["duration"],
            "waveform": item["waveform"],
        }

    json_response(
        handler,
        {
            "hopSeconds": hop_seconds,
            "duration": duration,
            "starts": starts,
            "skipped": skipped,
            "extractSeconds": extract_seconds,
            "tracks": tracks,
        },
    )


def handle_post_build_plan(handler: SimpleHTTPRequestHandler) -> None:
    body = read_json_body(handler)
    rms_by_track_input = dict(body.get("rmsByTrack") or {})
    starts_input = list(body.get("starts") or [])
    hop_seconds = float(body.get("hopSeconds") or 0.1)
    duration = float(body.get("duration") or 0.0)
    params = dict(body.get("params") or {})

    if not rms_by_track_input or not starts_input:
        json_response(handler, {"error": "rmsByTrack and starts are required"}, HTTPStatus.BAD_REQUEST)
        return

    track_names = list(rms_by_track_input.keys())
    min_frame_count = min(min(len(v) for v in rms_by_track_input.values()), len(starts_input))
    rms_by_track = np.vstack([np.asarray(rms_by_track_input[name][:min_frame_count]) for name in track_names])
    starts = np.asarray(starts_input[:min_frame_count], dtype=np.float64)

    plan = compute_gate_plan(track_names, rms_by_track, starts, hop_seconds, duration, params)

    GENERIC_PLAN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    GENERIC_PLAN_OUTPUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    json_response(handler, plan)


def ensure_target_track(engine, source_track, target_name: str):
    existing = [t for t in engine.track_list() if normalize_name(t.name) == normalize_name(target_name)]
    if existing:
        return existing[0]

    previous_ids = {t.id for t in engine.track_list()}
    engine.create_new_tracks(
        number_of_tracks=1,
        track_name=target_name,
        track_format=source_track.format,
        track_type=pt.TT_Audio,
        track_timebase=source_track.timebase,
    )
    deadline = time.monotonic() + 5.0
    created = None
    while time.monotonic() < deadline:
        candidates = [t for t in engine.track_list() if t.id not in previous_ids]
        if candidates:
            created = candidates[0]
            break
        time.sleep(0.1)
    if created is None:
        raise RuntimeError(f"Timed out waiting for Pro Tools to create track {target_name!r}")
    if created.name != target_name:
        engine.rename_target_track(created.name, target_name)
        created = find_track(engine.track_list(), target_name)
    return created


def handle_post_apply(handler: SimpleHTTPRequestHandler) -> None:
    body = read_json_body(handler)
    if body.get("confirm") is not True:
        json_response(handler, {"error": "confirm must be true to modify Pro Tools"}, HTTPStatus.BAD_REQUEST)
        return

    plan = body.get("plan") or {}
    track_names = list(body.get("trackNames") or [])
    target_suffix = body.get("targetSuffix") or DEFAULT_TARGET_SUFFIX
    batch_size = int(body.get("batchSize") or 200)
    if not track_names:
        json_response(handler, {"error": "trackNames must be a non-empty list"}, HTTPStatus.BAD_REQUEST)
        return

    report = {"version": 1, "kind": "appa_ptsl_gate_apply_report", "tracks": {}, "errors": {}}

    with PTSL_LOCK:
        with open_engine(company_name="APPA", application_name="PTSL Gate UI") as engine:
            engine.host_ready_check()
            sample_rate = engine.session_sample_rate()
            if sample_rate is None:
                json_response(handler, {"error": "Could not determine the session sample rate"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            sources = resolve_track_sources(engine)
            tracks_by_name = {t.name: t for t in engine.track_list() if t.type == pt.TT_Audio}
            range_end_samples = seconds_to_samples(plan.get("range", {}).get("end", 0.0), sample_rate)

            for name in track_names:
                try:
                    track_plan = plan["tracks"][name]
                    source = sources.get(name)
                    source_track = tracks_by_name.get(name)
                    if source_track is None or not source or source["status"] not in ("ok", "flagged"):
                        raise RuntimeError(f"Track {name!r} is not currently resolvable in Pro Tools")

                    target_name = f"{name}{target_suffix}"
                    target_track = ensure_target_track(engine, source_track, target_name)

                    source_end_samples = seconds_to_samples(track_plan["durationSeconds"], sample_rate)
                    segments = intervals_to_segments(
                        track_plan["mutedIntervals"], range_end_samples, source_end_samples, sample_rate
                    )
                    muted_count = sum(segment["muted"] for segment in segments)
                    started_at = time.monotonic()
                    src_channel_name = SOURCE_CHANNEL_BY_LABEL.get(
                        source.get("sourceChannel", "mono"), pt.SChannel_Mono
                    )
                    clip_ids = create_segment_clips(
                        engine, sanitize_label(name), source["fileId"], segments, batch_size, src_channel_name
                    )
                    clear_track(engine, target_name)
                    target_track = find_track(engine.track_list(), target_name)
                    spot_segment_clips(engine, target_track, clip_ids, segments)
                    events = export_track_events(engine, target_name)
                    verify_events(events, segments)
                    elapsed = time.monotonic() - started_at
                    report["tracks"][name] = {
                        "targetTrack": target_name,
                        "eventCount": len(events),
                        "mutedEventCount": muted_count,
                        "elapsedSeconds": round(elapsed, 3),
                    }
                except Exception as error:  # noqa: BLE001 - report per-track, keep going
                    report["errors"][name] = str(error)

    status = HTTPStatus.OK if not report["errors"] else HTTPStatus.MULTI_STATUS
    json_response(handler, report, status)


class GateUIRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/tracks":
            try:
                handle_get_tracks(self)
            except Exception as error:  # noqa: BLE001
                json_response(self, {"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        super().do_GET()

    def do_POST(self):
        clean_path = self.path.split("?", 1)[0]
        try:
            if clean_path == "/api/extract":
                handle_post_extract(self)
                return
            if clean_path == "/api/build-plan":
                handle_post_build_plan(self)
                return
            if clean_path == "/api/apply":
                handle_post_apply(self)
                return
        except Exception as error:  # noqa: BLE001
            json_response(self, {"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the generic Pro Tools RMS gate UI.")
    parser.add_argument("--port", type=int, default=5178)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if not WEB_GATE_ROOT.is_dir():
        parser.error(f"UI directory does not exist: {WEB_GATE_ROOT}")

    handler = partial(GateUIRequestHandler, directory=str(WEB_GATE_ROOT))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {WEB_GATE_ROOT} at http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPTSL gate UI server stopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
