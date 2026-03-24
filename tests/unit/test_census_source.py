"""Unit tests for CensusDataSource and CensusDistribution."""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from govsynth.sources.us.census import CensusDataSource, CensusDistribution

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "census_va.json"


@pytest.fixture
def census_dir(tmp_path: Path) -> Path:
    """Temp directory seeded with the VA fixture."""
    (tmp_path / "va.json").write_text(_FIXTURE.read_text())
    return tmp_path


class TestCensusDataSourceLoad:
    def test_loads_fixture_returns_distribution(self, census_dir: Path) -> None:
        dist = CensusDataSource("VA", data_dir=census_dir).load()
        assert dist is not None
        assert isinstance(dist, CensusDistribution)

    def test_state_field_is_uppercase(self, census_dir: Path) -> None:
        dist = CensusDataSource("VA", data_dir=census_dir).load()
        assert dist is not None
        assert dist.state == "VA"

    def test_income_fields(self, census_dir: Path) -> None:
        dist = CensusDataSource("VA", data_dir=census_dir).load()
        assert dist is not None
        assert dist.income_mu == pytest.approx(8.1)
        assert dist.income_sigma == pytest.approx(0.65)
        assert isinstance(dist.fpl_buckets, list)
        assert len(dist.fpl_buckets) == 4

    def test_household_size_weights(self, census_dir: Path) -> None:
        dist = CensusDataSource("VA", data_dir=census_dir).load()
        assert dist is not None
        assert len(dist.household_size_weights) == 6
        assert abs(sum(dist.household_size_weights) - 1.0) < 0.01

    def test_housing_fields(self, census_dir: Path) -> None:
        dist = CensusDataSource("VA", data_dir=census_dir).load()
        assert dist is not None
        assert dist.median_gross_rent_monthly == pytest.approx(1450)
        assert dist.pct_renter == pytest.approx(0.36)

    def test_demographics_fields(self, census_dir: Path) -> None:
        dist = CensusDataSource("VA", data_dir=census_dir).load()
        assert dist is not None
        assert dist.pct_with_children == pytest.approx(0.32)
        assert dist.pct_elderly_or_disabled == pytest.approx(0.18)
        assert dist.pct_citizen == pytest.approx(0.87)
        assert dist.pct_noncitizen_eligible == pytest.approx(0.05)
        assert dist.age_mu == pytest.approx(42)
        assert dist.age_sigma == pytest.approx(15)

    def test_income_sources_fields(self, census_dir: Path) -> None:
        dist = CensusDataSource("VA", data_dir=census_dir).load()
        assert dist is not None
        assert dist.labor_force_participation_rate == pytest.approx(0.67)
        assert dist.pct_social_security == pytest.approx(0.19)
        assert dist.pct_ssi == pytest.approx(0.03)
        assert dist.pct_public_assistance == pytest.approx(0.02)

    def test_program_participation_fields(self, census_dir: Path) -> None:
        dist = CensusDataSource("VA", data_dir=census_dir).load()
        assert dist is not None
        assert dist.snap_receipt_rate == pytest.approx(0.08)
        assert dist.medicaid_coverage_rate == pytest.approx(0.18)

    def test_case_insensitive_state(self, census_dir: Path) -> None:
        dist = CensusDataSource("va", data_dir=census_dir).load()
        assert dist is not None

    def test_missing_state_emits_warning(self, census_dir: Path) -> None:
        # census_dir contains only va.json (no national.json), so load() returns None
        # after warning. See test_missing_state_falls_back_to_national for the case
        # where national.json exists.
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = CensusDataSource("ZZ", data_dir=census_dir).load()
        assert result is None
        assert any("No census data for 'ZZ'" in str(warning.message) for warning in w)

    def test_missing_state_falls_back_to_national(self, tmp_path: Path) -> None:
        """If state file missing but national.json present, return national dist + warn."""
        data = json.loads(_FIXTURE.read_text())
        data["_metadata"]["state"] = "national"
        (tmp_path / "national.json").write_text(json.dumps(data))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = CensusDataSource("MD", data_dir=tmp_path).load()

        assert result is not None
        assert any("No census data for 'MD'" in str(warning.message) for warning in w)

    def test_national_missing_returns_none(self, tmp_path: Path) -> None:
        """No state file, no national.json -> None (no exception)."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = CensusDataSource("TX", data_dir=tmp_path).load()
        assert result is None
