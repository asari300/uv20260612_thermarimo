import json

import httpx
import pytest
import respx

from src.mod.api_client import OndotoriAPIError, OndotoriClient

URL = OndotoriClient.BASE_URL

RATE_HEADERS = {
    "X-RateLimit-Limit": "20",
    "X-RateLimit-Reset": "60",
    "X-RateLimit-Remaining": "19",
    "X-RateLimit-Remaining-DataCount": "116800",
}


@respx.mock
def test_fetch_csv_success(csv2_builder):
    body_text = csv2_builder([("2026-06-10 12:00:00", "25.1", "60.2")])
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            text=body_text,
            headers={"Content-Type": "text/csv; charset=utf-8", **RATE_HEADERS},
        )
    )
    with OndotoriClient("apikey", "loginid1", "pass") as client:
        text, rate = client.fetch_csv("EXAMPLE1", 1000, 2000)

    assert text == body_text
    assert (rate.limit, rate.reset, rate.remaining, rate.remaining_datacount) == (
        20,
        60,
        19,
        116800,
    )

    request = route.calls.last.request
    assert request.method == "POST"
    assert request.headers["X-HTTP-Method-Override"] == "GET"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {
        "api-key": "apikey",
        "login-id": "loginid1",
        "login-pass": "pass",
        "remote-serial": "EXAMPLE1",
        "unixtime-from": 1000,
        "unixtime-to": 2000,
        "number": 65535,
        "type": "csv2",
    }


@respx.mock
def test_fetch_csv_number_clamped():
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, text="", headers=RATE_HEADERS)
    )
    with OndotoriClient("k", "i", "p") as client:
        client.fetch_csv("EXAMPLE1", 1000, 2000, number=100_000)
    assert json.loads(route.calls.last.request.content)["number"] == 65535


@respx.mock
def test_fetch_csv_auth_error():
    respx.post(URL).mock(
        return_value=httpx.Response(
            401, json={"error": {"code": 401, "message": "Unauthorized"}}
        )
    )
    with OndotoriClient("bad", "bad", "bad") as client:
        with pytest.raises(OndotoriAPIError) as excinfo:
            client.fetch_csv("EXAMPLE1", 1000, 2000)
    assert excinfo.value.status == 401
    assert excinfo.value.code == 401
    assert "Unauthorized" in str(excinfo.value)


@respx.mock
def test_fetch_csv_non_json_error_body():
    respx.post(URL).mock(return_value=httpx.Response(503, text="Service Unavailable"))
    with OndotoriClient("k", "i", "p") as client:
        with pytest.raises(OndotoriAPIError) as excinfo:
            client.fetch_csv("EXAMPLE1", 1000, 2000)
    assert excinfo.value.status == 503
    assert excinfo.value.code is None
    assert "Service Unavailable" in excinfo.value.message


@respx.mock
def test_fetch_csv_429_waits_and_retries(csv2_builder):
    body_text = csv2_builder([("2026-06-10 12:00:00", "25.1", "60.2")])
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                headers={"X-RateLimit-Reset": "7"},
                json={"error": {"code": 429, "message": "Too Many Requests"}},
            )
        return httpx.Response(200, text=body_text, headers=RATE_HEADERS)

    respx.post(URL).mock(side_effect=responder)
    waits: list[float] = []
    with OndotoriClient("k", "i", "p", sleep_func=waits.append) as client:
        text, _rate = client.fetch_csv("EXAMPLE1", 1000, 2000)

    assert text == body_text
    assert calls["n"] == 2
    assert waits == [7]


@respx.mock
def test_fetch_csv_429_twice_raises():
    respx.post(URL).mock(
        return_value=httpx.Response(
            429,
            headers={"X-RateLimit-Reset": "5"},
            json={"error": {"code": 429, "message": "Too Many Requests"}},
        )
    )
    waits: list[float] = []
    with OndotoriClient("k", "i", "p", sleep_func=waits.append) as client:
        with pytest.raises(OndotoriAPIError) as excinfo:
            client.fetch_csv("EXAMPLE1", 1000, 2000)
    assert excinfo.value.status == 429
    assert waits == [5]  # 再試行は1回のみ
