# Startup script that uses EPICS_DB_INCLUDE_PATH
epicsEnvSet("P", "Test:")
dbLoadRecords("included.db", "P=$(P)")
