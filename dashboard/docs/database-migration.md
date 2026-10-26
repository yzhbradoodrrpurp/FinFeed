# PostgreSQL Storage, Updates, Backup, and Recovery

Reviewed against storage and deployment source on October 26, 2026. The operational check confirmed the project database process and backup-marker presence; it did not run a fresh backup/restore verification.

Production storage is a dedicated PostgreSQL 17.11 installation inside `/mnt/data/users/shx/FinFeed` on `47.114.43.129`. This document covers the current database and safe transfer procedures, not previous infrastructure.

## Cluster and access

The cluster listens only on `127.0.0.1:18766`, database `finfeed`, application schema `finfeed_private`. It does not expose a public database endpoint or a filesystem Unix socket. Client connections require TLS using `sslmode=require`. An independent CA identity-verification chain is not configured; do not describe this as `verify-full`.

| Identity | Role |
| --- | --- |
| `finfeed_app` | Application login, owns application objects; no superuser, role creation, or database creation |
| `finfeed_admin` | Dedicated cluster administration and recovery |
| OS UID/GID 65534 | Unprivileged PostgreSQL process identity selected by the project launcher |

The existing OS identity is reused rather than creating a system account. Data directories are mode 700 and private keys mode 600. Shared root or same-UID processes remain outside a strong isolation guarantee. Unrelated PostgreSQL installations are not used by FinFeed.

The cluster uses data checksums with `fsync`, `full_page_writes`, and `synchronous_commit` enabled. Current sizing is 24 maximum connections, 32 MB shared buffers, 2 MB work memory, 32 MB maintenance work memory, and 80–512 MB WAL sizing. Preserve durability settings; a successful crash-recovery check is not a hardware power-loss guarantee.

## Application schema

| Table | Stored purpose |
| --- | --- |
| `owner` | Initial owner identity and compatibility state |
| `accounts` | Account names, current record state, revision |
| `account_history` | Per-account prior state snapshots |
| `state_history` | Initial owner state history |
| `credentials` | Public Passkey credentials, counters, RP metadata |
| `sessions` | Hashed bearer sessions and expiry |
| `flows` | Temporary authentication challenges and flow payloads |
| `invitations` | Hashed invitations, expiry, consumption |
| `disabled_accounts` | Administrative account disable markers |
| `revoked_passkeys` | Revoked credential markers |
| `cache` | Shared market snapshots and provider budgets |
| `notification_settings` | Verified recipient and subscribed categories/thresholds |
| `notification_cursors` | Previously seen event state and baselines |
| `notification_sources` | Source polling state and coordination |
| `notification_outbox` | Durable delivery queue and status |

Account display orders live inside account state JSON, not a separate preferences table. Market summaries from `/api/quotes` project existing cache rows without writing account records.

These fifteen application tables include both user records and reusable market state. Counts change during normal saves, polling, and expiry cleanup; old row counts are not a permanent acceptance criterion.

## Connections and transactions

The worker owns an account/session pool with 1–4 connections and a separate cache pool with 0–2 connections. Pool checkout/connect limits are eight seconds, connections are checked on checkout, and uncertain socket reads close the connection rather than replaying a possibly committed write. TCP keepalives and user timeout reduce silent connection retention. Prepared statements are disabled. Transactions commit or roll back before a connection is returned.

Application initialization serializes schema updates with a PostgreSQL advisory transaction lock, creates missing application objects, revokes public schema/table access, and applies compatibility updates. SQLite is a test injection, not production storage. Schema changes must be reviewed in `backend/storage/store.py` and `backend/storage/notifications.py`; there is no separate versioned migration framework to substitute for that review.

State writes validate content, use revision/row locking, and retain the latest fifty previous states. Notification enqueueing and cursor advancement are transactional. Unknown write outcomes must be resolved by reading durable state rather than blindly repeating writes.

## Consistent archive creation

`deployment/h20/database_tools.py` provides `snapshot(url, archive)` and `verify(url, manifest)`. A snapshot:

1. Opens a read-only repeatable-read transaction and exports a PostgreSQL snapshot.
2. Reads all application tables using UTC and `extra_float_digits=3`.
3. Sorts JSONB row representations using C collation and computes length-framed UTF-8 SHA-256 digests and counts.
4. Records sequence values and `is_called` flags.
5. Runs project `pg_dump` in custom format using that same exported snapshot, restricted to `finfeed_private`, without owner/ACL restoration metadata.
6. Writes a companion manifest and log, with private file permissions.

The archive refuses to overwrite an existing file. Credentials are supplied through private configuration/environment, not command arguments. Archives contain confidential records and must not enter Git or public downloads.

On the server, a manual archive can be created without printing credentials:

```python
from pathlib import Path
from datetime import datetime, timezone
import json, sys
root = Path('/mnt/data/users/shx/FinFeed')
sys.path.insert(0, str(root / 'app/dashboard/deployment/h20'))
from database_tools import snapshot
config = json.loads((root / '.private/backend.json').read_text())
name = datetime.now(timezone.utc).strftime('manual-%Y%m%dT%H%M%SZ.dump')
snapshot(config['DATABASE_URL'], root / '.postgres/backups' / name)
```

## Scheduled backups

With `.private/postgresql-enabled`, the supervisor runs `database_backup.py`. It creates one consistent archive per UTC day, checks again every hour, retries failures on the next check, and atomically updates `.runtime/database-backup.json` after success. Archives, manifests, and logs are under `.postgres/backups`. There is no automatic deletion or off-server replication.

The historical October 10 production backup was checked successfully; that receipt is not verification of the newest daily archive. A separate final transfer archive and manifest were copied off-server and SHA-256 checked during deployment. This does not constitute a continuing off-server backup policy. Configure and test a separate encrypted off-server copy if protection against host/storage loss is required; monitor archive growth meanwhile.

## Restore and host/database transfer

Never restore over the sole production database or copy a live cluster directory as a consistent logical backup.

1. Preserve current code/configuration and take consistent archives of relevant databases.
2. Create a separate empty database under the project cluster administrator.
3. Restore with the project `pg_restore`, `--exit-on-error --single-transaction --no-owner --no-acl --role=finfeed_app`, using a private connection environment.
4. Compare all table counts/content hashes and sequences with the matching manifest using `verify`.
5. Check schema/constraints, TLS, account directory, original Passkey RP ID, record saves, cache reads, and notification state.
6. For a live transfer, stop/fence source writes and scheduling, take a final consistent archive, repeat restore and exact verification, then switch application configuration.
7. Remove any transfer-only write fences from the target only after verification. Preserve source protection and archives.
8. Resume one backend and one scheduler; verify actual frontend operations and observe subsequent writes.

The last production transfer matched all fifteen application tables, including account records, credentials, histories, caches, and notification state. The seven accounts and eight public credential records were retained at that snapshot; normal transient expiry remains active.

## Rollback and maintenance

Database-aware rollback must preserve changes made after cutover. Stop writes and scheduling, archive the latest state, restore/verify it in the rollback target, and only then switch connections. Switching to a stale snapshot can lose newly saved holdings, accounts, or alert settings.

Never run `initdb` on `.postgres/data`, overwrite it during code synchronization, or start two postmasters against it. Do not rotate SQL passwords without updating private application and backup configuration together. Test restore before relying on a backup. Retain manifests and off-server checksums with their corresponding archives.

Implementation references: `backend/storage/store.py`, `backend/storage/notifications.py`, and `deployment/h20/database*.py`. Official operational references: [pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html) and [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html).
