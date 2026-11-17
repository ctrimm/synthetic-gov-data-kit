"""SNAP (Supplemental Nutrition Assistance Program) data source connector.

Data sourced from:
  - USDA FNS SNAP COLA tables, one verified file per fiscal year (FY2021-FY2026)
  - data/thresholds/snap_fy{fiscal_year}.json

FISCAL YEAR:
  SNAP runs on the federal fiscal year: October 1 – September 30.
  FY2026 = Oct 1, 2025 – Sep 30, 2026 (current as of March 2026).
  FY2026 thresholds use the 2025 HHS poverty guidelines as their basis.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from govsynth.fiscal_year import DEFAULT_SNAP_FY, FiscalYearConfig
from govsynth.sources.base import THRESHOLD_DIR, DataSource, HouseholdThreshold, ProgramThresholds, _load_json_file

# Broad-based categorical eligibility (BBCE) is modeled by SNAPBBCESource
# (govsynth/sources/us/snap_bbce.py), driven by the per-state data table in
# data/thresholds/snap_bbce_*.json. SNAPSource itself models only the federal
# baseline (130% FPL gross, 100% FPL net, $3,000/$4,500 asset limits). A derived,
# data-backed `BBCE_STATES` set is available from snap_bbce for callers that need it.

# Alaska regions for allotment purposes
ALASKA_RURAL1 = {
    "Bethel",
    "Dillingham",
    "Nome",
    "Kodiak Island",
    "Lake and Peninsula",
    "Bristol Bay",
    "Aleutians West",
    "Aleutians East",
}


_DEDUCTION_REGIONS = ("48_states_dc", "alaska", "hawaii", "guam", "virgin_islands")


@lru_cache(maxsize=512)
def get_standard_deduction(
    household_size: int, region: str = "48_states_dc", fiscal_year: int = DEFAULT_SNAP_FY
) -> float:
    """Return the SNAP standard deduction for a household size, region and fiscal year.

    Read from ``standard_deductions_<region>`` in ``data/thresholds/snap_fy<YEAR>.json``,
    which carries the FNS COLA table for that fiscal year (keys "1".."5" and "6+").

    Raises ValueError for a region not in `_DEDUCTION_REGIONS` and KeyError for a household
    size the region's table has no entry for. This function used to silently
    fall back to the 48-states-and-DC table for any unrecognized region (via
    `tables.get(region, tables["48_states_dc"])`) and to 209 for any unrecognized
    size (via `t.get(..., 209)`) -- exactly the failure mode that, before this
    fiscal year's data was added, made Guam and the U.S. Virgin Islands
    silently receive the wrong standard deduction with no test able to catch
    it. If a future region is added to `_region_for_state` without a matching
    entry here, it must fail loudly instead of quietly regressing the same way.
    It also used to hard-code the FY2026 amounts, so any other fiscal year silently
    got FY2026 deductions; they now come from that year's data file.
    """
    if region not in _DEDUCTION_REGIONS:
        raise ValueError(
            f"get_standard_deduction: unrecognized region {region!r}; known regions: {sorted(_DEDUCTION_REGIONS)}"
        )
    path = THRESHOLD_DIR / FiscalYearConfig.for_program("snap", fiscal_year).threshold_filename
    table = _load_json_file(str(path))[f"standard_deductions_{region}"]
    key = "6+" if household_size >= 6 else str(household_size)
    if key not in table:
        raise KeyError(f"get_standard_deduction: region {region!r} has no entry for household size {key}")
    return float(table[key])


def _region_for_state(state: str) -> str:
    if state == "AK":
        return "alaska"
    if state == "HI":
        return "hawaii"
    if state == "GU":
        return "guam"
    if state == "VI":
        return "virgin_islands"
    return "48_states_dc"


@dataclass(frozen=True)
class NetIncomeBreakdown:
    """The steps of the SNAP net income calculation (7 CFR 273.9(d)), in order."""

    gross_income: float
    earned_income: float
    earned_deduction_pct: float
    earned_deduction: float
    after_earned: float
    standard_deduction: float
    after_standard: float
    dependent_care_deduction: float
    medical_deduction: float
    after_medical: float
    shelter_costs: float
    half_adjusted_income: float
    excess_shelter: float
    shelter_cap: float
    shelter_capped: bool
    shelter_deduction: float
    is_homeless: bool
    net_income: float


class SNAPSource(DataSource):
    """SNAP eligibility data source.

    Args:
        fiscal_year: Federal fiscal year (Oct 1–Sep 30). Default FY2026.
        state: Two-letter state code or 'national'.
    """

    def __init__(self, fiscal_year: int = DEFAULT_SNAP_FY, state: str = "national") -> None:
        super().__init__(year=fiscal_year, state=state)
        self.fy_config = FiscalYearConfig.for_program("snap", fiscal_year)
        self._region = _region_for_state(self.state)

    @property
    def program(self) -> str:
        return "snap"

    def fetch_thresholds(self) -> ProgramThresholds:
        raw = self._load_threshold_json(self.fy_config.threshold_filename)

        region_key = f"households_{self._region}"
        raw_hh = raw[region_key]

        households: dict[int, HouseholdThreshold] = {}
        for key, val in raw_hh.items():
            if key == "each_additional":
                continue
            size = int(key)
            # Alaska has per-region allotments; use urban as default
            max_b = val.get("max_benefit") or val.get("max_benefit_urban") or 0.0
            households[size] = HouseholdThreshold(
                household_size=size,
                gross_monthly=float(val["gross_monthly"]),
                net_monthly=float(val["net_monthly"]),
                max_benefit=float(max_b),
            )

        # Federal baseline asset limit. BBCE waivers/caps are applied by SNAPBBCESource.
        asset_limit: float | None = float(raw["asset_limit_general"])

        std_deductions = {size: get_standard_deduction(size, self._region, self.year) for size in range(1, 9)}

        shelter_key = f"excess_shelter_deduction_cap_{self._region}"
        shelter_cap = float(raw.get(shelter_key, raw.get("excess_shelter_deduction_cap_48_states_dc", 744)))

        # Minimum benefit resolves by region, same as the shelter cap above. Alaska has
        # three allotment tiers (Urban/Rural 1/Rural 2); this kit models a single Alaska
        # region and already defaults its *max* allotment to the Urban tier (see
        # `max_benefit_urban` fallback above), so `minimum_benefit_alaska` is the Urban
        # figure too, for consistency with that existing default rather than a new choice.
        minimum_benefit_key = f"minimum_benefit_{self._region}"
        minimum_benefit = float(raw.get(minimum_benefit_key, raw.get("minimum_benefit_48_states_dc", 24)))

        return ProgramThresholds(
            program="snap",
            fiscal_year=raw["_metadata"]["fiscal_year"],
            state=self.state,
            source=raw["_metadata"]["source"],
            source_url=raw["_metadata"].get("source_url"),
            households=households,
            asset_limit_general=asset_limit,
            asset_limit_elderly_disabled=float(raw["asset_limit_elderly_disabled"]),
            earned_income_deduction_pct=float(raw["earned_income_deduction_pct"]),
            standard_deductions=std_deductions,
            extra={
                "excess_shelter_cap": shelter_cap,
                "homeless_shelter_deduction": float(raw["homeless_shelter_deduction"]),
                "minimum_benefit": minimum_benefit,
                "cfr_reference": raw["_metadata"]["cfr_reference"],
                "region": self._region,
                "verification_status": raw["_metadata"]["verification_status"],
            },
        )

    def fetch_policy_summary(self) -> str:
        t = self.thresholds()
        assert t.extra is not None, "SNAP thresholds always populate `extra`"
        sd = {size: get_standard_deduction(size, self._region, self.year) for size in (1, 4, 5, 6)}
        asset_note = (
            f"Asset limits: ${t.asset_limit_general:,.0f} general, "
            f"${t.asset_limit_elderly_disabled:,.0f} elderly/disabled (60+ or disabled)."
        )
        return (
            f"SNAP Eligibility Rules ({self.fy_config.period_label}, {self.state}):\n"
            f"  [Based on {self.fy_config.fpl_year} HHS poverty guidelines]\n"
            f"- Gross income test: ≤130% FPL (7 CFR 273.9(a)(1))\n"
            f"- Net income test: ≤100% FPL (7 CFR 273.9(a)(2))\n"
            f"- Deductions: 20% earned income + standard deduction + allowable shelter/utility (7 CFR 273.9(d))\n"
            f"- {asset_note}\n"
            f"- Elderly/disabled: exempt from gross income test; "
            f"${t.asset_limit_elderly_disabled:,.0f} asset limit.\n"
            f"- Standard deduction (HH 1-3): ${sd[1]:,.0f}/month; HH4: ${sd[4]:,.0f}; "
            f"HH5: ${sd[5]:,.0f}; HH6+: ${sd[6]:,.0f}.\n"
            f"- Excess shelter cap: ${t.extra['excess_shelter_cap']:,.0f}/month.\n"
            f"Source: {t.source}"
        )

    def calculate_net_income(
        self,
        gross_income: float,
        household_size: int,
        earned_income: float | None = None,
        shelter_costs: float | None = None,
        dependent_care: float | None = None,
        medical_expenses: float = 0.0,
        has_elderly_or_disabled: bool = False,
        is_homeless: bool = False,
    ) -> float:
        """Apply 7 CFR 273.9(d) deductions to arrive at SNAP net income."""
        return self.net_income_breakdown(
            gross_income=gross_income,
            household_size=household_size,
            earned_income=earned_income,
            shelter_costs=shelter_costs,
            dependent_care=dependent_care,
            medical_expenses=medical_expenses,
            has_elderly_or_disabled=has_elderly_or_disabled,
            is_homeless=is_homeless,
        ).net_income

    def net_income_breakdown(
        self,
        gross_income: float,
        household_size: int,
        earned_income: float | None = None,
        shelter_costs: float | None = None,
        dependent_care: float | None = None,
        medical_expenses: float = 0.0,
        has_elderly_or_disabled: bool = False,
        is_homeless: bool = False,
    ) -> NetIncomeBreakdown:
        """Every intermediate amount of the 7 CFR 273.9(d) net income calculation.

        `calculate_net_income` returns this breakdown's ``net_income``, and rationale
        traces render the same breakdown, so a trace's arithmetic always reaches the
        net income the case is judged on.

        Raises:
            ValueError: If ``is_homeless`` is combined with positive shelter costs.
        """
        if is_homeless and shelter_costs and shelter_costs > 0:
            raise ValueError("is_homeless and shelter_costs > 0 are mutually exclusive")

        t = self.thresholds()
        assert t.extra is not None, "SNAP thresholds always populate `extra`"
        earned = earned_income if earned_income is not None else gross_income
        earned_pct = float(t.earned_income_deduction_pct or 20)

        # (d)(2) Earned income deduction -- 20% of earned income only
        earned_ded = earned * earned_pct / 100.0
        after_earned = gross_income - earned_ded

        # (d)(1) Standard deduction
        std_ded = float(get_standard_deduction(household_size, self._region, self.year))
        after_standard = after_earned - std_ded

        # (d)(4) Dependent care deduction
        dep_ded = dependent_care or 0.0
        after_dep_care = after_standard - dep_ded

        # (d)(3) Excess medical deduction for elderly/disabled (over $35 threshold)
        medical_ded = max(0.0, medical_expenses - 35) if has_elderly_or_disabled else 0.0
        after_medical = after_dep_care - medical_ded

        # (d)(6) Shelter deduction -- homeless flat deduction or excess shelter calculation.
        # Per 7 CFR 273.9(d)(6)(i)-(ii), these two paths are mutually exclusive.
        shelter_cap = float(t.extra["excess_shelter_cap"]) if t.extra else 744.0
        half_income = max(0.0, after_medical) * 0.5
        raw_excess = 0.0
        capped = False
        if is_homeless:
            shelter_ded = float(t.extra["homeless_shelter_deduction"])
        else:
            shelter_ded = 0.0
            if shelter_costs:
                raw_excess = max(0.0, shelter_costs - half_income)
                shelter_ded = raw_excess if has_elderly_or_disabled else min(raw_excess, shelter_cap)
                capped = shelter_ded < raw_excess

        return NetIncomeBreakdown(
            gross_income=gross_income,
            earned_income=earned,
            earned_deduction_pct=earned_pct,
            earned_deduction=earned_ded,
            after_earned=after_earned,
            standard_deduction=std_ded,
            after_standard=after_standard,
            dependent_care_deduction=dep_ded,
            medical_deduction=medical_ded,
            after_medical=after_medical,
            shelter_costs=float(shelter_costs or 0.0),
            half_adjusted_income=half_income,
            excess_shelter=raw_excess,
            shelter_cap=shelter_cap,
            shelter_capped=capped,
            shelter_deduction=shelter_ded,
            is_homeless=is_homeless,
            net_income=max(0.0, after_medical - shelter_ded),
        )

    def is_eligible(
        self,
        household_size: int,
        gross_income: float,
        net_income: float | None = None,
        liquid_assets: float = 0.0,
        has_elderly_or_disabled: bool = False,
        is_categorically_eligible: bool = False,
    ) -> tuple[bool, str]:
        """Determine SNAP eligibility. Returns (is_eligible, reason)."""
        if is_categorically_eligible:
            return True, "Categorically eligible (receives TANF/SSI or state BBCE program)"

        t = self.thresholds()
        limits = t.by_household_size(min(household_size, 8))

        # Gross income test — waived for elderly/disabled
        if not has_elderly_or_disabled and gross_income > limits.gross_monthly:
            return False, (
                f"Ineligible: gross income ${gross_income:,.2f} exceeds "
                f"${limits.gross_monthly:,.2f} (130% FPL, {self.fy_config.period_label}, "
                f"{household_size}-person HH)"
            )

        # Net income test
        eff_net = net_income if net_income is not None else gross_income
        if eff_net > limits.net_monthly:
            return False, (
                f"Ineligible: net income ${eff_net:,.2f} exceeds "
                f"${limits.net_monthly:,.2f} (100% FPL, {household_size}-person HH)"
            )

        # Asset test — may be waived by BBCE
        if t.asset_limit_general is not None:
            asset_cap = t.asset_limit_elderly_disabled if has_elderly_or_disabled else t.asset_limit_general
            if asset_cap and liquid_assets > asset_cap:
                return False, (f"Ineligible: assets ${liquid_assets:,.2f} exceed ${asset_cap:,.2f} limit")

        return True, "Eligible: all tests passed (gross income, net income, assets)"
