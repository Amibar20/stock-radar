import pandas as pd

from scanner.run import HISTORY_BARS, build_history


def _bars(n, start=100.0):
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"close": [start + i for i in range(n)]}, index=idx)


def test_history_uses_benchmark_axis_and_skips_stale_rows():
    bench = _bars(300)
    short = _bars(300).iloc[-50:]  # a stock listed recently: earlier days must be null, not shifted
    result = {
        "market": "il", "as_of": "2026-01-01", "generated_at": "x",
        "benchmarks": {"^TA125.TA": {}}, "indices": {"TA35.TA": {}},
        "stocks": [
            {"symbol": "NEW", "fetch": "NEW.TA", "indicators": {"close": 1.0}},
            {"symbol": "OLD", "fetch": "OLD.TA", "indicators": {"close": 1.0}, "stale_since": "2025-12-01"},
        ],
    }
    bars = {"^TA125.TA": bench, "NEW.TA": short, "OLD.TA": bench}
    h = build_history(result, bars)
    assert len(h["dates"]) == HISTORY_BARS
    assert h["dates"][-1] == bench.index[-1].date().isoformat()
    assert set(h["closes"]) == {"^TA125.TA", "NEW"}  # missing index skipped, stale row skipped
    new = h["closes"]["NEW"]
    assert new[-1] == short["close"].iloc[-1] and new[0] is None
    assert sum(v is not None for v in new) == 50
