# 邮件提醒配置与运行

入口：登录 → 我的账户 → 邮件提醒。每个账户独立绑定并验证邮箱，独立选择 NFP、PCE、十年美债、巨鲸及 News 类别。保存时选中任一类别即启用，全部取消即停用；默认不启用。验证码只保存哈希，10 分钟有效，最多尝试五次，每分钟最多发送一次。

## Gmail 发信配置（无需自有域名）

发件人使用自己的 Gmail 账户，后台通过 HTTPS Gmail API 发信；不依赖 SMTP 端口。当前后端运行在 h20，配置位置见 [部署说明](deployment.md)和 [h20 运维说明](h20-deployment.md)。只申请 `gmail.send` 权限，不读取邮箱内容。普通收件人不需要 Google 授权。

1. 在 Google Cloud 创建专用项目，启用 Gmail API，配置 Google Auth Platform。创建桌面 OAuth 客户端，用本机回环地址完成一次发件人授权。
2. 下载桌面客户端 JSON 后，在本机运行 `python3 dashboard/deployment/authorize_gmail.py --client /完整路径/client.json --sender 发件人@gmail.com`，在 Safari 打开工具打印的本机地址并完成授权。工具使用 PKCE、随机 state、离线访问，凭据保存在 Git 忽略的 `dashboard/.local/gmail-mailer.json`，文件权限为 600。将配置转存 h20 的 `.private/backend.json` 后妥善管理本机凭据，不提交代码。
3. 在 h20 私密配置中配置 `FINFEED_EMAIL_PROVIDER=gmail`、`FINFEED_EMAIL_FROM`（授权的 Gmail 邮箱）、`GMAIL_CLIENT_ID`、`GMAIL_CLIENT_SECRET`、`GMAIL_REFRESH_TOKEN`。
4. Google 外部应用处于 Testing 时，相关 refresh token 通常七天失效；长期运行需按 Google 要求调整发布状态及验证，不能把测试授权当成永久授权。用户撤销授权等情况仍会导致失效。
5. 继续配置下方的 `FINFEED_NOTIFICATION_CRON_TOKEN` 和外部调度，再完成实际邮件验证。Gmail 个人账户有发送限额；渠道接受不代表一定进入收件箱。

Gmail 不提供发送幂等键承诺。发送前持久化为 `sending`；明确拒绝时退避重试，网络超时、服务端异常等接收状态未知时记为 `uncertain` 并暂停自动重发。进程中断留下的 `sending` 也不自动重发，需管理者核查发件箱和日志。固定 Message-ID 仅用于追踪，不宣称 Gmail 会据此去重。此策略优先避免重复邮件，状态不明时可能需要人工补发。

