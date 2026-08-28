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

## 9. 取数性能优化（单次运行 27s → 4.4s）

> 用户反馈「现在跑一次比以前久」，排查后定位并修复。

### 9.1 定位方法

- 写一次性计时脚本，**逐标的**打印取数耗时，而非只看总时长，一眼看出瓶颈集中在腾讯前复权源
  （`stock_zh_a_hist_tx`）的几个标的（单标的 3–11s），新浪/中证源都在 1s 内。

### 9.2 根因与两处优化

- **根因**：腾讯源请求写死 `start_date=19900101`、`end_date=20500101`，**每次拉全量历史**
  （沪深300 约 5000+ 行、10s），最后才 `.tail(120)`。纯属浪费——MACD 只需约 120 根预热。
- **优化① 有界日期范围**（`tushare_client._get_close_akshare`）：按
  `start = today - (max(lookback,60)*2+40) 天` 只拉最近约一年（几百行），单标的 10s → ~1s。
- **优化② 并发取数**（`main.py`）：把单标的处理抽成 `_process_index()`，用
  `ThreadPoolExecutor(max_workers=min(8, 标的数)).map(...)` 并发。取数是网络 IO，GIL 不阻塞等待，
  总耗时≈最慢标的而非累加。`map` 保序，输出顺序与 `indices.json` 一致；单标的异常在函数内降级为 MISSING。

### 9.3 关键验证：有界范围不影响信号

- 实测「有界范围」vs「全历史」的 daily/2d/weekly 三周期 BAR **数值完全一致**（含对复权最敏感的国债 ETF），
  判定不受影响。原因：MACD 只看相对变化，预热 120+ 根即收敛。改性能优化时**务必做这类等价性验证**再上线。

## 10. 数据源扩展经验

### 10.1 复权口径踩坑（国债 ETF）

- 用户反馈国债 ETF 的 MACD 与同花顺/新浪 App 不符。根因是**复权口径**：ETF 有分红，不复权会使历史
  价偏高、MACD 偏大（国债ETF 不复权 BAR≈0.05，前复权≈0.01）。
- 修复：A股指数与 ETF 统一改用腾讯源 `ak.stock_zh_a_hist_tx(adjust='qfq')`（**前复权**），对齐主流 App。
  指数无分红、前复权值同原始，故指数/ETF 可共用同一接口（`api=index_daily`）。
- experience §2.3 旧表里的 `stock_zh_index_daily`/`fund_etf_hist_sina` 已被此方案取代。

### 10.2 新增标的的通用套路（以黄金 AU9999 为例）

不同资产类别取数接口不同，新增「非股票/指数/ETF」标的时按此套路：

1. **先实测接口**：写探测脚本确认接口名、symbol 写法、返回列名。黄金用
   `ak.spot_hist_sge(symbol='Au99.99')`（上海金交所官网源，返回 `date/open/close/low/high`）。
2. **加 api 类型**：`config.py` 的 `_infer_api` 加推断规则（`AU` 开头 → `spot_sge`）+ `validate` 白名单。
   ⚠️ 注意推断顺序：黄金 `AU9999` 无 `.SH/.SZ/.CSI` 后缀，若不显式识别会落到默认的 `index_global`（港股）被误判。
3. **加取数分支**：`tushare_client._get_close_akshare` 加 `spot_sge` 分支 + symbol 映射辅助函数
   （`AU9999` → `Au99.99`），统一返回 `DatetimeIndex` 升序、去空的 close Series。
4. **加测试 + 跑 dry-run**：`test_config` 补 api 推断用例；端到端 dry-run 确认标的出现在推送中。
- 已支持 api 类型：`index_daily`（A股指数/ETF，腾讯前复权）、`index_global`（港股，新浪）、
  `index_csi`（中证指数，官网源）、`spot_sge`（金交所黄金现货）。
