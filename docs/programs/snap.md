# SNAP — Supplemental Nutrition Assistance Program

**Agency:** USDA Food and Nutrition Service (FNS)
**Regulation:** [7 CFR Part 273](https://www.ecfr.gov/current/title-7/part-273)
**Fiscal Year:** FY2026 (October 1, 2025 – September 30, 2026)

---

## Eligibility Rules Overview

SNAP eligibility for most households requires passing three tests:

| Test | Rule | Threshold |
|---|---|---|
| Gross income | 7 CFR 273.9(a)(1) | ≤ 130% FPL |
| Net income | 7 CFR 273.9(a)(2) | ≤ 100% FPL |
| Assets | 7 CFR 273.8(b) | ≤ $2,500 general / ≤ $4,500 elderly or disabled |

**Exceptions:** Elderly/disabled households skip the gross income test. Households with TANF/SSI recipients skip all income tests (traditional categorical eligibility). Broad-Based Categorical Eligibility (BBCE) states **raise the gross income limit** (up to 200% FPL) **and** waive or raise the asset test — but the 100% FPL net income test still applies. See edge case 7 below and [`govsynth/sources/us/snap_bbce.py`](../../govsynth/sources/us/snap_bbce.py).

### Standard Deductions (FY2026, 48 States + DC)

| Household Size | Standard Deduction |
|---|---|
| 1–3 | $209/month |
| 4 | $223/month |
| 5 | $261/month |
| 6+ | $299/month |

### Net Income Calculation (7 CFR 273.9(c))

```
Net income = Gross income
           − 20% earned income deduction    [273.9(c)(1)]
           − Standard deduction             [273.9(c)(2)]
           − Dependent care deduction       [273.9(c)(3)]
           − Medical expense deduction*     [273.9(c)(4)]
           − Excess shelter deduction†      [273.9(c)(5)]
```

\* Medical deduction applies only to elderly/disabled households; expenses over $35/month.
† Excess shelter deduction is capped at $744/month unless the household contains an elderly or disabled member.

---

## Presets

| Preset | State | Gross limit | Asset Test | Notes |
|---|---|---|---|---|
| `snap.va` | Virginia | 200% FPL (BBCE) | Waived (BBCE) | Default for most examples |
| `snap.ca` | California | 200% FPL (BBCE) | Waived (BBCE) | |
| `snap.tx` | Texas | 165% FPL (BBCE) | $5,000 cap (BBCE) | Demonstrates a BBCE state with a dollar asset cap |
| `snap.md` | Maryland | 200% FPL (BBCE) | Waived (BBCE) | |

Per-state BBCE parameters (gross income limit, asset rule, conferring benefit) are tracked in `data/thresholds/snap_bbce_fy2026.json` and applied by `govsynth/sources/us/snap_bbce.py::SNAPBBCESource`, which the SNAP generator uses for the main threshold path and the BBCE edge case. `SNAPSource` models only the federal baseline (130% FPL gross, $3,000/$4,500 assets). A data-backed `BBCE_STATES` set (and `bbce_states(fiscal_year)`) is exported from `snap_bbce` for callers that need the current membership.

---

## Profile Strategies

```python
Pipeline.from_preset("snap.va", profile_strategy="edge_saturated")
# 80% threshold-boundary profiles, 20% special-population edge cases
# Recommended for stress-testing LLM reasoning

Pipeline.from_preset("snap.va", profile_strategy="realistic")
# Census ACS distributions; SNAP rules follow each profile's census year

Pipeline.from_preset("snap.va", profile_strategy="realistic", population="caseload")
# Households that actually receive SNAP (FNS SNAP QC characteristics, FY2024)

Pipeline.from_preset("snap.va", profile_strategy="uniform")
# National approximations, no census data required
```

### Caseload population

`population="caseload"` draws from the SNAP Quality Control tables in
`data/caseload/snap_qc_fy2024.json`, imported from the FNS report *Characteristics of
Supplemental Nutrition Assistance Program Households: Fiscal Year 2024* (SNAP-24-CHAR,
revised August 2026 with corrected weights) by `scripts/import_snap_qc.py`.

| Report table | Used for |
|---|---|
| A.3 | composition x gross income as % of poverty (national) |
| A.4 | household size x % of poverty (national) |
| A.6 | composition x earned income, SSI, Social Security (national) |
| A.17 | children x elderly / disabled, composition x size (national) |
| B.2 | state average gross income (calibrates the open top income bin) |
| B.3, B.5, B.6 | state % of poverty bins, composition, income sources |
| B.16 | state noncitizen share of participants |

The national cross-tabs are fit jointly with iterative proportional fitting, then raked to
each state's marginals. Within a cell, gross income is uniform over its poverty bin, evaluated
with the poverty guideline of the rules year (FY *Y* uses the year *Y*-1 guideline). The
report's top bin ("131 percent or greater") is open, because elderly and disabled households
have no gross limit; its upper end is set per state, between 140% and 400%, so mean gross
income matches Table B.2. Known simplifications:

- Earned income is all of gross for earners without SSI or Social Security, and half for those
  with either. The report gives source shares, not per-household amounts.
- One-person households with children (child-only units, 1.3% nationally) are rendered
  without dependent children.
- Countable resources are nonzero for 1.6% of households (Table A.17), averaging $550 (A.5).
- Noncitizen participants are rendered as qualified aliens.
- Shelter costs come from the state's ACS rents. The general eligibility path does not apply
  the excess shelter deduction, so some caseload households in the top income bin fail the
  net income test even though real ones would pass.

`govsynth validate-distribution --population caseload` compares sampled profiles with the
state's QC figures (poverty bins, elderly/disabled, elderly head, earnings, SSI, Social
Security, average gross income). The test suite runs it for all 51 jurisdictions.

