import argparse
import importlib
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from .log import logger
from .tools import __all__ as cli_tools


@runtime_checkable
class CLIModuleProtocol(Protocol):
    add_parser_args: Callable[[argparse.ArgumentParser], None] | None
    main: Callable[[argparse.Namespace], None]
    __doc__: str | None


def main():

    parser = argparse.ArgumentParser(
        description="A CLI utility for EPICS database operations."
    )
    parser.add_argument("--version", action="version", version="epicsdbtools 1.0.0")
    subparsers = parser.add_subparsers(
        dest="command", help="Available commands", required=True
    )

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
            cli_modules[command] = cli_module
        except Exception:
            logger.error(
                f"Failed to import CLI module for command: {command}", exc_info=True
            )

    for command in cli_modules.keys():
        logger.debug(f"Adding CLI subcommand: {command}")

        if hasattr(cli_modules[command], "__doc__"):
            cli_module_parser = subparsers.add_parser(
                command, help=cli_modules[command].__doc__
            )
        else:
            cli_module_parser = subparsers.add_parser(
                command, help=f"{command} command"
            )

        if hasattr(cli_modules[command], "add_parser_args"):
            add_parser_args_fn = cli_modules[command].add_parser_args
            if callable(add_parser_args_fn):
                add_parser_args_fn(cli_module_parser)
        else:
            logger.debug(f"No add_parser_args function found for command: {command}")

    args = parser.parse_args()
    if hasattr(cli_modules[args.command], "main"):
        cli_modules[args.command].main(args)
    else:
        logger.error(f"No main function found for command: {args.command}")


if __name__ == "__main__":
    main()
