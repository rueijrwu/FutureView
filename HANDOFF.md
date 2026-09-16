# FutureView Replay Handoff

Last updated: 2026-09-16
Primary branch: `master`
Current head before this handoff update: `e8eb875b105ea731327d5822b1d8954aab2400e0`

## 1. Current goal

FutureView is a historical futures replay/trading simulator with causal replay, manual simulated trading, chart annotation tools, and persistent trading state.

The browser must never receive future bars. The backend/Durable Object remains authoritative for replay and trading state.

Public frontend:

```text
https://futureview.pages.dev/
```

Backend Worker:

```text
https://futureview.rueijrwu.workers.dev/
```

## 2. Important files

```text
site/index.html                 main replay/trading UI
site/style.css                  layout and trading panel styling
site/app.js                     replay + trading client behavior
site/chart-tools.js             chart indicators/drawing/view tools
site/chart-tools-fixes.js       active patch layer for drawing + fit + scale behavior
site/login.html                 auth UI
site/login.js                   auth client
cloudflare/worker/replay-session.js
cloudflare/worker/index.js
cloudflare/migrations/
.github/workflows/replay-pages-deploy.yml
.github/workflows/replay-cloudflare-deploy.yml
.github/workflows/replay-data-publish.yml
HANDOFF.md
```

## 3. Replay invariants

Keep these unless explicitly changed:

1. Browser never receives bars after the replay cursor.
2. Durable Object owns authoritative replay state.
3. Actual futures contract identity/prices are execution truth.
4. Main replay clock is currently 5-minute bars.
5. User-facing time is `America/New_York`; protocol/storage timestamps are UTC.
6. Replay input is product + time; user does not preselect the actual contract.
7. Contract selection remains causal.
8. High replay speed may batch work but must not skip logical bars.
9. Play/Pause/Next must remain deterministic.
10. A market order requested at the current cursor fills only at the next released bar open.

Current speed buttons:

```text
1  5  10  50  100  Max
```

Default replay time is `08:30` ET.

## 4. Viewport / auto-fit policy — critical

This has regressed several times. Treat the following as the explicit product rule.

Automatic fit/scale is allowed when a new replay session starts or when explicitly requested:

```text
Start Replay
Random   (because Random starts a new replay session)
Restart
Fit
```

Normal actions must NOT move or auto-scale the user's chart:

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

`site/app.js` uses `shiftVisibleRangeOnNewBar: false` and preserves the visible logical range around normal data/marker/layout updates.

### Current Fit behavior

The active implementation is in `site/chart-tools-fixes.js`, overriding the base `fit()` implementation.

Fit is one-shot:

```text
fit X with fitContent()
enable price Y autoscale
enable volume Y autoscale
wait for Lightweight Charts to render/calculates ranges
freeze both Y scales again
```

The delayed freeze is intentional. Freezing immediately caused incorrect fitted Y ranges.

Horizontal panning must not continuously recompute either Y scale after Fit.

## 5. Price and volume axes

Price and volume are now intentionally independent.

```text
Price  -> right Y-axis
Volume -> left Y-axis
```

Volume was originally on a custom overlay price scale (`priceScaleId: "volume"`), but Lightweight Charts does not expose custom overlay scales as visible draggable axes.

`site/chart-tools-fixes.js` therefore moves volume to the built-in left scale:

```text
volume.priceScaleId = "left"
leftPriceScale.visible = true
rightPriceScale.visible = true
```

Expected behavior:

```text
manual right-axis scaling affects price only
manual left-axis scaling affects volume only
Fit fits both once, then freezes both
horizontal pan does not autoscale either
```

Volume retains its lower-chart margin (`top: 0.8`, `bottom: 0`).

## 6. Chart tools

Current chart feature set:

```text
candles
volume
OHLCV legend
SMA 5/10/20/60
VWAP
magnet crosshair
trend line
ray
horizontal line
vertical line
rectangle
Fibonacci retracement
text annotation
undo / clear drawings
zoom in/out
Fit
Latest
linear/log scale
```

Drawing rendering/hit testing comes from `lightweight-charts-drawing`, while local code provides interaction glue.

