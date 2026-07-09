"""Validation for EPICS databases against database definitions (.dbd files).

Checks that:
- Record types used in .db files exist in the database definition
- Fields used in records are valid for their record type
- DTYP values are valid device support choices for the given record type
- iocsh commands correspond to registered functions/registrars in the dbd
- No unexpanded macros remain in the IOC state
- StreamDevice protocol references are valid
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .log import logger
from .macro import MACRO_REGEX
from .parsers.database import Database, DatabaseException
from .parsers.database_definition import DatabaseDefinition
from .parsers.iocsh import IocshState
from .parsers.proto import ProtocolFile

# Define color codes as constants for readability
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
RESET = "\033[0m"  # Resets the color to default


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class ValidationMessage:
    severity: ValidationSeverity
    message: str
    record_name: str | None = None
    field_name: str | None = None

    def __str__(self) -> str:
        parts: list[str] = [f"[{self.severity.value.upper()}]"]
        if self.record_name:
            parts.append(f"record '{self.record_name}'")
        if self.field_name:
            parts.append(f"field '{self.field_name}'")
        parts.append(self.message)
        return " ".join(parts)


@dataclass
class ValidationResult:
    messages: list[ValidationMessage] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.severity == ValidationSeverity.WARNING]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(
        self,
        message: str,
        record_name: str | None = None,
        field_name: str | None = None,
    ) -> None:
        self.messages.append(
            ValidationMessage(
                severity=ValidationSeverity.ERROR,
                message=message,
                record_name=record_name,
                field_name=field_name,
            )
        )

    def add_warning(
        self,
        message: str,
        record_name: str | None = None,
        field_name: str | None = None,
    ) -> None:
        self.messages.append(
            ValidationMessage(
                severity=ValidationSeverity.WARNING,
                message=message,
                record_name=record_name,
                field_name=field_name,
            )
        )

    def __str__(self) -> str:
        out = "Validation Result: "
        if self.is_valid:
            out += f"{GREEN}PASSED{RESET}"
        else:
            out += f"{RED}FAILED{RESET}"
        out += f"\nErrors: {len(self.errors)}\nWarnings: {len(self.warnings)}"
        for message in self.messages:
            color = RED if message.severity == ValidationSeverity.ERROR else YELLOW
            out += f"\n{color}{message}{RESET}"
        return out


def validate_database(db: Database, dbd: DatabaseDefinition) -> ValidationResult:
    """Validate a database against a database definition.

    Checks:
    - Record type exists in the dbd
    - All fields used exist in the record type definition
    - DTYP values correspond to valid device support for the record type

    Parameters
    ----------
    db : Database
        The parsed database (.db file) to validate.
    dbd : DatabaseDefinition
        The database definition (.dbd file) to validate against.

    Returns
    -------
    ValidationResult
        Collection of errors and warnings found during validation.
    """
    result = ValidationResult()

    # Build a lookup of valid DTYP choices per record type
    dtyp_choices: dict[str, set[str]] = {}
    for device in dbd.devices:
        dtyp_choices.setdefault(device.record_type, set()).add(device.choice_string)

    for record in db.values():
        rtype_name = record.rtype_name

        # Check record type exists in dbd
        rtype_def = dbd.record_types.get(rtype_name)
        if rtype_def is None:
            dtyp_val = record.fields.get("DTYP")
            result.add_error(
                f"Record type '{rtype_name}' for DTYP "
                f"'{dtyp_val}' not found in database definition",
                record_name=record.name,
            )
            continue

        # Check each field exists in the record type definition
        for field_name, _field_value in record.fields.items():
            if field_name not in rtype_def.fields:
                result.add_error(
                    f"does not exist in record type '{rtype_name}'",
                    record_name=record.name,
                    field_name=field_name,
                )

        # Check DTYP validity
        dtyp_value = record.fields.get("DTYP")
        if dtyp_value is not None:
            valid_dtyps = dtyp_choices.get(rtype_name, set())
            if valid_dtyps and dtyp_value not in valid_dtyps:
                result.add_error(
                    f"'{dtyp_value}' is not a valid device support "
                    f"choice for record type '{rtype_name}'. "
                    f"Valid choices: {sorted(valid_dtyps)}",
                    record_name=record.name,
                    field_name="DTYP",
                )

    return result


def _find_unexpanded_macros(text: str) -> list[str]:
    """Find all unexpanded macro references in a string."""
    return [m.group(1) for m in MACRO_REGEX.finditer(text)]


def validate_macros(state: IocshState) -> ValidationResult:
    """Validate that no unexpanded macros remain in the IOC state.

    Checks record names, field values, and command arguments for any
    remaining $(MACRO) references that were not resolved during parsing.

    Parameters
    ----------
    state : IocshState
        The parsed IOC shell state to check.

    Returns
    -------
    ValidationResult
        Collection of errors for any unexpanded macros found.
    """
    result = ValidationResult()

    # Check macro values for unexpanded macros
    for macro_name, macro_value in state.macros.items():
        unresolved = _find_unexpanded_macros(macro_value)
        if unresolved:
            result.add_error(
                f"Unexpanded macro(s) in value of '{macro_name}': "
                f"{', '.join(unresolved)}",
            )

    # Check databases for unexpanded macros in record names and field values
    for db in state.databases:
        for record in db.values():
            # Check record name
            unresolved = _find_unexpanded_macros(record.name)
            if unresolved:
                result.add_error(
                    f"Unexpanded macro(s) in record name: {', '.join(unresolved)}",
                    record_name=record.name,
                )

            # Check field values
            for field_name, field_value in record.fields.items():
                unresolved = _find_unexpanded_macros(str(field_value))
                if unresolved:
                    result.add_error(
                        f"Unexpanded macro(s) in field value: {', '.join(unresolved)}",
                        record_name=record.name,
                        field_name=field_name,
                    )

    # Check other commands for unexpanded macros in arguments
    for cmd in state.other_commands:
        for arg in cmd.args:
            unresolved = _find_unexpanded_macros(arg)
            if unresolved:
                result.add_error(
                    f"Unexpanded macro(s) in argument to '{cmd.name}': "
                    f"{', '.join(unresolved)}",
                )

    return result


# Regex for parsing StreamDevice INP/OUT link format:
# @filename.proto protocol_name(arg1, arg2, ...) port
# The arguments are optional.
_STREAM_LINK_RE = re.compile(
    r"@(?P<file>\S+\.proto)\s+(?P<protocol>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"(?:\((?P<args>[^)]*)\))?"
)


def _parse_stream_link(link_value: str) -> tuple[str, str, list[str]] | None:
    """Parse a StreamDevice INP/OUT link value.

    Parameters
    ----------
    link_value : str
        The INP or OUT field value.

    Returns
    -------
    tuple[str, str, list[str]] | None
        A tuple of (proto_filename, protocol_name, arguments), or None
        if the link is not a StreamDevice link.
    """
    m = _STREAM_LINK_RE.search(link_value)
    if m is None:
        return None
    proto_file = m.group("file")
    protocol_name = m.group("protocol")
    args_str = m.group("args")
    if args_str:
        args = [a.strip() for a in args_str.split(",")]
    else:
        args = []
    return proto_file, protocol_name, args


# Mapping of record types to the set of compatible Python types for format converters.
# Records not listed here are not checked (e.g. waveform depends on FTVL).
_RECORD_TYPE_CONVERTER_TYPES: dict[str, set[type]] = {
    # Analog records: accept numeric types
    "ai": {int, float},
    "ao": {int, float},
    "calc": {int, float},
    "calcout": {int, float},
    "sel": {int, float},
    "sub": {int, float},
    "dfanout": {int, float},
    # Integer records: accept integer types
    "longin": {int},
    "longout": {int},
    "int64in": {int},
    "int64out": {int},
    # Binary/enum records: accept int (enum converters also map to int)
    "bi": {int},
    "bo": {int},
    "mbbi": {int},
    "mbbo": {int},
    "mbbidirect": {int},
    "mbbodirect": {int},
    # String records: accept string types
    "stringin": {str},
    "stringout": {str},
    "lsi": {str},
    "lso": {str},
}


def validate_stream_protocols(
    databases: list[Database],
    protocol_files: dict[str, ProtocolFile],
) -> ValidationResult:
    """Validate StreamDevice protocol references in database records.

    For each record with ``DTYP = "stream"`` (case-insensitive), extracts
    the protocol file and function from the ``INP`` or ``OUT`` field and checks:
    - The referenced protocol file exists in the provided set
    - The referenced protocol function exists in that file
    - The number of arguments matches the protocol's expected parameter count
    - The ``out`` command has format converters appropriate for output records
    - The ``in`` command has format converters appropriate for input records
    - The format converter type is compatible with the record type

    Parameters
    ----------
    databases : list[Database]
        The loaded databases to check.
    protocol_files : dict[str, ProtocolFile]
        Mapping of protocol filenames to their parsed contents.

    Returns
    -------
    ValidationResult
        Collection of errors and warnings found during validation.
    """
    result = ValidationResult()

    for db in databases:
        for record in db.values():
            dtyp = record.fields.get("DTYP", "")
            if not isinstance(dtyp, str) or dtyp.lower() != "stream":
                continue

            # Check INP and OUT fields for stream links
            for field_name in ("INP", "OUT"):
                link_value = record.fields.get(field_name)
                if link_value is None:
                    continue
                if not isinstance(link_value, str):
                    continue

                parsed = _parse_stream_link(link_value)
                if parsed is None:
                    result.add_warning(
                        f"Could not parse StreamDevice link: '{link_value}'",
                        record_name=record.name,
                        field_name=field_name,
                    )
                    continue

                proto_filename, protocol_name, args = parsed

                # Check protocol file exists
                if proto_filename not in protocol_files:
                    result.add_error(
                        f"Protocol file '{proto_filename}' not found in "
                        f"STREAM_PROTOCOL_PATH",
                        record_name=record.name,
                        field_name=field_name,
                    )
                    continue

                proto_file = protocol_files[proto_filename]
                protocol = proto_file.get_protocol(protocol_name)

                # Check protocol function exists
                if protocol is None:
                    result.add_error(
                        f"Protocol '{protocol_name}' not found in '{proto_filename}'",
                        record_name=record.name,
                        field_name=field_name,
                    )
                    continue

                # Check argument count
                expected_params = protocol.num_parameters
                actual_args = len(args)
                if expected_params > 0 and actual_args != expected_params:
                    result.add_error(
                        f"Protocol '{protocol_name}' expects "
                        f"{expected_params} argument(s) but "
                        f"{actual_args} provided",
                        record_name=record.name,
                        field_name=field_name,
                    )

                # Validate that output records have an out converter
                if field_name == "OUT":
                    out_convs = [c for c in protocol.out_converters if not c.skip]
                    if protocol.out_format is not None and not out_convs:
                        result.add_warning(
                            f"Protocol '{protocol_name}' out command has "
                            f"no format converters for record value",
                            record_name=record.name,
                            field_name=field_name,
                        )

                # Validate that input records have an in converter
                if field_name == "INP":
                    in_convs = [c for c in protocol.in_converters if not c.skip]
                    if protocol.in_format is not None and not in_convs:
                        result.add_warning(
                            f"Protocol '{protocol_name}' in command has "
                            f"no format converters for record value",
                            record_name=record.name,
                            field_name=field_name,
                        )

                # Validate format converter compatibility with record type
                rtype = record.rtype_name.lower()
                if rtype in _RECORD_TYPE_CONVERTER_TYPES:
                    allowed = _RECORD_TYPE_CONVERTER_TYPES[rtype]
                    # Check the primary converter (first non-skip) for the
                    # relevant direction
                    if field_name == "INP":
                        convs = [c for c in protocol.in_converters if not c.skip]
                    else:
                        convs = [c for c in protocol.out_converters if not c.skip]
                    if convs:
                        converter = convs[0]
                        if converter.value_type not in allowed:
                            allowed_names = sorted(t.__name__ for t in allowed)
                            result.add_error(
                                f"Format converter "
                                f"'%{converter.conversion}' "
                                f"(type "
                                f"'{converter.value_type.__name__}'"
                                f") is not compatible with record"
                                f" type '{record.rtype_name}'. "
                                f"Expected one of: {allowed_names}",
                                record_name=record.name,
                                field_name=field_name,
                            )

    return result


BUILTIN_IOCSH_COMMANDS = frozenset(
    {
        "cd",
        "chdir",
        "dbLoadDatabase",
        "dbLoadRecords",
        "dbLoadTemplate",
        "dbl",
        "dbnr",
        "dbpr",
        "dbpf",
        "dbgf",
        "dbgrep",
        "dbior",
        "dbhcr",
        "dbtr",
        "dbtgf",
        "dbtpf",
        "dba",
        "dbap",
        "dbcar",
        "dbstat",
        "epicsEnvSet",
        "epicsEnvShow",
        "epicsEnvUnset",
        "epicsPrtEnvParams",
        "epicsThreadSleep",
        "exit",
        "help",
        "iocInit",
        "iocBuild",
        "iocRun",
        "iocPause",
        "iocshLoad",
        "iocshRun",
        "iocLogInit",
        "require",
        "var",
        "system",
        "taskwdShow",
        "callbackParallelThreads",
        "callbackQueueShow",
        "scanppl",
        "scanOnceSetQueueSize",
        "errlogInit",
        "errLogInit",
        "eltc",
        "errlog",
        "ClockTime_Report",
        "generalTimeReport",
    }
)


def validate_iocsh_commands(
    state: IocshState, dbd: DatabaseDefinition | None = None, strict: bool = False
) -> ValidationResult:
    """Validate iocsh commands against a database definition.

    Checks that non-built-in commands correspond to functions or registrars
    declared in the database definition. Also validates that commands are called
    with the correct number of arguments when nargs information is available.

    Parameters
    ----------
    state : IocshState
        The parsed IOC shell state containing commands to validate.
    dbd : DatabaseDefinition, optional
        The database definition to check commands against. If None, uses
        state.dbd if available.
    strict : bool, optional
        If True, unknown commands are reported as errors instead of warnings.

    Returns
    -------
    ValidationResult
        Collection of errors and warnings found during validation.
    """
    result = ValidationResult()

    if dbd is None:
        dbd = state.dbd

    if dbd is None:
        result.add_warning("No database definition loaded; cannot validate commands")
        return result

    # Collect all registered command names from dbd
    registered_commands = set(dbd.functions) | set(dbd.registrars)
    # Include commands discovered from the IOC binary
    registered_commands |= set(state.registered_commands.keys())

    for cmd in state.other_commands:
        if cmd.name in BUILTIN_IOCSH_COMMANDS:
            continue
        if cmd.name.endswith("_registerRecordDeviceDriver"):
            continue
        if cmd.name not in registered_commands:
            msg = (
                f"Command '{cmd.name}' is not a built-in iocsh command and "
                f"was not found in the database definition's registered "
                f"functions or registrars"
            )
            if strict:
                result.add_error(msg)
            else:
                result.add_warning(msg)
        elif cmd.name in state.registered_commands:
            expected_nargs = state.registered_commands[cmd.name]
            actual_nargs = len(cmd.args)
            if actual_nargs > expected_nargs:
                result.add_error(
                    f"Command '{cmd.name}' called with {actual_nargs} argument(s), "
                    f"but expects at most {expected_nargs}"
                )

    return result


def validate_ioc(state: IocshState, strict: bool = False) -> ValidationResult:
    """Perform full validation of an IOC state.

    Validates unexpanded macros, iocsh commands, and all loaded databases
    against the database definition if one has been loaded.

    Parameters
    ----------
    state : IocshState
        The fully parsed IOC shell state.
    strict : bool, optional
        If True, unknown commands are reported as errors instead of warnings.

    Returns
    -------
    ValidationResult
        Combined validation results.
    """
    result = ValidationResult()

    # Validate unexpanded macros
    macro_result = validate_macros(state)
    result.messages.extend(macro_result.messages)

    # Validate commands against dbd
    cmd_result = validate_iocsh_commands(state, strict=strict)
    result.messages.extend(cmd_result.messages)

    # Validate databases against dbd
    if state.dbd is not None:
        for db in state.databases:
            db_result = validate_database(db, state.dbd)
            result.messages.extend(db_result.messages)
    else:
        if state.databases:
            result.add_warning(
                "No database definition loaded; cannot validate database records"
            )

    # Validate StreamDevice protocol references
    proto_result = validate_stream_protocols(state.databases, state.protocol_files)
    result.messages.extend(proto_result.messages)

    if result.is_valid:
        logger.info("IOC validation passed with no errors")
    else:
        logger.error(f"IOC validation found {len(result.errors)} error(s)")

    return result


def validate_ioc_or_raise(state: IocshState) -> ValidationResult:
    """Validate an IOC state and raise on errors.

    Convenience wrapper around validate_ioc that raises a DatabaseException
    if any validation errors are found.

    Parameters
    ----------
    state : IocshState
        The fully parsed IOC shell state.

    Returns
    -------
    ValidationResult
        The validation result (only returned if no errors).

    Raises
    ------
    DatabaseException
        If the validation produces any errors.
    """

    result = validate_ioc(state)
    if not result.is_valid:
        error_msgs = "\n".join(f"  {msg}" for msg in result.errors)
        raise DatabaseException(
            f"IOC validation failed with {len(result.errors)} error(s):\n{error_msgs}"
        )
    return result
