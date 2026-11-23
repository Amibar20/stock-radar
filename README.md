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
