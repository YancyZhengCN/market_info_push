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


if __name__ == "__main__":
    import types
    class _MP:
        def setattr(self, obj, name, val): setattr(obj, name, val)
    test_append_spot_when_intraday(_MP())
    test_intraday_no_spot_raises(_MP())
    test_switch_off(_MP())
    test_already_today_no_append(_MP())
    print("test_realtime OK")
