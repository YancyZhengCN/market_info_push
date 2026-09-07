"""MACD 计算。

口径严格对齐用户参考实现 calculateMACD.py：
  EMA12 = ewm(close, 12, adjust=False)
  EMA26 = ewm(close, 26, adjust=False)
  DIF   = EMA12 - EMA26
  DEA   = ewm(DIF, 9, adjust=False)
  BAR   = (DIF - DEA) * 2

三个周期构造（与 TRD §6 一致）：
  - daily ：原始日频 close 直接算
  - 2d    ：合成 2 日 K 线——**从最新一根锚定**，每 2 个交易日一桶，
            收盘取桶内**较新**那天的 close（对齐东方财富「2日」口径）
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


def _resample_2d(s: pd.Series) -> pd.Series:
    """合成 2 日 K 线：**从最新一根锚定**，每 2 个交易日一桶，桶收盘取桶内较新那天的 close。

    为何从最新锚定（而非从最旧 iloc[::2]）：
    - 本项目盘中会把实时价作为「当天临时收盘」拼到日线末尾，序列长度奇偶会变，
      若从头部按奇偶切片（iloc[::2]），被选中的整组物理日期会随长度奇偶整体翻转，
      导致 2 日 BAR 在盘中大幅跳变（实测沪深300 由 -9.x 跳到 -12.77）。
    - 东方财富「2日」是把**最新一根**当作正在形成的 2 日 K 线（当前仅含今日），
      再往前每 2 个交易日合成一根，收盘取窗口内**较新**那天。从最新锚定与之一致，
      且不受历史长度奇偶影响，盘中相位稳定。
    """
    n = len(s)
    if n <= 1:
        return s
    rev = s.iloc[::-1]  # 最新在前
    # 分桶：最新一根单独成桶(0)，其后每 2 根一桶(1,1,2,2,…)
    gid = [0] + [((i - 1) // 2) + 1 for i in range(1, n)]
    # head(1) 取每桶最新一根（保留日期索引），再反转回时间升序
    return rev.groupby(gid, sort=False).head(1).iloc[::-1]


def _prepare(close: pd.Series, period: str) -> pd.Series:
    s = close.sort_index() if isinstance(close.index, pd.DatetimeIndex) else close.reset_index(drop=True)
    if period == "2d":
        s = _resample_2d(s)
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
