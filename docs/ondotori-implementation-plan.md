# おんどとり WebStorage 温湿度モニタリング Webアプリ — 実装計画プロンプト

**TL;DR**

- おんどとりWebStorage公開APIの「指定期間・件数によるデータの取得」エンドポイント（`https://api.webstorage.jp/v1/devices/data`、POST + `X-HTTP-Method-Override: GET`、JSONボディ、レート制限「20回/60秒、もしくは160,000件/3600秒/機器毎」、`number`上限65,535・デフォルト16,000、`remote-serial`は**1台ずつ**指定、`type=csv2`でT&D Graph互換CSV）を正確に織り込んだ、Claude Code向けの完成実装計画プロンプトを以下にまとめた。
- 12時間×1秒間隔＝43,200点は上限65,535点未満のため**1リクエストで取得可能（ページング不要）**。`type=csv2`を採用すれば"Date/Time"列が機器の時差（GMT+9:00）補正済みJSTで返るため、unixtimeのタイムゾーン変換を回避できる（公式に「UTC」の明示はないが、ドキュメント例の値1504191600＝2017-09-01 00:00:00 JSTから標準UTCエポック秒と確認）。
- そのまま渡せる日本語の実装計画プロンプト本体（モジュール分割・関数シグネチャ・ディレクトリ構成・スケジューラ・データモデル・テスト方針まで）は「実装計画プロンプト本体」セクション全文。

---

## Key Findings（調査で確定した事実）

**API（公式リファレンスより抽出）**

- エンドポイント／メソッド：`https://api.webstorage.jp/v1/devices/data`、POST、`X-HTTP-Method-Override: GET`、`Content-Type: application/json`、HTTPS必須（HTTPは403）。
- 必須パラメータ：`api-key`（45文字）、`login-id`（8文字、参照専用ID可）、`login-pass`（4〜16文字）、`remote-serial`（8文字、**複数台指定不可**）。任意：`unixtime-from`／`unixtime-to`（UNIX時間）、`number`（デフォルト16,000・上限65,535）、`type`（json/csv/csv2）。
- 件数挙動：from/toはAND条件。期間内データが`number`超過時は`unixtime-to`起点で新しい方から`number`件のみ取得し古い側を切り捨て。`number`以下なら全件。
- レスポンス：JSON（`serial`/`model`/`name`/`time_diff`/`channel[]`/`data[]`、`data.unixtime`・`data.data-id`・`data.ch1`・`data.ch2`）またはCSV（UTF-8）。**`type=csv2`は"Date/Time"列が機器の時差・夏時間補正済みの`yyyy-mm-dd HH:mm:ss`（JST）**で返り、2行目ヘッダに「時差:GMT+9:00/夏時間:off」と明記される。
- タイムゾーン：`unixtime-*`および`data.unixtime`は標準UTCエポック秒。公式に「UTC」の明示語はないが、リクエスト例2「2017年8月1日00:00:00～2017年9月1日00:00:00…2017年8月分」で値`1504191600`をJST 2017-09-01 00:00:00として扱う記載から確認（JSONレスポンス例の`time_diff`は分単位で、JST機器は`"540"`、`dst_bias`は`"60"`固定）。
- チャンネル：ch1=温度（unit "C"）、ch2=湿度（unit "%"）。記録データ内エラー値はE0（通信）/E1（センサ）/E2（アンダー）/E3（オーバー）。`data-id`は0〜65535の連番で連続性チェックに利用可。
- レート制限ヘッダ：`X-RateLimit-Limit`／`X-RateLimit-Reset`（単位時間秒数）／`X-RateLimit-Remaining`（残回数）／`X-RateLimit-Remaining-DataCount`（残データ件数）。
- エラー：200=正常。`{"error":{"code":..,"message":..}}`。400フォーマット／401認証／403 HTTPS必須／415 JSON不正／429レート超過／503サーバ障害。
- API KEYはWebStorage管理画面「Account > API KEYの管理」で発行（API経由の取得・更新は不可）。

**機器 TR72A2（メーカー仕様、ティアンドデイ公式・販売代理店より）**

