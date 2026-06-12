"""Translated（_T）出力: SerialTime・ケルビン・湿度比率の列を付加する。"""

from datetime import datetime
from pathlib import Path

import polars as pl

# Excel シリアル値の起点（JST の壁時計、naive で扱う）。
# 2026-06-12 の実レスポンスで「Date/Time 列 = シリアル値×86400 を本起点に加算した時刻」
# が成立することを較正済み（例: 2026-06-12 12:00:00 JST ↔ 46185.5 ↔ 3,990,427,200 秒）。
SERIAL_EPOCH = datetime(1899, 12, 30)


def serial_time_expr() -> pl.Expr:
    """dateTime(JST) → Excel シリアル値相当の整数秒（= シリアル値 × 86400）。"""
    naive = pl.col("dateTime").dt.replace_time_zone(None)
    return (
        (naive - pl.lit(SERIAL_EPOCH)).dt.total_seconds().cast(pl.Int64).alias("SerialTime")
    )


def translate(df: pl.DataFrame) -> pl.DataFrame:
    """SerialTime と n_TDB_K（+273.15）・n_RH_Phi（×0.01）を元列の後ろに付加する。

    列順: dateTime, 1_TDB, 1_RH, ..., SerialTime, 1_TDB_K, 1_RH_Phi, ...
    null（エラー値由来）は換算後も null のまま伝播する。
    """
    exprs: list[pl.Expr] = [serial_time_expr()]
    for col in df.columns:
        if col.endswith("_TDB"):
            exprs.append((pl.col(col) + 273.15).alias(f"{col}_K"))
        elif col.endswith("_RH"):
            exprs.append((pl.col(col) * 0.01).alias(f"{col}_Phi"))
    return df.with_columns(exprs)


def translated_path(path: Path) -> Path:
    """`{元ファイル名}_T.{拡張子}` のパスを返す。"""
    return path.with_name(f"{path.stem}_T{path.suffix}")
