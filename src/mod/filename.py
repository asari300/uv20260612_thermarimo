"""保存ファイル名の生成。"""

from datetime import datetime


def make_filename(hours: int | str, seconds: int, start: datetime, end: datetime, ext: str) -> str:
    """命名規則 `{範囲:03d}h{間隔:03d}s_YYYYMMDDThhmmss-YYYYMMDDThhmmss.{ext}` で生成する。

    hours は 12/24/168 のような整数（ゼロ埋め3桁）か、全期間を表す文字列 "ALL"。
    例: 012h001s_20260610T120000-20260611T000000.csv
        ALLh060s_20260101T000000-20260611T180000.parquet
    """
    if isinstance(hours, str):
        if hours != "ALL":
            raise ValueError(f"hours に指定できる文字列は 'ALL' のみ: {hours!r}")
        hours_part = hours
    else:
        hours_part = f"{hours:03d}"
    stamp = f"{start:%Y%m%dT%H%M%S}-{end:%Y%m%dT%H%M%S}"
    return f"{hours_part}h{seconds:03d}s_{stamp}.{ext}"
