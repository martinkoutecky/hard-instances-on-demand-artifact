#!/usr/bin/env python3
"""Verify that every instance file referenced by a measurement report still
hashes to the sha256 recorded at measurement time.

Runs no solver.  Instances that are not redistributed here (SAT Competition
formulas, third-party TSPLIB/FHCP archives) are reported as `absent`, not as
failures; see the README for how to reconstruct them.

Two mismatches are expected and documented in the README's anonymization
notes.  They are listed in KNOWN_MISMATCHES below and reported separately.

Usage:
    python3 verify_hashes.py [--report PATH ...]
Exit status is non-zero only on an *undocumented* mismatch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DEFAULT_REPORTS = [
    ROOT / "current_machine_rebench" / "results" / "paper_instances.json",
]

# Files whose recorded hash intentionally refers to pre-anonymization content.
KNOWN_MISMATCHES = {
    "champions/tsp/champ_DiagonalCMA_U10000.tsp": (
        "TSPLIB NAME: header anonymized; distance matrix byte-identical"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", type=Path, default=[])
    args = parser.parse_args()

    expected: dict[str, set[str]] = {}
    for path in args.report or DEFAULT_REPORTS:
        if not path.is_file():
            print(f"[error] missing report: {path}", file=sys.stderr)
            return 1
        report = json.loads(path.read_text(encoding="utf-8"))
        for run in report.get("runs", []):
            source, recorded = run.get("source"), run.get("source_sha256")
            if source and recorded:
                expected.setdefault(source, set()).add(recorded)

    ok = absent = 0
    known: list[str] = []
    bad: list[str] = []
    for source in sorted(expected):
        target = ROOT / source
        if not target.is_file():
            absent += 1
            continue
        actual = sha256(target)
        if actual in expected[source]:
            ok += 1
        elif source in KNOWN_MISMATCHES:
            known.append(f"  {source}\n      expected ({KNOWN_MISMATCHES[source]})")
        else:
            bad.append(
                f"  {source}\n      recorded {sorted(expected[source])}\n      actual   {actual}"
            )

    print(f"instances referenced : {len(expected)}")
    print(f"  hash verified      : {ok}")
    print(f"  not redistributed  : {absent}  (reconstruct per README)")
    print(f"  documented mismatch: {len(known)}")
    print(f"  UNEXPECTED mismatch: {len(bad)}")
    for line in known:
        print(line)
    for line in bad:
        print(line)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
