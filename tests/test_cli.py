"""Basic tests for the Trussflow CLI."""

from trussflow.cli import main


def test_cli_version(capsys):
    code = main(["--version"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out
