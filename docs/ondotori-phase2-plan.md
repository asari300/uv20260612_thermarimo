# フェーズ2 実装計画 — 見送り機能の実装・ワイド形式化・Translated 出力・実 API リクエストテスト

原計画（[ondotori-implementation-plan.md](ondotori-implementation-plan.md)）を主仕様としつつ、本書の要件が重なる箇所（特に §8 データモデル）は**本書が優先**する。

## 1. 目的・完了条件

1. MVP で見送った機能の実装: リサンプリング / 日次・週次分割 / metadata / 429 待機リトライ / ページング / スケジューラ / marimo アプリ
2. 保存データのワイド形式化（ヘッダ1行: `dateTime, 1_TDB, 1_RH, 2_TDB, 2_RH`、シリアル列削除）
3. Translated（`_T`）ファイルの併産
4. `.config/secrets.toml` を用いた実 API リクエストテスト（今日 12:00:00〜12:05:00 JST）の実行と結果確認

## 2. 出力スキーマの刷新（ワイド化）— 原計画 §8 を置き換え

### 2.1 スキーマ

| カラム | 型 | 説明 |
| --- | --- | --- |
| dateTime | Datetime("us", "Asia/Tokyo") | 測定時刻（JST） |
| 1_TDB | Float64 | 1号機 乾球温度 ℃（devices[0]） |
| 1_RH | Float64 | 1号機 相対湿度 %RH |
| 2_TDB | Float64 | 2号機 乾球温度 ℃（devices[1]） |
| 2_RH | Float64 | 2号機 相対湿度 %RH |

- 列番号は `settings.devices` の並び順（1始まり）。**並び順を変えると過去データと不整合になる**ため、設定の並びは固定運用とする。
- 機器シリアル（EXAMPLE1 等）の列は持たない。Excel シリアル値列も保存しない（SerialTime は dateTime から導出、§4）。
- CSV/TSV の dateTime は `YYYY-MM-DD HH:MM:SS`（JST、オフセット表記なし）で出力（`write_csv(datetime_format=...)`）。Parquet はタイムゾーン付き型を保持。

### 2.2 パイプライン変更

- **parser.py**: 機器1台分の csv2 → `(dateTime, TDB, RH)` の DataFrame（serial 列廃止）。ヘッダ2行目の時差表記が `GMT+9:00`・夏時間 off 以外なら WARNING（原計画 Caveats 対応）。
- **collector.py**: 機器ごとのフレームを `n_TDB / n_RH` にリネームし `dateTime` で outer join。一部機器失敗時は欠け列を null の Float64 列として補完し、スキーマを常に固定 5 列にする。
- **storage.py のマージ**: 重複排除キーは `dateTime`。**`DataFrame.update(new, on="dateTime", how="full")`（include_nulls=False）** で結合する。ワイド形式では「機器2だけ失敗した再取得」が `unique(keep="last")` だと既存の機器2の値を null で潰してしまうため、null は上書きしない update 方式が必須。
- 既存の data/ に実データは無いため移行処理は不要。MVP の長形式テストはワイド形式に書き換える。

## 3. 数値クリーニングの考察（要件: クォート・空白除去の必要性）

現実装の評価:

- **ダブルクォート**: `csv.reader` が RFC4180 準拠で除去済み → 追加実装不要。
- **前後空白・全角空白**: 値ごとの `str.strip()` 適用済み（全角空白 U+3000 も Python の strip 対象）→ 追加実装不要。
- **数値化**: `float()` → Float64 化済み。E0〜E3 は null 化済み。

追加で実装するもの（プローブで実レスポンスを確認の上）:

- **BOM 除去**: レスポンス先頭に BOM が付く場合、ヘッダ判定 `rows[0][0] == "Date/Time"` が壊れるため `csv_text.lstrip("﻿")` を実装する（防御的・無害）。
- **桁区切りカンマ等**: 実レスポンスで観測された場合のみ対応（機械向け CSV のため想定薄）。

→ 結論: 「クォート・空白は既存実装で除去済み。BOM 対策のみ追加。その他は実データ確認後に判断」。プローブ結果を本書 §6 のテストで報告する。

## 4. Translated（`_T`）出力仕様

- ファイル名: `{元ファイル名}_T.{拡張子}`（例: `012h001s_..._T.csv`）。**全保存ファイル**（全ディレクトリ × csv/tsv/parquet）に併産する。
- 列順: `dateTime, 1_TDB, 1_RH, 2_TDB, 2_RH, SerialTime, 1_TDB_K, 1_RH_Phi, 2_TDB_K, 2_RH_Phi`
  - `n_TDB_K` = `n_TDB + 273.15`
  - `n_RH_Phi` = `n_RH * 0.01`
  - `SerialTime` = Excel シリアル値（日）を**整数秒**に直したもの。

