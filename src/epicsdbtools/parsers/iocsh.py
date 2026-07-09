from __future__ import annotations

import logging
import platform
import re
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..macro import macro_expand, macro_split
from .database import (
    Database,
    LoadIncludesStrategy,
    load_database_file,
)
from .database_definition import DatabaseDefinition, load_dbd_file
from .proto import ProtocolFile, load_protocol_file
from .substitution import load_substitution_file

logger = logging.getLogger("epicsdbtools")


@dataclass
class IocshCommand:
    """A generic iocsh command not specifically handled by the parser.

    Attributes
    ----------
    name : str
        The command name (e.g., "epicsEnvSet", "dbLoadRecords").
    args : list[str]
        Arguments passed to the command, after macro expansion.
    """

    name: str
    args: list[str]


@dataclass
class IocshState:
    """Accumulated state of an IOC shell startup script.

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
    registered_commands: dict[str, int] = field(default_factory=dict)
    dbd_path: Path | None = None
    protocol_files: dict[str, ProtocolFile] = field(default_factory=dict)

    def update(self, other: IocshState) -> None:
        self.macros.update(other.macros)
        self.databases.extend(other.databases)
        if other.dbd is not None:
            self.dbd = other.dbd
        if other.dbd_path is not None:
            self.dbd_path = other.dbd_path
        self.other_commands.extend(other.other_commands)
        self.registered_commands.update(other.registered_commands)
        self.protocol_files.update(other.protocol_files)

    def __str__(self) -> str:
        macro_lines = "".join(f"    {k} = {v}\n" for k, v in self.macros.items())
        db_lines = "".join(f"    {db.description}\n" for db in self.databases)
        cmd_lines = "".join(
            f"    {cmd.name}({', '.join(cmd.args)})\n" for cmd in self.other_commands
        )
        return (
            "IOC Shell State:\n"
            f"  Database Definition: {self.dbd}\n"
            f"  Current Working Directory: {self.cwd}\n"
            f"  Macros:\n{macro_lines}"
            f"  Databases:\n{db_lines}"
            f"  Other Commands:\n{cmd_lines}"
        )


def _expand_macros(text: str, macros: dict[str, str]) -> str:
    """Expand macros in a string.

    Handles both $(MACRO) and ${MACRO} syntax.

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
    # Normalize ${MACRO} to $(MACRO) for consistent handling
    text = re.sub(r"\$\{([^}]+)\}", r"$(\1)", text)
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
    """Resolve a file path relative to the IOC state's cwd.

    Uses an optional search path macro.

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


def _get_db_search_path(state: IocshState) -> set[Path] | None:
    """Build a search path set from the EPICS_DB_INCLUDE_PATH macro."""
    include_path = state.macros.get("EPICS_DB_INCLUDE_PATH", "")
    if not include_path:
        return None
    paths = set()
    for search_dir in include_path.split(":"):
        search_dir = search_dir.strip()
        if search_dir:
            paths.add(Path(search_dir))
    return paths if paths else None


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


_FUNCDEF_SYMBOL_RE = re.compile(r"^([0-9a-f]+)\s+[dDrRbB]\s+(.+(?:FuncDef|Def))$")


def _get_linked_libraries(binary_path: Path) -> list[Path]:
    """Get paths to all shared libraries linked by a binary via ldd.

    Parameters
    ----------
    binary_path : Path
        Path to the ELF binary or shared library.

    Returns
    -------
    list[Path]
        List of resolved library paths.
    """
    libs: list[Path] = []
    try:
        result = subprocess.run(
            ["ldd", str(binary_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("=>")
                if len(parts) == 2:
                    lib_path = parts[1].strip().split("(")[0].strip()
                    if lib_path and Path(lib_path).exists():
                        libs.append(Path(lib_path))
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"Failed to run ldd on {binary_path}: {e}")
    return libs


def _extract_commands_from_elf(elf_path: Path) -> dict[str, int]:
    """Extract iocsh command names and argument counts from an ELF file.

    Reads iocshFuncDef structs directly from the ELF binary by:
    1. Finding symbols ending in 'FuncDef' or 'Def' via nm
    2. Parsing ELF program headers for vaddr-to-file-offset mapping
    3. Parsing relocations to resolve pointer fields
    4. Reading the command name string and nargs from each struct

    Parameters
    ----------
    elf_path : Path
        Path to a 64-bit little-endian ELF file (binary or shared library).

    Returns
    -------
    dict[str, int]
        Mapping of command name to number of arguments.
    """
    commands: dict[str, int] = {}

    # Get FuncDef/Def data symbol addresses from nm
    try:
        result = subprocess.run(
            ["nm", str(elf_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return commands
    except (subprocess.TimeoutExpired, OSError):
        return commands

    funcdef_symbols: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        m = _FUNCDEF_SYMBOL_RE.match(line)
        if m:
            funcdef_symbols.append((int(m.group(1), 16), m.group(2)))

    if not funcdef_symbols:
        return commands

    try:
        with open(elf_path, "rb") as f:
            # Validate ELF magic and format
            f.seek(0)
            magic = f.read(4)
            if magic != b"\x7fELF":
                return commands
            ei_class = struct.unpack("B", f.read(1))[0]
            if ei_class != 2:  # 64-bit only
                return commands
            ei_data = struct.unpack("B", f.read(1))[0]
            if ei_data != 1:  # little-endian only
                return commands

            # Parse program headers for vaddr <-> file offset mapping
            f.seek(32)
            e_phoff = struct.unpack("<Q", f.read(8))[0]
            f.seek(54)
            e_phentsize = struct.unpack("<H", f.read(2))[0]
            e_phnum = struct.unpack("<H", f.read(2))[0]

            segments: list[tuple[int, int, int]] = []  # (p_offset, p_vaddr, p_filesz)
            for i in range(e_phnum):
                f.seek(e_phoff + i * e_phentsize)
                p_type = struct.unpack("<I", f.read(4))[0]
                if p_type == 1:  # PT_LOAD
                    f.seek(e_phoff + i * e_phentsize + 8)
                    p_offset = struct.unpack("<Q", f.read(8))[0]
                    p_vaddr = struct.unpack("<Q", f.read(8))[0]
                    f.read(8)  # p_paddr
                    p_filesz = struct.unpack("<Q", f.read(8))[0]
                    segments.append((p_offset, p_vaddr, p_filesz))

            def vaddr_to_offset(vaddr: int) -> int | None:
                for p_off, p_va, p_fsz in segments:
                    if p_va <= vaddr < p_va + p_fsz:
                        return vaddr - p_va + p_off
                return None

            def read_string_at(vaddr: int) -> str | None:
                off = vaddr_to_offset(vaddr)
                if off is None:
                    return None
                f.seek(off)
                b = b""
                while len(b) < 256:
                    c = f.read(1)
                    if c == b"\x00" or not c:
                        break
                    b += c
                try:
                    return b.decode("ascii")
                except UnicodeDecodeError:
                    return None

            # Parse section headers to find .rela.dyn (relocations)
            f.seek(40)
            e_shoff = struct.unpack("<Q", f.read(8))[0]
            f.seek(58)
            e_shentsize = struct.unpack("<H", f.read(2))[0]
            e_shnum = struct.unpack("<H", f.read(2))[0]

            # Build relocation map: vaddr -> resolved address
            # We only need R_X86_64_RELATIVE (type 8) for string pointers
            reloc_map: dict[int, int] = {}
            for i in range(e_shnum):
                f.seek(e_shoff + i * e_shentsize)
                f.read(4)  # sh_name
                sh_type = struct.unpack("<I", f.read(4))[0]
                if sh_type != 4:  # SHT_RELA
                    continue
                f.read(16)  # sh_flags + sh_addr
                sh_offset = struct.unpack("<Q", f.read(8))[0]
                sh_size = struct.unpack("<Q", f.read(8))[0]

                num_entries = sh_size // 24  # sizeof(Elf64_Rela)
                for j in range(num_entries):
                    f.seek(sh_offset + j * 24)
                    r_offset = struct.unpack("<Q", f.read(8))[0]
                    r_info = struct.unpack("<Q", f.read(8))[0]
                    r_addend = struct.unpack("<q", f.read(8))[0]
                    r_type = r_info & 0xFFFFFFFF
                    if r_type == 8:  # R_X86_64_RELATIVE: base + addend
                        reloc_map[r_offset] = r_addend

            def read_ptr(vaddr: int) -> int | None:
                """Read a pointer, using relocation if available."""
                if vaddr in reloc_map:
                    return reloc_map[vaddr]
                off = vaddr_to_offset(vaddr)
                if off is None:
                    return None
                f.seek(off)
                return struct.unpack("<Q", f.read(8))[0]

            # Read each FuncDef struct:
            #   offset 0: const char *name  (8 bytes, pointer)
            #   offset 8: int nargs         (4 bytes, plain int)
            for sym_vaddr, _sym_name in funcdef_symbols:
                name_ptr = read_ptr(sym_vaddr)
                if name_ptr is None or name_ptr == 0:
                    continue
                cmd_name = read_string_at(name_ptr)
                if not cmd_name or not cmd_name.isprintable():
                    continue

                nargs_off = vaddr_to_offset(sym_vaddr + 8)
                if nargs_off is None:
                    continue
                f.seek(nargs_off)
                nargs = struct.unpack("<i", f.read(4))[0]
                if nargs < 0 or nargs > 20:
                    continue

                commands[cmd_name] = nargs

    except OSError as e:
        logger.debug(f"Failed to read ELF file {elf_path}: {e}")

    return commands


def _discover_commands_from_binary(binary_path: Path) -> dict[str, int]:
    """Extract registered iocsh command names from an IOC binary and its libraries.

    Scans the binary and all its linked shared libraries by reading iocshFuncDef
    structs directly from the ELF data.

    Parameters
    ----------
    binary_path : Path
        Path to the IOC binary executable.

    Returns
    -------
    dict[str, int]
        Mapping of command name to number of arguments.
    """
    commands: dict[str, int] = {}

    files_to_scan = [binary_path] + _get_linked_libraries(binary_path)

    for file_path in files_to_scan:
        commands.update(_extract_commands_from_elf(file_path))

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

    logger.debug(
        f"Looking for IOC binary '{app_name}' in {bin_dir} for dbd at {dbd_path}"
    )

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
    return candidate


def consume_iocsh_command(line: str, current_state: IocshState) -> None:
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
            logger.info(f"Set macro: {key} = {value}")
        else:
            logger.error(
                f"Invalid epicsEnvSet command, expected at least 2 args: {line}"
            )

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
            dbd_record_types = (
                set(current_state.dbd.record_types.keys())
                if current_state.dbd
                else None
            )
            search_path = _get_db_search_path(current_state)
            db = load_database_file(
                db_path,
                macros=combined_macros,
                search_path=search_path,
                load_includes_strategy=LoadIncludesStrategy.LOAD_INTO_SELF,
                allow_unmatched_macros=True,
                valid_record_types=dbd_record_types,
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
                expanded_file = _expand_macros(str(sub.file), current_state.macros)
                template_path = _resolve_file_path(Path(expanded_file), current_state)
                if not template_path.exists():
                    raise FileNotFoundError(f"Template file not found: {template_path}")
                logger.debug(
                    f"Loading template file: {template_path} with macros: {sub.macros}"
                )
                dbd_record_types = (
                    set(current_state.dbd.record_types.keys())
                    if current_state.dbd
                    else None
                )
                search_path = _get_db_search_path(current_state)
                db = load_database_file(
                    template_path,
                    macros=combined_macros,
                    search_path=search_path,
                    load_includes_strategy=LoadIncludesStrategy.IGNORE,
                    valid_record_types=dbd_record_types,
                )
                current_state.databases.append(db)

    else:
        if command.endswith("_registerRecordDeviceDriver"):
            # Only scan for commands if not already discovered (via user-supplied
            # binary_path or shebang detection)
            if not current_state.registered_commands:
                app_name = command[: -len("_registerRecordDeviceDriver")]
                if current_state.dbd_path is not None:
                    binary_path = _find_ioc_binary(app_name, current_state.dbd_path)
                    if binary_path is not None:
                        logger.info(
                            "Scanning IOC binary '%s' for registered commands",
                            binary_path,
                        )
                        discovered_iocsh_commands = _discover_commands_from_binary(
                            binary_path
                        )
                        for cmd, nargs in discovered_iocsh_commands.items():
                            logger.info(
                                "Discovered iocsh command from binary: %s(%s args)",
                                cmd,
                                nargs,
                            )
                        current_state.registered_commands.update(
                            discovered_iocsh_commands
                        )
                    else:
                        logger.warning(
                            f"Could not find IOC binary for '{app_name}'; "
                            f"commands from registrars will not be validated"
                        )
                else:
                    logger.warning(
                        f"No dbd path available to locate IOC binary for '{app_name}'"
                    )
            elif command not in current_state.registered_commands:
                logger.warning(
                    f"Command '{command}' not found in the discovered binary commands; "
                    f"the specified binary may not match this IOC"
                )
        current_state.other_commands.append(IocshCommand(name=command, args=args))


def load_iocsh_file(
    filepath: Path,
    macros: dict[str, str] | None = None,
    resolve_sources: bool = True,
    binary_path: Path | None = None,
    _parent_state: IocshState | None = None,
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
    binary_path : Path, optional
        Explicit path to the IOC binary for command discovery. If not provided,
        the binary is auto-detected from a shebang line (e.g. #!/path/to/binary)
        or from the *_registerRecordDeviceDriver command.

    Returns
    -------
    IocshState
        The accumulated state after processing all commands.
    """
    logger.info(f"Loading IOC shell file: {filepath}")
    state = IocshState(macros=dict(macros) if macros else {})
    if _parent_state is not None:
        if _parent_state.dbd is not None:
            state.dbd = _parent_state.dbd
        if _parent_state.dbd_path is not None:
            state.dbd_path = _parent_state.dbd_path
        state.registered_commands.update(_parent_state.registered_commands)
    filepath = Path(filepath).resolve()

    if not filepath.exists():
        raise FileNotFoundError(f"IOC shell startup file not found: {filepath}")

    base_dir = filepath.parent
    # Set the cwd to the directory containing the startup script
    if state.cwd is None:
        state.cwd = base_dir

    # If binary_path provided explicitly, scan it immediately
    if binary_path is not None:
        binary_path = Path(binary_path)
        if binary_path.exists():
            logger.info(f"Scanning user-specified IOC binary: {binary_path}")
            discovered = _discover_commands_from_binary(binary_path)
            for cmd, nargs in discovered.items():
                logger.info(
                    f"Discovered iocsh command from binary: {cmd}({nargs} args)"
                )
            state.registered_commands.update(discovered)
        else:
            logger.warning(f"Specified binary path does not exist: {binary_path}")

    with open(filepath) as f:
        first_line = True
        for raw_line in f:
            line = raw_line.strip()

            # Check for shebang on the first line
            if first_line:
                first_line = False
                if line.startswith("#!") and binary_path is None:
                    shebang_binary = Path(line[2:].strip())
                    if not shebang_binary.is_absolute():
                        shebang_binary = base_dir / shebang_binary
                    if shebang_binary.exists():
                        logger.info(
                            f"Detected IOC binary from shebang: {shebang_binary}"
                        )
                        discovered = _discover_commands_from_binary(shebang_binary)
                        for cmd, nargs in discovered.items():
                            logger.info(
                                "Discovered iocsh command from binary: %s(%s args)",
                                cmd,
                                nargs,
                            )
                        state.registered_commands.update(discovered)
                    else:
                        logger.debug(f"Shebang binary not found: {shebang_binary}")
                    continue

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
                        _parent_state=state,
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
                            _parent_state=state,
                        )
                        state.update(child_state)
                    else:
                        raise FileNotFoundError(
                            f"Sourced script not found: {script_path}"
                        )
            else:
                consume_iocsh_command(expanded_line, state)

    # Load protocol files referenced by StreamDevice records
    _load_stream_protocol_files(state)

    return state


