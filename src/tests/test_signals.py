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


def test_build_signal_passthrough_target_position():
    """build_signal 只透传策略层 target_position，不据 MACD 重新推导。"""
    close = pd.Series([1, 2, 3, 4, 5, 6], index=pd.bdate_range("2024-01-01", periods=6))
    d = macd_mod.compute(close, "daily")
    sig = signal_mod.build_signal(
        "测试", "X", d, d, d, role="target",
        bull_status="NON_BULL", target_position="TARGET_CASH", strategy_reason="重放",
    )
    # 即使 MACD 上行（status 可能 BUY），target_position 仍为策略层给的 TARGET_CASH
    assert sig.target_position == "TARGET_CASH"
    assert sig.bull_status == "NON_BULL"
    assert sig.is_target is True
    print("PASS test_build_signal_passthrough_target_position")


def test_missing_signal_role_aware():
    """目标标的失败→target_position=UNKNOWN；观察标的失败不设 target_position。"""
    t = signal_mod.missing_signal("目标", "X", role="target")
    assert t.target_position == "UNKNOWN" and t.bull_status == "UNKNOWN"
    o = signal_mod.missing_signal("观察", "Y", role="observe")
    assert o.target_position == "" and o.is_target is False
    print("PASS test_missing_signal_role_aware")


if __name__ == "__main__":
    test_judge()
    test_periodmacd_trend()
    test_build_and_missing()
    test_build_signal_passthrough_target_position()
    test_missing_signal_role_aware()
    print("test_signals OK")
