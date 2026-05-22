"""CLI tool for validating EPICS databases against database definitions."""

import argparse
from pathlib import Path

from ..parsers.database import load_database_file
from ..parsers.database_definition import load_dbd_file
from ..validation import (
    BUILTIN_IOCSH_COMMANDS,
    ValidationMessage,
    ValidationResult,
    ValidationSeverity,
    validate_database,
    validate_ioc,
    validate_iocsh_commands,
)

__all__ = [
    "BUILTIN_IOCSH_COMMANDS",
    "ValidationMessage",
    "ValidationResult",
    "ValidationSeverity",
    "validate_database",
    "validate_ioc",
    "validate_iocsh_commands",
]


def add_parser_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "dbd_file",
        help="Path to the database definition (.dbd) file.",
    )
    parser.add_argument(
        "db_files",
        nargs="+",
        help="Path(s) to database (.db) file(s) to validate.",
    )


def main(args: argparse.Namespace) -> None:
    dbd_path = Path(args.dbd_file)
    if not dbd_path.is_file():
        raise FileNotFoundError(f"Database definition file not found: {dbd_path}")

    dbd = load_dbd_file(dbd_path)

    all_valid = True
    for db_file in args.db_files:
        db_path = Path(db_file)
        if not db_path.is_file():
            raise FileNotFoundError(f"Database file not found: {db_path}")

        db = load_database_file(db_path)
        result = validate_database(db, dbd)

        if result.is_valid:
            print(f"{db_path}: OK")
        else:
            all_valid = False
            print(f"{db_path}: FAILED")
            for msg in result.messages:
                print(f"  {msg}")

    if not all_valid:
        raise SystemExit(1)