- 標準版TR72A2：温度[1ch] 0〜55℃（精度±0.5℃）、湿度[1ch] 10〜95%RH（精度±5%RH at25℃,50%RH）。高精度版TR72A2-S：温度-25〜70℃（±0.3℃）、湿度0〜99%RH（±2.5%RH）。本計画は型番TR72A2を前提。
- 記録間隔：15通り（1秒〜60分、最小1秒）。本体データ記録容量：30,000件×2ch。Ch.1=温度、Ch.2=湿度の2チャンネル。

---

## Details ― 実装計画プロンプト本体（Claude Codeへそのまま渡す）

> 以下のマークダウン全文をAIコーディングエージェントに渡してください。

---

あなたはPython製のデータ収集・可視化Webアプリを実装するシニアエンジニアです。以下の計画に厳密に従い、モジュール分割された保守性の高いコードを実装してください。

### 1. プロジェクト概要と目的

おんどとり（T&D社）WebStorageに自動送信されている温湿度データロガー **TR72A2 2台分**（シリアル `EXAMPLE1`, `EXAMPLE2`）の記録データを、WebStorage公開API経由で6時間ごとに定期取得し、Polarsで時系列処理（結合・重複排除・複数間隔へのリサンプリング・複数期間幅への分割）した上でCSV/TSV/Parquetに保存し、marimo + Plotlyでダッシュボード表示するアプリを構築する。各機器はCh.1=温度（℃）、Ch.2=湿度（%RH）の2チャンネル。元データは1秒間隔。タイムゾーンは日本時間（JST, GMT+9）。

参考機器仕様：TR72A2 標準版は温度0〜55℃（±0.5℃）・湿度10〜95%RH（±5%RH）、記録間隔は1秒〜60分（15通り）、本体記録容量30,000件×2ch。

### 2. おんどとり WebStorage API 仕様まとめ（調査結果）

- **エンドポイント**：`https://api.webstorage.jp/v1/devices/data`（「指定期間・件数によるデータの取得」。対応機種 TR7A2/7A, TR-7nw/wb/wf, TR4A, TR32B にTR72A2が該当）。
- **HTTPメソッド**：POST。ヘッダに `X-HTTP-Method-Override: GET` を付与。`Content-Type: application/json`。Host `api.webstorage.jp:443`。HTTPS必須（HTTPは403）。
- **リクエストパラメータ（JSONボディ）**：
  - `api-key`（必須, 45文字）
  - `login-id`（必須, 8文字。参照専用IDでも可）
  - `login-pass`（必須, 4〜16文字）
  - `remote-serial`（必須, 8文字。**複数台指定不可。1台ずつリクエストする**）
  - `unixtime-from`（任意, number。指定時刻より新しいデータ＝この時刻を含まず以降）
  - `unixtime-to`（任意, number。デフォルトはアクセス時刻。指定時刻未満のデータ）
  - `number`（任意, number。デフォルト16,000、上限65,535。超指定は65,535に丸め）
  - `type`（任意, `json`/`csv`/`csv2`。デフォルトjson。**`csv2`がT&D Graph互換CSV**。`csv`はjson_encodeされた値のCSV化）
