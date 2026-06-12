from datetime import datetime

import pytest

from src.mod.periods import JST, to_unixtime, window_for_run


@pytest.mark.parametrize(
    ("run", "expected_start", "expected_end"),
    [
        # 02:00 → 前日12:00〜当日00:00
        (
            datetime(2026, 6, 11, 2, 0, tzinfo=JST),
            datetime(2026, 6, 10, 12, 0, tzinfo=JST),
            datetime(2026, 6, 11, 0, 0, tzinfo=JST),
        ),
        # 08:00 → 前日18:00〜当日06:00
        (
            datetime(2026, 6, 11, 8, 0, tzinfo=JST),
            datetime(2026, 6, 10, 18, 0, tzinfo=JST),
            datetime(2026, 6, 11, 6, 0, tzinfo=JST),
        ),
        # 14:00 → 当日00:00〜当日12:00
        (
            datetime(2026, 6, 11, 14, 0, tzinfo=JST),
            datetime(2026, 6, 11, 0, 0, tzinfo=JST),
            datetime(2026, 6, 11, 12, 0, tzinfo=JST),
        ),
        # 20:00 → 当日06:00〜当日18:00
        (
            datetime(2026, 6, 11, 20, 0, tzinfo=JST),
            datetime(2026, 6, 11, 6, 0, tzinfo=JST),
            datetime(2026, 6, 11, 18, 0, tzinfo=JST),
        ),
        # 年跨ぎ
        (
            datetime(2026, 1, 1, 2, 0, tzinfo=JST),
            datetime(2025, 12, 31, 12, 0, tzinfo=JST),
            datetime(2026, 1, 1, 0, 0, tzinfo=JST),
        ),
    ],
)
def test_window_for_run(run, expected_start, expected_end):
    assert window_for_run(run) == (expected_start, expected_end)


def test_window_for_run_off_grid():
    """リトライ等でグリッド外の時刻に実行されても同じウィンドウになる。"""
    base = window_for_run(datetime(2026, 6, 11, 2, 0, tzinfo=JST))
    assert window_for_run(datetime(2026, 6, 11, 2, 5, 30, tzinfo=JST)) == base
    assert window_for_run(datetime(2026, 6, 11, 5, 59, 59, tzinfo=JST)) == base


def test_window_for_run_naive_treated_as_jst():
    aware = window_for_run(datetime(2026, 6, 11, 14, 0, tzinfo=JST))
    assert window_for_run(datetime(2026, 6, 11, 14, 0)) == aware


def test_to_unixtime_official_doc_example():
    """公式ドキュメントの例: 2017-09-01 00:00:00 JST = 1504191600。"""
    assert to_unixtime(datetime(2017, 9, 1, 0, 0, tzinfo=JST)) == 1504191600
    assert to_unixtime(datetime(2017, 9, 1, 0, 0)) == 1504191600
