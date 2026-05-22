import argparse
import importlib
from collections.abc import Callable
import logging
from typing import Protocol, runtime_checkable

from .log import logger
from .tools import __all__ as cli_tools
from ._version import __version__


@runtime_checkable
class CLIModuleProtocol(Protocol):
    add_parser_args: Callable[[argparse.ArgumentParser], None] | None
    main: Callable[[argparse.Namespace], None]
    __doc__: str | None


def get_cli_modules() -> dict[str, CLIModuleProtocol]:
    cli_modules: dict[str, CLIModuleProtocol] = {}
    for command in cli_tools:
        try:
            cli_module = importlib.import_module(
                f".tools.{command}", package="epicsdbtools"
            )
            if not isinstance(cli_module, CLIModuleProtocol):
                logger.warning(
                    f"Module {command} does not conform to CLIModuleProtocol. Skipping."
                )
                continue
            cli_modules[command.replace("_", "-")] = cli_module
        except Exception:
            logger.error(
                f"Failed to import CLI module for command: {command}", exc_info=True
            )
    return cli_modules


def create_cli_module_subparsers(
    parser: argparse.ArgumentParser, cli_modules: dict[str, CLIModuleProtocol]
):
    subparsers = parser.add_subparsers(
        dest="command", help="Available commands", required=True
    )
    for command in cli_modules.keys():
        command = command.replace("_", "-")  # Allow commands to be defined with underscores but used with dashes

        logger.debug(f"Adding CLI subcommand: {command}")

        if hasattr(cli_modules[command], "__doc__"):
            cli_module_parser = subparsers.add_parser(
                command, help=cli_modules[command].__doc__
            )
        else:
            cli_module_parser = subparsers.add_parser(
                command, help=f"{command} command"
            )

        cli_module_parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")

        if hasattr(cli_modules[command], "add_parser_args"):
            add_parser_args_fn = cli_modules[command].add_parser_args
            if callable(add_parser_args_fn):
                add_parser_args_fn(cli_module_parser)
        else:
            logger.debug(f"No add_parser_args function found for command: {command}")


def main():

    parser = argparse.ArgumentParser(
        description="A CLI utility for EPICS database operations."
    )
    parser.add_argument("--version", action="version", version=f"epicsdbtools v{__version__}")

    cli_modules = get_cli_modules()
    create_cli_module_subparsers(parser, cli_modules)

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    if hasattr(cli_modules[args.command], "main"):
        cli_modules[args.command].main(args)
    else:
        logger.error(f"No main function found for command: {args.command}")


if __name__ == "__main__":
    main()
