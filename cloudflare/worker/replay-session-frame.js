import { ReplaySession as BaseReplaySession } from "./replay-session.js";
import {
  FRAME_RESOLUTIONS,
  dailyBarTradingDayKey,
  displayStamp,
  frameKey,
  tradingDayKey,
} from "./replay-time.js";

const SPEEDS = new Set([1, 5, 10, 25, 50, 100]);
const HISTORY_SECONDS = { "1D": 86400, "5D": 5 * 86400, "1M": 30 * 86400, "3M": 90 * 86400 };
const DISPLAY_WINDOW_BARS = 512;
const PREFETCH_THRESHOLD = 0.75;

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

function lowerBoundBarTime(items, target) {
  let lo = 0;
  let hi = items.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Number(items[mid].t) >= Number(target)) hi = mid;
    else lo = mid + 1;
  }
  return lo < items.length ? lo : items.length - 1;
}

export class ReplaySession extends BaseReplaySession {
  constructor(ctx, env) {
    super(ctx, env);
    this.displayResolution = "5";
    this.historyRange = "5D";
    this.displayWindowIndex = -1;
    this.displayWindows = new Map();
    this.displayShardMeta = new Map();
    this.displayPrefetchAt = -Infinity;
    this.displayPrefetchedIndex = -1;
    this.displayNextCheckAt = -Infinity;
  }

  async webSocketMessage(ws, message) {
    let command;
    try {
      command = JSON.parse(typeof message === "string" ? message : new TextDecoder().decode(message));
    } catch {
      return super.webSocketMessage(ws, message);
    }

    try {
      if (command.type === "step_frame") await this.stepFrame(command.timeframe);
      else if (command.type === "set_speed") await this.setSpeed(command.speed);
      else if (command.type === "set_timeframe") await this.setTimeframe(command.timeframe, command.history_range);
      else if (command.type === "set_history_range") await this.setHistoryRange(command.history_range);
      else return super.webSocketMessage(ws, message);
    } catch (error) {
      ws.send(JSON.stringify({ type: "error", error: String(error?.message ?? error) }));
    }
  }

  async _displayShardMeta(resolution = this.displayResolution) {
    const key = `${this.session?.contract || ""}:${resolution}`;
    if (this.displayShardMeta.has(key)) return this.displayShardMeta.get(key);
    const manifest = await this._manifest();
    const contract = manifest.contracts?.[this.session.contract];
    let value = contract?.display_shards?.[resolution] ?? [];
    // Manifest v6 used "1m" while v7 uses TradingView's canonical "1" resolution.
    if (!value.length && resolution === "1") value = contract?.display_shards?.["1m"] ?? contract?.shards ?? [];
    this.displayShardMeta.set(key, value);
    return value;
  }

  async _loadDisplayWindow(index, resolution = this.displayResolution) {
    if (index < 0) return null;
    const key = `${resolution}:${index}`;
    if (this.displayWindows.has(key)) return this.displayWindows.get(key);
    const shards = await this._displayShardMeta(resolution);
    const meta = shards[index];
    if (!meta) return null;
    const prefix = this._getPrefix();
    const object = await this.env.MES_DATA.get(`${prefix}/${meta.key}`);
    if (!object) throw new Error(`Missing display cache ${meta.key}`);
    const stream = meta.key.endsWith(".gz") ? object.body.pipeThrough(new DecompressionStream("gzip")) : object.body;
    const bars = JSON.parse(await new Response(stream).text());
    const value = { index, meta, bars };
    this.displayWindows.set(key, value);
    return value;
  }

  _resetDisplayCursor() {
    this.displayWindowIndex = -1;
    this.displayPrefetchAt = -Infinity;
    this.displayPrefetchedIndex = -1;
    this.displayNextCheckAt = -Infinity;
  }

