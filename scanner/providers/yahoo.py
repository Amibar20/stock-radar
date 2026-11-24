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


QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"


def _quotes(symbols: list[str], batch: int = 100) -> dict[str, dict]:
    """Yahoo's batch quote endpoint (one request per 100 symbols). Uses yfinance's session/crumb handling."""
    from yfinance.data import YfData

    data = YfData(session=yf_session())
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        for attempt in range(3):
            try:
                raw = data.get_raw_json(QUOTE_URL, params={"symbols": ",".join(chunk)})
                for q in raw.get("quoteResponse", {}).get("result", []):
                    out[q["symbol"]] = q
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("Yahoo quote batch failed (%s), attempt %d", scrub(exc), attempt + 1)
                time.sleep(3 * (attempt + 1))
    return out


def _ratio(price: float | None, eps: float | None) -> float | None:
    """price / EPS. None for missing data or losses (P/E is not meaningful when earnings are negative)."""
    if not price or eps is None or eps <= 0:
        return None
    return round(price / eps, 2)


def fundamentals(symbols: dict[str, float], main_currency: str) -> dict[str, dict]:
    """Trailing P/E (and forward P/E for US stocks) plus market cap, for {yahoo_symbol: last close}.

    P/E is computed from our own close so it matches the price shown in the app. Verified 2026-11-24 against the
    US listings of dual-listed companies (TEVA, ESLT, NICE, ICL): Yahoo's trailing EPS for .TA symbols is already
    in shekels even when financialCurrency says USD, so no conversion is applied. Yahoo's *forward* EPS for .TA
    symbols is inconsistent (sometimes USD, sometimes neither), so forward P/E is published for US stocks only.
    """
    quotes = _quotes(list(symbols))
    out: dict[str, dict] = {}
    for sym, close in symbols.items():
        q = quotes.get(sym)
        if not q:
            continue
        us_ok = main_currency != "USD" or (q.get("financialCurrency") or "USD") == "USD"
        eps = q.get("epsTrailingTwelveMonths")
        rec = {
            "pe": _ratio(close, eps) if us_ok else None,
            "fpe": _ratio(close, q.get("epsForward")) if main_currency == "USD" and us_ok else None,
            "eps_negative": isinstance(eps, (int, float)) and eps < 0,
            "mcap": q.get("marketCap"),
        }
        if any(v for v in rec.values()):
            out[sym] = rec
    log.info("Yahoo fundamentals: %d of %d symbols", len(out), len(symbols))
    return out


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
