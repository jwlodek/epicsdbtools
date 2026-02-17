from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from pathlib import Path

from ..tokenizer import Tokenizer


def parse_filename(src: Iterator[str]) -> Path | None:
    filename = None

    token = next(src)
    while True:
        if token == "{":
            break
        filename = token

        token = next(src)

    return Path(filename) if filename else None


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


class SubstitutionParseState(int, Enum):
    NEUTRAL = 0
    GLOBAL = 1
    FILE = 2
    PATTERN = 3
    SUBS = 4


@dataclass
class Subsitution:
    file: Path
    macros: dict[str, str]


def parse_substitution(source: StringIO) -> list[Subsitution]:
    """
    :param buffer source: EPICS substitutes
    :return: list of (filename, macros, values)
    """
    files = []

    src = iter(Tokenizer(source))

    global_macros = {}
    pattern_macros = None
    file_global_macros = {}
    file_path = None
    saved_state = state = SubstitutionParseState.NEUTRAL
    for token in src:
        match state:
            case SubstitutionParseState.NEUTRAL:
                match token:
                    case "file":
                        file_path = parse_filename(src)
                        pattern_macros = None
                        file_global_macros = {}
                        saved_state = state
                        state = SubstitutionParseState.FILE
                    case "global":
                        saved_state = state
                        state = SubstitutionParseState.GLOBAL
            case SubstitutionParseState.FILE:
                match token:
                    case "global":
                        saved_state = state
                        state = SubstitutionParseState.GLOBAL
                    case "pattern":
                        saved_state = state
                        state = SubstitutionParseState.PATTERN
                    case "{":
                        if pattern_macros is None:
                            macros, values = parse_macro_value(src)
                        else:
                            macros, values = pattern_macros, parse_pattern_values(src)
                        d = {}
                        d.update(global_macros)
                        d.update(file_global_macros)
                        d.update(zip(macros, values, strict=False))
                        if file_path is None:
                            raise ValueError("File path could not be determined")
                        files.append(Subsitution(file_path, d))
                    case "}":
                        saved_state = state
                        state = SubstitutionParseState.NEUTRAL
            case SubstitutionParseState.PATTERN:
                if token == "{":
                    pattern_macros = parse_pattern_macros(src)
                    state = saved_state
            case SubstitutionParseState.GLOBAL:
                if token == "{":
                    macros, values = parse_macro_value(src)
                    if saved_state == SubstitutionParseState.FILE:
                        file_global_macros.update(zip(macros, values, strict=False))
                    else:
                        global_macros.update(zip(macros, values, strict=False))
                    macros = values = None
                    state = saved_state

    return files


def load_substitution_file(filename):
    with open(filename) as fp:
        return parse_substitution(StringIO(fp.read()))


if __name__ == "__main__":
    import argparse
    import os

    from .database import Database, load_database_file

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-I", action="append", dest="includes", help="substitution include paths"
    )
    parser.add_argument(dest="substitution_files", nargs="+", help="substitution files")
    args = parser.parse_args()

    db = Database()
    for subs_file in args.substitution_files:
        if os.path.exists(subs_file):
            includes = {Path(subs_file).parent}
            if args.includes:
                includes.update([Path(i) for i in args.includes])
            for substitution in load_substitution_file(subs_file):
                db.update(
                    load_database_file(
                        Path(substitution.file),
                        substitution.macros,
                        includes,
                        args.encoding,
                    )
                )
    print(db)
