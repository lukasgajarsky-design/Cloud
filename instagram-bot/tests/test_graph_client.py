"""Testy HTTP klienta Meta Graph API: retries, rate limit, chyby, stránkovanie."""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from instagram_bot.exceptions import (
    MetaApiError,
    MetaAuthError,
    MetaNetworkError,
    MetaRateLimitError,
)
from instagram_bot.graph_client import MetaGraphClient, parse_usage_headers


class FakeResponse:
    def __init__(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self._payload = payload
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        pass


def make_client(outcomes: list[Any], **kwargs: Any) -> tuple[MetaGraphClient, FakeSession, list[float]]:
    session = FakeSession(outcomes)
    sleeps: list[float] = []
    client = MetaGraphClient(
        access_token="IGQtoken",
        host="graph.instagram.com",
        api_version="v23.0",
        session=session,  # type: ignore[arg-type]
        sleep=sleeps.append,
        max_retries=3,
        backoff_base_seconds=1,
        backoff_max_seconds=60,
        **kwargs,
    )
    return client, session, sleeps


def graph_error(code: int, message: str = "chyba", **extra: Any) -> dict[str, Any]:
    return {"error": {"message": message, "code": code, "fbtrace_id": "trace", **extra}}


def test_token_is_sent_in_header_not_url() -> None:
    client, session, _ = make_client([FakeResponse(200, {"id": "1"})], app_secret="tajne")
    assert client.get("me", {"fields": "id"}) == {"id": "1"}
    call = session.calls[0]
    assert session.headers["Authorization"] == "Bearer IGQtoken"
    assert "access_token" not in call["params"]
    assert len(call["params"]["appsecret_proof"]) == 64  # HMAC-SHA256 hex
    assert call["url"] == "https://graph.instagram.com/v23.0/me"


def test_retries_server_errors_with_backoff() -> None:
    client, session, sleeps = make_client(
        [FakeResponse(500, graph_error(2)), FakeResponse(503, {}), FakeResponse(200, {"ok": True})]
    )
    assert client.get("x") == {"ok": True}
    assert len(session.calls) == 3 and len(sleeps) == 2


def test_rate_limit_code_waits_then_succeeds() -> None:
    client, _, sleeps = make_client([FakeResponse(400, graph_error(4)), FakeResponse(200, {"ok": True})])
    assert client.get("x") == {"ok": True}
    assert sleeps and sleeps[0] >= 7.5  # pri rate limite čaká dlhšie než pri bežnej chybe


def test_long_rate_limit_raises_with_retry_after() -> None:
    usage = json.dumps({"123": [{"type": "instagram", "call_count": 100, "estimated_time_to_regain_access": 30}]})
    client, _, sleeps = make_client([FakeResponse(400, graph_error(80002), {"X-Business-Use-Case-Usage": usage})])
    with pytest.raises(MetaRateLimitError) as excinfo:
        client.get("x")
    assert excinfo.value.retry_after_seconds == 1800
    assert sleeps == []


def test_auth_error_is_not_retried() -> None:
    client, session, _ = make_client([FakeResponse(400, graph_error(190, "Session has expired"))])
    with pytest.raises(MetaAuthError):
        client.get("x")
    assert len(session.calls) == 1


def test_permanent_error_raises_immediately() -> None:
    client, session, _ = make_client([FakeResponse(400, graph_error(100, "Invalid parameter"))])
    with pytest.raises(MetaApiError) as excinfo:
        client.get("x")
    assert excinfo.value.code == 100 and len(session.calls) == 1


def test_post_read_timeout_is_not_retried_to_avoid_duplicates() -> None:
    client, session, _ = make_client([requests.exceptions.ReadTimeout("timeout")])
    with pytest.raises(MetaNetworkError) as excinfo:
        client.post("c1/replies", data={"message": "ahoj"})
    assert excinfo.value.ambiguous is True
    assert len(session.calls) == 1


def test_get_read_timeout_is_retried() -> None:
    client, session, _ = make_client([requests.exceptions.ReadTimeout("timeout"), FakeResponse(200, {"ok": 1})])
    assert client.get("x") == {"ok": 1}
    assert len(session.calls) == 2


def test_connect_timeout_is_retried_even_for_post() -> None:
    client, session, _ = make_client([requests.exceptions.ConnectTimeout("nope"), FakeResponse(200, {"id": "r1"})])
    assert client.post("c1/replies", data={"message": "ahoj"}) == {"id": "r1"}
    assert len(session.calls) == 2


def test_high_usage_triggers_proactive_throttle() -> None:
    usage = json.dumps({"call_count": 95, "total_time": 20, "total_cputime": 10})
    client, _, sleeps = make_client(
        [FakeResponse(200, {"ok": 1}, {"X-App-Usage": usage})],
        usage_throttle_threshold=75,
        max_throttle_sleep_seconds=60,
    )
    client.get("x")
    assert sleeps == [pytest.approx(48.0)]  # (95-75)/(100-75) * 60


def test_parse_usage_headers_nested() -> None:
    usage = parse_usage_headers(
        {
            "x-business-use-case-usage": json.dumps(
                {"1": [{"call_count": 12, "total_time": 80, "estimated_time_to_regain_access": 2}]}
            )
        }
    )
    assert usage.max_percent == 80 and usage.regain_access_seconds == 120


def test_iterate_follows_cursors_and_respects_limit() -> None:
    pages = [
        FakeResponse(
            200, {"data": [{"id": "1"}, {"id": "2"}], "paging": {"cursors": {"after": "A"}, "next": "https://x"}}
        ),
        FakeResponse(
            200, {"data": [{"id": "3"}, {"id": "4"}], "paging": {"cursors": {"after": "B"}, "next": "https://x"}}
        ),
    ]
    client, session, _ = make_client(pages)
    assert [item["id"] for item in client.iterate("me/media", {"limit": 2}, max_items=3)] == ["1", "2", "3"]
    assert session.calls[1]["params"]["after"] == "A"
