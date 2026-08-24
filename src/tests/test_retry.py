"""重试工具测试：验证失败重试、最终成功/失败、次数控制（不 sleep 真实等待用 0 间隔）。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import retry_util


def test_success_first_try():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return 42
    assert retry_util.call_with_retry(fn, "x", retries=3, backoff=(0,)) == 42
    assert calls["n"] == 1  # 一次成功不重试


def test_succeed_after_failures():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"
    assert retry_util.call_with_retry(fn, "x", retries=3, backoff=(0, 0, 0)) == "ok"
    assert calls["n"] == 3  # 前两次失败，第三次成功


def test_all_fail_raises():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        raise ValueError("always")
    with pytest.raises(ValueError):
        retry_util.call_with_retry(fn, "x", retries=3, backoff=(0, 0, 0))
    assert calls["n"] == 3  # 共尝试 3 次


if __name__ == "__main__":
    test_success_first_try()
    test_succeed_after_failures()
    test_all_fail_raises()
    print("test_retry OK")
