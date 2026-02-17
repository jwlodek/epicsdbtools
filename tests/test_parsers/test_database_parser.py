import os

import pytest

from epicsdbtools import Database, Record, RecordType, load_database_file
from epicsdbtools.parsers.database import (
    DatabaseException,
    LoadIncludesStrategy,
    find_database_file,
    parse_pair,
    parse_record,
)


@pytest.mark.parametrize(
    "input, expected",
    [
        ('(value, "test")', ("value", "test")),
        ('(name, "example")', ("name", "example")),
        ('(empty, "")', ("empty", "")),
        ('(ai, "example")', ("ai", "example")),
        ('(, "example")', (None, None)),
        ("test", (None, None)),
        ("(test)", ("test", None)),
        ("(test, x, y)", (None, None)),
        ("(test x)", (None, None)),
    ],
)
def test_parse_pair(tokenizer_factory, input, expected):
    assert parse_pair(iter(tokenizer_factory(input))) == expected


def test_record_repr():
    record = Record("testRecord", RecordType.AI)
    record.fields["VAL"] = 42
    record.fields["DESC"] = "Test record"
    expected_repr = """record (ai, "testRecord") {
    field(VAL , "42")
    field(DESC, "Test record")
}
"""
    assert repr(record) == expected_repr


def test_merge_records():
    record1 = Record("testRecord", RecordType.AI)
    record1.fields["VAL"] = 42
    record1.fields["DESC"] = "Test record"

    record2 = Record("testRecord", RecordType.AI)
    record2.fields["VAL"] = 100
    record2.fields["DESC"] = "Updated test record"

    record1.merge(record2)

    assert record1.fields["VAL"] == 100
    assert record1.fields["DESC"] == "Updated test record"


def test_merge_records_with_different_types():
    record1 = Record("testRecord", RecordType.AI)
    record2 = Record("testRecord", RecordType.AO)
    with pytest.raises(DatabaseException):
        record1.merge(record2)


def test_merge_records_different_names():
    record1 = Record("testRecord1", RecordType.AI)
    record2 = Record("testRecord2", RecordType.AI)
    with pytest.raises(DatabaseException):
        record1.merge(record2)


def test_parse_record(tokenizer_factory):
    record_str = """(ai, "testRecord") {
    field(VAL, "42")
    field(DESC, "Test record")
    info(TEST, "testInfo")
    alias("testAlias1")
    alias("testAlias2")
}
"""
    record = parse_record(iter(tokenizer_factory(record_str)))
    assert record.name == "testRecord"
    assert record.rtype == RecordType.AI
    assert record.fields["VAL"] == "42"
    assert record.fields["DESC"] == "Test record"
    assert record.infos["TEST"] == "testInfo"
    assert record.aliases == ["testAlias1", "testAlias2"]


def test_parse_record_invalid_type(tokenizer_factory):
    record_str = """
record(invalid, "testRecord") {
    field(VAL, "42")
    field(DESC, "Test record")
}
"""
    with pytest.raises(DatabaseException):
        parse_record(iter(tokenizer_factory(record_str)))


def test_find_database_file(tmp_path):
    file = tmp_path / "test.db"
    with open(file, "w") as f:
        f.write('record(ai, "testRecord") { field(VAL, "42") }')
    assert find_database_file(file) == file
    assert find_database_file("test.db", search_path={tmp_path}) == file

    os.chdir(tmp_path)
    assert find_database_file("test.db") == tmp_path / "test.db"
    with pytest.raises(FileNotFoundError):
        find_database_file("nonexistent.db", search_path={tmp_path})


def test_load_invalid_database_file(tmp_path):
    file = tmp_path / "invalid.db"
    with open(file, "w") as f:
        f.write("invalid content")
    with pytest.raises(DatabaseException):
        load_database_file(file)


def test_load_database_file_doesnot_exist(tmp_path):
    file = tmp_path / "nonexistent.db"
    with pytest.raises(FileNotFoundError):
        load_database_file(file)


def test_load_database_file(sample_asyn_db, tmp_path):
    file = tmp_path / "test.db"
    with open(file, "w") as f:
        f.write(repr(sample_asyn_db))
    assert load_database_file(file) == sample_asyn_db


def test_load_database_file_with_comments(tmp_path, sample_asyn_db):
    file = tmp_path / "test.db"
    for record in sample_asyn_db.values():
        with open(file, "w") as f:
            f.write("# This is a comment\n")
            f.write(repr(record))
    loaded_db = load_database_file(file)
    assert loaded_db == sample_asyn_db


def test_load_database_file_with_includes(sample_asyn_db, tmp_path):
    file = tmp_path / "db_with_includes.db"
    addtl_record = Record("additionalRecord", RecordType.AI)
    with open(file, "w") as f:
        f.write('include "included.db"\n')
        f.write(repr(addtl_record))
    with open(tmp_path / "included.db", "w") as f:
        f.write(repr(sample_asyn_db))

    total_expected_db = sample_asyn_db.copy()
    total_expected_db.add_record(addtl_record)

    # Test loading into new
    loaded_db = load_database_file(
        file, load_includes_strategy=LoadIncludesStrategy.LOAD_INTO_NEW
    )
    expected_db = Database()
    expected_db.add_record(addtl_record)
    assert loaded_db == expected_db
    assert loaded_db.get_included_templates() == {"included.db": sample_asyn_db}

    # Test loading into self (default)
    expected_db = sample_asyn_db.copy()
    expected_db.add_record(addtl_record)
    loaded_db = load_database_file(file)
    assert loaded_db == expected_db
    assert loaded_db.get_included_template_filepaths() == ["included.db"]

    # Test no load include strategy
    loaded_db = load_database_file(
        file, load_includes_strategy=LoadIncludesStrategy.IGNORE
    )
    expected_db = Database()
    expected_db.add_record(addtl_record)
    assert loaded_db == expected_db
    assert loaded_db.get_included_templates() == {"included.db": None}
