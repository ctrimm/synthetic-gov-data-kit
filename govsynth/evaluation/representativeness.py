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

When a state has PUMS household types (#8) the sampler draws from them, so the
targets are the types' own weighted shares and median; `pums_crosscheck` then
compares those shares with the summary tables, which catches a wrong PUMS build.
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
from govsynth.sources.us.household_types import HouseholdTypes, load_household_types


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
    types = load_household_types(state, dist.vintage)
    if types is not None:
        return _check_against_types(types, profiles, n)
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


def _check_against_types(types: HouseholdTypes, profiles: list[USHouseholdProfile], n: int) -> list[MetricCheck]:
    """Compare profiles with the shares of the PUMS household types they were drawn from."""
    checks = [
        _share_check("pct_with_children", types.share("kids"), sum(p.has_dependent_children for p in profiles) / n, n),
        _share_check(
            "pct_elderly_or_disabled", types.share("eld_dis"), sum(p.has_elderly_or_disabled for p in profiles) / n, n
        ),
        _share_check(
            "pct_citizen_head",
            types.share("head_citizen"),
            sum(p.citizenship_status == CitizenshipStatus.CITIZEN for p in profiles) / n,
            n,
        ),
        _share_check(
            "pct_households_with_earnings",
            types.share("earns"),
            sum((p.earned_income or 0) > 0 for p in profiles) / n,
            n,
        ),
    ]
    sizes = Counter(p.household_size for p in profiles)
    for size in range(1, 7):
        checks.append(_share_check(f"household_size_{size}", types.size_share(size), sizes[size] / n, n))
    target = types.median_annual_income() / 12
    got = median(p.monthly_gross_income for p in profiles)
    # 4 standard errors of a sample median (sqrt(1/(4n)) / density at the median), plus $10 rounding.
    tol = 4 * math.sqrt(1 / (4 * n)) / max(types.density_at_median(), 1e-12) / 12 + 10
    checks.append(
        MetricCheck("median_monthly_income", round(target, 2), round(got, 2), round(tol, 2), abs(got - target) <= tol)
    )
    return checks


# PUMS household types vs. the summary tables, in percentage points. Not identical by
# construction: PUMS is a ~1% sample of the 5-year ACS, citizenship is the head's
# (summary: persons), and the summary file's elderly/disabled rate is an
# independence upper bound, so PUMS may sit below it by up to ELD_DIS_SLACK.
CROSSCHECK_TOLERANCE = 0.03
ELD_DIS_SLACK = 0.10


def pums_crosscheck(state: str, vintage: CensusVintage | int | str | None = None) -> list[MetricCheck]:
    """Compare a state's PUMS household-type shares with its summary-table rates.

    Returns an empty list when the state has no PUMS types for the vintage.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dist = CensusDataSource(state, vintage=vintage).load()
    if dist is None:
        raise ValueError(f"No census data for {state}")
    types = load_household_types(state, dist.vintage)
    if types is None:
        return []
    tol = CROSSCHECK_TOLERANCE

    def check(metric: str, target: float, got: float, lo: float = tol, hi: float = tol) -> MetricCheck:
        return MetricCheck(metric, round(target, 4), round(got, 4), round(max(lo, hi), 4), -lo <= got - target <= hi)

    earn_target = dist.pct_households_with_earnings or dist.labor_force_participation_rate
    total_w = sum(dist.household_size_weights)
    checks = [
        check("pct_with_children", dist.pct_with_children, types.share("kids")),
        check("pct_elderly_or_disabled", dist.pct_elderly_or_disabled, types.share("eld_dis"), lo=ELD_DIS_SLACK),
        check("pct_households_with_earnings", earn_target, types.share("earns")),
        # Heads are likelier to be citizens than all residents (children of immigrants are often US-born
        # citizens, but so are many non-head adults); allow a wider band.
        check("pct_citizen", dist.pct_citizen, types.share("head_citizen"), lo=0.06, hi=0.06),
        check("household_size_1", dist.household_size_weights[0] / total_w, types.size_share(1)),
    ]
    return checks


def check_caseload(state: str, n: int = 3000, seed: int = 42) -> list[MetricCheck]:
    """Sample n SNAP caseload profiles for a state and compare them with the QC tables (#9).

    Targets come straight from the FNS 'Characteristics of SNAP Households' state
    tables: gross income as a percent of poverty (four bins), elderly, elderly or
    disabled, earnings, SSI, Social Security, and average gross income. The
    children share is compared with the fitted table's share of households of two or
    more with children, because one-person child-only units are rendered without
    dependent children.

    Raises:
        ValueError: If the state has no caseload data.
    """
    from govsynth.sources.us.snap_caseload import POV_RANGES, caseload_table, poverty_guideline_annual

    table = caseload_table(state)
    target = table.qc["states"][state.upper()]
    profiles = [
        USHouseholdProfile.random(state=state, seed=seed + i, strategy="realistic", population="caseload")
        for i in range(n)
    ]

    def pov4(p: USHouseholdProfile) -> int:
        if p.monthly_gross_income <= 0:
            return 0
        pct = (
            100
            * p.monthly_gross_income
            * 12
            / poverty_guideline_annual(p.household_size, state, (p.income_dollar_year or table.fiscal_year) - 1)
        )
        edges = [POV_RANGES["26_50"][1], POV_RANGES["76_100"][1]]
        return 1 if pct <= edges[0] else 2 if pct <= edges[1] else 3

    bins = Counter(pov4(p) for p in profiles)
    sources = [p.income_sources or () for p in profiles]
    checks = [
        _share_check(f"pov_bin_{label}", target["pov4_pct"][i] / 100, bins[i] / n, n)
        for i, label in enumerate(("zero", "1_50", "51_100", "101_plus"))
    ]
    checks += [
        _share_check(
            "pct_children_size2plus",
            table.share(lambda c: bool(c.kids) and c.size > 1),
            sum(p.has_dependent_children for p in profiles) / n,
            n,
        ),
        _share_check(
            "pct_elderly_or_disabled",
            target["pct_elderly_or_disabled"] / 100,
            sum(p.has_elderly_or_disabled for p in profiles) / n,
            n,
        ),
        _share_check(
            "pct_elderly_head", target["pct_elderly"] / 100, sum((p.age_of_head or 0) >= 60 for p in profiles) / n, n
        ),
        _share_check("pct_earned", target["pct_earned"] / 100, sum("earned" in s for s in sources) / n, n),
        _share_check("pct_ssi", target["pct_ssi"] / 100, sum("ssi" in s for s in sources) / n, n),
        _share_check(
            "pct_social_security",
            target["pct_social_security"] / 100,
            sum("social_security" in s for s in sources) / n,
            n,
        ),
    ]
    incomes = [p.monthly_gross_income for p in profiles]
    mean = sum(incomes) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in incomes) / max(n - 1, 1))
    # 4 standard errors plus 5% for the within-bin income model (the report gives bin shares, not amounts).
    tol = 4 * sd / math.sqrt(n) + 0.05 * target["avg_gross_income"]
    checks.append(
        MetricCheck(
            "avg_gross_income",
            target["avg_gross_income"],
            round(mean, 2),
            round(tol, 2),
            abs(mean - target["avg_gross_income"]) <= tol,
        )
    )
    return checks
