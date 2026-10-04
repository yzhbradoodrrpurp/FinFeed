# 私人云端部署：Render + Supabase + Passkey

实现状态：云端入口、Passkey、持久存储和迁移已实现并在本机验证；真正的 Render/Supabase 部署需要账户、项目和私密连接配置。没有账号密码登录接口，也不开放其他人注册。仅有一个私人账户。

## 1. 创建 Supabase 数据库

1. 在 <https://supabase.com/dashboard> 登录，创建 **Free** 项目。
2. 保存数据库密码到密码管理器。
3. 项目的 **Connect** 窗口选择 **Session pooler**，复制 PostgreSQL URI。该方式支持 IPv4；后端连接要求 TLS。密码中有特殊字符时，需要按 URI 规则编码，不能直接拼接。
4. URI 仅填写到 Render 的 `DATABASE_URL` 环境变量，或本机被忽略的私密配置。不要放进聊天、Git、截图或网页代码。

应用会创建 `finfeed_private` schema，存放单一账户、Passkey 公钥、会话、挑战、自选股、排序、持仓及缓存。这个 schema 不应加入 Supabase 的 **Exposed schemas**。不使用 Supabase Auth；Passkey 由 Python 后端按 WebAuthn 协议验证。浏览器不会取得数据库密码、service-role key 或 Passkey 私钥。

## 2. 准备本机记录与首次绑定码

在仓库根目录运行：

```sh
dashboard/.venv/bin/python dashboard/cloud_admin.py prepare
```

生成两个已被 Git 忽略、权限为 600 的私密文件：

- `dashboard/.local/cloud-migration/records.json`：当前自选股及顺序、持仓数量、平均成本和币种。
- `dashboard/.local/cloud-migration/bootstrap-code.txt`：高强度首次绑定码。重复准备不会重建它。

只在本机编辑器/密码管理器中查看绑定码，将它填写到 Render 的 `FINFEED_BOOTSTRAP_TOKEN`。不要公开这些文件。迁移文件是生成时的快照；部署前若又修改记录，应重新运行 `prepare`。

## 3. 在 Render 部署

1. 登录 <https://dashboard.render.com/>，授权读取 FinFeed GitHub 仓库。
2. 创建 **Blueprint**，选取包含根目录 `render.yaml` 的分支。使用免费方案。
3. 填入 `DATABASE_URL` 与 `FINFEED_BOOTSTRAP_TOKEN`。
4. 等待部署，记录 Render 实际分配的 HTTPS 网站地址。

Blueprint 的主要设置：

| 项目 | 值 |
| --- | --- |
| Root Directory | `dashboard` |
| Build Command | `pip install -r requirements-cloud.txt` |
| Start Command | `gunicorn 'cloud:create_app()' --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180` |
| Health Check | `/api/health` |
| Plan | Free |

前端与后端同站部署，没有跨域接口。应用默认从 Render 的 `RENDER_EXTERNAL_URL` 获取唯一可信网站 origin；绑定自定义域名时，需在首次注册 Passkey **前**设置 `PUBLIC_ORIGIN=https://实际域名`，不含路径。不能根据任意来访 Host 动态选择 RP ID。

Alpha Vantage 为可选备用源：在 Render 环境变量中单独添加 `ALPHAVANTAGE_API_KEY`。所有指标优先 Yahoo/yfinance，只有对应下一财季预测缺失时才尝试备用源。不要上传本机 API Key 配置文件。

## 4. 首次绑定 Passkey 与迁移

1. 在最终 HTTPS 网站打开登录页，输入首次绑定码。
2. 选择“绑定我的 Passkey”，在 Safari/Chrome/Edge 的系统提示中用指纹、面容或系统解锁确认。
3. 首次绑定成功后，设置码不再允许注册另一个账户；后续用 Passkey 登录。
4. 在“我的账户 → 选择导入文件”中选择私密 `records.json`。页面会显示标的数和持仓数，点击“确认替换云端记录”导入。
5. 检查排序、持仓数量和平均成本，刷新页面，再退出并用 Passkey 登录检查一次。
6. 登录后五分钟内可添加备用 Passkey；超过时间先退出并重新验证。添加同一把 Passkey 会被拒绝，应选择另一把/另一台设备的通行密钥。

也可以在本机直接导入数据库的空记录。把 URI 保存到被 Git 忽略的 `dashboard/.local/cloud-config.json`，内容为 `{"DATABASE_URL":"你的私密 URI"}`，设置文件权限为 600，然后运行：

```sh
dashboard/.venv/bin/python dashboard/cloud_admin.py import --config dashboard/.local/cloud-config.json
```

这个命令只允许写入尚未初始化的云端记录；已有记录时拒绝覆盖。网页导入则需登录及明确点击确认，原记录会留存历史备份。

## 登录与数据安全行为

- WebAuthn 注册和认证都要求 user verification，并验证固定 origin、RP ID、随机挑战和签名。随机挑战五分钟有效且一次性消费。
- 首次注册要求至少 32 字符的私密设置码；用工具生成的码具有足够随机性。仅已登录且最近五分钟验证过的账户能添加备用 Passkey。
- 会话十二小时过期，Cookie 为 `Secure`、`HttpOnly`、`SameSite=Strict`，使用 `__Host-` 前缀；退出登录会在数据库撤销该会话。
- 所有行情、自选股、持仓和 Passkey 列表接口都检查服务端会话。未登录返回 401，主页转向登录页。写操作要求准确的 Origin、JSON 和自定义请求头。
- 云端页面不把自选股和持仓镜像到 localStorage；私人页面和接口返回 `Cache-Control: no-store`。
- 持仓按数量与平均成本记录，不储存券商登录信息。数据存入云端数据库，并非客户端端到端加密；有数据库管理权限的人能访问记录。
- 每次状态修改在事务中写入，保留最近 50 个旧状态。数据库和 Passkey 的备份应由账户所有者保管；丢失所有 Passkey 时没有公开的密码绕过入口。
- Passkey 绑定网站域名；更换域名不能直接使用旧域名的 Passkey。确定最终地址后再注册。
- 免费服务器空闲时会休眠。页面打开时每分钟请求行情，关闭后不主动采集；财务与预测按北京时间更新日每天检查一次。季度快照及 Alpha 配额计数也持久化到数据库，服务器重启不会丢掉日度检查记录。

## 已验证与待上线验证

- 单元测试：未登录访问、非法 Origin/Host、首次注册归属、挑战过期/重放、退出撤销、未知/伪造凭据、额外 Passkey 的近期验证、部分状态修改和备份、缓存跨重启。
- Chromium 虚拟认证器：真正执行 WebAuthn 注册、签名登录、退出、绑定第二把 Passkey 并用第二把重新登录；不是只模拟“登录成功”按钮。
- 本机 PostgreSQL/TLS：私有 schema、数据写入/读取、历史记录、缓存、挑战消费与重启后读取。
- 上线还需验证：真实 Supabase 连接、Render 构建/HTTPS、云端 Yahoo 数据访问、实际设备 Passkey，以及本人数据迁移后的完整核对。

## 来源

部署规则核验于 2026-10-04（Asia/Shanghai）：

- [Render Flask 部署](https://render.com/docs/deploy-flask)、[Blueprint 配置](https://render.com/docs/blueprint-spec)、[免费服务限制](https://render.com/docs/free)。
- [Supabase PostgreSQL 连接及 Session pooler](https://supabase.com/docs/guides/database/connecting-to-postgres)。
- [py_webauthn 注册验证](https://duo-labs.github.io/py_webauthn/registration.html)、[认证验证](https://duo-labs.github.io/py_webauthn/authentication.html)。
