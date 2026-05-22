from pathlib import Path

import pytest

from epicsdbtools.parsers import load_database_file, load_dbd_file
from epicsdbtools.parsers.database import Database, DatabaseException, Record, RecordType
from epicsdbtools.parsers.database_definition import DatabaseDefinition
from epicsdbtools.parsers.iocsh import (
    IocshCommand,
    IocshState,
    consume_iocsh_command,
    load_iocsh_file,
)
from epicsdbtools.validation import (
    BUILTIN_IOCSH_COMMANDS,
    ValidationResult,
    ValidationSeverity,
    validate_database,
    validate_ioc,
    validate_iocsh_commands,
)

DATA_DIR = Path(__file__).parent / "test_validator_data"


@pytest.fixture
def dbd() -> DatabaseDefinition:
    return load_dbd_file(DATA_DIR / "test.dbd")


@pytest.fixture
def valid_db() -> Database:
    return load_database_file(DATA_DIR / "valid.db")


@pytest.fixture
def invalid_field_db() -> Database:
    return load_database_file(DATA_DIR / "invalid_field.db")


@pytest.fixture
def invalid_dtyp_db() -> Database:
    return load_database_file(DATA_DIR / "invalid_dtyp.db")


# --- validate_database tests ---


def test_valid_database_passes(dbd, valid_db):
    result = validate_database(valid_db, dbd)
    assert result.is_valid
    assert len(result.errors) == 0


def test_invalid_field_detected(dbd, invalid_field_db):
    result = validate_database(invalid_field_db, dbd)
    assert not result.is_valid
    assert len(result.errors) == 1
    assert "NONEXISTENT" in result.errors[0].message
    assert result.errors[0].record_name == "Test:BadField"
    assert result.errors[0].field_name == "NONEXISTENT"


def test_invalid_dtyp_detected(dbd, invalid_dtyp_db):
    result = validate_database(invalid_dtyp_db, dbd)
    assert not result.is_valid
    assert len(result.errors) == 1
    assert "nonExistentDriver" in result.errors[0].message
    assert result.errors[0].field_name == "DTYP"


def test_unknown_record_type(dbd):
    """A record type not in the dbd should produce an error."""
    db = Database()
    record = Record("Test:Waveform", RecordType.WAVEFORM)
    record.fields["FTVL"] = "DOUBLE"
    db.add_record(record)

    result = validate_database(db, dbd)
    assert not result.is_valid
    assert "not found in database definition" in result.errors[0].message


# --- validate_iocsh_commands tests ---


def test_builtin_commands_pass(dbd):
    state = IocshState(dbd=dbd)
    state.other_commands = [
        IocshCommand(name="iocInit", args=[]),
        IocshCommand(name="dbl", args=[]),
    ]
    result = validate_iocsh_commands(state)
    assert len(result.warnings) == 0


def test_registered_function_passes(dbd):
    state = IocshState(dbd=dbd)
    state.other_commands = [
        IocshCommand(name="mySubProcess", args=[]),
        IocshCommand(name="myCustomInit", args=[]),
    ]
    result = validate_iocsh_commands(state)
    assert len(result.warnings) == 0


def test_registered_registrar_passes(dbd):
    state = IocshState(dbd=dbd)
    state.other_commands = [
        IocshCommand(name="asSub", args=[]),
        IocshCommand(name="myDriverRegister", args=[]),
    ]
    result = validate_iocsh_commands(state)
    assert len(result.warnings) == 0


def test_unknown_command_warns(dbd):
    state = IocshState(dbd=dbd)
    state.other_commands = [
        IocshCommand(name="unknownCommand", args=["arg1"]),
    ]
    result = validate_iocsh_commands(state)
    assert len(result.warnings) == 1
    assert "unknownCommand" in result.warnings[0].message


def test_no_dbd_warns():
    state = IocshState()
    state.other_commands = [IocshCommand(name="something", args=[])]
    result = validate_iocsh_commands(state)
    assert len(result.warnings) == 1
    assert "No database definition loaded" in result.warnings[0].message


# --- validate_ioc tests ---


def test_full_valid_ioc(dbd, valid_db):
    state = IocshState(dbd=dbd)
    state.databases = [valid_db]
    state.other_commands = [
        IocshCommand(name="iocInit", args=[]),
        IocshCommand(name="mySubProcess", args=[]),
    ]
    result = validate_ioc(state)
    assert result.is_valid


def test_full_invalid_ioc(dbd, invalid_field_db):
    state = IocshState(dbd=dbd)
    state.databases = [invalid_field_db]
    state.other_commands = [
        IocshCommand(name="unknownCmd", args=[]),
    ]
    result = validate_ioc(state)
    assert not result.is_valid
    assert len(result.errors) >= 1
    assert len(result.warnings) >= 1


def test_no_dbd_with_databases_warns(valid_db):
    state = IocshState()
    state.databases = [valid_db]
    result = validate_ioc(state)
    # Should warn about missing dbd but not error
    assert result.is_valid
    assert any("No database definition" in w.message for w in result.warnings)


# --- dbLoadDatabase in iocsh tests ---


def test_db_load_database_sets_dbd():
    """consume_iocsh_command with dbLoadDatabase should set the dbd."""
    state = IocshState()
    dbd_path = str(DATA_DIR / "test.dbd")
    consume_iocsh_command(f'dbLoadDatabase("{dbd_path}")', state)
    assert state.dbd is not None
    assert "ai" in state.dbd.record_types
    assert "ao" in state.dbd.record_types


def test_db_load_database_file_not_found():
    state = IocshState()
    with pytest.raises(FileNotFoundError, match="Database definition file"):
        consume_iocsh_command('dbLoadDatabase("nonexistent.dbd")', state)


# --- load_iocsh_file with validate tests ---


def test_valid_startup_passes_validation():
    state = load_iocsh_file(
        DATA_DIR / "st_valid.cmd",
        macros={"DATA_DIR": str(DATA_DIR)},
    )
    result = validate_ioc(state)
    assert result.is_valid
    assert state.dbd is not None
    assert len(state.databases) == 1


def test_invalid_startup_raises_on_validation():
    state = load_iocsh_file(
        DATA_DIR / "st_invalid.cmd",
        macros={"DATA_DIR": str(DATA_DIR)},
    )
    with pytest.raises(DatabaseException, match="IOC validation failed"):
        from epicsdbtools.validation import validate_ioc_or_raise
        validate_ioc_or_raise(state)


def test_invalid_startup_no_validation_passes():
    state = load_iocsh_file(
        DATA_DIR / "st_invalid.cmd",
        macros={"DATA_DIR": str(DATA_DIR)},
    )
    assert state.dbd is not None
    assert len(state.databases) == 1
