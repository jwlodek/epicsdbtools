from collections.abc import Iterator
from enum import Enum
from io import StringIO
from pathlib import Path

from .tokenizer import Tokenizer


def parse_filename(src: Iterator[str]) -> str | None:
    filename = None

    token = next(src)
    while True:
        if token == "{":
            break
        filename = token

        token = next(src)

    return filename


def parse_pattern_macros(src: Iterator[str]) -> list[str]:
    macros = []

    token = next(src)
    while True:
        if token == "}":
            break

        if token != ",":
            macros.append(token)

        token = next(src)

    return macros


def parse_pattern_values(src: Iterator[str]) -> list[str]:
    values = []

    token = next(src)
    while True:
        if token == "}":
            break

        if token != ",":
            values.append(token)

        token = next(src)

    return values


def parse_macro_value(src: Iterator[str]) -> tuple[list[str], list[str]]:
    macros = []
    values = []

    equal = False
    token = next(src)
    while True:
        if token == "}":
            break

        if token == "=":
            equal = True
        elif token == ",":
            equal = False
        else:
            if equal:
                values.append(token)
                equal = False
            else:
                macros.append(token)

        token = next(src)

    return macros, values


class TemplateParseState(int, Enum):
    NEUTRAL = 0
    GLOBAL = 1
    FILE = 2
    PATTERN = 3
    SUBS = 4


def parse_template(source: StringIO) -> list[tuple[str, dict]]:
    """
    :param buffer source: EPICS substitutes
    :return: list of (filename, macros, values)
    """
    files = []

    src = iter(Tokenizer(source))

    global_macros = {}
    pattern_macros = None
    file_global_macros = {}
    filename = None
    saved_state = state = TemplateParseState.NEUTRAL
    while True:
        try:
            token = next(src)
        except StopIteration:
            break
        if state == TemplateParseState.NEUTRAL:
            if token == "file":
                filename = parse_filename(src)
                pattern_macros = None
                file_global_macros = {}
                saved_state = state
                state = TemplateParseState.FILE
            elif token == "global":
                saved_state = state
                state = TemplateParseState.GLOBAL
        elif state == TemplateParseState.FILE:
            if token == "global":
                saved_state = state
                state = TemplateParseState.GLOBAL
            elif token == "pattern":
                saved_state = state
                state = TemplateParseState.PATTERN
            elif token == "{":
                if pattern_macros is None:
                    macros, values = parse_macro_value(src)
                else:
                    macros, values = pattern_macros, parse_pattern_values(src)
                d = {}
                d.update(global_macros)
                d.update(file_global_macros)
                d.update(zip(macros, values, strict=False))
                files.append((filename, d))
            elif token == "}":
                saved_state = state
                state = TemplateParseState.NEUTRAL
        elif state == TemplateParseState.PATTERN:
            if token == "{":
                pattern_macros = parse_pattern_macros(src)
                state = saved_state
        elif state == TemplateParseState.GLOBAL:
            if token == "{":
                macros, values = parse_macro_value(src)
                if saved_state == TemplateParseState.FILE:
                    file_global_macros.update(zip(macros, values, strict=False))
                else:
                    global_macros.update(zip(macros, values, strict=False))
                macros = values = None
                state = saved_state

    return files


def load_template_file(filename):
    with open(filename) as fp:
        return parse_template(StringIO(fp.read()))


if __name__ == "__main__":
    import argparse
    import os

    from .database import Database, load_database_file

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-I", action="append", dest="includes", help="template include paths"
    )
    parser.add_argument(dest="substitution_files", nargs="+", help="substitution files")
    args = parser.parse_args()

    db = Database()
    for subs_file in args.substitution_files:
        if os.path.exists(subs_file):
            includes = {Path(subs_file).parent}
            if args.includes:
                includes.update([Path(i) for i in args.includes])
            for db_file, macros in load_template_file(subs_file):
                db.update(
                    load_database_file(Path(db_file), macros, includes, args.encoding)
                )
    print(db)
