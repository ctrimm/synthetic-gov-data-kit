"""LIHEAP income-eligibility test case generator.

Each case asks whether a household is income-eligible for one LIHEAP component
(heating, cooling, crisis, or weatherization) in a modeled state. States choose
different methods within the federal frame -- Virginia uses 150% FPL for heating
but 60% of state median income for weatherization, California 60% SMI for
everything, Texas 150% FPL for everything, and Maryland a %SMI rate that rises
with household size plus categorical eligibility for SNAP/TANF/SSI/means-tested
veterans' benefits -- so the reasoning a model has to show is which threshold
applies, not only the comparison.

Under 'edge_saturated' (the default) incomes sit on and around the limit; any
other strategy samples them uniformly up to twice the limit.
"""

from __future__ import annotations

import random

from govsynth.generators.base import Generator
from govsynth.models.enums import Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.reasoning.rules_engine import build_case_id, build_short_uid, build_threshold_test_step
from govsynth.sources.us.liheap import DEFAULT_LIHEAP_FY, LIHEAPSource

_INSTRUCTION = (
    "Based on the household described above, determine whether it is income-eligible for the named LIHEAP "
    "component in its state. Identify which income threshold the state applies to that component and how it is "
    "computed (percent of the poverty guidelines or of state median income), show the comparison step by step, "
    "and cite 42 U.S.C. 8624(b)(2). State your final determination (eligible or ineligible)."
)
_OFFSETS = (-0.10, -0.02, -0.002, 0.0, 0.002, 0.02, 0.10)
_SIZES = (1, 2, 3, 4, 5, 6)
_SIZE_WEIGHTS = (0.30, 0.25, 0.18, 0.14, 0.08, 0.05)


