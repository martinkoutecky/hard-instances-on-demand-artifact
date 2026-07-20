#!/usr/bin/env python3
"""Keep CPUs 1--4 loaded while a rebenchmark campaign has fewer live workers."""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


WORKER_MARKERS = ("followup_rebench.py", "run_rebench.py")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def active_worker_cpus() -> set[int]:
    active: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            if not any(marker in command for marker in WORKER_MARKERS):
                continue
            status = (entry / "status").read_text()
            allowed = next(
                line.split(":", 1)[1].strip()
                for line in status.splitlines()
                if line.startswith("Cpus_allowed_list:")
            )
            if allowed.isdigit():
                active.add(int(allowed))
        except (FileNotFoundError, PermissionError, ProcessLookupError, StopIteration):
            continue
    return active


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-pid", type=int, required=True)
    parser.add_argument("--completed", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    fillers: dict[int, subprocess.Popen] = {}
    args.log.parent.mkdir(parents=True, exist_ok=True)

    def record(message: str) -> None:
        with args.log.open("a", encoding="utf-8") as handle:
            handle.write(f"{utc_now()} {message}\n")

    try:
        while Path(f"/proc/{args.campaign_pid}").exists() and not args.completed.exists():
            active = active_worker_cpus()
            for cpu in (1, 2, 3, 4):
                filler = fillers.get(cpu)
                if cpu in active:
                    if filler is not None:
                        filler.terminate()
                        filler.wait(timeout=5)
                        del fillers[cpu]
                        record(f"stop filler cpu={cpu}; experiment active")
                elif filler is None or filler.poll() is not None:
                    fillers[cpu] = subprocess.Popen(
                        ["taskset", "-c", str(cpu), "/usr/bin/sha256sum", "/dev/zero"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    record(f"start filler cpu={cpu}; no experiment worker")
            time.sleep(1)
    finally:
        for cpu, filler in fillers.items():
            filler.terminate()
            try:
                filler.wait(timeout=5)
            except subprocess.TimeoutExpired:
                filler.kill()
            record(f"stop filler cpu={cpu}; keeper exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
