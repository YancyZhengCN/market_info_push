"""盘中实时价拼接测试：_maybe_append_spot 的拼接与降级逻辑（不联网，mock 实时价）。"""
import datetime as dt
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as config_mod
import realtime_client
import tushare_client as ts_client


def _daily_series(last_date: dt.date, n: int = 5):
    """构造以 last_date 结尾的日线 close 序列。"""
    idx = pd.to_datetime([last_date - dt.timedelta(days=i) for i in range(n)][::-1])
    return pd.Series([10.0 + i for i in range(n)], index=idx)


def _cfg(realtime=True):
    return config_mod.Config(
        tushare_token=None, serverchan_sendkey=None, push_enabled=False,
        log_level="INFO", demo=False, data_source="akshare", indices=[],
        realtime_intraday=realtime,
    )


def _idx():
    return config_mod.IndexConfig(name="测试", ts_code="000300.SH")


def test_append_spot_when_intraday(monkeypatch):
    """末行<今天 + 有实时价 → 追加今天临时收盘价，长度 +1。"""
    monkeypatch.setattr(realtime_client, "get_spot", lambda index: 99.9)
    close = _daily_series(dt.date.today() - dt.timedelta(days=1))
    out = ts_client._maybe_append_spot(close, _idx(), _cfg())
    assert len(out) == len(close) + 1
    assert out.index[-1].date() == dt.date.today()
    assert float(out.iloc[-1]) == 99.9
    print("PASS test_append_spot_when_intraday")


def test_intraday_no_spot_raises(monkeypatch):
    """盘中实时价取不到（None）→ 抛异常（标记 MISSING），绝不回退上一交易日日线。"""
    monkeypatch.setattr(realtime_client, "get_spot", lambda index: None)
    close = _daily_series(dt.date.today() - dt.timedelta(days=1))
    with pytest.raises(Exception):
        ts_client._maybe_append_spot(close, _idx(), _cfg())
    print("PASS test_intraday_no_spot_raises")


def test_switch_off(monkeypatch):
    """REALTIME_INTRADAY 关闭 → 不取实时价、不追加。"""
    called = {"n": 0}
    def _spy(index):
        called["n"] += 1
        return 99.9
    monkeypatch.setattr(realtime_client, "get_spot", _spy)
    close = _daily_series(dt.date.today() - dt.timedelta(days=1))
    out = ts_client._maybe_append_spot(close, _idx(), _cfg(realtime=False))
    assert len(out) == len(close)
    assert called["n"] == 0  # 关闭时根本不调用实时接口
    print("PASS test_switch_off")


def test_already_today_no_append(monkeypatch):
    """末行已是今天（收盘后日 K 已生成）→ 不追加。"""
    called = {"n": 0}
    def _spy(index):
        called["n"] += 1
        return 99.9
    monkeypatch.setattr(realtime_client, "get_spot", _spy)
    close = _daily_series(dt.date.today())
    out = ts_client._maybe_append_spot(close, _idx(), _cfg())
    assert len(out) == len(close)
    assert called["n"] == 0
    print("PASS test_already_today_no_append")


def test_non_trading_day_uses_prev_close(monkeypatch):
    """今天非交易日 → 不取实时价、不追加，直接用上一交易日收盘（序列不变）。"""
    called = {"n": 0}
    def _spy(index):
        called["n"] += 1
        return 99.9
    monkeypatch.setattr(realtime_client, "get_spot", _spy)
    close = _daily_series(dt.date.today() - dt.timedelta(days=1))
    out = ts_client._maybe_append_spot(close, _idx(), _cfg(), today_is_trading=False)
    assert len(out) == len(close)
    assert out.index[-1].date() == (dt.date.today() - dt.timedelta(days=1))
    assert called["n"] == 0  # 非交易日根本不调用实时接口
    print("PASS test_non_trading_day_uses_prev_close")


def test_is_trading_day_akshare_calendar(monkeypatch):
    """无 token 时用 akshare 交易日历识别节假日；接口异常则退化为仅工作日。"""
    import types

    # mock akshare.tool_trade_date_hist_sina：只含 2025-09-30 为交易日
    fake_df = pd.DataFrame({"trade_date": ["2025-09-30"]})
    fake_ak = types.SimpleNamespace(tool_trade_date_hist_sina=lambda: fake_df)
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    assert ts_client.is_trading_day(dt.date(2025, 9, 30), None, "akshare") is True
    # 2025-10-01 是周三工作日，但不在日历里 → 识别为节假日（非交易日）
    assert ts_client.is_trading_day(dt.date(2025, 10, 1), None, "akshare") is False

    # 日历接口异常 → 退化为仅工作日：周三 True、周六 False
    def _boom():
        raise RuntimeError("network down")
    monkeypatch.setitem(sys.modules, "akshare", types.SimpleNamespace(tool_trade_date_hist_sina=_boom))
    assert ts_client.is_trading_day(dt.date(2025, 10, 1), None, "akshare") is True   # 周三工作日
    assert ts_client.is_trading_day(dt.date(2025, 10, 4), None, "akshare") is False  # 周六
    print("PASS test_is_trading_day_akshare_calendar")


if __name__ == "__main__":
    import types
    class _MP:
        def setattr(self, obj, name, val): setattr(obj, name, val)
        def setitem(self, obj, name, val): obj[name] = val
    test_append_spot_when_intraday(_MP())
    test_intraday_no_spot_raises(_MP())
    test_switch_off(_MP())
    test_already_today_no_append(_MP())
    test_non_trading_day_uses_prev_close(_MP())
    test_is_trading_day_akshare_calendar(_MP())
    print("test_realtime OK")
