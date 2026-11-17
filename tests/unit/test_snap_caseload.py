"""Tests for the SNAP caseload population (#9): QC tables, IPF fit, sampler, and plumbing."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from govsynth.evaluation.representativeness import check_caseload
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.sources.us.census_fetcher import FIPS_CODES
from govsynth.sources.us.snap_caseload import caseload_table, load_qc
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[2]
QC = load_qc(2024)
NAT = QC["national"]
TOTAL = NAT["total_households_000"]


def _importer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("import_snap_qc", ROOT / "scripts/import_snap_qc.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestBundledData:
    def test_metadata(self) -> None:
        meta = QC["_metadata"]
        assert meta["fiscal_year"] == 2024
        assert meta["fpl_basis_year"] == 2023
        assert meta["verification_status"] == "verified"
        assert meta["source_url"].startswith("https://")

    def test_every_state_present(self) -> None:
        assert set(QC["states"]) == set(FIPS_CODES)

    def test_published_national_figures(self) -> None:
        # Spot values from the FY2024 report (Tables A.3, A.6, A.17).
        assert TOTAL == 21_595
        assert NAT["pov"]["none"] == 4_153
        assert NAT["income_type"]["ssi"] == 4_770
        assert NAT["kids_by_ed"]["1"]["elderly"] == 230
        assert NAT["size"]["1"] == 13_004

    def test_published_state_figures(self) -> None:
        # Spot values from the FY2024 report (Tables B.2, B.3, B.5, B.6).
        va, dc = QC["states"]["VA"], QC["states"]["DC"]
        assert va["pov4_pct"] == [18.1, 17.4, 39.2, 25.3]
        assert va["pct_children"] == 39.5
        assert dc["pct_tanf"] == 13.8
        assert dc["avg_gross_income"] == 842

    def test_state_shares_are_consistent(self) -> None:
        for code, s in QC["states"].items():
            assert sum(s["pov4_pct"]) == pytest.approx(100, abs=0.6), code
            assert s["pct_elderly_or_disabled"] >= s["pct_elderly"] - 0.6, code


class TestIPF:
    def test_national_table_reproduces_crosstabs(self) -> None:
        us = caseload_table("US")
        for size, groups in NAT["size_by_group"].items():
            for g in ("elderly", "disabled_only"):
                got = us.share(lambda c, s=int(size), g=g: c.size == s and c.group == g)
                assert got == pytest.approx(groups[g] / TOTAL, abs=1e-4)
        for pov, sizes in NAT["pov_by_size"].items():
            for size, v in sizes.items():
                got = us.share(lambda c, p=pov, s=int(size): c.pov == p and c.size == s)
                assert got == pytest.approx(v / TOTAL, abs=1e-4)
        for src, attr in (("earned", "earned"), ("ssi", "ssi"), ("social_security", "social_security")):
            for g in ("elderly", "disabled_only"):
                got = us.share(lambda c, a=attr, g=g: bool(getattr(c, a)) and c.group == g)
                assert got == pytest.approx(NAT["income_type_by_group"][src][g] / TOTAL, abs=1e-4)

    def test_zero_income_cells_have_no_sources(self) -> None:
        for c in caseload_table("US").cells:
            if c.pov == "none":
                assert not (c.earned or c.ssi or c.social_security)

    @pytest.mark.parametrize("state", ["VA", "CA", "DC", "WY"])
    def test_state_table_reproduces_state_margins(self, state: str) -> None:
        t, s = caseload_table(state), QC["states"][state]
        assert t.share(lambda c: c.pov == "none") == pytest.approx(
            s["pov4_pct"][0] / sum(s["pov4_pct"]), abs=1e-4
        )  # published bins can sum to 100.1
        assert t.share(lambda c: bool(c.kids)) == pytest.approx(s["pct_children"] / 100, abs=1e-4)
        assert t.share(lambda c: c.group == "elderly") == pytest.approx(s["pct_elderly"] / 100, abs=1e-4)
        assert t.share(lambda c: bool(c.ssi)) == pytest.approx(s["pct_ssi"] / 100, abs=1e-4)

    def test_state_keeps_national_structure(self) -> None:
        """Raking to state margins keeps the joint structure: elderly households stay mostly one-person."""
        t = caseload_table("VA")
        p_single_given_elderly = t.share(lambda c: c.group == "elderly" and c.size == 1) / t.share(
            lambda c: c.group == "elderly"
        )
        assert p_single_given_elderly > 0.7
        assert t.share(lambda c: bool(c.kids) and c.group == "elderly") < 0.03


class TestSampler:
    @pytest.mark.parametrize("state", sorted(FIPS_CODES))
    def test_profiles_match_qc_targets(self, state: str) -> None:
        bad = [c for c in check_caseload(state, n=1000, seed=42) if not c.ok]
        assert not bad, bad

    def test_check_detects_wrong_targets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A sampler that doesn't follow the QC tables must fail the check."""
        target = caseload_table("VA").qc["states"]["VA"]
        monkeypatch.setitem(target, "pct_ssi", target["pct_ssi"] + 15)
        monkeypatch.setitem(target, "pov4_pct", [8.1, 27.4, 39.2, 25.3])
        bad = {c.metric for c in check_caseload("VA", n=1000, seed=42) if not c.ok}
        assert {"pct_ssi", "pov_bin_zero", "pov_bin_1_50"} <= bad

    def test_caseload_differs_from_general_population(self) -> None:
        def single_share(population: str) -> float:
            ps = [
                USHouseholdProfile.random(state="VA", seed=i, strategy="realistic", population=population)
                for i in range(1500)
            ]
            return sum(p.household_size == 1 for p in ps) / len(ps)

        assert single_share("caseload") > single_share("general") + 0.15

    def test_profile_fields(self) -> None:
        for i in range(500):
            p = USHouseholdProfile.random(state="VA", seed=i, strategy="realistic", population="caseload")
            assert p.household_model == "snap_qc_fy2024"
            assert p.income_dollar_year == 2024
            assert p.earned_income + p.unearned_income == pytest.approx(p.monthly_gross_income)
            assert (p.earned_income > 0) == ("earned" in (p.income_sources or ()))
            if p.household_size == 1:
                assert not p.has_dependent_children
            if p.monthly_gross_income == 0:
                assert p.income_sources == ()

    def test_deterministic(self) -> None:
        a = [
            USHouseholdProfile.random(state="TX", seed=42 + i, strategy="realistic", population="caseload")
            for i in range(30)
        ]
        b = [
            USHouseholdProfile.random(state="TX", seed=42 + i, strategy="realistic", population="caseload")
            for i in range(30)
        ]
        assert [(p.household_size, p.monthly_gross_income, p.income_sources) for p in a] == [
            (p.household_size, p.monthly_gross_income, p.income_sources) for p in b
        ]

    def test_top_bin_calibrated_within_bounds(self) -> None:
        for code in FIPS_CODES:
            assert 140 <= caseload_table(code).top_bin_max_pct <= 400

    def test_rejects_bad_population(self) -> None:
        with pytest.raises(ValueError, match="population must be one of"):
            USHouseholdProfile.random(state="VA", seed=42, strategy="realistic", population="applicants")
        with pytest.raises(ValueError, match="only applies to strategy='realistic'"):
            USHouseholdProfile.random(state="VA", seed=42, strategy="uniform", population="caseload")


