"""Tests for MedicareSavingsGenerator."""

from __future__ import annotations

from collections import Counter

import pytest
from govsynth.generators.medicare_savings import MedicareSavingsGenerator


@pytest.fixture(scope="module")
def cases() -> list:
    return MedicareSavingsGenerator().generate(n=200, seed=42)


def test_determinism() -> None:
    a = MedicareSavingsGenerator().generate(n=20, seed=42)
    b = MedicareSavingsGenerator().generate(n=20, seed=42)
    assert [c.case_id for c in a] == [c.case_id for c in b]


def test_all_valid_and_program(cases: list) -> None:
    assert all(c.is_valid() and c.program == "medicare" for c in cases)


def test_covers_every_tier_and_outcome(cases: list) -> None:
    seen = Counter((c.metadata["case_type"], c.expected_outcome, c.metadata.get("msp_tier")) for c in cases)
    for tier in ("qmb", "slmb", "qi"):
        assert seen[("msp_tier", "eligible", tier)] > 0
    assert seen[("msp_tier", "ineligible", None)] > 0
    assert seen[("extra_help", "eligible", None)] > 0 and seen[("extra_help", "ineligible", None)] > 0


def test_outcome_agrees_with_source(cases: list) -> None:
    gen = MedicareSavingsGenerator()
    for c in cases:
        ctx = c.scenario.additional_context
        gross, resources, couple = c.scenario.monthly_gross_income, c.scenario.liquid_assets, ctx["couple"]
        if ctx["case_type"] == "msp_tier":
            tier, _ = gen.source.msp_tier(gross, resources, couple)
            assert tier == ctx["msp_tier"], c.case_id
            assert (tier is not None) == (c.expected_outcome == "eligible")
        else:
            ok, _ = gen.source.extra_help_eligible(gross, resources, couple, c.scenario.household_size)
            assert ok == (c.expected_outcome == "eligible"), c.case_id


def test_determinative_steps_match_outcome(cases: list) -> None:
    for c in cases:
        fails = [s for s in c.rationale_trace.steps if s.is_determinative and s.result.startswith("FAIL")]
        assert (c.expected_outcome == "ineligible") == bool(fails), c.case_id


def test_eligible_answer_names_the_tier(cases: list) -> None:
    for c in cases:
        tier = c.metadata.get("msp_tier")
        if tier:
            assert f"({tier.upper()})" in c.expected_answer
