# h20 后端迁移历史记录

> 此部署已于 2026-10-10 停用。后端和数据库迁至 `47.114.43.129`，h20 的 FinFeed 进程已停止并保留副本；当前启动与回滚请使用 [服务器运维说明](server-deployment.md)，不要直接执行本页旧启动步骤。

生产分支：`main`（`h20-backend` 已合并，保留用于追溯）。前端继续使用 Vercel，数据库已迁移到本项目内 PostgreSQL 17.11，原 Supabase 保留只读快照。
2026-10-10 已将 Vercel 生产部署和 cron-job.org 每分钟提醒任务切换到 h20。
Render 暂保留作回滚备用，未删除服务或数据库。

## 项目范围

所有部署文件位于 `/mnt/data/users/shx/FinFeed`：

| 路径 | 用途 |
| --- | --- |
| `app/dashboard` | 应用代码快照 |
| `.venv` | 独立 Python 环境和依赖 |
| `.private/backend.json` | 项目数据库、行情和 Gmail 私密配置，权限 600 |
| `.proxy` | 用户节点代理，仅监听 127.0.0.1:17890 |
| `.tailscale` | 官方便携程序、持久状态、证书和日志 |
| `.runtime` | 项目进程记录、锁和日志 |
| `.pip-cache` | 项目依赖下载缓存 |
| `.postgres` | PostgreSQL 程序、数据、TLS 和私密备份 |
| `.private/postgresql.json` | 专用数据库角色凭据和进程身份，权限 600 |

后端仅监听 `127.0.0.1:18765`。Tailscale 使用 `--tun=userspace-networking`、
`--accept-dns=false`、`--accept-routes=false`、`--ssh=false`，不创建系统服务、不修改
全局 DNS、路由、防火墙或其他项目环境，不修改 SSH 跳板机。

CPFS 不支持文件系统 Unix socket，因此 Tailscale 控制通道使用 Linux 内存中的
抽象 socket `@finfeed-h20-control`；它不创建项目外的文件。持久状态仍在项目目录内。

设备名为 `finfeed`，公网地址为 `https://finfeed.tail03a68f.ts.net`。Funnel 的节点权限仅匹配专用设备 IP `100.94.161.64`。

代理仅由 FinFeed 显式使用。公网 Funnel 仅转发 FinFeed 后端，账户接口继续要求登录。
在共享 root 环境中，文件权限与 loopback 不能防御其他 root 进程；这里的隔离保证是
不主动修改或接管其他项目，不能承诺共享 CPU、内存、磁盘和网络完全没有资源竞争。

## 启动与维护

先安装项目依赖：`.venv/bin/python -m pip install -r app/dashboard/requirements-cloud.txt`。
所有凭据仅写入 `.private/backend.json`，不得提交 Git。设置 `PUBLIC_ORIGIN` 为实际 Funnel
HTTPS 地址。`BLS_PROXY_URL`、`POLYMARKET_PROXY_URL` 和 `GMAIL_PROXY_URL` 均设为项目代理。Gmail 在服务器上通过 `GMAIL_PROXY_URL=http://127.0.0.1:17890` 单独走代理，`FRONTEND_ORIGIN` 保持 `https://finfeed-research.vercel.app`，数据库仅连接本机 `127.0.0.1:18766/finfeed`，要求 TLS。

使用 `.venv/bin/python app/dashboard/deployment/h20/supervise.py` 启动项目监督进程，
后台运行时将输出重定向到 `.runtime/supervisor.log`。监督进程仅管理自己启动的子进程，
会重启退出的代理、Tailscale 和后端。存在 `.private/postgresql-enabled` 时同时管理项目数据库及每日备份进程。数据库安装与恢复见 [数据库运维](database-migration.md)。首次启动前需停止之前的项目试运行进程，避免端口冲突。
不能同时启动两个监督进程。终止监督进程会终止它创建的子进程，不能使用全局 `pkill`。

进程可以在 SSH 断开后继续运行；容器重建或整机重启后需要在平台允许的项目启动钩子中
重新启动监督进程。没有安装系统级自启动服务，也未承诺平台重启后自动恢复。

