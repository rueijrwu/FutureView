import { ReplaySession as FrameReplaySession } from "./replay-session-frame.js";
import { FRAME_RESOLUTIONS, displayStamp } from "./replay-time.js";

const MAX_PARTIAL_MINUTES = 1500;

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

function indexAtOrBefore(bars, target) {
  let lo = 0;
  let hi = bars.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(bars[mid].t) <= Number(target)) lo = mid + 1;
    else hi = mid;
  }
  return lo - 1;
}

function indexAtOrAfter(bars, target) {
  let lo = 0;
  let hi = bars.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(bars[mid].t) >= Number(target)) hi = mid;
    else lo = mid + 1;
  }
  return lo < bars.length ? lo : -1;
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
  return aggregate ? { ...aggregate, display_resolution: String(resolution) } : null;
}

export class ReplaySession extends FrameReplaySession {
  constructor(ctx, env) {
    super(ctx, env);
    this.displayAggregate = null;
    this.displayAggregateResolution = null;
    this.displayAggregateCursor = null;
    this.displayAggregatePublishedStamp = null;
  }

  snapshot() {
    const value = super.snapshot();
    if (this.session && Number.isFinite(Number(this.session.cursorTs))) {
      value.cursor = Number(this.session.cursorTs);
    }
    return value;
  }

  async init(body) {
    const result = await super.init(body);
    const current = this.shard?.[this.session?.barIndex];
    if (current) {
      this.session.cursorTs = Number(current.t);
      this.session.originCursorTs = Number(current.t);
      await this.ctx.storage.put("session", this.session);
      result.cursor = Number(current.t);
    }
    return result;
  }

  async _locateAtOrBefore(target) {
    const manifest = await this._manifest();
    const shards = manifest.contracts?.[this.session.contract]?.shards || [];
    if (!shards.length) throw new Error("Replay contract has no canonical data");
    let shardIndex = lowerBoundShard(shards, target);
    let shard = await this._loadShard(shardIndex);
    if (!shard?.length) throw new Error("Replay canonical shard is empty");
    let barIndex = indexAtOrBefore(shard, target);
    if (barIndex < 0 && shardIndex > 0) {
      shardIndex -= 1;
      shard = await this._loadShard(shardIndex);
      barIndex = shard.length - 1;
    }
    if (barIndex < 0) barIndex = 0;
    return { shardIndex, barIndex, shard, bar: shard[barIndex] };
  }

  async _locateAtOrAfter(target) {
    const manifest = await this._manifest();
    const shards = manifest.contracts?.[this.session.contract]?.shards || [];
    if (!shards.length) throw new Error("Replay contract has no canonical data");
    let shardIndex = lowerBoundShard(shards, target);
    let shard = await this._loadShard(shardIndex);
    if (!shard?.length) throw new Error("Replay canonical shard is empty");
    let barIndex = indexAtOrAfter(shard, target);
    while (barIndex < 0 && shardIndex + 1 < shards.length) {
      shardIndex += 1;
      shard = await this._loadShard(shardIndex);
      barIndex = shard.length ? 0 : -1;
    }
    if (barIndex < 0) throw new Error("Replay cursor is beyond available data");
    return { shardIndex, barIndex, shard, bar: shard[barIndex] };
  }

  async _ensureReplayCursor() {
    if (!this.session) throw new Error("Session not initialized");
    const target = Number(this.session.cursorTs);

    const shard = await this._loadShard(Number(this.session.shardIndex));
    const current = shard?.[Number(this.session.barIndex)];
    if (current && (!Number.isFinite(target) || Number(current.t) === target)) {
      if (!Number.isFinite(target)) {
        this.session.cursorTs = Number(current.t);
        if (!Number.isFinite(Number(this.session.originCursorTs))) this.session.originCursorTs = Number(current.t);
        await this.ctx.storage.put("session", this.session);
      }
      return current;
    }

    const restoreTarget = Number.isFinite(target)
      ? target
      : Number(this.session.startTs);
    const located = await this._locateAtOrBefore(restoreTarget);
    this.session.shardIndex = located.shardIndex;
    this.session.barIndex = located.barIndex;
    this.session.cursorTs = Number(located.bar.t);
    this.shard = located.shard;
    const contract = (await this._manifest()).contracts[this.session.contract];
    this.shardKey = contract.shards[located.shardIndex]?.key ?? this.shardKey;
    await this.ctx.storage.put("session", this.session);
    return located.bar;
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
    this.displayAggregatePublishedStamp = null;
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
    this.displayAggregatePublishedStamp = null;
  }

  _consumeCanonicalBars(rawBars, resolution = this.displayResolution) {
    resolution = String(resolution || "1");
    if (resolution === "1") {
      return (rawBars || []).map((bar) => ({ ...bar, display_resolution: "1" }));
    }

    const completed = [];
    for (const bar of rawBars || []) {
      const stamp = displayStamp(bar.t, resolution);
      if (!this.displayAggregate || this.displayAggregateResolution !== resolution) {
        this.displayAggregate = newAggregate(bar, resolution);
        this.displayAggregateResolution = resolution;
        this.displayAggregatePublishedStamp = null;
      } else if (this.displayAggregate.t !== stamp) {
        if (this.displayAggregatePublishedStamp !== this.displayAggregate.t) {
          completed.push(displayBar(this.displayAggregate, resolution));
          this.displayAggregatePublishedStamp = this.displayAggregate.t;
        }
        this.displayAggregate = newAggregate(bar, resolution);
        this.displayAggregatePublishedStamp = null;
      } else {
        addToAggregate(this.displayAggregate, bar);
      }
      this.displayAggregateCursor = Number(bar.t);
    }
    return completed;
  }

