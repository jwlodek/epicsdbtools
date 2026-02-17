#!/usr/bin/env python

import os
from collections import OrderedDict
from collections.abc import Iterator
from enum import StrEnum
from io import StringIO
from pathlib import Path
from typing import Generic, TypeVar

from ..log import logger
from ..macro import macro_expand, macro_split
from ..tokenizer import Tokenizer


class RecordType(StrEnum):
    """
    Record types pulled from: https://epics-base.github.io/epics-base/recordrefmanual.html
    """

    AAI = "aai"  # Analog Array Input Record
    AAO = "aao"  # Analog Array Output Record
    AI = "ai"  # Analog Input Record
    AO = "ao"  # Analog Output Record
    ASUB = "aSub"  # Array Subroutine Record
    BI = "bi"  # Binary Input Record
    BO = "bo"  # Binary Output Record
    CALCOUT = "calcout"  # Calculation Output Record
    CALC = "calc"  # Calculation Record
    COMPRESS = "compress"  # Compression Record
    DFANOUT = "dfanout"  # Data Fanout Record
    EVENT = "event"  # Event Record
    FANOUT = "fanout"  # Fanout Record
    HISTOGRAM = "histogram"  # Histogram Record
    INT64IN = "int64in"  # 64bit Integer Input Record
    INT64OUT = "int64out"  # 64bit Integer Output Record
    LONGIN = "longin"  # Long Input Record
    LONGOUT = "longout"  # Long Output Record
    LSI = "lsi"  # Long String Input Record
    LSO = "lso"  # Long String Output Record
    MBBIDIRECT = "mbbiDirect"  # Multi-Bit Binary Input Direct Record
    MBBI = "mbbi"  # Multi-Bit Binary Input Record
    MBBODIRECT = "mbboDirect"  # Multi-Bit Binary Output Direct Record
    MBBO = "mbbo"  # Multi-Bit Binary Output Record
    PERMISSIVE = "permissive"  # Permissive Record
    PRINF = "prinf"  # Printf Record
    SEL = "sel"  # Select Record
    SEQ = "seq"  # Sequence Record
    STATE = "state"  # State Record
    STRINGIN = "stringin"  # String Input Record
    STRINGOUT = "stringout"  # String Output Record
    SUBARRAY = "subArray"  # Sub-Array Record
    SUB = "sub"  # Subroutine Record
    WAVEFORM = "waveform"  # Waveform Record


RecordTypeT = TypeVar("RecordTypeT", bound=RecordType)


class LoadIncludesStrategy(StrEnum):
    LOAD_INTO_SELF = "load_into_self"
    LOAD_INTO_NEW = "load_into_new"
    IGNORE = "ignore"


class DatabaseException(Exception):
    def __init__(self, msg: str):
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


class Record(Generic[RecordTypeT]):
    def __init__(self, name: str, rtype: RecordTypeT):
        self.name = name
        self.rtype = rtype
        self.infos: OrderedDict[str, str] = OrderedDict()
        self.fields: OrderedDict[str, str | int] = OrderedDict()
        self.aliases: list[str] = []

    def __repr__(self) -> str:
        repr = f'record ({self.rtype.value}, "{self.name}")' + " {\n"
        for field, value in self.fields.items():
            repr += f'    field({field:4}, "{value}")\n'
        for field, value in self.infos.items():
            repr += f'    info({field}, "{value}")\n'
        for alias in self.aliases:
            repr += f"    alias({alias})\n"
        repr += "}\n"
        return repr

    def merge(self, another: "Record") -> None:
        """
        Merge fields, infos, aliases from another record instance.
        """
        if self.rtype != another.rtype or self.name != another.name:
            raise DatabaseException(
                f"Cannot merge records with different types or names: "
                f"'{self.name}' ({self.rtype}) vs '{another.name}' ({another.rtype})"
            )

        self.fields.update(another.fields)
        self.infos.update(another.infos)
        self.aliases.extend(another.aliases)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Record):
            return False
        return (
            self.name == other.name
            and self.rtype == other.rtype
            and self.fields == other.fields
            and self.infos == other.infos
            and self.aliases == other.aliases
        )


class Database(OrderedDict[str, Record]):
    def __init__(self):
        super().__init__()
        self._included_templates: dict[str, Database | None] = {}

    def __repr__(self) -> str:
        msg = []
        for record in self.values():
            msg.append(repr(record))
        return "\n".join(msg)

    def add_record(self, record: "Record[RecordTypeT]") -> None:

        record_existed = self.get(record.name)
        if record_existed:
            if record_existed.rtype != record.rtype:
                raise DatabaseException(
                    f"Reappearing record '{record.name}' with"
                    f" conflicting record type '{record.rtype}'"
                )
            else:
                logger.warning(f"Merging into existing record: '{record.name}'")
                record_existed.merge(record)
        else:
            logger.debug(f"Adding record: '{record.name}'")
            self[record.name] = record

    def merge(self, database: "Database") -> None:
        """
        Merge records from another Database instance
        """
        for record in database.values():
            self.add_record(record)

    def add_included_template(self, template: str, database: "Database | None") -> None:
        self._included_templates[template] = database

    def get_included_templates(self) -> dict[str, "Database | None"]:
        return self._included_templates

    def get_included_template_filepaths(self) -> list[str]:
        return list(self._included_templates.keys())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Database):
            return False

        for record_name in self.keys():
            if record_name not in other.keys() or other.get(record_name) != self.get(
                record_name
            ):
                return False
        return True


