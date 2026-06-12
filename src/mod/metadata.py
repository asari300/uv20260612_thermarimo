"""メタ情報（取得回数・リクエスト回数等）の data/meta.json への永続化。"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class Meta(BaseModel):
    fetch_count: int = 0  # データ取得実行回数
    request_count: int = 0  # API 個別リクエスト回数（ページング・機器数を含む概算）
    last_fetch_at: datetime | None = None
    last_data_range: tuple[datetime, datetime] | None = None
    bytes_1sec: int = 0  # ALLh001s の非翻訳 Parquet のバイト数


def load_meta(path: Path) -> Meta:
    if not path.exists():
        return Meta()
    return Meta.model_validate_json(path.read_text(encoding="utf-8"))


def save_meta(meta: Meta, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def update_after_fetch(
    meta: Meta,
    *,
    n_requests: int,
    data_range: tuple[datetime, datetime] | None,
    bytes_1sec: int,
    fetched_at: datetime,
) -> Meta:
    return meta.model_copy(
        update={
            "fetch_count": meta.fetch_count + 1,
            "request_count": meta.request_count + n_requests,
            "last_fetch_at": fetched_at,
            "last_data_range": data_range,
            "bytes_1sec": bytes_1sec,
        }
    )
