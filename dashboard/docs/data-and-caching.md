# Data Providers, Request Scheduling, and Caching

## Provider map

| Feature | Data chain | Current routing |
| --- | --- | --- |
| Watchlist / Portfolio market, EPS and valuation | Longbridge OpenAPI; TTM P/E index and two-actual/two-forecast forward calculation | Longbridge SDK connection |
| Quarterly financial categories | Longbridge quarterly financial reports and detailed income/cash-flow statements | Longbridge OpenAPI |
| Home indices and sector charts | Yahoo Finance through yfinance and Yahoo request adapters | Project proxy |
| NFP levels, unemployment, hourly earnings | FRED series PAYEMS, UNRATE, CES0500000003; original publisher BLS | Direct |
| PCE price indexes | FRED PCEPI / PCEPILFE; original publisher BEA | Direct |
| Ten-year yield | FRED DGS10; original publisher Federal Reserve H.15 | Direct |
| NFP release calendar | BLS schedule; fallback to published FRED release 50 dates | BLS project proxy, FRED direct |
| PCE calendar | BEA calendar | Provider HTTP connectivity |
| DXY daily history | Yahoo DX-Y.NYB | Project proxy |
| Institutional holdings | SEC submissions and filing XML | Direct, optional explicit override |
| Earnings calls | Yahoo earnings-call index | Project proxy |
| Company SEC filings | Official SEC ticker map and EDGAR submissions API; primary-document links | Direct, optional SEC override |
| FOMC outcome history | Polymarket provider | Project proxy |
| Market trading calendar | pandas_market_calendars | Local calculation using library calendar |

A network route working once does not guarantee continued provider access. SEC requests need a compliant application User-Agent/contact and fair-access behavior. A proxy does not remove source limits, licensing obligations, or response-schema changes.

## Parsing and calculation rules

Securities use regular-session prices, currency/financial-period checks, consecutive quarters, and explicit missing reasons. Longbridge provides market capitalization, quotes, TTM P/E, historical bars and quarterly actual/forecast EPS. Forward EPS uses the next fiscal-quarter label after the latest reported Longbridge quarter. Forward P/E sums the latest two consecutive released actual quarterly GAAP diluted EPS and the next two consecutive quarterly forecasts. This is a blended four-quarter denominator, not standard NTM; annual forecast labels or single-quarter multiplication are not substitutes. Missing estimates or a zero aggregate denominator remain unavailable. Negative P/E is displayed as a dash labelled “盈利为负”; negative blended Forward P/E is displayed as a dash labelled “预期盈利为负”. Signed calculations and source inputs remain in backend snapshots. Quarterly Revenue, Gross Margin, Operating Margin, CapEx, FCF and Net Debt use Longbridge. Exact-quarter detailed income/CF fields take precedence over generic financial indicators. Net Debt is the provider NetDebt aggregate, including its sign; it is not Total Debt. FCF remains same-quarter operating cash flow minus absolute CapEx; NetFreeCashFlow is not substituted. The newest available revenue or released-EPS quarter anchors Q0. A missing new-quarter component stays missing; older quarters are never used in its place. Historical same-provider observations retain original provenance when omitted by a later response. Non-US/crypto market routes remain available, but unsupported quarterly fundamentals are explicitly missing rather than reverting to Yahoo.

The 52-week range is calculated over the latest 365 calendar days from Longbridge forward-adjusted regular-session daily bars, including corporate-action adjustment. It can differ from Yahoo's range definition and adjustment. Previous-ten-session average volume and relative volume retain the existing complete-day definition rather than using Longbridge's built-in volume ratio. NYSE holidays and early closes determine completion for US securities.

Successful raw provider blocks use versioned `longbridge:v1:<block>:<symbol>` cache keys in PostgreSQL. Static identities have a one-day TTL; quotes, indexes and bars have a 60-second TTL; EPS anchor statements and consensus have a five-minute TTL. Forced market refresh still observes a ten-second minimum per block; forced fundamental refresh observes a sixty-second minimum. Failed blocks back off for sixty seconds across users. Failed blocks retain dated successful raw snapshots and mark the affected display fields stale. Final security snapshots and browser validation use schema 10. Schema 8/9 market fallbacks can survive cutover, but old Yahoo quarterly series and TotalDebt values are cleared, so they cannot be relabelled Net Debt or Longbridge financial data. Existing private account records, preferences and holdings are unaffected; no database schema migration or cache purge is needed.

