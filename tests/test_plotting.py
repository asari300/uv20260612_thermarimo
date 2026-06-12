from datetime import datetime, timedelta

from src.mod.config import DeviceConfig
from src.mod.plotting import build_figure, downsample_for_display

DEVICES = [
    DeviceConfig(serial="SERIAL01", label="1号機"),
    DeviceConfig(serial="SERIAL02", label="2号機"),
]


def test_build_figure_traces(wide_builder):
    df = wide_builder(
        [
            ("2026-06-10T12:00:00", 25.0, 60.0, 30.0, 50.0),
            ("2026-06-10T12:00:01", 25.1, 61.0, 30.1, 51.0),
        ]
    )
    fig = build_figure(df, DEVICES)
    assert [t.name for t in fig.data] == [
        "1号機 温度",
        "1号機 湿度",
        "2号機 温度",
        "2号機 湿度",
    ]
    assert [t.line.dash for t in fig.data] == ["solid", "dash", "solid", "dash"]
    assert [t.yaxis for t in fig.data] == ["y", "y2", "y", "y2"]
    assert [t.yhoverformat for t in fig.data] == [".1f", ".1f", ".1f", ".1f"]
    assert fig.data[0].line.color == fig.data[1].line.color  # 同一機器は同色
    assert fig.data[0].line.color != fig.data[2].line.color


def test_build_figure_empty(wide_builder):
    fig = build_figure(wide_builder([]), DEVICES)
    assert len(fig.data) == 4
    assert all(len(t.x) == 0 for t in fig.data)


def test_downsample_for_display_passthrough(wide_builder):
    df = wide_builder(
        [
            ("2026-06-12T12:00:00", 24.0, 61.0, 18.0, 74.3),
            ("2026-06-12T12:00:01", 24.1, 61.0, 18.1, 74.4),
        ]
    )
    out, interval = downsample_for_display(df)
    assert out is df
    assert interval is None


def test_downsample_for_display_reduces_points(wide_builder):
    """1万行(1秒間隔)を max 1,000 点へ: 11秒平均に間引かれる。"""
    base = datetime(2026, 6, 12, 0, 0, 0)
    rows = [
        ((base + timedelta(seconds=i)).isoformat(), float(i), 50.0, None, None)
        for i in range(10_000)
    ]
    df = wide_builder(rows)
    out, interval = downsample_for_display(df, max_points=1000)
    assert interval == 11  # ceil(9999 / 999)
    assert out.height <= 1000
    # 平均集約されている（窓はエポック整列のため先頭窓は部分集合。0..10 の範囲内の平均）
    assert 0.0 <= out["1_TDB"][0] <= 10.0
    assert out["1_TDB"].is_sorted()
