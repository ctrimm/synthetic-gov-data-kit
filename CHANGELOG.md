# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed
- **Installed packages had no data.** The wheel shipped only `govsynth/`, so a `pip install`ed
  `govsynth generate` failed with `FileNotFoundError` on its first threshold file. `data/` now
  ships inside the package as `govsynth/data`, resolved by `govsynth/_paths.py` (falling back to
  the checkout's `data/` in development). CI builds the wheel, runs `twine check --strict`, and
  generates cases for every program from a clean install (`scripts/smoke_test_wheel.sh`).

### Added
- `.github/workflows/release.yml`: pushing a `v*` tag builds, smoke-tests, publishes to PyPI via
  trusted publishing, and creates a GitHub release (pre-release for `a`/`b`/`rc` versions).
- `DATA_SOURCES.md`: source and terms for every bundled dataset.
- SNAP caseload population (#9): `population="caseload"` (CLI `--population caseload`) samples
  households that actually receive SNAP, from the FNS *Characteristics of SNAP Households: FY2024*
  (SNAP QC) tables in `data/caseload/snap_qc_fy2024.json` (`scripts/import_snap_qc.py`). A joint
  table is fit by IPF to the report's national cross-tabs and raked to each state's poverty,
  composition and income-source shares; `validate-distribution --population caseload` and the
  tests check every state against the QC targets. Profiles record `income_sources`.
- Joint household types from ACS PUMS (#8): `realistic` profiles for acs5-2024 draw a whole
  weighted household type (size, income band, elderly/disabled, children, earnings, head
  citizenship, head age band, earned share) per state, built by
  `scripts/build_pums_households.py` into `data/census/acs5/2024/pums/` (51 files; aggregates of
  3+ households only, small cells folded into their nearest type). Profiles and SNAP, Medicaid
  and Catala case metadata record `household_model`; `validate-distribution` checks against the
  types, and the tests cross-check the types with the summary tables.
- `govsynth validate-distribution` and `govsynth.evaluation.representativeness` (#12): compare
  `realistic` profiles with their census targets (4-SE tolerances) and check the targets against
  plausible ranges; run for all 51 jurisdictions in the test suite.
- CPI-U restatement (#11): `data/thresholds/cpi_u_annual.json` (BLS CPI-U via FRED,
  `scripts/import_cpi.py`) and `income_dollar_year` on `USHouseholdProfile.random`. SNAP with a
  fixed fiscal year and Medicaid restate census incomes into the rules year's dollars and record
  `metadata["income_dollar_year"]`.
- CHIP and children's Medicaid (#18): `CHIPSource` and `CHIPEligibilityGenerator` (Medicaid /
  CHIP-funded Medicaid / separate CHIP / ineligible, by age group and insurance status), CY2026,
  all 50 states + DC from the KFF/Georgetown January 2026 table; presets `chip.va|ca|tx|md`.
- LIHEAP (#18): `LIHEAPSource` and `LIHEAPEligibilityGenerator` for heating/cooling/crisis/
  weatherization income eligibility in VA, CA, TX and MD, FY2026 (presets `liheap.va|ca|tx|md`).
  Uses the HHS IM2025-02 state median income table (all 51 jurisdictions, every cell checked
  against the 45 CFR 96.85 formula) and each state's FY2026 plan, including Maryland's
  household-size %SMI rate and SNAP/TANF/SSI categorical eligibility.
- Census data for all 50 states + DC + national, for every bundled vintage (ACS 5-year
  2021–2024, 1-year 2021–2025), fetched with the keyless `refresh-census-data` (#10).
  `realistic` profiles no longer fall back to national averages outside Virginia.
- Medicare low-income help (#15): `MedicareSource` and `MedicareSavingsGenerator` for
  QMB/SLMB/QI tier determinations and Extra Help (Part D LIS), CY2026, preset
  `medicare.national`. Income limits are derived from the poverty guidelines and match every
  figure Medicare.gov publishes for 2026.
- SSI (#16): `SSISource` and `SSIEligibilityGenerator` (category, SGA, resources, $20 and
  $65 + 1/2 exclusions, payment = FBR - countable income), CY2026 (90 FR 49047), preset
  `ssi.national`.
- SNAP rules for FY2021–FY2025 (`snap_fy2021.json`…`snap_fy2025.json`), transcribed from the
  FNS COLA tables by the new `scripts/import_snap_cola.py` and checked against new
  `us_fpl_2020.json`…`us_fpl_2024.json` (ASPE). Per-year BBCE tables
  (`snap_bbce_fy2021.json`…`snap_bbce_fy2025.json`): BBCE adoption from the FNS State Options
  Reports, per-state percentages carried back from FY2026 and marked `estimated`.
- `realistic` SNAP cases follow their census year's rules (`match_census_year`, default on;
  CLI `--fixed-policy-year` to opt out).
- Census year selection for `realistic` profiles: `census_years=` on `Pipeline`,
  `SNAPEligibilityGenerator.generate` and `CatalaEligibilityGenerator.generate`, plus
  `govsynth generate --census-year` (years, ranges, `acs1-YYYY`). Census data now lives in
  `data/census/<survey>/<year>/`; VA + national bundled for ACS 5-year 2021–2024 and 1-year
  2021–2025. Each case records `metadata["census_vintage"]`, exported in YAML/JSONL/CSV.
- `refresh-census-data --year/--survey/--source`; keyless fetching from ACS table-based
  summary files (2021+); `national` as a geography
- `.github/workflows/ci.yml` — ruff check, ruff format --check, mypy, and pytest on every
  push/PR across Python 3.10–3.12
- `govsynth/generators/medicaid_eligibility.py` — Medicaid eligibility generator (MAGI
  methodology, ACA expansion vs. non-expansion coverage-gap cases) and `medicaid.va` /
  `medicaid.tx` presets
- `govsynth/generators/base.py` — `Generator` ABC that SNAP/WIC/Medicaid generators now
  implement
- `govsynth/reasoning/rules_engine.py` — shared `build_case_id`, `build_short_uid`, and
  `build_threshold_test_step` helpers for new generators
- ~150 new unit/integration tests: WIC and Medicaid source connectors, all three
  eligibility generators, formatters, `Pipeline`/`BatchPipeline`, the preset registry, the
  rationale evaluator, the Census fetcher (respx-mocked), and CLI coverage for
  `validate`/`refresh-census-data`. Coverage: 76% → 95%; test count: 109 → 263.
- `SNAPBBCESource` (`govsynth/sources/us/snap_bbce.py`) — faithful Broad-Based Categorical Eligibility model: per-state gross income limit (130–200% FPL, derived from the FPL table), waived/capped asset rule, with the net income test still enforced (7 CFR 273.2(j)(2)(ii))
- `data/thresholds/snap_bbce_fy2026.json` — per-state BBCE parameters for all 50 states + DC + GU/VI, sourced from the USDA FNS BBCE States Chart (August 2025), cross-checked against CBPP, with per-row verification status
- Seventh SNAP edge case — `bbce_expanded_gross_limit`: a household at 130–200% FPL gross that is eligible under BBCE but ineligible federally (plus an adversarial above-limit variant)
- `bbce_states(fiscal_year)` helper and data-backed `BBCE_STATES` constant exported from `snap_bbce`
- `docs/claude-code-integration.md` — examples of using govsynth within Claude Code agentic workflows
- `docs/cli-integration.md` — guide to adding govsynth CLI access to Claude Code and other AI apps
- `docs/open-source-health.md` — open source checklist and project health reference
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1-based community standards
- `SECURITY.md` — vulnerability reporting policy and policy data integrity guidance
- `.github/ISSUE_TEMPLATE/` — structured templates for bug reports, feature requests, and threshold updates
- `.github/PULL_REQUEST_TEMPLATE.md` — standardized PR checklist with policy data verification steps
- 8 Jupyter notebooks covering quickstart, SNAP/WIC edge cases, realistic profiles, rationale evaluation,
  multi-state batch generation, CLI workflow, and custom generator tutorial
- `govsynth refresh-census-data` CLI command — fetches ACS 5-year estimates from Census Bureau API
- `CensusDataSource` and `CensusDistribution` — state-level ACS profile sampling distributions
- `USHouseholdProfile.random(strategy="realistic")` — Census-backed profile generation
- `--profile-strategy` / `-s` flag on `govsynth generate`
- Bundled Virginia ACS 2022 census distribution (`data/census/va.json`)
- Six SNAP special-population edge case types: homeless shelter deduction (7 CFR 273.9(c)(6)), student exclusion (7 CFR 273.5(a)+(b)), boarder income proration (7 CFR 273.1(b)(7)), migrant/seasonal income averaging (7 CFR 273.10(c)(3)), mixed immigration status HH size reduction (7 CFR 273.4(c)(3)), categorical eligibility via TANF/SSI (7 CFR 273.2(j)(2), 273.11(c))
- `EDGE_CASES.md` — documents all implemented and planned SNAP edge case types with CFR citations
- Special population fields on `USHouseholdProfile`: `is_homeless`, `student_status`, `is_boarder`, `is_migrant_worker`, `has_ineligible_members`, `ineligible_member_count`
- `is_homeless` parameter on `SNAPSource.calculate_net_income()` for homeless shelter deduction

### Fixed
- `realistic` income no longer piles up at $15,000/month (~21% of profiles): draws above the
  cap are redrawn instead of clamped, and the cap is raised to $50,000/month (#11).
- SNAP BBCE tables for FY2021–FY2025 are now verified row by row against each year's FNS
  BBCE States Chart (May 2020 – Aug 2024), replacing values carried back from FY2026 (#23).
  23 rows changed across the five years — e.g. Virginia had no BBCE in FY2021, Louisiana was
  130% until FY2025, New Mexico 165% until FY2026, Michigan had a $15,000 asset limit through
  FY2023. Alaska's and Arkansas's FY2026 BBCE rows are confirmed as 2025 adoptions. Each
  `snap_fy2021`–`2025.json` now cites its signed COLA memo (#24).
- `MedicaidEligibilityGenerator` ignored `profile_strategy` (always uniform) and silently
  skipped cases that failed to build (#13). `uniform`/`realistic` now take household size
  and income from the sampled profile, `realistic` accepts `census_years`, unknown
  strategies raise, and a failing case raises instead of being dropped. Edge-saturated
  output for a given seed is unchanged.
- `get_standard_deduction`, the SNAP policy summary, the homeless shelter deduction text and
  CFR citations hard-coded FY2026 values, so any other `fiscal_year` silently used FY2026
  deductions. They now come from the fiscal year's data file.
- Census fetcher read the wrong ACS variables for most fields: mislabeled income brackets
  above $50k, poverty buckets from the under-6 rows of B17024, "% with children" from
  married-couple rows, naturalized citizens sampled as non-qualified aliens, Medicaid rate
  from any-insurance rows, person-level 65+ elderly share. All now come from the correct
  household-level tables (#8–#12 track the remaining realism work)
- CI on `main` was red (first failing step: `ruff check`): split over-long strings in
  `us_household.py`, fixed two test lint errors, reformatted two files, and made
  `test_constructor_docstring_documents_exactly_its_parameters` independent of Python
  3.13's docstring dedenting (#14)
- **Case ID determinism**: SNAP/WIC (and the new Medicaid) generators built each case_id's
  random suffix with `uuid.uuid4()` instead of the generator's own seeded `random.Random`,
  so `generate(n, seed=42)` was not actually reproducible — case_ids (and therefore any
  downstream diffing) changed on every run despite the seed. Fixed by routing the suffix
  through `reasoning/rules_engine.py:build_short_uid(rng)` everywhere a case_id is built.
- **Rationale scoring accuracy**: `RationaleEvaluator._score_conclusion` used plain
  substring checks for eligibility signal words. Since `"eligible"` is a substring of
  `"ineligible"` (and `"qualify"` a substring of `"does not qualify"`), any model output
  that clearly said "ineligible" was scored as an ambiguous 0.5 instead of a correct 1.0 or
  wrong 0.0 — silently degrading the accuracy of the library's own core evaluation metric.
  Fixed with word-boundary regex matching that also strips negated phrases before checking
  positive signals.
- `lru_cache`-backed JSON loaders in `sources/base.py`, `sources/us/census.py`, and
  `sources/us/medicaid.py` returned the same shared dict object to every caller; any future
  in-place mutation would have silently corrupted the cache for the rest of the process.
  They now return a deep copy per call, and `refresh-census-data` explicitly invalidates
  the census cache after writing new files so in-process reloads see fresh data.
- `TestCase.validate()` shadowed pydantic's inherited `BaseModel.validate` classmethod with
  an unrelated signature; renamed to `TestCase.check_output_contract()`.
- `SNAPEligibilityGenerator` had no `.program` property, so `Pipeline.generate()`'s
  progress label silently fell back to `"unknown.va"` instead of `"snap.va"`.
- `notebooks/09_cli_workflow.ipynb` had 12 duplicate `"cell_type"` keys (malformed JSON
  that `json.loads` tolerated silently but broke stricter notebook tooling).
- **CI mypy failure**: `mypy govsynth/` failed in CI with `Type statement is only supported
  in Python 3.12 and greater` while parsing numpy's bundled stubs (pulled in transitively
  via the `hf` extra) — numpy dropped support for Python <3.12 and its stubs now use PEP 695
  `type` statement syntax unconditionally. Fixed by bumping `[tool.mypy] python_version` to
  `"3.12"` (the newest CI-tested interpreter, independent of the package's `>=3.10` minimum
  supported runtime version) and adding `types-PyYAML` to the `dev` extra so the PyYAML
  stub-missing errors it was masking don't resurface once mypy gets past the numpy blocker.
- Corrected stale BBCE state classification: TN/UT/WY are not BBCE; TX/VA are (per FNS Aug 2025)
- `data/thresholds/snap_bbce_fy2026.json`'s `verification_note` and
  `data/seeds/us/snap/eligibility_rules_fy2026.txt` both hardcoded "45 BBCE jurisdictions"
  while the note's own breakdown ("43 states + DC + GU + VI") already summed to 46,
  matching the actual 46 `bbce: true` entries in the data. Re-verified against FRAC's
  FNS-sourced BBCE table and USDA's State Options Report (17th Edition) plus the Alaska
  (HB 344, effective 2025-07-01) and Arkansas (Act 675) BBCE-adoption citations that
  explain the move from 44 to 46 jurisdictions since the report's October 2024 data
  reference: **this was a prose transcription typo, not a data error** — no `bbce` flag
  was changed. Also corrected `_metadata`, which claimed a CBPP cross-check that was
  never actually performed at authoring time; added a `reverification_2026_08` block
  documenting what this pass did and didn't verify (CBPP and the original FNS chart PDF
  were both unreachable), and marked `source_chart_url` dead (404) instead of silently
  dropping it. Added `TestVerificationNoteMatchesData` in `test_snap_bbce_source.py` to
  pin the prose count against the live data so it cannot drift again.
- WIC's `_classify_difficulty` (in `govsynth/generators/wic_eligibility.py`) carried the
  same sentinel-fabrication defect already fixed in SNAP: a missing `offset_pct`
  defaulted to `0.5` instead of `MEDIUM`, and categorical eligibility (which bypasses the
  income test outright) returned `EASY` despite never measuring distance from any
  threshold. Also fixed the same defect in `_make_id`, which defaulted `offset_pct` to
  `0.0` and fabricated an `"at_limit"` tag. Added `tests/unit/test_wic_difficulty.py`
  mirroring `test_snap_difficulty.py`.
- Notebooks `01`, `02`, `07`, and `08` narrated or executed against stale pre-BBCE-fix
  SNAP behavior (e.g. describing Texas as "strict federal" when it is actually BBCE with
  a $5,000 asset cap). Narration corrected, BBCE-sensitive demos swapped to
  `SNAPBBCESource`, and two boundary-flip demos moved to Kansas (non-BBCE) where the
  federal 130%/100% flip actually holds; notebooks re-executed so committed outputs
  match current behavior.
- `notebooks/01_quickstart.ipynb` had ten markdown cells carrying a stray `"outputs": []`
  key — invalid under nbformat v4, since only code cells may have `outputs` — which made
  `nbformat.validate()` fail. Stripped the key; all notebooks now validate.
- `LICENSE` — added full MIT license text with copyright year and holder
- `pyproject.toml` — replaced `your-org` placeholder URLs with actual repository paths
- `CONTRIBUTING.md` — corrected clone URL placeholder
- `README.md` — corrected install instructions (source install), preset list, profile strategies,
  and batch generation Python API example

### Changed
- **Behavior change:** WIC categorical-eligibility cases, which previously fabricated
  `Difficulty.EASY`, are now classified `Difficulty.MEDIUM` — the same fix already
  applied to SNAP. Categorical eligibility bypasses the income test outright, so these
  cases were never actually easy by threshold-proximity; the label was wrong, not the
  new behavior. **Any WIC corpus generated before this fix will show different
  difficulty labels for categorical-eligibility cases on regeneration.**
- `SNAPSource` reduced to the federal baseline (130% FPL gross, 100% FPL net, $3,000/$4,500 assets). The stale hardcoded `BBCE_STATES`/`STRICT_ASSET_TEST_STATES` sets were removed; BBCE is now modeled exclusively by `SNAPBBCESource`, which the SNAP generator uses for the main threshold path and the BBCE edge case. **Behavior change:** SNAP cases for BBCE states now apply the state's raised gross limit and correct asset rule (e.g. TX is now correctly BBCE at 165% FPL / $5,000 cap rather than federal strict).
- **BREAKING:** `SNAPEligibilityGenerator.__init__` no longer accepts `difficulty_distribution`. The parameter was accepted and documented but never read — `Difficulty` is derived from each generated profile, not requested by the caller. Passing it now raises `TypeError`.
- EDGE_CASES.md Group A special-population cases (homeless, student, boarder, migrant, mixed immigration status, categorical eligibility, expanded BBCE income) now emit `difficulty: adversarial` instead of `difficulty: hard`. These exist because models tend to misapply the specific rule, not because of proximity to a threshold, so `hard` mischaracterized them.
- **Silent behavior change — affects pinned fixtures:** `_OFFSETS` in `snap_eligibility.py` widened from `[0.0, 0.01, -0.01, 0.05, -0.05]` to also include `0.35, -0.35`, so `Difficulty.EASY` is reachable at all. This changes the offset distribution drawn for every seed, so **any corpus generated from a previously-pinned seed will now differ from what that seed used to produce**, even though the seed value and call site are unchanged. Anyone diffing against or asserting equality with previously generated fixtures needs to regenerate them.
- `SNAPEligibilityGenerator.generate()` now raises `RuntimeError` (chained from the original exception) if any case builder fails, on both the random-profile path (`uniform`/`realistic` strategies) and the edge-saturated path (special-population and regular edge-case builders). Previously a failing builder was logged with `print` and skipped, silently returning fewer cases than requested.
- `AGENTS.md` rewritten — it referenced files, classes, and fields that never existed
  (`case.civbench_id`, `formatters/civbench_yaml.py`, `reasoning/rules_engine.py` as
  registration point, `profiles/edge_cases.py`/`EdgeCaseFactory`, `config.py`,
  `formatters/base.py`, `tests/fixtures/civbench_schema_v1.yaml`), which would have sent
  any AI agent following it straight into `AttributeError`/`ModuleNotFoundError`. Every
  reference is now verified against the actual codebase.
- `CLAUDE.md` — corrected the same class of drift (dead `CitizenProfile`/`profiles/base.py`
  abstraction, a `SNAPSource(year=...)` example using the wrong constructor kwarg, an
  invented threshold-JSON schema, the ruff line-length claim) and documented the new
  `Generator`/`rules_engine` abstractions.
- `pyproject.toml` — ruff `line-length` 100 → 120 (generators build long natural-language
  rationale/citation f-strings that read worse split across lines) and `notebooks/`
  excluded from lint scope; fixed all 439 pre-existing `ruff check` errors and all 38
  pre-existing `mypy --strict` errors, both now enforced by CI.

---

## [0.1.0] — 2026-03-25

### Added
- Initial release of `synthetic-gov-data-kit`
- SNAP eligibility generator (`snap.va`, `snap.ca`, `snap.tx`, `snap.md` presets)
- WIC eligibility generator (`wic.national` preset)
- Medicaid source connector (data layer only — no presets yet)
- `USHouseholdProfile` with `edge_saturated` and `uniform` profile strategies
- `RationaleTrace` data model — step-by-step policy reasoning chain with CFR citations
- Output formatters: YAML, JSONL, CSV, HuggingFace datasets
- CLI (`govsynth`) with commands: `generate`, `batch`, `list-presets`, `validate`, `show`,
  `verify-thresholds`, `parse-policy` (stub)
- `Pipeline` and `BatchPipeline` orchestration
- Verified FY2026 SNAP and WIC threshold tables (USDA FNS)
- Verified FY2025 HHS Federal Poverty Guidelines
- `docs/bring-your-own-policy.md` — guide for adding custom program connectors
