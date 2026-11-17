"""Tests for selecting which ACS release ("vintage") realistic profiles come from."""

from __future__ import annotations

import json
import warnings
from collections import Counter
from pathlib import Path

import httpx
import pytest
import respx
from govsynth.cli.main import app
from govsynth.generators.snap_eligibility import SNAPEligibilityGenerator
from govsynth.pipeline import Pipeline
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.sources.us import census_fetcher as cf
from govsynth.sources.us.census import (
    DEFAULT_CENSUS_VINTAGE,
    CensusDataSource,
    CensusVintage,
    available_vintages,
    census_years_for_strategy,
    check_census_available,
    normalize_census_years,
    parse_census_years,
    vintage_dir,
)
from typer.testing import CliRunner

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "census_va.json"

A5 = "acs5"
A1 = "acs1"


def _seed(root: Path, vintage: CensusVintage, state: str = "va", **overrides: float) -> None:
    """Write the VA fixture as `state` under `vintage`, overriding demographics fields."""
    data = json.loads(_FIXTURE.read_text())
    data["demographics"].update(overrides)
    d = vintage_dir(vintage, root)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{state}.json").write_text(json.dumps(data))


class TestParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (2023, CensusVintage(A5, 2023)),
            ("2023", CensusVintage(A5, 2023)),
            ("acs1-2025", CensusVintage(A1, 2025)),
            ("ACS1:2025", CensusVintage(A1, 2025)),
            ("acs5 2021", CensusVintage(A5, 2021)),
            (CensusVintage(A1, 2022), CensusVintage(A1, 2022)),
        ],
    )
    def test_parse(self, value: object, expected: CensusVintage) -> None:
        assert CensusVintage.parse(value) == expected  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", ["acs3-2023", "23", "latest", "2023-2024"])
    def test_parse_rejects_malformed(self, bad: str) -> None:
        with pytest.raises(ValueError):
            CensusVintage.parse(bad)

    def test_label_round_trips(self) -> None:
        v = CensusVintage(A1, 2025)
        assert v.label == "acs1-2025"
        assert CensusVintage.parse(v.label) == v

    def test_spec_ranges_lists_and_dedup(self) -> None:
        assert parse_census_years("2021-2023, acs1-2025, 2022") == [
            CensusVintage(A5, 2021),
            CensusVintage(A5, 2022),
            CensusVintage(A5, 2023),
            CensusVintage(A1, 2025),
        ]
        assert parse_census_years("acs1-2023-2024") == [CensusVintage(A1, 2023), CensusVintage(A1, 2024)]

    def test_spec_rejects_reversed_range_and_empty(self) -> None:
        with pytest.raises(ValueError, match="ends before"):
            parse_census_years("2024-2021")
        with pytest.raises(ValueError):
            parse_census_years(" , ")

    def test_normalize_accepts_mixed_inputs(self) -> None:
        assert normalize_census_years(None) is None
        assert normalize_census_years(2022) == [CensusVintage(A5, 2022)]
        assert normalize_census_years(["2021-2022", 2024, "acs1-2025"]) == [
            CensusVintage(A5, 2021),
            CensusVintage(A5, 2022),
            CensusVintage(A5, 2024),
            CensusVintage(A1, 2025),
        ]
        with pytest.raises(ValueError):
            normalize_census_years([])

    def test_years_only_apply_to_realistic(self) -> None:
        assert census_years_for_strategy(None, "edge_saturated") is None
        with pytest.raises(ValueError, match="realistic"):
            census_years_for_strategy(2023, "edge_saturated")


class TestLoading:
    def test_loads_requested_vintage_and_tags_it(self, tmp_path: Path) -> None:
        _seed(tmp_path, CensusVintage(A5, 2021), pct_with_children=0.11)
        _seed(tmp_path, CensusVintage(A1, 2025), pct_with_children=0.22)
        old = CensusDataSource("VA", vintage=2021, data_dir=tmp_path).load()
        new = CensusDataSource("VA", vintage="acs1-2025", data_dir=tmp_path).load()
        assert old is not None and new is not None
        assert (old.pct_with_children, old.vintage) == (0.11, "acs5-2021")
        assert (new.pct_with_children, new.vintage) == (0.22, "acs1-2025")

    def test_default_vintage_used_when_none_requested(self, tmp_path: Path) -> None:
        _seed(tmp_path, DEFAULT_CENSUS_VINTAGE)
        dist = CensusDataSource("VA", data_dir=tmp_path).load()
        assert dist is not None and dist.vintage == DEFAULT_CENSUS_VINTAGE.label

    def test_explicit_missing_vintage_raises_with_guidance(self, tmp_path: Path) -> None:
        _seed(tmp_path, CensusVintage(A5, 2022))
        with pytest.raises(ValueError) as exc:
            CensusDataSource("VA", vintage=2019, data_dir=tmp_path).load()
        msg = str(exc.value)
        assert "acs5-2019" in msg and "acs5-2022" in msg and "refresh-census-data" in msg

    def test_missing_state_uses_same_vintage_national(self, tmp_path: Path) -> None:
        _seed(tmp_path, CensusVintage(A5, 2023), state="national", pct_with_children=0.33)
        _seed(tmp_path, CensusVintage(A5, 2024), state="national", pct_with_children=0.44)
        with pytest.warns(UserWarning, match="acs5-2023"):
            dist = CensusDataSource("MD", vintage=2023, data_dir=tmp_path).load()
        assert dist is not None and dist.pct_with_children == 0.33

    def test_available_vintages_sorted(self, tmp_path: Path) -> None:
        for v in [CensusVintage(A1, 2025), CensusVintage(A5, 2021), CensusVintage(A5, 2024)]:
            _seed(tmp_path, v)
        (tmp_path / "acs5" / "2030").mkdir(parents=True)  # empty dir is not a vintage
        assert [v.label for v in available_vintages(tmp_path)] == ["acs5-2021", "acs5-2024", "acs1-2025"]

    def test_check_census_available(self, tmp_path: Path) -> None:
        _seed(tmp_path, CensusVintage(A5, 2023))
        _seed(tmp_path, CensusVintage(A5, 2024), state="national")
        check_census_available("VA", [CensusVintage(A5, 2023), CensusVintage(A5, 2024)], tmp_path)
        with pytest.raises(ValueError, match="acs5-2021"):
            check_census_available("VA", [CensusVintage(A5, 2021)], tmp_path)


