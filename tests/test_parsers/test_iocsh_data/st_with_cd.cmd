# Startup script that uses cd to change directory
epicsEnvSet("P", "Test:")
cd("subdir")
dbLoadRecords("sub.db", "P=$(P)")
