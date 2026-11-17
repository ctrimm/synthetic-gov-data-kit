"""Tests for the 2026 ACA premium tax credit source and generator (#18)."""

from __future__ import annotations

import pytest
from govsynth.generators.aca_ptc_eligibility import ACAPremiumTaxCreditGenerator
from govsynth.pipeline import Pipeline
from govsynth.sources.us.aca_ptc import ACAPremiumTaxCreditSource, PTCApplicant

SRC = ACAPremiumTaxCreditSource(tax_year=2026, state="VA")
FPL1 = 15_650.0  # 2025 guideline, household of 1 (used for 2026 coverage)


def applicant(pct: float, size: int = 1, **kw: object) -> PTCApplicant:
    defaults: dict[str, object] = {"benchmark_monthly_premium": 700.0, "enrolled_monthly_premium": 700.0}
    defaults.update(kw)
    return PTCApplicant(household_size=size, annual_household_income=SRC.annual_fpl(size) * pct / 100, **defaults)  # type: ignore[arg-type]


class TestTable:
    def test_rev_proc_2025_25_values(self) -> None:
        assert SRC.required_contribution_pct == 9.96
        rows = [(r["from_pct_fpl"], r["initial_pct"], r["final_pct"]) for r in SRC.raw["applicable_percentage_table"]]
        assert rows == [(0, 2.10, 2.10), (133, 3.14, 4.19), (150, 4.19, 6.60), (200, 6.60, 8.44),
                        (250, 8.44, 9.96), (300, 9.96, 9.96)]  # fmt: skip

    def test_uses_2025_poverty_guidelines(self) -> None:
        assert SRC.fpl_year == 2025
        assert SRC.annual_fpl(1) == FPL1
        assert ACAPremiumTaxCreditSource(state="AK").annual_fpl(1) > FPL1

    @pytest.mark.parametrize(
        ("pct", "expected"),
        [
            (50, 2.10),
            (132.99, 2.10),
            (133, 3.14),
            (141.5, 3.67),
            (150, 4.19),
            (175, 5.40),
            (225, 7.52),
            (250, 8.44),
            (275, 9.20),
            (300, 9.96),
            (400, 9.96),
        ],  # fmt: skip
    )
    def test_applicable_percentage_is_linear_and_rounded(self, pct: float, expected: float) -> None:
        assert SRC.applicable_pct(pct) == expected

    def test_reproduces_the_regulations_worked_example(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """26 CFR 1.36B-3(g)(3) Example 1: 275% FPL is 8.78% under the original table (8.775 rounds up)."""
        original = [(0, 133, 2.0, 2.0), (133, 150, 3.0, 4.0), (150, 200, 4.0, 6.3), (200, 250, 6.3, 8.05),
                    (250, 300, 8.05, 9.5), (300, 400, 9.5, 9.5)]  # fmt: skip
        table = [{"from_pct_fpl": a, "to_pct_fpl": b, "initial_pct": c, "final_pct": d} for a, b, c, d in original]
        monkeypatch.setitem(SRC.raw, "applicable_percentage_table", table)
        assert SRC.applicable_pct(275) == 8.78


class TestDetermine:
    def test_income_limits_are_inclusive(self) -> None:
        assert SRC.determine(applicant(100)).eligible
        assert SRC.determine(applicant(400)).eligible
        assert SRC.determine(applicant(99.99)).failed_rule == "income_floor"
        assert SRC.determine(applicant(400.01)).failed_rule == "income_ceiling"  # enhanced credits expired

    def test_credit_formula(self) -> None:
        r = SRC.determine(applicant(250, benchmark_monthly_premium=600.0, enrolled_monthly_premium=550.0))
        contribution = round(FPL1 * 2.5 * 0.0844 / 12, 2)
        assert r.monthly_contribution == contribution
        assert r.monthly_credit == round(600.0 - contribution, 2)

    def test_credit_capped_at_enrolled_premium(self) -> None:
        r = SRC.determine(applicant(150, benchmark_monthly_premium=800.0, enrolled_monthly_premium=100.0))
        assert r.monthly_credit == 100.0

    def test_zero_credit(self) -> None:
        r = SRC.determine(applicant(390, benchmark_monthly_premium=50.0))
        assert not r.eligible and r.failed_rule == "zero_credit"

    def test_married_filing_separately(self) -> None:
        base = {"size": 2, "married": True, "files_jointly": False}
        assert SRC.determine(applicant(200, **base)).failed_rule == "joint_filing"
        assert SRC.determine(applicant(200, **base, abuse_or_abandonment_exception=True)).eligible

    def test_medicaid_eligibility_blocks_the_credit(self) -> None:
        assert SRC.determine(applicant(120, medicaid_eligible=True)).failed_rule == "medicaid"

    def test_employer_affordability_line(self) -> None:
        income = FPL1 * 3
        line = round(income * 0.0996 / 12, 2)
        assert SRC.determine(applicant(300, employer_offer_self_only_monthly=line)).failed_rule == (
            "affordable_employer_coverage"
        )
        assert SRC.determine(applicant(300, employer_offer_self_only_monthly=round(line + 1, 2))).eligible

    def test_income_based_sep_excluded_from_2026(self) -> None:
        assert SRC.determine(applicant(200, enrolled_via_income_sep=True)).failed_rule == "income_sep"

    def test_no_bundled_year_raises(self) -> None:
        with pytest.raises(ValueError, match="tax year 2025"):
            ACAPremiumTaxCreditSource(tax_year=2025)


class TestGenerator:
    @pytest.mark.parametrize("state", ["VA", "TX", "AK"])
    def test_outcomes_agree_with_source_and_traces_are_well_formed(self, state: str) -> None:
        gen = ACAPremiumTaxCreditGenerator(state=state)
        for strategy in ("edge_saturated", "uniform", "realistic"):
            for case in gen.generate(80, seed=42, profile_strategy=strategy):
                steps = case.rationale_trace.steps
                fails = [s for s in steps if s.is_determinative]
                assert len(fails) == (1 if case.expected_outcome == "ineligible" else 0), case.case_id
                assert [s.step_number for s in steps] == list(range(1, len(steps) + 1))
                assert (case.metadata["failed_rule"] is None) == (case.expected_outcome == "eligible")
                case.check_output_contract()

    def test_deterministic(self) -> None:
        a = ACAPremiumTaxCreditGenerator(state="VA").generate(60, seed=42)
        b = ACAPremiumTaxCreditGenerator(state="VA").generate(60, seed=42)
        assert [c.case_id for c in a] == [c.case_id for c in b]

    def test_every_case_family_appears(self) -> None:
        cases = ACAPremiumTaxCreditGenerator(state="VA").generate(400, seed=42)
        assert {c.metadata["case_family"] for c in cases} == {
            "income_band", "medicaid_overlap", "employer_offer", "married_filing_separately",
            "income_sep", "lawfully_present_below_100", "zero_credit",
        }  # fmt: skip

    def test_medicaid_overlap_depends_on_expansion(self) -> None:
        def medicaid_blocks(state: str) -> int:
            cases = ACAPremiumTaxCreditGenerator(state=state).generate(400, seed=42)
            return sum(c.metadata["failed_rule"] == "medicaid" for c in cases)

        assert medicaid_blocks("VA") > 0
        assert medicaid_blocks("TX") == 0  # no adult Medicaid above 15% FPL in Texas

    def test_lawfully_present_below_100_cites_section_71302(self) -> None:
        cases = ACAPremiumTaxCreditGenerator(state="VA").generate(300, seed=42)
        lp = [c for c in cases if c.metadata["case_family"] == "lawfully_present_below_100"]
        assert lp and all(c.expected_outcome == "ineligible" for c in lp)
        assert all("71302" in c.rationale_trace.steps[2].computation for c in lp)

    def test_preset(self) -> None:
        cases = Pipeline.from_preset("aca.tx").generate(10, seed=42)
        assert len(cases) == 10 and all(c.program == "aca_ptc" for c in cases)
