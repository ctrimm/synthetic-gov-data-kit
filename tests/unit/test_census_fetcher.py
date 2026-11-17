"""Unit tests for the Census Bureau ACS data fetcher.

Network-only module: all Census API calls are mocked with respx so these
tests never hit the network.
"""

import json
import math
from pathlib import Path

import httpx
import pytest
import respx
from govsynth.sources.us import census_fetcher as cf
from govsynth.sources.us.census_fetcher import (
    FIPS_CODES,
    _get,
    _safe_int,
    _safe_rate,
    build_state_census_json,
    fetch_state,
    write_state_file,
)


class TestSafeHelpers:
    def test_safe_int_parses_valid_string(self) -> None:
        assert _safe_int("42") == 42

    def test_safe_int_negative_clamps_to_zero(self) -> None:
        assert _safe_int("-5") == 0

    def test_safe_int_non_numeric_returns_zero(self) -> None:
        assert _safe_int("null") == 0

    def test_safe_rate_normal(self) -> None:
        assert _safe_rate(25, 100) == 0.25

    def test_safe_rate_zero_denominator(self) -> None:
        assert _safe_rate(25, 0) == 0.0


class TestGet:
    @respx.mock
    def test_get_returns_parsed_json_rows(self) -> None:
        url = "https://api.census.gov/data/2022/acs/acs5"
        respx.get(url).mock(return_value=httpx.Response(200, json=[["NAME", "B01001_001E"], ["Virginia", "8600000"]]))
        with httpx.Client() as client:
            rows = _get(client, url, {"get": "B01001_001E", "for": "state:51"})
        assert rows == [["NAME", "B01001_001E"], ["Virginia", "8600000"]]

    @respx.mock
    def test_get_raises_on_http_error(self) -> None:
        url = "https://api.census.gov/data/2022/acs/acs5"
        respx.get(url).mock(return_value=httpx.Response(500))
        with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
            _get(client, url, {"get": "B01001_001E", "for": "state:51"})


class TestFetchState:
    @respx.mock
    def test_fetch_state_makes_six_requests_and_returns_all_tables(self) -> None:
        url = "https://api.census.gov/data/2022/acs/acs5"
        route = respx.get(url).mock(return_value=httpx.Response(200, json=[["header"], ["1"]]))
        result = fetch_state("VA", 2022, api_key=None)
        assert route.call_count == 6
        assert set(result.keys()) == {
            "income",
            "poverty",
            "housing",
            "demographics",
            "income_sources",
            "health",
        }

    def test_fetch_state_unknown_state_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            fetch_state("ZZ", 2022, api_key=None)

    def test_all_state_fips_codes_are_two_digits(self) -> None:
        for code in FIPS_CODES.values():
            assert len(code) == 2 and code.isdigit()


def _table_row(header: list[str], values: dict[str, str]) -> list[list[str]]:
    """Build a [header, value] Census API row pair for the given var->value map."""
    row = [values.get(h, "0") for h in header]
    return [header, row]


def _raw(values: dict[str, str]) -> dict[str, list[list[str]]]:
    """Build a full fetch_state()-shaped response; unspecified variables are 0."""
    return {
        "income": _table_row(cf.INCOME_VARS, values),
        "poverty": _table_row(cf.POVERTY_VARS, values),
        "housing": _table_row(cf.HOUSING_VARS, values),
        "demographics": _table_row(cf.DEMOGRAPHIC_VARS, values),
        "income_sources": _table_row(cf.INCOME_SOURCE_VARS, values),
        "health": _table_row(cf.HEALTH_VARS, values),
    }


