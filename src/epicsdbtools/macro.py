import re
import sys

if sys.hexversion < 0x03000000:
    from StringIO import StringIO
else:
    from io import StringIO

from .tokenizer import tokenizer

Macros = re.compile(r"\$\(([^)=]+)(=([^)]*))?\)")


def macExpand(source, macros):
    """
    >>> macExpand('$(A) $(B) $(C=3)', {'A': '1'})
    ('1 $(B) 3', ['B'])
    """
    unmatched = set()

    def replace(matchobj):
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
        expanded = Macros.sub(replace, source)
        if expanded == source:
            break
        source = expanded

    return expanded, list(unmatched)


def macSplit(macro_string):
    """
    >>> print(macSplit('a=1,b="2",c,d=\\'hello\\''))
    {'a': '1', 'b': '2', 'd': 'hello'}
    """
    src = tokenizer(StringIO(macro_string))

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


if __name__ == "__main__":
    import doctest

    doctest.testmod()
