#!/usr/bin/env python3
"""Combine the censored corpus screens and exact representative remeasurements."""

from __future__ import annotations

import collections
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def load_instances(name: str) -> list[dict]:
    data = json.loads((RESULTS / name).read_text(encoding="utf-8"))
    instances = data["instances"]
    return list(instances.values()) if isinstance(instances, dict) else instances


def main() -> None:
    rows = (
        load_instances("full_cap12_shard0.json")
        + load_instances("full_cap12_shard1.json")
    )
    assert len(rows) == len({row["hash"] for row in rows}) == 498

    buckets = collections.Counter()
    for row in rows:
        elapsed = row["median"]
        if elapsed < 0.1:
            buckets["under_0.1"] += 1
        elif elapsed < 1:
            buckets["0.1_to_1"] += 1
        elif elapsed < 8:
            buckets["1_to_8"] += 1
        elif elapsed < 11.6:
            buckets["8_to_11.6"] += 1
        elif elapsed < 12:
            buckets["11.6_to_12"] += 1
        else:
            buckets["censored_at_12"] += 1

    family_totals = collections.Counter(row["family"] for row in rows)
    family_censored = collections.Counter(
        row["family"] for row in rows if row["median"] >= 12
    )
    hard_families = [
        {
            "family": family,
            "censored_at_12": count,
            "total": family_totals[family],
        }
        for family, count in family_censored.most_common()
    ]

    main_rows = sorted(
        load_instances("main_tracks_cap20.json"),
        key=lambda row: row["median"],
        reverse=True,
    )
    main_summary = {
        "unique_formulas": len(main_rows),
        "censored_at_20": sum(row["median"] >= 20 for row in main_rows),
        "gray_11.6_to_20": sum(11.6 <= row["median"] < 20 for row in main_rows),
        "under_11.6": sum(row["median"] < 11.6 for row in main_rows),
        "rows": main_rows,
    }

    exact = {}
    for path in sorted(RESULTS.glob("exact_*.json")):
        for row in load_instances(path.name):
            exact[row["hash"]] = {
                "source": path.name,
                **row,
            }

    output = {
        "corpus": {
            "unique_formulas": len(rows),
            "result_metadata": dict(
                collections.Counter(row["result"] for row in rows)
            ),
            "buckets": dict(buckets),
            "under_reported_champion_floor_11.6": sum(
                row["median"] < 11.6 for row in rows
            ),
            "hard_families": hard_families,
        },
        "recent_main": main_summary,
        "exact_remeasurements": exact,
    }
    destination = RESULTS / "aggregate.json"
    destination.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {destination}")


if __name__ == "__main__":
    main()
