"""Markdown 渲染（推送内容）。

买入/卖出两块按**目标仓位**分组，以表格展示牛市状态 + 价格 + 日/2日/周 MACD（柱值+箭头+前周期值）。
- 目标仓位标的（role=target）：TARGET_HOLD→买入表、TARGET_CASH→卖出表、UNKNOWN/失败→未触发。
- 观察标的（role=observe）：单独「观察指标」表，只展示价格与日/2日/周 MACD，不参与买卖分组。
价格/MACD/括号/箭头/粗体/两位小数格式化沿用本模块既有函数，保持线上卡片现状不变。
"""
from __future__ import annotations

import datetime as dt

from signals import PeriodMACD, Signal

# 固定东八区，避免云函数默认 UTC 导致时段判断偏差 8 小时
_CST = dt.timezone(dt.timedelta(hours=8))


def _session_label(hour: int) -> str:
    """按北京时间小时给出时段：<11 上午 | 11~13 中午 | >=13 下午。"""
    if hour < 11:
        return "上午"
    if hour < 13:
        return "中午"
    return "下午"


def _fmt_period(m: PeriodMACD) -> str:
    if m.bar is None or m.bar_prev is None:
        return "—"
    return f"{m.bar:.2f}{m.trend}({m.prev_label}{m.bar_prev:.2f})"


def _fmt_cell(m: PeriodMACD) -> str:
    """表格单元格：当前值+箭头（前周期值），如 0.88↑（0.66）。

    Server酱不支持 <br> 换行，故省去前值标签、只保留括号内前值以缩短单元格宽度，
    使 MACD 列更窄、标的列相对更宽。括号用**全角**：全角括号属 CJK 字符、提供换行断点，
    单元格可自然折成两行更窄，避免整表超出手机屏宽（半角 () 连成 ASCII 串不易断行会撑宽）。
    """
    if m.bar is None or m.bar_prev is None:
        return "—"
    return f"{m.bar:.2f}{m.trend}（{m.bar_prev:.2f}）"


# 买入/卖出表：标的后新增「牛市」列，其余列整体后移、相对顺序不变（改造说明「买入表/卖出表」）
_SIGNAL_TABLE_HEADER = [
    "| 标的 | 牛市 | 价格 | 日 | 2日 | 周 |",
    "|:---:|:---:|:---:|:---:|:---:|:---:|",
]

# 观察指标表：保持线上现状，不增加「牛市」列
_OBSERVE_TABLE_HEADER = [
    "| 标的 | 价格 | 日 | 2日 | 周 |",
    "|:---:|:---:|:---:|:---:|:---:|",
]

# 未触发（失败）表：至少展示 标的 | 原因
_FAILURE_TABLE_HEADER = [
    "| 标的 | 原因 |",
    "|:---:|:---:|",
]

# 牛市列图标
_BULL_ICON = {"BULL": "✅", "NON_BULL": "❌"}


def _fmt_price(price: float | None, pct_change: float | None = None) -> str:
    """价格单元格：价格（涨跌%），如 4618.90（+0.35%）。

    括号用全角（CJK 提供换行断点，窄屏可折行不撑宽，与 _fmt_cell 一致）；
    涨跌带正负号，缺失时只显示价格、无括号。
    """
    if price is None:
        return "—"
    if pct_change is None:
        return f"{price:.2f}"
    return f"{price:.2f}（{pct_change:+.2f}%）"


def _macd_cells(r: Signal) -> dict[str, str]:
    """返回 daily/p2d/weekly 三列 MACD 单元格文本。

    注：目标仓位改造后卡片不再按 basis 高亮判定列（basis 字段仍保留在配置中，后续可能启用）。
    """
    return {
        "daily": _fmt_cell(r.daily),
        "p2d": _fmt_cell(r.p2d),
        "weekly": _fmt_cell(r.weekly),
    }


def _signal_row(r: Signal) -> str:
    """买入/卖出行：标的 | 牛市 | 价格 | 日 | 2日 | 周。"""
    cells = _macd_cells(r)
    bull = _BULL_ICON.get(r.bull_status, "—")
    return (
        f"| {r.name} | {bull} | {_fmt_price(r.price, r.pct_change)} | "
        f"{cells['daily']} | {cells['p2d']} | {cells['weekly']} |"
    )


