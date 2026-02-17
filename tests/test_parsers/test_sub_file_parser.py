import pytest

from pathlib import Path
from epicsdbtools.parsers import substitution as sub_file_parser
import io

@pytest.fixture
def example_substitution_file_content():
    return """
# global macros
global {
    AA = aa
    BB = bb
}

file test.template {
pattern
{ P        R  }
{ MTEST:   AO1}
{ MTEST:   AO2}
}

file test.template {
# file global macros
global {
    P = MTEST:
}
# local overrides global
{ R = AO3, AA = AA }
{ R = AO4  BB = BB }

}
"""

@pytest.fixture
def example_substitution_file(example_substitution_file_content, tmp_path):

    sub_file_path = tmp_path / "test.sub"
    with open(sub_file_path, "w") as fp:
        fp.write(example_substitution_file_content)

    return sub_file_path




def test_parse_filename(tokenizer_factory):
    src = iter(tokenizer_factory("file test.db { pattern { MACRO1, MACRO2 }{VAL1, VAL2}}"))
    filename = sub_file_parser.parse_filename(src)
    assert filename == Path("test.db")


def test_parse_pattern_macros(tokenizer_factory):
    src = iter(tokenizer_factory("MACRO1, MACRO2 }{VAL1, VAL2}}"))
    macros = sub_file_parser.parse_pattern_macros(src)
    assert macros == ["MACRO1", "MACRO2"]


def test_parse_pattern_values(tokenizer_factory):
    src = iter(tokenizer_factory("VAL1, VAL2}}"))
    values = sub_file_parser.parse_pattern_values(src)
    assert values == ["VAL1", "VAL2"]


def test_parse_macro_value(tokenizer_factory):
    src = iter(tokenizer_factory("MACRO1 = VAL1, MACRO2 = VAL2 }}"))
    macros, values = sub_file_parser.parse_macro_value(src)
    assert macros == ["MACRO1", "MACRO2"]
    assert values == ["VAL1", "VAL2"]


def test_parse_substitution(example_substitution_file, example_substitution_file_content):

    def _check_sub_file(subs):
        assert len(subs) == 4

        assert subs[0].file == Path("test.template")
        assert list(subs[0].macros.keys()) == ["AA", "BB", "P", "R"]
        assert list(subs[0].macros.values()) == ["aa", "bb", "MTEST:", "AO1"]

        assert subs[1].file == Path("test.template")
        assert list(subs[1].macros.keys()) == ["AA", "BB", "P", "R"]
        assert list(subs[1].macros.values()) == ["aa", "bb", "MTEST:", "AO2"]

        assert subs[2].file == Path("test.template")
        assert list(subs[2].macros.keys()) == ["AA", "BB", "P", "R"]
        assert list(subs[2].macros.values()) == ["AA", "bb", "MTEST:", "AO3"]

        assert subs[3].file == Path("test.template")
        assert list(subs[3].macros.keys()) == ["AA", "BB", "P", "R"]
        assert list(subs[3].macros.values()) == ["aa", "BB", "MTEST:", "AO4"]

    _check_sub_file(sub_file_parser.load_substitution_file(example_substitution_file))
    _check_sub_file(sub_file_parser.parse_substitution(io.StringIO(example_substitution_file_content)))
