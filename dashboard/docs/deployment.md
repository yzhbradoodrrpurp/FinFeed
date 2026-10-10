# 网站部署：Vercel + 专用 PostgreSQL

更新于 2026-10-10（北京时间）。`h20-backend` 已合并到 `main`，当前生产部署如下：

| 组件 | 当前配置 |
| --- | --- |
| 前端 | https://finfeed-research.vercel.app ，Vercel，仓库 `main`，Root Directory `frontend` |
| 后端 HTTPS | https://finfeed.tail03a68f.ts.net ，Tailscale Funnel，仅转发 FinFeed |
| 后端进程 | `47.114.43.129`，`/mnt/data/users/shx/FinFeed`，监听 `127.0.0.1:18765` |
| 数据库 | 服务器项目 PostgreSQL 17.11，`127.0.0.1:18766`，TLS，`finfeed_private` schema |
| 邮件 | Gmail HTTPS API，仅 `gmail.send` 权限 |
| 调度 | cron-job.org 每分钟 POST 到当前服务器，项目本地 scheduler 默认关闭 |
| Render | 暂保留作回滚备用，不是当前生产转发目标 |

应用工厂为 `backend.app:create_app()`。不提供无登录的网站运行模式。服务器的 Python 环境、代理、Tailscale、私密文件和日志全部保存在项目目录内；不更改其他项目的环境、系统路由、DNS、防火墙或 SSH 跳板机。详细启动与恢复步骤见 [服务器运维说明](server-deployment.md)。

2026-10-10 随后已将后端、数据库和唯一 Funnel 身份迁至 `47.114.43.129`；原 h20 已停用，迁移验收见 [服务器运维](server-deployment.md)。

## 发布与数据库

Vercel 使用 `frontend/vercel.json` 和 `node build.cjs`，输出 `dist`，将 `/api/*` 转发到当前服务器。推送 `main` 会触发前端自动部署；服务器使用代码快照，更新代码需单独部署，不会随 Git push 自动同步。

2026-10-10 已将原 Supabase 中全部 15 张应用表的一致快照迁移并逐表校验，保留账户、持仓、Passkey、会话、历史、通知设置和缓存。`DATABASE_URL` 保存在 服务器的 `.private/backend.json`，权限 600；URI 中的特殊字符密码须编码，连接要求 TLS。数据库不开放公网端口。应用不使用 Supabase Auth，浏览器不会获得数据库密码或 Passkey 私钥。

PostgreSQL 安装、数据、TLS 与每日备份均位于 `.postgres`，由本项目监督进程管理。原 Supabase 以应用表写保护触发器保留只读快照；备份与回滚见 [数据库运维](database-migration.md)。连接凭据不在文档公布。

## 服务器私密配置与代理

配置文件为 `/mnt/data/users/shx/FinFeed/.private/backend.json`。禁止提交到 Git 或静态前端：

- `DATABASE_URL`：本机项目 PostgreSQL 的 `finfeed_app` 角色连接 URI，数据库名 `finfeed`。
- `PUBLIC_ORIGIN=https://finfeed.tail03a68f.ts.net`：固定后端 HTTPS origin，不含路径。
- `FRONTEND_ORIGIN=https://finfeed-research.vercel.app`：生产前端来源；现有 Passkey 继续使用此域名的 origin 和 RP ID。
- `FINFEED_BOOTSTRAP_TOKEN`：至少 32 字符的高强度首次绑定码；现有账户不重新初始化。
- `FRED_API_KEY`：宏观序列和备用 BLS 发布日期。
- `ALPHAVANTAGE_API_KEY`：可选备用预测源，Yahoo 缺少下一财季预测时使用；按 UTC 日管理调用预算。
- `YAHOO_SESSION_MODE`：默认 `anonymous`；如使用已有登录 Cookie，显式设置 `login`。`YAHOO_COOKIE_T`、`YAHOO_COOKIE_Y` 必须同时配置，仅在登录模式使用。登录不保证供应商预测覆盖。
- `YAHOO_PROXY_URL`：项目启动器固定为 `http://127.0.0.1:17890`。`BLS_PROXY_URL`、`POLYMARKET_PROXY_URL`、`GMAIL_PROXY_URL` 当前均显式设为同一项目代理。SEC 和 FRED 可直连，`SEC_PROXY_URL` 可选。
- Gmail 和调度变量：`FINFEED_EMAIL_PROVIDER=gmail`、`FINFEED_EMAIL_FROM`、`GMAIL_CLIENT_ID`、`GMAIL_CLIENT_SECRET`、`GMAIL_REFRESH_TOKEN`、`FINFEED_NOTIFICATION_CRON_TOKEN`，详见 [邮件提醒说明](email-notifications.md)。

代理文件 `.proxy/config.json` 为私密文件，当前由服务器香港节点连接美国节点，最终出口已验证为美国，不经过用户电脑。代理只监听本机，不开启全局 VPN、TUN、DNS 或公网控制面板；节点与目标 HTTPS 证书验证保持开启。Yahoo Cookie、订阅和节点认证都属于凭据，更新时不得输出到日志、聊天或 Git。

## 进程和缓存

项目监督进程运行一个 Gunicorn worker、64 个 HTTP 线程，禁用应用预加载；连接池在 worker 内创建。代理、Tailscale 和后端退出后由监督程序重新启动。SSH 断开不会停止进程；服务器/容器重启后仍需要项目启动钩子或人工启动，未安装系统级自启动服务。

