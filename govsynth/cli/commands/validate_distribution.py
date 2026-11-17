"""govsynth validate-distribution command.

Samples 'realistic' profiles and checks them against the census targets they are
drawn from (see govsynth.evaluation.representativeness). Exits 1 if any metric is
outside tolerance, so it can gate CI.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from govsynth.cli.output import emit_json, make_console
from govsynth.sources.us.census_fetcher import FIPS_CODES


def validate_distribution(
    state: Annotated[str, typer.Option("--state", "-s", help="Two-letter state code, or 'all'")] = "VA",
    census_year: Annotated[
        str | None,
        typer.Option("--census-year", help="ACS release, e.g. 2024 or acs1-2025 (default: the bundled default)"),
    ] = None,
    n: Annotated[int, typer.Option("--n", "-n", help="Profiles to sample per state")] = 3000,
    seed: Annotated[int, typer.Option(help="Base seed")] = 42,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check that realistic profiles reproduce their census targets."""
    from govsynth.evaluation.representativeness import check_state, plausibility_problems

    console = make_console()
    states = sorted(FIPS_CODES) if state.lower() == "all" else [state.upper()]
    if states[0] not in FIPS_CODES:
        console.print(f"[red]Error:[/red] Unknown state '{state}'. Use a two-letter code or 'all'.")
        raise typer.Exit(2)

    report: list[dict[str, Any]] = []
    failed = 0
    for code in states:
        try:
            checks = check_state(code, vintage=census_year, n=n, seed=seed)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(2) from exc
        bad = [c for c in checks if not c.ok]
        implausible = plausibility_problems(code, census_year)
        failed += len(bad) + len(implausible)
        report.append(
            {"state": code, "ok": not bad and not implausible, "checks": [c.as_dict() for c in checks],
             "implausible_targets": implausible}
        )  # fmt: skip
        for problem in implausible if not as_json else []:
            console.print(f"[red]implausible census data[/red] {problem}")
        if not as_json:
            console.print(
                f"{'✅' if not bad else '❌'} {code}: {len(checks) - len(bad)}/{len(checks)} metrics within tolerance"
            )
            for c in checks if len(states) == 1 else bad:
                mark = "ok " if c.ok else "OUT"
                console.print(
                    f"   {mark} {c.metric:<30} target {c.target:>12,.4f}  "
                    f"generated {c.generated:>12,.4f}  ±{c.tolerance:,.4f}"
                )

    if as_json:
        emit_json({"status": "ok" if not failed else "out_of_tolerance", "n": n, "states": report})
    if failed:
        raise typer.Exit(1)
