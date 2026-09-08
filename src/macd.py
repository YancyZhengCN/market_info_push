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
            分组相位按各标的上市首日锚定，逐值对齐东方财富「2日」（见 `_2D_PHASE_ANCHOR`）
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


# 2 日线相位锚点：东方财富的 2 日 K 线从**各标的上市首日**起固定两两分组（每 2 个交易日一根、
# 收盘取组内较新一天），故相位由「上市首日 → 今日」的交易日总数奇偶决定，各标的不同。
# 本项目为性能只拉最近 3 年（拿不到首日），改存一个已知锚点：
#   (锚点交易日, 该日在东财分组里是否为「一根 2 日 K 线的收盘日」)。
# 运行时用「锚点 → 序列末行」的交易日步数推算末行是否为收盘日，即末根是否与前一根配对。
# parity=1 表示该锚点日是收盘日（== 上一步离线用全历史算出的 inception-index 为奇/该日闭合）。
# 锚点由 tools 用全历史离线标定（见 experience.md §9.5）；新增标的需补标一次。
_2D_PHASE_ANCHOR: dict[str, tuple[str, int]] = {
    "000300.SH": ("2026-09-07", 0),
    "000688.SH": ("2026-09-07", 1),
    "399673.SZ": ("2026-09-07", 1),
    "511260.SH": ("2026-09-07", 0),
    "513120.SH": ("2026-09-07", 1),
    "899050.BJ": ("2026-09-07", 1),
    "HKTECH": ("2026-09-07", 1),
}


def _last_is_paired(s: pd.Series, ts_code: str | None) -> bool:
    """判断序列末行（今日/最新一根）在东财口径下应「与前一根配对」还是「单独成一根」。

    有锚点且落在序列内：用锚点相位 + 步数推算，逐值对齐东财。
    无锚点 / 锚点不在窗口 / 非日期索引：回退「末根单独」（旧口径，相位可能差一根）。
    """
    if ts_code not in _2D_PHASE_ANCHOR or not isinstance(s.index, pd.DatetimeIndex):
        return False
    anchor_date, anchor_parity = _2D_PHASE_ANCHOR[ts_code]
    ad = pd.Timestamp(anchor_date)
    if ad not in s.index:
        return False
    pos = s.index.get_loc(ad)
    steps = (len(s) - 1) - pos
    # 锚点相位每过 1 个交易日翻转一次；末行相位为奇(=1)时该行是「收盘日」→ 与前一根配对
    return (anchor_parity + steps) % 2 == 1


def _resample_2d(s: pd.Series, ts_code: str | None = None) -> pd.Series:
    """合成 2 日 K 线：每 2 个交易日一根，收盘取组内**较新**那天，相位对齐东方财富。

    - 东财从各标的**上市首日**固定两两分组：`_last_is_paired` 用相位锚点判定末根该
      「与前一根配对」（末根 = [昨,今]）还是「单独成一根」（末根 = [今]，当日正在形成）。
    - 不用旧的 `iloc[::2]`：它从头部按奇偶切片，盘中拼实时价改变序列奇偶会使整组日期翻转、
      BAR 大幅跳变；且固定「末根单独」在半数交易日会与东财差一根（本次修复的核心）。
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
