# 网站部署：Render + Supabase + Passkey

唯一服务入口为 `cloud:create_app()`。部署需要 HTTPS origin 和 PostgreSQL；不提供本机无登录模式。线上服务为 <https://finfeed-private.onrender.com>，Render 跟踪 `main` 分支。

## 数据库

在 Supabase 创建数据库，在 Connect 中复制 Session pooler URI，保存到 Render 的私密环境变量 `DATABASE_URL`。特殊字符密码须按 URI 规则编码。后端连接要求 TLS。

应用创建 `finfeed_private` schema，保存账户、Passkey 公钥、会话、挑战、自选股、排序、持仓、历史备份和应用缓存。不要把该 schema 加入 Exposed schemas。应用不使用 Supabase Auth；浏览器不会取得数据库密码或 Passkey 私钥。

## Render

选择 FinFeed 仓库的 `main` 分支，可使用根目录 `render.yaml` Blueprint，或创建 Web Service：

| 配置 | 值 |
| --- | --- |
| Runtime | Python |
| Root Directory | `dashboard` |
| Build Command | `python build_cloud.py` |
| Start Command | `python start_cloud.py` |
| Health Check | `/api/health` |
| Plan | Free |
| Auto Deploy | On Commit |

私密环境变量：

- `DATABASE_URL`：Supabase 连接 URI。
- `FINFEED_BOOTSTRAP_TOKEN`：至少 32 字符的高强度随机绑定码，可用 Render Generate 生成并保存到密码管理器，仅首次绑定使用。
- `PYTHON_VERSION`：`3.11.17`。
- `ALPHAVANTAGE_API_KEY`：可选备用数据源。所有指标优先 Yahoo/yfinance，下一财季预测缺失时才尝试备用源。
- `YAHOO_SESSION_MODE`：默认 `anonymous`，在服务器建立独立匿名 Cookie/Crumb；如需使用已有登录凭据，显式设为 `login` 后重新部署。
- `YAHOO_PROXY_URL`：可选 HTTP(S) / SOCKS5(H) 出站代理，仅作用于 yfinance。将完整地址和必要认证信息保存到 Render 私密环境变量；不要提交到仓库或放进前端。Render 必须能连接到该地址；本机的 `127.0.0.1:7890` 不能直接使用。代理供应商须允许此用途并遵守数据源请求限制。启用代理后会重新检查财务缓存。
- Clash/Mihomo 订阅：可将一个已选节点整理成 `{"proxies":[节点配置]}`，Base64 编码后存入 `MIHOMO_CONFIG_B64` 私密环境变量。只复制所选节点，不复制整个订阅链接。部署使用 `python build_cloud.py` 和 `python start_cloud.py`，经 SHA-256 校验的官方 Mihomo 仅监听 `127.0.0.1:17890`，不开放控制面板或公网代理；只有 yfinance 流量使用它。Base64 不是加密，变量仍属于秘密。
- 节点默认必须通过 TLS 证书校验。只有账户本人明确批准风险后才能配置 `MIHOMO_ALLOW_INSECURE_TLS=true` 并使用含 `skip-cert-verify: true` 的节点；Yahoo HTTPS 证书校验始终保留。
- `YAHOO_COOKIE_T`、`YAHOO_COOKIE_Y`：可选 Yahoo 登录会话，必须同时设置，且只在 `YAHOO_SESSION_MODE=login` 时由服务器通过 yfinance `Auth.set_login_cookies` 使用。每个进程验证一次；验证失败不停止其他可用数据请求。登录不保证恢复预测接口权限。

Yahoo Cookie 相当于账户登录凭据。由账户本人在 Yahoo Finance 登录后取得，在 Render 私密环境变量中配置；不要发送到聊天、提交到 Git 或放在前端。只在明确同意将会话交给 Render 后配置。过期时本人更新并重新部署；移除这两个变量并重新部署即可恢复匿名模式。匿名与登录模式切换会重新检查当日资料和预测，正常运行仍遵守每天一次的刷新频率。

应用使用 Render 的 `RENDER_EXTERNAL_URL` 固定可信 origin。若用自定义域名，在首次 Passkey 绑定前设置 `PUBLIC_ORIGIN=https://实际域名`，不含路径。不能依据来访 Host 动态选择 RP ID。

