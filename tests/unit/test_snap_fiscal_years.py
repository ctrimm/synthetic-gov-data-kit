"""SNAP rules for fiscal years before FY2026, and matching them to the census year.

FY2021-FY2025 threshold files are transcribed from the FNS COLA tables by
scripts/import_snap_cola.py. These tests pin the transcription against values
read off those tables, re-derive every income limit from the HHS poverty
guidelines, and run the same ground-truth invariants as FY2026 for every year.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from govsynth.generators.snap_eligibility import SNAPEligibilityGenerator
from govsynth.sources.us.snap import SNAPSource, get_standard_deduction
from govsynth.sources.us.snap_bbce import SNAPBBCESource, bbce_states

from tests.unit.test_snap_ground_truth_agreement import (
    NON_FINANCIAL_OUTCOME_TYPES,
    all_jurisdictions,
    bbce_outcome,
    case_type,
    determinative_problems,
    gross_limit_problems,
)

THRESHOLDS = Path(__file__).parent.parent.parent / "data" / "thresholds"
HISTORICAL = [2021, 2022, 2023, 2024, 2025]
ALL_YEARS = [*HISTORICAL, 2026]


def _snap(fy: int) -> dict:
    return json.loads((THRESHOLDS / f"snap_fy{fy}.json").read_text())


# Values read off the FNS tables for each year (48 States & DC column unless noted):
# (max allotment hh1, hh4, gross 130% hh1, net 100% hh1, std ded hh1-3, std ded 6+,
#  shelter cap, homeless, asset general, asset elderly/disabled, minimum benefit)
PINNED = {
    2021: (204, 680, 1383, 1064, 167, 243, 586, 156.74, 2250, 3500, 16),
    2022: (250, 835, 1396, 1074, 177, 246, 597, 159.73, 2500, 3750, 20),
    2023: (281, 939, 1473, 1133, 193, 258, 624, 166.81, 2750, 4250, 23),
    2024: (291, 973, 1580, 1215, 198, 279, 672, 179.66, 2750, 4250, 23),
    2025: (292, 975, 1632, 1255, 204, 291, 712, 190.30, 3000, 4500, 23),
    2026: (298, 994, 1696, 1305, 209, 299, 744, 198.99, 3000, 4500, 24),
}


@pytest.mark.parametrize("fy", ALL_YEARS)
def test_pinned_values_match_fns_tables(fy: int) -> None:
    d = _snap(fy)
    hh = d["households_48_states_dc"]
    got = (
        hh["1"]["max_benefit"],
        hh["4"]["max_benefit"],
        hh["1"]["gross_monthly"],
        hh["1"]["net_monthly"],
        d["standard_deductions_48_states_dc"]["1"],
        d["standard_deductions_48_states_dc"]["6+"],
        d["excess_shelter_deduction_cap_48_states_dc"],
        d["homeless_shelter_deduction"],
        d["asset_limit_general"],
        d["asset_limit_elderly_disabled"],
        d["minimum_benefit_48_states_dc"],
    )
    assert got == PINNED[fy]


@pytest.mark.parametrize("fy", ALL_YEARS)
@pytest.mark.parametrize(
    ("region", "fpl_region"), [("48_states_dc", "contiguous_48_dc"), ("alaska", "alaska"), ("hawaii", "hawaii")]
)
def test_income_limits_follow_the_prior_years_poverty_guidelines(fy: int, region: str, fpl_region: str) -> None:
    """Gross = ceil(130% FPL / 12), net = ceil(100% FPL / 12), using FY-1 guidelines."""
    d = _snap(fy)
    fpl = json.loads((THRESHOLDS / f"us_fpl_{fy - 1}.json").read_text())["regions"][fpl_region]
    for size in range(1, 9):
        annual = fpl["by_household_size"][str(size)]["annual"]
        row = d[f"households_{region}"][str(size)]
        assert row["gross_monthly"] == math.ceil(annual * 1.30 / 12), (fy, region, size)
        assert row["net_monthly"] == math.ceil(annual / 12), (fy, region, size)


@pytest.mark.parametrize("fy", HISTORICAL)
def test_historical_files_have_the_fy2026_shape(fy: int) -> None:
    assert set(_snap(fy)) == set(_snap(2026))
    bbce = json.loads((THRESHOLDS / f"snap_bbce_fy{fy}.json").read_text())
    bbce26 = json.loads((THRESHOLDS / "snap_bbce_fy2026.json").read_text())
    assert set(bbce["states"]) == set(bbce26["states"])


# Values read off each fiscal year's FNS BBCE States Chart (issue #23).
BBCE_COUNT = {2021: 43, 2022: 44, 2023: 44, 2024: 44, 2025: 44, 2026: 46}
CHART_DATE = {2021: "May 2020", 2022: "July 2021", 2023: "June 2022", 2024: "July 2023", 2025: "August 2024"}
# (state, fiscal year) -> (bbce, gross % FPL, asset limit), pinned where the charts changed.
BBCE_PINNED = {
    ("VA", 2021): (False, 130, 2250),  # not in the May 2020 chart
    ("VA", 2022): (True, 200, None),  # added in the July 2021 chart
    ("NE", 2022): (True, 130, 25000),
    ("NE", 2023): (True, 165, 25000),
    ("MI", 2023): (True, 200, 15000),
    ("MI", 2024): (True, 200, None),
    ("PA", 2023): (True, 160, None),
    ("PA", 2024): (True, 200, None),
    ("LA", 2024): (True, 130, None),
    ("LA", 2025): (True, 200, None),
    ("NM", 2025): (True, 165, None),
    ("NM", 2026): (True, 200, None),
    ("AK", 2025): (False, 130, 3000),
    ("AK", 2026): (True, 200, None),  # adopted during 2025
    ("AR", 2026): (True, 165, 5500),
}


@pytest.mark.parametrize("fy", HISTORICAL)
def test_historical_bbce_rows_are_verified_against_that_years_chart(fy: int) -> None:
    bbce = json.loads((THRESHOLDS / f"snap_bbce_fy{fy}.json").read_text())
    assert bbce["_metadata"]["verification_status"] == "verified"
    assert bbce["_metadata"]["chart_last_updated"] == CHART_DATE[fy]
    assert len(bbce_states(fy)) == BBCE_COUNT[fy]
    general = _snap(fy)["asset_limit_general"]
    for code, row in bbce["states"].items():
        assert row["verification_status"] == "verified", code
        if not row["bbce"]:
            assert row["asset_limit"] == general, code  # non-BBCE states use that year's federal limit


@pytest.mark.parametrize(("state", "fy"), sorted(BBCE_PINNED))
def test_bbce_values_pinned_to_the_charts(state: str, fy: int) -> None:
    row = json.loads((THRESHOLDS / f"snap_bbce_fy{fy}.json").read_text())["states"][state]
    assert (row["bbce"], row["gross_income_limit_pct_fpl"], row["asset_limit"]) == BBCE_PINNED[(state, fy)]


def test_bbce_citation_names_the_years_chart() -> None:
    gen = SNAPEligibilityGenerator(fiscal_year=2021, state="MD")
    assert gen._bbce_chart_citation == "USDA FNS SNAP BBCE States Chart (May 2020)"
    assert SNAPEligibilityGenerator(state="MD")._bbce_chart_citation == "USDA FNS SNAP BBCE States Chart (August 2025)"


def test_standard_deduction_is_read_from_the_fiscal_year() -> None:
    assert get_standard_deduction(3) == 209.0  # FY2026 default unchanged
    assert get_standard_deduction(3, fiscal_year=2021) == 167.0
    assert get_standard_deduction(6, "alaska", 2023) == 330.0
    assert get_standard_deduction(4, "virgin_islands", 2025) == 217.0
    with pytest.raises(ValueError):
        get_standard_deduction(1, "puerto_rico", 2024)


def test_policy_summary_states_the_years_own_figures() -> None:
    summary = SNAPSource(2022, "VA").fetch_policy_summary()
    assert "$177/month" in summary and "$3,750 asset limit" in summary and "$597/month" in summary


def test_non_bbce_state_uses_that_years_federal_asset_limit() -> None:
    src = SNAPBBCESource(fiscal_year=2021, state="KS")
    eligible, _ = src.is_eligible(household_size=1, gross_income=500, net_income=300, liquid_assets=2400)
    assert not eligible  # FY2021 federal limit was $2,250, not FY2026's $3,000


@pytest.mark.parametrize("fy", HISTORICAL)
@pytest.mark.parametrize("state", ["VA", "MD", "TX", "AK", "KS"])
def test_historical_cases_satisfy_the_ground_truth_invariants(fy: int, state: str) -> None:
    """Same invariants as FY2026: outcome agrees with the source, stated limits govern."""
    cases = SNAPEligibilityGenerator(fiscal_year=fy, state=state).generate(n=30, seed=42)
    problems: list[str] = []
    for case in cases:
        assert case.metadata["fiscal_year"] == fy
        problems += gross_limit_problems(case, fiscal_year=fy)
        problems += determinative_problems(case)
        if case_type(case) not in NON_FINANCIAL_OUTCOME_TYPES:
            outcome, reason = bbce_outcome(case, fiscal_year=fy)
            if outcome != case.expected_outcome:
                problems.append(f"{case.case_id}: {case.expected_outcome} vs source {outcome} ({reason})")
    assert not problems, "\n".join(problems[:10])


def test_all_jurisdictions_generate_for_every_historical_year() -> None:
    for fy in HISTORICAL:
        for state in all_jurisdictions(fy):
            assert SNAPEligibilityGenerator(fiscal_year=fy, state=state).generate(n=3, seed=42)


def test_year_specific_amounts_reach_the_case_text() -> None:
    cases = SNAPEligibilityGenerator(fiscal_year=2022, state="VA").generate(n=60, seed=42)
    homeless = [c for c in cases if c.metadata.get("profile_strategy") == "homeless_shelter_deduction"]
    assert homeless
    assert all("$159.73" in c.expected_answer and "198.99" not in c.expected_answer for c in homeless)
    assert all("7 CFR Part 273 (2021)" in c.source_citations for c in cases)


_STRATEGY_OF_BUILDER = {
    "_build_noncitizen_status_case": "noncitizen_status_eligibility",
    "_build_student_case": "student_exclusion",
}


@pytest.mark.parametrize(
    ("fy", "skipped"),
    [
        (2021, {"_build_noncitizen_status_case", "_build_student_case"}),
        (2023, {"_build_noncitizen_status_case", "_build_student_case"}),
        (2024, {"_build_noncitizen_status_case"}),
        (2025, {"_build_noncitizen_status_case"}),
        (2026, set()),
    ],
)
def test_builders_whose_rule_was_not_in_force_are_skipped(fy: int, skipped: set[str]) -> None:
    gen = SNAPEligibilityGenerator(fiscal_year=fy, state="VA")
    assert set(gen._builders_not_in_force()) == skipped
    produced = {c.metadata.get("profile_strategy") for c in gen.generate(n=60, seed=42)}
    assert not ({_STRATEGY_OF_BUILDER[b] for b in skipped} & produced)
    for name in set(_STRATEGY_OF_BUILDER) - skipped:
        assert _STRATEGY_OF_BUILDER[name] in produced, name


class TestCensusMatchedFiscalYear:
    def test_each_case_uses_the_fiscal_year_of_its_census_year(self) -> None:
        gen = SNAPEligibilityGenerator(state="VA")
        cases = gen.generate(n=10, profile_strategy="realistic", seed=42, census_years=["2021-2024", "acs1-2025"])
        pairs = {(c.metadata["census_vintage"], c.metadata["fiscal_year"]) for c in cases}
        assert pairs == {
            ("acs5-2021", 2021),
            ("acs5-2022", 2022),
            ("acs5-2023", 2023),
            ("acs5-2024", 2024),
            ("acs1-2025", 2025),
        }
        for case in cases:
            outcome, _ = bbce_outcome(case, fiscal_year=case.metadata["fiscal_year"])
            assert outcome == case.expected_outcome, case.case_id

    def test_opt_out_keeps_the_generators_fiscal_year(self) -> None:
        gen = SNAPEligibilityGenerator(state="VA")
        cases = gen.generate(n=4, profile_strategy="realistic", seed=42, census_years=2022, match_census_year=False)
        assert {c.metadata["fiscal_year"] for c in cases} == {2026}

    def test_deterministic(self) -> None:
        gen = SNAPEligibilityGenerator(state="VA")
        a = gen.generate(n=8, profile_strategy="realistic", seed=42, census_years="2021-2024")
        b = gen.generate(n=8, profile_strategy="realistic", seed=42, census_years="2021-2024")
        assert [c.case_id for c in a] == [c.case_id for c in b]

    def test_census_year_without_snap_data_raises(self) -> None:
        from govsynth.profiles.us_household import USHouseholdProfile

        gen = SNAPEligibilityGenerator(state="VA")
        profile = USHouseholdProfile(
            household_size=2, monthly_gross_income=1000.0, state="VA", census_vintage="acs1-2031"
        )
        with pytest.raises(ValueError, match="FY2031"):
            gen._generator_for_profile(profile)


class TestPipelineAndCli:
    def test_pipeline_follows_census_year_by_default(self) -> None:
        from govsynth.pipeline import Pipeline

        cases = Pipeline.from_preset("snap.va", profile_strategy="realistic", census_years="2022-2023").generate(
            n=30, seed=7
        )
        assert {(c.metadata["census_vintage"], c.metadata["fiscal_year"]) for c in cases} == {
            ("acs5-2022", 2022),
            ("acs5-2023", 2023),
        }

    def test_pipeline_fixed_policy_year(self) -> None:
        from govsynth.pipeline import Pipeline

        p = Pipeline.from_preset("snap.va", profile_strategy="realistic", census_years=2022, match_census_year=False)
        assert {c.metadata["fiscal_year"] for c in p.generate(n=30, seed=7)} == {2026}

    def test_generator_without_support_rejects_fixed_policy_year(self) -> None:
        from govsynth.pipeline import Pipeline

        with pytest.raises(ValueError, match="match_census_year"):
            Pipeline.from_preset("wic.national", match_census_year=False)

    def test_cli_flag(self) -> None:
        from govsynth.cli.main import app
        from typer.testing import CliRunner

        args = [
            "generate",
            "snap.va",
            "-n",
            "2",
            "--seed",
            "1",
            "-s",
            "realistic",
            "--census-year",
            "2022",
            "-f",
            "yaml",
        ]
        follow = CliRunner().invoke(app, args)
        fixed = CliRunner().invoke(app, [*args, "--fixed-policy-year"])
        assert follow.exit_code == 0 and fixed.exit_code == 0, follow.output + fixed.output
        assert "FY2022" in follow.stdout and "FY2026" not in follow.stdout
        assert "FY2026" in fixed.stdout
