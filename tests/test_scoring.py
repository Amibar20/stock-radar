import pytest

from scanner import scoring


def base_ind(**over):
    ind = {
        "bars": 260, "close": 110.0, "change_pct": 0.01, "sma20": 107.0, "sma50": 100.0, "sma200": 90.0,
        "sma50_10d_ago": 98.0, "rsi14": 60.0, "macd": 1.2, "macd_signal": 1.0, "macd_hist": 0.2,
        "macd_hist_prev": 0.1, "atr14": 2.0, "volume_ratio": 1.5, "avg_dollar_volume20": 50e6,
        "rs_63d": 0.10, "high_52w": 111.0, "prior_high_52w": 150.0, "dist_52w_high": -0.01,
        "swing_low_10d": 105.0,
    }
    ind.update(over)
    return ind


def test_perfect_setup_scores_100(cfg):
    sc, pts = scoring.score(base_ind(), cfg)
    assert sc == 100
    assert "penalty_rsi_overbought" not in pts


def test_score_components_are_transparent(cfg):
    sc, pts = scoring.score(base_ind(volume_ratio=1.1, rs_63d=0.025), cfg)
    assert pts["volume_mild_up_day"] == 5
    assert pts["relative_strength"] == pytest.approx(10.0)  # halfway between -5% and +10%
    assert sc == pytest.approx(sum(pts.values()))


def test_penalties_for_overbought_and_extended(cfg):
    sc, pts = scoring.score(base_ind(rsi14=82, close=120.0), cfg)
    assert pts["penalty_rsi_overbought"] == -15
    assert pts["penalty_extended_above_sma50"] == -15
    assert "rsi_in_range" not in pts
    assert sc < 70


def test_downtrend_scores_low(cfg):
    ind = base_ind(close=80.0, sma50=90.0, sma200=100.0, sma50_10d_ago=92.0, rsi14=35, macd=-1,
                   macd_signal=-0.5, macd_hist=-0.5, macd_hist_prev=-0.4, change_pct=-0.01,
                   rs_63d=-0.2, dist_52w_high=-0.35)
    sc, _ = scoring.score(ind, cfg)
    assert sc == 0


def test_gates(cfg):
    assert scoring.gate(base_ind(bars=150), "USD", cfg).startswith("only 150 bars")
    assert "liquidity" in scoring.gate(base_ind(avg_dollar_volume20=1e6), "USD", cfg)
    assert scoring.gate(base_ind(avg_dollar_volume20=4e6), "ILS", cfg) is None
    assert "missing" in scoring.gate(base_ind(sma200=None), "USD", cfg)


def test_labels(cfg):
    assert scoring.label(75, cfg)["he"] == "בדיקה לקנייה"
    assert scoring.label(55, cfg)["key"] == "watch"
    assert scoring.label(49.9, cfg) is None
