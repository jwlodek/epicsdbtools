from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..macro import macro_expand, macro_split

logger = logging.getLogger("epicsdbtools")
from .database import (
    Database,
    DatabaseException,
    LoadIncludesStrategy,
    load_database_file,
)
from .database_definition import DatabaseDefinition, load_dbd_file
from .substitution import load_substitution_file


@dataclass
class IocshCommand:
    """Represents a generic iocsh command that is not specifically handled by the parser.
    
    Attributes
    ----------
    name : str
        The name of the iocsh command (e.g., "epicsEnvSet", "dbLoadRecords").
    args : list[str]
        The list of arguments passed to the command, after macro expansion and stripping.
    """

    name: str
    args: list[str]


@dataclass
class IocshState:
    """Represents the accumulated state of an IOC shell startup script after processing commands.

    Attributes
    ----------
    macros : dict[str, str]
        The dictionary of macro definitions.
    databases : list[Database]
        The list of loaded databases.
    dbd : DatabaseDefinition | None
        The loaded database definition, if any.
    other_commands : list[IocshCommand]
        The list of other iocsh commands that are not specifically handled.
    cwd : Path | None
        The current working directory for resolving relative paths.
    """

    macros: dict[str, str] = field(default_factory=dict)
    databases: list[Database] = field(default_factory=list)
    dbd: DatabaseDefinition | None = None
    other_commands: list[IocshCommand] = field(default_factory=list)
    cwd: Path | None = None
    registered_commands: set[str] = field(default_factory=set)
    dbd_path: Path | None = None

    def update(self, other: IocshState) -> None:
        self.macros.update(other.macros)
        self.databases.extend(other.databases)
        if other.dbd is not None:
            self.dbd = other.dbd
        if other.dbd_path is not None:
            self.dbd_path = other.dbd_path
        self.other_commands.extend(other.other_commands)
        self.registered_commands.update(other.registered_commands)
        if other.cwd is not None:
            self.cwd = other.cwd

    def __str__(self) -> str:
        return (
            "IOC Shell State:\n"
            f"  Database Definition: {self.dbd}\n"
            f"  Current Working Directory: {self.cwd}\n"
            f"  Macros:\n{''.join(f'    {k} = {v}\n' for k, v in self.macros.items())}"
            f"  Databases:\n{''.join(f'    {db.description}\n' for db in self.databases)}"
            f"  Other Commands:\n{''.join(f'    {cmd.name}({', '.join(cmd.args)})\n' for cmd in self.other_commands)}"
        )

def _expand_macros(text: str, macros: dict[str, str]) -> str:
    """Expand macros in a string.

    Parameters
    ----------
    text : str
        The text containing macro references to expand.
    macros : dict[str, str]
        The macro definitions to use for expansion.

    Returns
    -------
    str
        The text with all resolvable macros expanded. Unresolved macros
        are left as-is.
    """
    expanded, _ = macro_expand(text, macros)
    return expanded


