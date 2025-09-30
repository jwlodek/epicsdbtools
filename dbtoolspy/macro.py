from __future__ import print_function

import re
import sys
from io import StringIO

from .tokenizer import tokenizer

Macros = re.compile('\$\(([^)=]+)(=([^)]*))?\)')

def expand_macros(source: str, macros: dict[str, str]) -> tuple[str, list[str]]:
    """
    >>> expand_macros('$(A) $(B) $(C=3)', {'A': '1'})
    ('1 $(B) 3', ['B'])
    """
    unmatched = set()

    def replace(matchobj):
        name = matchobj.group(1)
        default = matchobj.group(3)
        value =  macros.get(name)
        if value is None:
            if default is None:
                unmatched.add(name)
                return '$(%s)' % name 
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


def split_macros(macro_string: str) -> dict[str, str]:
    """
    >>> print(split_macros('a=1,b="2",c,d=\\'hello\\''))
    {'a': '1', 'b': '2', 'd': 'hello'}
    """
    src = tokenizer(StringIO(macro_string))
    
    macros = {}
    name = value = None
    for token in src:
        if token == '=':
            pass 
        elif token == ',':
            name = value = None
        else:
            if name:
                macros[name] = token
            else:
                name = token
       
    return macros


if __name__ == '__main__':
    import doctest
    doctest.testmod()
