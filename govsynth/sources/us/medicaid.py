"""Medicaid data source connector.

Data sourced from:
  - 42 CFR Part 435 (Medicaid eligibility)
  - data/thresholds/medicaid_cy{year}.json (bundled)
  - CMS / KFF state expansion status

CALENDAR NOTE:
  Medicaid uses MAGI (Modified Adjusted Gross Income) measured against HHS
  poverty guidelines published each January. Medicaid follows the CALENDAR
  YEAR, not the federal fiscal year. CY2026 uses the 2026 HHS poverty guidelines.

MAGI vs SNAP NET INCOME:
  Medicaid income is NOT the same calculation as SNAP net income.
  MAGI adds back certain deductions (e.g., student loan interest) and
  excludes others (e.g., SNAP standard deductions do NOT apply).
  For Medicaid, income = gross income minus a 5% FPL disregard.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from typing import Any

from govsynth._paths import THRESHOLD_DIR
from govsynth.fiscal_year import DEFAULT_MEDICAID_CY, FiscalYearConfig
from govsynth.sources.base import DataSource, HouseholdThreshold, ProgramThresholds

_DATA_DIR = THRESHOLD_DIR


@lru_cache(maxsize=16)
def _load_fpl_json_cached(path_str: str) -> dict[str, Any]:
    """Cached loader for FPL guidelines JSON.

    Private: returns the same dict object on every call. Use
    `_load_fpl_json` instead, which hands back a deep copy so callers
    can't corrupt the shared cache.
    """
    with open(path_str) as f:
        data: dict[str, Any] = json.load(f)
        return data


def _load_fpl_json(path_str: str) -> dict[str, Any]:
    """Load FPL guidelines JSON with a process-lifetime cache keyed by path.

    Returns a deep copy so callers can't mutate the shared cache.
    """
    return copy.deepcopy(_load_fpl_json_cached(path_str))


_CHILD_BANDS = (("0-1", 0, 0), ("1-5", 1, 5), ("6-18", 6, 18))
APPLICANT_TYPES = ("adult", "parent_caretaker", "pregnant", "child")


def child_age_band(age: int) -> str:
    """KFF/CMS age band for a child's Medicaid limit (0-1 means under age 1).

    Raises:
        ValueError: If the age is outside 0-18.
    """
    for band, lo, hi in _CHILD_BANDS:
        if lo <= age <= hi:
            return band
    raise ValueError(f"Children's Medicaid covers ages 0-18, got {age}")


class MedicaidSource(DataSource):
    """Medicaid MAGI eligibility limits for one state (data/thresholds/medicaid_cy{year}.json).

    Limits are percentages of the HHS poverty guideline for the MAGI household size
    (42 CFR 435.603), as published by KFF with the 5-point disregard already included,
    so household MAGI is compared to them directly. Alaska and Hawaii use their own
    guidelines.

    Args:
        calendar_year: Calendar year for income limits. Default CY2026.
        state: Two-letter state code.

    Usage:
        source = MedicaidSource(calendar_year=2026, state="VA")
        eligible, reason = source.is_eligible(household_size=1, monthly_magi=1500, applicant_type="adult")
    """

    def __init__(self, calendar_year: int = DEFAULT_MEDICAID_CY, state: str = "VA") -> None:
        super().__init__(year=calendar_year, state=state)
        self.fy_config = FiscalYearConfig.for_program("medicaid", calendar_year)
        self._raw: dict[str, Any] | None = None

    @property
    def program(self) -> str:
        return "medicaid"

    def _load_raw(self) -> dict[str, Any]:
        if self._raw is None:
            self._raw = self._load_threshold_json(self.fy_config.threshold_filename)
        return self._raw

    @property
    def row(self) -> dict[str, Any]:
        """This state's limits.

        Raises:
            ValueError: If the state has no row.
        """
        states: dict[str, Any] = self._load_raw()["states"]
        if self.state not in states:
            raise ValueError(f"No Medicaid limits for {self.state} in CY{self.year}")
        row: dict[str, Any] = states[self.state]
        return row

    def is_expansion_state(self) -> bool:
        """Return True if this state has adopted ACA Medicaid expansion."""
        return bool(self.row["aca_expansion"])

    def annual_fpl(self, household_size: int) -> float:
        """HHS poverty guideline (annual) for the household size, in this state's region."""
        fpl = _load_fpl_json(str(_DATA_DIR / f"us_fpl_{self.fy_config.fpl_year}.json"))
        region = {"AK": "alaska", "HI": "hawaii"}.get(self.state, "contiguous_48_dc")
        r = fpl["regions"][region]
        by_size = r["by_household_size"]
        if household_size <= 8:
            return float(by_size[str(household_size)]["annual"])
        return float(by_size["8"]["annual"]) + (household_size - 8) * float(r["per_additional_person_annual"])

    def monthly_limit(self, pct: float, household_size: int) -> float:
        """Monthly MAGI equal to `pct`% of the poverty guideline, to the cent."""
        return round(self.annual_fpl(household_size) * pct / 100 / 12, 2)

    def pct_fpl(self, monthly_magi: float, household_size: int) -> float:
        """Household MAGI as a percent of the poverty guideline (two decimals, for display)."""
        return round(monthly_magi * 12 / self.annual_fpl(household_size) * 100, 2)

    def limit_pct(self, applicant_type: str, child_age: int | None = None) -> int | None:
        """Income limit (% FPL) for an applicant type, or None when the state has no such coverage.

        Args:
            applicant_type: 'adult' (no dependent children), 'parent_caretaker', 'pregnant'
                (alias 'postpartum'), or 'child' (alias 'child_0_18'; needs `child_age`,
                default 6-18).
            child_age: The child's age, for 'child'.

        Raises:
            ValueError: On an unknown applicant type.
        """
        row = self.row
        if applicant_type == "adult":
            adults = row["other_adults_pct_fpl"]
            return int(adults) if adults else None
        if applicant_type == "parent_caretaker":
            return int(row["parents_caretakers_pct_fpl"]) or None
        if applicant_type in ("pregnant", "postpartum"):
            return int(row["pregnant_medicaid_pct_fpl"])
        if applicant_type in ("child", "child_0_18"):
            band = child_age_band(child_age if child_age is not None else 6)
            return int(row["children_medicaid_pct_fpl"][band])
        raise ValueError(f"Unknown applicant type {applicant_type!r}; expected one of {APPLICANT_TYPES}")

    def get_income_limit(
        self, applicant_type: str, household_size: int = 1, child_age: int | None = None
    ) -> float | None:
        """Monthly MAGI limit for an applicant type and household size, or None if no coverage."""
        pct = self.limit_pct(applicant_type, child_age)
        return None if pct is None else self.monthly_limit(pct, household_size)

    def fetch_thresholds(self) -> ProgramThresholds:
        """Adult limits by household size (other adults where covered, else parents/caretakers)."""
        raw = self._load_raw()
        pct = self.limit_pct("adult") or self.limit_pct("parent_caretaker") or 0
        households = {
            size: HouseholdThreshold(
                household_size=size,
                gross_monthly=self.monthly_limit(pct, size),
                net_monthly=self.monthly_limit(pct, size),  # MAGI has no SNAP-style net deductions
                max_benefit=None,
            )
            for size in range(1, 9)
        }
        return ProgramThresholds(
            program="medicaid",
            fiscal_year=self.year,
            state=self.state,
            source=raw["_metadata"]["source"],
            source_url=raw["_metadata"].get("source_url"),
            households=households,
            extra={
                "expansion_state": self.is_expansion_state(),
                "income_methodology": raw.get("income_methodology", "MAGI"),
                "adult_limit_pct_fpl": pct,
                "cfr_reference": raw["_metadata"]["cfr_reference"],
                "calendar_year": self.year,
                "fpl_year": self.fy_config.fpl_year,
            },
        )

    def fetch_policy_summary(self) -> str:
        row = self.row
        expansion = self.is_expansion_state()
        status = "expansion state (covers adults to 138% FPL)" if expansion else "non-expansion state"
        adults = row["other_adults_pct_fpl"]
        adult_line = (
            f"- Adults without dependent children: covered up to {adults}% FPL."
            if adults
            else "- Adults without dependent children: NO coverage (coverage gap below 100% FPL)."
        )
        return (
            f"Medicaid Eligibility Rules (CY{self.year}, {self.state} — {status}):\n"
            f"  [Based on {self.fy_config.fpl_year} HHS poverty guidelines]\n"
            "- Income methodology: MAGI (Modified Adjusted Gross Income) (42 CFR 435.603)\n"
            "- Income ≠ SNAP net income: MAGI has different rules, no SNAP deductions apply.\n"
            f"{adult_line}\n"
            f"- Parents/caretaker relatives: up to {row['parents_caretakers_pct_fpl']}% FPL.\n"
            f"- Pregnant women: up to {row['pregnant_medicaid_pct_fpl']}% FPL.\n"
            "- No asset test for MAGI-based Medicaid.\n"
            f"Source: {self._load_raw()['_metadata']['source']}"
        )

    def is_eligible(
        self,
        household_size: int,
        monthly_magi: float,
        applicant_type: str = "adult",
        child_age: int | None = None,
    ) -> tuple[bool, str]:
        """Determine MAGI Medicaid eligibility and return (is_eligible, reason).

        Args:
            household_size: MAGI household size (a pregnant woman's includes the expected child or children).
            monthly_magi: Monthly household MAGI.
            applicant_type: See `limit_pct`.
            child_age: The child's age, for 'child'.
        """
        pct = self.limit_pct(applicant_type, child_age)
        pct_fpl = self.pct_fpl(monthly_magi, household_size)
        if pct is None:
            if applicant_type == "adult" and pct_fpl < 100:
                return False, (
                    f"Ineligible: {self.state} has not expanded Medicaid and does not cover adults without "
                    f"dependent children. At {pct_fpl:.0f}% FPL this applicant is in the coverage gap: no Medicaid, "
                    "and below the 100% FPL floor for marketplace premium tax credits."
                )
            who = "adults without dependent children" if applicant_type == "adult" else "this group"
            return False, (
                f"Ineligible: {self.state} has not expanded Medicaid and does not cover {who} at any income "
                f"(MAGI is {pct_fpl:.0f}% FPL)."
            )
        limit = self.monthly_limit(pct, household_size)
        if monthly_magi <= limit:
            return True, (
                f"Eligible: MAGI ${monthly_magi:,.2f} ≤ ${limit:,.2f}, the {pct}% FPL limit for a household of "
                f"{household_size} (CY{self.year}, {self.state})"
            )
        return False, (
            f"Ineligible: MAGI ${monthly_magi:,.2f} exceeds ${limit:,.2f}, the {pct}% FPL limit for "
            f"{applicant_type.replace('_', ' ')} in a household of {household_size} (CY{self.year}, {self.state})"
        )
