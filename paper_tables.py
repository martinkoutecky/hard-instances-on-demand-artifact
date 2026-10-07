#!/usr/bin/env python3
"""Print the paper's Tables 3.1-3.5 in the paper's layout.

Without arguments, every cell is recomputed from the committed measurement
files, with the same aggregation code that produced the paper
(``current_machine_rebench.run_rebench.summarize``); the output reproduces the
published tables up to rounding.

With ``--rerun DIR`` (the output directory of ``./runme.sh --full``) every
cell shows the rerun's value followed by the paper's value in parentheses:
``rerun (paper)``.  The rows that the paper takes from the two four-core
follow-up campaigns (README, "Re-running the remeasurement") are filled from
``--followup`` and ``--ham-random`` when those campaigns have been run; by
default they are looked for next to DIR (``DIR/../followup`` and
``DIR/../ham-random``, i.e. ``runme_out/followup`` and ``runme_out/ham-random``
for the default DIR) and inside it.  Without them, the generated TSP/HAM rows
fall back to the serial campaign's own measurements (marked ``*``), and the
fresh RandomSearch controls that only the follow-ups produce are shown as
``n/a``.

Values are in seconds, rounded to three significant digits (one decimal above
100 s); ``>60`` is a
median censored at the cap.  Usage:

    python3 paper_tables.py
    python3 paper_tables.py --rerun runme_out/rerun [--followup DIR] [--ham-random DIR]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import report_tables

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "current_machine_rebench" / "results"
PAPER_MAIN = RESULTS / "paper_instances.json"
PAPER_FOLLOWUP = RESULTS / "followup-four-core"
PAPER_HAM_RANDOM = RESULTS / "ham-random-four-core"
HAM_ENCODINGS = ("perm_int", "perm_thr", "trivial")
SAT_BRANCHES = ("minisat22", "breakid_cadical195", "cryptominisat", "kissat404", "march_cu")


class Censored:
    """A median that is right-censored at the cap."""

    def __init__(self, cap: float):
        self.cap = cap


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


class Source:
    """All measurements of one campaign (the paper's, or a rerun)."""

    def __init__(self, rebench, main: Path, followup: Path | None, ham_random: Path | None):
        report = _load(main)
        if report is None:
            raise FileNotFoundError(main)
        self.summary = rebench.summarize(report)
        self.followup = followup if followup and followup.is_dir() else None
        self.ham_random = ham_random if ham_random and ham_random.is_dir() else None
        self.full = {}
        for suite in ("tsp", "ham"):
            data = _load(self.followup / f"{suite}-full-r3.json") if self.followup else None
            self.full[suite] = rebench.summarize(data)[suite] if data else None

    # --- SAT ------------------------------------------------------------
    def _sat_case(self, case: str) -> dict | None:
        for suite in ("sat", "sat_external"):
            node = self.summary[suite]
            if case in node:
                return node[case]
            # Fresh RandomSearch controls carry the evaluation index in their
            # name, which differs between campaigns: match by rank.
            matches = [key for key in node if key.startswith(case + "_eval")]
            if matches:
                return node[matches[0]]
        return None

    def sat(self, case: str, branch: str | None = None):
        node = self._sat_case(case)
        if node is None:
            return None
        value = node["virtual_best_median_s"] if branch is None else node["branches"][branch]["median_s"]
        return Censored(60.0) if value >= 60.0 else value

    def sat_rs(self):
        values = [self.sat(f"fresh_rs_original3_{enc}_rank01") for enc in ("kcnf", "mprefix")]
        values = [v for v in values if isinstance(v, float)]
        return max(values) if values else None

    # --- TSP / HAM generated instances ----------------------------------
    def gen(self, suite: str, case: str, split: str):
        """(value, from_serial_campaign) of a generated TSP/HAM instance."""
        node, serial = self.full[suite], False
        if node is None:
            node, serial = self.summary[suite], True
        if case not in node or split not in node[case]:
            return None, serial
        return node[case][split]["median_s"], serial

    # --- TSP / HAM external benchmarks ----------------------------------
    def _ext(self, suite: str):
        return self.summary[suite]

    def ext_median(self, suite: str, family: str):
        fam = self._ext(suite)["families"].get(family)
        return None if fam is None else fam["median_of_case_medians_s"]

    def ext_censored(self, suite: str, family: str):
        cases = [c for c in self._ext(suite)["cases"].values() if c["family"] == family and "train" in c]
        censored = sum("median_right_censored_at_s" in c["train"] for c in cases)
        return censored, len(cases)

    def ext_hardest_solved(self, suite: str, family: str):
        """Hardest case with no timeout on any train seed: (name, train median)."""
        solved = {
            name: c["train"]["median_s"]
            for name, c in self._ext(suite)["cases"].items()
            if c["family"] == family and "train" in c and c["train"]["timeout_seed_count"] == 0
        }
        if not solved:
            return None, None
        name = max(solved, key=solved.get)
        return name, solved[name]

    def ext_case(self, suite: str, case: str, split: str):
        c = self._ext(suite)["cases"].get(case, {}).get(split)
        if c is None:
            return None
        if "median_right_censored_at_s" in c:
            return Censored(c["median_right_censored_at_s"])
        return c["median_s"]

    def fixed_comparator(self, name: str, case: str, split: str):
        """gr229 / 20009_hard: three-repetition follow-up rerun, else the scan."""
        data = _load(self.followup / f"{name}.json") if self.followup else None
        if data is not None:
            return data["summary"][split]["median_s"], False
        return (self.ext_case("tsp_external", case, split) if split == "train" else None), True

    # --- RandomSearch controls of the follow-ups ------------------------
    def tsp_rs(self, field: str):
        data = _load(self.followup / "tsp-random-final.json") if self.followup else None
        if data is None:
            return None, None
        clean = data[field]["clean"]
        return clean["train"]["median_s"], clean["heldout"]["median_s"]

    def ham_rs(self):
        """Conservative best of the three encodings: the highest held-out median."""
        best = None
        for enc in HAM_ENCODINGS:
            data = _load(self.ham_random / f"ham-random-{enc}.json") if self.ham_random else None
            if data is None:
                continue
            clean = data["conservative_best_clean_heldout"]["clean"]
            pair = (clean["train"]["median_s"], clean["heldout"]["median_s"])
            if best is None or pair[1] > best[1]:
                best = pair
        return best or (None, None)

    def npfs8_rs(self):
        data = _load(self.followup / "npfs8-control.json") if self.followup else None
        if data is None:
            return None, None
        times = data["conservative_best_clean"]["seed_times_s"]  # seeds 1..30
        return statistics.median(times[:7]), statistics.median(times[7:])

    # --- NPFS -----------------------------------------------------------
    def npfs(self, case: str, key: str, cap: float = 60.0):
        node = self.summary["npfs"].get(case, {}).get(key)
        if node is None:
            return None
        statuses = node.get("statuses", [])
        unproven = sum(str(s).upper() != "OPTIMAL" for s in statuses)
        if statuses and unproven * 2 > len(statuses):
            return Censored(cap)
        return node["median_s"]


def fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, Censored):
        return f">{value.cap:g}"
    if isinstance(value, str):
        return value
    if value == 0:
        return "0"
    digits = max(1 if abs(value) >= 100 else 0, 2 - int(f"{abs(value):e}".split("e")[1]))
    return f"{value:.{digits}f}"


