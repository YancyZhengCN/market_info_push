"""配置加载：环境变量 + indices.json 动态标的清单。

密钥（Tushare Token / 企微 corpid·secret·chat_id）仅来自环境变量，代码零硬编码。
监控标的（代码/接口/名称）外置为 indices.json，增删标的只改该文件。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 可选
    pass


class ConfigError(Exception):
    pass


@dataclass
class IndexConfig:
    name: str
    ts_code: str
    api: str = ""  # 可选；留空则按 ts_code 自动推断（见 _infer_api）
    lookback: int = 120
    basis: str = "daily"  # 判定依据周期：daily / 2d / weekly

    def __post_init__(self) -> None:
        # 未显式指定 api 时，按 ts_code 后缀/格式自动推断，用户无需感知接口细节
        if not self.api:
            self.api = self._infer_api()

    def _infer_api(self) -> str:
        """按 ts_code 推断取数接口类型：
        - AU9999 / 以 AU 开头   -> spot_sge     （上海金交所黄金现货，如黄金 AU9999）
        - .CSI 结尾            -> index_csi   （中证指数，如港股创新药 931787.CSI）
        - .SH / .SZ 结尾       -> index_daily （A股指数与 ETF 同走腾讯前复权，无需区分）
        - 其余（非数字代码，如 HKTECH） -> index_global（港股指数，新浪源）
        """
        code = self.ts_code.upper()
        if code.startswith("AU"):
            return "spot_sge"
        if code.endswith(".CSI"):
            return "index_csi"
        if code.endswith(".SH") or code.endswith(".SZ"):
            return "index_daily"
        return "index_global"

    def validate(self) -> None:
        allowed = {"index_daily", "index_global", "fund_daily", "index_csi", "spot_sge"}
        if self.api not in allowed:
            raise ConfigError(
                f"标的 {self.name} 的 api 非法: {self.api!r}，应为 {sorted(allowed)}"
            )
        if not self.ts_code:
            raise ConfigError(f"标的 {self.name} 缺少 ts_code")
        allowed_basis = {"daily", "2d", "weekly"}
        if self.basis not in allowed_basis:
            raise ConfigError(
                f"标的 {self.name} 的 basis 非法: {self.basis!r}，应为 {sorted(allowed_basis)}"
            )


@dataclass
class Config:
    tushare_token: str | None
    serverchan_sendkey: str | None  # 可逗号分隔多个 SendKey（发给多个收件人）
    push_enabled: bool
    log_level: str
    demo: bool
    data_source: str
    indices: list[IndexConfig]
    indices_url: str | None = None
    realtime_intraday: bool = True  # 盘中把实时价作为当天临时收盘价拼接，算动态 MACD

    @property
    def serverchan_sendkeys(self) -> list[str]:
        """把 serverchan_sendkey 按逗号拆成去空的 SendKey 列表（每个对应一个收件人）。"""
        if not self.serverchan_sendkey:
            return []
        return [k.strip() for k in self.serverchan_sendkey.split(",") if k.strip()]

    @classmethod
    def load(cls, indices_path: str | None = None) -> "Config":
        token = os.getenv("TUSHARE_TOKEN") or None
        sendkey = os.getenv("SERVERCHAN_SENDKEY") or None
        push_enabled = os.getenv("PUSH_ENABLED", "false").lower() == "true"
        demo = os.getenv("DEMO", "false").lower() == "true"
        log_level = os.getenv("LOG_LEVEL", "INFO")
        data_source = os.getenv("DATA_SOURCE", "tushare").lower()
        indices_url = os.getenv("INDICES_URL") or None
        realtime_intraday = os.getenv("REALTIME_INTRADAY", "true").lower() == "true"

        indices = cls._load_indices(indices_path, indices_url)
        for idx in indices:
            idx.validate()

        cfg = cls(
            tushare_token=token,
            serverchan_sendkey=sendkey,
            push_enabled=push_enabled,
            log_level=log_level,
            demo=demo,
            data_source=data_source,
            indices=indices,
            indices_url=indices_url,
            realtime_intraday=realtime_intraday,
        )

        # 真实推送（Server酱 → 个人微信）仅需 SendKey；免确认、支持 markdown
        if push_enabled and not demo and not sendkey:
            raise ConfigError("推送已开启但缺少环境变量: SERVERCHAN_SENDKEY")

        # 真实取数必须指定可用数据源；tushare 还需 token
        if not demo and data_source == "tushare" and not token:
            raise ConfigError("DATA_SOURCE=tushare 但未设置 TUSHARE_TOKEN（或改用 DATA_SOURCE=akshare 免 token）")
        return cfg

    @staticmethod
    def _load_indices(
        indices_path: str | None, indices_url: str | None
    ) -> list[IndexConfig]:
        if indices_url:
            import requests

            raw = requests.get(indices_url, timeout=10).json()
        else:
            p = Path(indices_path) if indices_path else (Path(__file__).parent / "indices.json")
            if not p.exists():
                p2 = Path.cwd() / "indices.json"
                p = p2 if p2.exists() else p
            if not p.exists():
                raise ConfigError(f"未找到标的清单文件: {p}")
            raw = json.loads(p.read_text(encoding="utf-8"))
        return [IndexConfig(**item) for item in raw]
