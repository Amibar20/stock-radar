import json

import jsonschema
import pytest
from test_scoring import base_ind

from scanner import agents
from scanner.llm import BaseClient, LLMError, MockClient

UP = {"above_sma50": True, "above_sma200": True}
DOWN = {"above_sma50": False, "above_sma200": False}


def row(**over):
    r = {"symbol": "AAPL", "name": "Apple", "currency": "USD", "indicators": base_ind(), "score": 80,
         "points": {"x": 1}, "label": {"he": "בדיקה לקנייה"},
         "levels": {"entry": 109, "stop": 106, "target": 115}}
    r.update(over)
    return r


def test_risk_mode():
    assert agents.risk_mode("us", {"SPY": UP, "QQQ": UP}) == "positive"
    assert agents.risk_mode("us", {"SPY": DOWN, "QQQ": DOWN}) == "negative"
    assert agents.risk_mode("us", {"SPY": UP, "QQQ": DOWN}) == "cautious"
    assert agents.risk_mode("il", {"^TA125.TA": DOWN}) == "negative"


def test_parse_editor_validates_schema_and_ticker():
    good = {"ticker": "AAPL", "verdict_he": "רעיון", "summary_he": "סיכום", "confidence": "high",
            "key_risks_he": ["סיכון"]}
    assert agents.parse_editor("```json\n" + json.dumps(good) + "\n```", "AAPL")["confidence"] == "high"
    with pytest.raises(jsonschema.ValidationError):
        agents.parse_editor(json.dumps({**good, "confidence": "very high"}), "AAPL")
    with pytest.raises(jsonschema.ValidationError):
        agents.parse_editor(json.dumps({**good, "entry": 100}), "AAPL")  # extra keys (e.g. prices) rejected
    with pytest.raises(ValueError):
        agents.parse_editor(json.dumps({**good, "ticker": "MSFT"}), "AAPL")


def test_analyze_with_mock_keeps_levels_and_lowers_confidence_in_negative_market():
    r = row()
    ai = agents.analyze_candidate(MockClient(), r, "us", "negative", "SPY")
    assert ai["available"] and ai["confidence"] == "low" and ai["confidence_model"] == "medium"
    assert r["levels"] == {"entry": 109, "stop": 106, "target": 115}  # untouched
    ai = agents.analyze_candidate(MockClient(), r, "us", "positive", "SPY")
    assert ai["confidence"] == "medium"


class FailingClient(BaseClient):
    provider = "fail"

    def _complete(self, *a, **k):
        raise RuntimeError("503 UNAVAILABLE")


def test_llm_failure_degrades_to_no_ai_and_circuit_breaker():
    c = FailingClient(max_consecutive_failures=2)
    ai = agents.analyze_candidate(c, row(), "us", "positive", "SPY")
    assert ai == {"available": False, "note": agents.NO_AI_NOTE}
    agents.analyze_candidate(c, row(), "us", "positive", "SPY")
    assert not c.available
    with pytest.raises(LLMError):
        c.complete("s", "u")


class BadJsonClient(MockClient):
    def _complete(self, system, user, *, json_mode, max_tokens):
        return "not json" if json_mode else "טקסט"


def test_editor_invalid_json_retried_once_then_no_ai():
    c = BadJsonClient()
    ai = agents.analyze_candidate(c, row(), "us", "positive", "SPY")
    assert ai["available"] is False
    assert c.usage.calls == 4  # technical + bear + 2 editor attempts


def test_market_brief_without_llm_still_has_regime():
    b = agents.market_brief(None, "us", {"SPY": DOWN, "QQQ": DOWN}, {"count": 10})
    assert b["risk_mode_he"] == "שוק שלילי" and b["caution_banner"] and b["text_he"] is None
