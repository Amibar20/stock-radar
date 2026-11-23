"""Stage 2 'agents': small, separate prompts that only interpret numbers we computed.

The models never receive or return prices we publish: entry/stop/target always come from scoring.levels().
"""

from __future__ import annotations

import json
import logging

import jsonschema

from scanner.llm import BaseClient, LLMError

log = logging.getLogger(__name__)

NO_AI_NOTE = "ללא ניתוח AI"
RISK_MODE_HE = {"positive": "שוק חיובי", "cautious": "שוק זהיר", "negative": "שוק שלילי"}

GROUND_RULES = (
    "You are part of a personal stock-research tool. Write in Hebrew only (tickers and numbers may stay "
    "as-is). Use ONLY the numbers in the DATA block. Never invent prices, news, earnings dates, fundamentals, "
    "analyst views or events, and never claim records such as 'all-time high' unless the data says so. "
    "Do not give investment advice and never say 'buy now'; these are ideas to research further. "
    "Plain text, no markdown, no bullet points. Do not add disclaimers (the app shows one). "
    "Round numbers: prices to 2 decimals, RSI to whole numbers, percentages to 1 decimal. "
    "Hebrew style: say 'מצב השוק' (not 'משטר שוק'), 'ממוצע נע 50 יום', 'מחזור מסחר'; short, clear sentences."
)

TECHNICAL_SYSTEM = GROUND_RULES + (
    " Role: technical analyst. In 2-3 short sentences (max 60 words total), interpret trend "
    "(close vs SMA20/50/200), momentum "
    "(RSI14, MACD vs signal and histogram direction), volume ratio, relative strength vs the benchmark and "
    "distance from the 52-week high."
)

RISK_SYSTEM = GROUND_RULES + (
    " Role: risk reviewer arguing the bear case. In 1-2 short sentences (max 40 words), "
    "challenge the idea using the data: "
    "overextension (RSI, distance above SMA50), weak or missing volume confirmation, weak market regime, "
    "proximity to resistance, stop distance. Always add that the earnings date is unknown to this tool."
)

EDITOR_SYSTEM = GROUND_RULES + (
    " Role: editor. Combine the technical view and the bear case into strict JSON with exactly these keys: "
    '{"ticker": string, "verdict_he": string (max 6 words), "summary_he": string (max 2 short sentences), '
    '"confidence": "low"|"medium"|"high", "key_risks_he": array of 1-3 short strings}. '
    "Do not include any price levels in the JSON; entry, stop and target are shown separately and must not "
    "be changed. Confidence must be 'low' if the market regime is negative. Return JSON only."
)

BRIEF_SYSTEM = GROUND_RULES + (
    " Role: market brief writer. Write ONE short Hebrew paragraph (3-4 sentences) describing today's market "
    "using only the DATA: benchmark closes and daily change, position vs SMA50/SMA200, and breadth figures if "
    "given. Do not mention any specific stock. Do not repeat the risk-mode label; it is shown separately."
)

EDITOR_SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string", "minLength": 1},
        "verdict_he": {"type": "string", "minLength": 1, "maxLength": 80},
        "summary_he": {"type": "string", "minLength": 1, "maxLength": 400},
        "confidence": {"enum": ["low", "medium", "high"]},
        "key_risks_he": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1,
                         "maxItems": 3},
    },
    "required": ["ticker", "verdict_he", "summary_he", "confidence", "key_risks_he"],
    "additionalProperties": False,
}

LOWER = {"high": "medium", "medium": "low", "low": "low"}
BENCH_LABEL = {"SPY": "S&P 500 (SPY)", "QQQ": "Nasdaq-100 (QQQ)", "^TA125.TA": "TA-125"}


def _brief_snap(s: dict) -> dict:
    return {"date": s.get("date"), "close": _r(s.get("close")), "change_today_pct": _pct(s.get("change_pct")),
            "above_sma50": s.get("above_sma50"), "above_sma200": s.get("above_sma200"),
            "return_63d_pct": _pct(s.get("ret_63d"))}


def risk_mode(market: str, benchmarks: dict) -> str:
    """Rule-based regime. US uses SPY+QQQ, Israel uses TA-125."""
    snaps = list(benchmarks.values())
    if not snaps:
        return "cautious"
    above_all = all(s["above_sma50"] and s["above_sma200"] for s in snaps)
    below_all = all(not s["above_sma50"] and not s["above_sma200"] for s in snaps)
    return "positive" if above_all else "negative" if below_all else "cautious"


def breadth(stocks: list[dict]) -> dict:
    """Share of the scanned universe above SMA50/SMA200 and advancing today (derived, no prices)."""
    rows = [s["indicators"] for s in stocks if s.get("indicators") and not s.get("stale_since")]
    valid = [r for r in rows if r.get("sma50") and r.get("sma200") and r.get("close")]
    if not valid:
        return {}
    n = len(valid)
    return {
        "count": n,
        "pct_above_sma50": round(sum(r["close"] > r["sma50"] for r in valid) / n, 3),
        "pct_above_sma200": round(sum(r["close"] > r["sma200"] for r in valid) / n, 3),
        "pct_up_today": round(sum((r.get("change_pct") or 0) > 0 for r in valid) / n, 3),
    }


def _r(x, nd=2):
    return round(x, nd) if isinstance(x, (int, float)) else x


def _pct(x):
    return round(x * 100, 1) if isinstance(x, (int, float)) else None


