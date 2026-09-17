# FutureView Replay Handoff

Last updated: 2026-09-17
Primary branch: `master`

## 1. Current goal

FutureView is a historical futures replay/trading simulator with causal replay, manual simulated trading, chart annotation tools, and persistent trading state.

Core rule: the browser must never receive data after the replay cursor. The backend/Durable Object remains authoritative for replay and trading state.

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
src/futureview_replay/prepare.py
src/futureview_replay/store.py
src/futureview_replay/cloud_export.py
cloudflare/worker/replay-session.js
cloudflare/worker/main.js
.github/workflows/replay-pages-deploy.yml
.github/workflows/replay-cloudflare-deploy.yml
.github/workflows/replay-data-publish.yml
HANDOFF.md
```

## 3. Replay/data invariants

Keep these unless explicitly changed:

1. Browser never receives bars after the replay cursor.
2. Durable Object owns authoritative replay state.
3. Actual futures contract identity/prices are execution truth.
4. Canonical replay/runtime resolution is now **1 minute**.
5. User-facing time is `America/New_York`; protocol/storage timestamps are UTC.
6. Replay input is product + time; user does not preselect the actual contract.
7. Contract selection remains causal.
8. High replay speed may batch work but must not skip logical 1-minute bars.
9. Play/Pause/Next remain deterministic.
10. A market order requested at the current cursor fills only at the next released 1-minute bar open.

Current replay speed buttons:

```text
1  5  10  50  100  Max
```

Default replay time is `08:30` ET.

## 4. Multi-timeframe display data

Requested chart resolutions:

```text
1m
5m
30m
4h
1D
```

The chart timeframe is a display concern and must not change replay/trading state.

Native published data:

```text
1m  -> canonical replay/display source
1D  -> explicitly generated futures-session daily bars
```

TradingView Advanced Charts can rebuild larger intraday bars from native 1-minute data, so 5m/30m/4h do not need duplicated stored datasets.

The daily resolution is different: TradingView cannot rebuild daily bars from intraday data, therefore `cloud_export.py` now publishes native `1D` bars as well.

Cloud manifest version 6 advertises:

```text
supported_display_resolutions = ["1", "5", "30", "240", "1D"]
native_display_resolutions    = ["1", "1D"]
intraday_multipliers          = ["1"]
daily_multipliers             = ["1"]
```

Per-contract manifest data keeps:

```text
shards                  authoritative 1m replay shards used by Durable Object
display_shards["1m"]    native 1m chart data
display_shards["1D"]    native daily chart data
```

Daily OHLCV is grouped by the futures trading-session date, using the existing 17:00 ET session roll rule. The exported daily timestamp is 00:00 UTC for that trading day, as required by TradingView.

### Current chart-library caveat

Production `site/index.html` currently loads **TradingView Lightweight Charts 5.2.1**, not Advanced Charts. Lightweight Charts does not provide the Advanced Charts resolution selector/datafeed contract automatically.

The data side is now prepared correctly for Advanced Charts: 1m and 1D are native; 5m/30m/4h can be rebuilt from 1m. When the Advanced Charts widget/datafeed is connected, its `supported_resolutions`, `intraday_multipliers`, `daily_multipliers`, and `getBars` implementation should consume this manifest rather than create separate duplicated 5m/30m/4h archives.

Changing chart resolution must NOT:

```text
restart replay
move replay cursor
clear trades
change selected actual contract
reveal future data
change order execution resolution
```

## 5. Viewport / auto-fit policy — critical

Automatic fit/scale is allowed only when a new replay session starts or when explicitly requested:

```text
Start Replay
Random
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

Current Fit behavior in `site/chart-tools-fixes.js`:

```text
fit X with fitContent()
enable price Y autoscale
enable volume Y autoscale
wait for Lightweight Charts to calculate ranges
freeze both Y scales again
```

The delayed freeze is intentional. Freezing immediately caused incorrect fitted Y ranges.

## 6. Price and volume axes

Price and volume are intentionally independent:

```text
Price  -> right Y-axis
Volume -> left Y-axis
```

Expected behavior:

```text
manual right-axis scaling affects price only
manual left-axis scaling affects volume only
Fit fits both once, then freezes both
horizontal pan does not autoscale either
```

### Volume-axis panning

The left volume axis now supports both scaling and vertical panning.

Normal left-axis drag keeps Lightweight Charts' native scale/zoom behavior.

To vertically pan/translate the volume range without changing its span:

```text
Shift + left-drag on the left volume axis
or
middle-button drag on the left volume axis
```

Implementation uses Lightweight Charts 5.2 price-scale `getVisibleRange()` / `setVisibleRange()` and leaves the right price axis untouched. Autoscale remains disabled after manual volume panning.

Volume retains its lower-chart margin:

```text
top: 0.8
bottom: 0
```

## 7. Chart tools

