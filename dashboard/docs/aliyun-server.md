# Aliyun 后端迁移（aliyun-server 分支）

本分支适配已购买的新加坡 Ubuntu 24.04 轻量应用服务器（2 核 / 0.5 GiB / 20 GiB）。上线状态须以实际验收为准；验证新后端前保留 Render 正式服务。

## 结构与迁移范围

Vercel 前端 → HTTPS Caddy（自动续证、gzip/zstd 压缩）→ 回环地址 Gunicorn（1 worker / 64 threads）→ 原 Supabase PostgreSQL。

数据源、计算口径、缓存有效期、每分钟／每小时更新频率不改变。保留单 worker，避免倍增数据库连接池、请求锁和后台线程；Gunicorn 仍禁止 preload，以免 fork 后数据库维护线程失效。ARM / x86 均可安装固定版本、固定 SHA-256 的 Mihomo，仅作用于 Yahoo 代理。

私人账户、Passkey 公钥、自选股、持仓、通知设置及应用快照继续使用原 Supabase `finfeed_private` schema，不复制或清空数据。阿里云本地 `.cache` 仅是运行时文件；备份不能只备份该目录。

## 1. 实例与 HTTPS

使用已购买的专用 Ubuntu 24.04 实例。保留云平台现有网络规则，仅为应用开放 TCP 80 / 443；SSH 限制管理来源。后端需要可信 HTTPS 入口，前端仍为 `finfeed-research.vercel.app`。

0.5 GiB 是整台虚拟机内存，包含操作系统。安装脚本在小内存、无现有交换空间时添加 1 GiB 磁盘 swap，降低短时内存峰值造成退出的风险。swap 不能代替实际 RAM；切换前须检查 Linux 实际峰值、换页和接口延迟。保留 1 worker / 64 threads 及原有来源并发限制，不通过删除功能节省内存。

缓存放在 `/opt/finfeed/shared/cache`，跨版本部署和回退保留。日志限制为 50 MiB 持久 / 10 MiB 运行时；限制 glibc allocator arena 数量，减轻多线程内存保留。数据源、计算精度、缓存有效期和提醒频率不变。

## 2. 安装服务

在新建专用 Ubuntu 实例执行，替换路径和后端 DNS 名称：

```sh
git clone --branch aliyun-server https://github.com/yzhbradoodrrpurp/FinFeed.git
cd FinFeed
sudo bash dashboard/deployment/aliyun/setup.sh YOUR_BACKEND_HOST
sudoedit /etc/finfeed/backend.env
sudo bash dashboard/deployment/aliyun/deploy.sh "$PWD" aliyun-server
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
2. 创建 Vercel 预览部署，将预览 API rewrite 指向 Aliyun。预览域名与已有 Passkey 绑定域名不同，不用预览登录结果证明原 Passkey 可用；可用专用测试数据库和测试 Passkey 验证预览完整流程。
3. 正式切换前检查原数据库 TLS 连通、代理实际访问 Yahoo、全部数据源成功率、冷／热缓存延迟和内存峰值。不要以响应 200 作为数据准确性证明，抽查报价时间、季度期别、曲线日期及缺失提示。
4. 在本分支将 `frontend/vercel.json` 的 `/api/:path*` destination 改为 `https://实际阿里云后端/api/:path*`。核对其他前端入口无硬编码 Render 域名，再选择将通过验收的提交合并并发布正式前端。
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
git fetch origin aliyun-server
sudo bash dashboard/deployment/aliyun/deploy.sh "$PWD" origin/aliyun-server
sudo systemctl status finfeed --no-pager
sudo journalctl -u finfeed -n 80 --no-pager
```

回退可用同一个脚本指定已验证的旧 commit。保留最近成功 release，确认无进程使用后再清理更旧 release。首次创建服务器时启用 Ubuntu 自动安全更新；系统更新要求重启时安排维护窗口。限制 journald 总占用，观察内存、磁盘、带宽和健康检查。保留 Supabase 备份能力和账户记录导出，私密环境文件用独立加密备份管理。

正式流量回退：恢复 Vercel `/api/*` 的 Render destination；停用 Aliyun timer 后恢复旧 cron-job.org 任务。不要先删除 Render 或原数据库。两边共用数据库，没有数据复制的切换步骤；迁移验证期间要避免在两个服务器同时触发真实提醒。

## 已验证与待验证

本地验证覆盖部署脚本语法、通知调度请求头与失败脱敏、ARM / x86 代理校验和、现有后端回归。需实际验证阿里云实例安装、证书签发、Linux systemd 启动、真实数据库、供应商性能和实际邮件。必须有实例及访问配置后才能完成这些项目。
