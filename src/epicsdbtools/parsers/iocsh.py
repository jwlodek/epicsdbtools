from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..macro import macro_expand, macro_split
from .database import (
    Database,
    DatabaseException,
    LoadIncludesStrategy,
    load_database_file,
)
from .substitution import load_substitution_file


@dataclass
class IocshCommand:
    name: str
    args: list[str]


@dataclass
class IocshState:
    macros: dict[str, str] = field(default_factory=dict)
    databases: list[Database] = field(default_factory=list)
    other_commands: list[IocshCommand] = field(default_factory=list)

    def update(self, other: IocshState) -> None:
        self.macros.update(other.macros)
        self.databases.extend(other.databases)
        self.other_commands.extend(other.other_commands)


def _expand_macros(text: str, macros: dict[str, str], strict: bool = False) -> str:
    """Expand macros in a string.

    Parameters
    ----------
    text : str
        The text containing macro references to expand.
    macros : dict
        The macro definitions to use for expansion.
    strict : bool
        If True, raise UndefinedMacroError when any macros remain unresolved.

    Raises
    ------
    UndefinedMacroError
        If strict is True and there are unresolved macros.
    """
    expanded, unmatched = macro_expand(text, macros)
    if strict and unmatched:
        raise DatabaseException(f"Undefined macros in '{text}': {', '.join(unmatched)}")
    return expanded


