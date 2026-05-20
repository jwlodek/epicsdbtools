# Test source redirect
epicsEnvSet("TOP", "/some/path")
< sourced.cmd
epicsEnvSet("AFTER_SOURCE", "yes")
