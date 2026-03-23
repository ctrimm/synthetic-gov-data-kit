"""SNAP eligibility test case generator.

Generates CivBench-compatible TestCase objects for SNAP eligibility determination,
including full rationale traces grounded in 7 CFR Part 273.
"""

from __future__ import annotations

import random
import uuid
from typing import Any

from govsynth.fiscal_year import DEFAULT_SNAP_FY
from govsynth.models.enums import Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.sources.us.snap import SNAPSource, BBCE_STATES, get_standard_deduction


# Threshold types used in edge-saturated generation
_SNAP_THRESHOLD_TYPES = [
    "gross_income_limit",
    "net_income_limit",
    "asset_limit_general",
    "asset_limit_elderly_disabled",
]

# Offset values: at limit, just above, just below
_OFFSETS = [0.0, 0.01, -0.01, 0.05, -0.05]

_TASK_INSTRUCTION = (
    "Based on the household's situation described above, determine whether this household "
    "is eligible for SNAP (Supplemental Nutrition Assistance Program) benefits. "
    "Show your reasoning step by step, citing the specific federal regulations that apply. "
    "State your final determination (eligible or ineligible) and, if eligible, estimate "
    "the approximate monthly benefit amount."
)


class SNAPEligibilityGenerator:
    """Generates SNAP eligibility determination test cases.

    Each case includes:
      - A synthetic household scenario
      - The eligibility determination task
      - The expected outcome and answer
      - A full rationale trace (7 CFR Part 273)

    Args:
        fiscal_year: Federal fiscal year for thresholds. Default: FY2026.
        state: State code. Controls BBCE asset test rules.
        include_reasoning_trace: Always True for CivBench compatibility.
        difficulty_distribution: Fraction of cases at each difficulty level.
    """

    def __init__(
        self,
        fiscal_year: int = DEFAULT_SNAP_FY,
        state: str = "VA",
        difficulty_distribution: dict[str, float] | None = None,
    ) -> None:
        self.fiscal_year = fiscal_year
        self.state = state.upper()
        self.source = SNAPSource(fiscal_year=fiscal_year, state=state)
        self.difficulty_distribution = difficulty_distribution or {
            "easy": 0.15,
            "medium": 0.30,
            "hard": 0.40,
            "adversarial": 0.15,
        }

    def generate(
        self,
        n: int,
        profile_strategy: str = "edge_saturated",
        seed: int | None = None,
    ) -> list[TestCase]:
        """Generate n SNAP eligibility test cases.

        Args:
            n: Number of cases to generate.
            profile_strategy: 'edge_saturated' | 'uniform' | 'realistic'
            seed: RNG seed for reproducibility.

        Returns:
            List of TestCase objects.
        """
        rng = random.Random(seed)
        cases: list[TestCase] = []

        for i in range(n):
            case_seed = rng.randint(0, 2**31) if seed is not None else None

            if profile_strategy == "edge_saturated":
                profile = self._sample_edge_profile(rng, case_seed)
            else:
                profile = USHouseholdProfile.random(
                    state=self.state, seed=case_seed, strategy=profile_strategy
                )

            try:
                case = self._build_case(profile, case_seed, i)
                cases.append(case)
            except Exception as exc:
                # Log and continue — don't let one bad profile abort the batch
                print(f"  Warning: skipped case {i} due to error: {exc}")

        return cases

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sample_edge_profile(
        self, rng: random.Random, seed: int | None
    ) -> USHouseholdProfile:
        """Sample a profile using edge-saturated strategy."""
        hh_size = rng.choices([1, 2, 3, 4, 5, 6], weights=[0.15, 0.25, 0.25, 0.20, 0.10, 0.05])[0]
        threshold = rng.choice(_SNAP_THRESHOLD_TYPES)
        offset = rng.choice(_OFFSETS)

        return USHouseholdProfile.at_threshold(
            program="snap",
            threshold=threshold,
            state=self.state,
            household_size=hh_size,
            fiscal_year=self.fiscal_year,
            offset_pct=offset,
            seed=seed,
        )

    def _build_case(
        self, profile: USHouseholdProfile, seed: int | None, index: int
    ) -> TestCase:
        """Build a complete TestCase from a profile."""
        t = self.source.thresholds()
        fy_config = self.source.fy_config
        limits = t.by_household_size(min(profile.household_size, 8))

        # Compute net income if not already set
        net_income = profile.monthly_net_income
        if net_income is None:
            net_income = self.source.calculate_net_income(
                gross_income=profile.monthly_gross_income,
                household_size=profile.household_size,
                earned_income=profile.earned_income,
                shelter_costs=profile.shelter_costs,
                has_elderly_or_disabled=profile.has_elderly_or_disabled,
            )
            profile.monthly_net_income = round(net_income, 2)

        # Determine eligibility
        is_eligible, reason = self.source.is_eligible(
            household_size=profile.household_size,
            gross_income=profile.monthly_gross_income,
            net_income=net_income,
            liquid_assets=profile.liquid_assets,
            has_elderly_or_disabled=profile.has_elderly_or_disabled,
        )

        # Build rationale trace
        trace = self._build_rationale_trace(profile, net_income, limits, is_eligible, fy_config)

        # Determine difficulty
        difficulty = self._classify_difficulty(profile, is_eligible)

        # Generate unique ID
        civbench_id = self._make_civbench_id(profile, is_eligible, index)

        # Build scenario summary
        scenario_summary = profile.natural_language_summary("snap")

        # Build expected answer
        expected_answer = self._build_expected_answer(
            profile, net_income, limits, is_eligible, reason, fy_config
        )

        return TestCase(
            civbench_id=civbench_id,
            program=Program.SNAP.value,
            jurisdiction=f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=difficulty,
            scenario=ScenarioBlock(
                summary=scenario_summary,
                **{k: v for k, v in profile.to_scenario_fields().items()},
            ),
            task=TaskBlock(instruction=_TASK_INSTRUCTION),
            expected_outcome="eligible" if is_eligible else "ineligible",
            expected_answer=expected_answer,
            rationale_trace=trace,
            variation_tags=self._build_variation_tags(profile),
            source_citations=[
                "7 CFR Part 273 (2025)",
                f"USDA FNS SNAP Income and Resource Limits {fy_config.period_label}",
            ],
            seed=seed,
            metadata={
                "generator": "SNAPEligibilityGenerator",
                "profile_strategy": profile.extra.get("threshold_type", "random"),
                "state": self.state,
                "fiscal_year": self.fiscal_year,
            },
        )

    def _build_rationale_trace(
        self,
        profile: USHouseholdProfile,
        net_income: float,
        limits: Any,
        is_eligible: bool,
        fy_config: Any,
    ) -> RationaleTrace:
        """Construct the step-by-step reasoning chain for SNAP eligibility."""
        steps: list[ReasoningStep] = []
        std_ded = get_standard_deduction(profile.household_size)
        t = self.source.thresholds()
        bbce = self.state in BBCE_STATES

        step_n = 1

        # Step 1: Gross income test (skip for elderly/disabled)
        if not profile.has_elderly_or_disabled:
            gross_pass = profile.monthly_gross_income <= limits.gross_monthly
            steps.append(ReasoningStep(
                step_number=step_n,
                title="Check gross income limit",
                rule_applied="7 CFR 273.9(a)(1)",
                inputs={
                    "household_size": profile.household_size,
                    "gross_income": profile.monthly_gross_income,
                    "gross_limit": limits.gross_monthly,
                    "pct_fpl": "130%",
                    "period": fy_config.period_label,
                },
                computation=(
                    f"${profile.monthly_gross_income:,.2f} "
                    f"{'<=' if gross_pass else '>'} "
                    f"${limits.gross_monthly:,.2f} "
                    f"(130% FPL for {profile.household_size}-person HH, {fy_config.period_label})"
                ),
                result="PASS" if gross_pass else "FAIL — exceeds gross income limit",
                is_determinative=not gross_pass,
                note="Elderly/disabled households are exempt from the gross income test (7 CFR 273.9(a)(1))."
                     if profile.has_elderly_or_disabled else None,
            ))
            step_n += 1
            if not gross_pass:
                return RationaleTrace(
                    steps=steps,
                    conclusion=f"INELIGIBLE. Gross income ${profile.monthly_gross_income:,.2f} exceeds "
                               f"the ${limits.gross_monthly:,.2f} limit (130% FPL, {fy_config.period_label}).",
                    policy_basis=[PolicyCitation(
                        document="7 CFR Part 273",
                        section="7 CFR 273.9(a)(1)",
                        year=self.fiscal_year,
                        url="https://www.ecfr.gov/current/title-7/part-273",
                    )],
                )
        else:
            steps.append(ReasoningStep(
                step_number=step_n,
                title="Gross income test — waived for elderly/disabled household",
                rule_applied="7 CFR 273.9(a)(1)",
                inputs={"has_elderly_or_disabled": True},
                computation="Household contains elderly (60+) or disabled member — gross income test is waived.",
                result="WAIVED",
                is_determinative=False,
            ))
            step_n += 1

        # Step 2: Earned income deduction
        earned = profile.earned_income or profile.monthly_gross_income
        earned_ded = earned * (t.earned_income_deduction_pct or 20) / 100
        after_earned = profile.monthly_gross_income - earned_ded
        steps.append(ReasoningStep(
            step_number=step_n,
            title="Apply earned income deduction (20%)",
            rule_applied="7 CFR 273.9(c)(1)",
            inputs={"earned_income": earned, "deduction_rate": "20%"},
            computation=f"${earned:,.2f} × 20% = ${earned_ded:,.2f} deduction → ${after_earned:,.2f}",
            result=f"Income after earned deduction: ${after_earned:,.2f}",
            is_determinative=False,
        ))
        step_n += 1

        # Step 3: Standard deduction
        after_standard = after_earned - std_ded
        steps.append(ReasoningStep(
            step_number=step_n,
            title="Apply standard deduction",
            rule_applied="7 CFR 273.9(c)(2)",
            inputs={"household_size": profile.household_size, "standard_deduction": std_ded},
            computation=f"${after_earned:,.2f} − ${std_ded:,.0f} = ${after_standard:,.2f}",
            result=f"Income after standard deduction: ${after_standard:,.2f}",
            is_determinative=False,
        ))
        step_n += 1

        # Step 4: Net income test
        net_pass = net_income <= limits.net_monthly
        steps.append(ReasoningStep(
            step_number=step_n,
            title="Check net income limit",
            rule_applied="7 CFR 273.9(a)(2)",
            inputs={
                "net_income": round(net_income, 2),
                "net_limit": limits.net_monthly,
                "pct_fpl": "100%",
            },
            computation=(
                f"Net income ${net_income:,.2f} "
                f"{'<=' if net_pass else '>'} "
                f"${limits.net_monthly:,.2f} "
                f"(100% FPL for {profile.household_size}-person HH)"
            ),
            result="PASS" if net_pass else "FAIL — exceeds net income limit",
            is_determinative=not net_pass,
        ))
        step_n += 1
        if not net_pass:
            return RationaleTrace(
                steps=steps,
                conclusion=f"INELIGIBLE. Net income ${net_income:,.2f} exceeds "
                           f"the ${limits.net_monthly:,.2f} limit (100% FPL).",
                policy_basis=[PolicyCitation(
                    document="7 CFR Part 273",
                    section="7 CFR 273.9(a)(2)",
                    year=self.fiscal_year,
                    url="https://www.ecfr.gov/current/title-7/part-273",
                )],
            )

        # Step 5: Asset test
        if bbce:
            steps.append(ReasoningStep(
                step_number=step_n,
                title="Asset test — waived (broad-based categorical eligibility state)",
                rule_applied="7 CFR 273.8(a)",
                inputs={"state": self.state, "bbce": True},
                computation=f"{self.state} has adopted broad-based categorical eligibility — asset test is waived.",
                result="WAIVED",
                is_determinative=False,
                note="BBCE states may remove or relax the asset test for most or all households.",
            ))
        else:
            asset_limit = (
                t.asset_limit_elderly_disabled if profile.has_elderly_or_disabled
                else t.asset_limit_general
            ) or 2500.0
            asset_pass = profile.liquid_assets <= asset_limit
            steps.append(ReasoningStep(
                step_number=step_n,
                title="Check asset limit",
                rule_applied="7 CFR 273.8(b)(1)" if not profile.has_elderly_or_disabled else "7 CFR 273.8(b)(2)",
                inputs={
                    "liquid_assets": profile.liquid_assets,
                    "asset_limit": asset_limit,
                    "elderly_disabled": profile.has_elderly_or_disabled,
                },
                computation=(
                    f"${profile.liquid_assets:,.2f} "
                    f"{'<=' if asset_pass else '>'} "
                    f"${asset_limit:,.2f}"
                ),
                result="PASS" if asset_pass else "FAIL — exceeds asset limit",
                is_determinative=not asset_pass,
            ))
            if not asset_pass:
                return RationaleTrace(
                    steps=steps,
                    conclusion=f"INELIGIBLE. Assets ${profile.liquid_assets:,.2f} exceed "
                               f"the ${asset_limit:,.2f} limit.",
                    policy_basis=[PolicyCitation(
                        document="7 CFR Part 273",
                        section="7 CFR 273.8(b)",
                        year=self.fiscal_year,
                    )],
                )

        # All tests passed
        benefit = limits.max_benefit or 0.0
        return RationaleTrace(
            steps=steps,
            conclusion=(
                f"ELIGIBLE. All tests passed: "
                f"{'gross income (waived for elderly/disabled), ' if profile.has_elderly_or_disabled else 'gross income, '}"
                f"net income (${net_income:,.2f} ≤ ${limits.net_monthly:,.2f}), "
                f"{'assets (BBCE — waived).' if bbce else f'assets (${profile.liquid_assets:,.2f} ≤ ${(t.asset_limit_general or 0):,.2f}).'} "
                f"Estimated monthly benefit: ~${benefit:,.0f}."
            ),
            policy_basis=[
                PolicyCitation(
                    document="7 CFR Part 273",
                    section="7 CFR 273.9",
                    year=self.fiscal_year,
                    url="https://www.ecfr.gov/current/title-7/part-273",
                ),
                PolicyCitation(
                    document=f"USDA FNS SNAP Income and Resource Limits {fy_config.period_label}",
                    section="Income and Allotment Table",
                    year=self.fiscal_year,
                    url="https://www.fns.usda.gov/snap/recipient/eligibility",
                ),
            ],
        )

    def _build_expected_answer(
        self,
        profile: USHouseholdProfile,
        net_income: float,
        limits: Any,
        is_eligible: bool,
        reason: str,
        fy_config: Any,
    ) -> str:
        t = self.source.thresholds()
        std_ded = get_standard_deduction(profile.household_size)
        earned = profile.earned_income or profile.monthly_gross_income
        earned_ded = earned * 0.20

        if is_eligible:
            benefit = limits.max_benefit or 0.0
            return (
                f"This household is ELIGIBLE for SNAP benefits ({fy_config.period_label}).\n\n"
                f"Gross income test: ${profile.monthly_gross_income:,.2f} "
                f"{'(waived — elderly/disabled household)' if profile.has_elderly_or_disabled else f'≤ ${limits.gross_monthly:,.2f} — PASS'}.\n"
                f"Net income: ${profile.monthly_gross_income:,.2f} − ${earned_ded:,.2f} (20% earned deduction) − "
                f"${std_ded:,.0f} (standard deduction) = ${net_income:,.2f} ≤ ${limits.net_monthly:,.2f} — PASS.\n"
                f"Assets: ${profile.liquid_assets:,.2f} ≤ ${t.asset_limit_general or 'N/A (BBCE)'} — PASS.\n\n"
                f"Estimated monthly benefit: approximately ${benefit:,.0f} "
                f"(maximum for {profile.household_size}-person household, subject to net income calculation)."
            )
        else:
            return (
                f"This household is INELIGIBLE for SNAP benefits ({fy_config.period_label}).\n\n"
                f"Reason: {reason}\n\n"
                f"Applicable limits for a {profile.household_size}-person household: "
                f"Gross ${limits.gross_monthly:,.2f}/month (130% FPL), "
                f"Net ${limits.net_monthly:,.2f}/month (100% FPL), "
                f"Assets ${t.asset_limit_general:,.2f} (general)."
            )

    def _classify_difficulty(self, profile: USHouseholdProfile, is_eligible: bool) -> Difficulty:
        threshold_type = profile.extra.get("threshold_type", "")
        offset = profile.extra.get("offset_pct", 0.5)

        if abs(offset) <= 0.01 and threshold_type:
            return Difficulty.HARD
        elif profile.has_elderly_or_disabled or self.state in BBCE_STATES:
            return Difficulty.MEDIUM
        elif abs(offset) > 0.30:
            return Difficulty.EASY
        else:
            return Difficulty.MEDIUM

    def _make_civbench_id(
        self, profile: USHouseholdProfile, is_eligible: bool, index: int
    ) -> str:
        threshold = profile.extra.get("threshold_type", "general")
        offset = profile.extra.get("offset_pct", 0.0)
        offset_tag = (
            "at_limit" if offset == 0.0
            else "above_limit" if offset > 0 else "below_limit"
        )
        outcome = "eligible" if is_eligible else "ineligible"
        hh = f"hh{profile.household_size}"
        uid = str(uuid.uuid4())[:6]
        return f"snap.{self.state.lower()}.eligibility.{threshold}.{offset_tag}.{outcome}.{hh}.{uid}"

    def _build_variation_tags(self, profile: USHouseholdProfile) -> list[str]:
        tags: list[str] = []
        threshold = profile.extra.get("threshold_type", "")
        offset = profile.extra.get("offset_pct", None)

        if threshold:
            tags.append(threshold)
        if offset is not None:
            if offset == 0.0:
                tags.append("at_limit")
            elif offset > 0:
                tags.append("above_limit")
            else:
                tags.append("below_limit")
        if profile.has_elderly_or_disabled:
            tags.append("elderly_or_disabled")
            tags.append("gross_income_test_waived")
        if self.state in BBCE_STATES:
            tags.append("bbce_state")
            tags.append("asset_test_waived")
        if profile.household_size == 1:
            tags.append("single_person_household")
        elif profile.has_dependent_children:
            tags.append("family_with_children")

        return tags
