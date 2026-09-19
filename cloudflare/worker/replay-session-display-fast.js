import { ReplaySession as DisplayReplaySession } from "./replay-session-display.js";

const FRAME_RESOLUTIONS = new Set(["1", "5", "30", "240", "1D"]);
const LONG_GAP_SECONDS = 6 * 60 * 60;
const PREFETCH_THRESHOLD = 0.75;
const MAX_PARTIAL_MINUTES = 1500;
const HISTORY_SECONDS = { "1D": 86400, "5D": 5 * 86400, "1M": 30 * 86400, "3M": 90 * 86400 };
const HISTORY_LOAD_CONCURRENCY = 4;
const DISPLAY_WINDOW_CHUNK_BARS = 4096;

function newAggregate(bar, stamp) {
  return {
    t: Number(stamp),
    o: Number(bar.o),
    h: Number(bar.h),
    l: Number(bar.l),
    c: Number(bar.c),
    v: Number(bar.v) || 0,
  };
}

function addToAggregate(aggregate, bar) {
  aggregate.h = Math.max(Number(aggregate.h), Number(bar.h));
  aggregate.l = Math.min(Number(aggregate.l), Number(bar.l));
  aggregate.c = Number(bar.c);
  aggregate.v = (Number(aggregate.v) || 0) + (Number(bar.v) || 0);
}

function completedBar(aggregate, resolution) {
  return { ...aggregate, display_resolution: String(resolution) };
}

function lowerBoundBarTime(bars, target, start = 0) {
  let lo = Math.max(0, Number(start) || 0);
  let hi = bars.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(bars[mid].t) >= Number(target)) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

function lowerBoundLastTime(items, target) {
  let lo = 0;
  let hi = items.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(items[mid].last_time) >= Number(target)) hi = mid;
    else lo = mid + 1;
  }
  return lo < items.length ? lo : items.length - 1;
}

const HISTORY_ET_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  hourCycle: "h23",
});
const CONTRACT_MONTH = Object.fromEntries([..."FGHJKMNQUVXZ"].map((code, index) => [code, index + 1]));
const CONTRACT_RE = /^(.+?)([FGHJKMNQUVXZ])(\d{1,2})$/;

