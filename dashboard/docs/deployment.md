# Production Deployment and Configuration

## Current endpoints

| Item | Setting |
| --- | --- |
| Frontend | `https://finfeed-research.vercel.app` |
| Backend HTTPS | `https://finfeed.tail03a68f.ts.net` |
| SSH host | `root@47.114.43.129` |
| Project root | `/mnt/data/users/shx/FinFeed` |
| Backend listener | `127.0.0.1:18765` |
| PostgreSQL listener | `127.0.0.1:18766`, database `finfeed`, TLS required |
| Proxy listener | `127.0.0.1:17890` |

Reviewed on October 26, 2026 against the repository and a read-only project-service check. The server release marker identifies the October 23 category update (`de79594`); it lists that update's files, not an exhaustive hash of every deployed file. Use [server operations](server-deployment.md) for synchronization and restart, and [database operations](database-migration.md) for recovery.

## Frontend publishing

Vercel imports the GitHub repository's `main` branch with Root Directory `frontend` and Framework Preset Other. `frontend/vercel.json` runs `node build.cjs` and publishes `dist`.

`frontend/build.cjs` copies a fixed list of files from `dashboard/frontend/manifest.json`, plus the login bridge, callback, and privacy page. It does not package the entire repository. Browser scripts are native JavaScript rather than a bundled application framework.

The `/api/:path*` rewrite targets the fixed Funnel HTTPS origin. `/login` serves the bridge and `/auth/callback` serves the callback page. Static responses use `no-cache`; API responses use `no-store`. Response headers include a same-origin Content Security Policy, MIME-sniffing protection, and no-referrer policy. New assets must be added to the manifest/build copy list where applicable.

A push to `main` triggers a frontend build. It does not change the dedicated server snapshot. Check the actual Vercel deployment result before claiming publication.

## Backend dependencies

The server has a project Python 3.12 installation in `.python` and a separate `.venv`. Current direct application dependencies in `dashboard/requirements-cloud.txt` are:

| Package | Pinned version |
| --- | --- |
| yfinance | 1.7.0 |
| Flask | 3.1.3 |
| gunicorn | 23.0.0 |
| psycopg[binary] | 3.3.6 |
| psycopg-pool | 3.3.3 |
| webauthn | 2.8.0 |
| pandas_market_calendars | 5.5.0 |
| longbridge | 5.2.0 |

Transitive dependencies should also be captured privately when preparing a reproducible server update. Do not install into system Python. PostgreSQL and networking executables live in separate project directories.

## Private backend configuration

The supervisor reads `.private/backend.json` into the child environment. Keep the directory mode 700 and secret files mode 600. Values must be strings suitable for environment variables. Never publish a real configuration file.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | `finfeed_app` connection to the local `finfeed` database; encode special password characters |
| `FRONTEND_ORIGIN` | Fixed production Vercel origin |
| `PUBLIC_ORIGIN` | Fixed production Funnel origin |
| `FINFEED_BOOTSTRAP_TOKEN` | Strong first-account initialization token; existing databases must not be reinitialized |
| `FRED_API_KEY` | Macro observations and published-release-date fallback |
| `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, `LONGBRIDGE_ACCESS_TOKEN` | Server-only Longbridge market and fundamental API credentials; never sent to browsers |
| `ALPHAVANTAGE_API_KEY` | Optional legacy forecast configuration; not used by Longbridge market valuation |
| `YAHOO_SESSION_MODE` | Anonymous by default; explicit `login` only with both cookie variables |
| `YAHOO_COOKIE_T`, `YAHOO_COOKIE_Y` | Optional private Yahoo login cookies; never sent to browsers |
| `YAHOO_PROXY_URL` | Forced by the project launcher to loopback port 17890 |
| `BLS_PROXY_URL`, `POLYMARKET_PROXY_URL`, `GMAIL_PROXY_URL` | Explicit project proxy for those providers |
| `SEC_PROXY_URL` | Optional SEC routing override; current requests can use direct access |
| `SEC_USER_AGENT` | SEC-compliant application identity and contact information |
| `FINFEED_EMAIL_PROVIDER` | `gmail` |
| `FINFEED_EMAIL_FROM` | Gmail address authorized for sending |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` | Send-only OAuth credentials |
| `FINFEED_NOTIFICATION_CRON_TOKEN` | Independent random bearer secret, at least 32 characters |

Do not rotate origins casually: Passkeys, cookie transfer, and request validation depend on them. Credentials are not frontend build variables.

## HTTPS and outbound connectivity

Tailscale runs in userspace mode with an abstract control socket `@finfeed-h20-control`. Its persistent identity and certificates stay in `.tailscale`. DNS acceptance, route acceptance, and Tailscale SSH are disabled. Funnel forwards only the FinFeed HTTP listener. Keep the public identity unique; do not start the same state on two machines.

Mihomo runs from `.proxy/config.json` and listens only on loopback. Selected provider clients explicitly use the project proxy. The project uses a server-side configured subscription node, independent of the user's laptop. The last recorded October 21 cutover selected Hong Kong 03; treat the private runtime configuration as authoritative for later node changes. Destination HTTPS verification remains enabled. The explicitly approved proxy-transport TLS exception is scoped to the node connection; see [server operations](server-deployment.md). Never enable a global VPN/TUN or alter other projects' proxy settings to troubleshoot FinFeed.

## Release acceptance

1. Inspect the scoped diff and run appropriate regression checks and the static build.
2. Save a consistent database archive before schema-affecting updates.
3. Publish and verify the Vercel build; deploy the backend snapshot separately.
4. Verify local API liveness, authenticated readiness, public Funnel, and the Vercel rewrite.
5. Confirm the Vercel Passkey RP ID, unauthenticated rejection, owner-only saves, shared reads, and representative view refreshes.
6. Check upstream requests, stale-data behavior, Gmail token refresh, and external scheduler acceptance.
7. Observe a real delivery when validating mail changes. Token refresh and HTTP 202 do not prove inbox delivery.

The October 23 Bridgewater release passed 224 backend tests, frontend regression checks and the static build; SEC current/prior-quarter retrieval and cover/detail totals were checked. The earlier database transfer checked all fifteen application tables. These are dated release receipts, not proof of current provider health or every alert category's delivery. Documentation-only changes require link, source-consistency and asset checks rather than a full application regression run.
