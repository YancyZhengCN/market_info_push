"""策略层测试：增强版事件 / 牛市判定 / 目标仓位历史重放（三者可独立测试、结果确定）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import strategy as st


# ---------------------------------------------------------------------------
# 目标仓位历史重放（纯字符串事件/状态输入，覆盖状态机全部分支）
# ---------------------------------------------------------------------------
def _replay(events, bulls):
    idx = pd.RangeIndex(len(events))
    return list(st.replay_target_position(pd.Series(events, index=idx), pd.Series(bulls, index=idx)))


def test_replay_bull_always_hold():
    # 牛市状态始终输出 TARGET_HOLD，即使增强版为 SELL
    assert _replay(["SELL", "SELL"], ["BULL", "BULL"]) == ["TARGET_HOLD", "TARGET_HOLD"]


def test_replay_non_bull_transitions():
    assert _replay(["BUY"], ["NON_BULL"]) == ["TARGET_HOLD"]
    assert _replay(["SELL"], ["NON_BULL"]) == ["TARGET_CASH"]
    # 非牛市 HOLD 继承此前状态
    assert _replay(["BUY", "HOLD", "HOLD"], ["NON_BULL"] * 3) == ["TARGET_HOLD"] * 3
    assert _replay(["SELL", "HOLD"], ["NON_BULL"] * 2) == ["TARGET_CASH", "TARGET_CASH"]


def test_replay_unknown_start_holds_unknown():
    # 起始为 UNKNOWN 且只有 HOLD → 仍为 UNKNOWN
    assert _replay(["HOLD", "HOLD"], ["NON_BULL", "NON_BULL"]) == ["UNKNOWN", "UNKNOWN"]


def test_replay_bull_exit_applies_enhanced_same_day():
    # 从牛市退出当天立即应用增强版事件
    assert _replay(["BUY", "SELL"], ["BULL", "NON_BULL"]) == ["TARGET_HOLD", "TARGET_CASH"]
    assert _replay(["BUY", "HOLD"], ["BULL", "NON_BULL"]) == ["TARGET_HOLD", "TARGET_HOLD"]


def test_replay_missing_skips_without_changing_state():
    # 牛市 UNKNOWN 或 增强版 ERROR：当日不改变状态
    assert _replay(["BUY", "SELL", "HOLD"], ["NON_BULL", "UNKNOWN", "NON_BULL"]) == [
        "TARGET_HOLD", "TARGET_HOLD", "TARGET_HOLD",
    ]
    assert _replay(["BUY", "ERROR", "SELL"], ["NON_BULL"] * 3) == [
        "TARGET_HOLD", "TARGET_HOLD", "TARGET_CASH",
    ]


def test_replay_deterministic():
    events = ["HOLD", "BUY", "HOLD", "SELL", "HOLD"]
    bulls = ["NON_BULL", "NON_BULL", "BULL", "NON_BULL", "NON_BULL"]
    assert _replay(events, bulls) == _replay(events, bulls)


# ---------------------------------------------------------------------------
# 增强版事件（用可控收盘序列驱动 evaluate_enhanced 的末日事件）
# ---------------------------------------------------------------------------
def _series_last_event(close: pd.Series) -> str:
    return st.evaluate_enhanced(close).iloc[-1].event


def test_enhanced_error_when_history_insufficient():
    # 仅 1 个交易日：ΔBAR₂D 无法计算 → ERROR
    close = pd.Series([100.0], index=pd.bdate_range("2026-01-01", periods=1))
    assert _series_last_event(close) == st.EV_ERROR


def test_enhanced_sell_on_negative_delta():
    # 末日 2 日 BAR 明显走弱 → ΔBAR₂D<0 → SELL（不依赖周线）
    n = 400
    dates = pd.bdate_range(end="2026-09-18", periods=n)
    vals = np.linspace(100, 200, n)
    vals[-1] = vals[-2] - 20  # 末日大跌，压低 2 日 BAR
    close = pd.Series(vals, index=dates)
    assert _series_last_event(close) == st.EV_SELL


def test_enhanced_no_buy_without_sigma():
    # σ20 需要 min_periods(=10) 个 ΔBAR₂D 样本；n=10 时非空样本仅 9 个 → σ20 缺失，
    # 即使动量向上也不得出 BUY。
    n = 10
    dates = pd.bdate_range(end="2026-09-18", periods=n)
    close = pd.Series(np.linspace(100, 130, n), index=dates)
    dec = st.evaluate_enhanced(close).iloc[-1]
    assert dec.sigma20 is None, f"预期 σ20 缺失，实际 {dec.sigma20}"
    assert dec.event != st.EV_BUY


def test_enhanced_event_matrix():
    """用纯判定函数覆盖改造说明「增强版」测试矩阵（threshold 直接给定，只验分支逻辑）。"""
    c = st._classify_enhanced_event
    thr, sig = 1.0, 2.5
    # 周BAR上升 + ΔBAR₂D 严格大于阈值 → BUY
    assert c(1.5, sig, thr, 5.0, 4.0)[0] == st.EV_BUY
    # 周BAR持平 + ΔBAR₂D 严格大于阈值 → BUY（>= 视为未恶化）
    assert c(1.5, sig, thr, 4.0, 4.0)[0] == st.EV_BUY
    # 周BAR下降：即使 ΔBAR₂D 超阈值 → HOLD（不放行买入）
    assert c(1.5, sig, thr, 3.0, 4.0)[0] == st.EV_HOLD
    # ΔBAR₂D 等于阈值（非严格大于）→ HOLD
    assert c(1.0, sig, thr, 5.0, 4.0)[0] == st.EV_HOLD
    # ΔBAR₂D < 0 → SELL（不依赖周线）
    assert c(-0.1, sig, thr, 3.0, 4.0)[0] == st.EV_SELL
    # σ20 缺失（threshold=None）：即使动量向上也不得 BUY → HOLD
    assert c(1.5, None, None, 5.0, 4.0)[0] == st.EV_HOLD
    # ΔBAR₂D 缺失 → ERROR
    assert c(None, sig, thr, 5.0, 4.0)[0] == st.EV_ERROR
    # 卖出不依赖周BAR：周BAR 缺失时 ΔBAR₂D<0 仍 SELL
    assert c(-2.0, sig, thr, None, None)[0] == st.EV_SELL


def test_enhanced_decision_fields_present():
    n = 300
    dates = pd.bdate_range(end="2026-09-18", periods=n)
    vals = 100 + 5 * np.sin(np.arange(n) / 6.0) + np.random.default_rng(1).normal(0, 1, n).cumsum() * 0.5
    close = pd.Series(vals, index=dates)
    dec = st.evaluate_enhanced(close).iloc[-1]
    assert dec.event in (st.EV_BUY, st.EV_SELL, st.EV_HOLD, st.EV_ERROR)
    # 阈值 = 0.4 × σ20（若 σ20 存在）
    if dec.sigma20 is not None:
        assert abs(dec.threshold - 0.4 * dec.sigma20) < 1e-9


# ---------------------------------------------------------------------------
# 牛市判定
# ---------------------------------------------------------------------------
def test_bull_unknown_when_history_insufficient():
    # 已完成周线不足 slope+1 根 → UNKNOWN（不得默认非牛市）
    close = pd.Series(np.linspace(100, 110, 20), index=pd.bdate_range("2026-01-01", periods=20))
    assert st.evaluate_bull_market(close).iloc[-1].status == st.UNKNOWN


def test_bull_true_on_strong_uptrend():
    # 长期强上行：末日已完成周收盘远高于 EMA50 缓冲线且 EMA50 上行 → BULL
    n = 500
    dates = pd.bdate_range(end="2026-09-18", periods=n)
    close = pd.Series(np.linspace(100, 300, n), index=dates)
    dec = st.evaluate_bull_market(close).iloc[-1]
    assert dec.status == st.BULL
    assert dec.ema50 is not None and dec.ema50_8w_ago is not None
    assert dec.weekly_close_completed > dec.ema50 * 1.02


def test_bull_false_on_downtrend():
    # 长期下行：周收盘低于 EMA50 缓冲线 → NON_BULL
    n = 500
    dates = pd.bdate_range(end="2026-09-18", periods=n)
    close = pd.Series(np.linspace(300, 100, n), index=dates)
    assert st.evaluate_bull_market(close).iloc[-1].status == st.NON_BULL


def test_bull_boundary_strict_gt():
    # 常数序列：周收盘 == EMA50（buffer 后更高），且 EMA50 无斜率 → NON_BULL（严格大于）
    n = 500
    dates = pd.bdate_range(end="2026-09-18", periods=n)
    close = pd.Series(np.full(n, 100.0), index=dates)
    dec = st.evaluate_bull_market(close).iloc[-1]
    assert dec.status == st.NON_BULL


# ---------------------------------------------------------------------------
# 组合：decide_target_position 确定性
# ---------------------------------------------------------------------------
def test_decide_deterministic_and_valid_state():
    n = 500
    dates = pd.bdate_range(end="2026-09-18", periods=n)
    vals = 100 + 5 * np.sin(np.arange(n) / 6.0) + np.random.default_rng(7).normal(0, 1, n).cumsum() * 0.5
    close = pd.Series(vals, index=dates)
    d1 = st.decide_target_position(close)
    d2 = st.decide_target_position(close)
    assert d1.state == d2.state
    assert d1.state in (st.TARGET_HOLD, st.TARGET_CASH, st.UNKNOWN)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_strategy OK")
