import argparse
from pathlib import Path

import pytest

from epicsdbtools.parsers.database import DatabaseException
from epicsdbtools.tools.ioc_startup_linter import add_parser_args, main

DATA_DIR = Path(__file__).parent.parent / "test_parsers" / "test_iocsh_data"


@pytest.fixture
def make_args():
    """Helper to create an argparse.Namespace for the linter."""

    def _make_args(input_path: str | Path):
        parser = argparse.ArgumentParser()
        add_parser_args(parser)
        return parser.parse_args([str(input_path)])

    return _make_args


def test_linter_valid_startup(make_args, capsys):
    """A valid startup script with all macros defined should not raise."""
    args = make_args(DATA_DIR / "st.cmd")
    main(args)
    captured = capsys.readouterr()
    assert "IocshState" in captured.out


def test_linter_undefined_macro_raises(make_args):
    """A startup script using an undefined macro should raise DatabaseException."""
    args = make_args(DATA_DIR / "st_strict.cmd")
    with pytest.raises(DatabaseException, match="Undefined macros"):
        main(args)


def test_linter_file_not_found(make_args):
    """A non-existent startup script should raise FileNotFoundError."""
    args = make_args("/nonexistent/st.cmd")
    with pytest.raises(FileNotFoundError):
        main(args)


def test_linter_missing_sourced_file(tmp_path, make_args):
    """A startup script sourcing a non-existent file should raise FileNotFoundError."""
    cmd_file = tmp_path / "st.cmd"
    cmd_file.write_text("< nonexistent_file.cmd\n")
    args = make_args(cmd_file)
    with pytest.raises(FileNotFoundError, match="Sourced script not found"):
        main(args)


def test_linter_missing_db_file(tmp_path, make_args):
    """A startup script loading a non-existent db should raise FileNotFoundError."""
    cmd_file = tmp_path / "st.cmd"
    cmd_file.write_text('dbLoadRecords("missing.db", "P=x")\n')
    args = make_args(cmd_file)
    with pytest.raises(FileNotFoundError, match="Database file not found"):
        main(args)
