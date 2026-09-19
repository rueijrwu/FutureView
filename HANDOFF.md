# FutureView Handoff

Last updated: 2026-09-19
Branch: `master`
Forward plan: `CURRENT_PLAN.md`

## 1. Product goal

FutureView is a causal historical futures replay/trading simulator.

Core rule:

> The browser must never receive information from after the replay cursor.

Backend/Durable Object is authoritative for replay state, order execution, contract identity, and timestamp progression.

Production:

- Frontend: https://futureview.pages.dev
- Worker: https://futureview.rueijrwu.workers.dev

Do not use deployment-specific `xxxx.futureview.pages.dev` URLs for production debugging. Worker CORS is intentionally keyed to the canonical Pages origin.

## 2. Current architecture

Canonical replay/trading timeline:

- 1-minute actual-contract bars
- timestamp authoritative; array indexes are accelerators only
- market orders fill at the next released canonical 1-minute bar open
- high-speed playback may batch work but cannot skip logical 1-minute bars

Display resolutions:

- 1m
- 5m
- 30m
- 4h
- 1D

Display/cache is separate from canonical trading state.

Current native/precomputed display cache:

- 1m
- 5m
- 30m
- 4h
- 1D

Higher-timeframe current/incomplete bars must always be constructed from released canonical 1m bars only.

## 3. Time/session invariants

User-facing display time:

- `America/New_York`

Protocol/storage timestamps:

- UTC epoch seconds

Futures session roll:

- **18:00 ET**

This is a hard invariant.

### Two session hours, not one

There are two distinct questions, and the system answers them with two different
constants. Confusing them has already produced one wrong bug report (see below).

| Question | Constant | Python | Worker |
| --- | --- | --- | --- |
| Which trading session does this **bar** belong to? | `SESSION_ROLL_HOUR_ET = 18` | `resolver.py session_date` | `display-fast.js historySessionDate`, `display.js sessionStart` |
| Given a **requested start time**, what is the first session that can hold a bar at or after it? | `SESSION_END_HOUR_ET = 17` | `resolver.py requested_session_date` | `main.js tradingSessionDate` |

CME equity-index futures halt 17:00-18:00 ET daily. A request at 17:30 has no bar
left in the current session, so it must resolve to the next one - hence 17 for the
second question. The two answers differ only inside that halt hour.

**RESOLVED (was "critical bug"): `main.js`'s 17 is correct and must not be changed
to 18.** Earlier revisions of this document called it inconsistent and asked for it
to be raised to 18. That would have been a regression: every 17:00-17:59 ET start
would resolve to the session that has already ended, and `resolveContract` would
then select the contract from the wrong prior session.

The constant is now named `REQUESTED_SESSION_END_HOUR_ET` and pinned from both
sides by one shared fixture:

- `cloudflare/worker/replay-session-boundary.test.mjs`
- `tests/test_session_boundary.py`

Both assert the same table at 16:59, 17:00, 17:59, 18:00 and 18:01 ET, in EST, in
EDT, and across a DST change. Applying the old "fix" fails seven of them.

## 4. Correct restore/optimization baseline

The rollback to `5e741988` was too early.

The correct pre-second-review optimized checkpoint was:

- `dbf4c23d141e52b9b623c70b2c9e1062e564ab87`
  - `feat(replay): activate selected-timeframe display worker`

It was restored through:

- `ca54e1a2`
  - `revert: restore pre-second-review optimized state`

Everything after that was re-optimized incrementally with regression tests.

Do not repeat the large second-review refactor wholesale.

## 5. Critical production outage lesson

A previous refactor replaced the working auth path and queried:

- `app_users`
- `app_sessions`

Production D1 actually defines:

- `auth_users`
- `auth_sessions`

That caused authenticated API calls to fail and Firefox surfaced:

- `NetworkError when attempting to fetch resource`

The correct production auth path is the original `auth.js` implementation using the `auth_*` tables.

Do not reintroduce the inline `app_users/app_sessions` auth rewrite.

## 6. Deployment guards now required

Cloudflare deploy workflow must verify:

- live Worker `/api/auth/status`
- browser CORS preflight from `https://futureview.pages.dev`

Pages deploy workflow must verify:

- project production branch = `master`
- canonical `https://futureview.pages.dev/` returns the FutureView page

Do not treat a successful unique Pages deployment URL as proof production is healthy.

## 7. Viewport / auto-fit policy

Allowed to fit automatically:

- Start Replay
- Random
- Restart
- explicit Fit

Must preserve viewport:

- Play
- Pause
- Next
- speed changes
- incoming bars/batches
- timeframe data updates
- cached history arrival
- trade marker updates
- Buy/Sell
- Clear trading
- Trades/Console layout toggles

Recent fix:

- `532f18bc` — `fix(chart): never auto-fit after Next data`
- `1a51f4d5` — test-only correction

Root cause was duplicate fit behavior:

