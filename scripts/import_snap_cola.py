#!/usr/bin/env python3
"""Build data/thresholds/snap_fy{YEAR}.json from USDA FNS's published SNAP COLA tables.

FNS publishes each fiscal year's SNAP cost-of-living adjustments as three or four
small PDFs (income eligibility standards, maximum allotments + deductions, minimum
allotments). This script downloads them, extracts the tables with `pdftotext -layout`
(poppler-utils), cross-checks every income limit against the HHS poverty guidelines,
and writes a threshold file in the same shape as snap_fy2026.json.

Usage:
    python scripts/import_snap_cola.py 2024            # one fiscal year
    python scripts/import_snap_cola.py 2021 2022 2023 2024 2025
    python scripts/import_snap_cola.py 2024 --check    # parse + verify, write nothing

Adding a year: add its PDF URLs to SOURCES (FNS's media/file names are not
consistent from year to year -- search for "SNAP FY 20XX Maximum Allotments and
Deductions"), and make sure data/thresholds/us_fpl_{YEAR-1}.json exists, since the
income limits are verified against it.

Requires: `pdftotext` on PATH (apt-get install poppler-utils). Network access to
fns-prod.azureedge.us. This is a maintainer tool; nothing in govsynth imports it.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
THRESHOLDS = ROOT / "data" / "thresholds"

_B = "https://fns-prod.azureedge.us/sites/default/files"
_B2 = "https://fna-bwbufwdzbabpezgc.z01.azurefd.us/sites/default/files"

# Per fiscal year: the FNS PDFs that carry the official tables.
SOURCES: dict[int, dict[str, str]] = {
    2021: {
        "income": f"{_B}/media/file/FY21-Income-Eligibility-Standards.pdf",
        "tables": f"{_B}/media/file/FY21-Maximum-Allotments-Deductions.pdf",
        "minimum": f"{_B}/resource-files/FY21MinimumAllotments.pdf",
    },
    2022: {
        "income": f"{_B}/media/file/FY22-Income-Eligibility-Standards%20reviewed.pdf",
        "tables": f"{_B}/media/file/FY22-Maximum-Allotments-Deductions.pdf",
        "minimum": f"{_B}/resource-files/FY22MinimumAllotmentsReviewed.pdf",
    },
    2023: {
        "income": f"{_B}/resource-files/FY23-Income-Eligibility-Standards.pdf",
        "tables": f"{_B}/resource-files/FY23-Maximum-Allotments-Deductions.pdf",
        "minimum": f"{_B}/resource-files/FY23-Minimum-Allotments.pdf",
    },
    2024: {
        "income": f"{_B}/media/file/FY24-Income-Eligibility-Standards.pdf",
        "tables": f"{_B2}/media/file/FY24-Maximum-Allotments-and-Deductions.pdf",
        "minimum": f"{_B}/media/file/FY24-Minimum-Allotments.pdf",
    },
    2025: {
        "income": f"{_B}/media/file/FY2025-Income-Eligibility-Standards.pdf",
        "tables": f"{_B}/media/file/FY2025-Maximum-Allotments-Deductions.pdf",
        "minimum": f"{_B}/media/file/FY2025-Minimum-Allotments.pdf",
    },
}

# Temporary federal changes in force during a fiscal year that this kit's
# threshold model (regular COLA tables) does not represent. Recorded in each
# file so a generated case's provenance says what was left out.
NOT_MODELED: dict[int, list[str]] = {
    2021: [
        "Temporary 15% increase in maximum allotments, January-September 2021 (Consolidated "
        "Appropriations Act, 2021, sec. 702; extended by the American Rescue Plan Act, sec. 1101). "
        "The allotments here are the regular FY2021 COLA tables.",
        "COVID-19 emergency allotments (Families First Coronavirus Response Act, sec. 2302), "
        "which raised most households to the maximum allotment in states with an emergency "
        "declaration.",
        "Temporary student eligibility exemptions (Consolidated Appropriations Act, 2021, sec. 702(e)) "
        "for students eligible for work study or with an expected family contribution of $0.",
    ],
    2022: [
        "COVID-19 emergency allotments (FFCRA sec. 2302), in effect in most states.",
        "Temporary student eligibility exemptions (CAA 2021 sec. 702(e)).",
    ],
    2023: [
        "COVID-19 emergency allotments, which ended nationwide after February 2023 "
        "(Consolidated Appropriations Act, 2023, sec. 1300); some states ended them earlier.",
        "Temporary student eligibility exemptions, which ended with the COVID-19 public health "
        "emergency (May 11, 2023), applied until each household's next recertification.",
    ],
}

_REGIONS_ALLOT = ["48_states_dc", "alaska_urban", "alaska_rural1", "alaska_rural2", "guam", "hawaii", "virgin_islands"]
_REGIONS_DED = ["48_states_dc", "alaska", "guam", "hawaii", "virgin_islands"]
_REGIONS_INCOME = ["48_states_dc", "alaska", "hawaii"]


def _money(tok: str) -> float:
    return float(tok.replace("$", "").replace(",", "").replace("+", ""))


def _nums(line: str) -> list[float]:
    """All dollar figures on a line (handles '$1,234', '1,819', '+$486', '$166.81')."""
    return [_money(t) for t in re.findall(r"\+?\$?\d[\d,]*(?:\.\d+)?", line)]


def _pdftext(url: str, workdir: Path) -> str:
    path = workdir / (re.sub(r"[^A-Za-z0-9.]+", "_", url.rsplit("/", 1)[-1]))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (govsynth threshold importer)"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 -- fixed https FNS URLs
        path.write_bytes(resp.read())
    if not path.read_bytes().startswith(b"%PDF"):
        raise RuntimeError(f"{url} did not return a PDF")
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True)
    return out.stdout


def _size_rows(lines: list[str], start: int, width: int) -> tuple[dict[str, list[float]], int]:
    """Read household-size rows 1..8 (+ 'each additional') with `width` numeric columns."""
    rows: dict[str, list[float]] = {}
    i = start
    while i < len(lines) and len(rows) < 9:
        line = lines[i]
        m = re.match(r"^\s*([1-8])\s+(.*)$", line)
        if m and len(rows) < 8:
            vals = _nums(m.group(2))
            if len(vals) == width:
                rows[m.group(1)] = vals
        elif len(rows) == 8:
            # "Each Additional Member" may be split over lines; take the first line with `width` numbers.
            vals = _nums(line)
            if len(vals) == width:
                rows["each_additional"] = vals
        i += 1
    if len(rows) != 9:
        raise ValueError(f"expected 8 size rows + each additional, got {sorted(rows)}")
    return rows, i


def _find(lines: list[str], pattern: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if re.search(pattern, lines[i], re.I):
            return i
    raise ValueError(f"pattern not found: {pattern}")


def parse_income(text: str) -> dict[str, dict[str, list[float]]]:
    """Return {'gross'|'net'|'165': {size: [48, AK, HI]}} -- tables may appear in any order."""
    lines = text.splitlines()
    out: dict[str, dict[str, list[float]]] = {}
    for key, pat in [("gross", r"Gross Monthly Income Limit \(130%"), ("net", r"Net Monthly Income Limit"),
                     ("165", r"Separate Household|\(165% of")]:  # fmt: skip
        rows, _ = _size_rows(lines, _find(lines, pat), 3)
        out[key] = rows
    return out


def parse_tables(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    allot, _ = _size_rows(lines, _find(lines, r"Maximum Monthly Allotment"), 7)
    i = _find(lines, r"Standard Deductions")
    std: dict[str, list[float]] = {}
    for line in lines[i:]:
        m = re.match(r"^\s*(1|2|3|4|5|6\+)\s+(.*)$", line)
        if m:
            vals = _nums(m.group(2))
            if len(vals) == 5:
                std[m.group(1)] = vals
        if len(std) == 6:
            break
    shelter_i = _find(lines, r"Maximum (Excess )?Shelter Deduction")
    shelter = next(v for v in (_nums(x) for x in lines[shelter_i + 1 :]) if len(v) == 5)
    homeless_i = _find(lines, r"Homeless Shelter Deduction")
    homeless = next(v for v in (_nums(x) for x in lines[homeless_i + 1 :]) if len(v) == 5)
    asset_i = _find(lines, r"Maximum Asset Limits")
    assets = next(v for v in (_nums(x) for x in lines[asset_i + 1 :]) if len(v) == 2)
    if len(std) != 6:
        raise ValueError(f"standard deduction rows: {sorted(std)}")
    if len(set(homeless)) != 1:
        raise ValueError(f"homeless deduction differs by region: {homeless}")
    return {"allot": allot, "std": std, "shelter": shelter, "homeless": homeless[0], "assets": assets}


def parse_minimum(text: str) -> list[float]:
    for line in text.splitlines():
        m = re.match(r"^\s*1-2\s+(.*)$", line)
        if m:
            vals = _nums(m.group(1))
            if len(vals) == 7:
                return vals
    raise ValueError("minimum allotment row '1-2' not found")


def _fpl(year: int) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((THRESHOLDS / f"us_fpl_{year}.json").read_text())
    return data["regions"]


def verify_income(fy: int, income: dict[str, dict[str, list[float]]]) -> None:
    """Every printed limit must equal ceil(annual FPL x pct / 12) for the prior year's guidelines."""
    regions = _fpl(fy - 1)
    fpl_key = {"48_states_dc": "contiguous_48_dc", "alaska": "alaska", "hawaii": "hawaii"}
    for table, pct in [("gross", 130), ("net", 100), ("165", 165)]:
        for col, region in enumerate(_REGIONS_INCOME):
            r = regions[fpl_key[region]]
            for size in range(1, 9):
                annual = r["by_household_size"][str(size)]["annual"]
                want = math.ceil(annual * pct / 100 / 12)
                got = income[table][str(size)][col]
                if got != want:
                    raise ValueError(f"FY{fy} {table} {region} size {size}: printed {got}, FPL formula {want}")