- **件数挙動**：from/toはAND条件。期間内データが`number`超過時は`unixtime-to`起点で新しい方から`number`件のみ取得し古い側切り捨て。`number`以下なら全件。
- **タイムゾーン（要確認・推定込み）**：`unixtime-from`/`unixtime-to`・`data.unixtime`は標準UNIX時間（UTCエポック秒、タイムゾーン非依存）。公式ドキュメントに「UTC」の明示記述はないが、リクエスト例2が「2017年8月1日00:00:00～2017年9月1日00:00:00…2017年8月分」とし値`1504191600`をJST 2017-09-01 00:00:00として扱うことから、人間可読日時はJST記述と確認できる。JSON取得時はクライアント側で+9時間してJST表示する必要がある。機器の時差は`time_diff`（分単位、JSTは`"540"`、`dst_bias`は`"60"`固定）で返る。**`type=csv2`では"Date/Time"列が機器の時差・夏時間補正済みの`yyyy-mm-dd HH:mm:ss`（JST）**で返るため、CSV取得を採用すれば変換不要。
- **レスポンス形式**：JSONまたはCSV（`application/json; charset=utf-8` または `text/csv; charset=utf-8`、UTF-8）。CSV(csv2)は1〜3行目ヘッダ（1行目="Date/Time","Date/Time","No.1",… 2行目=時差情報・ch名称（例「時差:GMT+9:00/夏時間:off」）・3行目=単位）、4行目以降がデータ行（測定時刻, Excelシリアル値, ch1値, ch2値…）。JSONは`serial`/`model`/`name`/`time_diff`/`channel[]`/`data[]`。
- **チャンネル**：ch1=温度（unit "C"）、ch2=湿度（unit "%"）。値は文字型。エラー時はEで始まる値（E0通信/E1センサ/E2アンダー/E3オーバー）。
- **data-id**：0〜65535の連番、超えると0に戻る。unixtimeと併用で連続性チェック可。
- **レート制限**：20回/60秒、もしくは160,000件/3600秒/機器毎。レスポンスヘッダ `X-RateLimit-Limit`／`X-RateLimit-Reset`（単位時間秒数）／`X-RateLimit-Remaining`（残回数）／`X-RateLimit-Remaining-DataCount`（残データ件数）。
- **1リクエスト最大点数**：12時間×1秒間隔＝43,200点で上限65,535点未満のため**1リクエストで取得可能・ページング不要**。将来の安全策として件数が`number`超過時は`unixtime-to`を取得済み最古unixtimeに更新して後方ページングする戦略を実装（公式に明示手順はなく件数切り捨て挙動からの推定）。
- **認証**：API KEYはWebStorage管理画面（Account > API KEYの管理）で発行する45文字文字列。API経由の取得・更新は不可。login-id/login-passは利用者ID（または参照専用ID）とパスワード。
- **エラー**：HTTP 200が正常。エラー時JSON `{"error":{"code":..,"message":..}}`。400フォーマット／401認証／403 HTTPS必須／415 JSON不正／429レート超過／503サーバ障害。

### 3. 技術スタックと依存パッケージ（uv管理）

パッケージ管理は uv。`uv init` で初期化、`uv add` で依存追加。Python >=3.11。

`pyproject.toml`案：

```toml
[project]
name = "ondotori-monitor"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "marimo>=0.9",
    "plotly>=5.20",
    "polars>=1.0",
    "apscheduler>=3.10,<4.0",
    "httpx>=0.27",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]

[dependency-groups]
dev = ["pytest>=8.0", "pytest-mock", "respx", "ruff", "mypy"]
```

- HTTPクライアントは `httpx`（同期Client、タイムアウト・リトライ制御が容易）。
- 設定管理は `pydantic-settings`（`.config`/環境変数から型安全に読込）。
- APSchedulerは安定版3.x系（BackgroundScheduler / CronTrigger / DateTrigger）を使用。

### 4. ディレクトリ/ファイル構成

```
repo
├── pyproject.toml
├── uv.lock
├── .python-version
├── .gitignore                      # .config/secrets.toml 等を除外
├── README.md
├── src
│   ├── marimo
│   │   └── app.py                  # marimoアプリ本体
│   └── mod
│       ├── __init__.py
│       ├── config.py               # 設定・機密情報読込
│       ├── api_client.py           # WebStorage APIクライアント
│       ├── periods.py              # 期間計算（4実行時刻の12hウィンドウ）
│       ├── parser.py               # CSVレスポンス→Polars変換
│       ├── storage.py              # 結合・重複排除・分割・保存
│       ├── resample.py             # リサンプリング（1/5/10/60/300sec）
│       ├── filename.py             # ファイル名生成
│       ├── metadata.py             # メタ情報（取得回数・リクエスト回数等）管理
│       ├── collector.py            # 取得→処理→保存の統合フロー
│       ├── scheduler.py            # APSchedulerジョブ定義
│       └── plotting.py             # Plotlyグラフ生成
├── data
│   ├── 012h001s/  012h005s/  012h010s/  012h060s/  012h300s/   # 12時間幅×5間隔
│   ├── 024h001s/  024h005s/  024h010s/  024h060s/  024h300s/   # 1日幅×5間隔
│   ├── 168h001s/  168h005s/  168h010s/  168h060s/  168h300s/   # 週次幅×5間隔
│   └── ALLh001s/  ALLh005s/  ALLh010s/  ALLh060s/  ALLh300s/   # 全結合×5間隔
└── .config
    ├── secrets.toml                # 実際の機密情報（gitignore対象）
    └── secrets.example.toml        # サンプル（コミット対象）
```

