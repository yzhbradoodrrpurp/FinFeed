# Oracle 后端迁移（oracle-backend 分支）

此分支新增 Oracle Ubuntu 部署能力。现阶段尚未创建 Oracle 账户或实例，未迁移正式服务。Render / Vercel 的正式配置仍指向现有 main 部署。

## 结构与迁移范围

Vercel 前端 → HTTPS Caddy（自动续证、gzip/zstd 压缩）→ 回环地址 Gunicorn（1 worker / 64 threads）→ 原 Supabase PostgreSQL。

数据源、计算口径、缓存有效期、每分钟／每小时更新频率不改变。保留单 worker，避免倍增数据库连接池、请求锁和后台线程；Gunicorn 仍禁止 preload，以免 fork 后数据库维护线程失效。ARM / x86 均可安装固定版本、固定 SHA-256 的 Mihomo，仅作用于 Yahoo 代理。

私人账户、Passkey 公钥、自选股、持仓、通知设置及应用快照继续使用原 Supabase `finfeed_private` schema，不复制或清空数据。Oracle 本地 `.cache` 仅是运行时文件；备份不能只备份该目录。

## 1. 创建 Oracle 实例

1. 注册 Oracle Cloud，选择合适的 Home Region，仔细核对当前 Always Free 标识及成本估算。不要依靠试用赠金判断资源长期免费。
2. 创建 **Ubuntu 24.04** 实例，可选 Always Free ARM A1 或 x86 E2 Micro；具体容量以账户控制台为准。小内存机器先实测财务抓取峰值，再决定是否切换。
3. 保存 SSH 私钥到本人管理的位置，服务器仅安装公钥。SSH 22 端口限制为管理者 IP；公网开放 TCP 80 / 443。配置 VCN 路由、Internet Gateway 和系统防火墙，保留 Ubuntu / OCI 现有规则，不执行 iptables 清空操作。
4. 为后端准备能解析到实例公网 IP 的 DNS 名称。没有购买域名时，可用免费 DuckDNS 子域名作为初期入口；服务依赖第三方免费 DNS，需妥善保管更新 token。前端继续保留 `finfeed-research.vercel.app`。

