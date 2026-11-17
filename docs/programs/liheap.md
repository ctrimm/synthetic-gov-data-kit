# LIHEAP — Low Income Home Energy Assistance Program

Income eligibility for LIHEAP components in four states, FY2026
(`data/thresholds/liheap_fy2026.json`, presets `liheap.va`, `liheap.ca`, `liheap.tx`, `liheap.md`).

## Rules modeled

Federal ceiling: the greater of 150% FPL or 60% of state median income; floor: 110% FPL
(42 U.S.C. 8624(b)(2)). Within that, each state chooses:

| State | Heating | Cooling | Crisis | Weatherization | Categorical eligibility |
|---|---|---|---|---|---|
| VA | 150% FPL | — | 150% FPL | 60% SMI | — |
| CA | 60% SMI | — | 60% SMI | 60% SMI | — |
| TX | 150% FPL | 150% FPL | 150% FPL | 150% FPL | — |
| MD | %SMI by household size (39% → 60%) | — | same | same | SNAP, TANF, SSI, means-tested veterans' benefits |

SMI comes from HHS LIHEAP IM2025-02 Attachment 4 (mandatory for FY2026), bundled for all 51
jurisdictions. All 612 cells were checked against the 45 CFR 96.85 size-factor formula.
Poverty guidelines are the 2025 HHS guidelines the federal FY2026 tables are built on.

## Case types

- `{component}_{fpl|smi|smi_by_size}_limit`: annual gross income on and around the state's
  limit for that component. The reasoning step a model has to get right is *which* threshold
  applies (e.g. Virginia weatherization is 60% SMI, not 150% FPL).
- `{component}_categorical` (Maryland): recipients of SNAP, TANF, SSI or means-tested veterans'
  benefits, with plausible incomes for each. SNAP households can sit just above the LIHEAP limit
  (under Maryland's 200% FPL SNAP BBCE limit) and are eligible only through categorical eligibility.

## Not modeled

Benefit amounts, funding availability (LIHEAP is not an entitlement), vulnerability
priorities, states other than the four above, and state income definitions beyond annual gross
income (Virginia's plan states gross; CA/TX/MD are assumed to match).
