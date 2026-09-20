"""Markdown 渲染测试：验证牛市增强目标仓位卡片（颜色/信号列双槽位/分组/格式）与 2026-09-18 黄金样例。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals import PeriodMACD, Signal

import templates as templates_mod


def _sig(
    name, code, bar, bp, price=100.0, basis="daily", pct_change=None,
    role="target", bull_status="", target_position="", enhanced_position="",
    strategy_reason="", status="HOLD",
):
    return Signal(
        name, code, status,
        PeriodMACD(bar, bp, "前1日"),
        PeriodMACD(bar, bp, "前2日"),
        PeriodMACD(bar, bp, "前1周"),
        price=price,
        pct_change=pct_change,
        basis=basis,
        role=role,
        bull_status=bull_status,
        target_position=target_position,
        enhanced_position=enhanced_position,
        strategy_reason=strategy_reason,
    )


def _target(name, code, bull, tp, enh="", bar=0.5, bp=0.3, price=100.0, pct=0.5, basis="2d"):
    return _sig(name, code, bar, bp, price=price, basis=basis, pct_change=pct,
                role="target", bull_status=bull, target_position=tp, enhanced_position=enh)


def test_card_colors_and_headers():
    """买入🔴/卖出🟢；买卖表表头严格为 标的|信号|价格|日|2日|周；判定规则文案更新。"""
    results = [
        _target("沪深300", "000300.SH", "NON_BULL", "TARGET_HOLD", enh="TARGET_HOLD"),
        _target("恒生科技", "HKTECH", "NON_BULL", "TARGET_CASH", enh="TARGET_CASH"),
    ]
    md = templates_mod.render(results, "2026-09-18", hour=15)
    assert "## 🔴 今日买入信号" in md
    assert "## 🟢 今日卖出信号" in md
    assert "| 标的 | 信号 | 价格 | 日 | 2日 | 周 |" in md
    assert "| 标的 | 牛市 | 价格 | 日 | 2日 | 周 |" not in md  # 旧表头不复现
    assert "判定规则：牛市保持持仓；非牛市按macd策略增强版判断是否买入" in md
    assert "# 📊 指数MACD信号下午报 (2026-09-18)" in md
    assert "继续持有" not in md
    # 不再出现旧的 ✅/❌ 图标
    assert "✅" not in md and "❌" not in md
    print("PASS test_card_colors_and_headers")


def test_signal_icon_matrix():
    """信号列双槽位矩阵：🐮/⭕️、🐮/-、-/⭕️、-/-；UNKNOWN 也落 -/-。"""
    cases = [
        ("BULL", "TARGET_HOLD", "🐮/⭕️"),
        ("BULL", "TARGET_CASH", "🐮/-"),
        ("NON_BULL", "TARGET_HOLD", "-/⭕️"),
        ("NON_BULL", "TARGET_CASH", "-/-"),
        ("UNKNOWN", "UNKNOWN", "-/-"),
    ]
    for bull, enh, expected in cases:
        # 用 TARGET_HOLD 保证进买入表可渲染（分组不受信号列影响）
        r = _target("测试", "X.SH", bull, "TARGET_HOLD", enh=enh)
        # 剥离零宽 WORD JOINER 后比对可见内容（WJ 仅用于禁止窄屏换行）
        cell = templates_mod._fmt_strategy_signals(r).replace(templates_mod._WJ, "")
        assert cell == expected, f"bull={bull} enh={enh} 期望 {expected} 实际 {cell}"
    print("PASS test_signal_icon_matrix")


def test_signal_slot_has_word_joiner():
    """信号列用 WORD JOINER 包裹斜杠，禁止窄屏在斜杠处换行。"""
    r = _target("测试", "X.SH", "NON_BULL", "TARGET_HOLD", enh="TARGET_CASH")
    cell = templates_mod._fmt_strategy_signals(r)
    assert templates_mod._WJ in cell
    assert cell == f"-{templates_mod._WJ}/{templates_mod._WJ}-"
    print("PASS test_signal_slot_has_word_joiner")


def test_signal_column_position():
    """信号列位于标的之后（第二列）。"""
    r = _target("科创50", "000688.SH", "BULL", "TARGET_HOLD", enh="TARGET_HOLD")
    md = templates_mod.render([r], "2026-09-18", hour=15)
    row = [ln for ln in md.splitlines() if ln.startswith("| 科创50")][0]
    cells = [c.strip().replace(templates_mod._WJ, "") for c in row.split("|")]
    # cells: ['', 标的, 信号, 价格, 日, 2日, 周, '']
    assert cells[1] == "科创50"
    assert cells[2] == "🐮/⭕️", cells
    print("PASS test_signal_column_position")


def test_grouping_by_target_position():
    """买入表读 TARGET_HOLD、卖出表读 TARGET_CASH；信号列内容不影响分组。"""
    results = [
        # 牛市但增强版独立=CASH（🐮/-）仍按 target_position=HOLD 进买入表
        _target("科创50", "000688.SH", "BULL", "TARGET_HOLD", enh="TARGET_CASH"),
        _target("恒生科技", "HKTECH", "NON_BULL", "TARGET_CASH", enh="TARGET_CASH"),
    ]
    md = templates_mod.render(results, "2026-09-18", hour=15)
    buy_block = md.split("## 🔴 今日买入信号")[1].split("## 🟢")[0]
    sell_block = md.split("## 🟢 今日卖出信号")[1].split("## 📌")[0]
    assert "科创50" in buy_block and "科创50" not in sell_block
    assert "恒生科技" in sell_block and "恒生科技" not in buy_block
    print("PASS test_grouping_by_target_position")


def test_observe_table_no_signal_column():
    """观察表保持 标的|价格|日|2日|周，不增加信号列。"""
    results = [
        _target("沪深300", "000300.SH", "NON_BULL", "TARGET_HOLD", enh="TARGET_HOLD"),
        _sig("十年期国债ETF", "511260.SH", -0.02, -0.02, price=134.72, basis="daily",
             pct_change=0.02, role="observe", status="HOLD"),
    ]
    md = templates_mod.render(results, "2026-09-18", hour=15)
    assert "## 观察指标" in md
    observe_block = md.split("## 观察指标")[1]
    assert "| 标的 | 价格 | 日 | 2日 | 周 |" in observe_block
    assert "| 标的 | 信号 |" not in observe_block
    print("PASS test_observe_table_no_signal_column")


def test_untriggered_only_on_failure():
    """无失败时不渲染未触发；有失败（UNKNOWN/MISSING）时渲染 标的|原因。"""
    ok = [_target("沪深300", "000300.SH", "NON_BULL", "TARGET_HOLD", enh="TARGET_HOLD")]
    md_ok = templates_mod.render(ok, "2026-09-18", hour=15)
    assert "未触发" not in md_ok

    with_fail = ok + [_target("某标的", "X.SH", "UNKNOWN", "UNKNOWN", enh="UNKNOWN")]
    md_fail = templates_mod.render(with_fail, "2026-09-18", hour=15)
    assert "## — 未触发" in md_fail
    assert "| 标的 | 原因 |" in md_fail
    print("PASS test_untriggered_only_on_failure")


def test_notes_include_signal_legend():
    """备注含双槽位说明与⭕️重放语义。"""
    md = templates_mod.render(
        [_target("沪深300", "000300.SH", "BULL", "TARGET_HOLD", enh="TARGET_HOLD")],
        "2026-09-18", hour=15,
    )
    assert "信号固定为“牛市/增强版”" in md
    assert "🐮=牛市条件成立" in md and "⭕️=增强版独立判断当前应持仓" in md
    assert "BUY后显示，HOLD继承原状态，SELL后取消" in md
    print("PASS test_notes_include_signal_legend")


def test_golden_20260918():
    """2026-09-18 线上页面为黄金样例：固化列顺序、信号双槽位、括号、精度、箭头与分组。"""
    def g(name, code, bull, tp, enh, price, pct, d, dp, p2, p2p, w, wp):
        return Signal(
            name, code, "HOLD",
            PeriodMACD(d, dp, "前1日"), PeriodMACD(p2, p2p, "前2日"), PeriodMACD(w, wp, "前1周"),
            price=price, pct_change=pct, basis="2d", role="target",
            bull_status=bull, target_position=tp, enhanced_position=enh,
        )

    def o(name, code, price, pct, d, dp, p2, p2p, w, wp, basis="2d"):
        return Signal(
            name, code, "HOLD",
            PeriodMACD(d, dp, "前1日"), PeriodMACD(p2, p2p, "前2日"), PeriodMACD(w, wp, "前1周"),
            price=price, pct_change=pct, basis=basis, role="observe",
        )

    results = [
        # 沪深300：非牛市但增强版独立=HOLD → 信号 -/⭕️（最终 target_position=HOLD 进买入表）
        g("沪深300", "000300.SH", "NON_BULL", "TARGET_HOLD", "TARGET_HOLD", 4504.84, 1.00, -9.50, -16.70, -14.40, -17.78, -70.81, -70.95),
        # 科创50：牛市 + 增强版独立=HOLD → 🐮/⭕️
        g("科创50", "000688.SH", "BULL", "TARGET_HOLD", "TARGET_HOLD", 1649.79, 2.71, 18.50, 8.78, -9.13, -22.83, -77.39, -87.07),
        g("创业板50", "399673.SZ", "NON_BULL", "TARGET_HOLD", "TARGET_HOLD", 3502.38, 2.13, 13.35, 0.65, -2.63, -16.24, -182.03, -197.11),
        # 港股创新药ETF：牛市但增强版独立=CASH → 🐮/-
        g("港股创新药ETF", "513120.SH", "BULL", "TARGET_HOLD", "TARGET_CASH", 1.29, 0.86, -0.012, -0.023, -0.011, -0.013, 0.04, 0.05),
        g("恒生科技", "HKTECH", "NON_BULL", "TARGET_CASH", "TARGET_CASH", 4400.90, 2.09, -14.84, -34.69, -67.49, -82.87, -10.43, 2.42),
        g("北证50", "899050.BJ", "NON_BULL", "TARGET_CASH", "TARGET_CASH", 1037.36, 1.11, -5.60, -7.62, 4.67, 5.34, -13.98, -17.70),
        o("十年期国债ETF", "511260.SH", 134.72, 0.02, -0.021, -0.024, -0.04, -0.04, 0.04, 0.05, basis="daily"),
        o("黄金9999", "AU9999", 947.59, 1.37, -8.26, -11.06, -0.98, -0.59, 8.96, 9.67),
    ]
    md = templates_mod.render(results, "2026-09-18", hour=15)

    # 表头为信号列
    assert "| 标的 | 信号 | 价格 | 日 | 2日 | 周 |" in md

    # 分组：买入含四个、卖出含两个（信号列不影响分组）
    buy_block = md.split("## 🔴 今日买入信号")[1].split("## 🟢")[0]
    sell_block = md.split("## 🟢 今日卖出信号")[1].split("## 观察指标")[0]
    for nm in ("沪深300", "科创50", "创业板50", "港股创新药ETF"):
        assert nm in buy_block, f"{nm} 应在买入表"
    for nm in ("恒生科技", "北证50"):
        assert nm in sell_block, f"{nm} 应在卖出表"

    # 信号双槽位四种组合都出现（剥离零宽 WJ 后比对可见内容）
    md_visible = md.replace(templates_mod._WJ, "")
    assert "🐮/⭕️" in md_visible   # 科创50
    assert "🐮/-" in md_visible     # 港股创新药ETF
    assert "-/⭕️" in md_visible     # 沪深300
    assert "-/-" in md_visible       # 恒生科技/北证50
    assert "✅" not in md and "❌" not in md

    # 价格括号（全角、正负号、两位小数）
    assert "4504.84（+1.00%）" in md
    assert "1037.36（+1.11%）" in md
    # 不再按 basis 高亮判定列：整卡无加粗 MACD 单元格
    assert "**-14.40↑（-17.78）**" not in md
    assert "-14.40↑（-17.78）" in md
    # 箭头方向
    assert "-9.50↑（-16.70）" in md
    assert "-10.43↓（2.42）" in md
    # 观察表无信号列
    observe_block = md.split("## 观察指标")[1]
    assert "134.72（+0.02%）" in observe_block
    assert "| 标的 | 价格 | 日 | 2日 | 周 |" in observe_block
    # 当天无失败 → 无未触发块
    assert "未触发" not in md
    assert "继续持有" not in md
    print("=== 9-18 黄金样例渲染 ===")
    print(md)
    print("PASS test_golden_20260918")


def test_session_title():
    """标题按传入 hour 决定时段：<11 上午 | 11~13 中午 | >=13 下午。"""
    sig = [_target("沪深300", "000300.SH", "NON_BULL", "TARGET_HOLD", enh="TARGET_HOLD")]
    cases = {9: "上午", 10: "上午", 11: "中午", 12: "中午", 13: "下午", 15: "下午"}
    for hour, label in cases.items():
        md = templates_mod.render(sig, "2026-08-22", hour=hour)
        assert f"# 📊 指数MACD信号{label}报 (2026-08-22)" in md, f"hour={hour} 期望 {label}"
    print("PASS test_session_title")


if __name__ == "__main__":
    test_card_colors_and_headers()
    test_signal_icon_matrix()
    test_signal_column_position()
    test_grouping_by_target_position()
    test_observe_table_no_signal_column()
    test_untriggered_only_on_failure()
    test_notes_include_signal_legend()
    test_golden_20260918()
    test_session_title()
    print("test_render OK")
