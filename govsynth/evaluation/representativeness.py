"""Check that 'realistic' profiles reproduce the census distributions they are drawn from.

The census fetcher once read the wrong ACS variables for most fields ("% with
children" was the married-couple share, naturalized citizens were sampled as
non-qualified aliens) and nothing noticed, because nothing compared what the
sampler produced with what it claimed to reproduce. This module does that
comparison for one state and vintage; `govsynth validate-distribution` and the
test suite run it.

Tolerances are statistical: for a share p over n profiles the allowed gap is
4 standard errors plus one percentage point, so a correct sampler passes and a
mislabeled field (typically off by 10+ points) fails. The income check compares
the median with the median of the fitted lognormal truncated at the sampler's
redraw cap.
"""

from __future__ import annotations

import math
import warnings
from collections import Counter
from dataclasses import asdict, dataclass
from statistics import NormalDist, median
from typing import Any

from govsynth.models.enums import CitizenshipStatus
from govsynth.profiles.us_household import _REALISTIC_INCOME_CAP, USHouseholdProfile
from govsynth.sources.us.census import CensusDataSource, CensusVintage


@dataclass(frozen=True)
class MetricCheck:
    """One generated-vs-target comparison."""

    metric: str
    target: float
    generated: float
    tolerance: float
    ok: bool

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly form."""
        return asdict(self)


def _share_check(metric: str, target: float, generated: float, n: int) -> MetricCheck:
    tol = 4 * math.sqrt(max(target * (1 - target), 1e-6) / n) + 0.01
    return MetricCheck(metric, round(target, 4), round(generated, 4), round(tol, 4), abs(generated - target) <= tol)


def truncated_lognormal_median(mu: float, sigma: float, cap: float) -> float:
    """Median of LogNormal(mu, sigma) conditioned on being <= cap."""
    nd = NormalDist()
    p_below_cap = nd.cdf((math.log(cap) - mu) / sigma)
    return math.exp(mu + sigma * nd.inv_cdf(0.5 * p_below_cap))


# Bounds every US state's ACS household rates fall within, used to catch a census file
# whose *data* is wrong (which a sampler-vs-data comparison cannot: the sampler would
# faithfully reproduce the wrong number). Set wide enough to hold all 51 jurisdictions
# across the bundled vintages; e.g. the old fetcher's 0.756 "% with children" (really
# married couples) is far outside. They do NOT catch every mislabel -- the old citizen
# share (US-born only, ~0.85) was plausible -- so the fetcher's variable-pinning tests
# remain the first line of defense.
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "pct_with_children": (0.15, 0.50),
    "pct_elderly_or_disabled": (0.30, 0.80),
    "pct_citizen": (0.75, 1.00),
    "pct_households_with_earnings": (0.50, 0.95),
    "household_size_1": (0.15, 0.55),  # DC is ~45-50% one-person households
    "median_annual_income": (30_000, 150_000),
}


def plausibility_problems(state: str, vintage: CensusVintage | int | str | None = None) -> list[str]:
    """Census targets for a state that fall outside PLAUSIBLE_RANGES (empty if none)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dist = CensusDataSource(state, vintage=vintage).load()
    if dist is None:
        return [f"{state}: no census data"]
    values = {
        "pct_with_children": dist.pct_with_children,
        "pct_elderly_or_disabled": dist.pct_elderly_or_disabled,
        "pct_citizen": dist.pct_citizen,
        "pct_households_with_earnings": dist.pct_households_with_earnings or dist.labor_force_participation_rate,
        "household_size_1": dist.household_size_weights[0] / sum(dist.household_size_weights),
        "median_annual_income": math.exp(dist.income_mu) * 12,
    }
    return [
        f"{state}: {k} = {v:,.4f} outside plausible range {PLAUSIBLE_RANGES[k]}"
        for k, v in values.items()
        if not PLAUSIBLE_RANGES[k][0] <= v <= PLAUSIBLE_RANGES[k][1]
    ]


def check_state(
    state: str,
    vintage: CensusVintage | int | str | None = None,
    n: int = 3000,
    seed: int = 42,
) -> list[MetricCheck]:
    """Sample n realistic profiles for a state and compare them with the census targets.

    Args:
        state: Two-letter state code.
        vintage: ACS release (see CensusVintage.parse); None uses the default vintage.
        n: Number of profiles to sample.
        seed: Base seed; profile i uses seed + i.

    Returns:
        One MetricCheck per metric. All ``ok`` means the sampler reproduces the data.

    Raises:
        ValueError: If the state has no census data for the vintage.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a national fallback is reported below, not warned
        dist = CensusDataSource(state, vintage=vintage).load()
    if dist is None:
        raise ValueError(f"No census data for {state}")
    profiles = [
        USHouseholdProfile.random(state=state, seed=seed + i, strategy="realistic", census_vintage=vintage)
        for i in range(n)
    ]
    checks = [
        _share_check(
            "pct_with_children", dist.pct_with_children, sum(p.has_dependent_children for p in profiles) / n, n
        ),
        _share_check(
            "pct_elderly_or_disabled",
            dist.pct_elderly_or_disabled,
            sum(p.has_elderly_or_disabled for p in profiles) / n,
            n,
        ),
        _share_check(
            "pct_citizen",
            dist.pct_citizen,
            sum(p.citizenship_status == CitizenshipStatus.CITIZEN for p in profiles) / n,
            n,
        ),
        _share_check(
            "pct_households_with_earnings",
            dist.pct_households_with_earnings
            if dist.pct_households_with_earnings is not None
            else dist.labor_force_participation_rate,
            sum((p.earned_income or 0) > 0 for p in profiles) / n,
            n,
        ),
    ]
    sizes = Counter(p.household_size for p in profiles)
    total_w = sum(dist.household_size_weights)
    for size, weight in enumerate(dist.household_size_weights, start=1):
        checks.append(_share_check(f"household_size_{size}", weight / total_w, sizes[size] / n, n))
    target_median = truncated_lognormal_median(dist.income_mu, dist.income_sigma, _REALISTIC_INCOME_CAP)
    got_median = median(p.monthly_gross_income for p in profiles)
    # Relative tolerance: ~4 standard errors of a sample median of a lognormal, plus $10 rounding.
    rel_tol = 4 * 1.2533 * dist.income_sigma / math.sqrt(n) + 0.01
    checks.append(
        MetricCheck(
            "median_monthly_income",
            round(target_median, 2),
            round(got_median, 2),
            round(rel_tol * target_median + 10, 2),
            abs(got_median - target_median) <= rel_tol * target_median + 10,
        )
    )
    return checks
