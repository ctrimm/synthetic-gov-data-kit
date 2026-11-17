#!/usr/bin/env python3
"""Build a joint household-type table from ACS PUMS for one state and vintage (#8).

The summary-table census files hold one rate per trait, so 'realistic' profiles
used to draw each trait independently and lose the correlations that drive
eligibility (income vs. household size, age vs. disability, earnings vs. age).
This script reads the ACS Public Use Microdata Sample and writes a weighted table
of household *types*:

    (household size 1..6+, income band, any member 60+ or disabled, any member
     under 18, has earnings, head is a citizen, head's age band)

with each type's total household weight (WGTP) and its weighted mean share of
income that is earned. No individual record is written: a sampler picks a type by
weight and draws synthetic values within it, and types backed by fewer than
MIN_RECORDS unweighted households are not written: each is folded into the nearest
written type with the same size, children, elderly/disabled, earnings and head
citizenship (closest income band, then age band; relaxing citizenship, then
earnings, when there is none), so suppression does not bias those shares. Output:
data/census/<survey>/<year>/pums/<state>.json.

Usage:
    python scripts/build_pums_households.py --state VA --year 2024 --survey acs5

Network: www2.census.gov (keyless). Downloads are streamed to a temp directory and
deleted afterwards. This is a maintainer tool; govsynth reads only the output.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www2.census.gov/programs-surveys/acs/data/pums/{year}/{span}/csv_{kind}{st}.zip"
MIN_RECORDS = 3

# Annual household income band edges (dollars of the vintage year). The top band is
# capped at the sampler's $50,000/month ($600,000/year) ceiling.
INCOME_EDGES = [0, 5_000, 10_000, 15_000, 20_000, 25_000, 30_000, 40_000, 50_000, 60_000, 75_000,
                100_000, 125_000, 150_000, 200_000, 300_000, 600_000]  # fmt: skip
AGE_BANDS = [(15, 29), (30, 44), (45, 59), (60, 74), (75, 99)]


def _income_band(income: float) -> int:
    income = min(max(income, 0.0), INCOME_EDGES[-1] - 1)
    for i in range(len(INCOME_EDGES) - 1):
        if income < INCOME_EDGES[i + 1]:
            return i
    return len(INCOME_EDGES) - 2


def _age_band(age: int) -> int:
    for i, (lo, hi) in enumerate(AGE_BANDS):
        if lo <= age <= hi:
            return i
    return 0 if age < AGE_BANDS[0][0] else len(AGE_BANDS) - 1


# Key positions a neighbour must match, most to least specific (see reassign_small_cells).
_NEIGHBOUR_LEVELS = [(0, 2, 3, 4, 5), (0, 2, 3, 4), (0, 2, 3)]


def reassign_small_cells(
    cells: dict[tuple[int, ...], list[float]], min_records: int
) -> tuple[dict[tuple[int, ...], list[float]], float, float]:
    """Fold cells with fewer than min_records records into their nearest kept neighbour.

    Key layout: (size, income_band, eld_dis, kids, earns, head_citizen, age_band).
    A neighbour shares size and the four booleans -- or, failing that, size, children,
    elderly/disabled and earnings; then size, children and elderly/disabled.
    Distance is income-band gap, then age-band gap. Kept cells keep their unweighted count (>= min_records), so no
    written type is backed by fewer records than the threshold.

    Returns:
        (kept cells with folded-in weight, reassigned weight, dropped weight)
    """
    kept = {k: list(v) for k, v in cells.items() if v[1] >= min_records}
    reassigned = dropped = 0.0
    for k, v in cells.items():
        if v[1] >= min_records:
            continue
        candidates: list[tuple[int, ...]] = []
        for fields in _NEIGHBOUR_LEVELS:
            candidates = [kk for kk in kept if all(kk[i] == k[i] for i in fields)]
            if candidates:
                break
        if not candidates:
            dropped += v[0]
            continue
        target = min(candidates, key=lambda kk: (abs(kk[1] - k[1]), abs(kk[6] - k[6]), kk))
        kept[target][0] += v[0]
        kept[target][2] += v[2]
        reassigned += v[0]
    return kept, reassigned, dropped


def _download(url: str, dest: Path) -> Path:
    with httpx.stream("GET", url, timeout=600, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(1 << 20):
                f.write(chunk)
    return dest


def _rows(zip_path: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        with z.open(name) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))


def build(state: str, year: int, survey: str, workdir: Path) -> dict[str, Any]:
    """Download one state's PUMS household and person files and aggregate household types."""
    span = "5-Year" if survey == "acs5" else "1-Year"
    st = state.lower()
    h_zip = _download(BASE.format(year=year, span=span, kind="h", st=st), workdir / "h.zip")
    p_zip = _download(BASE.format(year=year, span=span, kind="p", st=st), workdir / "p.zip")

    people: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "head_age": None,
            "head_citizen": True,
            "any_60": False,
            "any_dis": False,
            "any_kid": False,
            "earnings": 0.0,
        }  # fmt: skip
    )
    for r in _rows(p_zip):
        hh = people[r["SERIALNO"]]
        age = int(r["AGEP"])
        adj = int(r["ADJINC"]) / 1_000_000
        if r.get("RELSHIPP") == "20":  # reference person
            hh["head_age"] = age
            hh["head_citizen"] = r["CIT"] != "5"
        hh["any_60"] |= age >= 60
        hh["any_dis"] |= r["DIS"] == "1"
        hh["any_kid"] |= age < 18
        hh["earnings"] += (float(r["WAGP"] or 0) + float(r["SEMP"] or 0)) * adj
    p_zip.unlink()

    cells: dict[tuple[int, ...], list[float]] = defaultdict(lambda: [0.0, 0, 0.0])  # weight, n, weighted earned share
    total_weight = 0.0
    for r in _rows(h_zip):
        if r["TYPEHUGQ"] != "1" or int(r["NP"] or 0) == 0 or not r["HINCP"]:
            continue  # group quarters and vacant units
        hh = people.get(r["SERIALNO"])
        if hh is None or hh["head_age"] is None:
            continue
        weight = float(r["WGTP"])
        income = float(r["HINCP"]) * int(r["ADJINC"]) / 1_000_000
        earned_share = min(max(hh["earnings"] / income, 0.0), 1.0) if income > 0 else 0.0
        key = (
            min(int(r["NP"]), 6),
            _income_band(income),
            int(hh["any_60"] or hh["any_dis"] or hh["head_age"] >= 60),
            int(hh["any_kid"]),
            int(hh["earnings"] > 0),
            int(hh["head_citizen"]),
            _age_band(hh["head_age"]),
        )
        cell = cells[key]
        cell[0] += weight
        cell[1] += 1
        cell[2] += weight * earned_share
        total_weight += weight
    h_zip.unlink()

    kept, reassigned, dropped = reassign_small_cells(cells, MIN_RECORDS)
    return {
        "_metadata": {
            "state": state.upper(),
            "acs_vintage": year,
            "acs_survey": survey,
            "dollar_year": year,
            "source": f"ACS {year} {span} Public Use Microdata Sample (household + person files)",
            "source_urls": [BASE.format(year=year, span=span, kind=k, st=st) for k in ("h", "p")],
            "built": date.today().isoformat(),
            "households_unweighted": int(sum(v[1] for v in cells.values())),
            "households_weighted": round(total_weight),
            "min_records_per_type": MIN_RECORDS,
            "suppressed_weight_share": round((reassigned + dropped) / total_weight, 4),
            "reassigned_weight_share": round(reassigned / total_weight, 4),
            "dropped_weight_share": round(dropped / total_weight, 4),
            "definition": (
                "Household types from occupied housing units (group quarters excluded). Income: HINCP x ADJINC "
                f"({year} dollars), clipped to [0, 600000). eld_dis: any member 60+ or with a disability (DIS=1). "
                "kids: any member under 18. earns: WAGP+SEMP > 0. head_citizen: reference person's CIT != 5. "
                "earned_share: weighted mean of (WAGP+SEMP)/HINCP clipped to [0,1]."
            ),
        },
        "income_edges": INCOME_EDGES,
        "age_bands": AGE_BANDS,
        "fields": [
            "size",
            "income_band",
            "eld_dis",
            "kids",
            "earns",
            "head_citizen",
            "age_band",
            "weight",
            "earned_share",
        ],
        "types": [[*k, round(v[0]), round(v[2] / v[0], 3) if v[0] else 0.0] for k, v in sorted(kept.items())],
    }


def main(argv: list[str]) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--state", required=True)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--survey", choices=["acs5", "acs1"], default="acs5")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        data = build(args.state, args.year, args.survey, Path(tmp))
    out = ROOT / "data" / "census" / args.survey / str(args.year) / "pums" / f"{args.state.lower()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    meta = data["_metadata"]
    print(
        f"{args.state.upper()} {args.survey}-{args.year}: {len(data['types'])} household types from "
        f"{meta['households_unweighted']:,} households; reassigned {meta['reassigned_weight_share']:.2%}, "
        f"dropped {meta['dropped_weight_share']:.2%} -> "
        f"{out.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