Longbridge quote and statement work starts concurrently in bounded pools. A quote preview and dated same-provider financial cache display before quarterly work finishes. Financial report, consensus, statement_IS and statement_CF blocks have five-minute TTLs and a sixty-second minimum manual-refresh interval. Each successful raw block is durably cached independently in PostgreSQL through the existing asynchronous writer. Failed blocks retain their successful timestamps and stale labels. Missing current-quarter fields have explicit reasons; the main report-period label indicates the newest available source quarter, not a verified official publication date. Legacy yahoo-financial keys remain unused by the active quarterly route.


Production uses one application worker and one shared Longbridge quote connection. The SDK controls quote calls to at most ten per second with at most five concurrent requests. FinFeed serializes fundamental calls with a 1.1-second minimum interval. The quarterly pool is bounded at four; all its fundamental calls share the same Longbridge limiter and block locks as EPS requests. Same-symbol refresh jobs and provider-block locks merge concurrent callers. Rate control bounds outbound traffic, not supplier availability or a guaranteed one-minute completion time for every distinct symbol. Multiple accounts sharing a ticker reuse its data; many distinct symbols can queue. Do not start extra production workers or probe quote connections with the same credentials without revisiting account-wide quotas.

Home sector histories cover three years of daily closes without dividend total-return adjustment. Macro series preserve original units and observation periods. Monthly NFP changes and PCE growth are computed from adjacent observations; missing months are not silently bridged. The daily Treasury series does not provide intraday threshold events. Current revisions are visible, but original vintages and market consensus are not synthesized.

BLS calendar fallback uses already published dates, not an assumed first Friday. When fallback dates lack times, the standard 08:30 America/New_York time is converted with timezone rules and the time basis is labeled. No published future date means an explicit unavailable schedule.

SEC 13F retrieval locates filings and compares adjacent reported quarters. Positions are combined using CUSIP, security class, option direction, and quantity type; value and comparison handling preserve filing semantics. A report is a quarter-end snapshot and may have amendments. It is not a full fund portfolio or transaction record.

News stores normalized titles, dates, document URLs, and identifiers, not article bodies. Earnings calls are limited to the latest two published fiscal quarters. Filings use a window anchored by the latest two original quarterly/annual filings. Unsafe URLs, future/unpublished entries, duplicates, and unrecognized periods are filtered.

Polymarket history uses six-hour historical sampling with hourly supplementation and a live endpoint update. Quotes are contract-specific market pricing subject to liquidity and spread; they are not official policy or a QE forecast.

## Browser request cycle

The browser loads account state and market data independently, limits watchlist fetch concurrency to four, and schedules views at their normal minute/hour intervals. Hidden tabs may be delayed by the browser. Re-entering the page checks overdue work. Rendering is combined on animation frames and updates existing rows/cells rather than rebuilding every table.

Home, sector, macro, and security refresh routes use shared jobs. Supported requests with `stream=1` receive NDJSON events containing cached, partial/progress, and completed states; ordinary JSON remains supported. A subscriber waits at most 25 seconds per response. A pending job can be rejoined after one second without forcing a duplicate refresh; browser total waiting is bounded at 125 seconds.

A third-party provider thread cannot safely be killed just because its HTTP subscriber times out. The job can finish and publish a cache after that response ends; subsequent subscribers reuse the same in-flight job. The Gunicorn timeout protects worker health, not every individual provider call.

## Cache layers

| Layer | Location | What it stores / lifetime |
| --- | --- | --- |
| Browser market snapshots | localStorage `finfeed-market:v1:*` | Public market data; read age depends on caller, helper default seven days |
| Browser preferences | localStorage | Sidebar settings, not holdings or credentials |
| Account display preferences | PostgreSQL account state JSON | Watchlist metric-group order and Home sector-card order, isolated per account |
| Worker refresh entries | Process memory | In-flight work, last successful value, TTL and retry state |
| Store hot cache | Process memory | Up to 1,024 database cache entries, sixty-second hot lifetime |
| Durable application cache | PostgreSQL `cache` | Shared successful snapshots, provider state and budgets; reusable after restart |
| Provider working files | `app/dashboard/.cache` | Provider/local working cache, not the authoritative account database |
| Package download cache | `.pip-cache` | Installation artifacts, unrelated to financial freshness |