  async _finalizeAggregateIfComplete(completed, resolution = this.displayResolution) {
    resolution = String(resolution || "1");
    if (resolution === "1" || !this.displayAggregate) return completed;
    const next = await this._peekNextReplayBar();
    const complete = !next || displayStamp(next.t, resolution) !== this.displayAggregate.t;
    if (complete && this.displayAggregatePublishedStamp !== this.displayAggregate.t) {
      completed.push(displayBar(this.displayAggregate, resolution));
      this.displayAggregatePublishedStamp = this.displayAggregate.t;
    }
    return completed;
  }

  _broadcastDisplayBars(bars, resolution = this.displayResolution, cursor = this.session?.cursorTs) {
    if (!bars?.length) return;
    const replayCursor = Number(cursor);
    if (String(resolution) === "1") {
      const raw = bars.map(({ display_resolution, ...bar }) => bar);
      if (raw.length === 1) this._broadcast({ type: "bar", bar: raw[0], cursor: replayCursor });
      else this._broadcast({ type: "bars_batch", bars: raw, cursor: replayCursor });
      return;
    }
    const payload = bars.map((bar) => ({ ...bar, display_resolution: String(resolution) }));
    if (payload.length === 1) this._broadcast({ type: "bar", bar: payload[0], cursor: replayCursor });
    else this._broadcast({ type: "bars_batch", bars: payload, cursor: replayCursor });
  }

  async setTimeframe(value, historyRange = this.historyRange) {
    this._resetDisplayAggregate();
    await super.setTimeframe(value, historyRange);
    await this._ensureDisplayAggregate();
  }

  async restart() {
    if (!this.session) return;
    this.generation += 1;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this._resetDisplayCursor();
    this._resetDisplayAggregate();

    const target = Number(this.session.originCursorTs ?? this.session.startTs);
    const located = await this._locateAtOrAfter(target);
    this.session.shardIndex = located.shardIndex;
    this.session.barIndex = located.barIndex;
    this.session.originShardIndex = located.shardIndex;
    this.session.originBarIndex = located.barIndex;
    this.session.cursorTs = Number(located.bar.t);
    this.session.originCursorTs = Number(located.bar.t);
    this.session.state = "PAUSED";
    this.session.speed = 1;
    this.session.trading = this._blankTrading(located.bar.c ?? located.bar.o ?? null);
    this.shard = located.shard;
    const contract = (await this._manifest()).contracts[this.session.contract];
    this.shardKey = contract.shards[located.shardIndex]?.key ?? null;

    const warmup = await this._warmupBars(located.shardIndex, located.barIndex, this.session.warmup);
    await this._clearPersistedTrading();
    await this._persist(true);
    await this._persistTradingSummary();
    this._broadcast({ type: "reset", warmup, snapshot: this.snapshot() });
    await this._broadcastDisplayWindow();
    await this._ensureDisplayAggregate();
  }

  async _release(count) {
    const contract = (await this._manifest()).contracts[this.session.contract];
    const released = [];
    while (released.length < count) {
      const item = contract.shards[this.session.shardIndex];
      if (!item) {
        this.session.state = "FINISHED";
        break;
      }
      if (!this.shard || this.shardKey !== item.key) await this._loadShard(this.session.shardIndex);

      if (this.session.barIndex + 1 < this.shard.length) {
        this.session.barIndex += 1;
        const bar = this.shard[this.session.barIndex];
        if (this._trading().pendingOrders.length) await this._fillPendingOrders(bar);
        this._trading().lastPrice = bar.c;
        this.session.cursorTs = Number(bar.t);
        released.push(bar);
        continue;
      }

      if (this.session.shardIndex + 1 >= contract.shards.length) {
        this.session.state = "FINISHED";
        break;
      }
      this.session.shardIndex += 1;
      this.session.barIndex = -1;
      this.shard = null;
      this.shardKey = null;
    }

    if (released.length && Number(released.at(-1).t) >= this.displayNextCheckAt) {
      await this._ensureDisplayWindows(released.at(-1).t);
    }
    return released;
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
      const rawBars = await this._release(due);
      if (rawBars.length) {
        let displayBars = this._consumeCanonicalBars(rawBars, this.displayResolution);
        displayBars = await this._finalizeAggregateIfComplete(displayBars, this.displayResolution);
        this._broadcastDisplayBars(displayBars, this.displayResolution, this.session.cursorTs);
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
      const bars = await this._release(1);
      if (!bars.length) break;
      released.push(bars[0]);
      if (released.length > 2000) throw new Error("Chart-frame step exceeded safety bound");
    }

    if (released.length) {
      let shown = this._consumeCanonicalBars(released, timeframe);
      shown = await this._finalizeAggregateIfComplete(shown, timeframe);
      this._broadcastDisplayBars(shown, timeframe, this.session.cursorTs);
    }
    await this._persist(false);
    this._broadcast(this.snapshot());
  }
}
