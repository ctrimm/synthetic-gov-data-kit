"""SSI (Supplemental Security Income) eligibility test case generator.

Each case walks the federal SSI determination in order (20 CFR Part 416):
category (aged, blind, or disabled) -> substantial gainful activity for non-blind
disabled applicants with earnings -> resources -> countable income after the $20
general and $65 + 1/2 earned income exclusions -> payment = FBR - countable income.

Case mix under 'edge_saturated' (the default): incomes back-solved so countable
income lands on and around the federal benefit rate (including exactly at it,
where no payment is due), resources around the limit, earnings around SGA for
disabled applicants, and applicants who are not aged, blind or disabled. Any other
strategy samples incomes and resources uniformly.
"""

from __future__ import annotations

import random

from govsynth.generators.base import Generator
from govsynth.models.enums import Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.reasoning.rules_engine import build_case_id, build_short_uid, build_threshold_test_step
from govsynth.sources.us.ssi import DEFAULT_SSI_CY, SSISource

_INSTRUCTION = (
    "Based on the situation described above, determine whether the applicant is eligible for federal "
    "Supplemental Security Income (SSI) and, if so, the monthly federal payment. Show your reasoning step "
    "by step, citing 20 CFR Part 416. Ignore state supplementary payments. State your final determination "
    "(eligible or ineligible)."
)
_KINDS = ("income", "resources", "sga", "not_categorical")
_KIND_WEIGHTS = (0.6, 0.15, 0.15, 0.10)
_INCOME_OFFSETS = (-0.10, -0.02, -0.002, 0.0, 0.002, 0.02, 0.10)


