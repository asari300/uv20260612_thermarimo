"""実行時刻から取得ウィンドウ（12時間幅）を算出する。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
WINDOW = timedelta(hours=12)


def _as_jst(dt: datetime) -> datetime:
    """naive は JST とみなし、aware は JST へ変換する。"""
    return dt.replace(tzinfo=JST) if dt.tzinfo is None else dt.astimezone(JST)


def window_for_run(run_dt: datetime) -> tuple[datetime, datetime]:
    """実行時刻を直近の6時間グリッド（00/06/12/18時 JST）へ切り捨てた時刻を終端とし、
    そこから12時間遡った区間 [start, end) を返す。

    02:00→前日12:00〜当日00:00 / 08:00→前日18:00〜当日06:00
    14:00→当日00:00〜当日12:00 / 20:00→当日06:00〜当日18:00

    グリッドへの切り捨てにより、リトライ等でずれた実行時刻でも同じウィンドウになる。
    隣接ウィンドウは6時間オーバーラップし、境界点の取りこぼし
    （API の from は指定時刻を含まない）は前後のウィンドウで補完される。
    """
    run = _as_jst(run_dt)
    end = run.replace(hour=run.hour - run.hour % 6, minute=0, second=0, microsecond=0)
    return end - WINDOW, end


def to_unixtime(dt: datetime) -> int:
    """JST の datetime（naive は JST とみなす）を UNIX エポック秒に変換する。"""
    return int(_as_jst(dt).timestamp())
