#!/usr/bin/env python3
"""Recompute the paper's aggregate tables from the committed measurement files.

This runs no solver.  It loads the measurement reports shipped in this
repository and applies the *same* aggregation code that produced the numbers in
the paper (``current_machine_rebench.run_rebench.summarize``), so the printed
medians are derived, not transcribed.

Rows are keyed by result file, not by paper table; ``paper_tables.py`` prints
the same aggregates laid out as Tables 3.1-3.5.

Usage:
    python3 report_tables.py [--json OUT.json] [--report PATH ...]
    python3 report_tables.py --report RERUN/paper_instances.json --compare
    python3 report_tables.py --report RERUN/tsp-full-r3.json --compare \
        --baseline current_machine_rebench/results/followup-four-core/tsp-full-r3.json

With ``--compare`` the script additionally prints every headline aggregate of
the given report next to the same aggregate recomputed from the committed
measurement file it re-measures (``--baseline``, default paper_instances.json),
with the ratio rerun/paper.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
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


# Headline aggregates compared by --compare.  Per-branch SAT medians are left
# out (they feed the virtual-best rows), as are counts, censoring bookkeeping,
# and the per-case rows of the external benchmarks (their per-family medians
# are kept).
HEADLINE_KEYS = (
    "virtual_best_median_s",
    "median_s",
    "median_of_case_medians_s",
    "geomean_s",
)


def _headline_rows(node: object, path: tuple[str, ...] = ()) -> dict:
    rows = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("branches", "cases"):
                continue
            if key in HEADLINE_KEYS and isinstance(value, (int, float)):
                # Fresh random-search controls are named by rank and by the
                # evaluation index that produced them; a rerun re-ranks the
                # seeded candidates by measured time, so align by rank only.
                name = re.sub(r"_eval\d+", "", "/".join(path + (key,)))
                rows[name] = float(value)
            else:
                rows.update(_headline_rows(value, path + (str(key),)))
    return rows


def _print_comparison(paper: dict, rerun: dict) -> None:
    paper_rows = _headline_rows(paper)
    rerun_rows = _headline_rows(rerun)
    print("=" * 78)
    print("Rerun vs. paper (committed measurements), headline aggregates in seconds")
    print("=" * 78)
    width = max(len(key) for key in paper_rows.keys() | rerun_rows.keys())
    print(f"{'aggregate':<{width}}  {'paper':>10}  {'rerun':>10}  {'rerun/paper':>11}")
    for key in sorted(paper_rows.keys() | rerun_rows.keys()):
        old = paper_rows.get(key)
        new = rerun_rows.get(key)
        ratio = f"{new / old:11.2f}" if old and new is not None else f"{'-':>11}"
        old_s = f"{old:10.3f}" if old is not None else f"{'missing':>10}"
        new_s = f"{new:10.3f}" if new is not None else f"{'missing':>10}"
        print(f"{key:<{width}}  {old_s}  {new_s}  {ratio}")
    print(
        "\nAbsolute times depend on the machine; the paper's claims are about"
        "\nratios between instances, so compare the rerun/paper column across"
        "\nrows rather than to 1.  The SAT fresh_rs_* controls are the top-20 of"
        "\na seeded random search ranked by measured solve time, so a rerun may"
        "\nselect different instances at each rank."
    )


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
    parser.add_argument(
        "--compare",
        action="store_true",
        help="compare the (single) --report against the committed measurements",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_REPORTS[0],
        help="committed report that --compare compares against "
        "(default: paper_instances.json)",
    )
    args = parser.parse_args()
    if args.compare and len(args.report) != 1:
        parser.error("--compare needs exactly one --report")

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

    if args.compare:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        _print_comparison(rebench.summarize(baseline), next(iter(summaries.values())))
        print()

    if args.json:
        args.json.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
