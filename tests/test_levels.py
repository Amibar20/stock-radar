import pytest
from test_scoring import base_ind

from scanner import scoring


def test_levels_formula(cfg):
    # close 110, SMA20 107, ATR 2 -> lower = max(107, 108) = 108, entry = 109
    lv, drop = scoring.levels(base_ind(prior_high_52w=150.0), cfg)
    assert drop is None
    assert lv["entry_low"] == 108 and lv["entry_high"] == 110 and lv["entry"] == 109
    # stop = 109 - 3 = 106; swing low 105 - 2 = 103 floor not binding
    assert lv["stop"] == pytest.approx(106)
    assert lv["target"] == pytest.approx(109 + 2 * 3)
    assert lv["reward_risk"] == pytest.approx(2.0)


def test_stop_never_more_than_1atr_below_swing_low(cfg):
    lv, _ = scoring.levels(base_ind(swing_low_10d=107.5, prior_high_52w=150.0), cfg)
    # entry - 1.5 ATR = 106 is more than 1 ATR below the swing low (107.5 - 2 = 105.5)? No: 106 > 105.5.
    assert lv["stop"] == pytest.approx(106)
    lv, _ = scoring.levels(base_ind(swing_low_10d=109.0, prior_high_52w=150.0), cfg)
    assert lv["stop"] == pytest.approx(107.0)  # raised to swing low - 1 ATR


def test_close_below_sma20_uses_half_atr_pullback(cfg):
    lv, _ = scoring.levels(base_ind(sma20=112.0, prior_high_52w=150.0), cfg)
    assert lv["entry_low"] == pytest.approx(109.0)
    assert lv["entry"] == pytest.approx(109.5)


def test_drop_when_prior_high_overhead(cfg):
    # close 110 below the prior high 111; entry 109, risk 3 -> 111 is less than 1R (112) above entry
    lv, drop = scoring.levels(base_ind(high_52w=111.0, prior_high_52w=111.0), cfg)
    assert lv is None and "52-week high" in drop


def test_breakout_above_prior_high_is_kept(cfg):
    # Today's high (111) is the 52-week high, close 110 is above the prior high 109.5: breakout, keep.
    lv, drop = scoring.levels(base_ind(high_52w=111.0, prior_high_52w=109.5), cfg)
    assert drop is None and lv is not None


def test_resistance_beyond_1r_is_kept(cfg):
    lv, drop = scoring.levels(base_ind(high_52w=113.0, prior_high_52w=113.0), cfg)  # 113 > entry + 1R
    assert drop is None and lv is not None


def test_drop_when_stop_too_wide(cfg):
    lv, drop = scoring.levels(base_ind(atr14=10.0, swing_low_10d=50.0, prior_high_52w=200.0), cfg)
    assert lv is None and "too wide" in drop