def _observe_row(r: Signal) -> str:
    """观察行：标的 | 价格 | 日 | 2日 | 周（无牛市列）。"""
    cells = _macd_cells(r)
    return (
        f"| {r.name} | {_fmt_price(r.price, r.pct_change)} | "
        f"{cells['daily']} | {cells['p2d']} | {cells['weekly']} |"
    )


def _signal_table(results: list[Signal]) -> list[str]:
    return [*_SIGNAL_TABLE_HEADER, *(_signal_row(r) for r in results)]


def _observe_table(results: list[Signal]) -> list[str]:
    return [*_OBSERVE_TABLE_HEADER, *(_observe_row(r) for r in results)]


def _failure_reason(r: Signal) -> str:
    """未触发原因：优先用策略层原因；观察标的/无原因时回退数据缺失说明。"""
    if r.status == "MISSING":
        return r.strategy_reason or "数据缺失（取数或计算失败）"
    if r.is_target and r.bull_status == "UNKNOWN":
        return r.strategy_reason or "牛市状态UNKNOWN，历史不足"
    return r.strategy_reason or "历史重放后目标仓位仍为UNKNOWN"


def _failure_table(results: list[Signal]) -> list[str]:
    return [*_FAILURE_TABLE_HEADER, *(f"| {r.name} | {_failure_reason(r)} |" for r in results)]


def _classify(results: list[Signal]) -> tuple[list[Signal], list[Signal], list[Signal], list[Signal]]:
    """把标的分到 买入 / 卖出 / 观察 / 未触发 四组。

    - 目标仓位标的：TARGET_HOLD→买入、TARGET_CASH→卖出、其余（UNKNOWN/MISSING）→未触发。
    - 观察标的：正常→观察表；取数失败(MISSING)→未触发（失败展示）。
    正常增强版 HOLD 已在策略层继承为 TARGET_HOLD/TARGET_CASH，不会落入未触发。
    """
    buy: list[Signal] = []
    sell: list[Signal] = []
    observe: list[Signal] = []
    failed: list[Signal] = []
    for r in results:
        if r.is_target:
            if r.status == "MISSING" or r.target_position not in ("TARGET_HOLD", "TARGET_CASH"):
                failed.append(r)
            elif r.target_position == "TARGET_HOLD":
                buy.append(r)
            else:  # TARGET_CASH
                sell.append(r)
        else:  # observe
            if r.status == "MISSING":
                failed.append(r)
            else:
                observe.append(r)
    return buy, sell, observe, failed


def render(results: list[Signal], date: str, hour: int | None = None) -> str:
    buy, sell, observe, failed = _classify(results)

    # 按北京时间当前小时决定时段（上午/中午/下午）；hour 可显式传入便于测试
    if hour is None:
        hour = dt.datetime.now(_CST).hour
    session = _session_label(hour)

    lines = [
        f"# 📊 指数MACD信号{session}报 ({date})",
        "> 判定规则：牛市保持持仓；非牛市按macd策略增强版判断是否买入",
        "",
    ]

    # 🔴 今日买入信号（目标仓位=TARGET_HOLD，表示当前应该持仓）
    lines.append("## 🔴 今日买入信号")
    lines.append("")
    if buy:
        lines.extend(_signal_table(buy))
    else:
        lines.append("- 无")

    # 🟢 今日卖出信号（目标仓位=TARGET_CASH，表示当前不应该持仓）
    lines.append("")
    lines.append("## 🟢 今日卖出信号")
    lines.append("")
    if sell:
        lines.extend(_signal_table(sell))
    else:
        lines.append("- 无")

    # 观察指标（不参与目标仓位/牛市判断）
    if observe:
        lines.append("")
        lines.append("## 观察指标")
        lines.append("")
        lines.extend(_observe_table(observe))

    # 未触发：仅在存在失败标的时展示（正常 HOLD 不进入此块）
    if failed:
        lines.append("")
        lines.append("## — 未触发")
        lines.append("")
        lines.extend(_failure_table(failed))

    lines.extend(
        [
            "",
            "## 📌 备注",
            "- **买入表**=当前应该持仓，**卖出表**=当前不应该持仓；不表示今天刚发生买入/卖出",
            "- 本信号仅供参考，不构成投资建议",
        ]
    )
    return "\n".join(lines)