  _trimDisplayWindows(centerIndex, resolution = this.displayResolution) {
    const keepIndices = resolution === "1"
      ? [centerIndex - 1, centerIndex]
      : [centerIndex - 1, centerIndex, centerIndex + 1, centerIndex + 2];
    const keep = new Set(keepIndices.map((index) => `${resolution}:${index}`));
    for (const key of [...this.displayWindows.keys()]) {
      if (key.startsWith(`${resolution}:`) && !keep.has(key)) this.displayWindows.delete(key);
      else if (!key.startsWith(`${resolution}:`)) this.displayWindows.delete(key);
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

    const current = await this._loadDisplayWindow(index, resolution);
    if (!current) return;
    const bars = current.bars || [];
    if (resolution !== "1") await this._loadDisplayWindow(index + 1, resolution);

    if (bars.length && !Number.isFinite(this.displayPrefetchAt)) {
      const thresholdIndex = Math.min(bars.length - 1, Math.floor((bars.length - 1) * PREFETCH_THRESHOLD));
      this.displayPrefetchAt = Number(bars[thresholdIndex].t);
    }

    if (
      resolution !== "1" &&
      cursor >= this.displayPrefetchAt &&
      this.displayPrefetchedIndex !== index + 2
    ) {
      await this._loadDisplayWindow(index + 2, resolution);
      this.displayPrefetchedIndex = index + 2;
    }

    const edge = Number(current.meta.last_time) + 1;
    this.displayNextCheckAt = resolution === "1" || this.displayPrefetchedIndex === index + 2
      ? edge
      : Math.min(edge, this.displayPrefetchAt);
    this._trimDisplayWindows(index, resolution);
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
    const activeDay = resolution === "1D" ? tradingDayKey(cursor) : null;

    for (let index = firstNeeded; index <= center; index += 1) {
      const window = await this._loadDisplayWindow(index, resolution);
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

  async _broadcastDisplayWindow() {
    const cursor = this.shard?.[this.session?.barIndex]?.t;
    const bars = await this._causalDisplayWindow(cursor, this.displayResolution, this.historyRange);
    if (bars.length) {
      this._broadcast({
        type: "display_window",
        resolution: this.displayResolution,
        history_range: this.historyRange,
        bars,
        cursor,
        future_data_included: false,
      });
    }
  }

  async setTimeframe(value, historyRange = this.historyRange) {
    const timeframe = String(value || "5");
    if (!FRAME_RESOLUTIONS.has(timeframe)) throw new Error(`Unsupported chart timeframe ${timeframe}`);
    if (historyRange != null && !HISTORY_SECONDS[String(historyRange)]) throw new Error(`Unsupported history range ${historyRange}`);
    this.displayResolution = timeframe;
    if (historyRange != null) this.historyRange = String(historyRange);
    this._resetDisplayCursor();
    await this._broadcastDisplayWindow();
    this._broadcast({
      ...this.snapshot(),
      display_resolution: this.displayResolution,
      history_range: this.historyRange,
      display_cache: {
        window_bars: DISPLAY_WINDOW_BARS,
        current_window: this.displayWindowIndex,
      },
    });
  }

  async setHistoryRange(value) {
    const range = String(value || "5D");
    if (!HISTORY_SECONDS[range]) throw new Error(`Unsupported history range ${range}`);
    this.historyRange = range;
    await this._broadcastDisplayWindow();
  }

  async restart() {
    this._resetDisplayCursor();
    await super.restart();
    await this._broadcastDisplayWindow();
  }

  async setSpeed(value) {
    if (!this.session) throw new Error("Session not initialized");
    let speed = value;
    if (String(value).toLowerCase() === "max") speed = "max";
    else {
      speed = Number(value);
      if (!SPEEDS.has(speed)) throw new Error("Invalid replay speed");
    }

    if (this.session.state === "PLAYING") {
      const now = Date.now();
      const oldSpeed = this.session.speed;
      if (oldSpeed !== "max" && speed !== "max") {
        this.credit += Math.max(0, (now - this.lastTick) / 1000) * Number(oldSpeed);
      } else {
        this.credit = 0;
      }
      this.lastTick = now;
    }
    this.session.speed = speed;
    await this.ctx.storage.put("session", this.session);
    this._broadcast(this.snapshot());
  }

  async _release(count) {
    const bars = await super._release(count);
    if (bars.length && Number(bars.at(-1).t) >= this.displayNextCheckAt) {
      await this._ensureDisplayWindows(bars.at(-1).t);
    }
    return bars;
  }

  async _peekNextReplayBar() {
    const contract = (await this._manifest()).contracts[this.session.contract];
    await this._loadShard(this.session.shardIndex);
    if (this.session.barIndex + 1 < this.shard.length) return this.shard[this.session.barIndex + 1];
    if (this.session.shardIndex + 1 >= contract.shards.length) return null;

    const savedShard = this.shard;
    const savedKey = this.shardKey;
    try {
      await this._loadShard(this.session.shardIndex + 1);
      return this.shard?.[0] ?? null;
    } finally {
      this.shard = savedShard;
      this.shardKey = savedKey;
    }
  }

  async stepFrame(value) {
    if (!this.session) throw new Error("Session not initialized");
    if (this.session.state === "PLAYING") throw new Error("Pause before stepping");

    const timeframe = String(value || this.displayResolution || "1");
    if (!FRAME_RESOLUTIONS.has(timeframe)) throw new Error(`Unsupported chart timeframe ${timeframe}`);
    if (timeframe !== this.displayResolution) await this.setTimeframe(timeframe, this.historyRange);

    await this._loadShard(this.session.shardIndex);
    const current = this.shard?.[this.session.barIndex];
    if (!current) throw new Error("Replay cursor is unavailable");
    const next = await this._peekNextReplayBar();
    if (!next) {
      this.session.state = "FINISHED";
      await this._persist(false);
      this._broadcast(this.snapshot());
      return;
    }

    const currentKey = frameKey(current.t, timeframe);
    const nextKey = frameKey(next.t, timeframe);
    const targetKey = nextKey === currentKey ? currentKey : nextKey;
    const released = [];

    while (this.session.state !== "FINISHED") {
      const upcoming = await this._peekNextReplayBar();
      if (!upcoming || frameKey(upcoming.t, timeframe) !== targetKey) break;
      const bars = await this._release(1);
      if (!bars.length) break;
      released.push(bars[0]);
      if (released.length > 2000) throw new Error("Chart-frame step exceeded safety bound");
    }

    if (released.length === 1) this._broadcast({ type: "bar", bar: released[0], cursor: Number(released[0].t) });
    else if (released.length > 1) this._broadcast({ type: "bars_batch", bars: released, cursor: Number(released.at(-1).t) });
    await this._persist(false);
    this._broadcast(this.snapshot());
  }
}
