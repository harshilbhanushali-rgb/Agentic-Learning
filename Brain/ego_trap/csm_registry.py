from __future__ import annotations
import csv
from pathlib import Path


def load_mapping(path: str | Path) -> dict[str, tuple[str, str]]:
    """Load a CSV with columns filename,csm_id,csm_name into {filename_stem: (csm_id, csm_name)}."""
    mapping: dict[str, tuple[str, str]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stem = Path(row["filename"]).stem
            mapping[stem] = (row["csm_id"].strip(), row["csm_name"].strip())
    return mapping