def candidate_data(row: dict, market: str, regime: str, benchmark_name: str) -> dict:
    """Numbers the agents may use, pre-rounded and with ratios converted to percent."""
    i = row["indicators"]
    lv = row.get("levels") or {}
    return {
        "symbol": row["symbol"],
        "name": row.get("name_he") or row.get("name"),
        "market": "US" if market == "us" else "Israel (TASE)",
        "currency": "₪" if row.get("currency") == "ILS" else "$",
        "close": _r(i.get("close")),
        "change_today_pct": _pct(i.get("change_pct")),
        "sma20": _r(i.get("sma20")), "sma50": _r(i.get("sma50")), "sma200": _r(i.get("sma200")),
        "pct_above_sma50": _pct(i["close"] / i["sma50"] - 1) if i.get("sma50") else None,
        "rsi14": _r(i.get("rsi14"), 0),
        "macd_above_signal": (i.get("macd") or 0) > (i.get("macd_signal") or 0),
        "macd_histogram_rising": (i.get("macd_hist") or 0) > (i.get("macd_hist_prev") or 0),
        "volume_vs_20d_avg": _r(i.get("volume_ratio"), 2),
        "return_63d_pct": _pct(i.get("ret_63d")),
        "relative_strength_63d_vs_benchmark_pct": _pct(i.get("rs_63d")),
        "benchmark": benchmark_name,
        "pct_from_52w_high": _pct(i.get("dist_52w_high")),
        "score_0_100": row.get("score"),
        "label": (row.get("label") or {}).get("he"),
        "levels_fixed_by_code": {k: _r(lv.get(k)) for k in ("entry_low", "entry_high", "stop", "target")}
        if lv else None,
        "stop_distance_pct": _pct(lv.get("risk_pct")) if lv else None,
        "market_condition": {"positive": "חיובי", "cautious": "זהיר", "negative": "שלילי"}[regime],
    }


def _data_block(d: dict) -> str:
    return "DATA:" + json.dumps(d, ensure_ascii=False, default=str)


def parse_editor(text: str, ticker: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
    start, end = raw.find("{"), raw.rfind("}")
    obj = json.loads(raw[start:end + 1])
    jsonschema.validate(obj, EDITOR_SCHEMA)
    if obj["ticker"].upper().removesuffix(".TA") != ticker.upper():
        raise ValueError(f"ticker mismatch {obj['ticker']} != {ticker}")
    return obj


def analyze_candidate(client: BaseClient, row: dict, market: str, regime: str, benchmark_name: str) -> dict:
    """Run the three agents; return the 'ai' block for the row. Never raises."""
    data = candidate_data(row, market, regime, benchmark_name)
    block = _data_block(data)
    try:
        technical = client.complete(TECHNICAL_SYSTEM, block, max_tokens=400)
        bear = client.complete(RISK_SYSTEM, block, max_tokens=300)
        editor_input = f"{block}\nTECHNICAL: {technical}\nBEAR_CASE: {bear}"
        editor = None
        for attempt in range(2):  # validate against the schema, retry once on invalid JSON
            text = client.complete(EDITOR_SYSTEM, editor_input, json_mode=True, max_tokens=500)
            try:
                editor = parse_editor(text, row["symbol"])
                break
            except (ValueError, jsonschema.ValidationError) as exc:
                log.warning("Editor JSON invalid for %s (attempt %d): %s", row["symbol"], attempt + 1,
                            str(exc)[:120])
        if editor is None:
            raise LLMError("editor returned invalid JSON twice")
    except LLMError as exc:
        log.warning("AI analysis skipped for %s: %s", row["symbol"], exc)
        return {"available": False, "note": NO_AI_NOTE}
    confidence = editor["confidence"]
    if regime == "negative":
        confidence = "low" if confidence == "low" else LOWER[confidence]
    return {
        "available": True,
        "technical_he": technical,
        "bear_case_he": bear,
        "verdict_he": editor["verdict_he"],
        "summary_he": editor["summary_he"],
        "confidence": confidence,
        "confidence_model": editor["confidence"],
        "key_risks_he": editor["key_risks_he"],
    }


def market_brief(client: BaseClient | None, market: str, benchmarks: dict, breadth_stats: dict,
                 other_market: dict | None = None) -> dict:
    regime = risk_mode(market, benchmarks)
    out = {"risk_mode": regime, "risk_mode_he": RISK_MODE_HE[regime], "caution_banner": regime == "negative",
           "breadth": breadth_stats}
    data = {"market": "US" if market == "us" else "Israel (TASE)",
            "benchmarks": {BENCH_LABEL.get(k, k): _brief_snap(v) for k, v in benchmarks.items()},
            "breadth_pct": {k: _pct(v) if k.startswith("pct") else v for k, v in (breadth_stats or {}).items()}}
    if other_market:
        data["other_market"] = {
            "market": other_market.get("market"), "as_of": other_market.get("as_of"),
            "condition": other_market.get("risk_mode"),
            "breadth_pct": {k: _pct(v) if k.startswith("pct") else v
                            for k, v in (other_market.get("breadth") or {}).items()},
        }
    if client is None or not client.available:
        out["text_he"], out["ai"] = None, False
        return out
    try:
        out["text_he"] = client.complete(BRIEF_SYSTEM, "MARKET_BRIEF " + _data_block(data), max_tokens=500)
        out["ai"] = True
    except LLMError as exc:
        log.warning("Market brief failed: %s", exc)
        out["text_he"], out["ai"] = None, False
    return out
