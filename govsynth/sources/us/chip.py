"""CHIP and children's Medicaid data source connector.

Data sourced from data/thresholds/chip_cy{year}.json: the KFF / Georgetown CCF table of
Medicaid and CHIP income limits for children (as of January 2026), with the 2026 HHS
poverty guidelines. Limits are MAGI-converted and already include the 5-percentage-
point disregard, so they are compared directly with household MAGI as a percent of FPL.

Determination order for a child (age 0-18):

1. Household MAGI at or below the Medicaid limit for the child's age band -> Medicaid,
   whether or not the child has other coverage.
2. Above it, CHIP covers only uninsured children (42 CFR 457.310(b)(2)):
   a. within the band's CHIP-funded Medicaid range -> Medicaid paid with CHIP funds;
   b. at or below the state's separate CHIP limit -> separate CHIP.
3. Otherwise not eligible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from govsynth.fiscal_year import FiscalYearConfig
from govsynth.sources.base import THRESHOLD_DIR, DataSource, HouseholdThreshold, ProgramThresholds, _load_json_file

DEFAULT_CHIP_CY = 2026

AGE_BANDS: tuple[str, ...] = ("0-1", "1-5", "6-18")


def age_band(age: int) -> str | None:
    """KFF age band for a child's age in years, or None if 19 or older."""
    if age < 1:
        return "0-1"
    if age <= 5:
        return "1-5"
    if age <= 18:
        return "6-18"
    return None


@dataclass(frozen=True)
class ChildCoverage:
    """Result of a children's Medicaid/CHIP determination."""

    program: str | None  # 'medicaid', 'medicaid_chip_funded', 'separate_chip', or None
    pct_fpl: float
    reason: str

    @property
    def eligible(self) -> bool:
        """Whether the child qualifies for any of the three."""
        return self.program is not None


