# Server Operations and Synchronization

Reviewed on October 26, 2026 against deployment sources and a read-only check of the release marker, owned service PIDs, local health and scheduler markers. No credentials or account records were exported.

Current host: `47.114.43.129`. Project root: `/mnt/data/users/shx/FinFeed`. Frontend hosting remains on Vercel. This runbook manages only FinFeed; do not restart or reconfigure unrelated host services.

## Filesystem layout

| Path under the project root | Content and handling |
| --- | --- |
| `app/dashboard` | Deployed application snapshot; update explicitly |
| `.python` | Project Python 3.12 runtime |
| `.venv` | Independent application packages |
| `.private/backend.json` | Private environment configuration, mode 600 |
| `.private/postgresql.json` | Cluster administrator credentials and OS process identity, mode 600 |
| `.private/postgresql-enabled` | Enables database and backup supervision |
| `.private/scheduler-enabled` | Enables optional local scheduler; absent in current production |
| `.private/retired-deployment` | Safety fence: supervisor refuses to start when this exists |
| `.postgres/engine` | PostgreSQL 17.11 executables and libraries |
| `.postgres/data` | Live cluster; never overwrite with application synchronization |
| `.postgres/tls` | Database TLS certificate and private key |
| `.postgres/backups` | Private consistent archives, manifests, and reports |
| `.proxy` | Project Mihomo executable and private node configuration |
| `.tailscale` | Portable Tailscale binaries, unique device state, and certificates |
| `.runtime` | PID files, supervisor lock, logs, backup success marker |
| `.pip-cache` | Project package download cache |
| `app/dashboard/.cache` | Application/provider working cache; not user records |

The project proxy routes `tailscale.com` and its subdomains directly before the upstream catch-all rule. This keeps tunnel control and DERP connections independent of the market-data VPN node. Yahoo, Gmail and other configured data requests continue using the upstream proxy. This rule affects only traffic through the FinFeed loopback proxy; it does not change system routing, DNS or other projects. Direct connectivity still depends on the server network.

On October 28, 2026, the owner-provided replacement subscription was imported and a tested node replaced the previous October 21 Hong Kong 03 configuration. The subscription endpoint returned HTTP 403 from the server; it was downloaded locally with HTTPS verification and transferred privately. The selected node passed Yahoo, SEC, Polymarket and Gmail API connectivity checks with proxy-node certificate verification enabled. The former self-signed-node exception is no longer enabled for this selected node. Production checks also read Yahoo/yfinance daily history, SEC filings, Polymarket history and public API health. Only the verified project proxy process was restarted; other service PIDs were unchanged. A private rollback configuration and receipts are retained in `.runtime/proxy-20261028`. These are dated checks, not a future availability or email-delivery guarantee. Node credentials and subscription contents must remain outside Git.

Private state is not in Git. A code checkout alone cannot reconstruct production credentials, live records, or tunnel identity.

## Supervision and startup

The executable entry is `app/dashboard/deployment/h20/supervise.py`; its directory name is a compatibility path. The root can be overridden with `FINFEED_H20_ROOT` for a deliberately separate installation. Production uses the default root above.

The supervisor takes an exclusive file lock, removes inherited global proxy variables from application environments, loads private configuration, and launches owned child processes. It restarts exited children. SIGTERM or SIGINT shuts down its child process groups, waiting before force termination. The database launcher drops root privileges to configured UID/GID 65534 before starting PostgreSQL.

To start an already provisioned, stopped deployment, first confirm no supervisor is running and no conflicting standalone FinFeed child remains. Run this on the server:

```python
from pathlib import Path
import subprocess
root = Path('/mnt/data/users/shx/FinFeed')
with (root / '.runtime/supervisor.log').open('ab') as log:
    subprocess.Popen(
        [str(root / '.venv/bin/python'),
         str(root / 'app/dashboard/deployment/h20/supervise.py')],
        cwd=root / 'app/dashboard', stdin=subprocess.DEVNULL,
        stdout=log, stderr=log, start_new_session=True)
```

The detached process survives SSH disconnection. This is not tmux and is not an installed system boot service. A host reboot requires a permitted project startup hook or manual startup. Do not promise automatic boot recovery until it is configured and tested.

## Safe stopping and restart

PID files are hints, not authority: PIDs can be reused. Before signaling a PID from `.runtime`, inspect `/proc/<pid>/cmdline`, its working directory, and the expected project executable. Backend command lines contain the project `worker.py`; they need not contain the literal word `gunicorn`.

- To reload only application code/configuration, terminate the verified backend process group and let the supervisor restart it. Existing requests can be interrupted; schedule disruptive changes.
- To stop the whole project, signal the verified supervisor and wait for owned children to exit and the supervisor PID file to be removed.
- Never use host-wide `pkill`, stop a system database, or kill an unfamiliar port owner.
- Never start a second supervisor or clone an active Funnel identity.

## Code synchronization

GitHub `main`, Vercel's build, and the server snapshot are three distinct release states. Record the deployed commit in the release notes or operational record; inspect differences before replacing server files.

A safe release workflow is:

