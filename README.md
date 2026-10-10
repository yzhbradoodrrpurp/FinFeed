# FinFeed

FinFeed 是一个资本市场研究网站，集中查看美股行情、关注列表、持仓和宏观信息。

## 功能

- 主要美股指数及标普 500 的 11 个板块 ETF，支持交互式历史图表与板块排序。
- 关注列表、持仓记录、财务指标与估值数据。
- 非农就业、PCE、美元指数、十年期美债收益率及预测市场信息。
- 机构 13F 持仓与新闻信息。
- Passkey 账户登录，以及可选择类别的邮件提醒。

数据更新受供应商延迟、发布频率及限流影响；历史持仓和日度统计不是实时交易数据。具体功能、数据口径与验证边界见 [网站说明](dashboard/README.md)。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `frontend/` | Vercel 前端构建与转发配置 |
| `dashboard/backend/` | Python 后端 |
| `dashboard/public/` | 页面、样式与浏览器脚本 |
| `dashboard/deployment/` | 部署及进程管理 |
| `dashboard/tests/` | 回归验证 |
| `dashboard/docs/` | 架构和运维文档 |
| `AGENTS.md` | 开发与安全约定 |

公开仓库不包含用户账户数据、凭据或数据库备份。

## 文档与验证

- [架构说明](dashboard/docs/architecture.md)
- [生产部署](dashboard/docs/deployment.md)
- [h20 运维](dashboard/docs/h20-deployment.md)
- [PostgreSQL 与数据库迁移](dashboard/docs/database-migration.md)
- [邮件提醒](dashboard/docs/email-notifications.md)

配置及依赖准备见部署文档。回归验证从仓库根目录运行：

```bash
dashboard/.venv/bin/python dashboard/tests/run.py
```

前端由 Vercel 托管，后端与专用 PostgreSQL 在 h20 的 FinFeed 项目内运行。数据库、代理、邮件及账户凭据只保存在私密配置中，不提交 Git。
