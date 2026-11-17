"""Unit tests for the Medicaid data source (data/thresholds/medicaid_cy2026.json).

Limits are KFF's January 2026 tables: VA is an expansion state; TX, KS and WI are not;
GA and WI cover other adults to 100% FPL without expansion.
"""

from __future__ import annotations

import json

import pytest
from govsynth._paths import THRESHOLD_DIR
from govsynth.sources.us.census_fetcher import FIPS_CODES
from govsynth.sources.us.medicaid import MedicaidSource, child_age_band

FPL_2026 = {1: 15_960, 2: 21_640, 3: 27_320, 4: 33_000}  # contiguous 48 + DC, annual


def src(state: str) -> MedicaidSource:
    return MedicaidSource(calendar_year=2026, state=state)


class TestBundledTable:
    raw = json.loads((THRESHOLD_DIR / "medicaid_cy2026.json").read_text())

    def test_verified_and_complete(self) -> None:
        assert self.raw["_metadata"]["verification_status"] == "verified"
        assert set(self.raw["states"]) == set(FIPS_CODES)

    def test_expansion_counts_match_kff(self) -> None:
        # KFF: 41 states (including DC) adopted; 10 have not.
        expansion = {s for s, r in self.raw["states"].items() if r["aca_expansion"]}
        assert len(expansion) == 41
        assert set(FIPS_CODES) - expansion == {"AL", "FL", "GA", "KS", "MS", "SC", "TN", "TX", "WI", "WY"}

    @pytest.mark.parametrize("state", ["KS", "WI"])
    def test_kansas_and_wisconsin_are_not_expansion_states(self, state: str) -> None:
        assert src(state).is_expansion_state() is False

    def test_children_match_the_chip_table(self) -> None:
        chip = json.loads((THRESHOLD_DIR / "chip_cy2026.json").read_text())["states"]
        for state, row in self.raw["states"].items():
            for band, pct in row["children_medicaid_pct_fpl"].items():
                c = chip[state]["age_bands"][band]
                top = max([c["medicaid_funded_pct_fpl"], (c["chip_funded_medicaid_pct_fpl"] or {}).get("high", 0)])
                assert pct == top, (state, band)

    def test_published_spot_values(self) -> None:
        s = self.raw["states"]
        assert (s["GA"]["parents_caretakers_pct_fpl"], s["GA"]["other_adults_pct_fpl"]) == (100, 100)
        assert s["TN"]["pregnant_medicaid_pct_fpl"] == 255
        assert s["WY"]["parents_caretakers_pct_fpl"] == 43
        assert s["VA"]["pregnant_medicaid_pct_fpl"] == 143
        assert s["DC"]["other_adults_pct_fpl"] == 138


class TestLimits:
    def test_limit_scales_with_household_size(self) -> None:
        va = src("VA")
        for size, annual in FPL_2026.items():
            assert va.get_income_limit("parent_caretaker", size) == pytest.approx(round(annual * 1.38 / 12, 2))

    def test_expansion_adult_is_138_pct(self) -> None:
        assert src("VA").limit_pct("adult") == 138

    def test_non_expansion_adult_without_coverage_has_no_limit(self) -> None:
        assert src("TX").limit_pct("adult") is None
        assert src("KS").get_income_limit("adult", 1) is None

    @pytest.mark.parametrize("state", ["GA", "WI"])
    def test_georgia_and_wisconsin_cover_adults_to_100_pct(self, state: str) -> None:
        assert src(state).limit_pct("adult") == 100

    def test_pregnant_uses_the_state_medicaid_limit(self) -> None:
        assert src("VA").limit_pct("pregnant") == 143
        assert src("TX").limit_pct("pregnant") == 203

    def test_children_by_age_band(self) -> None:
        tx = src("TX")
        assert [tx.limit_pct("child", age) for age in (0, 3, 12)] == [203, 149, 138]
        assert child_age_band(0) == "0-1" and child_age_band(18) == "6-18"
        with pytest.raises(ValueError):
            child_age_band(19)

    def test_alaska_uses_its_own_poverty_guideline(self) -> None:
        assert src("AK").annual_fpl(1) > src("VA").annual_fpl(1)

    def test_unknown_applicant_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown applicant type"):
            src("VA").limit_pct("not_a_real_type")


class TestIsEligible:
    def test_household_of_four_is_judged_by_its_own_poverty_line(self) -> None:
        # $3,000/month is 109% FPL for 4 people (eligible at 138%) but 226% for 1 person.
        eligible, _ = src("VA").is_eligible(4, 3000.0, "parent_caretaker")
        assert eligible

    def test_limit_is_inclusive_to_the_cent(self) -> None:
        va = src("VA")
        limit = va.get_income_limit("adult", 1)
        assert limit is not None
        assert va.is_eligible(1, limit, "adult")[0]
        assert not va.is_eligible(1, round(limit + 0.01, 2), "adult")[0]

    def test_coverage_gap_below_100_pct(self) -> None:
        eligible, reason = src("TX").is_eligible(1, 900.0, "adult")
        assert not eligible and "coverage gap" in reason

    def test_above_100_pct_is_not_called_a_coverage_gap(self) -> None:
        eligible, reason = src("TX").is_eligible(1, 1500.0, "adult")
        assert not eligible and "coverage gap" not in reason

    def test_kansas_adult_is_no_longer_treated_as_expansion(self) -> None:
        assert not src("KS").is_eligible(1, 1000.0, "adult")[0]


class TestSummaries:
    def test_expansion_summary(self) -> None:
        summary = src("VA").fetch_policy_summary()
        assert "expansion state" in summary and "138%" in summary

    def test_non_expansion_summary_mentions_coverage_gap(self) -> None:
        summary = src("TX").fetch_policy_summary()
        assert "coverage gap" in summary and "non-expansion state" in summary

    def test_thresholds_by_size(self) -> None:
        t = src("VA").thresholds()
        assert t.by_household_size(3).gross_monthly == pytest.approx(round(27_320 * 1.38 / 12, 2))