class TestBundledData:
    def test_default_vintage_is_bundled(self) -> None:
        assert (vintage_dir(DEFAULT_CENSUS_VINTAGE) / "va.json").exists()
        assert (vintage_dir(DEFAULT_CENSUS_VINTAGE) / "national.json").exists()

    @pytest.mark.parametrize("vintage", available_vintages())
    def test_each_bundled_vintage_metadata_matches_its_directory(self, vintage: CensusVintage) -> None:
        for path in vintage_dir(vintage).glob("*.json"):
            meta = json.loads(path.read_text())["_metadata"]
            assert (meta["acs_survey"], meta["acs_vintage"]) == (vintage.survey, vintage.year), path


class TestProfiles:
    def test_realistic_profile_records_vintage(self) -> None:
        p = USHouseholdProfile.random(state="VA", seed=1, strategy="realistic", census_vintage="acs5-2021")
        assert p.census_vintage == "acs5-2021"
        assert "census_vintage" not in p.to_scenario_fields()

    def test_default_vintage_recorded(self) -> None:
        p = USHouseholdProfile.random(state="VA", seed=1, strategy="realistic")
        assert p.census_vintage == DEFAULT_CENSUS_VINTAGE.label

    def test_vintage_changes_the_population(self) -> None:
        """Same seeds, different years -> different incomes (2021 vs 2025 dollars and distribution)."""
        old = [
            USHouseholdProfile.random("VA", seed=i, strategy="realistic", census_vintage="acs1-2021")
            for i in range(200)
        ]
        new = [
            USHouseholdProfile.random("VA", seed=i, strategy="realistic", census_vintage="acs1-2025")
            for i in range(200)
        ]
        assert sum(p.monthly_gross_income for p in new) > sum(p.monthly_gross_income for p in old)

    def test_vintage_with_non_realistic_strategy_raises(self) -> None:
        with pytest.raises(ValueError, match="realistic"):
            USHouseholdProfile.random(state="VA", seed=1, strategy="uniform", census_vintage=2023)


class TestGenerators:
    def test_snap_spreads_years_round_robin_and_records_them(self) -> None:
        gen = SNAPEligibilityGenerator(state="VA")
        cases = gen.generate(n=9, profile_strategy="realistic", seed=42, census_years="2022-2024")
        assert [c.metadata["census_vintage"] for c in cases] == ["acs5-2022", "acs5-2023", "acs5-2024"] * 3

    def test_snap_multi_year_is_deterministic(self) -> None:
        gen = SNAPEligibilityGenerator(state="VA")
        a = gen.generate(n=8, profile_strategy="realistic", seed=42, census_years=[2021, "acs1-2025"])
        b = gen.generate(n=8, profile_strategy="realistic", seed=42, census_years=[2021, "acs1-2025"])
        assert [c.case_id for c in a] == [c.case_id for c in b]

    def test_snap_rejects_years_for_edge_saturated(self) -> None:
        with pytest.raises(ValueError, match="realistic"):
            SNAPEligibilityGenerator(state="VA").generate(n=2, profile_strategy="edge_saturated", census_years=2023)


class TestPipeline:
    def test_years_are_balanced_across_batches(self) -> None:
        """Pipeline generates in batches of 25; the year rotation must carry across batches."""
        pipeline = Pipeline.from_preset("snap.va", profile_strategy="realistic", census_years="2021-2024")
        cases = pipeline.generate(n=60, seed=7)
        counts = Counter(c.metadata["census_vintage"] for c in cases)
        assert counts == {"acs5-2021": 15, "acs5-2022": 15, "acs5-2023": 15, "acs5-2024": 15}

    def test_missing_vintage_fails_before_generating(self) -> None:
        with pytest.raises(ValueError, match="acs5-2015"):
            Pipeline.from_preset("snap.va", profile_strategy="realistic", census_years=2015)

    def test_generator_without_census_support_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not support census_years"):
            Pipeline.from_preset("medicaid.va", profile_strategy="realistic", census_years=2023)

    def test_years_require_realistic(self) -> None:
        with pytest.raises(ValueError, match="realistic"):
            Pipeline.from_preset("snap.va", census_years=2023)


