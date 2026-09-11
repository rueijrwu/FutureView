import { DurableObject } from "cloudflare:workers";

const PREFIX = "mes-replay/v1";
const SPEEDS = new Set([1, 5, 10, 25, 50, 100]);

export class ReplaySession extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.ctx = ctx;
    this.env = env;
    this.session = null;
    this.manifest = null;
    this.shard = null;
    this.shardKey = null;
    this.timer = null;
    this.credit = 0;
    this.lastTick = 0;
    this.generation = 0;
    this.ticks = 0;
    this.ctx.blockConcurrencyWhile(async () => {
      this.session = (await this.ctx.storage.get("session")) ?? null;
      if (this.session?.state === "PLAYING") {
        this.session.state = "PAUSED";
        await this.ctx.storage.put("session", this.session);
      }
    });
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/init" && request.method === "POST") {
      try {
        return Response.json(await this.init(await request.json()));
      } catch (error) {
        return Response.json({ error: String(error?.message ?? error) }, { status: 400 });
      }
    }
    if (request.headers.get("upgrade")?.toLowerCase() === "websocket") {
      if (!this.session) return new Response("Session not initialized", { status: 409 });
      await this._loadShard(this.session.shardIndex);
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.ctx.acceptWebSocket(server);
      server.send(JSON.stringify(this.snapshot()));
      return new Response(null, { status: 101, webSocket: client });
    }
    return new Response("Not found", { status: 404 });
  }

  async _manifest() {
    if (this.manifest) return this.manifest;
    const object = await this.env.MES_DATA.get(`${PREFIX}/manifest.json`);
    if (!object) throw new Error("MES replay manifest is unavailable in R2");
    this.manifest = JSON.parse(await object.text());
    return this.manifest;
  }

  async _loadShard(index) {
    const contract = (await this._manifest()).contracts[this.session.contract];
    const item = contract.shards[index];
    if (!item) return null;
    if (this.shardKey === item.key && this.shard) return this.shard;
    const object = await this.env.MES_DATA.get(`${PREFIX}/${item.key}`);
    if (!object) throw new Error(`Missing R2 shard ${item.key}`);
    const stream = item.key.endsWith(".gz") ? object.body.pipeThrough(new DecompressionStream("gzip")) : object.body;
    this.shard = JSON.parse(await new Response(stream).text());
    this.shardKey = item.key;
    return this.shard;
  }

  async init(body) {
    const manifest = await this._manifest();
    const contract = manifest.contracts[String(body.contract ?? "")];
    if (!contract) throw new Error(`Unknown contract ${body.contract}`);
    const start = Math.floor(new Date(body.start).getTime() / 1000);
    if (!Number.isFinite(start)) throw new Error("Invalid start timestamp");
    const shardIndex = contract.shards.findIndex((x) => x.last_time >= start);
    if (shardIndex < 0) throw new Error("No bar exists at or after requested start");
    const shard = await this._loadForInit(contract, shardIndex);
    let barIndex = shard.findIndex((x) => x.t >= start);
    let resolvedShard = shardIndex;
    if (barIndex < 0) {
      resolvedShard += 1;
      const next = await this._loadShardForContract(contract, resolvedShard);
      if (!next) throw new Error("No bar exists at or after requested start");
      barIndex = 0;
    }
    this.session = {
      id: body.session_id,
      contract: contract.contract,
      shardIndex: resolvedShard,
      barIndex,
      originShardIndex: resolvedShard,
      originBarIndex: barIndex,
      state: "PAUSED",
      speed: 1,
      warmup: Math.max(0, Math.min(5000, Number(body.warmup ?? 300))),
      startTs: start,
    };
    this.shard = null;
    this.shardKey = null;
    await this._loadShard(resolvedShard);
    await this._persist(true);
    const warmup = await this._warmupBars(this.session.originShardIndex, this.session.originBarIndex, this.session.warmup);
    return { ...this.snapshot(), warmup, future_data_included: false };
  }

  async _loadForInit(contract, index) {
    return this._loadShardForContract(contract, index);
  }

  async _loadShardForContract(contract, index) {
    const item = contract.shards[index];
    if (!item) return null;
    const object = await this.env.MES_DATA.get(`${PREFIX}/${item.key}`);
    if (!object) throw new Error(`Missing R2 shard ${item.key}`);
    const stream = item.key.endsWith(".gz") ? object.body.pipeThrough(new DecompressionStream("gzip")) : object.body;
    return JSON.parse(await new Response(stream).text());
  }

  async _warmupBars(shardIndex, barIndex, count) {
    const contract = (await this._manifest()).contracts[this.session.contract];
    let remaining = count;
    let index = shardIndex;
    const chunks = [];
    while (index >= 0 && remaining > 0) {
      const bars = await this._loadShardForContract(contract, index);
      const takeEnd = index === shardIndex ? barIndex + 1 : bars.length;
      const takeStart = Math.max(0, takeEnd - remaining);
      chunks.unshift(bars.slice(takeStart, takeEnd));
      remaining -= takeEnd - takeStart;
      index -= 1;
    }
    const current = await this._loadShardForContract(contract, shardIndex);
    const cursor = current[barIndex];
    const flattened = chunks.flat();
    if (!flattened.length || flattened.at(-1)?.t !== cursor.t) flattened.push(cursor);
    return flattened;
  }

  snapshot() {
    if (!this.session || !this.shard) return { type: "session_snapshot", state: "STOPPED" };
    const bar = this.shard[this.session.barIndex];
    return {
      type: "session_snapshot",
      session_id: this.session.id,
      contract: this.session.contract,
      state: this.session.state,
      speed: this.session.speed,
      cursor: bar?.t ?? null,
    };
  }

  async webSocketMessage(ws, message) {
    try {
      const command = JSON.parse(typeof message === "string" ? message : new TextDecoder().decode(message));
      if (command.type === "play") await this.play(command.speed);
      else if (command.type === "pause") await this.pause();
      else if (command.type === "step") await this.step();
      else if (command.type === "restart") await this.restart();
      else ws.send(JSON.stringify({ type: "error", error: `Unknown command ${command.type}` }));
    } catch (error) {
      ws.send(JSON.stringify({ type: "error", error: String(error?.message ?? error) }));
    }
  }

  webSocketClose(ws, code, reason) {
    ws.close(code, reason);
  }

  _broadcast(payload) {
    const encoded = JSON.stringify(payload);
    for (const ws of this.ctx.getWebSockets()) {
      try { ws.send(encoded); } catch {}
    }
  }

  async play(value) {
    if (!this.session) throw new Error("Session not initialized");
    let speed = value;
    if (String(value).toLowerCase() === "max") speed = "max";
    else {
      speed = Number(value);
      if (!SPEEDS.has(speed)) throw new Error("Invalid replay speed");
    }
    this.generation += 1;
    this.session.state = "PLAYING";
    this.session.speed = speed;
    this.credit = 0;
    this.lastTick = Date.now();
    await this.ctx.storage.put("session", this.session);
    this._broadcast(this.snapshot());
    this._schedule(this.generation);
  }

  async pause() {
    if (!this.session) return;
    this.generation += 1;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.session.state !== "FINISHED") this.session.state = "PAUSED";
    await this._persist(true);
    this._broadcast(this.snapshot());
  }

  async step() {
    if (this.session.state === "PLAYING") throw new Error("Pause before stepping");
    const bars = await this._release(1);
    if (bars.length) this._broadcast({ type: "bar", bar: bars[0] });
    await this._persist(false);
    this._broadcast(this.snapshot());
  }

  async restart() {
    this.generation += 1;
    if (this.timer) clearTimeout(this.timer);
    this.session.shardIndex = this.session.originShardIndex;
    this.session.barIndex = this.session.originBarIndex;
    this.session.state = "PAUSED";
    this.session.speed = 1;
    this.shard = null;
    this.shardKey = null;
    await this._loadShard(this.session.shardIndex);
    const warmup = await this._warmupBars(this.session.originShardIndex, this.session.originBarIndex, this.session.warmup);
    await this._persist(true);
    this._broadcast({ type: "reset", warmup, snapshot: this.snapshot() });
  }

  _schedule(generation) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this._tick(generation), 50);
  }

  async _tick(generation) {
    if (!this.session || generation !== this.generation || this.session.state !== "PLAYING") return;
    const now = Date.now();
    const elapsed = Math.max(0, (now - this.lastTick) / 1000);
    this.lastTick = now;
    let due;
    if (this.session.speed === "max") due = 250;
    else {
      this.credit += elapsed * Number(this.session.speed);
      due = Math.floor(this.credit);
      this.credit -= due;
    }
    if (due > 0) {
      const bars = await this._release(due);
      if (bars.length === 1) this._broadcast({ type: "bar", bar: bars[0] });
      else if (bars.length > 1) this._broadcast({ type: "bars_batch", bars });
      this.ticks += 1;
      if (this.ticks % 20 === 0 || this.session.state === "FINISHED") await this._persist(this.session.state === "FINISHED");
    }
    if (this.session.state === "FINISHED") {
      this._broadcast(this.snapshot());
      return;
    }
    this._schedule(generation);
  }

  async _release(count) {
    const contract = (await this._manifest()).contracts[this.session.contract];
    const released = [];
    while (released.length < count) {
      await this._loadShard(this.session.shardIndex);
      if (this.session.barIndex + 1 < this.shard.length) {
        this.session.barIndex += 1;
        released.push(this.shard[this.session.barIndex]);
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
    return released;
  }

  async _persist(updateD1) {
    await this.ctx.storage.put("session", this.session);
    if (!updateD1 || !this.env.DB) return;
    const snapshot = this.snapshot();
    const now = new Date().toISOString();
    try {
      await this.env.DB.prepare(`
        INSERT INTO replay_sessions (id, contract, start_ts, cursor_ts, state, speed, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET cursor_ts=excluded.cursor_ts, state=excluded.state, speed=excluded.speed, updated_at=excluded.updated_at
      `).bind(
        this.session.id,
        this.session.contract,
        this.session.startTs,
        snapshot.cursor ?? this.session.startTs,
        this.session.state,
        String(this.session.speed),
        now,
        now,
      ).run();
    } catch (error) {
      console.error("D1 replay session persistence failed", error);
    }
  }
}
