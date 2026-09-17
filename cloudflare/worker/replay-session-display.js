import { ReplaySession as FrameReplaySession } from "./replay-session-frame.js";

const FRAME_RESOLUTIONS = new Set(["1", "5", "30", "240", "1D"]);
const HISTORY_SECONDS = { "1D": 86400, "5D": 5 * 86400, "1M": 30 * 86400, "3M": 90 * 86400 };
const MAX_PARTIAL_MINUTES = 1500;
const ET_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function etParts(seconds) {
  return Object.fromEntries(
    ET_FORMATTER.formatToParts(new Date(Number(seconds) * 1000))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
}

function wallToEpochSeconds(parts) {
  const wanted = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second || 0);
  let guess = wanted;
  for (let i = 0; i < 4; i += 1) {
    const shown = etParts(guess / 1000);
    const shownWall = Date.UTC(shown.year, shown.month - 1, shown.day, shown.hour, shown.minute, shown.second || 0);
    const delta = wanted - shownWall;
    guess += delta;
    if (!delta) break;
  }
  return Math.floor(guess / 1000);
}

function sessionStart(seconds) {
  const parts = etParts(seconds);
  const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour < 18) day.setUTCDate(day.getUTCDate() - 1);
  return wallToEpochSeconds({
    year: day.getUTCFullYear(),
    month: day.getUTCMonth() + 1,
    day: day.getUTCDate(),
    hour: 18,
    minute: 0,
    second: 0,
  });
}

function tradingDayDate(seconds) {
  const parts = etParts(seconds);
  const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour >= 18) day.setUTCDate(day.getUTCDate() + 1);
  return day;
}

function dailyTradingStamp(seconds) {
  const day = tradingDayDate(seconds);
  return wallToEpochSeconds({
    year: day.getUTCFullYear(),
    month: day.getUTCMonth() + 1,
    day: day.getUTCDate(),
    hour: 0,
    minute: 0,
    second: 0,
  });
}

function activeTradingDayKey(seconds) {
  const day = tradingDayDate(seconds);
  return day.getUTCFullYear() * 10000 + (day.getUTCMonth() + 1) * 100 + day.getUTCDate();
}

function dailyBarTradingDayKey(seconds) {
  // Both legacy 00:00-UTC bars and corrected 00:00-ET bars have the intended
  // trading-day calendar date in their UTC Y/M/D fields.
  const day = new Date(Number(seconds) * 1000);
  return day.getUTCFullYear() * 10000 + (day.getUTCMonth() + 1) * 100 + day.getUTCDate();
}

function displayStamp(seconds, resolution) {
  if (resolution === "1") return Number(seconds);
  if (resolution === "1D") return dailyTradingStamp(seconds);
  const start = sessionStart(seconds);
  const minutes = Number(resolution);
  return start + Math.floor(Math.max(0, Number(seconds) - start) / (minutes * 60)) * minutes * 60;
}

function lowerBoundShard(shards, target) {
  let lo = 0;
  let hi = shards.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(shards[mid].last_time) >= Number(target)) hi = mid;
    else lo = mid + 1;
  }
  return lo < shards.length ? lo : Math.max(0, shards.length - 1);
}

function lowerBoundLastTime(items, target) {
  let lo = 0;
  let hi = items.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(items[mid].last_time) >= Number(target)) hi = mid;
    else lo = mid + 1;
  }
  return lo < items.length ? lo : Math.max(0, items.length - 1);
}

function lowerBoundBarTime(items, target) {
  let lo = 0;
  let hi = items.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(items[mid].t) >= Number(target)) hi = mid;
    else lo = mid + 1;
  }
  return lo < items.length ? lo : Math.max(0, items.length - 1);
}

function indexAtOrBefore(bars, target) {
  let lo = 0;
  let hi = bars.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(bars[mid].t) <= Number(target)) lo = mid + 1;
    else hi = mid;
  }
  return Math.max(0, Math.min(bars.length - 1, lo - 1));
}

function newAggregate(bar, resolution) {
  return {
    t: displayStamp(bar.t, resolution),
    o: Number(bar.o),
    h: Number(bar.h),
    l: Number(bar.l),
    c: Number(bar.c),
    v: Number(bar.v) || 0,
  };
}

function addToAggregate(aggregate, bar) {
  aggregate.h = Math.max(aggregate.h, Number(bar.h));
  aggregate.l = Math.min(aggregate.l, Number(bar.l));
  aggregate.c = Number(bar.c);
  aggregate.v += Number(bar.v) || 0;
}

function displayBar(aggregate, resolution) {
  return aggregate ? { ...aggregate, display_resolution: resolution } : null;
}

export class ReplaySession extends FrameReplaySession {
  constructor(ctx, env) {
    super(ctx, env);
    this.displayAggregate = null;
    this.displayAggregateResolution = null;
    this.displayAggregateCursor = null;
  }

