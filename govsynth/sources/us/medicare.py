"""Medicare low-income help: Medicare Savings Programs (QMB/SLMB/QI) and Extra Help (Part D LIS).

Data sourced from data/thresholds/medicare_cy{year}.json (Medicare.gov 2026 limits;
SSA POMS HI 03001.020) and the HHS poverty guidelines for the same calendar year.

Income limits are derived, not stored: the countable-income limit for a tier is
``ceil(annual FPL x pct / 100 / 12)``, and the gross limit Medicare.gov publishes is
that plus the $20 general income disregard. Deriving them keeps Alaska and Hawaii
(which have their own poverty guidelines) correct; the published 48-state figures
are kept in the data file and pinned in tests.

Federal floor only: states administer MSPs and may disregard more income or drop the
resource test. Those state expansions are not modeled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from govsynth.fiscal_year import FiscalYearConfig
from govsynth.sources.base import THRESHOLD_DIR, DataSource, HouseholdThreshold, ProgramThresholds, _load_json_file

DEFAULT_MEDICARE_CY = 2026

MSP_TIERS: tuple[str, ...] = ("qmb", "slmb", "qi")

_FPL_REGION = {"AK": "alaska", "HI": "hawaii"}


@dataclass(frozen=True)
class MSPTier:
    """One Medicare Savings Program tier."""

    tier: str
    name: str
    max_pct_fpl: int
    pays: str


class MedicareSource(DataSource):
    """Federal Medicare Savings Program and Extra Help rules for one calendar year.

    Args:
        calendar_year: Calendar year of the limits. Default 2026.
        state: Two-letter state code; only AK and HI change the limits (their own
            poverty guidelines). 'national' uses the 48-state guidelines.
    """

    def __init__(self, calendar_year: int = DEFAULT_MEDICARE_CY, state: str = "national") -> None:
        super().__init__(year=calendar_year, state=state)
        self.fy_config = FiscalYearConfig.for_program("medicare", calendar_year)
        self._raw = self._load_threshold_json(self.fy_config.threshold_filename)
        fpl = _load_json_file(str(THRESHOLD_DIR / f"us_fpl_{self._raw['_metadata']['fpl_basis_year']}.json"))
        self._fpl_region = fpl["regions"][_FPL_REGION.get(self.state, "contiguous_48_dc")]

    @property
    def program(self) -> str:
        return "medicare"

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    @property
    def raw(self) -> dict[str, Any]:
        """The parsed medicare_cy{year}.json."""
        return self._raw

    @property
    def income_disregard(self) -> float:
        """Monthly general income disregard applied before the MSP income test ($20)."""
        return float(self._raw["msp"]["general_income_disregard_monthly"])

    def tiers(self) -> list[MSPTier]:
        """MSP tiers from most to least generous (QMB, SLMB, QI)."""
        return [MSPTier(t["tier"], t["name"], int(t["max_pct_fpl"]), t["pays"]) for t in self._raw["msp"]["tiers"]]

    def annual_fpl(self, household_size: int) -> float:
        """Annual poverty guideline for the household size."""
        by_size = self._fpl_region["by_household_size"]
        if household_size <= 8:
            return float(by_size[str(household_size)]["annual"])
        return float(by_size["8"]["annual"]) + (household_size - 8) * float(
            self._fpl_region["per_additional_person_annual"]
        )

    def msp_countable_limit(self, tier: str, couple: bool) -> float:
        """Monthly limit on COUNTABLE income (after the $20 disregard) for an MSP tier."""
        pct = next(t.max_pct_fpl for t in self.tiers() if t.tier == tier)
        return float(math.ceil(self.annual_fpl(2 if couple else 1) * pct / 100 / 12))

    def msp_gross_limit(self, tier: str, couple: bool) -> float:
        """Monthly gross-income limit as Medicare.gov publishes it (countable limit + $20)."""
        return self.msp_countable_limit(tier, couple) + self.income_disregard

    def msp_resource_limit(self, couple: bool) -> float:
        """MSP resource limit (QMB, SLMB and QI share one limit)."""
        key = "resource_limit_couple" if couple else "resource_limit_individual"
        return float(self._raw["msp"][key])

    def extra_help_annual_limit(self, household_size: int) -> float:
        """Annual countable-income limit for Extra Help (150% FPL)."""
        return self.annual_fpl(household_size) * float(self._raw["extra_help"]["max_pct_fpl"]) / 100

    def extra_help_resource_limit(self, couple: bool) -> float:
        """Extra Help resource limit (includes the burial-funds allowance)."""
        key = "resource_limit_couple" if couple else "resource_limit_individual"
        return float(self._raw["extra_help"][key])

    # ------------------------------------------------------------------
    # Determinations
    # ------------------------------------------------------------------

    def msp_tier(self, monthly_unearned_income: float, resources: float, couple: bool) -> tuple[str | None, str]:
        """Return (tier or None, reason) for a Medicare beneficiary's MSP eligibility."""
        countable = max(0.0, monthly_unearned_income - self.income_disregard)
        limit = self.msp_resource_limit(couple)
        if resources > limit:
            return None, f"Ineligible: resources ${resources:,.2f} exceed the ${limit:,.0f} MSP resource limit"
        for tier in self.tiers():
            cap = self.msp_countable_limit(tier.tier, couple)
            if countable <= cap:
                return tier.tier, (
                    f"Eligible for {tier.tier.upper()} ({tier.name}): countable income ${countable:,.2f} "
                    f"<= ${cap:,.0f} ({tier.max_pct_fpl}% FPL); pays {tier.pays}"
                )
        top = self.tiers()[-1]
        cap = self.msp_countable_limit(top.tier, couple)
        return None, (
            f"Ineligible: countable income ${countable:,.2f} exceeds ${cap:,.0f} ({top.max_pct_fpl}% FPL), "
            "the highest MSP tier (QI)"
        )

    def extra_help_eligible(
        self, monthly_unearned_income: float, resources: float, couple: bool, household_size: int
    ) -> tuple[bool, str]:
        """Return (eligible, reason) for Extra Help (Part D low-income subsidy)."""
        annual = max(0.0, monthly_unearned_income - self.income_disregard) * 12
        income_cap = self.extra_help_annual_limit(household_size)
        if annual > income_cap:
            return False, f"Ineligible: annual countable income ${annual:,.2f} exceeds ${income_cap:,.2f} (150% FPL)"
        res_cap = self.extra_help_resource_limit(couple)
        if resources > res_cap:
            return False, f"Ineligible: resources ${resources:,.2f} exceed the ${res_cap:,.0f} Extra Help limit"
        return True, (
            f"Eligible for Extra Help: annual countable income ${annual:,.2f} <= ${income_cap:,.2f} (150% FPL) "
            f"and resources ${resources:,.2f} <= ${res_cap:,.0f}"
        )

    # ------------------------------------------------------------------
    # DataSource interface
    # ------------------------------------------------------------------

    def fetch_thresholds(self) -> ProgramThresholds:
        """QMB gross limits by household size (1 = individual, 2 = couple)."""
        households = {
            size: HouseholdThreshold(
                household_size=size,
                gross_monthly=self.msp_gross_limit("qmb", couple=size == 2),
                net_monthly=self.msp_countable_limit("qmb", couple=size == 2),
            )
            for size in (1, 2)
        }
        return ProgramThresholds(
            program="medicare",
            fiscal_year=self.year,
            state=self.state,
            source=self._raw["_metadata"]["source"],
            source_url=self._raw["_metadata"]["source_url"],
            households=households,
            asset_limit_general=self.msp_resource_limit(couple=False),
            extra={
                "msp_resource_limit_couple": self.msp_resource_limit(couple=True),
                "extra_help_resource_limit_individual": self.extra_help_resource_limit(couple=False),
                "extra_help_resource_limit_couple": self.extra_help_resource_limit(couple=True),
                "verification_status": self._raw["_metadata"]["verification_status"],
            },
        )

    def fetch_policy_summary(self) -> str:
        """Plain-text summary of the MSP tiers and Extra Help limits."""
        lines = [f"Medicare Savings Programs and Extra Help ({self.fy_config.period_label}, {self.state}):"]
        for tier in self.tiers():
            lines.append(
                f"- {tier.tier.upper()} ({tier.name}): income <= {tier.max_pct_fpl}% FPL "
                f"(${self.msp_gross_limit(tier.tier, False):,.0f}/mo individual, "
                f"${self.msp_gross_limit(tier.tier, True):,.0f}/mo couple, incl. $20 disregard); pays {tier.pays}."
            )
        lines.append(
            f"- MSP resources: ${self.msp_resource_limit(False):,.0f} individual / "
            f"${self.msp_resource_limit(True):,.0f} couple."
        )
        lines.append(
            f"- Extra Help: income <= 150% FPL; resources <= ${self.extra_help_resource_limit(False):,.0f} / "
            f"${self.extra_help_resource_limit(True):,.0f} (42 CFR 423.773)."
        )
        return "\n".join(lines)
