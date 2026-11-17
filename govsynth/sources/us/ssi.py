"""SSI (Supplemental Security Income) data source connector.

Data sourced from data/thresholds/ssi_cy{year}.json: the federal benefit rates
from SSA's annual "Cost-of-Living Increase and Other Determinations" notice
(90 FR 49047 for 2026) and the statutory resource limits and income exclusions
in 20 CFR Part 416.

Federal SSI only: state supplementary payments, in-kind support and maintenance,
and deeming from an ineligible spouse or parent are not modeled.
"""

from __future__ import annotations

from dataclasses import dataclass

from govsynth.fiscal_year import FiscalYearConfig
from govsynth.sources.base import DataSource, HouseholdThreshold, ProgramThresholds

DEFAULT_SSI_CY = 2026

SSI_CATEGORIES: tuple[str, ...] = ("aged", "blind", "disabled")


@dataclass(frozen=True)
class SSIIncome:
    """Countable-income computation for one month (20 CFR 416.1112, 416.1124)."""

    unearned: float
    earned: float
    general_exclusion_on_unearned: float
    general_exclusion_on_earned: float
    earned_after_65: float
    countable_unearned: float
    countable_earned: float

    @property
    def countable(self) -> float:
        """Total countable income."""
        return self.countable_unearned + self.countable_earned


class SSISource(DataSource):
    """Federal SSI rules for one calendar year.

    Args:
        calendar_year: Calendar year of the federal benefit rate. Default 2026.
        state: Two-letter state code (recorded; federal rules are uniform).
    """

    def __init__(self, calendar_year: int = DEFAULT_SSI_CY, state: str = "national") -> None:
        super().__init__(year=calendar_year, state=state)
        self.fy_config = FiscalYearConfig.for_program("ssi", calendar_year)
        self._raw = self._load_threshold_json(self.fy_config.threshold_filename)

    @property
    def program(self) -> str:
        return "ssi"

    def fbr(self, couple: bool) -> float:
        """Monthly federal benefit rate for an individual or an eligible couple."""
        return float(self._raw["federal_benefit_rate_couple" if couple else "federal_benefit_rate_individual"])

    def resource_limit(self, couple: bool) -> float:
        """Countable resource limit (20 CFR 416.1205)."""
        return float(self._raw["resource_limit_couple" if couple else "resource_limit_individual"])

    @property
    def sga_nonblind(self) -> float:
        """Monthly substantial gainful activity amount for non-blind disabled applicants."""
        return float(self._raw["substantial_gainful_activity_nonblind"])

    def countable_income(self, unearned: float, earned: float) -> SSIIncome:
        """Apply the $20 general and $65 + 1/2 earned income exclusions.

        The $20 general exclusion comes off unearned income first; whatever is left
        of it comes off earned income (20 CFR 416.1124(c)(12), 416.1112(c)(4)). Then
        $65 of earned income and one-half of the remainder are excluded
        (416.1112(c)(5), (c)(7)).
        """
        general = float(self._raw["general_income_exclusion"])
        on_unearned = min(general, unearned)
        on_earned = min(general - on_unearned, earned)
        earned_after_general = earned - on_earned
        earned_after_65 = max(0.0, earned_after_general - float(self._raw["earned_income_exclusion"]))
        countable_earned = earned_after_65 * (1 - float(self._raw["earned_income_remainder_excluded_fraction"]))
        return SSIIncome(
            unearned=unearned,
            earned=earned,
            general_exclusion_on_unearned=on_unearned,
            general_exclusion_on_earned=on_earned,
            earned_after_65=earned_after_65,
            countable_unearned=unearned - on_unearned,
            countable_earned=round(countable_earned, 2),
        )

    def determine(
        self,
        category: str | None,
        unearned: float,
        earned: float,
        resources: float,
        couple: bool,
        blind: bool = False,
    ) -> tuple[bool, float, str]:
        """Return (eligible, monthly federal payment, reason).

        Args:
            category: 'aged', 'blind', 'disabled', or None if the applicant is none of these.
            unearned: Monthly unearned income (e.g. Social Security).
            earned: Monthly gross earnings.
            resources: Countable resources.
            couple: Eligible-couple determination (both members aged, blind or disabled).
            blind: Whether a disabled applicant is blind (SGA test does not apply).
        """
        if category not in SSI_CATEGORIES:
            return False, 0.0, "Ineligible: not aged (65+), blind, or disabled (20 CFR 416.202(a))"
        if category == "disabled" and not blind and earned > self.sga_nonblind:
            return (
                False,
                0.0,
                (
                    f"Ineligible: earnings ${earned:,.2f}/month exceed substantial gainful activity "
                    f"(${self.sga_nonblind:,.0f}), so the applicant is not disabled (20 CFR 416.920(b))"
                ),
            )
        res_cap = self.resource_limit(couple)
        if resources > res_cap:
            return False, 0.0, f"Ineligible: resources ${resources:,.2f} exceed the ${res_cap:,.0f} limit"
        income = self.countable_income(unearned, earned)
        fbr = self.fbr(couple)
        if income.countable >= fbr:
            return (
                False,
                0.0,
                (
                    f"Ineligible: countable income ${income.countable:,.2f} is not less than the "
                    f"${fbr:,.0f} federal benefit rate, so no payment is due"
                ),
            )
        payment = round(fbr - income.countable, 2)
        return (
            True,
            payment,
            f"Eligible: federal SSI payment ${payment:,.2f}/month (${fbr:,.0f} - ${income.countable:,.2f})",
        )

    def fetch_thresholds(self) -> ProgramThresholds:
        """FBR by household size (1 = individual, 2 = eligible couple)."""
        households = {
            size: HouseholdThreshold(
                household_size=size,
                gross_monthly=self.fbr(couple=size == 2),
                net_monthly=self.fbr(couple=size == 2),
                max_benefit=self.fbr(couple=size == 2),
            )
            for size in (1, 2)
        }
        return ProgramThresholds(
            program="ssi",
            fiscal_year=self.year,
            state=self.state,
            source=self._raw["_metadata"]["source"],
            source_url=self._raw["_metadata"]["source_url"],
            households=households,
            asset_limit_general=self.resource_limit(couple=False),
            extra={
                "resource_limit_couple": self.resource_limit(couple=True),
                "sga_nonblind": self.sga_nonblind,
                "verification_status": self._raw["_metadata"]["verification_status"],
            },
        )

    def fetch_policy_summary(self) -> str:
        """Plain-text summary of federal SSI rules."""
        return (
            f"SSI ({self.fy_config.period_label}, federal):\n"
            "- Must be aged (65+), blind, or disabled (20 CFR 416.202).\n"
            f"- Federal benefit rate: ${self.fbr(False):,.0f}/month individual, ${self.fbr(True):,.0f} couple.\n"
            "- Countable income: $20 general exclusion, then $65 + 1/2 of remaining earnings excluded.\n"
            "- Payment = FBR - countable income; no payment if countable income >= FBR.\n"
            f"- Resources: ${self.resource_limit(False):,.0f} individual / ${self.resource_limit(True):,.0f} couple.\n"
            f"- Disabled (non-blind) applicants earning over ${self.sga_nonblind:,.0f}/month (SGA) are not disabled."
        )
