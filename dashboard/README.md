# FinFeed 本机自选股平台

按需求实现 8 组指标、20 个数值列，加上 Ticker、Name 和交易日期。仅监听 `127.0.0.1`，无账户登录、无付费平台权限绕过、无 API 密钥。

## 使用

双击 `start.command`，或在仓库根目录运行：

```sh
./dashboard/start.command
```

启动后在默认浏览器打开 <http://127.0.0.1:8765>。关闭服务终端或按 Control-C 停止。已有 FinFeed 服务运行时，启动脚本直接打开页面，不重复启动。

首次运行需要 Python 3.11+ 和联网安装依赖。依赖固定为 yfinance 1.7.0；环境保存在被 Git 忽略的 `.venv/`。默认提供 AAPL、NVDA、MU、AMD、VRT、LRCX、VOO、QQQM，可添加 / 移除股票并按指标排序。Ticker 可以逗号或空格分隔，最多 40 个。

自选股只存在本机浏览器 localStorage。缓存存在 `.cache/`，不提交 Git。页面打开期间，每 60 秒自动刷新一次；手动刷新同样可用。自动 / 手动刷新绕过 15 分钟的普通读取缓存，5 秒内的重复请求合并，最多同时请求 2 个标的。上一轮仍在运行时跳过该次定时触发，避免请求堆积；网络失败保留已有快照并标记旧数据。关闭页面后停止刷新，浏览器后台节流或电脑休眠可能延迟定时器。刷新频率不改变 Yahoo 行情本身的延迟。

## 数据来源与限制（核验于 2026-10-03，Asia/Shanghai）

- 行情、财务和分析师预期：Yahoo Finance，经 [yfinance](https://ranaroussi.github.io/yfinance/) 读取。该项目并非 Yahoo 官方 SDK，适用于个人研究，数据的使用范围仍受供应商条款约束；不承诺实时、持续可用或覆盖所有市场。
- 原始来源入口：[SEC EDGAR](https://www.sec.gov/edgar/search/)、[SEC API 文档](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)。当前网络对 SEC Company Facts 的实际测试返回 HTTP 403，所以第一版使用 C 级 Yahoo 聚合财务值，不把它们标为直接提取的 SEC 数据。
- 每个标的提供北京时间检索时间、报价原始 UTC 时间、交易所时区、财季结束日期和逐字段来源。申报日期未从免费源可靠获得，因此明确缺失并提供 SEC 核对入口；数据期末不是公告日期。
- ETF 的公司 EPS、公司债务、营收和 FCF 不适用；ETF 的 P/E 也未用持仓加权或基金商估值替代。`BTC` 是 Grayscale Bitcoin Mini Trust 的 ETF 代码；BTC 现货应使用 `BTC-USD`，两者不能混用。
- 海外上市证券需输入 Yahoo 的完整代码，例如 `000660.KS`。报价币种和财务币种分别显示，金额不自动换成美元。不得把不同股票类别 / ADR / 本地上市证券静默合并。

## 指标口径

| 指标 | 数据或计算方式 |
| --- | --- |
| Ticker / Name / Market Cap | Yahoo 证券信息和公司市值；ETF 不用 AUM 替代市值 |
| Last Price / 52W High / Low | 常规交易时段最近成交价和供应商 52 周高低点，不混入盘后价 |
| Diluted EPS Q0 / Q−1 | 最新已披露财季与紧接的上一财季利润表 `DilutedEPS`；通常为 GAAP，实际取供应商口径 |
| Forward EPS Q0 | Yahoo `earningsTrend` 当前预测财季 `0q` 的分析师平均值；与已披露 Q0 可能不是同一季度，也可能是调整后 EPS；提供财季结束日期和分析师数量 |
| P/E LTM | Last Price / Yahoo `trailingEps`，不保证与表中四季 GAAP EPS 之和相同；EPS≤0 时不适用；币种不同则缺失 |
| P/E NTM | 应为 Last Price / 未来连续四个财季的同口径 EPS 预期之和；免费源当前不完整，明确缺失，不使用年度 `forwardPE` 冒充 |
| Avg Volume 10 | 比较日以前 10 个完整交易日成交股数均值，排除比较日本身 |
| Volume vs. 10 | 比较日完整日成交股数 / 此前 10 日均量；盘中待收盘，非交易日明确显示最近交易日期 |
| Revenue Q0 | 最新披露单季 TotalRevenue |
| Debt Q0 | 最新披露财季末 TotalDebt；取供应商分类，租赁负债等口径跨公司可能不同 |
| FCF Q0 | 单季 OperatingCashFlow − 单季资本支出（支出取正数）；计算的非 GAAP 指标 |
| 各项 Growth Q0 / Q−1 | 默认同比 = 本期 / 上年同期 − 1；上年同期日期允许±15天以匹配非日历财季；基期≤0或缺失时不计算 |

Yahoo 日线请求 `auto_adjust=False`，不做股息总回报调整，拆股处理遵循供应商。历史期数有限，只有 5 个财季时可以算 Q0 同比，却无法算 Q−1 同比；绝不将缺失值设为零，也不使用不同财季或不同财务口径填补。

表格点击行可查看计算输入、日期、币种、来源和缺失原因。网页里的“本季度”统一解释为最近已披露财季，并不假设当前日历季度已经发布。

## 验证与结构

```sh
cd dashboard
.venv/bin/python -m unittest test_metrics.py
node --check public/app.js
```

- `server.py`：本机 HTTP 服务和输入限制。
- `data.py`：数据源适配、日期与币种、逐项来源、缓存和失败恢复。
- `metrics.py`：同比、同年财季匹配、P/E 和完整日量比。
- `public/`：原生网页，不依赖前端构建。

后续可接 SEC 财务解析或有授权的四季预测 API。公开部署之前需要重新核对数据许可、服务器访问控制和缓存范围；当前版本的个人研究数据不作为公共网站数据接口。

2026-10-03 本地验证：8 个默认标的全部取得真实行情；另外检查了 ASML 的币种差异和 MSFT 的添加 / 移除 / 持久化。5 项财务边界测试通过；浏览器完成了桌面 / 390px 小屏检查、添加格式校验、行详情、视图切换和排序验证，未发现控制台错误。页面内表格可横向滚动，小屏正文没有横向溢出。可选 WebMCP 功能仅在浏览器支持时注册；本次验证浏览器没有可用的 WebMCP 上下文，该项未验证。
