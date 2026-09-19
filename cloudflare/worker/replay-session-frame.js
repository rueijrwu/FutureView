import { ReplaySession as BaseReplaySession } from "./replay-session.js";

const SPEEDS = new Set([1, 5, 10, 25, 50, 100]);
const HISTORY_SECONDS = { "1D": 86400, "5D": 5 * 86400, "1M": 30 * 86400, "3M": 90 * 86400 };

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
    }
    const foreign = [...this.displayWindows.keys()].filter((key) => !key.startsWith(`${resolution}:`));
    for (let i = 1; i < foreign.length; i += 1) this.displayWindows.delete(foreign[i]);
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
}
