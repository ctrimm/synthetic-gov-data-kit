"""Tests for LIHEAPSource, FY2026."""

from __future__ import annotations

import pytest
from govsynth.sources.us.liheap import LIHEAPSource

STATES = ("VA", "CA", "TX", "MD")
_FACTOR = {1: 52, 2: 68, 3: 84, 4: 100, 5: 116, 6: 132, 7: 135, 8: 138, 9: 141, 10: 144, 11: 147, 12: 150}


def test_smi_table_follows_the_45_cfr_96_85_size_factors() -> None:
    """Every cell = 4-person 60%-SMI x size factor (to $1). Catches any transcription error."""
    raw = LIHEAPSource(state="VA").raw["state_median_income"]
    assert len(raw) == 51
    for state, row in raw.items():
        four = row["sixty_pct_smi"]["4"]
        assert abs(four - row["smi_4_person"] * 0.6) <= 1, state
        for size, factor in _FACTOR.items():
            assert abs(row["sixty_pct_smi"][str(size)] - four * factor / 100) <= 1.01, (state, size)


def test_pinned_values() -> None:
    """IM2025-02 Att. 4 and 2025 HHS guidelines."""
    assert LIHEAPSource(state="VA").threshold("heating", 3).annual_limit == 39975  # 150% x $26,650
    assert LIHEAPSource(state="VA").threshold("weatherization", 4).annual_limit == 83500
    assert LIHEAPSource(state="CA").threshold("crisis", 1).annual_limit == 39980
    assert LIHEAPSource(state="TX").threshold("cooling", 2).annual_limit == 31725  # 150% x $21,150
    assert LIHEAPSource(state="MD").threshold("heating", 4).annual_limit == pytest.approx(154117 * 0.417, abs=1)


@pytest.mark.parametrize("state", STATES)
def test_every_threshold_within_federal_floor_and_ceiling(state: str) -> None:
    src = LIHEAPSource(state=state)
    for component in src.components:
        for size in range(1, 13):
            limit = src.threshold(component, size).annual_limit
            assert src.annual_fpl(size) * 1.10 - 1 <= limit <= src.federal_ceiling(size) + 1, (component, size)


def test_maryland_categorical_eligibility() -> None:
    src = LIHEAPSource(state="MD")
    limit = src.threshold("heating", 2).annual_limit
    assert not src.determine("heating", 2, limit + 100)[0]
    assert src.determine("heating", 2, limit + 100, receives=("SNAP",))[0]
    assert not LIHEAPSource(state="VA").determine("heating", 2, 1e6, receives=("SNAP",))[0]


def test_boundary_and_errors() -> None:
    src = LIHEAPSource(state="TX")
    limit = src.threshold("heating", 3).annual_limit
    assert src.determine("heating", 3, limit)[0] and not src.determine("heating", 3, limit + 0.01)[0]
    with pytest.raises(ValueError, match="cooling"):
        LIHEAPSource(state="VA").threshold("cooling", 3)
    with pytest.raises(ValueError, match="No FY2026 LIHEAP plan"):
        LIHEAPSource(state="NY")


def test_size_above_12_extends_the_factor() -> None:
    src = LIHEAPSource(state="CA")
    assert src.sixty_pct_smi(13) == round(128144 * 0.6 * 1.53)
