import os
from pathlib import Path
import pytest

from dbtoolspy.paramdefs import get_internal_param_type_from_dtyp, ParamType, ParamDef, get_params_from_db, generate_header_file_for_db, generate_cpp_file_for_db


def test_get_internal_param_type_from_dtyp():
    assert get_internal_param_type_from_dtyp(ParamType.INT) == "asynParamInt32"
    assert get_internal_param_type_from_dtyp(ParamType.DOUBLE) == "asynParamFloat64"
    assert get_internal_param_type_from_dtyp(ParamType.STRINGIN) == "asynParamOctet"
    assert get_internal_param_type_from_dtyp(ParamType.STRINGOUT) == "asynParamOctet"

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

    with open(header_file, "r") as hf:
        with open(expected_header, "r") as eh:
            assert hf.read() == eh.read()

    with open(cpp_file, "r") as cf:
        with open(expected_cpp, "r") as ec:
            assert cf.read() == ec.read()
