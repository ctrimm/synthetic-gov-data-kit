# Using synthetic-gov-data-kit with Claude Code

Claude Code is Anthropic's CLI for AI-assisted software development. This guide shows how
`govsynth` and Claude Code complement each other for building, evaluating, and extending
LLM-powered government benefits applications.

---

## Why These Tools Fit Together

`synthetic-gov-data-kit` generates policy-grounded test cases with step-by-step rationale traces.
Claude Code is an agentic coding assistant that can read files, run shell commands, and reason
about code. Together they enable:

- **Evaluation-driven development** — generate a test suite, then ask Claude Code to build a
  benefits chatbot that passes it
- **Policy accuracy auditing** — ask Claude Code to cross-check generated threshold values
  against the cited CFR sections
- **Automated dataset maintenance** — have Claude Code update threshold JSON files each year
  using the procedures in `data/thresholds/README.md`
- **Rapid program expansion** — use Claude Code to scaffold a new DataSource + Generator
  following the 8-step playbook in `AGENTS.md`

---

## Setup

Install the library so Claude Code can invoke the `govsynth` CLI:

```bash
pip install synthetic-gov-data-kit
# or, in development:
pip install -e ".[dev]"
```

Confirm it's available:

```bash
govsynth list-presets
```

---

## Example 1: Generate a Test Suite and Evaluate a Model Against It

This is the core use case. Generate structured cases, then ask Claude Code to build and run an
evaluator.

**Step 1 — Generate cases from the CLI:**

```bash
govsynth generate snap.va --n 50 --seed 42 --format jsonl --output ./eval-suite/
```

**Step 2 — Ask Claude Code to write an evaluator:**

```
I have 50 SNAP eligibility test cases in ./eval-suite/snap_va_cases.jsonl. Each case has:
- scenario.summary: a natural language description of a household
- task.instruction: what to determine
- expected_outcome: "eligible" or "ineligible"
- rationale_trace.steps: the correct reasoning chain

Write a Python script that:
1. Loads each case from the JSONL file
2. Sends the scenario + instruction to claude-sonnet-4-6 via the Anthropic SDK
3. Extracts the model's answer
4. Compares it to expected_outcome
5. Prints accuracy, and for incorrect cases, shows the expected vs actual answer

Use async batching to run 10 cases in parallel. Use seed from the case metadata
so results are reproducible.
```

**Step 3 — Ask Claude Code to score rationale quality:**

```
Now extend the evaluator to also score rationale quality. The govsynth library includes
a RationaleEvaluator in govsynth/evaluation/rationale_evaluator.py. Use it to compare
the model's reasoning steps against the expected rationale_trace, and report:
- Step coverage (what fraction of expected steps the model hit)
- CFR citation accuracy (did the model cite the right regulations?)
- Computation correctness (did arithmetic match?)
```

---

## Example 2: Build a Benefits Eligibility Chatbot — Test-First

Use govsynth to define the acceptance criteria before writing the application.

**Generate edge cases:**

```bash
# Edge-saturated cases stress-test threshold boundary logic
govsynth generate snap.va --n 100 --seed 42 --profile-strategy edge_saturated --output ./tests/fixtures/

# Adversarial cases test robustness to conflicting or missing information
govsynth generate snap.va --n 30 --seed 42 --profile-strategy adversarial --output ./tests/fixtures/adversarial/
```

**Prompt Claude Code:**

```
I'm building a SNAP eligibility assistant. The acceptance criteria are in
./tests/fixtures/ — 100 structured test cases, each with a scenario, the correct
eligibility determination, and a step-by-step rationale trace.

Please:
1. Read 5 representative cases so you understand the format
2. Build a simple FastAPI endpoint POST /eligibility that accepts a household
   description and returns {eligible: bool, reason: str, steps: list[str]}
3. Write a pytest test suite that runs each fixture case through the endpoint
   and asserts the expected_outcome matches

Use govsynth's RationaleTrace schema (govsynth/models/rationale.py) as the
type definition for the steps field in the response.
```

---

## Example 3: Annual Threshold Update Workflow

Each year, SNAP income limits update on October 1 and FPL guidelines update in January.
Claude Code can automate the mechanical parts of this update.

**Prompt Claude Code:**

