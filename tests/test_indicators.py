import numpy as np
import pandas as pd
import pytest
from conftest import make_bars

from scanner import indicators as ind


def test_sma_simple():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert ind.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert np.isnan(ind.sma(s, 3).iloc[1])


def test_ema_matches_recursive_formula():
    s = pd.Series([10, 11, 12, 13, 14, 15], dtype=float)
    e = ind.ema(s, 3)
    alpha = 2 / (3 + 1)
    expected = s.iloc[0]
    for x in s.iloc[1:]:
        expected = alpha * x + (1 - alpha) * expected
    assert e.iloc[-1] == pytest.approx(expected)


def test_rsi_extremes_and_known_value():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert ind.rsi(up).iloc[-1] == pytest.approx(100.0)
    down = pd.Series(np.arange(40, 1, -1, dtype=float))
    assert ind.rsi(down).iloc[-1] == pytest.approx(0.0)
    # Alternating +1/-1 -> equal average gain/loss -> RSI near 50
    alt = pd.Series(100 + np.tile([1.0, -1.0], 50).cumsum())
    assert ind.rsi(alt).iloc[-1] == pytest.approx(50.0, abs=5)


def test_macd_positive_in_uptrend(uptrend):
    m = ind.macd(uptrend["close"])
    assert m["macd"].iloc[-1] > 0
    assert m["hist"].iloc[-1] == pytest.approx(m["macd"].iloc[-1] - m["signal"].iloc[-1])


def test_atr_constant_range():
    df = make_bars([100.0] * 40, spread=0.01)  # high-low = 2, no gaps
    assert ind.atr(df).iloc[-1] == pytest.approx(2.0)


def test_compute_snapshot(uptrend):
    bench = uptrend["close"] * 0 + 100  # flat benchmark
    snap = ind.compute(uptrend, bench)
    assert snap["bars"] == 260
    assert snap["close"] > snap["sma50"] > snap["sma200"]
    assert snap["volume_ratio"] == pytest.approx(1.0)
    assert snap["ret_63d"] == pytest.approx(1.003 ** 63 - 1, rel=1e-6)
    assert snap["rs_63d"] == pytest.approx(snap["ret_63d"])  # benchmark flat
    assert snap["dist_52w_high"] < 0  # high includes the 1% intraday spread
    # Prior high excludes the last 10 bars, so in a steady uptrend it is below today's close
    assert snap["prior_high_52w"] < snap["close"] <= snap["high_52w"]
    assert snap["swing_low_10d"] == pytest.approx(uptrend["low"].iloc[-10:].min())