页面行情、季度财务和 Yahoo 预测每分钟检查，Macro/Whales/News 每小时检查，Polymarket 每分钟检查。刷新队列按类型隔离：行情 4、新闻 2、巨鲸 2、Macro 2、Home 2 个 worker；总排队与执行任务上限 256。浏览器 Watchlist 并发 4，账户自选股与持仓合计最多 128 个不同标的。相同键的请求合并；供应商延迟、限流和配额仍生效。

成功快照先显示并后台更新，失败保留已有成功快照并标记旧数据，缺失值不补造。缓存和队列口径见 [网站说明](../README.md)；邮件由独立服务器调度运行，关闭网页不停止已启用的提醒。

## 登录与记录

1. 仅全新数据库首次初始化时，在最终 HTTPS 网站输入首次绑定码并由本人保存 Passkey；当前生产账户直接使用已有 Passkey，不重新初始化。
2. 后续使用 Passkey 登录；其他用户在登录页选择“通过邀请码创建账户”，填写其他登录用户生成的邀请码及名称，并保存自己的 Passkey；账户名创建后不可修改。
3. 所有登录用户可通过“查看账户”只读访问彼此的 Watchlist 和完整 Portfolio；写入仅限当前登录账户。
4. 通过页面添加自选股和持仓，也可在“我的账户”选择记录 JSON 文件，预览数量并确认导入。导入前的记录会保留历史备份。
5. 登录后五分钟内可添加备用 Passkey。超过时间先退出并重新登录，应选择不同的通行密钥。

WebAuthn 要求 user verification，并验证固定 origin、RP ID、随机挑战及签名。挑战五分钟有效且一次性消费。会话十二小时过期，Cookie 为 Secure、HttpOnly、SameSite=Strict；退出时在数据库撤销。

所有私人接口均检查服务端会话，未登录返回 401。写操作要求准确 Origin、JSON 和自定义请求头。私人页面和接口返回 `Cache-Control: no-store`，记录不保存在 localStorage。数据库管理者可以访问记录，持仓并非端到端加密。

状态修改在事务内完成，保留最近 50 个旧状态。Passkey 绑定网站域名，丢失所有 Passkey 时没有公开的密码绕过入口。

## Macro 数据

FRED 提供 BLS 就业、BEA PCE 和美联储 H.15 DGS10 统计序列；Yahoo `DX-Y.NYB` 提供 DXY 日线。DGS10 是日度恒定期限收益率，不是实时单只国债报价。BLS ICS、BEA JSON 优先提供发布日历；BLS 不可用时备用读取 FRED release 50 的 BLS 已公布日期，按常规 08:30 美国东部转换并注明时刻口径，不推算未公布日期。

Macro 正常缓存一小时，失败状态短期重试；界面先显示成功快照，失败标注旧数据。定时或手动强制更新与首次复用有效缓存分开。邮件在临近 NFP/PCE 发布时使用自己的加速刷新策略。市场预期与修订前快照暂无，不把缺失值当作零。

## 验证与验收边界

从仓库根目录运行 `dashboard/.venv/bin/python dashboard/tests/run.py`；使用 Flask 测试客户端、测试数据库和虚拟认证器，不依赖无登录本机服务。结构见 [架构说明](architecture.md)。

2026-10-10 原 h20 部署已验证进程、项目 PostgreSQL 客户端 TLS、Yahoo 三年日线、BLS 官方日历/报告/数据 API、SEC、FRED、BEA、Polymarket、Gmail 令牌更新、Vercel 公网健康检查及自动调度 202。错误 Host/Origin 返回 403，未登录私人接口返回 401，登录选项保留 Vercel RP ID。迁移代码的后端 164 项测试与前端验证已通过。

这些检查不等于逐项重测全部页面操作，也不等于每类提醒均已实际投递。Alpha Vantage 本次迁移没有重新进行实际 API 验收。真实邮件送达边界见邮件提醒说明。`/api/health` 是存活检查；登录后的 `/api/ready` 才检查数据库和刷新队列。

## Render 备用与回滚

根目录 `render.yaml`、`dashboard/build_cloud.py`、`dashboard/start_cloud.py` 保留原 Render 部署兼容性，不是当前服务器启动入口。Blueprint 使用 `dashboard` 根目录、Python 3.11.17、`python build_cloud.py`、`python start_cloud.py`、`/api/health`。Render 仍保留私密环境变量；不要把 项目本机代理地址直接复制到 Render，因为其 loopback 指向不同机器。

数据库已迁移且 Supabase 应用表有写保护，不能直接启用旧 Render。回滚需暂停写入、同步并校验 当前服务器新增数据，再恢复转发与调度，保持前端 origin 和 Passkey RP ID；避免两个调度器同时运行。当前旧服务尚未删除，停止/删除作为独立运维操作处理。

## 来源

- [服务器运维记录](server-deployment.md)、[邮件提醒配置](email-notifications.md)。
- [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel)。
- [PostgreSQL 归档恢复](https://www.postgresql.org/docs/17/app-pgrestore.html)。
- [Render Blueprint](https://render.com/docs/blueprint-spec) 与 [免费服务](https://render.com/docs/free)，仅供备用部署参考。