def parse_pair(src: Iterator[str]) -> tuple[str | None, str | None]:
    """
    parse '(field, "value")' definition to tuple (field, value)
    """
    token = next(src)
    if token != "(":
        return None, None
    token = next(src)
    field = token
    token = next(src)
    if token == ")":
        return field, None
    elif token != ",":
        return None, None
    token = next(src)
    value = token
    token = next(src)
    if token != ")":
        return None, None
    return field, value


def parse_record(src: Iterator[str]) -> Record:
    """
    :param iter src: token generator
    """

    rtype, name = parse_pair(src)
    if name is None or rtype is None:
        raise DatabaseException(
            f"Failed to parse record signature! Name: '{name}', Rtype: '{rtype}'"
        )
    elif rtype not in RecordType:
        raise DatabaseException(f"Invalid record type '{rtype}' for record '{name}'")

    record = Record(name=name, rtype=RecordType[rtype.upper()])

    token = next(src)
    while True:
        if token == "}":
            break
        elif token in ("field", "info", "alias"):
            key, value = parse_pair(src)
            if token in ("field", "info") and key and value:
                logger.debug(f"Setting {token} '{key}' for record '{record.name}'")
                getattr(record, f"{token}s")[key] = value
            elif token == "alias" and key:
                record.aliases.append(key)
            else:
                logger.warning(f"Invalid {token} definition for record '{record.name}'")

        token = next(src)

    logger.debug(f"Parsed record: '{record.name}'")
    return record


def find_database_file(
    filename: Path | str, search_path: set[Path] | None = None
) -> Path:
    if isinstance(filename, str):
        filename = Path(filename)

    if filename.exists() and filename.is_file():
        return filename.absolute()
    elif not filename.is_absolute() and search_path is not None:
        for path in search_path:
            database_file = path / filename
            if database_file.exists() and database_file.is_file():
                return database_file.absolute()

    raise FileNotFoundError(
        f"Database file '{filename}' not found given search path {search_path}"
    )


def load_database_file(
    filename: Path | str,
    macros: dict[str, str] | None = None,
    search_path: set[Path] | None = None,
    load_includes_strategy: LoadIncludesStrategy = LoadIncludesStrategy.LOAD_INTO_SELF,
    allow_unmatched_macros: bool = True,
) -> Database:
    """
    :param str filename: EPICS database filename
    :return: list of record dict
    :rtype: list of dicts
    """

    filename = find_database_file(filename, search_path)

    database = Database()

    # read line by line and expand macros
    lineno = 1
    lines = []
    failed = False
    with open(filename) as fp:
        for line in fp.readlines():
            if macros is not None:
                expanded, unmatched = macro_expand(line, macros)
                if unmatched:
                    msg = f"{filename}:{lineno}: macro(s) {unmatched} undefined"
                    if not allow_unmatched_macros:
                        failed = True
                        logger.error(msg)
                    else:
                        logger.debug(msg)
                else:
                    lines.append(expanded)
            else:
                lines.append(line)
            lineno += 1

    if failed:
        raise DatabaseException(
            f"Failed to load database file '{filename}' due to undefined macros"
        )

    # parse record instances
    src = iter(Tokenizer(StringIO("".join(lines)), str(filename)))
    while True:
        try:
            token = next(src)
        except StopIteration:
            break

        if token == "record" or token == "grecord":
            database.add_record(parse_record(src))
        elif token == "alias":
            record_name, alias_name = parse_pair(src)
            if record_name is None or alias_name is None:
                logger.error("Failed to parse record alias")
            else:
                logger.debug(f"Adding alias '{alias_name}' for record '{record_name}'")
                database[record_name].aliases.append(alias_name)
        elif token == "include":
            inclusion = next(src)
            # Add placeholder entry for included file even if we don't end up loading it
            database.add_included_template(inclusion, None)

            # recursively load included file
            if load_includes_strategy != LoadIncludesStrategy.IGNORE:
                extended_search_path = search_path if search_path else set()
                extended_search_path.add(filename.parent)
                included_db = load_database_file(
                    Path(inclusion),
                    macros,
                    extended_search_path,
                    load_includes_strategy,
                    allow_unmatched_macros,
                )
                if load_includes_strategy == LoadIncludesStrategy.LOAD_INTO_SELF:
                    logger.debug(
                        f"Merging database from '{inclusion}' into '{filename}'"
                    )
                    database.merge(included_db)
                elif load_includes_strategy == LoadIncludesStrategy.LOAD_INTO_NEW:
                    logger.debug(
                        f"Adding database from '{inclusion}' as a separate template"
                    )
                    database.add_included_template(inclusion, included_db)
        else:
            raise DatabaseException(
                "Invalid token encountered while parsing database file"
            )

    logger.info(f"Loaded {len(database)} unique records from '{filename}'")

    return database


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--macro", help="macro substitution")
    parser.add_argument(
        "-I",
        action="append",
        dest="includes",
        default=[],
        help="template include paths",
    )
    parser.add_argument("--encoding", default="utf8", help="files encoding")
    parser.add_argument(dest="database_files", nargs="+", help="database files")
    args = parser.parse_args()

    macros = None
    if args.macro:
        macros = macro_split(args.macro)

    for file in args.database_files:
        if os.path.exists(file):
            database = load_database_file(file, macros, args.includes, args.encoding)
            print(database)
