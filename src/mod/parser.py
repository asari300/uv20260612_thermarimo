"""csv2 レスポンスを Polars DataFrame（1機器分のワイド前形式）へ変換する。"""

import csv
import io
import logging

import polars as pl

logger = logging.getLogger(__name__)

# 1機器分のパース結果スキーマ。collector が機器番号付き列名（n_TDB 等）へリネームする。
SCHEMA: dict[str, pl.DataType] = {
    "dateTime": pl.Datetime("us", "Asia/Tokyo"),
    "TDB": pl.Float64,
    "RH": pl.Float64,
}

EXPECTED_TZ_MARKS = ("GMT+9:00", "夏時間:off")


def parse_csv2(csv_text: str, serial: str) -> pl.DataFrame:
    """csv2 形式（ヘッダ3行 + データ行）をパースする。

    データ行は [Date/Time, Excelシリアル値, Ch.1温度, Ch.2湿度]。
    "Date/Time" 列は機器の時差補正済み（JST）文字列なので、そのまま JST として
    ローカライズする。E0〜E3 のエラー値は null に変換する。
    クォートは csv.reader が、前後空白は strip() が除去する（実レスポンスで確認済み）。
    """
    # 万一レスポンス先頭に BOM が付いてもヘッダ判定が壊れないようにする
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    if len(rows) < 3 or not rows[0] or rows[0][0] != "Date/Time":
        raise ValueError("csv2 形式のレスポンスではありません")

    header2 = ",".join(rows[1])
    if any(mark not in header2 for mark in EXPECTED_TZ_MARKS):
        logger.warning(
            "機器 %s: 時差ヘッダが想定（GMT+9:00/夏時間:off）と異なります: %s",
            serial,
            header2,
        )

    times: list[str] = []
    temps: list[float | None] = []
    humids: list[float | None] = []
    n_errors = 0
    for row in rows[3:]:
        if len(row) < 4 or not row[0].strip():
            continue
        times.append(row[0].strip())
        for raw, dest in ((row[2], temps), (row[3], humids)):
            value = raw.strip()
            if value.startswith("E"):
                n_errors += 1
                dest.append(None)
            elif not value:
                dest.append(None)
            else:
                dest.append(float(value))

    if n_errors:
        logger.warning("機器 %s: エラー値 %d 件を null に変換しました", serial, n_errors)

    df = pl.DataFrame(
        {"dateTime": times, "TDB": temps, "RH": humids},
        schema={"dateTime": pl.String, "TDB": pl.Float64, "RH": pl.Float64},
    )
    return df.with_columns(
        pl.col("dateTime")
        .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
        .dt.replace_time_zone("Asia/Tokyo")
    )
