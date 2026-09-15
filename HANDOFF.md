# FutureView Replay Handoff

Last updated: 2026-09-15
Primary branch: `master`
Current application head before this handoff update: `2b7a423c87785aca19eeb3a460991abbda13eff2`

## 1. Current goal

FutureView is a historical futures market replay/trading simulator. The current production focus is trustworthy causal replay plus manual simulated trading. `MES` and `ES` are supported by the trading engine; MES remains the primary replay product used during development.

The browser must never receive future bars. The backend/Durable Object is authoritative for replay and trading state.

## 2. Production architecture

Public frontend:

```text
https://futureview.pages.dev/
```

Backend Worker:

```text
https://futureview.rueijrwu.workers.dev/
```

Architecture:

```text
Cloudflare Pages (`site/`)
        |
        | HTTPS + WebSocket
        v
Cloudflare Worker `futureview`
        |
        +-- Durable Object ReplaySession
        +-- R2 replay/raw data
        +-- D1 auth/session/trade persistence
```

The workers.dev hostname is backend infrastructure, not the site name. Do not rename the public site to a rueijrwu hostname.

## 3. Important files

```text
site/index.html                 current replay/trading page
site/style.css                  page/chart/trading layout
site/app.js                     replay + trading client behavior
site/chart-tools.js             chart indicators/drawing/view tools
site/chart-tools-fixes.js       drawing interaction patches
site/login.html                 login/register page
site/login.js                   auth client
cloudflare/worker/replay-session.js
cloudflare/worker/index.js
cloudflare/migrations/
.github/workflows/replay-pages-deploy.yml
.github/workflows/replay-cloudflare-deploy.yml
.github/workflows/replay-data-publish.yml
HANDOFF.md
```

## 4. Replay invariants

Keep these unless explicitly changed:

1. Browser never receives bars after the replay cursor.
2. Durable Object owns authoritative replay state.
3. Actual futures contract identity/prices are execution truth; no synthetic/back-adjusted execution prices.
4. Main replay clock is currently 5-minute bars.
5. User-facing time is `America/New_York`; storage/protocol timestamps are UTC.
6. Replay input is product + date/time; user does not preselect the actual contract.
7. Contract selection remains causal from prior completed CME-session information.
8. High speed may batch network/rendering work but must not skip logical bars.
9. Play/Pause/Next command semantics must remain deterministic.
10. A trade requested at the current cursor fills only at the next released bar open.

Current speed choices in the UI are exactly:

```text
1  5  10  50  100  Max
```

Default replay time is `08:30` ET. The random-date button is labeled `Random`.

## 5. Chart viewport policy — important

This was repeatedly regressed and is now an explicit product rule.

Only these operations may automatically fit/scale the chart:

```text
Start Replay
Restart
Fit
```

Normal actions must NOT move or auto-scale the user's viewport:

```text
Play
Pause
Next
speed changes
Buy
Sell
Trades toggle
Console toggle
Clear trading
incoming replay bars
trade marker updates
horizontal panning
```

`site/app.js` uses `timeScale.shiftVisibleRangeOnNewBar: false` and preserves the logical viewport around normal data/marker/layout updates.

`site/chart-tools.js::fit()` performs the requested fit/autoscale and then freezes the price scale again. This is intentional: leaving `autoScale: true` caused horizontal panning to continuously rescale the Y axis.

Explicit chart controls such as Fit/Latest/zoom remain user-driven operations.

## 6. Chart/tooling state

The page uses TradingView Lightweight Charts for visualization only. It is not the simulation engine.

Current chart functionality includes:

```text
candles
volume
OHLCV legend
SMA 5/10/20/60
VWAP
magnet crosshair
trend line
ray
horizontal/vertical line
rectangle
Fibonacci retracement
text annotation
undo / clear drawings
zoom in/out
Fit
Latest
linear/log scale
```

Drawing support uses `lightweight-charts-drawing` plus local interaction glue/fixes.

The chart toolbar and OHLC legend remain above the plot. The right trade ledger must occupy only the plot row and must never cover Fit/Zoom/Latest or other chart tools.

## 7. Bottom replay/trading controls

The bottom control bar is one horizontal non-overlapping row.

Left/replay group:

```text
Restart · Next · Play · Pause · Speed · 1 · 5 · 10 · 50 · 100 · Max
```

Right/trading group is pinned to the far right using the established `margin-left: auto` layout and left divider:

```text
Trade · Qty · Buy · Sell · Trades
```

`Trades` belongs immediately to the right of `Sell` in the trading group. Do not move it back into replay controls.