def _load_stream_protocol_files(state: IocshState) -> None:
    """Scan databases for StreamDevice records and load referenced protocol files.

    Searches for protocol files in the directories listed in the
    STREAM_PROTOCOL_PATH macro/environment variable. Relative paths are
    resolved against the IOC's current working directory.
    """
    stream_protocol_path = state.macros.get("STREAM_PROTOCOL_PATH", "")
    if not stream_protocol_path:
        return

    search_dirs: list[Path] = []
    for dir_str in stream_protocol_path.split(":"):
        dir_str = dir_str.strip()
        if dir_str:
            p = Path(dir_str)
            if not p.is_absolute() and state.cwd is not None:
                p = state.cwd / p
            if p.is_dir():
                search_dirs.append(p)

    if not search_dirs:
        return

    # Collect all referenced proto filenames from stream records
    proto_filenames: set[str] = set()
    stream_link_re = re.compile(r"@(\S+\.proto)\s+")
    for db in state.databases:
        for record in db.values():
            dtyp = record.fields.get("DTYP", "")
            if not isinstance(dtyp, str) or dtyp.lower() != "stream":
                continue
            for field_name in ("INP", "OUT"):
                link_value = record.fields.get(field_name)
                if not isinstance(link_value, str):
                    continue
                m = stream_link_re.search(link_value)
                if m:
                    proto_filenames.add(m.group(1))

    # Load each referenced protocol file
    for proto_filename in proto_filenames:
        if proto_filename in state.protocol_files:
            continue
        for search_dir in search_dirs:
            proto_path = search_dir / proto_filename
            if proto_path.is_file():
                try:
                    state.protocol_files[proto_filename] = load_protocol_file(
                        proto_path
                    )
                    logger.info(f"Loaded protocol file: {proto_path}")
                except Exception as e:
                    logger.warning(f"Failed to parse protocol file '{proto_path}': {e}")
                break
        else:
            logger.warning(
                f"Protocol file '{proto_filename}' not found in "
                f"STREAM_PROTOCOL_PATH: {stream_protocol_path}"
            )