class Table:
    def __init__(self, paper: Source, rerun: Source | None):
        self.paper, self.rerun = paper, rerun
        self.serial_used = False

    def cell(self, getter, star: bool = False) -> str:
        """getter(Source) -> value, or (value, from_serial)."""

        def unpack(result):
            return result if isinstance(result, tuple) else (result, False)

        paper_value, _ = unpack(getter(self.paper))
        if self.rerun is None:
            return fmt(paper_value)
        rerun_value, serial = unpack(getter(self.rerun))
        mark = "*" if serial and rerun_value is not None else ""
        self.serial_used |= bool(mark)
        return f"{fmt(rerun_value)}{mark} ({fmt(paper_value)})"


def render(title: str, header: list[str], rows: list[list[str]], notes: list[str]) -> str:
    widths = [max(len(r[i]) for r in [header] + rows) for i in range(len(header))]
    line = "-" * (sum(widths) + 2 * (len(widths) - 1))
    out = [title, line]
    fmt_row = lambda r: "  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths)))
    out += [fmt_row(header), line] + [fmt_row(r) for r in rows] + [line]
    out += [f"  {n}" for n in notes]
    return "\n".join(out) + "\n"


def tables(paper: Source, rerun: Source | None) -> str:
    t = Table(paper, rerun)
    c = t.cell
    pair = lambda f: f"{c(lambda s: f(s)[0])} / {c(lambda s: f(s)[1])}"
    gen = lambda suite, case: f"{c(lambda s: s.gen(suite, case, 'train'))} / {c(lambda s: s.gen(suite, case, 'heldout'))}"
    out = []

    def hardest(suite, family):
        def get(s):
            name, value = s.ext_hardest_solved(suite, family)
            return value
        return get

    def censored(suite, family):
        def get(s):
            k, n = s.ext_censored(suite, family)
            return f"{k} of {n}" if n else None
        return get

    # Table 3.1 ------------------------------------------------------------
    rows = [
        ["SAT portfolio", c(lambda s: s.sat("champion_kcnf")), c(lambda s: s.sat_rs()),
         f"phase-transition random {c(lambda s: s.sat('phase_transition'))}; "
         f"van der Waerden {c(lambda s: s.sat('vdw_2_3_13_n160'))}"],
        ["TSP, Shiwa U=10^3", gen("tsp", "champion_shiwa"),
         pair(lambda s: s.tsp_rs("conservative_best_clean_heldout")),
         f"gr229 {c(lambda s: s.fixed_comparator('tsp-gr229', 'gr229', 'train'))} / "
         f"{c(lambda s: s.fixed_comparator('tsp-gr229', 'gr229', 'heldout'))}; "
         f"Hard-TSPLIB {c(censored('tsp_external', 'hard_tsplib'))} censored at 60 s"],
        ["HAM", gen("ham", "champion_discretebso"), pair(lambda s: s.ham_rs()),
         f"G(20,0.22): {gen('ham', 'control_gnp20_022')}"],
        ["NPFS, CP-Opt 10x5",
         f"{c(lambda s: s.npfs('champion_10x5_cpopt', 'cpopt_train'))} / "
         f"{c(lambda s: s.npfs('champion_10x5_cpopt', 'cpopt_heldout'))}",
         c(lambda s: s.npfs("control_10x5_cpopt", "cpopt_train")),
         f"CP-SAT {c(lambda s: s.npfs('champion_10x5_cpopt', 'cpsat_train', 600.0))}"],
        ["NPFS, CP-Opt 8x4",
         f"{c(lambda s: s.npfs('champion_8x4_cpopt', 'cpopt_train'))} / "
         f"{c(lambda s: s.npfs('champion_8x4_cpopt', 'cpopt_heldout'))}",
         pair(lambda s: s.npfs8_rs()),
         f"CP-SAT {c(lambda s: s.npfs('champion_8x4_cpopt', 'cpsat_train'))}"],
    ]
    out.append(render(
        "Table 3.1  Primary results (train / held-out)",
        ["case", "champion", "random control", "context"], rows,
        ["Not re-measured by the campaign (fixed external results quoted in the paper):",
         "SAT Competition 387 of 498 easier; hardest VRF 10x5 3.8 s, hardest Taillard 20x5 4.5 s",
         "(comparisons/sat_comp/, comparisons/npfs/)."]))

    # Table 3.2 ------------------------------------------------------------
    sat_rows = [
        ("random, ratio 4.27", "200", "854", "phase_transition"),
        ("PHP 12/11", "132", "738", "php12_11"),
        ("Tseitin expander", "150", "400", "tseitin_gbd_144799_150v_400c"),
        ("W(2;3,13)", "160", "7308", "vdw_2_3_13_n160"),
        ("RS (kcnf)", "200", "1000", "fresh_rs_original3_kcnf_rank01"),
        ("RS (mprefix)", "200", "852", "fresh_rs_original3_mprefix_rank01"),
        ("champion (kcnf)", "200", "1000", "champion_kcnf"),
        ("champion (mprefix)", "200", "889", "champion_mprefix"),
    ]
    rows = [[label, n, m] + [c(lambda s, case=case, b=b: s.sat(case, b)) for b in SAT_BRANCHES]
            for label, n, m, case in sat_rows]
    out.append(render(
        "Table 3.2  SAT: median of five runs per solver, cap 60 s",
        ["family", "n", "m", "minisat", "BID+cdc", "CMS", "kissat", "march"], rows,
        ["Portfolio objective = minimum of the first three columns. RS rows are the rank-1",
         "candidates of fresh seeded RandomSearch campaigns; a rerun re-ranks the candidates",
         "by measured time, so its RS row may be a different instance."]))

    # Table 3.3 ------------------------------------------------------------
    split = lambda f, sp: c(lambda s: f(s, sp))
    rows = [
        ["random Euclidean, hardest of draw", "20", split(lambda s, sp: s.gen("tsp", "control_random_euclidean", sp), "train"),
         split(lambda s, sp: s.gen("tsp", "control_random_euclidean", sp), "heldout")],
        ["TSPLIB, median", "<=300", c(lambda s: s.ext_median("tsp_external", "tsplib")), "--"],
        ["TSPLIB, hardest (gr229)", "229", c(lambda s: s.fixed_comparator("tsp-gr229", "gr229", "train")),
         c(lambda s: s.fixed_comparator("tsp-gr229", "gr229", "heldout"))],
        ["clustered Euclidean, median", "50-200", c(lambda s: s.ext_median("tsp_external", "clustered_euclidean")), "--"],
        ["Hard-TSPLIB, hardest solved (20009_hard)", "20",
         c(lambda s: s.fixed_comparator("tsp-20009", "20009_hard", "train")),
         c(lambda s: s.fixed_comparator("tsp-20009", "20009_hard", "heldout"))],
        ["Hard-TSPLIB, cases censored at 60 s", "10-76", c(censored("tsp_external", "hard_tsplib")), "--"],
        ["RandomSearch, best find", "20", split(lambda s, sp: s.tsp_rs("selection_winner")[sp == "heldout"], "train"),
         split(lambda s, sp: s.tsp_rs("selection_winner")[sp == "heldout"], "heldout")],
        ["RandomSearch, best held-out", "20",
         split(lambda s, sp: s.tsp_rs("conservative_best_clean_heldout")[sp == "heldout"], "train"),
         split(lambda s, sp: s.tsp_rs("conservative_best_clean_heldout")[sp == "heldout"], "heldout")],
    ]
    for label, case in (("champion CMA", "champion_cma"), ("champion Shiwa", "champion_shiwa"),
                        ("champion DiagonalCMA", "champion_diagonalcma_u10000")):
        rows.append([label, "20", split(lambda s, sp, case=case: s.gen("tsp", case, sp), "train"),
                     split(lambda s, sp, case=case: s.gen("tsp", case, sp), "heldout")])
    out.append(render(
        "Table 3.3  TSP: median Concorde process time, train = seeds 1-7, held-out = seeds 8-30",
        ["family", "N", "train", "held-out"], rows,
        ["gr229 / 20009_hard / generated rows: 3 repetitions per seed (four-core follow-up);",
         "TSPLIB, clustered and Hard-TSPLIB scans: 1 solve per seed (serial campaign).",
         "RandomSearch rows: fresh 100,000-draw campaign of the four-core follow-up."]))

    # Table 3.4 ------------------------------------------------------------
    rows = [
        ["random G(20,0.22)", "20", split(lambda s, sp: s.gen("ham", "control_gnp20_022", sp), "train"),
         split(lambda s, sp: s.gen("ham", "control_gnp20_022", sp), "heldout")],
        ["random cubic", "20", split(lambda s, sp: s.gen("ham", "control_cubic20", sp), "train"),
         split(lambda s, sp: s.gen("ham", "control_cubic20", sp), "heldout")],
        ["FHCP, hardest solved on all seeds", "108", c(hardest("ham_external", "fhcp")), "--"],
        ["FHCP, cases censored at 60 s", "90-150", c(censored("ham_external", "fhcp")), "--"],
        ["RandomSearch, best of three encodings", "20", split(lambda s, sp: s.ham_rs()[sp == "heldout"], "train"),
         split(lambda s, sp: s.ham_rs()[sp == "heldout"], "heldout")],
    ]
    for label, case in (("champion TwoPointsDE", "champion_twopointsde"), ("champion NGOptRW", "champion_ngoptrw"),
                        ("champion DiscreteBSO", "champion_discretebso")):
        rows.append([label, "20", split(lambda s, sp, case=case: s.gen("ham", case, sp), "train"),
                     split(lambda s, sp, case=case: s.gen("ham", case, sp), "heldout")])
    fhcp_names = {name for s in (paper, rerun) if s for name in [s.ext_hardest_solved("ham_external", "fhcp")[0]]}
    out.append(render(
        "Table 3.4  HAM: median Concorde process time, train = seeds 1-7, held-out = seeds 8-30",
        ["family", "N", "train", "held-out"], rows,
        [f"FHCP hardest solved on all seeds: {', '.join(sorted(n for n in fhcp_names if n))} "
         "(paper: graph8, N=108).",
         "RandomSearch row: fresh 100,000-draw campaigns of the HAM four-core follow-up."]))

    # Table 3.5 ------------------------------------------------------------
    def npfs_row(label, size, case, held, cap_sat=60.0, sat="cpsat_train", opt="cpopt_train"):
        return [label, size, c(lambda s: s.npfs(case, sat, cap_sat)) if sat else "--",
                c(lambda s: s.npfs(case, opt)), c(lambda s: s.npfs(case, held)) if held else "--"]

    rows = [
        npfs_row("champion, CP-SAT arm", "6x4", "champion_6x4_cpsat", "cpsat_heldout"),
        npfs_row("  RandomSearch, same arm", "6x4", "control_6x4_cpsat", "cpsat_heldout"),
        npfs_row("champion, CP-Opt arm", "6x4", "champion_6x4_cpopt", "cpopt_heldout"),
        npfs_row("  RandomSearch, same arm", "6x4", "control_6x4_cpopt", "cpopt_heldout"),
        ["RandomSearch, uniform", "8x4", "--", c(lambda s: s.npfs8_rs()[0]), c(lambda s: s.npfs8_rs()[1])],
        npfs_row("champion (DiagonalCMA)", "8x4", "champion_8x4_cpopt", "cpopt_heldout"),
        npfs_row("RandomSearch, uniform", "10x5", "control_10x5_cpopt", None, sat=None),
        npfs_row("champion (DE)", "10x5", "champion_10x5_cpopt", "cpopt_heldout", cap_sat=600.0),
    ]
    out.append(render(
        "Table 3.5  NPFS: median process time per engine, seeds 1-7; held-out = own engine, seeds 8-30",
        ["family", "n x m", "CP-SAT", "CP-Opt", "held-out"], rows,
        ["Cap 60 s, 600 s for 10x5; '>' = no optimality proof within the cap on most seeds.",
         "8x4 RandomSearch row: fresh 100,000-draw campaign of the four-core follow-up."]))

    if rerun is not None:
        head = [
            "Each cell: rerun value (paper value), in seconds, three significant digits.",
            "Absolute times depend on the machine; the paper's claims are about ratios",
            "between rows.",
        ]
        if t.serial_used:
            head += [
                "* = no four-core follow-up found; value from the serial campaign's own",
                "    TSP/HAM measurement (one repetition per seed instead of three).",
            ]
        if rerun.followup is None or rerun.ham_random is None:
            head += [
                "n/a = produced only by a four-core follow-up campaign that was not found",
                "    (README, 'Re-running the remeasurement'; pass --followup / --ham-random).",
            ]
        out.insert(0, "\n".join(head) + "\n")
    return "\n".join(out)


