# FinFeed 项目 PostgreSQL 与迁移记录

更新于 2026-10-10（北京时间）。生产数据库先从 Supabase 切换到 h20 内的专用 `finfeed` 数据库，随后将完整数据库迁至 `47.114.43.129` 的同名项目路径，前端仍为 Vercel。应用协议、账户 ID、Passkey RP ID、会话和数据结构保持兼容。

当前服务器部署与第二次迁移验收见 [服务器运维](server-deployment.md)。本页下方的表行数记录第一次 Supabase 迁移快照，后续线上清理及写入会正常改变计数。

## 安装范围

项目根目录为 `/mnt/data/users/shx/FinFeed`，未安装系统数据库服务、修改其他项目或修改 SSH 跳板机。

| 路径/配置 | 用途 |
| --- | --- |
| `.postgres/engine` | conda-forge PostgreSQL 17.11 程序及依赖，通过官方 micromamba 安装 |
| `.postgres/data` | 已初始化的数据集群；禁止覆盖、重新初始化或删除 |
| `.postgres/tls` | 本机 TLS 证书和私钥 |
| `.postgres/backups` | 包含私人数据的归档、逐表校验清单及迁移报告 |
| `.private/postgresql.json` | 数据库身份、端口与密码，权限 600 |
| `.private/backend.json` | 当前应用数据库连接和原有行情/Gmail 配置 |
| `.private/backend-supabase.json` | 原连接配置，仅用于受控恢复，权限 600 |
| `.private/postgresql-enabled` | 启用项目监督进程中的数据库和每日备份 |

数据库仅监听 `127.0.0.1:18766`，不创建文件系统 Unix socket，不通过 Funnel 暴露数据库。客户端强制 TLS；本机证书未配置独立 CA 验证，因此不能将它描述为 `verify-full` 身份验证。`finfeed_app` 无超级用户、创建角色或创建数据库权限；`finfeed_admin` 仅用于项目集群管理。

PostgreSQL 不能以 root 运行，启动器使用服务器已有 `nobody`（UID/GID 65534），没有新增或修改系统用户。项目数据目录权限 700，私钥 600。项目根目录允许穿越以便该进程访问数据；私密目录仍为 700。共享 root 和相同 UID 的进程不是严格安全隔离边界，资源也与其他项目共享。

集群启用了数据校验和，`fsync`、`full_page_writes`、`synchronous_commit` 保持开启。最大连接数 24，shared buffers 32 MB，单操作 work memory 2 MB。实际 CPFS 存储已通过写入、同步、目录同步及文件锁检查，并通过本项目 PostgreSQL 的崩溃恢复测试；这些检查不等于对存储断电持久性作保证。

## 迁移方法与验收

1. 保存完整 Supabase 数据库归档到本机私密目录，并保留原云数据库。
2. 试恢复全部 `finfeed_private` 表，校验一致快照。
3. 暂停 FinFeed 及提醒调度，对原库 15 张应用表增加 `finfeed_retired_source_readonly` 写保护触发器，阻止旧实例继续写入。
4. 在只读源上导出最终一致快照，恢复至新专用数据库，并校验后才切换连接。
5. 只解除本机目标库的迁移写保护，启动项目监督进程并恢复原每分钟提醒任务。

最终迁移快照包括：

| 表 | 行数 |
| --- | ---: |
| account_history | 86 |
| accounts | 7 |
| cache | 231 |
| credentials | 8 |
| disabled_accounts | 1 |
| flows | 2 |
| invitations | 19 |
| notification_cursors | 72 |
| notification_outbox | 0 |
| notification_settings | 4 |
| notification_sources | 69 |
| owner | 1 |
| revoked_passkeys | 1 |
| sessions | 3 |
| state_history | 1 |

这些是切换时的快照行数，线上运行后会变化。校验采用同一 PostgreSQL 导出快照；行转 JSONB 后按 C 排序，统一 UTC、`extra_float_digits=3`，对长度分隔的 UTF-8 内容计算 SHA-256，同时核对序列值。避免不同浮点显示设置造成误报；未通过校验时不切换。

Supabase Auth 用户、Storage 对象均为空；应用没有使用这些平台服务。其内部迁移元数据及平台扩展不加载进本机应用数据库，仍保存在完整源归档及原云数据库中。全部 FinFeed 应用数据位于已迁移的 15 张表，不是克隆整个 Supabase 平台。

已验证本机数据库 TLS、7 个账户和 8 条凭据、原域名 Passkey 登录选项、公网健康检查、私人接口未登录拒绝访问、来源校验，以及每日备份进程。69 个字段、17 个索引及 16 个约束与源库匹配；Gmail 授权刷新成功，恢复后的 cron-job.org 自动 POST 返回 202。迁移前的后端 164 项回归与前端验证通过。这不等于由用户逐项重新操作所有页面，也不等于每类事件邮件均已真实投递。

## 备份与恢复

`database_backup.py` 在监督进程下运行，每个 UTC 日创建一次事务一致的应用归档，失败后一小时重试。成功记录在 `.runtime/database-backup.json`；归档附带 `.manifest.json` 及日志。程序不自动删除旧备份，需监控磁盘容量和备份错误。

最终源归档为 `.postgres/backups/supabase-final-retry.dump`，校验清单及报告在同目录；已另存本机 Git 忽略的 `dashboard/.local/database-migration/`，并核对归档 SHA-256。每日异地备份尚未自动配置，同机备份不能防御整台服务器或存储丢失。归档和配置文件禁止提交 Git 或公开分享。

恢复应先创建新的空数据库，用项目 `pg_restore` 配合 `--exit-on-error --single-transaction --no-owner --no-acl --role=finfeed_app` 恢复；连接凭据通过私密环境传入，不能放在命令行或日志。使用 `database_tools.verify` 校验对应清单后再安排切换。源迁移归档含写保护函数/触发器，目标验证后才可解除它们。不能对唯一线上数据库执行覆盖恢复。

项目监督进程启动时，存在 `.private/postgresql-enabled` 才会运行数据库及备份。不要直接重复启动 PostgreSQL，不要在已有数据目录重新运行 initdb。SSH 断开不停止进程；服务器/容器重启后仍需项目启动钩子或人工启动，尚未配置系统自启动。

## 回滚边界

原 Supabase 的应用表保持写保护，旧 Render 服务不能继续作为可写生产后端。只读源是迁移时的快照，切换后 当前服务器上的新记录不自动回传。

需要回滚时：暂停应用与调度，另备份两端，导出 当前服务器最新一致快照，在恢复目标验证全部记录及结构后，再解除目标写保护并恢复应用和调度。保留原归档，避免两个可写后端并行。**不能只改回旧连接地址，否则切换后的新增或修改数据会丢失。**

来源：[PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html)、[pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html)。
