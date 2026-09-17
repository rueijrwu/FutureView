import { ReplaySession as DisplayReplaySession } from "./replay-session-display.js";

const FRAME_RESOLUTIONS = new Set(["1", "5", "30", "240", "1D"]);
const LONG_GAP_SECONDS = 6 * 60 * 60;
const PREFETCH_THRESHOLD = 0.75;
const MAX_PARTIAL_MINUTES = 1500;
const HISTORY_SECONDS = { "1D": 86400, "5D": 5 * 86400, "1M": 30 * 86400, "3M": 90 * 86400 };
const HISTORY_LOAD_CONCURRENCY = 4;

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

export class ReplaySession extends DisplayReplaySession {
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
    await this._preloadDisplayHistory(cursor, resolution, historyRange);
    return super._causalDisplayWindow(cursor, resolution, historyRange);
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
    if (timeframe !== String(this.displayResolution || "1") || timeframe === "1D") {
      return super.stepFrame(value);
    }

    const current = await this._ensureReplayCursor();

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
