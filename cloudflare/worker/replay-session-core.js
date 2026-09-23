import { DurableObject } from "cloudflare:workers";

const SPEEDS = new Set([1, 5, 10, 25, 50, 100]);
// commissionPerSide is charged per contract on every fill; slippageTicks is the
// adverse micro-slippage charged on any fill that reaches the market (market
// orders and triggered stops). Resting limits never slip: they fill at their
// own price or better, or they do not fill.
const PRODUCT_SPECS = {
  MES: { pointValue: 5, tickSize: 0.25, commissionPerSide: 0.62, slippageTicks: 1 },
  ES: { pointValue: 50, tickSize: 0.25, commissionPerSide: 2.25, slippageTicks: 1 },
};
const ORDER_TYPES = new Set(["market", "limit", "stop", "stop_limit"]);
const ORDER_SIDES = new Set(["buy", "sell"]);

// The auto-flatten boundary: 4:00 PM ET, the RTH equity-index close a real
// day-trading account closes out at — NOT the same as either of main.js's two
// session questions (17:00 requested_session_date, 18:00 session_date), which
// answer "what contract/session does this bar belong to" for data selection,
// not "when does a day-trading account have to be flat." Conflating this with
// the CME 18:00 session roll was the original bug: Ruei plays/steps through
// 4pm ET expecting a flatten and nothing happens until two hours later.
// Bucketed by UTC hour and cached, same technique (and same reasoning) as
// historySessionDate in replay-session-display-fast.js: this runs once per
// released bar, including inside 2000-bar timestamp-bounded releases.
const FLATTEN_HOUR_ET = 16;
const FLATTEN_DATE_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  hourCycle: "h23",
});
const FLATTEN_DATE_CACHE = new Map();
const FLATTEN_DATE_CACHE_MAX = 1 << 16;

