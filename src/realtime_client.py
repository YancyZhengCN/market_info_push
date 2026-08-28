"""盘中实时取价：按 api 类型分派到对应 akshare 实时接口（免 token，避开东方财富）。

用途：日线历史接口在收盘前不含当天这根日 K，盘中取到的最后一根仍是上一交易日。
本模块取当天**实时价**，由取数层作为「当天临时收盘价」拼接到日线序列末尾，算盘中动态 MACD。

各 api 类型的实时源（均为新浪/腾讯/金交所官网，非东财）：
- index_daily（A股指数）：ak.stock_zh_index_spot_sina（含 sh000300 / sz399673 等）
- index_daily（ETF）    ：ak.stock_zh_a_minute（新浪分钟线，取最后一根 close 作为实时价）
- index_daily（北证指数）：ak.stock_zh_a_minute（新浪分钟线，支持 bj899050）
- index_global（港股指数）：ak.stock_hk_index_spot_sina（含 HSTECH）
- spot_sge（黄金现货）   ：ak.spot_quotations_sge（Au99.99 现价）
- index_csi（中证指数）  ：**无可用实时源**，返回 None（盘中不参与，由上层剔除）

约定：取到返回 float 实时价；任何失败/无源返回 None，绝不抛错（单标的降级）。
"""
from __future__ import annotations

import logging
from typing import Optional

from config import IndexConfig

logger = logging.getLogger("index_signal")

# ETF 代码集合（与 A 股指数同为 index_daily，但实时源不同，靠 ts_code 区分）
# 511/159/58 等为 ETF 常见前缀；这里以是否为基金代码段粗略判断。
def _is_etf(ts_code: str) -> bool:
    code = ts_code.split(".")[0]
    return code.startswith(("51", "56", "58", "159", "15"))


def _is_bj_index(ts_code: str) -> bool:
    return ts_code.upper().endswith(".BJ")


def get_spot(index: IndexConfig) -> Optional[float]:
    """取标的当天实时价；无源或（重试后仍）失败返回 None，由上层降级用日线。"""
    api = index.api
    if api == "index_daily":
        if _is_etf(index.ts_code):
            fetch = _spot_etf
        elif _is_bj_index(index.ts_code):
            fetch = _spot_bj_index
        else:
            fetch = _spot_a_index
    elif api == "index_global":
        fetch = _spot_hk_index
    elif api == "spot_sge":
        fetch = _spot_gold
    else:
        return None  # index_csi 等无实时源

    import retry_util

    try:
        # 偶发网络抖动/限流：重试若干次再判失败，降低"取到上一交易日"的概率
        return retry_util.call_with_retry(
            lambda: fetch(index), what=f"实时取价 {index.ts_code}"
        )
    except Exception as e:  # 重试后仍失败 → 降级用日线，不阻断
        logger.warning("实时取价失败（降级用日线）: %s -> %s", index.ts_code, e)
        return None


def _spot_a_index(index: IndexConfig) -> Optional[float]:
    """A股指数实时：新浪指数实时全量，按 sh/sz+代码 命中。"""
    import akshare as ak

    code = index.ts_code.upper()
    if code.endswith(".SH"):
        symbol = "sh" + code.split(".")[0]
    elif code.endswith(".SZ"):
        symbol = "sz" + code.split(".")[0]
    else:
        return None
    df = ak.stock_zh_index_spot_sina()
    m = dict(zip(df["代码"], df["最新价"]))
    val = m.get(symbol)
    return float(val) if val is not None else None


def _spot_etf(index: IndexConfig) -> Optional[float]:
    """ETF 实时：新浪分钟线最后一根 close（1 分钟粒度足够作盘中快照）。"""
    import akshare as ak

    code = index.ts_code.upper()
    if code.endswith(".SH"):
        symbol = "sh" + code.split(".")[0]
    elif code.endswith(".SZ"):
        symbol = "sz" + code.split(".")[0]
    else:
        return None
    df = ak.stock_zh_a_minute(symbol=symbol, period="1", adjust="qfq")
    if df is None or df.empty:
        return None
    return float(df["close"].iloc[-1])


def _spot_bj_index(index: IndexConfig) -> Optional[float]:
    """北证指数实时：新浪分钟线最后一根 close（指数实时全量接口不收录 bj899050）。"""
    import akshare as ak

    code = index.ts_code.upper()
    if not code.endswith(".BJ"):
        return None
    symbol = "bj" + code.split(".")[0]
    df = ak.stock_zh_a_minute(symbol=symbol, period="1", adjust="qfq")
    if df is None or df.empty:
        return None
    return float(df["close"].iloc[-1])


def _spot_hk_index(index: IndexConfig) -> Optional[float]:
    """港股指数实时：新浪港股指数实时全量，按代码（如 HSTECH）命中。"""
    import akshare as ak

    symbol = "HSTECH" if index.ts_code.upper() == "HKTECH" else index.ts_code.upper()
    df = ak.stock_hk_index_spot_sina()
    m = dict(zip(df["代码"], df["最新价"]))
    val = m.get(symbol)
    return float(val) if val is not None else None


def _spot_gold(index: IndexConfig) -> Optional[float]:
    """黄金现货实时：上海金交所实时报价，取对应品种现价。"""
    import akshare as ak

    symbol = "Au99.99" if index.ts_code.upper() == "AU9999" else index.ts_code
    df = ak.spot_quotations_sge(symbol=symbol)
    if df is None or df.empty:
        return None
    # 返回多行（分时），取最后一行现价
    return float(df["现价"].iloc[-1])
