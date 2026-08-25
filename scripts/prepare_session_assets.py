#!/usr/bin/env python3
"""Prepare full-length APPA browser proxy, waveform, and activity assets."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import unicodedata
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
TRACK_COLORS = ["#e8c15b", "#57c1a7", "#86a8e7", "#e36b5d"]
SESSION_ID = "miuse-full"
SESSION_NAME = "미우새 전체 길이 프로젝트 세션"
SESSION_SUBTITLE = "미우새 4ch 전체 세션 · full-length proxy"
SOURCE_DIR = ROOT / "미우새"
SOURCE_PATTERNS = ["서장훈_02", "박중훈_02", "신동엽_02", "희철맘_02"]
ACTIVITY_SAMPLE_RATE = 8000
ACTIVITY_WINDOW_SECONDS = 0.2
ACTIVITY_HOP_SECONDS = 0.1
ACTIVITY_NOISE_PERCENTILE = 20.0
ACTIVITY_ACTIVE_PERCENTILE = 95.0
ACTIVITY_MIN_DYNAMIC_RANGE_DB = 12.0
WAVEFORM_SAMPLE_RATE = 800
WAVEFORM_WINDOW_SECONDS = 0.25
INT16_MAX = 32768


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFC", value).lower()


def dbfs(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-12))


def web_path(path: Path) -> str:
    return "./" + path.relative_to(WEB_ROOT).as_posix()


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def find_sources(requested_names: list[str]) -> list[Path]:
    candidates = sorted(SOURCE_DIR.glob("*.wav"))
    if not candidates:
        raise FileNotFoundError(f"No WAV files found in {SOURCE_DIR}")

    requested = [normalize_name(Path(name).name).removesuffix(".wav") for name in requested_names]
    sources: list[Path] = []
    for pattern in SOURCE_PATTERNS:
        normalized_pattern = normalize_name(pattern)
        pool = candidates
        if requested:
            requested_matches = [name for name in requested if normalized_pattern in name]
            if requested_matches:
                pool = [candidate for candidate in candidates if normalize_name(candidate.stem) in requested_matches]

        match = next((candidate for candidate in pool if normalized_pattern in normalize_name(candidate.stem)), None)
        if match is None:
            raise FileNotFoundError(f"Could not find source matching {pattern}")
        sources.append(match)

    return sources


def ensure_proxy(source: Path, target: Path) -> str:
    if target.exists() and target.stat().st_size > 0:
        return "existing"

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "48000",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "48k",
            str(tmp),
        ],
        check=True,
    )
    tmp.replace(target)
    return "generated"


def ensure_waveform(source: Path, target: Path) -> str:
    if target.exists() and target.stat().st_size > 0:
        return "existing"

    target.parent.mkdir(parents=True, exist_ok=True)
    window_samples = max(1, int(WAVEFORM_SAMPLE_RATE * WAVEFORM_WINDOW_SECONDS))
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            str(WAVEFORM_SAMPLE_RATE),
            "-f",
            "s16le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("ffmpeg stdout was not available")

    mins: list[float] = []
    maxs: list[float] = []
    window_bytes = window_samples * 2
    while True:
        chunk = process.stdout.read(window_bytes)
        if not chunk:
            break
        samples = np.frombuffer(chunk, dtype=np.int16)
        if samples.size == 0:
            continue
        mins.append(round(max(-1.0, float(np.min(samples)) / INT16_MAX), 4))
        maxs.append(round(min(1.0, float(np.max(samples)) / INT16_MAX), 4))

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg failed for {source} with exit code {return_code}")

    payload = {
        "source": source.name,
        "duration": probe_duration(source),
        "sampleRate": WAVEFORM_SAMPLE_RATE,
        "windowSeconds": WAVEFORM_WINDOW_SECONDS,
        "mins": mins,
        "maxs": maxs,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return "generated"


def stream_rms_db(path: Path) -> tuple[list[float], list[float]]:
    window_samples = max(1, int(round(ACTIVITY_WINDOW_SECONDS * ACTIVITY_SAMPLE_RATE)))
    hop_samples = max(1, int(round(ACTIVITY_HOP_SECONDS * ACTIVITY_SAMPLE_RATE)))
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(ACTIVITY_SAMPLE_RATE),
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("ffmpeg stdout was not available")

    rms_values: list[float] = []
    starts: list[float] = []
    buffer = np.empty(0, dtype=np.float32)
    absolute_start = 0
    chunk_bytes = ACTIVITY_SAMPLE_RATE * 20 * 4

    while True:
        chunk = process.stdout.read(chunk_bytes)
        if not chunk:
            break
        chunk_samples = np.frombuffer(chunk, dtype=np.float32)
        if chunk_samples.size == 0:
            continue
        buffer = np.concatenate((buffer, chunk_samples))
        offset = 0
        while offset + window_samples <= buffer.size:
            frame = buffer[offset : offset + window_samples]
            rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)) + 1e-12))
            rms_values.append(round(dbfs(rms), 2))
            starts.append(round((absolute_start + offset) / ACTIVITY_SAMPLE_RATE, 3))
            offset += hop_samples
        if offset > 0:
            buffer = buffer[offset:]
            absolute_start += offset

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg failed for {path} with exit code {return_code}")
    return rms_values, starts


def normalize_activity_scores(rms_values: list[float]) -> tuple[list[float], dict[str, float]]:
    data = np.asarray(rms_values, dtype=np.float64)
    noise_db = float(np.percentile(data, ACTIVITY_NOISE_PERCENTILE))
    active_db = float(np.percentile(data, ACTIVITY_ACTIVE_PERCENTILE))
    dynamic_range_db = max(ACTIVITY_MIN_DYNAMIC_RANGE_DB, active_db - noise_db)
    scores = np.clip((data - noise_db) / dynamic_range_db, 0.0, 1.0)
    return [round(float(score), 4) for score in scores], {
        "noiseDbfs": round(noise_db, 3),
        "activeDbfs": round(active_db, 3),
        "dynamicRangeDb": round(dynamic_range_db, 3),
    }


def ensure_analysis(tracks: list[dict[str, object]], analysis_dir: Path) -> tuple[str, Path, Path]:
    activity_path = analysis_dir / "activity.json"
    original_rms_path = analysis_dir / "original_rms.json"
    if activity_path.exists() and original_rms_path.exists():
        return "existing", activity_path, original_rms_path

    analysis_dir.mkdir(parents=True, exist_ok=True)
    raw_rms_by_track: list[list[float]] = []
    starts_by_track: list[list[float]] = []
    min_count: int | None = None
    for track in tracks:
        rms_values, starts = stream_rms_db(Path(str(track["audioPath"])))
        raw_rms_by_track.append(rms_values)
        starts_by_track.append(starts)
        min_count = len(rms_values) if min_count is None else min(min_count, len(rms_values))

    if min_count is None or min_count == 0:
        raise RuntimeError("No RMS frames were generated")

    starts = starts_by_track[0][:min_count]
    times = [round(start + ACTIVITY_WINDOW_SECONDS / 2, 3) for start in starts]
    series: dict[str, dict[str, object]] = {}
    sources = []

    for index, track in enumerate(tracks):
        rms_values = raw_rms_by_track[index][:min_count]
        scores, normalization = normalize_activity_scores(rms_values)
        data = np.asarray(rms_values, dtype=np.float64)
        track_id = str(track["id"])
        series[track_id] = {
            "trackId": track_id,
            "name": track["name"],
            "rmsDbfs": rms_values,
            "summary": {
                "minDbfs": round(float(np.min(data)), 2),
                "p10Dbfs": round(float(np.percentile(data, 10)), 2),
                "p20Dbfs": round(float(np.percentile(data, 20)), 2),
                "p50Dbfs": round(float(np.percentile(data, 50)), 2),
                "p80Dbfs": round(float(np.percentile(data, 80)), 2),
                "p90Dbfs": round(float(np.percentile(data, 90)), 2),
                "maxDbfs": round(float(np.max(data)), 2),
            },
        }
        sources.append(
            {
                "source": index + 1,
                "matchedTrack": track_id,
                "matchedLabel": track["name"],
                "matchConfidence": 1,
                "matchMargin": 1,
                "normalization": normalization,
                "scores": scores,
            }
        )

    settings = {
        "windowSeconds": ACTIVITY_WINDOW_SECONDS,
        "hopSeconds": ACTIVITY_HOP_SECONDS,
        "noisePercentile": ACTIVITY_NOISE_PERCENTILE,
        "activePercentile": ACTIVITY_ACTIVE_PERCENTILE,
        "minDynamicRangeDb": ACTIVITY_MIN_DYNAMIC_RANGE_DB,
    }
    duration = round(starts[-1] + ACTIVITY_WINDOW_SECONDS, 3)
    original_rms_payload = {
        "version": 1,
        "kind": "server_original_track_rms",
        "settings": {"sampleRate": ACTIVITY_SAMPLE_RATE, **settings},
        "duration": duration,
        "starts": starts,
        "times": times,
        "series": series,
    }
    activity_payload = {
        "version": 1,
        "kind": "server_source_activity",
        "settings": settings,
        "duration": duration,
        "starts": starts,
        "times": times,
        "algorithms": {"local-rms": {"sources": sources}},
    }
    original_rms_path.write_text(json.dumps(original_rms_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    activity_path.write_text(json.dumps(activity_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return "generated", activity_path, original_rms_path


def prepare_session(requested_names: list[str]) -> dict[str, object]:
    sources = find_sources(requested_names)
    proxy_statuses = []
    waveform_statuses = []
    tracks: list[dict[str, object]] = []
    for index, source in enumerate(sources, start=1):
        track_id = f"track{index}"
        proxy_path = WEB_ROOT / "assets" / "audio" / f"{track_id}.mp3"
        waveform_path = WEB_ROOT / "assets" / "waveforms" / f"{track_id}.json"
        proxy_statuses.append(ensure_proxy(source, proxy_path))
        waveform_statuses.append(ensure_waveform(proxy_path, waveform_path))
        tracks.append(
            {
                "id": track_id,
                "name": f"{index} {source.stem.split(' ', 1)[-1].replace('_02', '')}",
                "speaker": "Full proxy",
                "sourceName": source.name,
                "audio": web_path(proxy_path),
                "waveform": web_path(waveform_path),
                "audioPath": str(proxy_path),
                "color": TRACK_COLORS[index - 1],
            }
        )

    analysis_dir = WEB_ROOT / "assets" / "analysis" / SESSION_ID
    original_rms_path = analysis_dir / "original_rms.json"
    original_rms_status = "existing" if original_rms_path.exists() and original_rms_path.stat().st_size > 0 else "not-generated"
    for track in tracks:
        track.pop("audioPath", None)

    manifest = {
        "id": SESSION_ID,
        "name": SESSION_NAME,
        "subtitle": SESSION_SUBTITLE,
        "tracks": tracks,
        "status": {
            "proxy": "generated" if "generated" in proxy_statuses else "existing",
            "waveform": "generated" if "generated" in waveform_statuses else "existing",
            "analysis": "not-run",
            "originalRms": original_rms_status,
            "shortProxyBackup": "./assets/backup/miuse-27m-33m-short-proxy/",
        },
    }
    if original_rms_status == "existing":
        manifest["originalRmsUrl"] = web_path(original_rms_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file-name", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(prepare_session(args.file_name), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
