"""通用重试工具：akshare 接口偶发网络抖动/限流，取数需重试几次再判失败。"""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger("index_signal")

T = TypeVar("T")

# 默认重试次数与间隔（秒）；间隔递增，避免对被限流的源立即重压
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = (0.5, 1.0, 2.0)


def call_with_retry(
    fn: Callable[[], T],
    what: str,
    retries: int = DEFAULT_RETRIES,
    backoff: tuple[float, ...] = DEFAULT_BACKOFF,
) -> T:
    """执行 fn，失败重试 retries 次（共尝试 retries 次）。全部失败则抛最后一次异常。

    - what：日志用的操作描述（如 "日线取数 sh000300"）。
    - backoff：每次重试前的等待秒数；用尽后用最后一个值。
    """
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as e:  # 网络/解析等偶发失败
            last_err = e
            if attempt < retries:
                wait = backoff[min(attempt - 1, len(backoff) - 1)]
                logger.warning(
                    "%s 第 %d/%d 次失败: %s，%.1fs 后重试",
                    what, attempt, retries, repr(e)[:80], wait,
                )
                time.sleep(wait)
            else:
                logger.warning("%s 共 %d 次均失败: %s", what, retries, repr(e)[:80])
    raise last_err or RuntimeError(f"{what} 失败（未知错误）")
