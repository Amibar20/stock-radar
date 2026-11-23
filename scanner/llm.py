"""Minimal LLM clients: Gemini (default, free tier), Anthropic, and a deterministic mock for tests/UI work.

Select with env LLM_PROVIDER=gemini|anthropic|mock. Models: GEMINI_MODEL (default gemini-3.5-flash-lite,
fallbacks in GEMINI_FALLBACK_MODELS), ANTHROPIC_MODEL (default claude-opus-5-5; claude-haiku-5-5 is the
cheap option).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from scanner.config import env, scrub

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    provider: str = ""
    model: str = ""
    calls: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    disabled_reason: str | None = None
    models_used: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class BaseClient:
    provider = "base"

    def __init__(self, min_interval: float = 0.0, max_consecutive_failures: int = 4) -> None:
        self.usage = Usage(provider=self.provider)
        self.min_interval = min_interval
        self._last = 0.0
        self._consecutive_failures = 0
        self.max_consecutive_failures = max_consecutive_failures

    @property
    def available(self) -> bool:
        return self.usage.disabled_reason is None

    def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 600) -> str:
        """Return the model's text. Raises LLMError on failure (callers degrade to 'no AI')."""
        if not self.available:
            raise LLMError(self.usage.disabled_reason or "LLM disabled")
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            text = self._complete(system, user, json_mode=json_mode, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001
            self.usage.failures += 1
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.max_consecutive_failures:
                self.usage.disabled_reason = f"stopped after {self._consecutive_failures} failures: {scrub(exc)}"
                log.error("LLM disabled for the rest of the run: %s", self.usage.disabled_reason)
            raise LLMError(scrub(exc)) from exc
        self._consecutive_failures = 0
        self.usage.calls += 1
        return text

    def _complete(self, system: str, user: str, *, json_mode: bool, max_tokens: int) -> str:
        raise NotImplementedError


class GeminiClient(BaseClient):
    provider = "gemini"

    def __init__(self, api_key: str, models: list[str], **kw) -> None:
        super().__init__(**kw)
        from google import genai
        from google.genai import types

        self._types = types
        # Our own retry loop handles 429/503 with backoff; disable the SDK's long internal retries.
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=45_000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.models = models
        self.usage.model = models[0]

    def _complete(self, system: str, user: str, *, json_mode: bool, max_tokens: int) -> str:
        t = self._types
        cfg = t.GenerateContentConfig(system_instruction=system, temperature=0.2, max_output_tokens=max_tokens,
                                      response_mime_type="application/json" if json_mode else None)
        last: Exception | None = None
        for model in self.models:
            for attempt, pause in enumerate((0, 8, 20)):
                if pause:
                    time.sleep(pause)
                try:
                    r = self._client.models.generate_content(model=model, contents=user, config=cfg)
                    text = (r.text or "").strip()
                    if not text:
                        raise LLMError("empty response")
                    u = r.usage_metadata
                    self.usage.input_tokens += (u.prompt_token_count or 0) if u else 0
                    self.usage.output_tokens += ((u.candidates_token_count or 0)
                                                 + (getattr(u, "thoughts_token_count", 0) or 0)) if u else 0
                    self.usage.models_used[model] = self.usage.models_used.get(model, 0) + 1
                    return text
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    msg = str(exc)
                    retryable = any(code in msg for code in ("429", "503", "500", "UNAVAILABLE", "timed out"))
                    log.warning("Gemini %s attempt %d failed: %s", model, attempt + 1, scrub(msg)[:160])
                    if not retryable:
                        break
        raise LLMError(scrub(last))


class AnthropicClient(BaseClient):
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, **kw) -> None:
        super().__init__(**kw)
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=90.0)
        self.model = model
        self.usage.model = model

    def _complete(self, system: str, user: str, *, json_mode: bool, max_tokens: int) -> str:
        # Current models reject temperature; effort "low" keeps these short, simple tasks cheap.
        output_config: dict = {"effort": "low"}
        r = self._client.messages.create(
            model=self.model,
            max_tokens=max(max_tokens, 2000),
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        if r.stop_reason == "refusal":
            raise LLMError("model refused")
        self.usage.input_tokens += r.usage.input_tokens
        self.usage.output_tokens += r.usage.output_tokens
        self.usage.models_used[self.model] = self.usage.models_used.get(self.model, 0) + 1
        text = "".join(b.text for b in r.content if b.type == "text").strip()
        if not text:
            raise LLMError("empty response")
        return text


class MockClient(BaseClient):
    """Deterministic Hebrew placeholder text; used for tests and UI previews. Costs nothing."""

    provider = "mock"

    def _complete(self, system: str, user: str, *, json_mode: bool, max_tokens: int) -> str:
        self.usage.input_tokens += len(user) // 4
        self.usage.output_tokens += 40
        if json_mode:
            data = json.loads(user.split("DATA:", 1)[1].split("TECHNICAL:", 1)[0])
            return json.dumps({
                "ticker": data["symbol"],
                "verdict_he": "רעיון למחקר נוסף",
                "summary_he": f"{data['symbol']}: מגמה טכנית לפי הנתונים. טקסט לדוגמה בלבד.",
                "confidence": "medium",
                "key_risks_he": ["טקסט לדוגמה: אין מידע על מועד הדוחות"],
            }, ensure_ascii=False)
        if "MARKET_BRIEF" in user:
            return "סיכום שוק לדוגמה: הטקסט נוצר על ידי לקוח בדיקה ואינו ניתוח אמיתי."
        return "טקסט לדוגמה של הסוכן. אינו ניתוח אמיתי."


def make_client() -> BaseClient | None:
    provider = (env("LLM_PROVIDER", "gemini") or "gemini").lower()
    if provider == "mock":
        return MockClient()
    if provider == "anthropic":
        key = env("ANTHROPIC_API_KEY")
        if not key:
            log.warning("ANTHROPIC_API_KEY missing; publishing without AI")
            return None
        return AnthropicClient(key, env("ANTHROPIC_MODEL", "claude-opus-5-5"))
    key = env("GEMINI_API_KEY")
    if not key:
        log.warning("GEMINI_API_KEY missing; publishing without AI")
        return None
    models = [env("GEMINI_MODEL", "gemini-3.5-flash-lite")]
    models += [m.strip() for m in (env("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite") or "").split(",")
               if m.strip() and m.strip() not in models]
    # Free tier allows only a few requests per minute: keep calls >= 4.5 s apart.
    return GeminiClient(key, models, min_interval=float(env("LLM_MIN_INTERVAL", "4.5")))
