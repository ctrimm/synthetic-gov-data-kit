# Open Source Health Checklist

This document tracks the open source hygiene mechanisms in place for `synthetic-gov-data-kit`
and serves as a reference for maintainers onboarding contributors or publishing releases.

Inspired by the [Nava PBC Open Source Guide](https://github.com/navapbc/opensource-guide).

---

## Status Summary

| Mechanism | File | Status |
|-----------|------|--------|
| License | `LICENSE` | MIT, full text with copyright year |
| Readme | `README.md` | Quickstart, examples, CLI reference, roadmap |
| Contributing guide | `CONTRIBUTING.md` | Setup, code style, PR checklist |
| Code of conduct | `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 |
| Security policy | `SECURITY.md` | Disclosure process + policy data integrity |
| Changelog | `CHANGELOG.md` | Keep a Changelog format |
| Bug report template | `.github/ISSUE_TEMPLATE/bug_report.md` | Structured, includes policy data flag |
| Feature request template | `.github/ISSUE_TEMPLATE/feature_request.md` | Program/preset/task type scoped |
| Threshold update template | `.github/ISSUE_TEMPLATE/threshold_update.md` | Source verification required |
| PR template | `.github/PULL_REQUEST_TEMPLATE.md` | Policy + code checklists |
| AI assistant context | `CLAUDE.md` | Full project context for Claude Code |
| AI agent playbooks | `AGENTS.md` | Task-specific agent instructions |
| Package metadata | `pyproject.toml` | PyPI-ready, correct URLs, classifiers |
| Bring-your-own-policy guide | `docs/bring-your-own-policy.md` | Step-by-step program connector guide |
| Threshold update procedures | `data/thresholds/README.md` | Annual update calendar and sources |
| Claude Code integration | `docs/claude-code-integration.md` | Agentic workflow examples |
| CLI integration guide | `docs/cli-integration.md` | Embedding govsynth in AI apps |

---

## What Each File Does

### `LICENSE`

Full MIT License text. The project is permissively licensed — anyone can use, modify, and
redistribute it, including in commercial contexts, as long as the copyright notice is retained.

Key considerations for government / civic tech use:
- MIT is [OSI-approved](https://opensource.org/licenses/MIT)
- Compatible with Apache 2.0 and GPL
- Appropriate for a data generation library used in research and evaluation tooling

### `CODE_OF_CONDUCT.md`

Based on the [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct.html).
Establishes that submitting fabricated or unverified policy data is explicitly unacceptable behavior —
this reinforces the technical requirement in CONTRIBUTING.md at the community level.

### `SECURITY.md`

Covers:
- How to report software vulnerabilities (GitHub Security Advisories, not public issues)
- Policy data integrity — incorrect threshold values are treated as high-priority bugs
- What is explicitly out of scope (no auth, no user data, no PII)

The policy data integrity section is unique to this project: because downstream evaluation systems
may use the generated test cases to assess LLM behavior on real-world policy questions, a wrong
income limit is a meaningful defect, not just a data quality issue.

### `CHANGELOG.md`

Follows [Keep a Changelog](https://keepachangelog.com). Maintainers should add entries under
`[Unreleased]` as changes land, then rename that section when cutting a release.

```
## [Unreleased]
### Added
- ...

## [0.2.0] — YYYY-MM-DD
### Added
- ...
### Fixed
- ...
```

### `.github/ISSUE_TEMPLATE/`

Three templates:

1. **bug_report.md** — prompts for repro code, expected/actual behavior, environment info,
   and a flag for whether the issue is a policy data error.

2. **feature_request.md** — scoped to the contribution types most valuable for this project
   (new programs, state presets, task types, formatters). Requires a policy source for new programs.

3. **threshold_update.md** — specifically for the annual update workflow. Requires a source URL,
   page/section reference, and a verification checklist before merging.

### `.github/PULL_REQUEST_TEMPLATE.md`

Two checklists:
- **Policy data** — only shown when threshold values are changed; requires source citation and
  verified status
- **Code** — ruff, mypy, test coverage, docstrings, seed usage, CHANGELOG entry

### `AGENTS.md` and `CLAUDE.md`

These are the project's AI-native contribution mechanisms. See
[docs/claude-code-integration.md](claude-code-integration.md) for usage patterns and
[docs/cli-integration.md](cli-integration.md) for embedding govsynth in AI-powered apps.

---

## Publishing a Release

1. Move `[Unreleased]` entries in `CHANGELOG.md` to a new version section with today's date
2. Bump `version` in `pyproject.toml`
3. Tag the commit: `git tag v0.2.0`
4. Build: `python -m build`
5. Check: `twine check dist/*`
6. Upload: `twine upload dist/*`
7. Create a GitHub Release from the tag, copying the CHANGELOG section as release notes

---

## Accepting Contributions

### Triage labels

| Label | Meaning |
|-------|---------|
| `bug` | Something isn't working |
| `enhancement` | New feature or capability |
| `threshold-update` | Annual policy data update |
| `policy-data` | Any change to threshold JSON or seed text |
| `good first issue` | Bounded, well-documented task |
| `needs-source` | Policy data claim lacks a source citation |
| `policy-review` | Requires review by someone familiar with the relevant CFR |

### Policy accuracy review

Any PR with the `policy-data` label requires a reviewer to:
1. Independently verify the threshold values against the cited source
2. Confirm the fiscal year and effective date
3. Check `verification_status` is set correctly

This review cannot be waived, even for automated PRs. Incorrect policy data degrades the
quality of the entire evaluation dataset.

### Automation opportunities

- Dependabot for Python dependency updates
- Annual threshold reminder issues (opened each August for SNAP/WIC, each January for FPL/Medicaid)
- CI: `pytest`, `ruff check`, `mypy`, `python scripts/verify_thresholds.py`

---

## Community Health Score

This project meets the [GitHub community health](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)
checklist:

- [x] Description
- [x] README
- [x] Code of conduct
- [x] Contributing guide
- [x] License
- [x] Security policy
- [x] Issue templates
- [x] Pull request template
