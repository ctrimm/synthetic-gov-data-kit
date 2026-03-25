# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
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

### Fixed
- `LICENSE` — added full MIT license text with copyright year and holder
- `pyproject.toml` — replaced `your-org` placeholder URLs with actual repository paths
- `CONTRIBUTING.md` — corrected clone URL placeholder
- `README.md` — corrected install instructions (source install), preset list, profile strategies,
  and batch generation Python API example

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
