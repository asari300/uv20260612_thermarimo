"""時系列のダウンサンプリング（平均集約）。"""

import polars as pl


def resample(df: pl.DataFrame, interval_sec: int) -> pl.DataFrame:
    """dateTime を interval_sec 秒の窓（closed="left"、ラベルは窓開始時刻）へ集約する。

    値列（dateTime 以外）はすべて算術平均。interval_sec == 1 または空データは
    そのまま返す。
    """
    if interval_sec == 1 or df.height == 0:
        return df
    value_cols = [c for c in df.columns if c != "dateTime"]
    return (
        df.sort("dateTime")
        .group_by_dynamic("dateTime", every=f"{interval_sec}s", closed="left")
        .agg([pl.col(c).mean() for c in value_cols])
    )
