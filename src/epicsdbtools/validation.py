"""Validation for EPICS databases against database definitions (.dbd files).

Checks that:
- Record types used in .db files exist in the database definition
- Fields used in records are valid for their record type
- DTYP values are valid device support choices for the given record type
- iocsh commands correspond to registered functions/registrars in the dbd
- No unexpanded macros remain in the IOC state
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
        parts = [f"[{self.severity.value.upper()}]"]
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
        rtype_name = record.rtype.value

        # Check record type exists in dbd
        rtype_def = dbd.record_types.get(rtype_name)
        if rtype_def is None:
            result.add_error(
                f"Record type '{rtype_name}' not found in database definition",
                record_name=record.name,
            )
            continue

        # Check each field exists in the record type definition
        for field_name, field_value in record.fields.items():
            if field_name not in rtype_def.fields:
                result.add_error(
                    f"Field '{field_name}' does not exist in record type '{rtype_name}'",
                    record_name=record.name,
                    field_name=field_name,
                )

        # Check DTYP validity
        dtyp_value = record.fields.get("DTYP")
        if dtyp_value is not None:
            valid_dtyps = dtyp_choices.get(rtype_name, set())
            if valid_dtyps and dtyp_value not in valid_dtyps:
                result.add_error(
                    f"DTYP '{dtyp_value}' is not a valid device support "
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
                        f"Unexpanded macro(s) in field value: "
                        f"{', '.join(unresolved)}",
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
    state: IocshState, dbd: DatabaseDefinition | None = None
) -> ValidationResult:
    """Validate iocsh commands against a database definition.

    Checks that non-built-in commands correspond to functions or registrars
    declared in the database definition.

    Parameters
    ----------
    state : IocshState
        The parsed IOC shell state containing commands to validate.
    dbd : DatabaseDefinition, optional
        The database definition to check commands against. If None, uses
        state.dbd if available.

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
            result.add_warning(
                f"Command '{cmd.name}' is not a built-in iocsh command and "
                f"was not found in the database definition's registered "
                f"functions or registrars"
            )

    return result


def validate_ioc(state: IocshState) -> ValidationResult:
    """Perform full validation of an IOC state.

    Validates unexpanded macros, iocsh commands, and all loaded databases
    against the database definition if one has been loaded.

    Parameters
    ----------
    state : IocshState
        The fully parsed IOC shell state.

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
    cmd_result = validate_iocsh_commands(state)
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
            f"IOC validation failed with {len(result.errors)} error(s):\n"
            f"{error_msgs}"
        )
    return result
