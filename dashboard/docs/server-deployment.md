# 当前后端服务器运维

更新于 2026-10-10（北京时间）。生产后端与专用数据库已从 h20 迁至 `47.114.43.129`，前端仍在 Vercel。h20 的 FinFeed 进程已停止，原数据和备份保留。

## 隔离与路径

所有 FinFeed 持久文件仍位于 `/mnt/data/users/shx/FinFeed`。这台服务器原有 PostgreSQL、代理、Redis、Nginx 及其他项目均未被接管或修改。FinFeed 不使用系统 Python 的包目录或原有数据库。

| 路径 | 用途 |
| --- | --- |
| `app/dashboard` | 应用代码快照，不包含个人研究目录 |
| `.python` | 项目 Python 3.12，服务器系统 Python 3.14 保持原样 |
| `.venv` | 独立虚拟环境，47 个依赖版本与原 h20 环境一致 |
| `.private` | 数据库、行情、代理及 Gmail 私密配置 |
| `.postgres` | 独立 PostgreSQL 17.11 程序、集群、TLS 与备份 |
| `.proxy` | FinFeed 专用代理程序及用户节点配置 |
| `.tailscale` | 专用 Tailscale 程序、状态和证书 |
| `.runtime` | 监督进程、各服务 PID、日志及备份成功记录 |
| `.pip-cache` | 项目依赖缓存 |

后端监听 `127.0.0.1:18765`，项目 PostgreSQL 监听 `127.0.0.1:18766`，代理监听 `127.0.0.1:17890`。没有开放数据库公网端口或修改系统防火墙、路由、DNS。PostgreSQL 沿用已有 nobody 身份及专用 SQL 角色，没有修改系统账户；共享 root 的安全和资源隔离边界见 [数据库说明](database-migration.md)。

## 启动与更新

启动入口保留兼容路径 `app/dashboard/deployment/h20/supervise.py`；目录名称不代表仍在 h20 运行。它管理代理、Tailscale、后端，以及启用 `.private/postgresql-enabled` 时的数据库和每日备份。

启动前确认本项目没有监督进程正在运行；使用项目 Python 启动入口，并脱离 SSH 会话、将输出写入 `.runtime/supervisor.log`。进程退出会由监督程序重启，SSH 断开不停止服务。未创建系统服务，整机重启后仍需项目启动钩子或人工启动。

GitHub main 推送仅自动构建 Vercel 前端；服务器代码快照需单独同步。只同步明确的应用路径，不上传 `personal/`，不覆盖 `.private`、`.postgres`、`.tailscale` 等持久状态。依赖安装需使用项目虚拟环境及项目缓存；此服务器有既有全局 pip 镜像配置，维护时应为本次进程指定 `PIP_CONFIG_FILE=/dev/null` 和正确安装源，不改全局配置。

## 网络与提醒

公网入口仍为 `https://finfeed.tail03a68f.ts.net`，设备身份与证书已在 h20 停止后转移，因此 Vercel `/api/*` 转发及原每分钟 cron-job.org 任务无需改地址。

Tailscale 使用 userspace 模式、抽象控制 socket `@finfeed-h20-control`，关闭系统 DNS、路由接收和 SSH 功能。Funnel 仅转发 FinFeed。项目代理沿用服务器端香港节点连接美国节点的配置，Yahoo、BLS、Polymarket 和 Gmail 显式使用它；SEC、FRED 验证可直连，不依赖用户本机转发。原有代理进程保持独立。

本地 scheduler 仍关闭，提醒由原外部每分钟任务触发，避免重复调度。

## 数据迁移与旧实例

迁移前先试恢复一致快照并逐表校验，再将 h20 应用表设为只读，导出最终快照、停止 h20 全部 FinFeed 服务，恢复并校验新服务器后才接管公网身份。没有复制正在运行的 PostgreSQL 数据目录。

最终 15 张应用表逐表内容哈希和行数匹配，保留 7 个账户、8 条 Passkey 凭据及全部持仓、历史、缓存和提醒状态。流转挑战和会话有原定有效期；最终快照时分别为 1 条，过期记录正常清理，不是迁移丢失。

最终归档及清单在 `.postgres/backups/root-transfer-final-*.dump`，报告为 `root-cutover-report.json`。已另存本机 Git 忽略的 `dashboard/.local/root-migration/` 并核对 SHA-256。新服务器每日一致快照备份继续运行；每日异地自动备份尚未配置。

h20 留有 `.private/retired-deployment` 标记，监督程序拒绝启动，防止两台机器争用同一 Funnel 身份。h20 数据库也保留写保护。**不要同时启动旧副本；回滚前必须先暂停新实例、同步切换后新增数据、校验并转移唯一公网身份，不能直接启用旧快照。** Supabase 同样仍是历史只读副本。

## 验证记录

- 新环境中 161 项后端回归测试通过；依赖版本一致，pip check 通过。
- 试恢复及最终恢复的 15 张表内容校验通过，数据库客户端 TLS 正常。
- 新服务器本机健康检查和原 Vercel RP ID 的登录选项正常；未登录私人接口返回 401。
- BLS、Yahoo、SEC、FRED、Polymarket 网络检查及 Gmail 授权刷新成功。
- 原 Funnel 和 Vercel 的健康接口返回 200；Vercel 登录选项保持原 RP ID，设备身份保持不变。
- 新服务器日志确认原 cron-job.org 每分钟自动请求返回 202；新服务器每日备份已生成首份归档。

健康接口与网络检查不能替代用户逐项操作或每类提醒的真实投递验收；相关边界见 [邮件说明](email-notifications.md)。
