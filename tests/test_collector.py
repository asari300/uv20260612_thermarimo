import json
from datetime import datetime, timedelta

import httpx
import polars as pl
import pytest
import respx

from src.mod.api_client import OndotoriClient
from src.mod.collector import (
    CollectionError,
    _fetch_device_window,
    run_collection,
)
from src.mod.config import DeviceConfig, Settings
from src.mod.metadata import load_meta
from src.mod.periods import JST, to_unixtime

URL = OndotoriClient.BASE_URL

RATE_HEADERS = {
    "X-RateLimit-Limit": "20",
    "X-RateLimit-Reset": "60",
    "X-RateLimit-Remaining": "19",
    "X-RateLimit-Remaining-DataCount": "116800",
}


def make_settings(tmp_path) -> Settings:
    return Settings(
        api_key="K" * 45,
        login_id="USER0001",
        login_pass="pass",
        devices=[
            DeviceConfig(serial="SERIAL01", label="1号機"),
            DeviceConfig(serial="SERIAL02", label="2号機"),
        ],
        data_root=tmp_path / "data",
    )


def csv_responder(csv2_builder, times: list[str]):
    """機器シリアルごとに値を変えた csv2 レスポンスを返す respx side_effect。"""

    def _respond(request: httpx.Request) -> httpx.Response:
        serial = json.loads(request.content)["remote-serial"]
        base = 20.0 if serial == "SERIAL01" else 30.0
        rows = [(t, str(base + i * 0.1), str(50 + i)) for i, t in enumerate(times)]
        return httpx.Response(200, text=csv2_builder(rows), headers=RATE_HEADERS)

    return _respond


def read_all_parquet(settings: Settings) -> pl.DataFrame:
    files = [
        p
        for p in (settings.data_root / "ALLh001s").iterdir()
        if p.suffix == ".parquet" and not p.stem.endswith("_T")
    ]
    assert len(files) == 1
    return pl.read_parquet(files[0])


@respx.mock
def test_run_collection_end_to_end(tmp_path, csv2_builder):
    settings = make_settings(tmp_path)
    start = datetime(2026, 6, 10, 12, 0, tzinfo=JST)
    end = datetime(2026, 6, 11, 0, 0, tzinfo=JST)
    times = [f"2026-06-10 12:00:0{i}" for i in range(5)]
    respx.post(URL).mock(side_effect=csv_responder(csv2_builder, times))

    result = run_collection(settings, start, end, sleep_seconds=0)

    assert [d.rows for d in result.devices] == [5, 5]
    assert all(d.error is None for d in result.devices)

    data_root = settings.data_root
    # ワイド形式で結合されている（5タイムスタンプ × 2機器分の列）
    df = read_all_parquet(settings)
    assert df.columns == ["dateTime", "1_TDB", "1_RH", "2_TDB", "2_RH"]
    assert df.height == 5
    assert df["1_TDB"].to_list() == [20.0, 20.1, 20.2, 20.3, 20.4]
    assert df["2_TDB"].to_list() == [30.0, 30.1, 30.2, 30.3, 30.4]
    assert df["1_RH"].to_list() == df["2_RH"].to_list() == [50.0, 51.0, 52.0, 53.0, 54.0]

    # 12h ウィンドウ: 各間隔ディレクトリに 3形式×(通常+_T)=6 ファイル
    window_files = sorted(p.name for p in (data_root / "012h001s").iterdir())
    assert window_files == [
        "012h001s_20260610T120000-20260611T000000.csv",
        "012h001s_20260610T120000-20260611T000000.parquet",
        "012h001s_20260610T120000-20260611T000000.tsv",
        "012h001s_20260610T120000-20260611T000000_T.csv",
        "012h001s_20260610T120000-20260611T000000_T.parquet",
        "012h001s_20260610T120000-20260611T000000_T.tsv",
    ]
    for dir_name in ("012h300s", "ALLh001s", "ALLh300s", "024h001s", "168h001s"):
        assert len(list((data_root / dir_name).iterdir())) == 6, dir_name

    # 日次・週次のファイル名は期間境界
    daily = sorted(p.name for p in (data_root / "024h001s").iterdir())
    assert daily[0] == "024h001s_20260610T000000-20260611T000000.csv"
    weekly = sorted(p.name for p in (data_root / "168h001s").iterdir())
    assert weekly[0] == "168h001s_20260607T000000-20260614T000000.csv"  # 日曜起点

    # _T ファイルに換算列がある
    t_parquet = data_root / "012h001s" / "012h001s_20260610T120000-20260611T000000_T.parquet"
    tdf = pl.read_parquet(t_parquet)
    assert tdf.columns[-5:] == ["SerialTime", "1_TDB_K", "1_RH_Phi", "2_TDB_K", "2_RH_Phi"]
    assert tdf["1_TDB_K"][0] == 293.15

    # メタ情報
    meta = load_meta(data_root / "meta.json")
    assert meta.fetch_count == 1
    assert meta.request_count == 2
    assert meta.bytes_1sec > 0
    assert result.meta == meta


