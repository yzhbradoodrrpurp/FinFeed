# Gmail Authorization and Notification Delivery

Reviewed against notification, storage and Gmail transport sources on October 26, 2026.

The account dialog owns recipient verification and category selection. The current server uses the Gmail HTTPS API with only `gmail.send` authorization; it does not require SMTP or a custom sender domain. Recipient accounts do not need Google OAuth authorization.

## OAuth setup and private configuration

1. Create a dedicated Google Cloud project, enable Gmail API, and configure Google Auth Platform.
2. Create a desktop OAuth client and download its private client JSON.
3. Run the local authorization helper with the intended sender:

```sh
python3 dashboard/deployment/authorize_gmail.py   --client /private/path/client.json --sender sender@example.com
```

4. Open the helper's local callback/login URL, authorize the sending account, and complete the loopback flow. The helper uses PKCE, random state, and offline access.
5. Store the resulting ignored `dashboard/.local/gmail-mailer.json` privately and transfer the required values into server `.private/backend.json`, mode 600.
6. Set `FINFEED_EMAIL_PROVIDER=gmail`, `FINFEED_EMAIL_FROM`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN`. The sender must be the authorized Gmail account; the example above is a placeholder.
7. Reload only the FinFeed backend and validate token refresh plus an actual verification email.

Current authorization uses a production-mode application. This is not a claim of completed Google app verification. Testing-mode authorizations can have short refresh-token lifetimes; production-mode tokens can still fail after revocation or policy changes. Monitor refresh failures and reauthorize when needed. Do not add mail-reading scopes to troubleshoot sending.

The transport refreshes access tokens server-side and caches them until shortly before expiry. `GMAIL_PROXY_URL=http://127.0.0.1:17890` routes token refresh and message sending through the project proxy. Browser code never receives OAuth secrets.

## Scheduler

cron-job.org currently sends an HTTP POST every minute directly to:

```text
https://finfeed.tail03a68f.ts.net/api/notifications/tick
```

Configure a JSON body `{}`, Content-Type `application/json`, and `Authorization: Bearer <private scheduler token>`. The matching `FINFEED_NOTIFICATION_CRON_TOKEN` is an independent high-entropy secret of at least 32 characters in server configuration. Never place it in a URL, Git, screenshots, or logs.

HTTP 202 means background work was accepted; 403 indicates an invalid scheduler token and 503 indicates unavailable mail configuration. Acceptance is not inbox delivery. The scheduler runs without an open browser or SSH connection.

An optional project scheduler exists behind `.private/scheduler-enabled`; this marker is absent in current production. Do not enable it while the external job remains active. A host reboot requires backend/supervisor recovery before triggers can work.

## Binding and preferences

Verification codes are hashed, valid for ten minutes, limited to five attempts, and sent no more than once per minute. The interface disables empty-field actions, displays only countdown digits plus `s`, and hides the binding form after verification. A loading state prevents a verified account from briefly appearing unbound during initialization.

Categories are per account: NFP, PCE, Treasury, institutions, and the user's own Watchlist News. Saving with any category selected enables monitoring; saving with none selected disables it. Threshold changes are persisted per subscriber. The server-loaded preferences establish the saved baseline: unchanged settings show a disabled “提醒已设置” button, including after reload. Editing a category or threshold enables saving; success updates the baseline. Unbinding, replacing the address, or disabling categories cancels affected pending messages. Already accepted messages cannot be recalled.

## Trigger definitions

| Category | Trigger and included information |
| --- | --- |
| NFP / PCE pre-release | Once in the 24-hour pre-release window; indicator, planned time in Beijing and US Eastern, calendar link and time basis |
| NFP / PCE release time | Once when the planned time is reached, with a six-hour catch-up window; explicitly distinguishes planned release from retrieved data |
| NFP / PCE data update | New complete observation period after a prior baseline; values, units, corresponding dates, retrieval time and source |
| Ten-year Treasury | Successful daily yield crosses above/equal to or below the subscriber's threshold; prior/current values and dates, H.15/FRED links |
| Institutional holdings | Newly observed reports/amendments for the nineteen supported institutions, including Trian, Bridgewater and Mubadala; report period, filing/publication date and original SEC link |
| Watchlist News | New earnings calls or SEC index entries for the recipient's own watchlist; titles, dates and original document links |

The Treasury default is 5.1%, adjustable per account. First reads and changed thresholds establish baselines rather than sending an existing above-line state as a new crossing. This is daily-statistic monitoring, not intraday touching alerts. Institution and company first reads also establish baselines, avoiding historical floods. Calls follow the page's two-quarter window; SEC detection uses the full retrieved official submissions index, independently of the display window. SEC reminders deduplicate by EDGAR accession, so a switch between the primary document and an exhibit cannot create another alert. A fixed monitoring-start timestamp and subscription start times filter historical backfill, unknown dates, and future dates; Official SEC acceptance timestamps are used for precise eligibility; legacy day-level dates remain supported. First reads establish a baseline, and legacy cursors gain a timestamp without replaying older filings. The monitoring-start boundary does not advance on each poll: genuine disclosures published after monitoring began remain eligible if the provider indexes them late or a monitoring outage delays retrieval. Future or undated entries are not marked as seen until they have a valid publication date. Previously seen identifiers are retained.

