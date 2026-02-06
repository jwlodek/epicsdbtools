import pytest
from epicsdbtools import macro as macro_tools


@pytest.mark.parametrize("input_string, expected_macros", [
    ("a=1,b=\"2\",c,d=\"hello\"", {"a": "1", "b": "2", "d": "hello"}),
    ("X=42,Y=\"valueY\",Z", {"X": "42", "Y": "valueY"}),
    ("param1=100,param2=200,param3=\"test\"", {"param1": "100", "param2": "200", "param3": "test"}),
    ("key1=\"val1\",key2=val2,key3", {"key1": "val1", "key2": "val2"}),
    ("singleMacro", {}),
])
def test_macro_split(input_string, expected_macros):
    assert macro_tools.macro_split(input_string) == expected_macros

@pytest.mark.parametrize("input_string, macro_defs, expected_output", [
    ("", {}, ("", [])),
    ("No macros here", {}, ("No macros here", [])),
    ("$(A) $(B) $(C=3)", {"A": "1"}, ("1 $(B) 3", ["B"])),
    ("$(X) and $(Y=default)", {"X": "valueX"}, ("valueX and default", [])),
    ("$(UNDEF)", {}, ("$(UNDEF)", ["UNDEF"])),
    ("Nested $(A=$(B=2))", {"B": "5"}, ("Nested 5", [])),
    ("Multiple $(A) and $(A=default)", {}, ("Multiple $(A) and default", ["A"])),
])
def test_macro_expand(input_string, macro_defs, expected_output):
    assert macro_tools.macro_expand(input_string, macro_defs) == expected_output
