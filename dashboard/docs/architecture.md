# Architecture and Authentication

This document describes the running application structure and authentication model. See [deployment](deployment.md), [server operations](server-deployment.md), [database](database-migration.md), [data and caching](data-and-caching.md), and [email](email-notifications.md).

## Request topology

```mermaid
flowchart LR
  B[Browser] --> V[Vercel static frontend and API rewrite]
  V --> T[Tailscale Funnel HTTPS]
  T --> A[Flask / Gunicorn on loopback 18765]
  A --> D[Project PostgreSQL TLS on 18766]
  A --> P[Project Mihomo proxy on 17890]
  P --> U[Selected external data and Gmail APIs]
  A --> S[Direct SEC and FRED requests]
  C[cron-job.org] --> T
```

The server is `47.114.43.129`; all persistent deployment files are beneath `/mnt/data/users/shx/FinFeed`. Database and proxy ports are not public listeners. Funnel exposes the web API only; an HTTPS tunnel does not bypass application authentication.

The application is a modular monolith with a separate static browser frontend. Browser modules use native HTML, CSS and JavaScript with a Node copying build.

## Source boundaries

| Module | Responsibility |
| --- | --- |
| `backend/app.py` | Flask factory, authentication, authorization, routes, response security |
| `backend/services/` | Home, sectors, securities, macro, holdings, news, notification workflows |
| `backend/providers/` | Longbridge market/EPS/quarterly statements/daily bars, Yahoo sessions/history, FRED, BLS, BEA and Polymarket |
| `backend/domain/` | Calculation definitions and account-state validation |
| `backend/storage/` | PostgreSQL transactions, accounts, history, cache, notification state |
| `backend/infrastructure/` | Coalesced refresh jobs, Gmail transport, sanitized failure logging |
| `dashboard/frontend/` | Canonical browser source; `manifest.json` maps public asset names |
| Repository `frontend/` | Vercel copying build, rewrites, login bridge and callback |
| `deployment/worker.py` | Gunicorn initialization without application preloading |
| `deployment/h20/` | Current project supervisor and database/backup launchers |
| `tests/` | Backend and browser-logic regression checks |

The `deployment/h20/` launchers resolve their project root through `FINFEED_H20_ROOT`. Business services coordinate provider access and calculations.

## Process and concurrency model

The supervisor launches one Gunicorn worker with 64 HTTP threads and a 180-second worker timeout. Database pools are created inside the worker, not inherited from a preloaded parent. The supervisor also owns PostgreSQL, the project proxy, Tailscale, and the daily backup loop.

Refresh jobs have independent lanes: security 4 workers; daily candles 1; financial, home, sector, macro, whales, Yahoo news and SEC news 2 each. Total queued/running capacity is 256. Same-key work is coalesced inside a worker; notification source leases provide additional database coordination. Increasing Gunicorn worker count would multiply in-memory lanes, provider sessions, and database pools and therefore requires capacity analysis.

## Passkey and session security

WebAuthn verifies the fixed origin, RP ID, challenge, signature, and user verification. The RP ID remains `finfeed-research.vercel.app`. Challenges expire after five minutes and are consumed once. Device-held private keys never enter the database; public credentials and verification metadata do.

Sessions expire after twelve hours. The dashboard stays hidden and inert until the initial server authentication check succeeds. A non-secret browser expiry hint enables an immediate login redirect for known expired sessions; successful login responses replace that hint and status checks use the remaining server lifetime without extending the session. Missing hints still require server validation. Network failures retain the authentication gate and retry after fifteen seconds. Bearer tokens are hashed in storage. Cookies use Secure, HttpOnly, and SameSite=Strict. Logout invalidates the server session. State-changing requests validate origin, JSON content, and the application's custom request header. Private responses are `no-store`.

The frontend login bridge and callback exchange short-lived authentication tickets between the fixed frontend/backend origins. Preview domains are not automatically authorized. Do not change origin settings to arbitrary incoming Host values; changing a Passkey RP ID can make existing credentials unusable.

## API groups

| API group | Purpose |
| --- | --- |
| `/api/health` | Public process liveness |
| `/api/ready` | Authenticated database and refresh-queue readiness |
| `/api/auth/*` | Registration, login, logout, credentials, frontend ticket exchange |
| `/api/accounts`, `/api/state` | Authenticated directory, shared reads, owner-only updates; `quotes=none` skips market snapshots |
| `/api/quotes?symbols=...` | Authenticated database-only public quote summaries; no provider requests |
| `/api/preferences` | Authenticated account display-order reads and owner-only updates |
| `/api/invitations`, `/api/admin/*` | Invitations and administrator operations |
| `/api/home`, `/api/home/sectors/<symbol>` | Index and sector snapshots |
| `/api/security/<symbol>` | Shared quote and financial results |
| `/api/candles/<symbol>` | Authenticated database-only daily OHLCV snapshots |
| `/api/chart-drawings/<symbol>` | Current account private drawing reads and transactional edits |
| `/api/macro/<kind>` | Macro indicators and prediction-market data |
| `/api/whales/<kind>` | Institution holdings |
| `/api/news`, `/api/news/<symbol>/<kind>` | Company disclosure indexes |
| `/api/notifications` | Current account subscription and delivery queue status |
| `/api/notifications/email`, `/api/notifications/verify` | Email verification and unbinding |
| `/api/notifications/tick` | Scheduler-token protected background trigger |

Unauthenticated account operations return 401. Cross-account writes are rejected. Scheduler credentials authorize only alert triggering, not user login or database access.

## Isolation limits

Project processes do not modify global DNS, routing, firewall, package environments, or unrelated services. Loopback, private files, and separate SQL roles prevent accidental exposure and operational interference; they are not a strong boundary against another root process or a process using the same OS identity. CPU, memory, disk, and network remain shared host resources.

## Concurrent market and statement pipeline

For supported US equities, a single lock-protected backend timer schedules market/valuation work every minute and quarterly financial work hourly, independently of browser activity. Separate bounded lanes share the Longbridge connection and provider limits. Quotes consume the hourly financial cache; browser requests read existing snapshots and use content versions for empty HTTP 304 responses. Home, Macro, institutional holdings and News refresh hourly. Yahoo remains in Home/sectors, earnings-call indexes, DXY and supported non-US/crypto market routes. Complete public market snapshots are stored in IndexedDB; account records remain server-authoritative. Daily chart history refreshes hourly. Private trend segments use a separate account-scoped local database and confirmed PostgreSQL writes; revision-based HTTP 304 reads and HTTP 409 edit conflicts support multiple devices. See [cache and rate control](data-and-caching.md).

## Browser interactions

Dialogs share the chart's entrance animation and native close behavior. Ticker buttons open daily charts; financial cells open metric details. Chart navigation, measurements, Vegas EMA channels and account-private editable trend segments run in the browser. Confirmed drawings synchronize through the authenticated API and PostgreSQL; public OHLCV snapshots and private drawings use separate browser stores. Public read failures preserve usable snapshots and retry; unconfirmed account or drawing writes are not treated as committed.

The tunnel watchdog compares local API liveness with public Funnel and Vercel connectivity every minute. Three consecutive public failures with a healthy local API permit a verified project-tunnel restart, subject to a fifteen-minute cooldown. This recovery leaves the database, backend and proxy processes running.
