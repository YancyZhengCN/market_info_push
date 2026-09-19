"""信号判定：按标的的 basis 周期（日/2日/周）MACD 柱(BAR) 较上一周期变多 → 买入；变少 → 卖出；持平 → 未触发。

basis 默认 daily；未作判定的周期仅展示。
"""
from __future__ import annotations

from dataclasses import dataclass

import macd as macd_mod

PREV_LABEL = {"daily": "前1日", "2d": "前2日", "weekly": "前1周"}
BASIS_ATTR = {"daily": "daily", "2d": "p2d", "weekly": "weekly"}  # basis -> Signal 字段名


@dataclass
class PeriodMACD:
    bar: float | None
    bar_prev: float | None
    prev_label: str = ""

    @property
    def trend(self) -> str:
        """↑ 柱变多 / ↓ 柱变少 / — 持平或缺失"""
        if self.bar is None or self.bar_prev is None:
            return "—"
        if self.bar > self.bar_prev:
            return "↑"
        if self.bar < self.bar_prev:
            return "↓"
        return "—"


@dataclass
class Signal:
    name: str
    ts_code: str
    status: str  # BUY | SELL | HOLD | MISSING（观察标的沿用；目标仓位标的以 target_position 为准）
    daily: PeriodMACD
    p2d: PeriodMACD
    weekly: PeriodMACD
    price: float | None = None  # 最新收盘价（取数序列末值）
    pct_change: float | None = None  # 当天涨跌幅(%)：(最新收盘 - 前一日收盘)/前一日收盘×100
    basis: str = "daily"        # 判定依据周期：daily / 2d / weekly
    role: str = "target"        # 标的角色：target（目标仓位）/ observe（仅观察）
    # ---- 牛市增强目标仓位（仅 target 标的有效；observe 标的留空） ----
    bull_status: str = ""       # BULL / NON_BULL / UNKNOWN
    target_position: str = ""   # TARGET_HOLD / TARGET_CASH / UNKNOWN
    strategy_reason: str = ""   # 目标仓位判定原因（日志/说明用）
    bull_reason: str = ""       # 牛市判定原因（日志/说明用）

    @property
    def basis_attr(self) -> str:
        """判定所用周期对应的 PeriodMACD 字段名（daily/p2d/weekly），供渲染层高亮。"""
        return BASIS_ATTR.get(self.basis, "daily")

    @property
    def is_target(self) -> bool:
        return self.role == "target"


def judge(bar: float | None, bar_prev: float | None) -> str:
    if bar is None:
        return "MISSING"
    if bar_prev is None:
        return "HOLD"  # 数据不足以判定，按未触发处理
    if bar > bar_prev:
        return "BUY"
    if bar < bar_prev:
        return "SELL"
    return "HOLD"


def build_signal(
    name: str,
    ts_code: str,
    daily: macd_mod.MACDResult,
    p2d: macd_mod.MACDResult,
    weekly: macd_mod.MACDResult,
    price: float | None = None,
    basis: str = "daily",
    pct_change: float | None = None,
    role: str = "target",
    bull_status: str = "",
    target_position: str = "",
    strategy_reason: str = "",
    bull_reason: str = "",
) -> Signal:
    """组装单标的展示对象。

    - 观察标的（role=observe）沿用 basis MACD 柱变化的 BUY/SELL/HOLD/MISSING 语义。
    - 目标仓位标的（role=target）的分组以策略层算出的 `target_position` 为准，
      本函数**不**据 MACD 重新推导 target_position（只透传策略层结果）。
    """
    # 按 basis 选定判定周期（默认日线）——保留原有 status 语义供观察标的与调试使用
    basis_result = {"daily": daily, "2d": p2d, "weekly": weekly}.get(basis, daily)
    status = "MISSING" if basis_result.bar is None else judge(basis_result.bar, basis_result.bar_prev)
    return Signal(
        name=name,
        ts_code=ts_code,
        status=status,
        daily=PeriodMACD(daily.bar, daily.bar_prev, PREV_LABEL["daily"]),
        p2d=PeriodMACD(p2d.bar, p2d.bar_prev, PREV_LABEL["2d"]),
        weekly=PeriodMACD(weekly.bar, weekly.bar_prev, PREV_LABEL["weekly"]),
        price=price,
        pct_change=pct_change,
        basis=basis,
        role=role,
        bull_status=bull_status,
        target_position=target_position,
        strategy_reason=strategy_reason,
        bull_reason=bull_reason,
    )


def missing_signal(name: str, ts_code: str, basis: str = "daily", role: str = "target") -> Signal:
    return Signal(
        name=name,
        ts_code=ts_code,
        status="MISSING",
        daily=PeriodMACD(None, None, PREV_LABEL["daily"]),
        p2d=PeriodMACD(None, None, PREV_LABEL["2d"]),
        weekly=PeriodMACD(None, None, PREV_LABEL["weekly"]),
        basis=basis,
        role=role,
        # 取数/计算失败：目标仓位标的进未触发；observe 标的进观察失败
        bull_status="UNKNOWN" if role == "target" else "",
        target_position="UNKNOWN" if role == "target" else "",
        strategy_reason="取数或计算失败",
        bull_reason="",
    )