class TestGeneratorAndPipeline:
    def test_snap_generator_caseload_is_deterministic(self) -> None:
        from govsynth.generators.snap_eligibility import SNAPEligibilityGenerator

        gen = SNAPEligibilityGenerator(state="VA")
        a = gen.generate(40, profile_strategy="realistic", seed=42, population="caseload")
        b = gen.generate(40, profile_strategy="realistic", seed=42, population="caseload")
        assert [c.case_id for c in a] == [c.case_id for c in b]
        assert {c.metadata["household_model"] for c in a} == {"snap_qc_fy2024"}
        # Mostly-enrolled households: the bulk should come out eligible.
        assert sum(c.expected_outcome == "eligible" for c in a) / len(a) > 0.6

    def test_pipeline_rejects_caseload_for_other_programs(self) -> None:
        from govsynth.pipeline import Pipeline

        with pytest.raises(ValueError, match="caseload data is bundled for SNAP only"):
            Pipeline.from_preset("wic.national", profile_strategy="realistic", population="caseload")
        with pytest.raises(ValueError, match="only applies to profile_strategy='realistic'"):
            Pipeline.from_preset("snap.va", profile_strategy="uniform", population="caseload")

    def test_pipeline_caseload(self) -> None:
        from govsynth.pipeline import Pipeline

        cases = Pipeline.from_preset("snap.va", profile_strategy="realistic", population="caseload").generate(
            30, seed=42
        )
        assert len(cases) == 30
        assert {c.metadata["household_model"] for c in cases} == {"snap_qc_fy2024"}

    def test_cli(self) -> None:
        from govsynth.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["validate-distribution", "--state", "VA", "--population", "caseload", "-n", "500"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            app, ["generate", "snap.va", "-s", "realistic", "--population", "caseload", "-n", "5", "--seed", "42"]
        )
        assert result.exit_code == 0, result.output
        assert "snap.va.eligibility" in result.output


class TestImporterParsing:
    def test_rows_join_wrapped_labels_and_split_on_wide_gaps(self) -> None:
        mod = _importer()
        body = [
            " Gross countable income as a",
            " percentage of poverty guidelines",
            "   No gross income                    4,153      19.2",
            "   1 to 200                             827       3.8",
            " District of",
            " Columbia          24     28.8",
            "   Elderly individuals                    -        ‡",
        ]
        rows = mod._rows(body)
        assert rows[0] == (
            "Gross countable income as a percentage of poverty guidelines No gross income",
            [4153.0, 19.2],
        )
        assert rows[1] == ("1 to 200", [827.0, 3.8])
        assert rows[2] == ("District of Columbia", [24.0, 28.8])
        assert rows[3] == ("Elderly individuals", [0.0, 0.0])
        assert mod._labelled(rows, "No gross income", 2) == [4153.0, 19.2]

    def test_footnote_letter_does_not_eat_real_labels(self) -> None:
        mod = _importer()
        rows = [("Children", [1.0]), ("25 percent or lessd", [2.0])]
        assert mod._labelled(rows, "Children", 1) == [1.0]
        assert mod._labelled(rows, "25 percent or less", 1) == [2.0]
