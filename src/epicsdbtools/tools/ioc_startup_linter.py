"""Utility for linting IOC shell startup scripts."""

import argparse
from pathlib import Path

from ..parsers import load_iocsh_file


def add_parser_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "input_path",
        help="Path to the IOC startup script to lint.",
    )


def main(args: argparse.Namespace | None = None):
    if args is None:
        parser = argparse.ArgumentParser(description=__doc__)
        add_parser_args(parser)
        args = parser.parse_args()
        main(args)

    if not Path(args.input_path).is_file():
        raise FileNotFoundError(f"File not found: {args.input_path}")
    elif not (args.input_path.endswith(".cmd") or args.input_path.endswith(".iocsh")):
        raise ValueError(
            f"Invalid file type: {args.input_path}, must be .cmd or .iocsh"
        )

    iocsh_state = load_iocsh_file(args.input_path, strict_macros=True)
    # Perform linting on the loaded IOC shell state
    # This is where you would implement the actual linting logic
    # For now, we'll just print the loaded state
    print(iocsh_state)
