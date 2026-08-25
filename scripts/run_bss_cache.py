#!/usr/bin/env python3
"""Run and cache BSS analysis for a selected APPA timeline range."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from generate_waveform_assets import generate_waveform
from run_cpu_bss_experiment import (
    build_algorithms,
    corrcoef_rows,
    invert_stft,
    make_stft,
    mean_abs_offdiag,
    output_input_mapping,
    peak_normalize,
    rms_envelope,
    signal_stats,
)


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
TRACK_COUNT = 4
DEFAULT_SESSION_ID = "miuse-full"
DEFAULT_AUDIO_DIR = WEB_ROOT / "assets" / "audio"
DEFAULT_ANALYSIS_ROOT = WEB_ROOT / "assets" / "analysis"
DEFAULT_WAVEFORM_ROOT = WEB_ROOT / "assets" / "waveforms"
BSS_WAVEFORM_SAMPLE_RATE = 4000
BSS_WAVEFORM_WINDOW_SECONDS = 0.02
ACTIVITY_WINDOW_SECONDS = 0.2
ACTIVITY_HOP_SECONDS = 0.1
ACTIVITY_NOISE_PERCENTILE = 20.0
ACTIVITY_ACTIVE_PERCENTILE = 95.0
ACTIVITY_MIN_DYNAMIC_RANGE_DB = 12.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run cached BSS analysis for an APPA selection.")
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--analysis-root", type=Path, default=DEFAULT_ANALYSIS_ROOT)
    parser.add_argument("--waveform-root", type=Path, default=DEFAULT_WAVEFORM_ROOT)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--sample-rate", type=int, default=8000)
    parser.add_argument("--n-fft", type=int, default=1024)
    parser.add_argument("--hop-length", type=int, default=256)
    parser.add_argument("--algorithms", nargs="+", default=["auxiva"], choices=["auxiva", "ilrma", "fastmnmf"])
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def web_path(path: Path) -> str:
    return "./" + path.relative_to(WEB_ROOT).as_posix()


def db(value: float) -> float:
    return 20 * math.log10(max(float(value), 1e-12))


def cache_key(args: argparse.Namespace) -> str:
    start_ms = int(round(max(0.0, args.start) * 1000))
    duration_ms = int(round(max(0.1, args.duration) * 1000))
    algorithms = "-".join(args.algorithms)
    return f"s{start_ms:010d}_d{duration_ms:010d}_sr{args.sample_rate}_fft{args.n_fft}_hop{args.hop_length}_{algorithms}"


def manifest_is_complete(manifest_path: Path) -> bool:
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False

    required = [manifest_path]
    activity_url = manifest.get("activityUrl")
    report_url = manifest.get("reportUrl")
    if activity_url:
        required.append(WEB_ROOT / activity_url.removeprefix("./"))
    if report_url:
        required.append(WEB_ROOT / report_url.removeprefix("./"))

    for algorithm in (manifest.get("algorithms") or {}).values():
        for source in algorithm.get("sources", []):
            for key in ("audioUrl", "waveformUrl"):
                url = source.get(key)
                if url:
                    required.append(WEB_ROOT / url.removeprefix("./"))

    return all(path.exists() and path.stat().st_size > 0 for path in required)


def ffmpeg_decode_mono(path: Path, sample_rate: int, start: float, duration: float) -> np.ndarray:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(path),
        "-t",
        f"{duration:.3f}",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-af",
        "highpass=f=80,lowpass=f=3800",
        "-f",
        "f32le",
        "pipe:1",
    ]
    raw = subprocess.check_output(cmd)
    return np.frombuffer(raw, dtype=np.float32).copy()


def load_tracks(audio_dir: Path, sample_rate: int, start: float, duration: float) -> np.ndarray:
    tracks = []
    for index in range(1, TRACK_COUNT + 1):
        path = audio_dir / f"track{index}.mp3"
        if not path.exists():
            raise FileNotFoundError(path)
        tracks.append(ffmpeg_decode_mono(path, sample_rate=sample_rate, start=start, duration=duration))

    min_len = min(len(track) for track in tracks)
    if min_len <= 0:
        raise RuntimeError("No audio samples decoded for BSS analysis")
    return np.stack([track[:min_len] for track in tracks], axis=0).astype(np.float64)


def frame_rms(signal: np.ndarray, sample_rate: int) -> tuple[list[float], list[float]]:
    window = max(1, int(round(ACTIVITY_WINDOW_SECONDS * sample_rate)))
    hop = max(1, int(round(ACTIVITY_HOP_SECONDS * sample_rate)))
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


def normalize_activity(rms_values: list[float]) -> tuple[list[float], dict[str, float]]:
    rms_db = np.asarray([db(value) for value in rms_values], dtype=np.float64)
    noise_db = float(np.percentile(rms_db, ACTIVITY_NOISE_PERCENTILE))
    active_db = float(np.percentile(rms_db, ACTIVITY_ACTIVE_PERCENTILE))
    dynamic_range_db = max(ACTIVITY_MIN_DYNAMIC_RANGE_DB, active_db - noise_db)
    scores = np.clip((rms_db - noise_db) / dynamic_range_db, 0.0, 1.0)
    return [round(float(score), 4) for score in scores], {
        "noiseDbfs": round(noise_db, 3),
        "activeDbfs": round(active_db, 3),
        "dynamicRangeDb": round(dynamic_range_db, 3),
    }


def build_activity_payload(report: dict, analysis_dir: Path, timeline_start: float) -> dict:
    output = {
        "version": 1,
        "kind": "bss_source_activity",
        "settings": {
            "windowSeconds": ACTIVITY_WINDOW_SECONDS,
            "hopSeconds": ACTIVITY_HOP_SECONDS,
            "noisePercentile": ACTIVITY_NOISE_PERCENTILE,
            "activePercentile": ACTIVITY_ACTIVE_PERCENTILE,
            "minDynamicRangeDb": ACTIVITY_MIN_DYNAMIC_RANGE_DB,
            "rangeStart": round(timeline_start, 3),
            "rangeEnd": round(timeline_start + report["duration_seconds"], 3),
        },
        "duration": round(report["duration_seconds"], 3),
        "range": {
            "start": round(timeline_start, 3),
            "end": round(timeline_start + report["duration_seconds"], 3),
            "duration": round(report["duration_seconds"], 3),
        },
        "algorithms": {},
    }

    common_starts: list[float] | None = None
    for algorithm in report["algorithms"]:
        algorithm_id = algorithm["name"]
        source_root = analysis_dir / algorithm_id
        sources = []

        for mapping in algorithm["mapping"]:
            source_index = int(mapping["source"])
            signal, sample_rate = sf.read(source_root / f"source{source_index}.wav", dtype="float64")
            if signal.ndim > 1:
                signal = np.mean(signal, axis=1)

            rms_values, local_starts = frame_rms(signal, sample_rate)
            scores, normalization = normalize_activity(rms_values)
            if common_starts is None:
                common_starts = [round(timeline_start + value, 3) for value in local_starts]

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
    output["times"] = [round(start + ACTIVITY_WINDOW_SECONDS / 2, 3) for start in output["starts"]]
    return output


def write_manifest(
    *,
    manifest_path: Path,
    session_id: str,
    key: str,
    start: float,
    duration: float,
    analysis_dir: Path,
    waveform_dir: Path,
    report_path: Path,
    activity_path: Path,
    algorithms: list[str],
    cached: bool,
) -> dict:
    manifest = {
        "version": 1,
        "kind": "bss_analysis_cache",
        "id": key,
        "sessionId": session_id,
        "status": "cached" if cached else "generated",
        "range": {
            "start": round(start, 3),
            "end": round(start + duration, 3),
            "duration": round(duration, 3),
        },
        "activityUrl": web_path(activity_path),
        "reportUrl": web_path(report_path),
        "algorithms": {},
    }

    for algorithm_id in algorithms:
        manifest["algorithms"][algorithm_id] = {"sources": []}
        for source_index in range(1, TRACK_COUNT + 1):
            manifest["algorithms"][algorithm_id]["sources"].append(
                {
                    "source": source_index,
                    "audioUrl": web_path(analysis_dir / algorithm_id / f"source{source_index}.wav"),
                    "waveformUrl": web_path(waveform_dir / algorithm_id / f"track{source_index}.json"),
                }
            )

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def run_analysis(args: argparse.Namespace, analysis_dir: Path, waveform_dir: Path) -> dict:
    audio = load_tracks(args.audio_dir, sample_rate=args.sample_rate, start=args.start, duration=args.duration)
    duration_seconds = audio.shape[1] / args.sample_rate
    spec = make_stft(audio, sample_rate=args.sample_rate, n_fft=args.n_fft, hop_length=args.hop_length)
    input_env_corr = corrcoef_rows(np.log10(rms_envelope(audio, args.sample_rate) + 1e-8))
    input_wave_corr = corrcoef_rows(audio)
    report = {
        "audio_dir": str(args.audio_dir),
        "output_dir": str(analysis_dir),
        "timeline_start_seconds": args.start,
        "duration_seconds": duration_seconds,
        "sample_rate": args.sample_rate,
        "n_fft": args.n_fft,
        "hop_length": args.hop_length,
        "input_metrics": {
            "mean_abs_envelope_corr_offdiag": mean_abs_offdiag(input_env_corr),
            "mean_abs_waveform_corr_offdiag": mean_abs_offdiag(input_wave_corr),
            "envelope_corr_matrix": input_env_corr.tolist(),
            "waveform_corr_matrix": input_wave_corr.tolist(),
            "stats": signal_stats(audio),
        },
        "algorithms": [],
    }

    for algorithm in build_algorithms(args.algorithms):
        started_at = time.perf_counter()
        rng = np.random.default_rng(0)
        separator = algorithm.factory(rng)
        separated_spec = separator(spec, n_iter=algorithm.n_iter)
        separated = invert_stft(
            separated_spec,
            sample_rate=args.sample_rate,
            n_fft=args.n_fft,
            hop_length=args.hop_length,
            length=audio.shape[1],
        )
        runtime = time.perf_counter() - started_at
        separated = peak_normalize(separated)

        algorithm_dir = analysis_dir / algorithm.name
        algorithm_waveform_dir = waveform_dir / algorithm.name
        algorithm_dir.mkdir(parents=True, exist_ok=True)
        algorithm_waveform_dir.mkdir(parents=True, exist_ok=True)

        for source_index, signal in enumerate(separated, start=1):
            source_path = algorithm_dir / f"source{source_index}.wav"
            sf.write(source_path, signal, args.sample_rate)
            generate_waveform(
                source_path,
                algorithm_waveform_dir / f"track{source_index}.json",
                BSS_WAVEFORM_SAMPLE_RATE,
                BSS_WAVEFORM_WINDOW_SECONDS,
            )

        output_env_corr = corrcoef_rows(np.log10(rms_envelope(separated, args.sample_rate) + 1e-8))
        output_wave_corr = corrcoef_rows(separated)
        mapping, mapping_matrix = output_input_mapping(audio[:, : separated.shape[1]], separated, args.sample_rate)
        report["algorithms"].append(
            {
                "name": algorithm.name,
                "description": algorithm.description,
                "runtime_seconds": runtime,
                "output_dir": str(algorithm_dir),
                "metrics": {
                    "mean_abs_envelope_corr_offdiag": mean_abs_offdiag(output_env_corr),
                    "mean_abs_waveform_corr_offdiag": mean_abs_offdiag(output_wave_corr),
                    "envelope_corr_matrix": output_env_corr.tolist(),
                    "waveform_corr_matrix": output_wave_corr.tolist(),
                    "stats": signal_stats(separated),
                },
                "mapping": mapping,
                "output_to_input_envelope_corr_matrix": mapping_matrix.tolist(),
            }
        )

    return report


def main() -> int:
    args = parse_args()
    args.audio_dir = resolve_path(args.audio_dir)
    args.analysis_root = resolve_path(args.analysis_root)
    args.waveform_root = resolve_path(args.waveform_root)
    args.start = max(0.0, args.start)
    args.duration = max(1.0, args.duration)

    key = cache_key(args)
    analysis_dir = args.analysis_root / args.session_id / "bss" / key
    waveform_dir = args.waveform_root / args.session_id / "bss" / key
    manifest_path = analysis_dir / "manifest.json"
    report_path = analysis_dir / "report.json"
    activity_path = analysis_dir / "activity.json"

    if not args.force and manifest_is_complete(manifest_path):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "cached"
        print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
        return 0

    analysis_dir.mkdir(parents=True, exist_ok=True)
    waveform_dir.mkdir(parents=True, exist_ok=True)
    report = run_analysis(args, analysis_dir, waveform_dir)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    activity = build_activity_payload(report, analysis_dir, args.start)
    activity_path.write_text(json.dumps(activity, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    manifest = write_manifest(
        manifest_path=manifest_path,
        session_id=args.session_id,
        key=key,
        start=args.start,
        duration=report["duration_seconds"],
        analysis_dir=analysis_dir,
        waveform_dir=waveform_dir,
        report_path=report_path,
        activity_path=activity_path,
        algorithms=args.algorithms,
        cached=False,
    )
    print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
