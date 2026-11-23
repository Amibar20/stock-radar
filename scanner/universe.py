"""Build the US universe (S&P 500 + Nasdaq-100) from Wikipedia, with the committed file as fallback.

Run:  python -m scanner.universe --refresh-us
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import logging

import pandas as pd
import requests

from scanner.config import DATA_DIR, read_json, setup_logging, write_json

log = logging.getLogger(__name__)

US_FILE = DATA_DIR / "universe_us.json"
IL_FILE = DATA_DIR / "universe_il.json"

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
# Generic client name only; no personal details in requests to outside services.
HEADERS = {"User-Agent": "stock-radar-universe/1.0 (personal research script)"}


def normalize_us_symbol(sym: str) -> str:
    """Wikipedia uses BRK.B / BF.B; Twelve Data and Yahoo-style feeds expect a dash-free dot or a dash.

    We store the canonical dotted form (BRK.B) as used by Twelve Data; providers convert as needed.
    """
    return sym.strip().upper().replace("-", ".")


def _tables(url: str) -> list[pd.DataFrame]:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))


def _find_table(tables: list[pd.DataFrame], symbol_cols: tuple[str, ...]) -> tuple[pd.DataFrame, str]:
    for t in tables:
        for col in symbol_cols:
            if col in t.columns and len(t) >= 90:
                return t, col
    raise ValueError("constituents table not found")


def fetch_us_universe() -> list[dict]:
    sp_tables = _tables(SP500_URL)
    sp, sp_col = _find_table(sp_tables, ("Symbol",))
    ndx_tables = _tables(NDX_URL)
    ndx, ndx_col = _find_table(ndx_tables, ("Ticker", "Symbol"))

    by_symbol: dict[str, dict] = {}
    for _, row in sp.iterrows():
        sym = normalize_us_symbol(str(row[sp_col]))
        by_symbol[sym] = {
            "symbol": sym,
            "name": str(row.get("Security", "")),
            "sector": str(row.get("GICS Sector", "")),
            "indices": ["SP500"],
        }
    name_col = "Company" if "Company" in ndx.columns else None
    sector_col = next((c for c in ndx.columns if "Industry" in str(c) or "Sector" in str(c)), None)
    for _, row in ndx.iterrows():
        sym = normalize_us_symbol(str(row[ndx_col]))
        if sym in by_symbol:
            by_symbol[sym]["indices"].append("NDX")
        else:
            by_symbol[sym] = {
                "symbol": sym,
                "name": str(row[name_col]) if name_col else "",
                "sector": str(row[sector_col]) if sector_col else "",
                "indices": ["NDX"],
            }
    stocks = sorted(by_symbol.values(), key=lambda s: s["symbol"])
    if len(stocks) < 480:
        raise ValueError(f"suspiciously small universe: {len(stocks)}")
    return stocks


def refresh_us_universe() -> dict:
    """Fetch and write the US universe; on any failure keep the committed file."""
    previous = read_json(US_FILE)
    try:
        stocks = fetch_us_universe()
    except Exception as exc:  # noqa: BLE001 - any failure falls back to the committed file
        log.warning("US universe refresh failed (%s); keeping committed file", exc)
        if previous is None:
            raise
        return previous
    data = {
        "updated": dt.date.today().isoformat(),
        "source": "Wikipedia: S&P 500 + Nasdaq-100 constituents",
        "benchmarks": ["SPY", "QQQ"],
        "count": len(stocks),
        "stocks": stocks,
    }
    write_json(US_FILE, data)
    log.info("US universe: %d symbols", len(stocks))
    return data


def load_us_universe() -> dict:
    return read_json(US_FILE)


def load_il_universe() -> dict:
    return read_json(IL_FILE)


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--refresh-us", action="store_true")
    args = p.parse_args()
    if args.refresh_us:
        refresh_us_universe()


if __name__ == "__main__":
    main()
