"""Medicare Savings Program and Extra Help test case generator.

Two case types, both for Medicare beneficiaries:

- ``msp_tier``: which Medicare Savings Program, if any, the beneficiary qualifies
  for -- QMB (<=100% FPL), SLMB (<=120%), or QI (<=135%) -- after the $20 general
  income disregard, subject to the MSP resource limit.
- ``extra_help``: whether the beneficiary qualifies for Extra Help (Part D
  low-income subsidy, <=150% FPL and the Extra Help resource limit).

Under 'edge_saturated' (the default) incomes and resources are placed on and
around each limit, where tier boundaries are easiest to get wrong. Any other
strategy samples them uniformly over a plausible range.
"""

from __future__ import annotations

import random

from govsynth.generators.base import Generator
from govsynth.models.enums import Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.reasoning.rules_engine import build_case_id, build_short_uid, build_threshold_test_step
from govsynth.sources.us.medicare import DEFAULT_MEDICARE_CY, MedicareSource

_MSP_INSTRUCTION = (
    "Based on the situation described above, determine whether this Medicare beneficiary qualifies for a "
    "Medicare Savings Program and, if so, which one (QMB, SLMB, or QI). Show your reasoning step by step, "
    "citing the federal rules (42 U.S.C. 1396d(p), 1396a(a)(10)(E)). Use the federal limits; do not assume "
    "state expansions. State your final determination (eligible or ineligible) and the program."
)
_LIS_INSTRUCTION = (
    "Based on the situation described above, determine whether this Medicare beneficiary qualifies for "
    "Extra Help (the Part D prescription drug low-income subsidy). Show your reasoning step by step, citing "
    "42 CFR 423.773. State your final determination (eligible or ineligible)."
)
_OFFSETS = (-0.10, -0.02, -0.005, 0.0, 0.005, 0.02, 0.10)


