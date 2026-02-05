import argparse
from .tools import __all__ as cli_tools
import importlib

def main():

    parser = argparse.ArgumentParser(
        description="A CLI utility for EPICS database operations."
    )
    parser.add_argument(
        "--version", action="version", version="epicsdbtools 1.0.0"
    )
    subparsers = parser.add_subparsers(dest="command", help = "Available commands", required=True)

    cli_modules = {}
    for command in cli_tools:
        try:
            cli_modules[command] = importlib.import_module(f".tools.{command}", package="epicsdbtools")
        except Exception:
            pass

    # Add subcommands here
    # e.g., subparsers.add_parser("generate", help="Generate parameter definitions")
    for command in cli_modules.keys():
        cli_module_parser  =subparsers.add_parser(command, help=cli_modules[command].__doc__)
        if hasattr(cli_modules[command], "make_parser"):
            cli_modules[command].make_parser(cli_module_parser)

    args = parser.parse_args()
    if hasattr(cli_modules[args.command], "main"):
        cli_modules[args.command].main(args)

if __name__ == "__main__":
    main()