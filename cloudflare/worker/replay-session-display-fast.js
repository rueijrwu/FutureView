import { ReplaySession as DisplayReplaySession } from "./replay-session-display.js";

const FRAME_RESOLUTIONS = new Set(["1", "5", "30", "240", "1D"]);
const LONG_GAP_SECONDS = 6 * 60 * 60;

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

export class ReplaySession extends DisplayReplaySession {
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
        // The active trading-day candle is stamped at midnight ET and rolls at 18:00 ET.
        // DST transitions occur while CME equity futures are closed, so the active day's
        // midnight and 18:00 boundary share the same UTC offset. Weekend/session gaps still
        // delegate to the existing timezone-aware implementation when the rollover is crossed.
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
        // Holidays/weekends/DST boundaries are infrequent. Use the original ET calculation
        // for the first bar after such a gap, then return to the arithmetic hot path.
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
