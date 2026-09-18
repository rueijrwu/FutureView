import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let baselineSource = await fs.readFile(new URL("./replay-session-display.js", import.meta.url), "utf8");
baselineSource = baselineSource.replace(
  'import { ReplaySession as FrameReplaySession } from "./replay-session-frame.js";',
  "class FrameReplaySession {}",
);
const baselineUrl = `data:text/javascript;base64,${Buffer.from(baselineSource).toString("base64")}`;

let fastSource = await fs.readFile(new URL("./replay-session-display-fast.js", import.meta.url), "utf8");
fastSource = fastSource.replace("./replay-session-display.js", baselineUrl);
const fastUrl = `data:text/javascript;base64,${Buffer.from(fastSource).toString("base64")}`;
const { ReplaySession } = await import(fastUrl);

const sec = (iso) => Math.floor(Date.parse(iso) / 1000);

function harness() {
  const instance = Object.create(ReplaySession.prototype);
  instance.displayResolution = "5";
  instance.historyRange = "3M";
  instance.session = { contract: "MESZ6", cursorTs: sec("2026-09-18T16:00:00-04:00") };
  instance.displayAggregate = { t: sec("2026-09-18T16:00:00-04:00") };
  instance._getPrefix = () => "mes-replay/v1";
  return instance;
}

test("continuous history switches contracts using prior-session volume", async () => {
  const instance = harness();
  instance._manifest = async () => ({
    product: "MES",
    contract_selection: {
      sessions: ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"],
      session_volumes: {
        "2026-09-15": { MESU6: 1000, MESZ6: 100 },
        "2026-09-16": { MESU6: 700, MESZ6: 1200 },
        "2026-09-17": { MESU6: 100, MESZ6: 1800 },
        "2026-09-18": { MESZ6: 2000 },
      },
    },
    contracts: {
      MESU6: { display_shards: { "5": [] } },
      MESZ6: { display_shards: { "5": [] } },
    },
  });
  instance._contractHistoryBars = async (contractName) => {
    if (contractName === "MESU6") {
      return [
        { t: sec("2026-09-15T10:00:00-04:00"), v: 100 },
        { t: sec("2026-09-16T10:00:00-04:00"), v: 110 },
        { t: sec("2026-09-17T10:00:00-04:00"), v: 5 },
      ];
    }
    return [
      { t: sec("2026-09-16T10:00:00-04:00"), v: 7 },
      { t: sec("2026-09-17T10:00:00-04:00"), v: 140 },
      { t: sec("2026-09-18T10:00:00-04:00"), v: 150 },
    ];
  };

  const bars = await instance._causalContinuousHistory(
    sec("2026-09-18T16:00:00-04:00"),
    "5",
    "3M",
  );

  assert.deepEqual(
    bars.map((bar) => [bar.t, bar.v]),
    [
      [sec("2026-09-16T10:00:00-04:00"), 110],
      [sec("2026-09-17T10:00:00-04:00"), 140],
      [sec("2026-09-18T10:00:00-04:00"), 150],
    ],
  );
});

test("history contract selection never uses same-session volume", async () => {
  const instance = harness();
  instance._manifest = async () => ({
    product: "MES",
    contract_selection: {
      sessions: ["2026-09-15", "2026-09-16"],
      session_volumes: {
        "2026-09-15": { MESU6: 900, MESZ6: 100 },
        "2026-09-16": { MESU6: 1, MESZ6: 5000 },
      },
    },
    contracts: {
      MESU6: { display_shards: { "5": [] } },
      MESZ6: { display_shards: { "5": [] } },
    },
  });
  instance._contractHistoryBars = async (contractName) => contractName === "MESU6"
    ? [{ t: sec("2026-09-16T10:00:00-04:00"), v: 200 }]
    : [{ t: sec("2026-09-16T10:00:00-04:00"), v: 2 }];

  const bars = await instance._causalContinuousHistory(
    sec("2026-09-16T16:00:00-04:00"),
    "5",
    "3M",
  );

  assert.equal(bars.length, 1);
  assert.equal(bars[0].v, 200);
});
