"""Census Bureau ACS data fetcher.

Network-only module -- never imported at generation time.
All Census Bureau API calls go through httpx.

Typical usage (from refresh_census.py):
    data = build_state_census_json("VA", year=2022, api_key=None)
    write_state_file("VA", data, data_dir=Path("data/census"))
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx

# FIPS codes: state abbreviation -> two-digit Census FIPS code
FIPS_CODES: dict[str, str] = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
}

_BASE_URL = "https://api.census.gov/data"

# ---------------------------------------------------------------------------
# B19001: household income, 16 brackets (variables _002E through _017E).
#
# Bracket edges below are the ACS labels for B19001_002E..B19001_017E, verified
# against https://api.census.gov/data/2022/acs/acs5/variables/<VAR>.json. They
# are NOT evenly spaced above $50k: _011E is $50,000-59,999, _012E is
# $60,000-74,999, ... _017E is $200,000 or more. An earlier version labeled
# them as $5k-wide bins up to "$125,000 or more", which pushed the top ~40% of
# households down by tens of thousands of dollars and biased the fitted
# lognormal low.
#
# (lower, upper) in annual dollars; upper=None marks the open-ended top bracket.
# ---------------------------------------------------------------------------
_INCOME_BRACKETS: list[tuple[int, int | None]] = [
    (0, 10_000),
    (10_000, 15_000),
    (15_000, 20_000),
    (20_000, 25_000),
    (25_000, 30_000),
    (30_000, 35_000),
    (35_000, 40_000),
    (40_000, 45_000),
    (45_000, 50_000),
    (50_000, 60_000),
    (60_000, 75_000),
    (75_000, 100_000),
    (100_000, 125_000),
    (125_000, 150_000),
    (150_000, 200_000),
    (200_000, None),
]
_INCOME_BRACKET_LABELS = [
    "Less than $10,000",
    "$10,000 to $14,999",
    "$15,000 to $19,999",
    "$20,000 to $24,999",
    "$25,000 to $29,999",
    "$30,000 to $34,999",
    "$35,000 to $39,999",
    "$40,000 to $44,999",
    "$45,000 to $49,999",
    "$50,000 to $59,999",
    "$60,000 to $74,999",
    "$75,000 to $99,999",
    "$100,000 to $124,999",
    "$125,000 to $149,999",
    "$150,000 to $199,999",
    "$200,000 or more",
]
# Closed-bracket midpoints. The open-ended top bracket's representative value
# is computed per state by `_top_bracket_representative`.
_INCOME_BRACKET_MIDPOINTS = [(lo + hi) / 2 if hi is not None else float("nan") for lo, hi in _INCOME_BRACKETS]

# Fallback Pareto shape for the open-ended $200k+ bracket when the two top
# brackets can't support an estimate (e.g. zero counts in a mocked response).
_DEFAULT_PARETO_ALPHA = 2.0

# C17002: ratio of income to poverty level (persons for whom poverty status is
# determined). Variables _002E.._008E, upper bound of each bin as a multiple of
# the poverty line; None marks the open-ended "2.00 and over" bin.
_FPL_BINS: list[tuple[str, float | None]] = [
    ("C17002_002E", 0.50),
    ("C17002_003E", 1.00),
    ("C17002_004E", 1.25),
    ("C17002_005E", 1.50),
    ("C17002_006E", 1.85),
    ("C17002_007E", 2.00),
    ("C17002_008E", None),
]

# B25007: tenure by age of householder. Owner rows _003E.._011E and renter rows
# _013E.._021E share these nine age bands. Representative ages are bin
# midpoints; 85+ uses 90.
_HOUSEHOLDER_AGE_BINS: list[tuple[str, float]] = [
    ("15 to 24", 20.0),
    ("25 to 34", 30.0),
    ("35 to 44", 40.0),
    ("45 to 54", 50.0),
    ("55 to 59", 57.5),
    ("60 to 64", 62.5),
    ("65 to 74", 70.0),
    ("75 to 84", 80.0),
    ("85 and over", 90.0),
]

# ACS (B05001) reports citizenship but not immigration status, so it cannot by
# itself separate "qualified" non-citizens (8 U.S.C. 1641 -- LPRs, refugees,
# asylees, ...) from everyone else. This national share splits the ACS
# non-citizen count. Derived from DHS Office of Homeland Security Statistics
# January 2022 estimates: 12.9M lawful permanent residents vs. 11.0M
# unauthorized immigrants, i.e. 12.9 / (12.9 + 11.0) ~= 0.54. It omits
# refugees/asylees not yet adjusted (qualified) and nonimmigrant visa holders
# (not qualified), and it is applied uniformly to every state even though the
# real mix varies widely by state. Note "qualified" is not the same as
# "eligible": SNAP and Medicaid layer a five-year bar and other conditions on top.
_NONCITIZEN_QUALIFIED_SHARE = 0.54


def _top_bracket_representative(n_150_200: float, n_200_plus: float) -> float:
    """Representative annual income for the open-ended $200k+ bracket.

    Fits a Pareto tail through the two top brackets: if incomes above $150k
    follow Pareto(alpha), then P(X > 200k) / P(X > 150k) = (150/200)^alpha,
    so alpha = ln((n_150_200 + n_200_plus) / n_200_plus) / ln(200/150).

    Returns the value whose log equals E[ln X | X >= 200k] = ln(200k) + 1/alpha,
    which is what the log-space moment fit in `fit_lognormal` needs.

    Args:
        n_150_200: Household count in the $150,000-$199,999 bracket.
        n_200_plus: Household count in the $200,000+ bracket.

    Returns:
        Representative annual dollar value for the top bracket.
    """
    alpha = _DEFAULT_PARETO_ALPHA
    if n_200_plus > 0 and n_150_200 > 0:
        estimated = math.log((n_150_200 + n_200_plus) / n_200_plus) / math.log(200 / 150)
        # Guard against implausibly fat or thin tails from noisy small-state counts.
        alpha = min(max(estimated, 1.1), 5.0)
    return round(200_000 * math.exp(1 / alpha))


def fit_lognormal(buckets: list[dict[str, Any]]) -> tuple[float, float]:
    """Fit lognormal (mu, sigma) to ACS income bracket weights.

    Uses method of moments on log-transformed monthly midpoints.
    Weights are normalized so they need not sum to 1.0.

    Args:
        buckets: list of {"annual_midpoint": float, "weight": float}
                 annual_midpoint is in dollars/year.

    Returns:
        (mu, sigma) for use in random.lognormvariate(mu, sigma),
        where the distribution is over monthly income.
    """
    total = sum(b["weight"] for b in buckets)
    weights = [b["weight"] / total for b in buckets]
    log_monthly = [math.log(b["annual_midpoint"] / 12) for b in buckets]

    mu = sum(w * lm for w, lm in zip(weights, log_monthly, strict=False))
    variance = sum(w * (lm - mu) ** 2 for w, lm in zip(weights, log_monthly, strict=False))
    sigma = math.sqrt(variance)

    return round(mu, 4), round(sigma, 4)


def _get(client: httpx.Client, url: str, params: dict[str, Any]) -> list[list[str]]:
    """Make one Census API GET; return parsed JSON rows."""
    resp = client.get(url, params=params, timeout=30)
    resp.raise_for_status()
    result: list[list[str]] = resp.json()
    return result


def _safe_int(val: str) -> int:
    """Parse Census API value to int; return 0 on error or negative."""
    try:
        return max(0, int(val))
    except (ValueError, TypeError):
        return 0


def _safe_rate(numerator: int, denominator: int) -> float:
    """Return numerator/denominator rounded to 4 places; 0.0 if denom is 0."""
    return round(numerator / denominator, 4) if denominator > 0 else 0.0


def _vars(table: str, numbers: list[int]) -> list[str]:
    """Build ACS estimate variable names, e.g. _vars("B19001", [2]) -> ["B19001_002E"]."""
    return [f"{table}_{n:03d}E" for n in numbers]


# Variables requested per table group. Each group is one HTTP request and must
# stay under the Census API's 50-variable limit.
INCOME_VARS = _vars("B19001", list(range(2, 18)))
POVERTY_VARS = _vars("C17002", list(range(1, 9)))
HOUSING_VARS = (
    _vars("B25064", [1])
    + _vars("B25070", [1, 7, 8, 9, 10, 11])
    + _vars("B25003", [1, 3])
    + _vars("B25007", [1, *range(3, 12), *range(13, 22)])
)
DEMOGRAPHIC_VARS = (
    _vars("B11016", [1, *range(3, 9), *range(10, 17)])
    + _vars("B11005", [1, 2])
    + _vars("B11006", [1, 2])
    + _vars("B22010", [1, 3, 6])
    + _vars("B05001", [1, 6])
)
INCOME_SOURCE_VARS = (
    _vars("B22003", [1, 2])
    + _vars("B23025", [1, 2])
    + _vars("B19051", [1, 2])
    + _vars("B19055", [1, 2])
    + _vars("B19056", [1, 2])
    + _vars("B19057", [1, 2])
)
HEALTH_VARS = _vars("C27007", [1, 4, 7, 10, 14, 17, 20])

_TABLES = [
    "B19001",
    "C17002",
    "B25064",
    "B25070",
    "B25003",
    "B25007",
    "B11016",
    "B11005",
    "B11006",
    "B22010",
    "B05001",
    "B22003",
    "B23025",
    "B19051",
    "B19055",
    "B19056",
    "B19057",
    "C27007",
]


def fetch_state(state: str, year: int, api_key: str | None) -> dict[str, Any]:
    """Fetch all ACS tables for one state (6 HTTP requests).

    Args:
        state: Two-letter state abbreviation, e.g. 'VA'.
        year:  ACS vintage year, e.g. 2022.
        api_key: Census API key or None (unauthenticated: 500 req/day).

    Returns:
        Raw response dict keyed by table group name.

    Raises:
        KeyError: Unknown state abbreviation.
        httpx.HTTPStatusError: On Census API HTTP errors.
    """
    fips = FIPS_CODES[state.upper()]
    base_url = f"{_BASE_URL}/{year}/acs/acs5"
    base_params: dict[str, str] = {"for": f"state:{fips}"}
    if api_key:
        base_params["key"] = api_key

    groups = {
        "income": INCOME_VARS,
        "poverty": POVERTY_VARS,
        "housing": HOUSING_VARS,
        "demographics": DEMOGRAPHIC_VARS,
        "income_sources": INCOME_SOURCE_VARS,
        "health": HEALTH_VARS,
    }
    with httpx.Client() as client:
        return {name: _get(client, base_url, {**base_params, "get": ",".join(vs)}) for name, vs in groups.items()}


def _reader(rows: list[list[str]]) -> Callable[[str], int]:
    """Return a lookup function var -> int for a [header, values] Census response."""
    header, values = rows[0], rows[1]

    def get(var: str) -> int:
        return _safe_int(values[header.index(var)])

    return get


def build_state_census_json(state: str, year: int, api_key: str | None) -> dict[str, Any]:
    """Fetch ACS data for one state and build the census JSON dict.

    Every rate is computed over the universe the sampler applies it to: rates
    used per household (children, elderly/disabled, earnings, SNAP receipt)
    come from household-universe tables, not person or family tables.

    Args:
        state: Two-letter state abbreviation.
        year:  ACS vintage year.
        api_key: Census API key or None.

    Returns:
        Dict matching the schema in data/census/<state>.json.
    """
    raw = fetch_state(state, year, api_key)
    inc = _reader(raw["income"])
    pov = _reader(raw["poverty"])
    hsg = _reader(raw["housing"])
    dem = _reader(raw["demographics"])
    isrc = _reader(raw["income_sources"])
    hlth = _reader(raw["health"])

    # -- Income (household, B19001) --
    bracket_counts = [inc(v) for v in INCOME_VARS]
    total_hh_inc = sum(bracket_counts) or 1
    top_rep = _top_bracket_representative(bracket_counts[-2], bracket_counts[-1])
    buckets_raw = [
        {
            "label": _INCOME_BRACKET_LABELS[i],
            "annual_lower": lo,
            "annual_upper": hi,
            "annual_midpoint": _INCOME_BRACKET_MIDPOINTS[i] if hi is not None else top_rep,
            "weight": round(c / total_hh_inc, 4),
        }
        for i, (c, (lo, hi)) in enumerate(zip(bracket_counts, _INCOME_BRACKETS, strict=True))
    ]
    mu, sigma = fit_lognormal(buckets_raw)

    # -- Ratio of income to poverty level (persons, C17002) --
    pov_total = pov("C17002_001E")
    fpl_buckets = [{"fpl_pct": upper, "weight": _safe_rate(pov(var), pov_total)} for var, upper in _FPL_BINS]

    # -- Housing --
    burden_high = sum(hsg(v) for v in _vars("B25070", [7, 8, 9, 10]))
    # Exclude "not computed" (zero/negative income or no cash rent) from the base.
    burden_base = hsg("B25070_001E") - hsg("B25070_011E")

    # -- Age of householder (B25007, owners + renters) --
    age_counts = [
        hsg(o) + hsg(r)
        for o, r in zip(_vars("B25007", list(range(3, 12))), _vars("B25007", list(range(13, 22))), strict=True)
    ]
    age_total = sum(age_counts)
    if age_total > 0:
        age_mu = sum(c * a for c, (_, a) in zip(age_counts, _HOUSEHOLDER_AGE_BINS, strict=True)) / age_total
        age_var = (
            sum(c * (a - age_mu) ** 2 for c, (_, a) in zip(age_counts, _HOUSEHOLDER_AGE_BINS, strict=True)) / age_total
        )
        age_sigma = math.sqrt(age_var)
    else:
        age_mu, age_sigma = 40.0, 15.0
    age_buckets = [
        {"label": label, "weight": _safe_rate(c, age_total)}
        for c, (label, _) in zip(age_counts, _HOUSEHOLDER_AGE_BINS, strict=True)
    ]

    # -- Household size (B11016), family + nonfamily; bucket 6 is "6 or more" --
    raw_hh = [
        dem("B11016_010E"),
        dem("B11016_003E") + dem("B11016_011E"),
        dem("B11016_004E") + dem("B11016_012E"),
        dem("B11016_005E") + dem("B11016_013E"),
        dem("B11016_006E") + dem("B11016_014E"),
        dem("B11016_007E") + dem("B11016_008E") + dem("B11016_015E") + dem("B11016_016E"),
    ]
    hh_total = sum(raw_hh) or 1
    hh_weights = [round(c / hh_total, 4) for c in raw_hh]
    # Re-normalize to exactly 1.0 by adjusting last element
    hh_weights[-1] = round(hh_weights[-1] + (1.0 - sum(hh_weights)), 4)

    # -- Children: share of ALL households with 1+ person under 18 (B11005) --
    pct_with_children = _safe_rate(dem("B11005_002E"), dem("B11005_001E"))

    # -- Elderly/disabled at the household level --
    # SNAP's "elderly" is 60+ (7 CFR 271.2), so use B11006 (households with
    # someone 60+), and B22010 for households with 1+ person with a disability.
    # ACS publishes no cross-tab of the two, so the union assumes independence.
    # Disability and age are positively correlated, so this is an upper bound
    # on the true union; the true value lies in [max(p60, pdis), this].
    pct_hh_60_plus = _safe_rate(dem("B11006_002E"), dem("B11006_001E"))
    pct_hh_disability = _safe_rate(dem("B22010_003E") + dem("B22010_006E"), dem("B22010_001E"))
    pct_eld_dis = round(pct_hh_60_plus + pct_hh_disability - pct_hh_60_plus * pct_hh_disability, 4)

    # -- Citizenship (persons, B05001) --
    pop_b05 = dem("B05001_001E")
    pct_noncitizen = _safe_rate(dem("B05001_006E"), pop_b05)
    pct_citizen = round(1.0 - pct_noncitizen, 4) if pop_b05 > 0 else 0.0
    pct_noncitizen_eligible = round(pct_noncitizen * _NONCITIZEN_QUALIFIED_SHARE, 4)

    # -- Medicaid / means-tested public coverage (persons, C27007) --
    medicaid = sum(hlth(v) for v in _vars("C27007", [4, 7, 10, 14, 17, 20]))

    return {
        "_metadata": {
            "state": state.upper(),
            "acs_vintage": year,
            "acs_survey": "acs5",
            "dollar_year": year,
            "fetch_date": date.today().isoformat(),
            "tables": list(_TABLES),
            "notes": {
                "income": "Household income in dollar_year dollars; not inflated to the program year.",
                "fpl_buckets": "Persons (C17002), not households. fpl_pct = bin upper bound; null = open-ended.",
                "pct_elderly_or_disabled": "B11006 (60+) union B22010 (disability), independence assumed; upper bound.",
                "pct_noncitizen_eligible": f"Non-citizen share x {_NONCITIZEN_QUALIFIED_SHARE} (DHS LPR share).",
                "medicaid_coverage_rate": "Persons with Medicaid/means-tested public coverage (C27007).",
            },
        },
        "income": {
            "monthly_lognormal": {"mu": mu, "sigma": sigma},
            "fpl_buckets": fpl_buckets,
            "buckets_raw": buckets_raw,
        },
        "housing": {
            "median_gross_rent_monthly": hsg("B25064_001E"),
            "pct_renter": _safe_rate(hsg("B25003_003E"), hsg("B25003_001E")),
            "rent_burden_pct": _safe_rate(burden_high, burden_base),
        },
        "household_size": {
            "weights": hh_weights,
        },
        "demographics": {
            "pct_with_children": pct_with_children,
            "pct_elderly_or_disabled": pct_eld_dis,
            "pct_households_60_plus": pct_hh_60_plus,
            "pct_households_with_disability": pct_hh_disability,
            "pct_citizen": pct_citizen,
            "pct_noncitizen": pct_noncitizen,
            "pct_noncitizen_eligible": pct_noncitizen_eligible,
            "age": {"mu": round(age_mu, 2), "sigma": round(age_sigma, 2), "householder_buckets": age_buckets},
        },
        "income_sources": {
            "labor_force_participation_rate": _safe_rate(isrc("B23025_002E"), isrc("B23025_001E")),
            "pct_households_with_earnings": _safe_rate(isrc("B19051_002E"), isrc("B19051_001E")),
            "pct_social_security": _safe_rate(isrc("B19055_002E"), isrc("B19055_001E")),
            "pct_ssi": _safe_rate(isrc("B19056_002E"), isrc("B19056_001E")),
            "pct_public_assistance": _safe_rate(isrc("B19057_002E"), isrc("B19057_001E")),
        },
        "program_participation": {
            "snap_receipt_rate": _safe_rate(isrc("B22003_002E"), isrc("B22003_001E")),
            "medicaid_coverage_rate": _safe_rate(medicaid, hlth("C27007_001E")),
        },
    }


def write_state_file(state: str, data: dict[str, Any], data_dir: Path) -> Path:
    """Write state census JSON atomically (tmp file -> os.replace).

    Args:
        state: Two-letter state code.
        data:  Dict from build_state_census_json.
        data_dir: Target directory (created if absent).

    Returns:
        Path to the written file.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{state.lower()}.json"
    target = data_dir / filename
    tmp = data_dir / f"{filename}.tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    os.replace(tmp, target)
    return target
