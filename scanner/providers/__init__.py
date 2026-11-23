"""Market data providers. Each returns daily bars as a DataFrame indexed by date (ascending) with
columns open, high, low, close, volume. Prices are always in the trading currency's main unit
(USD, or ILS after agorot conversion)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class FetchResult:
    bars: dict[str, pd.DataFrame] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)  # symbol -> reason
    currency: dict[str, str] = field(default_factory=dict)
    credits_used: int = 0
    stopped_by_budget: bool = False


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names, sort ascending, drop empty rows and duplicate dates."""
    out = df.rename(columns=str.lower)[BAR_COLUMNS].astype(float)
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=["close"])