Current feature set:

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

### H-Line / V-Line special path

H-Line/V-Line placement bypasses `chart.subscribeClick()` and uses a capture-phase container click because the normal callback was unreliable for one-anchor tools.

Multi-point tools continue using the existing chart callback path.

## 8. Annotation lifecycle

Current behavior:

```text
Start Replay -> clear all drawings first
Random       -> clear all drawings first
Restart      -> does not explicitly clear drawings
```

Start/Random clearing is implemented in `site/chart-tools-fixes.js` before the new session begins.

## 9. Trading engine

Current execution model:

```text
market orders only
Buy/Sell quantity 1..100
request at current replay cursor
fill at NEXT released 1m bar OPEN
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

## 10. Restart vs Clear

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

Console is a trading activity log, hidden by default.

It records:

```text
ORDER when an order is accepted/queued
FILL  when the order executes
```

Temporary queued status must disappear when the fill event arrives while permanent ORDER/FILL history remains.

## 12. app.js editing warning — highest priority

The GitHub file-replacement connector previously truncated `site/app.js`, producing successful commits/deployments with a broken site.

Known bad commits included:

```text
5749e860
72adcd2c
```

Current known-good `site/app.js` blob:

```text
cb4a45259ad5efaa83c1359ab3699ca109f7c61a
```

Safe procedure for future `site/app.js` edits:

```text
1. fetch COMPLETE current blob
2. modify in memory
3. create_blob
4. create_tree using current master tree as base
5. create_commit with current master as parent
6. update_ref master
7. fetch modified region AND EOF tail
8. verify initialization and final `})();`
```

Do NOT use the truncating full-file replacement path for `site/app.js` until proven safe.

## 13. Recent implementation commits

```text
957ccf25  use 1m bars as canonical replay store
2d8fbaea  publish canonical 1m cloud bars
c7f9d800  exercise canonical 1m engine data
fa6bac59  validate 1m cloud manifest resolutions
86a68e93  align app fixture with 1m replay data
465d848e  allow independent volume-axis panning
e637b980  publish native 1m and futures-session 1D bars
c2764c4e  validate native 1m and 1D display shards
```

Earlier chart fixes still relevant:

```text
c7872d02  correct one-shot Fit timing
7b187078  independent visible volume Y-axis on left
8fa0bea3  clear annotations on Start Replay and Random
39600bfe  synchronize draw-tool toolbar state
e8eb875b  direct H-Line/V-Line placement path
```

## 14. Immediate smoke-test checklist

```text
1. Production page loads and login/start replay works.
2. Replay advances one minute per logical step.
3. Market order fills at next released 1m bar open.
4. No future 1m bar is exposed.
5. Start/Random fit and clear annotations as intended.
6. Play/Pause/Next do not move/scale viewport.
7. Right price-axis scaling affects price only.
8. Left volume-axis scaling affects volume only.
9. Shift+drag left volume axis vertically pans volume without changing price scale.
10. Middle-drag left volume axis does the same.
11. Fit restores/fits both scales once and freezes them.
12. H-Line/V-Line repeated arm/place cycles work.
13. Trend/Ray/Rect/Fib/Text still work.
14. Buy/Sell queued status appears and clears on fill.
15. Clear resets trading only and leaves replay cursor/view intact.
16. Republished R2 manifest reports version 6, resolution 1m, native 1m + 1D.
17. 1D bars use futures session dates and 00:00 UTC timestamps.
```

## 15. Recommended next work

```text
1. Finish/verify the Advanced Charts widget/datafeed integration.
2. Datafeed advertises supported resolutions 1, 5, 30, 240, 1D.
3. Datafeed serves native 1m and 1D only.
4. Allow TradingView to rebuild 5m/30m/4h from 1m.
5. Ensure realtime partial higher-timeframe bars remain causal.
6. Add JS syntax validation to CI for every file in site/.
7. Add browser smoke tests for viewport and volume-axis panning.
8. Keep regression tests for drawing tools and trading state.
```

## 16. Short handoff summary

```text
MASTER = FutureView historical futures replay + manual trading simulator.

Replay truth:
1-minute actual-contract bars.
No future data may pass the replay cursor.

Display resolutions:
1m / 5m / 30m / 4h / 1D.
Native data = 1m + 1D.
TradingView should rebuild 5m/30m/4h from 1m.

Trading:
market Buy/Sell; fill at next released 1m bar open.

Axes:
price = independent right Y-axis.
volume = independent left Y-axis.
left-axis normal drag scales; Shift+drag or middle-drag pans vertically.

Viewport:
new replay / Restart / Fit may auto-fit.
Normal replay/trading actions preserve the view.

Critical engineering risk:
do not use the unsafe full-file replacement path for site/app.js.

Current next task:
verify the 1m/1D R2 republish and then wire the Advanced Charts datafeed to the manifest.
```
