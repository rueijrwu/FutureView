import { ReplaySession as BaseReplaySession } from "./replay-session.js";

const FRAME_RESOLUTIONS = new Set(["1", "5", "30", "240", "1D"]);
const SPEEDS = new Set([1, 5, 10, 25, 50, 100]);
const HISTORY_SECONDS = { "1D": 86400, "5D": 5 * 86400, "1M": 30 * 86400, "3M": 90 * 86400 };
const DISPLAY_WINDOW_BARS = 512;
const PREFETCH_THRESHOLD = 0.75;
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
  const localDate = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour < 18) localDate.setUTCDate(localDate.getUTCDate() - 1);
  return wallToEpochSeconds({
    year: localDate.getUTCFullYear(),
    month: localDate.getUTCMonth() + 1,
    day: localDate.getUTCDate(),
    hour: 18,
    minute: 0,
    second: 0,
  });
}

function frameStart(seconds, resolution) {
  const start = sessionStart(seconds);
  if (resolution === "1D") return start;
  if (resolution === "1") return Number(seconds);
  const minutes = Number(resolution);
  return start + Math.floor(Math.max(0, Number(seconds) - start) / (minutes * 60)) * minutes * 60;
}

function frameKey(seconds, resolution) {
  const start = sessionStart(seconds);
  if (resolution === "1D") return `D:${start}`;
  const minutes = Number(resolution);
  const bucket = Math.floor(Math.max(0, Number(seconds) - start) / (minutes * 60));
  return `${start}:${minutes}:${bucket}`;
}

function dailyTradingStamp(seconds) {
  const parts = etParts(seconds);
  const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour >= 18) day.setUTCDate(day.getUTCDate() + 1);
  return Math.floor(day.getTime() / 1000);
}

function displayCutoff(seconds, resolution) {
  return resolution === "1D" ? dailyTradingStamp(seconds) : frameStart(seconds, resolution);
}

export class ReplaySession extends BaseReplaySession {
  constructor(ctx, env) {
    super(ctx, env);
    this.displayResolution = "5";
    this.historyRange = "5D";
    this.displayWindowIndex = -1;
    this.displayWindows = new Map();
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
    const manifest = await this._manifest();
    return manifest.contracts?.[this.session.contract]?.display_shards?.[resolution] ?? [];
  }

  async _loadDisplayWindow(index, resolution = this.displayResolution) {
    if (resolution === "1" || index < 0) return null;
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

  _trimDisplayWindows(centerIndex, resolution = this.displayResolution) {
    const keep = new Set([
      `${resolution}:${centerIndex - 1}`,
      `${resolution}:${centerIndex}`,
      `${resolution}:${centerIndex + 1}`,
      `${resolution}:${centerIndex + 2}`,
    ]);
    for (const key of [...this.displayWindows.keys()]) {
      if (key.startsWith(`${resolution}:`) && !keep.has(key)) this.displayWindows.delete(key);
    }
    const foreign = [...this.displayWindows.keys()].filter((key) => !key.startsWith(`${resolution}:`));
    for (let i = 1; i < foreign.length; i += 1) this.displayWindows.delete(foreign[i]);
  }

  async _ensureDisplayWindows(cursor) {
    const resolution = this.displayResolution;
    if (resolution === "1" || !Number.isFinite(Number(cursor))) return;
    const shards = await this._displayShardMeta(resolution);
    if (!shards.length) return;

    let index = this.displayWindowIndex;
    if (index < 0 || !shards[index] || Number(cursor) > Number(shards[index].last_time)) {
      index = shards.findIndex((meta) => Number(meta.last_time) >= Number(cursor));
      if (index < 0) index = shards.length - 1;
      this.displayWindowIndex = index;
    }

    const current = await this._loadDisplayWindow(index, resolution);
    if (!current) return;
    await this._loadDisplayWindow(index + 1, resolution);

    const bars = current.bars || [];
    if (bars.length) {
      let localIndex = bars.findIndex((bar) => Number(bar.t) >= Number(cursor));
      if (localIndex < 0) localIndex = bars.length - 1;
      const progress = bars.length > 1 ? localIndex / (bars.length - 1) : 1;
      if (progress >= PREFETCH_THRESHOLD) await this._loadDisplayWindow(index + 2, resolution);
    }
    this._trimDisplayWindows(index, resolution);
  }

  async _causalDisplayWindow(cursor, resolution = this.displayResolution, historyRange = this.historyRange) {
    if (resolution === "1" || !Number.isFinite(Number(cursor))) return [];
    await this._ensureDisplayWindows(cursor);
    const center = this.displayWindowIndex;
    if (center < 0) return [];

    const cutoff = displayCutoff(cursor, resolution);
    const seconds = HISTORY_SECONDS[historyRange] ?? HISTORY_SECONDS["5D"];
    const historyFrom = Number(cursor) - seconds;
    const shards = await this._displayShardMeta(resolution);
    const firstNeeded = Math.max(0, shards.findIndex((meta, index) => index <= center && Number(meta.last_time) >= historyFrom));
    const out = [];

    for (let index = firstNeeded; index <= center; index += 1) {
      const window = await this._loadDisplayWindow(index, resolution);
      if (!window) continue;
      for (const bar of window.bars || []) {
        const t = Number(bar.t);
        if (t >= historyFrom && t < cutoff) out.push(bar);
      }
    }
    out.sort((a, b) => Number(a.t) - Number(b.t));

    // Historical windows are response-only. Keep the forward rolling cache bounded.
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
    this.displayWindowIndex = -1;
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

  async setSpeed(value) {
    if (!this.session) throw new Error("Session not initialized");
    let speed = value;
    if (String(value).toLowerCase() === "max") speed = "max";
    else {
      speed = Number(value);
      if (!SPEEDS.has(speed)) throw new Error("Invalid replay speed");
    }

    this.session.speed = speed;
    if (this.session.state === "PLAYING") {
      this.credit = 0;
      this.lastTick = Date.now();
    }
    await this.ctx.storage.put("session", this.session);
    this._broadcast(this.snapshot());
  }

  async _release(count) {
    const bars = await super._release(count);
    if (bars.length) await this._ensureDisplayWindows(bars.at(-1).t);
    return bars;
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
    const initialKey = frameKey(current.t, timeframe);
    const released = [];

    while (this.session.state !== "FINISHED") {
      const bars = await this._release(1);
      if (!bars.length) break;
      const bar = bars[0];
      released.push(bar);
      if (frameKey(bar.t, timeframe) !== initialKey) break;
      if (released.length > 2000) throw new Error("Chart-frame step exceeded safety bound");
    }

    if (released.length === 1) this._broadcast({ type: "bar", bar: released[0] });
    else if (released.length > 1) this._broadcast({ type: "bars_batch", bars: released });
    await this._persist(false);
    this._broadcast(this.snapshot());
  }
}
