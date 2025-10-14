from __future__ import print_function
import sys

from .tokenizer import tokenizer

def parse_filename(src):
    filename = None

    token = next(src)
    while True:
        if token == '{':
            break
        filename = token

        token = next(src)

    return filename


def parse_pattern_macros(src):
    macros = []

    token = next(src)
    while True:
        if token == '}':
            break

        if token != ',':
            macros.append(token)

        token = next(src)

    return macros


def parse_pattern_values(src):
    values = []

    token = next(src)
    while True:
        if token == '}':
            break

        if token != ',':
            values.append(token)

        token = next(src)

    return values


def parse_macro_value(src):
    macros = []
    values = []
    
    equal = False
    token = next(src)
    while True:
        if token == '}':
            break

        if token == '=':
            equal = True
        elif token == ',':
            equal = False
        else:
            if equal:
                values.append(token)
                equal = False
            else:
                macros.append(token)

        token = next(src)

    return macros, values

NEUTRAL = 0
GLOBAL = 1
FILE = 2
PATTERN = 3
SUBS = 4

def parse_template(source):
    """
    :param buffer source: EPICS substitutes
    :return: list of (filename, macros, values)
    """
    files = []

    src = iter(tokenizer(source))

    global_macros = {}
    saved_state = state = NEUTRAL
    while True:
        try:
            token = next(src)
        except StopIteration:
            break
        if state == NEUTRAL:
            if token == 'file':
                filename = parse_filename(src)
                pattern_macros = None
                file_global_macros = {}
                saved_state = state
                state = FILE
            elif token == 'global':
                saved_state = state
                state = GLOBAL
        elif state == FILE:
            if token == 'global':
                saved_state = state
                state = GLOBAL
            elif token == 'pattern':
                saved_state = state
                state = PATTERN
            elif token == '{':
                if pattern_macros is None:
                    macros, values = parse_macro_value(src)
                else:
                    macros, values = pattern_macros, parse_pattern_values(src)
                d = {}
                d.update(global_macros)
                d.update(file_global_macros)
                d.update(zip(macros, values))
                files.append((filename, d))
            elif token == '}':
                saved_state = state
                state = NEUTRAL
        elif state == PATTERN:
            if token == '{':
                pattern_macros = parse_pattern_macros(src)
                state = saved_state
        elif state == GLOBAL:
            if token == '{':
                macros, values = parse_macro_value(src)
                if saved_state == FILE:
                    file_global_macros.update(zip(macros, values)) 
                else:
                    global_macros.update(zip(macros, values))
                macros = values = None
                state = saved_state

    return files


def load_template_file(filename, encoding='utf8'):
    if sys.hexversion < 0x03000000:
        return parse_template(open(filename))
    else:
        return parse_template(open(filename, encoding=encoding))


if __name__ == '__main__':
    import argparse
    from .database import load_database_file, Database
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument(
            '-I',
            action = 'append',
            dest = 'includes',
            help = 'template include paths')
    parser.add_argument(
            '--encoding',
            default='utf8',
            help = 'files encoding')
    parser.add_argument(
            dest = 'substitution_files',
            nargs = '+',
            help='substitution files')
    args = parser.parse_args()

    db = Database()
    for subs_file in args.substitution_files:
        if os.path.exists(subs_file):
            includes = [os.path.dirname(subs_file)]
            if args.includes:
                includes.extend(args.includes)
            for db_file, macros in load_template_file(subs_file, args.encoding):
                db.update(load_database_file(
                    db_file,
                    macros,
                    includes,
                    args.encoding))
    print(db)