- `app.js reset()` already explicitly calls `chartTools.fit()`
- `chartTools.reset()` also armed `_fvAutoFitPending = true`
- a later cached window could consume that flag during Next/Play and unexpectedly fit

Current rule:

- reset gets one explicit fit only
- `_fvAutoFitPending` must not remain armed after reset

## 8. History-range behavior

History-range buttons:

- 1D
- 5D
- 1M
- 3M

3M = 90 calendar days.

Recent 3M fixes:

### `b7c19114` — stream and apply full 3M history

Problem:

- Worker sent the entire 3M display window as one WebSocket message
- 5m 3M can be ~15k-18k bars
- visible 90-day range was not applied until history response arrived

Fix:

- visible axis switches to requested history immediately
- large display-history payloads are chunked at 4096 bars
- browser assembles chunks in `site/replay-window-assembler.js`
- chart `setData()` is called once after complete assembly
- small 1M/etc responses keep legacy single-message behavior

### `73a48c15` — keep history range anchored at replay cursor

Problem:

- synthetic right boundary used `cursor + max(1 day, history/4, ...)`
- 3M therefore created ~22.5 fake future days

Fix:

- left anchor = `cursor - history`
- right anchor = only a small selected-timeframe pad
- no multi-day future whitespace

## 9. Historical contract selection / volume

Recent fix:

- `636bb01a` — `fix(replay): stitch causal front-contract history`

Problem:

- long display history originally used `this.session.contract` for the whole range
- when looking months backward, that contract might not yet have been front/active
- early historical volume therefore looked abnormally tiny

Current behavior:

- historical display is stitched by trading session
- each session selects a contract using **previous-session volume only**
- same-session/future volume is never used
- current live replay remains on the actual cursor-selected contract
- no R2 republish was needed; existing per-contract display caches are reused

Important consequence:

- this is an **unadjusted front-contract continuous display**
- raw contract rolls can contain real price gaps
- do not silently back-adjust unless explicitly designed/approved
- if visual roll gaps become undesirable, add an explicit display mode rather than modifying execution truth

## 10. Timeframe switching / price-jump bug

Most recent fix:

- `2c486209ebd4fe03f75da70acff10666e835e2a7`
- `fix(replay): seed active frame before timeframe history`

Observed symptom:

- switching 1m -> 5m could make price jump
- switching through another scale could make it disappear

Root cause:

The Worker used this order:

1. clear selected-timeframe active aggregate
2. broadcast precomputed history
3. rebuild active partial candle

During step 2 there was no active-frame cutoff. The precomputed history could therefore include the **full current 5m candle**, including canonical 1m minutes after the replay cursor.

That leaked future data into the timeframe-change display path and could expose the wrong close.

Current order:

1. set new timeframe
2. reset aggregate + display cursor
3. build the causal active partial candle from released 1m data
4. establish active bucket timestamp
5. broadcast historical bars strictly before that bucket
6. send snapshot

Regression tests now cover:

- switching to 5m mid-bucket
- active 5m OHLC ends at actual replay cursor
- full cached current bucket is excluded from history

This is a critical causality invariant.

## 11. Incremental optimization work already applied

Important performance commits after the correct restore point include:

- `f961608b` — remove per-minute async release overhead
- `f3b84665` — reuse resident shard for warmup
- `da5021b0` — avoid per-minute timezone aggregation work
- `b17414eb` — batch selected-frame Next release
- `e9c3a32e` — fast-path resident cursor validation
- `5de489a4` — parallelize display window prefetch
- `e3f04447` — seed active frame aggregation once
- `7293fc53` — preload long history windows in parallel
- `d77e90fd` — dedupe/background display prefetch
- `8e81f4c9` — avoid repeated timezone conversion in VWAP scan
- `1938811b` — incremental VWAP updates
- `65ac541a` — rolling SMA updates
- `38d8a7c2` / `190357a8` — consume preloaded history synchronously + syntax fix
- `31699d29` — binary-search replay start position
- `6d6202a9` — defer hidden indicator history
- `b2c6b46b` — skip hidden live indicator updates
- `b390d890` — reuse resolved startup shard
- `6dced814` — rebuild daily active frame arithmetically
- `b4aea530` — batch daily Next release
- `54fb1a86` — cache indicator visibility
- `2a748bdd` — fast-path warmup aggregation
- `2f1258a1` — align raw daily stamps to Eastern midnight
- `fa453c8e` — prefetch next canonical shard

Optimization strategy must remain:

- one contained change at a time
- pin semantics with tests first
- do not touch auth/chart/transport simultaneously
- production API/CORS probe must stay green

## 12. Current transport/display implementation

Key files:

- `cloudflare/worker/replay-session-core.js`
  - stable core replay engine
- `cloudflare/worker/replay-session.js`
  - optimized wrapper around canonical release/warmup
- `cloudflare/worker/replay-session-frame.js`
  - selected-timeframe/window layer
- `cloudflare/worker/replay-session-display.js`
  - timestamp-authoritative selected-frame logic