Calendars prefer BLS/BEA. The BLS fallback uses published FRED release dates, with explicit standard-time assumptions if no exact time is provided. It does not invent future dates. FRED observation availability can lag the publishing institution.

## Polling and durable delivery

Macro and company monitoring run in separate lanes, with at most two source tasks concurrently in each lane. Database leases merge repeated source polling. Normal source intervals are one hour, failure retry is five minutes, and NFP/PCE near-release checks accelerate to one minute. The five minutes before to thirty minutes after release window accelerates macro refresh. Supplier and scheduler delays remain possible.

Subscriptions, cursors, source state, and the outbox are durable PostgreSQL records. Event insertion and cursor updates share a transaction, and unique event keys prevent duplicate queue entries. Existing public market caches are reused. No configured sender means monitoring is not started and extra source fetches are avoided.

Before sending, the durable outbox transitions to `sending`. Clear rejections use bounded exponential retry; messages stop retrying after 23 hours to avoid stale alerts. A timeout, server error, or interrupted `sending` state can mean Gmail already accepted the message: these become uncertain/nonautomatic retry work. Operators must inspect the sender's sent folder and private queue state before sending it again.

Gmail does not promise application idempotency. Fixed Message-ID values help tracking but do not guarantee deduplication. The policy favors avoiding duplicate messages; uncertain messages may require manual resolution.

## Message format

Verification and market alerts are plain-text messages with a personalized English greeting/sign-off and a currently Chinese body. Usernames come from the recipient's own account, not an account they happen to be viewing.

```text
Dear {account name},

{verification or subscribed-alert introduction}

{code or event details, reporting dates, units and source links}

{subscription-management instructions for market alerts}

Best regards,
FinFeed Team
```

Subjects begin with `FinFeed` for market events. Bodies identify planned release time versus observed data and include source context. Documentation translation does not change the language or behavior of actual outgoing messages.

## Operational acceptance and troubleshooting

The October 21 authorization recovery verified a valid sender token and seven recipient-inbox messages: six company News alerts and one Treasury threshold crossing. Verification-code reception/binding and scheduled trigger acceptance also have earlier receipts. These dated observations do not prove current authorization or delivery for every category. The October 26 check confirmed only that the local scheduler marker remained absent; it did not inspect cron-job.org execution history, refresh OAuth, or send mail. Mock transport tests and HTTP 202 must not be reported as proof of delivery.

Authenticated `GET /api/notifications` provides the account's queue counts. A `sent` state means channel acceptance, not guaranteed delivery, reading, or absence from spam. Check authorization, proxy connectivity, source/calendar validity, event baseline, subscription state, and outbox status in that order. Respect Gmail account sending limits and do not repeatedly trigger real mail as a health probe.

References: [Gmail sending](https://developers.google.com/workspace/gmail/api/guides/sending), [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [token expiration](https://developers.google.com/identity/protocols/oauth2#expiration), and [sending limits](https://support.google.com/mail/answer/22839).

### SEC provider cutover

Before activating the official SEC provider, coordinate a restart of only the verified backend, save a private backup of affected SEC cursors, and transactionally set their fixed `baseline_at` to the recorded cutover time while retaining all seen identifiers. This prevents newly discovered historical filings from being emailed during the provider switch. Filings accepted at or after that boundary remain eligible, including those published while deployment is in progress or indexed later. Do not reset the boundary on subsequent polls or deployments. Do not delete delivery history or resend uncertain mail. Verify historical replay produces zero events and a synthetic post-cutover accession produces one event, then zero on repetition, without sending real test mail.

### Recovery after automatic scheduler disablement

Check local backend health, public Funnel health and the scheduler execution history separately. Proxy upstream failure can interrupt tunnel connectivity even while Flask is healthy. The project proxy now routes Tailscale control and DERP domains directly; supplier and Gmail traffic retain the configured proxy. After connectivity recovers, test the existing authenticated POST for HTTP 202, re-enable the same cron-job.org job, and verify subsequent scheduled executions succeed. HTTP 202 proves trigger acceptance, not email delivery. Preserve notification baselines, cursors, seen accessions and outbox history; never reset them to recover connectivity. Validate Gmail token refresh without sending a test alert.

### Active authorization recovery

A configured sender only means the required credential fields exist; it does not prove Google still accepts the refresh token. On a missed-reminder report, check scheduled HTTP acceptance, source cursors, outbox states, and an actual token refresh independently. An HTTP 400 `invalid_grant` response means the credential was rejected; it must not be treated as a provider-network failure.

After a server migration or configuration restore, validate the active server authorization instead of assuming the local production authorization was synchronized. A previously authorized valid credential for the unchanged sender/client can be restored from its private source after validation. Back up the active private configuration, preserve other fields, and restart only the verified backend. If no valid credential remains, complete the existing send-only OAuth authorization again; do not broaden Gmail scopes.

After authorization recovers, an existing unexpired `pending` message without a provider acceptance ID or active lease can be made due for the normal scheduler. Preserve its original event ID, creation time, recipient, body and attempt history. Back up affected retry dates privately. Do not reset observation baselines, replay expired failures, or automatically resend `sending`/`uncertain` messages. Confirm actual provider acceptance in the outbox; inbox reception remains a separate check.
