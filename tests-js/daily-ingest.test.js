import assert from "node:assert/strict";
import test from "node:test";

import { normalizeGroupedDaily } from "../worker/daily-ingest.js";

test("normalizeGroupedDaily keeps complete numeric bars and rejects malformed rows", () => {
  const payload = {
    results: [
      { T: "AAA", o: 10, h: 12, l: 9, c: 11, v: 1000 },
      { T: "BBB", o: "20", h: "22", l: "19", c: "21", v: "2000" },
      { T: "MISS", o: 1, h: 2, l: 0.5, c: null, v: 50 },
      { o: 1, h: 2, l: 0.5, c: 1.5, v: 50 },
    ],
  };

  assert.deepEqual(normalizeGroupedDaily(payload, "2026-08-21"), [
    {
      symbol: "AAA",
      date: "2026-08-21",
      open: 10,
      high: 12,
      low: 9,
      close: 11,
      volume: 1000,
    },
    {
      symbol: "BBB",
      date: "2026-08-21",
      open: 20,
      high: 22,
      low: 19,
      close: 21,
      volume: 2000,
    },
  ]);
});
