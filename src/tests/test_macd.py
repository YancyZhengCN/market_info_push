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
    # 2 日 K 线：最新一根单独成桶 + 其后每 2 根一桶 → 20 根日线得 1 + ceil(19/2) = 11 根
    assert p2.series.shape[0] == 11, p2.series.shape[0]
    assert w.series.shape[0] >= 2
    print("PASS test_period_construction")


def test_2d_anchored_from_latest():
    """2 日 K 线从最新一根锚定：末根收盘恒为最新日线收盘，且相位不随行数奇偶漂移。"""
    for n in (20, 21):  # 覆盖奇偶两种行数
        close = _make_close(n=n)
        s2 = macd_mod._prepare(close, "2d")
        # 末根 2 日 K 线的收盘必须等于最新一根日线收盘（今日单独成桶）
        assert abs(float(s2.iloc[-1]) - float(close.iloc[-1])) < 1e-9, n
        assert s2.index[-1] == close.index[-1], n
        # 倒数第二根覆盖「前 2 个交易日」{-2,-3}，其收盘取较新那天（close.iloc[-2]）
        assert abs(float(s2.iloc[-2]) - float(close.iloc[-2])) < 1e-9, n
    print("PASS test_2d_anchored_from_latest")


if __name__ == "__main__":
    test_reference_alignment()
    test_period_construction()
    test_2d_anchored_from_latest()
    print("test_macd OK")
