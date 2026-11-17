"""Children's Medicaid and CHIP eligibility test case generator.

Each case asks which coverage, if any, a child qualifies for: Medicaid, Medicaid
paid with CHIP funds, or a separate CHIP program. The reasoning a model has to
show is the hand-off: find the Medicaid limit for the child's age band, and only
above it consider CHIP, which covers uninsured children only.

Under 'edge_saturated' (the default) household MAGI is placed on and around each
limit that exists for the child's age band in the state; about a quarter of
children above the Medicaid limit already have other coverage, and a few
applicants are 19 (no longer children). Any other strategy samples MAGI uniformly
up to 1.2x the state's upper limit.
"""

from __future__ import annotations

import random

from govsynth.generators.base import Generator
from govsynth.models.enums import Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.reasoning.rules_engine import build_case_id, build_short_uid
from govsynth.sources.us.chip import DEFAULT_CHIP_CY, CHIPSource, age_band

_INSTRUCTION = (
    "Based on the situation described above, determine whether the child qualifies for Medicaid, for CHIP, or "
    "for neither, in their state. Use household MAGI as a percent of the 2026 federal poverty guidelines, the "
    "limit for the child's age group, and whether the child has other health coverage. Show your reasoning step "
    "by step, citing 42 CFR 435.118 and 42 CFR 457.310. State your final determination (eligible or ineligible) "
    "and, if eligible, the program."
)
_OFFSETS = (-0.05, -0.01, -0.002, 0.0, 0.002, 0.01, 0.05)
_PROGRAM_NAME = {
    "medicaid": "Medicaid",
    "medicaid_chip_funded": "Medicaid (CHIP-funded)",
    "separate_chip": "separate CHIP",
}


