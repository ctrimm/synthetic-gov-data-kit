"""ACA premium tax credit eligibility test case generator (tax year 2026).

Each case asks whether a household qualifies for the premium tax credit and, if so,
for how much per month. The reasoning walks the rules in the order
ACAPremiumTaxCreditSource.determine applies them: filing status, household income
as a percent of the 2025 poverty guidelines (100-400%), Medicaid eligibility,
affordable employer coverage, special-enrollment route, then the applicable
percentage and credit. Exactly one step is determinative when the answer is
"ineligible".

Case families (weighted): income placed on and around the 100%/400% limits and the
applicable-percentage band edges; Medicaid overlap (expansion vs. non-expansion);
employer offers around the 9.96% affordability line; married filing separately
(with and without the abuse/abandonment exception); income-based special enrollment
(PL 119-21 section 71304); lawfully present noncitizens under 100% FPL (no longer
eligible from 2026, section 71302); and credits that round to $0.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any

from govsynth.generators.base import Generator
from govsynth.models.enums import CitizenshipStatus, Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.reasoning.rules_engine import build_case_id, build_short_uid
from govsynth.sources.us.aca_ptc import DEFAULT_PTC_TY, ACAPremiumTaxCreditSource, PTCApplicant, PTCResult
from govsynth.sources.us.census import CensusVintage, census_years_for_strategy
from govsynth.sources.us.medicaid import MedicaidSource

_STRATEGIES = ("edge_saturated", "uniform", "realistic")
_FAMILIES = (
    ("income_band", 0.34),
    ("medicaid_overlap", 0.16),
    ("employer_offer", 0.14),
    ("married_filing_separately", 0.08),
    ("income_sep", 0.08),
    ("lawfully_present_below_100", 0.08),
    ("zero_credit", 0.12),
)
_EDGES = (100, 133, 150, 200, 250, 300, 400)
_OFFSETS = (-0.02, -0.005, 0.0, 0.005, 0.02)

_INSTRUCTION = (
    "Based on the situation described above, determine whether this household qualifies for the ACA premium "
    "tax credit for 2026 coverage. Use household income as a percent of the federal poverty line, and check "
    "filing status, Medicaid eligibility, employer coverage and how the plan was enrolled in. If eligible, compute "
    "the monthly credit using the 2026 applicable percentage table. Show your reasoning step by step, citing "
    "26 U.S.C. 36B and 26 CFR 1.36B. State your final determination (eligible or ineligible) and the credit amount."
)
_RULES = {
    "joint_filing": "26 CFR 1.36B-2(b)(2)",
    "income": "26 U.S.C. 36B(c)(1)(A); 26 CFR 1.36B-2(b)(1)",
    "medicaid": "26 U.S.C. 36B(c)(2)(B); 26 CFR 1.36B-2(c)(2)",
    "employer": "26 CFR 1.36B-2(c)(3)(v); Rev. Proc. 2025-25 section 3.02",
    "sep": "26 U.S.C. 36B(c)(3)(A) as amended by PL 119-21 section 71304",
    "credit": "26 CFR 1.36B-3(d), (g); Rev. Proc. 2025-25 section 3.01",
}


class ACAPremiumTaxCreditGenerator(Generator):
    """Generates 2026 premium tax credit eligibility test cases for one state.

    Args:
        tax_year: Tax/coverage year. Default 2026 (the only bundled year).
        state: Two-letter state code (sets the poverty guidelines region and Medicaid rules).
    """

    def __init__(self, tax_year: int = DEFAULT_PTC_TY, state: str = "VA") -> None:
        self.tax_year = tax_year
        self.state = state.upper()
        self.source = ACAPremiumTaxCreditSource(tax_year=tax_year, state=self.state)
        self.medicaid = MedicaidSource(calendar_year=tax_year, state=self.state)

    @property
    def program(self) -> str:
        return "aca_ptc"

    def generate(
        self,
        n: int,
        profile_strategy: str = "edge_saturated",
        seed: int | None = None,
        census_years: Sequence[CensusVintage | int | str] | CensusVintage | int | str | None = None,
    ) -> list[TestCase]:
        """Generate n cases. Exactly n are returned.

        Args:
            n: Number of cases.
            profile_strategy: 'edge_saturated' (default) places income on and around the rule boundaries;
                'uniform' and 'realistic' take household size and income from the sampled profile.
            seed: RNG seed.
            census_years: ACS release(s) for 'realistic' profiles; only valid with 'realistic'.

        Raises:
            ValueError: On an unknown strategy or misplaced census_years.
            RuntimeError: If a case cannot be built.
        """
        if profile_strategy not in _STRATEGIES:
            raise ValueError(f"Unknown profile_strategy {profile_strategy!r}; expected one of {_STRATEGIES}")
        years = census_years_for_strategy(census_years, profile_strategy)
        rng = random.Random(seed)
        cases = []
        for i in range(n):
            case_seed = rng.randint(0, 2**31) if seed is not None else None
            vintage = years[i % len(years)] if years else None
            try:
                cases.append(self._build_case(rng, case_seed, profile_strategy, vintage))
            except Exception as exc:
                raise RuntimeError(f"ACA PTC case {i} of {n} failed to build: {exc}") from exc
        return cases

    # ------------------------------------------------------------------

    def _income_at(self, pct: float, size: int) -> float:
        return round(self.source.annual_fpl(size) * pct / 100, 2)

    def _build_case(
        self,
        rng: random.Random,
        seed: int | None,
        strategy: str,
        vintage: CensusVintage | int | str | None,
    ) -> TestCase:
        src = self.source
        family = rng.choices([f for f, _ in _FAMILIES], weights=[w for _, w in _FAMILIES])[0]
        size = rng.choices((1, 2, 3, 4, 5), weights=(0.35, 0.25, 0.18, 0.14, 0.08))[0]
        if family == "employer_offer":
            size = 1

        if strategy == "edge_saturated":
            if family == "income_band":
                income = self._income_at(rng.choice(_EDGES) * (1 + rng.choice(_OFFSETS)), size)
            elif family == "medicaid_overlap":
                income = self._income_at(rng.uniform(100, 150), size)
            elif family == "lawfully_present_below_100":
                income = self._income_at(rng.uniform(55, 99), size)
            elif family == "zero_credit":
                income = self._income_at(rng.uniform(330, 400), size)
            else:
                income = self._income_at(rng.uniform(140, 380), size)
            profile = USHouseholdProfile.random(state=self.state, seed=seed, strategy="uniform")
        else:
            profile = USHouseholdProfile.random(
                state=self.state,
                seed=seed,
                strategy=strategy,
                census_vintage=vintage,
                income_dollar_year=self.tax_year if strategy == "realistic" else None,
            )
            size = 1 if family == "employer_offer" else profile.household_size
            income = round(profile.monthly_gross_income * 12, 2)

        pct = src.pct_fpl(income, size)
        married = size >= 2 and rng.random() < 0.6
        files_jointly, exception = True, False
        if family == "married_filing_separately":
            married, files_jointly = True, False
            size = max(size, 2)
            exception = rng.random() < 0.35
        # Benchmark (second-lowest-cost silver) premium for the household; synthetic, stated in the scenario.
        per_person = rng.uniform(420, 760)
        benchmark = round(per_person * (1 + 0.85 * (size - 1)), 2)
        if family == "zero_credit":
            benchmark = round(rng.uniform(0.7, 1.05) * income * src.applicable_pct(min(pct, 400)) / 100 / 12, 2)
        enrolled = benchmark if rng.random() < 0.6 else round(benchmark * rng.uniform(0.55, 0.95), 2)

        applicant = "parent_caretaker" if size >= 3 else "adult"
        medicaid_eligible, medicaid_reason = self.medicaid.is_eligible(size, round(income / 12, 2), applicant)
        citizenship = CitizenshipStatus.CITIZEN
        if family == "lawfully_present_below_100":
            # Lawfully present but within the five-year bar, so Medicaid-ineligible because of status.
            citizenship = CitizenshipStatus.QUALIFIED_ALIEN
            medicaid_eligible = False
            medicaid_reason = "Ineligible for Medicaid because of immigration status (five-year bar)"
        offer = None
        if family == "employer_offer":
            threshold = income * src.required_contribution_pct / 100 / 12
            offer = round(threshold * rng.choice((0.8, 0.97, 1.0, 1.03, 1.25)), 2)

        a = PTCApplicant(
            household_size=size,
            annual_household_income=income,
            married=married,
            files_jointly=files_jointly,
            abuse_or_abandonment_exception=exception,
            medicaid_eligible=medicaid_eligible,
            employer_offer_self_only_monthly=offer,
            enrolled_via_income_sep=family == "income_sep",
            benchmark_monthly_premium=benchmark,
            enrolled_monthly_premium=enrolled,
        )
        result = src.determine(a)
        steps = self._steps(a, result, medicaid_reason, citizenship)

        outcome = "eligible" if result.eligible else "ineligible"
        descriptor = family if family != "income_band" else f"income_{int(round(pct))}pct"
        case_id = build_case_id("aca_ptc", self.state, descriptor, outcome, size, build_short_uid(rng))

        profile.household_size = size
        profile.monthly_gross_income = round(income / 12, 2)
        profile.monthly_net_income = round(income / 12, 2)
        profile.earned_income = round(income / 12, 2)
        profile.unearned_income = 0.0
        profile.citizenship_status = citizenship
        profile.has_elderly_or_disabled = False
        profile.age_of_head = rng.randint(26, 59)
        profile.has_dependent_children = size >= 3 or (size == 2 and not married)
        fields = profile.to_scenario_fields()
        context: dict[str, Any] = {
            "annual_household_income": income,
            "tax_family_size": size,
            "filing_status": "married_filing_jointly"
            if married and files_jointly
            else "married_filing_separately"
            if married
            else ("head_of_household" if size >= 2 else "single"),
            "benchmark_silver_premium_monthly": benchmark,
            "enrolled_plan_premium_monthly": enrolled,
            "employer_self_only_contribution_monthly": offer,
            "enrolled_via_income_based_sep": family == "income_sep",
        }
        if married and not files_jointly:
            context["domestic_abuse_or_abandonment_certified"] = exception
        if family == "lawfully_present_below_100":
            context["lawfully_present_medicaid_ineligible_due_to_status"] = True
        fields["additional_context"] = {**fields["additional_context"], **context}

        summary = self._summary(profile.head_of_household_name, a, context, family)
        if result.eligible:
            answer = (
                f"ELIGIBLE for the premium tax credit. Applicable percentage {result.applicable_pct:.2f}%, expected "
                f"contribution ${result.monthly_contribution:,.2f}/month, credit ${result.monthly_credit:,.2f}/month."
            )
        else:
            answer = f"INELIGIBLE for the premium tax credit: {result.reason}."
        near_edge = min(abs(pct - e) for e in _EDGES) <= 1
        difficulty = (
            Difficulty.ADVERSARIAL
            if family in ("lawfully_present_below_100", "income_sep", "married_filing_separately")
            else Difficulty.HARD
            if near_edge or family in ("employer_offer", "zero_credit")
            else Difficulty.MEDIUM
        )
        return TestCase(
            case_id=case_id,
            program=Program.ACA_PTC.value,
            jurisdiction=f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=difficulty,
            scenario=ScenarioBlock(summary=summary, **fields),
            task=TaskBlock(instruction=_INSTRUCTION),
            expected_outcome=outcome,
            expected_answer=answer,
            rationale_trace=RationaleTrace(
                steps=steps,
                conclusion=answer,
                policy_basis=[
                    PolicyCitation(
                        document="26 U.S.C. 36B; 26 CFR 1.36B-1 to 1.36B-3",
                        section="26 U.S.C. 36B",
                        year=self.tax_year,
                        url="https://www.ecfr.gov/current/title-26/chapter-I/subchapter-A/part-1/subject-group-ECFR4ea1b2c4fe1ea3b/section-1.36B-2",
                    ),
                    PolicyCitation(
                        document="Rev. Proc. 2025-25",
                        section="Applicable percentage table for 2026",
                        year=self.tax_year,
                        url=src.raw["_metadata"]["source_url"],
                    ),
                ],
            ),
            variation_tags=[family, descriptor],
            source_citations=["26 U.S.C. 36B", "26 CFR 1.36B-2", "26 CFR 1.36B-3", "Rev. Proc. 2025-25", "PL 119-21"],
            seed=seed,
            metadata={
                "generator": "ACAPremiumTaxCreditGenerator",
                "state": self.state,
                "tax_year": self.tax_year,
                "case_family": family,
                "profile_strategy": strategy,
                "failed_rule": result.failed_rule,
                "monthly_credit": result.monthly_credit,
                **({"census_vintage": profile.census_vintage} if profile.census_vintage else {}),
                **({"household_model": profile.household_model} if profile.household_model else {}),
            },
        )

    def _summary(self, name: str, a: PTCApplicant, ctx: dict[str, object], family: str) -> str:
        parts = [
            f"{name} lives in {self.state} and is applying for 2026 marketplace coverage for a tax household of "
            f"{a.household_size} with projected household income of ${a.annual_household_income:,.2f}.",
            f"The benchmark silver plan costs ${a.benchmark_monthly_premium:,.2f}/month and the plan they chose costs "
            f"${a.enrolled_monthly_premium:,.2f}/month.",
        ]
        if a.married:
            parts.append(
                "They are married and filing jointly."
                if a.files_jointly
                else "They are married and will file separately"
                + (
                    ", living apart from a spouse they cannot file with because of domestic abuse, and certify this."
                    if a.abuse_or_abandonment_exception
                    else "."
                )
            )
        if a.employer_offer_self_only_monthly is not None:
            parts.append(
                f"Their employer offers coverage costing ${a.employer_offer_self_only_monthly:,.2f}/month for "
                "self-only coverage."
            )
        if a.enrolled_via_income_sep:
            parts.append("They enrolled mid-year through a special enrollment period based on a change in income.")
        if family == "lawfully_present_below_100":
            parts.append(
                "They are lawfully present noncitizens who are not eligible for Medicaid because of their "
                "immigration status (the five-year bar)."
            )
        return " ".join(parts)

    def _steps(
        self, a: PTCApplicant, r: PTCResult, medicaid_reason: str, citizenship: CitizenshipStatus
    ) -> list[ReasoningStep]:
        """Steps in the order determine() applies them; exactly one determinative FAIL if ineligible."""
        src = self.source
        steps: list[ReasoningStep] = []

        def add(title: str, rule: str, inputs: dict[str, object], computation: str, result: str, fail: bool) -> bool:
            steps.append(
                ReasoningStep(
                    step_number=len(steps) + 1,
                    title=title,
                    rule_applied=rule,
                    inputs=inputs,
                    computation=computation,
                    result=result,
                    is_determinative=fail,
                )
            )
            return fail

        fpl = src.annual_fpl(a.household_size)
        add(
            "Express household income as a percent of the poverty line",
            "26 CFR 1.36B-1(e), (h)",
            {"annual_household_income": a.annual_household_income, "household_size": a.household_size, "fpl": fpl},
            f"${a.annual_household_income:,.2f} / ${fpl:,.0f} ({src.fpl_year} poverty guideline, in effect when 2026 "
            f"open enrollment began; household of {a.household_size}) = {r.pct_fpl:.2f}% FPL",
            f"{r.pct_fpl:.2f}% FPL",
            False,
        )
        status = "married filing jointly" if a.married and a.files_jointly else "unmarried" if not a.married else ""
        if a.married and not a.files_jointly:
            ok = a.abuse_or_abandonment_exception
            if add(
                "Check filing status",
                _RULES["joint_filing"],
                {"married": True, "files_jointly": False, "exception": ok},
                "Married filing separately; "
                + (
                    "the domestic abuse/abandonment exception applies (living apart, certified on the return)."
                    if ok
                    else "no exception applies, so the taxpayer must file jointly to claim the credit."
                ),
                "PASS - exception applies" if ok else "FAIL - married filing separately",
                not ok,
            ):
                return steps
        else:
            add(
                "Check filing status",
                _RULES["joint_filing"],
                {"married": a.married, "files_jointly": a.files_jointly},
                f"Taxpayer is {status}; no joint-filing problem.",
                "PASS",
                False,
            )

        lo, hi = src.raw["eligibility_pct_fpl"]["min"], src.raw["eligibility_pct_fpl"]["max"]
        within = lo <= r.pct_fpl <= hi
        note = ""
        if r.pct_fpl < lo and citizenship == CitizenshipStatus.QUALIFIED_ALIEN:
            note = (
                " Before 2026, lawfully present noncitizens below 100% FPL who were Medicaid-ineligible because of "
                "status could still qualify (36B(c)(1)(B)); PL 119-21 section 71302 removed that rule for 2026."
            )
        if add(
            "Check household income against 100-400% of the poverty line",
            _RULES["income"],
            {"pct_fpl": round(r.pct_fpl, 2), "min_pct_fpl": lo, "max_pct_fpl": hi},
            f"{r.pct_fpl:.2f}% FPL {'is' if within else 'is not'} within {lo}-{hi}% FPL.{note}",
            "PASS" if within else ("FAIL - below 100% FPL" if r.pct_fpl < lo else "FAIL - above 400% FPL"),
            not within,
        ):
            return steps

        if add(
            "Check eligibility for Medicaid",
            _RULES["medicaid"],
            {"medicaid_eligible": a.medicaid_eligible},
            "Medicaid uses current monthly income against its own CY2026 limits (2026 guidelines). "
            + medicaid_reason.replace("Ineligible: ", "Not eligible: ").replace(
                "Eligible: ", "Eligible for Medicaid: "
            ),
            "FAIL - eligible for Medicaid" if a.medicaid_eligible else "PASS - not eligible for Medicaid",
            a.medicaid_eligible,
        ):
            return steps

        if a.employer_offer_self_only_monthly is not None:
            annual = round(a.employer_offer_self_only_monthly * 12, 2)
            cap = round(a.annual_household_income * src.required_contribution_pct / 100, 2)
            affordable = annual <= cap
            if add(
                "Check whether the employer coverage offer is affordable",
                _RULES["employer"],
                {"self_only_annual": annual, "affordability_cap": cap},
                f"Self-only contribution ${annual:,.2f}/year {'<=' if affordable else '>'} "
                f"{src.required_contribution_pct}% of household income (${cap:,.2f})",
                "FAIL - affordable employer coverage" if affordable else "PASS - not affordable",
                affordable,
            ):
                return steps

        if add(
            "Check how the plan was enrolled in",
            _RULES["sep"],
            {"enrolled_via_income_based_sep": a.enrolled_via_income_sep},
            "Enrolled through a special enrollment period based on a change in expected household income, which is "
            "not a qualified health plan for the credit from 2026."
            if a.enrolled_via_income_sep
            else "Enrolled through open enrollment or a qualifying non-income special enrollment period.",
            "FAIL - income-based SEP enrollment" if a.enrolled_via_income_sep else "PASS",
            a.enrolled_via_income_sep,
        ):
            return steps

        assert r.applicable_pct is not None and r.monthly_contribution is not None and r.monthly_credit is not None
        zero = r.monthly_credit <= 0
        diff = round(a.benchmark_monthly_premium - r.monthly_contribution, 2)
        add(
            "Compute the applicable percentage and monthly credit",
            _RULES["credit"],
            {
                "pct_fpl": round(r.pct_fpl, 2),
                "applicable_pct": r.applicable_pct,
                "benchmark_monthly": a.benchmark_monthly_premium,
                "enrolled_monthly": a.enrolled_monthly_premium,
            },
            f"At {r.pct_fpl:.2f}% FPL the applicable percentage is {r.applicable_pct:.2f}%. Contribution: "
            f"${a.annual_household_income:,.2f} × {r.applicable_pct:.2f}% / 12 = ${r.monthly_contribution:,.2f}. "
            f"Benchmark ${a.benchmark_monthly_premium:,.2f} − contribution ${r.monthly_contribution:,.2f} = "
            f"{'−' if diff < 0 else ''}${abs(diff):,.2f}"
            + (" (no credit below $0)" if diff <= 0 else "")
            + f"; credit = lesser of that and the enrolled premium ${a.enrolled_monthly_premium:,.2f} = "
            f"${r.monthly_credit:,.2f}/month.",
            "FAIL - credit is $0" if zero else f"Credit ${r.monthly_credit:,.2f}/month",
            zero,
        )
        return steps
