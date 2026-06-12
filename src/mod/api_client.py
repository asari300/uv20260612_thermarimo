"""おんどとり WebStorage API クライアント。"""

from __future__ import annotations

import logging
import time
from typing import Callable

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

NUMBER_MAX = 65535  # API 仕様上の number 上限（超過指定は API 側でも丸められる）


class OndotoriAPIError(Exception):
    """HTTP 200 以外のレスポンス（API エラー）。"""

    def __init__(self, status: int, code: int | None, message: str) -> None:
        super().__init__(f"HTTP {status} (code={code}): {message}")
        self.status = status
        self.code = code
        self.message = message


class RateLimitInfo(BaseModel):
    """レスポンスヘッダのレート制限情報（ヘッダ欠落時は None）。"""

    limit: int | None = None
    reset: int | None = None
    remaining: int | None = None
    remaining_datacount: int | None = None


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


class OndotoriClient:
    """単一機器・単一期間のデータ取得を行う同期クライアント。

    429（レート超過）は X-RateLimit-Reset 秒（不明時 60 秒）待機して 1 回だけ
    再試行する。それ以外の 4xx/5xx は即時 OndotoriAPIError。
    """

    BASE_URL = "https://api.webstorage.jp/v1/devices/data"

    def __init__(
        self,
        api_key: str,
        login_id: str,
        login_pass: str,
        timeout: float = 30.0,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self._login_id = login_id
        self._login_pass = login_pass
        self._sleep = sleep_func
        self._client = httpx.Client(
            timeout=timeout,
            headers={"X-HTTP-Method-Override": "GET"},
        )

    def __enter__(self) -> OndotoriClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_csv(
        self,
        remote_serial: str,
        unixtime_from: int,
        unixtime_to: int,
        number: int = NUMBER_MAX,
    ) -> tuple[str, RateLimitInfo]:
        """type=csv2 で CSV 本文(str)とレート制限情報を返す。200 以外は OndotoriAPIError。"""
        body = self._build_body(remote_serial, unixtime_from, unixtime_to, number)
        response = self._client.post(self.BASE_URL, json=body)
        if response.status_code == 429:
            wait = _int_or_none(response.headers.get("X-RateLimit-Reset")) or 60
            logger.warning("レート制限超過(429)。%d 秒待機して再試行します", wait)
            self._sleep(wait)
            response = self._client.post(self.BASE_URL, json=body)
        rate = RateLimitInfo(
            limit=_int_or_none(response.headers.get("X-RateLimit-Limit")),
            reset=_int_or_none(response.headers.get("X-RateLimit-Reset")),
            remaining=_int_or_none(response.headers.get("X-RateLimit-Remaining")),
            remaining_datacount=_int_or_none(
                response.headers.get("X-RateLimit-Remaining-DataCount")
            ),
        )
        if response.status_code != 200:
            code: int | None = None
            message = response.text
            try:
                error = response.json().get("error", {})
                code = error.get("code")
                message = error.get("message", message)
            except ValueError:
                pass
            raise OndotoriAPIError(response.status_code, code, message)
        return response.text, rate

    def _build_body(self, serial: str, ufrom: int, uto: int, number: int) -> dict:
        return {
            "api-key": self._api_key,
            "login-id": self._login_id,
            "login-pass": self._login_pass,
            "remote-serial": serial,
            "unixtime-from": ufrom,
            "unixtime-to": uto,
            "number": min(number, NUMBER_MAX),
            "type": "csv2",
        }