  async _ensureReplayCursor() {
    if (!this.session) throw new Error("Session not initialized");
    const manifest = await this._manifest();
    const contract = manifest.contracts?.[this.session.contract];
    const shards = contract?.shards || [];
    if (!shards.length) throw new Error("Replay contract has no canonical data");

    let shardIndex = Number(this.session.shardIndex);
    let repaired = false;
    if (!Number.isInteger(shardIndex) || shardIndex < 0 || shardIndex >= shards.length) {
      const target = Number(this.session.cursorTs ?? this.session.startTs ?? shards[0].first_time);
      shardIndex = lowerBoundShard(shards, target);
      this.session.shardIndex = shardIndex;
      repaired = true;
    }

    let shard = await this._loadShard(shardIndex);
    if (!shard?.length) throw new Error("Replay canonical shard is empty");

    let barIndex = Number(this.session.barIndex);
    if (!Number.isInteger(barIndex) || barIndex < 0 || barIndex >= shard.length) {
      const cursorTs = Number(this.session.cursorTs);
      if (Number.isFinite(cursorTs)) {
        const targetShard = lowerBoundShard(shards, cursorTs);
        if (targetShard !== shardIndex) {
          shardIndex = targetShard;
          this.session.shardIndex = shardIndex;
          shard = await this._loadShard(shardIndex);
        }
        barIndex = indexAtOrBefore(shard, cursorTs);
      } else if (Number.isInteger(barIndex) && barIndex >= shard.length) {
        barIndex = shard.length - 1;
      } else {
        const target = Number(this.session.startTs ?? shard[0].t);
        barIndex = indexAtOrBefore(shard, target);
      }
      this.session.barIndex = barIndex;
      repaired = true;
    }

    const bar = shard[barIndex];
    if (!bar) throw new Error("Replay cursor could not be restored");
    if (Number(this.session.cursorTs) !== Number(bar.t)) {
      this.session.cursorTs = Number(bar.t);
      repaired = true;
    }
    if (repaired) await this.ctx.storage.put("session", this.session);
    return bar;
  }

  async webSocketMessage(ws, message) {
    try {
      const command = JSON.parse(typeof message === "string" ? message : new TextDecoder().decode(message));
      if (command?.type && command.type !== "set_history_range") await this._ensureReplayCursor();
    } catch {}
    return super.webSocketMessage(ws, message);
  }

  _resetDisplayAggregate() {
    this.displayAggregate = null;
    this.displayAggregateResolution = null;
    this.displayAggregateCursor = null;
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
    const stamp = displayStamp(current.t, resolution);
    let aggregate = null;
    for (const bar of warmup) {
      if (displayStamp(bar.t, resolution) !== stamp) continue;
      if (!aggregate) aggregate = newAggregate(bar, resolution);
      else addToAggregate(aggregate, bar);
    }
    this.displayAggregate = aggregate || newAggregate(current, resolution);
    this.displayAggregateResolution = resolution;
    this.displayAggregateCursor = Number(current.t);
  }

  _consumeCanonicalBars(rawBars, resolution = this.displayResolution) {
    resolution = String(resolution || "1");
    if (resolution === "1") return (rawBars || []).map((bar) => ({ ...bar, display_resolution: "1" }));
    const completed = [];
    for (const bar of rawBars || []) {
      const stamp = displayStamp(bar.t, resolution);
      if (!this.displayAggregate || this.displayAggregateResolution !== resolution) {
        this.displayAggregate = newAggregate(bar, resolution);
        this.displayAggregateResolution = resolution;
      } else if (this.displayAggregate.t !== stamp) {
        completed.push(displayBar(this.displayAggregate, resolution));
        this.displayAggregate = newAggregate(bar, resolution);
      } else {
        addToAggregate(this.displayAggregate, bar);
      }
      this.displayAggregateCursor = Number(bar.t);
    }
    return completed;
  }

  _broadcastDisplayBars(bars, resolution = this.displayResolution) {
    if (!bars?.length) return;
    if (String(resolution) === "1") {
      const raw = bars.map(({ display_resolution, ...bar }) => bar);
      if (raw.length === 1) this._broadcast({ type: "bar", bar: raw[0] });
      else this._broadcast({ type: "bars_batch", bars: raw });
      return;
    }
    const payload = bars.map((bar) => ({ ...bar, display_resolution: String(resolution) }));
    if (payload.length === 1) this._broadcast({ type: "bar", bar: payload[0] });
    else this._broadcast({ type: "bars_batch", bars: payload });
  }