---

## Edge Cases

The `edge_saturated` strategy generates two pools of cases:

- **80% threshold-boundary cases** — income or assets placed exactly at, just above, or just below a threshold boundary
- **20% special-population cases** — real-world scenarios where standard rules don't apply

### Threshold-Boundary Types

| Type | What it tests |
|---|---|
| `gross_income_limit` | Gross income at 130% FPL |
| `net_income_limit` | Net income at 100% FPL |
| `asset_limit_general` | Assets at $2,500 (strict-test states only) |
| `asset_limit_elderly_disabled` | Assets at $4,500 (elderly/disabled households) |

### Special-Population Edge Cases

These are the scenarios LLMs most commonly misapply. Each is implemented as a dedicated builder that constructs a `TestCase` with a multi-step `RationaleTrace` citing the specific CFR rule.

| Edge Case | CFR Citation | Key Policy Rule | Common Model Error |
|---|---|---|---|
| **Homeless shelter deduction** | 7 CFR 273.9(c)(6) | Flat $198.99 deduction applied **instead of** the excess shelter deduction — these are mutually exclusive | Applies the excess shelter formula to a homeless household instead of substituting the flat deduction |
| **Student exclusion** | 7 CFR 273.5(a),(b) | A student enrolled at least half-time is **ineligible** unless a 273.5(b) exception applies (20+ hrs/week work, single parent, TANF, work-study). Check fires **before** the income test | Skips the student status check; income-eligible student incorrectly passes |
| **Boarder income proration** | 7 CFR 273.1(b)(7) | Only the **profit** portion of board payments counts as income (payment received minus actual cost of food/housing provided) | Counts the full board payment as income instead of only the profit |
| **Migrant income averaging** | 7 CFR 273.10(c)(3) | Seasonal/migrant income is averaged over the **work period**, not taken as a current-month snapshot | Uses current-month income (zero between jobs) or annualizes incorrectly |
| **Mixed immigration status** | 7 CFR 273.4(c)(3) | Ineligible (non-qualified alien) members are excluded from **household size** for limit lookup, but their income counts **in full** | Either prorates the ineligible member's income (that's the sponsored noncitizen rule at 273.11(c)(3)) or includes them in household size |
| **Categorical eligibility (TANF/SSI)** | 7 CFR 273.2(j)(2); 7 CFR 273.11(c) | Households with TANF/SSI recipients are categorically eligible — the income test is **skipped entirely** | Runs the income test anyway and returns ineligible for above-limit households |
| **BBCE expanded gross limit** | 7 CFR 273.2(j)(2)(ii) | A BBCE state **raises the gross limit** (up to 200% FPL) and waives/raises assets, but the **net income test still applies**. A household at 130–200% FPL gross with net ≤ 100% FPL is eligible | Applies the federal 130% limit in a BBCE state (false ineligible), or assumes BBCE also waives the net income test (false eligible) |

