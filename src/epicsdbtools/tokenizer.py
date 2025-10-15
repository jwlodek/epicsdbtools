import re
import sys

if sys.hexversion < 0x03000000:
    pass
else:
    pass

__all__ = ["tokenizer"]


# Partial excerpt from Python/Lib/tokenize.py
def group(*choices):
    return "(" + "|".join(choices) + ")"


Whitespace = r"(?P<whitespace>[ \f\t]*)"
Comment = r"(?P<comment>#[^\r\n]*)"
Special = "[,={}()]"
Bareword = r"[a-zA-Z0-9_\-+:./\\\[\]<>]+"
QuotedString = group(r"'[^\n'\\]*(?:\\.[^\n'\\]*)*'", r'"[^\n"\\]*(?:\\.[^\n"\\]*)*"')
Token = group(Comment, Special, Bareword, QuotedString, Whitespace)


class TokenException(Exception):
    def __init__(self, msg, filename, lineno, colno, line):
        self.msg = msg
        self.filename = filename
        self.lineno = lineno
        self.colno = colno
        self.line = line

    def __str__(self):
        repr = f"{self.filename}:{self.lineno}:{self.colno}: {self.colno} ({self.msg})"
        return repr


class tokenizer:
    """
    >>> io = StringIO('bareword "$(NAME=VALUE)" name=value "" {name} # comments')
    >>> for t in tokenizer(io):
    ...     print(t, end=' ')
    bareword $(NAME=VALUE) name = value  { name }
    >>> for t in tokenizer(StringIO('# this is a comment line')):
    ...     print(t, end=' ')
    """

    def __init__(self, instream, filename=None):
        self.instream = instream
        if filename is None:
            if hasattr(self.instream, "name"):
                self.filename = self.instream.name
            else:
                self.filename = "<...>"
        else:
            self.filename = filename
        self.lineno = 1

    def __iter__(self):
        return self.get_token()

    def get_token(self):
        self.lineno = 1
        for line in self.instream:
            if not line:
                break
            self.lineno += 1

            line = line.strip()
            if line.startswith("#"):
                continue

            pos, max = 0, len(line)
            while pos < max:
                m = re.compile(Token).match(line, pos)
                if m.start() == m.end():
                    raise TokenException(
                        f'Illegal char "{line[pos]}"',
                        self.filename,
                        self.lineno,
                        pos,
                        line,
                    )
                pos = m.end()
                token = m.group(0)
                if not m.group("whitespace") and not m.group("comment"):
                    if token[0] == token[-1] == '"':
                        yield token[1:-1]
                    elif token[0] == token[-1] == "'":
                        yield token[1:-1]
                    else:
                        yield token


if __name__ == "__main__":
    import doctest

    doctest.testmod()
