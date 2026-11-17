"""Unit tests for MedicaidEligibilityGenerator."""

import pytest
from govsynth.generators.medicaid_eligibility import MedicaidEligibilityGenerator


def test_program_is_medicaid() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    assert gen.program == "medicaid"


def test_generate_returns_requested_count() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    cases = gen.generate(n=10, seed=42)
    assert len(cases) == 10


def test_generate_is_deterministic_with_seed() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    cases1 = gen.generate(n=15, seed=42)
    cases2 = gen.generate(n=15, seed=42)
    assert [c.case_id for c in cases1] == [c.case_id for c in cases2]
    assert [c.expected_outcome for c in cases1] == [c.expected_outcome for c in cases2]


def test_all_generated_cases_pass_output_contract() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    cases = gen.generate(n=30, seed=7)
    for case in cases:
        assert case.is_valid(), case.check_output_contract()


def test_case_ids_follow_medicaid_state_schema() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    cases = gen.generate(n=10, seed=42)
    for case in cases:
        assert case.case_id.startswith("medicaid.va.eligibility.")


def test_non_expansion_state_produces_coverage_gap_cases() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="TX")
    cases = gen.generate(n=40, seed=42)
    descriptors = {tag for case in cases for tag in case.variation_tags}
    assert "non_expansion_coverage_gap" in descriptors
    gap_cases = [c for c in cases if "non_expansion_coverage_gap" in c.variation_tags]
    assert all(c.expected_outcome == "ineligible" for c in gap_cases)


def test_expansion_state_produces_both_outcomes_across_seeds() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    cases = gen.generate(n=60, seed=1)
    outcomes = {c.expected_outcome for c in cases}
    assert outcomes == {"eligible", "ineligible"}


def test_each_case_has_applicant_type_in_metadata() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    cases = gen.generate(n=10, seed=42)
    valid_types = {"adult", "pregnant", "child", "parent_caretaker"}
    for case in cases:
        assert case.metadata["applicant_type"] in valid_types


def test_rationale_trace_cites_42_cfr_435() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    cases = gen.generate(n=5, seed=42)
    for case in cases:
        citations = [str(c) for c in case.rationale_trace.policy_basis]
        assert any("42 CFR 435" in c for c in citations)


# --- #13: profile_strategy is honoured and cases are never dropped -------------------------------


def test_uniform_strategy_takes_size_and_income_from_the_profile() -> None:
    from govsynth.profiles.us_household import USHouseholdProfile

    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    edge = gen.generate(n=30, seed=42)
    uniform = gen.generate(n=30, seed=42, profile_strategy="uniform")
    assert [c.scenario.monthly_gross_income for c in edge] != [c.scenario.monthly_gross_income for c in uniform]
    for case in uniform:
        assert case.metadata["profile_strategy"] == "uniform"
        assert case.scenario.monthly_net_income == case.scenario.monthly_gross_income
    # The case's household is the sampled profile's household.
    profile = USHouseholdProfile.random(state="VA", seed=uniform[0].seed, strategy="uniform")
    assert uniform[0].scenario.household_size == profile.household_size


def test_realistic_strategy_uses_census_and_records_the_vintage() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    cases = gen.generate(n=6, seed=42, profile_strategy="realistic", census_years="2022-2024")
    assert [c.metadata["census_vintage"] for c in cases] == ["acs5-2022", "acs5-2023", "acs5-2024"] * 2


@pytest.mark.parametrize("strategy", ["edge_saturated", "uniform", "realistic"])
def test_every_strategy_returns_exactly_n_deterministic_cases(strategy: str) -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="TX")
    a = gen.generate(n=25, seed=42, profile_strategy=strategy)
    b = gen.generate(n=25, seed=42, profile_strategy=strategy)
    assert len(a) == 25
    assert [c.case_id for c in a] == [c.case_id for c in b]


@pytest.mark.parametrize("state", ["VA", "TX", "GA", "KS", "AK"])
def test_outcome_agrees_with_the_source_for_every_strategy(state: str) -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state=state)
    for strategy in ("edge_saturated", "uniform", "realistic"):
        for case in gen.generate(n=40, seed=42, profile_strategy=strategy):
            ok, _ = gen.source.is_eligible(
                case.scenario.household_size,
                case.scenario.monthly_gross_income,
                case.metadata["applicant_type"],
                case.metadata.get("child_age"),
            )
            assert ok == (case.expected_outcome == "eligible"), case.case_id


@pytest.mark.parametrize("state", ["VA", "TX", "WI"])
def test_trace_invariants(state: str) -> None:
    for case in MedicaidEligibilityGenerator(state=state).generate(n=120, seed=42):
        steps = case.rationale_trace.steps
        determinative = [s for s in steps if s.is_determinative]
        if case.expected_outcome == "ineligible":
            assert len(determinative) == 1, case.case_id
        else:
            assert not determinative, case.case_id
        assert [s.step_number for s in steps] == list(range(1, len(steps) + 1))
        applicant = case.metadata["applicant_type"]
        if applicant in ("pregnant", "parent_caretaker", "child"):
            assert case.scenario.household_size >= 2, case.case_id
        if applicant == "child":
            assert 0 <= case.metadata["child_age"] <= 18
        assert case.scenario.additional_context["age_of_head"] < 65  # MAGI adult groups are under 65


def test_coverage_gap_note_depends_on_income() -> None:
    cases = MedicaidEligibilityGenerator(state="TX").generate(n=300, seed=42)
    gap = [c for c in cases if "non_expansion_coverage_gap" in c.variation_tags]
    above = [c for c in cases if "no_adult_coverage_above_100pct" in c.variation_tags]
    assert gap and above
    assert all("coverage gap" in (c.rationale_trace.steps[1].note or "") for c in gap)
    assert all("premium tax credits (100-400% FPL)" in (c.rationale_trace.steps[1].note or "") for c in above)


def test_unknown_strategy_and_misplaced_census_years_raise() -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")
    with pytest.raises(ValueError, match="profile_strategy"):
        gen.generate(n=1, profile_strategy="adversarial")
    with pytest.raises(ValueError, match="realistic"):
        gen.generate(n=1, census_years=2023)


def test_a_failing_case_raises_instead_of_being_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    gen = MedicaidEligibilityGenerator(calendar_year=2026, state="VA")

    def boom(*args: object, **kwargs: object) -> None:
        raise KeyError("missing limit")

    monkeypatch.setattr(gen.source, "is_eligible", boom)
    with pytest.raises(RuntimeError, match="Medicaid case 0 of 3"):
        gen.generate(n=3, seed=42)


def test_pipeline_realistic_medicaid() -> None:
    from govsynth.pipeline import Pipeline

    cases = Pipeline.from_preset("medicaid.tx", profile_strategy="realistic", census_years=2023).generate(n=5, seed=1)
    assert len(cases) == 5 and all(c.metadata["census_vintage"] == "acs5-2023" for c in cases)