class TestGenerateCli:
    runner = CliRunner()

    def test_census_year_flag(self) -> None:
        result = self.runner.invoke(
            app,
            ["generate", "snap.va", "-n", "4", "--seed", "1", "-s", "realistic", "--census-year", "2023",
             "--census-year", "acs1-2025", "-f", "jsonl", "--json"],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        lines = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        assert [c["metadata"]["census_vintage"] for c in lines] == ["acs5-2023", "acs1-2025"] * 2

    def test_bad_census_year_exits_two(self) -> None:
        result = self.runner.invoke(app, ["generate", "snap.va", "-s", "realistic", "--census-year", "1999"])
        assert result.exit_code == 2


class TestSummaryFileFetch:
    def _dat(self, table: str, rows: dict[str, int]) -> str:
        """Fake summary file: header + one line per GEO_ID; every estimate = value."""
        vars_ = sorted({v for vs in cf._TABLE_GROUPS.values() for v in vs if v.startswith(table + "_")})
        cols = [f"{table}_E{v.split('_')[1][:3]}" for v in vars_]
        header = "|".join(["GEO_ID", *[c for col in cols for c in (col, col.replace("_E", "_M"))]])
        lines = [header]
        lines.append("|".join(["0100000US", *["9"] * (2 * len(cols))]))  # national comes first
        lines.extend("|".join([geo, *[str(val)] * (2 * len(cols))]) for geo, val in rows.items())
        lines.append("|".join(["1400000US51001000100", *["1"] * (2 * len(cols))]))  # a tract, ignored
        return "\n".join(lines) + "\n"

    @respx.mock
    def test_streams_each_table_once_for_all_states(self) -> None:
        tables = sorted({v.split("_")[0] for vs in cf._TABLE_GROUPS.values() for v in vs})
        routes = {
            t: respx.get(cf._summary_file_url(t, 2024, "acs5")).mock(
                return_value=httpx.Response(200, text=self._dat(t, {"0400000US51": 5, "0400000US24": 7}))
            )
            for t in tables
        }
        out = cf.fetch_states_summary_file(["VA", "MD", "NATIONAL"], 2024, "acs5")
        assert all(r.call_count == 1 for r in routes.values())
        assert set(out) == {"VA", "MD", "NATIONAL"}
        header, values = out["VA"]["income"]
        assert header == cf.INCOME_VARS and set(values) == {"5"}
        assert set(out["MD"]["health"][1]) == {"7"}
        assert set(out["NATIONAL"]["poverty"][1]) == {"9"}

    @respx.mock
    def test_missing_state_row_raises(self) -> None:
        respx.get(url__regex=r".*\.dat").mock(side_effect=lambda req: httpx.Response(200, text=self._dat(
            req.url.path.rsplit("-", 1)[1].removesuffix(".dat").upper(), {})))  # fmt: skip
        with pytest.raises(ValueError, match="No row for VA"):
            cf.fetch_states_summary_file(["VA"], 2024, "acs5")

    def test_url_shapes(self) -> None:
        assert cf._summary_file_url("B19001", 2025, "acs1").endswith(
            "/2025/table-based-SF/data/1YRData/acsdt1y2025-b19001.dat"
        )
        assert cf._summary_file_url("C27007", 2024, "acs5").endswith("/5YRData/acsdt5y2024-c27007.dat")
        assert cf._sf_column_to_api_var("B19001_E002") == "B19001_002E"
        assert cf._sf_column_to_api_var("B19001_M002") is None


def test_warning_free_default_path() -> None:
    """The bundled default vintage has VA data, so the common path emits no fallback warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        USHouseholdProfile.random(state="VA", seed=3, strategy="realistic")


class TestFormatters:
    def test_vintage_survives_export_and_is_absent_otherwise(self) -> None:
        import yaml
        from govsynth.formatters.csv_fmt import CSVFormatter
        from govsynth.formatters.jsonl import JSONLFormatter
        from govsynth.formatters.yaml_fmt import YAMLFormatter

        gen = SNAPEligibilityGenerator(state="VA")
        realistic = gen.generate(n=1, profile_strategy="realistic", seed=5, census_years="acs1-2025")[0]
        edge = gen.generate(n=1, profile_strategy="edge_saturated", seed=5)[0]

        assert yaml.safe_load(YAMLFormatter().format_one(realistic))["census_vintage"] == "acs1-2025"
        assert JSONLFormatter().format_one(realistic)["metadata"]["census_vintage"] == "acs1-2025"
        assert CSVFormatter().format_row(realistic)["census_vintage"] == "acs1-2025"

        assert "census_vintage" not in yaml.safe_load(YAMLFormatter().format_one(edge))
        assert "census_vintage" not in JSONLFormatter().format_one(edge)["metadata"]
        assert CSVFormatter().format_row(edge)["census_vintage"] == ""
