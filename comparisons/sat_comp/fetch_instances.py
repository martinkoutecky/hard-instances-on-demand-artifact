#!/usr/bin/env python3
"""Fetch the manifest's SAT formulas from the Global Benchmark Database."""

from __future__ import annotations

import argparse
import csv
import lzma
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
GBD_FILE_URL = "https://benchmark-database.de/file/{hash}?context=cnf"


def dimacs_header(path: Path) -> tuple[int, int]:
    with path.open("rt", encoding="ascii", errors="replace") as handle:
        for line in handle:
            if line.startswith("p cnf "):
                _, _, variables, clauses = line.split()[:4]
                return int(variables), int(clauses)
    raise ValueError(f"no DIMACS header in {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest.csv")
    parser.add_argument("--output-dir", type=Path, default=HERE / "instances")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    rows = list(csv.DictReader(args.manifest.open(encoding="utf-8")))
    if args.limit is not None:
        rows = rows[: args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, 1):
        destination = args.output_dir / f"{row['hash']}.cnf"
        if not destination.exists():
            request = urllib.request.Request(
                GBD_FILE_URL.format(hash=row["hash"]),
                headers={"User-Agent": "nevergrad-alenex-artifact/1.0"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                compressed = response.read()
            destination.write_bytes(lzma.decompress(compressed))
        actual = dimacs_header(destination)
        expected = (int(row["variables"]), int(row["clauses"]))
        if actual != expected:
            raise ValueError(
                f"{row['hash']}: header {actual} does not match manifest {expected}"
            )
        if index % 25 == 0 or index == len(rows):
            print(f"verified {index}/{len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
