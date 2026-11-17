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

from faker import Faker

from govsynth.fiscal_year import DEFAULT_MEDICAID_CY
from govsynth.generators.base import Generator
from govsynth.models.enums import Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.reasoning.rules_engine import build_case_id, build_short_uid, build_threshold_test_step
from govsynth.sources.us.census import CensusVintage, census_years_for_strategy
from govsynth.sources.us.medicaid import MedicaidSource, child_age_band

_APPLICANT_TYPES = ["adult", "pregnant", "child", "parent_caretaker"]

_STRATEGIES = ("edge_saturated", "uniform", "realistic")

_APPLICANT_ROLE_DESC = {
    "adult": "an adult with no dependent children",
    "pregnant": "a pregnant woman",
    "child": "a child",
    "parent_caretaker": "a parent/caretaker relative",
}

# Household sizes by applicant type (MAGI household, 42 CFR 435.603(f)); a pregnant
# woman's household counts the expected child (435.603(b)).
_SIZES = {
    "adult": ((1, 2), (0.75, 0.25)),
    "parent_caretaker": ((2, 3, 4, 5), (0.30, 0.35, 0.22, 0.13)),
    "pregnant": ((2, 3, 4), (0.45, 0.35, 0.20)),
    "child": ((2, 3, 4, 5), (0.25, 0.35, 0.25, 0.15)),
}