- dataディレクトリは hours∈{012,024,168,ALL} × seconds∈{001,005,010,060,300} の計15個。命名 `{hours:03d}h{seconds:03d}s`（ALLのみ文字列"ALL"を用い`ALLh001s`等）。起動時に自動生成する。

### 5. モジュール設計（src/mod）

**config.py — 設定・機密情報読込**
責務：`.config/secrets.toml`と環境変数から認証情報・対象機器・保存設定を型安全に読込。

```python
class DeviceConfig(BaseModel):
    serial: str            # "EXAMPLE1"
    label: str             # 表示名

class Settings(BaseSettings):
    api_key: str
    login_id: str
    login_pass: str
    devices: list[DeviceConfig]
    data_root: Path = Path("data")
    request_timeout: float = 30.0
    resample_intervals: list[int] = [1, 5, 10, 60, 300]

def load_settings(config_dir: Path = Path(".config")) -> Settings: ...
```

**api_client.py — WebStorage APIクライアント**
責務：単一機器・単一期間のデータ取得。POST・ヘッダ付与・レート制限ヘッダ読取・エラー変換。

```python
class OndotoriAPIError(Exception):
    def __init__(self, status: int, code: int | None, message: str): ...

class RateLimitInfo(BaseModel):
    limit: int; reset: int; remaining: int; remaining_datacount: int

class OndotoriClient:
    BASE_URL = "https://api.webstorage.jp/v1/devices/data"
    def __init__(self, api_key, login_id, login_pass, timeout=30.0): ...
    def fetch_csv(self, remote_serial: str, unixtime_from: int,
                  unixtime_to: int, number: int = 65535
                  ) -> tuple[str, RateLimitInfo]:
        """type=csv2 でCSV本文(str)とレート情報を返す。200以外はOndotoriAPIError。"""
    def _build_body(self, serial, ufrom, uto, number) -> dict: ...
```

- ボディ：`{"api-key":..,"login-id":..,"login-pass":..,"remote-serial": serial,"unixtime-from": ufrom,"unixtime-to": uto,"number": number,"type":"csv2"}`。
- レート制限尊重：機器ごとの連続リクエスト間に最低3秒スリープ（20回/60秒に余裕）。`X-RateLimit-Remaining`が0なら`X-RateLimit-Reset`秒待機。

**periods.py — 期間計算**
責務：実行時刻（JST）から12時間幅のfrom/toを算出。

```python
JST = ZoneInfo("Asia/Tokyo")

def window_for_run(run_dt: datetime) -> tuple[datetime, datetime]:
    """02:00→前日12:00〜当日00:00 / 08:00→前日18:00〜当日06:00
    14:00→当日00:00〜当日12:00 / 20:00→当日06:00〜当日18:00"""

def to_unixtime(dt: datetime) -> int: ...   # JST aware datetime → epoch秒
```

- 設計意図：6時間ごとに12時間幅を取得し隣接ウィンドウが6時間オーバーラップする冗長設計で境界欠損を防ぐ。重複は保存時にunixtimeで排除。

**parser.py — CSVレスポンス→Polars変換**
責務：csv2のヘッダ3行をスキップし `[timestamp, serial, temperature, humidity]` のDataFrameに変換。

```python
def parse_csv2(csv_text: str, serial: str) -> pl.DataFrame:
    """スキーマ: timestamp(Datetime["us","Asia/Tokyo"]), serial(str),
    temperature(Float64), humidity(Float64)。
    "Date/Time"列はJST済み文字列。Eで始まるエラー値はnullに変換。"""
```

