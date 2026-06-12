"""Plotly グラフ生成（温度=左軸・実線 / 湿度=右軸・破線、機器ごとに色分け）。"""

from __future__ import annotations

import math

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from src.mod.config import DeviceConfig
from src.mod.resample import resample

DEVICE_COLORS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728")

# ブラウザへ送る点数の上限目安。超えると Plotly JSON が肥大化して
# marimo の出力上限（既定 5MB）に達するため、表示用に平均で間引く。
MAX_PLOT_POINTS = 5000


def downsample_for_display(
    df: pl.DataFrame, max_points: int = MAX_PLOT_POINTS
) -> tuple[pl.DataFrame, int | None]:
    """表示用に max_points 以下となる間隔へ平均で間引く（保存データには影響しない）。

    間引き不要なら (df, None)、実施したら (間引き後 df, 適用間隔秒) を返す。
    """
    if df.height <= max_points:
        return df, None
    span = (df["dateTime"].max() - df["dateTime"].min()).total_seconds()
    interval = max(1, math.ceil(span / max(1, max_points - 1)))
    if interval == 1:
        return df, None
    return resample(df, interval), interval


def build_figure(
    df: pl.DataFrame,
    devices: list[DeviceConfig],
    temp_range: tuple[float, float] = (-10, 40),
    humid_range: tuple[float, float] = (0, 100),
    x_range: tuple | None = None,
) -> go.Figure:
    """ワイド形式（dateTime, n_TDB, n_RH）から 2軸グラフを生成する。"""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    x = df["dateTime"].to_list() if df.height else []
    for idx, device in enumerate(devices, start=1):
        color = DEVICE_COLORS[(idx - 1) % len(DEVICE_COLORS)]
        tdb_col, rh_col = f"{idx}_TDB", f"{idx}_RH"
        if tdb_col in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=df[tdb_col].to_list() if df.height else [],
                    mode="lines",
                    name=f"{device.label} 温度",
                    line=dict(color=color, dash="solid"),
                    yhoverformat=".1f",
                ),
                secondary_y=False,
            )
        if rh_col in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=df[rh_col].to_list() if df.height else [],
                    mode="lines",
                    name=f"{device.label} 湿度",
                    line=dict(color=color, dash="dash"),
                    yhoverformat=".1f",
                ),
                secondary_y=True,
            )
    fig.update_yaxes(title_text="温度 [℃]", range=list(temp_range), secondary_y=False)
    fig.update_yaxes(title_text="湿度 [%RH]", range=list(humid_range), secondary_y=True)
    fig.update_xaxes(title_text="時刻 (JST)")
    if x_range is not None:
        fig.update_xaxes(range=list(x_range))
    fig.update_layout(legend=dict(orientation="h"), margin=dict(t=30))
    return fig
