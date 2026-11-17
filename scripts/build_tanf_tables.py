#!/usr/bin/env python3
"""Write data/thresholds/tanf_{va,md,tx,ca}_2026.json from the state primary sources (#17).

Every amount below was transcribed from the documents retrieved 2026-11-17 and posted to
issue #17 (VDSS TANF Manual Ch. 300; 22VAC40-295-50; COMAR 07.03.03 with MD DHS IM 26-13;
Texas Works Handbook A-1341, A-1425 and C-111 Rev. 26-4; CDSS ACL 26-39 and ACL 26-66).
Each file carries the effective date of each parameter, because the four states update on
different cycles.

Usage:
    python scripts/build_tanf_tables.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RETRIEVED = "2026-11-17"


def meta(state: str, source: str, url: str, rules: str, **extra: str) -> dict[str, Any]:
    """Common _metadata block."""
    return {
        "program": "tanf",
        "state": state,
        "period": "2026",
        "source": source,
        "source_url": url,
        "rules_reference": rules,
        "retrieved": RETRIEVED,
        "verification_status": "verified",
        "verification_note": "Transcribed from the state primary sources posted to issue #17; see each section's "
        "effective date. Built by scripts/build_tanf_tables.py.",
        **extra,
    }


VA = {
    "_metadata": meta(
        "VA",
        "Virginia DSS TANF Manual Chapter 300 (Need and Amount of Assistance), Appendices 1 and 2 to Section 304 "
        "and Appendix 1 to Section 305; 22VAC40-295-50",
        "https://www.dss.virginia.gov/media/vdss/benefit-programs/documents/tanfview/tanf/"
        "Chapter-300---Need-and-Amount-of-Assistance.pdf",
        "22VAC40-295-50; VDSS TANF Manual sections 304-305",
        disregard_note="22VAC40-295-50.C disregards 'an amount equal to the Food Stamp standard deduction' and then "
        "20% of the remainder of earned income. The manual's examples list $198/$208/$244/$279 (the FY2024 SNAP "
        "amounts); the current FY2026 SNAP standard deduction is used, per the regulation.",
    ),
    "standard_of_assistance": {
        "effective": "2022-07",
        "group_ii": {"1": 262, "2": 385, "3": 482, "4": 577, "5": 681, "6": 761},
        "group_iii": {"1": 366, "2": 489, "3": 587, "4": 681, "5": 811, "6": 887},
    },
    "maximum_income": {
        "effective": "2022-07",
        "group_ii": {"1": 524, "2": 767, "3": 966, "4": 1152, "5": 1361, "6": 1522},
        "group_iii": {"1": 730, "2": 974, "3": 1175, "4": 1361, "5": 1622, "6": 1773},
    },
    "maximum_reimbursable_payment": {"effective": "2022-07", "group_ii": 723, "group_iii": 861},
    "earned_disregard": {"standard_deduction": "snap_fy2026 48-state standard deduction", "pct_of_remainder": 20},
    "asset_limit": None,
    "locality_groups": {
        "effective": "2020-07",
        "group_ii_counties": [
            "Accomack", "Alleghany", "Amelia", "Amherst", "Appomattox", "Bath", "Bedford", "Bland", "Botetourt",
            "Brunswick", "Buchanan", "Buckingham", "Campbell", "Carroll", "Charles City", "Charlotte", "Chesterfield",
            "Clarke", "Craig", "Culpeper", "Cumberland", "Dickenson", "Dinwiddie", "Essex", "Floyd", "Fluvanna",
            "Franklin", "Frederick", "Giles", "Gloucester", "Goochland", "Grayson", "Greene", "Greensville", "Halifax",
            "Hanover", "Henrico", "Henry", "Highland", "Isle of Wight", "King and Queen", "Lancaster", "Lee",
            "Loudoun", "Louisa", "Lunenburg", "Madison", "Mathews", "Mecklenburg", "Middlesex", "Nelson", "New Kent",
            "Northampton", "Northumberland", "Nottoway", "Orange", "Page", "Patrick", "Pittsylvania", "Powhatan",
            "Prince Edward", "Prince George", "Pulaski", "Rappahannock", "Richmond", "Roanoke", "Rockbridge",
            "Rockingham", "Russell", "Scott", "Shenandoah", "Smyth", "Southampton", "Surry", "Sussex", "Tazewell",
            "Warren", "Washington", "Westmoreland", "Wise", "Wythe",
        ],
        "group_ii_cities": [
            "Bristol", "Buena Vista", "Chesapeake", "Clifton Forge", "Covington", "Danville", "Emporia", "Franklin",
            "Galax", "Harrisonburg", "Hopewell", "Lexington", "Lynchburg", "Martinsville", "Norfolk", "Norton",
            "Petersburg", "Portsmouth", "Radford", "Richmond", "Roanoke", "Salem", "Suffolk", "Virginia Beach",
            "Williamsburg", "Winchester",
        ],
        "group_iii_counties": [
            "Albemarle", "Arlington", "Augusta", "Caroline", "Fairfax", "Fauquier", "James City", "King George",
            "Montgomery", "Prince William", "Spotsylvania", "Stafford", "York",
        ],
        "group_iii_cities": [
            "Alexandria", "Charlottesville", "Colonial Heights", "Fairfax", "Falls Church", "Fredericksburg",
            "Hampton", "Manassas", "Manassas Park", "Newport News", "Poquoson", "Staunton", "Waynesboro",
        ],
    },
}  # fmt: skip

MD = {
    "_metadata": meta(
        "MD",
        "COMAR 07.03.03 (Temporary Cash Assistance) Regs. .11-.13; Maryland DHS FIA Information Memo 26-13 (FIP "
        "schedule effective January 1, 2026)",
        "https://regs.maryland.gov/us/md/exec/comar/07.03.03.01",
        "COMAR 07.03.03.11, .13E",
        schedule_url="https://dhs.maryland.gov/documents/FIA/Action%20Transmittals-AT%20-%20Information%20Memo-IM/"
        "AT-IM2026/26-13-IM-2026-TCA-TDAP-Benefit-Increase.pdf",
    ),
    "allowable_payment": {
        "effective": "2026-01-01",
        "by_size": {"1": 348, "2": 612, "3": 773, "4": 926, "5": 1074, "6": 1180},
    },
    "earned_disregard_pct_application": 20,
    "earned_disregard_pct_ongoing": 40,
    "self_employment_disregard_pct": 50,
    "minimum_benefit": 10,
    "asset_limit": None,
}

TX = {
    "_metadata": meta(
        "TX",
        "Texas Works Handbook A-1341 (Rev. 21-3), A-1425 (Rev. 15-4), C-111 Budgetary Allowances (Rev. 26-4)",
        "https://fhb.hhs.texas.gov/handbooks/texas-works-handbook/c-110-tanf",
        "Texas Works Handbook A-1341, A-1425.1-.3, A-1238; C-111",
        tests_url="https://fhb.hhs.texas.gov/handbooks/texas-works-handbook/a-1340-income-limits",
        deductions_url="https://fhb.hhs.texas.gov/handbooks/texas-works-handbook/a-1420-types-deductions",
    ),
    "budgetary_allowances": {
        "effective": "2026-10-01",
        "one_parent": {
            "budgetary_needs": {"2": 650, "3": 751, "4": 903, "5": 1003, "6": 1153},
            "recognizable_needs": {"2": 163, "3": 188, "4": 226, "5": 251, "6": 288},
            "max_grant": {"2": 336, "3": 388, "4": 466, "5": 517, "6": 595},
        },
        "two_parent": {
            "budgetary_needs": {"3": 824, "4": 925, "5": 1073, "6": 1176},
            "recognizable_needs": {"3": 206, "4": 231, "5": 268, "6": 294},
            "max_grant": {"3": 425, "4": 477, "5": 553, "6": 606},
        },
    },
    "work_related_expense": 120,
    "applicant_one_third_disregard": True,
    "earned_income_deduction_pct": 90,
    "earned_income_deduction_cap": 1400,
    "budgetary_needs_min_unmet": 0.50,
    "recognizable_needs_min_unmet": 0.01,
    "asset_limit": 1000,
}

CA = {
    "_metadata": meta(
        "CA",
        "CDSS All-County Letters 26-39 (MBSAC, effective July 1, 2026) and 26-66 (MAP, effective October 1, 2026, "
        "AB 152)",
        "https://www.cdss.ca.gov/Portals/9/Additional-Resources/Letters-and-Notices/ACLs/2026/26-66.pdf",
        "Welfare and Institutions Code 11450-11453; ACL 26-39; ACL 26-66",
        mbsac_url="https://www.cdss.ca.gov/Portals/9/Additional-Resources/Letters-and-Notices/ACLs/2026/26-39.pdf",
    ),
    "mbsac": {
        "effective": "2026-07-01",
        "region_1": {"1": 963, "2": 1581, "3": 1960, "4": 2325, "5": 2653, "6": 2983},
        "region_2": {"1": 914, "2": 1501, "3": 1859, "4": 2211, "5": 2529, "6": 2839},
    },
    "map_non_exempt": {
        "effective": "2026-10-01",
        "region_1": {"1": 747, "2": 947, "3": 1196, "4": 1441, "5": 1689, "6": 1936},
        "region_2": {"1": 708, "2": 900, "3": 1135, "4": 1370, "5": 1606, "6": 1841},
    },
    "map_exempt": {
        "effective": "2026-10-01",
        "region_1": {"1": 824, "2": 1058, "3": 1338, "4": 1607, "5": 1883, "6": 2161},
        "region_2": {"1": 784, "2": 1005, "3": 1270, "4": 1525, "5": 1790, "6": 2054},
    },
    "applicant_earned_deduction_per_employed_adult": 450,
    "benefit_earned_disregard_first": 600,
    "benefit_earned_disregard_pct_of_remainder": 50,
    "region_1_counties": [
        "Alameda", "Contra Costa", "Los Angeles", "Marin", "Monterey", "Napa", "Orange", "San Diego",
        "San Francisco", "San Luis Obispo", "San Mateo", "Santa Barbara", "Santa Clara", "Santa Cruz", "Solano",
        "Sonoma", "Ventura",
    ],
    "asset_limit": None,
    "asset_note": "CalWORKs has a property limit; sources disagree on the current amount, so it is not modeled.",
}  # fmt: skip


def check() -> None:
    """Internal consistency against relations the sources state."""
    for g in ("group_ii", "group_iii"):  # VA max income is ~200% of the standard of assistance
        for n, soa in VA["standard_of_assistance"][g].items():  # type: ignore[index]
            assert abs(VA["maximum_income"][g][n] / soa - 2) < 0.02, (g, n)  # type: ignore[index]
    assert len(CA["region_1_counties"]) == 17  # ACL 26-66: 17 Region 1 counties  # type: ignore[arg-type]
    tx = TX["budgetary_allowances"]["one_parent"]  # type: ignore[index]
    for n, bn in tx["budgetary_needs"].items():  # Recognizable Needs is 25% of Budgetary Needs
        assert abs(tx["recognizable_needs"][n] - bn * 0.25) <= 1, n
    # NCCP's MD fam-3 maximum earned income $941.25 = $753 / 0.8 (pre-2026 schedule) -- the formula holds.
    assert round(753 / (1 - MD["earned_disregard_pct_application"] / 100), 2) == 941.25  # type: ignore[operator]


def main() -> int:
    """Write the four files."""
    check()
    for st, data in (("va", VA), ("md", MD), ("tx", TX), ("ca", CA)):
        path = ROOT / "data" / "thresholds" / f"tanf_{st}_2026.json"
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