class LIHEAPEligibilityGenerator(Generator):
    """Generates LIHEAP income-eligibility test cases for one state.

    Args:
        fiscal_year: Federal fiscal year. Default FY2026.
        state: State whose FY2026 plan is modeled (VA, CA, TX, MD).
    """

    def __init__(self, fiscal_year: int = DEFAULT_LIHEAP_FY, state: str = "VA") -> None:
        self.fiscal_year = fiscal_year
        self.state = state.upper()
        self.source = LIHEAPSource(fiscal_year=fiscal_year, state=state)

    @property
    def program(self) -> str:
        return "liheap"

    def generate(
        self,
        n: int,
        profile_strategy: str = "edge_saturated",
        seed: int | None = None,
    ) -> list[TestCase]:
        """Generate n LIHEAP cases. Exactly n are returned."""
        rng = random.Random(seed)
        cases = []
        for i in range(n):
            case_seed = rng.randint(0, 2**31) if seed is not None else None
            try:
                cases.append(self._build_case(rng, case_seed, edge=profile_strategy == "edge_saturated"))
            except Exception as exc:
                raise RuntimeError(f"LIHEAP case {i} of {n} failed to build: {exc}") from exc
        return cases

    def _income_for_recipient(self, rng: random.Random, program: str, size: int, limit: float) -> float:
        """A plausible annual income for a household receiving `program`.

        TANF, SSI and means-tested veterans' benefits have their own low income limits, so
        those households sit well under the LIHEAP limit. SNAP is the case where categorical
        eligibility matters: under Maryland's 200% FPL BBCE gross limit a SNAP household can
        have income just above the LIHEAP limit and still be eligible through SNAP alone.
        """
        fpl = self.source.annual_fpl(size)
        if program == "SNAP" and 2 * fpl > limit * 1.001:
            return round(rng.uniform(limit * 1.001, 2 * fpl), 2)
        if program == "TANF":
            return round(rng.uniform(0.10, 0.40) * fpl, 2)
        if program == "SSI":
            return round(rng.uniform(6000, 14000), 2)
        return round(rng.uniform(0.5, 1.0) * min(fpl, limit), 2)

    def _build_case(self, rng: random.Random, seed: int | None, edge: bool) -> TestCase:
        src = self.source
        component = rng.choice(src.components)
        size = rng.choices(_SIZES, weights=_SIZE_WEIGHTS)[0]
        threshold = src.threshold(component, size)
        limit = threshold.annual_limit

        categorical = bool(src.categorical_programs) and rng.random() < 0.2
        receives: tuple[str, ...] = (rng.choice(src.categorical_programs),) if categorical else ()
        if categorical:
            income = self._income_for_recipient(rng, receives[0], size, limit)
        elif edge:
            income = round(limit * (1 + rng.choice(_OFFSETS)), 2)
        else:
            income = round(rng.uniform(0.2, 2.0) * limit, 2)

        eligible, reason = src.determine(component, size, income, receives)

        profile = USHouseholdProfile.random(state=self.state, seed=seed)
        profile.household_size = size
        profile.monthly_gross_income = round(income / 12, 2)
        profile.has_dependent_children = profile.has_dependent_children and size > 1

        steps = [
            ReasoningStep(
                step_number=1,
                title=f"Identify {self.state}'s income threshold for {component}",
                rule_applied=f"42 U.S.C. 8624(b)(2); {self.state} FY{self.fiscal_year} LIHEAP plan",
                inputs={"state": self.state, "component": component, "basis": threshold.basis, "pct": threshold.pct},
                computation=threshold.explanation,
                result=f"Annual income limit for {component}, household of {size}: ${limit:,.2f}",
                is_determinative=False,
            )
        ]
        if src.categorical_programs:
            steps.append(
                ReasoningStep(
                    step_number=2,
                    title="Check categorical income eligibility",
                    rule_applied="42 U.S.C. 8624(b)(2)(A)",
                    inputs={"receives": list(receives), "conferring_programs": src.categorical_programs},
                    computation=(
                        f"Household receives {receives[0]}, one of {', '.join(src.categorical_programs)}"
                        if receives
                        else f"Household receives none of {', '.join(src.categorical_programs)}"
                    ),
                    result="PASS - categorically income-eligible" if receives else "Not categorically eligible",
                    is_determinative=bool(receives),
                )
            )
        if not receives:
            steps.append(
                build_threshold_test_step(
                    step_number=len(steps) + 1,
                    title="Compare annual gross household income with the limit",
                    rule_applied=f"{self.state} FY{self.fiscal_year} LIHEAP plan ({component})",
                    amount=income,
                    amount_key="annual_gross_income",
                    limit=limit,
                    limit_key="income_limit",
                    context_note=f"{component}, household of {size}",
                )
            )

        outcome = "eligible" if eligible else "ineligible"
        descriptor = f"{component}_categorical" if receives else f"{component}_{threshold.basis}_limit"
        case_id = build_case_id("liheap", self.state, descriptor, outcome, size, build_short_uid(rng))
        benefit_text = f" The household receives {receives[0]}." if receives else ""
        summary = (
            f"{profile.head_of_household_name} lives in {self.state} in a household of {size} with "
            f"${income:,.2f} in annual gross income and is applying for LIHEAP {component} assistance.{benefit_text}"
        )
        if receives:
            difficulty = Difficulty.ADVERSARIAL if income > limit else Difficulty.MEDIUM
        else:
            gap = abs(income - limit) / limit
            difficulty = Difficulty.HARD if gap <= 0.01 else (Difficulty.EASY if gap > 0.15 else Difficulty.MEDIUM)

        fields = profile.to_scenario_fields()
        fields["additional_context"] = {
            **fields["additional_context"],
            "liheap_component": component,
            "annual_gross_income": income,
            "receives": list(receives),
        }
        return TestCase(
            case_id=case_id,
            program=Program.LIHEAP.value,
            jurisdiction=f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=difficulty,
            scenario=ScenarioBlock(summary=summary, **fields),
            task=TaskBlock(instruction=_INSTRUCTION),
            expected_outcome=outcome,
            expected_answer=(
                f"The household is {'ELIGIBLE' if eligible else 'INELIGIBLE'} for LIHEAP {component}. {reason}."
            ),
            rationale_trace=RationaleTrace(
                steps=steps,
                conclusion=f"{outcome.upper()}. {reason}.",
                policy_basis=[
                    PolicyCitation(
                        document="42 U.S.C. 8624",
                        section="42 U.S.C. 8624(b)(2)",
                        year=self.fiscal_year,
                        url=src.raw["states"][self.state]["plan_url"],
                    )
                ],
            ),
            variation_tags=[descriptor, threshold.basis],
            source_citations=[
                "42 U.S.C. 8624(b)(2)",
                "HHS LIHEAP IM2025-02 (State Median Income, mandatory FY2026)",
                f"{self.state} FY{self.fiscal_year} LIHEAP Detailed Model Plan",
            ],
            seed=seed,
            metadata={
                "generator": "LIHEAPEligibilityGenerator",
                "state": self.state,
                "fiscal_year": self.fiscal_year,
                "component": component,
                "threshold_basis": threshold.basis,
            },
        )