### Drawing state synchronization

Recent issue: a drawing toolbar button could visually appear armed while the internal draw state was stale.

`site/chart-tools-fixes.js` now uses one authoritative patched handler for draw-tool buttons, synchronizing:

```text
activeDrawTool
button .armed class
aria-pressed
cancel / complete state
```

### H-Line / V-Line special path

H-Line and V-Line were still occasionally armed but failed to place because the Lightweight Charts `subscribeClick()` callback was unreliable for these one-anchor tools.

Current fix in commit `e8eb875b`:

```text
H-Line/V-Line placement bypasses chart.subscribeClick()
a capture-phase click listener on the chart container converts the click directly to a chart anchor
the one-anchor drawing is finalized immediately
the tool then cleanly disarms
the event is stopped before the normal chart callback can interfere
```

Multi-point tools continue using the existing chart callback path.

This area should be smoke-tested before further drawing refactors.

## 7. Annotation lifecycle

A new replay session should start with a clean annotation canvas.

Current behavior:

```text
Start Replay -> clear all drawings first
Random       -> clear all drawings first
Restart      -> currently does NOT explicitly clear drawings via this patch
```

The Start/Random clearing is implemented in `site/chart-tools-fixes.js` with a capture-phase click listener, so annotations are cleared before `app.js` starts the new session.

If Restart should also clear annotations in the future, add it deliberately; current request only covered Start Replay and Random.

## 8. Trading engine

Current execution model:

```text
market orders only
Buy/Sell quantity 1..100
request at current replay cursor
fill at NEXT released 5m bar OPEN
multiple pending orders supported
scaling supported
partial exits supported
reversals supported
```

Point values:

```text
MES = $5 / point / contract
ES  = $50 / point / contract
```

Accounting tracks:

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

When flat:

```text
Avg        = —
Unrealized = $0.00
```

That is intentional. Once a fill creates a nonzero position, Avg and Unrealized should update from the authoritative trading snapshot/current mark.

## 9. Bottom controls / ledger

Bottom control bar remains a single horizontal row.

Left/replay group:

```text
Restart · Next · Play · Pause · Speed · 1 · 5 · 10 · 50 · 100 · Max
```

Far-right trading group:

```text
Trade · Qty · Buy · Sell · Trades
```

`Trades` belongs immediately to the right of `Sell`.

The right trade ledger contains:

```text
fixed 112px summary
flexible trade table
fixed 44px footer
```

Summary fields:

```text
Position
Avg
Unrealized
Realized
Total P&L
```

Footer:

```text
Clear
Console
```

The ledger must start below the chart toolbar/OHLC legend and must never cover Fit/Latest/zoom controls.

## 10. Restart vs Clear

These are intentionally different.

Restart:

```text
restart replay state/cursor
clear trading state
fit chart
```

Clear:

```text
clear trading only
clear pending orders/fills
reset position/avg/P&L
clear persisted current-session trading records
clear Console history
DO NOT change replay cursor/time/state
DO NOT fit/move chart
```

Backend command:

```text
clear_trading
```

Do not implement Clear by calling Restart.

## 11. Console and queued-order status

Console is a trading activity log, hidden by default, below the main control bar.

It records:

```text
ORDER when an order is accepted/queued
FILL  when the order executes
```

Temporary page status example:

```text
Order queued: SELL 1 · fills at next bar open
```

This temporary status MUST disappear when the fill event arrives.

Current `site/app.js` `fills` handler does:

```text
setTrading(x.trading)
error()
```

so the queued status is cleared while permanent ORDER/FILL history remains in Console.

Relevant commit:

```text
041b04da  clear queued status when order fills
```

## 12. app.js editing warning — highest priority

The GitHub file-replacement connector repeatedly truncated `site/app.js`, making the site completely unresponsive while still producing successful commits/deployments.

Examples of bad/truncated commits included:

```text
5749e860
72adcd2c
```

The successful recovery used Git blob/tree/ref operations, NOT `update_file`.

Known-good restored `app.js` blob after recovery:

```text
8d34d37d5201abfc91831b59a6563ad4b6f711ab
```

