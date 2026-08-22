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
    status: str  # BUY | SELL | HOLD | MISSING
    daily: PeriodMACD
    p2d: PeriodMACD
    weekly: PeriodMACD
    price: float | None = None  # 最新收盘价（取数序列末值）
    basis: str = "daily"        # 判定依据周期：daily / 2d / weekly

    @property
    def basis_attr(self) -> str:
        """判定所用周期对应的 PeriodMACD 字段名（daily/p2d/weekly），供渲染层高亮。"""
        return BASIS_ATTR.get(self.basis, "daily")


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
) -> Signal:
    # 按 basis 选定判定周期（默认日线）
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
        basis=basis,
    )


def missing_signal(name: str, ts_code: str, basis: str = "daily") -> Signal:
    return Signal(
        name=name,
        ts_code=ts_code,
        status="MISSING",
        daily=PeriodMACD(None, None, PREV_LABEL["daily"]),
        p2d=PeriodMACD(None, None, PREV_LABEL["2d"]),
        weekly=PeriodMACD(None, None, PREV_LABEL["weekly"]),
        basis=basis,
    )