def _first_dir(*candidates: Path) -> Path | None:
    return next((p for p in candidates if p.is_dir()), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rerun", type=Path, help="output directory of ./runme.sh --full")
    parser.add_argument("--followup", type=Path, help="output directory of run_followup_four_core.sh")
    parser.add_argument("--ham-random", type=Path, help="output directory of run_ham_random_four_core.sh")
    args = parser.parse_args()

    report_tables._install_import_stubs()
    rebench = report_tables._load_rebench()
    paper = Source(rebench, PAPER_MAIN, PAPER_FOLLOWUP, PAPER_HAM_RANDOM)
    rerun = None
    if args.rerun is not None:
        main_report = args.rerun / "paper_instances.json"
        if not main_report.is_file():
            print(f"[error] no paper_instances.json in {args.rerun}", file=sys.stderr)
            return 1
        followup = args.followup or _first_dir(args.rerun / "followup", args.rerun.parent / "followup")
        ham_random = args.ham_random or _first_dir(args.rerun / "ham-random", args.rerun.parent / "ham-random")
        rerun = Source(rebench, main_report, followup, ham_random)
        print(f"Rerun:      {main_report}")
        print(f"Follow-ups: {rerun.followup or 'not found'}; {rerun.ham_random or 'not found'}\n")
    print(tables(paper, rerun))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
