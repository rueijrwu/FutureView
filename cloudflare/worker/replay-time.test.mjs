import assert from "node:assert/strict";
import test from "node:test";

import {
  dailyTradingStamp,
  displayStamp,
  etParts,
  frameKey,
  sessionStart,
  tradingDayKey,
} from "./replay-time.js";

const ts = (iso) => Math.floor(Date.parse(iso) / 1000);

test("5m and 30m buckets use Eastern session alignment", () => {
  const value = ts("2024-06-10T14:32:00Z"); // 10:32 EDT
  assert.equal(displayStamp(value, "5"), ts("2024-06-10T14:30:00Z"));
  assert.equal(displayStamp(value, "30"), ts("2024-06-10T14:30:00Z"));
});

test("overnight bars stay in the 18:00 ET futures session", () => {
  const value = ts("2024-06-11T01:15:00Z"); // 21:15 EDT on June 10
  assert.equal(sessionStart(value), ts("2024-06-10T22:00:00Z"));
  assert.equal(displayStamp(value, "240"), ts("2024-06-11T02:00:00Z")); // 22:00 EDT bucket
  assert.equal(tradingDayKey(value), 20240611);
});

test("daily bars are stamped at midnight Eastern in daylight time", () => {
  const value = ts("2024-06-10T14:30:00Z");
  assert.equal(dailyTradingStamp(value), ts("2024-06-10T04:00:00Z"));
  assert.deepEqual(etParts(dailyTradingStamp(value)), {
    month: 6, day: 10, year: 2024, hour: 0, minute: 0, second: 0,
  });
});

test("daily bars are stamped at midnight Eastern in standard time", () => {
  const value = ts("2024-12-10T15:30:00Z");
  assert.equal(dailyTradingStamp(value), ts("2024-12-10T05:00:00Z"));
});

test("18:00 ET starts the next trading day", () => {
  const value = ts("2024-06-10T22:01:00Z"); // 18:01 EDT
  assert.equal(tradingDayKey(value), 20240611);
  assert.equal(frameKey(value, "1D"), "D:20240611");
});
