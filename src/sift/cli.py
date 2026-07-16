"""Sift command-line interface.

Seven flat subcommands per SPEC.md §5.8. All bodies are stubs in plan 01-01;
new/ingest/show are implemented later in this phase, the rest in later phases.
"""

from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def new(
    case_name: str,
    input: Annotated[str, typer.Option("--input", help="Directory of artefacts")],
    # Typer reads the default once at import time, so the shared list is safe here.
    adapter: Annotated[
        list[str], typer.Option("--adapter", help="glob=name adapter override")
    ] = [],  # noqa: B006
) -> None:
    """Create a new case from a directory of artefacts."""
    print("new is implemented later in this phase")
    raise typer.Exit(1)


@app.command()
def ingest(case: str) -> None:
    """Parse the case's input directory and store canonical events."""
    print("ingest is implemented later in this phase")
    raise typer.Exit(1)


@app.command()
def show(case: str, what: str) -> None:
    """Show events, clusters or hypotheses for a case."""
    print("show is implemented later in this phase")
    raise typer.Exit(1)


@app.command()
def analyze() -> None:
    """Cluster events and generate ranked root-cause hypotheses."""
    print("analyze arrives in Phase 4 (M4)")
    raise typer.Exit(1)


@app.command()
def report() -> None:
    """Render the triage report."""
    print("report arrives in Phase 6 (M6)")
    raise typer.Exit(1)


@app.command("eval")
def eval_() -> None:
    """Run the golden-case evaluation suite."""
    print("eval arrives in Phase 7 (M7)")
    raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """Check the local environment and inference endpoint."""
    print("doctor arrives in Phase 3 (M3)")
    raise typer.Exit(1)