- `cloudflare/worker/replay-session-display-fast.js`
  - current optimized display subclass
- `cloudflare/worker/main-frame.js`
  - exports current display replay class
- `site/chart-ui-repair.js`
  - browser chart controller
- `site/replay-range.js`
  - history range/timeframe WebSocket interception + range behavior
- `site/replay-window-assembler.js`
  - chunked long-history reassembly
- `site/app.js`
  - main replay/trading client

## 13. app.js editing warning

Do not use a connector path that replaces `site/app.js` without verifying full content; this previously truncated the file while still producing a successful commit/deploy.

Safe procedure:

1. fetch complete current `site/app.js`
2. modify in memory
3. `create_blob`
4. `create_tree` using current master tree
5. `create_commit`
6. `update_ref`
7. fetch edited region and EOF tail
8. verify final `})();`

Prefer Git Data API primitives for `site/app.js`.

## 14. Trading behavior

Current model:

- market orders only
- quantity 1..100
- request at current replay cursor
- fill at next released canonical 1m bar open
- multiple pending orders
- scale in/out
- reversals
- persisted trading state

Point values:

- MES = $5 / point / contract
- ES = $50 / point / contract

Clear trading:

- clears position/pending/fills/P&L/console
- does not restart replay
- does not move cursor
- does not fit chart

## 15. Required smoke tests after every relevant change

### Production/connectivity

1. canonical `futureview.pages.dev` loads
2. login/auth works
3. Worker `/api/auth/status` reachable
4. CORS preflight from canonical Pages origin succeeds
5. replay WebSocket stays connected

### Replay causality

6. browser never gets a canonical bar after cursor
7. 1m Next advances exactly one 1m bar
8. 5m Next advances exactly one selected 5m display frame while processing underlying 1m bars
9. pending order fills at first newly released 1m bar open
10. changing timeframe does not move replay cursor
11. current incomplete higher-TF candle contains only released 1m bars
12. cached current higher-TF bucket is never exposed as completed history

### Viewport

13. Start/Random/Restart/Fit may fit
14. Next never fits
15. Play never fits
16. incoming cache/data never fits
17. timeframe change preserves viewport unless explicitly requested otherwise

### History

18. 1D/5D/1M/3M buttons change requested visible domain
19. 3M does not show fake future days
20. chunked 3M history reassembles exactly once
21. historical contract stitching uses prior-session volume only
22. no same-session/future volume drives historical contract choice

### Time

23. all display labels ET
24. protocol/storage UTC
25. futures session roll = 18:00 ET

## 16. Current known risks / next work

See `CURRENT_PLAN.md` for the full optimization and dead-code plan, its evidence,
and its sequencing. What remains open from this document's own list:

1. ~~Fix `SESSION_END_HOUR_ET = 17` in `cloudflare/worker/main.js` to 18~~ -
   **withdrawn, the value was already correct.** See section 3. Boundary tests
   landed on both sides; the constant was renamed, not changed.
2. Audit the duplicated session/expiry/contract-selection helpers now present in `main.js` and `replay-session-display-fast.js`; centralize only after tests exist.
3. Add an end-to-end timeframe-switch test that compares visible current price across 1m/5m/30m/4h at the same cursor.
4. Add a test around a real contract-roll boundary:
   - current cursor contract
   - stitched historical front contract
   - active partial candle
   - no accidental price substitution
5. Decide whether front-contract historical display should remain raw/unadjusted or offer an explicit back-adjusted visualization mode. Never alter execution truth.
6. Continue optimization only after the above correctness checks.

## 17. Short handoff

```text
HEAD = 2c486209ebd4fe03f75da70acff10666e835e2a7

Production:
https://futureview.pages.dev
https://futureview.rueijrwu.workers.dev

Canonical replay/trading:
1-minute actual-contract bars.

Display:
1m / 5m / 30m / 4h / 1D.
Current higher-TF bar is always reconstructed from released 1m only.

History:
1D / 5D / 1M / 3M.
3M uses chunked WebSocket history.
Historical display is causally stitched across front contracts using prior-session volume.

Viewport:
Start / Random / Restart / Fit may fit.
Next / Play / data / cache / timeframe updates must not auto-fit.

Recent critical fixes:
636bb01a  causal front-contract history (fixes tiny early volume)
2c486209  active partial frame seeded before timeframe history (fixes 1m->5m price jump / future bucket leak)
532f18bc  no delayed auto-fit after Next
73a48c15  no large fake future range anchor
b7c19114  chunked full 3M history

Session hours (two, deliberately):
18:00 ET  which session a bar belongs to    (session_date / historySessionDate)
17:00 ET  which session a requested start resolves to
          (requested_session_date / tradingSessionDate)
They differ only inside the 17:00-18:00 ET halt. Do not collapse them.

Do not reapply the old second full-refactor wholesale.
Continue incrementally with semantic tests + production health gates.
```
