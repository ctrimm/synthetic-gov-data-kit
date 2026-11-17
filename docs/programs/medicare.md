# Medicare Savings Programs and Extra Help

Federal floor for the two low-income Medicare programs, CY2026
(`data/thresholds/medicare_cy2026.json`, preset `medicare.national`).

## Rules modeled

| Program | Income (countable, after $20 disregard) | Resources | Pays |
|---|---|---|---|
| QMB | ≤ 100% FPL | $9,950 / $14,910 couple | Part A/B premiums and cost sharing |
| SLMB | ≤ 120% FPL | same | Part B premium |
| QI | ≤ 135% FPL | same | Part B premium (first come, first served) |
| Extra Help (Part D LIS) | ≤ 150% FPL (annual) | $18,090 / $36,100 couple | Part D premiums and cost sharing |

The monthly gross limits Medicare.gov publishes for 2026 (QMB $1,350 / $1,824; SLMB
$1,616 / $2,184; QI $1,816 / $2,455) are `ceil(FPL × pct / 12) + $20`. `MedicareSource`
derives them from `us_fpl_2026.json`, so Alaska and Hawaii get their own guidelines, and
`tests/unit/test_medicare_source.py` checks every derived figure against the published one.

## Case types

- `msp_tier`: QMB / SLMB / QI / none, with income placed on and around each tier boundary and
  resources around the limit. The rationale checks resources, then each tier in order.
- `extra_help`: income around 150% FPL and resources around the Extra Help limit.

## Not modeled

State MSP expansions (higher income disregards, no resource test), QDWI, earned income in
MSP/LIS income counting, and Medicare Part A buy-in mechanics.

## Sources

- [Medicare.gov — Medicare Savings Programs](https://www.medicare.gov/basics/costs/help/medicare-savings-programs) (2026 limits)
- [SSA POMS HI 03001.020](https://secure.ssa.gov/poms.nsf/lnx/0603001020) (2026 Extra Help resource limits)
- 42 U.S.C. 1396d(p), 1396a(a)(10)(E); 42 CFR 423.773