- 1列目"Date/Time"を`%Y-%m-%d %H:%M:%S`でパースしJSTローカライズ。2列目（Excelシリアル値）は無視。3列目=温度、4列目=湿度。

**resample.py — リサンプリング**
責務：1秒データを5/10/60/300秒へダウンサンプリング。温湿度は平均で集約。

```python
def resample(df: pl.DataFrame, interval_sec: int) -> pl.DataFrame:
    """group_by_dynamic("timestamp", every=f"{interval_sec}s",
    closed="left", group_by="serial") で温湿度を mean 集約。
    interval_sec==1 はそのまま返す。"""
```

- 集約方法：温度・湿度とも算術平均（`pl.col(...).mean()`）を既定。物理量の代表値として平均が妥当（必要なら最大/最小列も併設可）。

**filename.py — ファイル名生成**
責務：命名規則 `{範囲:03d}h{間隔:03d}s_YYYYMMDDThhmmss-YYYYMMDDThhmmss.{ext}`。

```python
def make_filename(hours: int | str, seconds: int,
                  start: datetime, end: datetime, ext: str) -> str:
    """hours=12/24/168 はゼロ埋め3桁、'ALL'はそのまま'ALL'。
    例: 012h001s_20260610T120000-20260611T000000.csv
        ALLh060s_20260101T000000-20260611T180000.parquet"""
```

**storage.py — 結合・重複排除・分割・保存**
責務：新規取得データを既存ALLと結合・重複排除し、各期間幅×各間隔で保存。

```python
def append_and_dedup(existing: pl.LazyFrame | None,
                     new: pl.DataFrame) -> pl.DataFrame:
    """concat → unique(subset=["serial","timestamp"], keep="last")
    → sort(["serial","timestamp"])。"""

def split_daily(df: pl.DataFrame) -> dict[date, pl.DataFrame]: ...
def split_weekly(df: pl.DataFrame) -> dict[date, pl.DataFrame]:
    """日曜00:00:00〜翌日曜00:00:00で区切る。
    group_by_dynamic("timestamp", every="1w", start_by="sunday")。"""

def save_dataframe(df: pl.DataFrame, path: Path, ext: str) -> int:
    """ext: csv/tsv/parquet。csv/tsvはUTF-8-Sig（write_csv(..., include_bom=True)）、
    tsvはseparator='\t'。parquetはwrite_parquet。書き込みバイト数を返す。"""

def persist_all(new_df: pl.DataFrame, settings: Settings) -> SaveReport:
    """12h(取得ウィンドウ単位)/24h(日次)/168h(週次)/ALL を、
    1/5/10/60/300秒の各間隔で全15ディレクトリ×3フォーマット保存。"""
```

- 保存フォーマットはCSV・TSV・Parquetの3種。Parquet以外はUTF-8-Sig（`include_bom=True`）。
- ALLは新規取得ごとに再出力。12hは取得ウィンドウ単位、24hは日次、168hは週次。

**metadata.py — メタ情報管理**
責務：取得回数・総リクエスト回数・最終取得日時・1secデータ容量等をJSONで永続化。

```python
class Meta(BaseModel):
    fetch_count: int = 0          # データ取得実行回数
    request_count: int = 0        # API個別リクエスト回数（機器×実行）
    last_fetch_at: datetime | None = None
    last_data_range: tuple[datetime, datetime] | None = None
    bytes_1sec: int = 0           # ALL 1secデータ容量(byte)

def load_meta(path: Path) -> Meta: ...
def save_meta(meta: Meta, path: Path) -> None: ...
def update_after_fetch(meta, n_requests, data_range, bytes_1sec) -> Meta: ...
```

- 保存先 `data/meta.json`。marimoアプリと共有。

**collector.py — 統合フロー**
責務：「期間決定→2台分取得→パース→結合保存→メタ更新」を統合。手動・定期両方から呼ぶ。

