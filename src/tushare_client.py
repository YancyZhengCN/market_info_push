"""取数层：支持 Tushare 与 AkShare（新浪 / 腾讯源）双数据源，外加确定性合成数据(DEMO)。

统一约定：
- 每个标的返回 DatetimeIndex 升序、去空的 close Series，供 MACD/信号层消费。
- 数据源由 `config.data_source` 决定：tushare（默认，需 token）/ akshare（免 token）。
- Tushare / akshare 均为懒加载（仅真实取数时 import），便于无依赖演示。
- akshare 走腾讯 / 新浪源接口：A股指数与 ETF 用 stock_zh_a_hist_tx（腾讯，前复权，
  与同花顺/新浪 App 的 MACD 口径一致）；港股指数用 stock_hk_index_daily_sina（新浪）。
  规避东方财富行情接口在部分网络下被断连的问题。
- DEMO 模式或无可用数据源：返回确定性合成序列，跑通全流程无需联网。
"""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Optional

import pandas as pd

from config import Config, IndexConfig

# Tushare 接口映射（仅 tushare 源使用）
_TUSHARE_API_MAP = {
    "index_daily": "index_daily",
    "index_global": "index_global",
    "fund_daily": "fund_daily",
}


def _pro(token: str):
    import tushare as ts

    return ts.pro_api(token)


def is_trading_day(date: dt.date, token: Optional[str] = None, data_source: str = "tushare") -> bool:
    """优先用 Tushare trade_cal 判定；否则退化为"仅工作日"判断。"""
    if data_source == "tushare" and token:
        try:
            pro = _pro(token)
            cal = pro.trade_cal(exchange="SSE", date=date.strftime("%Y%m%d"))
            if not cal.empty and int(cal.iloc[0]["is_open"]) == 1:
                return True
            return False
        except Exception:
            pass
    return date.weekday() < 5


def get_close(index: IndexConfig, config: Config, pro=None) -> pd.Series:
    # DEMO：确定性合成数据，无需联网
    if config.demo:
        return _synthetic_close(index.ts_code, index.lookback)

    source = (config.data_source or "tushare").lower()
    if source == "akshare":
        close = _get_close_akshare_retry(index, config)
        return _maybe_append_spot(close, index, config)
    if source == "tushare":
        if not config.tushare_token:
            # 无 token 自动降级到 AkShare（东方财富，免 token）
            close = _get_close_akshare_retry(index, config)
            return _maybe_append_spot(close, index, config)
        return _get_close_tushare(index, config, pro)

    raise ValueError(f"未知数据源: {source}")


def _get_close_akshare_retry(index: IndexConfig, config: Config) -> pd.Series:
    """日线取数带重试：akshare 偶发网络抖动/限流，重试若干次再判失败，
    降低单标的因一次抖动就被标记 MISSING（数据缺失）的概率。"""
    import retry_util

    return retry_util.call_with_retry(
        lambda: _get_close_akshare(index, config), what=f"日线取数 {index.ts_code}"
    )


def _maybe_append_spot(close: pd.Series, index: IndexConfig, config: Config) -> pd.Series:
    """盘中把实时价作为「当天临时收盘价」拼接到日线序列末尾，算动态 MACD。

    - config.realtime_intraday 关闭：直接用日线（用户主动选择日线口径，不算误导）。
    - 序列末行日期 >= 今天（当天日 K 已生成）：无需拼接，直接返回。
    - 序列末行 < 今天（盘中，当天日 K 未生成）：**必须**拿到实时价拼接；
      若实时价取不到（重试后仍失败 / 无实时源），则**抛异常**让该标的标记 MISSING，
      **绝不回退显示上一交易日日线**——否则用户会误以为是今天的数据。
    实时价用今天作为索引追加；若已有今天则替换。
    """
    if not getattr(config, "realtime_intraday", True):
        return close
    if close is None or len(close) == 0 or not isinstance(close.index, pd.DatetimeIndex):
        return close

    today = pd.Timestamp(dt.date.today())
    last_day = close.index[-1].normalize()
    if last_day >= today:
        return close  # 当天日 K 已生成，无需拼接

    import realtime_client

    spot = realtime_client.get_spot(index)
    if spot is None:
        # 盘中但实时价取不到：不能回退用上一交易日日线（会误导用户以为是今天），
        # 抛异常 → 上层标记 MISSING → 进「数据缺失」块。
        raise ValueError(
            f"盘中实时价取不到（{index.ts_code}），拒绝回退上一交易日日线，标记数据缺失"
        )

    out = close.copy()
    out.loc[today] = float(spot)
    return out.sort_index()


