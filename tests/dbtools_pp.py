import sys

import pyparsing as pp

COMMA = pp.Literal(",").suppress()
EQUAL = pp.Literal("=").suppress()
O_BRACE = pp.Literal("{").suppress()
C_BRACE = pp.Literal("}").suppress()

PATH_CHAR = pp.Word(pp.alphanums + "_-+:;./\\")
VALUE_CHAR = pp.Word(pp.alphanums + "_-+:;./\\<>[]")


value = VALUE_CHAR | pp.QuotedString('"') | pp.QuotedString("'")
file_name = PATH_CHAR | pp.QuotedString('"') | pp.QuotedString("'")
variable_name = pp.Word(pp.alphas + "_", pp.alphanums + "_-")

variable_defs = pp.OneOrMore(variable_name + EQUAL + value + pp.Optional(COMMA))

global_defs = pp.Literal("global") + O_BRACE + pp.Group(variable_defs) + C_BRACE

variable_subs = pp.OneOrMore(
    global_defs | (O_BRACE + pp.Group(variable_defs) + C_BRACE)
)

pattern_values = pp.OneOrMore(value + pp.Optional(COMMA))
pattern_defs = pp.OneOrMore(
    global_defs | (O_BRACE + pp.Group(pattern_values) + C_BRACE)
)
pattern_names = pp.OneOrMore(variable_name + pp.Optional(COMMA))
pattern_subs = (
    pp.Literal("pattern") + O_BRACE + pp.Group(pattern_names) + C_BRACE + pattern_defs
)

subs = pattern_subs | variable_subs
template_subs = pp.Literal("file") + file_name + O_BRACE + pp.ZeroOrMore(subs) + C_BRACE

substitution_file = pp.OneOrMore(global_defs | template_subs)
substitution_file.ignore(pp.pythonStyleComment)


d = substitution_file.parseString(open(sys.argv[1]).read())

for v in d:
    print(v)
