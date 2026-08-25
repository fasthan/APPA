#!/usr/bin/env python3
"""Create peak-normalized BSS assets for the browser UI."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bss-root", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss"))
    parser.add_argument("--out-root", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss/peak"))
    parser.add_argument("--report", type=Path, default=Path("web/assets/analysis/miuse-27m-33m/bss/report.json"))
    parser.add_argument("--target-peak-dbfs", type=float, default=-1.0)
    parser.add_argument("--max-gain-db", type=float, default=36.0)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def db(value: float) -> float:
    return 20 * math.log10(max(float(value), 1e-12))


def gain_from_db(gain_db: float) -> float:
    return 10 ** (gain_db / 20)


def load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    bss_root = resolve_path(args.bss_root)
    out_root = resolve_path(args.out_root)
    report = load_report(resolve_path(args.report))
    out_root.mkdir(parents=True, exist_ok=True)

    target_peak = gain_from_db(args.target_peak_dbfs)
    manifest = {
        "version": 1,
        "kind": "bss_peak_normalize",
        "settings": {
            "targetPeakDbfs": args.target_peak_dbfs,
            "maxGainDb": args.max_gain_db,
        },
        "algorithms": {},
    }

    for algorithm in report["algorithms"]:
        algorithm_id = algorithm["name"]
        source_root = bss_root / algorithm_id
        algorithm_out = out_root / algorithm_id
        algorithm_out.mkdir(parents=True, exist_ok=True)
        sources = []

        for mapping in algorithm["mapping"]:
            source_index = int(mapping["source"])
            source_path = source_root / f"source{source_index}.wav"
            signal, sample_rate = sf.read(source_path, dtype="float64")
            if signal.ndim > 1:
                signal = np.mean(signal, axis=1)

            source_peak = float(np.max(np.abs(signal)))
            if source_peak <= 1e-12:
                applied_gain_db = 0.0
                applied_gain = 1.0
            else:
                desired_gain_db = args.target_peak_dbfs - db(source_peak)
                applied_gain_db = min(desired_gain_db, args.max_gain_db)
                applied_gain = gain_from_db(applied_gain_db)

            adjusted = signal * applied_gain
            adjusted_peak = float(np.max(np.abs(adjusted)))
            sf.write(algorithm_out / f"source{source_index}.wav", adjusted, sample_rate)

            sources.append(
                {
                    "source": source_index,
                    "bestLabel": mapping["best_label"],
                    "sourcePeakDbfs": db(source_peak),
                    "targetPeakDbfs": args.target_peak_dbfs,
                    "adjustedPeakDbfs": db(adjusted_peak),
                    "appliedGainDb": applied_gain_db,
                    "gainLimited": applied_gain_db >= args.max_gain_db,
                }
            )

        manifest["algorithms"][algorithm_id] = {"sources": sources}

    (bss_root / "peak_normalize.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {bss_root / 'peak_normalize.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
