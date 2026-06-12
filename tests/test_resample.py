from datetime import datetime
from zoneinfo import ZoneInfo

from src.mod.resample import resample

JST = ZoneInfo("Asia/Tokyo")


def test_resample_5s_mean(wide_builder):
    rows = [
        (f"2026-06-10T12:00:0{i}", float(i + 1), float(i * 10), None, None)
        for i in range(10)
    ]
    df = wide_builder(rows)
    out = resample(df, 5)
    assert out.height == 2
    assert out["dateTime"].to_list() == [
        datetime(2026, 6, 10, 12, 0, 0, tzinfo=JST),
        datetime(2026, 6, 10, 12, 0, 5, tzinfo=JST),
    ]
    assert out["1_TDB"].to_list() == [3.0, 8.0]  # (1..5), (6..10) の平均
    assert out["1_RH"].to_list() == [20.0, 70.0]
    assert out["2_TDB"].to_list() == [None, None]  # 全 null の平均は null


def test_resample_closed_left(wide_builder):
    df = wide_builder(
        [
            ("2026-06-10T12:00:04", 1.0, 1.0, 1.0, 1.0),
            ("2026-06-10T12:00:05", 9.0, 9.0, 9.0, 9.0),
        ]
    )
    out = resample(df, 5)
    assert out.height == 2  # 12:00:05 ちょうどは次の窓
    assert out["1_TDB"].to_list() == [1.0, 9.0]


def test_resample_passthrough_1s(wide_builder):
    df = wide_builder([("2026-06-10T12:00:00", 1.0, 1.0, 1.0, 1.0)])
    assert resample(df, 1) is df


def test_resample_empty(wide_builder):
    df = wide_builder([])
    out = resample(df, 60)
    assert out.height == 0
