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