function flattenPeriodAtUncached(seconds) {
  const parts = Object.fromEntries(
    FLATTEN_DATE_FORMATTER.formatToParts(new Date(Number(seconds) * 1000))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
  const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour >= FLATTEN_HOUR_ET) day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

function flattenPeriodAt(seconds) {
  const hour = Math.floor(Number(seconds) / 3600);
  if (!Number.isFinite(hour)) return flattenPeriodAtUncached(seconds);
  const cached = FLATTEN_DATE_CACHE.get(hour);
  if (cached !== undefined) return cached;
  const value = flattenPeriodAtUncached(seconds);
  if (FLATTEN_DATE_CACHE.size >= FLATTEN_DATE_CACHE_MAX) FLATTEN_DATE_CACHE.clear();
  FLATTEN_DATE_CACHE.set(hour, value);
  return value;
}
// Stops are evaluated before limits inside one canonical bar. Both can trigger on
// the same minute and 1m OHLCV carries no intrabar sequence, so the order has to
// be a stated convention rather than an accident of insertion order.
const ORDER_EVAL_RANK = { stop: 0, stop_limit: 0, market: 1, limit: 2 };

// Base of the replay chain. This class is never deployed on its own: wrangler
// ships the display-fast subclass via main-frame.js. Five methods it calls are
// deliberately not defined here, because every implementation that ever ran was
// the subclass override and keeping a shadowed copy only invited drift:
//
//   _findShardAtOrAfter / _findBarAtOrAfter   binary search, replay-session.js
//   _warmupBars                               resident-shard reuse, replay-session.js
//   _release                                  batched release, replay-session.js
//   _tick                                     display aggregation, replay-session-display.js
//
// A subclass must supply all five.
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
    if (url.pathname === "/save" && request.method === "POST") {
      try {
        const body = await request.json();
        return Response.json(await this.save(body.user_id));
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

  _blankTrading(lastPrice = null) {
    return {
      positionQty: 0,
      avgPrice: 0,
      realizedPnl: 0,
      commission: 0,
      slippage: 0,
      pendingOrders: [],
      fills: [],
      nextSequence: 1,
      nextOrderSequence: 1,
      lastPrice,
      lastBarTs: null,
    };
  }

  _trading() {
    if (!this.session.trading) this.session.trading = this._blankTrading();
    return this.session.trading;
  }

  // Rebuilds a trading record from a saved snapshot (see save()). lastPrice is
  // never trusted from the snapshot: it is recomputed from the bar the resumed
  // session actually lands on, same as a fresh init().
  _hydrateTrading(saved, lastPrice) {
    const blank = this._blankTrading(lastPrice);
    if (!saved || typeof saved !== "object") return blank;
    const num = (value, fallback) => (Number.isFinite(Number(value)) ? Number(value) : fallback);
    return {
      positionQty: num(saved.positionQty, blank.positionQty),
      avgPrice: num(saved.avgPrice, blank.avgPrice),
      realizedPnl: num(saved.realizedPnl, blank.realizedPnl),
      commission: num(saved.commission, blank.commission),
      slippage: num(saved.slippage, blank.slippage),
      pendingOrders: Array.isArray(saved.pendingOrders) ? saved.pendingOrders.map((order) => ({ ...order })) : [],
      fills: Array.isArray(saved.fills) ? saved.fills.map((fill) => ({ ...fill })) : [],
      nextSequence: num(saved.nextSequence, blank.nextSequence) || 1,
      nextOrderSequence: num(saved.nextOrderSequence, blank.nextOrderSequence) || 1,
      lastPrice,
      lastBarTs: null,
    };
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
    const shardIndex = this._findShardAtOrAfter(contract, start);
    if (shardIndex < 0) throw new Error("No bar exists at or after requested start");
    const shard = await this._loadShardForContract(contract, shardIndex, product);
    let resolvedBars = shard;
    let barIndex = this._findBarAtOrAfter(resolvedBars, start);
    let resolvedShard = shardIndex;
    if (barIndex < 0) {
      resolvedShard += 1;
      resolvedBars = await this._loadShardForContract(contract, resolvedShard, product);
      if (!resolvedBars) throw new Error("No bar exists at or after requested start");
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
      warmup: Math.max(0, Math.min(100000, Number(body.warmup ?? 300))),
      startTs: start,
      trading: this._blankTrading(),
      autoFlattenAtSessionEnd: body.auto_flatten_at_session_end !== false,
      currentFlattenPeriod: null,
    };
    this.shard = resolvedBars;
    this.shardKey = contract.shards[resolvedShard]?.key ?? null;
    const current = this.shard[this.session.barIndex];
    const cursorPrice = current?.c ?? current?.o ?? null;
    this.session.trading = body.trading ? this._hydrateTrading(body.trading, cursorPrice) : this._blankTrading(cursorPrice);
    this.session.trading.lastBarTs = current?.t ?? null;
    this.session.currentFlattenPeriod = current ? flattenPeriodAt(current.t) : null;
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
      commission_per_side: spec.commissionPerSide,
      slippage_ticks: spec.slippageTicks,
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
      auto_flatten_at_session_end: this.session.autoFlattenAtSessionEnd === true,
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
      else if (command.type === "order") await this.placeOrder(command);
      else if (command.type === "cancel_order") await this.cancelOrder(command.order_id);
      else if (command.type === "clear_trading") await this.clearTrading();
      else if (command.type === "set_auto_flatten") await this.setAutoFlatten(command.enabled);
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

  // Prices the user names must sit on the contract's tick grid. tickSize was
  // published in the account snapshot long before anything validated against it.
  _requireTickPrice(value, label) {
    const price = Number(value);
    if (!Number.isFinite(price) || price <= 0) throw new Error(`${label} must be a positive price`);
    const spec = this._spec();
    const ticks = price / spec.tickSize;
    if (Math.abs(ticks - Math.round(ticks)) > 1e-9) {
      throw new Error(`${label} must be a multiple of ${spec.tickSize}`);
    }
    return Math.round(ticks) * spec.tickSize;
  }

  async placeOrder(command) {
    if (!this.session) throw new Error("Session not initialized");
    if (this.session.state === "FINISHED") throw new Error("Replay is finished");
    const side = String(command?.side || "").toLowerCase();
    const type = String(command?.order_type || "market").toLowerCase();
    const quantity = Number(command?.quantity);
    if (!ORDER_SIDES.has(side)) throw new Error("Order side must be buy or sell");
    if (!ORDER_TYPES.has(type)) throw new Error(`Unsupported order type ${command?.order_type}`);
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 100) throw new Error("Quantity must be an integer from 1 to 100");
    const cursor = this.shard?.[this.session.barIndex]?.t;
    if (!Number.isFinite(cursor)) throw new Error("Replay cursor is unavailable");

    const t = this._trading();
    const needsLimit = type === "limit" || type === "stop_limit";
    const needsStop = type === "stop" || type === "stop_limit";
    const limitPrice = needsLimit ? this._requireTickPrice(command?.limit_price, "Limit price") : null;
    const stopPrice = needsStop ? this._requireTickPrice(command?.stop_price, "Stop price") : null;

    // A stop that is already through the market is an order-entry mistake, not a
    // stop: it would trigger on the very next bar and behave as a market order.
    if (needsStop && Number.isFinite(Number(t.lastPrice))) {
      const last = Number(t.lastPrice);
      if (side === "buy" && stopPrice <= last) throw new Error("A buy stop must be above the current price");
      if (side === "sell" && stopPrice >= last) throw new Error("A sell stop must be below the current price");
    }

    // A bracket attaches a take-profit and/or a stop-loss that only start working
    // once this entry fills (see _fillPendingOrders). Either leg is optional, but
    // both are validated against where we expect the entry to fill, so a bracket
    // can never be placed backwards.
    const hasTakeProfit = command?.take_profit_price != null;
    const hasStopLoss = command?.stop_loss_price != null;
    let takeProfitPrice = null;
    let stopLossPrice = null;
    if (hasTakeProfit || hasStopLoss) {
      takeProfitPrice = hasTakeProfit ? this._requireTickPrice(command.take_profit_price, "Take-profit price") : null;
      stopLossPrice = hasStopLoss ? this._requireTickPrice(command.stop_loss_price, "Stop-loss price") : null;
      const reference = needsLimit ? limitPrice : (needsStop ? stopPrice : Number(t.lastPrice));
      if (Number.isFinite(reference)) {
        if (side === "buy") {
          if (takeProfitPrice != null && takeProfitPrice <= reference) throw new Error("Take-profit must be above the entry price for a buy bracket");
          if (stopLossPrice != null && stopLossPrice >= reference) throw new Error("Stop-loss must be below the entry price for a buy bracket");
        } else {
          if (takeProfitPrice != null && takeProfitPrice >= reference) throw new Error("Take-profit must be below the entry price for a sell bracket");
          if (stopLossPrice != null && stopLossPrice <= reference) throw new Error("Stop-loss must be above the entry price for a sell bracket");
        }
      }
    }

    const order = {
      id: crypto.randomUUID(),
      sequence: t.nextOrderSequence++,
      type,
      side,
      quantity,
      limit_price: limitPrice,
      stop_price: stopPrice,
      status: "working",
      requested_at_ts: cursor,
      triggered_at_ts: null,
      take_profit_price: takeProfitPrice,
      stop_loss_price: stopLossPrice,
    };
    t.pendingOrders.push(order);
    await this.ctx.storage.put("session", this.session);
    await this._persistOrder(order);
    this._broadcast({ type: "order_accepted", order, trading: this._accountSnapshot() });
  }

  async cancelOrder(orderId) {
    if (!this.session) throw new Error("Session not initialized");
    const t = this._trading();
    const index = t.pendingOrders.findIndex((order) => order.id === orderId);
    if (index < 0) throw new Error("No working order with that id");
    const [order] = t.pendingOrders.splice(index, 1);
    order.status = "cancelled";
    await this.ctx.storage.put("session", this.session);
    await this._persistOrderStatus(order.id, "cancelled");
    this._broadcast({ type: "order_cancelled", order, trading: this._accountSnapshot() });
  }

  async clearTrading() {
    if (!this.session) throw new Error("Session not initialized");
    const current = this.shard?.[this.session.barIndex];
    this.session.trading = this._blankTrading(current?.c ?? current?.o ?? null);
    this.session.trading.lastBarTs = current?.t ?? null;
    await this._clearPersistedTrading();
    await this.ctx.storage.put("session", this.session);
    await this._persistTradingSummary();
    this._broadcast({ type: "trading_cleared", trading: this._accountSnapshot() });
  }

  // Toggled live from the trading UI, independent of restart/clearTrading. The
  // session-boundary tracker keeps running either way (see
  // _maybeFlattenForSessionEnd), so flipping this on mid-session only starts
  // flattening at the *next* boundary crossed, never retroactively.
  async setAutoFlatten(enabled) {
    if (!this.session) throw new Error("Session not initialized");
    this.session.autoFlattenAtSessionEnd = enabled === true;
    await this.ctx.storage.put("session", this.session);
    this._broadcast({ type: "auto_flatten_changed", enabled: this.session.autoFlattenAtSessionEnd });
  }

  // Called once per released canonical bar (see _release / _releaseUntilBefore
  // in replay-session.js) to detect the 4:00 PM ET day-trading close and, when
  // enabled, force-close any open position and cancel resting orders as of the
  // last bar before the close — mirroring a real day-trading account that
  // cannot carry a position past it. closePrice/closeTs are the last bar
  // before the close (this.trading.lastPrice/lastBarTs), never the incoming
  // bar: the fill must not see a price from after the close.
  async _maybeFlattenForSessionEnd(bar) {
    const key = flattenPeriodAt(bar.t);
    const previous = this.session.currentFlattenPeriod;
    if (previous && key !== previous && this.session.autoFlattenAtSessionEnd === true) {
      const t = this._trading();
      await this._forceCloseSessionEnd(t.lastPrice, t.lastBarTs);
    }
    this.session.currentFlattenPeriod = key;
  }

  // Cancels every resting order (including bracket legs) and, if a position is
  // open, closes it at closePrice with the same commission/slippage a market
  // order pays (see _applyFill) — the account cannot walk into the next session
  // carrying risk it never placed an order to carry.
  async _forceCloseSessionEnd(closePrice, closeTs) {
    const t = this._trading();
    const cancelled = [];
    if (t.pendingOrders.length) {
      for (const order of t.pendingOrders) {
        order.status = "cancelled";
        cancelled.push({ ...order });
      }
      t.pendingOrders = [];
    }

    let fill = null;
    if (t.positionQty !== 0 && Number.isFinite(Number(closePrice))) {
      const order = {
        id: crypto.randomUUID(),
        sequence: t.nextOrderSequence++,
        type: "market",
        side: t.positionQty > 0 ? "sell" : "buy",
        quantity: Math.abs(t.positionQty),
        limit_price: null,
        stop_price: null,
        status: "working",
        requested_at_ts: closeTs,
        triggered_at_ts: null,
        take_profit_price: null,
        stop_loss_price: null,
      };
      await this._persistOrder(order);
      fill = this._applyFill(order, Number(closePrice), closeTs, true);
      t.fills.push(fill);
      await this._persistFill(fill);
      await this._persistOrderStatus(order.id, "filled");
    }

    if (!cancelled.length && !fill) return;
    for (const order of cancelled) await this._persistOrderStatus(order.id, "cancelled");
    await this._persistTradingSummary();
    this._broadcast({ type: "session_end_flatten", cancelled_orders: cancelled, fill, trading: this._accountSnapshot() });
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
    this.session.trading = this._blankTrading();
    this.shard = null;
    this.shardKey = null;
    await this._loadShard(this.session.shardIndex);
    const current = this.shard[this.session.barIndex];
    this.session.trading.lastPrice = current?.c ?? current?.o ?? null;
    this.session.trading.lastBarTs = current?.t ?? null;
    this.session.currentFlattenPeriod = current ? flattenPeriodAt(current.t) : null;
    const warmup = await this._warmupBars(this.session.originShardIndex, this.session.originBarIndex, this.session.warmup);
    await this._clearPersistedTrading();
    await this._persist(true);
    await this._persistTradingSummary();
    this._broadcast({ type: "reset", warmup, snapshot: this.snapshot() });
  }

  _tickDelayMs() {
    if (this.session?.speed === "max") return 100;
    return Number(this.session?.speed) >= 50 ? 100 : 50;
  }

  _schedule(generation) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this._tick(generation), this._tickDelayMs());
  }

  // Limits require the bar to trade *through* the price, stops trigger on a touch.
  // That asymmetry is deliberate: a stop is a market trigger, while a resting
  // limit sitting exactly at a bar's extreme is behind a queue we cannot model, so
  // crediting it a fill would flatter every result.
  _evaluateLimit(order, open, high, low) {
    const limit = Number(order.limit_price);
    if (order.side === "buy") {
      if (open <= limit) return { action: "fill", price: open };
      if (low < limit) return { action: "fill", price: limit };
      return { action: "rest" };
    }
    if (open >= limit) return { action: "fill", price: open };
    if (high > limit) return { action: "fill", price: limit };
    return { action: "rest" };
  }

  // Decides what one working order does against the bar being released right now.
  // It never looks at any later bar, which is what keeps the replay causal.
  _evaluateOrder(order, bar) {
    const open = Number(bar.o);
    const high = Number(bar.h);
    const low = Number(bar.l);
    const type = order.type ?? "market";

    if (type === "market") return { action: "fill", price: open, marketable: true };
    if (type === "limit") return this._evaluateLimit(order, open, high, low);

    if (order.status !== "triggered") {
      const stop = Number(order.stop_price);
      const hit = order.side === "buy" ? high >= stop : low <= stop;
      if (!hit) return { action: "rest" };
      if (type === "stop") {
        // A bar that gapped straight through the stop never traded at it, so the
        // fill is the open and the user eats the gap. This is the whole point of
        // modelling stops honestly.
        const price = order.side === "buy" ? Math.max(stop, open) : Math.min(stop, open);
        return { action: "fill", price, marketable: true };
      }
      // stop_limit: the limit goes live, but not on the bar that triggered it.
      // 1m OHLCV gives no intrabar sequence, so we cannot claim the limit was
      // reachable after the stop printed within the same minute.
      return { action: "trigger" };
    }

    return this._evaluateLimit(order, open, high, low);
  }

  // The two legs of a bracket, created once its entry order fills. They start
  // eligible on the *next* bar, never the one that just filled the entry — the
  // same rule a triggered stop-limit follows, for the same reason: nothing here
  // gets to act on a move it wasn't resting for.
  _bracketLegs(entry, t, filledAtTs) {
    const legs = [];
    const exitSide = entry.side === "buy" ? "sell" : "buy";
    const bracketId = entry.id;
    if (entry.take_profit_price != null) {
      legs.push({
        id: crypto.randomUUID(),
        sequence: t.nextOrderSequence++,
        type: "limit",
        side: exitSide,
        quantity: entry.quantity,
        limit_price: entry.take_profit_price,
        stop_price: null,
        status: "working",
        requested_at_ts: filledAtTs,
        triggered_at_ts: null,
        take_profit_price: null,
        stop_loss_price: null,
        oco_group: bracketId,
        bracket_role: "take_profit",
      });
    }
    if (entry.stop_loss_price != null) {
      legs.push({
        id: crypto.randomUUID(),
        sequence: t.nextOrderSequence++,
        type: "stop",
        side: exitSide,
        quantity: entry.quantity,
        limit_price: null,
        stop_price: entry.stop_loss_price,
        status: "working",
        requested_at_ts: filledAtTs,
        triggered_at_ts: null,
        take_profit_price: null,
        stop_loss_price: null,
        oco_group: bracketId,
        bracket_role: "stop_loss",
      });
    }
    return legs;
  }

  async _fillPendingOrders(bar) {
    const t = this._trading();
    if (!t.pendingOrders.length) return;

    const rank = (order) => ORDER_EVAL_RANK[order.type ?? "market"] ?? 1;
    const queue = t.pendingOrders
      .map((order, index) => ({ order, index }))
      .sort((a, b) => (rank(a.order) - rank(b.order))
        || (Number(a.order.sequence ?? 0) - Number(b.order.sequence ?? 0))
        || (a.index - b.index));

    const filled = new Set();
    const cancelled = new Set();
    const fills = [];
    const triggered = [];
    const ocoCancelled = [];
    const bracketLegs = [];
    for (const { order } of queue) {
      if (filled.has(order.id) || cancelled.has(order.id)) continue;
      const outcome = this._evaluateOrder(order, bar);
      if (outcome.action === "rest") continue;
      if (outcome.action === "trigger") {
        order.status = "triggered";
        order.triggered_at_ts = Number(bar.t);
        triggered.push({ ...order });
        continue;
      }
      const fill = this._applyFill(order, outcome.price, Number(bar.t), outcome.marketable === true);
      filled.add(order.id);
      fills.push(fill);
      t.fills.push(fill);

      // One-cancels-other: a fill on either bracket leg cancels its sibling.
      // Only a fill triggers this — manually cancelling one leg leaves the other
      // working, same as most brokers, so a bracket can be pared down on purpose.
      if (order.oco_group) {
        for (const sibling of t.pendingOrders) {
          if (sibling.id === order.id || sibling.oco_group !== order.oco_group) continue;
          if (filled.has(sibling.id) || cancelled.has(sibling.id)) continue;
          sibling.status = "cancelled";
          cancelled.add(sibling.id);
          ocoCancelled.push({ ...sibling });
        }
      }

      if (order.take_profit_price != null || order.stop_loss_price != null) {
        bracketLegs.push(...this._bracketLegs(order, t, Number(bar.t)));
      }
    }

    if (!fills.length && !triggered.length && !bracketLegs.length) return;

    if (filled.size || cancelled.size) {
      t.pendingOrders = t.pendingOrders.filter((order) => !filled.has(order.id) && !cancelled.has(order.id));
    }
    if (bracketLegs.length) t.pendingOrders.push(...bracketLegs);

    for (const fill of fills) {
      await this._persistFill(fill);
      await this._persistOrderStatus(fill.order_id, "filled");
    }
    for (const order of triggered) await this._persistOrderStatus(order.id, "triggered", order.triggered_at_ts);
    for (const order of ocoCancelled) await this._persistOrderStatus(order.id, "cancelled");
    for (const leg of bracketLegs) await this._persistOrder(leg);
    await this._persistTradingSummary();

    const snapshot = this._accountSnapshot();
    if (triggered.length) this._broadcast({ type: "orders_triggered", orders: triggered, trading: snapshot });
    if (bracketLegs.length) this._broadcast({ type: "bracket_attached", orders: bracketLegs, trading: snapshot });
    if (ocoCancelled.length) this._broadcast({ type: "orders_cancelled", orders: ocoCancelled, reason: "oco", trading: snapshot });
    if (fills.length) this._broadcast({ type: "fills", fills, trading: snapshot });
  }

  _applyFill(order, price, filledAt, marketable = true) {
    const t = this._trading();
    const spec = this._spec();
    // Costs are accounted in their own buckets rather than folded into the fill
    // price, because total_pnl already subtracts them and the average price stays
    // readable as the price the trade actually printed at.
    const commission = spec.commissionPerSide * order.quantity;
    const slippage = marketable
      ? spec.slippageTicks * spec.tickSize * spec.pointValue * order.quantity
      : 0;
    t.commission += commission;
    t.slippage += slippage;
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

    return {
      id: crypto.randomUUID(),
      sequence: t.nextSequence++,
      order_id: order.id,
      order_type: order.type ?? "market",
      bracket_role: order.bracket_role ?? null,
      side: order.side,
      quantity: order.quantity,
      limit_price: order.limit_price ?? null,
      stop_price: order.stop_price ?? null,
      requested_at_ts: order.requested_at_ts,
      filled_at_ts: filledAt,
      fill_price: price,
      realized_delta: realizedDelta,
      position_after: t.positionQty,
      avg_price_after: t.avgPrice,
      commission,
      slippage,
    };
  }

  async _persistOrder(order) {
    if (!this.env.DB || !this.session) return;
    try {
      await this.env.DB.prepare(`
        INSERT INTO trade_orders
          (id, replay_session_id, sequence, order_type, side, quantity, limit_price, stop_price, status, requested_at_ts, triggered_at_ts, take_profit_price, stop_loss_price, oco_group, bracket_role, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        order.id,
        this.session.id,
        order.sequence,
        order.type,
        order.side,
        order.quantity,
        order.limit_price,
        order.stop_price,
        order.status,
        order.requested_at_ts,
        order.triggered_at_ts,
        order.take_profit_price ?? null,
        order.stop_loss_price ?? null,
        order.oco_group ?? null,
        order.bracket_role ?? null,
        new Date().toISOString(),
        new Date().toISOString(),
      ).run();
    } catch (error) {
      console.error("D1 order persistence failed", error);
    }
  }

  async _persistOrderStatus(orderId, status, triggeredAt = null) {
    if (!this.env.DB || !this.session || !orderId) return;
    try {
      await this.env.DB.prepare(`
        UPDATE trade_orders
        SET status = ?, triggered_at_ts = COALESCE(?, triggered_at_ts), updated_at = ?
        WHERE id = ? AND replay_session_id = ?
      `).bind(status, triggeredAt, new Date().toISOString(), orderId, this.session.id).run();
    } catch (error) {
      console.error("D1 order status persistence failed", error);
    }
  }

  async _persistFill(fill) {
    if (!this.env.DB) return;
    try {
      await this.env.DB.prepare(`
        INSERT INTO trade_fills
          (id, replay_session_id, sequence, order_id, order_type, side, quantity, limit_price, stop_price, requested_at_ts, filled_at_ts, fill_price, realized_delta, commission, slippage, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        fill.id,
        this.session.id,
        fill.sequence,
        fill.order_id,
        fill.order_type,
        fill.side,
        fill.quantity,
        fill.limit_price,
        fill.stop_price,
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
        this.env.DB.prepare("DELETE FROM trade_orders WHERE replay_session_id = ?").bind(this.session.id),
        this.env.DB.prepare("DELETE FROM simulation_accounts WHERE replay_session_id = ?").bind(this.session.id),
      ]);
    } catch (error) {
      console.error("D1 trading reset failed", error);
    }
  }

  // Persists the current replay cursor and full trading record as the single
  // resumable save for a user, overwriting any prior save (ON CONFLICT). Only
  // one slot is supported, per the product requirement.
  async save(userId) {
    if (!this.session || !this.shard) throw new Error("Session not initialized");
    if (!this.env.DB) throw new Error("Saving is unavailable");
    const ownerId = Number(userId) || null;
    if (this.session.userId && ownerId && Number(this.session.userId) !== ownerId) {
      throw new Error("Not authorized to save this session");
    }
    if (!ownerId && !this.session.userId) throw new Error("A user is required to save a session");
    const bar = this.shard[this.session.barIndex];
    const cursorTs = Number(bar?.t ?? this.session.startTs);
    const t = this._trading();
    const trading = {
      positionQty: t.positionQty,
      avgPrice: t.avgPrice,
      realizedPnl: t.realizedPnl,
      commission: t.commission,
      slippage: t.slippage,
      pendingOrders: t.pendingOrders.map((order) => ({ ...order })),
      fills: t.fills.map((fill) => ({ ...fill })),
      nextSequence: t.nextSequence,
      nextOrderSequence: t.nextOrderSequence,
    };
    const savedAt = new Date().toISOString();
    await this.env.DB.prepare(`
      INSERT INTO saved_sessions
        (user_id, product, contract, contract_selection, start_ts, cursor_ts, warmup, trading, saved_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(user_id) DO UPDATE SET
        product=excluded.product,
        contract=excluded.contract,
        contract_selection=excluded.contract_selection,
        start_ts=excluded.start_ts,
        cursor_ts=excluded.cursor_ts,
        warmup=excluded.warmup,
        trading=excluded.trading,
        saved_at=excluded.saved_at
    `).bind(
      ownerId ?? this.session.userId,
      this.session.product,
      this.session.contract,
      this.session.contractSelection ? JSON.stringify(this.session.contractSelection) : null,
      this.session.startTs,
      cursorTs,
      this.session.warmup,
      JSON.stringify(trading),
      savedAt,
    ).run();
    return { ok: true, saved_at: savedAt, cursor_ts: cursorTs };
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
