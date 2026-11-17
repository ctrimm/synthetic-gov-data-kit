"""SNAP caseload population: who actually receives SNAP, from the SNAP Quality Control sample (#9).

The ACS describes everyone who *might* ask an eligibility question; the SNAP caseload
is far more often elderly, disabled, one-person, on SSI or Social Security, or with
no income at all. data/caseload/snap_qc_fy<YEAR>.json (scripts/import_snap_qc.py)
holds the FNS 'Characteristics of SNAP Households' tables built from the QC sample.

The sampler works on a joint table of caseload household *cells*:

    children (0/1) x elderly/disabled group (none, elderly, non-elderly disabled only)
    x household size (1..6+) x gross income as % of poverty (7 bins)
    x earned income (0/1) x SSI (0/1) x Social Security (0/1)

The national table is fit by iterative proportional fitting (IPF) to every national
cross-tabulation in the report (composition x size, composition x poverty, size x
poverty, composition x income type), so a cell's traits keep their real
correlations. Each state's table rakes the national one to the state's own
marginals (poverty bins, composition, income sources). Zero-income cells have no
income sources by construction.
"""

from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from govsynth._paths import CASELOAD_DIR, THRESHOLD_DIR
from govsynth.sources.base import _load_json_file

DEFAULT_QC_FY = 2024

GROUPS = ("none", "elderly", "disabled_only")
POV_BINS = ("none", "le25", "26_50", "51_75", "76_100", "101_130", "gt130")
# Gross income as a percent of the poverty guideline within each bin. The report's
# top bin is open ("131 percent or greater": BBCE households up to 200%, and elderly
# or disabled households, who have no gross limit). Its upper end is set per state
# so that the state's mean gross income matches Table B.2 (see top_bin_max_pct);
# 200% is only the national default.
POV_RANGES: dict[str, tuple[float, float]] = {
    "none": (0.0, 0.0),
    "le25": (0.5, 25.0),
    "26_50": (25.0, 50.0),
    "51_75": (50.0, 75.0),
    "76_100": (75.0, 100.0),
    "101_130": (100.0, 130.0),
    "gt130": (130.0, 200.0),
}
# State tables (B.3) use four coarser bins.
POV4 = {"none": 0, "le25": 1, "26_50": 1, "51_75": 2, "76_100": 2, "101_130": 3, "gt130": 3}


@dataclass(frozen=True)
class CaseloadCell:
    """One caseload household cell."""

    kids: int
    group: str
    size: int
    pov: str
    earned: int
    ssi: int
    social_security: int


def _cells() -> list[CaseloadCell]:
    out = []
    for kids, group, size, pov, e, ssi, ss in itertools.product(
        (0, 1), GROUPS, range(1, 7), POV_BINS, (0, 1), (0, 1), (0, 1)
    ):
        if pov == "none" and (e or ssi or ss):
            continue  # no countable income means no income sources
        out.append(CaseloadCell(kids, group, size, pov, e, ssi, ss))
    return out


Margin = tuple[Callable[[CaseloadCell], object], dict[object, float]]


def _ipf(cells: Sequence[CaseloadCell], weights: list[float], margins: list[Margin], iters: int = 200) -> list[float]:
    """Iterative proportional fitting of cell weights to target margins (shares)."""
    w = list(weights)
    indexed = []
    for key, target in margins:
        groups: dict[object, list[int]] = {}
        for i, c in enumerate(cells):
            groups.setdefault(key(c), []).append(i)
        total = sum(target.values())
        indexed.append([(idx, target.get(k, 0.0) / total) for k, idx in groups.items()])
    for _ in range(iters):
        worst = 0.0
        for groups_t in indexed:
            total_w = sum(w)
            for idx, share in groups_t:
                cur = sum(w[i] for i in idx) / total_w
                if cur > 0:
                    f = share / cur
                    worst = max(worst, abs(f - 1))
                    for i in idx:
                        w[i] *= f
        if worst < 1e-7:
            break
    total = sum(w)
    return [x / total for x in w]


