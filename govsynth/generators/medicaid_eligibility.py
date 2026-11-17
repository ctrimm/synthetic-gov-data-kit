"""Medicaid eligibility test case generator.

Generates compatible TestCase objects for Medicaid eligibility determination
under the MAGI (Modified Adjusted Gross Income) methodology, covering both
ACA-expansion states (adults covered to 138% FPL) and non-expansion states
(the adult "coverage gap"), plus the higher pregnant/child income limits
that apply regardless of expansion status.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from govsynth.fiscal_year import DEFAULT_MEDICAID_CY
from govsynth.generators.base import Generator
from govsynth.models.enums import Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.reasoning.rules_engine import build_case_id, build_short_uid, build_threshold_test_step
from govsynth.sources.us.census import CensusVintage, census_years_for_strategy
from govsynth.sources.us.medicaid import MedicaidSource

_APPLICANT_TYPES = ["adult", "pregnant", "child_0_18", "parent_caretaker"]

_STRATEGIES = ("edge_saturated", "uniform", "realistic")

_APPLICANT_ROLE_DESC = {
    "adult": "a childless adult",
    "pregnant": "a pregnant woman",
    "child_0_18": "a child",
    "parent_caretaker": "a parent/caretaker relative",
}

_TASK_INSTRUCTION = (
    "Based on the individual's situation described above, determine whether they "
    "are eligible for Medicaid. Show your reasoning step by step, citing the specific "
    "federal regulations (42 CFR Part 435) that apply. State your final determination "
    "(eligible or ineligible) and, if ineligible, explain why — including whether the "
    "individual falls into the ACA coverage gap."
)


class MedicaidEligibilityGenerator(Generator):
    """Generates Medicaid eligibility determination test cases.

    Args:
        calendar_year: Calendar year for MAGI income limits. Default CY2026.
        state: Two-letter state code. Determines ACA expansion status.
    """

    def __init__(self, calendar_year: int = DEFAULT_MEDICAID_CY, state: str = "VA") -> None:
        self.calendar_year = calendar_year
        self.state = state.upper()
        self.source = MedicaidSource(calendar_year=calendar_year, state=state)

    @property
    def program(self) -> str:
        return "medicaid"

    def generate(
        self,
        n: int,
        profile_strategy: str = "edge_saturated",
        seed: int | None = None,
        census_years: Sequence[CensusVintage | int | str] | CensusVintage | int | str | None = None,
    ) -> list[TestCase]:
        """Generate n Medicaid eligibility test cases.

        Args:
            n: Number of cases to generate. Exactly n are returned.
            profile_strategy: 'edge_saturated' (default) places each household's MAGI on
                and around its applicant type's income limit, where determinations are
                hardest. 'uniform' and 'realistic' take household size and income from
                the sampled profile instead ('realistic' samples from Census ACS data).
            seed: RNG seed for reproducibility.
            census_years: ACS release(s) for 'realistic' profiles (see
                SNAPEligibilityGenerator.generate); spread round-robin across cases.
                Only valid with 'realistic'. Medicaid limits stay at `calendar_year`.

        Raises:
            ValueError: On an unknown profile_strategy, or census_years with a
                strategy other than 'realistic'.
            RuntimeError: If a case cannot be built. Cases are never silently dropped.
        """
        if profile_strategy not in _STRATEGIES:
            raise ValueError(f"Unknown profile_strategy {profile_strategy!r}; expected one of {_STRATEGIES}")
        years = census_years_for_strategy(census_years, profile_strategy)
        rng = random.Random(seed)
        cases: list[TestCase] = []

        for i in range(n):
            case_seed = rng.randint(0, 2**31) if seed is not None else None
            vintage = years[i % len(years)] if years else None
            try:
                cases.append(self._build_case(rng, case_seed, profile_strategy, vintage))
            except Exception as exc:
                raise RuntimeError(f"Medicaid case {i} of {n} failed to build: {exc}") from exc

        return cases

    def _build_case(
        self,
        rng: random.Random,
        seed: int | None,
        profile_strategy: str = "edge_saturated",
        census_vintage: CensusVintage | int | str | None = None,
    ) -> TestCase:
        applicant_type = rng.choice(_APPLICANT_TYPES)
        income_limit = self.source.get_income_limit(applicant_type)
        expansion = self.source.is_expansion_state()

        if profile_strategy == "edge_saturated":
            # Draw order is unchanged from before strategies were honoured, so
            # edge-saturated output for a given seed is identical.
            hh_size = rng.choices([1, 2, 3, 4], weights=[0.40, 0.30, 0.20, 0.10])[0]
            if income_limit is None:
                # Adult in a non-expansion state: no MAGI Medicaid path at any
                # income — the coverage gap itself. Sample a plausible low income.
                magi = round(rng.uniform(200, 2000), 2)
            else:
                # Place income near the limit so PASS/FAIL outcomes vary.
                offset = rng.choice([-0.15, -0.05, 0.0, 0.05, 0.15])
                magi = round(max(0.0, income_limit * (1 + offset)), 2)
            profile = USHouseholdProfile.random(state=self.state, seed=seed, strategy="uniform")
            profile.household_size = hh_size
            profile.monthly_gross_income = magi
        else:
            # Household size and income come from the sampled profile itself.
            profile = USHouseholdProfile.random(
                state=self.state,
                seed=seed,
                strategy=profile_strategy,
                census_vintage=census_vintage,
                # Census incomes are in the vintage's dollars; judge them in the rules year's (CPI-U).
                income_dollar_year=self.calendar_year if profile_strategy == "realistic" else None,
            )
            hh_size = profile.household_size
            magi = round(profile.monthly_gross_income, 2)
        profile.monthly_net_income = magi  # MAGI has no SNAP-style deductions

        is_eligible, reason = self.source.is_eligible(hh_size, magi, applicant_type)

        outcome = "eligible" if is_eligible else "ineligible"
        descriptor = "non_expansion_coverage_gap" if income_limit is None else f"{applicant_type}_magi_limit"
        uid = build_short_uid(rng)
        case_id = build_case_id(
            program="medicaid",
            jurisdiction=self.state,
            descriptor=descriptor,
            outcome=outcome,
            household_size=hh_size,
            uid=uid,
        )

        steps = self._build_steps(magi, applicant_type, income_limit, expansion)
        role = _APPLICANT_ROLE_DESC.get(applicant_type, "an applicant")

        return TestCase(
            case_id=case_id,
            program=Program.MEDICAID.value,
            jurisdiction=f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=Difficulty.HARD if income_limit is None else Difficulty.MEDIUM,
            scenario=ScenarioBlock(
                summary=(
                    f"{profile.head_of_household_name} is {role} in {self.state} applying for "
                    f"Medicaid, with a household MAGI of ${magi:,.2f}/month."
                ),
                **{
                    **profile.to_scenario_fields(),
                    "additional_context": {
                        **profile.to_scenario_fields()["additional_context"],
                        "applicant_type": applicant_type,
                        "expansion_state": expansion,
                    },
                },
            ),
            task=TaskBlock(instruction=_TASK_INSTRUCTION),
            expected_outcome=outcome,
            expected_answer=(f"This applicant is {'ELIGIBLE' if is_eligible else 'INELIGIBLE'} for Medicaid. {reason}"),
            rationale_trace=RationaleTrace(
                steps=steps,
                conclusion=f"{'ELIGIBLE' if is_eligible else 'INELIGIBLE'}. {reason}",
                policy_basis=[
                    PolicyCitation(
                        document="42 CFR Part 435",
                        section="42 CFR 435.603",
                        year=self.calendar_year,
                        url="https://www.ecfr.gov/current/title-42/part-435",
                    ),
                ],
            ),
            variation_tags=[descriptor],
            source_citations=[
                "42 CFR Part 435",
                f"CMS/KFF Medicaid Income Eligibility Limits CY{self.calendar_year}",
            ],
            seed=seed,
            metadata={
                "generator": "MedicaidEligibilityGenerator",
                "state": self.state,
                "calendar_year": self.calendar_year,
                "applicant_type": applicant_type,
                "profile_strategy": profile_strategy,
                **({"census_vintage": profile.census_vintage} if profile.census_vintage else {}),
                **({"household_model": profile.household_model} if profile.household_model else {}),
                **({"income_dollar_year": profile.income_dollar_year} if profile.income_dollar_year else {}),
            },
        )

    def _build_steps(
        self,
        magi: float,
        applicant_type: str,
        income_limit: float | None,
        expansion: bool,
    ) -> list[ReasoningStep]:
        steps = [
            ReasoningStep(
                step_number=1,
                title="Identify MAGI income methodology",
                rule_applied="42 CFR 435.603",
                inputs={"monthly_magi": magi, "applicant_type": applicant_type},
                computation=(
                    f"Household MAGI (Modified Adjusted Gross Income): ${magi:,.2f}/month. "
                    f"MAGI does not apply SNAP-style earned income or standard deductions."
                ),
                result=f"Countable MAGI: ${magi:,.2f}",
                is_determinative=False,
            ),
        ]

        if income_limit is None:
            steps.append(
                ReasoningStep(
                    step_number=2,
                    title="Check ACA Medicaid expansion status",
                    rule_applied="42 CFR 435.119",
                    inputs={"state": self.state, "expansion_state": expansion},
                    computation=(
                        f"{self.state} has NOT adopted ACA Medicaid expansion. Adults without "
                        f"dependent children have no MAGI-based Medicaid income path in this state."
                    ),
                    result="No income limit applies — coverage gap",
                    is_determinative=True,
                    note=(
                        "This applicant's income is too high for traditional Medicaid and too "
                        "low to qualify for ACA marketplace subsidies (which require ≥100% FPL)."
                    ),
                )
            )
            return steps

        steps.append(
            build_threshold_test_step(
                step_number=2,
                title=f"Check MAGI income limit for applicant type '{applicant_type}'",
                rule_applied="42 CFR 435.603",
                amount=magi,
                amount_key="monthly_magi",
                limit=income_limit,
                limit_key="income_limit",
                context_note=f"{applicant_type} MAGI limit, CY{self.calendar_year}",
            )
        )
        return steps
