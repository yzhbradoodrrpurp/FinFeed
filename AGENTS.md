# FinFeed Development Instructions

## Scope and layout

FinFeed is a capital-market research website. Canonical browser sources live in `dashboard/frontend/`; the repository-level `frontend/` directory wraps Vercel publishing. Python services live in `dashboard/backend/`, operational tools in `dashboard/deployment/`, tests in `dashboard/tests/`, and technical documentation in `dashboard/docs/`.

Personal research and records belong in ignored `personal/`. Do not upload that directory, local credential files, database archives, or ignored runtime state.

## Working requirements

1. Inspect current code, relevant documentation, and Git status before editing. Preserve user changes.
2. Preserve account permissions, Passkey compatibility, API paths, calculation definitions, cache semantics, and existing features.
3. Verify behavior proportionately. Distinguish implemented, tested, deployed, accepted by a provider, and actually delivered.
4. Run `dashboard/.venv/bin/python dashboard/tests/run.py` from the repository root for regression verification when needed. Documentation-only changes do not require a full application test run.
5. Keep English documentation consistent with current code and production configuration. Do not describe unused platforms as active infrastructure.

## Financial data and security

- Prefer original publishers. Preserve source, reporting period, retrieval time, timezone, unit, revision basis, and delay indicators. Never invent missing observations.
- Separate official facts, market expectations, and inference. Prediction-market prices are not official policy commitments; do not promise investment returns.
- Respect provider licenses, rate limits, and SEC fair-access requirements. Keep successful snapshots when refreshes fail and label stale data.
- Never commit or print API keys, cookies, OAuth credentials, proxy subscriptions, database passwords, account records, or backups.
- Never force-add ignored private files. Build and synchronize explicit application paths rather than the entire working tree.
- Do not introduce authentication bypasses for testing or deployment.

## Production boundaries

The frontend is on Vercel. The backend, PostgreSQL, proxy, and HTTPS tunnel run under `/mnt/data/users/shx/FinFeed` on `47.114.43.129`. Follow the deployment, server, database, and email runbooks.

- Manage only FinFeed-owned files and verified processes. Do not change other projects, global Python, system services, firewall rules, DNS, or routing.
- A push to `main` publishes the frontend; the server application snapshot requires an explicit separate update.
- Never synchronize over `.private`, `.postgres`, `.proxy`, `.tailscale`, `.venv`, or `.runtime` during an application update.
- Back up and verify databases before schema changes or restore. Preserve source copies and include post-cutover writes in any rollback.
- Do not run duplicate supervisors, schedulers, database clusters, or copies of the public tunnel identity.
- Infrastructure deletion, Git history rewriting, and database cleanup are separate operations requiring task-specific authorization.

## Product documentation boundary

The root [README](README.md) is a public feature overview. Keep it focused on user capabilities, research context and access expectations. Do not add host addresses, runtime topology, dependency lists, repository layout or deployment instructions there. Keep technical documentation in English. The README feature illustration lives in `dashboard/docs/assets/finfeed-overview.svg`; it is conceptual artwork with no account records or live financial observations.

## Architecture and production reference

Reviewed against repository source and a read-only service check on October 26, 2026 (Asia/Shanghai). This is a configuration reference, not a continuous health guarantee.

| Component | Current implementation |
| --- | --- |
| Website | `https://finfeed-research.vercel.app`, static frontend on Vercel |
| Browser application | Native HTML/CSS/JavaScript modules; Node copying build; no Vue/React/Vite migration has been implemented |
| API | Python / Flask / Gunicorn on the dedicated project at `47.114.43.129` |
| Public API entry | `https://finfeed.tail03a68f.ts.net`, Tailscale Funnel HTTPS |
| Database | Project-owned PostgreSQL 17.11, loopback TLS, `finfeed_private` schema |
| Outbound connectivity | Project-only Mihomo proxy with explicit provider routing |
| Email | Gmail HTTPS API with send-only OAuth authorization |
| Alert scheduling | External cron-job.org POST every minute; optional local scheduler remains disabled |
| Process management | Project Python supervisor, independent of interactive SSH sessions |

The application is a modular monolith with a separate static frontend. Requests traverse Vercel's API rewrite and Funnel before reaching Flask on `127.0.0.1:18765`. PostgreSQL uses `127.0.0.1:18766`; the project proxy uses `127.0.0.1:17890`. The launcher uses one Gunicorn worker, 64 HTTP threads and a 180-second worker timeout. Public market data is shared, while account records and writes retain authentication and authorization controls. Preserve the production Passkey RP ID `finfeed-research.vercel.app`.

Longbridge supplies supported US market, EPS, valuation and quarterly financial data. Company SEC filings and institutional 13F holdings use official SEC APIs. Yahoo supplies Home/sectors, DXY, earnings-call indexes and supported non-US/crypto market routes. FRED supplies macro observations; BLS/BEA provide release-calendar information, and Polymarket supplies contract-specific market expectations. Keep provider period, provenance and missing-value semantics intact.

Watchlist and Portfolio startup uses `/api/state?quotes=none`, then database-only `/api/quotes` summaries and normal per-symbol refreshes. Public snapshots use browser storage, worker memory and PostgreSQL; committed account records and notification state are authoritative in PostgreSQL. Financial details and TTM/blended Forward P/E definitions are in the application guide and data runbook. Polling intervals and source publication times are distinct.

## Repository reference

| Path | Responsibility |
| --- | --- |
| `frontend/` | Vercel build wrapper, rewrites and authentication bridge |
| `dashboard/frontend/` | Canonical pages, styles, browser scripts and asset manifest |
| `dashboard/backend/` | API, business services, providers, calculations, storage and transport |
| `dashboard/deployment/` | Build tools, worker entry points and project service management |
| `dashboard/tests/` | Backend and frontend regression checks |
| `dashboard/docs/` | Technical documentation, operational runbooks and README illustration |
| `dashboard/README.md` | Application behavior, permissions and financial definitions |
| `AGENTS.md` | Contributor instructions and technical entry point |

Personal research under `personal/`, local credentials, runtime caches and database archives are excluded from version control and deployment. Git history is not a private storage mechanism. Build and synchronize explicit application paths.

## Technical documentation index

- [Application guide](dashboard/README.md)
- [Architecture and authentication](dashboard/docs/architecture.md)
- [Production configuration and deployment](dashboard/docs/deployment.md)
- [Server operations and code synchronization](dashboard/docs/server-deployment.md)
- [Database updates, backup and restore](dashboard/docs/database-migration.md)
- [Data providers, requests and caching](dashboard/docs/data-and-caching.md)
- [Gmail and notification delivery](dashboard/docs/email-notifications.md)

## Development verification reference

From the repository root, with the dashboard environment prepared:

```sh
dashboard/.venv/bin/python dashboard/tests/run.py
node frontend/build.cjs
git diff --check
```

The unified runner includes the static build. Documentation-only updates require local-link, configuration-consistency and illustration/render checks rather than the full application suite. A passing health check is not functional acceptance. Keep dated test results, source acceptance and observed email delivery distinct.

Account display preferences persist Watchlist metric-group order and Home sector-card order through authenticated endpoints and PostgreSQL account state. Watchlist handles support long-press dragging and keyboard reordering. Frontend publishing and backend snapshot synchronization remain separate; documentation-only synchronization does not require a backend restart or an application release-marker change.