def load_qc(fiscal_year: int = DEFAULT_QC_FY) -> dict[str, Any]:
    """The bundled QC tables for a fiscal year.

    Raises:
        ValueError: If no file is bundled for the year.
    """
    path = CASELOAD_DIR / f"snap_qc_fy{fiscal_year}.json"
    if not path.exists():
        bundled = sorted(p.stem for p in CASELOAD_DIR.glob("snap_qc_fy*.json"))
        raise ValueError(f"No SNAP QC caseload data for FY{fiscal_year}; bundled: {bundled}")
    return _load_json_file(str(path))


def _national_margins(nat: dict[str, Any]) -> list[Margin]:
    total = nat["total_households_000"]
    gt = nat["group_totals"]

    def by_kids_group(
        table: dict[str, dict[str, float]], row_total: dict[str, float]
    ) -> tuple[dict[object, float], dict[object, float]]:
        """Split (row x children) and (row x elderly/disabled group) targets out of a report column triple."""
        kids: dict[object, float] = {}
        grp: dict[object, float] = {}
        for r, cols in table.items():
            kids[(r, 1)] = cols["children"]
            kids[(r, 0)] = row_total[r] - cols["children"]
            grp[(r, "elderly")] = cols["elderly"]
            grp[(r, "disabled_only")] = cols["disabled_only"]
            grp[(r, "none")] = row_total[r] - cols["elderly"] - cols["disabled_only"]
        return kids, grp

    size_kids, size_grp = by_kids_group(nat["size_by_group"], nat["size"])
    pov_kids, pov_grp = by_kids_group(nat["pov_by_group"], nat["pov"])
    margins: list[Margin] = [
        (
            lambda c: (c.kids, c.group),
            {(int(k), g): v for k, row in nat["kids_by_ed"].items() for g, v in row.items()},
        ),
        (lambda c: (str(c.size), c.kids), size_kids),
        (lambda c: (str(c.size), c.group), size_grp),
        (lambda c: (c.pov, c.kids), pov_kids),
        (lambda c: (c.pov, c.group), pov_grp),
        (lambda c: (c.pov, str(c.size)), {(p, s): v for p, row in nat["pov_by_size"].items() for s, v in row.items()}),
    ]
    attr = {"earned": "earned", "ssi": "ssi", "social_security": "social_security"}
    for src, a in attr.items():
        by_g = nat["income_type_by_group"][src]
        yes_none = nat["income_type"][src] - by_g["elderly"] - by_g["disabled_only"]
        margins.append(
            (
                lambda c, a=a: (getattr(c, a), c.group),  # type: ignore[misc]
                {
                    (1, "elderly"): by_g["elderly"],
                    (0, "elderly"): gt["elderly"] - by_g["elderly"],
                    (1, "disabled_only"): by_g["disabled_only"],
                    (0, "disabled_only"): gt["disabled_only"] - by_g["disabled_only"],
                    (1, "none"): yes_none,
                    (0, "none"): total - gt["elderly"] - gt["disabled_only"] - yes_none,
                },
            )
        )
        margins.append(
            (
                lambda c, a=a: (getattr(c, a), c.kids),  # type: ignore[misc]
                {
                    (1, 1): by_g["children"],
                    (0, 1): gt["children"] - by_g["children"],
                    (1, 0): nat["income_type"][src] - by_g["children"],
                    (0, 0): total - gt["children"] - nat["income_type"][src] + by_g["children"],
                },
            )
        )
    return margins


def _state_margins(st: dict[str, Any]) -> list[Margin]:
    def binary(p: float) -> dict[object, float]:
        return {1: p, 0: 100.0 - p}

    disabled_only = max(st["pct_elderly_or_disabled"] - st["pct_elderly"], 0.0)
    return [
        (lambda c: POV4[c.pov], dict(enumerate(st["pov4_pct"]))),
        (lambda c: c.kids, binary(st["pct_children"])),
        (
            lambda c: c.group,
            {
                "elderly": st["pct_elderly"],
                "disabled_only": disabled_only,
                "none": 100.0 - st["pct_elderly"] - disabled_only,
            },
        ),
        (lambda c: c.earned, binary(st["pct_earned"])),
        (lambda c: c.ssi, binary(st["pct_ssi"])),
        (lambda c: c.social_security, binary(st["pct_social_security"])),
    ]