## 登录与记录

1. 打开最终 HTTPS 网站，输入首次绑定码，点击“绑定我的 Passkey”，由本人完成系统验证。
2. 后续使用 Passkey 登录；其他用户在登录页选择“通过邀请码创建账户”，填写其他登录用户生成的邀请码及名称，并保存自己的 Passkey；账户名创建后不可修改。
3. 所有登录用户可通过“查看账户”只读访问彼此的 Watchlist 和完整 Portfolio；写入仅限当前登录账户。
3. 通过页面添加自选股和持仓，也可在“我的账户”选择记录 JSON 文件，预览数量并确认导入。导入前的记录会保留历史备份。
4. 登录后五分钟内可添加备用 Passkey。超过时间先退出并重新登录，应选择不同的通行密钥。

WebAuthn 要求 user verification，并验证固定 origin、RP ID、随机挑战及签名。挑战五分钟有效且一次性消费。会话十二小时过期，Cookie 为 Secure、HttpOnly、SameSite=Strict；退出时在数据库撤销。

所有私人接口均检查服务端会话，未登录返回 401。写操作要求准确 Origin、JSON 和自定义请求头。私人页面和接口返回 `Cache-Control: no-store`，记录不保存在 localStorage。数据库管理者可以访问记录，持仓并非端到端加密。

状态修改在事务内完成，保留最近 50 个旧状态。Passkey 绑定网站域名，丢失所有 Passkey 时没有公开的密码绕过入口。

免费服务空闲时会休眠。页面打开时每分钟请求行情，关闭后不主动采集；财务与预测按北京时间更新日每天检查一次。应用缓存和配额计数持久保存于数据库；yfinance 自身的 cookie/时区临时文件不作为自选股或持仓存储。

页面初始化从私人数据库批量读取自选股和持仓标的的现有快照，先显示缓存，再更新。每个浏览器页面最多 128 个标的并行，单进程后端全局最多 1024 个标的并行（Gunicorn 配置 1025 个线程）；同一标的仍有互斥锁，避免重复请求。每分钟只下载最近一个月日线用于 10 日均量，52 周高低点来自 Yahoo 元数据；季度财务和预测继续每天一次。并发不会修复供应商 HTTP 401，也不保证刷新耗时缩短到固定比例。

## 验证

开发测试使用 Flask 测试客户端、注入的测试数据库及虚拟认证器，不提供单独的本机网站服务。运行：

```sh
cd dashboard
python -m unittest test_cloud test_metrics test_refresh test_alpha test_yahoo_session
node --check public/app.js
node --check public/auth-client.js
node test_positions.cjs
```

2026-10-04 已验证 Supabase TLS 连接、记录迁移、Render main 分支部署、HTTPS 健康检查及未登录接口返回 401。供应商在云端的实际覆盖受网络、配额和数据权限影响，缺失值明确显示。

## 来源

- [Render Flask 部署](https://render.com/docs/deploy-flask)、[Blueprint](https://render.com/docs/blueprint-spec)、[免费服务](https://render.com/docs/free)。
- [Supabase 连接方式](https://supabase.com/docs/guides/database/connecting-to-postgres)。
- [WebAuthn 注册验证](https://duo-labs.github.io/py_webauthn/registration.html)、[认证验证](https://duo-labs.github.io/py_webauthn/authentication.html)。

## Macro 免费数据

在 Render 私密环境变量设置 `FRED_API_KEY`（免费申请），不要放入 Vercel 前端或仓库。
Macro 在已登录用户访问时请求 `/api/macro/jobs|pce|treasury|dxy`。就业和 PCE 为 BLS/BEA 经 FRED 发布的统计数据，官方日历分别读取 BLS ICS 与 BEA JSON；DXY 使用 yfinance `DX-Y.NYB` 日线，DGS10 为 H.15 日度恒定期限收益率。
四项指标均共享有效缓存 24 小时；页面在 Macro 可见时每 24 小时重新请求，首次进入仍立即加载。手动刷新读取有效缓存，不强制访问上游。刷新失败替换过期快照，失败提示保留 60 秒，不使用旧数据补齐。BEA 数字暂经 FRED 获取，因此当前无需保存 BEA Key。市场预期和修订前快照暂无。
