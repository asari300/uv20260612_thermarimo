"""定期取得スケジューラ。`uv run python -m src.mod.scheduler` で常駐起動する。

marimo アプリとは別プロセスで動かし、data/ と meta.json を介して連携する。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from src.mod.collector import run_collection
from src.mod.config import Settings, load_settings
from src.mod.periods import JST, window_for_run
from src.mod.storage import ensure_data_dirs

logger = logging.getLogger(__name__)

RUN_HOURS = (2, 8, 14, 20)  # JST の定期実行時刻
MAX_RETRIES = 3
RETRY_DELAY = timedelta(minutes=5)


def collect_job(settings: Settings, scheduler, retry: int = 0) -> None:
    """実行時刻から12時間ウィンドウを決めて取得する。失敗時は5分後の単発リトライを登録。"""
    now = datetime.now(JST)
    start, end = window_for_run(now)
    try:
        run_collection(settings, start, end)
    except Exception:
        logger.exception("定期取得に失敗しました（retry=%d）", retry)
        if retry < MAX_RETRIES:
            run_at = now + RETRY_DELAY
            scheduler.add_job(
                collect_job,
                trigger=DateTrigger(run_date=run_at),
                args=[settings, scheduler],
                kwargs={"retry": retry + 1},
                id=f"retry_{run_at:%Y%m%dT%H%M%S}",
                replace_existing=True,
            )
            logger.info("%s に再試行します（%d/%d）", run_at, retry + 1, MAX_RETRIES)
        else:
            logger.error("リトライ上限（%d回）に到達。次回の定期実行まで中断します", MAX_RETRIES)


def build_scheduler(settings: Settings) -> BlockingScheduler:
    """専用プロセス用のため BlockingScheduler を使う（原計画の常駐要件と等価）。"""
    scheduler = BlockingScheduler(timezone=JST)
    for hour in RUN_HOURS:
        scheduler.add_job(
            collect_job,
            trigger=CronTrigger(hour=hour, minute=0, timezone=JST),
            args=[settings, scheduler],
            id=f"collect_{hour:02d}00",
            coalesce=True,
            misfire_grace_time=300,
        )
    return scheduler


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = load_settings()
    ensure_data_dirs(settings.data_root)
    scheduler = build_scheduler(settings)
    logger.info("スケジューラ起動: 毎日 %s 時（JST）に定期取得します", list(RUN_HOURS))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("スケジューラを停止します")


if __name__ == "__main__":
    main()
