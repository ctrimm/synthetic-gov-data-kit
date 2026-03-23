# data/thresholds/

Policy threshold tables for US government benefits programs.

---

## Naming Convention

Files use **period-prefixed** names to make the calendar system explicit:

```
{program}_fy{year}.json    — Federal fiscal year (Oct 1 – Sep 30)
{program}_cy{year}.json    — Calendar year (Jan 1 – Dec 31)
us_fpl_{year}.json         — HHS Poverty Guidelines (calendar year, published ~Jan 15)
```

### Examples

| File | Period | In Effect |
|---|---|---|
| `snap_fy2026.json` | FY2026 | Oct 1, 2025 – Sep 30, 2026 |
| `wic_fy2026.json` | FY2026 | Oct 1, 2025 – Sep 30, 2026 |
| `medicaid_cy2026.json` | CY2026 | Jan 1, 2026 – Dec 31, 2026 |
| `us_fpl_2025.json` | CY2025 | ~Jan 15, 2025 onward |
| `us_fpl_2026.json` | CY2026 | ~Jan 15, 2026 onward |

---

## The Two Calendars

### Federal Fiscal Year (FY)
- Runs **October 1 – September 30**
- Used by: SNAP, WIC, CHIP, Section 8/HCV, LIHEAP, TANF
- **FY2026 = Oct 1, 2025 – Sep 30, 2026** ← current period as of March 2026
- Programs that follow the federal FY update their income limits every October

### HHS Poverty Guidelines (Calendar Year)
- Published by HHS ASPE each **January** (~January 15)
- Used directly by: **Medicaid** (MAGI-based), ACA marketplace
- **2026 guidelines** = in effect now (March 2026)

### The Critical Relationship: FY → FPL Basis Year

Federal FY programs (SNAP, WIC) use the **previous January's** poverty guidelines
as the basis for that fiscal year's income limits:

```
SNAP FY2026 income limits → calculated from 2025 HHS poverty guidelines
SNAP FY2027 income limits → will use 2026 HHS poverty guidelines
```

This means:
- `snap_fy2026.json` references `us_fpl_2025.json` as its basis
- `medicaid_cy2026.json` references `us_fpl_2026.json` as its basis

The `govsynth.fiscal_year` module handles all of this automatically.

---

## Current Status (as of March 2026)

| File | Status | Notes |
|---|---|---|
| `snap_fy2026.json` | ⚠️ Estimated | Verify at fns.usda.gov |
| `wic_fy2026.json` | ⚠️ Estimated | Verify at fns.usda.gov |
| `medicaid_cy2026.json` | ⚠️ Estimated | Verify at kff.org / cms.gov |
| `us_fpl_2025.json` | ✅ Published | HHS ASPE, Jan 2025 |
| `us_fpl_2026.json` | ⚠️ Estimated | Verify at aspe.hhs.gov |

**⚠️ = Estimated values.** All threshold files with `verification_status: "estimated"` in their
`_metadata` block must be verified against official government publications before use in
production evaluations. Incorrect thresholds produce incorrect ground-truth labels.

---

## How to Verify & Update Thresholds

### SNAP FY Thresholds
1. Go to: https://www.fns.usda.gov/snap/recipient/eligibility
2. Download the "SNAP Income and Allotment Table" for the current FY
3. Update the `households` block in `snap_fy{year}.json`
4. Change `verification_status` from `"estimated"` to `"verified"`
5. Add the publication date and document title to `_metadata.source`

### WIC FY Thresholds
1. Go to: https://www.fns.usda.gov/wic/wic-income-eligibility-guidelines
2. Find the current FY income eligibility table
3. Update `wic_fy{year}.json`

### HHS Poverty Guidelines
1. Go to: https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines
2. Published each January ~15th
3. Update `us_fpl_{year}.json`

### Medicaid
1. Go to: https://www.kff.org/medicaid/state-indicator/medicaid-income-eligibility-limits/
2. Also check: https://www.medicaid.gov/medicaid/eligibility/index.html
3. Update `medicaid_cy{year}.json`

---

## Adding a New Year

When a new fiscal year begins (October 1) or new FPL guidelines are published (January):

```bash
# Copy the prior year file as starting point
cp snap_fy2026.json snap_fy2027.json

# Update _metadata, fiscal_year, federal_fy_start/end, fpl_basis_year
# Update all household dollar amounts from official published tables
# Set verification_status to "verified" once confirmed
# Run: pytest tests/unit/test_thresholds.py
```

The `govsynth.fiscal_year` module's `FEDERAL_FY_TO_FPL_YEAR` dict must also be updated
in `govsynth/fiscal_year.py` to include the new year mapping.

---

## Schema Reference

Every threshold file must have a `_metadata` block:

```json
{
  "_metadata": {
    "program": "snap",
    "period": "FY2026",
    "fiscal_year": 2026,
    "federal_fy_start": "2025-10-01",
    "federal_fy_end": "2026-09-30",
    "fpl_basis_year": 2025,
    "source": "...",
    "source_url": "...",
    "cfr_reference": "...",
    "verification_status": "estimated | verified",
    "verification_note": "..."
  }
}
```