```python
def run_collection(settings: Settings,
                   start: datetime, end: datetime) -> CollectionResult:
    """各deviceについてfetch_csv→parse_csv2、結合、persist_all、メタ更新。
    例外は各機器単位で捕捉しログ。全機器失敗時はraiseして
    スケジューラのリトライ対象にする。"""
```

**scheduler.py** はセクション7、**plotting.py** はセクション6を参照。

### 6. marimoアプリ設計（src/marimo/app.py）

セル構成（上から下へ依存）：

1. **import/初期化**：`import marimo as mo`, polars, plotly, mod各種。`settings = load_settings()`。
2. **メタ情報表示**：`meta = load_meta(...)`。最終取得日時・データ取得回数・リクエスト回数・合計データ範囲・1secデータ容量(byte)を `mo.md`/`mo.stat` で表示。
3. **データ読込**：選択間隔のALL Parquetを `pl.scan_parquet` で遅延読込。
4. **UIコントロール**：
   - `interval_dropdown = mo.ui.dropdown(options={"1sec":1,"5sec":5,"10sec":10,"60sec":60,"300sec":300}, value="1sec")`
   - 期間入力：`mo.ui.date_range(...)` ＋開始/終了時刻。デフォルトは最後に取得したデータ範囲。
   - 軸レンジ：温度 `mo.ui.range_slider(-10,40,value=[-10,40])`、湿度 `mo.ui.range_slider(0,100,value=[0,100])`、横軸幅は既定12時間。
   - 手動取得：`fetch_button = mo.ui.run_button(label="WebStorageから取得")` ＋取得期間入力。
5. **グラフ描画**：UI値を参照し選択間隔データを読み、`plotting.build_figure(...)`で図を生成、`mo.ui.plotly(fig)`で表示。
6. **手動取得実行**：`mo.stop(not fetch_button.value)` でガード後 `run_collection(settings, start, end)` を実行し、結果と更新後メタを表示。

`plotting.build_figure`仕様：

```python
def build_figure(df: pl.DataFrame, devices: list[DeviceConfig],
                 temp_range=(-10,40), humid_range=(0,100),
                 x_range=None) -> go.Figure:
    """make_subplots(specs=[[{"secondary_y": True}]])。
    各機器: 温度=実線(go.Scatter, line=dict(dash="solid"), secondary_y=False)、
            湿度=破線(line=dict(dash="dash"), secondary_y=True)。
    左Y軸=温度℃[-10,40]、右Y軸=湿度%[0,100]、X軸=時刻(既定幅12h)。
    機器ごとに色を分け、凡例に機器ラベルとch種別を表示。"""
```

- 2台分の表示：機器ごとに固有色（EXAMPLE1=青系, EXAMPLE2=橙系）を割り当て、温度=実線・湿度=破線で機器内ch種別を区別。計4トレース。各軸レンジはUIで変更可能。
- 注意：marimoでPlotly図を表示する際は `fig.show()` を呼ばず、図オブジェクトを最終式にするか `mo.ui.plotly(fig)` を使う（`fig.show()`はKeyError要因）。

状態管理：UI要素のreactive valueで基本完結（`mo.state`は原則不要）。メタ情報の永続化は`data/meta.json`ファイル経由（セッション外でスケジューラが更新するため、表示セルは`mo.ui.refresh`で定期再読込し最新化）。

### 7. スケジューラ設計（src/mod/scheduler.py）

- `BackgroundScheduler(timezone=ZoneInfo("Asia/Tokyo"))` を使用。
- 4つのcronジョブ：`CronTrigger(hour=2, minute=0)`, `hour=8`, `hour=14`, `hour=20`（いずれもJST）。
- 各ジョブは `periods.window_for_run(now_jst)` で期間決定→`collector.run_collection` を実行。
- **リトライ**：ジョブ内で例外発生時 `scheduler.add_job(..., trigger="date", run_date=now+timedelta(minutes=5))` で5分後の単発リトライを登録。リトライ回数上限（例3回）を設け上限到達でログ＆中断。`EVENT_JOB_ERROR`リスナーでの失敗捕捉でも可。
- `coalesce=True`, `misfire_grace_time=300` を設定し起動直後の取りこぼしを制御。
- スケジューラはmarimoアプリと別プロセス（`python -m src.mod.scheduler`等のエントリ）で常駐させ、両者は`data/`ファイルとmeta.jsonを介して連携する。

