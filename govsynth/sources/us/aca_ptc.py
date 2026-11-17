"""ACA premium tax credit (26 U.S.C. 36B) data source, tax year 2026.

Data: data/thresholds/aca_ptc_ty2026.json -- the Rev. Proc. 2025-25 applicable
percentage table and 9.96% required contribution percentage, with the Public Law
119-21 changes that apply to 2026 (sections 71302, 71304, 71305). The ARPA/IRA
enhanced credits expired after 2025, so the original structure applies: household
income of 100-400% of the poverty line (the 2025 guidelines, 26 CFR 1.36B-1(h)).

Rules, in the order `determine` applies them:
  1. Married taxpayers must file jointly, unless the domestic-abuse/abandonment
     exception applies (26 CFR 1.36B-2(b)(2)).
  2. Household income is at least 100% and not more than 400% of the poverty line
     (36B(c)(1)(A)). Since PL 119-21 section 71302 there is no under-100% route for
     lawfully present noncitizens.
  3. Not eligible for Medicaid (minimum essential coverage, 36B(c)(2)(B)).
  4. No affordable employer coverage: the self-only contribution is unaffordable if
     it exceeds 9.96% of household income (1.36B-2(c)(3)(v)).
  5. The plan was not enrolled in through an income-based special enrollment period
     (PL 119-21 section 71304).
  6. Credit = lesser of the enrolled premium and (benchmark premium - household income
     x applicable percentage / 12) (1.36B-3(d)); none if that is $0.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from govsynth.sources.base import THRESHOLD_DIR, DataSource, HouseholdThreshold, ProgramThresholds, _load_json_file

DEFAULT_PTC_TY = 2026


@dataclass(frozen=True)
class PTCApplicant:
    """The facts a premium tax credit determination needs."""

    household_size: int
    annual_household_income: float
    married: bool = False
    files_jointly: bool = True
    abuse_or_abandonment_exception: bool = False
    medicaid_eligible: bool = False
    employer_offer_self_only_monthly: float | None = None  # None = no employer offer
    enrolled_via_income_sep: bool = False
    benchmark_monthly_premium: float = 0.0
    enrolled_monthly_premium: float = 0.0


@dataclass(frozen=True)
class PTCResult:
    """Outcome of a premium tax credit determination."""

    eligible: bool
    reason: str
    failed_rule: str | None
    pct_fpl: float
    applicable_pct: float | None = None
    monthly_contribution: float | None = None
    monthly_credit: float | None = None


class ACAPremiumTaxCreditSource(DataSource):
    """Premium tax credit rules for one tax year and state (the state only sets AK/HI poverty guidelines).

    Args:
        tax_year: Tax/coverage year. Only 2026 is bundled.
        state: Two-letter state code.
    """

    def __init__(self, tax_year: int = DEFAULT_PTC_TY, state: str = "VA") -> None:
        super().__init__(year=tax_year, state=state)
        path = THRESHOLD_DIR / f"aca_ptc_ty{tax_year}.json"
        if not path.exists():
            raise ValueError(f"No premium tax credit rules bundled for tax year {tax_year}")
        self.raw: dict[str, Any] = _load_json_file(str(path))
        fpl = _load_json_file(str(THRESHOLD_DIR / f"us_fpl_{self.fpl_year}.json"))
        self._fpl: dict[str, Any] = fpl["regions"][{"AK": "alaska", "HI": "hawaii"}.get(self.state, "contiguous_48_dc")]

    @property
    def program(self) -> str:
        return "aca_ptc"

    @property
    def fpl_year(self) -> int:
        """Poverty guideline year used for this tax year (in effect at the start of open enrollment)."""
        return int(self.raw["_metadata"]["fpl_basis_year"])

    @property
    def required_contribution_pct(self) -> float:
        """Employer-coverage affordability threshold, percent of household income."""
        return float(self.raw["required_contribution_pct"])

    def annual_fpl(self, household_size: int) -> float:
        """Poverty guideline (annual) for the tax family size."""
        by_size = self._fpl["by_household_size"]
        if household_size <= 8:
            return float(by_size[str(household_size)]["annual"])
        return float(by_size["8"]["annual"]) + (household_size - 8) * float(self._fpl["per_additional_person_annual"])

    def pct_fpl(self, annual_income: float, household_size: int) -> float:
        """Household income as a percent of the poverty line (unrounded)."""
        return annual_income / self.annual_fpl(household_size) * 100

    def applicable_pct(self, pct_fpl: float) -> float:
        """Applicable percentage: linear within the band, rounded to 0.01% (26 CFR 1.36B-3(g)(1))."""
        rows = self.raw["applicable_percentage_table"]
        for i, row in enumerate(rows):
            last = i == len(rows) - 1
            if pct_fpl < row["to_pct_fpl"] or (last and pct_fpl <= row["to_pct_fpl"]):
                # Decimal throughout, so a value exactly halfway (e.g. 8.775) rounds up as the regulation's
                # own example does, rather than to whatever binary float lands nearest.
                lo, hi = Decimal(str(row["from_pct_fpl"])), Decimal(str(row["to_pct_fpl"]))
                start, end = Decimal(str(row["initial_pct"])), Decimal(str(row["final_pct"]))
                frac = max(Decimal(0), (Decimal(str(pct_fpl)) - lo) / (hi - lo)) if hi > lo else Decimal(0)
                return float((start + (end - start) * frac).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        raise ValueError(f"No applicable percentage above {rows[-1]['to_pct_fpl']}% FPL")

    def determine(self, a: PTCApplicant) -> PTCResult:
        """Apply the eligibility rules in order and compute the monthly credit."""
        pct = self.pct_fpl(a.annual_household_income, a.household_size)
        if a.married and not a.files_jointly and not a.abuse_or_abandonment_exception:
            return PTCResult(False, "married taxpayers must file a joint return", "joint_filing", pct)
        lo, hi = self.raw["eligibility_pct_fpl"]["min"], self.raw["eligibility_pct_fpl"]["max"]
        if pct < lo:
            return PTCResult(False, f"household income is {pct:.2f}% FPL, below the {lo}% minimum", "income_floor", pct)
        if pct > hi:
            return PTCResult(
                False, f"household income is {pct:.2f}% FPL, above the {hi}% maximum", "income_ceiling", pct
            )
        if a.medicaid_eligible:
            return PTCResult(False, "eligible for Medicaid (minimum essential coverage)", "medicaid", pct)
        if a.employer_offer_self_only_monthly is not None and self.employer_coverage_affordable(
            a.employer_offer_self_only_monthly, a.annual_household_income
        ):
            return PTCResult(False, "offered affordable employer coverage", "affordable_employer_coverage", pct)
        if a.enrolled_via_income_sep:
            return PTCResult(
                False,
                "enrolled through an income-based special enrollment period (PL 119-21 section 71304)",
                "income_sep",
                pct,
            )
        ap = self.applicable_pct(pct)
        contribution = round(a.annual_household_income * ap / 100 / 12, 2)
        credit = round(min(a.enrolled_monthly_premium, max(0.0, a.benchmark_monthly_premium - contribution)), 2)
        if credit <= 0:
            return PTCResult(
                False,
                f"the expected contribution ${contribution:,.2f}/month is at least the benchmark premium",
                "zero_credit",
                pct,
                ap,
                contribution,
                0.0,
            )
        return PTCResult(True, f"monthly credit ${credit:,.2f}", None, pct, ap, contribution, credit)

    def employer_coverage_affordable(self, self_only_monthly: float, annual_income: float) -> bool:
        """Whether the employee's self-only contribution is at most 9.96% of household income."""
        return round(self_only_monthly * 12, 2) <= round(annual_income * self.required_contribution_pct / 100, 2)

    def fetch_thresholds(self) -> ProgramThresholds:
        """Income ceiling (400% FPL, monthly) by household size."""
        hi = float(self.raw["eligibility_pct_fpl"]["max"])
        households = {
            n: HouseholdThreshold(
                household_size=n,
                gross_monthly=round(self.annual_fpl(n) * hi / 100 / 12, 2),
                net_monthly=round(self.annual_fpl(n) * hi / 100 / 12, 2),
                max_benefit=None,
            )
            for n in range(1, 9)
        }
        return ProgramThresholds(
            program="aca_ptc",
            fiscal_year=self.year,
            state=self.state,
            source=self.raw["_metadata"]["source"],
            source_url=self.raw["_metadata"]["source_url"],
            households=households,
            extra={"fpl_year": self.fpl_year, "required_contribution_pct": self.required_contribution_pct},
        )

    def fetch_policy_summary(self) -> str:
        return (
            f"Premium tax credit, tax year {self.year} ({self.state}):\n"
            f"- Household income 100-400% of the {self.fpl_year} poverty guidelines (enhanced credits expired after "
            "2025).\n"
            "- Not eligible for Medicaid/CHIP or affordable employer coverage "
            f"(self-only contribution <= {self.required_contribution_pct}% of income).\n"
            "- Married taxpayers file jointly (abuse/abandonment exception).\n"
            "- Credit = benchmark premium - income x applicable percentage (Rev. Proc. 2025-25), "
            "capped at the premium.\n"
            "- 2026 changes (PL 119-21): no under-100% route for lawfully present noncitizens; income-based SEP "
            "enrollments excluded; excess advance credit repaid in full."
        )