# ---------- Tushare 源 ----------
def _get_close_tushare(index: IndexConfig, config: Config, pro=None) -> pd.Series:
    if pro is None:
        pro = _pro(config.tushare_token)
    api_name = _TUSHARE_API_MAP[index.api]
    end = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=index.lookback * 2)).strftime("%Y%m%d")
    df = getattr(pro, api_name)(ts_code=index.ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        raise ValueError(f"取数为空: {index.ts_code}")
    df = df.dropna(subset=["close"])
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.set_index("trade_date").sort_index()
    return df["close"].astype(float)


# ---------- AkShare 源（新浪 / 腾讯，免 token）----------
def _ak_symbol(index: IndexConfig) -> str:
    """把 ts_code 转成 akshare 新浪源 symbol（含市场前缀）。

    沪深指数 000300.SH -> sh000300；399673.SZ -> sz399673；北证50 899050.BJ -> bj899050。
    ETF     511260.SH -> sh511260；159915.SZ -> sz159915。
    港股指数 HKTECH    -> HSTECH（stock_hk_index_daily_sina 专用代码，无前缀）。
    """
    code = index.ts_code.upper()
    if code == "HKTECH":
        return "HSTECH"
    if code.endswith(".SH"):
        return "sh" + code.split(".")[0]
    if code.endswith(".SZ"):
        return "sz" + code.split(".")[0]
    if code.endswith(".BJ"):
        return "bj" + code.split(".")[0]
    raise ValueError(f"无法推导 akshare symbol: {index.ts_code}")


def _sge_symbol(index: IndexConfig) -> str:
    """把黄金 ts_code 转成 akshare 金交所现货 symbol。

    黄金 AU9999 -> Au99.99（spot_hist_sge 专用代码）。其余 AU 开头暂原样透传。
    """
    code = index.ts_code.upper()
    if code == "AU9999":
        return "Au99.99"
    return index.ts_code


def _get_close_akshare(index: IndexConfig, config: Config) -> pd.Series:
    """经 akshare 取日线收盘。

    - index_daily / fund_daily：A股指数与 ETF 走 ak.stock_zh_a_hist_tx（腾讯，**前复权**），
      与同花顺 / 新浪 App 的 MACD 口径一致（ETF 分红需前复权，否则 MACD 偏大）。
    - index_global：港股指数走 ak.stock_hk_index_daily_sina（新浪，指数无复权）。
    - index_csi：中证指数（如港股创新药 931787）走 ak.stock_zh_index_hist_csindex
      （中证官网源，不走东财，返回中文列名）。
    - spot_sge：上海金交所黄金现货（如黄金 AU9999）走 ak.spot_hist_sge
      （金交所官网源，symbol=Au99.99，返回 date/open/close/low/high）。
    统一返回 DatetimeIndex 升序、去空的 close Series（取最近 lookback 段）。
    """
    import akshare as ak

    # 上海金交所黄金现货：官网源，无复权概念，单独处理
    if index.api == "spot_sge":
        df = ak.spot_hist_sge(symbol=_sge_symbol(index))
        if df is None or df.empty:
            raise ValueError(f"取数为空: {index.ts_code}")
        df = df.dropna(subset=["close"]).copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df["close"].astype(float).tail(max(index.lookback, 60))

    # 中证指数：官网源，中文列名，单独处理
    if index.api == "index_csi":
        code = index.ts_code.split(".")[0]  # 931787.CSI -> 931787
        df = ak.stock_zh_index_hist_csindex(symbol=code, start_date="19900101", end_date="20500101")
        if df is None or df.empty:
            raise ValueError(f"取数为空: {index.ts_code}")
        df = df.rename(columns={"日期": "date", "收盘": "close"})
        df = df.dropna(subset=["close"]).copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df["close"].astype(float).tail(max(index.lookback, 60))

    symbol = _ak_symbol(index)
    if index.api == "index_global":
        # 港股指数：新浪指数接口（腾讯 A 股个股接口取不到港股）
        df = ak.stock_hk_index_daily_sina(symbol=symbol)
    else:
        # A股指数 / ETF：腾讯个股历史，前复权对齐主流行情软件。
        # 只拉最近一段（约 lookback 个交易日 + 预热余量），避免拉全量历史拖慢单次运行：
        # 全历史约 5000+ 行、单标的耗时 10s+；有界范围仅几百行、耗时 ~1s，
        # MACD 只看相对变化，预热 120+ 根已足够收敛，不影响信号判定。
        need = max(index.lookback, 60)
        start = (dt.date.today() - dt.timedelta(days=need * 2 + 40)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist_tx(
            symbol=symbol, start_date=start, end_date="20500101", adjust="qfq"
        )

    if df is None or df.empty:
        raise ValueError(f"取数为空: {index.ts_code}")
    if "close" not in df.columns or "date" not in df.columns:
        raise ValueError(f"akshare 返回缺少 date/close 列: {index.ts_code} -> {list(df.columns)}")

    df = df.dropna(subset=["close"]).copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df["close"].astype(float).tail(max(index.lookback, 60))


# ---------- 合成数据（DEMO / 无网络兜底） ----------
def _synthetic_close(ts_code: str, lookback: int = 120) -> pd.Series:
    """演示用合成序列：确定性（按代码哈希做种子），无需 token/联网。"""
    import numpy as np

    n = max(lookback, 130)
    seed = int(hashlib.md5(ts_code.encode("utf-8")).hexdigest(), 16) % (2**31)
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=dt.date.today(), periods=n)
    t = np.arange(n)
    vals = 100 + 5 * np.sin(t / 6.0) + rng.normal(0, 1, n).cumsum() * 0.5
    return pd.Series(vals.round(2), index=dates)
