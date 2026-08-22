# 指数 MACD 买卖信号推送

按日频 MACD 柱（BAR）的日间变化，对一组指数 / ETF 生成买卖信号，渲染成 Markdown 日报并通过 Server酱推送到个人微信。支持本地运行与云函数入口。

## 功能概览

- **多标的监控**：标的清单外置于 `indices.json`，增删标的只改该文件。
- **双数据源**：`tushare`（需 token）/ `akshare`（新浪·腾讯源，免 token），另有 `DEMO` 合成数据离线兜底。
- **三周期 MACD**：日线（daily）/ 2日（隔行取样）/ 周线（W-FRI 重采样）。
- **信号规则**：按各标的配置的判定周期（`basis`：日/2日/周）的 MACD 柱较上一周期 **变多 → 买入**、**变少 → 卖出**、持平 → 未触发；其余周期并列展示，推送表格中对判定所依据的那一列加粗高亮。
- **推送**：**Server酱³**（`sctapi.ftqq.com`）推送到个人微信，免确认、实时、支持 markdown。`PUSH_ENABLED=false` 时仅本地打印（dry-run），不联网。

## 目录结构

```
src/
├── main.py            # 编排入口（本地 __main__ / 云函数 main_handler）
├── config.py          # 环境变量 + indices.json 加载与校验
├── tushare_client.py  # 取数层：tushare / akshare(新浪·腾讯) / 合成数据
├── macd.py            # MACD 计算（EMA12/26 → DIF/DEA → BAR）
├── signals.py         # 信号判定（BUY/SELL/HOLD/MISSING）
├── templates.py       # Markdown 日报渲染
├── notifier.py        # 企业微信推送（含 dry-run）
├── indices.json       # 监控标的清单
├── requirements.txt   # 依赖
├── .env.example       # 环境变量样例
└── tests/             # 单元测试
```

## 快速开始

### 1. 安装依赖

```bash
python3 -m pip install --user -r requirements.txt
```

> macOS 自带 `python3`（无 `python` 命令）。`urllib3` 在 LibreSSL 下的 `NotOpenSSLWarning` 可忽略。

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并按需填写：

```bash
cp .env.example .env
```

| 变量 | 说明 |
|---|---|
| `DATA_SOURCE` | `tushare`(需 token) / `akshare`(免 token，新浪·腾讯源) |
| `TUSHARE_TOKEN` | `DATA_SOURCE=tushare` 时必填 |
| `DEMO` | `true` 用合成数据跑通全流程（无需 token / 联网） |
| `PUSH_ENABLED` | `true` 才真实推送；`false` 仅本地打印（dry-run） |
| `FORCE_RUN` | `true` 跳过交易日判断（周末 / 调试预览用；生产务必 `false`） |
| `LOG_LEVEL` | 日志级别，默认 `INFO` |
| `SERVERCHAN_SENDKEY` | Server酱 SendKey，真实推送必填（到 https://sct.ftqq.com/ 登录获取） |
| `WECOM_*` | 企业微信凭证（备用，当前推送未使用） |

> 真实推送（`PUSH_ENABLED=true` 且非 DEMO）要求 `SERVERCHAN_SENDKEY` 已配置，否则启动即报错。

### 推送说明（重要）

采用 **Server酱³**（`POST https://sctapi.ftqq.com/<SENDKEY>.send`）把日报推送到**个人微信**：

- **免确认、实时自动**：无需人工确认，运行即推送。
- **支持 markdown**：`desp` 字段支持 markdown 语法，日报保留富文本格式（标题取正文首行，去掉开头 `#`）。
- **额度限制**：Server酱免费版有每日推送条数额度（每天 1 条日报通常够用），超额会被限流；`code` 非 0 直接抛错、不静默，失败重试 1 次。
- **触达对象**：Server酱通过服务号触达个人微信，需先在 https://sct.ftqq.com/ 关注并获取 SendKey。
- 企业微信相关 `WECOM_*` 变量作为备用保留，当前推送链路未使用。

### 3. 运行

```bash
cd src

# 免 token 真实取数（推荐，新浪·腾讯源）
DATA_SOURCE=akshare python3 main.py

# 离线合成数据，验证全链路
DEMO=true python3 main.py

# 用 tushare（需在 .env 配置 TUSHARE_TOKEN）
DATA_SOURCE=tushare python3 main.py
```

非交易日默认跳过；调试预览可临时设 `FORCE_RUN=true`。

## 数据源说明（重要）

- **推荐 `akshare` 免 token**，底层走**新浪 / 腾讯源**，规避东方财富行情接口在部分网络（公司网络 / 防火墙）下被断连的问题。
- akshare 各标的对应接口：

  | 标的类型 | `indices.json` 的 `api` | akshare 接口 | symbol 示例 |
  |---|---|---|---|
  | A股指数 | `index_daily` | `stock_zh_index_daily` | `sh000300` / `sz399673` |
  | ETF | `fund_daily` | `fund_etf_hist_sina` | `sh511260` |
  | 港股指数 | `index_global` | `stock_hk_index_daily_sina` | `HSTECH` |

- ⚠️ 不要改用 akshare 的 `index_zh_a_hist` / `fund_etf_hist_em` 等接口，它们底层仍是东方财富，会在受限网络下同样断连。

## 配置监控标的

编辑 `indices.json`，每项包含 `name` / `ts_code` / `api`（可选 `lookback`，默认 120）：

```json
[
  { "name": "沪深300",       "ts_code": "000300.SH", "api": "index_daily"  },
  { "name": "十年期国债ETF", "ts_code": "511260.SH", "api": "fund_daily"   },
  { "name": "恒生科技",       "ts_code": "HKTECH",    "api": "index_global" }
]
```

- `ts_code`：A股用 `代码.SH` / `代码.SZ`，港股恒生科技固定用 `HKTECH`。
- `api` 仅允许 `index_daily` / `index_global` / `fund_daily`。
- 也可用 `INDICES_URL` 从远程（对象存储）动态拉取清单。

## 运行测试

```bash
cd src && python3 -m pytest tests/ -v
```

## 云函数部署

入口函数：`main.py` 的 `main_handler(event, context)`。配置同上，通过环境变量注入密钥与开关。

## 免责声明

本信号仅供参考，不构成投资建议。
