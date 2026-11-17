"""TANF cash assistance eligibility test case generator (VA, MD, TX, CA; 2026).

Each case is a first-time applicant household (a caretaker relative and children) whose
earnings and/or Social Security income are tested against the state's own TANF rules. The
rationale trace is exactly the ordered list of facts and tests TANFSource.evaluate returns,
so it can never disagree with the determination; an ineligible case has one determinative
FAIL, the first test the household fails.

Under 'edge_saturated' (the default) each case targets one of the state's income tests and
places income on and around that test's boundary, located by bisection on the test itself,
so every test's boundary is exercised, not only the binding one. California cases stay at
least 3% from a boundary, because 'below the MBSAC' and the minimum-grant rule are not pinned
down to the dollar by the retrieved sources.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from govsynth.generators.base import Generator
from govsynth.models.enums import Difficulty, Program, TaskType
from govsynth.models.rationale import PolicyCitation, RationaleTrace, ReasoningStep
from govsynth.models.test_case import ScenarioBlock, TaskBlock, TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.reasoning.rules_engine import build_case_id, build_short_uid
from govsynth.sources.us.census import CensusVintage, census_years_for_strategy
from govsynth.sources.us.tanf import TANFCheck, TANFHousehold, TANFSource

_STRATEGIES = ("edge_saturated", "uniform", "realistic")
_OFFSETS = (-0.05, -0.01, 0.0, 0.01, 0.05)
_CA_OFFSETS = (-0.08, -0.03, 0.03, 0.08)
# A few Region 2 counties (every California county not in ACL 26-66's Region 1 list is Region 2).
_CA_REGION_2_SAMPLE = (
    "Fresno", "Kern", "Sacramento", "Riverside", "San Bernardino", "Tulare", "Stanislaus",
    "Butte", "Shasta", "Humboldt", "Merced", "Placer", "Yolo", "Imperial", "San Joaquin",
)  # fmt: skip

_INSTRUCTION = (
    "Based on the situation described above, determine whether this household is eligible for TANF cash "
    "assistance in its state. Apply the state's own income tests in order, with the disregards each test allows, "
    "and cite the state rule for each step. State your final determination (eligible or ineligible) and the test "
    "that decides it."
)


class TANFEligibilityGenerator(Generator):
    """Generates TANF eligibility test cases for one of VA, MD, TX, CA.

    Args:
        state: Two-letter state code.
        year: Rule year (2026).
    """

    def __init__(self, state: str = "VA", year: int = 2026) -> None:
        self.state = state.upper()
        self.year = year
        self.source = TANFSource(state=self.state, year=year)

    @property
    def program(self) -> str:
        return "tanf"

    def generate(
        self,
        n: int,
        profile_strategy: str = "edge_saturated",
        seed: int | None = None,
        census_years: Sequence[CensusVintage | int | str] | CensusVintage | int | str | None = None,
    ) -> list[TestCase]:
        """Generate n cases. Exactly n are returned.

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
                raise RuntimeError(f"TANF case {i} of {n} failed to build: {exc}") from exc
        return cases

    # ------------------------------------------------------------------

    def _locality(self, rng: random.Random) -> dict[str, Any]:
        raw = self.source.raw
        if self.state == "VA":
            g = raw["locality_groups"]
            kind = rng.choice(("counties", "cities"))
            group = rng.choice(("group_ii", "group_iii"))
            name = rng.choice(g[f"{group}_{kind}"])
            return {"locality": f"{name} {'County' if kind == 'counties' else 'city'}"}
        if self.state == "CA":
            r1 = raw["region_1_counties"]
            return {"county": rng.choice(r1) if rng.random() < 0.5 else rng.choice(_CA_REGION_2_SAMPLE)}
        return {}

    @staticmethod
    def _boundary(passes: Callable[[float], bool], hi: float = 8000.0) -> float:
        """Largest whole-cent amount for which `passes` holds (it holds at 0 and fails above)."""
        lo = 0.0
        if passes(hi):
            return hi
        for _ in range(60):
            mid = (lo + hi) / 2
            if passes(mid):
                lo = mid
            else:
                hi = mid
        x = int(lo * 100) / 100
        while x > 0 and not passes(x):
            x = round(x - 0.01, 2)
        return x

    def _build_case(
        self, rng: random.Random, seed: int | None, strategy: str, vintage: CensusVintage | int | str | None
    ) -> TestCase:
        src = self.source
        size = rng.choice(src.sizes)
        two_parent = self.state == "TX" and size >= 3 and rng.random() < 0.25
        kind = rng.choices(("earned", "unearned", "both"), weights=(0.65, 0.25, 0.10))[0]
        if self.state == "TX" and kind == "both":
            kind = "earned"  # TX households have one income type (see module docstring of tanf.py)
        resources = 0.0
        if self.state == "TX":
            resources = round(rng.uniform(950, 1100), 2) if rng.random() < 0.1 else round(rng.uniform(0, 900), 2)
        base = TANFHousehold(size=size, two_parent=two_parent, countable_resources=resources, **self._locality(rng))
        unearned_share = rng.uniform(0.2, 0.5) if kind == "both" else 0.0

        def household(amount: float) -> TANFHousehold:
            if kind == "earned":
                return replace(base, earned=round(amount, 2))
            if kind == "unearned":
                return replace(base, unearned=round(amount, 2))
            return replace(
                base, earned=round(amount * (1 - unearned_share), 2), unearned=round(amount * unearned_share, 2)
            )

        tests = [
            i for i, c in enumerate(src.all_checks(household(0))) if c.passed is not None and "resources" not in c.title
        ]
        if strategy == "edge_saturated":
            target = rng.choice(tests)
            boundary = self._boundary(lambda x: src.all_checks(household(x))[target].passed is True)
            offset = rng.choice(_CA_OFFSETS if self.state == "CA" else _OFFSETS)
            amount = round(boundary * (1 + offset), 2) if boundary > 0 else round(rng.uniform(50, 400), 2)
            hh = household(amount)
            profile = USHouseholdProfile.random(state=self.state, seed=seed, strategy="uniform")
        else:
            profile = USHouseholdProfile.random(
                state=self.state,
                seed=seed,
                strategy=strategy,
                census_vintage=vintage,
                income_dollar_year=self.year if strategy == "realistic" else None,
            )
            earned, unearned = round(profile.earned_income or 0.0, 2), round(profile.unearned_income or 0.0, 2)
            if self.state == "TX" and earned and unearned:
                earned, unearned = (earned, 0.0) if earned >= unearned else (0.0, unearned)
            hh = replace(base, earned=earned, unearned=unearned)
            offset = None

        checks = src.evaluate(hh)
        eligible = all(c.passed is not False for c in checks)
        failed = next((c for c in checks if c.passed is False), None)
        steps = [
            ReasoningStep(
                step_number=i + 1,
                title=c.title,
                rule_applied=c.rule,
                inputs=c.inputs,
                computation=c.computation,
                result=c.result,
                is_determinative=c.passed is False,
            )
            for i, c in enumerate(checks)
        ]
        outcome = "eligible" if eligible else "ineligible"
        descriptor = _slug(failed) if failed else "all_tests_passed"
        case_id = build_case_id("tanf", self.state, descriptor, outcome, size, build_short_uid(rng))

        profile.household_size = size
        profile.monthly_gross_income = round(hh.earned + hh.unearned, 2)
        profile.monthly_net_income = None
        profile.earned_income = hh.earned
        profile.unearned_income = hh.unearned
        profile.has_dependent_children = True
        profile.has_elderly_or_disabled = False
        profile.age_of_head = rng.randint(20, 50)
        profile.liquid_assets = resources if self.state == "TX" else round(rng.uniform(0, 600), 2)
        fields = profile.to_scenario_fields()
        context: dict[str, Any] = {
            "first_time_applicant": True,
            "earned_income_monthly": hh.earned,
            "social_security_monthly": hh.unearned,
        }
        if hh.locality:
            context["locality"] = hh.locality
        if hh.county:
            context["county"] = hh.county
            context["property_within_limit"] = True
            context["exempt_caretaker"] = False
        if self.state == "TX":
            context["case_type"] = "two_parent" if two_parent else "one_parent"
            context["countable_resources"] = resources
        fields["additional_context"] = {**fields["additional_context"], **context}

        difficulty = (
            Difficulty.MEDIUM
            if offset is None
            else Difficulty.HARD
            if abs(offset) <= 0.01
            else Difficulty.MEDIUM
            if abs(offset) <= 0.05
            else Difficulty.EASY
        )
        answer = (
            "ELIGIBLE for TANF: the household passes every test."
            if eligible
            else f"INELIGIBLE for TANF: fails '{failed.title}' ({failed.result})."  # type: ignore[union-attr]
        )
        m = src.raw["_metadata"]
        return TestCase(
            case_id=case_id,
            program=Program.TANF.value,
            jurisdiction=f"us.{self.state.lower()}",
            task_type=TaskType.ELIGIBILITY,
            difficulty=difficulty,
            scenario=ScenarioBlock(summary=self._summary(profile.head_of_household_name, hh), **fields),
            task=TaskBlock(instruction=_INSTRUCTION),
            expected_outcome=outcome,
            expected_answer=answer,
            rationale_trace=RationaleTrace(
                steps=steps,
                conclusion=answer,
                policy_basis=[
                    PolicyCitation(
                        document=m["source"], section=m["rules_reference"], year=self.year, url=m["source_url"]
                    )
                ],
            ),
            variation_tags=[descriptor, f"income_{kind}"],
            source_citations=[m["rules_reference"], "45 CFR Part 260"],
            seed=seed,
            metadata={
                "generator": "TANFEligibilityGenerator",
                "state": self.state,
                "year": self.year,
                "income_type": kind,
                "profile_strategy": strategy,
                "failed_test": failed.title if failed else None,
                **({"census_vintage": profile.census_vintage} if profile.census_vintage else {}),
            },
        )

    def _summary(self, name: str, hh: TANFHousehold) -> str:
        names = {"VA": "Virginia", "MD": "Maryland", "TX": "Texas", "CA": "California"}
        place = {"VA": hh.locality, "CA": f"{hh.county} County"}.get(self.state)
        where = f"{place}, {names[self.state]}" if place else names[self.state]
        parents = f"{name} and another parent" if hh.two_parent else name
        children = hh.size - (2 if hh.two_parent else 1)
        parts = [
            f"{name} lives in {where} and is applying for TANF for the first time (no TANF in the past "
            f"four months) for a household of {hh.size}: {parents} and {children} "
            f"{'child' if children == 1 else 'children'}."
        ]
        if hh.earned:
            parts.append(f"One adult earns ${hh.earned:,.2f}/month in wages.")
        if hh.unearned:
            parts.append(f"The household receives ${hh.unearned:,.2f}/month in Social Security benefits.")
        if not hh.earned and not hh.unearned:
            parts.append("The household has no income.")
        if self.state == "TX":
            parts.append(f"Countable resources (cash and savings) total ${hh.countable_resources:,.2f}.")
        if self.state == "CA":
            parts.append("The family's property is within the CalWORKs limit and no caretaker is exempt (disabled).")
        return " ".join(parts)


def _slug(check: TANFCheck) -> str:
    words = "".join(ch if ch.isalnum() else " " for ch in check.title.lower()).split()
    return "_".join(words[:5])
