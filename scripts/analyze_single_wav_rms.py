#!/usr/bin/env python3
"""Stream a WAV file and save APPA-compatible RMS analysis artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
import unicodedata
from pathlib import Path

import numpy as np


DEFAULT_SAMPLE_RATE = 8_000
DEFAULT_WINDOW_SECONDS = 0.2
DEFAULT_HOP_SECONDS = 0.1
NOISE_PERCENTILE = 20
ACTIVE_PERCENTILE = 95
MIN_DYNAMIC_RANGE_DB = 12.0


def stream_rms(
    input_path: Path,
    sample_rate: int,
    window_seconds: float,
    hop_seconds: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    window_samples = max(1, round(window_seconds * sample_rate))
    hop_samples = max(1, round(hop_seconds * sample_rate))
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "pipe:1",
    ]

    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    if process.stdout is None:
        raise RuntimeError("ffmpeg stdout pipe was not created")

    buffer = np.empty(0, dtype=np.float32)
    rms_parts: list[np.ndarray] = []
    total_samples = 0
    chunk_bytes = 1_048_576 * np.dtype(np.float32).itemsize

    while True:
        raw = process.stdout.read(chunk_bytes)
        if not raw:
            break
        chunk = np.frombuffer(raw, dtype=np.float32)
        total_samples += len(chunk)
        buffer = np.concatenate((buffer, chunk))

        frame_count = 1 + (len(buffer) - window_samples) // hop_samples
        if frame_count <= 0:
            continue

        starts = np.arange(frame_count, dtype=np.int64) * hop_samples
        squared = np.square(buffer, dtype=np.float64)
        cumulative = np.concatenate(([0.0], np.cumsum(squared, dtype=np.float64)))
        energies = (cumulative[starts + window_samples] - cumulative[starts]) / window_samples
        rms_parts.append(np.sqrt(energies + 1e-12))
        buffer = buffer[frame_count * hop_samples :]

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg exited with status {return_code}")

    rms = np.concatenate(rms_parts) if rms_parts else np.empty(0, dtype=np.float64)
    rms_dbfs = 20.0 * np.log10(np.maximum(rms, 1e-12))
    frame_times = np.arange(len(rms_dbfs), dtype=np.float64) * hop_seconds
    return frame_times, rms_dbfs, total_samples


def percentile_summary(values: np.ndarray) -> dict[str, float]:
    percentiles = [1, 5, 10, 20, 25, 50, 75, 80, 90, 95, 99]
    result = {
        "minDbfs": round(float(np.min(values)), 3),
        "meanDbfs": round(float(np.mean(values)), 3),
        "stdDb": round(float(np.std(values)), 3),
        "maxDbfs": round(float(np.max(values)), 3),
    }
    for percentile in percentiles:
        result[f"p{percentile}Dbfs"] = round(float(np.percentile(values, percentile)), 3)
    return result


def minute_summary(times: np.ndarray, values: np.ndarray) -> list[dict[str, float]]:
    minute_indices = np.floor(times / 60.0).astype(np.int64)
    rows = []
    for minute in np.unique(minute_indices):
        selected = values[minute_indices == minute]
        rows.append(
            {
                "minute": int(minute),
                "startSeconds": float(minute * 60),
                "p10Dbfs": float(np.percentile(selected, 10)),
                "medianDbfs": float(np.percentile(selected, 50)),
                "p90Dbfs": float(np.percentile(selected, 90)),
            }
        )
    return rows


def save_plot(
    output_path: Path,
    input_path: Path,
    rms_dbfs: np.ndarray,
    minute_rows: list[dict[str, float]],
    noise_dbfs: float,
    active_dbfs: float,
    rms_gate_dbfs: float,
) -> None:
    import matplotlib.pyplot as plt

    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams["font.family"] = "Apple SD Gothic Neo"
    plt.rcParams["axes.unicode_minus"] = False
    display_name = unicodedata.normalize("NFC", input_path.name)
    figure, axes = plt.subplots(3, 1, figsize=(15, 12), constrained_layout=True)
    figure.suptitle(
        f"APPA Full-WAV RMS Analysis\n{display_name}",
        fontsize=18,
        fontweight="bold",
    )

    histogram = axes[0]
    histogram.hist(rms_dbfs, bins=120, color="#d8a82f", alpha=0.9, edgecolor="none")
    histogram.axvline(noise_dbfs, color="#3f8f83", linewidth=2, label=f"P20 noise {noise_dbfs:.1f} dBFS")
    histogram.axvline(np.median(rms_dbfs), color="#303640", linewidth=2, label=f"Median {np.median(rms_dbfs):.1f} dBFS")
    histogram.axvline(active_dbfs, color="#cf5a4b", linewidth=2, label=f"P95 active {active_dbfs:.1f} dBFS")
    histogram.axvline(rms_gate_dbfs, color="#6b4fa1", linewidth=2, linestyle="--", label=f"RMS gate {rms_gate_dbfs:.0f} dBFS")
    histogram.set_title("Frame RMS Distribution")
    histogram.set_xlabel("RMS level (dBFS)")
    histogram.set_ylabel("Frame count")
    histogram.legend(loc="upper left", ncols=2)

    trend = axes[1]
    minute = np.asarray([row["minute"] for row in minute_rows], dtype=np.float64)
    p10 = np.asarray([row["p10Dbfs"] for row in minute_rows])
    median = np.asarray([row["medianDbfs"] for row in minute_rows])
    p90 = np.asarray([row["p90Dbfs"] for row in minute_rows])
    trend.fill_between(minute, p10, p90, color="#77a69f", alpha=0.3, label="P10-P90 range")
    trend.plot(minute, median, color="#245c55", linewidth=1.5, label="Minute median")
    trend.axhline(rms_gate_dbfs, color="#6b4fa1", linewidth=1.5, linestyle="--", label="RMS gate")
    trend.set_title("RMS Trend by Minute")
    trend.set_xlabel("Timeline (minutes)")
    trend.set_ylabel("RMS level (dBFS)")
    trend.legend(loc="lower right")

    cdf = axes[2]
    sorted_values = np.sort(rms_dbfs)
    cumulative = np.arange(1, len(sorted_values) + 1) / len(sorted_values)
    cdf.plot(sorted_values, cumulative * 100.0, color="#bf553f", linewidth=2)
    cdf.axvline(rms_gate_dbfs, color="#6b4fa1", linewidth=1.5, linestyle="--")
    cdf.set_title("Cumulative RMS Distribution")
    cdf.set_xlabel("RMS level (dBFS)")
    cdf.set_ylabel("Frames at or below level (%)")
    cdf.set_ylim(0, 100)

    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a full WAV with the APPA RMS settings.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--window-seconds", type=float, default=DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--hop-seconds", type=float, default=DEFAULT_HOP_SECONDS)
    parser.add_argument("--rms-gate-dbfs", type=float, default=-55.0)
    args = parser.parse_args()

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    frame_times, rms_dbfs, decoded_samples = stream_rms(
        input_path,
        args.sample_rate,
        args.window_seconds,
        args.hop_seconds,
    )
    elapsed = time.perf_counter() - started
    if len(rms_dbfs) == 0:
        raise RuntimeError("No complete RMS frames were decoded")

    noise_dbfs = float(np.percentile(rms_dbfs, NOISE_PERCENTILE))
    active_dbfs = float(np.percentile(rms_dbfs, ACTIVE_PERCENTILE))
    dynamic_range_db = max(MIN_DYNAMIC_RANGE_DB, active_dbfs - noise_dbfs)
    scores = np.clip((rms_dbfs - noise_dbfs) / dynamic_range_db, 0.0, 1.0)
    passes_rms_gate = rms_dbfs >= args.rms_gate_dbfs
    minute_rows = minute_summary(frame_times, rms_dbfs)

    summary = {
        "input": {
            "path": str(input_path),
            "sizeBytes": input_path.stat().st_size,
            "durationSeconds": round(decoded_samples / args.sample_rate, 6),
        },
        "settings": {
            "analysisSampleRate": args.sample_rate,
            "windowSeconds": args.window_seconds,
            "hopSeconds": args.hop_seconds,
            "noisePercentile": NOISE_PERCENTILE,
            "activePercentile": ACTIVE_PERCENTILE,
            "minDynamicRangeDb": MIN_DYNAMIC_RANGE_DB,
            "rmsGateDbfs": args.rms_gate_dbfs,
        },
        "performance": {
            "elapsedSeconds": round(elapsed, 3),
            "audioToWallClockRatio": round((decoded_samples / args.sample_rate) / elapsed, 2),
            "decodedSamples": decoded_samples,
            "frameCount": len(rms_dbfs),
        },
        "normalization": {
            "noiseDbfs": round(noise_dbfs, 3),
            "activeDbfs": round(active_dbfs, 3),
            "dynamicRangeDb": round(dynamic_range_db, 3),
        },
        "distribution": percentile_summary(rms_dbfs),
        "thresholds": {
            "framesAtOrAboveRmsGate": int(np.count_nonzero(passes_rms_gate)),
            "percentAtOrAboveRmsGate": round(float(np.mean(passes_rms_gate) * 100.0), 3),
            "framesAtOrAboveActivityScore070": int(np.count_nonzero(scores >= 0.7)),
            "percentAtOrAboveActivityScore070": round(float(np.mean(scores >= 0.7) * 100.0), 3),
        },
    }

    summary_path = output_dir / "summary.json"
    frames_path = output_dir / "rms_frames.csv"
    minutes_path = output_dir / "rms_by_minute.csv"
    npz_path = output_dir / "rms_frames.npz"
    plot_path = output_dir / "rms_distribution.png"

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with frames_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["time_seconds", "rms_dbfs", "activity_score", "passes_rms_gate"])
        for frame_time, rms_value, score, passes in zip(frame_times, rms_dbfs, scores, passes_rms_gate):
            writer.writerow([f"{frame_time:.3f}", f"{rms_value:.3f}", f"{score:.4f}", int(passes)])

    with minutes_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(minute_rows[0]))
        writer.writeheader()
        writer.writerows(minute_rows)

    np.savez_compressed(
        npz_path,
        times=frame_times.astype(np.float32),
        rms_dbfs=rms_dbfs.astype(np.float32),
        activity_scores=scores.astype(np.float32),
        passes_rms_gate=passes_rms_gate,
    )
    save_plot(plot_path, input_path, rms_dbfs, minute_rows, noise_dbfs, active_dbfs, args.rms_gate_dbfs)

    print(json.dumps({"summary": summary, "outputs": {
        "summary": str(summary_path),
        "framesCsv": str(frames_path),
        "minutesCsv": str(minutes_path),
        "framesNpz": str(npz_path),
        "plot": str(plot_path),
    }}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
