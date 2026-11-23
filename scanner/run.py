"""Daily scan entry point.

    python -m scanner.run --market us                 # full US scan, writes docs/data/us.json
    python -m scanner.run --dry-run --limit 15 --market il --no-llm   # local test, writes out/il.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import time
from zoneinfo import ZoneInfo

import pandas as pd

from scanner import agents, indicators, scoring
from scanner.config import (
    CONFIG_DIR,
    DOCS_DATA_DIR,
    ROOT,
    env,
    load_env,
    read_json,
    setup_logging,
    write_json,
)
from scanner.llm import make_client
from scanner.providers import FetchResult
from scanner.universe import load_il_universe, load_us_universe

log = logging.getLogger("scanner.run")

MAX_FAILURE_RATIO = 0.30
SPARKLINE_BARS = 30
FINAL_BAR_BUFFER_MIN = 45  # minutes after the close before today's bar is treated as final


# ---------------------------------------------------------------- helpers
def drop_partial_bar(df: pd.DataFrame, market_cfg: dict, now_utc: dt.datetime) -> pd.DataFrame:
    """Remove today's bar if the market has not closed yet (providers return a live, partial bar)."""
    if df.empty:
        return df
    tz = ZoneInfo(market_cfg["timezone"])
    now_local = now_utc.astimezone(tz)
    if df.index[-1].date() != now_local.date():
        return df
    close_str = market_cfg.get("close_local_friday") if now_local.isoweekday() == 5 else None
    hh, mm = map(int, (close_str or market_cfg["close_local"]).split(":"))
    close_dt = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now_local < close_dt + dt.timedelta(minutes=FINAL_BAR_BUFFER_MIN):
        return df.iloc[:-1]
    return df


def market_snapshot(df: pd.DataFrame) -> dict:
    ind = indicators.compute(df)
    keys = ("date", "close", "change_pct", "sma50", "sma200", "rsi14", "ret_63d")
    snap = {k: ind.get(k) for k in keys}
    c = ind["close"]
    snap["above_sma50"] = bool(ind["sma50"] and c > ind["sma50"])
    snap["above_sma200"] = bool(ind["sma200"] and c > ind["sma200"])
    return snap


def _universe(market: str, limit: int | None, watchlist: list[str]) -> tuple[list[dict], list[str], str]:
    if market == "us":
        u = load_us_universe()
        stocks = [{"symbol": s["symbol"], "fetch": s["symbol"], "name": s["name"], "name_he": None,
                   "sector": s.get("sector")} for s in u["stocks"]]
        known = {s["symbol"] for s in stocks}
        for w in watchlist:
            if not w.endswith(".TA") and w not in known:
                stocks.append({"symbol": w, "fetch": w, "name": w, "name_he": None, "watch_only": True})
        return stocks, list(u["benchmarks"]), "USD"
    u = load_il_universe()
    stocks = [{"symbol": s["symbol"], "fetch": s["yahoo"], "name": s["name_en"], "name_he": s["name_he"],
               "index": s["index"]} for s in u["stocks"] if s.get("enabled", True)]
    known = {s["fetch"] for s in stocks}
    for w in watchlist:
        if w.endswith(".TA") and w not in known:
            stocks.append({"symbol": w[:-3], "fetch": w, "name": w, "name_he": None, "watch_only": True})
    return stocks, [u["benchmark"]["yahoo"]], "ILS"


