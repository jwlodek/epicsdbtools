"""Parser for EPICS database definition (.dbd) files.

Database definition files describe the structure of record types,
menus, device support, drivers, registrars, functions, variables,
and break tables used by an EPICS IOC.
"""

from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ..log import logger
from ..tokenizer import Tokenizer


class DbdException(Exception):
    def __init__(self, msg: str):
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


@dataclass
class MenuChoice:
    name: str
    string: str


@dataclass
class Menu:
    name: str
    choices: list[MenuChoice] = field(default_factory=list)


@dataclass
class FieldDefinition:
    name: str
    type: str
    attributes: OrderedDict[str, str] = field(default_factory=OrderedDict)


@dataclass
class RecordTypeDefinition:
    name: str
    fields: OrderedDict[str, FieldDefinition] = field(default_factory=OrderedDict)


@dataclass
class DeviceSupport:
    record_type: str
    link_type: str
    dset_name: str
    choice_string: str


@dataclass
class BreakTable:
    name: str
    entries: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class DatabaseDefinition:
    """Represents a parsed EPICS database definition (.dbd) file."""

    menus: OrderedDict[str, Menu] = field(default_factory=OrderedDict)
    record_types: OrderedDict[str, RecordTypeDefinition] = field(
        default_factory=OrderedDict
    )
    devices: list[DeviceSupport] = field(default_factory=list)
    drivers: list[str] = field(default_factory=list)
    registrars: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    variables: list[tuple[str, str | None]] = field(default_factory=list)
    break_tables: OrderedDict[str, BreakTable] = field(default_factory=OrderedDict)
    includes: list[str] = field(default_factory=list)


def _parse_pair(src: Iterator[str]) -> tuple[str | None, str | None]:
    """Parse '(name, "value")' to tuple (name, value)."""
    token = next(src)
    if token != "(":
        return None, None
    token = next(src)
    first = token
    token = next(src)
    if token == ")":
        return first, None
    elif token != ",":
        return None, None
    token = next(src)
    second = token
    token = next(src)
    if token != ")":
        return None, None
    return first, second


def _parse_menu(src: Iterator[str]) -> Menu:
    """Parse a menu definition block."""
    token = next(src)
    if token != "(":
        raise DbdException("Expected '(' after 'menu'")
    name = next(src)
    token = next(src)
    if token != ")":
        raise DbdException(f"Expected ')' after menu name '{name}'")

    menu = Menu(name=name)

    token = next(src)
    if token != "{":
        raise DbdException(f"Expected '{{' to open menu '{name}'")

    token = next(src)
    while token != "}":
        if token == "choice":
            choice_name, choice_string = _parse_pair(src)
            if choice_name is None or choice_string is None:
                raise DbdException(f"Invalid choice in menu '{name}'")
            menu.choices.append(MenuChoice(name=choice_name, string=choice_string))
        elif token == "include":
            # Some dbd files include other files inside menu blocks; skip the filename
            next(src)
        else:
            raise DbdException(
                f"Unexpected token '{token}' in menu '{name}'"
            )
        token = next(src)

    logger.debug(f"Parsed menu '{name}' with {len(menu.choices)} choices")
    return menu


def _parse_field_definition(src: Iterator[str]) -> FieldDefinition:
    """Parse a field definition within a record type."""
    field_name, field_type = _parse_pair(src)
    if field_name is None or field_type is None:
        raise DbdException("Invalid field definition")

    field_def = FieldDefinition(name=field_name, type=field_type)

    token = next(src)
    if token != "{":
        raise DbdException(f"Expected '{{' to open field '{field_name}'")

    token = next(src)
    while token != "}":
        # Field attributes like: asl(ASL0), initial("0"), etc.
        attr_name = token
        token = next(src)
        if token == "(":
            attr_value = next(src)
            token = next(src)
            if token != ")":
                raise DbdException(
                    f"Expected ')' after attribute value in field '{field_name}'"
                )
            field_def.attributes[attr_name] = attr_value
        else:
            # Attribute with no value (bare keyword)
            field_def.attributes[attr_name] = ""
            continue
        token = next(src)

    return field_def


def _parse_record_type(src: Iterator[str]) -> RecordTypeDefinition:
    """Parse a recordtype definition block."""
    token = next(src)
    if token != "(":
        raise DbdException("Expected '(' after 'recordtype'")
    name = next(src)
    token = next(src)
    if token != ")":
        raise DbdException(f"Expected ')' after recordtype name '{name}'")

    record_type = RecordTypeDefinition(name=name)

    token = next(src)
    if token != "{":
        raise DbdException(f"Expected '{{' to open recordtype '{name}'")

    token = next(src)
    while token != "}":
        if token == "field":
            field_def = _parse_field_definition(src)
            record_type.fields[field_def.name] = field_def
        elif token == "%":
            # C code include line (e.g., %#include "dbCommon.h")
            # The tokenizer will yield the rest as tokens; skip to next line
            # These are typically handled as bare tokens
            pass
        elif token == "include":
            next(src)
        else:
            raise DbdException(
                f"Unexpected token '{token}' in recordtype '{name}'"
            )
        token = next(src)

    logger.debug(
        f"Parsed recordtype '{name}' with {len(record_type.fields)} fields"
    )
    return record_type


