"""Tests for SSISource, CY2026."""

from __future__ import annotations

import pytest
from govsynth.sources.us.ssi import SSISource


@pytest.fixture(scope="module")
def src() -> SSISource:
    return SSISource(calendar_year=2026)


def test_pinned_2026_values(src: SSISource) -> None:
    """90 FR 49047: $994 / $1,491; SGA $1,690. 20 CFR 416.1205: $2,000 / $3,000."""
    assert (src.fbr(False), src.fbr(True)) == (994, 1491)
    assert (src.resource_limit(False), src.resource_limit(True)) == (2000, 3000)
    assert src.sga_nonblind == 1690


@pytest.mark.parametrize(
    ("unearned", "earned", "countable"),
    [
        (500, 0, 480),
        (0, 500, 207.5),  # (500 - 20 - 65) / 2
        (10, 500, 212.5),  # $10 of the $20 left for earnings
        (300, 65, 280),  # $65 of earnings fully excluded
        (15, 0, 0),
    ],
)
def test_countable_income(src: SSISource, unearned: float, earned: float, countable: float) -> None:
    assert src.countable_income(unearned, earned).countable == pytest.approx(countable)


def test_payment_and_fbr_boundary(src: SSISource) -> None:
    eligible, payment, _ = src.determine("aged", 520, 0, 0, couple=False)
    assert eligible and payment == 494
    eligible, payment, _ = src.determine("aged", 1014, 0, 0, couple=False)  # countable == FBR
    assert not eligible and payment == 0


def test_category_resources_and_sga(src: SSISource) -> None:
    assert not src.determine(None, 100, 0, 0, couple=False)[0]
    assert not src.determine("aged", 100, 0, 2000.01, couple=False)[0]
    assert src.determine("aged", 100, 0, 3000, couple=True)[0]
    assert not src.determine("disabled", 0, 1690.01, 0, couple=False)[0]
    assert src.determine("disabled", 0, 1690, 0, couple=False)[0]
    assert src.determine("blind", 0, 1700, 0, couple=False, blind=True)[0]  # SGA test not applied to blind
