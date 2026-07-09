from io import StringIO
from pathlib import Path

import pytest

from epicsdbtools.parsers.database_definition import (
    DbdException,
    MenuChoice,
    _parse_breaktable,
    _parse_device,
    _parse_menu,
    _parse_record_type,
    load_dbd_file,
    parse_dbd,
)
from epicsdbtools.tokenizer import Tokenizer

TEST_DBD_DIR = Path(__file__).parent / "test_dbd_data"


def tokenize(text: str):
    return iter(Tokenizer(StringIO(text), "test.dbd"))


# --- _parse_menu tests ---


def test_parse_menu_simple():
    text = """(menuScan) {
        choice(menuScanPassive, "Passive")
        choice(menuScanEvent, "Event")
    }"""
    menu = _parse_menu(tokenize(text))
    assert menu.name == "menuScan"
    assert len(menu.choices) == 2
    assert menu.choices[0] == MenuChoice(name="menuScanPassive", string="Passive")
    assert menu.choices[1] == MenuChoice(name="menuScanEvent", string="Event")


def test_parse_menu_empty():
    text = "(emptyMenu) {}"
    menu = _parse_menu(tokenize(text))
    assert menu.name == "emptyMenu"
    assert len(menu.choices) == 0


def test_parse_menu_invalid_missing_paren():
    text = "menuScan {"
    with pytest.raises(DbdException):
        _parse_menu(tokenize(text))


# --- _parse_record_type tests ---


def test_parse_recordtype_simple():
    text = """(ai) {
        field(VAL, DBF_DOUBLE) {
            prompt("Current EGU Value")
            asl(ASL0)
        }
        field(DESC, DBF_STRING) {
            prompt("Descriptor")
            size(41)
        }
    }"""
    rt = _parse_record_type(tokenize(text))
    assert rt.name == "ai"
    assert len(rt.fields) == 2
    assert "VAL" in rt.fields
    assert rt.fields["VAL"].type == "DBF_DOUBLE"
    assert rt.fields["VAL"].attributes["prompt"] == "Current EGU Value"
    assert rt.fields["VAL"].attributes["asl"] == "ASL0"
    assert rt.fields["DESC"].type == "DBF_STRING"
    assert rt.fields["DESC"].attributes["size"] == "41"


def test_parse_recordtype_empty():
    text = "(empty) {}"
    rt = _parse_record_type(tokenize(text))
    assert rt.name == "empty"
    assert len(rt.fields) == 0


# --- _parse_device tests ---


def test_parse_device_simple():
    text = '(ai, CONSTANT, devAiSoft, "Soft Channel")'
    dev = _parse_device(tokenize(text))
    assert dev.record_type == "ai"
    assert dev.link_type == "CONSTANT"
    assert dev.dset_name == "devAiSoft"
    assert dev.choice_string == "Soft Channel"


def test_parse_device_invalid():
    text = "(ai CONSTANT devAiSoft)"
    with pytest.raises(DbdException):
        _parse_device(tokenize(text))


# --- _parse_breaktable tests ---


def test_parse_breaktable_simple():
    text = """(typeJdegC) {
        0.000000 0.0
        365.023224 67.0
    }"""
    bt = _parse_breaktable(tokenize(text))
    assert bt.name == "typeJdegC"
    assert len(bt.entries) == 2
    assert bt.entries[0] == ("0.000000", "0.0")
    assert bt.entries[1] == ("365.023224", "67.0")


# --- parse_dbd tests ---


def test_parse_dbd_full():
    text = """
menu(menuYesNo) {
    choice(menuYesNoNO, "NO")
    choice(menuYesNoYES, "YES")
}

recordtype(bi) {
    field(VAL, DBF_ENUM) {
        prompt("Current Value")
        asl(ASL0)
        pp(TRUE)
    }
}

device(bi, CONSTANT, devBiSoft, "Soft Channel")

driver(drvAsyn)

registrar(asSub)

function(myFunc)

variable(debugLevel, int)

breaktable(typeKdegC) {
    0.0 0.0
    100.0 50.0
}

include "base.dbd"
"""
    dbd = parse_dbd(tokenize(text))
    assert "menuYesNo" in dbd.menus
    assert len(dbd.menus["menuYesNo"].choices) == 2
    assert "bi" in dbd.record_types
    assert "VAL" in dbd.record_types["bi"].fields
    assert len(dbd.devices) == 1
    assert dbd.devices[0].record_type == "bi"
    assert dbd.drivers == ["drvAsyn"]
    assert dbd.registrars == ["asSub"]
    assert dbd.functions == ["myFunc"]
    assert dbd.variables == [("debugLevel", "int")]
    assert "typeKdegC" in dbd.break_tables
    assert dbd.includes == ["base.dbd"]


def test_parse_dbd_invalid_token():
    text = "invalid_keyword(something)"
    with pytest.raises(DbdException, match="Unexpected top-level token"):
        parse_dbd(tokenize(text))


# --- load_dbd_file tests ---


def test_load_dbd_file():
    dbd = load_dbd_file(TEST_DBD_DIR / "test.dbd")

    # Menus
    assert "menuScan" in dbd.menus
    assert len(dbd.menus["menuScan"].choices) == 7
    assert "menuAlarmSevr" in dbd.menus
    assert len(dbd.menus["menuAlarmSevr"].choices) == 4

    # Record types
    assert "ai" in dbd.record_types
    assert "ao" in dbd.record_types
    ai = dbd.record_types["ai"]
    assert "VAL" in ai.fields
    assert ai.fields["VAL"].type == "DBF_DOUBLE"
    assert ai.fields["PREC"].attributes["interest"] == "1"
    assert len(ai.fields) == 5

    ao = dbd.record_types["ao"]
    assert len(ao.fields) == 3

    # Devices
    assert len(dbd.devices) == 3
    assert dbd.devices[0].choice_string == "Soft Channel"

    # Drivers
    assert dbd.drivers == ["drvAsyn"]

    # Registrars
    assert dbd.registrars == ["asSub", "dbndInitialize"]

    # Functions
    assert dbd.functions == ["mySubProcess"]

    # Variables
    assert ("asCaDebug", "int") in dbd.variables
    assert ("dbRecordsOnceOnly", None) in dbd.variables

    # Break tables
    assert "typeJdegC" in dbd.break_tables
    assert len(dbd.break_tables["typeJdegC"].entries) == 4

    # Includes
    assert dbd.includes == ["menuGlobal.dbd"]


def test_load_dbd_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_dbd_file("nonexistent.dbd")
