from pathlib import Path

from epicsdbtools.parsers.proto import (
    load_protocol_file,
    parse_protocol,
)

TEST_DATA_DIR = Path(__file__).parent / "test_proto_data"


def test_parse_global_variables():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    assert proto.variables["Terminator"] == "CR LF"
    assert proto.variables["ReplyTimeout"] == "1000"
    assert proto.variables["ReadTimeout"] == "200"
    assert proto.variables["ExtraInput"] == "Ignore"


def test_parse_simple_protocol():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    get_val = proto.get_protocol("getVal")
    assert get_val is not None
    assert len(get_val.commands) == 2
    assert get_val.commands[0].name == "out"
    assert get_val.commands[0].argument == '"VAL?"'
    assert get_val.commands[1].name == "in"
    assert get_val.commands[1].argument == '"%f"'
    assert get_val.parameters == []
    assert get_val.handlers == []


def test_parse_protocol_with_init_handler():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    set_val = proto.get_protocol("setVal")
    assert set_val is not None
    assert len(set_val.commands) == 1
    assert set_val.commands[0].name == "out"
    assert len(set_val.handlers) == 1
    assert set_val.handlers[0].name == "init"
    assert len(set_val.handlers[0].commands) == 1
    assert set_val.handlers[0].commands[0].name == "getVal"


def test_parse_parameterized_protocol():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    get_param = proto.get_protocol("getParam")
    assert get_param is not None
    assert get_param.parameters == ["1"]
    assert get_param.num_parameters == 1
    assert len(get_param.commands) == 2
    assert get_param.variables["ExtraInput"] == "Ignore"


def test_parse_protocol_with_multiple_handlers():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    read_status = proto.get_protocol("readStatus")
    assert read_status is not None
    assert len(read_status.handlers) == 3
    handler_names = [h.name for h in read_status.handlers]
    assert "mismatch" in handler_names
    assert "readtimeout" in handler_names
    assert "init" in handler_names


def test_parse_from_string():
    source = """
    Terminator = LF;
    query {
        out "Q?";
        in "%s";
    }
    """
    proto = parse_protocol(source)
    assert proto.variables["Terminator"] == "LF"
    assert len(proto.protocols) == 1
    assert proto.protocols[0].name == "query"


def test_file_not_found():
    try:
        load_protocol_file("/nonexistent/path/file.proto")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass


def test_empty_protocol():
    source = """
    emptyProto {
    }
    """
    proto = parse_protocol(source)
    assert len(proto.protocols) == 1
    assert proto.protocols[0].name == "emptyProto"
    assert proto.protocols[0].commands == []


def test_protocol_count():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    assert len(proto.protocols) == 8


def test_positional_parameters_inferred():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    set_ch = proto.get_protocol("setChannel")
    assert set_ch is not None
    assert set_ch.parameters == ["1"]
    assert set_ch.num_parameters == 1


def test_multiple_positional_parameters():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    get_range = proto.get_protocol("getRange")
    assert get_range is not None
    assert get_range.parameters == ["1", "2"]
    assert get_range.num_parameters == 2


def test_out_format_and_converters():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    set_val = proto.get_protocol("setVal")
    assert set_val is not None
    assert set_val.out_format == "VAL %f"
    assert len(set_val.out_converters) == 1
    assert set_val.out_converters[0].conversion == "f"
    assert set_val.out_converters[0].value_type is float


def test_in_format_and_converters():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    get_val = proto.get_protocol("getVal")
    assert get_val is not None
    assert get_val.in_format == "%f"
    assert len(get_val.in_converters) == 1
    assert get_val.in_converters[0].conversion == "f"
    assert get_val.in_converters[0].value_type is float


def test_format_converter_width():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    set_ch = proto.get_protocol("setChannel")
    assert set_ch is not None
    out_convs = set_ch.out_converters
    assert len(out_convs) == 1
    assert out_convs[0].conversion == "d"
    assert out_convs[0].width == 2
    assert out_convs[0].flags == "0"
    assert out_convs[0].value_type is int


def test_skip_converter():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    read_status = proto.get_protocol("readStatus")
    assert read_status is not None
    mismatch_handler = next(h for h in read_status.handlers if h.name == "mismatch")
    in_cmd = mismatch_handler.commands[0]
    convs = in_cmd.converters
    assert len(convs) == 1
    assert convs[0].skip is True
    assert convs[0].conversion == "s"


def test_command_parameter_refs():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    get_range = proto.get_protocol("getRange")
    assert get_range is not None
    out_cmd = get_range.out_commands[0]
    refs = out_cmd.parameter_refs
    assert "1" in refs
    assert "2" in refs


def test_multiple_in_converters():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    get_range = proto.get_protocol("getRange")
    assert get_range is not None
    assert len(get_range.in_converters) == 2
    assert all(c.value_type is float for c in get_range.in_converters)


def test_no_out_format_returns_none():
    source = """
    readOnly {
        in "%d";
    }
    """
    proto = parse_protocol(source)
    assert proto.protocols[0].out_format is None
    assert proto.protocols[0].out_converters == []


def test_get_protocol_not_found():
    source = """
    myProto {
        out "X";
    }
    """
    proto = parse_protocol(source)
    assert proto.get_protocol("nonexistent") is None


def test_enum_converter():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    set_switch = proto.get_protocol("setSwitch")
    assert set_switch is not None
    convs = set_switch.out_converters
    assert len(convs) == 1
    assert convs[0].conversion == "enum"
    assert convs[0].enum_choices == ["OFF", "ON"]
    assert convs[0].value_type is int
    assert str(convs[0]) == "%{OFF|ON}"


def test_enum_converter_in():
    proto = load_protocol_file(TEST_DATA_DIR / "test.proto")
    get_switch = proto.get_protocol("getSwitch")
    assert get_switch is not None
    convs = get_switch.in_converters
    assert len(convs) == 1
    assert convs[0].conversion == "enum"
    assert convs[0].enum_choices == ["OFF", "ON"]
