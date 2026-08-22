# 云函数部署指南（每日定时推送）

把「指数 MACD 信号推送」部署到云函数 + 定时触发器，**零成本、免运维、不怕关机漏推**。
适合本项目「每天定时跑 1 次、跑完退出」的批处理特性。

> 平台推荐：**腾讯云 SCF** 或 **阿里云函数计算 FC**（选**国内区域**，保证能访问新浪财经 / Server酱）。
> 下面以腾讯云 SCF 为主线，阿里云 FC 差异在末尾标注。

---

## 0. 为什么不能直接把本地代码传上去（重要）

本项目依赖 `numpy / pandas / lxml / curl_cffi`（akshare 间接依赖）都含 **C 扩展二进制**。
你在 **macOS** 上装的 `.so` 文件**无法在云函数的 Linux 环境运行**，直接上传会报
`ImportError` / `invalid ELF header`。

**解决**：用仓库提供的打包脚本在 Linux 兼容环境安装依赖再打包——
[deploy/build_package_nodocker.sh](./build_package_nodocker.sh)（免 Docker，推荐）或
[deploy/build_package.sh](./build_package.sh)（Docker）。

---

## 1. 构建部署包

有两种方式，**任选其一**产出 `src/dist/function.zip`（入口 `main.main_handler`）。

### 方式 A：免 Docker（推荐，你的 macOS 可直接用）

用 pip 直接下载 Linux 平台 wheel，无需 Docker。已实测 numpy/pandas/lxml/curl_cffi 均能拉到
`manylinux2014_x86_64` wheel。

```bash
cd src
bash deploy/build_package_nodocker.sh
# 云函数是 ARM 架构时：把脚本里 PLATFORM 改为 manylinux2014_aarch64
```

### 方式 B：Docker（依赖有源码包、方式 A 失败时用）

前置：本机装好 Docker（当前这台机器**未安装** Docker，若要用此方式需先装）。

```bash
cd src
bash deploy/build_package.sh
```

两个脚本都会：
1. 把 `requirements.txt` 依赖装到 `dist/build/`（**Linux 二进制**）；
2. 拷贝业务 `*.py` + `indices.json`（排除测试/缓存/`.env`）；
3. 打成平铺结构的 `function.zip`（依赖与 `main.py` 同级，云函数可直接 import）。

> 云函数运行时选 Python 3.10 时：方式 A 用 `PY_VER=310`，方式 B 用 `PY_VER=3.10`，保持一致。

---

## 2. 创建云函数（腾讯云 SCF）

1. 控制台 → 云函数 SCF → 新建 → **自定义创建**。
2. 运行环境：**Python 3.9**（与打包一致）。
3. 提交方法：**本地上传 zip 包**，上传 `dist/function.zip`。
4. **执行入口**：`main.main_handler` ← 注意是 `main` 模块的 `main_handler` 函数。
5. **超时时间**：改为 **120 秒**（默认 3s 会因取数超时失败）。
6. **内存**：128–256 MB 足够。

---

## 3. 配置环境变量（不要写进代码/zip）

在函数「环境变量」里配置（等价于本地 `.env`，但**云端只放需要的**）：

| 变量 | 值 | 说明 |
|---|---|---|
| `DATA_SOURCE` | `akshare` | 免 token，走新浪/腾讯源 |
| `SERVERCHAN_SENDKEY` | `SCTxxx` 或 `SCTa,SCTb` | 推送 key，多人用逗号分隔 |
| `PUSH_ENABLED` | `true` | **生产必须 true 才真实推送** |
| `FORCE_RUN` | `false` | **生产必须 false**，让交易日过滤生效 |
| `LOG_LEVEL` | `INFO` | 可选 |

> - 用 akshare 就**不需要** `TUSHARE_TOKEN`；企微 `WECOM_*` 当前链路用不到，可不配。
> - `.env` 不上传云端；`build_package.sh` 已排除它。云函数以「环境变量配置」为准。

---

## 4. 配置定时触发器

需求：工作日每天推送 **3 次**——**10:00、11:45、14:30**。

