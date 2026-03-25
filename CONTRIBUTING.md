# Contributing to synthetic-gov-data-kit

Thank you for contributing. This project generates policy-grounded test cases
for evaluating government AI systems — policy accuracy is paramount.

---

## The Most Important Rule

**Never fabricate or estimate policy thresholds without flagging them.**

If you're adding or updating income limits, asset limits, or deduction values,
they must be sourced from an official government publication and cited.
Set `verification_status: "verified"` only after confirming values against
the published source. Use `"estimated"` with a clear note otherwise.

---

## Development Setup

```bash
git clone https://github.com/ctrimm/synthetic-gov-data-kit
cd synthetic-gov-data-kit
pip install -e ".[dev]"
pre-commit install
```

## Running Tests

```bash
pytest                          # all tests
pytest tests/unit/ -v           # unit tests only
pytest -k "snap" -v             # filter by name
python scripts/verify_thresholds.py  # check threshold verification status
```

## What to Contribute

### High priority
- **Annual threshold updates** — FPL guidelines publish each January;
  SNAP/WIC COLA memos publish each August for October 1 effective date.
  See `data/thresholds/README.md` for update procedures.
- **Additional US programs** — CHIP, LIHEAP, TANF, Section 8/HCV.
  Follow the playbook in `AGENTS.md`.
- **More state presets** — add to `govsynth/presets.py`.
- **Test case quality** — better edge case coverage, more adversarial scenarios.

### How to add a program

1. `data/thresholds/{program}_{fy or cy}{year}.json` — threshold table
2. `data/seeds/us/{program}/eligibility_rules_{fy or cy}{year}.txt` — policy seed
3. `govsynth/sources/us/{program}.py` — DataSource subclass
4. `govsynth/generators/{program}_eligibility.py` — Generator
5. `govsynth/presets.py` — register presets
6. `tests/unit/test_{program}_source.py` — unit tests
7. `docs/programs/{program}.md` — documentation

## Code Style

```bash
ruff format .    # format
ruff check .     # lint
mypy govsynth/   # type check
```

Line length: 100. Google-style docstrings. All public functions must have docstrings.

## Pull Request Checklist

- [ ] Threshold values are verified against official source
- [ ] `verification_status` set correctly in threshold JSON
- [ ] Source URL cited in `_metadata`
- [ ] Unit tests added/updated
- [ ] `ruff` and `mypy` pass
- [ ] `python scripts/verify_thresholds.py` shows no new unverified entries
- [ ] CHANGELOG.md entry added

## Policy Accuracy Review

PRs that add or change threshold values require a policy accuracy review.
Tag `@policy-reviewers` and include:
- Link to official source document
- Specific page/section where values were found
- Fiscal year / effective date confirmed

---

*By contributing, you agree that your contributions will be licensed under the MIT License.*
