"""Tests for SSIEligibilityGenerator."""

from __future__ import annotations

from collections import Counter

import pytest
from govsynth.generators.ssi_eligibility import SSIEligibilityGenerator


@pytest.fixture(scope="module")
def cases() -> list:
    return SSIEligibilityGenerator().generate(n=300, seed=42)


def test_determinism() -> None:
    a = SSIEligibilityGenerator().generate(n=20, seed=42)
    b = SSIEligibilityGenerator().generate(n=20, seed=42)
    assert [c.case_id for c in a] == [c.case_id for c in b]


def test_all_valid(cases: list) -> None:
    assert all(c.is_valid() and c.program == "ssi" for c in cases)


def test_case_mix(cases: list) -> None:
    seen = Counter((c.metadata["case_type"], c.expected_outcome) for c in cases)
    for kind in ("income", "resources", "sga"):
        assert seen[(kind, "eligible")] and seen[(kind, "ineligible")], kind
    assert seen[("not_categorical", "ineligible")] and not seen[("not_categorical", "eligible")]


def test_outcome_and_payment_agree_with_source(cases: list) -> None:
    src = SSIEligibilityGenerator().source
    for c in cases:
        ctx = c.scenario.additional_context
        ok, payment, _ = src.determine(
            ctx["ssi_category"], ctx["unearned_income"], ctx["earned_income"], c.scenario.liquid_assets,
            ctx["couple"], blind=ctx["blind"],
        )  # fmt: skip
        assert ok == (c.expected_outcome == "eligible"), c.case_id
        assert (ctx["monthly_federal_payment"] or 0) == pytest.approx(payment)
        if ok:
            assert f"${payment:,.2f}" in c.expected_answer


def test_determinative_steps_match_outcome(cases: list) -> None:
    for c in cases:
        fails = [s for s in c.rationale_trace.steps if s.is_determinative and s.result.startswith("FAIL")]
        assert (c.expected_outcome == "ineligible") == (len(fails) == 1), c.case_id


def test_income_at_exactly_the_fbr_is_ineligible() -> None:
    cases = SSIEligibilityGenerator().generate(n=400, seed=7)
    src = SSIEligibilityGenerator().source
    at_fbr = [
        c for c in cases
        if c.metadata["case_type"] == "income"
        and src.countable_income(
            c.scenario.additional_context["unearned_income"], c.scenario.additional_context["earned_income"]
        ).countable == src.fbr(c.scenario.additional_context["couple"])
    ]  # fmt: skip
    assert at_fbr and all(c.expected_outcome == "ineligible" for c in at_fbr)
