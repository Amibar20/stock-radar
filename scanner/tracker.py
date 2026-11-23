"""Track record: did past ideas reach their target or stop?

Rules (documented in the README):
- An idea is recorded on its data date (the scan's as_of) with entry (middle of the zone), stop and target.
- It is "entered" on the first bar within 5 trading days whose low touches the entry price (limit order,
  filled at the entry price, or at the open if the bar opens below entry). Otherwise it is "not_triggered"
  and left out of the statistics.
- After the fill, each bar is checked: low <= stop -> "stopped" (filled at the stop, or at the open if it gaps
  below); high >= target -> "target" (filled at the target). If one bar touches both, it counts as stopped
  (conservative). On the fill bar only the stop is checked.
- After 20 trading days in the trade it "expired" at that day's close.
- R multiple = (exit - entry) / (entry - stop). The benchmark (SPY / TA-125) return is measured over the same
  dates (fill to exit) for comparison.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import pandas as pd

from scanner.config import read_json, write_json

log = logging.getLogger(__name__)

MAX_WAIT_BARS = 5
MAX_HOLD_BARS = 20
MIN_COMPLETED_FOR_CONCLUSION = 30
FINAL = {"target", "stopped", "expired", "not_triggered"}


def idea_id(market: str, symbol: str, date: str) -> str:
    return f"{market}:{symbol}:{date}"


# ------------------------------------------------------------------ recording
def picks_from_result(result: dict) -> list[dict]:
    """Ideas worth tracking: labelled picks with levels (watchlist-only rows without a label are skipped)."""
    out = []
    for r in result["stocks"]:
        lv = r.get("levels")
        if not (r.get("selected") and r.get("label") and lv) or r.get("stale_since"):
            continue
        out.append({
            "id": idea_id(result["market"], r["symbol"], r["date"]),
            "market": result["market"],
            "symbol": r["symbol"],
            "fetch": r.get("fetch", r["symbol"]),
            "name": r.get("name_he") or r.get("name"),
            "date": r["date"],
            "currency": r.get("currency"),
            "score": r.get("score"),
            "label": r["label"]["key"],
            "entry_low": lv["entry_low"], "entry_high": lv["entry_high"],
            "entry": lv["entry"], "stop": lv["stop"], "target": lv["target"],
            "confidence": (r.get("ai") or {}).get("confidence"),
        })
    return out


def record_picks(result: dict, history_dir: Path) -> Path | None:
    """Write/merge today's picks into history/<as_of>.json (one file per date, both markets)."""
    picks = picks_from_result(result)
    if not result.get("as_of"):
        return None
    path = history_dir / f"{result['as_of']}.json"
    data = read_json(path, {"date": result["as_of"], "markets": {}})
    data["markets"][result["market"]] = picks
    write_json(path, data)
    return path


def load_history(history_dir: Path) -> list[dict]:
    ideas = []
    for f in sorted(history_dir.glob("*.json")):
        data = read_json(f, {})
        for picks in (data.get("markets") or {}).values():
            ideas.extend(picks)
    return ideas


