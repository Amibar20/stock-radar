"""Paths, environment loading and secret-safe logging helpers."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:  # Use the OS certificate store (fixes TLS errors behind antivirus HTTPS scanning on Windows).
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover - optional
    pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DOCS_DATA_DIR = ROOT / "docs" / "data"

# Local .env lives outside OneDrive by default so keys are never synced to the cloud.
LOCAL_ENV_FILE = Path(os.environ.get("STOCK_RADAR_ENV", Path.home() / "stock-radar-local" / ".env"))

# Optional local CA bundle (certifi + Windows roots) for PCs whose antivirus intercepts HTTPS.
# Not present on GitHub runners, where the default certificates are used.
_DEFAULT_CA = Path.home() / "stock-radar-local" / "ca-bundle.pem"
LOCAL_CA_BUNDLE = Path(os.environ.get("STOCK_RADAR_CA_BUNDLE", _DEFAULT_CA))


def yf_session():
    """curl_cffi session for yfinance that honours the local CA bundle when it exists; else None."""
    if not LOCAL_CA_BUNDLE.exists():
        return None
    from curl_cffi import requests as curl_requests

    return curl_requests.Session(impersonate="chrome", verify=str(LOCAL_CA_BUNDLE))


SECRET_ENV_NAMES =("TWELVEDATA_API_KEY", "EODHD_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")

_QUERY_SECRET_RE = re.compile(r"(?i)\b(apikey|api_key|api_token|token|key)=([^&\s\"']+)")


def load_env() -> None:
    """Load the local .env (outside OneDrive), then a project .env if present. Real env vars win."""
    if LOCAL_ENV_FILE.exists():
        load_dotenv(LOCAL_ENV_FILE, override=False)
    project_env = ROOT / ".env"
    if project_env.exists():
        load_dotenv(project_env, override=False)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def scrub(text: Any) -> str:
    """Remove API keys from any text (URLs in exception messages included)."""
    s = str(text)
    s = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}=***", s)
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name)
        if value and len(value) >= 6:
            s = s.replace(value, "***")
    return s


class ScrubbingFilter(logging.Filter):
    """Logging filter that scrubs secrets from every record before it is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    handler.addFilter(ScrubbingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # urllib3 logs full request URLs (with keys) at DEBUG; keep it quiet.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        if compact:  # large machine-read files (chart history): no indentation
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)
