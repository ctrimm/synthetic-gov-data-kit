"""Tests for LIHEAPEligibilityGenerator."""

from __future__ import annotations

from collections import Counter

import pytest
from govsynth.generators.liheap_eligibility import LIHEAPEligibilityGenerator

STATES = ("VA", "CA", "TX", "MD")


def test_determinism() -> None:
    a = LIHEAPEligibilityGenerator(state="MD").generate(n=20, seed=42)
    b = LIHEAPEligibilityGenerator(state="MD").generate(n=20, seed=42)
    assert [c.case_id for c in a] == [c.case_id for c in b]


@pytest.mark.parametrize("state", STATES)
def test_cases_valid_and_agree_with_source(state: str) -> None:
    gen = LIHEAPEligibilityGenerator(state=state)
    cases = gen.generate(n=150, seed=42)
    assert len(cases) == 150
    assert {c.metadata["component"] for c in cases} == set(gen.source.components)
    assert Counter(c.expected_outcome for c in cases).keys() == {"eligible", "ineligible"}
    for c in cases:
        assert c.is_valid() and c.program == "liheap"
        ctx = c.scenario.additional_context
        ok, _ = gen.source.determine(
            ctx["liheap_component"], c.scenario.household_size, ctx["annual_gross_income"], tuple(ctx["receives"])
        )
        assert ok == (c.expected_outcome == "eligible"), c.case_id
        fails = [s for s in c.rationale_trace.steps if s.is_determinative and s.result.startswith("FAIL")]
        assert (c.expected_outcome == "ineligible") == (len(fails) == 1), c.case_id


def test_maryland_categorical_cases_are_plausible() -> None:
    gen = LIHEAPEligibilityGenerator(state="MD")
    cases = [c for c in gen.generate(n=400, seed=7) if c.scenario.additional_context["receives"]]
    assert cases and all(c.expected_outcome == "eligible" for c in cases)
    above = []
    for c in cases:
        program = c.scenario.additional_context["receives"][0]
        income = c.scenario.additional_context["annual_gross_income"]
        limit = gen.source.threshold(c.metadata["component"], c.scenario.household_size).annual_limit
        if income > limit:
            above.append(c)
            assert program == "SNAP", c.case_id  # only SNAP households plausibly exceed the LIHEAP limit
    assert above  # the SNAP-above-limit case (eligible only through categorical eligibility) is generated


def test_states_without_categorical_eligibility_never_produce_it() -> None:
    for state in ("VA", "CA", "TX"):
        assert not any(
            c.scenario.additional_context["receives"]
            for c in LIHEAPEligibilityGenerator(state=state).generate(80, seed=1)
        )
