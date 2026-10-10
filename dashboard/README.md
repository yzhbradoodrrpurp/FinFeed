# FinFeed Application Guide

This document describes current behavior; operational details are in [the technical documentation](docs/architecture.md). Documentation is English; the application interface and alert bodies currently remain primarily Chinese.

## Views and refresh behavior

| View | Content | Normal browser polling |
| --- | --- | --- |
| Home | S&P 500, Nasdaq Composite, Dow Jones, eleven sector ETFs | Every minute |
| Watchlist / Portfolio | Quotes, financial statements, quarterly forecasts, valuation | Every minute |
| Macro | NFP, PCE, DXY, ten-year Treasury yields | Every hour |
| Polymarket | Meeting-specific outcome prices and history | Every minute |
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

## Financial definitions

| Field | Definition |
| --- | --- |
| Price | Latest regular-session quote; not a blended after-hours price |
| Market capitalization | Provider company market cap; ETF AUM is not substituted |
| Actual diluted EPS | Latest reported quarter and adjacent preceding quarter |
| Forward EPS | Analyst estimate for the quarter immediately after the latest reported quarter |
| P/E | Price / (latest actual quarterly EPS × 4) |
| Forward P/E | Price / (next-quarter estimated EPS × 4) |
| Revenue | Reported quarterly revenue |
| Debt | Quarter-end total debt under provider classification |
| Gross / operating margin | Same-quarter gross profit / revenue and operating income / revenue; latest, year-ago, previous and second-previous quarters |
| Capital expenditure | Quarterly cash outflow displayed positive, using the same four quarter anchors; not company-adjusted net capex |
| Free cash flow | Quarterly operating cash flow minus positive capital expenditure |
| Quarterly growth | Current / adjacent previous quarter − 1 |
| Average volume | Mean of the ten complete trading days before the comparison day |
| Relative volume | Complete comparison-day volume / that preceding mean |

Annualizing a single quarter is not LTM earnings or an NTM forecast. Actual EPS may follow GAAP while forecasts may be adjusted; the denominator bases can differ. Nonpositive EPS, differing currencies, unavailable adjacent quarters, and invalid denominators are explicitly unavailable. Financial quarters must be consecutive, with a 65–120 day interval; missing values are not zero. Volume comparisons wait for a complete day rather than comparing partial-day volume with complete days.

Company financial fields are not applied to ETFs. Use full exchange-qualified Yahoo symbols for international listings. `BTC` is an ETF ticker; Bitcoin spot is `BTC-USD`.

## Charts and research boundaries

Home sector symbols are XLC, XLY, XLP, XLE, XLF, XLV, XLI, XLK, XLB, XLRE, and XLU. Charts cover three years of daily closes, with `auto_adjust=False`; they are not dividend total-return series. Split handling follows the provider and the current day can change before close. Sector order is a browser preference, preserved through quote refreshes. Handles support dragging and keyboard moves; charts support pointer, touch, and keyboard inspection.

NFP employment changes are derived from monthly PAYEMS levels. PCE monthly and annual growth are derived from price indexes. The previous observation reflects current revisions; pre-release consensus and original unrevised vintages are not supplied. DXY is Yahoo `DX-Y.NYB`, not a broad trade-weighted dollar index. DGS10 is H.15 daily constant-maturity yield, not an intraday bond quote. The application default observation line is 5.1%; each email subscriber can set their own threshold.

Polymarket prices describe a specific contract and meeting, not an official commitment or QE forecast. Institution comparisons use quarterly 13F holdings, not trade times or a complete fund portfolio. News contains indexes and original links, not stored article bodies.

## Email and interface behavior

The account dialog loads notification settings before showing binding controls, avoiding a false unbound state. Verified accounts hide the verification form. Sending a code starts a sixty-second countdown displaying only the number and `s`; empty required fields disable their actions. Verification, unbinding, invitation generation, login/logout, and notification saving provide transition feedback. Saving produces a disabled saved-state button; editing categories or the threshold re-enables saving.

Users select categories directly; saving with none selected disables alerts. See [email delivery](docs/email-notifications.md) for trigger definitions and operational limitations.
