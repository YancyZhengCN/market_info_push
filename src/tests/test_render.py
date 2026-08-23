"""Markdown 渲染测试：验证括号前周期值与分块格式。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals import PeriodMACD, Signal

import templates as templates_mod


def _sig(name, code, status, bar, bp, price=100.0, basis="daily", pct_change=None):
    return Signal(
        name, code, status,
        PeriodMACD(bar, bp, "前1日"),
        PeriodMACD(bar, bp, "前2日"),
        PeriodMACD(bar, bp, "前1周"),
        price=price,
        pct_change=pct_change,
        basis=basis,
    )


def test_render_format():
    results = [
        _sig("沪深300", "000300.SH", "BUY", 0.88, 0.66, price=4618.90, pct_change=0.35),
        _sig("科创50", "000688.SH", "SELL", -0.36, -0.30, price=1653.55, pct_change=-1.20),
        _sig("恒生科技", "HKTECH", "MISSING", None, None),
        _sig("国债", "511260.SH", "HOLD", 0.10, 0.10, price=135.77),
    ]
    md = templates_mod.render(results, "2026-08-22")
    # 买入/卖出块为表格：含表头（标的后加价格列）+ 数据行（单元格无 <br>）
    assert "| 标的 | 价格 | 日 | 2日 | 周 |" in md
    assert "|:---:|:---:|:---:|:---:|:---:|" in md
    # 价格列带涨跌%（全角括号、正负号）
    assert "4618.90（+0.35%）" in md
    assert "1653.55（-1.20%）" in md
    # 无 pct_change 时价格列只显示价格（国债 HOLD 在未触发块的价格另算，此处校验买卖块即可）
    # 默认 basis=daily：日 列单元格被加粗高亮（含 ** 标记）
    assert "**" in md and "0.88↑（0.66）" in md          # 买入行日MACD值存在且有加粗
    assert "1653.55" in md                                # 卖出行价格
    assert "<br>" not in md                               # 确认不再输出 <br>
    # 表格不应再出现旧的列表前缀写法
    assert "- **沪深300**" not in md
    # 未触发/数据缺失仍为列表
    assert "数据缺失" in md
    assert "- **国债** (511260.SH)：" in md
    assert "不构成投资建议" in md
    assert "今日买入信号" in md and "今日卖出信号" in md
    # 判定规则文案已更新
    assert "判定规则：根据日/2日/周MACD识别买入或卖出" in md
    print("=== render 预览 ===")
    print(md)
    print("=== 结束 ===")
    print("PASS test_render_format")


def test_basis_highlight_column():
    """basis 决定高亮列：daily 高亮日MACD，weekly 高亮周MACD。"""
    # weekly basis：周MACD 单元格被加粗，日MACD 不被加粗
    r = _sig("国债ETF", "511260.SH", "SELL", 0.10, 0.20, price=135.0, basis="weekly")
    md = templates_mod.render([r], "2026-08-22")
    # 找到该行，周MACD（第 5 列）应含加粗包裹
    row = [ln for ln in md.splitlines() if ln.startswith("| 国债ETF")][0]
    cells = [c.strip() for c in row.split("|")]
    # cells: ['', 标的, 价格, 日, 2日, 周, '']
    assert "**" in cells[5], f"周MACD 列应高亮: {cells[5]}"     # 判定依据列（周）
    assert "**" not in cells[3], f"日MACD 列不应高亮: {cells[3]}"  # 非判定列
    print("PASS test_basis_highlight_column")


def test_other_section_hidden_when_empty():
    """无未触发/数据缺失标的时，不展示"未触发 / 数据缺失"分块；有则展示。"""
    # 全为买/卖，无 HOLD/MISSING
    only_signals = [
        _sig("沪深300", "000300.SH", "BUY", 0.88, 0.66),
        _sig("科创50", "000688.SH", "SELL", -0.36, -0.30),
    ]
    md = templates_mod.render(only_signals, "2026-08-22")
    assert "未触发 / 数据缺失" not in md

    # 含一个 HOLD → 应出现该分块
    with_other = only_signals + [_sig("国债", "511260.SH", "HOLD", 0.10, 0.10)]
    md2 = templates_mod.render(with_other, "2026-08-22")
    assert "## — 未触发 / 数据缺失" in md2
    print("PASS test_other_section_hidden_when_empty")


def test_session_title():
    """标题按传入 hour 决定时段：<11 上午 | 11~13 中午 | >=13 下午。"""
    sig = [_sig("沪深300", "000300.SH", "BUY", 0.88, 0.66)]
    cases = {
        9: "上午",   # 10:00 触发场景
        10: "上午",
        11: "中午",  # 11:45 触发场景（边界：11 点归中午）
        12: "中午",
        13: "下午",  # 14:30 触发场景（边界：13 点归下午）
        15: "下午",
    }
    for hour, label in cases.items():
        md = templates_mod.render(sig, "2026-08-22", hour=hour)
        assert f"# 📊 指数MACD信号{label}报 (2026-08-22)" in md, f"hour={hour} 期望 {label}"
    print("PASS test_session_title")


if __name__ == "__main__":
    test_render_format()
    test_session_title()
    print("test_render OK")
