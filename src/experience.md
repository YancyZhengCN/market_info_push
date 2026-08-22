# 开发经验沉淀（experience.md）

> 指数 MACD 买卖信号推送 —— 取数链路排查与 akshare 数据源改造经验

## 1. 背景

`src/main.py` 编排流程为：交易日判断 → 逐标的取数 → MACD 计算 → 信号判定 → Markdown 渲染 → 企微推送（dry-run 时仅本地打印）。
本次围绕「main.py 走不通」做了两轮排查：先修依赖导致的伪配置错误，再把取数源从东方财富直连改为真正调用 akshare（新浪 / 腾讯源）。

## 2. 关键问题与结论

### 2.1 伪装成「配置错误」的依赖缺失（高迷惑性）

- **现象**：`.env` 明明写了 `DATA_SOURCE=akshare` 且填了 `TUSHARE_TOKEN`，运行却报
  `DATA_SOURCE=tushare 但未设置 TUSHARE_TOKEN`。
- **根因**：运行环境未安装 `python-dotenv`，而 `config.py` 用 `try/except` **静默吞掉**了
  `import dotenv` 的失败，导致 `.env` 根本没被加载，所有变量走默认值（`DATA_SOURCE` 默认 `tushare`），
  最终撞上 `config.load()` 的 token 校验抛错。同时 `requests` 也缺失。
- **修复**：`pip install --user python-dotenv requests`（二者本就在 requirements.txt，只是运行环境没装）。
- **教训**：
  - 「静默吞异常」会把「依赖没装」误导成「配置写错」，排查成本极高。可选改进：dotenv 加载失败时打
    `warning` 日志，或启动时显式校验关键依赖。
  - 报错信息与实际配置矛盾时，优先怀疑「配置根本没生效（没加载）」，而非「配置值写错」。

### 2.2 东方财富行情接口在部分网络下被断连

- **现象**：装好依赖后主流程跑通，但 5 个标的取数全部 `RemoteDisconnected` / `Connection aborted`。
- **排查路径（逐层缩小）**：
  1. 基础网络正常：`baidu`、企微 `qyapi` 均返回 200。
  2. DNS 正常：`push2his.eastmoney.com` 能解析到 IP。
  3. 但行情接口域名 `push2his.eastmoney.com` / `push2.eastmoney.com` 连接直接被拒（`curl` HTTP 000），
     http/https、沙盒 / 非沙盒结果一致。
- **结论**：当前网络环境专门拦截了东方财富行情数据 API host（公司网络 / 防火墙对这类接口限流常见），
  **非代码 bug**。
- **临时验证手段**：`DEMO=true python3 main.py` 用确定性合成数据离线跑通全链路（取数→MACD→信号→渲染→dry-run）。

### 2.3 改造为 akshare（务必避开东方财富源）

- **坑**：akshare 里常用的 `index_zh_a_hist`、`fund_etf_hist_em` 等接口**底层仍走东方财富**，
  换了包却会踩同一个断连坑。
- **做法**：先写一次性探测脚本实测各接口连通性，最终选定**新浪 / 腾讯源**接口：

  | 标的类型 | indices.json 的 `api` | akshare 接口 | symbol 示例 |
  |---|---|---|---|
  | A股指数 | `index_daily` | `ak.stock_zh_index_daily` | `sh000300` / `sz399673` |
  | ETF | `fund_daily` | `ak.fund_etf_hist_sina` | `sh511260` |
  | 港股指数 | `index_global` | `ak.stock_hk_index_daily_sina` | `HSTECH` |

- **symbol 映射**（`tushare_client._ak_symbol`）：`000300.SH` → `sh000300`，`399673.SZ` → `sz399673`，
  ETF `511260.SH` → `sh511260`，港股 `HKTECH` → `HSTECH`（新浪港股指数专用代码，无市场前缀）。
- **统一约定**：所有接口返回统一处理为 `DatetimeIndex` 升序、去空的 `close` Series，取最近
  `max(lookback, 60)` 段，供 MACD/信号层消费。

