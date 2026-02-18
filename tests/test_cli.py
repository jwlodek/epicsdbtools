import argparse
import logging
import sys

import pytest

from epicsdbtools.cli import (
    CLIModuleProtocol,
    create_cli_module_subparsers,
    get_cli_modules,
)
from epicsdbtools.tools import __all__ as cli_tools
from epicsdbtools.tools import paramdefs


class TestCLIModuleProtocol:
    """Test"""

    def add_parser_args(self, parser: argparse.ArgumentParser):
        pass

    def main(self, args: argparse.Namespace):
        pass


class TestCLIModuleProtocolNoArgs:
    def main(self):
        pass


def add_parser_args(parser: argparse.ArgumentParser):
    pass


def main(args: argparse.Namespace):
    pass


class NotACLIModuleProtocol:
    pass


@pytest.mark.parametrize(
    "input, is_cli_module_protocol",
    [
        (paramdefs, True),
        (TestCLIModuleProtocol(), True),
        (sys.modules[__name__], True),
        (argparse.ArgumentParser, False),
        (NotACLIModuleProtocol(), False),
    ],
)
def test_cli_module_protocol(input, is_cli_module_protocol):
    assert isinstance(input, CLIModuleProtocol) == is_cli_module_protocol


def test_get_cli_modules():
    cli_modules = get_cli_modules()
    for command in cli_tools:
        assert command in cli_modules
        assert isinstance(cli_modules[command], CLIModuleProtocol)


def test_get_cli_modules_import_failure(monkeypatch, caplog):
    def mock_import_module(name, package=None):
        raise ImportError(f"Mock import error importing {package}{name}")

    monkeypatch.setattr("importlib.import_module", mock_import_module)
    with caplog.at_level(logging.ERROR):
        cli_modules = get_cli_modules()
    assert cli_modules == {}
    assert "Failed to import CLI module for command" in caplog.text


def test_get_cli_modules_not_valid_protocol(monkeypatch, caplog):

    def mock_import_module(name, package=None):
        return NotACLIModuleProtocol()

    monkeypatch.setattr("importlib.import_module", mock_import_module)
    with caplog.at_level(logging.WARNING):
        cli_modules = get_cli_modules()
    assert cli_modules == {}
    assert "does not conform to CLIModuleProtocol" in caplog.text


def test_create_cli_module_subparsers():
    parser = argparse.ArgumentParser()
    cli_modules = get_cli_modules()
    create_cli_module_subparsers(parser, cli_modules)

    def _check_cli_module_subparser(command: str, cli_module: CLIModuleProtocol):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for subparser_name in action.choices.keys():
                    if subparser_name == command:
                        return True
        return False

    for name, cli_module in cli_modules.items():
        assert _check_cli_module_subparser(name, cli_module), (
            f"Subparser not found for CLI module: {name}"
        )


def test_create_cli_module_subparsers_no_parser_args(caplog):

    parser = argparse.ArgumentParser()
    cli_modules = {"mod": TestCLIModuleProtocolNoArgs()}
    with caplog.at_level(logging.DEBUG):
        create_cli_module_subparsers(parser, cli_modules)  # type: ignore
    assert len(parser._actions) == 2  # Help action and subparsers action
    assert isinstance(parser._actions[1], argparse._SubParsersAction)
    name, subparser = list(parser._actions[1].choices.items())[0]
    assert name == "mod"
    assert isinstance(subparser, argparse.ArgumentParser)
    assert len(subparser._actions) == 1  # Only help action
    assert "No add_parser_args function found for command" in caplog.text