def _parse_command_line(line: str) -> list[str] | None:
    """Parse an iocsh command line into command name and arguments.

    Handles both forms:
      - command("arg1", "arg2")
      - command arg1, arg2
    
    Parameters
    ----------
    line : str
        The iocsh command line to parse.

    Returns
    -------
    list[str] | None
        The parsed command name and arguments, or None for empty/comment lines.
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
    """Split argument string on commas, respecting quoted sections.
    
    Parameters
    ----------
    arg_str : str
        The argument string to split.

    Returns
    -------
    list[str]
        The list of split arguments.
    """

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


def _resolve_file_path(
    path: Path,
    state: IocshState,
    search_path_macro: str | None = "EPICS_DB_INCLUDE_PATH",
) -> Path:
    """Resolve a file path relative to the IOC state's cwd and an optional search path macro.

    Parameters
    ----------
    path : Path
        The file path to resolve.
    state : IocshState
        The current IOC state (provides cwd and macros).
    search_path_macro : str | None
        The name of a macro containing a colon-separated list of directories
        to search when the file is not found directly. Set to None to disable.
        Defaults to "EPICS_DB_INCLUDE_PATH".

    Returns
    -------
    Path
        The resolved path if found, otherwise the original path (possibly
        made absolute relative to cwd).
    """
    if path.is_absolute():
        if path.exists():
            return path
    else:
        # Resolve relative to cwd
        if state.cwd is not None:
            candidate = state.cwd / path
            if candidate.exists():
                return candidate
        # Check if it exists as-is (e.g. already relative to process cwd)
        if path.exists():
            return path

    # Search the specified macro path
    if search_path_macro is not None:
        include_path = state.macros.get(search_path_macro, "")
        if include_path:
            for search_dir in include_path.split(":"):
                search_dir = search_dir.strip()
                if not search_dir:
                    continue
                candidate = Path(search_dir) / path
                if candidate.exists():
                    return candidate

    # Return as absolute relative to cwd if possible
    if not path.is_absolute() and state.cwd is not None:
        return state.cwd / path
    return path


def _get_arch() -> str:
    """Get the EPICS target architecture string for the current platform."""
    machine = platform.machine()
    system = platform.system().lower()
    arch_map = {
        ("linux", "x86_64"): "linux-x86_64",
        ("linux", "aarch64"): "linux-aarch64",
        ("linux", "armv7l"): "linux-arm",
        ("darwin", "x86_64"): "darwin-x86",
        ("darwin", "arm64"): "darwin-aarch64",
    }
    return arch_map.get((system, machine), f"{system}-{machine}")


def _discover_commands_from_binary(binary_path: Path) -> set[str]:
    """Extract registered iocsh command names from an IOC binary and its libraries.

    Finds command names by looking for strings ending in 'FuncDef' or 'Def'
    that also have a corresponding bare command name string in the same file.

    Parameters
    ----------
    binary_path : Path
        Path to the IOC binary executable.

    Returns
    -------
    set[str]
        Set of discovered iocsh command names.
    """
    commands: set[str] = set()

    # Get the binary and all its linked shared libraries
    files_to_scan = [binary_path]
    try:
        result = subprocess.run(
            ["ldd", str(binary_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                # Parse ldd output: libname.so => /path/to/lib.so (0x...)
                parts = line.split("=>")
                if len(parts) == 2:
                    lib_path = parts[1].strip().split("(")[0].strip()
                    if lib_path and Path(lib_path).exists():
                        files_to_scan.append(Path(lib_path))
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"Failed to run ldd on {binary_path}: {e}")

    for file_path in files_to_scan:
        try:
            result = subprocess.run(
                ["strings", str(file_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                continue
        except (subprocess.TimeoutExpired, OSError):
            continue

        all_strings = set(result.stdout.splitlines())

        for s in all_strings:
            if s.endswith("FuncDef"):
                cmd_name = s[: -len("FuncDef")]
                if cmd_name and cmd_name in all_strings:
                    commands.add(cmd_name)
            elif s.endswith("Def") and not s.endswith("FuncDef"):
                cmd_name = s[: -len("Def")]
                if cmd_name and cmd_name in all_strings:
                    commands.add(cmd_name)

    return commands


def _find_ioc_binary(app_name: str, dbd_path: Path) -> Path | None:
    """Locate the IOC binary based on the app name and dbd file path.

    Looks in <dbd_dir>/../bin/<arch>/<app_name> for the binary.

    Parameters
    ----------
    app_name : str
        The application name (prefix of *_registerRecordDeviceDriver).
    dbd_path : Path
        Path to the loaded .dbd file.

    Returns
    -------
    Path | None
        Path to the binary if found, None otherwise.
    """
    # dbd is typically in <top>/dbd/, binary in <top>/bin/<arch>/
    top_dir = dbd_path.parent.parent
    bin_dir = top_dir / "bin"

    if not bin_dir.is_dir():
        return None

    logger.debug(f"Looking for IOC binary '{app_name}' in {bin_dir} for dbd at {dbd_path}")

    # Try the current platform architecture first
    candidate = None
    arch = _get_arch()
    candidate = bin_dir / arch / app_name

    # Fall back to searching any arch directory
    if not candidate.exists():
        candidate = None
        for arch_dir in bin_dir.iterdir():
            if arch_dir.is_dir():
                candidate = arch_dir / app_name
                if candidate.exists():
                    break
                candidate = None

    if candidate:
        logger.debug(f"Found IOC binary for '{app_name}': {candidate}")
    return None


def consume_iocsh_command(
    line: str, current_state: IocshState
) -> None:
    """Process a single iocsh command line, mutating the current state.

    Handles:
    - epicsEnvSet: sets environment/macro variables
    - cd / chdir: changes the current working directory
    - dbLoadRecords / dbLoadTemplate: loads database files
    - dbLoadDatabase: loads database definition files
    - < filename: sources another startup script (inline)
    - All other commands are stored in other_commands

    Parameters
    ----------
    line : str
        The iocsh command line to process.
    current_state : IocshState
        The current accumulated state to update based on the command.
    """
    # Expand macros in the line first
    line = _expand_macros(line, current_state.macros)

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
            logger.debug(f"Set macro: {key} = {value}")
        else:
            logger.error(f"Invalid epicsEnvSet command, expected at least 2 args: {line}")

    elif command in ("cd", "chdir"):
        if len(args) >= 1:
            new_dir = Path(args[0])
            if not new_dir.is_absolute() and current_state.cwd is not None:
                new_dir = current_state.cwd / new_dir
            current_state.cwd = new_dir.resolve()
            logger.info(f"Changed directory to: {current_state.cwd}")

    elif command == "dbLoadDatabase":
        # dbLoadDatabase("file.dbd", "path", "substitutions")
        if len(args) >= 1:
            dbd_path = _resolve_file_path(Path(args[0]), current_state)
            if not dbd_path.exists():
                logger.error(f"Database definition file not found: {dbd_path}")
                raise FileNotFoundError(
                    f"Database definition file not found: {dbd_path}"
                )
            logger.info(f"Loading database definition file: {dbd_path}")
            current_state.dbd = load_dbd_file(dbd_path)
            current_state.dbd_path = dbd_path.resolve()

    elif command == "dbLoadRecords":
        # dbLoadRecords("file.db", "macros")
        if len(args) >= 1:
            db_path = _resolve_file_path(Path(args[0]), current_state)
            db_macros: dict[str, str] = {}
            if len(args) >= 2 and args[1]:
                db_macros = macro_split(args[1])
            # Merge current state macros as defaults
            combined_macros = {**current_state.macros, **db_macros}
            if not db_path.exists():
                raise FileNotFoundError(f"Database file not found: {db_path}")
            logger.info(f"Loading database file: {db_path} with macros: {db_macros}")
            db = load_database_file(
                db_path,
                macros=combined_macros,
                load_includes_strategy=LoadIncludesStrategy.LOAD_INTO_SELF,
                allow_unmatched_macros=True,
            )
            current_state.databases.append(db)

    elif command == "dbLoadTemplate":
        # dbLoadTemplate("file.substitutions")
        if len(args) >= 1:
            sub_path = _resolve_file_path(Path(args[0]), current_state)
            if not sub_path.exists():
                raise FileNotFoundError(f"Substitution file not found: {sub_path}")
            logger.info(f"Loading substitution file: {sub_path}")
            substitutions = load_substitution_file(sub_path)
            for sub in substitutions:
                combined_macros = {**current_state.macros, **sub.macros}
                template_path = _resolve_file_path(sub.file, current_state)
                if not template_path.exists():
                    raise FileNotFoundError(
                        f"Template file not found: {template_path}"
                    )
                logger.debug(f"Loading template file: {template_path} with macros: {sub.macros}")
                db = load_database_file(
                    template_path,
                    macros=combined_macros,
                    load_includes_strategy=LoadIncludesStrategy.IGNORE,
                )
                current_state.databases.append(db)

    else:
        if command.endswith("_registerRecordDeviceDriver"):
            app_name = command[: -len("_registerRecordDeviceDriver")]
            if current_state.dbd_path is not None:
                binary_path = _find_ioc_binary(app_name, current_state.dbd_path)
                if binary_path is not None:
                    logger.info(
                        f"Scanning IOC binary '{binary_path}' for registered commands"
                    )
                    discovered_iocsh_commands = _discover_commands_from_binary(binary_path)
                    for cmd in discovered_iocsh_commands:
                        logger.debug(f"Discovered iocsh command from binary: {cmd}")
                    current_state.registered_commands.update(discovered_iocsh_commands)
                else:
                    logger.warning(
                        f"Could not find IOC binary for '{app_name}'; "
                        f"commands from registrars will not be validated"
                    )
            else:
                logger.warning(
                    f"No dbd path available to locate IOC binary for '{app_name}'"
                )
        current_state.other_commands.append(IocshCommand(name=command, args=args))


def load_iocsh_file(
    filepath: Path,
    macros: dict[str, str] | None = None,
    resolve_sources: bool = True,
) -> IocshState:
    """Parse an IOC shell startup file and return the resulting state.

    Parameters
    ----------
    filepath : Path
        Path to the IOC shell startup script (e.g., st.cmd).
    macros : dict[str, str], optional
        Initial macros/environment variables to seed the state with.
    resolve_sources : bool
        If True, recursively parse sourced scripts (< file or iocshLoad).

    Returns
    -------
    IocshState
        The accumulated state after processing all commands.
    """
    logger.info(f"Loading IOC shell file: {filepath}")
    state = IocshState(macros=dict(macros) if macros else {})
    filepath = Path(filepath).resolve()

    if not filepath.exists():
        raise FileNotFoundError(f"IOC shell startup file not found: {filepath}")

    base_dir = filepath.parent
    # Set the cwd to the directory containing the startup script
    if state.cwd is None:
        state.cwd = base_dir

    with open(filepath) as f:
        for raw_line in f:
            line = raw_line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Expand macros in the line
            expanded_line = _expand_macros(line, state.macros)

            logger.debug(f"Processing line: {line}")
            if line != expanded_line:
                logger.debug(f"Expanded to: {expanded_line}")

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
                    sourced_path = (state.cwd or base_dir) / sourced_path

                if resolve_sources:
                    if not sourced_path.exists():
                        raise FileNotFoundError(
                            f"Sourced script not found: {sourced_path}"
                        )
                    logger.info(f"Sourcing script: {sourced_path}")
                    child_state = load_iocsh_file(
                        sourced_path,
                        macros=state.macros,
                        resolve_sources=resolve_sources,
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
                        script_path = (state.cwd or base_dir) / script_path
                    # Second arg may be macros for the sub-script
                    sub_macros = dict(state.macros)
                    if len(args) >= 2 and args[1]:
                        sub_macros.update(macro_split(args[1]))
                    if script_path.exists():
                        child_state = load_iocsh_file(
                            script_path,
                            macros=sub_macros,
                            resolve_sources=resolve_sources,
                        )
                        state.update(child_state)
                    else:
                        raise FileNotFoundError(
                            f"Sourced script not found: {script_path}"
                        )
            else:
                consume_iocsh_command(expanded_line, state)

    return state
