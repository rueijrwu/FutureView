// The 17:00-18:00 ET daily halt is where FutureView's two session questions give
// different answers, and where they have been confused before (HANDOFF.md section 16
// item 1 asked for main.js's 17 to be "fixed" to 18, which would have been a bug).
//
//   main.js tradingSessionDate        mirrors resolver.py requested_session_date (17)
//     "first session that can hold a bar at or after this requested start"
//   display-fast.js historySessionDate mirrors resolver.py session_date          (18)
//     "which trading session does this bar belong to"
//
// SESSION_BOUNDARY_CASES below is generated from the Python implementations and is
// asserted by both suites; tests/test_resolver.py checks the same table. If the two
// sides ever disagree, one of these suites fails instead of production quietly
// selecting a contract from the wrong session.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

const SESSION_BOUNDARY_CASES = [
  { et: "2026-03-16T16:59:00", utc: 1773694740, requested: "2026-03-16", session: "2026-03-16", note: "EDT, hour before the halt" },
  { et: "2026-03-16T17:00:00", utc: 1773694800, requested: "2026-03-17", session: "2026-03-16", note: "EDT, halt begins" },
  { et: "2026-03-16T17:59:00", utc: 1773698340, requested: "2026-03-17", session: "2026-03-16", note: "EDT, last minute of the halt" },
  { et: "2026-03-16T18:00:00", utc: 1773698400, requested: "2026-03-17", session: "2026-03-17", note: "EDT, session roll" },
  { et: "2026-03-16T18:01:00", utc: 1773698460, requested: "2026-03-17", session: "2026-03-17", note: "EDT, just after the roll" },
  { et: "2026-12-09T16:59:00", utc: 1796853540, requested: "2026-12-09", session: "2026-12-09", note: "EST, hour before the halt" },
  { et: "2026-12-09T17:00:00", utc: 1796853600, requested: "2026-12-10", session: "2026-12-09", note: "EST, halt begins" },
  { et: "2026-12-09T17:59:00", utc: 1796857140, requested: "2026-12-10", session: "2026-12-09", note: "EST, last minute of the halt" },
  { et: "2026-12-09T18:00:00", utc: 1796857200, requested: "2026-12-10", session: "2026-12-10", note: "EST, session roll" },
  { et: "2026-03-07T17:30:00", utc: 1772922600, requested: "2026-03-08", session: "2026-03-07", note: "EST, halt on the Saturday before the DST change" },
  { et: "2026-03-08T17:30:00", utc: 1773005400, requested: "2026-03-09", session: "2026-03-08", note: "EDT, halt on the DST change day" },
];

// Both helpers are module-private. Load each module with its imports stubbed and
// the helper appended to the export list, rather than widening the real surface.
async function loadPrivate(file, replacements, exportNames) {
  let source = await fs.readFile(new URL(file, import.meta.url), "utf8");
  for (const [pattern, to] of replacements) {
    assert.match(source, pattern, `${file} no longer matches ${pattern}`);
    source = source.replace(pattern, to);
  }
  source += `\nexport { ${exportNames.join(", ")} };\n`;
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
}

const { tradingSessionDate, REQUESTED_SESSION_END_HOUR_ET } = await loadPrivate(
  "./main.js",
  [[/import \{[\s\S]*?\} from "\.\/auth\.js";/, "const authenticate = null, createAuthSession = null, currentUser = null, destroySession = null, purgeExpiredSessions = null, register = null, registrationOpen = null;"]],
  ["tradingSessionDate", "REQUESTED_SESSION_END_HOUR_ET"],
);

const { historySessionDate, historySessionDateUncached } = await loadPrivate(
  "./replay-session-display-fast.js",
  [[/import \{ ReplaySession as DisplayReplaySession \} from "\.\/replay-session-display\.js";/, "class DisplayReplaySession {}"]],
  ["historySessionDate", "historySessionDateUncached"],
);

test("the requested-session hour is 17, matching resolver.py requested_session_date", () => {
  assert.equal(REQUESTED_SESSION_END_HOUR_ET, 17);
});

for (const item of SESSION_BOUNDARY_CASES) {
  test(`requested session at ${item.et} ET (${item.note})`, () => {
    assert.equal(tradingSessionDate(item.utc * 1000), item.requested);
  });

  test(`bar session at ${item.et} ET (${item.note})`, () => {
    assert.equal(historySessionDate(item.utc), item.session);
  });
}

test("the two questions genuinely differ inside the 17:00-18:00 ET halt", () => {
  // The guard that makes this suite worth having: if someone "fixes" main.js to 18,
  // these rows collapse to equality and this fails.
  const inHalt = SESSION_BOUNDARY_CASES.filter((item) => item.requested !== item.session);
  assert.ok(inHalt.length >= 4, "expected halt-window cases where the answers diverge");
  for (const item of inHalt) {
    const hour = Number(item.et.slice(11, 13));
    assert.ok(hour >= 17 && hour < 18, `${item.et} diverges outside the halt window`);
  }
});

test("outside the halt window both questions agree", () => {
  for (const item of SESSION_BOUNDARY_CASES) {
    const hour = Number(item.et.slice(11, 13));
    if (hour >= 17 && hour < 18) continue;
    assert.equal(item.requested, item.session, `${item.et} should agree`);
  }
});

// historySessionDate memoises on the UTC hour. That is only sound because
// America/New_York is offset from UTC by a whole number of hours, so one UTC hour
// never straddles an ET calendar day or the 18:00 session boundary. Sweep every
// hour across both DST transitions and assert the memoised answer equals the
// direct one - if that assumption ever breaks, this fails instead of production
// stitching history onto the wrong contract.
test("the memoised session date matches the direct computation hour by hour", () => {
  const spans = [
    ["2026-03-06T00:00:00Z", 24 * 6],  // spring forward, 2026-03-08
    ["2026-10-30T00:00:00Z", 24 * 6],  // fall back, 2026-11-01
    ["2026-06-15T00:00:00Z", 24 * 3],  // a plain EDT week
    ["2026-01-05T00:00:00Z", 24 * 3],  // a plain EST week
  ];
  let checked = 0;
  for (const [start, hours] of spans) {
    const base = Math.floor(Date.parse(start) / 1000);
    for (let hour = 0; hour < hours; hour += 1) {
      for (const offset of [0, 1, 1799, 3599]) {
        const seconds = base + hour * 3600 + offset;
        for (const daily of [false, true]) {
          assert.equal(
            historySessionDate(seconds, daily),
            historySessionDateUncached(seconds, daily),
            `mismatch at ${new Date(seconds * 1000).toISOString()} daily=${daily}`,
          );
          checked += 1;
        }
      }
    }
  }
  assert.ok(checked > 2000, `expected a dense sweep, checked ${checked}`);
});

test("a non-finite timestamp bypasses the cache instead of poisoning it", () => {
  // formatToParts rejects an invalid date, and it did before memoising too, so the
  // throw is the pre-existing contract. What matters here is that NaN takes the
  // uncached path rather than becoming a cache key.
  assert.throws(() => historySessionDateUncached(NaN, false), RangeError);
  assert.throws(() => historySessionDate(NaN, false), RangeError);
  assert.throws(() => historySessionDate(Infinity, true), RangeError);
  // A real lookup is unaffected afterwards. 17:00 ET is inside the halt, so the
  // bar-session answer is still the 16th - this is the 18:00 question, not the
  // requested-start one.
  assert.equal(historySessionDate(1773694800), "2026-03-16");
  assert.equal(historySessionDate(1773694800), historySessionDateUncached(1773694800, false));
});