class SSIEligibilityGenerator(Generator):
    """Generates federal SSI eligibility and payment test cases.

    Args:
        calendar_year: Calendar year of the federal benefit rate. Default 2026.
        state: Two-letter state code or 'national' (federal rules are uniform).
    """

    def __init__(self, calendar_year: int = DEFAULT_SSI_CY, state: str = "national") -> None:
        self.calendar_year = calendar_year
        self.state = state.upper() if state != "national" else "national"
        self.source = SSISource(calendar_year=calendar_year, state=state)

    @property
    def program(self) -> str:
        return "ssi"

    def generate(
        self,
        n: int,
        profile_strategy: str = "edge_saturated",
        seed: int | None = None,
    ) -> list[TestCase]:
        """Generate n SSI cases."""
        rng = random.Random(seed)
        cases = []
        for _ in range(n):
            case_seed = rng.randint(0, 2**31) if seed is not None else None
            kind = rng.choices(_KINDS, weights=_KIND_WEIGHTS)[0]
            cases.append(self._build_case(rng, case_seed, kind, edge=profile_strategy == "edge_saturated"))
        return cases

    # ------------------------------------------------------------------

    def _applicant(self, rng: random.Random, kind: str) -> tuple[str | None, bool, int]:
        """(category, blind, age)."""
        if kind == "not_categorical":
            return None, False, rng.randint(22, 59)
        if kind == "sga":
            return "disabled", False, rng.randint(22, 64)
        category = rng.choices(("aged", "blind", "disabled"), weights=(0.4, 0.1, 0.5))[0]
        age = rng.randint(65, 92) if category == "aged" else rng.randint(19, 64)
        return category, category == "blind", age

    def _income(self, rng: random.Random, kind: str, couple: bool, edge: bool) -> tuple[float, float]:
        """(unearned, earned) monthly income for the case kind."""
        src = self.source
        fbr = src.fbr(couple)
        if kind == "sga":
            return 0.0, round(src.sga_nonblind * (1 + rng.choice((-0.03, -0.001, 0.0, 0.001, 0.03))), 2)
        if kind != "income" or not edge:
            unearned = round(rng.uniform(0, fbr * 0.8), 2)
            earned = round(rng.uniform(0, 600), 2) if rng.random() < 0.3 else 0.0
            return unearned, earned
        # Back-solve gross income so countable income lands at FBR x (1 + offset).
        target = round(fbr * (1 + rng.choice(_INCOME_OFFSETS)), 2)
        mix = rng.choice(("unearned", "earned", "both"))
        if mix == "unearned":
            return round(target + 20, 2), 0.0
        if mix == "earned":
            return 0.0, round(2 * target + 85, 2)
        unearned = round(rng.uniform(100, target * 0.7), 2)
        return unearned, round(2 * (target - (unearned - 20)) + 65, 2)

    def _build_case(self, rng: random.Random, seed: int | None, kind: str, edge: bool) -> TestCase:
        src = self.source
        couple = kind in ("income", "resources") and rng.random() < 0.25
        category, blind, age = self._applicant(rng, kind)
        unearned, earned = self._income(rng, kind, couple, edge)
        res_limit = src.resource_limit(couple)
        if kind == "resources":
            resources = round(res_limit * (1 + rng.choice((-0.05, -0.001, 0.0, 0.001, 0.05, 0.25))), 2)
        else:
            resources = round(rng.uniform(0, res_limit * 0.9), 2)

        profile = USHouseholdProfile.random(state="VA" if self.state == "national" else self.state, seed=seed)
        profile.household_size = 2 if couple else 1
        profile.age_of_head = age
        profile.has_elderly_or_disabled = category is not None or age >= 60
        profile.has_dependent_children = False
        profile.monthly_gross_income = round(unearned + earned, 2)
        profile.earned_income = earned
        profile.unearned_income = unearned
        profile.liquid_assets = resources

        eligible, payment, reason = src.determine(category, unearned, earned, resources, couple, blind=blind)
        steps = self._steps(category, blind, age, unearned, earned, resources, couple)
        outcome = "eligible" if eligible else "ineligible"
        descriptor = {
            "income": "countable_income_vs_fbr",
            "resources": "resource_limit",
            "sga": "substantial_gainful_activity",
            "not_categorical": "not_aged_blind_disabled",
        }[kind]
        jurisdiction = "national" if self.state == "national" else self.state.lower()
        case_id = build_case_id("ssi", jurisdiction, descriptor, outcome, 2 if couple else 1, build_short_uid(rng))

        who = {
            "aged": f"is {age} years old",
            "blind": f"is {age} and legally blind",
            "disabled": f"is {age} and has a medically determinable impairment expected to last at least 12 months",
            None: f"is {age} and has no disability",
        }[category]
        parts = []
        if unearned:
            parts.append(f"${unearned:,.2f}/month in unearned income (Social Security)")
        if earned:
            parts.append(f"${earned:,.2f}/month in gross wages")
        income_text = " and ".join(parts) if parts else "no income"
        spouse = " Their spouse is also aged, blind, or disabled and applying with them." if couple else ""
        summary = (
            f"{profile.head_of_household_name} {who} and is applying for SSI.{spouse} "
            f"They have {income_text}, and ${resources:,.2f} in countable resources."
        )
        fbr = src.fbr(couple)
        answer = (
            f"The applicant is ELIGIBLE for SSI with a federal payment of ${payment:,.2f}/month. {reason}."
            if eligible
            else f"The applicant is INELIGIBLE for SSI. {reason}."
        )
        countable = src.countable_income(unearned, earned).countable
        if kind == "not_categorical":
            difficulty = Difficulty.EASY
        elif kind == "sga":
            difficulty = Difficulty.ADVERSARIAL
        else:
            amount, limit = (resources, res_limit) if kind == "resources" else (countable, fbr)
            gap = abs(amount - limit) / limit
            difficulty = Difficulty.HARD if gap <= 0.01 else (Difficulty.EASY if gap > 0.15 else Difficulty.MEDIUM)

        fields = profile.to_scenario_fields()
        fields["additional_context"] = {
            **fields["additional_context"],
            "ssi_category": category,
            "blind": blind,
            "couple": couple,
            "monthly_federal_payment": payment if eligible else None,
        }
        return TestCase(
            case_id=case_id,
            program=Program.SSI.value,
            jurisdiction="us" if self.state == "national" else f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=difficulty,
            scenario=ScenarioBlock(summary=summary, **fields),
            task=TaskBlock(instruction=_INSTRUCTION),
            expected_outcome=outcome,
            expected_answer=answer,
            rationale_trace=RationaleTrace(
                steps=steps,
                conclusion=f"{outcome.upper()}. {reason}.",
                policy_basis=[
                    PolicyCitation(
                        document="20 CFR Part 416",
                        section="20 CFR 416.202, 416.1100-416.1124, 416.1205",
                        year=self.calendar_year,
                        url="https://www.ecfr.gov/current/title-20/chapter-III/part-416",
                    )
                ],
            ),
            variation_tags=[descriptor, "couple" if couple else "individual"],
            source_citations=[
                "20 CFR Part 416",
                f"SSA Cost-of-Living Increase and Other Determinations for {self.calendar_year} (90 FR 49047)",
            ],
            seed=seed,
            metadata={
                "generator": "SSIEligibilityGenerator",
                "state": self.state,
                "calendar_year": self.calendar_year,
                "case_type": kind,
            },
        )

    def _steps(
        self,
        category: str | None,
        blind: bool,
        age: int,
        unearned: float,
        earned: float,
        resources: float,
        couple: bool,
    ) -> list[ReasoningStep]:
        """Reasoning steps in the order SSISource.determine applies them; stops at the first failure."""
        src = self.source
        steps = [
            ReasoningStep(
                step_number=1,
                title="Identify the applicant's circumstances",
                rule_applied="20 CFR 416.200",
                inputs={
                    "age": age,
                    "monthly_unearned_income": unearned,
                    "monthly_earned_income": earned,
                    "resources": resources,
                    "couple": couple,
                },
                computation=(
                    f"Age {age}; unearned ${unearned:,.2f}/month; earned ${earned:,.2f}/month; "
                    f"resources ${resources:,.2f}; {'eligible couple' if couple else 'individual'}"
                ),
                result="Facts recorded",
                is_determinative=False,
            ),
            ReasoningStep(
                step_number=2,
                title="Check categorical eligibility (aged, blind, or disabled)",
                rule_applied="20 CFR 416.202(a)",
                inputs={"age": age, "category": category},
                computation=(
                    f"Applicant is {category}" + (f" (age {age} >= 65)" if category == "aged" else "")
                    if category
                    else f"Applicant is {age} (under 65), not blind, and not disabled"
                ),
                result="PASS" if category else "FAIL - not aged, blind, or disabled",
                is_determinative=category is None,
            ),
        ]
        if category is None:
            return steps
        if category == "disabled" and not blind and earned > 0:
            sga = src.sga_nonblind
            ok = earned <= sga
            steps.append(
                ReasoningStep(
                    step_number=len(steps) + 1,
                    title="Check substantial gainful activity (non-blind disability)",
                    rule_applied="20 CFR 416.920(b), 416.974",
                    inputs={"monthly_earnings": earned, "sga_limit": sga},
                    computation=(
                        f"${earned:,.2f} {'<=' if ok else '>'} ${sga:,.0f} (SGA, non-blind, {self.calendar_year})"
                    ),
                    result="PASS" if ok else "FAIL - working at SGA, so not disabled",
                    is_determinative=not ok,
                )
            )
            if not ok:
                return steps
        res_step = build_threshold_test_step(
            step_number=len(steps) + 1,
            title="Check the resource limit",
            rule_applied="20 CFR 416.1205",
            amount=resources,
            amount_key="resources",
            limit=src.resource_limit(couple),
            limit_key="resource_limit",
            context_note="couple" if couple else "individual",
        )
        steps.append(res_step)
        if res_step.result == "FAIL":
            return steps
        inc = src.countable_income(unearned, earned)
        steps.append(
            ReasoningStep(
                step_number=len(steps) + 1,
                title="Apply the $20 general income exclusion to unearned income",
                rule_applied="20 CFR 416.1124(c)(12)",
                inputs={"unearned_income": unearned, "general_exclusion_used": inc.general_exclusion_on_unearned},
                computation=(
                    f"${unearned:,.2f} - ${inc.general_exclusion_on_unearned:,.2f} = ${inc.countable_unearned:,.2f}"
                ),
                result=f"Countable unearned income: ${inc.countable_unearned:,.2f}",
                is_determinative=False,
            )
        )
        if earned:
            steps.append(
                ReasoningStep(
                    step_number=len(steps) + 1,
                    title="Apply earned income exclusions ($20 remainder, $65, one-half)",
                    rule_applied="20 CFR 416.1112(c)(4), (c)(5), (c)(7)",
                    inputs={"earned_income": earned, "general_exclusion_remaining": inc.general_exclusion_on_earned},
                    computation=(
                        f"(${earned:,.2f} - ${inc.general_exclusion_on_earned:,.2f} - $65) / 2 = "
                        f"${inc.earned_after_65:,.2f} / 2 = ${inc.countable_earned:,.2f}"
                    ),
                    result=f"Countable earned income: ${inc.countable_earned:,.2f}",
                    is_determinative=False,
                )
            )
        fbr = src.fbr(couple)
        ok = inc.countable < fbr
        steps.append(
            ReasoningStep(
                step_number=len(steps) + 1,
                title="Compare countable income with the federal benefit rate",
                rule_applied="20 CFR 416.1100, 416.410, 416.420",
                inputs={"countable_income": inc.countable, "federal_benefit_rate": fbr},
                computation=(
                    f"${inc.countable_unearned:,.2f} + ${inc.countable_earned:,.2f} = ${inc.countable:,.2f} "
                    f"{'<' if ok else '>='} ${fbr:,.0f} "
                    f"({'couple' if couple else 'individual'} FBR, {self.calendar_year})"
                ),
                result=(
                    f"PASS - payment ${fbr - inc.countable:,.2f}/month"
                    if ok
                    else "FAIL - countable income is not less than the FBR, so no payment is due"
                ),
                is_determinative=not ok,
            )
        )
        return steps
