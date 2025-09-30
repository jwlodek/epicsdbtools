#!/usr/bin/env python
from __future__ import print_function

import collections
import os
from io import StringIO
import warnings

from .tokenizer import Tokenizer
from .macro import expand_macros, split_macros


class DatabaseException(Exception):
    def __init__(self, msg: str):
        self.msg = msg

    def __str__(self) -> str:
        return self.msg

    
class Record:
    def __init__(self):
        self.name = None
        self.rtyp = None
        self.infos = collections.OrderedDict()
        self.fields = collections.OrderedDict()
        self.aliases = []

    def __bool__(self) -> bool:
        return self.name != None and self.rtyp != None

    def __repr__(self) -> str:
        repr = 'record ({0}, "{1}")\n'.format(self.rtyp, self.name)
        repr += '{\n'
        for field, value in self.fields.items():
            repr += '    field({0:4}, "{1}")\n'.format(field, value)
        for field, value in self.infos.items():
            repr += '    info({0}, "{1}")\n'.format(field, value)
        for alias in self.aliases:
            repr += '    alias({0})\n'.format(alias)
        repr += '}'
        return repr

    def is_valid(self) -> bool:
        """
        Valid record has defined name and type.
        """
        return self.name and self.rtyp

    def merge(self, another) -> None:
        """
        Merge fields, infos, aliases from another record instance.
        """
        self.fields.update(another.fields)
        self.infos.update(another.infos)
        self.aliases.extend(another.aliases)


class Database(collections.OrderedDict[str, Record]):
    def __init__(self):
        super(Database, self).__init__()

    def __repr__(self) -> str:
        msg = []
        for record in self.values():
            msg.append(repr(record))
        return '\n'.join(msg)

    def add_record(self, record: Record) -> None:
        if not record.is_valid():
            return

        record_existed = self.get(record.name)
        if record_existed:
            if record_existed.rtyp != record.rtyp:
                raise DatabaseException('Reappearing record "%s" with conflicting record type "%s"'
                        %(record.name, record.rtyp))
            else:
                warnings.warn('Merging record "%s"' % (record.name), stacklevel=2)
                record_existed.merge(record)
        else:
            self[record.name] = record

    def get_records_by_type(self, rtyp: str) -> list[Record]:
        records = []
        for record in self.values():
            if record.rtyp == rtyp:
                records.append(record)
        return records

    def get_records_by_info(self, info: str, value: str) -> list[Record]:
        records = []
        for record in self.values():
            if info in record.infos and record.infos.get(info) == value:
                records.append(record)
        return records

    def filter_records_by_info(self, info: str, value: str) -> list[Record]:
        records = []
        for record in self.values():
            if info not in record.infos or record.infos.get(info) != value:
                records.append(record)
        return records

    def update(self, database: collections.OrderedDict[str, Record]) -> None:
        for record in database.values():
            self.add_record(record)
 

def parse_pair(src: str) -> tuple[str, str]:
    """
    parse '(field, "value")' definition to tuple (field, value)
    """
    token = next(src)
    if token != '(':
        return None, None
    token = next(src)
    field = token
    token = next(src)
    if token == ')':
        return field, None
    elif token != ',':
        return None, None
    token = next(src)
    value = token
    token = next(src)
    if token != ')':
        return None, None
    return field, value


def parse_record(src: str) -> Record:
    """
    :param iter src: token generator
    """
    record = Record()

    record.rtyp, record.name = parse_pair(src)

    token = next(src)
    while True:
        if token == '}':
            break

        elif token == 'field':
            field, value = parse_pair(src)
            record.fields[field] = value
        elif token == 'info':
            field, value = parse_pair(src)
            record.infos[field] = value
        elif token == 'alias':
            record.aliases.append(parse_pair(src))

        token = next(src)

    return record


def find_database_file(filename: str, includes: list[str]) -> str:
    if not os.path.isabs(filename):
        for include in includes:
            path = os.path.join(include, filename)
            if os.path.exists(path):
                filename = path
                break
    return filename


def load_database_file(filename: str, macros: dict[str, str]=None, includes: list[str]=[], encoding: str='utf8') -> Database:
    """
    :param str filename: EPICS database filename
    :return: list of record dict
    :rtype: list of dicts
    """
    # search filename through include directories
    filename = find_database_file(filename, includes)

    database = Database()

    # read line by line and expand macros
    lineno = 1
    lines = []
    failed = False
    for line in open(filename, encoding=encoding):
        if macros is not None:
            expanded, unmatched = expand_macros(line, macros)
            if unmatched:
                failed = True
                print('{0}:{1}: macro "{2}" is undefined ({3})'.format(
                    os.path.basename(filename), 
                    lineno, 
                    '" "'.join(unmatched), 
                    line.strip()))
            else:
                lines.append(expanded)
        else:
            lines.append(line)
        lineno += 1
    
    if failed:
        return database

    # parse record instances
    src = iter(Tokenizer(StringIO(''.join(lines)), filename))
    while True:
        try:
            token = next(src)
        except StopIteration:
            break

        if token == 'record' or token == 'grecord':
            database.add_record(parse_record(src))
        elif token == 'alias':
            record_name, alias_name = parse_pair(src)
            database[alias_name] = database[record_name]
        elif token == 'include':
            inclusion = next(src)
            extended_includes = set(includes)
            extended_includes.add(os.path.dirname(filename))
            for record in load_database_file(inclusion, macros, extended_includes).values():
                database.add_record(record)

    return database


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-m', '--macro',
            help='macro substitution')
    parser.add_argument(
            '-I',
            action = 'append',
            dest = 'includes',
            default = [],
            help = 'template include paths')
    parser.add_argument(
            '--encoding',
            default='utf8',
            help = 'files encoding')
    parser.add_argument(
            dest = 'database_files',
            nargs = '+',
            help='database files')
    args = parser.parse_args()

    macros = None
    if args.macro:
        macros = split_macros(args.macro)

    for file in args.database_files:
        if os.path.exists(file):
            database = load_database_file(file, macros, args.includes, args.encoding)
            print(database) 
