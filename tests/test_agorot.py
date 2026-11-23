import datetime as dt

import pytest
from conftest import make_bars

from scanner.providers.yahoo import to_main_currency
from scanner.run import drop_partial_bar


def test_ila_converted_to_ils():
    df = make_bars([13270.0, 13300.0], volume=500)
    out, cur = to_main_currency(df, "ILA")
    assert cur == "ILS"
    assert out["close"].tolist() == pytest.approx([132.70, 133.00])
    assert out["high"].iloc[0] == pytest.approx(13270 * 1.01 / 100)
    assert out["volume"].tolist() == [500, 500]  # share volume unchanged
    assert df["close"].iloc[0] == 13270.0  # input not mutated


def test_ils_and_usd_unchanged():
    df = make_bars([3768.97])
    for code in ("ILS", "USD"):
        out, cur = to_main_currency(df, code)
        assert cur == code and out["close"].iloc[0] == pytest.approx(3768.97)


def test_missing_currency_fails_instead_of_guessing():
    with pytest.raises(ValueError):
        to_main_currency(make_bars([13270.0]), None)


def test_partial_bar_dropped_before_close():
    df = make_bars([1.0, 2.0, 3.0])
    last_day = df.index[-1].date()
    cal = {"timezone": "America/New_York", "close_local": "16:00"}
    # 15:30 New York on the last bar's day -> bar is live, drop it
    during = dt.datetime.combine(last_day, dt.time(20, 30), tzinfo=dt.UTC)  # 15:30 EST (winter)
    assert len(drop_partial_bar(df, cal, during)) == 2
    after = dt.datetime.combine(last_day, dt.time(22, 30), tzinfo=dt.UTC)
    assert len(drop_partial_bar(df, cal, after)) == 3
