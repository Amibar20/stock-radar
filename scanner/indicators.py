"""Technical indicators implemented with pandas/numpy (no TA-Lib).

Conventions: input DataFrame indexed by date ascending with open/high/low/close/volume.
RSI and ATR use Wilder's smoothing (alpha = 1/period), as in most charting platforms.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    # No losses at all -> RSI 100; no gains and no losses -> 50.
    out = out.where(avg_loss != 0, np.where(avg_gain > 0, 100.0, 50.0))
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def pct_return(close: pd.Series, n: int) -> float | None:
    if len(close) <= n:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1)


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def compute(df: pd.DataFrame, benchmark_close: pd.Series | None = None) -> dict:
    """Return the latest indicator snapshot for one symbol (plain floats, JSON-friendly)."""
    close, vol = df["close"], df["volume"]
    s20, s50, s200 = sma(close, 20), sma(close, 50), sma(close, 200)
    m = macd(close)
    a = atr(df)
    avg_vol20 = sma(vol, 20)
    last = close.iloc[-1]
    prev = close.iloc[-2] if len(close) > 1 else np.nan
    window = close.iloc[-252:]
    high_52w = df["high"].iloc[-252:].max()

    rs_63 = None
    ret_63 = pct_return(close, 63)
    if benchmark_close is not None and ret_63 is not None:
        bench = benchmark_close.reindex(close.index).ffill().dropna()
        bench_ret = pct_return(bench, 63)
        if bench_ret is not None:
            rs_63 = ret_63 - bench_ret

    # Volume ratio compares today's volume with the 20-day average *before* today.
    prior_avg_vol = avg_vol20.shift(1).iloc[-1]
    return {
        "bars": int(len(df)),
        "date": df.index[-1].date().isoformat(),
        "close": _f(last),
        "change_pct": _f(last / prev - 1) if prev else None,
        "sma20": _f(s20.iloc[-1]),
        "sma50": _f(s50.iloc[-1]),
        "sma200": _f(s200.iloc[-1]),
        "sma50_10d_ago": _f(s50.iloc[-11]) if len(s50) > 11 else None,
        "ema20": _f(ema(close, 20).iloc[-1]),
        "rsi14": _f(rsi(close).iloc[-1]),
        "macd": _f(m["macd"].iloc[-1]),
        "macd_signal": _f(m["signal"].iloc[-1]),
        "macd_hist": _f(m["hist"].iloc[-1]),
        "macd_hist_prev": _f(m["hist"].iloc[-2]) if len(m) > 1 else None,
        "atr14": _f(a.iloc[-1]),
        "avg_volume20": _f(prior_avg_vol),
        "volume": _f(vol.iloc[-1]),
        "volume_ratio": _f(vol.iloc[-1] / prior_avg_vol) if prior_avg_vol else None,
        "avg_dollar_volume20": _f((close * vol).rolling(20).mean().iloc[-1]),
        "ret_63d": _f(ret_63),
        "rs_63d": _f(rs_63),
        "high_52w": _f(high_52w),
        "dist_52w_high": _f(last / high_52w - 1) if high_52w else None,
        # Resistance = 52-week high *before* the last 10 bars, so a fresh breakout is not its own ceiling.
        "prior_high_52w": _f(df["high"].iloc[-252:-10].max()) if len(df) > 20 else None,
        "low_52w": _f(window.min()),
        "swing_low_10d": _f(df["low"].iloc[-10:].min()),
    }