Current later app.js blob after the safe queued-status patch:

```text
cb4a45259ad5efaa83c1359ab3699ca109f7c61a
```

Safe procedure for future `site/app.js` edits:

```text
1. fetch the COMPLETE current blob
2. modify it in memory
3. create_blob
4. create_tree using current master tree as base and replace only site/app.js blob SHA
5. create_commit with current master as parent
6. update_ref master to the new commit
7. fetch the modified region AND the EOF tail
8. verify EOF still contains initialization and final `})();`
```

Do NOT use `GitHub.update_file` for `site/app.js` unless the truncation issue is proven resolved.

A successful Pages workflow does not validate JS syntax/completeness.

## 13. Recent commits of interest

```text
c8a7defb  restore full app + ORDER/FILL Console
f076ed0b  restore complete app.js via Git tree/blob path
041b04da  clear queued-order status on fill, safely via blob/tree
c7872d02  correct one-shot Fit timing
7b187078  add independent visible volume Y-axis on left
8fa0bea3  clear annotations on Start Replay and Random
39600bfe  synchronize draw-tool toolbar state
 e8eb875b  direct H-Line/V-Line placement path
```

Earlier viewport baseline:

```text
28c53aae  explicit action-button viewport policy
```

## 14. Immediate smoke-test checklist

Before adding new features, verify production in this order:

```text
1. Open https://futureview.pages.dev/ and confirm the page responds.
2. Login and start a replay.
3. Verify Start Replay auto-fits.
4. Verify Random starts a new session, auto-fits, and clears annotations.
5. Verify Start Replay clears annotations.
6. Verify Play/Pause/Next do not move/scale viewport.
7. Verify horizontal pan does not auto-rescale price or volume.
8. Verify right price axis scales price only.
9. Verify left volume axis scales volume only.
10. Click Fit and verify price + volume fit correctly once, then remain frozen while panning.
11. Draw H-Line repeatedly; every arm should place exactly one line on the next chart click.
12. Draw V-Line repeatedly with the same expectation.
13. Verify Trend/Ray/Rect/Fib/Text still work after H/V direct-click patch.
14. Buy/Sell and verify queued status appears.
15. Release next bar and verify queued status disappears and Console gains FILL.
16. Verify Avg/Unrealized update when position is nonzero.
17. Verify trading updates do not move viewport.
18. Verify Clear resets trading only and leaves replay time/view intact.
```

## 15. Recommended next work

Highest-value work is still regression protection rather than more execution features.

Recommended:

```text
1. add JS syntax validation to CI for every file in site/
2. add browser-level smoke tests for page load
3. add browser tests for viewport invariants
4. add drawing-tool tests, especially H-Line/V-Line repeated arm/place cycles
5. add tests for independent left-volume/right-price scaling
6. add test that Start/Random clear drawings
7. add test that queued status clears exactly on fill
8. only then continue commission/slippage, 1m fill model, Limit/Stop/Flatten, etc.
```

## 16. Short handoff summary

```text
MASTER = FutureView historical futures replay + manual trading simulator.

Public site:
https://futureview.pages.dev/

Backend:
https://futureview.rueijrwu.workers.dev/

Replay:
5m causal actual-contract bars; ET display; UTC storage.

Trading:
market Buy/Sell; fill at next released bar open; authoritative DO accounting.

Viewport:
new replay session / Restart / Fit may auto-fit.
Normal replay/trading/pan actions must preserve view.

Axes:
price = right Y-axis
volume = independent left Y-axis
both fit once and freeze after Fit.

Annotations:
Start Replay and Random clear all drawings first.

Drawing tools:
H-Line/V-Line use a direct capture-phase chart click path because the normal chart callback was unreliable for one-anchor placement.

Console:
permanent ORDER/FILL log; temporary queued message clears when FILL arrives.

Critical engineering risk:
DO NOT use the truncating full-file connector path for site/app.js. Use Git blob/tree/ref operations and verify EOF.

Immediate next task:
smoke-test repeated H-Line/V-Line placement and the independent price/volume scale behavior in production.
```