> 代码无状态，触发几次就推几次，**改触发频率不用改代码、不用重新打包**，只在平台加/改触发器即可。
> 因这 3 个时间点的「分钟」各不相同（00 / 45 / 30），**无法用一条 cron 合并**，需建 **3 个定时触发器**。

1. 函数 → 触发管理 → 新建 → 类型「**定时触发**」，按下表各建一个。
2. **Cron 表达式**（腾讯云 SCF 为 7 段，含秒）：

   | 触发器 | 时间 | Cron 表达式 |
   |---|---|---|
   | 触发器 1 | 工作日 10:00 | `0 0 10 ? * MON-FRI *` |
   | 触发器 2 | 工作日 11:45 | `0 45 11 ? * MON-FRI *` |
   | 触发器 3 | 工作日 14:30 | `0 30 14 ? * MON-FRI *` |

3. ⚠️ **时区**：务必确认触发器/函数时区为 **UTC+8（Asia/Shanghai）**，否则会错峰。
   SCF 定时触发器默认按北京时间，阿里云 FC 需在 cron 里显式指定时区（见末尾）。

> 推送时点说明：10:00 / 11:45 / 14:30 取到的都是**盘中快照**数据，非收盘确定值——同一天
> 3 次推送的信号可能随盘中行情变化而不同，这是预期。若想要收盘后确定信号，需把时间改到
> **15:00 收盘之后**（技术方案 §9 原按 14:30 单次）。

---

## 5. 验证

- **手动测试**：函数控制台点「测试」，用空事件 `{}` 触发一次。
- **看日志**：SCF 运行日志 / CLS 里应看到：
  ```
  运行日期 ... | 标的数 5 | ... | push=True | source=akshare
  标的 沪深300 → SELL ...
  Server酱推送完成：成功 N / 共 N
  ```
- **看微信**：配置的 SendKey 对应微信应收到日报。
- 若当天是非交易日且 `FORCE_RUN=false`，会打印「非交易日，跳过推送」并正常退出（这是预期）。
  想在非交易日也测试，可临时把 `FORCE_RUN` 设 `true` 手动触发验证，验证完改回 `false`。

---

## 6. 交易日历说明（akshare 场景）

`is_trading_day` 在无 Tushare token 时**退化为「仅判断是否工作日」**（周一至周五即视为交易日），
**不识别法定节假日**。这意味着：**国庆/春节等节假日，若 `PUSH_ENABLED=true` 仍会推送一条**
（数据为节前最后交易日的值）。若要精确跳过法定节假日，需接入交易日历（配 Tushare token 或
用 akshare 的 `tool_trade_date_hist_sina`）。当前实现的取舍已记录在 experience.md。

---

## 7. 阿里云 FC 差异

- 入口写法：FC 的 handler 为 `main.main_handler`，签名 `(event, context)` 已兼容。
- 依赖：同样用 `build_package.sh` 产物；或用 FC 的「层」功能挂依赖。
- 定时触发器 cron 为 **6 段**（无秒），同样建 3 个，并在触发器配置里设时区 `Asia/Shanghai`
  （FC 支持在 cron 前加 `CRON_TZ=Asia/Shanghai` 或在控制台选时区）：
  - 10:00 → `0 10 * * MON-FRI`
  - 11:45 → `45 11 * * MON-FRI`
  - 14:30 → `30 14 * * MON-FRI`
- 超时同样调到 120s。

---

## 8. 成本

每工作日 3 次、每次约 1 分钟、128MB 内存，**仍远在腾讯云/阿里云函数的每月免费额度内**，实际几乎零成本。
（注意 Server酱免费版有每日推送条数额度：一天 3 条通常仍够用，超额会被限流。）

---

## 附：更新代码后如何重新部署

```bash
cd src
bash deploy/build_package.sh          # 重新打包
# 控制台上传新的 dist/function.zip，或用 CLI：
# scf deploy / 阿里云 s deploy（若已配置 Serverless 工具链）
```
环境变量改动无需重新打包，直接在控制台改即可。
