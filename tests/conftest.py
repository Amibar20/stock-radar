import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_bars(closes, volume=1_000_000, spread=0.01) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range("2025-01-02", periods=len(closes))
    return pd.DataFrame({
        "open": closes,
        "high": closes * (1 + spread),
        "low": closes * (1 - spread),
        "close": closes,
        "volume": np.full(len(closes), float(volume)),
    }, index=idx)


@pytest.fixture
def uptrend() -> pd.DataFrame:
    # Steady 0.3%/day rise for 260 bars
    return make_bars(100 * 1.003 ** np.arange(260))


@pytest.fixture
def cfg():
    from scanner.scoring import load_config

    return load_config()
