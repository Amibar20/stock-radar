"""Rule-based score (0-100), price levels and labels. All weights come from config/scoring.json."""

from __future__ import annotations

from typing import Any

from scanner.config import CONFIG_DIR, read_json

Indicators = dict[str, Any]


def load_config() -> dict:
    return read_json(CONFIG_DIR / "scoring.json")


def gate(ind: Indicators, currency: str, cfg: dict) -> str | None:
    """Return a reason string if the stock fails a data-quality gate, else None."""
    g = cfg["gates"]
    if ind.get("bars", 0) < g["min_bars"]:
        return f"only {ind.get('bars', 0)} bars (< {g['min_bars']})"
    needed = ("close", "sma20", "sma50", "sma200", "rsi14", "atr14", "macd", "macd_signal")
    missing = [k for k in needed if ind.get(k) is None]
    if missing:
        return "missing " + ",".join(missing)
    min_dv = g["min_avg_dollar_volume"].get(currency)
    dv = ind.get("avg_dollar_volume20")
    if min_dv and (dv is None or dv < min_dv):
        return f"low liquidity ({(dv or 0) / 1e6:.1f}M {currency}/day)"
    return None


def score(ind: Indicators, cfg: dict) -> tuple[float, dict[str, float]]:
    """Return (score 0-100, points per rule) so every score is explainable."""
    pts: dict[str, float] = {}
    c, s50, s200 = ind["close"], ind["sma50"], ind["sma200"]

    t = cfg["trend"]
    if c > s50:
        pts["close_above_sma50"] = t["close_above_sma50"]
    if s50 > s200:
        pts["sma50_above_sma200"] = t["sma50_above_sma200"]
    if c > s200:
        pts["close_above_sma200"] = t["close_above_sma200"]
    if ind.get("sma50_10d_ago") is not None and s50 > ind["sma50_10d_ago"]:
        pts["sma50_rising_10d"] = t["sma50_rising_10d"]

    m = cfg["momentum"]
    if m["rsi_low"] <= ind["rsi14"] <= m["rsi_high"]:
        pts["rsi_in_range"] = m["rsi_in_range"]
    if ind["macd"] > ind["macd_signal"]:
        pts["macd_above_signal"] = m["macd_above_signal"]
    if ind.get("macd_hist_prev") is not None and ind["macd_hist"] > ind["macd_hist_prev"]:
        pts["macd_hist_rising"] = m["macd_hist_rising"]

    v = cfg["volume"]
    up_day = (ind.get("change_pct") or 0) > 0
    vr = ind.get("volume_ratio") or 0
    if up_day and vr >= v["strong_ratio"]:
        pts["volume_strong_up_day"] = v["strong_up_day"]
    elif up_day and vr >= v["mild_ratio"]:
        pts["volume_mild_up_day"] = v["mild_up_day"]

    r = cfg["relative_strength"]
    rs = ind.get("rs_63d")
    if rs is not None:
        frac = (rs - r["rs_zero_points_at"]) / (r["rs_full_points_at"] - r["rs_zero_points_at"])
        frac = min(max(frac, 0.0), 1.0)
        if frac > 0:
            pts["relative_strength"] = round(r["max_points"] * frac, 1)

    h = cfg["near_52w_high"]
    d = ind.get("dist_52w_high")
    if d is not None:
        if d >= -0.05:
            pts["near_52w_high"] = h["within_5pct"]
        elif d >= -0.10:
            pts["near_52w_high"] = h["within_10pct"]
        elif d >= -0.20:
            pts["near_52w_high"] = h["within_20pct"]

    p = cfg["penalties"]
    if ind["rsi14"] > p["rsi_overbought_level"]:
        pts["penalty_rsi_overbought"] = -p["rsi_overbought"]
    if c > s50 * (1 + p["extended_pct"]):
        pts["penalty_extended_above_sma50"] = -p["extended_above_sma50"]

    total = min(max(sum(pts.values()), 0.0), 100.0)
    return round(total, 1), pts


def levels(ind: Indicators, cfg: dict) -> tuple[dict | None, str | None]:
    """Entry zone / stop / target. Returns (levels, None) or (None, reason the idea is dropped).

    entry zone: upper = close; lower = max(SMA20, close - 1.0*ATR) when SMA20 is below the close,
                otherwise close - 0.5*ATR. Entry reference = middle of the zone.
    stop:       entry - 1.5*ATR, but never more than 1*ATR below the 10-day swing low.
    target:     entry + 2 * (entry - stop)  -> reward:risk = 2 by construction.
    dropped if: stop is more than 10% below entry, or the prior 52-week high (excluding the last 10 bars)
                sits between entry and entry + 1R while the close is still below it (overhead resistance
                before the first R is earned). A close at/above that prior high is a breakout and is kept.
    """
    lv = cfg["levels"]
    c, s20, a = ind["close"], ind["sma20"], ind["atr14"]
    if not a or a <= 0:
        return None, "ATR unavailable"
    lower = max(s20, c - lv["entry_pullback_atr"] * a) if s20 < c else c - lv["entry_below_sma20_atr"] * a
    upper = c
    entry = (lower + upper) / 2
    stop = entry - lv["stop_atr"] * a
    swing = ind.get("swing_low_10d")
    if swing is not None:
        stop = max(stop, swing - lv["max_stop_below_swing_low_atr"] * a)
    risk = entry - stop
    if risk <= 0:
        return None, "invalid stop"
    if risk / entry > lv["max_stop_pct"]:
        return None, f"stop too wide ({risk / entry:.0%})"
    target = entry + lv["reward_risk"] * risk
    resistance = ind.get("prior_high_52w")
    breakout = resistance is not None and c >= resistance
    if (resistance is not None and not breakout
            and entry < resistance < entry + lv["min_room_to_52w_high_r"] * risk):
        return None, "52-week high is less than 1R above entry"
    return {
        "entry_low": round(lower, 4),
        "entry_high": round(upper, 4),
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "risk_pct": round(risk / entry, 4),
        "reward_risk": round((target - entry) / risk, 2),
    }, None


def label(score_value: float, cfg: dict) -> dict | None:
    lab = cfg["labels"]
    if score_value >= lab["research_buy"]["min_score"]:
        return {"key": "research_buy", "he": lab["research_buy"]["he"]}
    if score_value >= lab["watch"]["min_score"]:
        return {"key": "watch", "he": lab["watch"]["he"]}
    return None
