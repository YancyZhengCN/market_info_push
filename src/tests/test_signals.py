"""信号判定测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import macd as macd_mod
import signals as signal_mod


def test_judge():
    assert signal_mod.judge(1.0, 0.5) == "BUY"
    assert signal_mod.judge(0.5, 1.0) == "SELL"
    assert signal_mod.judge(0.5, 0.5) == "HOLD"
    assert signal_mod.judge(None, 0.5) == "MISSING"
    assert signal_mod.judge(0.5, None) == "HOLD"
    print("PASS test_judge")


def test_periodmacd_trend():
    assert signal_mod.PeriodMACD(0.88, 0.66, "前1日").trend == "↑"
    assert signal_mod.PeriodMACD(-0.36, -0.30, "前1日").trend == "↓"
    assert signal_mod.PeriodMACD(None, None, "前1日").trend == "—"
    print("PASS test_periodmacd_trend")


def test_build_and_missing():
    close = pd.Series([1, 2, 3, 4, 5, 6], index=pd.bdate_range("2024-01-01", periods=6))
    d = macd_mod.compute(close, "daily")
    sig = signal_mod.build_signal("测试", "X", d, d, d)
    assert sig.status in ("BUY", "SELL", "HOLD", "MISSING")
    miss = signal_mod.missing_signal("缺失", "Y")
    assert miss.status == "MISSING"
    print("PASS test_build_and_missing")


if __name__ == "__main__":
    test_judge()
    test_periodmacd_trend()
    test_build_and_missing()
    print("test_signals OK")
