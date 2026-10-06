"""Nízkoúrovňový HTTP klient pre oficiálne Meta Graph API (knižnica ``requests``).

Čo tento modul rieši:

* **Autentifikácia** – access token posielame v hlavičke ``Authorization: Bearer``,
  nie v URL, aby sa nedostal do logov proxy serverov. Voliteľne pridávame
  ``appsecret_proof`` (HMAC-SHA256 tokenu tajomstvom aplikácie).
* **Retries s exponenciálnym vyčkávaním** pri 429, 5xx a prechodných chybách.
* **Rate limiting** – Meta väčšinou nevracia 429, ale HTTP 400/403 s kódmi
  4, 17, 32, 613 alebo 800xx. Tie rozpoznáme a počkáme. Navyše čítame hlavičky
  ``X-App-Usage`` / ``X-Business-Use-Case-Usage`` a pri vysokom využití limitu
  bot preventívne spomalí ešte predtým, než ho Meta zablokuje.
* **Ochrana pred duplicitami** – zápisové operácie (odpoveď na komentár, DM,
  publikovanie) nie sú idempotentné. Ak vyprší čas pri čítaní odpovede, požiadavka
  mohla prejsť, preto ju neopakujeme a vyhodíme ``MetaNetworkError(ambiguous=True)``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

import requests

from . import __version__
from .exceptions import (
    MetaApiError,
    MetaAuthError,
    MetaNetworkError,
    MetaRateLimitError,
)
from .retry import compute_backoff

logger = logging.getLogger(__name__)

# Kódy chýb Graph API, ktoré znamenajú prekročenie limitu volaní.
RATE_LIMIT_ERROR_CODES: Final[frozenset[int]] = frozenset(
    {4, 17, 32, 613, 80001, 80002, 80003, 80004, 80005, 80006, 80008, 80009, 80014}
)
# Prechodné chyby („Unknown error“, „Service temporarily unavailable“).
TRANSIENT_ERROR_CODES: Final[frozenset[int]] = frozenset({1, 2})
# Neplatný/expirovaný token alebo session.
AUTH_ERROR_CODES: Final[frozenset[int]] = frozenset({102, 190})
# Hlavičky, v ktorých Meta posiela percentuálne využitie limitov.
USAGE_HEADERS: Final[tuple[str, ...]] = ("x-app-usage", "x-business-use-case-usage", "x-page-usage")
_USAGE_KEYS: Final[tuple[str, ...]] = ("call_count", "total_cputime", "total_time")

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class UsageSnapshot:
    """Najvyššie využitie limitu (v %) a odhad, kedy Meta znova povolí volania."""

    max_percent: float = 0.0
    regain_access_seconds: float = 0.0


def parse_usage_headers(headers: Mapping[str, str]) -> UsageSnapshot:
    """Prečíta hlavičky s využitím limitov a vráti najhoršiu (najvyššiu) hodnotu.

    Formát hlavičiek sa líši (``X-App-Usage`` je plochý objekt,
    ``X-Business-Use-Case-Usage`` je mapa ``{id: [ {...}, ... ]}``), preto
    prechádzame JSON rekurzívne a hľadáme známe kľúče.
    """
    max_percent = 0.0
    regain_seconds = 0.0
    for name in USAGE_HEADERS:
        raw = headers.get(name)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for entry in _iter_usage_entries(data):
            for key in _USAGE_KEYS:
                value = entry.get(key)
                if isinstance(value, (int, float)):
                    max_percent = max(max_percent, float(value))
            minutes = entry.get("estimated_time_to_regain_access")
            if isinstance(minutes, (int, float)) and minutes > 0:
                regain_seconds = max(regain_seconds, float(minutes) * 60)
    return UsageSnapshot(max_percent=max_percent, regain_access_seconds=regain_seconds)


def _iter_usage_entries(data: Any) -> Iterator[Mapping[str, Any]]:
    """Rekurzívne vráti všetky objekty, ktoré obsahujú metriky využitia."""
    if isinstance(data, dict):
        if any(key in data for key in _USAGE_KEYS):
            yield data
        else:
            for value in data.values():
                yield from _iter_usage_entries(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_usage_entries(item)


class MetaGraphClient:
    """Tenký, ale robustný wrapper nad ``requests.Session`` pre Graph API."""

    def __init__(
        self,
        *,
        access_token: str,
        host: str,
        api_version: str,
        app_secret: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 5,
        backoff_base_seconds: float = 2.0,
        backoff_max_seconds: float = 120.0,
        usage_throttle_threshold: float = 75.0,
        max_throttle_sleep_seconds: float = 60.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not access_token:
            raise ValueError("Chýba Meta access token.")
        self._base_url = f"https://{host}/{api_version}"
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": f"instagram-bot/{__version__}",
            }
        )
        # appsecret_proof dokazuje, že volanie prichádza od vlastníka aplikácie –
        # ukradnutý token bez tajomstva aplikácie je potom nepoužiteľný.
        self._appsecret_proof = (
            hmac.new(app_secret.encode("utf-8"), access_token.encode("utf-8"), hashlib.sha256).hexdigest()
            if app_secret
            else None
        )
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self._throttle_threshold = usage_throttle_threshold
        self._max_throttle_sleep = max_throttle_sleep_seconds
        self._sleep = sleep
        self.last_usage = UsageSnapshot()

    @property
    def base_url(self) -> str:
        return self._base_url

    def close(self) -> None:
        """Uzavrie HTTP spojenia (volá sa pri ukončení bota)."""
        self._session.close()

    # ------------------------------------------------------------------ verejné API
    def get(self, path: str, params: Mapping[str, Any] | None = None) -> JsonDict:
        """GET je idempotentný – pri sieťovej chybe ho môžeme bezpečne zopakovať."""
        return self.request("GET", path, params=params, idempotent=True)

    def post(
        self,
        path: str,
        *,
        data: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        idempotent: bool = False,
    ) -> JsonDict:
        """POST – predvolene NEidempotentný (nezopakuje sa pri nejasnom výsledku)."""
        return self.request("POST", path, data=data, json_body=json_body, idempotent=idempotent)

    def iterate(self, path: str, params: Mapping[str, Any] | None = None, *, max_items: int) -> Iterator[JsonDict]:
        """Prechádza stránkovaný zoznam (``data`` + ``paging.cursors.after``).

        Kurzory používame namiesto ``paging.next`` URL, aby sme do ďalších
        požiadaviek neprenášali parametre (napr. tokeny) vložené Meta-ou do URL.
        """
        query: dict[str, Any] = dict(params or {})
        remaining = max_items
        while remaining > 0:
            page = self.get(path, query)
            items = page.get("data") or []
            for item in items:
                if isinstance(item, dict):
                    yield item
                    remaining -= 1
                    if remaining <= 0:
                        return
            paging = page.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not items or not paging.get("next") or not after:
                return
            query["after"] = after

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        idempotent: bool,
    ) -> JsonDict:
        """Vykoná požiadavku s retries, backoffom a kontrolou rate limitu.

        :raises MetaAuthError: neplatný token – nemá zmysel pokračovať.
        :raises MetaRateLimitError: limit prekročený na dlhší čas, než chceme čakať.
        :raises MetaNetworkError: sieťová chyba po vyčerpaní pokusov.
        :raises MetaApiError: iná (trvalá) chyba API, napr. neplatný parameter.
        """
        url = self._url(path)
        query: dict[str, Any] = dict(params or {})
        if self._appsecret_proof:
            query["appsecret_proof"] = self._appsecret_proof

        for attempt in range(self._max_retries + 1):
            is_last_attempt = attempt >= self._max_retries
            started = time.monotonic()
            try:
                response = self._session.request(
                    method,
                    url,
                    params=query or None,
                    data=data,
                    json=json_body,
                    timeout=self._timeout,
                )
            except requests.exceptions.ConnectTimeout as exc:
                # Spojenie sa vôbec nenadviazalo → požiadavka určite neprešla.
                self._retry_or_raise(exc, method, path, attempt, is_last_attempt, safe=True, ambiguous=False)
                continue
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                # Timeout pri čítaní / prerušené spojenie → výsledok je neistý.
                self._retry_or_raise(
                    exc, method, path, attempt, is_last_attempt, safe=idempotent, ambiguous=not idempotent
                )
                continue

            elapsed = time.monotonic() - started
            logger.debug("%s %s → HTTP %s (%.2fs)", method, path, response.status_code, elapsed)
            usage = parse_usage_headers(response.headers)
            self.last_usage = usage

            if response.status_code < 400:
                self._throttle(usage)
                return self._parse_json(response, method, path)

            error = self._error_from_response(response)

            if response.status_code == 401 or error.code in AUTH_ERROR_CODES:
                raise MetaAuthError(
                    f"Meta access token je neplatný alebo expiroval: {error.message}",
                    status_code=error.status_code,
                    code=error.code,
                    subcode=error.subcode,
                    fbtrace_id=error.fbtrace_id,
                )

            if response.status_code == 429 or error.code in RATE_LIMIT_ERROR_CODES:
                wait = self._rate_limit_wait(response, usage, attempt)
                if is_last_attempt or wait > self._backoff_max:
                    raise MetaRateLimitError(
                        f"Prekročený limit volaní Meta API: {error.message}",
                        retry_after_seconds=max(wait, self._backoff_max),
                        status_code=error.status_code,
                        code=error.code,
                        subcode=error.subcode,
                        fbtrace_id=error.fbtrace_id,
                    )
                logger.warning(
                    "Rate limit Meta API (%s) pri %s %s – čakám %.0f s (pokus %d/%d).",
                    error,
                    method,
                    path,
                    wait,
                    attempt + 1,
                    self._max_retries,
                )
                self._sleep(wait)
                continue

            transient = response.status_code >= 500 or error.is_transient or error.code in TRANSIENT_ERROR_CODES
            if transient and not is_last_attempt:
                delay = compute_backoff(attempt, self._backoff_base, self._backoff_max)
                logger.warning(
                    "Prechodná chyba Meta API (%s) pri %s %s – opakujem o %.1f s (pokus %d/%d).",
                    error,
                    method,
                    path,
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                self._sleep(delay)
                continue

            raise error

        # Sem sa kód nikdy nedostane – cyklus vždy skončí return/raise.
        raise MetaApiError(f"Vyčerpané pokusy pre {method} {path}.")

    # --------------------------------------------------------------- interné metódy
    def _url(self, path: str) -> str:
        if path.startswith("https://"):
            return path
        return f"{self._base_url}/{path.lstrip('/')}"

    def _retry_or_raise(
        self,
        exc: Exception,
        method: str,
        path: str,
        attempt: int,
        is_last_attempt: bool,
        *,
        safe: bool,
        ambiguous: bool,
    ) -> None:
        """Pri sieťovej chybe buď počká a dovolí ďalší pokus, alebo vyhodí výnimku."""
        if safe and not is_last_attempt:
            delay = compute_backoff(attempt, self._backoff_base, self._backoff_max)
            logger.warning(
                "Sieťová chyba (%s) pri %s %s – opakujem o %.1f s (pokus %d/%d).",
                type(exc).__name__,
                method,
                path,
                delay,
                attempt + 1,
                self._max_retries,
            )
            self._sleep(delay)
            return
        raise MetaNetworkError(
            f"Sieťová chyba pri {method} {path}: {type(exc).__name__}"
            + (" – výsledok požiadavky je neistý, neopakujem ju (ochrana proti duplicite)." if ambiguous else ""),
            ambiguous=ambiguous,
        ) from exc

    def _throttle(self, usage: UsageSnapshot) -> None:
        """Preventívne spomalenie: čím bližšie k 100 % limitu, tým dlhšia pauza."""
        if self._max_throttle_sleep <= 0 or usage.max_percent < self._throttle_threshold:
            return
        span = max(1.0, 100.0 - self._throttle_threshold)
        ratio = min(1.0, (usage.max_percent - self._throttle_threshold) / span)
        pause = max(1.0, ratio * self._max_throttle_sleep)
        logger.info("Využitie limitu Meta API je %.0f %% – spomaľujem o %.1f s.", usage.max_percent, pause)
        self._sleep(pause)

    def _rate_limit_wait(self, response: requests.Response, usage: UsageSnapshot, attempt: int) -> float:
        """Koľko čakať po rate-limit chybe: Retry-After → odhad z hlavičky → backoff."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                pass
        if usage.regain_access_seconds > 0:
            return usage.regain_access_seconds
        # Bez nápovedy čakáme dlhšie než pri bežnej chybe – limity Meta sa uvoľňujú pomaly.
        return compute_backoff(attempt, max(self._backoff_base, 15.0), self._backoff_max)

    @staticmethod
    def _parse_json(response: requests.Response, method: str, path: str) -> JsonDict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaApiError(
                f"Graph API vrátilo neplatný JSON pre {method} {path}.", status_code=response.status_code
            ) from exc
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    @staticmethod
    def _error_from_response(response: requests.Response) -> MetaApiError:
        """Vytvorí ``MetaApiError`` z objektu ``error`` v tele odpovede."""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return MetaApiError(
                f"HTTP {response.status_code} bez detailu chyby",
                status_code=response.status_code,
                is_transient=response.status_code >= 500,
            )
        message = str(error.get("error_user_msg") or error.get("message") or "Neznáma chyba Graph API")
        return MetaApiError(
            message[:500],
            status_code=response.status_code,
            code=_as_int(error.get("code")),
            subcode=_as_int(error.get("error_subcode")),
            fbtrace_id=str(error["fbtrace_id"]) if error.get("fbtrace_id") else None,
            is_transient=bool(error.get("is_transient")),
        )


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
