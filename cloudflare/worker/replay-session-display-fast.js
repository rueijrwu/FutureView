import { ReplaySession as DisplayReplaySession } from "./replay-session-display.js";

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
}
