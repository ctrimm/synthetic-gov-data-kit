"""Tests for CHIPSource, CY2026."""

from __future__ import annotations

import pytest
from govsynth.sources.us.chip import AGE_BANDS, CHIPSource, age_band


def test_table_is_internally_consistent_for_all_states() -> None:
    """Upper limit = the row's maximum; CHIP-funded ranges start at or below the Medicaid limit."""
    states = CHIPSource(state="VA").raw["states"]
    assert len(states) == 51
    for code, row in states.items():
        values = [row["separate_chip_pct_fpl"] or 0]
        for band in AGE_BANDS:
            b = row["age_bands"][band]
            values.append(b["medicaid_funded_pct_fpl"])
            if b["chip_funded_medicaid_pct_fpl"]:
                values.append(b["chip_funded_medicaid_pct_fpl"]["high"])
                assert b["chip_funded_medicaid_pct_fpl"]["low"] <= b["medicaid_funded_pct_fpl"] + 1, (code, band)
        assert max(values) == row["upper_limit_pct_fpl"], code


@pytest.mark.parametrize(
    ("state", "medicaid", "upper"),
    [
        ("VA", (148, 148, 148), 205),
        ("CA", (208, 142, 133), 266),
        ("TX", (203, 149, 138), 206),
        ("MD", (194, 138, 133), 322),
    ],
)
def test_pinned_limits(state: str, medicaid: tuple[int, int, int], upper: int) -> None:
    src = CHIPSource(state=state)
    assert tuple(src.medicaid_limit(b) for b in AGE_BANDS) == medicaid
    assert src.chip_limit_above_medicaid("6-18") == upper


def test_age_bands() -> None:
    assert [age_band(a) for a in (0, 1, 5, 6, 18, 19)] == ["0-1", "1-5", "1-5", "6-18", "6-18", None]


def test_hand_off_at_each_boundary() -> None:
    va = CHIPSource(state="VA")
    m148, m205 = va.monthly_limit(148, 3), va.monthly_limit(205, 3)
    assert va.determine(10, 3, m148, insured=True).program == "medicaid"  # Medicaid regardless of insurance
    assert va.determine(10, 3, m148 + 0.01, insured=False).program == "separate_chip"
    assert va.determine(10, 3, m148 + 0.01, insured=True).program is None  # CHIP is for uninsured children
    assert va.determine(10, 3, m205, insured=False).program == "separate_chip"
    assert va.determine(10, 3, m205 + 0.01, insured=False).program is None
    md = CHIPSource(state="MD")
    assert md.determine(3, 4, md.monthly_limit(300, 4), insured=False).program == "medicaid_chip_funded"
    assert va.determine(19, 3, 100.0, insured=False).program is None


def test_uses_2026_poverty_guidelines() -> None:
    assert CHIPSource(state="VA").annual_fpl(3) == 27320  # KFF: 2026 FPL for a family of three
