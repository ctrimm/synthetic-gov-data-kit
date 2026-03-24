"""govsynth list-presets command (stub — full implementation in Task 4)."""
import typer

app = typer.Typer(help="List all available generation presets.")


@app.callback(invoke_without_command=True)
def list_presets() -> None:
    """List all available generation presets."""
    raise NotImplementedError("list-presets not yet implemented")