参考：[Gmail 发送接口](https://developers.google.com/workspace/gmail/api/guides/sending)、[桌面 OAuth 与 PKCE](https://developers.google.com/identity/protocols/oauth2/native-app)、[令牌有效期](https://developers.google.com/identity/protocols/oauth2#expiration)、[Gmail 发送限制](https://support.google.com/mail/answer/22839)。

## 外部调度与收件邮箱验证

1. 在 h20 的 `.private/backend.json` 设置 `FINFEED_NOTIFICATION_CRON_TOKEN`：独立随机字符串，至少 32 字符。可在本机运行 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成。不要提交到 Git 或贴入聊天。
2. 让 FinFeed 后端重新加载配置。在外部定时服务中设置每分钟执行一次 HTTP POST：
   - URL：`https://finfeed.tail03a68f.ts.net/api/notifications/tick`，直接调用 h20 后端。
   - Header `Authorization: Bearer <上一步生成的调度密钥>`。
   - Header `Content-Type: application/json`。
   - Body：`{}`。
   - 不把密钥放进 URL。将调度密钥保存在定时服务的加密配置中。
3. 在网站“我的账户”输入收件邮箱，发送验证码并验证，选择需要的提醒类别并保存；全部取消后保存即停用。已验证邮箱隐藏验证表单，解绑后恢复。
4. 检查定时服务日志：202 表示任务已接受，403 表示密钥不匹配，503 表示邮件服务未配置。202 不代表邮件已送达。登录后的 `GET /api/notifications` 返回本人队列计数；`sent` 表示渠道已接受，不能等同收件箱送达。

自动化测试使用模拟邮件渠道。每次首次配置渠道必须完成真实邮箱验证和一次实际触发验收；代码测试通过不代表生产邮件已送达。

## 邮件格式

验证码与各类提醒统一使用纯文本格式：`Dear {账户用户名},` 开头，随后为中文说明和实际验证码或提醒数据，末尾为 `Best regards,` 与 `FinFeed Team`。市场提醒保留来源、时间及通知设置说明；用户名取接收者自己的账户名称，不使用被查看账户的名称。

## 提醒口径

- **NFP / PCE**：优先按 BLS / BEA 官方日历；BLS 日历不可用时使用 FRED release 50 的已公布日期，按 BLS 常规 08:30 美国东部转换，并在邮件中注明日期来源与时刻口径，不推算未公布日期。取得可用日历后，发布前 24 小时窗口提醒一次；到计划发布时刻再提醒一次。计划时刻提醒明确区别于实际数据已经取得。取得新的完整数据对应期后另发数据更新邮件。启用时距发布不足 24 小时，首次检查会补发即将发布提醒。来源故障可能延迟提醒；发布时刻补发窗口为六小时。
- **十年美债**：目前沿用 H.15 / FRED DGS10 日度十年恒定期限收益率。比较连续成功读取的数据，在从低于预警线到达到/超过，或从达到/超过回落至下方时发送。默认 5.1%，可修改。首次读取或修改阈值建立基线，不把当前已在线上的状态当作新穿越。**不是实时盘中预警**。
- **巨鲸**：每小时检查网站现有机构的最新 13F 报告及修订。邮件附持仓报告期、申报时间和 SEC 原文件；不能视为实时交易。
- **News**：每小时检查收件人自己 Watchlist 中的 Earnings Calls 和 SEC Filings。沿用页面的最近两个已发布季度筛选口径。新增股票首次成功读取建立基线，之后的新条目才通知。无新内容不发邮件。

## 调度、缓存与失败处理

任务在服务器后台执行，网页无需打开。宏观检查与公司数据抓取分开运行，分别最多两个源任务并发；相同数据源按数据库租约合并。正常源间隔一小时，NFP/PCE 临近发布时检查间隔一分钟，失败五分钟后重试。复用已有成功市场缓存，发布前五分钟至发布后半小时内加快宏观源刷新。上游发布、外部定时器、平台唤醒、抓取和邮件渠道都可能产生延迟，不能保证整点零延迟。

当前 cron-job.org 每分钟调用 h20，项目本地 scheduler 默认关闭，避免重复调度。h20 监督进程不依赖浏览器或 SSH 会话；服务器/容器重启后仍需项目启动钩子或人工启动。代理与 Funnel 可用性也会影响调度。外部调度与 Gmail 渠道的额度、限制以各自账户面板为准。

订阅、已见事件和发件队列持久化到私人数据库。新内容入队和游标更新在同一事务中完成，唯一事件键防止重复排队。失败指数退避，超过 23 小时停止重试，避免发送过时提醒。故障不会把旧数据当作新事件。关闭类别（全部取消即停用）、解绑、换邮箱会取消相应待发邮件；已经提交到邮件渠道的消息无法撤回。

账户与通知数据库可用性是执行前提。没有配置发送服务时不启动监控，不额外抓取市场数据。监控不开启网站登录链路中的同步数据请求。

### 实际配置进度（2026-10-10，北京时间）

- Google Cloud 专用项目、Gmail API、桌面 OAuth 客户端及仅含 `gmail.send` 的授权已配置。应用已切换正式模式；发信配置已迁至 h20 私密文件，令牌更新已验证成功。正式模式不等于 Google 已完成应用验证，撤销授权及平台策略变化仍可能导致失效。
- 此前真实邮箱验证码已被收件人收到并完成绑定；迁移沿用原数据库，不要求重新绑定。未在此文档公布具体收件地址或令牌。
- cron-job.org 的 `FinFeed email reminders` 已启用，每分钟 POST 到 `https://finfeed.tail03a68f.ts.net/api/notifications/tick`，独立 Bearer 密钥保留在配置中，不放入 URL。保存后已重新加载核对，h20 日志连续记录自动请求返回 202。202 代表任务已接受，不代表邮件已送达。
- 提醒类别由账户分别选择，全部不选即关闭；没有独立总开关。代码默认十年美债预警线 5.1%，每个账户的实际设置以数据库和“我的账户”为准，迁移不覆盖用户值。
- Gmail 令牌更新、历史验证码收件和当前自动调度已验证；尚未逐类观察新市场事件完成真实投递，不能宣称全部事件类别已通过生产投递验收。首次成功读取仍建立基线，避免发送历史内容。
- 发信代码仅支持 Gmail，不依赖 Resend。当前 `GMAIL_PROXY_URL=http://127.0.0.1:17890` 显式使用 FinFeed 项目代理；BLS 和 Polymarket 也分别使用项目代理变量。
- 解绑与验证成功时平滑切换界面；发送后倒计时只显示数字和 `s`。空邮箱/空验证码对应按钮禁用。保存成功显示“提醒已设置”并禁用按钮，更改类别或阈值后恢复“保存提醒设置”。

此记录不包含密钥或凭据内容。真实提醒投递验收结果应在发生后补充，不能以 202 或代码测试替代。
