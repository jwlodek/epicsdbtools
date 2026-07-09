"""Parser for EPICS StreamDevice protocol (.proto) files.

StreamDevice protocol files define communication protocols between EPICS IOCs and
hardware devices. The file format supports:
- Global variable assignments (e.g. ``Terminator = CR LF;``)
- Protocol definitions with commands (out, in, wait, event, exec, disconnect, connect)
- Handler blocks (@init, @mismatch, @writetimeout, @readtimeout, @replytimeout)
- Protocol references (calling other protocols)
- Parameterized protocols with named or positional (``$1``) parameters
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ..log import logger

# Regex matching StreamDevice format converters: %[-+ 0#]*[width][.prec]conversion
_FORMAT_CONVERTER_RE = re.compile(
    r"%(?P<skip>\*)?(?P<flags>[-+ 0#]*)(?P<width>\d*)"
    r"(?:\.(?P<precision>\d+))?(?P<conversion>[diouxXeEfFgGsScCbBrR])"
)

# Regex matching StreamDevice enum format converters: %{choice0|choice1|...}
_ENUM_CONVERTER_RE = re.compile(r"%\{(?P<choices>[^}]+)\}")

# Regex matching parameter references: \$NAME, \${NAME}, \$1, \${1} (inside quotes)
# and $NAME, ${NAME}, $1, ${1} (outside quotes)
_PARAM_REF_RE = re.compile(r"\\?\$\{?([a-zA-Z_][a-zA-Z0-9_]*|\d+)\}?")


@dataclass
class FormatConverter:
    """A parsed StreamDevice format converter (e.g. ``%f``, ``%02d``, ``%{OFF|ON}``).

    Attributes
    ----------
    conversion : str
        The conversion character (d, f, s, e, etc.), or ``'enum'`` for ``%{...}``.
    width : int | None
        Field width, if specified.
    precision : int | None
        Precision, if specified.
    flags : str
        Format flags (-, +, 0, #, space).
    skip : bool
        Whether this is a skip converter (``%*``), meaning the value is discarded.
    enum_choices : list[str] | None
        For enum converters (``%{OFF|ON}``), the list of choices.
    """

    conversion: str
    width: int | None = None
    precision: int | None = None
    flags: str = ""
    skip: bool = False
    enum_choices: list[str] | None = None

    @property
    def value_type(self) -> type:
        """Python type corresponding to the format conversion.

        Returns
        -------
        type
            The Python type: int, float, str, or bytes.
        """
        if self.conversion == "enum":
            return int
        return _CONVERSION_TYPES.get(self.conversion.lower(), bytes)

    def __str__(self) -> str:
        if self.conversion == "enum" and self.enum_choices is not None:
            return "%{" + "|".join(self.enum_choices) + "}"
        s = "%"
        if self.skip:
            s += "*"
        s += self.flags
        if self.width is not None:
            s += str(self.width)
        if self.precision is not None:
            s += f".{self.precision}"
        s += self.conversion
        return s


_CONVERSION_TYPES: dict[str, type] = {
    "d": int,
    "i": int,
    "o": int,
    "u": int,
    "x": int,
    "e": float,
    "f": float,
    "g": float,
    "s": str,
    "c": str,
    "b": bytes,
    "r": bytes,
}


@dataclass
class ProtocolCommand:
    """A single command within a protocol definition.

    Attributes
    ----------
    name : str
        The command type (out, in, wait, event, exec, disconnect, connect).
    argument : str
        The raw argument string for the command.
    """

    name: str
    argument: str

    @property
    def format_string(self) -> str | None:
        """The quoted format string from the argument, or None if not a string command.

        Returns
        -------
        str | None
            The format string content (without quotes), or None.
        """
        m = re.search(r'"((?:[^"\\]|\\.)*)"', self.argument)
        return m.group(1) if m else None

    @property
    def converters(self) -> list[FormatConverter]:
        """Extract all format converters from the command's format string.

        Returns
        -------
        list[FormatConverter]
            Parsed format converters found in the format string, including
            enum converters like ``%{OFF|ON}``.
        """
        fmt = self.format_string
        if fmt is None:
            return []
        result: list[tuple[int, FormatConverter]] = []
        for m in _FORMAT_CONVERTER_RE.finditer(fmt):
            result.append((m.start(), FormatConverter(
                conversion=m.group("conversion"),
                width=int(m.group("width")) if m.group("width") else None,
                precision=int(m.group("precision")) if m.group("precision") else None,
                flags=m.group("flags"),
                skip=m.group("skip") is not None,
            )))
        for m in _ENUM_CONVERTER_RE.finditer(fmt):
            choices = [c.strip() for c in m.group("choices").split("|")]
            result.append((m.start(), FormatConverter(
                conversion="enum",
                enum_choices=choices,
            )))
        # Return in order of appearance
        result.sort(key=lambda x: x[0])
        return [conv for _, conv in result]

    @property
    def parameter_refs(self) -> list[str]:
        """Extract parameter references ($NAME or $1) from the format string.

        Returns
        -------
        list[str]
            Referenced parameter names or positional indices as strings.
        """
        fmt = self.format_string
        if fmt is None:
            return []
        return _PARAM_REF_RE.findall(fmt)


@dataclass
class ProtocolHandler:
    """A handler block within a protocol (e.g. @init, @mismatch).

    Attributes
    ----------
    name : str
        The handler name (init, mismatch, writetimeout, readtimeout, replytimeout).
    commands : list[ProtocolCommand]
        The commands within the handler block.
    """

    name: str
    commands: list[ProtocolCommand] = field(default_factory=list)


@dataclass
class Protocol:
    """A single protocol definition.

    Attributes
    ----------
    name : str
        The protocol name.
    parameters : list[str]
        Inferred positional parameter indices (e.g. ['1', '2']) based on
        ``$1`` ... ``$9`` references found in the protocol body.
    commands : list[ProtocolCommand]
        The commands in the protocol body.
    handlers : list[ProtocolHandler]
        Handler blocks (e.g. @init).
    variables : dict[str, str]
        Protocol-local variable overrides.
    """

    name: str
    parameters: list[str] = field(default_factory=list)
    commands: list[ProtocolCommand] = field(default_factory=list)
    handlers: list[ProtocolHandler] = field(default_factory=list)
    variables: dict[str, str] = field(default_factory=dict)

    @property
    def num_parameters(self) -> int:
        """Number of parameters this protocol expects.

        Returns
        -------
        int
            The parameter count.
        """
        return len(self.parameters)

    @property
    def out_commands(self) -> list[ProtocolCommand]:
        """All ``out`` commands in this protocol.

        Returns
        -------
        list[ProtocolCommand]
            The output commands.
        """
        return [c for c in self.commands if c.name == "out"]

    @property
    def in_commands(self) -> list[ProtocolCommand]:
        """All ``in`` commands in this protocol.

        Returns
        -------
        list[ProtocolCommand]
            The input commands.
        """
        return [c for c in self.commands if c.name == "in"]

    @property
    def out_format(self) -> str | None:
        """The format string of the first ``out`` command, or None.

        Returns
        -------
        str | None
            The output format string.
        """
        cmds = self.out_commands
        return cmds[0].format_string if cmds else None

    @property
    def in_format(self) -> str | None:
        """The format string of the first ``in`` command, or None.

        Returns
        -------
        str | None
            The input format string.
        """
        cmds = self.in_commands
        return cmds[0].format_string if cmds else None

    @property
    def out_converters(self) -> list[FormatConverter]:
        """Format converters from the first ``out`` command.

        Returns
        -------
        list[FormatConverter]
            The output format converters.
        """
        cmds = self.out_commands
        return cmds[0].converters if cmds else []

    @property
    def in_converters(self) -> list[FormatConverter]:
        """Format converters from the first ``in`` command.

        Returns
        -------
        list[FormatConverter]
            The input format converters.
        """
        cmds = self.in_commands
        return cmds[0].converters if cmds else []


@dataclass
class ProtocolFile:
    """Parsed representation of a StreamDevice protocol file.

    Attributes
    ----------
    variables : dict[str, str]
        Global variable assignments.
    protocols : list[Protocol]
        Protocol definitions in the file.
    """

    variables: dict[str, str] = field(default_factory=dict)
    protocols: list[Protocol] = field(default_factory=list)

    def get_protocol(self, name: str) -> Protocol | None:
        """Look up a protocol by name.

        Parameters
        ----------
        name : str
            The protocol name to search for.

        Returns
        -------
        Protocol | None
            The matching protocol, or None if not found.
        """
        for proto in self.protocols:
            if proto.name == name:
                return proto
        return None


# StreamDevice built-in protocol commands
_COMMAND_NAMES = {"out", "in", "wait", "event", "exec", "disconnect", "connect"}

# Known system variables
_SYSTEM_VARIABLES = {
    "Terminator",
    "InTerminator",
    "OutTerminator",
    "MaxInput",
    "Separator",
    "ExtraInput",
    "ReadTimeout",
    "WriteTimeout",
    "ReplyTimeout",
    "LockTimeout",
    "PollPeriod",
}

# Regex for tokenizing protocol files
_COMMENT_RE = re.compile(r"#.*$")
_STRING_RE = re.compile(r"""(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")
_WORD_RE = re.compile(r"[a-zA-Z_$%][a-zA-Z0-9_.$%]*")
_NUMBER_RE = re.compile(r"\d+")
_SPECIAL_RE = re.compile(r"[{}();,=@]")
_WHITESPACE_RE = re.compile(r"\s+")


def _tokenize(source: str) -> list[tuple[str, str]]:
    """Tokenize a protocol file into (type, value) pairs.

    Token types: 'string', 'word', 'number', 'special', 'eof'
    """
    tokens: list[tuple[str, str]] = []
    pos = 0
    length = len(source)

    while pos < length:
        # Skip whitespace
        m = _WHITESPACE_RE.match(source, pos)
        if m:
            pos = m.end()
            continue

        # Skip comments
        m = _COMMENT_RE.match(source, pos)
        if m:
            pos = m.end()
            continue

        # Quoted strings
        m = _STRING_RE.match(source, pos)
        if m:
            # Strip quotes and store content
            raw = m.group(0)
            tokens.append(("string", raw[1:-1]))
            pos = m.end()
            continue

        # Special characters
        m = _SPECIAL_RE.match(source, pos)
        if m:
            tokens.append(("special", m.group(0)))
            pos = m.end()
            continue

        # Words/identifiers
        m = _WORD_RE.match(source, pos)
        if m:
            tokens.append(("word", m.group(0)))
            pos = m.end()
            continue

        # Numbers
        m = _NUMBER_RE.match(source, pos)
        if m:
            tokens.append(("number", m.group(0)))
            pos = m.end()
            continue

        # Unknown character - skip
        pos += 1

    tokens.append(("eof", ""))
    return tokens


class _Parser:
    """Recursive descent parser for StreamDevice protocol files."""

    def __init__(self, tokens: list[tuple[str, str]]):
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> tuple[str, str]:
        return self._tokens[self._pos]

    def _advance(self) -> tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, ttype: str, value: str | None = None) -> tuple[str, str]:
        tok = self._advance()
        if tok[0] != ttype:
            raise ProtoParseError(
                f"Expected token type '{ttype}' but got '{tok[0]}' ('{tok[1]}')"
            )
        if value is not None and tok[1] != value:
            raise ProtoParseError(
                f"Expected '{value}' but got '{tok[1]}'"
            )
        return tok

    def _at_end(self) -> bool:
        return self._peek()[0] == "eof"

    def parse(self) -> ProtocolFile:
        """Parse the token stream into a ProtocolFile."""
        proto_file = ProtocolFile()

        while not self._at_end():
            ttype, value = self._peek()

            if ttype == "special" and value == ";":
                # Stray semicolons
                self._advance()
                continue

            if ttype != "word":
                self._advance()
                continue

            # Look ahead to determine if this is a variable assignment or protocol
            name = value
            self._advance()

            next_type, next_value = self._peek()

            if next_type == "special" and next_value == "=":
                # Variable assignment: Name = value ;
                self._advance()  # consume '='
                var_value = self._parse_variable_value()
                proto_file.variables[name] = var_value
            elif next_type == "special" and next_value == "{":
                # Protocol definition
                self._advance()  # consume '{'
                protocol = self._parse_protocol_body(name)
                proto_file.protocols.append(protocol)
            else:
                # Unknown top-level construct, skip
                continue

        return proto_file

    def _parse_variable_value(self) -> str:
        """Parse the value portion of a variable assignment until ';'."""
        parts: list[str] = []
        while not self._at_end():
            ttype, value = self._peek()
            if ttype == "special" and value == ";":
                self._advance()
                break
            elif ttype == "special" and value == "{":
                # Hit next block - the semicolon was omitted
                break
            parts.append(value)
            self._advance()
        return " ".join(parts)

    def _parse_protocol_body(self, name: str) -> Protocol:
        """Parse the body of a protocol definition until '}'."""
        protocol = Protocol(name=name)

        while not self._at_end():
            ttype, value = self._peek()

            if ttype == "special" and value == "}":
                self._advance()
                break

            if ttype == "special" and value == ";":
                self._advance()
                continue

            if ttype == "special" and value == "@":
                # Handler block
                self._advance()
                handler = self._parse_handler()
                protocol.handlers.append(handler)
                continue

            if ttype != "word" and ttype != "number":
                self._advance()
                continue

            # Determine if command or variable assignment
            word = value
            self._advance()

            next_type, next_value = self._peek()

            if next_type == "special" and next_value == "=":
                # Variable assignment within protocol
                self._advance()  # consume '='
                var_value = self._parse_variable_value()
                protocol.variables[word] = var_value
            elif word.lower() in _COMMAND_NAMES:
                # Protocol command
                arg = self._parse_command_argument()
                cmd = ProtocolCommand(
                    name=word.lower(), argument=arg
                )
                protocol.commands.append(cmd)
            else:
                # Could be a protocol reference (calling another protocol)
                arg = self._parse_command_argument()
                cmd = ProtocolCommand(name=word, argument=arg)
                protocol.commands.append(cmd)

        # Infer positional parameters from $1..$9 references
        _infer_positional_params(protocol)

        return protocol

    def _parse_handler(self) -> ProtocolHandler:
        """Parse a handler block: @name { commands }."""
        _, handler_name = self._advance()  # handler name

        handler = ProtocolHandler(name=handler_name)

        # Expect opening brace
        next_type, next_value = self._peek()
        if next_type == "special" and next_value == "{":
            self._advance()
        else:
            return handler

        while not self._at_end():
            ttype, value = self._peek()

            if ttype == "special" and value == "}":
                self._advance()
                break

            if ttype == "special" and value == ";":
                self._advance()
                continue

            if ttype != "word" and ttype != "number":
                self._advance()
                continue

            word = value
            self._advance()

            next_type, next_value = self._peek()

            if next_type == "special" and next_value == "=":
                self._advance()
                # Skip variable value in handler
                self._parse_variable_value()
            elif word.lower() in _COMMAND_NAMES:
                arg = self._parse_command_argument()
                cmd = ProtocolCommand(
                    name=word.lower(), argument=arg
                )
                handler.commands.append(cmd)
            else:
                arg = self._parse_command_argument()
                cmd = ProtocolCommand(name=word, argument=arg)
                handler.commands.append(cmd)

        return handler

    def _parse_command_argument(self) -> str:
        """Parse the argument to a command until ';' or '}'."""
        parts: list[str] = []
        while not self._at_end():
            ttype, value = self._peek()
            if ttype == "special" and value == ";":
                self._advance()
                break
            elif ttype == "special" and value == "}":
                # Don't consume - let the caller handle it
                break
            elif ttype == "string":
                parts.append(f'"{value}"')
                self._advance()
            else:
                parts.append(value)
                self._advance()
        return " ".join(parts)


def _infer_positional_params(protocol: Protocol) -> None:
    """Detect positional parameter references and populate parameters.

    Handles both ``$1`` (outside quotes) and ``\\$1`` (inside quotes) styles,
    as well as ``${1}`` and ``\\${1}`` variants.
    """
    max_index = 0
    # Matches $1, ${1}, \$1, \${1}
    positional_re = re.compile(r"\\?\$\{?(\d+)\}?")
    for cmd in protocol.commands:
        fmt = cmd.format_string
        if fmt:
            for m in positional_re.finditer(fmt):
                idx = int(m.group(1))
                if idx > 0:
                    max_index = max(max_index, idx)
        # Also check raw argument for unquoted $1 references
        for m in positional_re.finditer(cmd.argument):
            idx = int(m.group(1))
            if idx > 0:
                max_index = max(max_index, idx)
    for handler in protocol.handlers:
        for cmd in handler.commands:
            fmt = cmd.format_string
            if fmt:
                for m in positional_re.finditer(fmt):
                    idx = int(m.group(1))
                    if idx > 0:
                        max_index = max(max_index, idx)
            for m in positional_re.finditer(cmd.argument):
                idx = int(m.group(1))
                if idx > 0:
                    max_index = max(max_index, idx)
    if max_index > 0:
        protocol.parameters = [str(i) for i in range(1, max_index + 1)]


class ProtoParseError(Exception):
    """Raised when a protocol file cannot be parsed."""

    pass


def parse_protocol(source: str | StringIO) -> ProtocolFile:
    """Parse StreamDevice protocol file content into a ProtocolFile.

    Parameters
    ----------
    source : str | StringIO
        The protocol file content as a string or StringIO.

    Returns
    -------
    ProtocolFile
        The parsed variables and protocols.

    Raises
    ------
    ProtoParseError
        If the file cannot be parsed.
    """
    if isinstance(source, StringIO):
        text = source.read()
    else:
        text = source

    tokens = _tokenize(text)
    parser = _Parser(tokens)
    return parser.parse()


def load_protocol_file(filepath: str | Path) -> ProtocolFile:
    """Load and parse a StreamDevice protocol file.

    Parameters
    ----------
    filepath : str | Path
        Path to the .proto file.

    Returns
    -------
    ProtocolFile
        The parsed variables and protocols.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ProtoParseError
        If the file cannot be parsed.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Protocol file not found: {filepath}")

    logger.info(f"Loading protocol file: {filepath}")
    text = filepath.read_text()
    return parse_protocol(text)
