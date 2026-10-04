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
| Build Command | `pip install -r requirements-cloud.txt` |
| Start Command | `gunicorn 'cloud:create_app()' --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180` |
| Health Check | `/api/health` |
| Plan | Free |
| Auto Deploy | On Commit |

私密环境变量：

- `DATABASE_URL`：Supabase 连接 URI。
- `FINFEED_BOOTSTRAP_TOKEN`：至少 32 字符的高强度随机绑定码，可用 Render Generate 生成并保存到密码管理器，仅首次绑定使用。
- `PYTHON_VERSION`：`3.11.17`。
- `ALPHAVANTAGE_API_KEY`：可选备用数据源。所有指标优先 Yahoo/yfinance，下一财季预测缺失时才尝试备用源。

应用使用 Render 的 `RENDER_EXTERNAL_URL` 固定可信 origin。若用自定义域名，在首次 Passkey 绑定前设置 `PUBLIC_ORIGIN=https://实际域名`，不含路径。不能依据来访 Host 动态选择 RP ID。

## 登录与记录

1. 打开最终 HTTPS 网站，输入首次绑定码，点击“绑定我的 Passkey”，由本人完成系统验证。
2. 后续使用 Passkey 登录；不开放其他账户注册。
3. 通过页面添加自选股和持仓，也可在“我的账户”选择记录 JSON 文件，预览数量并确认导入。导入前的记录会保留历史备份。
4. 登录后五分钟内可添加备用 Passkey。超过时间先退出并重新登录，应选择不同的通行密钥。

WebAuthn 要求 user verification，并验证固定 origin、RP ID、随机挑战及签名。挑战五分钟有效且一次性消费。会话十二小时过期，Cookie 为 Secure、HttpOnly、SameSite=Strict；退出时在数据库撤销。

所有私人接口均检查服务端会话，未登录返回 401。写操作要求准确 Origin、JSON 和自定义请求头。私人页面和接口返回 `Cache-Control: no-store`，记录不保存在 localStorage。数据库管理者可以访问记录，持仓并非端到端加密。

状态修改在事务内完成，保留最近 50 个旧状态。Passkey 绑定网站域名，丢失所有 Passkey 时没有公开的密码绕过入口。

免费服务空闲时会休眠。页面打开时每分钟请求行情，关闭后不主动采集；财务与预测按北京时间更新日每天检查一次。应用缓存和配额计数持久保存于数据库；yfinance 自身的 cookie/时区临时文件不作为自选股或持仓存储。

## 验证

开发测试使用 Flask 测试客户端、注入的测试数据库及虚拟认证器，不提供单独的本机网站服务。运行：

```sh
cd dashboard
python -m unittest test_cloud test_metrics test_refresh test_alpha
node --check public/app.js
node --check public/auth-client.js
node test_positions.cjs
```

2026-10-04 已验证 Supabase TLS 连接、记录迁移、Render main 分支部署、HTTPS 健康检查及未登录接口返回 401。供应商在云端的实际覆盖受网络、配额和数据权限影响，缺失值明确显示。

## 来源

- [Render Flask 部署](https://render.com/docs/deploy-flask)、[Blueprint](https://render.com/docs/blueprint-spec)、[免费服务](https://render.com/docs/free)。
- [Supabase 连接方式](https://supabase.com/docs/guides/database/connecting-to-postgres)。
- [WebAuthn 注册验证](https://duo-labs.github.io/py_webauthn/registration.html)、[认证验证](https://duo-labs.github.io/py_webauthn/authentication.html)。