### 4.1 SerialTime の換算式と較正

要件の例: `46183.0000000000 → 3,990,297,600`。`3,990,297,600 / 86400 = 46184` なので、例は **`(シリアル値 + 1) × 86400`** に一致する。

- 仮説: T&D のシリアル値は「1900-01-01 = 1.0（うるう年バグ非互換）」系で、`46183.0 = 2026-06-11 00:00`。このとき `SerialTime = (dateTime(JST naive) − 1899-12-30 00:00) の秒数 = round((シリアル値 + 1) × 86400)` で例と整合する。
- 実装は dateTime からの導出とする: `serial_time(dateTime) = (dateTime − 1899-12-30T00:00:00) // 1秒`。シリアル値列を保持せずに済み、リサンプリング後の行にも正確に付与できる。
- **較正手順**: プローブ取得（§6）で実レスポンスの「Date/Time 列」と「Excel シリアル値列」の対応を確認し、上記仮説を検証する。仮説どおりなら例 `46183 → 3,990,297,600` をユニットテストに固定。**ズレた場合は実装前に報告し換算式の確認を仰ぐ。**

> **較正結果（2026-06-12 実施・確定）**: 実レスポンスは `2026-06-12 12:00:00 JST ↔ シリアル値 46185.5` で、**標準 Excel シリアル（1899-12-30 起点）**だった。仮説の「+1日」は不要で、ユーザー確認の上 **`SerialTime = シリアル値 × 86400`（= dateTime の 1899-12-30 00:00 JST 起点経過秒）で確定**。要件の例 46183 → 3,990,297,600 は 1 日分のズレで、正しくは 46183 → 3,990,211,200（2026-06-10 00:00 JST）。実装は dateTime からの導出（translate.py）。
> あわせてプローブで確認した事実: 全フィールド引用符付き・CRLF・BOM なし・余分な空白なし（クリーニング追加は BOM 防御のみ）、API は from/to の**両端を含む**（公式記載と異なる。ページング境界とウィンドウ境界の重複はマージで排除）。

## 5. 見送り機能の実装設計

### 5.1 resample.py

`group_by_dynamic("dateTime", every=f"{i}s", closed="left")` で 4 値列を `mean()` 集約（ラベルは窓の開始時刻）。`i == 1` はそのまま返す。対象間隔: 5/10/60/300 秒。

### 5.2 日次・週次分割と persist_all（storage.py）

- `split_daily`: JST 0時境界で分割。`split_weekly`: 日曜 0時境界（`group_by_dynamic(every="1w", start_by="sunday")`）。
- `persist_all`: 12h=取得ウィンドウ / 24h=日次 / 168h=週次 / ALL=全結合 を 5 間隔 × 3 形式 ×（通常 + `_T`）で保存。
- 日次・週次は**新規データが触れた日・週のみ**再出力（同名ファイル上書き）。ALL は毎回再出力し旧ファイル削除（現行踏襲）。1回の取得で再出力されるのは概ね 120〜150 ファイル想定（データ量が小さいため許容、遅ければ見直し）。
- ファイル名は期間境界で命名（例: `024h001s_20260612T000000-20260613T000000.csv`）。

### 5.3 metadata.py

原計画どおり `Meta(fetch_count, request_count, last_fetch_at, last_data_range, bytes_1sec)` を `data/meta.json` に永続化。`bytes_1sec` は ALLh001s の**非翻訳 Parquet** のバイト数と定義。collector 成功時に更新。

### 5.4 api_client 強化（429 リトライ・ページング）

- **429**: `X-RateLimit-Reset` 秒（欠落時 60 秒）待機して 1 回だけ再試行、再度 429 なら raise。待機は注入可能にしてテストでは 0 秒化。400/401/403/415 は即時失敗（現行どおり）。
- **成功後** `X-RateLimit-Remaining == 0` なら collector 側で Reset 秒待ってから次機器へ。
- **ページング**（collector のヘルパー `fetch_device_window`）: 取得行数が `number`（65,535）に達したら `unixtime-to` を「取得済み最古 dateTime の unixtime」に更新して後方取得を繰り返し、結合する。12h×1秒=43,200 点では発動しない防御実装（モックでテスト）。

### 5.5 scheduler.py

- APScheduler 3.x。専用プロセスのため `BlockingScheduler(timezone=JST)` を採用（原計画の BackgroundScheduler+常駐ループと機能等価で簡素なため）。
- CronTrigger hour=2/8/14/20、`coalesce=True`・`misfire_grace_time=300`。
- ジョブ: `window_for_run(now)` → `run_collection`。例外時は date トリガで 5 分後リトライを登録、上限 3 回で ERROR ログ。
- 起動: `uv run python -m src.mod.scheduler`。依存追加: `apscheduler>=3.10,<4.0`。

