from datetime import datetime

import pytest

from src.mod.filename import make_filename


def test_window_filename():
    assert (
        make_filename(12, 1, datetime(2026, 6, 10, 12, 0, 0), datetime(2026, 6, 11, 0, 0, 0), "csv")
        == "012h001s_20260610T120000-20260611T000000.csv"
    )


def test_all_filename():
    assert (
        make_filename("ALL", 60, datetime(2026, 1, 1), datetime(2026, 6, 11, 18, 0, 0), "parquet")
        == "ALLh060s_20260101T000000-20260611T180000.parquet"
    )


def test_invalid_hours_string():
    with pytest.raises(ValueError):
        make_filename("週次", 1, datetime(2026, 1, 1), datetime(2026, 1, 2), "csv")