# Coverage group regulation for each applicant type.
_GROUP_RULE = {
    "adult": "42 CFR 435.119",
    "parent_caretaker": "42 CFR 435.110",
    "pregnant": "42 CFR 435.116",
    "child": "42 CFR 435.118",
}
_GROUP_NAME = {
    "adult": "adult group (ages 19-64, no dependent children)",
    "parent_caretaker": "parents and caretaker relatives",
    "pregnant": "pregnant women",
    "child": "infants and children under 19",
}
_OFFSETS = (-0.15, -0.05, -0.01, 0.0, 0.01, 0.05, 0.15)

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
        src = self.source
        applicant_type = rng.choice(_APPLICANT_TYPES)
        child_age = rng.randint(0, 18) if applicant_type == "child" else None
        pct_limit = src.limit_pct(applicant_type, child_age)
        expansion = src.is_expansion_state()
        sizes, weights = _SIZES[applicant_type]

        if profile_strategy == "edge_saturated":
            hh_size = rng.choices(sizes, weights=weights)[0]
            if pct_limit is None:
                # No coverage group for this applicant: sample around the 100% FPL marketplace floor,
                # so both the coverage gap and the above-100% case appear.
                magi = round(src.monthly_limit(rng.uniform(20, 130), hh_size), 2)
            else:
                magi = round(max(0.0, src.monthly_limit(pct_limit, hh_size) * (1 + rng.choice(_OFFSETS))), 2)
            profile = USHouseholdProfile.random(state=self.state, seed=seed, strategy="uniform")
        else:
            # Household income (and size, where it fits the applicant type) come from the profile.
            profile = USHouseholdProfile.random(
                state=self.state,
                seed=seed,
                strategy=profile_strategy,
                census_vintage=census_vintage,
                # Census incomes are in the vintage's dollars; judge them in the rules year's (CPI-U).
                income_dollar_year=self.calendar_year if profile_strategy == "realistic" else None,
            )
            hh_size = min(max(profile.household_size, sizes[0]), sizes[-1])
            magi = round(profile.monthly_gross_income, 2)

        # Make the profile describe the applicant: adults and parents are 19-64 (MAGI groups),
        # so no elderly member is implied; children and pregnancy imply a family.
        profile.household_size = hh_size
        profile.monthly_gross_income = magi
        profile.monthly_net_income = magi  # MAGI has no SNAP-style deductions
        profile.earned_income = magi
        profile.unearned_income = 0.0
        profile.has_elderly_or_disabled = False
        profile.age_of_head = rng.randint(19, 59) if applicant_type != "pregnant" else rng.randint(19, 42)
        if applicant_type == "pregnant":
            names = Faker("en_US")
            names.seed_instance(seed)
            profile.head_of_household_name = names.name_female()
        profile.has_dependent_children = applicant_type in ("parent_caretaker", "child") or (
            applicant_type == "pregnant" and hh_size > 2
        )

        is_eligible, reason = src.is_eligible(hh_size, magi, applicant_type, child_age)
        pct_fpl = src.pct_fpl(magi, hh_size)
        outcome = "eligible" if is_eligible else "ineligible"
        if pct_limit is None:
            descriptor = "non_expansion_coverage_gap" if pct_fpl < 100 else "no_adult_coverage_above_100pct"
        else:
            descriptor = f"{applicant_type}_magi_limit"
        case_id = build_case_id(
            program="medicaid",
            jurisdiction=self.state,
            descriptor=descriptor,
            outcome=outcome,
            household_size=hh_size,
            uid=build_short_uid(rng),
        )

        steps = self._build_steps(magi, hh_size, applicant_type, child_age, pct_limit, expansion)
        if pct_limit is None:
            difficulty = Difficulty.HARD
        else:
            gap = abs(magi - src.monthly_limit(pct_limit, hh_size)) / src.monthly_limit(pct_limit, hh_size)
            difficulty = Difficulty.HARD if gap <= 0.01 else Difficulty.MEDIUM if gap <= 0.05 else Difficulty.EASY
        role = _APPLICANT_ROLE_DESC[applicant_type]
        who = f"{profile.head_of_household_name} is {role}"
        if applicant_type == "child":
            who = f"{profile.head_of_household_name}'s {'infant' if child_age == 0 else f'{child_age}-year-old'} child"
        household = f"a household of {hh_size}" + (
            " (counting the expected child)" if applicant_type == "pregnant" else ""
        )
        extra_context: dict[str, object] = {"applicant_type": applicant_type, "expansion_state": expansion}
        if child_age is not None:
            extra_context["child_age"] = child_age
            extra_context["child_has_other_coverage"] = False
        if applicant_type == "adult" and pct_limit is not None and not expansion and self.state == "GA":
            extra_context["meets_georgia_pathways_qualifying_activities"] = True
        summary = (
            f"{who} in {self.state}, applying for Medicaid. {household.capitalize()} has a MAGI of ${magi:,.2f}/month."
        )
        if child_age is not None:
            summary += " The child has no other health coverage."

        fields = profile.to_scenario_fields()
        fields["additional_context"] = {**fields["additional_context"], **extra_context}
        return TestCase(
            case_id=case_id,
            program=Program.MEDICAID.value,
            jurisdiction=f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=difficulty,
            scenario=ScenarioBlock(summary=summary, **fields),
            task=TaskBlock(instruction=_TASK_INSTRUCTION),
            expected_outcome=outcome,
            expected_answer=f"This applicant is {'ELIGIBLE' if is_eligible else 'INELIGIBLE'} for Medicaid. {reason}",
            rationale_trace=RationaleTrace(
                steps=steps,
                conclusion=f"{'ELIGIBLE' if is_eligible else 'INELIGIBLE'}. {reason}",
                policy_basis=[
                    PolicyCitation(
                        document="42 CFR Part 435",
                        section=f"42 CFR 435.603; {_GROUP_RULE[applicant_type]}",
                        year=self.calendar_year,
                        url="https://www.ecfr.gov/current/title-42/part-435",
                    ),
                ],
            ),
            variation_tags=[descriptor] + ([f"ages_{child_age_band(child_age)}"] if child_age is not None else []),
            source_citations=[
                "42 CFR 435.603",
                _GROUP_RULE[applicant_type],
                f"KFF Medicaid Income Eligibility Limits (January {self.calendar_year})",
            ],
            seed=seed,
            metadata={
                "generator": "MedicaidEligibilityGenerator",
                "state": self.state,
                "calendar_year": self.calendar_year,
                "applicant_type": applicant_type,
                "profile_strategy": profile_strategy,
                **({"child_age": child_age} if child_age is not None else {}),
                **({"census_vintage": profile.census_vintage} if profile.census_vintage else {}),
                **({"household_model": profile.household_model} if profile.household_model else {}),
                **({"income_dollar_year": profile.income_dollar_year} if profile.income_dollar_year else {}),
            },
        )

    def _build_steps(
        self,
        magi: float,
        hh_size: int,
        applicant_type: str,
        child_age: int | None,
        pct_limit: int | None,
        expansion: bool,
    ) -> list[ReasoningStep]:
        """Steps in the order MedicaidSource.is_eligible applies them; one determinative FAIL if ineligible."""
        src = self.source
        fpl = src.annual_fpl(hh_size)
        pct_fpl = src.pct_fpl(magi, hh_size)
        counted = ", counting the expected child per 42 CFR 435.603(b)" if applicant_type == "pregnant" else ""
        steps = [
            ReasoningStep(
                step_number=1,
                title="Express household MAGI as a percent of the poverty guideline",
                rule_applied="42 CFR 435.603",
                inputs={"monthly_magi": magi, "household_size": hh_size, "annual_fpl": fpl},
                computation=(
                    f"MAGI ${magi:,.2f}/month × 12 / ${fpl:,.0f} ({src.fy_config.fpl_year} poverty guideline, "
                    f"household of {hh_size}{counted}) = {pct_fpl:.2f}% FPL. "
                    "MAGI has no SNAP-style earned income or standard deductions."
                ),
                result=f"{pct_fpl:.2f}% FPL",
                is_determinative=False,
            ),
        ]
        group = _GROUP_NAME[applicant_type]
        if child_age is not None:
            group += f", ages {child_age_band(child_age)}"
        rule = _GROUP_RULE[applicant_type]
        note = src.row.get("note") if applicant_type in ("adult", "parent_caretaker") else None

        if pct_limit is None:
            gap = pct_fpl < 100
            steps.append(
                ReasoningStep(
                    step_number=2,
                    title="Identify a Medicaid coverage group",
                    rule_applied=rule,
                    inputs={"state": self.state, "expansion_state": expansion, "applicant_type": applicant_type},
                    computation=(
                        f"{self.state} has NOT adopted ACA Medicaid expansion and has no coverage group for adults "
                        "without dependent children, so there is no MAGI Medicaid income limit to test."
                    ),
                    result="FAIL - no Medicaid coverage group",
                    is_determinative=True,
                    note=(
                        f"At {pct_fpl:.0f}% FPL the applicant is in the coverage gap: below the 100% FPL floor for "
                        "marketplace premium tax credits."
                        if gap
                        else f"At {pct_fpl:.0f}% FPL the applicant may instead qualify for marketplace premium tax "
                        "credits (100-400% FPL)."
                    ),
                )
            )
            return steps

        limit = src.monthly_limit(pct_limit, hh_size)
        basis = "ACA expansion adult group" if applicant_type == "adult" and expansion else group
        steps.append(
            ReasoningStep(
                step_number=2,
                title="Identify the coverage group and its income limit",
                rule_applied=rule,
                inputs={"applicant_type": applicant_type, "limit_pct_fpl": pct_limit, "income_limit": limit},
                computation=(
                    f"{self.state}: {basis}, limit {pct_limit}% FPL = ${fpl:,.0f} × {pct_limit}% / 12 = "
                    f"${limit:,.2f}/month for a household of {hh_size}"
                ),
                result=f"Income limit ${limit:,.2f}/month",
                is_determinative=False,
                note=note,
            )
        )
        over_note = None
        row = src.row
        if magi > limit and applicant_type == "pregnant":
            other = max(v for v in (row["pregnant_chip_pct_fpl"], row["pregnant_fcep_pct_fpl"], 0) if v is not None)
            if other and pct_fpl <= other:
                over_note = (
                    f"Above the Medicaid limit, but {self.state} covers pregnancy through CHIP up to {other}% FPL."
                )
        if magi > limit and applicant_type == "child":
            over_note = "Above the Medicaid limit; the child may still qualify for a separate CHIP program."
        steps.append(
            build_threshold_test_step(
                step_number=3,
                title="Compare MAGI to the income limit",
                rule_applied=rule,
                amount=magi,
                amount_key="monthly_magi",
                limit=limit,
                limit_key="income_limit",
                context_note=f"{pct_limit}% FPL, household of {hh_size}, CY{self.calendar_year}",
                note=over_note,
            )
        )
        return steps