class CHIPSource(DataSource):
    """Children's Medicaid and CHIP income limits for one state.

    Args:
        calendar_year: Calendar year of the limits. Default 2026.
        state: Two-letter state code (any of the 50 states or DC).
    """

    def __init__(self, calendar_year: int = DEFAULT_CHIP_CY, state: str = "VA") -> None:
        super().__init__(year=calendar_year, state=state)
        self.fy_config = FiscalYearConfig.for_program("chip", calendar_year)
        self._raw = self._load_threshold_json(self.fy_config.threshold_filename)
        if self.state not in self._raw["states"]:
            raise ValueError(f"No CY{calendar_year} CHIP data for {self.state}")
        self._row: dict[str, Any] = self._raw["states"][self.state]
        fpl = _load_json_file(str(THRESHOLD_DIR / f"us_fpl_{self._raw['_metadata']['fpl_basis_year']}.json"))
        self._fpl: dict[str, Any] = fpl["regions"][{"AK": "alaska", "HI": "hawaii"}.get(self.state, "contiguous_48_dc")]

    @property
    def program(self) -> str:
        return "chip"

    @property
    def raw(self) -> dict[str, Any]:
        """The parsed chip_cy{year}.json."""
        return self._raw

    def annual_fpl(self, household_size: int) -> float:
        """Annual 2026 poverty guideline for the MAGI household size."""
        by_size = self._fpl["by_household_size"]
        if household_size <= 8:
            return float(by_size[str(household_size)]["annual"])
        return float(by_size["8"]["annual"]) + (household_size - 8) * float(self._fpl["per_additional_person_annual"])

    def pct_fpl(self, monthly_magi: float, household_size: int) -> float:
        """Household MAGI as a percent of the poverty guideline, to two decimals (for display)."""
        return round(monthly_magi * 12 / self.annual_fpl(household_size) * 100, 2)

    def medicaid_limit(self, band: str) -> int:
        """Medicaid-funded upper limit (% FPL) for an age band."""
        return int(self._row["age_bands"][band]["medicaid_funded_pct_fpl"])

    def chip_funded_range(self, band: str) -> tuple[int, int] | None:
        """CHIP-funded Medicaid income range (% FPL) for an age band, if any."""
        r = self._row["age_bands"][band]["chip_funded_medicaid_pct_fpl"]
        return (int(r["low"]), int(r["high"])) if r else None

    @property
    def separate_chip_limit(self) -> int | None:
        """Upper limit (% FPL) of the state's separate CHIP program, or None."""
        v = self._row["separate_chip_pct_fpl"]
        return int(v) if v is not None else None

    def chip_limit_above_medicaid(self, band: str) -> int | None:
        """Highest limit (% FPL) at which an uninsured child above the Medicaid limit is covered."""
        candidates = [self.medicaid_limit(band)]
        r = self.chip_funded_range(band)
        if r:
            candidates.append(r[1])
        if self.separate_chip_limit is not None:
            candidates.append(self.separate_chip_limit)
        top = max(candidates)
        return top if top > self.medicaid_limit(band) else None

    def monthly_limit(self, pct: float, household_size: int) -> float:
        """Monthly MAGI equal to `pct`% of the poverty guideline."""
        return round(self.annual_fpl(household_size) * pct / 100 / 12, 2)

    def within(self, monthly_magi: float, pct: float, household_size: int) -> bool:
        """Whether monthly MAGI is at or below `pct`% FPL, compared in dollars rounded to the cent."""
        return monthly_magi <= self.monthly_limit(pct, household_size)

    def determine(self, age: int, household_size: int, monthly_magi: float, insured: bool) -> ChildCoverage:
        """Determine a child's Medicaid/CHIP eligibility.

        Limits are converted to monthly dollars (rounded to the cent) and compared with
        monthly MAGI, so an income a few cents over a limit is never rounded into it.
        """
        pct = self.pct_fpl(monthly_magi, household_size)
        band = age_band(age)
        if band is None:
            return ChildCoverage(
                None, pct, f"Ineligible: at {age} the applicant is not a child (CHIP covers ages 0-18)"
            )
        med = self.medicaid_limit(band)
        med_dollars = self.monthly_limit(med, household_size)
        if self.within(monthly_magi, med, household_size):
            return ChildCoverage(
                "medicaid",
                pct,
                f"Eligible for Medicaid: ${monthly_magi:,.2f} <= ${med_dollars:,.2f} ({med}% FPL, ages {band})",
            )
        top = self.chip_limit_above_medicaid(band)
        if top is None:
            return ChildCoverage(None, pct, (
                f"Ineligible: ${monthly_magi:,.2f} exceeds the ${med_dollars:,.2f} ({med}% FPL) Medicaid limit and "
                f"{self.state} has no CHIP coverage above it for ages {band}"
            ))  # fmt: skip
        if insured:
            return ChildCoverage(None, pct, (
                f"Ineligible: ${monthly_magi:,.2f} exceeds the ${med_dollars:,.2f} ({med}% FPL) Medicaid limit, and "
                "CHIP covers only uninsured children (42 CFR 457.310(b)(2))"
            ))  # fmt: skip
        r = self.chip_funded_range(band)
        if r and self.within(monthly_magi, r[1], household_size):
            return ChildCoverage("medicaid_chip_funded", pct, (
                f"Eligible for Medicaid funded by CHIP: ${monthly_magi:,.2f} <= "
                f"${self.monthly_limit(r[1], household_size):,.2f} ({r[1]}% FPL) and the child is uninsured"
            ))  # fmt: skip
        sep = self.separate_chip_limit
        if sep is not None and self.within(monthly_magi, sep, household_size):
            return ChildCoverage("separate_chip", pct, (
                f"Eligible for separate CHIP: ${monthly_magi:,.2f} <= "
                f"${self.monthly_limit(sep, household_size):,.2f} ({sep}% FPL) and the child is uninsured"
            ))  # fmt: skip
        return ChildCoverage(None, pct, (
            f"Ineligible: ${monthly_magi:,.2f} exceeds ${self.monthly_limit(top, household_size):,.2f}, "
            f"{self.state}'s {top}% FPL upper limit"
        ))  # fmt: skip

    def fetch_thresholds(self) -> ProgramThresholds:
        """Monthly upper limits (any program, uninsured child aged 6-18) by household size 2-8."""
        top = self.chip_limit_above_medicaid("6-18") or self.medicaid_limit("6-18")
        households = {
            size: HouseholdThreshold(
                household_size=size,
                gross_monthly=self.monthly_limit(top, size),
                net_monthly=self.monthly_limit(top, size),
            )
            for size in range(2, 9)
        }
        return ProgramThresholds(
            program="chip",
            fiscal_year=self.year,
            state=self.state,
            source=self._raw["_metadata"]["source"],
            source_url=self._raw["_metadata"]["source_url"],
            households=households,
            extra={"upper_limit_pct_fpl": self._row["upper_limit_pct_fpl"], "chip_model": self._row["chip_model"]},
        )

    def fetch_policy_summary(self) -> str:
        """Plain-text summary of the state's children's Medicaid and CHIP limits."""
        lines = [f"Children's Medicaid and CHIP ({self.fy_config.period_label}, {self.state}; % of 2026 FPL, MAGI):"]
        for band in AGE_BANDS:
            r = self.chip_funded_range(band)
            extra = f"; CHIP-funded Medicaid {r[0]}%-{r[1]}%" if r else ""
            lines.append(f"- Ages {band}: Medicaid up to {self.medicaid_limit(band)}%{extra}.")
        sep = self.separate_chip_limit
        lines.append(f"- Separate CHIP: up to {sep}% (uninsured children)." if sep else "- No separate CHIP program.")
        return "\n".join(lines)