  async _causalDisplayWindow(cursor, resolution = this.displayResolution, historyRange = this.historyRange) {
    cursor = Number(cursor);
    if (!Number.isFinite(cursor)) return [];
    await this._ensureDisplayWindows(cursor);
    const center = this.displayWindowIndex;
    if (center < 0) return [];

    const seconds = HISTORY_SECONDS[historyRange] ?? HISTORY_SECONDS["5D"];
    const historyFrom = cursor - seconds;
    const shards = await this._displayShardMeta(resolution);
    if (!shards.length) return [];
    const firstNeeded = Math.max(0, Math.min(center, lowerBoundLastTime(shards, historyFrom)));
    const out = [];
    const cutoff = resolution === "1D" ? null : displayStamp(cursor, resolution);
    const activeDay = resolution === "1D" ? activeTradingDayKey(cursor) : null;

    for (let index = firstNeeded; index <= center; index += 1) {
      const cacheKey = `${resolution}:${index}`;\n      const window = this.displayWindows?.get(cacheKey) ?? await this._loadDisplayWindow(index, resolution);
      if (!window) continue;
      const bars = window.bars || [];
      let start = lowerBoundBarTime(bars, historyFrom);
      if (start < 0) start = 0;
      for (let i = start; i < bars.length; i += 1) {
        const bar = bars[i];
        const t = Number(bar.t);
        if (resolution === "1D") {
          if (dailyBarTradingDayKey(t) >= activeDay) break;
        } else if (t >= cutoff) {
          break;
        }
        if (t >= historyFrom) out.push(bar);
      }
    }

    this._trimDisplayWindows(center, resolution);
    return out;
  }

  async setTimeframe(value, historyRange = this.historyRange) {
    this._resetDisplayAggregate();
    await super.setTimeframe(value, historyRange);
    await this._ensureDisplayAggregate();
  }

  async restart() {
    this._resetDisplayAggregate();
    await super.restart();
    const current = await this._ensureReplayCursor();
    this.session.cursorTs = Number(current.t);
    await this.ctx.storage.put("session", this.session);
  }

  async _tick(generation) {
    if (!this.session || generation !== this.generation || this.session.state !== "PLAYING") return;
    await this._ensureReplayCursor();
    await this._ensureDisplayAggregate();

    const now = Date.now();
    const elapsed = Math.max(0, (now - this.lastTick) / 1000);
    this.lastTick = now;
    let due;
    if (this.session.speed === "max") {
      due = this._tickDelayMs() >= 100 ? 500 : 250;
    } else {
      this.credit += elapsed * Number(this.session.speed);
      due = Math.floor(this.credit);
      this.credit -= due;
    }

    if (due > 0) {
      const rawBars = await super._release(due);
      if (rawBars.length) {
        this.session.cursorTs = Number(rawBars.at(-1).t);
        const displayBars = this._consumeCanonicalBars(rawBars, this.displayResolution);
        this._broadcastDisplayBars(displayBars, this.displayResolution);
      }
      this.ticks += 1;
      if (this.ticks % 20 === 0 || this.session.state === "FINISHED") {
        await this._persist(this.session.state === "FINISHED");
      }
    }

    if (this.session.state === "FINISHED") {
      this._broadcast(this.snapshot());
      return;
    }
    this._schedule(generation);
  }

  async stepFrame(value) {
    if (!this.session) throw new Error("Session not initialized");
    if (this.session.state === "PLAYING") throw new Error("Pause before stepping");

    const timeframe = String(value || this.displayResolution || "1");
    if (!FRAME_RESOLUTIONS.has(timeframe)) throw new Error(`Unsupported chart timeframe ${timeframe}`);
    if (timeframe !== this.displayResolution) await this.setTimeframe(timeframe, this.historyRange);

    const current = await this._ensureReplayCursor();
    await this._ensureDisplayAggregate();
    const next = await this._peekNextReplayBar();
    if (!next) {
      this.session.state = "FINISHED";
      await this._persist(false);
      this._broadcast(this.snapshot());
      return;
    }

    const currentStamp = displayStamp(current.t, timeframe);
    const nextStamp = displayStamp(next.t, timeframe);
    const targetStamp = nextStamp === currentStamp ? currentStamp : nextStamp;
    const released = [];

    while (this.session.state !== "FINISHED") {
      const upcoming = await this._peekNextReplayBar();
      if (!upcoming || displayStamp(upcoming.t, timeframe) !== targetStamp) break;
      const bars = await super._release(1);
      if (!bars.length) break;
      released.push(bars[0]);
      if (released.length > 2000) throw new Error("Chart-frame step exceeded safety bound");
    }

    if (released.length) {
      this.session.cursorTs = Number(released.at(-1).t);
      this._consumeCanonicalBars(released, timeframe);
      const shown = timeframe === "1"
        ? [{ ...released.at(-1), display_resolution: "1" }]
        : [displayBar(this.displayAggregate, timeframe)];
      this._broadcastDisplayBars(shown, timeframe);
    }
    await this._persist(false);
    this._broadcast(this.snapshot());
  }
}