# Counts chosen so every derived rate has a hand-checkable expected value.
_BASE_VALUES: dict[str, str] = {
    # B19001: 100 households in every bracket
    **{v: "100" for v in cf.INCOME_VARS},
    # C17002: persons by ratio of income to poverty, total 1000
    "C17002_001E": "1000",
    "C17002_002E": "50",
    "C17002_003E": "50",
    "C17002_004E": "30",
    "C17002_005E": "30",
    "C17002_006E": "40",
    "C17002_007E": "20",
    "C17002_008E": "780",
    # Housing
    "B25064_001E": "1450",
    "B25070_001E": "2100",
    "B25070_007E": "100",
    "B25070_008E": "100",
    "B25070_009E": "100",
    "B25070_010E": "100",
    "B25070_011E": "100",  # not computed -> excluded from the base (2000)
    "B25003_001E": "8000",
    "B25003_003E": "3000",
    # B25007: 100 owner + 100 renter householders aged 35-44 and 65-74
    "B25007_001E": "400",
    "B25007_005E": "100",
    "B25007_015E": "100",
    "B25007_009E": "100",
    "B25007_019E": "100",
    # B11016 household size
    "B11016_001E": "1000",
    "B11016_010E": "300",  # 1-person
    "B11016_003E": "250",  # family 2
    "B11016_011E": "50",  # nonfamily 2
    "B11016_004E": "150",  # family 3
    "B11016_005E": "120",  # family 4
    "B11016_013E": "10",  # nonfamily 4
    "B11016_006E": "60",  # family 5
    "B11016_007E": "30",  # family 6
    "B11016_008E": "20",  # family 7+
    "B11016_016E": "10",  # nonfamily 7+
    # B11005: households with someone under 18
    "B11005_001E": "1000",
    "B11005_002E": "300",
    # B11006: households with someone 60+
    "B11006_001E": "1000",
    "B11006_002E": "400",
    # B22010: households with a person with a disability (SNAP + non-SNAP)
    "B22010_001E": "1000",
    "B22010_003E": "50",
    "B22010_006E": "150",
    # B05001: citizenship (naturalized citizens are not listed separately)
    "B05001_001E": "1000",
    "B05001_006E": "50",
    # Income sources
    "B22003_001E": "1000",
    "B22003_002E": "80",
    "B23025_001E": "1000",
    "B23025_002E": "650",
    "B19051_001E": "1000",
    "B19051_002E": "790",
    "B19055_001E": "1000",
    "B19055_002E": "300",
    "B19056_001E": "1000",
    "B19056_002E": "40",
    "B19057_001E": "1000",
    "B19057_002E": "20",
    # C27007: Medicaid / means-tested coverage, 6 x 25 = 150 of 1000
    "C27007_001E": "1000",
    **{v: "25" for v in ["C27007_004E", "C27007_007E", "C27007_010E", "C27007_014E", "C27007_017E", "C27007_020E"]},
}


@pytest.fixture
def raw_census_response() -> dict[str, list[list[str]]]:
    return _raw(_BASE_VALUES)


