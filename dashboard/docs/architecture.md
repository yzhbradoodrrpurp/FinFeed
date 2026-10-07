# Dashboard 代码结构

## 目录职责

- `backend/app.py`：Flask 应用、登录、权限和路由；本轮保持完整，避免同时改动认证控制流。
- `backend/services/`：证券、宏观、机构持仓、新闻和首页业务。证券数据为 Watchlist 与 Portfolio 共用。
- `backend/providers/`：FRED 观测值、BLS/BEA 发布日历、Yahoo 会话与诊断、Alpha Vantage 和 Polymarket。
- `backend/domain/`：财务/宏观计算、账户记录校验。
- `backend/storage/store.py`：数据库连接池、事务、账户和缓存存储；本轮不改变 schema 或拆分事务。
- `backend/infrastructure/`：刷新队列、脱敏日志。
- `frontend/pages/`、`styles/`、`js/core/`、`js/components/`、`js/views/`、`assets/`：前端源码。
- `frontend/manifest.json`：原静态 URL 文件名到源码路径的唯一映射；Flask 和 Vercel 构建共同使用。
- `deployment/`：构建、Gunicorn worker、启动与可选代理。根目录两个脚本保留 Render 原有命令。
- `tests/backend/`、`tests/frontend/`：Python 与 Node 回归测试；`tests/run.py` 为统一入口。

仓库根目录 `frontend/` 是 Vercel 部署包装，不是第二套业务前端。它从 `dashboard/frontend/` 构建到 `frontend/dist/`，保持原 URL 和脚本顺序。

## 稳定性约束

本轮不更换框架、数据源或第三方依赖，不修改页面源码、API URL、Cookie、返回格式、缓存键、数据库表、刷新间隔及并发限制。`backend/paths.py` 将磁盘缓存和代理二进制继续定位到 `dashboard/.cache/`，私有配置继续保留在 `.local/`；这些目录不提交。

宏观数据链：FRED 提供 BLS 非农/失业率/时薪、BEA PCE 和 H.15 收益率序列；BLS/BEA 直接提供发布日历；Yahoo 提供 DXY 日线。`services/macro.py` 组合结果，`domain/macro_metrics.py` 保留原计算及缺月判断。

这是第一阶段目录迁移。`app.py` 路由拆分、`store.py` 内部拆分，以及其他业务模块中尚存的供应商调用提取，留待单独变更，不宣称已完成全部分层。

## 验证

从仓库根目录执行：

```sh
dashboard/.venv/bin/python dashboard/tests/run.py
```

覆盖后端、前端逻辑、旧静态 URL、启动参数、worker fork 行为和前端构建。前端为原生脚本，不引入打包运行时；源码移动不增加网络请求。
