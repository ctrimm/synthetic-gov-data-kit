# Data sources

Everything under `data/` ships inside the package (as `govsynth/data`). This page lists where each
dataset comes from and the terms it is redistributed under. Each JSON file also records its own
source in `_metadata` (`source`, `source_url`, and where relevant `verification_status`).

No file contains personal data. The census and caseload files are aggregates; the PUMS household
types (`data/census/acs5/2024/pums/`) store only weighted types backed by at least three sampled
households, never a microdata record.

## U.S. federal government works (public domain)

Works of the U.S. federal government are not subject to copyright in the United States
(17 U.S.C. § 105). The project's MIT license covers the code; these data carry no additional
restrictions. Please cite the agency.

| Files | Source | Agency |
|---|---|---|
| `thresholds/snap_fy2021.json` – `snap_fy2026.json` | SNAP Cost-of-Living Adjustment tables and memos (per-year URLs in each file and in `scripts/import_snap_cola.py`) | USDA Food and Nutrition Service |
| `thresholds/snap_bbce_fy2021.json` – `snap_bbce_fy2026.json` | SNAP Broad-Based Categorical Eligibility States Charts (FY2021–FY2025 via the Internet Archive copies cited in each file) | USDA FNS |
| `thresholds/wic_fy2026.json` | WIC Income Eligibility Guidelines, 90 FR 11598 (March 10, 2025) | USDA FNS |
| `caseload/snap_qc_fy2024.json` | *Characteristics of SNAP Households: Fiscal Year 2024* (SNAP-24-CHAR, revised August 2026), from the SNAP Quality Control sample | USDA FNS |
| `thresholds/us_fpl_2020.json` – `us_fpl_2026.json` | HHS Poverty Guidelines (Federal Register) | HHS ASPE |
| `thresholds/liheap_fy2026.json` | LIHEAP IM2025-02 (poverty guidelines and state median income estimates) and state FY2026 LIHEAP plans | HHS ACF Office of Community Services; state LIHEAP offices |
| `thresholds/medicare_cy2026.json` | Medicare Savings Programs limits (Medicare.gov); SSA POMS HI 03001.020 | CMS; Social Security Administration |
| `thresholds/ssi_cy2026.json` | Cost-of-Living Increase and Other Determinations for 2026, 90 FR 49047 | Social Security Administration |
| `thresholds/cpi_u_annual.json` | CPI-U, U.S. city average (series CUUR0000SA0 / FRED CPIAUCNS), annual averages | Bureau of Labor Statistics (retrieved via FRED, Federal Reserve Bank of St. Louis) |
| `census/<survey>/<year>/*.json` | American Community Survey 1-year and 5-year table-based summary files | U.S. Census Bureau |
| `census/acs5/2024/pums/*.json` | ACS 2020–2024 5-year Public Use Microdata Sample, aggregated to household types (`scripts/build_pums_households.py`) | U.S. Census Bureau |
| `seeds/us/<program>/eligibility_rules_*.txt` | Project-written summaries of eligibility rules, quoting and citing the Code of Federal Regulations (7 CFR 246, 273; 20 CFR 416; 42 CFR 423, 435, 457; 45 CFR 96) and agency guidance | Regulations: National Archives (eCFR). Summaries: this project (MIT) |

Census Bureau data products are produced by a federal agency; the Bureau asks that users cite it
as the source.

## Third-party data: KFF

| Files | Source | Status |
|---|---|---|
| `thresholds/chip_cy2026.json` | KFF, *Medicaid and CHIP Income Eligibility Limits for Children as a Percent of the Federal Poverty Level*, as of January 2026 (survey by KFF and the Georgetown University Center for Children and Families) | Restructured from the KFF table |
| `thresholds/medicaid_cy2026.json` | KFF State Health Facts, *Medicaid Income Eligibility Limits* (2026) | Restructured from the KFF table; `verification_status: "estimated"` |

KFF's [permissions page](https://www.kff.org/about-us/permissions-citations-reprints/) says
that "most of KFF's State Health Facts information is public and may be reproduced for free with
appropriate citation", unless an indicator's sourcing note says otherwise. It also says that KFF
website content is licensed under CC BY-NC-ND 4.0 ("with proper attribution and without
alteration").

These two files reorganize KFF's tables into a machine-readable structure. The underlying limits are
state policy parameters set in state Medicaid and CHIP plans. **The maintainers have not yet decided
whether that reuse fits KFF's terms.** Until they do, treat these two files as KFF-attributed and
non-commercial. Re-sourcing them from primary sources (Medicaid.gov eligibility tables, CMS State
Plan Amendments; see issue #24) would remove the question.

Citation, in KFF's format:

> Medicaid and CHIP Income Eligibility Limits for Children as a Percent of the Federal Poverty
> Level, KFF, accessed January 2026,
> https://www.kff.org/affordable-care-act/state-indicator/medicaid-and-chip-income-eligibility-limits-for-children-as-a-percent-of-the-federal-poverty-level/
>
> Medicaid Income Eligibility Limits, KFF, accessed 2026,
> https://www.kff.org/medicaid/state-indicator/medicaid-income-eligibility-limits/

## Updating data

Each importer under `scripts/` records its source URL and retrieval date in the file it writes.
When adding a dataset, add a row here with its license or terms. Prefer primary government
sources over secondary compilations.
