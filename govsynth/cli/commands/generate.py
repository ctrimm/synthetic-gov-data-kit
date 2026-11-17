"""govsynth generate command — single-preset case generation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from govsynth.cli.output import emit_status, make_console
from govsynth.formatters.jsonl import JSONLFormatter
from govsynth.formatters.yaml_fmt import YAMLFormatter
from govsynth.models.test_case import TestCase
from govsynth.pipeline import Pipeline
from govsynth.sources.us.census import DEFAULT_CENSUS_VINTAGE, normalize_census_years


def generate(
    preset: Annotated[str, typer.Argument(help="Preset name, e.g. snap.va")],
    n: Annotated[int, typer.Option("--n", "-n", help="Number of cases")] = 100,
    seed: Annotated[int | None, typer.Option(help="RNG seed")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output dir/file")] = None,
    formats: Annotated[list[str] | None, typer.Option("--format", "-f", help="yaml|jsonl|csv (repeatable)")] = None,
    profile_strategy: Annotated[
        str | None,
        typer.Option(
            "--profile-strategy",
            "-s",
            help="Profile sampling strategy: edge_saturated|realistic|uniform|adversarial",
        ),
    ] = None,
    census_year: Annotated[
        list[str] | None,
        typer.Option(
            "--census-year",
            help="ACS release(s) for --profile-strategy realistic (repeatable). A year means the 5-year "
            "estimates ending that year; also accepts ranges and surveys: 2023, 2021-2024, acs1-2025, "
            "2022,2024. Several years are spread evenly across cases. Default: "
            f"{DEFAULT_CENSUS_VINTAGE.label}",
        ),
    ] = None,
    fixed_policy_year: Annotated[
        bool,
        typer.Option(
            "--fixed-policy-year",
            help="With --profile-strategy realistic, apply the preset's fiscal-year rules to every case "
            "instead of the rules of each profile's census year (SNAP).",
        ),
    ] = False,
    population: Annotated[
        str,
        typer.Option(
            "--population",
            help="With --profile-strategy realistic: 'general' (ACS population, default) or 'caseload' "
            "(households that actually receive SNAP, from the SNAP Quality Control tables; SNAP presets).",
        ),
    ] = "general",
    quiet: Annotated[bool, typer.Option("--quiet", "-q")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate synthetic test cases for a single preset."""
    if formats is None:
        formats = ["yaml"]
    console = make_console(quiet=quiet)

    try:
        census_years = normalize_census_years(census_year) if census_year else None
        pipeline = Pipeline.from_preset(
            preset,
            profile_strategy=profile_strategy,
            console=console,
            census_years=census_years,
            match_census_year=not fixed_policy_year,
            population=population,
        )
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(2) from e

    cases = pipeline.generate(n=n, seed=seed)

    if output is None:
        # Validate formats before streaming — only yaml and jsonl support stdout
        stdout_formats = {"yaml", "jsonl"}
        unsupported = [f for f in formats if f.lower().strip() not in stdout_formats]
        if unsupported:
            console.print(
                f"[red]Error:[/red] Stdout streaming not supported for format(s): "
                f"{', '.join(unsupported)}. Use --output to write to a directory."
            )
            raise typer.Exit(2)
        _stream_to_stdout(cases, formats)
    else:
        pipeline.save(cases, output, formats=formats)

    emit_status(
        {
            "command": "generate",
            "preset": preset,
            "n": len(cases),
            **({"census_years": [v.label for v in pipeline.census_years]} if pipeline.census_years else {}),
            **({"population": population} if population != "general" else {}),
            "output": str(output),
            "status": "ok",
        },
        as_json=as_json,
        console=console,
    )


def _stream_to_stdout(cases: list[TestCase], formats: list[str]) -> None:
    """Write cases to stdout in the requested format(s).

    Args:
        cases: List of TestCase objects to stream.
        formats: List of format strings ('yaml' or 'jsonl').
    """
    yaml_fmt = YAMLFormatter()
    jsonl_fmt = JSONLFormatter()

    for fmt in formats:
        fmt = fmt.lower().strip()
        if fmt == "yaml":
            for case in cases:
                sys.stdout.write("---\n")
                sys.stdout.write(yaml_fmt.format_one(case))
        elif fmt == "jsonl":
            for case in cases:
                sys.stdout.write(json.dumps(jsonl_fmt.format_one(case)) + "\n")
