#!/usr/bin/env python3

import argparse
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .database import Database, LoadIncludesStrategy, load_database_file
from .log import logger


class ParamType(Enum):
    INT = "asynInt32"
    DOUBLE = "asynFloat64"
    STRINGIN = "asynOctetRead"
    STRINGOUT = "asynOctetWrite"


@dataclass(frozen=True)
class ParamDef:
    record_str: str
    name: str
    type: ParamType


def get_internal_param_type_from_dtyp(dtyp: ParamType) -> str:
    if dtyp in [ParamType.STRINGIN, ParamType.STRINGOUT]:
        return "asynParamOctet"
    else:
        return "asynParam" + dtyp.value.split("asyn")[-1]


def get_params_from_db(database: Database, base_name: str) -> list[ParamDef]:
    params = {}
    for record in database.values():
        for field_name in ["OUT", "INP"]:
            if field_name in record.fields:
                param_string = record.fields[field_name].rsplit(")", 1)[-1]
                param_suffix = "".join(
                    [p.lower().capitalize() for p in param_string.split("_")[1:]]
                )
                param_name = f"{base_name}_{param_suffix}"
                if param_name not in params:
                    logger.debug(
                        f"Found param: {param_string} of type {record.fields['DTYP']}"
                    )
                    params[param_name] = ParamDef(
                        record_str=param_string,
                        name=param_name,
                        type=ParamType(record.fields["DTYP"]),
                    )
                else:
                    logger.debug(
                        f"Param {param_name} already defined, skipping duplicate."
                    )
    return list(params.values())


def generate_header_file_for_db(
    params: list[ParamDef], output_path: Path, base_name: str
):
    header_file = output_path / f"{base_name}ParamDefs.h"
    logger.info(f"Generating header file {header_file} for {len(params)} params")

    with open(header_file, "w") as hf:
        hf.write(f"#ifndef {base_name.upper()}_PARAM_DEFS_H\n")
        hf.write(f"#define {base_name.upper()}_PARAM_DEFS_H\n\n")
        hf.write("// This file is auto-generated. Do not edit directly.\n")
        hf.write(f"// Generated from {base_name}.template\n\n")

        hf.write("// String definitions for parameters\n")
        for param in params:
            logger.debug("Defining string for param: %s", param.name)
            hf.write(f'#define {param.name}String "{param.record_str}"\n')
        hf.write("\n")

        hf.write("// Parameter index definitions\n")
        for param in params:
            logger.debug("Defining index for param: %s", param.name)
            hf.write(f"int {param.name};\n")

        if len(params) > 0:
            hf.write(f"\n#define {base_name.upper()}_FIRST_PARAM {list(params)[0].name}\n")
            hf.write(f"#define {base_name.upper()}_LAST_PARAM {list(params)[-1].name}\n\n")
        hf.write(
            f"#define NUM_{base_name.upper()}_PARAMS {len(params)}\n\n"
        )
        hf.write("#endif\n")


def generate_cpp_file_for_db(params: list[ParamDef], output_path: Path, base_name: str):
    cpp_file = output_path / f"{base_name}ParamDefs.cpp"
    logger.info(f"Generating cpp file {cpp_file} for {len(params)} params")

    with open(cpp_file, "w") as cf:
        cf.write("// This file is auto-generated. Do not edit directly.\n")
        cf.write(f"// Generated from {base_name}.template\n\n")
        cf.write(f'#include "{base_name}.h"\n\n')
        cf.write(f"void {base_name}::createAllParams() {{\n")
        for param in params:
            logger.debug(f"Creating param: {param.name}")
            cf.write(
                f"    createParam({param.name}String, {get_internal_param_type_from_dtyp(param.type)}, &{param.name});\n"  # noqa E501
            )
        cf.write("}\n")


def generate_param_defs_cli():
    parser = argparse.ArgumentParser(
        description="Generate asyn parameter definitions from EPICS DB template."
    )
    parser.add_argument(
        "input_path",
        help="Path to the EPICS DB template file, or directory containing it.",
    )
    parser.add_argument(
        "output_path", help="Directory to save the generated header and source files."
    )
    parser.add_argument("-f", "--filename", help="Base name for generated files.")
    parser.add_argument(
        "-m", "--macros", nargs="*", help="Optional macros to apply to the template."
    )

    args = parser.parse_args()

    template_files = (
        [args.input_path]
        if os.path.isfile(args.input_path)
        else [
            os.path.join(args.input_path, f)
            for f in os.listdir(args.input_path)
            if f.endswith(".template")
        ]
    )
    output_path = Path(args.output_path)
    for template_file in template_files:
        base_name = (
            args.filename
            if args.filename
            else os.path.splitext(os.path.basename(template_file))[0]
        )
        database = load_database_file(
            Path(template_file), load_includes_strategy=LoadIncludesStrategy.IGNORE
        )
        params = get_params_from_db(database, base_name)
        for param in params:
            logger.info(
                f"Param: {param.name}, Type: {param.type}, Record: {param.record_str}"
            )
        generate_header_file_for_db(params, output_path, base_name)
        generate_cpp_file_for_db(params, output_path, base_name)


if __name__ == "__main__":
    generate_param_defs_cli()