function historyEtParts(seconds) {
  return Object.fromEntries(
    HISTORY_ET_FORMATTER.formatToParts(new Date(Number(seconds) * 1000))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
}

function historySessionDateUncached(seconds, daily) {
  const parts = historyEtParts(seconds);
  const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (!daily && parts.hour >= 18) day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

// historySessionDate runs Intl.DateTimeFormat.formatToParts, and the continuous
// history merge calls it once per bar: ~18k bars for a 3M window at 5m, ~129k at
// 1m, per timeframe switch and per history-range press. Measured on that merge,
// memoising here takes it from 147ms to 11ms at 5m and 1182ms to 35ms at 1m.
//
// Bucketing on the UTC hour is exact, not approximate. America/New_York is offset
// from UTC by a whole number of hours, so every timestamp inside one UTC hour has
// the same ET year, month, day and hour, and therefore the same answer. The 18:00
// session boundary falls on an hour edge, so a bucket can never straddle it.
// `daily` skips that advance, so it needs its own table.
const SESSION_DATE_CACHE = new Map();
const DAILY_SESSION_DATE_CACHE = new Map();
const SESSION_DATE_CACHE_MAX = 1 << 16;

function historySessionDate(seconds, daily = false) {
  const hour = Math.floor(Number(seconds) / 3600);
  if (!Number.isFinite(hour)) return historySessionDateUncached(seconds, daily);
  const cache = daily ? DAILY_SESSION_DATE_CACHE : SESSION_DATE_CACHE;
  const cached = cache.get(hour);
  if (cached !== undefined) return cached;
  const value = historySessionDateUncached(seconds, daily);
  if (cache.size >= SESSION_DATE_CACHE_MAX) cache.clear();
  cache.set(hour, value);
  return value;
}

function contractExpiryLocal(contract, referenceYear) {
  const match = CONTRACT_RE.exec(String(contract));
  if (!match) return null;
  const month = CONTRACT_MONTH[match[2]];
  const digits = match[3];
  let year;
  if (digits.length === 2) year = 2000 + Number(digits);
  else {
    const digit = Number(digits);
    const candidates = [];
    for (let y = referenceYear - 1; y < referenceYear + 10; y += 1) {
      if (y % 10 === digit) candidates.push(y);
    }
    year = candidates.sort((a, b) => Math.abs(a - referenceYear) - Math.abs(b - referenceYear))[0];
  }
  const first = new Date(Date.UTC(year, month - 1, 1));
  const firstFriday = 1 + (5 - first.getUTCDay() + 7) % 7;
  return { year, month, day: firstFriday + 14, hour: 9, minute: 30 };
}

function compareLocalParts(a, b) {
  for (const key of ["year", "month", "day", "hour", "minute"]) {
    const av = Number(a?.[key] ?? 0);
    const bv = Number(b?.[key] ?? 0);
    if (av !== bv) return av - bv;
  }
  return 0;
}

function contractExpiredForSession(contract, sessionDate) {
  const [year, month, day] = String(sessionDate).split("-").map(Number);
  const expiry = contractExpiryLocal(contract, year);
  if (!expiry) return false;
  return compareLocalParts({ year, month, day, hour: 18, minute: 0 }, expiry) >= 0;
}

function selectedContractForHistorySession(manifest, sessions, sessionVolumes, sessionIndex) {
  const sessionDate = sessions[sessionIndex];
  const sourceSession = sessionIndex > 0 ? sessions[sessionIndex - 1] : null;
  if (!sourceSession) return null;
  const candidates = Object.entries(sessionVolumes[sourceSession] ?? {})
    .map(([contract, volume]) => [contract, Number(volume)])
    .filter(([contract, volume]) =>
      manifest.contracts?.[contract] &&
      Number.isFinite(volume) &&
      volume > 0 &&
      !contractExpiredForSession(contract, sessionDate)
    )
    .sort((a, b) => b[1] - a[1]);
  return candidates[0]?.[0] ?? null;
}

export class ReplaySession extends DisplayReplaySession {
  async _loadHistoricalContractWindow(contractName, resolution, index, meta) {
    const cacheKey = `history:${contractName}:${resolution}:${index}`;
    const cached = this._fvHistoricalDisplayWindows ??= new Map();
    if (cached.has(cacheKey)) return cached.get(cacheKey);

    const loads = this._fvHistoricalDisplayLoads ??= new Map();
    if (loads.has(cacheKey)) return loads.get(cacheKey);
    const load = (async () => {
      const prefix = this._getPrefix();
      const object = await this.env.MES_DATA.get(`${prefix}/${meta.key}`);
      if (!object) throw new Error(`Missing historical display cache ${meta.key}`);
      const stream = meta.key.endsWith(".gz")
        ? object.body.pipeThrough(new DecompressionStream("gzip"))
        : object.body;
      const bars = JSON.parse(await new Response(stream).text());
      const value = { index, meta, bars };
      cached.set(cacheKey, value);
      while (cached.size > 96) cached.delete(cached.keys().next().value);
      return value;
    })();
    loads.set(cacheKey, load);
    try {
      return await load;
    } finally {
      if (loads.get(cacheKey) === load) loads.delete(cacheKey);
    }
  }

  async _contractHistoryBars(contractName, resolution, historyFrom, cursor) {
    const manifest = await this._manifest();
    const contract = manifest.contracts?.[contractName];
    if (!contract) return [];
    let shards = contract.display_shards?.[resolution] ?? [];
    if (!shards.length && resolution === "1") {
      shards = contract.display_shards?.["1m"] ?? contract.shards ?? [];
    }
    if (!shards.length) return [];

    const first = Math.max(0, lowerBoundLastTime(shards, historyFrom));
    const last = Math.max(first, lowerBoundLastTime(shards, cursor));
    const windows = [];
    for (let index = first; index <= last; index += HISTORY_LOAD_CONCURRENCY) {
      const group = [];
      for (let offset = 0; offset < HISTORY_LOAD_CONCURRENCY && index + offset <= last; offset += 1) {
        const windowIndex = index + offset;
        group.push(this._loadHistoricalContractWindow(
          contractName,
          resolution,
          windowIndex,
          shards[windowIndex],
        ));
      }
      windows.push(...await Promise.all(group));
    }

    const out = [];
    for (const window of windows) {
      for (const bar of window?.bars ?? []) {
        const t = Number(bar.t);
        if (t >= historyFrom && t <= cursor) out.push(bar);
      }
    }
    return out;
  }

  // maxExclusive drops bars at or after the active frame before they are looked up
  // and before the sort, instead of after. The caller used to post-filter the whole
  // merged array; doing it here is the same output for strictly less work.
  async _causalContinuousHistory(cursor, resolution, historyRange, maxExclusive = null) {
    const manifest = await this._manifest();
    const selection = manifest.contract_selection ?? {};
    const sessionVolumes = selection.session_volumes;
    const sessions = (Array.isArray(selection.sessions)
      ? selection.sessions.map((item) => typeof item === "string" ? item : item?.session).filter(Boolean)
      : Object.keys(sessionVolumes ?? {})
    ).sort();
    if (!sessionVolumes || !sessions.length) return null;

    const seconds = HISTORY_SECONDS[historyRange] ?? HISTORY_SECONDS["5D"];
    const historyFrom = Number(cursor) - seconds;
    const firstSession = historySessionDate(historyFrom, resolution === "1D");
    const lastSession = historySessionDate(cursor, resolution === "1D");
    let firstIndex = sessions.findIndex((session) => session >= firstSession);
    if (firstIndex < 0) return [];
    const lastIndex = sessions.findLastIndex((session) => session <= lastSession);
    if (lastIndex < firstIndex) return [];

    const selectedBySession = new Map();
    const contracts = new Set();
    for (let index = firstIndex; index <= lastIndex; index += 1) {
      const contractName = selectedContractForHistorySession(manifest, sessions, sessionVolumes, index);
      if (!contractName) continue;
      selectedBySession.set(sessions[index], contractName);
      contracts.add(contractName);
    }
    if (!contracts.size) return null;

    const contractBars = await Promise.all(
      [...contracts].map(async (contractName) => [
        contractName,
        await this._contractHistoryBars(contractName, resolution, historyFrom, cursor),
      ]),
    );

    const merged = [];
    const daily = resolution === "1D";
    const limit = Number.isFinite(maxExclusive) ? Number(maxExclusive) : Infinity;
    for (const [contractName, bars] of contractBars) {
      for (const bar of bars) {
        const t = Number(bar.t);
        if (t >= limit) continue;
        if (selectedBySession.get(historySessionDate(t, daily)) === contractName) merged.push(bar);
      }
    }
    merged.sort((a, b) => Number(a.t) - Number(b.t));
    return merged;
  }

  async setTimeframe(value, historyRange = this.historyRange) {
    const timeframe = String(value || "5");
    if (!FRAME_RESOLUTIONS.has(timeframe)) throw new Error(`Unsupported chart timeframe ${timeframe}`);
    if (historyRange != null && !HISTORY_SECONDS[String(historyRange)]) {
      throw new Error(`Unsupported history range ${historyRange}`);
    }

    this.displayResolution = timeframe;
    if (historyRange != null) this.historyRange = String(historyRange);
    this._resetDisplayAggregate();
    this._resetDisplayCursor();

    // Establish the causal active bucket before historical cache assembly.
    // Otherwise the precomputed current bucket may contain unreleased future
    // canonical minutes and can momentarily replace the live partial candle.
    await this._ensureDisplayAggregate();
    await this._broadcastDisplayWindow();

    this._broadcast({
      ...this.snapshot(),
      display_resolution: this.displayResolution,
      history_range: this.historyRange,
      display_cache: {
        window_bars: 512,
        current_window: this.displayWindowIndex,
      },
    });
  }

  async _ensureReplayCursor() {
    const session = this.session;
    if (session && this.shard) {
      const shardIndex = Number(session.shardIndex);
      const barIndex = Number(session.barIndex);
      const contract = this.manifest?.contracts?.[session.contract];
      const meta = contract?.shards?.[shardIndex];
      if (
        meta &&
        this.shardKey === meta.key &&
        Number.isInteger(barIndex) &&
        barIndex >= 0 &&
        barIndex < this.shard.length
      ) {
        const bar = this.shard[barIndex];
        if (bar && Number(session.cursorTs) === Number(bar.t)) return bar;
      }
    }
    return super._ensureReplayCursor();
  }

  async _ensureDisplayAggregate() {
    const resolution = String(this.displayResolution || "1");
    if (resolution === "1") return;
    const current = await this._ensureReplayCursor();
    if (
      this.displayAggregate &&
      this.displayAggregateResolution === resolution &&
      Number(this.displayAggregateCursor) === Number(current.t)
    ) return;

    const warmup = await this._warmupBars(
      this.session.shardIndex,
      this.session.barIndex,
      MAX_PARTIAL_MINUTES,
    );

    this.displayAggregate = null;
    this.displayAggregateResolution = null;
    this.displayAggregateCursor = null;
    super._consumeCanonicalBars([current], resolution);
    const frameStart = Number(this.displayAggregate?.t);
    if (!Number.isFinite(frameStart)) return super._ensureDisplayAggregate();

    // A daily display bar is stamped at midnight ET for its trading day.
    // The CME equity-futures session for that trading day begins at 18:00 ET
    // on the previous calendar day, exactly six elapsed hours before midnight.
    const activeStart = resolution === "1D" ? frameStart - 6 * 60 * 60 : frameStart;
    const start = lowerBoundBarTime(warmup, activeStart);
    let aggregate = null;
    for (let index = start; index < warmup.length; index += 1) {
      const bar = warmup[index];
      if (Number(bar.t) > Number(current.t)) break;
      if (!aggregate) aggregate = newAggregate(bar, frameStart);
      else addToAggregate(aggregate, bar);
    }

    this.displayAggregate = aggregate || newAggregate(current, frameStart);
    this.displayAggregateResolution = resolution;
    this.displayAggregateCursor = Number(current.t);
  }

  async _loadDisplayWindow(index, resolution = this.displayResolution) {
    const key = `${resolution}:${index}`;
    if (this.displayWindows?.has(key)) return this.displayWindows.get(key);
    const loads = this._fvDisplayWindowLoads ??= new Map();
    if (loads.has(key)) return loads.get(key);

    const load = super._loadDisplayWindow(index, resolution);
    loads.set(key, load);
    try {
      return await load;
    } finally {
      if (loads.get(key) === load) loads.delete(key);
    }
  }

  async _ensureDisplayWindows(cursor) {
    const resolution = this.displayResolution;
    cursor = Number(cursor);
    if (!Number.isFinite(cursor)) return;
    if (cursor < this.displayNextCheckAt && this.displayWindowIndex >= 0) return;

    const shards = await this._displayShardMeta(resolution);
    if (!shards.length) return;

    let index = this.displayWindowIndex;
    const meta = shards[index];
    if (index < 0 || !meta || cursor < Number(meta.first_time) || cursor > Number(meta.last_time)) {
      index = lowerBoundLastTime(shards, cursor);
      if (index < 0) return;
      this.displayWindowIndex = index;
      this.displayPrefetchedIndex = -1;
      this.displayPrefetchAt = -Infinity;
    }

    let current;
    if (resolution === "1") {
      current = await this._loadDisplayWindow(index, resolution);
    } else {
      [current] = await Promise.all([
        this._loadDisplayWindow(index, resolution),
        this._loadDisplayWindow(index + 1, resolution),
      ]);
    }
    if (!current) return;
    const bars = current.bars || [];

    if (bars.length && !Number.isFinite(this.displayPrefetchAt)) {
      const thresholdIndex = Math.min(bars.length - 1, Math.floor((bars.length - 1) * PREFETCH_THRESHOLD));
      this.displayPrefetchAt = Number(bars[thresholdIndex].t);
    }

    if (
      resolution !== "1" &&
      cursor >= this.displayPrefetchAt &&
      this.displayPrefetchedIndex !== index + 2
    ) {
      const target = index + 2;
      this.displayPrefetchedIndex = target;
      const prefetch = this._loadDisplayWindow(target, resolution).catch((error) => {
        if (this.displayPrefetchedIndex === target) this.displayPrefetchedIndex = -1;
        console.error("Display prefetch failed", error);
        return null;
      });
      if (this.ctx?.waitUntil) this.ctx.waitUntil(prefetch);
      else await prefetch;
    }

    const edge = Number(current.meta.last_time) + 1;
    this.displayNextCheckAt = resolution === "1" || this.displayPrefetchedIndex === index + 2
      ? edge
      : Math.min(edge, this.displayPrefetchAt);
    this._trimDisplayWindows(index, resolution);
  }

  async _preloadDisplayHistory(cursor, resolution = this.displayResolution, historyRange = this.historyRange) {
    cursor = Number(cursor);
    resolution = String(resolution || this.displayResolution || "5");
    historyRange = String(historyRange || this.historyRange || "5D");
    if (!Number.isFinite(cursor) || resolution !== String(this.displayResolution)) return;

    await this._ensureDisplayWindows(cursor);
    const center = Number(this.displayWindowIndex);
    if (!Number.isInteger(center) || center < 0) return;

    const shards = await this._displayShardMeta(resolution);
    if (!shards.length) return;
    const seconds = HISTORY_SECONDS[historyRange] ?? HISTORY_SECONDS["5D"];
    const historyFrom = cursor - seconds;
    const firstNeeded = Math.max(0, Math.min(center, lowerBoundLastTime(shards, historyFrom)));
    const missing = [];
    for (let index = firstNeeded; index <= center; index += 1) {
      if (!this.displayWindows.has(`${resolution}:${index}`)) missing.push(index);
    }

    for (let offset = 0; offset < missing.length; offset += HISTORY_LOAD_CONCURRENCY) {
      const group = missing.slice(offset, offset + HISTORY_LOAD_CONCURRENCY);
      await Promise.all(group.map((index) => this._loadDisplayWindow(index, resolution)));
    }
  }

  async _causalDisplayWindow(cursor, resolution = this.displayResolution, historyRange = this.historyRange) {
    cursor = Number(cursor);
    resolution = String(resolution || this.displayResolution || "5");
    historyRange = String(historyRange || this.historyRange || "5D");
    if (!Number.isFinite(cursor)) return [];

    // 1D is bounded by trading day, not by timestamp, so it keeps its own filter -
    // and it is ~90 bars for a 3M window, so there is nothing to gain there anyway.
    // Every other resolution is bounded by the active frame start, which the merge
    // can apply itself. A non-finite aggregate timestamp means no bound, exactly as
    // the old post-filter's `!Number.isFinite(activeStart) ||` did.
    const activeStart = resolution === "1D"
      ? null
      : (resolution === "1" ? Number(cursor) : Number(this.displayAggregate?.t));
    const maxExclusive = Number.isFinite(activeStart) ? activeStart : null;

    const continuous = await this._causalContinuousHistory(cursor, resolution, historyRange, maxExclusive);
    if (continuous) {
      if (resolution === "1D") {
        const cutoff = historySessionDate(cursor, true);
        return continuous.filter((bar) => historySessionDate(bar.t, true) < cutoff);
      }
      // maxExclusive has already dropped these inside the merge, so this is a
      // second pass over an array that is usually unchanged. It stays anyway: not
      // leaking a bar at or after the active frame is the invariant the whole
      // system exists to protect, and it must not depend on one caller passing
      // the right argument. The cost is one comparison per surviving bar.
      if (maxExclusive === null) return continuous;
      return continuous.filter((bar) => Number(bar.t) < maxExclusive);
    }

    await this._preloadDisplayHistory(cursor, resolution, historyRange);
    return super._causalDisplayWindow(cursor, resolution, historyRange);
  }

  async _broadcastDisplayWindow() {
    const cursor = Number(this.shard?.[this.session?.barIndex]?.t ?? this.session?.cursorTs);
    if (!Number.isFinite(cursor)) return;
    const bars = await this._causalDisplayWindow(cursor, this.displayResolution, this.historyRange);
    if (!bars.length) return;

    const base = {
      type: "display_window",
      resolution: this.displayResolution,
      history_range: this.historyRange,
      cursor,
      future_data_included: false,
    };
    if (bars.length <= DISPLAY_WINDOW_CHUNK_BARS) {
      this._broadcast({ ...base, bars });
      return;
    }

    this._fvDisplayTransferSequence = (Number(this._fvDisplayTransferSequence) || 0) + 1;
    const transferId = `${this.session?.id || "replay"}:${this._fvDisplayTransferSequence}`;
    const chunkCount = Math.ceil(bars.length / DISPLAY_WINDOW_CHUNK_BARS);
    for (let chunkIndex = 0; chunkIndex < chunkCount; chunkIndex += 1) {
      const start = chunkIndex * DISPLAY_WINDOW_CHUNK_BARS;
      this._broadcast({
        ...base,
        transfer_id: transferId,
        chunk_index: chunkIndex,
        chunk_count: chunkCount,
        total_bars: bars.length,
        bars: bars.slice(start, start + DISPLAY_WINDOW_CHUNK_BARS),
      });
    }
  }

  _consumeCanonicalBars(rawBars, resolution = this.displayResolution) {
    resolution = String(resolution || "1");
    const bars = rawBars || [];
    if (resolution === "1") {
      return bars.map((bar) => ({ ...bar, display_resolution: "1" }));
    }

    const completed = [];
    const interval = resolution === "1D" ? null : Number(resolution) * 60;

    for (const bar of bars) {
      const timestamp = Number(bar.t);
      if (!this.displayAggregate || this.displayAggregateResolution !== resolution) {
        completed.push(...super._consumeCanonicalBars([bar], resolution));
        continue;
      }

      if (resolution === "1D") {
        const rollover = Number(this.displayAggregate.t) + (18 * 60 * 60);
        if (timestamp >= rollover) {
          completed.push(...super._consumeCanonicalBars([bar], resolution));
        } else {
          addToAggregate(this.displayAggregate, bar);
          this.displayAggregateCursor = timestamp;
        }
        continue;
      }

      const frameStart = Number(this.displayAggregate.t);
      const frameEnd = frameStart + interval;
      if (timestamp < frameEnd) {
        addToAggregate(this.displayAggregate, bar);
        this.displayAggregateCursor = timestamp;
        continue;
      }

      const cursor = Number(this.displayAggregateCursor);
      const longGap = Number.isFinite(cursor) && (timestamp - cursor) > LONG_GAP_SECONDS;
      if (longGap || timestamp < frameStart) {
        completed.push(...super._consumeCanonicalBars([bar], resolution));
        continue;
      }

      completed.push(completedBar(this.displayAggregate, resolution));
      const frameSteps = Math.max(1, Math.floor((timestamp - frameStart) / interval));
      this.displayAggregate = newAggregate(bar, frameStart + frameSteps * interval);
      this.displayAggregateResolution = resolution;
      this.displayAggregateCursor = timestamp;
    }

    return completed;
  }

  async stepFrame(value) {
    if (!this.session) throw new Error("Session not initialized");
    if (this.session.state === "PLAYING") throw new Error("Pause before stepping");

    const timeframe = String(value || this.displayResolution || "1");
    if (!FRAME_RESOLUTIONS.has(timeframe)) throw new Error(`Unsupported chart timeframe ${timeframe}`);
    if (timeframe !== String(this.displayResolution || "1")) {
      return super.stepFrame(value);
    }

    const current = await this._ensureReplayCursor();

    if (timeframe === "1D") {
      await this._ensureDisplayAggregate();
      const nextIndex = Number(this.session.barIndex) + 1;
      const next = this.shard?.[nextIndex] ?? await this._peekNextReplayBar();
      if (!next) {
        this.session.state = "FINISHED";
        await this._persist(false);
        this._broadcast(this.snapshot());
        return;
      }

      const currentTime = Number(current.t);
      const nextTime = Number(next.t);
      const dailyStamp = Number(this.displayAggregate?.t);
      if (
        !Number.isFinite(currentTime) ||
        !Number.isFinite(nextTime) ||
        !Number.isFinite(dailyStamp) ||
        (nextTime - currentTime) > LONG_GAP_SECONDS
      ) {
        return super.stepFrame(value);
      }

      const currentRollover = dailyStamp + 18 * 60 * 60;
      const targetEnd = nextTime < currentRollover
        ? currentRollover
        : dailyStamp + 24 * 60 * 60 + 18 * 60 * 60;
      const released = await this._releaseUntilBefore(targetEnd, 2000);
      if (released.length) {
        const last = released.at(-1);
        this.session.cursorTs = Number(last.t);
        if (Number(last.t) >= this.displayNextCheckAt) await this._ensureDisplayWindows(last.t);
        this._consumeCanonicalBars(released, "1D");
        this._broadcastDisplayBars([
          { ...this.displayAggregate, display_resolution: "1D" },
        ], "1D");
      }
      await this._persist(false);
      this._broadcast(this.snapshot());
      return;
    }

    if (timeframe === "1") {
      const released = await this._release(1);
      if (released.length) {
        this.session.cursorTs = Number(released.at(-1).t);
        this._consumeCanonicalBars(released, "1");
        this._broadcastDisplayBars([{ ...released.at(-1), display_resolution: "1" }], "1");
      }
      await this._persist(false);
      this._broadcast(this.snapshot());
      return;
    }

    await this._ensureDisplayAggregate();
    const nextIndex = Number(this.session.barIndex) + 1;
    const next = this.shard?.[nextIndex];
    if (!next || !this.displayAggregate) return super.stepFrame(value);

    const currentTime = Number(current.t);
    const nextTime = Number(next.t);
    if (!Number.isFinite(currentTime) || !Number.isFinite(nextTime) || (nextTime - currentTime) > LONG_GAP_SECONDS) {
      return super.stepFrame(value);
    }

    const interval = Number(timeframe) * 60;
    const aggregateStart = Number(this.displayAggregate.t);
    if (!Number.isFinite(interval) || !Number.isFinite(aggregateStart) || interval <= 0) {
      return super.stepFrame(value);
    }

    const currentFrameEnd = aggregateStart + interval;
    const targetStart = nextTime < currentFrameEnd
      ? aggregateStart
      : aggregateStart + Math.max(1, Math.floor((nextTime - aggregateStart) / interval)) * interval;
    const targetEnd = targetStart + interval;

    const lastCurrentShardTime = Number(this.shard?.at(-1)?.t);
    if (!Number.isFinite(lastCurrentShardTime)) return super.stepFrame(value);
    if (targetEnd > lastCurrentShardTime) {
      const contract = this.manifest?.contracts?.[this.session.contract];
      const nextMeta = contract?.shards?.[Number(this.session.shardIndex) + 1];
      if (nextMeta && Number(nextMeta.first_time) < targetEnd) return super.stepFrame(value);
    }

    const endIndex = lowerBoundBarTime(this.shard, targetEnd, nextIndex);
    const count = endIndex - nextIndex;
    if (count <= 0 || count > 2000) return super.stepFrame(value);

    const released = await this._release(count);
    if (released.length) {
      this.session.cursorTs = Number(released.at(-1).t);
      this._consumeCanonicalBars(released, timeframe);
      this._broadcastDisplayBars([
        { ...this.displayAggregate, display_resolution: timeframe },
      ], timeframe);
    }
    await this._persist(false);
    this._broadcast(this.snapshot());
  }
}