class MedicareSavingsGenerator(Generator):
    """Generates Medicare Savings Program (QMB/SLMB/QI) and Extra Help test cases.

    Args:
        calendar_year: Calendar year of the limits. Default 2026.
        state: Two-letter state code or 'national'. Only AK and HI change the limits.
    """

    def __init__(self, calendar_year: int = DEFAULT_MEDICARE_CY, state: str = "national") -> None:
        self.calendar_year = calendar_year
        self.state = state.upper() if state != "national" else "national"
        self.source = MedicareSource(calendar_year=calendar_year, state=state)

    @property
    def program(self) -> str:
        return "medicare"

    def generate(
        self,
        n: int,
        profile_strategy: str = "edge_saturated",
        seed: int | None = None,
    ) -> list[TestCase]:
        """Generate n cases, alternating MSP-tier and Extra Help determinations."""
        rng = random.Random(seed)
        cases = []
        for i in range(n):
            case_seed = rng.randint(0, 2**31) if seed is not None else None
            if i % 2 == 0:
                cases.append(self._msp_case(rng, case_seed, profile_strategy == "edge_saturated"))
            else:
                cases.append(self._extra_help_case(rng, case_seed, profile_strategy == "edge_saturated"))
        return cases

    # ------------------------------------------------------------------

    def _beneficiary(self, rng: random.Random, seed: int | None, couple: bool) -> tuple[USHouseholdProfile, str]:
        """A Medicare beneficiary profile and a sentence on how they are entitled."""
        aged = rng.random() < 0.8
        age = rng.randint(65, 92) if aged else rng.randint(30, 64)
        profile = USHouseholdProfile.random(state="VA" if self.state == "national" else self.state, seed=seed)
        profile.household_size = 2 if couple else 1
        profile.age_of_head = age
        profile.has_elderly_or_disabled = True
        profile.has_dependent_children = False
        entitlement = (
            f"is {age} and enrolled in Medicare Part A"
            if aged
            else (
                f"is {age}, has received Social Security disability benefits for over 24 months, "
                "and is enrolled in Medicare Part A"
            )
        )
        return profile, entitlement

    def _place(self, rng: random.Random, limit: float, edge: bool, low: float, high: float) -> float:
        if edge:
            return round(max(0.0, limit * (1 + rng.choice(_OFFSETS))), 2)
        return round(rng.uniform(low, high), 2)

    @staticmethod
    def _difficulty(amount: float, limits: list[float]) -> Difficulty:
        gap = min(abs(amount - lim) / lim for lim in limits if lim)
        if gap <= 0.01:
            return Difficulty.HARD
        return Difficulty.EASY if gap > 0.15 else Difficulty.MEDIUM

    def _entitlement_step(self, name: str, entitlement: str) -> ReasoningStep:
        return ReasoningStep(
            step_number=1,
            title="Confirm Medicare entitlement",
            rule_applied="42 U.S.C. 1396d(p)(1)(A)",
            inputs={"entitled_to_part_a": True},
            computation=f"{name} {entitlement}.",
            result="Entitled to Medicare Part A",
            is_determinative=False,
        )

    def _countable_step(self, gross: float, couple: bool) -> ReasoningStep:
        disregard = self.source.income_disregard
        countable = max(0.0, gross - disregard)
        return ReasoningStep(
            step_number=2,
            title="Compute countable income",
            rule_applied="42 U.S.C. 1396d(p)(2)(D) (SSI income methodology; 20 CFR 416.1124(c)(12))",
            inputs={"gross_monthly_income": gross, "general_disregard": disregard},
            computation=f"${gross:,.2f} - ${disregard:,.0f} general income disregard = ${countable:,.2f}",
            result=f"Countable income: ${countable:,.2f}/month ({'couple' if couple else 'individual'})",
            is_determinative=False,
        )

    def _msp_case(self, rng: random.Random, seed: int | None, edge: bool) -> TestCase:
        couple = rng.random() < 0.3
        src = self.source
        profile, entitlement = self._beneficiary(rng, seed, couple)
        boundary = rng.choice(list(src.tiers()))
        countable_limit = src.msp_countable_limit(boundary.tier, couple)
        countable = self._place(rng, countable_limit, edge, 400, 2600)
        gross = round(countable + src.income_disregard, 2)
        res_limit = src.msp_resource_limit(couple)
        resources = (
            self._place(rng, res_limit, True, 0, 0)
            if rng.random() < 0.25
            else round(rng.uniform(0, res_limit * 0.9), -1)
        )
        profile.monthly_gross_income = gross
        profile.earned_income = 0.0
        profile.unearned_income = gross
        profile.liquid_assets = resources

        tier, reason = src.msp_tier(gross, resources, couple)
        steps = [
            self._entitlement_step(profile.head_of_household_name, entitlement),
            self._countable_step(gross, couple),
        ]
        res_step = build_threshold_test_step(
            step_number=3,
            title="Check the MSP resource limit",
            rule_applied="42 U.S.C. 1396d(p)(1)(C)",
            amount=resources,
            amount_key="resources",
            limit=res_limit,
            limit_key="resource_limit",
            context_note=f"{'couple' if couple else 'individual'}, CY{self.calendar_year}",
        )
        steps.append(res_step)
        if res_step.result == "PASS":
            tiers = src.tiers()
            for k, t in enumerate(tiers):
                cap = src.msp_countable_limit(t.tier, couple)
                passed = countable <= cap
                last = k == len(tiers) - 1
                steps.append(
                    ReasoningStep(
                        step_number=len(steps) + 1,
                        title=f"Check {t.tier.upper()} income limit ({t.max_pct_fpl}% FPL)",
                        rule_applied=f"42 U.S.C. 1396d(p) / 1396a(a)(10)(E) ({t.name})",
                        inputs={"countable_income": countable, "income_limit": cap},
                        computation=(
                            f"${countable:,.2f} {'<=' if passed else '>'} ${cap:,.0f} "
                            f"({t.max_pct_fpl}% FPL, {'couple' if couple else 'individual'}; "
                            f"${cap + src.income_disregard:,.0f} gross with the $20 disregard)"
                        ),
                        result=f"PASS - qualifies for {t.tier.upper()}" if passed else "FAIL",
                        is_determinative=(not passed and last),
                        note=None if passed or last else "Above this tier; check the next tier.",
                    )
                )
                if passed:
                    break

        outcome = "eligible" if tier else "ineligible"
        descriptor = f"msp_{tier}" if tier else "msp_none"
        case_id = build_case_id(
            "medicare", self._jurisdiction_code, descriptor, outcome, 2 if couple else 1, build_short_uid(rng)
        )
        limits = [src.msp_countable_limit(t.tier, couple) for t in src.tiers()] + [res_limit]
        who = "a married couple" if couple else "single"
        summary = (
            f"{profile.head_of_household_name} {entitlement}. They are {who}, with "
            f"${gross:,.2f}/month in Social Security and pension income and ${resources:,.2f} in countable resources."
        )
        answer = (
            f"This beneficiary is {'ELIGIBLE' if tier else 'INELIGIBLE'} for a Medicare Savings Program"
            f"{f' ({tier.upper()})' if tier else ''}. {reason}."
        )
        return self._case(
            case_id, profile, summary, _MSP_INSTRUCTION, outcome, answer, steps, reason,
            self._difficulty(countable if res_step.result == "PASS" else resources, limits),
            {"case_type": "msp_tier", "msp_tier": tier, "couple": couple},
            [descriptor, "medicare_savings_program"],
            "42 U.S.C. 1396d(p)",
        )  # fmt: skip

    def _extra_help_case(self, rng: random.Random, seed: int | None, edge: bool) -> TestCase:
        couple = rng.random() < 0.3
        hh_size = 2 if couple else 1
        src = self.source
        profile, entitlement = self._beneficiary(rng, seed, couple)
        annual_limit = src.extra_help_annual_limit(hh_size)
        countable = self._place(rng, annual_limit / 12, edge, 600, 3200)
        gross = round(countable + src.income_disregard, 2)
        annual = round((gross - src.income_disregard) * 12, 2)
        res_limit = src.extra_help_resource_limit(couple)
        resources = (
            self._place(rng, res_limit, True, 0, 0)
            if rng.random() < 0.25
            else round(rng.uniform(0, res_limit * 0.9), -1)
        )
        profile.monthly_gross_income = gross
        profile.earned_income = 0.0
        profile.unearned_income = gross
        profile.liquid_assets = resources

        eligible, reason = src.extra_help_eligible(gross, resources, couple, hh_size)
        steps = [
            self._entitlement_step(profile.head_of_household_name, entitlement),
            self._countable_step(gross, couple),
        ]
        income_step = build_threshold_test_step(
            step_number=3,
            title="Check annual income against 150% FPL",
            rule_applied="42 CFR 423.773(b)(1)",
            amount=annual,
            amount_key="annual_countable_income",
            limit=annual_limit,
            limit_key="income_limit",
            context_note=f"150% FPL, household of {hh_size}, CY{self.calendar_year}",
        )
        steps.append(income_step)
        if income_step.result == "PASS":
            steps.append(
                build_threshold_test_step(
                    step_number=4,
                    title="Check the Extra Help resource limit",
                    rule_applied="42 CFR 423.773(b)(2)",
                    amount=resources,
                    amount_key="resources",
                    limit=res_limit,
                    limit_key="resource_limit",
                    context_note=f"{'couple' if couple else 'individual'}, includes burial allowance",
                )
            )
        outcome = "eligible" if eligible else "ineligible"
        case_id = build_case_id(
            "medicare", self._jurisdiction_code, "extra_help", outcome, hh_size, build_short_uid(rng)
        )
        who = "a married couple" if couple else "single"
        summary = (
            f"{profile.head_of_household_name} {entitlement}. They are {who}, with ${gross:,.2f}/month in "
            f"Social Security and pension income and ${resources:,.2f} in countable resources."
        )
        answer = f"This beneficiary is {'ELIGIBLE' if eligible else 'INELIGIBLE'} for Extra Help. {reason}."
        return self._case(
            case_id, profile, summary, _LIS_INSTRUCTION, outcome, answer, steps, reason,
            self._difficulty(annual, [annual_limit])
            if income_step.result == "FAIL" or resources <= res_limit
            else self._difficulty(resources, [res_limit]),
            {"case_type": "extra_help", "couple": couple},
            ["extra_help", "part_d_lis"],
            "42 CFR 423.773",
        )  # fmt: skip

    @property
    def _jurisdiction_code(self) -> str:
        return "national" if self.state == "national" else self.state.lower()

    def _case(
        self,
        case_id: str,
        profile: USHouseholdProfile,
        summary: str,
        instruction: str,
        outcome: str,
        answer: str,
        steps: list[ReasoningStep],
        reason: str,
        difficulty: Difficulty,
        context: dict[str, object],
        tags: list[str],
        primary_rule: str,
    ) -> TestCase:
        fields = profile.to_scenario_fields()
        fields["additional_context"] = {**fields["additional_context"], **context}
        return TestCase(
            case_id=case_id,
            program=Program.MEDICARE.value,
            jurisdiction="us" if self.state == "national" else f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=difficulty,
            scenario=ScenarioBlock(summary=summary, **fields),
            task=TaskBlock(instruction=instruction),
            expected_outcome=outcome,
            expected_answer=answer,
            rationale_trace=RationaleTrace(
                steps=steps,
                conclusion=f"{outcome.upper()}. {reason}.",
                policy_basis=[
                    PolicyCitation(
                        document=primary_rule,
                        section=primary_rule,
                        year=self.calendar_year,
                        url="https://www.medicare.gov/basics/costs/help/medicare-savings-programs",
                    )
                ],
            ),
            variation_tags=tags,
            source_citations=[primary_rule, f"Medicare.gov Medicare Savings Programs, CY{self.calendar_year} limits"],
            seed=None,
            metadata={
                "generator": "MedicareSavingsGenerator",
                "state": self.state,
                "calendar_year": self.calendar_year,
                **context,
            },
        )