# ------------------------------------------------------------------ evaluation
def _bench_return(bench: pd.Series | None, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    if bench is None or bench.empty:
        return None
    b = bench.sort_index()
    s, e = b[b.index <= start], b[b.index <= end]
    if s.empty or e.empty:
        return None
    return float(e.iloc[-1] / s.iloc[-1] - 1)


def evaluate_idea(idea: dict, bars: pd.DataFrame, bench: pd.Series | None = None) -> dict:
    """Pure function: status and result of one idea given daily bars (ascending, any length)."""
    entry, stop, target = idea["entry"], idea["stop"], idea["target"]
    risk = entry - stop
    after = bars[bars.index > pd.Timestamp(idea["date"])]
    res: dict = {"id": idea["id"], "status": "pending", "fill_date": None, "exit_date": None,
                 "exit_price": None, "r": None, "pct": None, "bench_pct": None, "bars_held": 0}

    fill_pos = None
    for pos in range(min(len(after), MAX_WAIT_BARS)):
        if after["low"].iloc[pos] <= entry:
            fill_pos = pos
            break
    if fill_pos is None:
        if len(after) >= MAX_WAIT_BARS:
            res["status"] = "not_triggered"
        return res

    fill_date = after.index[fill_pos]
    fill_price = min(float(after["open"].iloc[fill_pos]), entry)
    res["fill_date"] = fill_date.date().isoformat()
    res["fill_price"] = round(fill_price, 4)

    def close_out(status: str, pos: int, price: float) -> dict:
        d = after.index[pos]
        res.update(status=status, exit_date=d.date().isoformat(), exit_price=round(price, 4),
                   r=round((price - entry) / risk, 3), pct=round(price / entry - 1, 4),
                   bars_held=pos - fill_pos)
        bp = _bench_return(bench, fill_date, d)
        res["bench_pct"] = round(bp, 4) if bp is not None else None
        return res

    # Fill bar: only the stop can be judged (we don't know the intraday order).
    if after["low"].iloc[fill_pos] <= stop:
        return close_out("stopped", fill_pos, min(fill_price, stop))

    for pos in range(fill_pos + 1, len(after)):
        o, lo, hi = (float(after[c].iloc[pos]) for c in ("open", "low", "high"))
        if lo <= stop:  # also wins ties with the target on the same bar (conservative)
            return close_out("stopped", pos, min(o, stop))
        if hi >= target:
            return close_out("target", pos, target)
        if pos - fill_pos >= MAX_HOLD_BARS:
            return close_out("expired", pos, float(after["close"].iloc[pos]))

    # Still open: mark to market at the last close.
    last = len(after) - 1
    price = float(after["close"].iloc[last])
    res.update(status="open", r=round((price - entry) / risk, 3), pct=round(price / entry - 1, 4),
               bars_held=last - fill_pos, last_close=round(price, 4))
    bp = _bench_return(bench, fill_date, after.index[last])
    res["bench_pct"] = round(bp, 4) if bp is not None else None
    return res


# ------------------------------------------------------------------ summary
def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def summarize(evals: list[dict]) -> dict:
    done = [e for e in evals if e["status"] in ("target", "stopped", "expired")]
    n = len(done)
    with_bench = [e for e in done if e.get("bench_pct") is not None]
    avg_pct, avg_bench = _avg([e["pct"] for e in with_bench]), _avg([e["bench_pct"] for e in with_bench])
    return {
        "ideas": len(evals),
        "completed": n,
        "open": sum(e["status"] == "open" for e in evals),
        "pending": sum(e["status"] == "pending" for e in evals),
        "not_triggered": sum(e["status"] == "not_triggered" for e in evals),
        "targets": sum(e["status"] == "target" for e in done),
        "stops": sum(e["status"] == "stopped" for e in done),
        "expired": sum(e["status"] == "expired" for e in done),
        "hit_rate": round(sum(e["status"] == "target" for e in done) / n, 3) if n else None,
        "win_rate": round(sum((e["r"] or 0) > 0 for e in done) / n, 3) if n else None,
        "avg_r": _avg([e["r"] for e in done]),
        "total_r": round(sum(e["r"] for e in done), 3) if n else None,
        "avg_pct": _avg([e["pct"] for e in done]),
        "avg_bench_pct_same_period": avg_bench,
        "avg_excess_vs_bench_pct": round(avg_pct - avg_bench, 4) if with_bench else None,
        "too_few_to_conclude": n < MIN_COMPLETED_FOR_CONCLUSION,
        "min_completed_for_conclusion": MIN_COMPLETED_FOR_CONCLUSION,
    }


def update_track_record(market: str, bars: dict[str, pd.DataFrame], bench: pd.Series | None,
                        history_dir: Path, track_file: Path, now_iso: str) -> dict:
    """Re-evaluate every non-final idea of `market` with today's bars; keep final ones as they are."""
    ideas = load_history(history_dir)
    old = read_json(track_file, {}) or {}
    prev_evals = {e["id"]: e for e in old.get("evaluations", [])}
    evals: dict[str, dict] = {}
    for idea in ideas:
        prev = prev_evals.get(idea["id"])
        if idea["market"] != market or (prev and prev["status"] in FINAL):
            if prev:
                evals[idea["id"]] = prev
            continue
        df = bars.get(idea["fetch"])
        if df is None or df.empty:
            if prev:
                evals[idea["id"]] = prev  # no data today: keep yesterday's evaluation
            else:
                evals[idea["id"]] = {"id": idea["id"], "status": "pending"}
            continue
        e = evaluate_idea(idea, df, bench)
        evals[idea["id"]] = e

    by_id = {i["id"]: i for i in ideas}
    rows = []
    for iid, e in evals.items():
        idea = by_id.get(iid, {})
        rows.append({**{k: idea.get(k) for k in ("market", "symbol", "name", "date", "label", "score",
                                                   "entry", "stop", "target", "currency", "confidence")}, **e})
    rows.sort(key=lambda r: (r.get("date") or "", r.get("market") or "", r.get("symbol") or ""), reverse=True)
    data = {
        "updated": now_iso,
        "rules": {"max_wait_bars": MAX_WAIT_BARS, "max_hold_bars": MAX_HOLD_BARS,
                  "same_bar_stop_and_target": "stopped", "benchmark": {"us": "SPY", "il": "TA-125"}},
        "summary": {"all": summarize(rows), "us": summarize([r for r in rows if r["market"] == "us"]),
                    "il": summarize([r for r in rows if r["market"] == "il"])},
        "evaluations": rows,
    }
    write_json(track_file, data)
    return data


def today_iso() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
