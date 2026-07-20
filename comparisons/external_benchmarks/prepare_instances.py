#!/usr/bin/env python3
"""Fetch, verify, and prepare the paper's external benchmark instances."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import lzma
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(source: dict, cache: Path, filename: str) -> Path:
    target = cache / filename
    expected = source["sha256"]
    if target.exists() and sha256(target) == expected:
        return target
    target.unlink(missing_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    partial.unlink(missing_ok=True)
    print(f"downloading {source['url']}", flush=True)
    request = urllib.request.Request(
        source["url"], headers={"User-Agent": "nevergrad-alenex-artifact/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        with partial.open("wb") as output:
            shutil.copyfileobj(response, output)
    actual = sha256(partial)
    if actual != expected:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch for {source['url']}: {actual} != {expected}")
    partial.replace(target)
    return target


def download_gbd_cnf(source: dict, cache: Path) -> Path:
    target = cache / f"{source['gbd_hash']}.cnf"
    expected = source["sha256_uncompressed"]
    if target.exists() and sha256(target) == expected:
        return target
    target.unlink(missing_ok=True)
    request = urllib.request.Request(
        source["url"], headers={"User-Agent": "nevergrad-alenex-artifact/1.0"}
    )
    print(f"downloading {source['url']}", flush=True)
    with urllib.request.urlopen(request, timeout=120) as response:
        data = lzma.decompress(response.read())
    actual = sha256_bytes(data)
    if actual != expected:
        raise RuntimeError(f"checksum mismatch for {source['url']}: {actual} != {expected}")
    target.write_bytes(data)
    return target


def tsplib_header(data: bytes) -> tuple[str | None, int | None]:
    problem_type = None
    dimension = None
    for raw in data.decode("latin-1").splitlines():
        fields = raw.replace(":", " ").split()
        if not fields:
            continue
        if fields[0] == "TYPE" and len(fields) > 1:
            problem_type = fields[1]
        elif fields[0] == "DIMENSION" and len(fields) > 1:
            dimension = int(fields[1])
        if problem_type is not None and dimension is not None:
            break
    return problem_type, dimension


def reset_directory(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)


def prepare_tsplib(archive: Path, destination: Path) -> list[Path]:
    reset_directory(destination)
    selected = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            if not member.isfile() or not member.name.endswith(".tsp.gz"):
                continue
            extracted = bundle.extractfile(member)
            if extracted is None:
                continue
            data = gzip.decompress(extracted.read())
            problem_type, dimension = tsplib_header(data)
            if problem_type == "TSP" and dimension is not None and dimension <= 300:
                target = destination / Path(member.name).name.removesuffix(".gz")
                target.write_bytes(data)
                selected.append(target)
    selected.sort()
    expected = MANIFEST["sources"]["tsplib95"]["expected_count"]
    if len(selected) != expected:
        raise RuntimeError(f"selected {len(selected)} TSPLIB files, expected {expected}")
    return selected


def prepare_hard_tsplib(archive: Path, destination: Path) -> list[Path]:
    reset_directory(destination)
    selected = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            path = Path(member.name)
            if not member.isfile() or path.parent.name != "instances" or path.suffix != ".tsp":
                continue
            extracted = bundle.extractfile(member)
            if extracted is None:
                continue
            target = destination / path.name
            target.write_bytes(extracted.read())
            selected.append(target)
    selected.sort()
    expected = MANIFEST["sources"]["hard_tsplib"]["expected_count"]
    if len(selected) != expected:
        raise RuntimeError(f"selected {len(selected)} Hard-TSPLIB files, expected {expected}")
    return selected


def prepare_fhcp(archive: Path, destination: Path) -> list[Path]:
    reset_directory(destination)
    bsdtar = shutil.which("bsdtar")
    if bsdtar is None:
        raise RuntimeError("bsdtar is required to extract the official FHCPCS.7z archive")
    names = {f"graph{index}.hcp" for index in range(5, 16)}
    with tempfile.TemporaryDirectory(prefix="fhcp_extract_", dir=destination.parent) as temporary:
        subprocess.run([bsdtar, "-xf", str(archive), "-C", temporary], check=True)
        available = {path.name: path for path in Path(temporary).rglob("*.hcp")}
        missing = sorted(names - available.keys())
        if missing:
            raise RuntimeError(f"FHCP archive is missing {missing}")
        selected = []
        for name in sorted(names, key=lambda value: int(value[5:-4])):
            data = available[name].read_bytes()
            problem_type, dimension = tsplib_header(data)
            if problem_type != "HCP" or dimension is None or not 90 <= dimension <= 150:
                raise RuntimeError(f"unexpected FHCP header for {name}: {problem_type}, {dimension}")
            target = destination / name
            target.write_bytes(data)
            selected.append(target)
    expected = MANIFEST["sources"]["fhcp"]["expected_count"]
    if len(selected) != expected:
        raise RuntimeError(f"selected {len(selected)} FHCP files, expected {expected}")
    return selected


def write_explicit_tsp(path: Path, matrix: np.ndarray, name: str) -> None:
    n = len(matrix)
    lines = [
        f"NAME: {name}",
        "TYPE: TSP",
        f"DIMENSION: {n}",
        "EDGE_WEIGHT_TYPE: EXPLICIT",
        "EDGE_WEIGHT_FORMAT: UPPER_ROW",
        "EDGE_WEIGHT_SECTION",
    ]
    for row in range(n):
        lines.append(" ".join(str(int(np.rint(matrix[row, column]))) for column in range(row + 1, n)))
    lines.append("EOF")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_clustered(destination: Path) -> list[Path]:
    reset_directory(destination)
    selected = []
    specification = MANIFEST["deterministic_generators"]["clustered_euclidean"]
    n_clusters = specification["clusters"]
    for n in specification["sizes"]:
        for seed in specification["seeds"]:
            rng = np.random.default_rng(seed)
            per_cluster, remainder = divmod(n, n_clusters)
            coordinates = []
            for cluster in range(n_clusters):
                center = rng.uniform(0, 10000, size=2)
                count = per_cluster + (1 if cluster < remainder else 0)
                for _ in range(count):
                    coordinates.append(center + rng.normal(0, 10, size=2))
            points = np.asarray(coordinates)
            matrix = np.zeros((n, n))
            for left in range(n):
                for right in range(left + 1, n):
                    distance = np.sqrt(np.sum((points[left] - points[right]) ** 2))
                    matrix[left, right] = matrix[right, left] = distance
            target = destination / f"clustered_{n}_s{seed}.tsp"
            write_explicit_tsp(target, matrix, target.stem)
            selected.append(target)
    return selected


def write_dimacs(
    path: Path, n_variables: int, clauses: list[list[int]], comment: str | None
) -> None:
    lines = [] if comment is None else [f"c {comment}"]
    lines.append(f"p cnf {n_variables} {len(clauses)}")
    lines.extend(" ".join(str(literal) for literal in clause) + " 0" for clause in clauses)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pigeonhole() -> tuple[int, list[list[int]]]:
    holes = 11
    pigeons = holes + 1
    variable = lambda pigeon, hole: pigeon * holes + hole + 1
    clauses = [[variable(pigeon, hole) for hole in range(holes)] for pigeon in range(pigeons)]
    for hole in range(holes):
        for first in range(pigeons):
            for second in range(first + 1, pigeons):
                clauses.append([-variable(first, hole), -variable(second, hole)])
    return pigeons * holes, clauses


def van_der_waerden() -> tuple[int, list[list[int]]]:
    n = 160
    clauses = []
    for length, positive in ((3, True), (13, False)):
        for difference in range(1, (n - 1) // (length - 1) + 1):
            for start in range(1, n - (length - 1) * difference + 1):
                progression = [start + offset * difference for offset in range(length)]
                clauses.append(progression if positive else [-value for value in progression])
    return n, clauses


def prepare_sat(destination: Path, tseitin_source: Path) -> list[Path]:
    reset_directory(destination)
    outputs = []
    for filename, generator, comment in (
        ("php12_11.cnf", pigeonhole, None),
        ("vdw_2_3_13_n160.cnf", van_der_waerden, "two-colour van der Waerden W(2;3,13) contradiction on [160]"),
    ):
        n_variables, clauses = generator()
        target = destination / filename
        write_dimacs(target, n_variables, clauses, comment)
        outputs.append(target)
    tseitin_target = destination / "tseitin_gbd_144799_150v_400c.cnf"
    tseitin_target.write_bytes(tseitin_source.read_bytes())
    outputs.append(tseitin_target)
    expected_headers = {
        "php12_11.cnf": (132, 738),
        "tseitin_gbd_144799_150v_400c.cnf": (150, 400),
        "vdw_2_3_13_n160.cnf": (160, 7308),
    }
    for path in outputs:
        header = next(line for line in path.read_text().splitlines() if line.startswith("p cnf"))
        _, _, n_variables, n_clauses = header.split()
        actual = (int(n_variables), int(n_clauses))
        if actual != expected_headers[path.name]:
            raise RuntimeError(f"bad SAT dimensions for {path}: {actual}")
    expected_php = (
        "948c811b15dd757ac0c50db9ce1b5a781a498c326dc7e13d19aa887456b5a036"
    )
    if sha256(destination / "php12_11.cnf") != expected_php:
        raise RuntimeError("PHP generator no longer matches the recovered gen_hard_tests.py order")
    expected_vdw = (
        "7a3425ca3d8a0331b72087820f0a0112db9db441b9b911d90dd7a8bcdd02ee14"
    )
    if sha256(destination / "vdw_2_3_13_n160.cnf") != expected_vdw:
        raise RuntimeError("van der Waerden generator output changed")
    return outputs


def digest_manifest(paths: list[Path]) -> str:
    lines = [f"{path.name} {sha256(path)}" for path in sorted(paths)]
    return sha256_bytes(("\n".join(lines) + "\n").encode())


def prepared_metadata(path: Path) -> dict:
    if path.suffix == ".cnf":
        header = next(
            line for line in path.read_text(errors="replace").splitlines()
            if line.startswith("p cnf")
        )
        _, _, variables, clauses = header.split()[:4]
        return {"type": "CNF", "variables": int(variables), "clauses": int(clauses)}
    problem_type, dimension = tsplib_header(path.read_bytes())
    return {"type": problem_type, "dimension": dimension}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    cache = output / "cache"
    instances = output / "instances"
    cache.mkdir(parents=True, exist_ok=True)
    instances.mkdir(parents=True, exist_ok=True)

    sources = MANIFEST["sources"]
    tsplib_archive = download(sources["tsplib95"], cache, "ALL_tsp.tar.gz")
    hard_archive = download(sources["hard_tsplib"], cache, "HardTSPLIB-74b142a.tar.gz")
    fhcp_archive = download(sources["fhcp"], cache, "FHCPCS.7z")
    tseitin_source = download_gbd_cnf(sources["tseitin_gbd"], cache)

    prepared = {
        "tsplib": prepare_tsplib(tsplib_archive, instances / "tsplib"),
        "hard_tsplib": prepare_hard_tsplib(hard_archive, instances / "hard_tsplib"),
        "fhcp": prepare_fhcp(fhcp_archive, instances / "fhcp"),
        "clustered_euclidean": prepare_clustered(instances / "clustered_euclidean"),
        "sat": prepare_sat(instances / "sat", tseitin_source),
    }
    for family, digest_key in (("tsplib", "tsplib95"), ("fhcp", "fhcp")):
        actual = digest_manifest(prepared[family])
        expected = sources[digest_key]["selected_manifest_digest"]
        if actual != expected:
            raise RuntimeError(f"selected {family} manifest digest {actual} != {expected}")

    report = {
        "schema_version": 1,
        "source_manifest": MANIFEST,
        "families": {
            family: [
                {
                    "path": str(path.relative_to(output)),
                    "sha256": sha256(path),
                    **prepared_metadata(path),
                }
                for path in paths
            ]
            for family, paths in prepared.items()
        },
    }
    (output / "prepared_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"prepared external benchmarks under {output}", flush=True)
    for family, paths in prepared.items():
        print(f"  {family}: {len(paths)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
