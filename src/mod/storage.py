"""取得データの結合・分割・リサンプリングと data/ への保存。

保存対象: 12h=取得ウィンドウ / 24h=日次 / 168h=週次（日曜起点） / ALL=全結合 を
各間隔（既定 1/5/10/60/300 秒）× 3形式（csv/tsv/parquet）×（通常 + 翻訳 _T）で出力する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from src.mod.config import Settings
from src.mod.filename import make_filename
from src.mod.resample import resample
from src.mod.translate import translate, translated_path

logger = logging.getLogger(__name__)

HOURS_DIRS = ("012", "024", "168", "ALL")
INTERVAL_SECONDS = (1, 5, 10, 60, 300)
SAVE_FORMATS = ("csv", "tsv", "parquet")
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"  # CSV/TSV の dateTime 表記（JST、オフセットなし）

# CSV/TSV の測定値の小数桁数（接尾辞 → 桁数）。Parquet は Float64 のまま保持する。
FLOAT_TEXT_FORMATS = (("_TDB_K", 2), ("_TDB", 1), ("_RH_Phi", 3), ("_RH", 1))


def _text_formatted(df: pl.DataFrame) -> pl.DataFrame:
    """テキスト出力用に測定値列を固定小数点（Decimal）へ変換する。

    `24.0 → "24.00"` のように末尾ゼロを保持し、null は空欄のまま出力される。
    """
    exprs = []
    for col, dtype in df.schema.items():
        if dtype != pl.Float64:
            continue
        digits = next(
            (d for suffix, d in FLOAT_TEXT_FORMATS if col.endswith(suffix)), None
        )
        if digits is not None:
            exprs.append(pl.col(col).cast(pl.Decimal(scale=digits)))
    return df.with_columns(exprs) if exprs else df


def value_columns(n_devices: int) -> list[str]:
    """ワイド形式の値列名（設定の機器並び順で 1 始まり）。"""
    return [f"{i}_{metric}" for i in range(1, n_devices + 1) for metric in ("TDB", "RH")]


def ensure_data_dirs(data_root: Path) -> None:
    """`{hours}h{seconds:03d}s` 形式の保存先ディレクトリ（4×5=20個）を生成する。"""
    for hours in HOURS_DIRS:
        for seconds in INTERVAL_SECONDS:
            (data_root / f"{hours}h{seconds:03d}s").mkdir(parents=True, exist_ok=True)


def merge_frames(existing: pl.DataFrame | None, new: pl.DataFrame) -> pl.DataFrame:
    """dateTime の full join + 列ごとの coalesce(新, 旧) で結合する。

    ワイド形式では「一部機器だけ失敗した再取得」の null が既存値を潰してはならない
    ため、unique(keep="last") ではなく null を上書きしない update 方式を取る。
    """
    if existing is None or existing.height == 0:
        return new.sort("dateTime")
    value_cols = [c for c in new.columns if c != "dateTime"]
    old = existing
    for col in value_cols:
        if col not in old.columns:
            old = old.with_columns(pl.lit(None, dtype=pl.Float64).alias(col))
    old = old.select(["dateTime", *value_cols])
    merged = old.join(new, on="dateTime", how="full", coalesce=True, suffix="_new")
    merged = merged.with_columns(
        [pl.coalesce([pl.col(f"{c}_new"), pl.col(c)]).alias(c) for c in value_cols]
    )
    return merged.select(["dateTime", *value_cols]).sort("dateTime")


def save_dataframe(df: pl.DataFrame, path: Path, ext: str) -> int:
    """csv/tsv/parquet で保存し、書き込みバイト数を返す。

    csv/tsv は UTF-8-Sig で、測定値は固定小数点表記（TDB/RH=1桁、TDB_K=2桁、
    RH_Phi=3桁）。parquet は Float64 のまま保存する。
    """
    if ext == "csv":
        _text_formatted(df).write_csv(
            path, include_bom=True, datetime_format=DATETIME_FORMAT
        )
    elif ext == "tsv":
        _text_formatted(df).write_csv(
            path, separator="\t", include_bom=True, datetime_format=DATETIME_FORMAT
        )
    elif ext == "parquet":
        df.write_parquet(path)
    else:
        raise ValueError(f"未対応の拡張子: {ext}")
    return path.stat().st_size


def split_daily(df: pl.DataFrame) -> dict[datetime, pl.DataFrame]:
    """JST 0時境界で日ごとに分割する。キーは日の開始時刻。"""
    if df.height == 0:
        return {}
    parts = df.with_columns(_period=pl.col("dateTime").dt.truncate("1d")).partition_by(
        "_period", as_dict=True
    )
    return {_key(k): part.drop("_period") for k, part in parts.items()}


def split_weekly(df: pl.DataFrame) -> dict[datetime, pl.DataFrame]:
    """日曜 0時（JST）起点で週ごとに分割する。キーは週の開始時刻。"""
    if df.height == 0:
        return {}
    day = pl.col("dateTime").dt.truncate("1d")
    week_start = day - pl.duration(days=day.dt.weekday() % 7)  # 月=1〜日=7 → 日曜で 0
    parts = df.with_columns(_period=week_start).partition_by("_period", as_dict=True)
    return {_key(k): part.drop("_period") for k, part in parts.items()}


def _key(key: object) -> datetime:
    return key[0] if isinstance(key, tuple) else key  # partition_by のキーはタプル


@dataclass
class SaveReport:
    written: list[Path]
    rows_window: int
    rows_all: int
    all_range: tuple[datetime, datetime] | None
    bytes_1sec: int


def _load_latest_all(all_dir: Path) -> pl.DataFrame | None:
    """ALLh001s の最新の非翻訳 Parquet を読む（ファイル名の終端時刻順 = 辞書順）。"""
    files = sorted(
        p for p in all_dir.glob("ALLh001s_*.parquet") if not p.stem.endswith("_T")
    )
    if not files:
        return None
    return pl.read_parquet(files[-1])


def _save_set(
    df: pl.DataFrame, dir_path: Path, hours: int | str, seconds: int,
    start: datetime, end: datetime,
) -> list[Path]:
    """1データセットを 3形式 ×（通常 + _T）で保存する。"""
    translated = translate(df)
    written: list[Path] = []
    for ext in SAVE_FORMATS:
        path = dir_path / make_filename(hours, seconds, start, end, ext)
        save_dataframe(df, path, ext)
        written.append(path)
        t_path = translated_path(path)
        save_dataframe(translated, t_path, ext)
        written.append(t_path)
    return written


def persist_all(
    new_df: pl.DataFrame, start: datetime, end: datetime, settings: Settings
) -> SaveReport:
    """取得ウィンドウ(12h)・日次(24h)・週次(168h)・全結合(ALL)を全間隔×全形式で保存する。

    日次・週次は新規データが触れた期間のみ再出力（同名上書き）。ALL は毎回再出力し、
    置き換え後に旧ファイルを削除する。
    """
    data_root = settings.data_root
    ensure_data_dirs(data_root)
    intervals = settings.resample_intervals
    written: list[Path] = []

    # 12h: 取得ウィンドウ（ファイル名は要求ウィンドウの境界）
    for sec in intervals:
        written += _save_set(
            resample(new_df, sec), data_root / f"012h{sec:03d}s", 12, sec, start, end
        )

    # ALL: 既存と結合して全間隔で再出力、旧ファイルは削除
    merged = merge_frames(_load_latest_all(data_root / "ALLh001s"), new_df)
    all_range = (
        (merged["dateTime"].min(), merged["dateTime"].max()) if merged.height else None
    )
    bytes_1sec = 0
    for sec in intervals:
        all_dir = data_root / f"ALLh{sec:03d}s"
        stale = {p for p in all_dir.iterdir() if p.is_file()}
        files = _save_set(
            resample(merged, sec), all_dir, "ALL", sec, *(all_range or (start, end))
        )
        written += files
        if sec == 1:
            parquet = next(
                p for p in files if p.suffix == ".parquet" and not p.stem.endswith("_T")
            )
            bytes_1sec = parquet.stat().st_size
        for path in stale - set(files):
            path.unlink()
            logger.info("旧 ALL ファイルを削除しました: %s", path)

    # 24h / 168h: 新規データが触れた期間のみ再出力
    if new_df.height:
        new_min, new_max = new_df["dateTime"].min(), new_df["dateTime"].max()
        plans = (
            (split_daily, 24, "024", timedelta(days=1)),
            (split_weekly, 168, "168", timedelta(days=7)),
        )
        for split_fn, hours, prefix, delta in plans:
            for period_start, part in split_fn(merged).items():
                period_end = period_start + delta
                if period_end <= new_min or period_start > new_max:
                    continue
                for sec in intervals:
                    written += _save_set(
                        resample(part, sec), data_root / f"{prefix}h{sec:03d}s",
                        hours, sec, period_start, period_end,
                    )

    logger.info("保存完了: %d ファイル（ALL %d 行）", len(written), merged.height)
    return SaveReport(
        written=written,
        rows_window=new_df.height,
        rows_all=merged.height,
        all_range=all_range,
        bytes_1sec=bytes_1sec,
    )
