# Dashboard 代码结构

更新于 2026-10-10（北京时间）。生产代码在 `main`；Vercel 前端、h20 后端和 Supabase 数据库的运维见 [部署说明](deployment.md)。

## 目录职责

- `backend/app.py`：Flask 应用、登录、权限和路由。
- `backend/services/`：证券、宏观、机构持仓、新闻和首页业务。证券数据为 Watchlist 与 Portfolio 共用。
- `backend/providers/`：FRED 观测值、BLS/BEA 发布日历、Yahoo 会话与诊断、Alpha Vantage 和 Polymarket。
- `backend/domain/`：财务/宏观计算、账户记录校验。
- `backend/storage/store.py`：数据库连接池、事务、账户和缓存存储。
- `backend/infrastructure/`：刷新队列、Gmail 邮件渠道和脱敏日志。
- `frontend/pages/`、`styles/`、`js/core/`、`js/components/`、`js/views/`、`assets/`：前端源码。
- `frontend/manifest.json`：原静态 URL 文件名到源码路径的唯一映射；Flask 和 Vercel 构建共同使用。
- `deployment/`：构建、Gunicorn worker、启动与可选代理。`deployment/h20/` 包含项目后端启动器、监督程序和可选本地调度器；根目录 `build_cloud.py`、`start_cloud.py` 保留 Render 备用部署命令。
- `tests/backend/`、`tests/frontend/`：Python 与 Node 回归测试；`tests/run.py` 为统一入口。

仓库根目录 `frontend/` 是 Vercel 部署包装，不是第二套业务前端。它从 `dashboard/frontend/` 构建到 `frontend/dist/`，保持原 URL 和脚本顺序。

## 稳定性约束

h20 迁移保持账户、Passkey、API 路径、Cookie、数据库 schema 和缓存键兼容，使用同一 Supabase 数据库。`backend/paths.py` 的应用临时缓存位于代码快照内的 `dashboard/.cache/`；服务器私密配置位于 `/mnt/data/users/shx/FinFeed/.private/`，代理、Tailscale、虚拟环境和日志均在项目目录内，不提交 Git。本机授权和测试文件仍可位于 Git 忽略的 `dashboard/.local/`。

后台路径：浏览器 → Vercel `/api/*` 转发 → Tailscale Funnel → h20 `127.0.0.1:18765` → 应用。出站代理只监听 `127.0.0.1:17890`，Yahoo、Gmail、BLS 和 Polymarket 通过各自显式配置使用；SEC/FRED 可直连。当前代理由服务器香港节点连接美国节点，最终出口已验证为美国，不经用户电脑，不改变系统路由或其他项目设置。

监督进程仅管理它创建的进程并自动重启退出的子进程，不安装系统服务。邮件由外部 cron-job.org 每分钟调度，项目本地调度默认关闭。服务器重启后的恢复、权限范围和日志管理边界见 [h20 运维说明](h20-deployment.md)。

宏观数据链：FRED 提供 BLS 非农/失业率/时薪、BEA PCE 和 H.15 收益率序列；BLS/BEA 优先直接提供发布日历，BLS 失败时备用读取 FRED 的 BLS 已公布日期并标注时刻口径；Yahoo 提供 DXY 日线。`services/macro.py` 组合结果，`domain/macro_metrics.py` 保留原计算及缺月判断。

2026-10-08 的目录整理保留了以下待办：`app.py` 路由拆分、`store.py` 内部拆分，以及其他业务模块中尚存的供应商调用提取，留待单独变更，不宣称已完成全部分层。

## 验证

从仓库根目录执行：

```sh
dashboard/.venv/bin/python dashboard/tests/run.py
```

覆盖后端、前端逻辑、旧静态 URL、启动参数、worker fork 行为和前端构建。前端为原生脚本，不引入打包运行时；源码移动不增加网络请求。