## 代码更新与日志

GitHub `main` 推送会触发 Vercel 前端构建，但不会自动更新 h20 的 `app/dashboard` 快照。更新 h20 时只同步应用代码，保留 `.private`、`.postgres`、`.proxy`、`.tailscale`、`.venv` 和 `.runtime`；不得对项目根目录执行清空或覆盖私密状态。依赖变化时在项目虚拟环境安装，并只重启 FinFeed 后端或项目监督进程。

当前日志为 `.runtime/backend.log`、`proxy.log`、`tailscale.log` 和 `supervisor.log`；应用失败搜索 `request_failure`。程序尚未自动轮转日志，维护时只处理本项目日志。`/api/health` 仅检查存活；登录后的 `/api/ready` 检查数据库及队列。健康检查成功不能替代登录、保存记录或真实邮件投递验收。

## 切换检查

1. 验证项目 PostgreSQL TLS、只读账户记录、FRED、Yahoo 三年日线、SEC、Polymarket 和 Gmail 授权。
2. 验证公网 HTTPS、未登录账户接口返回 401、错误 Origin/Host 返回 403，以及 Vercel 域名的 Passkey。
3. 更新 Vercel `/api/*` 转发地址，前端来源及 Passkey RP ID 保持原 Vercel 域名。
4. 将邮件检查调度迁移到新后端。若使用项目本地调度，关闭旧外部调度后创建
   `.private/scheduler-enabled` 并重启项目监督进程；默认不开启本地调度。
5. 验证前端实际请求、邮件提醒和刷新；旧 Render 目前仍保留，停止或删除必须作为独立操作处理。

数据库切换后不能直接恢复旧 Render 写入：必须暂停写入、将 h20 上切换后新增数据同步回目标数据库并校验，再解除只读保护及切换转发和调度。详见 [数据库回滚边界](database-migration.md)。

## 迁移验证记录（2026-10-10 北京）

- 2026-10-10 项目 PostgreSQL 客户端 TLS 已验证；15 张应用表的一致快照恢复后逐表内容哈希及行数完全匹配，7 个账户、8 条 Passkey、3 条会话和所有历史、缓存、通知游标均保留。运行后的记录会正常变化。
- 已验证仅本项目数据库的 WAL 崩溃恢复、已提交数据保留；每日一致快照备份已产生首份归档。最终迁移归档另复制到本机；每日异地备份尚未配置。
- Yahoo 三年日线、SEC、FRED、BEA、Gmail 令牌更新及 Polymarket 已在 h20 验证。
- `GMAIL_PROXY_URL`、`POLYMARKET_PROXY_URL` 显式指向项目代理；SEC 和 FRED 可直接连接。
- BLS 在香港出口返回 403；2026-10-10 切换到美国出口后，浏览器模拟请求的官方日历、报告和数据 API 均返回 200。
  美国节点由项目香港节点连接，最终出口已验证为 US；全程在服务器运行，不经过用户本机。
  美国直连节点连接超时，中继节点证书校验失败，未关闭证书校验。
  官方日历失败时备用使用 FRED release 50 的 BLS 公布日期，不按首个周五推算。
  FRED 未提供时刻，按 BLS 常规 08:30 美国东部转换，邮件保留时间口径说明；若没有已公布未来日期则报错。
  官方接口与口径：[FRED release dates](https://fred.stlouisfed.org/docs/api/fred/release_dates.html)、
  [BLS 日程](https://www.bls.gov/schedule/news_release/empsit.htm)。
- 公网未登录返回 401；错误 Host/Origin 返回 403。Vercel 登录选项保留原 RP ID。
- cron-job.org 新入口已保存并重新加载核实；h20 日志确认每分钟自动请求返回 202 Accepted。
  项目本地 scheduler 仍关闭，避免重复调度。
- 生产前端从 h20 读取板块、关注列表数据已在后端访问日志确认。
- 首次 Vercel 生产部署从 h20-backend 手动提升；2026-10-10 已将迁移分支合并到 main。
  main 的 `/api/*` 转发地址已指向 h20，后续 main 发布沿用新后端。
