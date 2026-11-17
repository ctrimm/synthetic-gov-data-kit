#!/usr/bin/env python3
"""Import SNAP caseload targets from the FNS 'Characteristics of SNAP Households' report (#9).

The report tabulates the SNAP Quality Control sample: the weighted, household-level
record of who actually receives SNAP. This script reads the report PDF (via
`pdftotext -layout`) and writes data/caseload/snap_qc_fy<YEAR>.json with:

- ``national``: cross-tabulations (thousands of households) that give the caseload's
  joint structure -- children x elderly/disabled, each of those x household size,
  x gross income as a percent of poverty, and x income type; size x poverty.
  (Tables A.3, A.4, A.6, A.17.)
- ``states``: per-state marginals -- poverty bins (B.3), household composition
  (B.5), income sources (B.6), average size and gross income (B.2), and the
  noncitizen share of participants (B.16).

The QC microdata itself (snapqcdata.net) is not used: it refuses automated access.

Usage:
    python scripts/import_snap_qc.py --pdf snap-fy2024householdcharacteristics-report.pdf --year 2024

Source PDF:
    https://fns-prod.azureedge.us/sites/default/files/resource-files/snap-fy2024householdcharacteristics-report.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SOURCE_URL = (
    "https://fns-prod.azureedge.us/sites/default/files/resource-files/snap-fy{year}householdcharacteristics-report.pdf"
)

STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "Guam": "GU", "Virgin Islands": "VI",
}  # fmt: skip

_NUM = r"-?[\d,]+(?:\.\d+)?†?|-|‡"
POV_BINS = ["none", "le25", "26_50", "51_75", "76_100", "101_130", "gt130"]
SIZES = ["1", "2", "3", "4", "5", "6"]


def _num(tok: str) -> float:
    tok = tok.rstrip("†")
    return 0.0 if tok in ("-", "‡") else float(tok.replace(",", ""))


def _table_body(lines: list[str], title: str) -> list[str]:
    """Lines of a table body (incl. continuation pages), excluding the table of contents."""
    starts = [i for i, ln in enumerate(lines) if ln.startswith(title) and "...." not in ln]
    if not starts:
        raise ValueError(f"table not found: {title}")
    i = starts[-1]
    body: list[str] = []
    for ln in lines[i + 1 :]:
        if ln.startswith("Table ") and not ln.startswith(title.rstrip(".") + " (continued)"):
            break
        body.append(ln)
    return body


def _rows(body: list[str]) -> list[tuple[str, list[float]]]:
    """(label, numbers) for every data row; wrapped labels are joined.

    pdftotext -layout separates the label from the numbers (and numbers from each
    other) by two or more spaces, while labels such as "1 to 200" use single spaces.
    """
    out: list[tuple[str, list[float]]] = []
    pending = ""
    for ln in body:
        fields = [f for f in re.split(r"\s{2,}", ln.strip()) if f]
        if not fields:
            pending = ""
            continue
        label = fields[0] if re.search(r"[A-Za-z]", fields[0]) else ""
        tokens = [t for f in (fields[1:] if label else fields) for t in f.split()]
        if tokens and all(re.fullmatch(_NUM, t) for t in tokens):
            full = (pending + " " + label).strip() if pending else label
            out.append((full, [_num(t) for t in tokens]))
            pending = ""
        elif len(fields) == 1 and label and len(label) < 40:
            pending = (pending + " " + label).strip()
        else:
            pending = ""
    return out


def _states(rows: list[tuple[str, list[float]]], width: int) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for label, nums in rows:
        name = re.sub(r"[a-z]$", "", label) if label.startswith("Total") else label
        name = re.sub(r"\s+", " ", name.replace("Totala", "Total"))
        if name in STATE_CODES or name == "Total":
            if len(nums) != width:
                raise ValueError(f"{name}: expected {width} numbers, got {nums}")
            out["US" if name == "Total" else STATE_CODES[name]] = nums
    return out


def _labelled(rows: list[tuple[str, list[float]]], label: str, width: int, nth: int = 0) -> list[float]:
    def matches(lab: str) -> bool:
        # A wrapped section header may be glued in front; a footnote letter may trail.
        return any(c == label or c.endswith(" " + label) for c in (lab, lab[:-1]))

    hits = [n for lab, n in rows if matches(lab) and len(n) == width]
    if len(hits) <= nth:
        raise ValueError(f"row not found: {label!r} (width {width})")
    return hits[nth]


def parse(text: str) -> dict[str, Any]:
    """Parse the report text into national cross-tabs and per-state marginals."""
    lines = text.splitlines()
    b2 = _states(_rows(_table_body(lines, "Table B.2.")), 7)
    b3 = _states(_rows(_table_body(lines, "Table B.3.")), 9)
    b5 = _states(_rows(_table_body(lines, "Table B.5.")), 12)
    b6 = _states(_rows(_table_body(lines, "Table B.6.")), 10)
    b16 = _states(_rows(_table_body(lines, "Table B.16.")), 12)

    a3 = _rows(_table_body(lines, "Table A.3."))
    a4 = _rows(_table_body(lines, "Table A.4."))
    a6 = _rows(_table_body(lines, "Table A.6."))
    a17 = _rows(_table_body(lines, "Table A.17."))

    # A.3 columns: total, children, elderly, non-elderly disabled, elderly or disabled (number, %).
    pov_labels = ["No gross income", "25 percent or less", "26 to 50 percent", "51 to 75 percent",
                  "76 to 100 percent", "101 to 130 percent", "131 percent or greater"]  # fmt: skip
    a3_pov = [_labelled(a3, lab, 10)[0::2] for lab in pov_labels]  # first (gross) occurrence
    a4_pov = [_labelled(a4, lab, 12)[0::2] for lab in pov_labels]
    a6_total = _labelled(a6, "Total", 10)[0::2]
    a6_rows = (("earned", "Countable earned income"), ("ssi", "SSI"), ("social_security", "Social Security"))
    a6_types = {k: _labelled(a6, lab, 10)[0::2] for k, lab in a6_rows}
    # A.17 columns: total, children, school-age, preschool, elderly, non-elderly disabled, eld or dis.
    a17_comp = {k: _labelled(a17, lab, 14)[0::2] for k, lab in
                (("children", "Children"), ("elderly", "Elderly individuals"))}  # fmt: skip
    a17_size = [_labelled(a17, lab, 14)[0::2] for lab in
                ("1 person", "2 people", "3 people", "4 people", "5 people", "6 or more people")]  # fmt: skip

    def by_group(cols: list[float], c: int, e: int, ed: int) -> dict[str, float]:
        """Split a children/elderly/eld-or-dis column triple into children + ed groups."""
        return {"children": cols[c], "elderly": cols[e], "disabled_only": cols[ed] - cols[e]}

    total = a6_total[0]
    kids_eld = a17_comp["children"][4]
    kids_eldis = a17_comp["children"][6]
    elderly, eldis = a17_comp["elderly"][0], a6_total[4]
    national = {
        "total_households_000": total,
        # children (0/1) x ed (none / elderly / non-elderly disabled only), thousands
        "kids_by_ed": {
            "1": {
                "elderly": kids_eld,
                "disabled_only": kids_eldis - kids_eld,
                "none": a17_comp["children"][0] - kids_eldis,
            },
            "0": {
                "elderly": elderly - kids_eld,
                "disabled_only": (eldis - elderly) - (kids_eldis - kids_eld),
                "none": total - a17_comp["children"][0] - (eldis - kids_eldis),
            },
        },  # fmt: skip
        "size": {s: row[0] for s, row in zip(SIZES, a17_size, strict=True)},
        "size_by_group": {s: by_group(row, 1, 4, 6) for s, row in zip(SIZES, a17_size, strict=True)},
        "pov": {b: row[0] for b, row in zip(POV_BINS, a3_pov, strict=True)},
        "pov_by_group": {b: by_group(row, 1, 2, 4) for b, row in zip(POV_BINS, a3_pov, strict=True)},
        "pov_by_size": {b: dict(zip(SIZES, row, strict=True)) for b, row in zip(POV_BINS, a4_pov, strict=True)},
        "income_type": {k: v[0] for k, v in a6_types.items()},
        "income_type_by_group": {k: by_group(v, 1, 2, 4) for k, v in a6_types.items()},
        "group_totals": by_group(a6_total, 1, 2, 4),
    }

    states: dict[str, Any] = {}
    for code in sorted(set(b3) - {"US"}):
        if code in ("GU", "VI"):
            continue
        p3, p5, p6, p2, p16 = b3[code], b5[code], b6[code], b2[code], b16[code]
        participants = p16[0]
        noncitizen = p16[6] + p16[8]  # refugees + other noncitizens
        states[code] = {
            "households_000": p3[0],
            # Gross countable income as % of poverty: zero, 1-50, 51-100, 101+ (row %)
            "pov4_pct": [p3[2], p3[4], p3[6], p3[8]],
            "pct_children": p5[1],
            "pct_elderly": p5[3],
            "pct_nonelderly_disabled": p5[5],
            "pct_elderly_or_disabled": p5[7],
            "pct_earned": p6[1],
            "pct_ga": p6[3],
            "pct_ssi": p6[5],
            "pct_social_security": p6[7],
            "pct_tanf": p6[9],
            "avg_gross_income": p2[1],
            "avg_household_size": p2[5],
            "pct_noncitizen_participants": round(100 * noncitizen / participants, 2) if participants else 0.0,
        }
    return {"national": national, "states": states, "_check_us": {"b3": b3["US"], "b5": b5["US"], "b6": b6["US"]}}


def verify(data: dict[str, Any]) -> list[str]:
    """Internal-consistency checks against the report's own totals."""
    problems = []
    nat = data["national"]
    total = nat["total_households_000"]
    if abs(sum(nat["size"].values()) - total) > 5:
        problems.append(f"size rows sum {sum(nat['size'].values())} != total {total}")
    if abs(sum(nat["pov"].values()) - total) > 5:
        problems.append(f"poverty rows sum {sum(nat['pov'].values())} != total {total}")
    cells = [v for g in nat["kids_by_ed"].values() for v in g.values()]
    if min(cells) < 0 or abs(sum(cells) - total) > 1:
        problems.append(f"kids x ed cells {nat['kids_by_ed']} inconsistent")
    for code, s in data["states"].items():
        if abs(sum(s["pov4_pct"]) - 100) > 0.6:
            problems.append(f"{code}: poverty bins sum to {sum(s['pov4_pct'])}")
        if s["pct_elderly_or_disabled"] + 0.6 < max(s["pct_elderly"], s["pct_nonelderly_disabled"]):
            problems.append(f"{code}: elderly-or-disabled below its parts")
    if len(data["states"]) != 51:
        problems.append(f"expected 51 jurisdictions, got {len(data['states'])}")
    us = data["_check_us"]
    weighted = sum(s["households_000"] for s in data["states"].values())
    if not 0.97 * us["b3"][0] <= weighted <= us["b3"][0]:  # Guam and the Virgin Islands are excluded
        problems.append(f"state households sum {weighted} vs total {us['b3'][0]}")
    return problems