class CaseloadTable:
    """Weighted caseload cells for one state (or 'US') and fiscal year."""

    def __init__(self, cells: list[CaseloadCell], weights: list[float], qc: dict[str, Any], state: str) -> None:
        self.cells = cells
        self.weights = weights
        self.qc = qc
        self.state = state
        self.fiscal_year = int(qc["_metadata"]["fiscal_year"])
        self._cum = list(itertools.accumulate(weights))
        self.top_bin_max_pct = self._calibrate_top_bin()

    def _calibrate_top_bin(self) -> float:
        """Upper end of the open top poverty bin that reproduces the state's mean gross income.

        Mean income is linear in the top bin's upper end U: cells outside the top bin
        contribute their bin midpoint, top-bin cells (130 + U) / 2 percent of their
        poverty guideline. Solve for U and clamp to [140, 400].
        """
        target = self.qc["states"].get(self.state, {}).get("avg_gross_income")
        if target is None:
            return POV_RANGES["gt130"][1]
        fpl_year = int(self.qc["_metadata"]["fpl_basis_year"])
        fixed = top = 0.0
        for c, w in zip(self.cells, self.weights, strict=True):
            monthly = poverty_guideline_annual(c.size, self.state, fpl_year) / 12 / 100
            lo, hi = POV_RANGES[c.pov]
            if c.pov == "gt130":
                fixed += w * monthly * lo / 2
                top += w * monthly / 2
            else:
                fixed += w * monthly * (lo + hi) / 2
        total = self._cum[-1]
        u = (target * total - fixed) / top if top else POV_RANGES["gt130"][1]
        return min(max(u, 140.0), 400.0)

    def income_range_pct(self, pov: str) -> tuple[float, float]:
        """Percent-of-poverty range incomes in a bin are drawn from."""
        lo, hi = POV_RANGES[pov]
        return (lo, self.top_bin_max_pct) if pov == "gt130" else (lo, hi)

    def sample(self, rng: random.Random) -> CaseloadCell:
        """Draw one cell with probability proportional to its weight."""
        import bisect

        return self.cells[min(bisect.bisect_right(self._cum, rng.random() * self._cum[-1]), len(self.cells) - 1)]

    def share(self, pred: Callable[[CaseloadCell], bool]) -> float:
        """Weighted share of cells satisfying a predicate."""
        return sum(w for c, w in zip(self.cells, self.weights, strict=True) if pred(c)) / self._cum[-1]

    def mean_size(self) -> float:
        """Weighted mean household size (6 = six or more)."""
        return sum(c.size * w for c, w in zip(self.cells, self.weights, strict=True)) / self._cum[-1]


@lru_cache(maxsize=8)
def _national(fiscal_year: int) -> tuple[list[CaseloadCell], list[float]]:
    qc = load_qc(fiscal_year)
    cells = _cells()
    return cells, _ipf(cells, [1.0] * len(cells), _national_margins(qc["national"]))


@lru_cache(maxsize=64)
def caseload_table(state: str, fiscal_year: int = DEFAULT_QC_FY) -> CaseloadTable:
    """The caseload table for a state ('US' for the national table).

    Raises:
        ValueError: If the fiscal year or state has no QC data.
    """
    qc = load_qc(fiscal_year)
    cells, national = _national(fiscal_year)
    code = state.upper()
    if code == "US":
        return CaseloadTable(cells, national, qc, code)
    if code not in qc["states"]:
        raise ValueError(f"No SNAP QC caseload data for {code} in FY{fiscal_year}")
    return CaseloadTable(cells, _ipf(cells, national, _state_margins(qc["states"][code])), qc, code)


def poverty_guideline_annual(size: int, state: str, fpl_year: int) -> float:
    """HHS poverty guideline (annual dollars) for a household size, state region and year."""
    base, step = _fpl_region(state.upper(), fpl_year)
    return base + step * (size - 1)


@lru_cache(maxsize=64)
def _fpl_region(state: str, fpl_year: int) -> tuple[float, float]:
    fpl = _load_json_file(str(THRESHOLD_DIR / f"us_fpl_{fpl_year}.json"))
    region = {"AK": "alaska", "HI": "hawaii"}.get(state, "contiguous_48_dc")
    r = fpl["regions"][region]
    return float(r["base_annual"]), float(r["per_additional_person_annual"])