1. Confirm a clean/scoped local diff and an accepted commit.
2. Prepare a staging directory under the project root containing only deployable application files.
3. Exclude `personal/`, `.local/`, `.cache/`, virtual environments, bytecode, logs, credentials, and archives.
4. Compare the staged snapshot and validate dependencies before replacing application files.
5. Synchronize only `dashboard` application source into `app/dashboard`; preserve runtime cache paths explicitly. Never apply deletion to the entire project root.
6. Install changed dependencies into `.venv`, run `pip check`, and retain the previous code/dependency snapshot for rollback.
7. Restart the verified backend only when application code or runtime configuration requires a reload, then check private/public requests and real feature behavior. Documentation and README assets alone do not require a service restart. Record a documentation-only synchronization separately from the application release marker.

For dependency installation, avoid the host's inherited package-manager configuration. Use process-local overrides, without changing global settings:

```sh
PIP_CONFIG_FILE=/dev/null PIP_INDEX_URL=https://pypi.org/simple   /mnt/data/users/shx/FinFeed/.venv/bin/python -m pip install   --cache-dir /mnt/data/users/shx/FinFeed/.pip-cache   -r /mnt/data/users/shx/FinFeed/app/dashboard/requirements-cloud.txt
/mnt/data/users/shx/FinFeed/.venv/bin/python -m pip check
```

Use the explicit project proxy for this command only if the selected package source requires it. Do not weaken TLS verification. A failed dependency update must not be treated as a complete release.

## Monitoring and maintenance

Check only project PID files and paths. The expected active services are supervisor, database, proxy, Tailscale, backend, and database-backup. The external scheduler is separate.

| Check | Meaning |
| --- | --- |
| `/api/health` locally, via Funnel, and via Vercel | Distinguishes app, tunnel, and frontend routing availability |
| Authenticated `/api/ready` | Database/queue readiness, not every supplier's availability |
| `.runtime/backend.log`, `request_failure` entries | Sanitized provider and API failures |
| `.runtime/proxy.log`, `tailscale.log`, `supervisor.log` | Project networking and child lifecycle |
| `.runtime/database-backup.log` and `database-backup.json` | Backup attempt and last successful UTC day |
| Disk, memory, swap, database connections | Shared resource pressure and growth |
| cron-job.org execution history | Trigger acceptance; not email delivery |
| Notification queue counters | Pending, accepted, failed, or uncertain delivery work |

Application failure logs include UTC time, operation/source, request ID, status, exception type, and available duration. They omit request bodies, full query URLs, cookies, and account identities; do not add secret-bearing exception dumps while debugging. Logs currently have no automatic rotation. Backups have no automatic retention deletion. Monitor growth and manage only scoped files after preserving needed evidence.

## Recovery priorities

1. Separate local backend failure from public tunnel or outbound provider failure.
2. Check database TLS and readiness before changing unrelated infrastructure.
3. Preserve successful caches during provider outages; do not replace missing data with zero.
4. Confirm OAuth authorization and queue state before retrying uncertain mail.
5. For database damage, restore into a separate database and verify a consistent manifest before switching.
6. For host replacement, stop the old deployment, fence writes, transfer the final verified data, and move the unique tunnel identity only after the previous daemon stops.

A rollback must include records written after release/cutover. See [database operations](database-migration.md). Daily off-server backups and automatic host-boot recovery are not yet configured.

## Documentation and product assets

The root `README.md` is a product-facing overview. Keep architecture, repository layout, runtime endpoints and development verification in `AGENTS.md` and the linked technical runbooks. `dashboard/docs/assets/finfeed-overview.svg` is a conceptual feature illustration, not an authenticated screenshot or a source of market observations. It is repository documentation, not a new application asset or frontend build dependency.

## Tunnel health recovery

The FinFeed backend worker starts one lock-protected tunnel health thread when the project launcher enables `FINFEED_TUNNEL_WATCHDOG`. Every minute it checks the local API and the public Funnel route, with the Vercel API route through the existing project proxy as a second check. The separate egress avoids treating blocked direct outbound HTTPS as a tunnel failure. Three consecutive public failures while the local API remains healthy permit a restart of the verified FinFeed Tailscale process group through the existing supervisor. Recovery has a fifteen-minute cooldown retained across backend reloads. It never changes routing, credentials, or Funnel identity, and does not restart the database, proxy, or backend. State is recorded in `.runtime/tunnel-watchdog.json`.

This detects a stalled public tunnel even when its daemon has not exited. It cannot guarantee availability during a wider network or provider outage. Account JSON reads retry transient failures up to three times with ten-second attempt deadlines; a failed account load retries after fifteen seconds and stays in a loading state. Already loaded records remain visible during a same-account retry, with editing disabled until the server validates the state again. Private account records are not persisted in browser market caches.

## Polymarket history recovery

Polymarket outbound requests share a four-request concurrency limit. Failed fortnight history windows retry once; an incomplete or empty refresh never replaces a successful full curve. Each successful curve is stored in the existing PostgreSQL cache, keyed by event slug and outcome token, with its original retrieval time. Workers reload these snapshots after restart; failed refreshes retain the curve and expose its stale status and retrieval time separately from current prices. History is refreshed hourly, with a one-minute retry cooldown after failure. Event-request failures also retain the last snapshot and its original timestamp. No schema migration is required.

The Macro Fed endpoint supports the same NDJSON cache-first refresh protocol as other market cards. Existing database snapshots are published before outbound refresh work; concurrent clients share the background job. Browser caches remain visible while that job finishes. News startup reads only the authenticated owner's ticker list via /api/news, then reads per-symbol cached streams with bounded concurrency; it no longer downloads all archived news snapshots in a single bootstrap response. Failed list reads retry without discarding displayed news. Sector cards show skeletons until a first result arrives.
