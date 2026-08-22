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


def _process_index(idx: config_mod.IndexConfig, cfg: config_mod.Config, pro) -> signal_mod.Signal:
    """单标的处理：取数 → MACD → 信号。单标的失败返回 MISSING，不阻塞其余。"""
    try:
        close = ts_client.get_close(idx, cfg, pro)
        d = macd_mod.compute(close, "daily")
        p2 = macd_mod.compute(close, "2d")
        w = macd_mod.compute(close, "weekly")
        price = float(close.iloc[-1]) if len(close) else None
        sig = signal_mod.build_signal(idx.name, idx.ts_code, d, p2, w, price, idx.basis)
        logger.info(
            "标的 %s → %s (判定周期 %s | 日BAR %.4f / 前1日 %.4f)",
            idx.name,
            sig.status,
            idx.basis,
            d.bar if d.bar is not None else float("nan"),
            d.bar_prev if d.bar_prev is not None else float("nan"),
        )
        return sig
    except Exception as e:  # 单标的失败不阻塞其余
        logger.error("标的 %s 处理失败: %s", idx.name, e)
        return signal_mod.missing_signal(idx.name, idx.ts_code, idx.basis)


def run(cfg: config_mod.Config) -> int:
    today = dt.date.today()
    date_str = today.strftime("%Y-%m-%d")
    logger.info("运行日期 %s | 标的数 %d | demo=%s | push=%s | source=%s", date_str, len(cfg.indices), cfg.demo, cfg.push_enabled, cfg.data_source)

    # 交易日过滤（演示模式 / FORCE_RUN 跳过，便于任意日期预览与调试）
    force_run = os.getenv("FORCE_RUN", "false").lower() == "true"
    if not cfg.demo and not force_run and not ts_client.is_trading_day(today, cfg.tushare_token, cfg.data_source):
        logger.info("非交易日，跳过推送")
        return 0
    if force_run:
        logger.info("FORCE_RUN=true，跳过交易日判断")

    pro = None
    if cfg.data_source == "tushare" and cfg.tushare_token and not cfg.demo:
        pro = ts_client._pro(cfg.tushare_token)

    # 并发拉取各标的；用 map 保序，输出顺序与 indices 一致
    workers = min(_MAX_WORKERS, max(len(cfg.indices), 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda idx: _process_index(idx, cfg, pro), cfg.indices))

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
