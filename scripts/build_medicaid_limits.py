#!/usr/bin/env python3
"""Build data/thresholds/medicaid_cy2026.json from KFF's January 2026 eligibility tables.

Adults, parents, pregnant women and ACA expansion status are transcribed below from
the KFF State Health Facts tables (retrieved 2026-11-17 and posted to issue #24).
Children's limits are read from the already-verified chip_cy2026.json (KFF/Georgetown
children's table, January 2026), so the two files cannot disagree.

All percentages are MAGI-converted and already include the 5-percentage-point
disregard, as KFF publishes them; compare household MAGI to them directly.

Usage:
    python scripts/build_medicaid_limits.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

KFF_ADULTS_URL = (
    "https://www.kff.org/affordable-care-act/state-indicator/"
    "medicaid-income-eligibility-limits-for-adults-as-a-percent-of-the-federal-poverty-level/"
)
KFF_PREGNANT_URL = (
    "https://www.kff.org/affordable-care-act/state-indicator/"
    "medicaid-and-chip-income-eligibility-limits-for-pregnant-women-as-a-percent-of-the-federal-poverty-level/"
)
KFF_EXPANSION_URL = (
    "https://www.kff.org/health-reform/state-indicator/"
    "state-activity-around-expanding-medicaid-under-the-affordable-care-act/"
)

# KFF adults table, as of January 2026: (parents in a family of three, other adults), % FPL.
# Every state not listed is 138 / 138.
ADULTS_EXCEPTIONS: dict[str, tuple[int, int]] = {
    "AL": (18, 0), "FL": (26, 0), "GA": (100, 100), "KS": (38, 0), "MS": (21, 0),
    "SC": (67, 0), "TN": (105, 0), "TX": (15, 0), "WI": (100, 100), "WY": (43, 0),
}  # fmt: skip

# KFF pregnant-women table, as of January 2026: (Medicaid, CHIP, From-Conception-to-End-of-Pregnancy), % FPL.
PREGNANT: dict[str, tuple[int, int | None, int | None]] = {
    "AL": (146, None, 317), "AK": (230, None, None), "AZ": (161, None, None), "AR": (214, None, 214),
    "CA": (213, None, 322), "CO": (195, 260, 265), "CT": (263, None, 263), "DE": (217, None, None),
    "DC": (324, None, 324), "FL": (196, None, None), "GA": (225, None, None), "HI": (196, None, None),
    "ID": (138, None, None), "IL": (213, None, 213), "IN": (213, None, None), "IA": (220, None, None),
    "KS": (171, None, None), "KY": (195, 218, None), "LA": (138, None, 214), "ME": (214, None, 213),
    "MD": (264, None, 264), "MA": (205, None, 205), "MI": (200, None, 200), "MN": (283, None, 283),
    "MS": (199, None, None), "MO": (196, 305, 305), "MT": (162, None, None), "NE": (199, None, 202),
    "NV": (205, None, None), "NH": (201, None, None), "NJ": (194, 205, None), "NM": (255, None, None),
    "NY": (223, None, 223), "NC": (201, None, None), "ND": (175, None, None), "OH": (205, None, None),
    "OK": (210, None, 210), "OR": (190, None, 190), "PA": (220, None, None), "RI": (190, 258, 258),
    "SC": (199, None, None), "SD": (138, None, 138), "TN": (255, None, 255), "TX": (203, None, 207),
    "UT": (144, None, None), "VT": (213, None, None), "VA": (143, 205, 205), "WA": (215, None, 215),
    "WV": (185, 305, None), "WI": (306, None, 306), "WY": (159, None, None),
}  # fmt: skip

# KFF expansion-status table (as of November 2026): implementation date of adopting states.
EXPANSION_IMPLEMENTED: dict[str, str] = {
    "AK": "2015-09-01", "AZ": "2014-01-01", "AR": "2014-01-01", "CA": "2014-01-01", "CO": "2014-01-01",
    "CT": "2014-01-01", "DE": "2014-01-01", "DC": "2014-01-01", "HI": "2014-01-01", "ID": "2020-01-01",
    "IL": "2014-01-01", "IN": "2015-02-01", "IA": "2014-01-01", "KY": "2014-01-01", "LA": "2016-07-01",
    "ME": "2019-01-10", "MD": "2014-01-01", "MA": "2014-01-01", "MI": "2014-04-01", "MN": "2014-01-01",
    "MO": "2021-10-01", "MT": "2016-01-01", "NE": "2020-10-01", "NV": "2014-01-01", "NH": "2014-08-15",
    "NJ": "2014-01-01", "NM": "2014-01-01", "NY": "2014-01-01", "NC": "2023-12-01", "ND": "2014-01-01",
    "OH": "2014-01-01", "OK": "2021-07-01", "OR": "2014-01-01", "PA": "2015-01-01", "RI": "2014-01-01",
    "SD": "2023-07-01", "UT": "2020-01-01", "VT": "2014-01-01", "VA": "2019-01-01", "WA": "2014-01-01",
    "WV": "2014-01-01",
}  # fmt: skip
NOT_ADOPTED = {"AL", "FL", "GA", "KS", "MS", "SC", "TN", "TX", "WI", "WY"}

# Notes that change how a limit applies, kept with the state's row.
STATE_NOTES = {
    "GA": "Other adults to 100% FPL through Georgia Pathways to Coverage (a section 1115 demonstration with a "
    "qualifying-activities requirement), not ACA expansion.",
    "WI": "Adults to 100% FPL through a section 1115 demonstration (BadgerCare), not ACA expansion.",
    "DC": "Effective January 1, 2026, parents and other adults were reduced from 221%/215% to 138%; the Healthy "
    "DC Plan (Basic Health Program) covers 138-200% FPL.",
}


def children_limits(chip: dict[str, Any], state: str) -> dict[str, int]:
    """Children's Medicaid limit per age band: Medicaid-funded or CHIP-funded Medicaid, whichever is higher."""
    out = {}
    for band, row in chip["states"][state]["age_bands"].items():
        limits = [row["medicaid_funded_pct_fpl"]]
        if row["chip_funded_medicaid_pct_fpl"]:
            limits.append(row["chip_funded_medicaid_pct_fpl"]["high"])
        out[band] = int(max(limits))
    return out


