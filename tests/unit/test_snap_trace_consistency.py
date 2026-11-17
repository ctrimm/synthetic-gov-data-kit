"""SNAP rationale traces must reach the net income each case is judged on (#33)."""

from __future__ import annotations

import re

import pytest
from govsynth.generators.snap_eligibility import SNAPEligibilityGenerator
from govsynth.models.test_case import TestCase
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.sources.us.snap import SNAPSource

STRATEGIES = [
    {"profile_strategy": "edge_saturated"},
    {"profile_strategy": "uniform"},
    {"profile_strategy": "realistic"},
    {"profile_strategy": "realistic", "population": "caseload"},
]


def _general_path(cases: list[TestCase]) -> list[TestCase]:
    """Cases whose trace came from the general builder (special-population builders write their own)."""
    return [c for c in cases if any(s.title == "Check net income limit" for s in c.rationale_trace.steps)]


def _amount(text: str) -> float:
    found = re.findall(r"\$([\d,]+\.\d\d)", text)
    assert found, text
    return float(found[-1].replace(",", ""))


@pytest.mark.parametrize("state", ["VA", "AK", "HI", "TX"])
@pytest.mark.parametrize("kwargs", STRATEGIES, ids=lambda k: "-".join(map(str, k.values())))
def test_trace_reaches_the_cases_net_income(state: str, kwargs: dict[str, str]) -> None:
    cases = _general_path(SNAPEligibilityGenerator(state=state).generate(120, seed=42, **kwargs))
    assert cases
    for c in cases:
        steps = c.rationale_trace.steps
        i = next(i for i, s in enumerate(steps) if s.title == "Check net income limit")
        assert _amount(steps[i - 1].result) == pytest.approx(c.scenario.monthly_net_income, abs=0.01), c.case_id
        assert [s.step_number for s in steps] == list(range(1, len(steps) + 1)), c.case_id


@pytest.mark.parametrize("kwargs", STRATEGIES[2:], ids=lambda k: "-".join(map(str, k.values())))
def test_no_earned_deduction_without_earnings(kwargs: dict[str, str]) -> None:
    cases = _general_path(SNAPEligibilityGenerator(state="VA").generate(200, seed=42, **kwargs))
    unearned_only = [c for c in cases if (c.scenario.additional_context.get("earned_income") or 0) == 0]
    assert unearned_only, "fixture should include households with no earnings"
    for c in unearned_only:
        titles = [s.title for s in c.rationale_trace.steps]
        assert "Apply earned income deduction (20%)" not in titles, c.case_id
        assert "Earned income deduction — not applicable" in titles, c.case_id


def test_shelter_step_whenever_shelter_costs_are_stated() -> None:
    cases = _general_path(SNAPEligibilityGenerator(state="VA").generate(200, seed=42, profile_strategy="uniform"))
    for c in cases:
        if (c.scenario.additional_context.get("shelter_costs") or 0) > 0:
            shelter = [s for s in c.rationale_trace.steps if s.title == "Apply excess shelter deduction"]
            assert len(shelter) == 1, c.case_id
            assert shelter[0].rule_applied == "7 CFR 273.9(d)(6)(ii)"


def test_deduction_citations_use_273_9_d() -> None:
    """Deductions are 7 CFR 273.9(d); (c) is income exclusions."""
    cases = _general_path(SNAPEligibilityGenerator(state="VA").generate(100, seed=42, profile_strategy="uniform"))
    rules = {s.title: s.rule_applied for c in cases for s in c.rationale_trace.steps}
    assert rules["Apply standard deduction"] == "7 CFR 273.9(d)(1)"
    assert rules["Apply earned income deduction (20%)"] == "7 CFR 273.9(d)(2)"
    assert not any("273.9(c)" in r for r in rules.values())


class TestBreakdown:
    src = SNAPSource(fiscal_year=2026, state="VA")

    def test_unearned_income_gets_no_earned_deduction(self) -> None:
        b = self.src.net_income_breakdown(gross_income=1500.0, household_size=1, earned_income=0.0)
        assert b.earned_deduction == 0.0
        assert b.after_earned == 1500.0
        assert b.net_income == pytest.approx(1500.0 - b.standard_deduction)

    def test_shelter_cap_applies_only_without_elderly_or_disabled(self) -> None:
        kwargs = {"gross_income": 1000.0, "household_size": 2, "shelter_costs": 3000.0}
        capped = self.src.net_income_breakdown(**kwargs)
        uncapped = self.src.net_income_breakdown(**kwargs, has_elderly_or_disabled=True)
        assert capped.shelter_capped and capped.shelter_deduction == capped.shelter_cap
        assert not uncapped.shelter_capped and uncapped.shelter_deduction == uncapped.excess_shelter

    def test_matches_calculate_net_income(self) -> None:
        for gross, earned, shelter in ((2000.0, 2000.0, 900.0), (1200.0, 300.0, 0.0), (800.0, 0.0, 1500.0)):
            kw = {"gross_income": gross, "household_size": 3, "earned_income": earned, "shelter_costs": shelter}
            assert self.src.net_income_breakdown(**kw).net_income == self.src.calculate_net_income(**kw)

    def test_alaska_uses_its_own_standard_deduction(self) -> None:
        ak = SNAPSource(fiscal_year=2026, state="AK").net_income_breakdown(gross_income=2000.0, household_size=1)
        va = self.src.net_income_breakdown(gross_income=2000.0, household_size=1)
        assert ak.standard_deduction != va.standard_deduction


@pytest.mark.parametrize("state", ["VA", "AK", "TX"])
@pytest.mark.parametrize("offset", [-0.01, 0.0, 0.01])
def test_net_threshold_profiles_include_shelter_and_land_on_the_limit(state: str, offset: float) -> None:
    from govsynth.sources.us.snap_bbce import SNAPBBCESource

    src = SNAPBBCESource(fiscal_year=2026, state=state)
    for seed in range(10):
        p = USHouseholdProfile.at_threshold(
            program="snap", threshold="net_income_limit", state=state, household_size=3, offset_pct=offset, seed=seed
        )
        recomputed = src.calculate_net_income(
            gross_income=p.monthly_gross_income,
            household_size=3,
            shelter_costs=p.shelter_costs,
            has_elderly_or_disabled=p.has_elderly_or_disabled,
        )
        assert p.monthly_net_income == pytest.approx(recomputed, abs=0.005)
        target = src.thresholds().by_household_size(3).net_monthly * (1 + offset)
        assert target - 0.01 <= p.monthly_net_income <= target