@pytest.fixture
def built(raw_census_response: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr("govsynth.sources.us.census_fetcher.fetch_state", lambda *a, **kw: raw_census_response)
    return build_state_census_json("VA", year=2022, api_key=None)


class TestVariableSelection:
    """Pin which ACS tables feed each concept.

    Each of these previously pointed at a different table than its name implied
    (B17024 under-6 rows for FPL buckets, B11003 married-couple rows for
    children, B27001 any-insurance rows for Medicaid).
    """

    def test_each_request_is_under_census_variable_limit(self) -> None:
        for group in (
            cf.INCOME_VARS,
            cf.POVERTY_VARS,
            cf.HOUSING_VARS,
            cf.DEMOGRAPHIC_VARS,
            cf.INCOME_SOURCE_VARS,
            cf.HEALTH_VARS,
        ):
            assert len(group) <= 50
            assert len(group) == len(set(group))

    def test_mislabeled_tables_are_not_requested(self) -> None:
        all_vars = (
            cf.INCOME_VARS
            + cf.POVERTY_VARS
            + cf.HOUSING_VARS
            + cf.DEMOGRAPHIC_VARS
            + cf.INCOME_SOURCE_VARS
            + cf.HEALTH_VARS
        )
        for table in ("B17024", "B11003", "B27001"):
            assert not [v for v in all_vars if v.startswith(table)], table

    def test_income_bracket_edges_match_acs_b19001(self) -> None:
        # B19001_011E..017E per the ACS variable list.
        assert cf._INCOME_BRACKETS[9:] == [
            (50_000, 60_000),
            (60_000, 75_000),
            (75_000, 100_000),
            (100_000, 125_000),
            (125_000, 150_000),
            (150_000, 200_000),
            (200_000, None),
        ]
        assert cf._INCOME_BRACKET_LABELS[-1] == "$200,000 or more"
        assert len(cf._INCOME_BRACKETS) == len(cf._INCOME_BRACKET_LABELS) == len(cf.INCOME_VARS) == 16


class TestDerivedValues:
    def test_income_buckets_use_corrected_midpoints(self, built: dict) -> None:
        buckets = built["income"]["buckets_raw"]
        assert buckets[9]["annual_midpoint"] == 55_000
        assert buckets[14]["annual_midpoint"] == 175_000
        # Equal 150-200k and 200k+ counts -> alpha = ln 2 / ln(4/3) ~ 2.41
        # -> 200k * exp(1/alpha) ~ 303k.
        assert buckets[15]["annual_midpoint"] == pytest.approx(303_000, rel=0.01)

    def test_top_bracket_falls_back_when_counts_are_zero(self) -> None:
        assert cf._top_bracket_representative(0, 0) == round(200_000 * math.exp(1 / cf._DEFAULT_PARETO_ALPHA))

    def test_fpl_buckets_come_from_c17002(self, built: dict) -> None:
        fpl = built["income"]["fpl_buckets"]
        assert [b["fpl_pct"] for b in fpl] == [0.5, 1.0, 1.25, 1.5, 1.85, 2.0, None]
        assert [b["weight"] for b in fpl] == [0.05, 0.05, 0.03, 0.03, 0.04, 0.02, 0.78]
        assert sum(b["weight"] for b in fpl) == pytest.approx(1.0)

    def test_pct_with_children_is_share_of_all_households(self, built: dict) -> None:
        assert built["demographics"]["pct_with_children"] == 0.3

    def test_naturalized_citizens_count_as_citizens(self, built: dict) -> None:
        dem = built["demographics"]
        assert dem["pct_citizen"] == 0.95
        assert dem["pct_noncitizen"] == 0.05
        assert dem["pct_noncitizen_eligible"] == round(0.05 * cf._NONCITIZEN_QUALIFIED_SHARE, 4)
        assert dem["pct_citizen"] + dem["pct_noncitizen"] == pytest.approx(1.0)

    def test_elderly_or_disabled_is_household_union(self, built: dict) -> None:
        dem = built["demographics"]
        assert dem["pct_households_60_plus"] == 0.4
        assert dem["pct_households_with_disability"] == 0.2
        assert dem["pct_elderly_or_disabled"] == pytest.approx(0.4 + 0.2 - 0.4 * 0.2)

    def test_household_size_six_plus_includes_seven_or_more(self, built: dict) -> None:
        # 1:300, 2:300, 3:150, 4:130, 5:60, 6+:30+20+10=60 over 1000
        assert built["household_size"]["weights"] == [0.3, 0.3, 0.15, 0.13, 0.06, 0.06]

    def test_householder_age_fitted_from_b25007(self, built: dict) -> None:
        age = built["demographics"]["age"]
        assert age["mu"] == pytest.approx(55.0)  # half at 40, half at 70
        assert age["sigma"] == pytest.approx(15.0)

    def test_medicaid_rate_uses_c27007(self, built: dict) -> None:
        assert built["program_participation"]["medicaid_coverage_rate"] == 0.15

    def test_household_earnings_and_lfpr_are_distinct(self, built: dict) -> None:
        isrc = built["income_sources"]
        assert isrc["pct_households_with_earnings"] == 0.79
        assert isrc["labor_force_participation_rate"] == 0.65

    def test_rent_burden_excludes_not_computed(self, built: dict) -> None:
        assert built["housing"]["rent_burden_pct"] == 0.2


class TestBuildStateCensusJson:
    def test_builds_expected_top_level_shape(self, raw_census_response: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("govsynth.sources.us.census_fetcher.fetch_state", lambda *a, **kw: raw_census_response)
        data = build_state_census_json("VA", year=2022, api_key=None)
        assert data["_metadata"]["state"] == "VA"
        assert data["_metadata"]["acs_vintage"] == 2022
        assert set(data.keys()) == {
            "_metadata",
            "income",
            "housing",
            "household_size",
            "demographics",
            "income_sources",
            "program_participation",
        }

    def test_household_size_weights_sum_to_one(
        self, raw_census_response: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("govsynth.sources.us.census_fetcher.fetch_state", lambda *a, **kw: raw_census_response)
        data = build_state_census_json("VA", year=2022, api_key=None)
        weights = data["household_size"]["weights"]
        assert len(weights) == 6
        assert sum(weights) == pytest.approx(1.0, abs=0.001)

    def test_rates_are_between_zero_and_one(self, raw_census_response: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("govsynth.sources.us.census_fetcher.fetch_state", lambda *a, **kw: raw_census_response)
        data = build_state_census_json("VA", year=2022, api_key=None)
        for key in (
            "pct_citizen",
            "pct_noncitizen",
            "pct_noncitizen_eligible",
            "pct_with_children",
            "pct_elderly_or_disabled",
        ):
            assert 0.0 <= data["demographics"][key] <= 1.0
        for key in ("labor_force_participation_rate", "pct_social_security"):
            assert 0.0 <= data["income_sources"][key] <= 1.0

    def test_output_matches_govsynth_census_data_source_schema(
        self, raw_census_response: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The built dict must be loadable by CensusDataSource._parse."""
        from govsynth.sources.us.census import CensusDataSource

        monkeypatch.setattr("govsynth.sources.us.census_fetcher.fetch_state", lambda *a, **kw: raw_census_response)
        data = build_state_census_json("VA", year=2022, api_key=None)
        write_state_file("VA", data, tmp_path)
        dist = CensusDataSource("VA", data_dir=tmp_path).load()
        assert dist is not None
        assert dist.state == "VA"


class TestWriteStateFile:
    def test_writes_valid_json_and_returns_path(self, tmp_path: Path) -> None:
        data = {"_metadata": {"state": "VA"}}
        path = write_state_file("VA", data, tmp_path)
        assert path == tmp_path / "va.json"
        assert json.loads(path.read_text()) == data

    def test_does_not_leave_tmp_file_behind(self, tmp_path: Path) -> None:
        write_state_file("VA", {"a": 1}, tmp_path)
        assert not (tmp_path / "va.json.tmp").exists()

    def test_creates_missing_directory(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "nested" / "census"
        write_state_file("TX", {"a": 1}, target_dir)
        assert (target_dir / "tx.json").exists()
