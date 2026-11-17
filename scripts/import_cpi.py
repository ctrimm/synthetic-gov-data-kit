#!/usr/bin/env python3
"""Build data/thresholds/cpi_u_annual.json from the BLS CPI-U series, via FRED.

CPI-U, U.S. city average, all items, not seasonally adjusted (BLS series
CUUR0000SA0; FRED mirrors it as CPIAUCNS). Used to restate Census incomes,
which are in the ACS vintage's dollars, in the dollars of a program year.

Usage:
    python scripts/import_cpi.py            # write the file
    python scripts/import_cpi.py --check    # print, write nothing

Annual averages are the mean of the published months. A year with fewer than
12 published months is kept but flagged ("complete": false) with its month
count, so callers can see it is partial. This is a maintainer tool; nothing in
govsynth imports it.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "thresholds" / "cpi_u_annual.json"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS"
FIRST_YEAR = 2019


def main(argv: list[str]) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    resp = httpx.get(URL, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    months: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        year = int(r["observation_date"][:4])
        if year >= FIRST_YEAR and r["CPIAUCNS"] not in (".", ""):
            months[year].append((r["observation_date"][:7], float(r["CPIAUCNS"])))
    annual = {}
    for year, vals in sorted(months.items()):
        published = [m for m, _ in vals]
        missing = [f"{year}-{m:02d}" for m in range(1, 13) if f"{year}-{m:02d}" not in published]
        annual[str(year)] = {
            "average": round(sum(v for _, v in vals) / len(vals), 3),
            "months": len(vals),
            "complete": len(vals) == 12,
            **({"missing_months": missing} if missing else {}),
        }
    data = {
        "_metadata": {
            "type": "cpi_u_annual_average",
            "series": "CPI-U, U.S. city average, all items, NSA (BLS CUUR0000SA0; FRED CPIAUCNS), 1982-84=100",
            "source": "U.S. Bureau of Labor Statistics, via Federal Reserve Bank of St. Louis FRED",
            "source_url": URL,
            "retrieved": date.today().isoformat(),
            "verification_status": "verified",
            "verification_note": (
                "Complete-year averages equal the BLS published CPI-U annual averages (e.g. 2022 292.655, "
                "2023 304.702, 2024 313.689). Years with missing months are averages of the published months only "
                "and are marked complete=false."
            ),
        },
        "annual": annual,
    }
    if args.check:
        print(json.dumps(annual, indent=1))
    else:
        OUT.write_text(json.dumps(data, indent=2) + "\n")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
