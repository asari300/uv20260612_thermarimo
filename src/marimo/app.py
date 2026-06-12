"""温湿度モニタリング marimo アプリ。

起動: uv run marimo run src/marimo/app.py （開発時は run の代わりに edit）
"""

import marimo

app = marimo.App(width="medium")


@app.cell
def _():
    import sys as _sys
    from pathlib import Path as _Path

    # marimo はアプリファイルを直接ロードするため、`src.mod` を import できるよう
    # リポジトリルートをパスへ追加する（cwd に依存しない）
    _repo_root = str(_Path(__file__).resolve().parents[2])
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)

    from datetime import datetime, timedelta

    import marimo as mo
    import polars as pl

    from src.mod.collector import run_collection
    from src.mod.config import load_settings
    from src.mod.metadata import load_meta
    from src.mod.periods import JST
    from src.mod.plotting import build_figure, downsample_for_display

    settings = load_settings()
    return (
        JST,
        build_figure,
        datetime,
        downsample_for_display,
        load_meta,
        mo,
        pl,
        run_collection,
        settings,
        timedelta,
    )


@app.cell
def _(mo):
    refresh = mo.ui.refresh(default_interval="60s", label="自動再読込")
    refresh
    return (refresh,)


@app.cell
def _(load_meta, mo, refresh, settings):
    refresh  # 定期再読込（スケジューラ等の別プロセス更新を反映）
    meta = load_meta(settings.data_root / "meta.json")
    _range = (
        f"{meta.last_data_range[0]:%Y-%m-%d %H:%M:%S} 〜 {meta.last_data_range[1]:%Y-%m-%d %H:%M:%S}"
        if meta.last_data_range
        else "—"
    )
    mo.hstack(
        [
            mo.stat(meta.fetch_count, label="データ取得回数"),
            mo.stat(meta.request_count, label="APIリクエスト回数"),
            mo.stat(
                f"{meta.last_fetch_at:%Y-%m-%d %H:%M:%S}" if meta.last_fetch_at else "—",
                label="最終取得日時",
            ),
            mo.stat(_range, label="データ範囲"),
            mo.stat(f"{meta.bytes_1sec:,} B", label="1秒データ容量(ALL)"),
        ],
        wrap=True,
    )
    return (meta,)


@app.cell
def _(mo):
    interval_dropdown = mo.ui.dropdown(
        options={"1sec": 1, "5sec": 5, "10sec": 10, "60sec": 60, "300sec": 300},
        value="1sec",
        label="表示間隔",
    )
    temp_slider = mo.ui.range_slider(
        start=-10, stop=40, step=1, value=[-10, 40], label="温度軸 [℃]"
    )
    humid_slider = mo.ui.range_slider(
        start=0, stop=100, step=1, value=[0, 100], label="湿度軸 [%]"
    )
    mo.hstack([interval_dropdown, temp_slider, humid_slider], wrap=True)
    return humid_slider, interval_dropdown, temp_slider


@app.cell
def _(JST, datetime, meta, mo, timedelta):
    _now = datetime.now(JST).replace(tzinfo=None, microsecond=0)
    if meta.last_data_range:
        _view_start = meta.last_data_range[0].replace(tzinfo=None)
        _view_end = meta.last_data_range[1].replace(tzinfo=None)
    else:
        _view_start, _view_end = _now - timedelta(hours=12), _now
    view_start = mo.ui.datetime(value=_view_start, label="表示開始 (JST)")
    view_end = mo.ui.datetime(value=_view_end, label="表示終了 (JST)")
    fetch_start = mo.ui.datetime(value=_now - timedelta(hours=12), label="取得開始 (JST)")
    fetch_end = mo.ui.datetime(value=_now, label="取得終了 (JST)")
    fetch_button = mo.ui.run_button(label="WebStorage から取得")
    mo.vstack(
        [
            mo.hstack([view_start, view_end], wrap=True),
            mo.hstack([fetch_start, fetch_end, fetch_button], wrap=True),
        ]
    )
    return fetch_button, fetch_end, fetch_start, view_end, view_start


@app.cell
def _(interval_dropdown, pl, refresh, settings):
    refresh
    _dir = settings.data_root / f"ALLh{interval_dropdown.value:03d}s"
    _files = (
        sorted(p for p in _dir.glob("ALL*.parquet") if not p.stem.endswith("_T"))
        if _dir.exists()
        else []
    )
    all_df = pl.read_parquet(_files[-1]) if _files else None
    return (all_df,)


@app.cell
def _(
    JST,
    all_df,
    build_figure,
    downsample_for_display,
    humid_slider,
    mo,
    pl,
    settings,
    temp_slider,
    view_end,
    view_start,
):
    if all_df is None:
        _out = mo.md("データがまだありません。下の取得ボタンか `uv run main.py` で取得してください。")
    else:
        _start = view_start.value.replace(tzinfo=JST)
        _end = view_end.value.replace(tzinfo=JST)
        _df = all_df.filter(pl.col("dateTime").is_between(_start, _end))
        _df_disp, _disp_interval = downsample_for_display(_df)
        _fig = build_figure(
            _df_disp,
            settings.devices,
            temp_range=tuple(temp_slider.value),
            humid_range=tuple(humid_slider.value),
        )
        _plot = mo.ui.plotly(_fig)
        if _disp_interval is None:
            _out = _plot
        else:
            _out = mo.vstack(
                [
                    mo.md(
                        f"※ 表示点数を抑えるため {_disp_interval} 秒平均へ自動間引き"
                        f"（{_df.height:,} 行 → {_df_disp.height:,} 行）。"
                        "保存データは間引きされません。表示間隔を大きくすると間引きなしで表示できます。"
                    ),
                    _plot,
                ]
            )
    _out
    return


@app.cell
def _(JST, fetch_button, fetch_end, fetch_start, mo, run_collection, settings):
    mo.stop(not fetch_button.value, mo.md("「WebStorage から取得」ボタンで手動取得を実行します。"))
    _result = run_collection(
        settings,
        fetch_start.value.replace(tzinfo=JST),
        fetch_end.value.replace(tzinfo=JST),
    )
    _lines = [
        f"- {d.serial} ({d.label}): "
        + (f"{d.rows} 件" if d.error is None else f"失敗 — {d.error}")
        for d in _result.devices
    ]
    mo.md(
        "**取得完了**\n\n"
        + "\n".join(_lines)
        + f"\n\n保存 {len(_result.report.written)} ファイル"
        f"（ウィンドウ {_result.report.rows_window} 行 / ALL {_result.report.rows_all} 行）"
    )
    return


if __name__ == "__main__":
    app.run()
