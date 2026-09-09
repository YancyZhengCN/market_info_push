"""MACD 计算。

口径严格对齐用户参考实现 calculateMACD.py：
  EMA12 = ewm(close, 12, adjust=False)
  EMA26 = ewm(close, 26, adjust=False)
  DIF   = EMA12 - EMA26
  DEA   = ewm(DIF, 9, adjust=False)
  BAR   = (DIF - DEA) * 2

三个周期构造（与 TRD §6 一致）：
  - daily ：原始日频 close 直接算
  - 2d    ：合成 2 日 K 线——每 2 个交易日一根、收盘取组内**较新**那天；
            分组相位用全局锚点收盘日锁定（东财口径全标的统一），逐值对齐东方财富「2日」
            （见 `_2D_PHASE_ANCHOR_CLOSE_DAY`）
  - weekly：日频 close 按 W-FRI 重采样取周最后值后算
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FAST = 12
SLOW = 26
SIGNAL = 9


@dataclass
class MACDResult:
    period: str
    bar: float | None
    bar_prev: float | None
    dif: float | None
    dea: float | None
    series: pd.DataFrame


# 2 日线相位锚点（全局单锚点）。
# 关键事实（经东方财富多标的、跨日实测）：东财 2 日 K 线的「收盘日」是一套**全局统一的交易日历
# 相位**——所有标的在同一天要么都是收盘日、要么都不是，与各标的上市首日/历史长度**无关**。
# 因此只需一个「已知收盘日」作全局锚点：任一标的、任一交易日 X，若 X 与锚点的交易日步数为偶数，
# 则 X 也是收盘日（末根 = [今]，单独成一根）；为奇数则末根 = [昨,今]（配对）。
# 交易日步数用该标的**自身**日线序列计数（天然是其交易日），故不依赖历史行数是否完整/稳定。
#
# ⚠️ 历史教训（见 experience.md §9.6）：早期版本用「各标的全历史行数奇偶」定相位，既因 akshare
# 早期行会增删而漂移，又因 akshare 行数≠东财所用行数而系统性偏一格（科创50/北证50 全错）。
# 全局收盘日锚点不碰行数，彻底规避这两点。
#
# 锚点取一个**足够早、所有在监标的都已上市**的已知收盘日，保证它恒在 3 年窗口内、且 ≤ 序列末行
# （searchsorted 不会越界）。2025-06-17 经东财实测为收盘日（与 2026-09-09 相隔偶数个交易日），
# 且沪深300/科创50/创业板50/北证50/国债ETF/港股创新药ETF 当日均有数据。
# 锚点长期有效，无需逐日维护；仅当东财口径变化时才需重标。
_2D_PHASE_ANCHOR_CLOSE_DAY = "2025-06-17"


def _last_is_paired(s: pd.Series, ts_code: str | None = None) -> bool:
    """判断序列末行（今日/最新一根）应「与前一根配对」（[昨,今]）还是「单独成一根」（[今]）。

    用全局锚点收盘日 + 该标的自身序列的交易日步数推算：
      末行与锚点步数为偶 → 末行也是收盘日 → 单独（不配对）；为奇 → 配对。
    锚点日不必恰好在序列内（个别标的停牌）：用 searchsorted 取其位置，只要相对末行的
    交易日**奇偶**正确即可（同一交易日历下停牌日各标的一致，parity 不变）。
    非日期索引 / 空序列：回退「末根单独」（不配对）。
    """
    if not isinstance(s.index, pd.DatetimeIndex) or len(s) == 0:
        return False
    ad = pd.Timestamp(_2D_PHASE_ANCHOR_CLOSE_DAY)
    # 锚点选自足够早的历史收盘日，恒 ≤ 序列末行；searchsorted(left) 给出其在序列中的位置。
    pos = int(s.index.searchsorted(ad, side="left"))
    if pos >= len(s):
        # 整段序列都早于锚点（仅合成/历史回测会出现，生产不会）：无法据锚点定相位，
        # 回退「末根单独」（不配对）。
        return False
    steps = (len(s) - 1) - pos
    # 步数为奇 → 末行不是收盘日 → 与前一根配对
    return steps % 2 == 1


def _resample_2d(s: pd.Series, ts_code: str | None = None) -> pd.Series:
    """合成 2 日 K 线：每 2 个交易日一根，收盘取组内**较新**那天，相位对齐东方财富。

    - `_last_is_paired` 用全局锚点收盘日判定末根该「与前一根配对」（末根 = [昨,今]）还是
      「单独成一根」（末根 = [今]，当日正在形成）。
    - 不用旧的 `iloc[::2]`：它从头部按奇偶切片，盘中拼实时价改变序列奇偶会使整组日期翻转、
      BAR 大幅跳变；且固定「末根单独」在半数交易日会与东财差一根。
    """
    n = len(s)
    if n <= 1:
        return s
    rev = s.iloc[::-1]  # 最新在前
    if _last_is_paired(s, ts_code):
        # 末根与前一根配对：从最新起每 2 根一桶(0,0,1,1,…)
        gid = np.arange(n) // 2
    else:
        # 末根单独成桶(0)，其后每 2 根一桶(1,1,2,2,…)
        gid = [0] + [((i - 1) // 2) + 1 for i in range(1, n)]
    # head(1) 取每桶最新一根（保留日期索引），再反转回时间升序
    return rev.groupby(gid, sort=False).head(1).iloc[::-1]


def _prepare(close: pd.Series, period: str, ts_code: str | None = None) -> pd.Series:
    s = close.sort_index() if isinstance(close.index, pd.DatetimeIndex) else close.reset_index(drop=True)
    if period == "2d":
        s = _resample_2d(s, ts_code)
    elif period == "weekly":
        s = s.resample("W-FRI").last().dropna()
    return s


def macd_series(close: pd.Series, period: str = "daily", ts_code: str | None = None) -> pd.DataFrame:
    s = _prepare(close, period, ts_code)
    ewma12 = s.ewm(span=FAST, adjust=False).mean()
    ewma26 = s.ewm(span=SLOW, adjust=False).mean()
    dif = ewma12 - ewma26
    dea = dif.ewm(span=SIGNAL, adjust=False).mean()
    bar = (dif - dea) * 2
    return pd.DataFrame({"dif": dif, "dea": dea, "bar": bar}, index=s.index)


def compute(close: pd.Series, period: str = "daily", ts_code: str | None = None) -> MACDResult:
    df = macd_series(close, period, ts_code)
    bar = df["bar"]
    n = len(bar)
    if n == 0:
        return MACDResult(period, None, None, None, None, df)
    if n == 1:
        return MACDResult(
            period,
            float(bar.iloc[-1]),
            None,
            float(df["dif"].iloc[-1]),
            float(df["dea"].iloc[-1]),
            df,
        )
    return MACDResult(
        period,
        float(bar.iloc[-1]),
        float(bar.iloc[-2]),
        float(df["dif"].iloc[-1]),
        float(df["dea"].iloc[-1]),
        df,
    )