def _parse_command_line(line: str) -> list[str] | None:
    """Parse an iocsh command line into command name and arguments.

    Returns None for empty/comment lines.
    Handles both forms:
      - command("arg1", "arg2")
      - command arg1, arg2
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Check for function-call style: command(args...)
    paren_idx = line.find("(")
    if paren_idx > 0 and line.rstrip().endswith(")"):
        command = line[:paren_idx].strip()
        # Extract content between outer parens
        arg_str = line[paren_idx + 1 : -1]
    else:
        # Whitespace-separated: command arg1 arg2...
        parts = line.split(None, 1)
        if not parts:
            return None
        command = parts[0]
        arg_str = parts[1] if len(parts) > 1 else ""

    args: list[str] = []
    if arg_str.strip():
        # Split on commas, respecting quotes
        raw_args = _split_args(arg_str)
        for arg in raw_args:
            arg = arg.strip()
            # Strip surrounding quotes
            if len(arg) >= 2 and arg[0] in ('"', "'") and arg[-1] == arg[0]:
                arg = arg[1:-1]
            if arg:
                args.append(arg)

    return [command] + args


def _split_args(arg_str: str) -> list[str]:
    """Split argument string on commas, respecting quoted sections."""
    args = []
    current = []
    in_quote = None

    for ch in arg_str:
        if ch in ('"', "'") and in_quote is None:
            in_quote = ch
            current.append(ch)
        elif ch == in_quote:
            in_quote = None
            current.append(ch)
        elif ch == "," and in_quote is None:
            args.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        args.append("".join(current))

    return args


def consume_iocsh_command(
    line: str, current_state: IocshState, strict_macros: bool = False
) -> None:
    """Process a single iocsh command line, mutating the current state.

    Handles:
    - epicsEnvSet: sets environment/macro variables
    - dbLoadRecords / dbLoadTemplate: loads database files
    - dbLoadTemplate: loads substitution files
    - < filename: sources another startup script (inline)
    - All other commands are stored in other_commands

    Parameters
    ----------
    strict_macros : bool
        If True, raise UndefinedMacroError on unresolved macro substitutions.
    """
    # Expand macros in the line first
    line = _expand_macros(line, current_state.macros, strict=strict_macros)

    parsed = _parse_command_line(line)
    if parsed is None:
        return

    command = parsed[0]
    args = parsed[1:]

    if command == "epicsEnvSet":
        # epicsEnvSet("KEY", "VALUE") or epicsEnvSet KEY VALUE
        if len(args) >= 2:
            key = args[0]
            value = args[1]
            current_state.macros[key] = value

    elif command in ("dbLoadRecords", "dbLoadDatabase"):
        # dbLoadRecords("file.db", "macros")
        if len(args) >= 1:
            db_path = Path(args[0])
            db_macros: dict[str, str] = {}
            if len(args) >= 2 and args[1]:
                db_macros = macro_split(args[1])
            # Merge current state macros as defaults
            combined_macros = {**current_state.macros, **db_macros}
            if not db_path.exists():
                raise FileNotFoundError(f"Database file not found: {db_path}")
            db = load_database_file(
                db_path,
                macros=combined_macros,
                load_includes_strategy=LoadIncludesStrategy.LOAD_INTO_SELF,
                allow_unmatched_macros=not strict_macros,
            )
            current_state.databases.append(db)

    elif command == "dbLoadTemplate":
        # dbLoadTemplate("file.substitutions")
        if len(args) >= 1:
            sub_path = Path(args[0])
            if not sub_path.exists():
                raise FileNotFoundError(f"Substitution file not found: {sub_path}")
            substitutions = load_substitution_file(sub_path)
            for sub in substitutions:
                combined_macros = {**current_state.macros, **sub.macros}
                if not sub.file.exists():
                    raise FileNotFoundError(f"Template file not found: {sub.file}")
                db = load_database_file(
                    sub.file,
                    macros=combined_macros,
                    load_includes_strategy=LoadIncludesStrategy.IGNORE,
                )
                current_state.databases.append(db)

    else:
        current_state.other_commands.append(IocshCommand(name=command, args=args))


def load_iocsh_file(
    filepath: Path,
    macros: dict[str, str] | None = None,
    *,
    resolve_sources: bool = True,
    strict_macros: bool = False,
) -> IocshState:
    """Parse an IOC shell startup file and return the resulting state.

    Parameters
    ----------
    filepath : Path
        Path to the IOC shell startup script (e.g., st.cmd).
    macros : dict, optional
        Initial macros/environment variables to seed the state with.
    resolve_sources : bool
        If True, recursively parse sourced scripts (< file or iocshLoad).
    strict_macros : bool
        If True, raise UndefinedMacroError when a macro substitution cannot
        be resolved.

    Returns
    -------
    IocshState
        The accumulated state after processing all commands.
    """
    state = IocshState(macros=dict(macros) if macros else {})
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"IOC shell startup file not found: {filepath}")

    base_dir = filepath.parent

    with open(filepath) as f:
        for raw_line in f:
            line = raw_line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Expand macros in the line
            expanded_line = _expand_macros(line, state.macros, strict=strict_macros)

            # Handle source redirect: < filename
            if expanded_line.startswith("<"):
                sourced_file = expanded_line[1:].strip()
                # Strip quotes if present
                if (
                    len(sourced_file) >= 2
                    and sourced_file[0] in ('"', "'")
                    and sourced_file[-1] == sourced_file[0]
                ):
                    sourced_file = sourced_file[1:-1]

                sourced_path = Path(sourced_file)
                if not sourced_path.is_absolute():
                    sourced_path = base_dir / sourced_path

                if resolve_sources:
                    if not sourced_path.exists():
                        raise FileNotFoundError(
                            f"Sourced script not found: {sourced_path}"
                        )
                    child_state = load_iocsh_file(
                        sourced_path,
                        macros=state.macros,
                        resolve_sources=resolve_sources,
                        strict_macros=strict_macros,
                    )
                    state.update(child_state)
                continue

            # Handle iocshLoad / iocshCmd for sourcing other scripts
            parsed = _parse_command_line(expanded_line)
            if parsed is None:
                continue

            command = parsed[0]

            if command in ("iocshLoad", "iocshRun") and resolve_sources:
                args = parsed[1:]
                if args:
                    script_path = Path(args[0])
                    if not script_path.is_absolute():
                        script_path = base_dir / script_path
                    # Second arg may be macros for the sub-script
                    sub_macros = dict(state.macros)
                    if len(args) >= 2 and args[1]:
                        sub_macros.update(macro_split(args[1]))
                    if script_path.exists():
                        child_state = load_iocsh_file(
                            script_path,
                            macros=sub_macros,
                            resolve_sources=resolve_sources,
                            strict_macros=strict_macros,
                        )
                        state.update(child_state)
                    else:
                        raise FileNotFoundError(
                            f"Sourced script not found: {script_path}"
                        )
            else:
                consume_iocsh_command(expanded_line, state, strict_macros=strict_macros)

    return state
