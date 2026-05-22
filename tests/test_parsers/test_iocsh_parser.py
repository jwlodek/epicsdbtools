from pathlib import Path

import pytest

from epicsdbtools.parsers.database import DatabaseException
from epicsdbtools.parsers.iocsh import (
    IocshCommand,
    IocshState,
    _expand_macros,
    _parse_command_line,
    _resolve_file_path,
    consume_iocsh_command,
    load_iocsh_file,
)
from epicsdbtools.validation import validate_macros

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


def test_expand_macros_unresolved_left_as_is():
    assert _expand_macros("$(MISSING)", {}) == "$(MISSING)"


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


def test_consume_undefined_macro_stored_unexpanded():
    """Undefined macros are kept in the state for later validation."""
    state = IocshState()
    consume_iocsh_command('someCmd("$(UNDEFINED)")', state)
    assert len(state.other_commands) == 1
    assert "$(UNDEFINED)" in state.other_commands[0].args[0]


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


def test_validate_macros_catches_undefined_in_command():
    """validate_macros detects unexpanded macros in command arguments."""
    state = load_iocsh_file(DATA_DIR / "st_strict.cmd")
    result = validate_macros(state)
    assert not result.is_valid
    assert any("UNDEFINED_MACRO" in err.message for err in result.errors)


def test_validate_macros_catches_undefined_in_database():
    """validate_macros detects unexpanded macros in loaded database fields."""
    state = IocshState()
    db_path = str(DATA_DIR / "test.db")
    # Only provide P and R, but PORT is also required in the .db file
    consume_iocsh_command(f'dbLoadRecords("{db_path}", "P=X:,R=Y:")', state)
    result = validate_macros(state)
    assert not result.is_valid
    assert any("PORT" in err.message for err in result.errors)


# --- cwd and cd tests ---


def test_load_sets_cwd_to_script_directory():
    """Loading a startup script sets cwd to the script's directory."""
    state = load_iocsh_file(DATA_DIR / "st.cmd")
    assert state.cwd == DATA_DIR.resolve()


def test_cd_changes_cwd():
    """The cd command updates the working directory."""
    state = IocshState(cwd=Path("/some/path"))
    consume_iocsh_command('cd("/other/path")', state)
    assert state.cwd == Path("/other/path")


def test_cd_relative_resolves_from_cwd():
    """A relative cd resolves against the current cwd."""
    state = IocshState(cwd=DATA_DIR.resolve())
    consume_iocsh_command('cd("subdir")', state)
    assert state.cwd == (DATA_DIR / "subdir").resolve()


def test_load_with_cd_finds_db():
    """A startup script using cd can find db files in the new directory."""
    state = load_iocsh_file(DATA_DIR / "st_with_cd.cmd")
    assert len(state.databases) == 1
    assert "Test:SubRecord" in state.databases[0]


# --- EPICS_DB_INCLUDE_PATH tests ---


def test_include_path_resolves_db():
    """EPICS_DB_INCLUDE_PATH allows finding db files in listed directories."""
    include_dir = str(DATA_DIR / "include_path_dir")
    state = load_iocsh_file(
        DATA_DIR / "st_with_include_path.cmd",
        macros={"EPICS_DB_INCLUDE_PATH": include_dir},
    )
    assert len(state.databases) == 1
    assert "Test:IncludeRecord" in state.databases[0]


def test_include_path_multiple_dirs(tmp_path):
    """EPICS_DB_INCLUDE_PATH supports colon-separated directories."""
    # Create a db file in a temp directory
    db_file = tmp_path / "found.db"
    db_file.write_text('record(ai, "MyRec") {\n    field(DTYP, "Soft Channel")\n}\n')

    state = IocshState(
        cwd=tmp_path,
        macros={"EPICS_DB_INCLUDE_PATH": f"/nonexistent:{tmp_path}"},
    )
    consume_iocsh_command('dbLoadRecords("found.db")', state)
    assert len(state.databases) == 1
    assert "MyRec" in state.databases[0]


def test_include_path_not_found_raises():
    """FileNotFoundError is raised if file is not in cwd or include path."""
    state = IocshState(
        cwd=DATA_DIR.resolve(),
        macros={"EPICS_DB_INCLUDE_PATH": "/nonexistent"},
    )
    with pytest.raises(FileNotFoundError, match="Database file not found"):
        consume_iocsh_command('dbLoadRecords("no_such_file.db")', state)


# --- _resolve_file_path with custom macro ---


def test_resolve_file_path_custom_macro(tmp_path):
    """_resolve_file_path works with an arbitrary search path macro."""
    db_file = tmp_path / "proto.db"
    db_file.write_text("placeholder")

    state = IocshState(
        cwd=Path("/nonexistent"),
        macros={"STREAM_PROTOCOL_PATH": str(tmp_path)},
    )
    resolved = _resolve_file_path(
        Path("proto.db"), state, search_path_macro="STREAM_PROTOCOL_PATH"
    )
    assert resolved == db_file


def test_resolve_file_path_no_macro_search():
    """_resolve_file_path with search_path_macro=None skips macro search."""
    state = IocshState(
        cwd=DATA_DIR.resolve(),
        macros={"EPICS_DB_INCLUDE_PATH": str(DATA_DIR / "include_path_dir")},
    )
    # "included.db" exists in include_path_dir but not in DATA_DIR
    resolved = _resolve_file_path(Path("included.db"), state, search_path_macro=None)
    # Should NOT find it since we disabled the search
    assert not resolved.exists()


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
