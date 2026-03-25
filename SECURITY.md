# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

**Do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability, please open a
[GitHub Security Advisory](https://github.com/ctrimm/synthetic-gov-data-kit/security/advisories/new)
or email the maintainers directly. You should receive a response within 72 hours.

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact

## Scope

This library generates **entirely synthetic** data — no real applicant data is ever used or stored.
The primary security concerns are:

- **Dependency vulnerabilities** in pydantic, httpx, or other dependencies
- **Policy data injection** — malicious threshold files that produce incorrect eligibility
  determinations in downstream systems
- **Output validation bypass** — crafted inputs that cause the library to emit malformed TestCase
  objects that pass Pydantic validation but contain incorrect policy logic

## Policy Data Integrity

All threshold values in `data/thresholds/` must be sourced from official US government publications.
If you discover that a threshold value is incorrect (diverges from the actual CFR or agency table
for the stated fiscal year), please open a GitHub issue with the title prefix `[POLICY DATA]` and
include a link to the authoritative source. Incorrect policy data is treated as a high-priority bug.

## What Is Out of Scope

- The library does not make eligibility determinations for real benefit applications.
- It has no user accounts, authentication, or persistent storage.
- It does not transmit data to external services (the optional Census API connector is read-only).
