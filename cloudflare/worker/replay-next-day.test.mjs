// "Next Day" transport button: jumps the replay cursor to 9:30 AM ET (market
// open) on the next trading day found in manifest.contract_selection.sessions
// - skipping weekends/holidays since those never appear in that list - by
// handing the target timestamp to the existing _releaseUntilBefore primitive
// (replay-session.js), so auto-flatten and order fills still run bar by bar
// across the jump exactly as a normal play/step would.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let source = await fs.readFile(new URL("./replay-session-display.js", import.meta.url), "utf8");
source = source.replace(
  'import { ReplaySession as FrameReplaySession } from "./replay-session-frame.js";',
  "class FrameReplaySession {}",
);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { ReplaySession } = await import(moduleUrl);

const sec = (iso) => Math.floor(Date.parse(iso) / 1000);

function bar(iso, price) {
  const t = sec(iso);
  return { t, o: price, h: price + 1, l: price - 1, c: price + 0.5, v: 1 };
}

function minuteBars(startIso, count, priceBase = 100) {
  const first = sec(startIso);
  return Array.from({ length: count }, (_, i) => ({
    t: first + i * 60,
    o: priceBase + i,
    h: priceBase + i + 1,
    l: priceBase + i - 1,
    c: priceBase + i + 0.5,
    v: 1,
  }));
}

function harness({ current, sessions, displayResolution = "1" }) {
  const instance = Object.create(ReplaySession.prototype);
  instance.session = { state: "PAUSED", cursorTs: current.t };
  instance.displayResolution = displayResolution;
  instance.displayAggregate = null;
  instance.displayAggregateResolution = null;
  instance.displayAggregateCursor = null;
  instance._ensureReplayCursor = async () => current;
  if (displayResolution !== "1") {
    // Short-circuits _ensureDisplayAggregate's warmup path: nextDay isn't
    // exercising aggregate reconstruction, only what it does with the
    // released bars, so seed a matching in-progress aggregate up front.
    instance.displayAggregate = { t: current.t, o: current.o, h: current.h, l: current.l, c: current.c, v: current.v };
    instance.displayAggregateResolution = displayResolution;
    instance.displayAggregateCursor = current.t;
  }
  instance._manifest = async () => ({ contract_selection: { sessions } });
  instance._persist = async () => {};
  const broadcasts = [];
  instance._broadcast = (payload) => broadcasts.push(payload);
  instance.snapshot = () => ({ type: "session_snapshot" });
  return { instance, broadcasts };
}

test("nextDay releases through 9:30 ET on the next session and broadcasts completed + in-progress display bars", async () => {
  const current = bar("2026-09-16T14:00:00-04:00", 5000);
  const { instance, broadcasts } = harness({
    current,
    sessions: ["2026-09-15", "2026-09-16", "2026-09-17"],
    displayResolution: "5",
  });

  const marketOpen = sec("2026-09-17T09:30:00-04:00");
  const releaseArgs = [];
  const raw = minuteBars("2026-09-17T09:20:00-04:00", 11, 5010); // 09:20 through 09:30
  instance._releaseUntilBefore = async (targetExclusive, maxCount) => {
    releaseArgs.push({ targetExclusive, maxCount });
    return raw;
  };

  await instance.nextDay();

  assert.equal(releaseArgs.length, 1);
  assert.equal(releaseArgs[0].targetExclusive, marketOpen + 60, "target is the bar after the 9:30 open, so it's included");
  assert.equal(instance.session.cursorTs, raw.at(-1).t);

  const batch = broadcasts.find((b) => b.type === "bars_batch");
  assert.ok(batch, "expects a batch of aggregated 5m display bars");
  // The stale in-progress candle from before the jump (seeded at the old
  // cursor) is flushed first because the new bars land in a different
  // bucket, same as any other large gap; then 11 one-minute bars from :20
  // through :30 make two completed 5m candles (:20-:24, :25-:29) plus one
  // in-progress candle (:30 alone) - four bars total.
  assert.equal(batch.bars.length, 4);
  assert.equal(batch.bars.at(-1).t, sec("2026-09-17T09:30:00-04:00"));
  assert.equal(batch.bars.at(-1).display_resolution, "5");

  assert.ok(broadcasts.some((b) => b.type === "session_snapshot"));
});

test("nextDay skips a weekend by following the sessions list, not calendar days", async () => {
  const current = bar("2026-09-18T10:00:00-04:00", 5000); // Friday
  const { instance } = harness({
    current,
    sessions: ["2026-09-17", "2026-09-18", "2026-09-21"], // Thu, Fri, Mon
  });

  let target = null;
  instance._releaseUntilBefore = async (targetExclusive) => {
    target = targetExclusive;
    return [];
  };

  await instance.nextDay();

  assert.equal(target, sec("2026-09-21T09:30:00-04:00") + 60, "jumps to Monday's open, not Saturday");
});

test("nextDay is a no-op when the manifest has no further trading day", async () => {
  const current = bar("2026-09-18T10:00:00-04:00", 5000);
  const { instance, broadcasts } = harness({
    current,
    sessions: ["2026-09-17", "2026-09-18"],
  });

  let called = false;
  instance._releaseUntilBefore = async () => { called = true; return []; };

  await instance.nextDay();

  assert.equal(called, false, "nothing to jump to, so the release primitive is never invoked");
  assert.ok(broadcasts.some((b) => b.type === "session_snapshot"));
});

test("nextDay refuses to run while playing, same guard as stepFrame", async () => {
  const current = bar("2026-09-16T14:00:00-04:00", 5000);
  const { instance } = harness({ current, sessions: ["2026-09-16", "2026-09-17"] });
  instance.session.state = "PLAYING";

  await assert.rejects(() => instance.nextDay(), /Pause before jumping to the next day/);
});