Public snapshots use a bounded asynchronous database writer: updates coalesce by key, wait a 100 ms batching window, and write up to 32 entries per transaction. The pending map is capped at 1,024 keys; overflow is logged and that evicted pending value remains memory-only. Failed writes retry after fifteen seconds. Account writes remain synchronous transactions. Recent snapshots can therefore be visible in memory before durable persistence; a crash can lose the unflushed market-cache update, not a committed account record.

The API's HTTP `no-store` policy is separate from the application-controlled public market cache. Private account data and credentials are excluded from localStorage. Clearing browser market caches does not delete holdings; clearing database or private paths can.

Browser cache writers reject stale, partial, refreshing, and invalid responses and avoid overwriting a newer provider timestamp with an older one. Web Locks coordinate same-market fetches across tabs; an in-page promise map further merges matching calls. Unsupported browsers still benefit from backend request coalescing.

Worker cache TTLs follow service frequency: minute quotes/Home/sectors/Polymarket and hour macro/holdings/news. Successful durable snapshots can display immediately while refresh proceeds. An old snapshot retains its original data/retrieval dates and stale indication. Schema versions and validation invalidate incompatible payloads rather than recasting old metrics as new ones.

## Queue and failure policy

Refresh lanes isolate slow company/SEC calls from minute quotes. Limits are security 4; Yahoo news, SEC news, whales, macro, home, sector 2 each, with 256 queued/running jobs. Same-key requests share one job in the process. Failed refreshes back off for 60, 120, 240, 480, then 900 seconds; success resets the retry state. Forced requests still share a just-completed result within five seconds.

Failures preserve usable previous data. An unavailable field stays unavailable rather than becoming zero; a successful quote can coexist with missing financial data. HTTP failures, invalid payloads, empty responses, database faults, and stale fallback events produce sanitized `request_failure` records. Client failures are best-effort reported with request IDs; if the backend is unreachable, reporting can also fail.

## Cache maintenance

- Diagnose source timestamps, cache flags, and upstream errors before invalidating anything.
- Do not purge all shared snapshots to fix one failing source; it increases request load and removes useful fallback data.
- Change schema/validation with compatible rollout plans when calculation definitions change.
- Preserve `app/dashboard/.cache` during code synchronization unless a specific disposable provider cache is deliberately reset.
- Monitor upstream budgets and queue pressure; adding workers may amplify limits rather than improve latency.
- Use [the application guide](../README.md) for the exact portfolio and financial metric definitions.

## Account display order

Authenticated `GET /api/preferences` loads the account's `watchlistGroupOrder` and `homeSectorOrder`. `PUT /api/preferences` validates complete permutations and merges only the supplied preference fields into account state inside the existing state transaction. No database schema change is required. Older state clients preserve these fields when saving watchlists or positions.

Watchlist group handles activate after a 300 ms hold; pointer dragging uses an anchored preview, animated column swaps, and horizontal edge scrolling. Left/right arrow keys also reorder groups. Home retains its card drag and keyboard controls. Reorders update the view immediately and queue server writes; failures restore the prior order and display an error. Controls remain disabled until account preferences load. When viewing another account's Watchlist, the group order comes from that account's state and drag handles are hidden; only the owner can reorder their groups. Both reorder and save callbacks check ownership and loading state. Preference writes resolve the account from the authenticated session, and requests targeting another account are rejected. Two-account regression tests verify that edits preserve the other account's state, revision, and history. Other devices load the saved order on login/reload and refresh it when the window regains focus; this is not a live broadcast channel.

## Quarterly profitability and capital expenditure

