from pathlib import Path

import polars as pl

from src.mod.translate import translate, translated_path


def test_translate_column_order(wide_builder):
    df = translate(wide_builder([("2026-06-10T12:00:00", 25.0, 60.0, 30.0, 50.0)]))
    assert df.columns == [
        "dateTime",
        "1_TDB",
        "1_RH",
        "2_TDB",
        "2_RH",
        "SerialTime",
        "1_TDB_K",
        "1_RH_Phi",
        "2_TDB_K",
        "2_RH_Phi",
    ]
    assert df.schema["SerialTime"] == pl.Int64


def test_serial_time_values(wide_builder):
    """較正済み換算: SerialTime = Excel シリアル値 × 86400（1899-12-30 起点の経過秒）。

    要件の例 46183 は 2026-06-10 00:00 JST に対応し 3,990,211,200 秒
    （要件記載の 3,990,297,600 は 1 日分のズレと確認し、本式で確定）。
    実レスポンス較正ベクトル: 2026-06-12 12:00:00 JST ↔ 46185.5 ↔ 3,990,427,200。
    """
    df = translate(
        wide_builder(
            [
                ("2026-06-10T00:00:00", 25.0, 60.0, 30.0, 50.0),  # シリアル値 46183.0
                ("2026-06-12T12:00:00", 25.0, 60.0, 30.0, 50.0),  # シリアル値 46185.5
            ]
        )
    )
    assert df["SerialTime"].to_list() == [
        46183 * 86400,  # 3,990,211,200
        3_990_427_200,
    ]


def test_kelvin_and_phi_conversion(wide_builder):
    df = translate(wide_builder([("2026-06-10T12:00:00", 25.0, 60.0, -10.0, 100.0)]))
    assert df["1_TDB_K"][0] == 298.15
    assert df["1_RH_Phi"][0] == 0.6
    assert df["2_TDB_K"][0] == 263.15
    assert df["2_RH_Phi"][0] == 1.0


def test_null_propagates(wide_builder):
    df = translate(wide_builder([("2026-06-10T12:00:00", None, None, 30.0, 50.0)]))
    assert df["1_TDB_K"][0] is None
    assert df["1_RH_Phi"][0] is None
    assert df["2_TDB_K"][0] == 303.15


def test_translate_empty(wide_builder):
    df = translate(wide_builder([]))
    assert df.height == 0
    assert "SerialTime" in df.columns


def test_translated_path():
    assert translated_path(
        Path("data/012h001s/012h001s_20260610T120000-20260611T000000.csv")
    ) == Path("data/012h001s/012h001s_20260610T120000-20260611T000000_T.csv")
    assert translated_path(Path("x/ALLh060s_a-b.parquet")).name == "ALLh060s_a-b_T.parquet"
