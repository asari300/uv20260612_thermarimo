import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from src.mod.parser import parse_csv2

JST = ZoneInfo("Asia/Tokyo")


def test_parse_csv2_basic(csv2_builder):
    text = csv2_builder(
        [
            ("2026-06-10 12:00:00", "25.1", "60"),
            ("2026-06-10 12:00:01", "25.2", "61"),
        ]
    )
    df = parse_csv2(text, "EXAMPLE1")
    assert dict(df.schema) == {
        "dateTime": pl.Datetime("us", "Asia/Tokyo"),
        "TDB": pl.Float64,
        "RH": pl.Float64,
    }
    assert df.height == 2
    assert df["dateTime"][0] == datetime(2026, 6, 10, 12, 0, 0, tzinfo=JST)
    assert df["TDB"].to_list() == [25.1, 25.2]
    assert df["RH"].to_list() == [60.0, 61.0]


def test_parse_csv2_error_values_to_null(csv2_builder):
    text = csv2_builder(
        [
            ("2026-06-10 12:00:00", "E1", "60.2"),
            ("2026-06-10 12:00:01", "25.2", "E0"),
        ]
    )
    df = parse_csv2(text, "EXAMPLE1")
    assert df["TDB"].to_list() == [None, 25.2]
    assert df["RH"].to_list() == [60.2, None]


def test_parse_csv2_strips_bom(csv2_builder):
    text = "﻿" + csv2_builder([("2026-06-10 12:00:00", "25.1", "60.2")])
    df = parse_csv2(text, "EXAMPLE1")
    assert df.height == 1


def test_parse_csv2_warns_on_unexpected_timezone(caplog):
    text = (
        '"Date/Time","Date/Time","No.1","No.2"\r\n'
        '"時差:GMT+8:00/夏時間:off","","Ch.1","Ch.2"\r\n'
        '"","","C","%"\r\n'
        '"2026-06-10 12:00:00","45000.5","25.1","60.2"\r\n'
    )
    with caplog.at_level(logging.WARNING, logger="src.mod.parser"):
        df = parse_csv2(text, "EXAMPLE1")
    assert df.height == 1
    assert any("時差ヘッダ" in r.message for r in caplog.records)


def test_parse_csv2_empty_data(csv2_builder):
    df = parse_csv2(csv2_builder([]), "EXAMPLE1")
    assert df.height == 0
    assert df.schema["dateTime"] == pl.Datetime("us", "Asia/Tokyo")


def test_parse_csv2_invalid_header():
    with pytest.raises(ValueError):
        parse_csv2("foo,bar\n1,2\n", "EXAMPLE1")


def test_parse_csv2_rejects_array_body():
    """未登録シリアル時に API が返す `Array` ボディは csv2 として拒否される。"""
    with pytest.raises(ValueError):
        parse_csv2("Array", "EXAMPLE9")
