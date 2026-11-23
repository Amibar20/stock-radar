# Stock Radar

Personal daily stock scanner (S&P 500 + Nasdaq-100, TASE TA-125) published as a Hebrew PWA on GitHub Pages.
**Personal research tool, not investment advice.**

Status: Stage 1 (skeleton, universes, provider probe). Full setup, scoring formulas and limits are documented as
the stages land.

## Local setup (Windows)
- Virtual env and secrets live outside OneDrive: `%USERPROFILE%\stock-radar-local\.venv` and `...\.env`
  (template: `.env.example`).
- `python -m scanner.universe --refresh-us` rebuilds `data/universe_us.json` from Wikipedia.
- `python scripts/probe_providers.py` makes 1-2 live calls per provider and writes `probe_results/probe.json`
  (git-ignored).
- If an antivirus intercepts HTTPS (e.g. AVG Web Shield), put a CA bundle with the Windows roots at
  `%USERPROFILE%\stock-radar-local\ca-bundle.pem`; the code picks it up automatically.

## Universe files
- `data/universe_us.json`: generated, refreshed monthly; the committed copy is the fallback.
- `data/universe_il.json`: TA-125 from the TASE website (TA-35 + TA-90), hand-editable. Set `"enabled": false`
  to skip a stock.
- `config/watchlist.json`: tickers always analysed, e.g. `["AAPL", "TEVA.TA"]`.

## Scoring (config/scoring.json)
Every stock that passes the data-quality gates (>= 200 daily bars, 20-day average traded value >= $20M or
>= ₪3M) gets points per rule; the total is clipped to 0-100 and every rule's points are published with the stock.

| Group | Rule | Points |
|---|---|---|
| Trend | close > SMA50 / SMA50 > SMA200 / close > SMA200 / SMA50 higher than 10 days ago | 10 / 10 / 5 / 5 |
| Momentum | RSI14 between 45 and 70 / MACD above signal / MACD histogram rising | 10 / 8 / 7 |
| Volume | up day with volume >= 1.3x the prior 20-day average (or >= 1.0x for 5 points) | 15 |
| Relative strength | 63-day return minus benchmark's (SPY for US, TA-125 for Israel): 0 at -5%, full at +10%, linear | 0-20 |
| 52-week high | within 5% / 10% / 20% of the 52-week high | 10 / 6 / 3 |
| Penalties | RSI14 > 78 / close more than 15% above SMA50 | -15 / -15 |

Labels: score >= 70 "בדיקה לקנייה", 50-69 "מעקב", below 50 not shown.

## Levels
- **Entry zone**: upper = last close; lower = max(SMA20, close - 1 x ATR14) when SMA20 is below the close,
  otherwise close - 0.5 x ATR14. The **entry reference** used for R math is the middle of the zone.
- **Stop**: entry - 1.5 x ATR14, raised if needed so it is never more than 1 x ATR14 below the 10-day swing low.
- **Target**: entry + 2 x (entry - stop), so reward:risk is exactly 2 by construction.
- **Dropped ideas**: stop more than 10% below entry, or the prior 52-week high (excluding the last 10 bars) sits
  between entry and entry + 1R while the close is still below it. A close at or above that prior high is a breakout
  and is kept.
- Today's bar is ignored until 45 minutes after the market close (providers return a live, partial bar).
- Israeli prices arrive from Yahoo in agorot (ILA) and are divided by 100 to shekels; a symbol without currency metadata is
  failed rather than guessed.

## Limits (verified 2026-11-23)
- Twelve Data free: 8 credits/min, 800/day. 518 US stocks + SPY + QQQ = 520 credits ≈ 66 minutes per run.
  The run checks credits already used today and stops at 780.
- EODHD free has no Tel Aviv exchange; Twelve Data needs the Pro plan for TASE. Israel therefore uses yfinance only
  (works from GitHub runners: 119/125 symbols). If Yahoo fails for a symbol, its previous signals are kept and
  marked stale; if more than 30% fail, the previous data is kept and the UI shows why.

## AI agents (Stage 3)
Only the selected candidates (top 12 US, top 6 Israel, plus the watchlist; at most 20 per run) are sent to the LLM,
as small separate prompts that receive **only our computed, pre-rounded numbers**:
1. **Technical analyst**: 2-3 Hebrew sentences interpreting the indicators.
2. **Risk reviewer**: 1-2 Hebrew sentences with the bear case (always notes the earnings date is unknown).
3. **Editor**: strict JSON `{ticker, verdict_he, summary_he, confidence, key_risks_he}` validated with a JSON schema
   (extra keys such as prices are rejected), retried once. Entry/stop/target always come from the code.
4. **Market brief**: one Hebrew paragraph per market from the benchmarks and breadth. The risk mode
   (positive / cautious / negative) is rule-based: negative when every benchmark is below both SMA50 and SMA200
   (US: SPY and QQQ; Israel: TA-125). A negative regime shows a caution banner and lowers each confidence one step.

Provider: `LLM_PROVIDER=gemini` (default, free tier, `gemini-3.5-flash-lite` with `gemini-3.1-flash-lite` as
fallback), `anthropic`, or `mock` (deterministic placeholder text, no cost). The free Gemini tier frequently answers
503/504 under load: calls are retried with backoff, failed candidates get a second pass, the client stops after 4
consecutive failures, and the whole AI step is capped at `LLM_TIME_BUDGET` seconds. Anything not analysed is
published with "ללא ניתוח AI". Token usage is logged in the run summary and in `stats.llm`.
`--no-llm` skips the AI step entirely.

## Track record (Stage 4)
Each published run appends its labelled picks to `docs/data/history/<data date>.json` (one file per date, both
markets) and re-evaluates every open idea of that market with the fresh bars into `docs/data/track_record.json`.

| Status | Rule |
|---|---|
| pending | waiting for the price to touch the entry (middle of the zone), up to 5 trading days |
| not_triggered | never touched the entry within 5 trading days; excluded from the statistics |
| open | entered; marked to market at the last close |
| target | high reached the target (exit at the target) |
| stopped | low reached the stop (exit at the stop, or at the open on a gap down). A bar that touches both counts as stopped; on the fill bar only the stop is checked |
| expired | 20 trading days after the fill, exit at that day's close |

R multiple = (exit - entry) / (entry - stop); entry is filled at the entry price, or at the open if the bar opens
below it. The summary (overall / US / Israel) reports hit rate (targets / completed), win rate (R > 0), average and
total R, average % move, and the benchmark's average % move over the same fill-to-exit dates (SPY for US, TA-125
for Israel). Below 30 completed ideas `too_few_to_conclude` is true and the UI says so.

`--as-of YYYY-MM-DD` (only with `--dry-run`) re-runs the scanner as if on an earlier date, writing to `out/`, to test
the tracker end to end. Simulated ideas are never published.