def main(argv: list[str]) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--year", type=int, required=True, help="SNAP fiscal year of the report")
    args = parser.parse_args(argv)
    text = subprocess.run(["pdftotext", "-layout", str(args.pdf), "-"], check=True, capture_output=True, text=True)
    data = parse(text.stdout)
    problems = verify(data)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    del data["_check_us"]
    out = {
        "_metadata": {
            "program": "snap",
            "fiscal_year": args.year,
            "source": f"USDA FNS, Characteristics of Supplemental Nutrition Assistance Program Households: Fiscal Year "
            f"{args.year} (SNAP Quality Control sample)",
            "source_url": SOURCE_URL.format(year=args.year),
            "tables": "National: A.3, A.4, A.6, A.17. States: B.2, B.3, B.5, B.6, B.16.",
            "fpl_basis_year": args.year - 1,
            "units": "national: thousands of households; states: row percents unless named otherwise",
            "definitions": {
                "elderly": "household has a member 60+",
                "disabled_only": "household has a non-elderly member with a disability and no elderly member",
                "pov bins": "gross countable monthly income as a percent of the HHS poverty guideline, "
                + ", ".join(POV_BINS),
                "pct_noncitizen_participants": "refugees + other noncitizens as a share of participants "
                "(person level, Table B.16)",
            },
            "imported": date.today().isoformat(),
            "verification_status": "verified",
            "verification_note": "Parsed from the report PDF; row sums checked against the report's totals.",
        },
        **data,
    }
    path = ROOT / "data" / "caseload" / f"snap_qc_fy{args.year}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {path.relative_to(ROOT)}: {len(data['states'])} states")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
