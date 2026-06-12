"""期間決定→取得→パース→保存→メタ更新の統合フロー。手動・定期実行の両方から呼ぶ。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import polars as pl

from src.mod.api_client import NUMBER_MAX, OndotoriClient, RateLimitInfo
from src.mod.config import Settings
from src.mod.metadata import Meta, load_meta, save_meta, update_after_fetch
from src.mod.parser import parse_csv2
from src.mod.periods import JST, to_unixtime
from src.mod.storage import SaveReport, persist_all, value_columns

logger = logging.getLogger(__name__)

INTER_REQUEST_SLEEP = 3.0  # レート制限（20回/60秒）への余裕として機器間に挟むスリープ
MAX_PAGES = 10  # 後方ページングの安全弁


class CollectionError(Exception):
    """全機器の取得に失敗した。"""


@dataclass
class DeviceResult:
    serial: str
    label: str
    rows: int = 0
    error: str | None = None


@dataclass
class CollectionResult:
    start: datetime
    end: datetime
    devices: list[DeviceResult]
    report: SaveReport
    meta: Meta


def _fetch_device_window(
    client: OndotoriClient,
    serial: str,
    unixtime_from: int,
    unixtime_to: int,
    *,
    number: int = NUMBER_MAX,
) -> tuple[pl.DataFrame, int, RateLimitInfo]:
    """1機器分を取得する。number 件に達したら unixtime-to を最古時刻へ後方シフトして
    ページングする（12h×1秒=43,200点では発動しない防御実装）。

    実 API は from/to の両端を含むためページ境界が 1 点重複する。dateTime の
    unique で排除する。戻り値は (DataFrame, リクエスト回数, 最終レート情報)。
    """
    frames: list[pl.DataFrame] = []
    n_requests = 0
    cursor_to = unixtime_to
    rate = RateLimitInfo()
    while True:
        csv_text, rate = client.fetch_csv(serial, unixtime_from, cursor_to, number=number)
        n_requests += 1
        page = parse_csv2(csv_text, serial)
        frames.append(page)
        if page.height < number:
            break
        oldest = page["dateTime"].min()
        next_to = to_unixtime(oldest)
        if next_to <= unixtime_from:
            break
        if n_requests >= MAX_PAGES:
            logger.warning("機器 %s: ページ上限 %d 回に到達したため打ち切ります", serial, MAX_PAGES)
            break
        cursor_to = next_to
        if rate.remaining == 0:
            wait = rate.reset or 60
            logger.warning("レート残 0。%d 秒待機します", wait)
            time.sleep(wait)
    df = pl.concat(frames).unique(subset=["dateTime"], keep="first").sort("dateTime")
    return df, n_requests, rate


def build_wide_frame(
    device_frames: dict[int, pl.DataFrame], n_devices: int
) -> pl.DataFrame:
    """機器ごとのフレーム（dateTime, TDB, RH）を dateTime で outer join し、
    欠けた機器の列は null で補完して固定スキーマのワイド形式にする。"""
    wide: pl.DataFrame | None = None
    for idx in range(1, n_devices + 1):
        frame = device_frames.get(idx)
        if frame is None:
            continue
        renamed = frame.rename({"TDB": f"{idx}_TDB", "RH": f"{idx}_RH"})
        wide = (
            renamed
            if wide is None
            else wide.join(renamed, on="dateTime", how="full", coalesce=True)
        )
    assert wide is not None  # 呼び出し元で全滅は除外済み
    cols = value_columns(n_devices)
    missing = [pl.lit(None, dtype=pl.Float64).alias(c) for c in cols if c not in wide.columns]
    if missing:
        wide = wide.with_columns(missing)
    return wide.select(["dateTime", *cols]).sort("dateTime")


def run_collection(
    settings: Settings,
    start: datetime,
    end: datetime,
    *,
    sleep_seconds: float = INTER_REQUEST_SLEEP,
) -> CollectionResult:
    """全機器分を取得・結合して保存し、メタ情報を更新する。

    機器単位の失敗は捕捉してログに残し、全機器が失敗した場合のみ
    CollectionError を送出する（スケジューラのリトライ対象にするため）。
    """
    logger.info("取得開始: %s 〜 %s", start, end)
    ufrom, uto = to_unixtime(start), to_unixtime(end)
    device_frames: dict[int, pl.DataFrame] = {}
    results: list[DeviceResult] = []
    total_requests = 0
    with OndotoriClient(
        settings.api_key,
        settings.login_id,
        settings.login_pass,
        timeout=settings.request_timeout,
    ) as client:
        for idx, device in enumerate(settings.devices, start=1):
            if idx > 1 and sleep_seconds > 0:
                time.sleep(sleep_seconds)
            result = DeviceResult(serial=device.serial, label=device.label)
            try:
                df, n_requests, rate = _fetch_device_window(
                    client, device.serial, ufrom, uto
                )
                total_requests += n_requests
                result.rows = df.height
                device_frames[idx] = df
                logger.info(
                    "機器 %s (%s): %d 件取得（リクエスト %d 回、レート残: %s）",
                    device.serial,
                    device.label,
                    df.height,
                    n_requests,
                    rate.remaining,
                )
            except Exception as exc:
                total_requests += 1  # 失敗した試行も概算で計上
                result.error = str(exc)
                logger.warning(
                    "機器 %s (%s) の取得に失敗: %s", device.serial, device.label, exc
                )
            results.append(result)

    if not device_frames:
        raise CollectionError("全機器の取得に失敗しました")

    new_df = build_wide_frame(device_frames, len(settings.devices))
    report = persist_all(new_df, start, end, settings)

    meta_path = settings.data_root / "meta.json"
    meta = update_after_fetch(
        load_meta(meta_path),
        n_requests=total_requests,
        data_range=report.all_range,
        bytes_1sec=report.bytes_1sec,
        fetched_at=datetime.now(JST),
    )
    save_meta(meta, meta_path)

    logger.info(
        "保存完了: ウィンドウ %d 行 / ALL %d 行 / %d ファイル",
        report.rows_window,
        report.rows_all,
        len(report.written),
    )
    return CollectionResult(
        start=start, end=end, devices=results, report=report, meta=meta
    )
