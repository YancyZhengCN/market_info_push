"""notifier 推送测试：验证 Server酱 payload、标题提取与失败处理（全程 mock，不联网）。"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as config_mod
import notifier as notifier_mod


def _cfg(push_enabled=True):
    return config_mod.Config(
        tushare_token=None,
        serverchan_sendkey="SCTtest",
        push_enabled=push_enabled,
        log_level="INFO",
        demo=False,
        data_source="akshare",
        indices=[],
    )


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_dry_run_no_network():
    """PUSH_ENABLED=false 时仅打印、返回 None、不触发任何 requests 调用。"""
    fake_requests = mock.Mock()
    with mock.patch.dict(sys.modules, {"requests": fake_requests}):
        assert notifier_mod.push_markdown("hello", _cfg(push_enabled=False)) is None
    fake_requests.post.assert_not_called()
    print("PASS test_dry_run_no_network")


def test_push_payload_and_title():
    """真实推送走 sctapi，URL 含 sendkey，title 取首行去 #，desp 为完整正文。"""
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return _Resp({"code": 0, "message": "", "data": {"pushid": "123"}})

    content = "# 📊 指数MACD信号日报 (2026-08-22)\n\n## 🟢 今日买入信号\n- 无"
    fake_requests = mock.Mock(post=fake_post)
    with mock.patch.dict(sys.modules, {"requests": fake_requests}):
        data = notifier_mod.push_markdown(content, _cfg())

    assert data["total"] == 1 and data["success"] == 1
    assert captured["url"] == "https://sctapi.ftqq.com/SCTtest.send"
    assert captured["data"]["title"] == "📊 指数MACD信号日报 (2026-08-22)"  # 去掉了开头的 #
    assert captured["data"]["desp"] == content  # 完整 markdown 作为正文
    print("PASS test_push_payload_and_title")


def test_multi_sendkey():
    """多个 SendKey（逗号分隔）应逐个发送，命中每个收件人各一次。"""
    cfg = _cfg()
    cfg.serverchan_sendkey = "SCTaaa, SCTbbb"  # 含空格，验证会被 strip
    urls = []

    def fake_post(url, data=None, timeout=None):
        urls.append(url)
        return _Resp({"code": 0})

    fake_requests = mock.Mock(post=fake_post)
    with mock.patch.dict(sys.modules, {"requests": fake_requests}):
        data = notifier_mod.push_markdown("正文", cfg)

    assert data["total"] == 2 and data["success"] == 2
    assert urls == [
        "https://sctapi.ftqq.com/SCTaaa.send",
        "https://sctapi.ftqq.com/SCTbbb.send",
    ]
    print("PASS test_multi_sendkey")


def test_partial_failure_not_block():
    """多收件人时单个失败不阻断其余：一个成功一个失败仍返回，success=1。"""
    cfg = _cfg()
    cfg.serverchan_sendkey = "SCTok,SCTbad"

    def fake_post(url, data=None, timeout=None):
        if "SCTbad" in url:
            return _Resp({"code": 40001, "message": "bad pushkey"})
        return _Resp({"code": 0})

    fake_requests = mock.Mock(post=fake_post)
    with mock.patch.dict(sys.modules, {"requests": fake_requests}), \
         mock.patch.object(notifier_mod.time, "sleep"):  # 跳过失败重试的 5s 等待
        data = notifier_mod.push_markdown("正文", cfg)

    assert data["total"] == 2 and data["success"] == 1
    print("PASS test_partial_failure_not_block")


def test_code_nonzero_raises():
    """唯一收件人 code 非 0（全部失败）应抛出，不静默。"""
    def fake_post(url, data=None, timeout=None):
        return _Resp({"code": 40001, "message": "bad pushkey"})

    fake_requests = mock.Mock(post=fake_post)
    raised = False
    with mock.patch.dict(sys.modules, {"requests": fake_requests}), \
         mock.patch.object(notifier_mod.time, "sleep"):  # 跳过失败重试的 5s 等待
        try:
            notifier_mod.push_markdown("x", _cfg())
        except RuntimeError:
            raised = True
    assert raised
    print("PASS test_code_nonzero_raises")


if __name__ == "__main__":
    test_dry_run_no_network()
    test_push_payload_and_title()
    test_multi_sendkey()
    test_partial_failure_not_block()
    test_code_nonzero_raises()
    print("test_notifier OK")
