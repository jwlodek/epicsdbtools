import pytest

from epics_dbtools.database import Database, Record

ASYN_DTYPES_TO_RTYPES_MAP = {
    "asynInt32": ["bo", "bi", "longin", "longout", "mbbi", "mbbo", "ao", "ai"],
    "asynFloat64": ["ai", "ao", "longin", "longout"],
    "asynOctetRead": ["stringin", "stringout", "waveform"],
    "asynOctetWrite": ["stringout", "stringin", "waveform"],
}


@pytest.fixture
def sample_asyn_db():
    db = Database()
    for dtype, rtypes in ASYN_DTYPES_TO_RTYPES_MAP.items():
        for rtype in rtypes:
            record = Record()
            record.name = f"AsynTest{rtype.capitalize()}{dtype.capitalize()}"
            record.rtyp = rtype
            record.fields["DTYP"] = dtype
            if rtype.endswith("in") or rtype.endswith("i"):
                record.fields["INP"] = (
                    f"@asyn($(PORT),0,1)TST_{rtype.upper()}_{dtype.upper()}"
                )
            else:
                record.fields["OUT"] = (
                    f"@asyn($(PORT),0,1)TST_{rtype.upper()}_{dtype.upper()}"
                )
            db.add_record(record)
    return db