def _parse_device(src: Iterator[str]) -> DeviceSupport:
    """Parse a device support definition."""
    token = next(src)
    if token != "(":
        raise DbdException("Expected '(' after 'device'")

    record_type = next(src)
    token = next(src)
    if token != ",":
        raise DbdException("Expected ',' after record type in device definition")

    link_type = next(src)
    token = next(src)
    if token != ",":
        raise DbdException("Expected ',' after link type in device definition")

    dset_name = next(src)
    token = next(src)
    if token != ",":
        raise DbdException("Expected ',' after dset name in device definition")

    choice_string = next(src)
    token = next(src)
    if token != ")":
        raise DbdException("Expected ')' to close device definition")

    logger.debug(f"Parsed device support: {record_type}, {dset_name}")
    return DeviceSupport(
        record_type=record_type,
        link_type=link_type,
        dset_name=dset_name,
        choice_string=choice_string,
    )


def _parse_breaktable(src: Iterator[str]) -> BreakTable:
    """Parse a break table definition."""
    token = next(src)
    if token != "(":
        raise DbdException("Expected '(' after 'breaktable'")
    name = next(src)
    token = next(src)
    if token != ")":
        raise DbdException(f"Expected ')' after breaktable name '{name}'")

    break_table = BreakTable(name=name)

    token = next(src)
    if token != "{":
        raise DbdException(f"Expected '{{' to open breaktable '{name}'")

    token = next(src)
    while token != "}":
        raw_value = token
        eng_value = next(src)
        break_table.entries.append((raw_value, eng_value))
        token = next(src)

    logger.debug(
        f"Parsed breaktable '{name}' with {len(break_table.entries)} entries"
    )
    return break_table


def _parse_single_arg(src: Iterator[str]) -> str:
    """Parse a single parenthesized argument like (name)."""
    token = next(src)
    if token != "(":
        raise DbdException("Expected '('")
    value = next(src)
    token = next(src)
    if token != ")":
        raise DbdException(f"Expected ')' after '{value}'")
    return value


def _parse_variable(src: Iterator[str]) -> tuple[str, str | None]:
    """Parse a variable definition: variable(name, type) or variable(name)."""
    token = next(src)
    if token != "(":
        raise DbdException("Expected '(' after 'variable'")
    name = next(src)
    token = next(src)
    if token == ")":
        return name, None
    elif token == ",":
        var_type = next(src)
        token = next(src)
        if token != ")":
            raise DbdException(f"Expected ')' after variable type for '{name}'")
        return name, var_type
    else:
        raise DbdException(f"Unexpected token '{token}' in variable definition")


def parse_dbd(src: Iterator[str]) -> DatabaseDefinition:
    """Parse tokens from a .dbd file into a DatabaseDefinition.

    :param src: Token iterator (from Tokenizer)
    :return: Parsed database definition
    """
    dbd = DatabaseDefinition()

    while True:
        try:
            token = next(src)
        except StopIteration:
            break

        if token == "menu":
            menu = _parse_menu(src)
            dbd.menus[menu.name] = menu
        elif token == "recordtype":
            record_type = _parse_record_type(src)
            dbd.record_types[record_type.name] = record_type
        elif token == "device":
            dbd.devices.append(_parse_device(src))
        elif token == "driver":
            dbd.drivers.append(_parse_single_arg(src))
        elif token == "registrar":
            dbd.registrars.append(_parse_single_arg(src))
        elif token == "function":
            dbd.functions.append(_parse_single_arg(src))
        elif token == "variable":
            dbd.variables.append(_parse_variable(src))
        elif token == "breaktable":
            bt = _parse_breaktable(src)
            dbd.break_tables[bt.name] = bt
        elif token == "include":
            filename = next(src)
            dbd.includes.append(filename)
            logger.debug(f"Recorded include: '{filename}'")
        else:
            raise DbdException(f"Unexpected top-level token: '{token}'")

    return dbd


def load_dbd_file(
    filename: Path | str,
    search_path: set[Path] | None = None,
) -> DatabaseDefinition:
    """Load and parse an EPICS database definition (.dbd) file.

    :param filename: Path to the .dbd file
    :param search_path: Optional set of directories to search for the file
    :return: Parsed DatabaseDefinition
    """
    if isinstance(filename, str):
        filename = Path(filename)

    if not filename.exists():
        if search_path:
            found = False
            for path in search_path:
                candidate = path / filename
                if candidate.exists():
                    filename = candidate
                    found = True
                    break
            if not found:
                raise FileNotFoundError(
                    f"Database definition file '{filename}' not found"
                )
        else:
            raise FileNotFoundError(
                f"Database definition file '{filename}' not found"
            )

    with open(filename) as fp:
        content = fp.read()

    src = iter(Tokenizer(StringIO(content), str(filename)))
    dbd = parse_dbd(src)

    logger.info(
        f"Loaded dbd file '{filename}': "
        f"{len(dbd.menus)} menus, "
        f"{len(dbd.record_types)} record types, "
        f"{len(dbd.devices)} devices"
    )

    return dbd