def _apply_limit(stocks: list[dict], limit: int | None, watchlist: list[str]) -> list[dict]:
    if not limit:
        return stocks
    watched = [s for s in stocks if s["symbol"] in watchlist or s["fetch"] in watchlist]
    rest = [s for s in stocks if s not in watched]
    step = max(len(rest) // limit, 1)  # spread the sample across the list instead of the first N
    return rest[::step][:limit] + watched


def fetch(market: str, symbols: list[str]) -> FetchResult:
    if market == "us":
        from scanner.providers.twelvedata import TwelveDataClient

        key = env("TWELVEDATA_API_KEY")
        if not key:
            raise SystemExit("TWELVEDATA_API_KEY is not set")
        return TwelveDataClient(key).fetch_many(symbols)
    from scanner.providers import yahoo

    return yahoo.fetch_many(symbols)


# ---------------------------------------------------------------- main scan
def scan(market: str, limit: int | None, now_utc: dt.datetime, previous: dict | None) -> dict:
    cfg = scoring.load_config()
    cal = read_json(CONFIG_DIR / "calendar.json")[market]
    watchlist = read_json(CONFIG_DIR / "watchlist.json", [])
    stocks, benchmarks, currency = _universe(market, limit, watchlist)
    stocks = _apply_limit(stocks, limit, watchlist)

    res = fetch(market, benchmarks + [s["fetch"] for s in stocks])
    bars = {k: drop_partial_bar(v, cal, now_utc) for k, v in res.bars.items()}

    bench_close = bars[benchmarks[0]]["close"] if benchmarks[0] in bars else None
    bench_snap = {b: market_snapshot(bars[b]) for b in benchmarks if b in bars and len(bars[b]) >= 200}

    prev_by_symbol = {s["symbol"]: s for s in (previous or {}).get("stocks", [])}
    rows: list[dict] = []
    for s in stocks:
        df = bars.get(s["fetch"])
        if df is None or df.empty:
            reason = res.failed.get(s["fetch"], "no data")
            prev = prev_by_symbol.get(s["symbol"])
            if prev:  # keep yesterday's derived signals, clearly marked stale
                stale = dict(prev)
                stale["stale_since"] = prev.get("stale_since") or prev.get("date")
                stale["selected"] = False
                for k in ("rank", "sparkline"):  # stale rows never compete with today's ranking
                    stale.pop(k, None)
                rows.append(stale)
            else:
                rows.append({**_ident(s), "error": reason})
            continue
        ind = indicators.compute(df, bench_close)
        row = {**_ident(s), "date": ind["date"], "currency": res.currency.get(s["fetch"], currency),
               "indicators": _round(ind)}
        reason = scoring.gate(ind, row["currency"], cfg)
        if reason:
            row["gate"] = reason
        else:
            sc, pts = scoring.score(ind, cfg)
            row["score"], row["points"] = sc, pts
            row["label"] = scoring.label(sc, cfg)
            lv, drop = scoring.levels(ind, cfg)
            row["levels"], row["drop_reason"] = lv, drop
        row["_closes"] = df["close"].iloc[-SPARKLINE_BARS:]
        rows.append(row)

    ranked = sorted((r for r in rows if r.get("score") is not None and not r.get("stale_since")),
                    key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    top_n = cfg["selection"]["us_top" if market == "us" else "il_top"]
    picks = [r for r in ranked if r.get("label") and r.get("levels")][:top_n]
    watched = [r for r in rows if r["symbol"] in watchlist or r.get("fetch") in watchlist]
    selected = {id(r) for r in picks + watched}
    watched_ids = {id(r) for r in watched}
    for r in rows:
        closes = r.pop("_closes", None)
        r["selected"] = id(r) in selected
        r["watchlist"] = id(r) in watched_ids
        if r["selected"] and closes is not None:
            r["sparkline"] = [round(float(x), 4) for x in closes]

    as_of = max((r["date"] for r in rows if r.get("date") and not r.get("stale_since")), default=None)
    fetched = len([s for s in stocks if s["fetch"] in res.bars])
    return {
        "market": market,
        "currency": currency,
        "generated_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of,
        "benchmarks": bench_snap,
        "stats": {
            "universe": len(stocks),
            "fetched": fetched,
            "failed": sorted(s["symbol"] for s in stocks if s["fetch"] not in res.bars),
            "failure_ratio": round(1 - fetched / len(stocks), 3) if stocks else 0,
            "scored": len(ranked),
            "picks": len(picks),
            "credits_used": res.credits_used,
            "stopped_by_budget": res.stopped_by_budget,
        },
        "stocks": sorted(rows, key=lambda r: (r.get("rank") or 10_000, r["symbol"])),
    }


def _ident(s: dict) -> dict:
    keys = ("symbol", "fetch", "name", "name_he", "sector", "index", "watch_only")
    return {k: s[k] for k in keys if s.get(k) is not None}


def _round(ind: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ind.items()}


OTHER = {"us": "il", "il": "us"}
BENCHMARK_NAME = {"us": "SPY", "il": "TA-125"}


def add_ai(result: dict, use_llm: bool, other: dict | None) -> None:
    """Attach the market brief and per-candidate AI analysis. Quantitative results never depend on it.

    The free Gemini tier is often overloaded, so the whole AI step has a time budget (LLM_TIME_BUDGET seconds,
    default 1200); anything not analysed in time is published with the 'no AI' note.
    """
    market = result["market"]
    cfg = scoring.load_config()
    client = make_client() if use_llm else None
    regime = agents.risk_mode(market, result["benchmarks"])
    deadline = time.monotonic() + float(env("LLM_TIME_BUDGET", "1200"))

    def in_time() -> bool:
        if client is not None and client.available and time.monotonic() > deadline:
            client.usage.disabled_reason = "AI time budget reached"
            log.warning("AI time budget reached; remaining candidates published without AI")
        return client is not None and client.available

    other_summary = None
    if other and other.get("brief"):
        other_summary = {"market": other["market"], "as_of": other.get("as_of"),
                         "risk_mode": other["brief"].get("risk_mode"), "breadth": other["brief"].get("breadth")}
    # Market brief first: it is the most important text of the day.
    result["brief"] = agents.market_brief(client, market, result["benchmarks"], agents.breadth(result["stocks"]),
                                          other_summary)

    selected = [r for r in result["stocks"] if r.get("selected") and r.get("indicators")]
    cap = cfg["selection"]["max_llm_candidates"]
    no_ai = {"available": False, "note": agents.NO_AI_NOTE}
    for i, row in enumerate(selected):
        if i < cap and in_time():
            row["ai"] = agents.analyze_candidate(client, row, market, regime, BENCHMARK_NAME[market])
        else:
            row["ai"] = dict(no_ai)
    # One more pass for candidates hit by a transient error (free-tier 503s are common).
    for row in selected[:cap]:
        if not row["ai"].get("available") and in_time():
            row["ai"] = agents.analyze_candidate(client, row, market, regime, BENCHMARK_NAME[market])

    usage = client.usage.as_dict() if client else {"provider": None, "disabled_reason": "--no-llm or no key"}
    usage["candidates_analyzed"] = sum(1 for r in selected if (r.get("ai") or {}).get("available"))
    usage["candidates_selected"] = len(selected)
    result["stats"]["llm"] = usage


def summary_markdown(out: dict) -> str:
    st = out["stats"]
    brief = out.get("brief") or {}
    llm = st.get("llm") or {}
    lines = [f"## {out['market'].upper()} scan — data as of {out['as_of']}",
             f"- market regime: {brief.get('risk_mode_he', '?')}"
             + (" — CAUTION BANNER" if brief.get("caution_banner") else ""),
             f"- LLM: {llm.get('provider')} {llm.get('model', '')} calls={llm.get('calls', 0)} "
             f"failures={llm.get('failures', 0)} tokens in/out={llm.get('input_tokens', 0)}/"
             f"{llm.get('output_tokens', 0)} analyzed={llm.get('candidates_analyzed', 0)}"
             + (f" disabled: {llm['disabled_reason']}" if llm.get("disabled_reason") else ""),
             f"- symbols fetched: {st['fetched']}/{st['universe']} (failure ratio {st['failure_ratio']:.0%})",
             f"- failures: {', '.join(st['failed'][:30]) or 'none'}",
             f"- provider credits used: {st['credits_used']}"
             + (" — STOPPED BY DAILY BUDGET" if st["stopped_by_budget"] else ""),
             f"- scored: {st['scored']}, picks: {st['picks']}", "",
             "| # | symbol | score | label | entry | stop | target |",
             "|---|---|---|---|---|---|---|"]
    for r in out["stocks"]:
        if r.get("selected"):
            lv = r.get("levels") or {}
            lab = (r.get("label") or {}).get("he", "")
            lines.append(f"| {r.get('rank', '')} | {r['symbol']} | {r.get('score', '')} | {lab} | "
                         f"{lv.get('entry_low', '')}–{lv.get('entry_high', '')} | {lv.get('stop', '')} | "
                         f"{lv.get('target', '')} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "il"], required=True)
    ap.add_argument("--limit", type=int, default=None, help="scan only N symbols (testing)")
    ap.add_argument("--dry-run", action="store_true", help="write to out/ instead of docs/data")
    ap.add_argument("--no-llm", action="store_true", help="skip the AI agents (Stage 3)")
    args = ap.parse_args(argv)

    load_env()
    setup_logging()
    out_dir = ROOT / "out" if args.dry_run else DOCS_DATA_DIR
    out_file = out_dir / f"{args.market}.json"
    previous = read_json(DOCS_DATA_DIR / f"{args.market}.json")
    now = dt.datetime.now(dt.UTC)

    result = scan(args.market, args.limit, now, previous)

    status_file = out_dir / "status.json"
    status = read_json(status_file, {}) or {}
    if not args.dry_run and previous and result["as_of"] and previous.get("as_of") and \
            result["as_of"] <= previous["as_of"]:
        log.info("No new trading-day bar (%s); nothing to publish.", result["as_of"])
        return 0
    if result["stats"]["failure_ratio"] > MAX_FAILURE_RATIO:
        msg = (f"{result['stats']['failure_ratio']:.0%} of {args.market.upper()} symbols failed; "
               "previous data kept")
        log.error(msg)
        status[args.market] = {"ok": False, "checked_at": result["generated_at"], "message": msg}
        write_json(status_file, status)
        return 0

    add_ai(result, use_llm=not args.no_llm, other=read_json(DOCS_DATA_DIR / f"{OTHER[args.market]}.json"))
    md = summary_markdown(result)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md)
    write_json(out_file, result)
    status[args.market] = {"ok": True, "checked_at": result["generated_at"], "as_of": result["as_of"]}
    write_json(status_file, status)
    log.info("Wrote %s", out_file.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
