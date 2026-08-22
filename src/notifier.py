"""Server酱推送（sctapi.ftqq.com → 个人微信）。

推送通道：Server酱³（Server酱 Turbo），把日报推送到**个人微信**。
- 免确认、实时自动送达；`desp` 支持 markdown 语法，日报可保留富文本格式。
- 接口：`POST https://sctapi.ftqq.com/<SENDKEY>.send`，表单参数 title + desp。
- 支持**多个收件人**：SERVERCHAN_SENDKEY 逗号分隔多个 SendKey（每个 key 对应一个微信），
  逐个发送，单个失败不影响其余收件人。
- PUSH_ENABLED=false 时仅本地打印（dry-run），不联网（requests 懒加载）。

注意：
- 每个收件人需各自登录 https://sct.ftqq.com/ 关注服务号、拿到自己的 SendKey。
- Server酱免费版有每日推送条数额度（每日 1 条日报通常够用），超额会被限流。
"""
from __future__ import annotations

import logging
import time

from config import Config

logger = logging.getLogger("index_signal")

_SEND_URL_TMPL = "https://sctapi.ftqq.com/{sendkey}.send"


def _split_title(content: str) -> tuple[str, str]:
    """从 markdown 正文取首行（去掉开头的 # 与空白）作为标题，整体作为 desp。"""
    first_line = ""
    for line in content.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            first_line = s
            break
    title = first_line or "指数MACD信号日报"
    # 微信标题过长会被截断，做个保守限制
    if len(title) > 100:
        title = title[:100]
    return title, content


def push_markdown(content: str, config: Config) -> dict | None:
    """把日报内容通过 Server酱推送到个人微信（dry-run 时仅本地打印）。

    支持多个 SendKey（多收件人）：逐个发送，单个失败仅记录日志、不阻断其余；
    全部失败时抛出异常。返回按 SendKey 前缀聚合的发送结果摘要。
    """
    if not config.push_enabled:
        print("=== [DRY-RUN] 以下为将要推送的 markdown（Server酱 → 个人微信）===")
        print(content)
        print("=== [DRY-RUN] 结束 ===")
        return None

    sendkeys = config.serverchan_sendkeys
    if not sendkeys:
        raise RuntimeError("未配置 SERVERCHAN_SENDKEY，无法推送")

    title, desp = _split_title(content)
    results: dict[str, str] = {}
    last_err: Exception | None = None
    success = 0
    for key in sendkeys:
        masked = key[:8] + "***"  # 日志脱敏，避免泄露完整 SendKey
        try:
            _post_with_retry(key, title, desp)
            results[masked] = "ok"
            success += 1
        except Exception as e:  # 单个收件人失败不影响其余
            results[masked] = f"fail: {e}"
            last_err = e
            logger.error("Server酱推送失败（收件人 %s）: %s", masked, e)

    logger.info("Server酱推送完成：成功 %d / 共 %d", success, len(sendkeys))
    if success == 0:
        raise last_err or RuntimeError("Server酱推送全部失败")
    return {"total": len(sendkeys), "success": success, "results": results}


def _post_with_retry(sendkey: str, title: str, desp: str, retries: int = 1) -> dict:
    """POST 到 Server酱，失败重试（默认 1 次，间隔 5s）；code!=0 视为失败。"""
    import requests

    url = _SEND_URL_TMPL.format(sendkey=sendkey)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, data={"title": title, "desp": desp}, timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("code", 0) == 0:
                return data
            raise RuntimeError(f"Server酱推送失败: {data}")
        except Exception as e:  # 网络异常 / code 非 0
            last_err = e
        if attempt < retries:
            time.sleep(5)
    raise last_err or RuntimeError("Server酱推送失败（未知错误）")