class CHIPEligibilityGenerator(Generator):
    """Generates children's Medicaid/CHIP eligibility test cases for one state.

    Args:
        calendar_year: Calendar year of the limits. Default 2026.
        state: Two-letter state code (any of the 50 states or DC).
    """

    def __init__(self, calendar_year: int = DEFAULT_CHIP_CY, state: str = "VA") -> None:
        self.calendar_year = calendar_year
        self.state = state.upper()
        self.source = CHIPSource(calendar_year=calendar_year, state=state)

    @property
    def program(self) -> str:
        return "chip"

    def generate(
        self,
        n: int,
        profile_strategy: str = "edge_saturated",
        seed: int | None = None,
    ) -> list[TestCase]:
        """Generate n cases. Exactly n are returned."""
        rng = random.Random(seed)
        cases = []
        for i in range(n):
            case_seed = rng.randint(0, 2**31) if seed is not None else None
            try:
                cases.append(self._build_case(rng, case_seed, edge=profile_strategy == "edge_saturated"))
            except Exception as exc:
                raise RuntimeError(f"CHIP case {i} of {n} failed to build: {exc}") from exc
        return cases

    # ------------------------------------------------------------------

    def _boundaries(self, band: str) -> list[int]:
        src = self.source
        limits = {src.medicaid_limit(band)}
        r = src.chip_funded_range(band)
        if r:
            limits.add(r[1])
        if src.separate_chip_limit is not None:
            limits.add(src.separate_chip_limit)
        return sorted(limits)

    def _build_case(self, rng: random.Random, seed: int | None, edge: bool) -> TestCase:
        src = self.source
        age = 19 if rng.random() < 0.05 else rng.choice([0, *range(1, 19)])
        size = rng.choices((2, 3, 4, 5, 6), weights=(0.20, 0.30, 0.28, 0.14, 0.08))[0]
        band = age_band(age) or "6-18"
        limits = self._boundaries(band)
        if edge:
            target = rng.choice(limits)
            magi = round(src.monthly_limit(target, size) * (1 + rng.choice(_OFFSETS)), 2)
        else:
            magi = round(rng.uniform(0.2, 1.2) * src.monthly_limit(max(limits), size), 2)
        insured = magi > src.monthly_limit(src.medicaid_limit(band), size) and rng.random() < 0.25

        result = src.determine(age, size, magi, insured)
        steps = self._steps(age, size, magi, insured)

        profile = USHouseholdProfile.random(state=self.state, seed=seed)
        profile.household_size = size
        profile.monthly_gross_income = magi
        profile.monthly_net_income = magi
        profile.has_dependent_children = True

        outcome = "eligible" if result.eligible else "ineligible"
        descriptor = result.program or (
            "not_a_child" if age > 18 else "insured_above_medicaid" if insured else "above_limit"
        )
        case_id = build_case_id("chip", self.state, descriptor, outcome, size, build_short_uid(rng))
        coverage = "has employer-sponsored coverage" if insured else "has no other health coverage"
        who = "infant" if age == 0 else f"{age}-year-old"
        summary = (
            f"{profile.head_of_household_name}'s {who} child in {self.state} {coverage}. The household of {size} "
            f"has a monthly MAGI of ${magi:,.2f}."
        )
        gaps = [abs(magi - src.monthly_limit(lim, size)) / src.monthly_limit(lim, size) for lim in limits]
        if age > 18:
            difficulty = Difficulty.EASY
        elif insured:
            difficulty = Difficulty.ADVERSARIAL
        else:
            gap = min(gaps)
            difficulty = Difficulty.HARD if gap <= 0.01 else (Difficulty.EASY if gap > 0.15 else Difficulty.MEDIUM)
        program_name = _PROGRAM_NAME.get(result.program or "", "")
        answer = (
            f"The child is ELIGIBLE for {program_name}. {result.reason}."
            if result.eligible
            else f"The child is INELIGIBLE for Medicaid and CHIP. {result.reason}."
        )

        fields = profile.to_scenario_fields()
        fields["additional_context"] = {
            **fields["additional_context"],
            "child_age": age,
            "child_insured": insured,
            "monthly_magi": magi,
            "pct_fpl": result.pct_fpl,
            "coverage_program": result.program,
        }
        return TestCase(
            case_id=case_id,
            program=Program.CHIP.value,
            jurisdiction=f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=difficulty,
            scenario=ScenarioBlock(summary=summary, **fields),
            task=TaskBlock(instruction=_INSTRUCTION),
            expected_outcome=outcome,
            expected_answer=answer,
            rationale_trace=RationaleTrace(
                steps=steps,
                conclusion=f"{outcome.upper()}. {result.reason}.",
                policy_basis=[
                    PolicyCitation(
                        document="42 CFR Part 457",
                        section="42 CFR 435.118; 42 CFR 457.310",
                        year=self.calendar_year,
                        url=src.raw["_metadata"]["source_url"],
                    )
                ],
            ),
            variation_tags=[descriptor, f"ages_{band}"],
            source_citations=[
                "42 CFR 435.118",
                "42 CFR 457.310",
                f"KFF Medicaid and CHIP Income Eligibility Limits for Children (January {self.calendar_year})",
            ],
            seed=seed,
            metadata={
                "generator": "CHIPEligibilityGenerator",
                "state": self.state,
                "calendar_year": self.calendar_year,
                "coverage_program": result.program,
            },
        )

    def _steps(self, age: int, size: int, magi: float, insured: bool) -> list[ReasoningStep]:
        """Steps in the order CHIPSource.determine applies them; exactly one determinative FAIL if ineligible."""
        src = self.source
        band = age_band(age)
        pct = src.pct_fpl(magi, size)
        fpl = src.annual_fpl(size)
        steps = [
            ReasoningStep(
                step_number=1,
                title="Express household MAGI as a percent of the poverty guideline",
                rule_applied="42 CFR 435.603",
                inputs={"monthly_magi": magi, "household_size": size, "annual_fpl": fpl},
                computation=f"${magi:,.2f} x 12 / ${fpl:,.0f} (2026 FPL, household of {size}) = {pct:.2f}%",
                result=f"{pct:.2f}% FPL",
                is_determinative=False,
            ),
            ReasoningStep(
                step_number=2,
                title="Identify the child's age group",
                rule_applied="42 CFR 435.118; 42 CFR 457.310(a)",
                inputs={"age": age, "age_band": band},
                computation=f"Age {age}: " + (f"ages {band}" if band else "19 or older, not a child"),
                result=f"Age group {band}" if band else "FAIL - not a child (ages 0-18 only)",
                is_determinative=band is None,
            ),
        ]
        if band is None:
            return steps
        med = src.medicaid_limit(band)
        med_dollars = src.monthly_limit(med, size)
        in_medicaid = src.within(magi, med, size)
        top = src.chip_limit_above_medicaid(band)
        steps.append(
            ReasoningStep(
                step_number=3,
                title=f"Check the Medicaid limit for ages {band}",
                rule_applied="42 CFR 435.118",
                inputs={"monthly_magi": magi, "income_limit": med_dollars, "limit_pct_fpl": med},
                computation=f"${magi:,.2f} {'<=' if in_medicaid else '>'} ${med_dollars:,.2f} ({med}% FPL)",
                result="PASS - eligible for Medicaid" if in_medicaid else "Above the Medicaid limit",
                is_determinative=False,
            )
        )
        if in_medicaid:
            return steps
        if top is None:
            steps.append(self._fail(4, "Check for CHIP coverage above Medicaid", "42 CFR 457.310",
                                    f"{self.state} has no CHIP coverage above {med}% FPL for ages {band}"))  # fmt: skip
            return steps
        steps.append(
            ReasoningStep(
                step_number=4,
                title="Check whether the child has other coverage",
                rule_applied="42 CFR 457.310(b)(2)",
                inputs={"has_other_coverage": insured},
                computation="Child has employer-sponsored coverage" if insured else "Child has no other coverage",
                result="FAIL - CHIP covers only uninsured children" if insured else "PASS - uninsured",
                is_determinative=insured,
            )
        )
        if insured:
            return steps
        top_dollars = src.monthly_limit(top, size)
        ok = src.within(magi, top, size)
        r = src.chip_funded_range(band)
        program = "Medicaid (CHIP-funded)" if r and src.within(magi, r[1], size) else "separate CHIP" if ok else "none"
        steps.append(
            ReasoningStep(
                step_number=5,
                title="Check the CHIP upper limit",
                rule_applied="42 CFR 457.310; state CHIP plan",
                inputs={"monthly_magi": magi, "income_limit": top_dollars, "limit_pct_fpl": top},
                computation=(
                    f"${magi:,.2f} {'<=' if ok else '>'} ${top_dollars:,.2f} ({top}% FPL, {self.state} upper limit)"
                ),
                result=f"PASS - eligible for {program}" if ok else "FAIL - above the upper limit",
                is_determinative=not ok,
            )
        )
        return steps

    @staticmethod
    def _fail(n: int, title: str, rule: str, computation: str) -> ReasoningStep:
        return ReasoningStep(
            step_number=n,
            title=title,
            rule_applied=rule,
            inputs={},
            computation=computation,
            result="FAIL - no CHIP coverage above Medicaid",
            is_determinative=True,
        )