```
The SNAP FY2027 income limits were just published by FNS. The source document is at
https://www.fns.usda.gov/snap/eligibility (I'll paste the table values below).

Please:
1. Read data/thresholds/snap_fy2026.json to understand the current structure
2. Create data/thresholds/snap_fy2027.json with the new values
3. Update _metadata.fiscal_year, _metadata.effective_date, _metadata.source_url,
   and set _metadata.verification_status to "verified"
4. Run python scripts/verify_thresholds.py to confirm the file is valid
5. Update CHANGELOG.md with an entry under [Unreleased]

Here are the new values:
[paste FNS table]
```

The `data/thresholds/README.md` has the exact update procedure and source URLs —
Claude Code will follow it if you reference that file.

---

## Example 4: Scaffold a New Program (LIHEAP)

The `AGENTS.md` file contains an explicit 8-step playbook for adding a new benefits program.
Claude Code uses it automatically.

**Prompt Claude Code:**

```
Add LIHEAP (Low Income Home Energy Assistance Program) support to this library.

The AGENTS.md file has a step-by-step playbook. Please follow it exactly.

Policy sources:
- CFR: 45 CFR Part 96, Subpart C
- Income limit: 60% of state median income (varies by state) or 150% FPL, whichever is higher
- Agency: HHS Office of Community Services

Start with Virginia. Use estimated thresholds (verification_status: "estimated") and
add a comment citing the HHS OCS website. Use seed=42 in all test cases.
```

Claude Code will:
1. Read `AGENTS.md` for the playbook
2. Read an existing source connector (e.g., `govsynth/sources/us/snap.py`) as a pattern
3. Create `data/thresholds/liheap_fy2026.json`
4. Create `govsynth/sources/us/liheap.py`
5. Create `govsynth/generators/liheap_eligibility.py`
6. Register a `liheap.va` preset in `govsynth/presets.py`
7. Add unit tests
8. Add `docs/programs/liheap.md`

---

## Example 5: Policy Q&A Test Case Generation

Generate cases where the task is answering a specific policy question, not just
determining eligibility.

```
Using the govsynth library, write a Python script that generates 20 policy_qa test
cases for SNAP. Each case should:
- Describe a household with some unusual circumstance (student exemption, elderly
  household, homeless applicant, etc.)
- Ask a specific policy question about how that circumstance affects eligibility
- Include a rationale trace that cites the relevant CFR subsection

Use the existing WICEligibilityGenerator (govsynth/generators/wic_eligibility.py)
as a pattern for the Generator structure, but set task_type=TaskType.POLICY_QA.

Save output to ./output/snap_policy_qa.jsonl
```

---

## How Claude Code Uses `CLAUDE.md` and `AGENTS.md`

When you open this repository in Claude Code, it automatically reads `CLAUDE.md`, which gives it:

- The full project layout and key abstractions
- Pydantic v2 patterns to follow
- Threshold JSON schema
- Test case ID naming rules
- The 8-step playbook for adding a new program
- Code style requirements (ruff, mypy strict)

`AGENTS.md` provides task-specific playbooks for the most common contribution types. Claude Code
uses these to self-guide multi-step tasks without needing step-by-step human instructions.

You can reference these files explicitly in any prompt:

```
Following the playbook in AGENTS.md, add a new state preset snap.ny for New York.
```

Or implicitly — Claude Code will consult them when working in this repository.

---

## Tips for Effective Use

**Be specific about policy accuracy requirements.** Claude Code knows (from `CLAUDE.md`) that
fabricating threshold values is prohibited. If you're asking it to add estimated thresholds,
explicitly note that they're estimates and should be flagged as `"estimated"` in the JSON.

**Use `--seed` for reproducible evaluation.** All govsynth generators accept a seed. Fix it
in your prompts (`seed=42`) so evaluation runs are reproducible and comparable across sessions.

**Pipe `govsynth` output directly.** The CLI writes data to stdout and status to stderr:

```bash
govsynth generate snap.va --n 10 --seed 42 --format jsonl --quiet | \
  python my_evaluator.py
```

**Use `govsynth validate` to check generated files.** After Claude Code writes or modifies
test case YAML files, validate them:

```bash
govsynth validate ./output/*.yaml
```

**Reference `docs/bring-your-own-policy.md`** when asking Claude Code to add a custom program
not yet in the library. It has the complete schema definitions Claude Code needs.
