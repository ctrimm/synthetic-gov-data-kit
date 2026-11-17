"""Tests for #11: CPI-U restatement of census incomes and no pile-up at the cap."""

from __future__ import annotations

from collections import Counter

import pytest
from govsynth.generators.medicaid_eligibility import MedicaidEligibilityGenerator
from govsynth.generators.snap_eligibility import SNAPEligibilityGenerator
from govsynth.profiles.us_household import _REALISTIC_INCOME_CAP, USHouseholdProfile
from govsynth.sources.us.cpi import cpi_annual_average, inflation_factor


def test_cpi_values() -> None:
    """BLS CPI-U annual averages (complete years)."""
    assert cpi_annual_average(2022) == 292.655
    assert cpi_annual_average(2024) == 313.689
    assert inflation_factor(2024, 2024) == 1.0
    assert inflation_factor(2022, 2024) == pytest.approx(313.689 / 292.655)
    with pytest.raises(ValueError, match="No CPI-U"):
        cpi_annual_average(1999)


def test_partial_years_are_flagged() -> None:
    import json
    from pathlib import Path

    annual = json.loads((Path(__file__).parents[2] / "data" / "thresholds" / "cpi_u_annual.json").read_text())["annual"]
    assert annual["2025"]["complete"] is False and annual["2025"]["missing_months"] == ["2025-10"]
    assert all(annual[str(y)]["complete"] for y in range(2019, 2025))


def test_no_pile_up_at_the_cap() -> None:
    incomes = [USHouseholdProfile.random("VA", seed=i, strategy="realistic").monthly_gross_income for i in range(4000)]
    assert max(incomes) <= _REALISTIC_INCOME_CAP
    assert Counter(incomes).most_common(1)[0][1] / len(incomes) < 0.01  # was ~21% at exactly $15,000
    assert sum(i > 15_000 for i in incomes) > 0  # the old clamp no longer truncates the top


def test_income_restated_in_the_requested_year() -> None:
    base = USHouseholdProfile.random("VA", seed=3, strategy="realistic", census_vintage=2022)
    restated = USHouseholdProfile.random(
        "VA", seed=3, strategy="realistic", census_vintage=2022, income_dollar_year=2024
    )
    assert base.income_dollar_year == 2022 and restated.income_dollar_year == 2024
    assert restated.monthly_gross_income == pytest.approx(
        base.monthly_gross_income * inflation_factor(2022, 2024), abs=10
    )
    with pytest.raises(ValueError, match="income_dollar_year"):
        USHouseholdProfile.random("VA", seed=1, strategy="uniform", income_dollar_year=2026)


def test_generators_record_and_apply_the_dollar_year() -> None:
    snap = SNAPEligibilityGenerator(state="VA")
    matched = snap.generate(n=3, profile_strategy="realistic", seed=1, census_years=2022)
    fixed = snap.generate(n=3, profile_strategy="realistic", seed=1, census_years=2022, match_census_year=False)
    assert {c.metadata["income_dollar_year"] for c in matched} == {2022}  # rules year = census year
    assert {c.metadata["income_dollar_year"] for c in fixed} == {2026}  # restated to FY2026 rules
    medicaid = MedicaidEligibilityGenerator(state="VA").generate(n=3, seed=1, profile_strategy="realistic")
    assert {c.metadata["income_dollar_year"] for c in medicaid} == {2026}
