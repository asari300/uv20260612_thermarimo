from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from src.mod.storage import (
    ensure_data_dirs,
    merge_frames,
    save_dataframe,
    split_daily,
    split_weekly,
    value_columns,
)
from src.mod.translate import translate

JST = ZoneInfo("Asia/Tokyo")


def test_value_columns():
    assert value_columns(2) == ["1_TDB", "1_RH", "2_TDB", "2_RH"]


def test_merge_frames_without_existing(wide_builder):
    df = wide_builder(
        [
            ("2026-06-10T12:00:01", 2.0, 2.0, 2.0, 2.0),
            ("2026-06-10T12:00:00", 1.0, 1.0, 1.0, 1.0),
        ]
    )
    merged = merge_frames(None, df)
    assert merged["1_TDB"].to_list() == [1.0, 2.0]  # dateTime でソートされる


def test_merge_frames_new_values_win(wide_builder):
    old = wide_builder([("2026-06-10T12:00:00", 25.0, 60.0, 30.0, 50.0)])
    new = wide_builder(
        [
            ("2026-06-10T12:00:00", 26.0, 61.0, 30.5, 50.5),
            ("2026-06-10T12:00:01", 27.0, 62.0, 31.0, 51.0),
        ]
    )
    merged = merge_frames(old, new)
    assert merged.height == 2
    assert merged["1_TDB"].to_list() == [26.0, 27.0]
    assert merged["2_TDB"].to_list() == [30.5, 31.0]


def test_merge_frames_null_does_not_clobber(wide_builder):
    """一部機器だけ失敗した再取得（null列）が既存値を潰さないこと。"""
    old = wide_builder([("2026-06-10T12:00:00", 25.0, 60.0, 30.0, 50.0)])
    new = wide_builder(
        [
            ("2026-06-10T12:00:00", 26.0, 61.0, None, None),
            ("2026-06-10T12:00:01", 27.0, 62.0, None, None),
        ]
    )
    merged = merge_frames(old, new)
    assert merged["1_TDB"].to_list() == [26.0, 27.0]  # 新値が優先
    assert merged["2_TDB"].to_list() == [30.0, None]  # 既存値は保持、新規行は null
    assert merged["2_RH"].to_list() == [50.0, None]
    assert merged.columns == ["dateTime", "1_TDB", "1_RH", "2_TDB", "2_RH"]


def test_ensure_data_dirs(tmp_path):
    ensure_data_dirs(tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 20  # hours{012,024,168,ALL} × seconds{001,005,010,060,300}
    assert "012h001s" in names
    assert "168h060s" in names
    assert "ALLh300s" in names


@pytest.mark.parametrize("ext", ["csv", "tsv"])
def test_save_dataframe_text_formats(tmp_path, ext, wide_builder):
    df = wide_builder([("2026-06-10T12:00:00", 25.0, 60.0, 30.0, 50.0)])
    path = tmp_path / f"out.{ext}"
    size = save_dataframe(df, path, ext)
    raw = path.read_bytes()
    assert size == len(raw) > 0
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8-Sig
    text = path.read_text(encoding="utf-8-sig")
    assert "dateTime" in text.splitlines()[0]
    assert "2026-06-10 12:00:00" in text  # JST・オフセットなし表記
    assert "+09" not in text
    if ext == "tsv":
        assert "\t" in text


def test_save_dataframe_fixed_decimal_formatting(tmp_path, wide_builder):
    """CSV/TSV の測定値表記: TDB/RH=1桁（末尾ゼロ保持、null は空欄）。"""
    df = wide_builder([("2026-06-12T12:00:00", 24.0, 61.0, None, 74.3)])
    path = tmp_path / "out.csv"
    save_dataframe(df, path, "csv")
    line = path.read_text(encoding="utf-8-sig").splitlines()[1]
    assert line == "2026-06-12 12:00:00,24.0,61.0,,74.3"


def test_save_translated_fixed_decimal_formatting(tmp_path, wide_builder):
    """_T 出力: TDB_K=2桁、RH_Phi=3桁、SerialTime は整数のまま。"""
    df = translate(wide_builder([("2026-06-12T12:00:00", 24.0, 61.0, 18.0, 74.3)]))
    path = tmp_path / "out_T.csv"
    save_dataframe(df, path, "csv")
    line = path.read_text(encoding="utf-8-sig").splitlines()[1]
    assert line == (
        "2026-06-12 12:00:00,24.0,61.0,18.0,74.3,"
        "3990427200,297.15,0.610,291.15,0.743"
    )


def test_save_dataframe_parquet_roundtrip(tmp_path, wide_builder):
    df = wide_builder([("2026-06-10T12:00:00", 25.0, 60.0, 30.0, 50.0)])
    path = tmp_path / "out.parquet"
    save_dataframe(df, path, "parquet")
    back = pl.read_parquet(path)
    assert back.equals(df)
    assert back.schema["dateTime"] == pl.Datetime("us", "Asia/Tokyo")


def test_save_dataframe_unknown_ext(tmp_path, wide_builder):
    with pytest.raises(ValueError):
        save_dataframe(wide_builder([]), tmp_path / "out.xlsx", "xlsx")


def test_split_daily_jst_boundary(wide_builder):
    df = wide_builder(
        [
            ("2026-06-10T23:59:59", 1.0, 1.0, 1.0, 1.0),
            ("2026-06-11T00:00:00", 2.0, 2.0, 2.0, 2.0),
            ("2026-06-11T10:00:00", 3.0, 3.0, 3.0, 3.0),
        ]
    )
    parts = split_daily(df)
    keys = sorted(parts)
    assert keys == [
        datetime(2026, 6, 10, 0, 0, tzinfo=JST),
        datetime(2026, 6, 11, 0, 0, tzinfo=JST),
    ]
    assert parts[keys[0]].height == 1
    assert parts[keys[1]].height == 2
    assert parts[keys[0]].columns == ["dateTime", "1_TDB", "1_RH", "2_TDB", "2_RH"]


def test_split_weekly_sunday_anchor(wide_builder):
    # 2026-06-06 は土曜、2026-06-07 は日曜
    df = wide_builder(
        [
            ("2026-06-06T10:00:00", 1.0, 1.0, 1.0, 1.0),
            ("2026-06-07T00:00:00", 2.0, 2.0, 2.0, 2.0),
            ("2026-06-12T12:00:00", 3.0, 3.0, 3.0, 3.0),
        ]
    )
    parts = split_weekly(df)
    keys = sorted(parts)
    assert keys == [
        datetime(2026, 5, 31, 0, 0, tzinfo=JST),  # 日曜
        datetime(2026, 6, 7, 0, 0, tzinfo=JST),  # 日曜
    ]
    assert parts[keys[0]].height == 1
    assert parts[keys[1]].height == 2


def test_split_empty(wide_builder):
    assert split_daily(wide_builder([])) == {}
    assert split_weekly(wide_builder([])) == {}