### 8. データモデル（Polars schema）

全保存ファイル共通スキーマ：

| カラム | 型 | 説明 |
|---|---|---|
| timestamp | Datetime("us","Asia/Tokyo") | 測定時刻（JST） |
| serial | Utf8/Categorical | 機器シリアル（EXAMPLE1/EXAMPLE2） |
| temperature | Float64 | Ch.1 温度℃（エラー値はnull） |
| humidity | Float64 | Ch.2 湿度%RH（エラー値はnull） |

- timestampはcsv2のJST済み文字列をパースしtimezone-aware Datetimeで保持。CSV/TSV出力はISO8601相当文字列、Parquetはtimezone情報を保持。重複排除キーは`(serial, timestamp)`。

### 9. 設定・機密情報管理

- `.config/secrets.toml`（gitignore対象）に実値：

```toml
api_key = "YOUR_45_CHAR_API_KEY"
login_id = "USERNAME"
login_pass = "PASSWORD"

[[devices]]
serial = "EXAMPLE1"
label = "1号機"
[[devices]]
serial = "EXAMPLE2"
label = "2号機"
```

- `.config/secrets.example.toml` を同構造のプレースホルダでコミット。
- 環境変数（`ONDOTORI_API_KEY`等）でのオーバーライドも`pydantic-settings`で許可。
- `.gitignore` に `.config/secrets.toml`, `data/`, `.venv/`, `__pycache__/` を記載。

### 10. エラーハンドリングとロギング方針

- 標準`logging`で構造化ログ（INFO:取得開始/完了・件数・レート残、WARNING:機器単位失敗・E値検出、ERROR:全失敗・リトライ枯渇）。`data/logs/`にローテーション出力。
- APIエラーは`OndotoriAPIError`に集約しHTTPステータス別に分岐（429は`reset`秒待機して即リトライ可、400/401/403/415は即失敗・リトライ無意味としてログのみ）。
- レート制限：`X-RateLimit-Remaining`が0なら`X-RateLimit-Reset`秒待機。機器間に固定スリープ。
- 記録データ内Eエラー値（E0-E3）はnull化しつつWARNINGログ。
- ネットワーク例外（`httpx.TimeoutException`等）はスケジューラの5分後リトライ対象。

### 11. 実装ステップ（フェーズ分けタスクリスト）

1. **フェーズ0 環境構築**：`uv init`、依存追加、ディレクトリ・15個のdataフォルダ・.config雛形生成、.gitignore。
2. **フェーズ1 設定とAPIクライアント**：config.py、api_client.py実装。参照専用ID等で単発取得を疎通確認。
3. **フェーズ2 パース・期間計算**：parser.py、periods.py。csv2サンプルでパースのユニットテスト。
4. **フェーズ3 時系列処理**：resample.py、storage.py、filename.py。結合・重複排除・分割・15ディレクトリ保存を検証。
5. **フェーズ4 メタ情報と統合フロー**：metadata.py、collector.py。手動1回実行で全成果物生成を確認。
6. **フェーズ5 スケジューラ**：scheduler.py。4時刻cron＋5分リトライ。短縮間隔でテスト。
7. **フェーズ6 marimoアプリ**：plotting.py、app.py。グラフ・UI・手動取得ボタン・メタ表示。
8. **フェーズ7 仕上げ**：ログ整備、README、エラーパス検証、型チェック（mypy）・lint（ruff）。

### 12. テスト方針

- **ユニットテスト（pytest）**：parser（csv2固定文字列→期待DataFrame、E値→null）、periods（4実行時刻→期待from/to、JST境界）、filename（命名規則）、resample（既知系列→平均値）、storage（重複排除・週次分割の境界＝日曜00:00）。
- **APIクライアント**：httpxをモック（respx/pytest-mock）し、200/400/401/429レスポンスとレートヘッダ解釈を検証。実APIは叩かない。
- **結合テスト**：モックレスポンスで`collector.run_collection`を通し、15ディレクトリ×3フォーマット生成とmeta.json更新を確認。
- **手動E2E**：参照専用IDで実APIから短期間取得し、グラフ表示まで確認（CI対象外）。

