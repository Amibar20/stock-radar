"""yfinance (Yahoo, unofficial) for TASE .TA symbols. Prices for TASE stocks arrive in ILA (agorot)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from scanner.config import scrub, yf_session
from scanner.providers import FetchResult, clean_bars

log = logging.getLogger(__name__)

PRICE_COLUMNS = ["open", "high", "low", "close"]


def to_main_currency(df: pd.DataFrame, currency: str | None) -> tuple[pd.DataFrame, str]:
    """Convert agorot (ILA, 1/100 shekel) to shekels (ILS). Other currencies are returned unchanged.

    Yahoo reports TASE stocks as 'ILA'; some feeds use 'ILa' or 'GBX'-style minor units, so compare
    case-sensitively only for the known minor-unit code.
    """
    if not currency:
        # Never guess: a wrong guess would show agorot as shekels (100x error). Fail the symbol instead.
        raise ValueError("currency missing in Yahoo metadata")
    if currency in ("ILA", "ILa"):
        out = df.copy()
        out[PRICE_COLUMNS] = out[PRICE_COLUMNS] / 100.0
        return out, "ILS"
    return df, currency


def _fetch_one(sym: str, period: str, retries: int = 2) -> tuple[str, pd.DataFrame | None, str, str | None]:
    import yfinance as yf

    last_err = "no data"
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(sym, session=yf_session())
            hist = t.history(period=period, interval="1d", auto_adjust=False, actions=False)
            if hist is None or hist.empty:
                last_err = "no data"
            else:
                currency = (t.history_metadata or {}).get("currency")
                df, cur = to_main_currency(clean_bars(hist), currency)
                return sym, df, cur, None
        except Exception as exc:  # noqa: BLE001
            last_err = scrub(exc)
        time.sleep(2 * (attempt + 1))
    return sym, None, "", last_err


def fetch_many(symbols: Iterable[str], period: str = "14mo", workers: int = 4) -> FetchResult:
    res = FetchResult()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for sym, df, cur, err in pool.map(lambda s: _fetch_one(s, period), list(symbols)):
            if df is None:
                res.failed[sym] = err or "no data"
            else:
                res.bars[sym] = df
                res.currency[sym] = cur
    if res.failed:
        log.warning("Yahoo failed for %d symbols: %s", len(res.failed), ", ".join(sorted(res.failed)))
    return res
