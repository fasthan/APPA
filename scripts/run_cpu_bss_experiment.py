#!/usr/bin/env python3
"""Run CPU-based blind source separation experiments on APPA multitrack audio.

This is intentionally an experiment runner rather than production code.  The
goal is to create listenable stems and a few proxy metrics that help us decide
whether BSS is useful for lavalier crosstalk cleanup.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
from scipy.optimize import linear_sum_assignment
from scipy.signal import istft, stft


TRACK_LABELS = ["1 서장훈", "2 박중훈", "3 신동엽", "4 희철맘"]


@dataclass(frozen=True)
class BSSAlgorithm:
    name: str
    description: str
    factory: Callable[[np.random.Generator], object]
    n_iter: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=Path("web/assets/audio/miuse-27m-33m"),
        help="Directory containing track1.mp3 ... track4.mp3.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("experiments/bss_cpu/miuse-27m-33m"),
        help="Directory where separated wavs and reports are written.",
    )
    parser.add_argument("--sample-rate", type=int, default=8000)
    parser.add_argument("--n-fft", type=int, default=1024)
    parser.add_argument("--hop-length", type=int, default=256)
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional duration in seconds for a quick smoke test.",
    )
    parser.add_argument(
        "--algorithms",
        nargs="+",
        default=["auxiva", "ilrma", "fastmnmf"],
        choices=["auxiva", "ilrma", "fastmnmf"],
    )
    return parser.parse_args()


def ffmpeg_decode_mono(path: Path, sample_rate: int, duration: float | None) -> np.ndarray:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-af",
        "highpass=f=80,lowpass=f=3800",
    ]

    if duration is not None:
        cmd.extend(["-t", str(duration)])

    cmd.extend(["-f", "f32le", "pipe:1"])

    raw = subprocess.check_output(cmd)
    return np.frombuffer(raw, dtype=np.float32).copy()


def load_tracks(audio_dir: Path, sample_rate: int, duration: float | None) -> np.ndarray:
    tracks = []

    for index in range(1, 5):
        path = audio_dir / f"track{index}.mp3"
        if not path.exists():
            raise FileNotFoundError(path)
        tracks.append(ffmpeg_decode_mono(path, sample_rate=sample_rate, duration=duration))

    min_len = min(len(track) for track in tracks)
    stacked = np.stack([track[:min_len] for track in tracks], axis=0)
    return stacked.astype(np.float64)


def make_stft(audio: np.ndarray, sample_rate: int, n_fft: int, hop_length: int) -> np.ndarray:
    specs = []
    for channel in audio:
        _, _, zxx = stft(
            channel,
            fs=sample_rate,
            window="hann",
            nperseg=n_fft,
            noverlap=n_fft - hop_length,
            boundary="zeros",
            padded=True,
        )
        specs.append(zxx)
    return np.stack(specs, axis=0)


def invert_stft(spec: np.ndarray, sample_rate: int, n_fft: int, hop_length: int, length: int) -> np.ndarray:
    outputs = []
    for source in spec:
        _, signal = istft(
            source,
            fs=sample_rate,
            window="hann",
            nperseg=n_fft,
            noverlap=n_fft - hop_length,
            input_onesided=True,
            boundary=True,
        )
        outputs.append(signal[:length])

    min_len = min(len(output) for output in outputs)
    return np.stack([output[:min_len] for output in outputs], axis=0)


def peak_normalize(audio: np.ndarray, peak: float = 0.98) -> np.ndarray:
    max_abs = float(np.max(np.abs(audio)))
    if max_abs <= 1e-12:
        return audio
    return audio * (peak / max_abs)


def rms_envelope(audio: np.ndarray, sample_rate: int, window_sec: float = 0.1, hop_sec: float = 0.05) -> np.ndarray:
    window = max(1, int(round(window_sec * sample_rate)))
    hop = max(1, int(round(hop_sec * sample_rate)))
    frame_count = max(0, 1 + (audio.shape[-1] - window) // hop)
    envelopes = np.empty((audio.shape[0], frame_count), dtype=np.float64)

    for frame_index in range(frame_count):
        start = frame_index * hop
        frame = audio[:, start : start + window]
        envelopes[:, frame_index] = np.sqrt(np.mean(frame * frame, axis=1) + 1e-12)

    return envelopes


def corrcoef_rows(features: np.ndarray) -> np.ndarray:
    centered = features - np.mean(features, axis=1, keepdims=True)
    denom = np.linalg.norm(centered, axis=1, keepdims=True)
    denom = np.maximum(denom, 1e-12)
    normed = centered / denom
    return normed @ normed.T


def mean_abs_offdiag(matrix: np.ndarray) -> float:
    mask = ~np.eye(matrix.shape[0], dtype=bool)
    return float(np.mean(np.abs(matrix[mask])))


def output_input_mapping(input_audio: np.ndarray, output_audio: np.ndarray, sample_rate: int) -> tuple[list[dict], np.ndarray]:
    input_env = np.log10(rms_envelope(input_audio, sample_rate) + 1e-8)
    output_env = np.log10(rms_envelope(output_audio, sample_rate) + 1e-8)
    frame_count = min(input_env.shape[1], output_env.shape[1])
    input_env = input_env[:, :frame_count]
    output_env = output_env[:, :frame_count]

    corr = np.empty((output_env.shape[0], input_env.shape[0]), dtype=np.float64)
    for out_idx in range(output_env.shape[0]):
        for in_idx in range(input_env.shape[0]):
            pair = corrcoef_rows(np.stack([output_env[out_idx], input_env[in_idx]], axis=0))
            corr[out_idx, in_idx] = abs(float(pair[0, 1]))

    rows, cols = linear_sum_assignment(-corr)
    unique_assignment = {int(out_idx): int(in_idx) for out_idx, in_idx in zip(rows, cols)}
    mapping = []
    for out_idx in range(output_env.shape[0]):
        in_idx = int(np.argmax(corr[out_idx]))
        ordered = np.sort(corr[out_idx])[::-1]
        best = float(corr[out_idx, in_idx])
        second = float(ordered[1]) if len(ordered) > 1 else 0.0
        mapping.append(
            {
                "source": int(out_idx + 1),
                "best_input": int(in_idx + 1),
                "best_label": TRACK_LABELS[in_idx],
                "envelope_corr": best,
                "margin_to_second": best - second,
                "unique_assignment_input": int(unique_assignment[out_idx] + 1),
                "unique_assignment_label": TRACK_LABELS[unique_assignment[out_idx]],
            }
        )

    return mapping, corr


def signal_stats(audio: np.ndarray) -> list[dict]:
    stats = []
    for index, signal in enumerate(audio):
        rms = float(np.sqrt(np.mean(signal * signal) + 1e-12))
        peak = float(np.max(np.abs(signal)))
        stats.append(
            {
                "source": index + 1,
                "rms_dbfs": 20 * math.log10(max(rms, 1e-12)),
                "peak_dbfs": 20 * math.log10(max(peak, 1e-12)),
                "silent_ratio_below_-60dbfs": float(np.mean(np.abs(signal) < 10 ** (-60 / 20))),
            }
        )
    return stats


def build_algorithms(names: list[str]) -> list[BSSAlgorithm]:
    from ssspy.bss.ilrma import GaussILRMA
    from ssspy.bss.iva import AuxLaplaceIVA
    from ssspy.bss.mnmf import FastGaussMNMF

    algorithms = {
        "auxiva": BSSAlgorithm(
            name="auxiva",
            description="AuxIVA, independent-vector-analysis BSS with iterative projection",
            factory=lambda rng: AuxLaplaceIVA(spatial_algorithm="IP", scale_restoration=True, reference_id=0),
            n_iter=50,
        ),
        "ilrma": BSSAlgorithm(
            name="ilrma",
            description="Gaussian ILRMA, IVA + low-rank NMF source model",
            factory=lambda rng: GaussILRMA(
                n_basis=2,
                spatial_algorithm="IP",
                source_algorithm="MM",
                scale_restoration=True,
                reference_id=0,
                rng=rng,
            ),
            n_iter=40,
        ),
        "fastmnmf": BSSAlgorithm(
            name="fastmnmf",
            description="Fast Gaussian MNMF, multichannel NMF with jointly diagonalizable spatial model",
            factory=lambda rng: FastGaussMNMF(
                n_basis=2,
                n_sources=4,
                diagonalizer_algorithm="IP",
                reference_id=0,
                rng=rng,
            ),
            n_iter=25,
        ),
    }
    return [algorithms[name] for name in names]


def write_report(report: dict, out_dir: Path) -> None:
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# CPU BSS Experiment Report",
        "",
        f"- Audio dir: `{report['audio_dir']}`",
        f"- Duration: {report['duration_seconds']:.3f}s",
        f"- Sample rate: {report['sample_rate']} Hz",
        f"- STFT: n_fft={report['n_fft']}, hop={report['hop_length']}",
        "",
        "## Input Proxy Metrics",
        "",
        f"- Mean abs envelope correlation off-diagonal: {report['input_metrics']['mean_abs_envelope_corr_offdiag']:.4f}",
        f"- Mean abs waveform correlation off-diagonal: {report['input_metrics']['mean_abs_waveform_corr_offdiag']:.4f}",
        "",
        "## Algorithms",
        "",
    ]

    for result in report["algorithms"]:
        lines.extend(
            [
                f"### {result['name']}",
                "",
                f"- Description: {result['description']}",
                f"- Runtime: {result['runtime_seconds']:.2f}s",
                f"- Mean abs envelope correlation off-diagonal: {result['metrics']['mean_abs_envelope_corr_offdiag']:.4f}",
                f"- Mean abs waveform correlation off-diagonal: {result['metrics']['mean_abs_waveform_corr_offdiag']:.4f}",
                f"- Output dir: `{result['output_dir']}`",
                "",
                "| Source | Best input | Envelope corr | Margin | Unique assignment |",
                "|---:|---|---:|---:|---|",
            ]
        )
        for row in result["mapping"]:
            lines.append(
                f"| {row['source']} | {row['best_label']} | {row['envelope_corr']:.4f} | {row['margin_to_second']:.4f} | {row['unique_assignment_label']} |"
            )
        lines.append("")

    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    audio = load_tracks(args.audio_dir, sample_rate=args.sample_rate, duration=args.duration)
    duration_seconds = audio.shape[1] / args.sample_rate

    input_dir = args.out_dir / "input_reference"
    input_dir.mkdir(parents=True, exist_ok=True)
    for index, signal in enumerate(audio, start=1):
        sf.write(input_dir / f"track{index}.wav", peak_normalize(signal), args.sample_rate)

    input_env_corr = corrcoef_rows(np.log10(rms_envelope(audio, args.sample_rate) + 1e-8))
    input_wave_corr = corrcoef_rows(audio)
    spec = make_stft(audio, sample_rate=args.sample_rate, n_fft=args.n_fft, hop_length=args.hop_length)

    report = {
        "audio_dir": str(args.audio_dir),
        "output_dir": str(args.out_dir),
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
        print(f"Running {algorithm.name} ({algorithm.n_iter} iterations)...", flush=True)
        start = time.perf_counter()
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
        runtime = time.perf_counter() - start

        separated = peak_normalize(separated)
        algorithm_dir = args.out_dir / algorithm.name
        algorithm_dir.mkdir(parents=True, exist_ok=True)

        for source_index, signal in enumerate(separated, start=1):
            sf.write(algorithm_dir / f"source{source_index}.wav", signal, args.sample_rate)

        output_env_corr = corrcoef_rows(np.log10(rms_envelope(separated, args.sample_rate) + 1e-8))
        output_wave_corr = corrcoef_rows(separated)
        mapping, mapping_matrix = output_input_mapping(audio[:, : separated.shape[1]], separated, args.sample_rate)

        result = {
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
        report["algorithms"].append(result)
        write_report(report, args.out_dir)
        print(f"Finished {algorithm.name}: {runtime:.2f}s", flush=True)

    write_report(report, args.out_dir)
    print(f"Wrote {args.out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