## 3. 最终验证

`DATA_SOURCE=akshare`、`DEMO=false`、`FORCE_RUN=true` 下 `python3 main.py`：
5 个标的全部取到**真实行情**并算出信号，无一失败，dry-run 报告正常输出。

## 4. 可复用排查清单

1. 报错与配置矛盾 → 先确认 `.env` / 依赖是否真的加载生效（`python3 -c "import xxx"` 逐个验证）。
2. 取数失败 → 分层验证：基础网络（baidu）→ 目标域名 DNS → 目标接口 host 连通性（curl -w '%{http_code}'）。
3. 确认是网络拦截而非代码问题后，再决定「换源」而非「改代码逻辑」。
4. 换 akshare 源时，务必确认所选接口底层数据源（东方财富 / 新浪 / 腾讯），避开被拦的源。
5. 离线兜底：`DEMO=true` 合成数据可随时跑通全链路，用于验证「非取数环节」的代码正确性。

## 5. 环境备注

- 运行解释器：系统 `python3`（macOS 自带，`python` 命令不存在，需用 `python3`）。
- 依赖安装：`python3 -m pip install --user -r requirements.txt`（已含 `akshare>=1.14`）。
- `urllib3` 在 LibreSSL 下会打 `NotOpenSSLWarning`，不影响功能，可忽略。

## 6. 企业微信推送改造（externalcontact 客户群发）

### 6.1 原实现的真实 bug

- 旧 `notifier.py` 走 `POST /cgi-bin/message/send` 却传 `chat_id` 字段——该接口是**应用消息/内部**接口，
  只认 `agentid` + `touser/toparty/totag`，**根本不认 `chat_id`**，真去调必然报参数错误。
- `config.py` 加载了 `wecom_agentid` 却全程未使用；docstring 声称「客户群」，接口却用错——自相矛盾。

### 6.2 三种接口不可混用（选型即决定字段）

| 目标 | 接口 | 关键字段 |
|---|---|---|
| 内部成员/应用消息 | `/cgi-bin/message/send` | `agentid` + `touser`，msgtype 可 markdown |
| 内部群聊 | `/cgi-bin/appchat/create` + `/appchat/send` | `chatid`（需先建群） |
| 外部客户群发（本项目选用） | `/cgi-bin/externalcontact/add_msg_template` | `chat_type=group` + `chat_id_list` + `sender` |

### 6.3 externalcontact 客户群发的硬约束（接口本身，非取舍）

- **不支持 markdown**：仅 `text`(纯文本) + 附件(image/link/miniprogram/video/file)。日报 markdown 以纯文本送达。
- **`sender` 必填**：客户群发场景必须带发送成员 userid → 新增 `WECOM_SENDER` 配置。
- **异步 + 需人工确认**：创建成功仅返回 `msgid`，由成员/群主在企微端确认后才送达（官方防骚扰），非实时自动。
- 返回 `fail_list` 非空表示部分群失败，应向上暴露以便观测。

### 6.4 一并补齐的工程细节

- access_token 进程内缓存复用（技术方案 §5.2 要求，旧实现每次都重新换取）；`expires_in` 提前 5 分钟过期。
- token 失效（`40014`/`42001`）清缓存后自动刷新重试；其余 `errcode` 非 0 直接抛错、不静默。
- 推送必填校验从「token + 全部企微凭证」改为 externalcontact 实际所需的
  `WECOM_CORPID`/`WECOM_CORPSECRET`/`WECOM_CHAT_ID`/`WECOM_SENDER`（不再强制 TUSHARE_TOKEN，取数已可走 akshare）。
- 新增 `tests/test_notifier.py`：全程 mock 验证 payload 结构 / token 缓存 / 错误抛出 / dry-run 不联网。

### 6.5 教训

- 改第三方接口前先查**官方文档确认字段**，尤其外部接口字段与内部接口差异极大，凭记忆极易写错。
- 「配置字段加载了却没用到」往往是接口用错的信号，值得顺手核对。