## 8. Trading engine

Manual trading V1 is implemented.

Current execution model:

```text
market orders only
Buy/Sell quantity 1..100
request recorded at current replay cursor
fill occurs at NEXT released 5m bar OPEN
multiple pending orders are supported
scaling in/out is supported
position reversal is supported
```

Contract point values currently used:

```text
MES = $5 / point / contract
ES  = $50 / point / contract
```

Trading accounting tracks:

```text
position quantity
average price
realized P&L
unrealized P&L
total P&L
commission (currently zero)
slippage (currently zero)
pending orders
fills
```

The Durable Object is authoritative. Do not move authoritative P&L/accounting into browser-only state.

D1 persistence includes simulated account/fill records. Relevant schema additions include:

```text
simulation_accounts
trade_fills
```

## 9. Restart vs Clear

These are deliberately different.

`Restart`:

```text
restart replay cursor/time
reset replay state
clear trading state
fit chart
```

`Clear`:

```text
clear trading records only
clear pending orders
clear fills
reset position / average price / P&L
clear persisted current-session trading records
DO NOT change replay cursor/time/state
DO NOT fit/move chart
```

Backend command:

```text
clear_trading
```

Do not implement Clear by calling Restart.

## 10. Trade ledger layout

The right trade ledger is collapsible with the `Trades` button.

Its internal structure is:

```text
fixed-height general trading summary at top
flexible trade table in middle
fixed-height footer toolbar at bottom
```

General summary is always visible when the ledger is open and contains:

```text
Position
Avg
Unrealized
Realized
Total P&L
```

The ledger footer toolbar is fixed at 44px and contains:

```text
Clear
Console
```

The summary is fixed-height (currently 112px). It must not expand with the ledger.

## 11. Console behavior

`Console` does NOT control Buy/Sell/Qty. Buy/Sell/Qty remain always visible in the far-right main trading toolbar.

Console toggles a separate trading activity/detail panel at the very bottom of the page, below the replay/trading control bar. It is hidden by default.

The Console is now an activity log, not merely a selected-row detail placeholder.

It records:

```text
ORDER — when Buy/Sell is accepted/queued
FILL  — when the order actually executes
```

Example semantics:

```text
ORDER SELL 1 MES queued for next bar open
FILL  SELL 1 MES @ <price> realized <PnL> -> resulting position
```

The temporary page status message:

```text
Order queued: SELL 1 · fills at next bar open
```

is allowed while the order is pending, but MUST clear once a new fill is observed. The permanent ORDER/FILL history remains in Console.

`Clear` also clears Console history.

## 12. Trade markers and ledger interaction

Completed fills are shown as Buy/Sell arrow markers on the candle series using Lightweight Charts series markers.

Normal fill/marker updates must preserve the current viewport.

Clicking a trade ledger row is an intentional navigation action and currently jumps the chart to a range around that fill. This is separate from normal Buy/Sell behavior; Buy/Sell themselves must never refit or jump the chart.

## 13. Authentication

A login/register system is implemented for the Pages site.

Current product intent:

```text
registration is currently open
initially only a very small number of accounts are expected
registration can be closed later
login uses username/account + password
```

Auth is backed by the Worker/D1. The frontend stores the auth token and validates `/api/auth/me` before loading the replay UI.

Do not reintroduce the earlier broken account state/password behavior without checking current auth code/migrations.

## 14. Data/storage model

Raw source of truth remains Cloudflare R2 bucket:

```text
futureview-data
```

Current raw data is Databento GLBX.MDP3 `ohlcv-1m`, with 5m replay bars prepared independently per actual contract. Never aggregate across futures contracts.

Generic raw layout:

```text
raw/databento/<DATASET>/<PRODUCT>/<SCHEMA>/
```

Current MES prefix:

```text
raw/databento/GLBX.MDP3/MES/ohlcv-1m/
```

Do not re-add raw DBN files to Git/LFS.

Production replay storage still has legacy compatibility naming in places (`mes-replay/v1`). Migrate deliberately later rather than casually renaming it.

## 15. Deployment workflows

Important workflows:

```text
replay-python.yml
replay-cloudflare-check.yml
replay-cloudflare-deploy.yml
replay-data-publish.yml
replay-pages-deploy.yml
```

Worker deployment and replay-data publishing are intentionally separate. Do not make normal Worker/UI edits rebuild and upload the entire replay dataset.

Pages production branch is `master`; `site/` is deployed to the `futureview` Pages project.

## 16. CRITICAL editing warning: `site/app.js`

