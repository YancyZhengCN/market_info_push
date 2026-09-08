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
    """无相位锚点（ts_code=None）时回退「末根单独」：末根收盘恒为最新日线收盘，相位不随行数奇偶漂移。"""
    for n in (20, 21):  # 覆盖奇偶两种行数
        close = _make_close(n=n)
        s2 = macd_mod._prepare(close, "2d")
        # 末根 2 日 K 线的收盘必须等于最新一根日线收盘（今日单独成桶）
        assert abs(float(s2.iloc[-1]) - float(close.iloc[-1])) < 1e-9, n
        assert s2.index[-1] == close.index[-1], n
        # 倒数第二根覆盖「前 2 个交易日」{-2,-3}，其收盘取较新那天（close.iloc[-2]）
        assert abs(float(s2.iloc[-2]) - float(close.iloc[-2])) < 1e-9, n
    print("PASS test_2d_anchored_from_latest")


def test_2d_phase_anchor_pairing():
    """相位锚点决定末根「配对/单独」，逐日不随行数奇偶漂移，逐值对齐东方财富。"""
    # 构造一段确定的日频序列，锚点日在序列中部（保证去掉末行后锚点仍在窗口内）
    dates = pd.bdate_range(end="2026-09-11", periods=44)  # 覆盖锚点日 09-07 及其后若干交易日
    close = pd.Series(np.arange(len(dates), dtype=float) + 100.0, index=dates)
    ts = "000300.SH"
    anchor_date, anchor_parity = macd_mod._2D_PHASE_ANCHOR[ts]
    assert pd.Timestamp(anchor_date) in close.index  # 锚点须在窗口内

    # 相位随交易日步数翻转：去掉末行（往前 1 个交易日）后配对判定应取反
    assert macd_mod._last_is_paired(close.iloc[:-1], ts) != macd_mod._last_is_paired(close, ts)

    # 序列末行恰为锚点日时：_last_is_paired 应等于 anchor_parity==1
    at_anchor = close.loc[:anchor_date]
    assert macd_mod._last_is_paired(at_anchor, ts) == (anchor_parity == 1)

    # 无锚点标的回退「末根单独」（不配对）
    assert macd_mod._last_is_paired(close, "UNKNOWN.XX") is False

    # 2d 末根收盘恒为最新日线收盘；末根配对时倒数第二根 = 往前第 3 根（[-3,-4] 组取较新的 -3）
    s2 = macd_mod._prepare(close, "2d", ts)
    assert abs(float(s2.iloc[-1]) - float(close.iloc[-1])) < 1e-9
    if macd_mod._last_is_paired(close, ts):
        assert abs(float(s2.iloc[-2]) - float(close.iloc[-3])) < 1e-9
    print("PASS test_2d_phase_anchor_pairing")


if __name__ == "__main__":
    test_reference_alignment()
    test_period_construction()
    test_2d_anchored_from_latest()
    test_2d_phase_anchor_pairing()
    print("test_macd OK")