See [`EDGE_CASES.md`](../../EDGE_CASES.md) at the repo root for full documentation of each case including examples and planned future cases.

---

## Generating SNAP Cases

```python
from govsynth import Pipeline

# Standard generation — edge-saturated (default)
pipeline = Pipeline.from_preset("snap.va")
cases = pipeline.generate(n=100, seed=42)

# Inspect special-population cases
special = [
    c
    for c in cases
    if any(
        tag in c.variation_tags
        for tag in [
            "homeless_shelter_deduction",
            "student_exclusion",
            "boarder_income_proration",
            "migrant_income_averaging",
            "mixed_immigration_status_hh_size_reduction",
            "categorical_eligibility_tanf_ssi",
            "bbce_expanded_gross_limit",
        ]
    )
]
print(f"{len(special)} special-population cases in this batch")
```

```bash
# CLI
govsynth generate snap.va --n 100 --seed 42 --output ./output/

# Inspect variation tags across the batch
govsynth generate snap.va --n 100 --seed 42 --format jsonl | \
  jq -r '.variation_tags[]' | sort | uniq -c | sort -rn
```

---

## Fiscal Years

SNAP rules are bundled for **FY2021–FY2026** (`data/thresholds/snap_fy20XX.json`), each
transcribed from FNS's COLA tables by `scripts/import_snap_cola.py`, with every income
limit checked against the prior year's HHS poverty guidelines (`us_fpl_20XX.json`).

```python
SNAPEligibilityGenerator(fiscal_year=2022, state="VA").generate(n=100, seed=42)
```

With `profile_strategy="realistic"`, each case uses the fiscal year matching its census
year (ACS year Y → FY Y, which covers October Y-1 to September Y, nine of the twelve
months ACS year Y measures). `match_census_year=False` / `--fixed-policy-year` turns
that off.

| | FY2021–FY2025 | FY2026 |
|---|---|---|
| Income limits, allotments, deductions, asset limits | ✅ verified, FNS tables | ✅ verified |
| BBCE states, gross % and asset rule | ✅ verified, each year's FNS BBCE chart (May 2020 – Aug 2024) | ✅ Aug 2025 chart |
| Noncitizen builder (P.L. 119-21) | skipped: law not yet enacted | ✅ |
| Student builder | skipped FY2021–23 (pandemic exemptions); ✅ FY2024–25 | ✅ |

**Not modeled** (recorded in each file's `_metadata.not_modeled`): the temporary 15%
allotment increase (Jan–Sep 2021) and COVID-19 emergency allotments (through Feb 2023).
These raised benefit *amounts*; eligibility determinations are unaffected, but the
`monthly_allotment` in FY2021–FY2023 cases is the regular COLA amount.

Alaska and Arkansas adopted BBCE during 2025: both are absent from every chart through
August 2024 and present in the August 2025 chart (FY2026).

## Policy Data Sources

| Source | What it covers |
|---|---|
| [7 CFR Part 273](https://www.ecfr.gov/current/title-7/part-273) | Full eligibility rules, deductions, income definitions |
| [FNS SNAP COLA FY2026 Memo](https://www.fns.usda.gov/snap/allotment/COLA) | FY2026 income limits and allotment tables |
| FNS FY2021–FY2025 COLA tables | Per-year PDFs listed in `scripts/import_snap_cola.py` and each file's `_metadata` |
| [FNS State Options Report](https://www.fns.usda.gov/snap/state-options-report) | BBCE state list, categorical eligibility options |
| [FNS BBCE States Chart](https://www.fns.usda.gov/snap/broad-based-categorical-eligibility) | Per-state BBCE gross income limits and asset rules (basis for `snap_bbce_fy2026.json`) |
| [FNS Characteristics of SNAP Households: FY2024](https://fns-prod.azureedge.us/sites/default/files/resource-files/snap-fy2024householdcharacteristics-report.pdf) | SNAP QC caseload tables behind `population="caseload"` (`data/caseload/snap_qc_fy2024.json`) |
| `data/thresholds/snap_fy2026.json` | Bundled threshold table (income limits, asset limits, deductions) |
| `data/thresholds/snap_bbce_fy2026.json` | Per-state BBCE parameters (gross % FPL, asset rule, conferring benefit) |
| `data/seeds/us/snap/` | CFR excerpts used as rationale grounding context |
