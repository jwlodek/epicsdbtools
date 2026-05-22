# Startup script that loads a dbd and a valid database
dbLoadDatabase("$(DATA_DIR)/test.dbd")
dbLoadRecords("$(DATA_DIR)/valid.db")
iocInit()
