#!/usr/bin/env python3
"""Continuously log per-CPU frequency and load during benchmark campaigns."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path


CPU_ROOT = Path("/sys/devices/system/cpu")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def read_int(path: Path) -> int | None:
    value = read_text(path)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def cpu_number(path: Path) -> int:
    return int(path.parents[1].name.removeprefix("cpu"))


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def temperature_source(path: Path) -> dict[str, str]:
    base_name = path.name.removesuffix("_input")
    return {
        "path": str(path),
        "driver": read_text(path.parent / "name") or "unknown",
        "label": read_text(path.with_name(base_name + "_label")) or base_name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output.with_name(output.name + ".lock")
    lock_file = lock_path.open("a+")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"frequency monitor lock is already held: {lock_path}")

    frequency_paths = sorted(
        CPU_ROOT.glob("cpu[0-9]*/cpufreq/scaling_cur_freq"), key=cpu_number
    )
    if not frequency_paths:
        raise SystemExit("no readable scaling_cur_freq paths found")

    cpu_ids = [cpu_number(path) for path in frequency_paths]
    cpufreq_dirs = {cpu_number(path): path.parent for path in frequency_paths}
    scaling_max = {
        cpu: read_int(directory / "scaling_max_freq")
        for cpu, directory in cpufreq_dirs.items()
    }
    temperature_paths = sorted(Path("/sys/class/hwmon").glob("hwmon*/temp*_input"))
    temperature_sources = {
        str(path): temperature_source(path) for path in temperature_paths
    }
    cpu_temperature_paths = [
        path
        for path in temperature_paths
        if temperature_sources[str(path)]["driver"] == "k10temp"
    ]
    boost_path = CPU_ROOT / "cpufreq/boost"
    metadata = {
        "started_at": utc_now(),
        "pid": os.getpid(),
        "sample_interval_s": args.interval,
        "cpu_ids": cpu_ids,
        "boost_control_path": str(boost_path),
        "boost_enabled_at_start": read_text(boost_path),
        "scaling_driver": {
            str(cpu): read_text(directory / "scaling_driver")
            for cpu, directory in cpufreq_dirs.items()
        },
        "scaling_governor": {
            str(cpu): read_text(directory / "scaling_governor")
            for cpu, directory in cpufreq_dirs.items()
        },
        "scaling_max_khz": {str(cpu): scaling_max[cpu] for cpu in cpu_ids},
        "temperature_sources": list(temperature_sources.values()),
        "interpretation": (
            "A CPU is counted above_scaling_max when scaling_cur_freq exceeds its "
            "scaling_max_freq. Under acpi-cpufreq this is driver-reported sampled "
            "frequency, not cycle-accurate APERF/MPERF effective frequency."
        ),
    }
    metadata_path = output.with_name(output.stem + ".metadata.json")
    atomic_json(metadata_path, metadata)

    fields = [
        "timestamp_utc",
        "monotonic_s",
        "boost_enabled",
        "load1",
        "load5",
        "load15",
        "cpu_tctl_millic",
        "max_temp_millic",
        "above_scaling_max_count",
        "max_observed_khz",
        *(f"cpu{cpu}_khz" for cpu in cpu_ids),
    ]
    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    is_new = not output.exists() or output.stat().st_size == 0
    with output.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if is_new:
            writer.writeheader()
            stream.flush()
        next_sample = time.monotonic()
        while not stop:
            frequencies = {
                cpu_number(path): read_int(path) for path in frequency_paths
            }
            observed = [value for value in frequencies.values() if value is not None]
            above_scaling_max = sum(
                1
                for cpu, value in frequencies.items()
                if value is not None
                and scaling_max[cpu] is not None
                and value > scaling_max[cpu]
            )
            temperatures = [
                value
                for path in temperature_paths
                if (value := read_int(path)) is not None
            ]
            cpu_temperatures = [
                value
                for path in cpu_temperature_paths
                if (value := read_int(path)) is not None
            ]
            load1, load5, load15 = os.getloadavg()
            row: dict[str, object] = {
                "timestamp_utc": utc_now(),
                "monotonic_s": f"{time.monotonic():.6f}",
                "boost_enabled": read_text(boost_path),
                "load1": f"{load1:.6f}",
                "load5": f"{load5:.6f}",
                "load15": f"{load15:.6f}",
                "cpu_tctl_millic": (
                    max(cpu_temperatures) if cpu_temperatures else ""
                ),
                "max_temp_millic": max(temperatures) if temperatures else "",
                "above_scaling_max_count": above_scaling_max,
                "max_observed_khz": max(observed) if observed else "",
            }
            row.update(
                {
                    f"cpu{cpu}_khz": "" if frequencies[cpu] is None else frequencies[cpu]
                    for cpu in cpu_ids
                }
            )
            writer.writerow(row)
            stream.flush()
            next_sample += args.interval
            time.sleep(max(0.0, next_sample - time.monotonic()))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