来源核验于 2026-10-09：[Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)、[SSH 连接实例](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/accessinginstance.htm)、[DuckDNS](https://www.duckdns.org/about.jsp)。Always Free 空闲实例可能被回收；创建时也可能没有可用容量。

## 2. 安装服务

在新建专用 Ubuntu 实例执行，替换路径和后端 DNS 名称：

```sh
git clone --branch oracle-backend https://github.com/yzhbradoodrrpurp/FinFeed.git
cd FinFeed
sudo bash dashboard/deployment/oracle/setup.sh YOUR_BACKEND_HOST
sudoedit /etc/finfeed/backend.env
sudo bash dashboard/deployment/oracle/deploy.sh "$PWD" oracle-backend
```

`setup.sh` 安装 Python、venv、Caddy 和 systemd unit，生成 root 所有、权限 600 的环境文件。它会替换专用实例的 Caddy 配置，不应直接用于已有其他网站的服务器。Caddy 自动证书要求 DNS 指向此实例、80/443 公网可达：[Caddy 官方说明](https://caddyserver.com/docs/automatic-https)。

环境文件使用 systemd `EnvironmentFile` 语法，不写 `export`，包含空格等特殊字符的值要正确引用。填写：

- `PUBLIC_ORIGIN=https://实际后端DNS名称`，不含路径或末尾 `/`。
- `FRONTEND_ORIGIN=https://finfeed-research.vercel.app`，保留已有 Passkey 的前端 origin。
- `DATABASE_URL`：原 Supabase 的 TLS Session pooler URI。
- 从 Render 私密配置迁入现有 FRED、Yahoo 可选代理及 Gmail OAuth 配置。只在用户自己的配置后台与服务器环境文件中传递，不输出到终端日志或 Git。
- `FINFEED_NOTIFICATION_CRON_TOKEN`：已有专用调度密钥，迁入时保持安全。不要把 Gmail、数据库密钥用于调度。
- 已有账户不需要创建新 bootstrap token。

`deploy.sh` 从指定提交生成独立 release / venv，安装依赖和代理，原子切换 `/opt/finfeed/current`，启动服务，最多等待约两分钟确认 `/api/health`。失败时有旧 release 则自动回退。首次部署失败没有旧版本可恢复，需要修正配置重试。

systemd 负责开机启动与异常退出重启；连续五次启动失败后停止反复重启，排查后运行 `sudo systemctl reset-failed finfeed`。Caddy 负责 HTTPS 与压缩。服务日志进入 journald，不配置记录私人 HTTP 响应或密钥的访问日志。

## 3. 验收后切换

1. 先检查新后端公网 HTTPS `/api/health`。这只是进程存活检查，不能证明数据库和供应商正常。
2. 创建 Vercel 预览部署，将预览 API rewrite 指向 Oracle。预览域名与已有 Passkey 绑定域名不同，不用预览登录结果证明原 Passkey 可用；可用专用测试数据库和测试 Passkey 验证预览完整流程。
3. 正式切换前检查原数据库 TLS 连通、代理实际访问 Yahoo、全部数据源成功率、冷／热缓存延迟和内存峰值。不要以响应 200 作为数据准确性证明，抽查报价时间、季度期别、曲线日期及缺失提示。
4. 在本分支将 `frontend/vercel.json` 的 `/api/:path*` destination 改为 `https://实际Oracle后端/api/:path*`。核对其他前端入口无硬编码 Render 域名，再选择将通过验收的提交合并并发布正式前端。
5. 正式 Vercel origin 不变、原数据库不变，已有前端域名 Passkey 可继续验证；后端 cookie 会话应通过原网站实测。若用户曾仅绑定 Render 域名的 Passkey，不应假定能迁移到新后端域名。
6. 用自己的账号登录，验收账户、Watchlist 读写与只读访问其他账户、Portfolio、Home、Macro、Whales、News、绑定邮箱及保存提醒。写操作只用专用测试 ticker / 记录，并恢复测试数据。

## 4. 迁移提醒调度

部署时通知 timer **默认不启用**，避免与 cron-job.org 同时运行。

正式切换时先停用旧 cron-job.org 任务，再启用本机 timer：

```sh
sudo systemctl enable --now finfeed-notifications.timer
systemctl list-timers finfeed-notifications.timer
sudo journalctl -u finfeed-notifications.service --since '10 minutes ago'
```

timer 每分钟通过回环地址调用原通知接口，沿用来源刷新间隔、订阅、持久去重和发信状态。HTTP 202 仅表示任务接受；需要经过用户授权的实际提醒验收才能证明邮件送达。服务器停机期间无法提供准点提醒，恢复后由现有补发窗口决定是否发送。

## 5. 更新、回退与维护

更新默认手动执行，避免未经验收的分支提交自动进入正式网站：

```sh
git fetch origin oracle-backend
sudo bash dashboard/deployment/oracle/deploy.sh "$PWD" origin/oracle-backend
sudo systemctl status finfeed --no-pager
sudo journalctl -u finfeed -n 80 --no-pager
```

回退可用同一个脚本指定已验证的旧 commit。保留最近成功 release，确认无进程使用后再清理更旧 release。首次创建服务器时启用 Ubuntu 自动安全更新；系统更新要求重启时安排维护窗口。限制 journald 总占用，观察内存、磁盘、带宽和健康检查。保留 Supabase 备份能力和账户记录导出，私密环境文件用独立加密备份管理。

正式流量回退：恢复 Vercel `/api/*` 的 Render destination；停用 Oracle timer 后恢复旧 cron-job.org 任务。不要先删除 Render 或原数据库。两边共用数据库，没有数据复制的切换步骤；迁移验证期间要避免在两个服务器同时触发真实提醒。

## 已验证与待验证

本地验证覆盖部署脚本语法、通知调度请求头与失败脱敏、ARM / x86 代理校验和、现有后端回归。尚未验证 Oracle 实例安装、证书签发、Linux systemd 启动、真实数据库、供应商性能和实际邮件。必须有实例及访问配置后才能完成这些项目。
