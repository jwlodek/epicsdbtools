import pytest

from pathlib import Path
from epicsdbtools.parsers import substitution as sub_file_parser
import io


@pytest.fixture
def example_substitution_file():
    return Path(__file__).parent / "examples/afg3011.substitutions"


@pytest.fixture
def example_substitution_file_content(example_substitution_file):
    with open(example_substitution_file) as f:
        return f.read()


def test_parse_filename():
    src = iter(["file", "test.db", "{", "pattern", "{", "MACRO1", "MACRO2", "}", "{", "VAL1", "VAL2", "}", "}"])
    filename = sub_file_parser.parse_filename(src)
    assert filename == Path("test.db")


def test_parse_pattern_macros():
    src = iter(["MACRO1", ",", "MACRO2", "}", "{", "VAL1", "VAL2", "}", "}"])
    macros = sub_file_parser.parse_pattern_macros(src)
    assert macros == ["MACRO1", "MACRO2"]


def test_parse_pattern_values():
    src = iter(["VAL1", ",", "VAL2", "}", "}"])
    values = sub_file_parser.parse_pattern_values(src)
    assert values == ["VAL1", "VAL2"]


def test_parse_macro_value():
    src = iter(["MACRO1", "=", "VAL1", ",", "MACRO2", "=", "VAL2", "}", "}"])
    macros, values = sub_file_parser.parse_macro_value(src)
    assert macros == ["MACRO1", "MACRO2"]
    assert values == ["VAL1", "VAL2"]


def test_parse_substitution(example_substitution_file, example_substitution_file_content):

    def _check_sub_file(subs):
        assert len(subs) == 4

        assert subs[0].file == Path("TektronixAFG3K.template")
        assert list(subs[0].macros.keys()) == ["P", "R", "PORT"]
        assert list(subs[0].macros.values()) == ["TST:", "AFG3011", "AFG3K"]

        assert subs[1].file == Path("TektronixAFG3K.template")
        assert list(subs[1].macros.keys()) == ["P", "R", "PORT"]
        assert list(subs[1].macros.values()) == ["TST:", "AFG3011", "AFG3K2"]

        assert subs[2].file == Path("TektronixAFG3K_Output.template")
        assert list(subs[2].macros.keys()) == ["P", "R", "PORT", "OUTPUT_NUM"]
        assert list(subs[2].macros.values()) == ["TST:", "AFG3011:Output", "AFG3K", "1"]

        assert subs[3].file == Path("TektronixAFG3K_Source.template")
        assert list(subs[3].macros.keys()) == ["P", "R", "PORT", "SOURCE_NUM"]
        assert list(subs[3].macros.values()) == ["TST:", "AFG3011:Source", "AFG3K", "1"]

    _check_sub_file(sub_file_parser.load_substitution_file(example_substitution_file))
    _check_sub_file(sub_file_parser.parse_substitution(io.StringIO(example_substitution_file_content)))
