# FinFeed Application Guide

Reviewed against application source on October 26, 2026 (Asia/Shanghai). This document describes current behavior; operational details are in [the technical documentation](docs/architecture.md). Documentation is English; the application interface and alert bodies currently remain primarily Chinese.

## Views and refresh behavior

| View | Content | Normal browser polling |
| --- | --- | --- |
| Home | S&P 500, Nasdaq Composite, Dow Jones, eleven sector ETFs | Every minute |
| Watchlist / Portfolio | Quotes, financial statements, quarterly forecasts, valuation | Minute quotes; five-minute statements and EPS/forecasts |
| Macro | NFP, PCE, DXY, ten-year Treasury yields | Every hour |
| Polymarket | Meeting-specific outcome prices and history | Hourly while the view is initialized; also on entry/focus when its snapshot is at least one minute old |
| Whale Holdings | Supported institutions' SEC 13F reports | Every hour |
| News | Company earnings calls and SEC filing indexes | Every hour |

Background tabs can be throttled; due requests resume when the browser returns. Email monitoring is independent of open pages. Polling frequency is not upstream publication frequency.

## Accounts and access

Passkeys use the production Vercel origin and RP ID. New accounts require a single-use invitation, valid for seven days. Names are fixed after registration; each account supports up to ten Passkeys. A recently authenticated user can add a backup Passkey within five minutes of login.

Every authenticated user can view other enabled accounts' watchlists and complete portfolios, including quantities and costs. Only the owner can edit records. This is authenticated sharing, not private visibility between registered users. Database administrators can access records; they are not end-to-end encrypted.

The administrator can disable and restore accounts or revoke and restore credentials. Disabling preserves records but hides shared state and invalidates sessions. Self-removal and removal of the final administrator credential are prevented.

## Watchlists and portfolios

Watchlists support persistent manual ordering and temporary column sorting. Holdings are separate from watchlists; removing a watched symbol does not delete a position. The union is limited to 128 distinct symbols per account. Each position is an aggregate quantity, average unit cost, and cost currency, not a transaction ledger.

```text
Cost = quantity × average unit cost
Market value = quantity × latest regular-session price
Unrealized P/L = market value − cost
Return = unrealized P/L ÷ cost
```

Zero-cost returns are unavailable. Missing quotes or differing quote/cost currencies leave valuation unavailable. Totals are grouped by currency without FX conversion; allocation uses valued holdings in the same currency. Closed trades, dividends, cash balances, and realized gains are not calculated.

State saves use authenticated `/api/state`, with revision and transaction controls and the latest fifty prior states retained. Import/export is available in the account dialog. Browser localStorage is not the source of account records.

## Account startup and cached views

Watchlist and Portfolio load account records separately from public market data. Existing browser snapshots appear first; a separate database-only batch supplies missing price summaries, followed by per-symbol refreshes. A summary explicitly waits for complete calculation details. Provider failures retain usable dated snapshots; a recent retrieval time is not a guarantee that the provider has published the latest quarter. See [cache semantics](docs/data-and-caching.md).

## Financial definitions

| Field | Definition |
| --- | --- |
| Price | Latest regular-session quote; not a blended after-hours price |
| Market capitalization | Provider company market cap; ETF AUM is not substituted |
| Actual diluted EPS | Longbridge latest reported quarter and adjacent preceding quarter |
| Forward EPS | Longbridge GAAP diluted analyst estimate for the immediately following fiscal quarter |
| P/E | Longbridge TTM P/E: price relative to the last twelve months of earnings |
| Forward P/E | Price / (latest two reported actual quarterly GAAP diluted EPS + next two quarterly GAAP diluted EPS forecasts) |
| Revenue | Reported quarterly revenue |
| Net Debt | Quarter-end Longbridge NetDebt under provider classification; negative values indicate provider-defined net cash |
| Gross / operating margin | Same-quarter gross profit / revenue and operating income / revenue; latest, year-ago, previous and second-previous quarters |
| Capital expenditure | Quarterly cash outflow displayed positive, using the same four quarter anchors; not company-adjusted net capex |
| Free cash flow | Quarterly operating cash flow minus positive capital expenditure |
| Quarterly growth | (Current − comparison) / abs(comparison); QoQ uses the adjacent quarter, YoY uses the matching year-ago quarter; zero bases have no percentage |
| Average volume | Mean of the ten complete trading days before the comparison day |
| Relative volume | Complete comparison-day volume / that preceding mean |

Market, EPS and quarterly financial categories come from Longbridge. Net Debt uses the provider NetDebt field; negative values represent vendor-defined net cash. FCF is calculated from same-quarter operating cash flow less absolute CapEx, not the provider NetFreeCashFlow aggregate. Longbridge actual and forecast EPS use GAAP diluted consensus, matched to explicit fiscal-quarter labels. P/E uses the provider TTM index. Forward P/E uses two consecutive actual quarters plus the next two consecutive forecast quarters, not standard NTM. All four observations are required; negative totals are displayed as a dash with an earnings-loss label; signed calculations and source inputs remain in backend snapshots. A zero total, differing currencies, unavailable quarters, and invalid denominators are explicitly unavailable. Financial quarters must be consecutive, with a 65–120 day interval; missing values are not zero. Volume comparisons wait for a complete day rather than comparing partial-day volume with complete days.

Company financial fields are not applied to ETFs. The Longbridge market adapter covers US stocks and ETFs; existing international/crypto routes remain on Yahoo with explicit provider labels. `BTC` is an ETF ticker; Bitcoin spot is `BTC-USD`.

## Charts and research boundaries

Home sector symbols are XLC, XLY, XLP, XLE, XLF, XLV, XLI, XLK, XLB, XLRE, and XLU. Charts cover three years of daily closes, with `auto_adjust=False`; they are not dividend total-return series. Split handling follows the provider and the current day can change before close. Sector order is an authenticated account preference stored in PostgreSQL, preserved through quote refreshes and loaded on other devices. Handles support dragging and keyboard moves; charts support pointer, touch, and keyboard inspection.

NFP employment changes are derived from monthly PAYEMS levels. PCE monthly and annual growth are derived from price indexes. The previous observation reflects current revisions; pre-release consensus and original unrevised vintages are not supplied. DXY is Yahoo `DX-Y.NYB`, not a broad trade-weighted dollar index. DGS10 is H.15 daily constant-maturity yield, not an intraday bond quote. The application default observation line is 5.1%; each email subscriber can set their own threshold.

Polymarket has a one-minute server quote-cache TTL; the visible Macro view checks every minute and selects the next verified FOMC meeting automatically. History is supplemented hourly, and failed updates preserve successful outcome curves with their original timestamps. Polymarket prices describe a specific contract and meeting, not an official commitment or QE forecast. Institution comparisons use quarterly 13F holdings, not trade times or a complete fund portfolio. The current registry contains nineteen institutions in Long-term Value, Technology and Growth, Quantitative Funds, and Sovereign Wealth categories; Trian appears under Long-term Value, Bridgewater under Quantitative Funds and Mubadala under Sovereign Wealth. News contains indexes and original links, not stored article bodies.

## Email and interface behavior

The account dialog loads notification settings before showing binding controls, avoiding a false unbound state. Verified accounts hide the verification form. Sending a code starts a sixty-second countdown displaying only the number and `s`; empty required fields disable their actions. Verification, unbinding, invitation generation, login/logout, and notification saving provide transition feedback. Saving produces a disabled saved-state button; editing categories or the threshold re-enables saving.

Users select categories directly; saving with none selected disables alerts. See [email delivery](docs/email-notifications.md) for trigger definitions and operational limitations.
