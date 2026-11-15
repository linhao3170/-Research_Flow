"""Generate the bundled synthetic tabular dataset (T0 WP-05).

Deterministic: the same seed always produces byte-identical CSV content, so
the dataset registry hash is reproducible.  The data is synthetic and authored
for this project (CC0-1.0) — no third-party rows, no network access.

Usage:
    python scripts/build_template_dataset.py                 # bundled data dir
    python scripts/build_template_dataset.py --out <dir> --seed 7
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "researchflow" / "templates" / "data"
DATASET_NAME = "synthetic_breast_cancer.csv"
URI = "local://datasets/" + DATASET_NAME
COLUMNS = [
    "patient_id",
    "event_time",
    "age",
    "bmi",
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "diagnosis",
]
DEFAULT_SEED = 20261114


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def generate_rows(seed: int) -> list[list[str]]:
    rng = np.random.default_rng(seed)
    group_count = 120
    start = datetime(2025, 1, 1, 0, 0, 0)
    rows: list[list[str]] = []
    for group_index in range(group_count):
        group_id = f"P{group_index:04d}"
        latent = float(rng.normal(0.0, 1.0))
        group_time = start + timedelta(days=3 * group_index)
        row_count = int(rng.integers(4, 8))
        for row_index in range(row_count):
            f1 = round(latent + float(rng.normal(0.0, 0.6)), 6)
            f2 = round(0.8 * latent + float(rng.normal(0.0, 0.8)), 6)
            f3 = round(-0.5 * latent + float(rng.normal(0.0, 1.0)), 6)
            f4 = round(float(rng.normal(0.0, 1.0)), 6)
            f5 = round(0.3 * latent * latent + float(rng.normal(0.0, 0.7)), 6)
            f6 = round(float(rng.normal(0.0, 1.0)), 6)
            age = int(np.clip(round(float(rng.normal(55.0, 12.0))), 20, 90))
            bmi = round(float(np.clip(rng.normal(26.0, 4.0), 15.0, 45.0)), 6)
            logit = (
                1.4 * latent
                + 0.6 * f1
                + 0.3 * (age - 55) / 12.0
                + 0.2 * (bmi - 26) / 4.0
                - 0.4
            )
            diagnosis = 1 if float(rng.random()) < _sigmoid(logit) else 0
            event_time = group_time + timedelta(minutes=5 * row_index)
            rows.append(
                [
                    group_id,
                    event_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    str(age),
                    f"{bmi:.6f}",
                    f"{f1:.6f}",
                    f"{f2:.6f}",
                    f"{f3:.6f}",
                    f"{f4:.6f}",
                    f"{f5:.6f}",
                    f"{f6:.6f}",
                    str(diagnosis),
                ]
            )
    return rows


def write_dataset(out_dir: Path, seed: int, license_id: str = "CC0-1.0") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = generate_rows(seed)
    csv_path = out_dir / DATASET_NAME
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(",".join(COLUMNS) + "\n")
        for row in rows:
            handle.write(",".join(row) + "\n")
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    registry = {
        "schema_version": "1.0",
        "generated_by": "scripts/build_template_dataset.py",
        "seed": seed,
        "provenance": (
            "synthetic data generated in-repo; no third-party rows, no network access"
        ),
        "datasets": {
            URI: {
                "path": DATASET_NAME,
                "sha256": digest,
                "license": license_id,
                "rows": len(rows),
                "columns": COLUMNS,
                "target": "diagnosis",
            }
        },
    }
    (out_dir / "registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    registry = write_dataset(Path(args.out), args.seed)
    entry = registry["datasets"][URI]
    print(f"DATASET_OK path={args.out} rows={entry['rows']} sha256={entry['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())