import { DurableObject } from "cloudflare:workers";

const SPEEDS = new Set([1, 5, 10, 25, 50, 100]);
const PRODUCT_SPECS = {
  MES: { pointValue: 5, tickSize: 0.25 },
  ES: { pointValue: 50, tickSize: 0.25 },
};

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

  _getPrefix(product) {
    const prod = product ?? this.session?.product ?? "MES";
    return `${prod.toLowerCase()}-replay/v1`;
  }

  _spec() {
    return PRODUCT_SPECS[this.session?.product] ?? PRODUCT_SPECS.MES;
  }

  _trading() {
    if (!this.session.trading) {
      this.session.trading = {
        positionQty: 0,
        avgPrice: 0,
        realizedPnl: 0,
        commission: 0,
        slippage: 0,
        pendingOrders: [],
        fills: [],
        nextSequence: 1,
        lastPrice: null,
      };
    }
    return this.session.trading;
  }

  async _manifest(product) {
    if (this.manifest) return this.manifest;
    const prefix = this._getPrefix(product);
    const object = await this.env.MES_DATA.get(`${prefix}/manifest.json`);
    if (!object) throw new Error(`${product ?? this.session?.product ?? "MES"} replay manifest is unavailable in R2`);
    this.manifest = JSON.parse(await object.text());
    return this.manifest;
  }

  async _loadShard(index) {
    const contract = (await this._manifest()).contracts[this.session.contract];
    const item = contract.shards[index];
    if (!item) return null;
    if (this.shardKey === item.key && this.shard) return this.shard;
    const prefix = this._getPrefix();
    const object = await this.env.MES_DATA.get(`${prefix}/${item.key}`);
    if (!object) throw new Error(`Missing R2 shard ${item.key}`);
    const stream = item.key.endsWith(".gz") ? object.body.pipeThrough(new DecompressionStream("gzip")) : object.body;
    this.shard = JSON.parse(await new Response(stream).text());
    this.shardKey = item.key;
    return this.shard;
  }

  async init(body) {
    const product = body.product || "MES";
    const manifest = await this._manifest(product);
    const contract = manifest.contracts[String(body.contract ?? "")];
    if (!contract) throw new Error(`Unknown contract ${body.contract}`);
    const start = Math.floor(new Date(body.start).getTime() / 1000);
    if (!Number.isFinite(start)) throw new Error("Invalid start timestamp");
    const shardIndex = contract.shards.findIndex((x) => x.last_time >= start);
    if (shardIndex < 0) throw new Error("No bar exists at or after requested start");
    const shard = await this._loadShardForContract(contract, shardIndex, product);
    let barIndex = shard.findIndex((x) => x.t >= start);
    let resolvedShard = shardIndex;
    if (barIndex < 0) {
      resolvedShard += 1;
      const next = await this._loadShardForContract(contract, resolvedShard, product);
      if (!next) throw new Error("No bar exists at or after requested start");
      barIndex = 0;
    }
    this.session = {
      id: body.session_id,
      userId: Number(body.user_id || 0) || null,
      product,
      contract: contract.contract,
      contractSelection: body.contract_selection ?? null,
      shardIndex: resolvedShard,
      barIndex,
      originShardIndex: resolvedShard,
      originBarIndex: barIndex,
      state: "PAUSED",
      speed: 1,
      warmup: Math.max(0, Math.min(5000, Number(body.warmup ?? 300))),
      startTs: start,
      trading: {
        positionQty: 0,
        avgPrice: 0,
        realizedPnl: 0,
        commission: 0,
        slippage: 0,
        pendingOrders: [],
        fills: [],
        nextSequence: 1,
        lastPrice: null,
      },
    };
    this.shard = null;
    this.shardKey = null;
    await this._loadShard(resolvedShard);
    const current = this.shard[this.session.barIndex];
    this.session.trading.lastPrice = current?.c ?? current?.o ?? null;
    await this._persist(true);
    await this._persistTradingSummary();
    const warmup = await this._warmupBars(this.session.originShardIndex, this.session.originBarIndex, this.session.warmup);
    return { ...this.snapshot(), warmup, future_data_included: false };
  }

  async _loadShardForContract(contract, index, product = null) {
    const item = contract.shards[index];
    if (!item) return null;
    const prefix = this._getPrefix(product);
    const object = await this.env.MES_DATA.get(`${prefix}/${item.key}`);
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

  _accountSnapshot() {
    if (!this.session) return null;
    const t = this._trading();
    const spec = this._spec();
    const last = Number(t.lastPrice);
    const unrealized = t.positionQty && Number.isFinite(last)
      ? (last - t.avgPrice) * t.positionQty * spec.pointValue
      : 0;
    return {
      product: this.session.product,
      contract: this.session.contract,
      point_value: spec.pointValue,
      tick_size: spec.tickSize,
      position_qty: t.positionQty,
      avg_price: t.avgPrice,
      realized_pnl: t.realizedPnl,
      unrealized_pnl: unrealized,
      commission: t.commission,
      slippage: t.slippage,
      total_pnl: t.realizedPnl + unrealized - t.commission - t.slippage,
      pending_orders: t.pendingOrders.map((x) => ({ ...x })),
      fills: t.fills.map((x) => ({ ...x })),
    };
  }

  snapshot() {
    if (!this.session || !this.shard) return { type: "session_snapshot", state: "STOPPED" };
    const bar = this.shard[this.session.barIndex];
    return {
      type: "session_snapshot",
      session_id: this.session.id,
      contract: this.session.contract,
      contract_selection: this.session.contractSelection,
      state: this.session.state,
      speed: this.session.speed,
      cursor: bar?.t ?? null,
      trading: this._accountSnapshot(),
    };
  }

  async webSocketMessage(ws, message) {
    try {
      const command = JSON.parse(typeof message === "string" ? message : new TextDecoder().decode(message));
      if (command.type === "play") await this.play(command.speed);
      else if (command.type === "pause") await this.pause();
      else if (command.type === "step") await this.step();
      else if (command.type === "restart") await this.restart();
      else if (command.type === "order") await this.placeOrder(command.side, command.quantity);
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

  async placeOrder(side, quantity) {
    if (!this.session) throw new Error("Session not initialized");
    if (this.session.state === "FINISHED") throw new Error("Replay is finished");
    side = String(side || "").toLowerCase();
    quantity = Number(quantity);
    if (!new Set(["buy", "sell"]).has(side)) throw new Error("Order side must be buy or sell");
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 100) throw new Error("Quantity must be an integer from 1 to 100");
    const cursor = this.shard?.[this.session.barIndex]?.t;
    if (!Number.isFinite(cursor)) throw new Error("Replay cursor is unavailable");
    const t = this._trading();
    const order = {
      id: crypto.randomUUID(),
      side,
      quantity,
      requested_at_ts: cursor,
    };
    t.pendingOrders.push(order);
    await this.ctx.storage.put("session", this.session);
    this._broadcast({ type: "order_accepted", order, trading: this._accountSnapshot() });
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
    this.session.trading = {
      positionQty: 0,
      avgPrice: 0,
      realizedPnl: 0,
      commission: 0,
      slippage: 0,
      pendingOrders: [],
      fills: [],
      nextSequence: 1,
      lastPrice: null,
    };
    this.shard = null;
    this.shardKey = null;
    await this._loadShard(this.session.shardIndex);
    const current = this.shard[this.session.barIndex];
    this.session.trading.lastPrice = current?.c ?? current?.o ?? null;
    const warmup = await this._warmupBars(this.session.originShardIndex, this.session.originBarIndex, this.session.warmup);
    await this._clearPersistedTrading();
    await this._persist(true);
    await this._persistTradingSummary();
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
        const bar = this.shard[this.session.barIndex];
        await this._fillPendingOrders(bar);
        this._trading().lastPrice = bar.c;
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
    return released;
  }

  async _fillPendingOrders(bar) {
    const t = this._trading();
    if (!t.pendingOrders.length) return;
    const pending = t.pendingOrders.splice(0);
    const fills = [];
    for (const order of pending) {
      const fill = this._applyFill(order, Number(bar.o), Number(bar.t));
      fills.push(fill);
      t.fills.push(fill);
      await this._persistFill(fill);
    }
    await this._persistTradingSummary();
    this._broadcast({ type: "fills", fills, trading: this._accountSnapshot() });
  }

  _applyFill(order, price, filledAt) {
    const t = this._trading();
    const spec = this._spec();
    const signed = order.side === "buy" ? order.quantity : -order.quantity;
    const oldQty = t.positionQty;
    const oldAvg = t.avgPrice;
    let realizedDelta = 0;

    if (oldQty === 0 || Math.sign(oldQty) === Math.sign(signed)) {
      const newQty = oldQty + signed;
      t.avgPrice = ((Math.abs(oldQty) * oldAvg) + (Math.abs(signed) * price)) / Math.abs(newQty);
      t.positionQty = newQty;
    } else {
      const closing = Math.min(Math.abs(oldQty), Math.abs(signed));
      realizedDelta = closing * (price - oldAvg) * Math.sign(oldQty) * spec.pointValue;
      t.realizedPnl += realizedDelta;
      const newQty = oldQty + signed;
      t.positionQty = newQty;
      if (newQty === 0) t.avgPrice = 0;
      else if (Math.sign(newQty) !== Math.sign(oldQty)) t.avgPrice = price;
    }

    const fill = {
      id: crypto.randomUUID(),
      sequence: t.nextSequence++,
      side: order.side,
      quantity: order.quantity,
      requested_at_ts: order.requested_at_ts,
      filled_at_ts: filledAt,
      fill_price: price,
      realized_delta: realizedDelta,
      position_after: t.positionQty,
      avg_price_after: t.avgPrice,
      commission: 0,
      slippage: 0,
    };
    return fill;
  }

  async _persistFill(fill) {
    if (!this.env.DB) return;
    try {
      await this.env.DB.prepare(`
        INSERT INTO trade_fills
          (id, replay_session_id, sequence, side, quantity, requested_at_ts, filled_at_ts, fill_price, realized_delta, commission, slippage, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        fill.id,
        this.session.id,
        fill.sequence,
        fill.side,
        fill.quantity,
        fill.requested_at_ts,
        fill.filled_at_ts,
        fill.fill_price,
        fill.realized_delta,
        fill.commission,
        fill.slippage,
        new Date().toISOString(),
      ).run();
    } catch (error) {
      console.error("D1 trade fill persistence failed", error);
    }
  }

  async _persistTradingSummary() {
    if (!this.env.DB || !this.session) return;
    const t = this._trading();
    try {
      await this.env.DB.prepare(`
        INSERT INTO simulation_accounts
          (replay_session_id, user_id, product, contract, position_qty, avg_price, realized_pnl, commission, slippage, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(replay_session_id) DO UPDATE SET
          position_qty=excluded.position_qty,
          avg_price=excluded.avg_price,
          realized_pnl=excluded.realized_pnl,
          commission=excluded.commission,
          slippage=excluded.slippage,
          updated_at=excluded.updated_at
      `).bind(
        this.session.id,
        this.session.userId,
        this.session.product,
        this.session.contract,
        t.positionQty,
        t.avgPrice,
        t.realizedPnl,
        t.commission,
        t.slippage,
        new Date().toISOString(),
      ).run();
    } catch (error) {
      console.error("D1 simulation account persistence failed", error);
    }
  }

  async _clearPersistedTrading() {
    if (!this.env.DB || !this.session) return;
    try {
      await this.env.DB.batch([
        this.env.DB.prepare("DELETE FROM trade_fills WHERE replay_session_id = ?").bind(this.session.id),
        this.env.DB.prepare("DELETE FROM simulation_accounts WHERE replay_session_id = ?").bind(this.session.id),
      ]);
    } catch (error) {
      console.error("D1 trading reset failed", error);
    }
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
