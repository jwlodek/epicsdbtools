# Startup script that loads a dbd and a database with invalid fields
dbLoadDatabase("$(DATA_DIR)/test.dbd")
dbLoadRecords("$(DATA_DIR)/invalid_field.db")
iocInit()
