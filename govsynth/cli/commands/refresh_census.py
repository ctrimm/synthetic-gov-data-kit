"""govsynth refresh-census-data command.

Writes data/census/<survey>/<year>/<state>.json for one ACS vintage.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Annotated, Any

import httpx
import typer

from govsynth._paths import CENSUS_DIR
from govsynth.cli.output import make_console
from govsynth.sources.us.census import DEFAULT_CENSUS_VINTAGE, CensusVintage, vintage_dir
from govsynth.sources.us.census_fetcher import NATIONAL

_DATA_DIR = CENSUS_DIR

_ALL_STATES = [
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
]


def _emit(as_json: bool, console: Any, msg: dict[str, Any], text: str) -> None:  # noqa: ANN401 -- rich Console
    """Print a status line as JSON (stderr) or rich text."""
    if as_json:
        print(json.dumps(msg), file=sys.stderr)
    else:
        console.print(text)


def refresh_census_data(
    state: Annotated[
        str | None,
        typer.Option("--state", "-s", help="Single state code (e.g. VA) or 'national'. Default: all states + national"),
    ] = None,
    year: Annotated[
        int,
        typer.Option("--year", help="ACS vintage (end) year, e.g. 2024 for the 2020-2024 5-year estimates"),
    ] = DEFAULT_CENSUS_VINTAGE.year,
    survey: Annotated[
        str,
        typer.Option("--survey", help="acs5 (5-year, more precise) or acs1 (1-year, more current)"),
    ] = DEFAULT_CENSUS_VINTAGE.survey,
    source: Annotated[
        str,
        typer.Option(
            "--source",
            help="auto | api | summary-file. auto uses the Census API when CENSUS_API_KEY is set, "
            "otherwise the keyless bulk summary files (ACS 2021+)",
        ),
    ] = "auto",
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch ACS Census data for one vintage and update data/census/<survey>/<year>/."""
    console = make_console()
    api_key: str | None = os.environ.get("CENSUS_API_KEY")

    if survey not in ("acs5", "acs1"):
        console.print(f"[red]Error:[/red] Unknown survey '{survey}'. Use acs5 or acs1.")
        raise typer.Exit(2)
    if source not in ("auto", "api", "summary-file"):
        console.print(f"[red]Error:[/red] Unknown source '{source}'. Use auto, api or summary-file.")
        raise typer.Exit(2)
    if state is not None and state.upper() not in (*_ALL_STATES, NATIONAL):
        console.print(f"[red]Error:[/red] Unknown state '{state}'. Use a two-letter US state/DC code or 'national'.")
        raise typer.Exit(2)

    resolved_source = source if source != "auto" else ("api" if api_key else "summary-file")
    vintage = CensusVintage("acs1" if survey == "acs1" else "acs5", year)
    out_dir = vintage_dir(vintage, _DATA_DIR)
    states = [state.upper()] if state else [*_ALL_STATES, NATIONAL]

    # Confirmation prompt for all-states (non-dry-run only)
    if not state and not dry_run:
        if resolved_source == "api":
            n_calls = len(states) * 6
            key_note = (
                "CENSUS_API_KEY not set — the API rejects most keyless data requests."
                if not api_key
                else "CENSUS_API_KEY is set."
            )
            console.print(
                f"[yellow]Warning:[/yellow] This will make ~{n_calls} API calls "
                f"({len(states)} geographies × 6 table groups) for {vintage.label}.\n{key_note}"
            )
        else:
            console.print(
                f"[yellow]Warning:[/yellow] This will stream 18 ACS summary files from www2.census.gov "
                f"for {vintage.label} ({len(states)} geographies, no API key needed)."
            )
        if not typer.confirm("Continue?", default=False):
            raise typer.Exit(0)

    if dry_run:
        for s in states:
            out_path = str(out_dir / f"{s.lower()}.json")
            msg: dict[str, Any] = {
                "command": "refresh-census-data",
                "state": s,
                "vintage": vintage.label,
                "source": resolved_source,
                "status": "dry_run",
                "would_write": out_path,
            }
            _emit(as_json, console, msg, f"[dim]dry-run[/dim]  {s} ({vintage.label}) → {out_path}")
        return

    from govsynth.sources.us import census_fetcher

    ok: list[str] = []
    failed: list[str] = []

    def _fail(s: str, error: str) -> None:
        failed.append(s)
        err = {"command": "refresh-census-data", "state": s, "status": "error", "error": error}
        _emit(as_json, console, err, f"[red]✗[/red] {s}: {error}")

    def _write(s: str, data: dict[str, Any], note: str = "") -> None:
        path = census_fetcher.write_state_file(s, data, out_dir)
        ok.append(s)
        msg = {"command": "refresh-census-data", "state": s, "status": "ok", "output_file": str(path)}
        _emit(as_json, console, msg, f"[green]✓[/green] {s} → {path}{note}")

    if resolved_source == "summary-file":
        try:
            raws = census_fetcher.fetch_states_summary_file(states, year=year, survey=vintage.survey)
        except httpx.HTTPStatusError as exc:
            for s in states:
                _fail(s, f"HTTP {exc.response.status_code} fetching summary file (ACS {vintage.label} may not exist)")
            raws = {}
        except Exception as exc:  # noqa: BLE001
            for s in states:
                _fail(s, str(exc)[:200])
            raws = {}
        for s, raw in raws.items():
            try:
                data = census_fetcher.build_state_census_json(s, year, None, survey=vintage.survey, raw=raw)
                data["_metadata"]["source"] = "ACS table-based summary file (www2.census.gov)"
                _write(s, data)
            except Exception as exc:  # noqa: BLE001
                _fail(s, str(exc)[:200])
    else:
        for s in states:
            try:
                _write(s, census_fetcher.build_state_census_json(s, year, api_key, survey=vintage.survey))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    console.print(f"[yellow]Rate limited on {s}, retrying in 10s...[/yellow]")
                    time.sleep(10)
                    try:
                        _write(
                            s,
                            census_fetcher.build_state_census_json(s, year, api_key, survey=vintage.survey),
                            " (retry)",
                        )
                        continue
                    except Exception:  # noqa: BLE001, S110
                        pass
                _fail(s, f"HTTP {exc.response.status_code}")
            except Exception as exc:  # noqa: BLE001
                _fail(s, str(exc)[:200])

    if ok:
        # Invalidate the in-process JSON cache so any CensusDataSource used
        # later in this same process (e.g. a notebook or long-lived script)
        # sees the freshly written files instead of stale cached data.
        from govsynth.sources.us.census import _load_census_json_cached

        _load_census_json_cached.cache_clear()

    # Summary line
    status = "ok" if not failed else ("partial" if ok else "error")
    summary: dict[str, Any] = {
        "command": "refresh-census-data",
        "vintage": vintage.label,
        "summary": {"total": len(states), "ok": len(ok), "failed": len(failed)},
        "status": status,
    }
    if as_json:
        print(json.dumps(summary), file=sys.stderr)
    else:
        if failed:
            console.print(f"[yellow]Warning:[/yellow] {len(failed)} state(s) failed: {', '.join(failed)}")
        console.print(f"[green]Done:[/green] {len(ok)}/{len(states)} geographies refreshed for {vintage.label}.")

    if failed and not ok:
        raise typer.Exit(1)
