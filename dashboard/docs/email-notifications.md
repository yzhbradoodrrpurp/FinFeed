# Gmail Authorization and Notification Delivery

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
| Institutional holdings | Newly observed reports/amendments for supported institutions; report period, filing/publication date and original SEC link |
| Watchlist News | New earnings calls or SEC index entries for the recipient's own watchlist; titles, dates and original document links |

The Treasury default is 5.1%, adjustable per account. First reads and changed thresholds establish baselines rather than sending an existing above-line state as a new crossing. This is daily-statistic monitoring, not intraday touching alerts. Institution and company first reads also establish baselines, avoiding historical floods. News follows the page's two-quarter window. SEC reminders deduplicate by EDGAR accession, so a switch between the primary document and an exhibit cannot create another alert. Persistent observation timestamps and subscription start times filter historical backfill, unknown dates, and future dates; same-day SEC filings remain eligible because the index provides day-level dates. First reads establish a baseline, and legacy cursors gain a timestamp without replaying older filings. Genuine disclosures published during a monitoring outage remain eligible after recovery. Previously seen identifiers are retained.

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

The current deployment has verified Gmail token refresh, prior real verification-code reception and binding, and automatic every-minute trigger acceptance. Every category has not yet been observed delivering a new production event; mock transport tests and HTTP 202 must not be reported as proof of those deliveries.

Authenticated `GET /api/notifications` provides the account's queue counts. A `sent` state means channel acceptance, not guaranteed delivery, reading, or absence from spam. Check authorization, proxy connectivity, source/calendar validity, event baseline, subscription state, and outbox status in that order. Respect Gmail account sending limits and do not repeatedly trigger real mail as a health probe.

References: [Gmail sending](https://developers.google.com/workspace/gmail/api/guides/sending), [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [token expiration](https://developers.google.com/identity/protocols/oauth2#expiration), and [sending limits](https://support.google.com/mail/answer/22839).
