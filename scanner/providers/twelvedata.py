"""Twelve Data (US). Free plan: 8 credits/minute, 800/day, 1 credit per symbol per time_series call.

The key is sent in the Authorization header, never in the URL, so it cannot leak through error messages.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable

import pandas as pd
import requests

from scanner.config import scrub
from scanner.providers import FetchResult, clean_bars

log = logging.getLogger(__name__)

BASE = "https://api.twelvedata.com"


class TwelveDataClient:
    def __init__(self, api_key: str, *, min_interval: float = 7.6, daily_budget: int = 780,
                 max_retries: int = 4, sleep: Callable[[float], None] = time.sleep) -> None:
        self._headers = {"Authorization": f"apikey {api_key}"}
        self.min_interval = min_interval
        self.daily_budget = daily_budget
        self.max_retries = max_retries
        self._sleep = sleep
        self._last_call = 0.0
        self.used_before_run = 0
        self.credits_used = 0

    def _wait_turn(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, path: str, params: dict) -> dict:
        delay = 15.0
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            try:
                r = requests.get(f"{BASE}/{path}", params=params, headers=self._headers, timeout=30)
                body = r.json()
            except (requests.RequestException, ValueError) as exc:
                body = {"status": "error", "code": 0, "message": scrub(exc)}
                r = None
            code = body.get("code") if isinstance(body, dict) else None
            rate_limited = (r is not None and r.status_code == 429) or code == 429
            transient = code == 0 or (r is not None and r.status_code >= 500)
            if (rate_limited or transient) and attempt < self.max_retries:
                log.warning("Twelve Data %s (attempt %d); backing off %.0fs", "429" if rate_limited else
                            "transient error", attempt + 1, delay)
                self._sleep(delay)
                delay *= 2
                continue
            return body
        return body

    def daily_usage(self) -> int:
        """Credits already used today (persisted by Twelve Data, so a second run on the same day is safe)."""
        body = self._get("api_usage", {})
        try:
            return int(body.get("daily_usage", 0))
        except (TypeError, ValueError):
            return 0

    def remaining_budget(self) -> int:
        return self.daily_budget - self.used_before_run - self.credits_used

    def time_series(self, symbol: str, outputsize: int = 260) -> pd.DataFrame:
        body = self._get("time_series", {"symbol": symbol, "interval": "1day", "outputsize": outputsize})
        self.credits_used += 1
        if body.get("status") != "ok":
            raise RuntimeError(scrub(body.get("message") or "unknown error"))
        values = body.get("values") or []
        if not values:
            raise RuntimeError("no values")
        df = pd.DataFrame(values).set_index("datetime")
        return clean_bars(df)

    def fetch_many(self, symbols: Iterable[str], outputsize: int = 260) -> FetchResult:
        res = FetchResult()
        self.used_before_run = self.daily_usage()
        log.info("Twelve Data: %d credits already used today; budget %d", self.used_before_run,
                 self.daily_budget)
        for i, sym in enumerate(symbols, 1):
            if self.remaining_budget() <= 0:
                res.stopped_by_budget = True
                res.failed[sym] = "daily credit budget reached"
                continue
            try:
                res.bars[sym] = self.time_series(sym, outputsize)
                res.currency[sym] = "USD"
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
                res.failed[sym] = scrub(exc)
                log.warning("Twelve Data %s failed: %s", sym, scrub(exc))
            if i % 50 == 0:
                log.info("Twelve Data progress: %d symbols, %d credits", i, self.credits_used)
        res.credits_used = self.credits_used
        return res