def build(fy: int, income: dict[str, Any], tables: dict[str, Any], minimum: list[float]) -> dict[str, Any]:
    """Assemble the snap_fy{fy}.json structure (same keys as snap_fy2026.json)."""
    a = {region: {s: row[c] for s, row in tables["allot"].items()} for c, region in enumerate(_REGIONS_ALLOT)}
    inc = {
        region: {t: {s: row[c] for s, row in income[t].items()} for t in ("gross", "net", "165")}
        for c, region in enumerate(_REGIONS_INCOME)
    }
    mins = dict(zip(_REGIONS_ALLOT, minimum, strict=True))

    def hh(income_region: str, allot_region: str) -> dict[str, Any]:
        out = {}
        for s in [*map(str, range(1, 9)), "each_additional"]:
            out[s] = {
                "gross_monthly": int(inc[income_region]["gross"][s]),
                "net_monthly": int(inc[income_region]["net"][s]),
                "max_benefit": int(a[allot_region][s]),
            }
        return out

    alaska = {}
    for s in [*map(str, range(1, 9)), "each_additional"]:
        alaska[s] = {
            "gross_monthly": int(inc["alaska"]["gross"][s]),
            "net_monthly": int(inc["alaska"]["net"][s]),
            "max_benefit_urban": int(a["alaska_urban"][s]),
            "max_benefit_rural1": int(a["alaska_rural1"][s]),
            "max_benefit_rural2": int(a["alaska_rural2"][s]),
        }
    std = {region: {k: int(v[c]) for k, v in tables["std"].items()} for c, region in enumerate(_REGIONS_DED)}
    shelter = dict(zip(_REGIONS_DED, tables["shelter"], strict=True))
    elderly_assets, general_assets = tables["assets"]
    src = SOURCES[fy]
    start, end = f"{fy - 1}-10-01", f"{fy}-09-30"
    return {
        "_metadata": {
            "program": "snap",
            "period": f"FY{fy}",
            "fiscal_year": fy,
            "federal_fy_start": start,
            "federal_fy_end": end,
            "fpl_basis_year": fy - 1,
            "source": f"USDA FNS SNAP FY{fy} Cost-of-Living Adjustments: Income Eligibility Standards, "
            "Maximum Allotments and Deductions, and Minimum Allotments tables",
            "source_url": src["tables"],
            "source_url_income_standards": src["income"],
            "source_url_minimum_allotments": src["minimum"],
            "cfr_reference": "7 CFR 273.9",
            "verification_status": "verified",
            "verification_note": (
                "Transcribed by scripts/import_snap_cola.py from the official FNS tables (pdftotext). "
                f"Every gross (130%), net (100%) and 165% income limit was checked against "
                f"ceil(annual FPL x pct / 12) using us_fpl_{fy - 1}.json."
            ),
            "not_modeled": NOT_MODELED.get(fy, []),
        },
        "gross_income_pct_fpl": 130,
        "net_income_pct_fpl": 100,
        "earned_income_deduction_pct": 20,
        "asset_limit_general": int(general_assets),
        "asset_limit_elderly_disabled": int(elderly_assets),
        "households_48_states_dc": hh("48_states_dc", "48_states_dc"),
        "households_alaska": alaska,
        "households_hawaii": hh("hawaii", "hawaii"),
        "households_guam": hh("48_states_dc", "guam"),
        "households_virgin_islands": hh("48_states_dc", "virgin_islands"),
        **{f"standard_deductions_{r}": std[r] for r in ["48_states_dc", "alaska", "hawaii", "guam", "virgin_islands"]},
        **{
            f"excess_shelter_deduction_cap_{r}": int(shelter[r])
            for r in ["48_states_dc", "alaska", "hawaii", "guam", "virgin_islands"]
        },
        "homeless_shelter_deduction": tables["homeless"],
        "minimum_benefit_48_states_dc": int(mins["48_states_dc"]),
        "minimum_benefit_alaska": int(mins["alaska_urban"]),
        "minimum_benefit_hawaii": int(mins["hawaii"]),
        "minimum_benefit_guam": int(mins["guam"]),
        "minimum_benefit_virgin_islands": int(mins["virgin_islands"]),
        "gross_income_165pct_households_48_states_dc": {s: int(v) for s, v in inc["48_states_dc"]["165"].items()},
        "notes": [
            f"Effective October 1, {fy - 1} through September 30, {fy}.",
            f"Asset limits: ${int(general_assets):,} general, ${int(elderly_assets):,} with a member 60+ or disabled.",
            "Guam and the Virgin Islands share the 48-states income limits (FNS prints one column for "
            "'48 States, D.C., Guam, Virgin Islands'); only their allotments and deductions differ.",
            "minimum_benefit_alaska is the Urban tier, matching the Urban default for Alaska's max allotment.",
        ],
    }


def main(argv: list[str]) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("years", type=int, nargs="+")
    parser.add_argument("--check", action="store_true", help="parse and verify only; write nothing")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for fy in args.years:
            if fy not in SOURCES:
                print(f"FY{fy}: no SOURCES entry", file=sys.stderr)
                return 2
            src = SOURCES[fy]
            income = parse_income(_pdftext(src["income"], work))
            verify_income(fy, income)
            tables = parse_tables(_pdftext(src["tables"], work))
            data = build(fy, income, tables, parse_minimum(_pdftext(src["minimum"], work)))
            out = THRESHOLDS / f"snap_fy{fy}.json"
            if args.check:
                print(f"FY{fy}: parsed and verified (not written)")
            else:
                out.write_text(json.dumps(data, indent=2) + "\n")
                print(f"FY{fy}: wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
