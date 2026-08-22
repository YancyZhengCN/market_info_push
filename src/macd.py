"""MACD 计算。

口径严格对齐用户参考实现 calculateMACD.py：
  EMA12 = ewm(close, 12, adjust=False)
  EMA26 = ewm(close, 26, adjust=False)
  DIF   = EMA12 - EMA26
  DEA   = ewm(DIF, 9, adjust=False)
  BAR   = (DIF - DEA) * 2

三个周期构造（与 TRD §6 一致）：
  - daily ：原始日频 close 直接算
  - 2d    ：日频序列隔行取样（iloc[::2]，保留 0,2,4…）
  - weekly：日频 close 按 W-FRI 重采样取周最后值后算
"""
from __future__ import annotations

from dataclasses import dataclass

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


def _prepare(close: pd.Series, period: str) -> pd.Series:
    s = close.sort_index() if isinstance(close.index, pd.DatetimeIndex) else close.reset_index(drop=True)
    if period == "2d":
        s = s.iloc[::2]
    elif period == "weekly":
        s = s.resample("W-FRI").last().dropna()
    return s


def macd_series(close: pd.Series, period: str = "daily") -> pd.DataFrame:
    s = _prepare(close, period)
    ewma12 = s.ewm(span=FAST, adjust=False).mean()
    ewma26 = s.ewm(span=SLOW, adjust=False).mean()
    dif = ewma12 - ewma26
    dea = dif.ewm(span=SIGNAL, adjust=False).mean()
    bar = (dif - dea) * 2
    return pd.DataFrame({"dif": dif, "dea": dea, "bar": bar}, index=s.index)


def compute(close: pd.Series, period: str = "daily") -> MACDResult:
    df = macd_series(close, period)
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
