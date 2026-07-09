"""Utility for linting IOC shell startup scripts."""

import argparse
from pathlib import Path

from ..parsers import load_iocsh_file
from ..validation import validate_ioc


def add_parser_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "input_path",
        help="Path to the IOC startup script to lint.",
    )
    parser.add_argument(
        "--print-final-state",
        action="store_true",
        help="Print the final parsed state of the IOC after validation.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat unknown iocsh commands as errors instead of warnings.",
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

    iocsh_state = load_iocsh_file(args.input_path)

    if args.print_final_state:
        print(iocsh_state)

    print(validate_ioc(iocsh_state, strict=args.strict))