### 5.6 marimo アプリ・plotting.py

- 依存追加: `marimo>=0.9`, `plotly>=5.20`。
- `plotting.build_figure`: ワイド形式対応。`n_TDB`=実線（左軸 ℃, 既定 -10〜40）、`n_RH`=破線（右軸 %, 0〜100）、機器ごとに色分け（計4トレース）。
- `src/marimo/app.py`: 原計画 §6 のセル構成（メタ表示 / 間隔ドロップダウン / 期間・軸レンジ UI / `mo.ui.plotly` / 手動取得ボタン / `mo.ui.refresh`）。ALL Parquet（非翻訳）を `scan_parquet` で読む。
- 起動: `uv run marimo run src/marimo/app.py`（開発時は `edit`）。ユニットテスト対象外（手動確認）。

## 6. リクエストテスト計画（実 API・secrets.toml 使用）

レート影響: 最大 2 回の実行 × 2 機器 = 4 リクエスト（制限 20回/60秒に対し余裕）。認証情報は読み込みのみで、内容は出力・ログに一切表示しない。

1. **プローブ（実装前・1回）**: `scripts/fetch_raw.py`（小さな常設スクリプト）で 12:00:00〜12:05:00 の生 csv2 を取得し `data/` 配下に保存。確認observ点:
   - クォート・空白・BOM・改行コードの実態（§3 の考察の裏取り）
   - Excel シリアル値列と Date/Time 列の対応（§4.1 SerialTime 較正）
   - 実記録間隔（1秒想定 → 期待 299 行/機器。from は指定時刻を含まないため 12:00:01〜12:04:59）
   - レート制限ヘッダの実値
2. **本実行（全実装完了後）**: `uv run main.py --start "2026-06-12 12:00:00" --end "2026-06-12 12:05:00"` を実行し、
   - 全ディレクトリへの出力（通常 + `_T`）、ヘッダ1行・列順・数値型を確認
   - `_T` の SerialTime / `_K`(+273.15) / `_Phi`(×0.01) をスポット検算
   - meta.json の更新を確認し、結果サマリ（行数・ファイル数・レート残）を報告
   - 注: 5 分窓のため 012h ディレクトリのファイル名は実窓 `...T120000-...T120500` となる（ディレクトリ名は公称幅）

## 7. テスト方針（pytest）

- **書き換え**: parser / storage / collector の既存テストをワイド形式へ移行。
- **新規ユニット**: resample（既知系列→平均、closed="left" 境界）/ split_daily・split_weekly（JST 0時・日曜境界）/ translate（**例 46183→3,990,297,600 を固定テスト**、_K・_Phi、列順、`_T` 命名）/ metadata（roundtrip・更新）/ api_client 429（respx で 429→200、待機0秒注入）/ ページング（number 縮小モックで後方シフト）/ update マージ（機器片落ち再取得で既存値が null に潰されないこと）/ scheduler（トリガ時刻計算とリトライ登録のみ、実走なし）。
- **結合**: respx モックで run_collection → 全ディレクトリ×（通常+_T）生成と meta.json 更新。
- **手動 E2E**: §6 の本実行（CI 対象外）。

## 8. 実装順序

1. プローブ実行と考察報告（§3 裏取り・§4.1 較正）— ここで換算式が仮説とズレたら停止して確認
2. ワイド形式移行: parser / collector / storage(update マージ) + 既存テスト書き換え
3. translate.py + `_T` 併産（保存系に組み込み）
4. resample.py + 日次/週次分割 + persist_all 完成
5. metadata.py + collector 統合
6. api_client 強化（429 リトライ・ページング）
7. scheduler.py
8. marimo / plotting.py（依存追加含む）
9. リクエストテスト本実行・結果報告（§6-2）
10. 仕上げ: README 更新（任意: ruff/mypy 導入）

## 9. 要確認事項（指摘がなければ提案どおり実装）

| # | 論点 | 提案（デフォルト） |
| --- | --- | --- |
| 1 | SerialTime 換算式 | 例のとおり `(シリアル値+1)×86400` 相当＝「1899-12-30 起点の経過秒」で実装。プローブで実データと矛盾したら報告・確認 |
| 2 | `_T` の適用範囲 | 全保存ファイル（全ディレクトリ × 3 形式）に併産 |
| 3 | ワイド化の適用範囲 | ALL/Parquet 含む**全保存物**をワイド形式に統一（長形式は全廃）。1号機=devices[0] |
| 4 | CSV/TSV の dateTime 表記 | `YYYY-MM-DD HH:MM:SS`（JST、オフセットなし、Excel 親和） |
