from collections.abc import Callable
from io import StringIO
from pathlib import Path

import pytest

from epicsdbtools import Database, Record, RecordType, tokenizer

ASYN_DTYPES_TO_RTYPES_MAP: dict[str, list[RecordType]] = {
    "asynInt32": [
        RecordType.BO,
        RecordType.BI,
        RecordType.LONGIN,
        RecordType.LONGOUT,
        RecordType.MBBI,
        RecordType.MBBO,
        RecordType.AO,
        RecordType.AI,
    ],
    "asynFloat64": [
        RecordType.AI,
        RecordType.AO,
        RecordType.LONGIN,
        RecordType.LONGOUT,
    ],
    "asynOctetRead": [RecordType.STRINGIN, RecordType.STRINGOUT, RecordType.WAVEFORM],
    "asynOctetWrite": [RecordType.STRINGOUT, RecordType.STRINGIN, RecordType.WAVEFORM],
    "asynUInt32Digital": [
        RecordType.MBBI,
        RecordType.MBBO,
        RecordType.BI,
        RecordType.BO,
    ],
}


@pytest.fixture
def sample_asyn_db() -> Database:
    db = Database()
    for dtype, rtypes in ASYN_DTYPES_TO_RTYPES_MAP.items():
        for rtype in rtypes:
            record = Record(
                f"AsynTest{rtype.value.capitalize()}{dtype.capitalize()}", rtype
            )

            record.fields["DTYP"] = dtype
            if rtype.value.endswith("in") or rtype.value.endswith("i"):
                record.fields["INP"] = (
                    f"@asyn($(PORT),0,1)TST_{rtype.name}_{dtype.upper()}"
                )
            else:
                record.fields["OUT"] = (
                    f"@asyn($(PORT),0,1)TST_{rtype.name}_{dtype.upper()}"
                )
            record.infos["recordId"] = f"{rtype.name}_{dtype.upper()}"
            record.aliases.append(f"{rtype.name}_{dtype.upper()}")
            db.add_record(record)
    return db


@pytest.fixture
def tokenizer_factory() -> Callable[[Path | str], tokenizer.Tokenizer]:
    def _factory(input: Path | str) -> tokenizer.Tokenizer:
        if isinstance(input, Path):
            with open(input) as fp:
                return tokenizer.Tokenizer(StringIO(fp.read()), filename=str(input))
        else:
            return tokenizer.Tokenizer(StringIO(input), filename="test_input.txt")

    return _factory
