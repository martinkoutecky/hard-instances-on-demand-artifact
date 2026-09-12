#!/usr/bin/env python3
"""Recompute the paper's aggregate tables from the committed measurement files.

This runs no solver.  It loads the measurement reports shipped in this
repository and applies the *same* aggregation code that produced the numbers in
the paper (``current_machine_rebench.run_rebench.summarize``), so the printed
medians are derived, not transcribed.

Use ``current_machine_rebench/CURRENT-MACHINE-PAPER-NUMBERS.md`` to map each
printed row onto its table in the paper.

Usage:
    python3 report_tables.py [--json OUT.json] [--report PATH ...]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REBENCH = ROOT / "current_machine_rebench"

DEFAULT_REPORTS = [
    REBENCH / "results" / "paper_instances.json",
]


def _install_import_stubs() -> list[str]:
    """Let ``run_rebench`` import without the measurement-only dependencies.

    ``summarize()`` is pure ``statistics`` over the already-recorded runs, but
    the module imports numpy and python-sat at top level because its *other*
    entry points drive solvers.  Stub whichever of those is absent so that a
    reviewer can regenerate every table with a stdlib-only Python.  Nothing
    stubbed here is reachable from ``summarize()``.
    """
    stubbed: list[str] = []
    try:
        import numpy  # noqa: F401
    except ModuleNotFoundError:
        numpy = types.ModuleType("numpy")
        numpy.ndarray = object  # only used in type annotations
        sys.modules["numpy"] = numpy
        stubbed.append("numpy")
    try:
        import pysat.solvers  # noqa: F401
    except ModuleNotFoundError:
        pysat = types.ModuleType("pysat")
        solvers = types.ModuleType("pysat.solvers")
        solvers.Solver = object
        pysat.solvers = solvers
        sys.modules["pysat"] = pysat
        sys.modules["pysat.solvers"] = solvers
        stubbed.append("python-sat")
    return stubbed


def _load_rebench():
    sys.path.insert(0, str(REBENCH))  # run_rebench imports sat_common by name
    spec = importlib.util.spec_from_file_location(
        "run_rebench", REBENCH / "run_rebench.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _print_block(title: str, node: object, indent: int = 0) -> None:
    pad = "  " * indent
    if isinstance(node, dict):
        scalars = {
            key: value
            for key, value in node.items()
            if isinstance(value, (int, float, str, bool)) or value is None
        }
        nested = {key: value for key, value in node.items() if key not in scalars}
        if title:
            print(f"{pad}{title}" + (f": {', '.join(f'{k}={_fmt(v)}' for k, v in scalars.items())}" if scalars else ""))
        for key, value in nested.items():
            _print_block(str(key), value, indent + 1)
    elif isinstance(node, list):
        if node and all(isinstance(item, (int, float)) for item in node):
            print(f"{pad}{title}: [{', '.join(_fmt(v) for v in node)}]")
        else:
            print(f"{pad}{title}: {len(node)} entries")
    else:
        print(f"{pad}{title}: {_fmt(node)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="append",
        type=Path,
        default=[],
        help="measurement report to summarize; repeatable (default: paper_instances.json)",
    )
    parser.add_argument(
        "--json", type=Path, help="also write the recomputed summary to this file"
    )
    args = parser.parse_args()

    stubbed = _install_import_stubs()
    if stubbed:
        print(
            f"[note] {', '.join(stubbed)} not installed; stubbed for import only "
            "(no solver code runs in this script).\n"
        )
    rebench = _load_rebench()

    reports = args.report or DEFAULT_REPORTS
    summaries = {}
    for path in reports:
        if not path.is_file():
            print(f"[error] missing report: {path}", file=sys.stderr)
            return 1
        report = json.loads(path.read_text(encoding="utf-8"))
        print("=" * 78)
        print(f"Report:  {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
        machine = report.get("machine", {})
        print(f"Machine: {machine.get('cpu_model', '?')}  |  runs: {len(report.get('runs', []))}")
        print(f"Taken:   {report.get('completed_at', '?')}")
        print("=" * 78)
        summary = rebench.summarize(report)
        summaries[str(path)] = summary
        for suite, node in summary.items():
            print(f"\n--- {suite} " + "-" * (72 - len(suite)))
            _print_block("", node)
        print()

    if args.json:
        args.json.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
