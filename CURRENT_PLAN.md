# FutureView Optimization & Dead-Code Plan

Written: 2026-09-19
Base commit: `c46ab174` (`docs: refresh FutureView optimization handoff`)
Companion document: `HANDOFF.md` (status, invariants, history). This file is the
forward-looking work plan; `HANDOFF.md` remains the record of what happened.

**Implementation status (2026-09-19): Phase 1 and Phase 3 items 8-10 are done.**
Everything each item below cites still describes the code as it was when this
plan was written; a note at the top of each implemented section says what
changed and points at the commit. Items still open: §2.3 (unreferenced Python),
§2.5 (`step`/`step_frame`), §3 P3/P4/P6, all of §4 (both frontend-copy options
and the worker helper extraction - both still need Ruei's decision), and Phase 4
in full.

## 0. How to read this

Every item below cites the code it came from as `file:line`. Each performance
item is labelled with the evidence behind it:

- **measured** — a benchmark was run against a faithful copy of the shipped
  function; the number is quoted along with what was measured.
- **structural** — the cost is visible in the code (an R2 round trip, an extra
  copy of an array) but was not timed end to end.
- **reasoned** — an inference from reading the code, not yet demonstrated.

No item claims a speedup that was not either measured or is not a direct
consequence of removing work that provably happens.

### Baseline verified before planning

- `node --test cloudflare/worker/*.test.mjs site/*.test.mjs` → **72 pass, 0 fail**
  on `c46ab174`. That is the regression gate every item below must keep green.
- Benchmarks were run on Node 22.22.2. A Workers isolate is generally slower
  than local Node, so the worker-side numbers are a floor, not a ceiling.

### Ground rules carried forward from HANDOFF.md §11

- One contained change at a time.
- Pin semantics with tests before changing them.
- Never touch auth, chart and transport in the same change.
- The production API/CORS probe stays green.
- **The browser must never receive data from after the replay cursor.** No item
  in this plan may weaken that, and the two items that touch causal paths
  (P1, P3) are explicitly specified to be output-identical.

---

## 1. Summary of what was found

| Area | Finding | Size |
| --- | --- | --- |
| Worker dead code | 5 methods in `replay-session-frame.js`, 1 in `replay-session-display.js`, 5 in `replay-session-core.js`, plus the module-level helper block they were the only users of | **312 lines, 23% of the worker's 1,367 core lines** |
| Worker hot path | `historySessionDate()` called once per bar while merging continuous history | **147 ms → 11 ms** (5m/3M), **1,182 ms → 35 ms** (1m/3M), measured |
| Browser hot path | `sessionKey()` called once per bar inside `_indicatorData()`, plus a per-bar `Object.entries()` allocation | **147 ms → 26 ms** (18k bars), measured, byte-identical output |
| Worker I/O | Playback downloads and parses a whole display window per window crossing to read a single timestamp out of it | structural |
| Duplication | Three divergent copies of the frontend; helper functions duplicated across four worker modules | 18 commits of drift |
| Correctness | `SESSION_END_HOUR_ET = 17` is **correct as written** — HANDOFF.md §16 item 1 is wrong | see §5 |

---

## 2. Dead code

### 2.1 Statically unreachable worker methods — safe to delete

**Done** in `6101fae` and `fa4bdd8`. All eleven methods below and the orphaned
helper block were removed exactly as described; 76 tests passed immediately
before and after each commit.

The durable-object class is a five-level chain:

```
DurableObject
  └ replay-session-core.js        ReplaySession
      └ replay-session.js          (shard prefetch, binary search)
          └ replay-session-frame.js    (display windows, timeframe/history)
              └ replay-session-display.js   (timestamp-authoritative aggregation)
                  └ replay-session-display-fast.js   ← wrangler.jsonc ships this one
```

`cloudflare/worker/main-frame.js:1` is the deployed entry point and exports the
`display-fast` subclass. Several methods on the lower levels are overridden by a
higher level that never calls `super` on them, and no `this.`-call can reach them
because dispatch always starts at `display-fast`. They are unreachable.

| File | Lines | Method | Why it is unreachable |
| --- | --- | --- | --- |
| `replay-session-frame.js` | 183–226 | `_ensureDisplayWindows` | overridden at `display-fast.js:352`, no `super` call |
| `replay-session-frame.js` | 228–259 | `_causalDisplayWindow` | overridden at `display.js:289`, which does not call `super` |
| `replay-session-frame.js` | 261–274 | `_broadcastDisplayWindow` | overridden at `display-fast.js:466`, no `super` call |
| `replay-session-frame.js` | 276–293 | `setTimeframe` | only caller is `display.js:330`, itself unreachable (next row) |
| `replay-session-frame.js` | 357–394 | `stepFrame` | overridden at `display.js:379`, which does not call `super` |
| `replay-session-display.js` | 328–332 | `setTimeframe` | overridden at `display-fast.js:246`, no `super` call |
| `replay-session-core.js` | 104–106 | `_findShardAtOrAfter` | binary-search override at `replay-session.js:66` |
| `replay-session-core.js` | 108–110 | `_findBarAtOrAfter` | binary-search override at `replay-session.js:78` |
| `replay-session-core.js` | 167–185 | `_warmupBars` | resident-shard override at `replay-session.js:95` |
| `replay-session-core.js` | 350–376 | `_tick` | overridden at `display.js:342`, no `super` call |
| `replay-session-core.js` | 378–401 | `_release` | overridden at `replay-session.js:182`, no `super` call |

Removing those eleven methods orphans the entire module-level timezone helper
block in `replay-session-frame.js`, which nothing else in that file uses:
`ET_FORMATTER` (8–17), `etParts` (19), `wallToEpochSeconds` (27),
`sessionStart` (40), `frameStart` (54), `frameKey` (62), `dailyTradingStamp` (70),
`displayCutoff` (77), `lowerBoundLastTime` (81), `lowerBoundBarTime` (92), and the
constants `DISPLAY_WINDOW_BARS` (6), `PREFETCH_THRESHOLD` (7) and
`FRAME_RESOLUTIONS` (3). `HISTORY_SECONDS` (5) and `SPEEDS` (4) stay: they are
still used by the live `setHistoryRange` (295) and `setSpeed` (308).

**Verification performed.** All of the above was physically deleted from a scratch
copy of the tree and the suite re-run:

```
replay-session-frame.js    395 → 164 lines
replay-session-display.js  422 → 417 lines
replay-session-core.js     550 → 474 lines
                          ----------------
                          1367 → 1055 lines   (−312)

node --check on every worker file:  parses OK
node --test (worker + site):        72 pass, 0 fail
```

That is evidence, not proof — the suite is 72 tests, not a coverage guarantee.
Delete in three commits (one per file) so any surprise bisects cleanly.

### 2.2 `main.js` exports the wrong replay class

**Done** in the same pass, folded into `fa4bdd8`.

`cloudflare/worker/main.js:1` imports `ReplaySession` from `replay-session.js`
and re-exports it at `main.js:12`. That export is dead: `main-frame.js:1` binds
the name to the `display-fast` subclass and `main-frame.js:2` takes only
`main.js`'s default export. The line is worse than unused — it is a loaded gun.
Anything that ever deploys `main.js` directly as the wrangler entry gets a
durable object with no display layer at all. Delete the import and the re-export.

### 2.3 Unreferenced Python

Three functions in `src/futureview_replay/resolver.py` are referenced nowhere in
`src/` or `tests/`:

- `session_volumes_from_bars` (line 70) — `cloud_export.py:137` builds session
  volumes inline instead of calling it.
- `build_selection_calendar` (line 160) — its own docstring says
  "Compatibility/diagnostic view only".
- `resolve_from_calendar` (line 172) — "Backward-compatible reader for old
  manifests"; the worker has its own legacy branch at `main.js:154`.

Roughly 40 lines. These are a *decision*, not an obvious delete: they exist for
old-manifest compatibility. Resolve them together with the v6-manifest question
in §3.5 rather than separately.

### 2.4 A dead local

**Done**, folded into the P1 commit (`20af785`) since it sat inside the code that commit rewrote.

`replay-session-display-fast.js:451` declares `const interval = Number(resolution) * 60;`
inside the non-daily branch of `_causalDisplayWindow` and never reads it — the
branch below uses `this.displayAggregate?.t`. One line.

### 2.5 The `step` command is a live endpoint on a stale code path

`replay-session-core.js:232` still routes `{type: "step"}` to `step()`
(`core.js:312`), and `site/app.js:172` still wires `#next` to `command("step")`.
In practice `site/replay-range.js:299-306` intercepts the `#next` click in the
capture phase and sends `step_frame` instead, so `step` never fires in the
browser. But if it ever did, `step()` calls `_release(1)` directly and never
updates `session.cursorTs` or the display aggregate, unlike every other release
path. That is a latent desync, not just dead weight.

Pick one and do it deliberately: either delete `step()` and the `#next` fallback
in `app.js`, or make `step()` route through the same release-and-aggregate path
as `stepFrame`. Do not leave it as is.

---

## 3. Performance

### P1 — Per-bar timezone conversion in continuous-history assembly (worker)

**Done** in `20af785`. Measured against the real (not reconstructed) function,
R2 stubbed so only the CPU stage is timed, output asserted identical:
164.6 ms → 14.5 ms (5m/3M), 1,242.7 ms → 126.3 ms (1m/3M) - close to the
estimates below. New equivalence tests sweep every hour across both DST
transitions (2,300+ comparisons) rather than trusting the "whole-hour bucket"
reasoning alone.

**The hot loop.** `replay-session-display-fast.js:236-241`:

```js
for (const [contractName, bars] of contractBars) {
  for (const bar of bars) {
    const sessionDate = historySessionDate(bar.t, resolution === "1D");
    if (selectedBySession.get(sessionDate) === contractName) merged.push(bar);
  }
}
```

`historySessionDate` (`:74`) calls `historyEtParts` (`:66`), which runs
`Intl.DateTimeFormat.formatToParts`, an `Array.filter`, an `Array.map` and
`Object.fromEntries` — then builds a `Date`, mutates it and calls
`toISOString().slice()`. Once per bar, per contract.

This runs on **every timeframe switch and every history-range button press**,
inside a WebSocket message handler, on the isolate's CPU budget.

**Measured** (`Intl` and the surrounding allocations, plus the `merged.sort()` and
the second filter at `:455-459`, against a hand-written version that filters once
up front and memoizes the session date per hour bucket):

| Case | Current | Optimized | Output |
| --- | --- | --- | --- |
| 5m / 3M, 18,000 bars × 2 contracts | **146.8 ms** | **11.3 ms** | identical |
| 1m / 3M, 129,000 bars × 2 contracts | **1,182.0 ms** | **35.1 ms** | identical |

**Why memoizing is sound.** A trading session boundary is 18:00 ET. Bucketing on
`Math.floor(t / 3600)` gives at most one distinct answer per clock hour, so the
cache can never merge two timestamps that fall on different session dates. Daily
mode needs a separate key (the benchmark used `~h`).

**The second half of the win** is ordering: the current code computes the session
date for every bar, keeps roughly all of them, sorts the whole array, and only
then discards everything at or after the active frame start (`:449`, `:455-459`).
Filtering by timestamp first is a pure comparison and drops the work before the
expensive part.

**Change.** In `_causalContinuousHistory`, hoist the active-frame cutoff above the
merge loop, discard by timestamp first, and memoize `historySessionDate` on an
hour bucket. **Do not change what is emitted.** The regression test is
`replay-continuous-history.test.mjs`; add a case that asserts the new output is
element-for-element equal to the old for a window spanning a contract roll before
touching the implementation.

### P2 — Per-bar timezone conversion in browser indicator rebuild

**Done** in `9e4e74d`, in `site/` only. Measured against the real function:
117.7 ms → 13.4 ms (5m/3M), 253.9 ms → 40.1 ms (1m/1M), output byte-identical.
Per §4.1, this has **not** been copied into `cloudflare/public/` or
`src/futureview_replay/static/` - `chart-tools.js` is currently byte-identical
across all three, and which of §4.1's three options resolves that divergence
is still Ruei's call, not something to default on silently.

**The hot loop.** `site/chart-tools.js:848-863` (`_indicatorData`):

```js
this.bars.forEach((bar, index) => {
  Object.entries(SMA_PERIODS).forEach(([key, period]) => { ... });   // allocates per bar
  const key = sessionKey(bar.time);                                   // Intl per bar
  ...
});
```

`sessionKey` (`site/chart-tools.js:41`) is the same `formatToParts` pattern as P1.
`Object.entries(SMA_PERIODS)` allocates a fresh 4-element array of 2-element
arrays on **every** bar — ~90,000 allocations for an 18k-bar load.

`_indicatorData` runs from `_refreshIndicators` (`chart-tools.js:871`), which
`site/chart-ui-repair.js:549` calls from `_fvSetDisplayData` whenever any
indicator is active — i.e. on every 3M history load and every timeframe switch.
This is main-thread work; the user feels it as the 3M button hanging.

**Measured**, against a version that hoists `Object.entries(SMA_PERIODS)` to a
module constant, uses an indexed loop, and memoizes `sessionKey` per hour bucket:

| Case | Current | Optimized | Output |
| --- | --- | --- | --- |
| 5m / 3M, 18,000 bars | **146.6 ms** | **25.9 ms** | `JSON.stringify` identical |
| 1m / 1M, 43,200 bars | **300.6 ms** | **39.6 ms** | `JSON.stringify` identical |

`_updateIndicatorsForLastBar` (`chart-tools.js:911`) and
`chart-ui-repair.js:440,455,466` have the same per-call `Object.entries` pattern
on the per-bar path; fold them into the same change.

**Note on scope.** `chart-tools.js` is the one file that is byte-identical across
all three frontend copies (§4.1). Decide §4.1 first, or this fix lands in `site/`
and silently does not reach the other two.

### P3 — Playback downloads a display window to read one number out of it

**Structural.** `replay-session-display-fast.js:371-386`:

```js
[current] = await Promise.all([
  this._loadDisplayWindow(index, resolution),
  this._loadDisplayWindow(index + 1, resolution),
]);
...
const bars = current.bars || [];
if (bars.length && !Number.isFinite(this.displayPrefetchAt)) {
  const thresholdIndex = Math.min(bars.length - 1, Math.floor((bars.length - 1) * PREFETCH_THRESHOLD));
  this.displayPrefetchAt = Number(bars[thresholdIndex].t);   // ← the only read
}
```

`_loadDisplayWindow` (`frame.js:147`) does an R2 `get`, a gzip decompress and a
`JSON.parse` of the whole window. I audited every reader of
`this.displayWindows` and of a loaded window's `.bars`:

- `display-fast.js:381` → `bars[thresholdIndex].t`, above. The only live read.
- `display-fast.js:191` reads `.bars`, but from `_loadHistoricalContractWindow`'s
  **separate** cache (`_fvHistoricalDisplayWindows`, `:136`), not this one.
- `display.js:307,309` and the now-dead `frame.js:204,246` are the fallback path
  that a v7 manifest never takes (§3.5).

So on the shipped manifest format, every window loaded into `this.displayWindows`
is downloaded, decompressed, parsed, cached, trimmed — and never displayed. The
`index + 1` preload at `:377` and the `index + 2` prefetch at `:395` feed nothing.

What it costs depends on the resolution, because window size is not uniform.
`cloud_export.py:14` sets `DISPLAY_WINDOW_BARS = 512` for the 5m/30m/240m/1D
caches, but the `"1"` display shards are the **monthly canonical shards**
(`cloud_export.py:177`), so a 1m "window" is roughly 43,200 bars, not 512.

**Change.** `_ensureDisplayWindows` needs a timestamp three quarters of the way
through the window. The manifest already carries `first_time` and `last_time` per
shard (`cloud_export.py:102-108`), so interpolate the threshold from metadata and
stop fetching bars on the playback path entirely. Gated on §3.5, because the
fallback path does still read those bars.

This is the largest available win in wall-clock terms — it removes R2 round trips
from playback rather than shaving CPU — but it is also the one with the least
test coverage today. Write the coverage first: a test that asserts no R2 `get` is
issued while stepping within a window, and one that asserts the prefetch still
fires at the same cursor as before.

### P4 — The historical-window cache counts windows, not bars

**Reasoned.** `replay-session-display-fast.js:150-151`:

```js
cached.set(cacheKey, value);
while (cached.size > 96) cached.delete(cached.keys().next().value);
```

96 entries. At 5m that is 96 × 512 ≈ 49k bars — fine. At 1m an entry is a whole
month, so the same cap admits 96 × ~43,200 ≈ 4.1M bar objects. The cap does not
bound memory, and a durable object is not a generous memory environment. Reaching
it takes a long session of switching timeframes, ranges and contracts, so this is
a robustness item, not a hot path.

**Change.** Budget by bar count rather than entry count.

Related, smaller: `frame.js:179-180` evicts foreign-resolution windows but keeps
`foreign[0]` indefinitely, whichever that happens to be in insertion order. At 1m
that is a retained month. Make the retention explicit or drop it.

### P5 — `renderTrading()` on every bar rebuilds the whole trades table

**Done** in `540dfde`. `app.js` has no test harness (a DOM-coupled IIFE with no
exports) and none was added; the new gating logic was instead extracted and
driven directly, confirming it renders once, skips repeated calls with
unchanged fills, re-renders on a real fill, and re-renders once when forced by
a selection change.

**Structural.** `site/app.js:130` — `render(b)` ends with `renderTrading()`, and
`renderTrading` (`:104`) rebuilds the fills table with
`$("trade-rows").innerHTML = fills.map(...).join("")` (`:118`) and then calls
`renderConsole()` (`:119`), which rebuilds the console with
`consoleEvents.map(...).join("\n")` (`:70`).

A newly released bar can change exactly five things: the unrealized, realized and
total P&L fields, the mark price and the time status. It cannot change the fills
list or the console. Yet every 1m bar during 1× playback re-serialises both.

`renderMany` (`:132`) calls `renderTrading()` once per batch, so this only bites
at low speed — but low speed is where a user actually sits and watches.

**Change.** Split `renderTrading` into a P&L update and a fills/console render,
and gate the latter on a change signature. The file already has exactly this
pattern in `renderTradeMarkers` (`:99-101`, `lastMarkerSignature`) — copy it.

Cheap and free alongside it: `$()` is `document.getElementById` (`app.js:2`) and
the per-bar path calls it repeatedly. Cache the handful of hot element
references at startup.

### P6 — Session volumes are accumulated row by row in the exporter

**Structural, build-time only.** `cloud_export.py:136-138` loops
`group.itertuples()` and calls `session_date()` — a `.astimezone()` — once per
1m row, for every row of every contract of every month. CI only exercises
`--limit 1`, so this is invisible there and expensive on a full republish.

`pandas` can do this as one vectorised `dt.tz_convert` plus a `groupby().sum()`.
Low priority: it never runs in a user's request path. Worth doing when the
exporter is next touched for another reason.

---

## 4. Duplication

### 4.1 Three frontends, one of them deployed

Measured against the working tree:

| File | `site/` ↔ `cloudflare/public/` | `cloudflare/public/` ↔ `src/futureview_replay/static/` |
| --- | --- | --- |
| `chart-tools.js` | identical | identical |
| `chart-tools-fixes.js` | 243 differing lines | 122 differing lines |
| `app.js` | 199 differing lines | 133 differing lines |
| `style.css` | 211 differing lines | identical |
| `index.html` | 81 differing lines | 10 differing lines |

`site/` was last touched by `1a51f4d` (2026-09-18). The other two were last
touched by `8c0d9d5` (2026-09-17). **18 commits have landed in `site/` since**,
including every chart performance commit and every causality fix listed in
`HANDOFF.md` §11.

The divergence is structural, not cosmetic. `site/index.html:102-107` loads six
scripts; `cloudflare/public/index.html:48-50` and
`src/futureview_replay/static/index.html:48-50` load three. The other two copies
have no `chart-ui-repair.js`, no `replay-window-assembler.js` and no
`replay-range.js` — so no timeframe control, no history-range buttons and no
chunked 3M assembly at all.

Both stale copies are reachable:

- `cloudflare/public/` is the worker's `ASSETS` binding (`wrangler.jsonc`), and
  `main.js:334` falls through to it for any authenticated request that matches no
  API route. Hitting the `workers.dev` origin directly serves the stale UI.
  `main.js:21` also serves `login.html`/`auth.js`/`auth.css` from here, so the
  directory cannot simply be emptied.
- `src/futureview_replay/static/` is mounted by the local FastAPI dev server
  (`app.py:62`, `app.py:76`) and shipped as package data (`pyproject.toml`).

**This is the highest-leverage structural item in the plan**, because it is what
turns every other fix into a third of a fix. Three options, in order of
preference:

1. **One source, built copies.** Keep `site/` canonical; have the deploy
   workflows copy it into the other two locations. Costs a build step; ends the
   drift permanently.
2. **Delete the duplicates.** Reduce `cloudflare/public/` to the login assets
   `main.js:21` actually needs and redirect the worker root to the Pages origin;
   point the FastAPI dev server at `site/`. Smallest tree, but changes how the
   dev server and the `workers.dev` origin behave.
3. **Status quo plus a guard.** Add a CI check that fails when `site/` changes
   without the copies changing. Cheapest, but keeps three of everything.

**This needs a decision from Ruei before anything else in §4 proceeds** — it is a
product question (does the local dev server still matter? should `workers.dev`
serve a UI at all?), not a refactor.

### 4.2 Duplicated helpers inside the worker

`HANDOFF.md` §16 item 2 flags this. Concretely, after the §2.1 deletions the
remaining duplication is:

- **Contract-expiry logic**, twice: `main.js:19-20,61-95` (`MONTH_NUMBER`,
  `CONTRACT_RE`, `contractExpiry`, `compareLocal`, `isExpiredAt`, `expiryLabel`)
  and `display-fast.js:63-115` (`CONTRACT_MONTH`, `CONTRACT_RE`,
  `contractExpiryLocal`, `compareLocalParts`, `contractExpiredForSession`).
  Same third-Friday + 14 rule, same 09:30 ET cutoff, two implementations.
- **Front-contract selection**, twice: `main.js:97-158` (`resolveContract`) picks
  the contract for a *requested start*; `display-fast.js:117-131`
  (`selectedContractForHistorySession`) picks it for *each historical session*.
  Same "highest prior-session volume among non-expired" rule.
- **ET part extraction**, three times: `display.js:6-23`, `display-fast.js:55-72`,
  `main.js:23-52`, each with its own `Intl.DateTimeFormat` and its own
  `Object.fromEntries(formatToParts(...))`. A fourth, `frame.js:8-25`, disappears
  with §2.1.
- **`HISTORY_SECONDS`** in three files, **`FRAME_RESOLUTIONS`** in three,
  **`SPEEDS`** in two, and near-identical `lowerBound*` binary searches in four.

HANDOFF.md's instruction — centralize only after tests exist — is right, and the
tests that matter are §5's boundary tests. Extract into a shared
`cloudflare/worker/session-time.js` once those land. Extracting the *expiry and
selection* logic is more valuable than extracting the binary searches, because
the two copies encode the same market rule and can drift apart silently.

### 4.3 No linter

**Partially done** in `a92696d`. `ruff` (pyflakes rules only) runs in
`replay-python.yml` before the unit tests; it is scoped to `select = ["F"]`
because the full default rule set surfaces ~30 pre-existing style findings
unrelated to this pass, and gating on those is a separate decision. The
JS-side no-unused-vars lint for `replay-cloudflare-check.yml` is still open -
it needs an eslint devDependency and config, a larger change than adding an
already-installed Python extra.

There is no `ruff`, `flake8`, `eslint` or equivalent in `pyproject.toml` or in
any workflow — CI runs `node --check` (syntax only) and `pytest`. Every finding in
§2.3 and §2.4 is something a linter reports for free.

Add `ruff` to the `test` extra and a lint step to `replay-python.yml`; add an
`eslint` no-unused-vars pass to `replay-cloudflare-check.yml`. This is the item
that stops §2 from being needed again in three months.

Note also that `replay-cloudflare-check.yml` syntax-checks
`cloudflare/public/app.js` and `src/futureview_replay/static/app.js` but not
`chart-tools.js` or `chart-tools-fixes.js` in either location — the stale copies
are only partly guarded even at the syntax level.

---

## 5. HANDOFF.md §16 item 1 is wrong: do not change `SESSION_END_HOUR_ET`

**Done** in `e1aad2f`. The value is unchanged (confirmed correct, per the
analysis below); the constant is renamed to `REQUESTED_SESSION_END_HOUR_ET`
with the reasoning below as an inline comment, and pinned from both sides by
`cloudflare/worker/replay-session-boundary.test.mjs` and
`tests/test_session_boundary.py` - one shared fixture of eleven timestamps
(16:59/17:00/17:59/18:00/18:01 ET, in EST, in EDT, and across a DST change),
asserted by both suites. Applying the change HANDOFF.md originally asked for
fails seven of the JS suite's rows. `HANDOFF.md` §3, §16 and §17 are corrected.

`HANDOFF.md` §3 and §16 call `SESSION_END_HOUR_ET = 17` at
`cloudflare/worker/main.js:16` a critical bug and instruct changing it to 18.
**That would introduce a bug, not fix one.** Evidence:

`src/futureview_replay/resolver.py:11-12` defines **two** constants, deliberately:

```python
SESSION_ROLL_HOUR_ET = 18
SESSION_END_HOUR_ET = 17
```

They serve different functions:

- `session_date()` (`resolver.py:19`) uses **18** and answers *"which trading
  session does this bar belong to?"*. It is what builds `session_volumes` and
  therefore the manifest's `sessions` list (`cloud_export.py:137,199`). 18:00 ET
  is the CME equity-index session roll, and it is correctly a hard invariant.
- `requested_session_date()` (`resolver.py:29`) uses **17** and answers *"given a
  requested start time, what is the first session that can contain a bar at or
  after it?"* — a different question with a different answer.

`main.js:54` `tradingSessionDate` has exactly one caller: `resolveContract`
(`main.js:108`), which maps a user-requested start to a session key. It is the JS
mirror of `requested_session_date`, not of `session_date`. **17 is correct there.**

The reason 17 is right: CME equity-index futures halt 17:00–18:00 ET daily. A
request at 17:30 ET falls inside that gap — there is no bar left in the current
session — so the first session that can contain a bar at or after it is the next
one. `resolver.py:30`'s docstring says precisely this.

Changing it to 18 would make a 17:00–17:59 ET start resolve to the session that
has already ended, and `resolveContract` would select the contract from the wrong
prior session.

Note that `replay-session-frame.js:43`, `replay-session-display.js:41` and
`display-fast.js:77` all use 18 — correctly, because they are all answering
`session_date`'s question, not `requested_session_date`'s.

**Action:**

1. Do **not** change the value.
2. Rename it to `REQUESTED_SESSION_END_HOUR_ET` and add a comment at
   `main.js:16` pointing at `resolver.py:29`, so the next reader does not file
   this again.
3. Add the boundary tests HANDOFF.md asked for — 16:59, 17:00, 17:59, 18:00 —
   asserting the **current** behaviour, and assert that `main.js`'s
   `tradingSessionDate` agrees with `resolver.py`'s `requested_session_date`
   while `display-fast.js`'s `historySessionDate` agrees with `session_date`.
   That is the test that makes the distinction impossible to lose again.
4. Correct `HANDOFF.md` §3 and §16 item 1.

---

## 6. Sequencing

The ordering is chosen so every risky change lands behind a test that already
passes, and so nothing has to be done twice.

**Addendum, 2026-09-19:** alongside this plan, a separately-reported bug was
fixed in `24af5e4` - switching bar scale never fit the chart, because
`_fvAutoFitPending` was initialized, read and cleared but nothing ever set it
to `true`. Unrelated to anything in this plan; noted here only because it
landed in the same batch of commits.

**Phase 1 — make the ground safe (no behaviour change).**

1. §5: rename the constant, add the four boundary tests plus the two
   cross-checks against `resolver.py`, fix `HANDOFF.md`. *Unblocks §4.2, and
   closes out HANDOFF's highest-priority item by disproving it.*
2. §4.3: add `ruff` and an unused-symbol JS lint to CI.
3. §2.1: delete the eleven unreachable methods and the orphaned helper block.
   Three commits, one per file; suite green after each. *(−312 lines, verified.)*
4. §2.2: drop the misleading `ReplaySession` re-export from `main.js`.
5. §2.4: drop the dead local.

**Phase 2 — decisions Ruei needs to make.** Neither is a refactor call:

6. §4.1: which of the three options for the frontend copies.
7. §3.5 / §2.3: is v6-manifest compatibility still required? If not,
   `_preloadDisplayHistory`, `display.js:289-326`, the `"1m"` fallback at
   `frame.js:142`, `main.js:154-157` and the three Python resolver functions all
   go, and P3 becomes straightforward.

**Phase 3 — the measured wins.** Each preceded by a test that pins the current
output, then the change, then the same test.

8. **P1** (worker continuous history) — 147 ms → 11 ms / 1,182 ms → 35 ms.
   Self-contained, highest value per unit of risk. Do this one first.
9. **P2** (browser indicator rebuild) — 147 ms → 26 ms. Blocked on §4.1 only
   because `chart-tools.js` is the shared file.
10. **P5** (per-bar `renderTrading`). Independent of everything else.
11. **P3** (stop loading window bars on the playback path). Blocked on item 7.
    Needs new tests first — it has the thinnest coverage of anything here.
12. **P4** (bar-budgeted cache). Robustness; can ride with P3.

**Phase 4 — carried over from HANDOFF.md §16, unchanged and still open.**

13. End-to-end timeframe-switch test: same cursor, compare visible current price
    across 1m/5m/30m/4h (HANDOFF §16.3).
14. Contract-roll boundary test (HANDOFF §16.4).
15. Decide raw vs. back-adjusted historical front-contract display
    (HANDOFF §16.5). Execution truth does not change either way.
16. §2.5: resolve the `step` / `step_frame` split.
17. **P6** (vectorise the exporter), whenever `cloud_export.py` is next opened.

HANDOFF.md §16 gates optimization behind items 13–15. That gating is relaxed here
for Phase 1 and Phase 3 items 8–10, which are output-identical by construction
and each land behind a pinning test. It is **not** relaxed for P3, which changes
when I/O happens on a causal path — that one waits for real coverage.

---

## 7. What was not verified

Stated plainly so nothing here is mistaken for more than it is.

- **No production measurement.** Every number is a local Node benchmark of a
  faithful copy of the shipped function, on synthetic bars. Nothing was timed
  against `futureview.workers.dev`, R2 or a real browser. Real R2 latency,
  isolate CPU throttling and the browser's own rendering are not in any figure.
- **Bar counts are estimates.** 18k bars for 5m/3M and 129k for 1m/3M are derived
  from `DISPLAY_WINDOW_BARS = 512`, the 5m/30m/240m/1D resolution set
  (`cloud_export.py:13`) and a ~23-hour session. The deployed manifest was not
  read; it needs auth.
- **The dead-code result is test evidence, not proof.** 72 tests passing after
  removal is strong but not exhaustive. The unreachability argument in §2.1 is
  static and I believe it is sound, but the deletions should still land one file
  per commit.
- **§3.5 rests on the exporter, not on the live manifest.** `cloud_export.py:201`
  writes `"version": 7` with `session_volumes` populated, and
  `display-fast.js:207` only falls back when `session_volumes` is absent — so the
  continuous path is taken for any manifest this code publishes. If a
  hand-published or older manifest is live, that inference does not hold.
- **P3 and P4 are structural and reasoned respectively**, not measured. P3's
  value is real but its size is unknown until R2 latency is measured.
- **Not audited at all:** `cloudflare/worker/auth.js`, the D1 migrations, the
  drawing-tool half of `chart-tools.js` (roughly lines 55–820), and the deploy
  workflows beyond reading what they check.
