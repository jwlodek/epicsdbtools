# Basic st.cmd for testing
epicsEnvSet("IOC", "testIOC")
epicsEnvSet("PORT", "MYPORT")
epicsEnvSet("P", "Test:")
epicsEnvSet("R", "Dev:")

# Some other commands
iocInit()
dbl()
