from pathlib import Path

import pytest

from epicsdbtools.parsers.database import DatabaseException
from epicsdbtools.parsers.iocsh import (
    IocshCommand,
    IocshState,
    _expand_macros,
    _parse_command_line,
    consume_iocsh_command,
    load_iocsh_file,
)

DATA_DIR = Path(__file__).parent / "test_iocsh_data"


# --- _expand_macros tests ---


@pytest.mark.parametrize(
    "text, macros, expected",
    [
        ("$(A) and $(B)", {"A": "1", "B": "2"}, "1 and 2"),
        ("$(A) $(B)", {"A": "1"}, "1 $(B)"),
        ("no macros here", {}, "no macros here"),
        ("$(X)", {"X": "val"}, "val"),
        ("$(A)$(A)", {"A": "x"}, "xx"),
    ],
)
def test_expand_macros(text, macros, expected):
    assert _expand_macros(text, macros) == expected


def test_expand_macros_strict_raises_on_undefined():
    with pytest.raises(DatabaseException, match="Undefined macros"):
        _expand_macros("$(MISSING)", {}, strict=True)


def test_expand_macros_strict_no_error_when_all_defined():
    assert _expand_macros("$(X)", {"X": "val"}, strict=True) == "val"


# --- _parse_command_line tests ---


@pytest.mark.parametrize(
    "line, expected",
    [
        ("", None),
        ("   ", None),
        ("# this is a comment", None),
        ("iocInit", ["iocInit"]),
        ("iocInit()", ["iocInit"]),
        (
            'dbLoadRecords("file.db", "P=x,R=y")',
            ["dbLoadRecords", "file.db", "P=x,R=y"],
        ),
        ('epicsEnvSet("KEY", "VALUE")', ["epicsEnvSet", "KEY", "VALUE"]),
    ],
)
def test_parse_command_line(line, expected):
    assert _parse_command_line(line) == expected


# --- consume_iocsh_command tests ---


def test_consume_epics_env_set():
    state = IocshState()
    consume_iocsh_command('epicsEnvSet "IOC", "myIOC"', state)
    assert state.macros == {"IOC": "myIOC"}


def test_consume_epics_env_set_uses_existing_macros():
    state = IocshState(macros={"TOP": "/opt"})
    consume_iocsh_command('epicsEnvSet "BIN", "$(TOP)/bin"', state)
    assert state.macros["BIN"] == "/opt/bin"


def test_consume_unknown_command_stored():
    state = IocshState()
    consume_iocsh_command("iocInit", state)
    assert len(state.other_commands) == 1
    assert state.other_commands[0].name == "iocInit"


def test_consume_comment_ignored():
    state = IocshState()
    consume_iocsh_command("# comment", state)
    assert state.macros == {}
    assert state.other_commands == []


def test_consume_db_load_records():
    state = IocshState()
    db_path = str(DATA_DIR / "test.db")
    consume_iocsh_command(f'dbLoadRecords("{db_path}", "P=X:,R=Y:,PORT=P1")', state)
    assert len(state.databases) == 1
    assert len(state.databases[0]) == 2


def test_consume_strict_macros_raises():
    state = IocshState()
    with pytest.raises(DatabaseException):
        consume_iocsh_command("someCmd $(UNDEFINED)", state, strict_macros=True)


# --- load_iocsh_file tests ---


def test_load_basic_startup():
    state = load_iocsh_file(DATA_DIR / "st.cmd")
    assert state.macros["IOC"] == "testIOC"
    assert state.macros["PORT"] == "MYPORT"
    assert state.macros["P"] == "Test:"
    assert state.macros["R"] == "Dev:"
    # iocInit and dbl should be in other commands
    cmd_names = [c.name for c in state.other_commands]
    assert "iocInit" in cmd_names
    assert "dbl" in cmd_names


def test_load_source_redirect():
    state = load_iocsh_file(DATA_DIR / "st_with_source.cmd")
    assert state.macros["TOP"] == "/some/path"
    assert state.macros["SOURCED_VAR"] == "hello"
    assert state.macros["AFTER_SOURCE"] == "yes"


def test_load_iocsh_load():
    state = load_iocsh_file(DATA_DIR / "st_with_iocshload.cmd")
    assert state.macros["BASE"] == "world"
    assert state.macros["SOURCED_VAR"] == "hello"


def test_load_resolve_sources_false():
    state = load_iocsh_file(DATA_DIR / "st_with_source.cmd", resolve_sources=False)
    assert state.macros["TOP"] == "/some/path"
    assert "SOURCED_VAR" not in state.macros
    assert state.macros["AFTER_SOURCE"] == "yes"


def test_load_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_iocsh_file(Path("/nonexistent/st.cmd"))


def test_load_initial_macros():
    state = load_iocsh_file(DATA_DIR / "st.cmd", macros={"EXTRA": "val"})
    assert state.macros["EXTRA"] == "val"
    assert state.macros["IOC"] == "testIOC"


def test_load_strict_macros_on_undefined():
    with pytest.raises(DatabaseException):
        load_iocsh_file(DATA_DIR / "st_strict.cmd", strict_macros=True)


def test_load_strict_macros_undefined_in_database():
    """Macro used inside a .db file but not provided raises with strict_macros."""
    state = IocshState()
    db_path = str(DATA_DIR / "test.db")
    # Only provide P and R, but PORT is also required in the .db file
    with pytest.raises(DatabaseException):
        consume_iocsh_command(
            f'dbLoadRecords("{db_path}", "P=X:,R=Y:")', state, strict_macros=True
        )


# --- IocshState tests ---


def test_iocsh_state_update_merges():
    s1 = IocshState(
        macros={"A": "1"}, databases=[], other_commands=[IocshCommand("cmd1", [])]
    )
    s2 = IocshState(
        macros={"B": "2"}, databases=[], other_commands=[IocshCommand("cmd2", [])]
    )
    s1.update(s2)
    assert s1.macros == {"A": "1", "B": "2"}
    assert len(s1.other_commands) == 2
