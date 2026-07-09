# Startup script that exercises all validation error categories
epicsEnvSet("STREAM_PROTOCOL_PATH", "protocols")

dbLoadDatabase("test.dbd")
test_registerRecordDeviceDriver()

dbLoadRecords("all_errors.db")

# Unknown iocsh command (not registered)
totallyUnknownCommand("arg1")

iocInit()
