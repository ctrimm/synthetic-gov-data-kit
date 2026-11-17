"""Tests for TANF in VA, MD, TX and CA (#17)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from govsynth.generators.tanf_eligibility import TANFEligibilityGenerator
from govsynth.pipeline import Pipeline
from govsynth.sources.us.tanf import TANFHousehold, TANFSource

ROOT = Path(__file__).resolve().parents[2]


def passes(state: str, **kw: object) -> bool:
    return TANFSource(state).is_eligible(TANFHousehold(**kw))  # type: ignore[arg-type]


def failed_test(state: str, **kw: object) -> str | None:
    checks = TANFSource(state).evaluate(TANFHousehold(**kw))  # type: ignore[arg-type]
    return next((c.title for c in checks if c.passed is False), None)


class TestData:
    @pytest.mark.parametrize("state", ["VA", "MD", "TX", "CA"])
    def test_verified(self, state: str) -> None:
        assert TANFSource(state).raw["_metadata"]["verification_status"] == "verified"

    def test_builder_consistency_checks(self) -> None:
        spec = importlib.util.spec_from_file_location("build_tanf_tables", ROOT / "scripts/build_tanf_tables.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        mod.check()

    def test_published_values(self) -> None:
        assert TANFSource("VA").raw["standard_of_assistance"]["group_iii"]["3"] == 587
        assert TANFSource("MD").raw["allowable_payment"]["by_size"]["3"] == 773
        assert TANFSource("TX").raw["budgetary_allowances"]["one_parent"]["recognizable_needs"]["3"] == 188
        assert TANFSource("CA").raw["map_non_exempt"]["region_1"]["3"] == 1196

    def test_unsupported_state(self) -> None:
        with pytest.raises(ValueError, match="bundled for"):
            TANFSource("NY")


class TestVirginia:
    def test_locality_groups(self) -> None:
        va = TANFSource("VA")
        assert va.va_group("Fairfax County") == "group_iii"
        assert va.va_group("Fairfax city") == "group_iii"
        assert va.va_group("Norfolk city") == "group_ii"
        assert va.va_group("Isle of Wight County") == "group_ii"
        with pytest.raises(ValueError):
            va.va_group("Atlantis County")

    def test_same_income_depends_on_group(self) -> None:
        assert passes("VA", size=3, earned=900, locality="Fairfax County")
        assert not passes("VA", size=3, earned=900, locality="Norfolk city")

    def test_disregard_uses_fy2026_snap_standard_deduction(self) -> None:
        net = TANFSource("VA").evaluate(TANFHousehold(size=3, earned=1000, locality="Arlington County"))[2]
        assert net.inputs["net_income"] == round((1000 - 209) * 0.8, 2)

    def test_net_must_be_strictly_below_standard(self) -> None:
        assert not passes("VA", size=3, unearned=587, locality="Arlington County")
        assert passes("VA", size=3, unearned=586.99, locality="Arlington County")

    def test_gross_screen(self) -> None:
        assert failed_test("VA", size=3, earned=1200, locality="Arlington County") == (
            "Gross income screening against the Maximum Income Chart"
        )


class TestMaryland:
    def test_twenty_percent_disregard_against_allowable_payment(self) -> None:
        # 80% of $966.25 = $773.00 = the allowable payment, but the benefit would be $0 (< $10).
        assert failed_test("MD", size=3, earned=966.26) == "Compare net income to the allowable payment"

    def test_ten_dollar_minimum_benefit(self) -> None:
        assert passes("MD", size=3, earned=954.99)  # net $763.99 -> rounded $763 -> benefit $10
        assert failed_test("MD", size=3, earned=955.0) == "Compute the benefit and apply the $10 minimum"

    def test_unearned_counts_in_full(self) -> None:
        assert not passes("MD", size=3, unearned=770)  # benefit $3


class TestTexas:
    def test_part_a_one_third_disregard_boundary(self) -> None:
        assert passes("TX", size=3, earned=401.98)  # (281.98 x 2/3) = 187.99 -> $0.01 unmet need
        assert failed_test("TX", size=3, earned=402.0) == (
            "Recognizable Needs test, Part A (applicants: $120 and 1/3 disregard)"
        )

    def test_budgetary_needs_fifty_cent_rule(self) -> None:
        assert failed_test("TX", size=3, unearned=750.51) == "Budgetary Needs test (applicants)"

    def test_resource_limit(self) -> None:
        assert failed_test("TX", size=3, earned=100, countable_resources=1000.01) == "Check countable resources"
        assert passes("TX", size=3, earned=100, countable_resources=1000)

    def test_two_parent_standards(self) -> None:
        assert (
            TANFSource("TX")
            .evaluate(TANFHousehold(size=4, two_parent=True))[0]
            .result.startswith("Budgetary Needs $925")
        )


class TestCalifornia:
    def test_regions(self) -> None:
        ca = TANFSource("CA")
        assert ca.ca_region("Los Angeles") == "region_1"
        assert ca.ca_region("Fresno") == "region_2"

    def test_applicant_test_deducts_450(self) -> None:
        # Region 1, unit of 3: MBSAC $1,960. $2,409.99 - $450 = $1,959.99 < $1,960.
        assert failed_test("CA", size=3, earned=2409.99, county="Alameda") != "Applicant income test against the MBSAC"
        assert failed_test("CA", size=3, earned=2410, county="Alameda") == "Applicant income test against the MBSAC"

    def test_grant_uses_600_and_half(self) -> None:
        checks = TANFSource("CA").evaluate(TANFHousehold(size=3, earned=2000, county="Los Angeles"))
        assert checks[-1].inputs["grant"] == 1196 - 700


class TestGenerator:
    @pytest.mark.parametrize("state", ["VA", "MD", "TX", "CA"])
    def test_outcomes_and_traces(self, state: str) -> None:
        gen = TANFEligibilityGenerator(state=state)
        for strategy in ("edge_saturated", "uniform", "realistic"):
            for case in gen.generate(80, seed=42, profile_strategy=strategy):
                steps = case.rationale_trace.steps
                fails = [s for s in steps if s.is_determinative]
                assert len(fails) == (1 if case.expected_outcome == "ineligible" else 0), case.case_id
                assert len(steps) >= 2
                ctx = case.scenario.additional_context
                hh = TANFHousehold(
                    size=case.scenario.household_size,
                    earned=ctx["earned_income_monthly"],
                    unearned=ctx["social_security_monthly"],
                    locality=ctx.get("locality"),
                    county=ctx.get("county"),
                    two_parent=ctx.get("case_type") == "two_parent",
                    countable_resources=ctx.get("countable_resources", 0.0),
                )
                assert gen.source.is_eligible(hh) == (case.expected_outcome == "eligible"), case.case_id
                case.check_output_contract()

    @pytest.mark.parametrize("state", ["VA", "MD", "TX", "CA"])
    def test_every_income_test_is_determinative_somewhere(self, state: str) -> None:
        cases = TANFEligibilityGenerator(state=state).generate(300, seed=42)
        failed = {c.metadata["failed_test"] for c in cases} - {None}
        tests = {c.title for c in TANFSource(state).all_checks(TANFHousehold(size=3, locality="Arlington County",
                                                                               county="Alameda"))
                 if c.passed is not None}  # fmt: skip
        if state == "TX":  # Part A is stricter than Part B for every applicant, so Part B never decides
            tests -= {"Recognizable Needs test, Part B ($120 and 90% earned income deduction)"}
        assert tests <= failed
        assert any(c.expected_outcome == "eligible" for c in cases)

    def test_deterministic(self) -> None:
        a = TANFEligibilityGenerator(state="TX").generate(50, seed=42)
        b = TANFEligibilityGenerator(state="TX").generate(50, seed=42)
        assert [c.case_id for c in a] == [c.case_id for c in b]

    @pytest.mark.parametrize("preset", ["tanf.va", "tanf.md", "tanf.tx", "tanf.ca"])
    def test_presets(self, preset: str) -> None:
        cases = Pipeline.from_preset(preset).generate(10, seed=42)
        assert len(cases) == 10 and all(c.program == "tanf" for c in cases)
