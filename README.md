# FinFeed

FinFeed is a capital-market research dashboard with US market quotes, sector ETF charts, watchlists, portfolios, macroeconomic indicators, institutional holdings, company disclosures, Passkey accounts, and email alerts.

## Production system

| Component | Current implementation |
| --- | --- |
| Website | [finfeed-research.vercel.app](https://finfeed-research.vercel.app), static frontend on Vercel |
| API | Python / Flask / Gunicorn on the dedicated project at `47.114.43.129` |
| Public API entry | [finfeed.tail03a68f.ts.net](https://finfeed.tail03a68f.ts.net), Tailscale Funnel HTTPS |
| Database | Project-owned PostgreSQL 17.11, loopback TLS, `finfeed_private` schema |
| Outbound connectivity | Project-only Mihomo proxy; explicit provider routing |
| Email | Gmail HTTPS API with send-only OAuth authorization |
| Alert scheduling | External cron-job.org POST every minute |
| Process management | Project Python supervisor, independent of interactive SSH sessions |

Production configuration was checked on October 10, 2026 (Asia/Shanghai). Runtime status and provider availability can change. Frontend publishing and backend deployment are separate operations.

## Features

- Three major US equity indices and eleven Select Sector SPDR ETFs with three-year daily charts and draggable ordering.
- Independent watchlists and portfolios, financial metrics, currency-aware valuation, imports, and exports.
- NFP, PCE, DXY, ten-year Treasury yields, and meeting-specific Polymarket pricing.
- SEC 13F institutional holdings and company earnings-call / filing indexes.
- Passkey login, invitation registration, account sharing, administration, and verified email subscriptions.

Market polling does not make upstream data real-time. Daily yields and quarterly holdings are not intraday quotes or trading records. See the [application guide](dashboard/README.md) for calculation and access boundaries.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `frontend/` | Vercel build wrapper, rewrites, and authentication bridge |
| `dashboard/frontend/` | Canonical pages, styles, browser scripts, and asset manifest |
| `dashboard/backend/` | API, business services, providers, calculations, storage, and transport |
| `dashboard/deployment/` | Build tools, worker entry points, project service management |
| `dashboard/tests/` | Backend and frontend regression checks |
| `dashboard/docs/` | Technical documentation and operational runbooks |
| `AGENTS.md` | Development and security instructions |

Personal research under `personal/`, local credentials, runtime caches, and database archives are excluded from version control and deployments. Git history is not a private storage mechanism.

## Technical documentation

- [Architecture and authentication](dashboard/docs/architecture.md)
- [Production configuration and deployment](dashboard/docs/deployment.md)
- [Server operations and code synchronization](dashboard/docs/server-deployment.md)
- [Database updates, backup, and restore](dashboard/docs/database-migration.md)
- [Data providers, requests, and caching](dashboard/docs/data-and-caching.md)
- [Gmail and notification delivery](dashboard/docs/email-notifications.md)

## Development verification

From the repository root, with the dashboard virtual environment prepared:

```sh
dashboard/.venv/bin/python dashboard/tests/run.py
node frontend/build.cjs
git diff --check
```

Use the unified test runner for code changes; documentation-only changes require link, configuration, and consistency checks. A passing health check is not a functional acceptance test.

Account display preferences synchronize Watchlist metric-group order and Home sector-card order through authenticated backend endpoints and PostgreSQL account state. Watchlist group headings support long-press dragging and keyboard reordering.
