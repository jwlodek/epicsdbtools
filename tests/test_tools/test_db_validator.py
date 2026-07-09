from pathlib import Path

import pytest

from epicsdbtools.parsers import load_database_file, load_dbd_file
from epicsdbtools.parsers.database import (
    Database,
    DatabaseException,
    Record,
    RecordType,
)
from epicsdbtools.parsers.database_definition import DatabaseDefinition
from epicsdbtools.parsers.iocsh import (
    IocshCommand,
    IocshState,
    consume_iocsh_command,
    load_iocsh_file,
)
from epicsdbtools.parsers.proto import parse_protocol
from epicsdbtools.validation import (
    validate_database,
    validate_ioc,
    validate_iocsh_commands,
    validate_stream_protocols,
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
    assert "does not exist" in result.errors[0].message
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


# --- validate_stream_protocols tests ---


def _make_stream_db(
    proto_file: str,
    protocol: str,
    args: str = "",
    field_name: str = "INP",
) -> Database:
    """Helper to build a database with a single stream record."""
    db = Database()
    record = Record("Test:StreamRec", "ai")
    record.fields["DTYP"] = "stream"
    link_value = f"@{proto_file} {protocol}"
    if args:
        link_value = f"@{proto_file} {protocol}({args})"
    link_value += " PORT1"
    record.fields[field_name] = link_value
    db.add_record(record)
    return db


def test_stream_proto_valid():
    """A valid stream protocol reference should produce no errors."""
    proto = parse_protocol("""
        getVal {
            out "VAL?";
            in "%f";
        }
    """)
    db = _make_stream_db("test.proto", "getVal")
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert result.is_valid


def test_stream_proto_file_not_found():
    """A reference to a missing protocol file should produce an error."""
    db = _make_stream_db("missing.proto", "getVal")
    result = validate_stream_protocols([db], {})
    assert not result.is_valid
    assert "not found" in result.errors[0].message


def test_stream_proto_function_not_found():
    """A reference to a missing protocol function should produce an error."""
    proto = parse_protocol("""
        getVal {
            out "VAL?";
            in "%f";
        }
    """)
    db = _make_stream_db("test.proto", "nonexistent")
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert not result.is_valid
    assert "nonexistent" in result.errors[0].message


def test_stream_proto_wrong_arg_count():
    """Wrong number of args to a parameterized protocol should error."""
    proto = parse_protocol("""
        getParam {
            out "\\$1:READ?";
            in "%f";
        }
    """)
    # Protocol expects 1 arg, provide 2
    db = _make_stream_db("test.proto", "getParam", args="A, B")
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert not result.is_valid
    assert "expects 1 argument(s) but 2 provided" in result.errors[0].message


def test_stream_proto_correct_arg_count():
    """Correct number of args should pass."""
    proto = parse_protocol("""
        getParam {
            out "\\$1:READ?";
            in "%f";
        }
    """)
    db = _make_stream_db("test.proto", "getParam", args="ADDR")
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert result.is_valid


def test_stream_proto_no_args_for_no_params():
    """A protocol with no params and no args should pass."""
    proto = parse_protocol("""
        getVal {
            out "VAL?";
            in "%f";
        }
    """)
    db = _make_stream_db("test.proto", "getVal")
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert result.is_valid


def test_stream_proto_non_stream_record_skipped():
    """Records without DTYP=stream should be skipped."""
    proto = parse_protocol("""
        getVal {
            out "VAL?";
            in "%f";
        }
    """)
    db = Database()
    record = Record("Test:NonStream", "ai")
    record.fields["DTYP"] = "Soft Channel"
    record.fields["INP"] = "@missing.proto getVal PORT1"
    db.add_record(record)
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert result.is_valid


def test_stream_proto_stringin_with_int_converter():
    """A stringin record with %d should produce an error."""
    proto = parse_protocol("""
        readInt {
            out "VAL?";
            in "%d";
        }
    """)
    db = Database()
    record = Record("Test:StrInt", "stringin")
    record.fields["DTYP"] = "stream"
    record.fields["INP"] = "@test.proto readInt PORT1"
    db.add_record(record)
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert not result.is_valid
    assert "not compatible" in result.errors[0].message
    assert "'int'" in result.errors[0].message


def test_stream_proto_bi_with_float_converter():
    """A bi record with %f should produce an error."""
    proto = parse_protocol("""
        readFloat {
            out "VAL?";
            in "%f";
        }
    """)
    db = Database()
    record = Record("Test:BiFloat", "bi")
    record.fields["DTYP"] = "stream"
    record.fields["INP"] = "@test.proto readFloat PORT1"
    db.add_record(record)
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert not result.is_valid
    assert "not compatible" in result.errors[0].message
    assert "'float'" in result.errors[0].message


def test_stream_proto_bi_with_enum_converter():
    """A bi record with %{OFF|ON} should pass (enum maps to int)."""
    proto = parse_protocol("""
        readSwitch {
            out "SW?";
            in "%{OFF|ON}";
        }
    """)
    db = Database()
    record = Record("Test:BiEnum", "bi")
    record.fields["DTYP"] = "stream"
    record.fields["INP"] = "@test.proto readSwitch PORT1"
    db.add_record(record)
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert result.is_valid


def test_stream_proto_longin_with_float_converter():
    """A longin record with %f should produce an error."""
    proto = parse_protocol("""
        readFloat {
            out "VAL?";
            in "%f";
        }
    """)
    db = Database()
    record = Record("Test:LongFloat", "longin")
    record.fields["DTYP"] = "stream"
    record.fields["INP"] = "@test.proto readFloat PORT1"
    db.add_record(record)
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert not result.is_valid
    assert "not compatible" in result.errors[0].message


def test_stream_proto_ai_with_string_converter():
    """An ai record with %s should produce an error."""
    proto = parse_protocol("""
        readStr {
            out "VAL?";
            in "%s";
        }
    """)
    db = Database()
    record = Record("Test:AiStr", "ai")
    record.fields["DTYP"] = "stream"
    record.fields["INP"] = "@test.proto readStr PORT1"
    db.add_record(record)
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert not result.is_valid
    assert "not compatible" in result.errors[0].message


def test_stream_proto_ai_with_float_converter():
    """An ai record with %f should pass."""
    proto = parse_protocol("""
        readFloat {
            out "VAL?";
            in "%f";
        }
    """)
    db = Database()
    record = Record("Test:AiFloat", "ai")
    record.fields["DTYP"] = "stream"
    record.fields["INP"] = "@test.proto readFloat PORT1"
    db.add_record(record)
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert result.is_valid


def test_stream_proto_stringout_with_string_converter():
    """A stringout record with %s should pass."""
    proto = parse_protocol("""
        writeStr {
            out "%s";
        }
    """)
    db = Database()
    record = Record("Test:StrOut", "stringout")
    record.fields["DTYP"] = "stream"
    record.fields["OUT"] = "@test.proto writeStr PORT1"
    db.add_record(record)
    result = validate_stream_protocols([db], {"test.proto": proto})
    assert result.is_valid


# --- System test: all error categories in one startup script ---


def test_system_all_validation_categories():
    """Load a startup script that has errors in every validation category.

    Categories checked:
    1. Unknown record type
    2. Invalid field name
    3. Invalid DTYP
    4. Unexpanded macros
    5. Stream proto file not found
    6. Stream proto function not found
    7. Stream proto wrong arg count
    8. Stream converter incompatible with record type (stringin + %f)
    9. Stream converter incompatible with record type (bi + %f)
    10. Stream converter incompatible with record type (longin + %f)
    11. Unknown iocsh command
    """
    state = load_iocsh_file(
        DATA_DIR / "st_all_errors.cmd",
    )

    result = validate_ioc(state)

    # Should have failed
    assert not result.is_valid

    error_messages = [e.message for e in result.errors]
    warning_messages = [w.message for w in result.warnings]

    # 1. Unknown record type
    assert any("not found in database definition" in m for m in error_messages)

    # 2. Invalid field
    assert any(
        e.field_name == "NONEXISTENT_FIELD" and "does not exist" in e.message
        for e in result.errors
    )

    # 3. Invalid DTYP
    assert any("noSuchDriver" in m for m in error_messages)

    # 4. Unexpanded macros
    assert any("UNDEFINED_MACRO" in m for m in error_messages)

    # 5. Proto file not found
    assert any("nonexistent.proto" in m for m in error_messages)

    # 6. Proto function not found
    assert any("noSuchProtocol" in m for m in error_messages)

    # 7. Wrong arg count
    assert any("expects 1 argument(s) but 2 provided" in m for m in error_messages)

    # 8. stringin with float converter
    assert any("not compatible" in m and "stringin" in m for m in error_messages)

    # 9. bi with float converter
    assert any("not compatible" in m and "bi" in m for m in error_messages)

    # 10. longin with float converter
    assert any("not compatible" in m and "longin" in m for m in error_messages)

    # 11. Unknown iocsh command (warning by default)
    assert any("totallyUnknownCommand" in m for m in warning_messages)

    # Verify valid records did not produce errors about them
    assert not any("Test:GoodStream" in m for m in error_messages)
    assert not any("Test:GoodBiEnum" in m for m in error_messages)
    assert not any("Test:GoodStringIn" in m for m in error_messages)
    assert not any("Test:GoodParam" in m for m in error_messages)
