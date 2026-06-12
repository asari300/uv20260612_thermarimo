"""テスト共通ヘルパー。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

JST = ZoneInfo("Asia/Tokyo")

CSV2_HEADER = (
    '"Date/Time","Date/Time","No.1","No.2"\r\n'
    '"時差:GMT+9:00/夏時間:off","日付のシリアル値(Excel)","Ch.1","Ch.2"\r\n'
    '"","","C","%"\r\n'
)

WIDE_SCHEMA = {
    "dateTime": pl.Datetime("us", "Asia/Tokyo"),
    "1_TDB": pl.Float64,
    "1_RH": pl.Float64,
    "2_TDB": pl.Float64,
    "2_RH": pl.Float64,
}


def build_csv2(rows: list[tuple[str, str, str]]) -> str:
    """(Date/Time文字列, ch1, ch2) の行リストから csv2 レスポンス本文を組み立てる。"""
    body = "".join(f'"{t}","45000.123456","{ch1}","{ch2}"\r\n' for t, ch1, ch2 in rows)
    return CSV2_HEADER + body


def build_wide(
    rows: list[tuple[str, float | None, float | None, float | None, float | None]],
) -> pl.DataFrame:
    """(ISO時刻文字列, 1_TDB, 1_RH, 2_TDB, 2_RH) の行リストからワイド形式 DataFrame を作る。"""
    return pl.DataFrame(
        {
            "dateTime": [
                datetime.fromisoformat(r[0]).replace(tzinfo=JST) for r in rows
            ],
            "1_TDB": [r[1] for r in rows],
            "1_RH": [r[2] for r in rows],
            "2_TDB": [r[3] for r in rows],
            "2_RH": [r[4] for r in rows],
        },
        schema=WIDE_SCHEMA,
    )


@pytest.fixture
def csv2_builder():
    return build_csv2


@pytest.fixture
def wide_builder():
    return build_wide
