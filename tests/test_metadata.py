from datetime import datetime
from zoneinfo import ZoneInfo

from src.mod.metadata import Meta, load_meta, save_meta, update_after_fetch

JST = ZoneInfo("Asia/Tokyo")


def test_load_meta_missing_returns_defaults(tmp_path):
    meta = load_meta(tmp_path / "meta.json")
    assert meta == Meta()
    assert meta.fetch_count == 0


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "meta.json"
    meta = Meta(
        fetch_count=3,
        request_count=7,
        last_fetch_at=datetime(2026, 6, 12, 14, 0, tzinfo=JST),
        last_data_range=(
            datetime(2026, 6, 10, 12, 0, tzinfo=JST),
            datetime(2026, 6, 12, 12, 5, tzinfo=JST),
        ),
        bytes_1sec=12345,
    )
    save_meta(meta, path)
    assert load_meta(path) == meta


def test_update_after_fetch_increments(tmp_path):
    fetched_at = datetime(2026, 6, 12, 14, 0, tzinfo=JST)
    data_range = (
        datetime(2026, 6, 12, 12, 0, tzinfo=JST),
        datetime(2026, 6, 12, 12, 5, tzinfo=JST),
    )
    meta = update_after_fetch(
        Meta(fetch_count=1, request_count=2),
        n_requests=3,
        data_range=data_range,
        bytes_1sec=999,
        fetched_at=fetched_at,
    )
    assert meta.fetch_count == 2
    assert meta.request_count == 5
    assert meta.last_fetch_at == fetched_at
    assert meta.last_data_range == data_range
    assert meta.bytes_1sec == 999
