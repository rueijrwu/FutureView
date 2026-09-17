import { ReplaySession as BaseReplaySession } from "./replay-session.js";

const FRAME_RESOLUTIONS = new Set(["1", "5", "30", "240", "1D"]);
const SPEEDS = new Set([1, 5, 10, 25, 50, 100]);
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
  const parts = Object.fromEntries(
    ET_FORMATTER.formatToParts(new Date(Number(seconds) * 1000))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
  return parts;
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

function frameKey(seconds, resolution) {
  const start = sessionStart(seconds);
  if (resolution === "1D") return `D:${start}`;
  const minutes = Number(resolution);
  const bucket = Math.floor(Math.max(0, Number(seconds) - start) / (minutes * 60));
  return `${start}:${minutes}:${bucket}`;
}

export class ReplaySession extends BaseReplaySession {
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
      else return super.webSocketMessage(ws, message);
    } catch (error) {
      ws.send(JSON.stringify({ type: "error", error: String(error?.message ?? error) }));
    }
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

  async stepFrame(value) {
    if (!this.session) throw new Error("Session not initialized");
    if (this.session.state === "PLAYING") throw new Error("Pause before stepping");

    const timeframe = String(value || "1");
    if (!FRAME_RESOLUTIONS.has(timeframe)) throw new Error(`Unsupported chart timeframe ${timeframe}`);

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
