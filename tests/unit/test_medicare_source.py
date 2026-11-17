"""Tests for MedicareSource: MSP tiers and Extra Help, CY2026."""

from __future__ import annotations

import pytest
from govsynth.sources.us.medicare import MSP_TIERS, MedicareSource


@pytest.fixture(scope="module")
def src() -> MedicareSource:
    return MedicareSource(calendar_year=2026)


@pytest.mark.parametrize("tier", MSP_TIERS)
@pytest.mark.parametrize(("who", "couple"), [("individual", False), ("couple", True)])
def test_derived_limits_equal_medicare_gov_published_limits(
    src: MedicareSource, tier: str, who: str, couple: bool
) -> None:
    """ceil(FPL x pct / 12) + $20 must reproduce every figure Medicare.gov publishes for 2026."""
    published = src.raw["msp"]["published_monthly_income_limits_48_states"][tier][who]
    assert src.msp_gross_limit(tier, couple) == published


def test_pinned_2026_values(src: MedicareSource) -> None:
    assert src.msp_gross_limit("qmb", False) == 1350
    assert src.msp_gross_limit("qi", True) == 2455
    assert (src.msp_resource_limit(False), src.msp_resource_limit(True)) == (9950, 14910)
    assert (src.extra_help_resource_limit(False), src.extra_help_resource_limit(True)) == (18090, 36100)
    assert src.extra_help_annual_limit(1) == 23940  # 150% x $15,960
    assert src.extra_help_annual_limit(2) == 32460


def test_alaska_and_hawaii_use_their_own_guidelines() -> None:
    assert MedicareSource(state="AK").msp_gross_limit("qmb", False) == 19950 / 12 // 1 + 1 + 20  # ceil(1662.5)+20
    assert MedicareSource(state="HI").msp_countable_limit("qmb", False) == 1530  # 18,360 / 12


@pytest.mark.parametrize(
    ("gross", "resources", "couple", "tier"),
    [
        (1350.00, 0, False, "qmb"),  # exactly at the QMB limit
        (1350.01, 0, False, "slmb"),
        (1616.00, 0, False, "slmb"),
        (1616.01, 0, False, "qi"),
        (1816.00, 0, False, "qi"),
        (1816.01, 0, False, None),
        (1824.00, 0, True, "qmb"),
        (1000.00, 9950, False, "qmb"),
        (1000.00, 9950.01, False, None),  # resource limit binds even at QMB income
    ],
)
def test_msp_tier_boundaries(
    src: MedicareSource, gross: float, resources: float, couple: bool, tier: str | None
) -> None:
    got, _ = src.msp_tier(gross, resources, couple)
    assert got == tier


def test_extra_help_boundaries(src: MedicareSource) -> None:
    at_limit = 23940 / 12 + 20
    assert src.extra_help_eligible(at_limit, 0, False, 1)[0]
    assert not src.extra_help_eligible(at_limit + 0.01, 0, False, 1)[0]
    assert not src.extra_help_eligible(1000, 18090.01, False, 1)[0]
    assert src.extra_help_eligible(1000, 36100, True, 2)[0]


def test_summary_mentions_every_tier(src: MedicareSource) -> None:
    text = src.fetch_policy_summary()
    assert all(t.upper() in text for t in MSP_TIERS) and "$9,950" in text
