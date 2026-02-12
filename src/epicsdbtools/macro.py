import re
from io import StringIO
from re import Pattern

from .tokenizer import Tokenizer

MACRO_REGEX: Pattern = re.compile(r"\$\(([^)=]+)(=([^)]*))?\)")


def macro_expand(source: str, macros: dict[str, str]) -> tuple[str, list[str]]:
    """
    >>> macro_expand('$(A) $(B) $(C=3)', {'A': '1'})
    ('1 $(B) 3', ['B'])
    """
    unmatched = set()

    def replace(matchobj: re.Match) -> str:
        name = matchobj.group(1)
        default = matchobj.group(3)
        value = macros.get(name)
        if value is None:
            if default is None:
                unmatched.add(name)
                return f"$({name})"
            else:
                return default
        else:
            return value

    while True:
        expanded = MACRO_REGEX.sub(replace, source)
        if expanded == source:
            break
        source = expanded

    return expanded, list(unmatched)


def macro_split(macro_string: str) -> dict[str, str]:
    """
    >>> print(macro_split('a=1,b="2",c,d=\\'hello\\''))
    {'a': '1', 'b': '2', 'd': 'hello'}
    """
    src = Tokenizer(StringIO(macro_string))

    macros = {}
    name = None
    for token in src:
        if token == "=":
            pass
        elif token == ",":
            name = None
        else:
            if name:
                macros[name] = token
            else:
                name = token

    return macros