- 黄金现货**无复权概念**，直接用现货收盘价算 MACD。
- 北证50（`899050.BJ`）同样走 `index_daily`：腾讯日线 symbol 为 `bj899050`；新浪指数实时全量接口
  不收录它，盘中改用 `stock_zh_a_minute(symbol="bj899050")` 的最后一根分钟 close。配置的代码
  自动推断需将 `.BJ` 与 `.SH`/`.SZ` 一起映射到 `index_daily`。

## 11. 推送渲染样式经验（Server酱 markdown）

### 11.1 ⭐ 表格超屏与「全角括号换行断点」（最易重踩的坑）

- **现象**：把单元格前值括号从全角 `（）` 改成半角 `()` 后，表格在手机上**超出屏宽**、「标的」列被挤出可视区、出现横向滚动。
- **根因**：全角 `（）` 是 **CJK 字符，给渲染器提供了换行断点**，单元格能自然折成「当前值↑ / （前值）」两行、宽度更窄；
  半角 `()` 与数字连成一串 **ASCII 不易断行**，把列撑宽导致整表超屏。
- **结论**：单元格括号**必须用全角 `（）`**（已在 `templates._fmt_cell` 注释里锁定原因，防再次踩坑）。
  这是本项目「窄屏适配」的隐性依赖，不是随意的风格选择。
- **彻底根治超屏**（若全角仍不够）：只能减少表格内容宽度——去掉括号前值/去掉某列（如 2日/价格），无法靠 CSS，
  因为 Server酱会过滤 HTML/style。

### 11.2 Server酱渲染的能力边界（关掉不了的样式）

- 表格的**表头灰底 + 数据行斑马纹**是 Server酱把 markdown 渲染成 `<table>` 时**自带的 CSS 主题**，
  markdown 语法里没有「背景色」，也无法注入 CSS 覆盖 → **去不掉**。要无底色只能弃用表格改纯文本排版（丢列对齐）。
- 同理 `<br>`/`<font>` 等 HTML 标签会被当纯文本原样显示 → 换行用不了、高亮不能标红，**判定列高亮只能用 markdown 加粗**。
- 表格对齐由分隔行冒号控制：`:---:` 居中 / `:---` 左 / `---:` 右 / `---` 默认(左)。本项目用 `:---:` 全列居中。

### 11.3 本轮其他样式调整（均已同步产品/技术方案）

- 判定规则文案统一为「根据日/2日/周MACD识别买入或卖出」（旧文案「日线较前一日变多→买入」已与多周期 `basis` 判定矛盾）。
- 表头 `日MACD/2日MACD/周MACD` 精简为 `日/2日/周`（进一步省宽度）。
- 买入/卖出小标题去掉「（日MACD柱变多/变少）」限定，避免与按 `basis` 判定的语义冲突。
- 「未触发/数据缺失」分块**仅在存在此类标的时才展示**（`other` 为空则整块省略，不再输出「- 无」）。

## 12. 协作与工程流程约定

- **改代码后不自动 `git push`、不自动重打包 `function.zip`**；两者仅在用户明确说「push」「打包」时执行（用户统一安排时机）。
  本地改代码、同步文档、跑测试可照常进行。
- **需求变更三同步**：代码、产品方案、技术方案必须同时改，文档里的 TODO/待办要反映真实进度（区分「已完成」与「后续迭代」）。
- **目录结构**：项目更名为 `market_info_push`；纯文档（README/experience/方案）放根目录（GitHub 首页渲染），
  但 `deploy/` 与 `tests/` **必须留在 `src/` 内**——打包脚本靠「上一级即源码目录」定位、测试靠 `sys.path` 指父目录，移出会断路径依赖。
- **重打包提速**：依赖未变时可复用 `dist/build/` 的 Linux wheel，只 `cp *.py indices.json` 刷新业务代码后重打 zip，
  免去重新下载依赖；打包前校验 `dist/build` 无 Mach-O（`file *.so | grep mach-o`）。
