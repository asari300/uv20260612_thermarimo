"""生の csv2 レスポンスを取得して保存する診断用スクリプト。

使い方:
    uv run python -m scripts.fetch_raw --start "2026-06-12 12:00:00" --end "2026-06-12 12:05:00"

レスポンス本文を data/raw/ にそのまま保存し、レート制限ヘッダを表示する。
認証情報は読み込むだけで一切出力しない。
"""

import argparse
import time
from datetime import datetime
from pathlib import Path

from src.mod.api_client import OndotoriClient
from src.mod.config import load_settings
from src.mod.periods import JST, to_unixtime


def main() -> None:
    parser = argparse.ArgumentParser(description="csv2 生レスポンスの取得（診断用）")
    parser.add_argument("--start", required=True, help="取得開始時刻（JST）")
    parser.add_argument("--end", required=True, help="取得終了時刻（JST）")
    parser.add_argument("--outdir", default="data/raw")
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=JST)
    end = datetime.fromisoformat(args.end).replace(tzinfo=JST)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    with OndotoriClient(
        settings.api_key,
        settings.login_id,
        settings.login_pass,
        timeout=settings.request_timeout,
    ) as client:
        for i, device in enumerate(settings.devices):
            if i > 0:
                time.sleep(3)
            text, rate = client.fetch_csv(
                device.serial, to_unixtime(start), to_unixtime(end)
            )
            path = outdir / (
                f"raw_{device.serial}_{start:%Y%m%dT%H%M%S}-{end:%Y%m%dT%H%M%S}.csv"
            )
            path.write_text(text, encoding="utf-8", newline="")
            print(f"{device.serial} ({device.label}): {len(text)} 文字 -> {path}")
            print(
                f"  rate: limit={rate.limit} remaining={rate.remaining}"
                f" reset={rate.reset} datacount={rate.remaining_datacount}"
            )


if __name__ == "__main__":
    main()