Gross Margin, Operating Margin and Capital Expenditure each display Q0 single-quarter value, Q0 year-over-year change, Q0 quarter-over-quarter change and Q−1 quarter-over-quarter change, anchored to the latest reported income-statement quarter. Margin levels are percentages. Relative changes for margins, Revenue, Debt, FCF and CapEx use (current − comparison) / abs(comparison), displayed as percentages. A margin increase from 40% to 50% is +25%, not a percentage-point difference. Negative bases retain a numeric rate with a label for narrowing, widening, unchanged, reaching zero or turning positive; positive-to-negative changes are labelled as turning negative. Zero bases have no numeric percentage and show a zero-to-positive, zero-to-negative or unchanged label. Missing observations remain missing. All numeric changes, including Debt and CapEx, use green for positive values and red for negative values; colors indicate direction, not investment merit. Spending uses the absolute cash outflow reported by the provider. Comparisons preserve the consecutive-quarter and matching-year rules and do not indicate investment performance. Backend snapshots are recalculated from cached quarterly series; browser snapshots with stored comparison inputs are upgraded before display, sorting and details without discarding successful data or forcing a provider refresh. Calculation version 3 distinguishes the new derived values.

### Official company filings

SEC filings use `company_tickers.json` to resolve CIKs and `data.sec.gov/submissions/CIK##########.json` for official filing metadata. Ticker aliases normalize dots to hyphens. The ticker map refreshes daily; a failed refresh retains known CIK mappings and applies a sixty-second retry cooldown, while unresolved symbols fail rather than being incorrectly cached as unsupported; an unmapped symbol is reported as unsupported, never guessed from another issuer. Submissions preserve accession, form, filing date, acceptance timestamp, report date, and primary document. Additional submissions pages are read when needed to find two original periodic-report anchors (10-Q, 10-K, 20-F, or 40-F). The page retains its report window; reminder detection reads the full retrieved index so display-window changes cannot hide newly indexed disclosures. Calls continue to use Yahoo. Requests share the existing SEC limiter and contact User-Agent with institutional holdings. API/schema failures retain prior successful caches and do not advance notification cursors. Official SEC caches have a separate versioned key from historical Yahoo caches. SEC download attempts have an eight-second per-attempt budget and at most three attempts within the original thirty-second operation deadline; transient network and HTTP 408/429/5xx failures can retry, respecting integer Retry-After when it fits the budget. Permanent HTTP and TLS certificate failures are not retried or bypassed. Each attempt uses the shared SEC limiter.

News browser responses (JSON, NDJSON and optional cache bootstrap) omit `notification_items`. This projection leaves the complete persisted index intact for reminder detection; displayed filings still cover the same two-report window. Yahoo calls and SEC filings have separate two-worker server lanes and separate two-worker browser queues, so slow calls cannot consume all SEC slots. Browser source failures retain displayed snapshots and retry after 1, 2, 4, 8 and then 15 minutes until recovery; successful recovery resets the delay. Seeding browser caches does not clear a pending failure state. The existing hourly refresh and server backoff remain in effect.

### Mubadala institutional holdings

Mubadala Investment Co PJSC (CIK 1704268, application ID `mubadala`) is included in the Whale Holdings manager registry and sovereign-investment category. It uses the same SEC filings, amendment handling, prior-quarter comparison, cache and stale-data rules as the other managers. The 13F scope is not its complete global portfolio. Existing institutional-alert subscribers use the normal source-observation baseline and deduplication rules for this manager.

### Account startup and market payloads

Watchlist and Portfolio first read `/api/state?quotes=none`. This authenticated request returns private records and permissions without reading or serializing market-cache entries. The default `/api/state` response remains compatible and includes current-schema cached snapshots, with browser-only projection applied.

The browser immediately renders records and existing local market snapshots. For tickers without local prices, authenticated `/api/quotes?symbols=...` returns database-only summaries, with no provider requests or private account fields. This separate request has a five-second browser deadline; failure falls through to normal per-ticker reads. Summaries retain values, units, periods, missing reasons and stale indicators but defer calculation inputs and source/basis text to the complete snapshot. They are marked partial/bootstrap, labelled in the UI, and never persisted as completed browser snapshots. Account generation and cancellation checks reject late responses after switching accounts.

Browser security responses omit internal `series` and `longbridge_market` blocks; complete metric explanations and inputs remain in normal security responses. Durable server snapshots retain those internal blocks for recalculation and source reuse. Other views' staggered background startup waits for the initial ticker queue, for at most fifteen seconds, giving the active account view priority without removing background updates.
