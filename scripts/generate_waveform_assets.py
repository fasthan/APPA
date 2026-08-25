#!/usr/bin/env python3
"""Generate lightweight waveform JSON files for APPA's browser test UI."""

from __future__ import annotations

import array
import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "미우새"
OUT_DIR = ROOT / "web" / "assets" / "waveforms"
SAMPLE_RATE = 800
WINDOW_SECONDS = 0.25
INT16_MAX = 32768


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


def generate_waveform(source: Path, target: Path, sample_rate: int, window_seconds: float) -> None:
    window_samples = max(1, int(sample_rate * window_seconds))
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
            str(sample_rate),
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
        samples = array.array("h")
        samples.frombytes(chunk)
        if not samples:
            continue
        mins.append(round(max(-1.0, min(samples) / INT16_MAX), 4))
        maxs.append(round(min(1.0, max(samples) / INT16_MAX), 4))

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg failed for {source} with exit code {return_code}")

    payload = {
        "source": source.name,
        "duration": probe_duration(source),
        "sampleRate": sample_rate,
        "windowSeconds": window_seconds,
        "mins": mins,
        "maxs": maxs,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate APPA waveform JSON assets.")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--pattern", default="*.wav")
    parser.add_argument("--expected-count", type=int, default=4)
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE)
    parser.add_argument("--window-seconds", type=float, default=WINDOW_SECONDS)
    args = parser.parse_args()

    source_dir = args.source_dir if args.source_dir.is_absolute() else ROOT / args.source_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir

    out_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(source_dir.glob(args.pattern))
    if len(sources) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} files in {source_dir}, found {len(sources)}")

    for index, source in enumerate(sources, start=1):
        target = out_dir / f"track{index}.json"
        print(f"Generating {target.name} from {source.name}")
        generate_waveform(source, target, args.sample_rate, args.window_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
