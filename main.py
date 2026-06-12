"""おんどとり WebStorage からの手動データ取得 CLI。

使い方:
    uv run main.py                  # 現在時刻に応じた12時間ウィンドウを取得
    uv run main.py --start "2026-06-10 12:00:00" --end "2026-06-11 00:00:00"
"""

import argparse
import logging
import sys
from datetime import datetime

from pydantic import ValidationError

from src.mod.collector import CollectionError, run_collection
from src.mod.config import load_settings
from src.mod.periods import JST, window_for_run
from src.mod.storage import ensure_data_dirs


def _parse_jst(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=JST) if dt.tzinfo is None else dt.astimezone(JST)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="おんどとり WebStorage から温湿度データを1回取得して data/ に保存する"
    )
    parser.add_argument("--start", help="取得開始時刻（JST, 例: 2026-06-10 12:00:00）")
    parser.add_argument("--end", help="取得終了時刻（JST）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if (args.start is None) != (args.end is None):
        parser.error("--start と --end は両方指定してください")
    if args.start:
        start, end = _parse_jst(args.start), _parse_jst(args.end)
    else:
        start, end = window_for_run(datetime.now(JST))

    try:
        settings = load_settings()
    except ValidationError as exc:
        print(
            "設定の読み込みに失敗しました。.config/secrets.toml を用意してください"
            "（雛形: .config/secrets.example.toml）",
            file=sys.stderr,
        )
        print(exc, file=sys.stderr)
        return 1

    ensure_data_dirs(settings.data_root)

    try:
        result = run_collection(settings, start, end)
    except CollectionError as exc:
        print(f"取得に失敗しました: {exc}", file=sys.stderr)
        return 1

    print(f"取得ウィンドウ: {start:%Y-%m-%d %H:%M:%S} 〜 {end:%Y-%m-%d %H:%M:%S} (JST)")
    for device in result.devices:
        status = f"{device.rows} 件" if device.error is None else f"失敗 — {device.error}"
        print(f"  {device.serial} ({device.label}): {status}")
    report = result.report
    print(
        f"保存: {len(report.written)} ファイル"
        f"（ウィンドウ {report.rows_window} 行 / ALL {report.rows_all} 行）"
    )
    meta = result.meta
    print(
        f"メタ: 取得 {meta.fetch_count} 回 / APIリクエスト {meta.request_count} 回"
        f" / ALL 1秒 Parquet {meta.bytes_1sec:,} bytes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
