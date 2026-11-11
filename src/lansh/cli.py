"""
The ``lansh`` command line.

Sub-commands are added as each plan step lands. Each command imports what it needs when it
runs, so starting the CLI stays cheap. A command's docstring is its ``--help`` text. The
``lansh estate`` commands live in :mod:`lansh.estate.cli`, beside the estate tooling they
drive, because some of them read the answer key, which factory code must never do.
"""

from __future__ import annotations

import logging

import typer

from lansh import __version__
from lansh.estate.cli import estate_app

app = typer.Typer(
    help="LANSH: a reconciliation-first agentic migration factory.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(estate_app, name="estate")


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    """
    Set up logging before any command runs.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def version() -> None:
    """
    Print the LANSH version.
    """
    typer.echo(f"lansh {__version__}")


def main() -> None:
    """
    Run the command line; ``pyproject.toml`` installs this as the ``lansh`` script.
    """
    app()