@respx.mock
def test_run_collection_dedups_overlap_across_runs(tmp_path, csv2_builder):
    settings = make_settings(tmp_path)
    start1 = datetime(2026, 6, 10, 12, 0, tzinfo=JST)
    end1 = start1 + timedelta(hours=12)
    start2 = start1 + timedelta(hours=6)
    end2 = start2 + timedelta(hours=12)
    times1 = ["2026-06-10 12:00:00", "2026-06-10 12:00:01", "2026-06-10 12:00:02"]
    times2 = ["2026-06-10 12:00:02", "2026-06-10 12:00:03"]  # 1点が前回と重複

    route = respx.post(URL)
    route.mock(side_effect=csv_responder(csv2_builder, times1))
    run_collection(settings, start1, end1, sleep_seconds=0)
    route.mock(side_effect=csv_responder(csv2_builder, times2))
    result = run_collection(settings, start2, end2, sleep_seconds=0)

    df = read_all_parquet(settings)  # 旧 ALL は置き換えられ非_T parquet は1つ
    assert df.height == 4  # 3 + 2 - 重複1（ワイド形式なので機器数は行数に影響しない）
    # 12h ウィンドウは取得ごとに蓄積（2回分 × 6ファイル）
    assert len(list((settings.data_root / "012h001s").iterdir())) == 12
    assert result.meta.fetch_count == 2
    assert result.meta.request_count == 4


@respx.mock
def test_run_collection_partial_failure_then_repair(tmp_path, csv2_builder):
    """機器2が失敗 → null 列で保存 → 再取得成功で null が埋まる（update セマンティクス）。"""
    settings = make_settings(tmp_path)
    start = datetime(2026, 6, 10, 12, 0, tzinfo=JST)
    end = datetime(2026, 6, 11, 0, 0, tzinfo=JST)
    times = ["2026-06-10 12:00:00", "2026-06-10 12:00:01"]

    def failing_responder(request: httpx.Request) -> httpx.Response:
        serial = json.loads(request.content)["remote-serial"]
        if serial == "SERIAL02":
            return httpx.Response(
                401, json={"error": {"code": 401, "message": "Unauthorized"}}
            )
        return csv_responder(csv2_builder, times)(request)

    route = respx.post(URL)
    route.mock(side_effect=failing_responder)
    result1 = run_collection(settings, start, end, sleep_seconds=0)

    ok, failed = result1.devices
    assert ok.rows == 2 and ok.error is None
    assert failed.error is not None and "401" in failed.error
    df1 = read_all_parquet(settings)
    assert df1["1_TDB"].to_list() == [20.0, 20.1]
    assert df1["2_TDB"].to_list() == [None, None]  # 失敗機器は null

    # 2回目: 両機器成功 → null が埋まり、既存値は保持される
    route.mock(side_effect=csv_responder(csv2_builder, times))
    run_collection(settings, start, end, sleep_seconds=0)
    df2 = read_all_parquet(settings)
    assert df2.height == 2
    assert df2["1_TDB"].to_list() == [20.0, 20.1]
    assert df2["2_TDB"].to_list() == [30.0, 30.1]


@respx.mock
def test_run_collection_all_failed_raises(tmp_path):
    settings = make_settings(tmp_path)
    respx.post(URL).mock(
        return_value=httpx.Response(
            401, json={"error": {"code": 401, "message": "Unauthorized"}}
        )
    )
    with pytest.raises(CollectionError):
        run_collection(
            settings,
            datetime(2026, 6, 10, 12, 0, tzinfo=JST),
            datetime(2026, 6, 11, 0, 0, tzinfo=JST),
            sleep_seconds=0,
        )


@respx.mock
def test_fetch_device_window_pages_backward(csv2_builder):
    """number 件に達したら unixtime-to を最古時刻へシフトして遡る（実APIの両端含む挙動を模擬）。"""
    all_times = [datetime(2026, 6, 10, 12, 0, s, tzinfo=JST) for s in range(7)]

    def paging_responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        ufrom, uto, number = (
            body["unixtime-from"],
            body["unixtime-to"],
            body["number"],
        )
        hits = [t for t in all_times if ufrom <= to_unixtime(t) <= uto]
        newest = sorted(hits)[-number:]
        rows = [(t.strftime("%Y-%m-%d %H:%M:%S"), "25.0", "60.0") for t in newest]
        return httpx.Response(200, text=csv2_builder(rows), headers=RATE_HEADERS)

    respx.post(URL).mock(side_effect=paging_responder)
    with OndotoriClient("k", "i", "p") as client:
        df, n_requests, _rate = _fetch_device_window(
            client,
            "SERIAL01",
            to_unixtime(all_times[0]),
            to_unixtime(all_times[-1]),
            number=3,
        )

    assert n_requests == 3
    assert df.height == 7  # 重複なく全件
    assert df["dateTime"].to_list() == all_times
