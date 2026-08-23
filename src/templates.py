"""Markdown 渲染（推送内容）。买入/卖出两块以表格展示日/2日/周 MACD 柱值+趋势箭头+前周期值。"""
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


_TABLE_HEADER = [
    "| 标的 | 价格 | 日 | 2日 | 周 |",
    "|:---:|:---:|:---:|:---:|:---:|",
]


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


def _emphasize(text: str) -> str:
    """高亮判定依据列：用 markdown 加粗（Server酱不支持 HTML 颜色标签，故不标红）。"""
    return f"**{text}**"


def _table_row(r: Signal) -> str:
    # 判定依据周期对应列加粗，其余列正常
    basis = r.basis_attr  # daily / p2d / weekly
    cells = {
        "daily": _fmt_cell(r.daily),
        "p2d": _fmt_cell(r.p2d),
        "weekly": _fmt_cell(r.weekly),
    }
    if basis in cells:
        cells[basis] = _emphasize(cells[basis])
    return (
        f"| {r.name} | {_fmt_price(r.price, r.pct_change)} | "
        f"{cells['daily']} | {cells['p2d']} | {cells['weekly']} |"
    )


def _table(results: list[Signal]) -> list[str]:
    """把一组信号渲染成 markdown 表格（含表头）。"""
    return [*_TABLE_HEADER, *(_table_row(r) for r in results)]


def render(results: list[Signal], date: str, hour: int | None = None) -> str:
    buy = [r for r in results if r.status == "BUY"]
    sell = [r for r in results if r.status == "SELL"]
    other = [r for r in results if r.status in ("HOLD", "MISSING")]

    # 按北京时间当前小时决定时段（上午/中午/下午）；hour 可显式传入便于测试
    if hour is None:
        hour = dt.datetime.now(_CST).hour
    session = _session_label(hour)

    lines = [
        f"# 📊 指数MACD信号{session}报 ({date})",
        "> 判定规则：根据日/2日/周MACD识别买入或卖出",
        "",
    ]

    lines.append("## 🟢 今日买入信号")
    lines.append("")
    if buy:
        lines.extend(_table(buy))
    else:
        lines.append("- 无")

    lines.append("")
    lines.append("## 🔴 今日卖出信号")
    lines.append("")
    if sell:
        lines.extend(_table(sell))
    else:
        lines.append("- 无")

    # 仅在存在未触发/数据缺失标的时才展示该分块
    if other:
        lines.append("")
        lines.append("## — 未触发 / 数据缺失")
        for r in other:
            if r.status == "MISSING":
                lines.append(f"- **{r.name}** ({r.ts_code})：数据缺失（取数失败，不参与判定）")
            else:
                lines.append(f"- **{r.name}** ({r.ts_code})：日MACD {_fmt_period(r.daily)} ｜ 2日MACD {_fmt_period(r.p2d)} ｜ 周MACD {_fmt_period(r.weekly)}")

    lines.extend(
        [
            "",
            "## 📌 备注",
            "- 表格中**加粗**的那一列是该标的的**判定依据**周期（日/2日/周 MACD）",
            "- 判定依据周期的 MACD柱较上一周期变多→买入、变少→卖出、持平→未触发；其余周期仅展示",
            "- 本信号仅供参考，不构成投资建议",
        ]
    )
    return "\n".join(lines)
