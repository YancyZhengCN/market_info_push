"""MACD 计算测试：核心是与用户参考实现 calculateMACD.py 逐值一致（M3 验收）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import macd as macd_mod

try:
    import calculateMACD as ref_mod  # 项目内参考基准

    HAVE_REF = True
except Exception:
    HAVE_REF = False


def _make_close(seed=0, n=200, start="2024-01-01"):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=n)
    t = np.arange(n)
    vals = 100 + 5 * np.sin(t / 6.0) + rng.normal(0, 1, n).cumsum() * 0.5
    return pd.Series(vals, index=dates)


def test_reference_alignment():
    if not HAVE_REF:
        print("SKIP test_reference_alignment: 参考 calculateMACD.py 不可用")
        return
    for period in ("daily", "2d", "weekly"):
        close = _make_close(seed=1, n=200)
        mine = macd_mod.macd_series(close, period)["bar"]
        s = macd_mod._prepare(close, period)
        df = pd.DataFrame({"close": s.values}, index=s.index)
        ref_mod.calculate_macd(df)
        ref_bar = df["bar"]
        np.testing.assert_allclose(
            mine.values, ref_bar.values, rtol=1e-9,
            err_msg=f"MACD 与参考实现不一致: {period}",
        )
    print("PASS test_reference_alignment (daily/2d/weekly 与参考实现逐值一致)")


def test_period_construction():
    close = _make_close(n=20)
    d = macd_mod.compute(close, "daily")
    p2 = macd_mod.compute(close, "2d")
    w = macd_mod.compute(close, "weekly")
    assert d.bar is not None
    assert p2.series.shape[0] == 10, p2.series.shape[0]  # 20 -> 隔行 10
    assert w.series.shape[0] >= 2
    print("PASS test_period_construction")


if __name__ == "__main__":
    test_reference_alignment()
    test_period_construction()
    print("test_macd OK")
