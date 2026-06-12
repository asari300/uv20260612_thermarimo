# ondotori-monitor

おんどとり（T&D）WebStorage に送信される温湿度ロガー TR72A2（2台）のデータを公開 API で定期取得し、Polars で処理して CSV/TSV/Parquet に保存、marimo + Plotly で可視化するアプリ。

設計書: [docs/ondotori-implementation-plan.md](docs/ondotori-implementation-plan.md) / [docs/ondotori-phase2-plan.md](docs/ondotori-phase2-plan.md)

## セットアップ

```bash
bash src/Shell/setup_dirs.sh                           # data/ ディレクトリ構成を作成（git clone 直後の初回に実行）
cp .config/secrets.example.toml .config/secrets.toml   # API キー・ID・機器シリアルを記入
uv sync
```

`data/` は gitignore 対象のため clone 直後には存在しない。`setup_dirs.sh` が保存先20ディレクトリと `data/raw` を作成する（冪等。`main.py` やスケジューラの起動時にも自動生成される）。

## 使い方

```bash
# 手動取得（現在時刻に応じた12時間ウィンドウ）
uv run main.py
# 期間指定の手動取得
uv run main.py --start "2026-06-12 12:00:00" --end "2026-06-12 12:05:00"

# 定期取得スケジューラ常駐（毎日 02/08/14/20 時 JST、失敗時5分後リトライ×3）
uv run python -m src.mod.scheduler

# ダッシュボード（WSL 等でブラウザ自動起動に失敗する場合は --headless を付け、
# 表示された URL をブラウザで開く。"gio: ... Operation not supported" は無害）
uv run marimo run src/marimo/app.py --headless

# テスト
uv run pytest

# 診断用: 生 csv2 レスポンスの取得（data/raw/ に保存）
uv run python -m scripts.fetch_raw --start "2026-06-12 12:00:00" --end "2026-06-12 12:05:00"
```

## データ仕様

- 保存先: `data/{範囲}h{間隔:03d}s/`（範囲 = 012/024/168/ALL、間隔 = 001/005/010/060/300 秒の20ディレクトリ）。
  12h=取得ウィンドウ、24h=日次（JST 0時区切り）、168h=週次（日曜0時起点）、ALL=全期間結合（取得ごとに再出力）。
- 形式: CSV / TSV（UTF-8-Sig）と Parquet。各ファイルに換算列付きの `{元ファイル名}_T.{拡張子}` を併産。
- CSV/TSV の測定値は固定小数点表記（`TDB`/`RH`=1桁、`TDB_K`=2桁、`RH_Phi`=3桁。null は空欄）。Parquet は Float64 のまま。
- スキーマ（ワイド形式、列番号は secrets.toml の機器並び順で1始まり）:
  - 通常: `dateTime, 1_TDB, 1_RH, 2_TDB, 2_RH`（JST、温度℃、湿度%RH。機器のエラー値 E0〜E3 は null）
  - `_T`: 上記 + `SerialTime, 1_TDB_K, 1_RH_Phi, 2_TDB_K, 2_RH_Phi`
    - `SerialTime` = Excel シリアル値×86400（1899-12-30 起点の経過秒、整数）
    - `_K` = ℃ + 273.15、`_Phi` = %RH × 0.01
- メタ情報: `data/meta.json`（取得回数・APIリクエスト回数・最終取得・データ範囲・ALL 1秒 Parquet 容量）。
- ダッシュボードは表示点数が約 5,000 を超えると表示用に平均で自動間引きする（保存データは変更されない。間引き時はグラフ上に注記を表示）。
- 重複排除: dateTime の full join + 列ごと coalesce（新値優先、null は既存値を潰さない）。
