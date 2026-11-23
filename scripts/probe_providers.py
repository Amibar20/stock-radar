"""Stage 1 live probe: 1-2 real calls per provider, report what works and the limits observed.

Usage:
    python scripts/probe_providers.py                 # all providers
    python scripts/probe_providers.py --only yfinance,eodhd
Never prints API keys (all output goes through scrub()).
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.config import ROOT, env, load_env, read_json, scrub, yf_session  # noqa: E402

OUT_DIR = ROOT / "probe_results"


def p(msg: str) -> None:
    print(scrub(msg), flush=True)


def probe_twelvedata() -> dict:
    key = env("TWELVEDATA_API_KEY")
    if not key:
        return {"ok": False, "error": "TWELVEDATA_API_KEY missing"}
    result: dict = {"calls": []}
    for sym in ("AAPL", "BRK.B"):
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": sym, "interval": "1day", "outputsize": 260}
        t0 = time.time()
        try:
            # Header auth keeps the key out of URLs (and therefore out of error messages).
            r = requests.get(url, params=params, headers={"Authorization": f"apikey {key}"}, timeout=30)
            body = r.json()
        except Exception as exc:  # noqa: BLE001
            result["calls"].append({"symbol": sym, "error": scrub(exc)})
            continue
        values = body.get("values") or []
        call = {
            "symbol": sym,
            "http": r.status_code,
            "status": body.get("status"),
            "message": scrub(body.get("message", "")),
            "bars": len(values),
            "last_bar": values[0] if values else None,
            "currency": (body.get("meta") or {}).get("currency"),
            "credits_used_header": r.headers.get("api-credits-used"),
            "credits_left_header": r.headers.get("api-credits-left"),
            "seconds": round(time.time() - t0, 2),
        }
        result["calls"].append(call)
        time.sleep(8)  # respect 8 credits/min
    try:
        r = requests.get("https://api.twelvedata.com/api_usage", headers={"Authorization": f"apikey {key}"},
                         timeout=30)
        result["api_usage"] = r.json()
    except Exception as exc:  # noqa: BLE001
        result["api_usage"] = {"error": scrub(exc)}
    result["ok"] = any(c.get("bars", 0) >= 200 for c in result["calls"])
    return result


def probe_eodhd() -> dict:
    key = env("EODHD_API_KEY")
    if not key:
        return {"ok": False, "error": "EODHD_API_KEY missing"}
    result: dict = {"calls": []}
    try:
        r = requests.get("https://eodhd.com/api/user", params={"api_token": key, "fmt": "json"}, timeout=30)
        user = r.json()
        result["user"] = {k: user.get(k) for k in ("subscriptionType", "apiRequests", "dailyRateLimit",
                                                    "apiRequestsDate", "extraLimit")}
    except Exception as exc:  # noqa: BLE001
        result["user"] = {"error": scrub(exc)}
    for sym in ("TEVA.TA",):
        try:
            r = requests.get(f"https://eodhd.com/api/eod/{sym}",
                             params={"api_token": key, "fmt": "json", "period": "d"}, timeout=30)
            is_json = r.headers.get("content-type", "").startswith("application/json")
            body = r.json() if is_json else r.text[:200]
        except Exception as exc:  # noqa: BLE001
            result["calls"].append({"symbol": sym, "error": scrub(exc)})
            continue
        if isinstance(body, list):
            result["calls"].append({"symbol": sym, "http": r.status_code, "bars": len(body),
                                    "first_date": body[0]["date"] if body else None,
                                    "last_bar": body[-1] if body else None})
        else:
            result["calls"].append({"symbol": sym, "http": r.status_code, "body": scrub(body)})
    result["ok"] = any(c.get("bars", 0) >= 200 for c in result["calls"])
    return result


def probe_yfinance() -> dict:
    import yfinance as yf

    il = read_json(ROOT / "data" / "universe_il.json")
    symbols = [s["yahoo"] for s in il["stocks"]] + [il["benchmark"]["yahoo"]]
    t0 = time.time()
    result: dict = {"requested": len(symbols)}
    try:
        df = yf.download(symbols, period="13mo", interval="1d", group_by="ticker", auto_adjust=False,
                         progress=False, threads=True, session=yf_session())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": scrub(exc)}
    ok, failed, short = [], [], []
    for sym in symbols:
        try:
            closes = df[sym]["Close"].dropna()
        except KeyError:
            failed.append(sym)
            continue
        if len(closes) == 0:
            failed.append(sym)
        elif len(closes) < 200:
            short.append(f"{sym}:{len(closes)}")
        else:
            ok.append(sym)
    result.update({"ok_count": len(ok), "failed": failed, "short_history": short,
                   "seconds": round(time.time() - t0, 1)})
    sample = {}
    for sym in ("TEVA.TA", "ESLT.TA", il["benchmark"]["yahoo"]):
        try:
            t = yf.Ticker(sym, session=yf_session())
            fi = t.fast_info
            closes = df[sym]["Close"].dropna()
            sample[sym] = {"currency": fi["currency"], "last_close": float(closes.iloc[-1]),
                           "last_date": str(closes.index[-1].date()), "bars": len(closes)}
        except Exception as exc:  # noqa: BLE001
            sample[sym] = {"error": scrub(exc)}
    result["sample"] = sample
    result["ok"] = len(ok) >= 0.7 * len(symbols)
    return result


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="twelvedata,eodhd,yfinance")
    args = ap.parse_args()
    report = {"host": platform.node()[:3] + "…", "python": platform.python_version(),
              "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    probes = {"twelvedata": probe_twelvedata, "eodhd": probe_eodhd, "yfinance": probe_yfinance}
    for name in args.only.split(","):
        p(f"--- probing {name} ...")
        report[name] = probes[name]()
        p(json.dumps(report[name], ensure_ascii=False, indent=2, default=str))
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "probe.json").write_text(scrub(json.dumps(report, ensure_ascii=False, indent=2, default=str)),
                                        encoding="utf-8")


if __name__ == "__main__":
    main()