def build() -> dict[str, Any]:
    """Assemble the per-state table and check it against KFF's stated totals."""
    chip = json.loads((ROOT / "data/thresholds/chip_cy2026.json").read_text())
    states = sorted(chip["states"])
    assert len(states) == 51 and set(PREGNANT) == set(states), "pregnant table must cover 50 states + DC"
    assert set(EXPANSION_IMPLEMENTED) | NOT_ADOPTED == set(states) and not set(EXPANSION_IMPLEMENTED) & NOT_ADOPTED
    # KFF: "41 states (including DC) have adopted the Medicaid expansion and 10 states have not".
    assert len(EXPANSION_IMPLEMENTED) == 41 and len(NOT_ADOPTED) == 10
    # KFF: "seven states use CHIP funding to cover pregnant individuals and 25 states ... FCEP".
    assert sum(v[1] is not None for v in PREGNANT.values()) == 7
    assert sum(v[2] is not None for v in PREGNANT.values()) == 25
    out: dict[str, Any] = {}
    for st in states:
        parents, adults = ADULTS_EXCEPTIONS.get(st, (138, 138))
        expansion = st in EXPANSION_IMPLEMENTED
        assert not expansion or (parents, adults) == (138, 138), f"{st}: expansion state below 138%"
        med, chip_preg, fcep = PREGNANT[st]
        out[st] = {
            "aca_expansion": expansion,
            "expansion_implemented": EXPANSION_IMPLEMENTED.get(st),
            "parents_caretakers_pct_fpl": parents,
            "other_adults_pct_fpl": adults or None,
            "pregnant_medicaid_pct_fpl": med,
            "pregnant_chip_pct_fpl": chip_preg,
            "pregnant_fcep_pct_fpl": fcep,
            "children_medicaid_pct_fpl": children_limits(chip, st),
            **({"note": STATE_NOTES[st]} if st in STATE_NOTES else {}),
        }
    return {
        "_metadata": {
            "program": "medicaid",
            "period": "CY2026",
            "calendar_year": 2026,
            "fpl_basis_year": 2026,
            "source": "KFF State Health Facts (national survey by KFF and the Georgetown University Center for "
            "Children and Families): Medicaid income eligibility limits for adults, for pregnant women, and for "
            "children (via chip_cy2026.json), as of January 2026; expansion status as of November 2026",
            "source_url": KFF_ADULTS_URL,
            "source_urls": {
                "adults": KFF_ADULTS_URL,
                "pregnant": KFF_PREGNANT_URL,
                "expansion_status": KFF_EXPANSION_URL,
                "children": "data/thresholds/chip_cy2026.json",
            },
            "retrieved": "2026-11-17",
            "cfr_reference": "42 CFR Part 435",
            "verification_status": "verified",
            "verification_note": "Transcribed from the KFF tables posted to issue #24; checked against KFF's "
            "stated counts (41 expansion / 10 not; 7 CHIP and 25 FCEP pregnancy states) and against Medicaid.gov "
            "(Dec 2023) for expansion status. Built by scripts/build_medicaid_limits.py.",
            "units": "percent of the HHS poverty guideline for the MAGI household size; includes the 5-point "
            "disregard. other_adults_pct_fpl null = no coverage for adults without dependent children.",
        },
        "income_methodology": "MAGI",
        "states": out,
    }


def main() -> int:
    """Write the file."""
    data = build()
    path = ROOT / "data/thresholds/medicaid_cy2026.json"
    path.write_text(json.dumps(data, indent=2) + "\n")
    exp = sum(s["aca_expansion"] for s in data["states"].values())
    print(f"wrote {path.relative_to(ROOT)}: {len(data['states'])} jurisdictions, {exp} expansion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
