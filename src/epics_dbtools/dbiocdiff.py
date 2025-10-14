#!/usr/bin/env python
"""
This script loads records from a substitution file and reports fields
that have inconsistencies values with those in the running IOC.

"""
from __future__ import print_function

import argparse
import os
import re

from .. import load_database_file, load_template_file, Database
from CaChannel import ca, CaChannel

class TablePrinter(object):
    """
    Print a list of values as table fields according to user defined widths.
    """
    def __init__(self, *widths):
        formatter = ''
        for i in range(len(widths)):
            formatter += '{%d:<%d} ' % (i, widths[i])

        self.formatter = formatter.rstrip()
        self.widths = widths

    def print_line(self, *args):
        print(self.formatter.format(*args))

    def print_separator(self):
        print(' '.join(['-'*w for w in self.widths]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rtyps',
            help='record types separated by ",". (default: all)')
    parser.add_argument('--encoding', default='utf8',
            help = 'files encoding (default: utf8)')
    parser.add_argument('subs',
            help='substitute file')
    args = parser.parse_args()

    if args.rtyps:
        rtyps = args.rtyps.split(',')
    else:
        rtyps = None

    subs = os.path.expanduser(args.subs)

    db = Database()
    for filename, macros in load_template_file(subs, args.encoding):
        db.update(load_database_file(filename, macros, [os.path.dirname(subs)], args.encoding))

    # print output as table
    printer = TablePrinter(30, 15, 15)
    printer.print_line('channel', 'IOC', 'database')
    printer.print_separator()

    for record in db.values():
        if rtyps and record.rtyp not in rtyps:
            continue

        # issue connect requests and wait for connection
        chans = {}
        for field in record.fields:
            chan = CaChannel(record.name + '.' + field)
            chan.search()
            chans[field] = chan
        ca.pend_io(10)

        # issue read requests and wait for completion
        for chan in chans.values():
            chan.array_get(ca.dbf_type_to_DBR_CTRL(chan.field_type()))
        ca.pend_io(10)

        # compare and print
        all_consistent = True
        for field, chan in chans.items():
            # get configured value
            config_value = record.fields[field]
            # skip those with empty config values
            if config_value == '':
                continue

            # dbr is a dict containing the channel information
            dbr = chan.getValue()
            actual_value = dbr['pv_value']

            # convert actual or config value for comparison if necessary
            ftype = chan.field_type()
            if ftype == ca.DBF_STRING:
                # remove "NPP" "NMS" from known link fields
                if re.match(r'SDIS|FLNK|SIOL|SIML|RDBL|RLNK|DINP|RINP|STOO|NVL|SELL|DOL\d?|LNK[1-9A]|OUT[A-U]?|INP[A-U]?|IN([A-L])\1', field):
                    actual_value = re.sub(' +', ' ', re.sub(' +(NPP|NMS)', '', actual_value)).strip()
                    config_value = re.sub(' +', ' ', re.sub(' +(NPP|NMS)', '', config_value)).strip()
                # capitialize calc expressions
                elif re.match(r'(CALC|OCAL|CLC[A-P])', field) and record.rtyp in ['calc', 'calcout']:
                    config_value = config_value.upper()
                    actual_value = actual_value.upper()
            elif ftype == ca.DBF_ENUM:
                # convert the actual value to the same choice string as the configured value
                if not config_value.isdigit():
                    if actual_value < len(dbr['pv_statestrings']):
                        actual_value = dbr['pv_statestrings'][actual_value]
                else:
                    config_value = int(config_value)
            else:
                # convert to float for all other numeric types
                config_value = float(config_value)

            if isinstance(config_value, float):
                if abs(actual_value - config_value) > 1e-9:
                    all_consistent = False
                    printer.print_line(chan.name(), actual_value, record.fields[field])
            elif actual_value != config_value:
                all_consistent = False
                printer.print_line(chan.name(), actual_value, record.fields[field])

        if not all_consistent:
            printer.print_separator()

if __name__ == '__main__':
    main()