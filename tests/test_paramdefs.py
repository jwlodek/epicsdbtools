import os
from pathlib import Path

from epicsdbtools.tools.paramdefs import (
    ParamType,
    generate_cpp_file_for_db,
    generate_header_file_for_db,
    get_internal_param_type_from_dtyp,
    get_params_from_db,
)


def test_get_internal_param_type_from_dtyp():
    assert get_internal_param_type_from_dtyp(ParamType.INT) == "asynParamInt32"
    assert get_internal_param_type_from_dtyp(ParamType.DOUBLE) == "asynParamFloat64"
    assert get_internal_param_type_from_dtyp(ParamType.STRINGIN) == "asynParamOctet"
    assert get_internal_param_type_from_dtyp(ParamType.STRINGOUT) == "asynParamOctet"
    assert get_internal_param_type_from_dtyp(ParamType.UINTDIGITAL) == "asynParamUInt32Digital"


def test_get_params_from_db(sample_asyn_db):
    params = get_params_from_db(sample_asyn_db, "Test")
    expected_param_names = [
        "Test_BoAsynint32",
        "Test_BiAsynint32",
        "Test_LonginAsynint32",
        "Test_LongoutAsynint32",
        "Test_MbbiAsynint32",
        "Test_MbboAsynint32",
        "Test_AoAsynint32",
        "Test_AiAsynint32",
        "Test_AiAsynfloat64",
        "Test_AoAsynfloat64",
        "Test_LonginAsynfloat64",
        "Test_LongoutAsynfloat64",
        "Test_StringinAsynoctetread",
        "Test_StringoutAsynoctetread",
        "Test_WaveformAsynoctetread",
        "Test_StringoutAsynoctetwrite",
        "Test_StringinAsynoctetwrite",
        "Test_WaveformAsynoctetwrite",
        "Test_MbbiAsynuint32digital",
        "Test_MbboAsynuint32digital",
        "Test_BiAsynuint32digital",
        "Test_BoAsynuint32digital",
    ]
    for i, param in enumerate(params):
        assert expected_param_names[i] == param.name


def test_generate_header_and_cpp_files(tmp_path, sample_asyn_db):
    params = get_params_from_db(sample_asyn_db, "Test")
    generate_header_file_for_db(params, tmp_path, "Test")
    generate_cpp_file_for_db(params, tmp_path, "Test")

    header_file = tmp_path / "TestParamDefs.h"
    cpp_file = tmp_path / "TestParamDefs.cpp"

    assert header_file.exists()
    assert cpp_file.exists()

    expected_dir = Path(os.path.dirname(__file__)) / "expected_paramdefs"
    expected_header = expected_dir / "TestParamDefs.h"
    expected_cpp = expected_dir / "TestParamDefs.cpp"

    with open(header_file) as hf:
        with open(expected_header) as eh:
            assert hf.read() == eh.read()

    with open(cpp_file) as cf:
        with open(expected_cpp) as ec:
            assert cf.read() == ec.read()


def test_generate_header_file_with_prefix(tmp_path, sample_asyn_db):
    params = get_params_from_db(sample_asyn_db, "Test", prefix="TST_MB")
    generate_header_file_for_db(params, tmp_path, "Test")

    header_file = tmp_path / "TestParamDefs.h"
    assert header_file.exists()
    with open(header_file) as hf:
        content = hf.read()
        assert "Test_MbbiAsynint32" in content
        assert "Test_MbboAsynint32" in content
        assert "Test_MbbiAsynuint32digital" in content
        assert "Test_MbboAsynuint32digital" in content
        assert "Test_BoAsynint32" not in content
        assert "Test_AiAsynfloat64" not in content


def test_generate_header_file_no_params(tmp_path):
    generate_header_file_for_db([], tmp_path, "EmptyTest")
    header_file = tmp_path / "EmptyTestParamDefs.h"
    assert header_file.exists()
    with open(header_file) as hf:
        content = hf.read()
        assert "#define NUM_EMPTYTEST_PARAMS 0" in content
        assert "#define EMPTYTEST_FIRST_PARAM" not in content
        assert "#define EMPTYTEST_LAST_PARAM" not in content
