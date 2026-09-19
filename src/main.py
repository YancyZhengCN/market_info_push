"""编排入口：交易日判断 → 逐标的采集 → MACD → 信号 → 渲染 → 推送。

本地运行：  python main.py            （需同级 .env 或环境变量；无 token 自动走合成数据）
云函数入口：main_handler(event, context)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import config as config_mod
import macd as macd_mod
import notifier as notifier_mod
import signals as signal_mod
import strategy as strategy_mod
import templates as templates_mod
import tushare_client as ts_client

logger = logging.getLogger("index_signal")

# 取数以网络 IO 为主，用线程池并发拉取多标的（GIL 不阻塞 IO 等待）；
# 上限取标的数与 8 的较小值，避免对数据源发起过多并发连接。
_MAX_WORKERS = 8


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _process_index(idx: config_mod.IndexConfig, cfg: config_mod.Config, pro, today_is_trading: bool = True) -> signal_mod.Signal:
    """单标的处理：取数 → MACD →（目标仓位标的再跑策略）→ 信号。

    - 观察标的（role=observe）：沿用原路径，仅展示价格与日/2日/周MACD。
    - 目标仓位标的（role=target）：额外计算增强版事件、牛市状态并按历史重放目标仓位，
      分组以 target_position 为准（不再用当日 MACD 柱变化直接判买卖）。
    - today_is_trading=False（非交易日强跑预览）：取数层不拼接实时价，直接用上一交易日收盘。
    单标的失败返回 MISSING（target→未触发 / observe→观察失败），不阻塞其余。
    """
    try:
        close = ts_client.get_close(idx, cfg, pro, today_is_trading)
        d = macd_mod.compute(close, "daily", idx.ts_code)
        p2 = macd_mod.compute(close, "2d", idx.ts_code)
        w = macd_mod.compute(close, "weekly", idx.ts_code)
        price = float(close.iloc[-1]) if len(close) else None
        # 当天涨跌幅(%)：(最新收盘 - 前一日收盘) / 前一日收盘 × 100
        pct_change = None
        if len(close) >= 2:
            prev_close = float(close.iloc[-2])
            if prev_close:
                pct_change = (float(close.iloc[-1]) - prev_close) / prev_close * 100

        # 目标仓位标的：跑牛市增强策略并按历史重放目标仓位
        bull_status = target_position = strategy_reason = bull_reason = ""
        if idx.is_target:
            decision = strategy_mod.decide_target_position(close)
            bull_status = decision.bull.status
            target_position = decision.state
            strategy_reason = decision.reason
            bull_reason = decision.bull.reason
            _log_strategy(idx, date_of(close), decision)

        sig = signal_mod.build_signal(
            idx.name, idx.ts_code, d, p2, w, price, idx.basis, pct_change,
            role=idx.role,
            bull_status=bull_status,
            target_position=target_position,
            strategy_reason=strategy_reason,
            bull_reason=bull_reason,
        )
        logger.info(
            "标的 %s → status=%s target=%s bull=%s (判定周期 %s | 日BAR %.4f / 前1日 %.4f)",
            idx.name,
            sig.status,
            target_position or "-",
            bull_status or "-",
            idx.basis,
            d.bar if d.bar is not None else float("nan"),
            d.bar_prev if d.bar_prev is not None else float("nan"),
        )
        return sig
    except Exception as e:  # 单标的失败不阻塞其余
        logger.error("标的 %s 处理失败: %s", idx.name, e)
        return signal_mod.missing_signal(idx.name, idx.ts_code, idx.basis, role=idx.role)


def date_of(close) -> str:
    """取收盘序列末日字符串，仅用于日志。"""
    try:
        return close.index[-1].strftime("%Y-%m-%d")
    except Exception:
        return "-"


def _log_strategy(idx: config_mod.IndexConfig, date_str: str, decision) -> None:
    """记录目标仓位标的的策略明细（用于解释分组，不进入微信表格）。"""
    enh = decision.enhanced
    bull = decision.bull

    def _f(x):
        return f"{x:.4f}" if isinstance(x, (int, float)) else "NA"

    logger.info(
        "[策略] %s %s | 增强版事件=%s 目标仓位=%s 牛市=%s | "
        "ΔBAR2D=%s σ20=%s 0.4σ20=%s 已完成周BAR=%s 前一已完成周BAR=%s | "
        "已完成周收盘=%s EMA50=%s 8周前EMA50=%s | 原因: %s / %s",
        idx.name, date_str,
        enh.event, decision.state, bull.status,
        _f(enh.delta_bar_2d), _f(enh.sigma20), _f(enh.threshold),
        _f(enh.weekly_bar_completed), _f(enh.weekly_bar_completed_prev),
        _f(bull.weekly_close_completed), _f(bull.ema50), _f(bull.ema50_8w_ago),
        decision.reason, bull.reason,
    )


def run(cfg: config_mod.Config) -> int:
    today = dt.date.today()
    date_str = today.strftime("%Y-%m-%d")
    logger.info("运行日期 %s | 标的数 %d | demo=%s | push=%s | source=%s", date_str, len(cfg.indices), cfg.demo, cfg.push_enabled, cfg.data_source)

    # 交易日过滤（演示模式 / FORCE_RUN 跳过，便于任意日期预览与调试）
    force_run = os.getenv("FORCE_RUN", "false").lower() == "true"
    today_is_trading = cfg.demo or ts_client.is_trading_day(today, cfg.tushare_token, cfg.data_source)
    if not cfg.demo and not force_run and not today_is_trading:
        logger.info("非交易日，跳过推送")
        return 0
    if force_run:
        logger.info("FORCE_RUN=true，跳过交易日判断")
    if not today_is_trading:
        # 非交易日强跑（FORCE_RUN 预览）：不拼接实时价，用上一交易日收盘
        logger.info("今天非交易日：数据使用上一交易日收盘（不拼接实时价）")

    pro = None
    if cfg.data_source == "tushare" and cfg.tushare_token and not cfg.demo:
        pro = ts_client._pro(cfg.tushare_token)

    # 并发拉取各标的；用 map 保序，输出顺序与 indices 一致
    workers = min(_MAX_WORKERS, max(len(cfg.indices), 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda idx: _process_index(idx, cfg, pro, today_is_trading), cfg.indices))

    content = templates_mod.render(results, date_str)
    notifier_mod.push_markdown(content, cfg)
    return 0


def main_handler(event=None, context=None):
    """云函数入口。"""
    cfg = config_mod.Config.load()
    setup_logging(cfg.log_level)
    return run(cfg)


if __name__ == "__main__":
    cfg = config_mod.Config.load()
    setup_logging(cfg.log_level)
    sys.exit(run(cfg))
