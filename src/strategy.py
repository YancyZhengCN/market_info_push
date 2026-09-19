"""牛市增强目标仓位策略层。

三个可独立测试的纯函数（同一历史输入重复运行必须得到相同结果）：

1. `evaluate_enhanced(close)`   → 每个交易日的增强版事件 BUY / SELL / HOLD / ERROR
2. `evaluate_bull_market(close)`→ 每个交易日的牛市状态 BULL / NON_BULL / UNKNOWN
3. `replay_target_position(...)`→ 按历史顺序重放出每日目标仓位 TARGET_HOLD / TARGET_CASH / UNKNOWN

组合逻辑（改造说明「策略选择」）：
    牛市    → 目标仓位固定持仓（TARGET_HOLD）
    非牛市  → 按增强版事件更新目标仓位（BUY→持仓 / SELL→空仓 / HOLD→继承）

展示层只读取 `TargetPositionDecision`，不得再次推导策略。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import config as config_mod
import macd as macd_mod

# 事件 / 状态取值常量
EV_BUY, EV_SELL, EV_HOLD, EV_ERROR = "BUY", "SELL", "HOLD", "ERROR"
BULL, NON_BULL, UNKNOWN = "BULL", "NON_BULL", "UNKNOWN"
TARGET_HOLD, TARGET_CASH = "TARGET_HOLD", "TARGET_CASH"


# ---------------------------------------------------------------------------
# 数据模型（与改造说明「数据模型」一致）
# ---------------------------------------------------------------------------
@dataclass
class EnhancedDecision:
    event: str
    reason: str
    delta_bar_2d: float | None
    sigma20: float | None
    threshold: float | None
    weekly_bar_completed: float | None
    weekly_bar_completed_prev: float | None


@dataclass
class BullMarketDecision:
    status: str
    reason: str
    weekly_close_completed: float | None
    ema50: float | None
    ema50_slope_reference: float | None  # 斜率回看基准：N 周前的 EMA50（N=slope_lookback_weeks）
    slope_lookback_weeks: int            # 斜率回看周数（当前生产=12）
    price_buffer: float                  # 价格缓冲（当前生产=0.00，即只需严格站上 EMA50）


@dataclass
class TargetPositionDecision:
    state: str
    reason: str
    bull: BullMarketDecision
    enhanced: EnhancedDecision
    enhanced_position: str = UNKNOWN  # 增强版**独立**历史重放的当前仓位（不受牛市覆盖），仅用于展示/解释


# ---------------------------------------------------------------------------
# 增强版事件
# ---------------------------------------------------------------------------
def _delta_bar_2d_history(close: pd.Series) -> pd.Series:
    """逐交易日重算“截至当日”的 2 日 BAR 增量 ΔBAR₂D(t) = BAR₂D(t) - BAR₂D_prev(t)。

    口径要求（改造说明「2日增量与阈值」）：
      - ΔBAR₂D 用“最近两根 2 日 K 的 BAR 之差”，其中 2 日 K 相位需逐日按当日截断序列判定
        （盘中/末根配对随交易日推移翻转，见 macd._resample_2d），故必须逐日截断重算，
        不能用一次性合成的 2 日序列直接 diff。
      - 每日一个快照，供 σ20 用最近 20 个交易日的样本标准差。
    """
    if not isinstance(close.index, pd.DatetimeIndex):
        close = close.sort_index()
    n = len(close)
    deltas: list[float] = []
    for i in range(n):
        sub = close.iloc[: i + 1]
        bar2d = macd_mod.bar_series(macd_mod._prepare(sub, "2d"))
        if len(bar2d) >= 2:
            deltas.append(float(bar2d.iloc[-1]) - float(bar2d.iloc[-2]))
        else:
            deltas.append(np.nan)
    return pd.Series(deltas, index=close.index, dtype=float)


def _completed_weekly_bar_history(close: pd.Series) -> pd.DataFrame:
    """逐交易日的“最近两根已完成周 BAR”。

    对每个交易日，取截至当日的已完成周收盘序列算周BAR，返回最后一根(cur)与倒数第二根(prev)。
    与牛市 EMA50 复用同一“已完成周线”边界（macd.completed_weekly_close）。
    """
    if not isinstance(close.index, pd.DatetimeIndex):
        close = close.sort_index()
    # 周边界只随“末日所属周”变化：把同属一个 W-FRI 桶的交易日聚成一批，批内已完成周线相同，
    # 只需按“正在形成的本周右边界”分组算一次，避免逐日重算周BAR（O(N)×周重采样）。
    forming_ends = pd.Index([macd_mod.week_end(ts) for ts in close.index])
    cur_list: list[float | None] = []
    prev_list: list[float | None] = []
    cache: dict[pd.Timestamp, tuple[float | None, float | None]] = {}
    for i, ts in enumerate(close.index):
        fe = forming_ends[i]
        if fe not in cache:
            sub = close.iloc[: i + 1]
            comp = macd_mod.completed_weekly_close(sub)
            wbar = macd_mod.bar_series(comp) if len(comp) else pd.Series(dtype=float)
            cur = float(wbar.iloc[-1]) if len(wbar) >= 1 else None
            prev = float(wbar.iloc[-2]) if len(wbar) >= 2 else None
            cache[fe] = (cur, prev)
        cur, prev = cache[fe]
        cur_list.append(cur)
        prev_list.append(prev)
    return pd.DataFrame({"weekly_bar": cur_list, "weekly_bar_prev": prev_list}, index=close.index)


def _classify_enhanced_event(
    delta_bar_2d: float | None,
    sigma20: float | None,
    threshold: float | None,
    weekly_bar: float | None,
    weekly_bar_prev: float | None,
) -> tuple[str, str]:
    """增强版事件的纯判定（不依赖 pandas），返回 (event, reason)。

        if data_missing(ΔBAR₂D 缺失):                     ERROR
        elif ΔBAR₂D < 0:                                   SELL   # 卖出不依赖周线
        elif weekly_ok 且 ΔBAR₂D > 0.4×σ20:                BUY
        else:                                              HOLD
    weekly_ok = 已完成周BAR >= 上一已完成周BAR；σ20 缺失时不得出 BUY。
    """
    if delta_bar_2d is None:
        return EV_ERROR, "ΔBAR₂D 缺失（历史不足或计算失败）"
    if delta_bar_2d < 0:
        return EV_SELL, "2日动量转弱(ΔBAR₂D<0)，快速退出"
    weekly_ok = (
        weekly_bar is not None
        and weekly_bar_prev is not None
        and weekly_bar >= weekly_bar_prev
    )
    if weekly_ok and threshold is not None and delta_bar_2d > threshold:
        return EV_BUY, "周动量未恶化且ΔBAR₂D>0.4σ20"
    # 未出买入也未出卖出：区分原因便于日志解释
    if sigma20 is None:
        reason = "σ20缺失，不生成买入；维持HOLD"
    elif weekly_bar is None or weekly_bar_prev is None:
        reason = "已完成周BAR不足，不放行买入；维持HOLD"
    elif weekly_bar < weekly_bar_prev:
        reason = "周动量恶化，不放行买入；维持HOLD"
    else:
        reason = "ΔBAR₂D未超阈值；维持HOLD"
    return EV_HOLD, reason


def evaluate_enhanced(close: pd.Series) -> "pd.Series":
    """返回每个交易日的 EnhancedDecision（含 event = BUY / SELL / HOLD / ERROR）。

    事件规则见 `_classify_enhanced_event`；σ20 缺失时不得出 BUY。
    """
    window = config_mod.ENHANCED_SIGMA_WINDOW
    min_periods = config_mod.ENHANCED_SIGMA_MIN_PERIODS
    mult = config_mod.ENHANCED_THRESHOLD_MULTIPLIER

    delta = _delta_bar_2d_history(close)
    # σ20：最近 window 个交易日 ΔBAR₂D 快照的样本标准差（ddof=1），min_periods 控制缺失
    sigma = delta.rolling(window=window, min_periods=min_periods).std(ddof=1)
    weekly = _completed_weekly_bar_history(close)

    out: list[EnhancedDecision] = []
    for ts in close.index:
        d = delta.loc[ts]
        s = sigma.loc[ts]
        wbar = weekly.loc[ts, "weekly_bar"]
        wprev = weekly.loc[ts, "weekly_bar_prev"]

        d_val = float(d) if pd.notna(d) else None
        s_val = float(s) if pd.notna(s) else None
        thr = float(mult * s_val) if s_val is not None else None
        wbar_val = float(wbar) if wbar is not None and pd.notna(wbar) else None
        wprev_val = float(wprev) if wprev is not None and pd.notna(wprev) else None

        ev, reason = _classify_enhanced_event(d_val, s_val, thr, wbar_val, wprev_val)
        out.append(
            EnhancedDecision(
                event=ev,
                reason=reason,
                delta_bar_2d=d_val,
                sigma20=s_val,
                threshold=thr,
                weekly_bar_completed=wbar_val,
                weekly_bar_completed_prev=wprev_val,
            )
        )
    return pd.Series(out, index=close.index, dtype=object)


# ---------------------------------------------------------------------------
# 牛市判定
# ---------------------------------------------------------------------------
def evaluate_bull_market(close: pd.Series) -> "pd.Series":
    """返回每个交易日的 BullMarketDecision（status = BULL / NON_BULL / UNKNOWN）。

    判定（牛市规则），使用**已完成周收盘**算 EMA50：
        已完成周收盘 > EMA50 × (1+buffer)  且  当前EMA50 > N周前EMA50  → BULL
        其余可正常计算的情况                                          → NON_BULL
        数据不足以算 EMA50 或 N 周斜率                                → UNKNOWN（不得默认非牛市）
    参数：buffer=BULL_CLOSE_BUFFER（生产0.00）、N=BULL_SLOPE_LOOKBACK_WEEKS（生产12）。
    与增强版周BAR复用同一“已完成周线”边界。
    """
    span = config_mod.BULL_EMA_WEEKS
    slope = config_mod.BULL_SLOPE_LOOKBACK_WEEKS
    buffer = config_mod.BULL_CLOSE_BUFFER

    if not isinstance(close.index, pd.DatetimeIndex):
        close = close.sort_index()

    forming_ends = pd.Index([macd_mod.week_end(ts) for ts in close.index])
    cache: dict[pd.Timestamp, BullMarketDecision] = {}
    out: list[BullMarketDecision] = []
    for i, ts in enumerate(close.index):
        fe = forming_ends[i]
        if fe not in cache:
            comp = macd_mod.completed_weekly_close(close.iloc[: i + 1])
            cache[fe] = _bull_from_completed_weekly(comp, span, slope, buffer)
        out.append(cache[fe])
    return pd.Series(out, index=close.index, dtype=object)


def _classify_bull(
    latest_close: float | None,
    latest_ema50: float | None,
    ema50_slope_reference: float | None,
    buffer: float,
    slope: int,
) -> tuple[str, str]:
    """牛市状态的纯判定（不依赖 pandas），返回 (status, reason)。

        任一必要值缺失                                         → UNKNOWN
        已完成周收盘 > EMA50×(1+buffer) 且 EMA50 > N周前EMA50   → BULL
        否则                                                   → NON_BULL
    两个比较均为严格大于（等于都不通过）。
    """
    if latest_close is None or latest_ema50 is None or ema50_slope_reference is None:
        return UNKNOWN, f"已完成周线历史不足，无法取得{slope}周前50周EMA"
    price_ok = latest_close > latest_ema50 * (1 + buffer)
    slope_ok = latest_ema50 > ema50_slope_reference
    if price_ok and slope_ok:
        return BULL, f"已完成周收盘价高于50周EMA，且50周EMA高于{slope}周前，判定为牛市"
    if not price_ok:
        return NON_BULL, "已完成周收盘价未严格高于50周EMA，判定为非牛市"
    return NON_BULL, f"50周EMA未严格高于{slope}周前50周EMA，判定为非牛市"


def _bull_from_completed_weekly(
    comp: pd.Series, span: int, slope: int, buffer: float
) -> BullMarketDecision:
    """在“已完成周收盘”序列上做一次牛市判定。"""
    # 需要至少 slope+1 根已完成周线才能取到 N 周前 EMA50；EMA50 本身可在样本不足时被拉偏，
    # 故要求样本足以覆盖 EMA50 预热与 N 周斜率（min_len）。
    min_len = slope + 1
    if len(comp) < min_len:
        status, reason = _classify_bull(None, None, None, buffer, slope)
        return BullMarketDecision(
            status=status,
            reason=reason,
            weekly_close_completed=None,
            ema50=None,
            ema50_slope_reference=None,
            slope_lookback_weeks=slope,
            price_buffer=buffer,
        )
    ema = comp.ewm(span=span, adjust=False).mean()
    close_now = float(comp.iloc[-1])
    ema_now = float(ema.iloc[-1])
    ema_ref = float(ema.iloc[-1 - slope])  # N 周前 EMA50（斜率基准）

    status, reason = _classify_bull(close_now, ema_now, ema_ref, buffer, slope)
    return BullMarketDecision(
        status=status,
        reason=reason,
        weekly_close_completed=close_now,
        ema50=ema_now,
        ema50_slope_reference=ema_ref,
        slope_lookback_weeks=slope,
        price_buffer=buffer,
    )


# ---------------------------------------------------------------------------
# 目标仓位历史重放
# ---------------------------------------------------------------------------
def replay_target_position(
    enhanced_events: pd.Series,
    bull_states: pd.Series,
) -> "pd.Series":
    """按时间顺序重放每日目标仓位状态（TARGET_HOLD / TARGET_CASH / UNKNOWN）。

    转换规则（改造说明「状态机」）：
      - 必要数据缺失（增强版 ERROR 或 牛市 UNKNOWN）：跳过当日，不改变状态；
      - 牛市（BULL）：state = TARGET_HOLD；
      - 非牛市：BUY→TARGET_HOLD，SELL→TARGET_CASH，HOLD→继承前一状态；
      - 从牛市退出当天立即应用增强版事件（无额外确认/冷却）。
    入参为两条同索引的 Series（EnhancedDecision / BullMarketDecision，或直接的字符串事件/状态）。
    """
    idx = enhanced_events.index
    state = UNKNOWN
    states: list[str] = []
    for ts in idx:
        ev = _as_event(enhanced_events.loc[ts])
        bull = _as_bull_status(bull_states.loc[ts])

        # 必要数据缺失：牛市 UNKNOWN 或 增强版 ERROR → 当日不改变状态（重放跳过）
        if bull == UNKNOWN or ev == EV_ERROR:
            states.append(state)
            continue

        if bull == BULL:
            state = TARGET_HOLD
        elif ev == EV_BUY:
            state = TARGET_HOLD
        elif ev == EV_SELL:
            state = TARGET_CASH
        # ev == HOLD：继承（state 不变）
        states.append(state)
    return pd.Series(states, index=idx, dtype=object)


def _as_event(x) -> str:
    return x.event if isinstance(x, EnhancedDecision) else str(x)


def _as_bull_status(x) -> str:
    return x.status if isinstance(x, BullMarketDecision) else str(x)


def replay_enhanced_position(enhanced_events: pd.Series) -> "pd.Series":
    """增强版**独立**仓位历史重放（不考虑牛市覆盖），返回每日 TARGET_HOLD / TARGET_CASH / UNKNOWN。

    仅用于卡片「信号」列右槽的 ⭕️ 展示与解释，不参与最终目标仓位分组。
    转换规则（改造说明「增强版独立重放」）：
      - BUY  → TARGET_HOLD
      - SELL → TARGET_CASH
      - HOLD → 继承前一状态（起始为 UNKNOWN 则保持 UNKNOWN）
      - ERROR→ 保持前一状态
    纯函数：同一事件历史重复执行结果完全一致。
    """
    idx = enhanced_events.index
    state = UNKNOWN
    states: list[str] = []
    for ts in idx:
        ev = _as_event(enhanced_events.loc[ts])
        if ev == EV_BUY:
            state = TARGET_HOLD
        elif ev == EV_SELL:
            state = TARGET_CASH
        # HOLD / ERROR：继承前一状态（state 不变）
        states.append(state)
    return pd.Series(states, index=idx, dtype=object)


# ---------------------------------------------------------------------------
# 组装：单标的目标仓位决策（供 main / 展示层调用）
# ---------------------------------------------------------------------------
def decide_target_position(close: pd.Series) -> TargetPositionDecision:
    """对单标的的完整日线（含当天拼接的实时价）计算最终 TargetPositionDecision。

    - 无法计算（历史为空）时返回 UNKNOWN。
    - 展示层据 state 分类：TARGET_HOLD→买入表、TARGET_CASH→卖出表、UNKNOWN→未触发。
    """
    if close is None or len(close) == 0:
        empty_enh = EnhancedDecision(EV_ERROR, "无收盘数据", None, None, None, None, None)
        empty_bull = BullMarketDecision(
            UNKNOWN, "无收盘数据", None, None, None,
            config_mod.BULL_SLOPE_LOOKBACK_WEEKS, config_mod.BULL_CLOSE_BUFFER,
        )
        return TargetPositionDecision(
            UNKNOWN, "无收盘数据", empty_bull, empty_enh, enhanced_position=UNKNOWN,
        )

    enhanced = evaluate_enhanced(close)
    bull = evaluate_bull_market(close)
    target = replay_target_position(enhanced, bull)
    enhanced_pos = replay_enhanced_position(enhanced)

    last = close.index[-1]
    enh_last: EnhancedDecision = enhanced.loc[last]
    bull_last: BullMarketDecision = bull.loc[last]
    state = str(target.loc[last])

    if state == UNKNOWN:
        reason = f"目标仓位重放后仍为UNKNOWN（牛市:{bull_last.status}/增强版:{enh_last.event}）"
    elif bull_last.status == BULL:
        reason = "牛市持有 → 目标持仓"
    else:
        reason = f"非牛市，增强版历史重放 → {state}"
    return TargetPositionDecision(
        state=state,
        reason=reason,
        bull=bull_last,
        enhanced=enh_last,
        enhanced_position=str(enhanced_pos.loc[last]),
    )