## 7. 推送方案改为 Server酱（个人微信，免确认）

### 7.1 为什么弃用企微外部客户群发

- 企微外部客户群发（externalcontact）有**平台强制的人工确认机制**（防骚扰），且**仅纯文本**，
  不满足「免确认、实时自动、富文本」的诉求——这是企微政策，任何 API 参数都绕不过。
- 企微「免确认」的方案（群机器人 Webhook / 应用消息）只能触达**企业内部**群或成员，
  发不到含普通微信用户的场景。

### 7.2 三类「免确认」通道对比（每天 1 条日报场景）

| 方案 | 费用 | 免确认实时 | markdown | 触达对象 |
|---|---|---|---|---|
| 企微群机器人 Webhook | 免费 | ✅ | ✅ | 企业内部群 |
| 企微应用消息 message/send | 免费 | ✅ | ✅ | 企业内部成员 |
| **Server酱³（本项目选用）** | 免费额度够用 | ✅ | ✅ | 个人微信（服务号） |

### 7.3 Server酱接入要点

- 接口：`POST https://sctapi.ftqq.com/<SENDKEY>.send`，表单参数 `title` + `desp`（desp 支持 markdown）。
- 实现：`title` 取日报正文首行（去开头 `#`），`desp` 用完整 markdown 正文；返回 `code==0` 为成功。
- 配置：仅需 `SERVERCHAN_SENDKEY`（不再需要企微凭证）；`WECOM_*` 保留为备用。
- 限制：免费版有每日推送条数额度，超额限流；`code` 非 0 直接抛错、失败重试 1 次。
- `notifier.push_markdown` 对外签名不变，main 编排层无需改动；测试 `tests/test_notifier.py` 同步改为 Server酱用例。

### 7.4 教训

- 「能不能免确认自动推」本质由**推送受众**决定（内部 vs 外部微信用户），是产品决策而非纯技术问题，
  改接口前应先与用户确认受众，避免反复返工。

## 8. 云函数部署（每日定时）

本项目是「每天定时跑 1 次、跑完退出」的批处理，`main.py` 已提供 `main_handler(event, context)`，
天然适配云函数 + 定时触发器，零成本免运维。完整步骤见 `deploy/DEPLOY.md`。

### 8.1 最大的坑：跨平台二进制不兼容

- `numpy/pandas/lxml/curl_cffi` 含 C 扩展，**macOS 装的 `.so` 无法在云函数 Linux 运行**，
  直接打包上传会报 `invalid ELF header` / `ImportError`。
- 两种解法（仓库已提供脚本）：
  - `deploy/build_package_nodocker.sh`：`pip --platform manylinux2014_x86_64 --only-binary=:all:`
    直接拉 Linux wheel，**macOS 无需 Docker 即可打包**（已实测 numpy/pandas/lxml/curl_cffi 均有 wheel）。
  - `deploy/build_package.sh`：用 `python:3.9-slim` 容器装依赖（依赖只有源码包时用）。
- 产物 `function.zip` 为平铺结构，云函数入口填 `main.main_handler`。

### 8.2 部署关键配置

- 环境变量：`DATA_SOURCE=akshare` / `SERVERCHAN_SENDKEY` / `PUSH_ENABLED=true` / `FORCE_RUN=false`。
  生产必须 `PUSH_ENABLED=true`（真推）且 `FORCE_RUN=false`（交易日过滤生效）。
- 定时触发：工作日 14:30，SCF cron `0 30 14 ? * MON-FRI *`（7 段含秒），FC 为 `30 14 * * MON-FRI`（6 段）。
- **务必确认平台时区为 Asia/Shanghai**，否则错峰触发。
- 超时调到 120s（默认 3s 会因取数失败），内存 128–256MB。

### 8.3 已知限制

- 无 Tushare token 时 `is_trading_day` 退化为「仅判断工作日」，**不识别法定节假日**，
  节假日仍会推一条（数据为节前最后交易日）。要精确跳过需接入交易日历。
