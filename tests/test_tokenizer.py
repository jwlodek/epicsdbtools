import pytest

from epicsdbtools import tokenizer
from io import StringIO
from pathlib import Path


@pytest.fixture
def tokenizer_factory():
    def _factory(input: Path| str) -> tokenizer.Tokenizer:
        if isinstance(input, Path):
            with open(input, "r") as fp:
                return tokenizer.Tokenizer(StringIO(fp.read()), filename=str(input))
        else:
            return tokenizer.Tokenizer(StringIO(input), filename="test_input.txt")
    return _factory


def test_tokenizer_mixed_line(tokenizer_factory):
    tokens = list(tokenizer_factory('bareword "$(NAME=VALUE)" name=value "" {name} # comments'))
    assert len(tokens) == 9
    assert tokens[0] == "bareword"
    assert tokens[1] == "$(NAME=VALUE)"
    assert tokens[2] == "name"
    assert tokens[3] == "="
    assert tokens[4] == "value"
    assert tokens[5] == ""
    assert tokens[6] == "{"
    assert tokens[7] == "name"
    assert tokens[8] == "}"


@pytest.mark.parametrize("input", [
    "# this is a comment line",
    "\n",
    "   \t  \n",
])
def test_tokenizer_with_no_expected_tokens(tokenizer_factory, input):
    tokens = list(tokenizer_factory(input))
    assert len(tokens) == 0  # No tokens should be produced


@pytest.mark.parametrize("trailing_open_bracket", [True, False])
def test_tokenizer_with_epics_record_signature(tokenizer_factory, trailing_open_bracket):
    input = "record(ai, \"$(PREFIX)$(NAME)\")" + (" {" if trailing_open_bracket else "")
    tokens = list(tokenizer_factory(input))
    expected_tokens = [
        "record", "(", "ai", ",", "$(PREFIX)$(NAME)", ")",
    ]
    if trailing_open_bracket:
        expected_tokens.append("{")
    assert tokens == expected_tokens


@pytest.mark.parametrize("input, expected_tokens", [
    ("field(DTYP, \"asynInt32\")", ["field", "(", "DTYP", ",", "asynInt32", ")"]),
    ("field(INP, \"@asyn($(PORT),0,1)TST_BI_ASYNINT32\")", ["field", "(", "INP", ",", "@asyn($(PORT),0,1)TST_BI_ASYNINT32", ")"]),
    ("field(OUT, \"@asyn($(PORT),0,1)TST_BO_ASYNINT32\")", ["field", "(", "OUT", ",", "@asyn($(PORT),0,1)TST_BO_ASYNINT32", ")"]),
    ("field(FLNK, \"XF:31ID1-ES{S:TEST}TEST\")", ["field", "(", "FLNK", ",", "XF:31ID1-ES{S:TEST}TEST", ")"]),
])
def test_tokenizer_epics_field_definition(tokenizer_factory, input, expected_tokens):
    tokens = list(tokenizer_factory(input))
    assert tokens == expected_tokens
