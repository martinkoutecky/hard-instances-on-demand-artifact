#!/usr/bin/env python3
"""Validate the curated ALENEX artifact inventory without running solvers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).with_name("manifest.json")


def fail(messages: list[str], message: str) -> None:
    messages.append(message)


def validate() -> list[str]:
    errors: list[str] = []
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    for required in manifest["required_files"]:
        if not (ROOT / required).is_file():
            fail(errors, f"missing required file: {required}")

    for domain, specification in manifest["domains"].items():
        for group in specification["config_groups"]:
            matches = sorted(ROOT.glob(group["glob"]))
            if len(matches) != group["count"]:
                fail(
                    errors,
                    f"{domain}: {group['glob']} matched {len(matches)}, "
                    f"expected {group['count']}",
                )
            for path in matches:
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    fail(errors, f"invalid JSON {path.relative_to(ROOT)}: {error}")

        champions = sorted(ROOT.glob(specification["champion_glob"]))
        if len(champions) != specification["champion_count"]:
            fail(
                errors,
                f"{domain}: {specification['champion_glob']} matched "
                f"{len(champions)}, expected {specification['champion_count']}",
            )
        for relative in specification["headline"] + specification["runners"]:
            if not (ROOT / relative).is_file():
                fail(errors, f"{domain}: missing canonical path {relative}")

    tracked = subprocess.check_output(
        ["git", "ls-files"], cwd=ROOT, text=True
    ).splitlines()
    for relative in tracked:
        path = Path(relative)
        if path.suffix == ".pyc" or "__pycache__" in path.parts:
            fail(errors, f"compiled Python artifact is tracked: {relative}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("ALENEX manifest validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    counts = {
        domain: specification["champion_count"]
        for domain, specification in manifest["domains"].items()
    }
    print(f"ALENEX manifest valid; exported instance counts: {counts}")
    print(f"Known missing selected artifacts: {len(manifest['known_missing_ids'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
