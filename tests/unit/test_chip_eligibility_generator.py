"""Tests for CHIPEligibilityGenerator."""

from __future__ import annotations

from collections import Counter

import pytest
from govsynth.generators.chip_eligibility import CHIPEligibilityGenerator
from govsynth.sources.us.chip import CHIPSource


def test_determinism() -> None:
    a = CHIPEligibilityGenerator(state="TX").generate(n=20, seed=42)
    b = CHIPEligibilityGenerator(state="TX").generate(n=20, seed=42)
    assert [c.case_id for c in a] == [c.case_id for c in b]


@pytest.mark.parametrize(
    ("state", "chip_program"),
    [("VA", "separate_chip"), ("CA", "medicaid_chip_funded"), ("TX", "separate_chip"), ("MD", "medicaid_chip_funded")],
)
def test_cases_agree_with_source_and_cover_every_path(state: str, chip_program: str) -> None:
    gen = CHIPEligibilityGenerator(state=state)
    cases = gen.generate(n=200, seed=42)
    assert len(cases) == 200
    programs = Counter(c.metadata["coverage_program"] for c in cases)
    assert programs["medicaid"] and programs[chip_program] and programs[None]
    descriptors = {c.case_id.split(".")[3] for c in cases}
    assert {"insured_above_medicaid", "above_limit", "not_a_child"} <= descriptors
    for c in cases:
        assert c.is_valid() and c.program == "chip"
        ctx = c.scenario.additional_context
        result = gen.source.determine(
            ctx["child_age"], c.scenario.household_size, ctx["monthly_magi"], ctx["child_insured"]
        )
        assert result.program == ctx["coverage_program"], c.case_id
        assert result.eligible == (c.expected_outcome == "eligible")
        fails = [s for s in c.rationale_trace.steps if s.is_determinative and s.result.startswith("FAIL")]
        assert (c.expected_outcome == "ineligible") == (len(fails) == 1), c.case_id
        assert [s.step_number for s in c.rationale_trace.steps] == list(range(1, len(c.rationale_trace.steps) + 1))


def test_every_state_generates() -> None:
    for state in CHIPSource(state="VA").raw["states"]:
        assert len(CHIPEligibilityGenerator(state=state).generate(n=5, seed=1)) == 5
