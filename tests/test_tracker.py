import pandas as pd
import pytest

from scanner import tracker

IDEA = {"id": "us:AAA:2025-01-01", "market": "us", "symbol": "AAA", "fetch": "AAA", "date": "2025-01-01",
        "entry": 100.0, "stop": 95.0, "target": 110.0}


def bars(rows, start="2025-01-02"):
    """rows: list of (open, high, low, close)."""
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=1.0)


def test_target_hit_is_plus_2r():
    b = bars([(101, 102, 99.5, 101), (101, 104, 100, 103), (103, 111, 102, 109)])
    e = tracker.evaluate_idea(IDEA, b)
    assert e["status"] == "target" and e["r"] == pytest.approx(2.0) and e["pct"] == pytest.approx(0.10)
    assert e["fill_date"] == "2025-01-02" and e["exit_date"] == "2025-01-06" and e["bars_held"] == 2


def test_stop_hit_is_minus_1r():
    b = bars([(101, 102, 99.5, 101), (100, 100.5, 94.0, 95)])
    e = tracker.evaluate_idea(IDEA, b)
    assert e["status"] == "stopped" and e["r"] == pytest.approx(-1.0)


def test_gap_below_stop_fills_at_open():
    b = bars([(101, 102, 99.5, 101), (93, 94, 92, 93)])
    e = tracker.evaluate_idea(IDEA, b)
    assert e["exit_price"] == 93 and e["r"] == pytest.approx(-1.4)


def test_same_bar_stop_and_target_counts_as_stopped():
    b = bars([(101, 102, 99.5, 101), (100, 112, 94, 105)])
    assert tracker.evaluate_idea(IDEA, b)["status"] == "stopped"


def test_fill_bar_only_checks_stop():
    # Fill and spike to target on the same bar: not counted as target (order unknown); later bars decide.
    b = bars([(101, 111, 99.0, 104)])
    e = tracker.evaluate_idea(IDEA, b)
    assert e["status"] == "open"


def test_open_below_entry_fills_at_open_but_r_uses_plan():
    b = bars([(98, 99, 97, 98.5)])
    e = tracker.evaluate_idea(IDEA, b)
    assert e["fill_price"] == 98 and e["status"] == "open"
    assert e["r"] == pytest.approx((98.5 - 100) / 5)


def test_not_triggered_after_5_bars_and_pending_before():
    high = [(105, 106, 104, 105)] * 5
    assert tracker.evaluate_idea(IDEA, bars(high[:3]))["status"] == "pending"
    assert tracker.evaluate_idea(IDEA, bars(high))["status"] == "not_triggered"


def test_expired_after_20_bars_at_close():
    rows = [(101, 102, 99.5, 101)] + [(101, 102, 99, 101.5)] * 20
    e = tracker.evaluate_idea(IDEA, bars(rows))
    assert e["status"] == "expired" and e["bars_held"] == 20 and e["r"] == pytest.approx(0.3)


def test_bars_on_idea_date_are_ignored():
    b = bars([(90, 91, 80, 85), (101, 102, 99.5, 101)], start="2025-01-01")  # first bar = idea date
    e = tracker.evaluate_idea(IDEA, b)
    assert e["status"] == "open" and e["fill_date"] == "2025-01-02"


def test_benchmark_return_same_period():
    b = bars([(101, 102, 99.5, 101), (103, 111, 102, 109)])
    bench = pd.Series([400.0, 404.0, 410.0], index=pd.bdate_range("2025-01-01", periods=3))
    e = tracker.evaluate_idea(IDEA, b, bench)
    # fill 2025-01-02 (404) -> exit 2025-01-03 (410)
    assert e["bench_pct"] == pytest.approx(410 / 404 - 1, abs=1e-4)


def test_summary_and_too_few_notice():
    evals = [{"status": "target", "r": 2.0, "pct": 0.1, "bench_pct": 0.01},
             {"status": "stopped", "r": -1.0, "pct": -0.05, "bench_pct": 0.0},
             {"status": "expired", "r": 0.5, "pct": 0.02, "bench_pct": -0.01},
             {"status": "open", "r": 0.2, "pct": 0.01, "bench_pct": 0.0},
             {"status": "not_triggered", "r": None, "pct": None}]
    s = tracker.summarize(evals)
    assert s["completed"] == 3 and s["open"] == 1 and s["not_triggered"] == 1
    assert s["hit_rate"] == pytest.approx(1 / 3, abs=1e-3) and s["win_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["avg_r"] == pytest.approx(0.5) and s["total_r"] == pytest.approx(1.5)
    assert s["avg_excess_vs_bench_pct"] == pytest.approx(0.0233 - 0.0, abs=1e-3)
    assert s["too_few_to_conclude"] is True


def test_record_and_update_roundtrip(tmp_path):
    result = {"market": "us", "as_of": "2025-01-01", "stocks": [
        {"symbol": "AAA", "fetch": "AAA", "name": "Aaa", "date": "2025-01-01", "selected": True,
         "label": {"key": "research_buy", "he": "x"}, "score": 80, "currency": "USD",
         "levels": {"entry_low": 99, "entry_high": 101, "entry": 100.0, "stop": 95.0, "target": 110.0}},
        {"symbol": "BBB", "date": "2025-01-01", "selected": True, "label": None, "levels": None}]}
    hist = tmp_path / "history"
    tracker.record_picks(result, hist)
    track = tmp_path / "track_record.json"
    b = {"AAA": bars([(101, 102, 99.5, 101), (103, 111, 102, 109)])}
    data = tracker.update_track_record("us", b, None, hist, track, "now")
    assert data["summary"]["us"]["completed"] == 1 and data["evaluations"][0]["status"] == "target"
    # Final results are kept even if the symbol has no data on a later day
    data = tracker.update_track_record("us", {}, None, hist, track, "later")
    assert data["evaluations"][0]["status"] == "target"