以上の計画に従って実装してください。「要確認」とした項目（特にunixtimeのタイムゾーン解釈）は、`type=csv2`取得を前提とすることで回避できます。

---

## Recommendations（実装着手の優先順位と判断基準）

1. **まず`type=csv2`を採用して着手せよ。** これによりタイムゾーン変換ロジック（JSON+9hの実装と検証）が不要になり、最大の不確実性（公式に「UTC」明示なし）を回避できる。JSONが必要になるのは、`data-id`によるギャップ検出を厳密に行いたい場合のみ。その判断は「欠損データの連続性チェック要件が出てきたら」が分岐点。
2. **疎通確認は参照専用IDで行う。** 公開APIは参照専用IDで利用可能なため、書き込み権限のある本ID/パスワードをCIや開発環境に置かずに済む。
3. **1リクエスト=12時間/1秒/43,200点で固定し、ページングは初期実装に含めない。** 上限65,535点に対し余裕があり、ページングは過剰設計。ただし将来1秒未満の取得や24時間超の窓に拡張する場合は、`unixtime-to`後方シフト方式を有効化する（しきい値：1窓のデータ点数が60,000点を超えたら分割）。
4. **レート制限は機器間3秒スリープ＋429時`Reset`秒待機で十分。** 4時刻×2機器=8リクエスト/日であり、20回/60秒・160,000件/3600秒/機器の上限に対し大幅な余裕がある。レート設計を複雑化しないこと。
5. **スケジューラとmarimoは別プロセスに分離し、`data/`とmeta.jsonで疎結合に。** marimoのreactiveセッションに収集ジョブを埋めると、ブラウザを閉じると停止する。常駐収集はBackgroundScheduler常駐プロセスで担保し、UIは`mo.ui.refresh`で最新ファイルを読み直す構成が堅牢。

## Caveats（留意点・未確認事項）

- **unixtimeのタイムゾーン**：公式ドキュメントに「UTC」の明示文言はない。標準UTCエポック秒であることはリクエスト例（1504191600＝2017-09-01 00:00:00 JST）からの確認であり、`type=csv2`採用でこの不確実性を実装上回避する前提で計画している。JSON取得に切り替える場合は`time_diff`（分単位、JST="540"）でのJST変換を必ず実装・テストすること。
- **ページング手順は公式未記載**：件数超過時の「`unixtime-to`後方シフト」は公式の明示手順ではなく、件数切り捨て挙動からの妥当な推定。
- **機器精度・範囲は型番依存**：本計画はTR72A2（標準版、温度0〜55℃/±0.5℃、湿度10〜95%RH/±5%RH）前提。高精度版TR72A2-S（温度-25〜70℃/±0.3℃、湿度0〜99%RH/±2.5%RH）を使う場合はグラフ軸の既定レンジ（-10〜40℃, 0〜100%）が実測範囲と合致するか再確認すること。
- **本体記録容量30,000件×2ch・現在値グラフ保存は最大450日分**：長期間の遡及取得には機器側・WebStorage側の保存上限がある。`unixtime-from`を450日より前に設定しても取得できない可能性がある。
- **ライブラリ挙動の注意**：marimoでPlotlyは`fig.show()`不可（`mo.ui.plotly`または最終式表示）。Polars `unique`はデフォルト`maintain_order=False`のため、重複排除後は明示的に`sort`すること。APScheduler 3.xと4.xはAPIが大きく異なる（本計画は3.x前提）。
- **タイムスタンプの厳密性**：csv2の"Date/Time"は機器の時差・夏時間設定を反映する。日本国内設置で夏時間OFF（"夏時間:off"）が前提だが、機器設定が異なる場合はヘッダ2行目の時差表記をパースして検証するロジックを追加するのが安全。
