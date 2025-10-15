#!/usr/bin/env python

import os
from collections import OrderedDict
from collections.abc import Iterator
from enum import Enum
from io import StringIO
from pathlib import Path

from .log import logger
from .macro import macro_expand, macro_split
from .tokenizer import Tokenizer


class LoadIncludesStrategy(str, Enum):
    LOAD_INTO_SELF = "load_into_self"
    LOAD_INTO_NEW = "load_into_new"
    IGNORE = "ignore"


class DatabaseException(Exception):
    def __init__(self, msg: str):
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


class Record:
    def __init__(self):
        self.name: str | None = None
        self.rtyp: str | None = None
        self.infos: OrderedDict[str, str] = OrderedDict()
        self.fields: OrderedDict[str, str] = OrderedDict()
        self.aliases: list[tuple[str, str | None]] = []

    def __bool__(self) -> bool:
        return self.name is not None and self.rtyp is not None

    def __repr__(self) -> str:
        repr = f'record ({self.rtyp}, "{self.name}")\n'
        repr += "{\n"
        for field, value in self.fields.items():
            repr += f'    field({field:4}, "{value}")\n'
        for field, value in self.infos.items():
            repr += f'    info({field}, "{value}")\n'
        for alias in self.aliases:
            repr += f"    alias({alias})\n"
        repr += "}"
        return repr

    def is_valid(self) -> bool:
        """
        Valid record has defined name and type.
        """
        return self.name is not None and self.rtyp is not None

    def merge(self, another: "Record") -> None:
        """
        Merge fields, infos, aliases from another record instance.
        """
        self.fields.update(another.fields)
        self.infos.update(another.infos)
        self.aliases.extend(another.aliases)


class Database(OrderedDict):
    def __init__(self):
        super().__init__()
        self._included_templates: dict[str, Database | None] = {}

    def __repr__(self) -> str:
        msg = []
        for record in self.values():
            msg.append(repr(record))
        return "\n".join(msg)

    def add_record(self, record: "Record") -> None:
        if not record.is_valid():
            return

        record_existed = self.get(record.name)
        if record_existed:
            if record_existed.rtyp != record.rtyp:
                raise DatabaseException(
                    f"Reappearing record '{record.name}' with"
                    f" conflicting record type '{record.rtyp}'"
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
    record = Record()

    record.rtyp, record.name = parse_pair(src)

    token = next(src)
    while True:
        if token == "}":
            break
        elif token in ("field", "info", "alias"):
            key, value = parse_pair(src)
            if key and value:
                logger.debug(f"Setting {token} '{key}' for record '{record.name}'")
                getattr(record, f"{token}s")[key] = value
            else:
                logger.warning(f"Invalid {token} definition for record '{record.name}'")

        token = next(src)

    logger.debug(f"Parsed record: '{record.name}'")
    return record


def find_database_file(filename: Path, includes: set[Path] | None = None) -> Path:
    if not filename.is_absolute() and includes is not None:
        for include in includes:
            path = include / filename
            if path.exists():
                filename = path
                break
    else:
        if not filename.exists():
            raise DatabaseException(f"Database file '{filename}' not found")
    return filename


def load_database_file(
    filename: Path,
    macros: dict[str, str] | None = None,
    includes: set[Path] | None = None,
    load_includes_strategy: LoadIncludesStrategy = LoadIncludesStrategy.LOAD_INTO_SELF,
    allow_unmatched_macros: bool = True,
):
    """
    :param str filename: EPICS database filename
    :return: list of record dict
    :rtype: list of dicts
    """
    # search filename through include directories
    if includes is None:
        includes = set()
    filename = find_database_file(filename, includes)

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
        return database

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
            database[alias_name] = database[record_name]
        elif token == "include":
            inclusion = next(src)
            # Add placeholder entry for included file even if we
            database.add_included_template(inclusion, None)

            # recursively load included file
            if load_includes_strategy != LoadIncludesStrategy.IGNORE:
                extended_includes = set(includes)
                extended_includes.add(filename.parent)
                included_db = load_database_file(
                    Path(inclusion),
                    macros,
                    extended_includes,
                    load_includes_strategy,
                    allow_unmatched_macros,
                )
                if load_includes_strategy == LoadIncludesStrategy.LOAD_INTO_SELF:
                    database.merge(included_db)
                if load_includes_strategy == LoadIncludesStrategy.LOAD_INTO_SELF:
                    database.merge(included_db)
                elif load_includes_strategy == LoadIncludesStrategy.LOAD_INTO_NEW:
                    database.add_included_template(inclusion, included_db)

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