Two recent GitHub connector edits accidentally truncated `site/app.js`, making the whole site unresponsive. This happened during seemingly small full-file replacements.

Recovery commits included:

```text
c8a7defb  restore full app and trading console events
2b7a423c  restore complete app after another truncated update
```

Before ANY future write to `site/app.js`:

1. Fetch the complete current file/blob.
2. Verify the source contains the end-of-file initialization and closing `})();`.
3. Apply the smallest possible change locally/in-memory.
4. Write the COMPLETE file, never a partial fetch range.
5. Immediately fetch the resulting file tail and verify it still ends with the initialization block and `})();`.
6. Check the Pages workflow/deployment.
7. Prefer a patch/PR/local git workflow over repeated connector full-file replacement if available.

A successful GitHub commit or Pages workflow does NOT prove JavaScript syntax/runtime correctness; Pages will happily deploy a truncated JS file.

This warning is high priority for the next agent.

## 17. Recent commits of interest

Trading/UI work during the current session includes:

```text
641fda84  trading persistence schema
1c8f50cb  causal trading engine
57691fad  trading controls/sidebar structure
6637a169  trading sidebar styling
61c9e6e3  frontend trading behavior
7b9fa0f3  dedicated clear_trading backend command
2276db47  restore Buy/Sell controls; Console details-only phase
c0dad287  trading control styling/layout
16fd05a6  fixed-height ledger footer
bef6adec  ledger grid sizing
c4240e34  move Console below controls
67b344cc  fixed summary/footer sizing
28c53aae  viewport policy baseline
c8a7defb  restore full app + ORDER/FILL console logging
97906b37  freeze price autoscale after Fit
5749e860  intended queued-status clearing change (subsequently found to truncate app.js)
2b7a423c  restore complete app after truncated update
```

There were several intermediate viewport/control experiments and reverts. Do not infer desired behavior from one intermediate commit; use the explicit viewport policy in this handoff.

## 18. Known verification needed immediately after handoff

Because `site/app.js` was just recovered from truncation, the next agent should first smoke-test production before adding features:

```text
1. Open the Pages site and confirm it responds.
2. Login/register as appropriate.
3. Start a replay at 08:30 ET.
4. Verify Restart auto-fits.
5. Pan/zoom manually.
6. Verify Play/Pause/Next do not move or auto-scale the viewport.
7. Verify horizontal pan does not auto-rescale Y.
8. Buy 1; confirm queued status and Console ORDER.
9. Release next bar; confirm fill, ledger row/marker, Console FILL, and queued status disappears.
10. Verify Buy/Sell/fill do not move viewport.
11. Open Trades; verify ledger does not cover chart toolbar.
12. Verify summary and footer heights remain fixed.
13. Toggle Console; verify it appears below the main control bar.
14. Clear trading; verify replay time is unchanged and trading/account/Console reset.
15. Restart; verify replay resets and chart fits.
```

## 19. Recommended next work

Do not add more execution complexity until the above smoke test is stable.

After stability:

```text
1. Add automated frontend smoke/regression tests for app.js load and core controls.
2. Add a CI syntax check for site JavaScript so truncated files cannot deploy.
3. Add browser-level tests for the viewport invariants.
4. Improve order lifecycle/status representation instead of using the generic error/status field.
5. Add configurable commission/slippage.
6. Later use retained 1m data for a more realistic fill model.
7. Later add Limit/Stop/Flatten and conservative intrabar ambiguity rules.
8. Persist/report complete session trade/equity history for backtest analysis.
```

The highest-value engineering improvement is currently regression protection, not more features.

## 20. Short handoff summary

```text
MASTER = FutureView historical futures replay + manual trading simulator.

Public site:
https://futureview.pages.dev/

Backend:
https://futureview.rueijrwu.workers.dev/

Replay:
causal 5m actual-contract bars; ET display; UTC storage.

Trading:
market Buy/Sell; fills at next released bar open; authoritative DO accounting; D1 fill persistence.

UI:
replay controls left; Qty/Buy/Sell/Trades far right; collapsible right ledger; Console below main controls.

Viewport rule:
ONLY Start Replay, Restart, and Fit auto-fit/scale.
All normal replay/trading/pan actions preserve the user's view.

Clear:
trading only; never replay cursor.

Console:
ORDER + FILL activity history; hidden by default.

Critical risk:
Do not truncate site/app.js during connector edits. Fetch/write/verify the COMPLETE file.

Immediate next task:
production smoke-test all replay/trading/viewport behavior before adding features.
```
