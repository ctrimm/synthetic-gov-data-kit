## Summary

Brief description of what this PR does and why.

Closes # (issue number, if applicable)

---

## Type of change

- [ ] Bug fix
- [ ] New feature (program, preset, task type, formatter, etc.)
- [ ] Annual threshold / policy data update
- [ ] Documentation
- [ ] Refactor / internal improvement
- [ ] CI / tooling

---

## Policy data checklist

*Skip this section if no threshold values or policy rules were added or modified.*

- [ ] All threshold values are sourced from an official government publication
- [ ] Source URL is cited in `_metadata.source_url`
- [ ] `_metadata.verification_status` is set correctly (`"verified"` or `"estimated"`)
- [ ] Fiscal year / effective date is confirmed and documented
- [ ] `python scripts/verify_thresholds.py` shows no new unverified entries

---

## Code checklist

- [ ] `ruff format .` and `ruff check .` pass
- [ ] `mypy govsynth/` passes
- [ ] Unit tests added or updated for changed modules
- [ ] All new public functions/classes have Google-style docstrings
- [ ] `seed=42` used in any new test cases
- [ ] `CHANGELOG.md` entry added under `[Unreleased]`

---

## Notes for reviewers

Anything specific you'd like reviewers to look at, or context that helps with review.
