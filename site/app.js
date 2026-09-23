(() => {
  const $ = (id) => document.getElementById(id);
  const DISPLAY_TIME_ZONE = "America/New_York";
  const API_ORIGIN = "https://futureview.rueijrwu.workers.dev";
  const TOKEN_KEY = "futureview_auth_token";
  const USER_KEY = "futureview_auth_user";
  const DEFAULT_REPLAY_TIME = "08:30";
  let speed = 1;
  let sessionId = null;
  let ws = null;
  let wsOpen = false;
  let wsSynced = false;
  let wsPath = null;
  let wsReconnectTimer = null;
  let wsReconnectDelay = 1000;
  let commandAckTimer = null;
  let pendingCommand = null;
  let lastState = "STOPPED";
  let lastTrading = null;
  let lastMarkPrice = null;
  let lastMarkTs = null;
  let selectedFillId = null;
  let hasSavedSession = false;
  let savedSessionLoaded = false;
  let lastMarkerSignature = null;
  let consoleEvents = [];
  const consoleOrderIds = new Set();
  const consoleFillIds = new Set();
  const consoleTriggerIds = new Set();
  const ORDER_TYPE_LABELS = {market:"Market",limit:"Limit",stop:"Stop",stop_limit:"Stop limit"};
  const orderPriceLines = new Map();

  function token(){return localStorage.getItem(TOKEN_KEY)||""}
  function clearAuth(){localStorage.removeItem(TOKEN_KEY);localStorage.removeItem(USER_KEY)}
  function goLogin(){clearAuth();location.replace("/login.html")}

  const zonedPartsFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"});
  const statusFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23", timeZoneName:"short"});
  const axisFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23"});
  function partsAt(date){const parts=Object.fromEntries(zonedPartsFormatter.formatToParts(date).filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));return {year:+parts.year,month:+parts.month,day:+parts.day,hour:+parts.hour,minute:+parts.minute,second:+parts.second}}
  function wallTimeToUtcIso(raw){const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(raw);if(!m)throw new Error("Invalid replay start time");const wanted={year:+m[1],month:+m[2],day:+m[3],hour:+m[4],minute:+m[5],second:0};const wall=Date.UTC(wanted.year,wanted.month-1,wanted.day,wanted.hour,wanted.minute,0);let guess=wall;for(let i=0;i<4;i++){const shown=partsAt(new Date(guess));const shownWall=Date.UTC(shown.year,shown.month-1,shown.day,shown.hour,shown.minute,shown.second);const d=wall-shownWall;guess+=d;if(d===0)break}return new Date(guess).toISOString()}
  function displaySeconds(seconds){return statusFormatter.format(new Date(seconds*1000))}
  function epochMs(time){if(typeof time==="number")return time*1000;if(typeof time==="string")return Date.parse(time);return Date.UTC(time.year,time.month-1,time.day)}
  function money(value){const n=Number(value)||0;return `${n<0?"-":""}$${Math.abs(n).toFixed(2)}`}
  function number(value){return Number.isFinite(Number(value))?Number(value).toFixed(2):"—"}
  function sessionAtDefaultTime(info){
    const sessions=Array.isArray(info?.sessions)?info.sessions.filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x)):[];
    for(const day of sessions){const value=`${day}T${DEFAULT_REPLAY_TIME}`;try{const ms=Date.parse(wallTimeToUtcIso(value));if(ms>=Number(info.first_time)*1000&&ms<=Number(info.last_time)*1000)return value}catch{}}
    if(sessions.length)return `${sessions[0]}T${DEFAULT_REPLAY_TIME}`;
    const p=partsAt(new Date(Number(info.first_time)*1000)),pad=n=>String(n).padStart(2,"0");
    return `${p.year}-${pad(p.month)}-${pad(p.day)}T${DEFAULT_REPLAY_TIME}`;
  }

  const T=getComputedStyle(document.documentElement);
  const cssVar=(name,fallback)=>(T.getPropertyValue(name)||fallback).trim();
  const chart=LightweightCharts.createChart($("chart"),{autoSize:true,attributionLogo:true,layout:{background:{type:"solid",color:cssVar("--chart-bg","#090e15")},textColor:cssVar("--chart-text","#aab5c5")},grid:{vertLines:{color:cssVar("--chart-grid","#17202d")},horzLines:{color:cssVar("--chart-grid","#17202d")}},crosshair:{mode:LightweightCharts.CrosshairMode.Magnet},localization:{timeFormatter:t=>statusFormatter.format(new Date(epochMs(t)))},timeScale:{timeVisible:true,secondsVisible:false,shiftVisibleRangeOnNewBar:false,tickMarkFormatter:t=>axisFormatter.format(new Date(epochMs(t)))}});
  const candles=chart.addSeries(LightweightCharts.CandlestickSeries,{upColor:cssVar("--chart-up","#26a69a"),downColor:cssVar("--chart-down","#ef5350"),borderVisible:false,wickUpColor:cssVar("--chart-up","#26a69a"),wickDownColor:cssVar("--chart-down","#ef5350")});
  const volume=chart.addSeries(LightweightCharts.HistogramSeries,{priceFormat:{type:"volume"},priceScaleId:"volume"});volume.priceScale().applyOptions({scaleMargins:{top:.8,bottom:0}});
  const tradeMarkers=typeof LightweightCharts.createSeriesMarkers==="function"?LightweightCharts.createSeriesMarkers(candles,[]):null;
  const chartTools=new window.FutureViewChartTools({chart,candles,volume,toolbar:$("chart-toolbar"),legend:$("chart-legend"),container:$("chart"),formatTime:displaySeconds});
  const candle=b=>({time:b.t,open:b.o,high:b.h,low:b.l,close:b.c}),vol=b=>({time:b.t,value:b.v,color:b.c>=b.o?"rgba(38,166,154,.46)":"rgba(239,83,80,.46)"});

  function preserveChartViewport(mutator){
    const ts=chart.timeScale();
    const logical=ts.getVisibleLogicalRange?.()||null;
    const time=logical?null:(ts.getVisibleRange?.()||null);
    mutator();
    const restore=()=>{try{if(logical&&typeof ts.setVisibleLogicalRange==="function")ts.setVisibleLogicalRange(logical);else if(time)ts.setVisibleRange(time)}catch{}};
    restore();
    requestAnimationFrame(restore);
  }

  function renderConsole(){
    const el=$("trade-detail");
    if(!consoleEvents.length){el.textContent="No trading activity yet.";return;}
    el.textContent=consoleEvents.map((x,i)=>`${String(i+1).padStart(2,"0")}  ${x}`).join("\n");
    el.scrollTop=el.scrollHeight;
  }
  function appendConsole(text){consoleEvents.push(text);renderConsole()}
  function clearConsole(){consoleEvents=[];consoleOrderIds.clear();consoleFillIds.clear();consoleTriggerIds.clear();renderConsole()}
  const BRACKET_ROLE_LABELS = {take_profit:"Take profit", stop_loss:"Stop loss"};
  // A bracket leg is reported under its role (Take profit / Stop loss), not its
  // underlying order type (limit / stop) — the role is what the user placed and
  // what they will recognize, the type is just how it is evaluated internally.
  function orderTypeLabel(order){
    if(order?.bracket_role)return BRACKET_ROLE_LABELS[order.bracket_role]||orderTypeLabelForType(order?.type);
    return orderTypeLabelForType(order?.type);
  }
  function orderTypeLabelForType(type){return ORDER_TYPE_LABELS[type||"market"]||"Market"}
  function hasBracket(order){return order&&(order.take_profit_price!=null||order.stop_loss_price!=null)}
  function bracketSummary(order){
    if(!hasBracket(order))return "";
    const parts=[];
    if(order.take_profit_price!=null)parts.push(`TP ${number(order.take_profit_price)}`);
    if(order.stop_loss_price!=null)parts.push(`SL ${number(order.stop_loss_price)}`);
    return parts.join(" / ");
  }
  // full: both legs of a stop-limit, for the console and the row tooltip. Without
  // it the row shows only the price the order is waiting for right now, which is
  // the one drawn on the chart. A bracket entry appends its attached legs, since
  // those do not show up anywhere else until the entry fills.
  // The compact form is what a row shows; the full form (tooltip, console) also
  // spells out a stop-limit's other leg and a bracket entry's attached prices,
  // which is too much text for a table cell but exactly what a hover wants.
  function orderPriceText(order,full=false){
    if(!order)return "";
    let base;
    if(order.type==="limit")base=`limit ${number(order.limit_price)}`;
    else if(order.type==="stop")base=`stop ${number(order.stop_price)}`;
    else if(order.type==="stop_limit"){
      base=full?`stop ${number(order.stop_price)} → limit ${number(order.limit_price)}`
        :(order.status==="triggered"?`limit ${number(order.limit_price)}`:`stop ${number(order.stop_price)}`);
    }else base="next bar open";
    if(!full)return base;
    const bracket=bracketSummary(order);
    return bracket?`${base} · ${bracket}`:base;
  }
  function recordAcceptedOrder(order){
    if(!order||consoleOrderIds.has(order.id))return;
    consoleOrderIds.add(order.id);
    appendConsole(`${displaySeconds(order.requested_at_ts)}  ORDER  ${orderTypeLabel(order).toUpperCase()} ${String(order.side).toUpperCase()} ${order.quantity} ${lastTrading?.contract||""}  ${orderPriceText(order,true)}`);
  }
  function recordCancelledOrder(order){
    if(!order)return;
    appendConsole(`${displaySeconds(lastMarkTs ?? order.requested_at_ts)}  CANCEL ${orderTypeLabel(order).toUpperCase()} ${String(order.side).toUpperCase()} ${order.quantity}  ${orderPriceText(order,true)}`);
  }
  function recordTriggeredOrders(orders){
    for(const order of orders||[]){
      if(consoleTriggerIds.has(order.id))continue;
      consoleTriggerIds.add(order.id);
      appendConsole(`${displaySeconds(order.triggered_at_ts)}  TRIGGER ${String(order.side).toUpperCase()} ${order.quantity}  stop ${number(order.stop_price)} hit, now working as limit ${number(order.limit_price)}`);
    }
  }
  const consoleBracketIds = new Set();
  function recordAttachedBracket(orders){
    for(const order of orders||[]){
      if(consoleBracketIds.has(order.id))continue;
      consoleBracketIds.add(order.id);
      appendConsole(`${displaySeconds(order.requested_at_ts)}  BRACKET ${orderTypeLabel(order).toUpperCase()} ${String(order.side).toUpperCase()} ${order.quantity}  ${orderPriceText(order,true)} attached`);
    }
  }
  function recordOcoCancelled(orders){
    for(const order of orders||[]){
      appendConsole(`${displaySeconds(lastMarkTs ?? order.requested_at_ts)}  CANCEL ${orderTypeLabel(order).toUpperCase()} ${String(order.side).toUpperCase()} ${order.quantity}  ${orderPriceText(order,true)} · OCO, other leg filled`);
    }
  }
  function recordSessionEndCancelled(orders){
    for(const order of orders||[]){
      appendConsole(`${displaySeconds(lastMarkTs ?? order.requested_at_ts)}  CANCEL ${orderTypeLabel(order).toUpperCase()} ${String(order.side).toUpperCase()} ${order.quantity}  ${orderPriceText(order,true)} · session end`);
    }
  }
  function syncFillConsole(trading){
    for(const f of trading?.fills||[]){
      if(consoleFillIds.has(f.id))continue;
      consoleFillIds.add(f.id);
      const after=Number(f.position_after)===0?"Flat":`${Number(f.position_after)>0?"Long":"Short"} ${Math.abs(Number(f.position_after))} @ ${number(f.avg_price_after)}`;
      const label=f.bracket_role?BRACKET_ROLE_LABELS[f.bracket_role]?.toUpperCase()||"FILL":"FILL";
      appendConsole(`${displaySeconds(f.filled_at_ts)}  ${label.padEnd(6)} ${String(f.side).toUpperCase()} ${f.quantity} ${trading?.contract||""} @ ${number(f.fill_price)}  realized ${money(f.realized_delta)}  → ${after}`);
    }
  }

  function applyPnlClass(el,value){el.classList.toggle("pnl-positive",Number(value)>0);el.classList.toggle("pnl-negative",Number(value)<0)}
  function derivedTrading(){
    if(!lastTrading)return null;
    const t={...lastTrading};
    if(Number(t.position_qty)!==0&&Number.isFinite(Number(lastMarkPrice))){t.unrealized_pnl=(Number(lastMarkPrice)-Number(t.avg_price))*Number(t.position_qty)*Number(t.point_value||0);t.total_pnl=Number(t.realized_pnl||0)+t.unrealized_pnl-Number(t.commission||0)-Number(t.slippage||0)}
    return t;
  }
  function renderTradeMarkers(){
    if(!tradeMarkers)return;
    const fills=lastTrading?.fills||[];
    const signature=fills.map(f=>`${f.id}:${f.filled_at_ts}:${f.side}:${f.quantity}`).join("|");
    if(signature===lastMarkerSignature)return;
    lastMarkerSignature=signature;
    preserveChartViewport(()=>{tradeMarkers.setMarkers(fills.map(f=>({time:Number(f.filled_at_ts),position:f.side==="buy"?"belowBar":"aboveBar",color:f.side==="buy"?cssVar("--chart-up","#26a69a"):cssVar("--chart-down","#ef5350"),shape:f.side==="buy"?"arrowUp":"arrowDown",text:`${f.side==="buy"?"B":"S"}${f.quantity}`,id:f.id,size:1}))) });
  }
  // A new bar can only change the P&L/mark fields: unrealized P&L, total P&L and
  // the mark price they derive from. It cannot add or remove a working order, a
  // fill or a console line, so rebuilding the record table and re-serialising the
  // console on every bar (as low as once a second at 1x) was pure waste. Split the
  // two and gate the record rebuild on a signature, the same pattern
  // renderTradeMarkers already uses for the chart markers.
  let lastRecordSignature=null;
  function recordSignature(orders,fills){
    return orders.map(o=>`${o.id}:${o.status}:${o.limit_price}:${o.stop_price}`).join("|")
      +"#"+fills.map(f=>f.id).join("|")
      +"#"+selectedFillId;
  }
  function renderPnl(t){
    if(!t){
      $("trade-position").textContent="Flat";$("trade-avg").textContent="—";$("trade-unrealized").textContent="$0.00";$("trade-realized").textContent="$0.00";$("trade-costs").textContent="$0.00";$("trade-total").textContent="$0.00";
      return;
    }
    const qty=Number(t.position_qty)||0;
    $("trade-position").textContent=qty===0?"Flat":`${qty>0?"Long":"Short"} ${Math.abs(qty)}`;
    $("trade-avg").textContent=qty===0?"—":number(t.avg_price);
    $("trade-unrealized").textContent=money(t.unrealized_pnl);applyPnlClass($("trade-unrealized"),t.unrealized_pnl);
    $("trade-realized").textContent=money(t.realized_pnl);applyPnlClass($("trade-realized"),t.realized_pnl);
    // Commission and slippage are charged in their own buckets, so the cost of
    // trading is visible instead of hidden inside the average price.
    const costs=Number(t.commission||0)+Number(t.slippage||0);
    $("trade-costs").textContent=costs?`−${money(costs).replace("-","")}`:"$0.00";
    $("trade-costs").title=`Commission ${money(t.commission||0)} · slippage ${money(t.slippage||0)}`;
    $("trade-total").textContent=money(t.total_pnl);applyPnlClass($("trade-total"),t.total_pnl);
  }

  // A working order is drawn on the chart at the price it is waiting for: the stop
  // until it triggers, the limit once it does.
  function orderActivePrice(order){
    if(order.type==="limit")return Number(order.limit_price);
    if(order.type==="stop")return Number(order.stop_price);
    if(order.type==="stop_limit")return Number(order.status==="triggered"?order.limit_price:order.stop_price);
    return null;
  }
  function syncOrderPriceLines(orders){
    const live=new Set();
    for(const order of orders){
      const price=orderActivePrice(order);
      if(!Number.isFinite(price))continue;
      live.add(order.id);
      const existing=orderPriceLines.get(order.id);
      if(existing&&existing.price===price)continue;
      if(existing){try{candles.removePriceLine(existing.line)}catch{}}
      try{
        const line=candles.createPriceLine({
          price,
          color:order.side==="buy"?cssVar("--chart-up","#26a69a"):cssVar("--chart-down","#ef5350"),
          lineWidth:1,
          lineStyle:2,
          axisLabelVisible:true,
          title:`${orderTypeLabel(order)} ${order.side==="buy"?"B":"S"}${order.quantity}`,
        });
        orderPriceLines.set(order.id,{price,line});
      }catch{}
    }
    for(const [id,entry] of orderPriceLines){
      if(live.has(id))continue;
      try{candles.removePriceLine(entry.line)}catch{}
      orderPriceLines.delete(id);
    }
  }

  // Working orders and fills share one table: the orders are what you can still
  // act on, so they sit on top, and the fills are the history underneath.
  function orderRow(o){
    const mark=o.status==="triggered"?"▸":(o.oco_group?"⇄":(hasBracket(o)?"◎":"○"));
    const markTitle=o.status==="triggered"?"Stop triggered, working as a limit"
      :o.oco_group?"Bracket leg — filling this cancels its sibling"
      :hasBracket(o)?`Bracket entry — attaches ${bracketSummary(o)} once filled`
      :"Working order";
    return `<tr class="order-row${o.status==="triggered"?" triggered":""}${o.oco_group?" bracket-leg":""}">`
      +`<td class="order-mark" title="${markTitle}">${mark}</td>`
      +`<td class="order-type">${orderTypeLabel(o)}</td>`
      +`<td class="${o.side==="buy"?"buy-text":"sell-text"}">${o.side==="buy"?"Buy":"Sell"}</td>`
      +`<td>${o.quantity}</td>`
      +`<td class="order-price" title="${orderPriceText(o,true)}">${orderPriceText(o)}</td>`
      +`<td><button type="button" class="order-cancel" data-order-id="${o.id}" title="Cancel this order">✕</button></td>`
      +`</tr>`;
  }
  function fillRow(f){
    return `<tr class="trade-row${selectedFillId===f.id?" selected":""}" data-fill-id="${f.id}">`
      +`<td>${f.sequence}</td>`
      +`<td>${ORDER_TYPE_LABELS[f.order_type||"market"]||"Market"}</td>`
      +`<td class="${f.side==="buy"?"buy-text":"sell-text"}">${f.side==="buy"?"Buy":"Sell"}</td>`
      +`<td>${f.quantity}</td>`
      +`<td>${number(f.fill_price)}</td>`
      +`<td class="${Number(f.realized_delta)>0?"pnl-positive":Number(f.realized_delta)<0?"pnl-negative":""}">${money(f.realized_delta)}</td>`
      +`</tr>`;
  }
  function renderRecordAndConsole(t){
    const orders=t?.pending_orders||[];
    const fills=t?.fills||[];
    const signature=recordSignature(orders,fills);
    if(signature===lastRecordSignature)return;
    lastRecordSignature=signature;
    $("trades-toggle").textContent=orders.length
      ?`Trades ${fills.length} · ${orders.length} working`
      :(fills.length?`Trades ${fills.length}`:"Trades");
    $("trade-rows").innerHTML=(orders.length||fills.length)
      ?orders.map(orderRow).join("")+fills.map(fillRow).join("")
      :'<tr class="trade-empty"><td colspan="6">No orders or trades yet</td></tr>';
    syncOrderPriceLines(orders);
    renderConsole();
  }
  function renderTrading(){
    const t=derivedTrading();
    renderPnl(t);
    renderRecordAndConsole(t);
  }
  function setTrading(trading){if(!trading)return;lastTrading=trading;syncFillConsole(trading);renderTrading();renderTradeMarkers();syncControls()}
  function inspectFill(fillId){
    const fill=(lastTrading?.fills||[]).find(f=>f.id===fillId);if(!fill)return;
    selectedFillId=fill.id;lastRecordSignature=null;renderTrading();
    const before=Number(fill.filled_at_ts)-3600,after=Number(fill.filled_at_ts)+3600;try{chart.timeScale().setVisibleRange({from:before,to:after})}catch{}
  }

  // chartTools.append/appendMany already write the display candle and volume
  // themselves (aggregated to the active bar scale via _fvEmitDisplayBar) -
  // writing the raw 1-minute bar to the series here too, on top of that, used
  // to race it: this raw write always lands *after* the aggregated bucket's
  // own time at any scale coarser than 1m, so the very next aggregated write
  // (same tick, same bucket) could land earlier than what this just set and
  // get rejected by the chart as "going backwards" - most visible right after
  // a scale switch, while bars are still streaming in live.
  function render(b){
    preserveChartViewport(()=>{chartTools.append(b)});
    lastMarkPrice=Number(b.c);lastMarkTs=Number(b.t);$("time-status").textContent=displaySeconds(b.t);renderPnl(derivedTrading());
  }
  function renderMany(bs){
    preserveChartViewport(()=>{chartTools.appendMany(bs)});
    if(bs.length){lastMarkPrice=Number(bs[bs.length-1].c);lastMarkTs=Number(bs[bs.length-1].t);$("time-status").textContent=displaySeconds(bs[bs.length-1].t);renderPnl(derivedTrading())}
  }
  function reset(bs){chartTools._cancelDrawing?.();candles.setData(bs.map(candle));volume.setData(bs.map(vol));chartTools.reset(bs);chartTools.fit();lastMarkPrice=bs.length?Number(bs[bs.length-1].c):null;lastMarkTs=bs.length?Number(bs[bs.length-1].t):null;selectedFillId=null;lastMarkerSignature=null;lastRecordSignature=null;clearConsole();renderTradeMarkers()}
  function error(m=""){$("error").textContent=m}
  async function api(path,opts={}){const authToken=token();if(!authToken)return goLogin();const r=await fetch(`${API_ORIGIN}${path}`,{headers:{"Content-Type":"application/json","Authorization":`Bearer ${authToken}`,...(opts.headers||{})},...opts});if(r.status===401)return goLogin();if(!r.ok){let m=`HTTP ${r.status}`;try{m=(await r.json()).error||m}catch{}throw new Error(m)}return r.json()}
  async function validateAuth(){const authToken=token();if(!authToken){goLogin();return false}const r=await fetch(`${API_ORIGIN}/api/auth/me`,{cache:"no-store",headers:{"Authorization":`Bearer ${authToken}`}});if(!r.ok){goLogin();return false}return true}
  async function logout(){const authToken=token();try{if(authToken)await fetch(`${API_ORIGIN}/api/auth/logout`,{method:"POST",headers:{"Authorization":`Bearer ${authToken}`}})}catch{}goLogin()}

  function syncControls(){const ready=!!sessionId&&wsOpen&&wsSynced;const busy=!!pendingCommand;const finished=lastState==="FINISHED";$("play").disabled=!ready||busy||lastState==="PLAYING"||finished;$("pause").disabled=!ready||busy||lastState!=="PLAYING";$("next").disabled=!ready||busy||lastState==="PLAYING"||finished;$("next-day").disabled=!ready||busy||lastState==="PLAYING"||finished;$("restart").disabled=!ready||busy;$("buy-btn").disabled=!ready||finished;$("sell-btn").disabled=!ready||finished;$("trade-qty").disabled=!ready||finished;$("trade-type").disabled=!ready||finished;$("trade-limit").disabled=!ready||finished;$("trade-stop").disabled=!ready||finished;$("trade-bracket").disabled=!ready||finished;$("trade-take-profit").disabled=!ready||finished;$("trade-stop-loss").disabled=!ready||finished;$("trade-clear").disabled=!ready;syncSaveButton(ready)}
  // The button reads "Resume" whenever a saved session exists and hasn't been
  // loaded into the app yet - it invites picking up where you left off. Once
  // that saved session is actually loaded (or there is nothing to resume), it
  // reads "Save", and a click there overwrites the single save slot.
  function syncSaveButton(ready){
    const btn=$("save-resume");
    const label=(!savedSessionLoaded&&hasSavedSession)?"Resume":"Save";
    btn.textContent=label;
    btn.disabled=isStarting||(label==="Save"?!ready:false);
  }
  async function refreshSavedStatus(){try{const x=await api("/api/replay/saved");hasSavedSession=!!x?.exists}catch{}syncControls()}
  async function saveOrResume(){
    const btn=$("save-resume");
    if(btn.disabled)return;
    error();
    if(!savedSessionLoaded&&hasSavedSession){
      if(isStarting)return;
      isStarting=true;$("start-btn").disabled=true;$("random-btn").disabled=true;syncControls();
      try{
        const x=await api("/api/replay/sessions/resume",{method:"POST"});
        if(!x)return;
        sessionId=x.session_id;wsSynced=false;lastTrading=x.trading||null;reset(x.warmup||[]);update(x,true);renderTrading();
        savedSessionLoaded=true;
        connect(x.websocket);
      }catch(e){error(e.message)}
      finally{isStarting=false;$("start-btn").disabled=false;$("random-btn").disabled=false;syncControls()}
      return;
    }
    if(!sessionId){error("Start a replay session before saving");return}
    btn.disabled=true;
    try{
      await api("/api/replay/sessions/save",{method:"POST",body:JSON.stringify({session_id:sessionId})});
      hasSavedSession=true;savedSessionLoaded=true;
    }catch(e){error(e.message)}
    finally{syncControls()}
  }
  function update(s,authoritative=false){if(!s)return;if(s.state)lastState=s.state;if(authoritative){wsSynced=true;pendingCommand=null;clearTimeout(commandAckTimer);commandAckTimer=null;}$("state-status").textContent=lastState;if(s.contract)$("contract-status").textContent=s.contract;if(s.cursor!=null){lastMarkTs=Number(s.cursor);$("time-status").textContent=displaySeconds(s.cursor);}else if(!sessionId)$("time-status").textContent="No session";if(s.auto_flatten_at_session_end!=null)$("auto-flatten").checked=!!s.auto_flatten_at_session_end;if(s.trading)setTrading(s.trading);syncControls()}
  function command(type,extra={}){if(!ws||ws.readyState!==WebSocket.OPEN||!wsSynced){error("Replay socket is not synchronized - reconnecting…");if(wsPath)connect(wsPath);return}pendingCommand=type;if(type==="play")lastState="PLAYING";else if(type==="pause"||type==="restart")lastState="PAUSED";update({state:lastState});ws.send(JSON.stringify({type,...extra}));clearTimeout(commandAckTimer);commandAckTimer=setTimeout(()=>{if(pendingCommand===type){pendingCommand=null;wsSynced=false;error("Replay command acknowledgement timed out - resynchronizing…");syncControls();if(wsPath)connect(wsPath)}},2000)}
  function tickSize(){const size=Number(lastTrading?.tick_size);return Number.isFinite(size)&&size>0?size:0.25}
  function readPrice(id,label){
    const raw=$(id).value;
    if(raw==="")throw new Error(`${label} is required for this order type`);
    const price=Number(raw);
    if(!Number.isFinite(price)||price<=0)throw new Error(`${label} must be a positive price`);
    const size=tickSize();
    const ticks=price/size;
    if(Math.abs(ticks-Math.round(ticks))>1e-9)throw new Error(`${label} must be a multiple of ${size}`);
    return Math.round(ticks)*size;
  }
  function syncOrderFields(){
    const type=$("trade-type").value;
    $("trade-limit-field").hidden=!(type==="limit"||type==="stop_limit");
    $("trade-stop-field").hidden=!(type==="stop"||type==="stop_limit");
    const bracket=$("trade-bracket").checked;
    $("trade-tp-field").hidden=!bracket;
    $("trade-sl-field").hidden=!bracket;
    const step=String(tickSize());
    $("trade-limit").step=step;$("trade-stop").step=step;$("trade-take-profit").step=step;$("trade-stop-loss").step=step;
  }
  function placeOrder(side){
    if(!ws||ws.readyState!==WebSocket.OPEN||!wsSynced){error("Replay socket is not synchronized");return}
    const quantity=Number($("trade-qty").value);
    if(!Number.isInteger(quantity)||quantity<1||quantity>100){error("Quantity must be an integer from 1 to 100");return}
    const order_type=$("trade-type").value;
    const payload={type:"order",order_type,side,quantity};
    try{
      if(order_type==="limit"||order_type==="stop_limit")payload.limit_price=readPrice("trade-limit","Limit price");
      if(order_type==="stop"||order_type==="stop_limit")payload.stop_price=readPrice("trade-stop","Stop price");
      if($("trade-bracket").checked){
        const tpRaw=$("trade-take-profit").value,slRaw=$("trade-stop-loss").value;
        if(tpRaw==="" && slRaw==="")throw new Error("A bracket needs a take-profit, a stop-loss, or both");
        if(tpRaw!=="")payload.take_profit_price=readPrice("trade-take-profit","Take-profit price");
        if(slRaw!=="")payload.stop_loss_price=readPrice("trade-stop-loss","Stop-loss price");
      }
    }catch(e){error(e.message);return}
    error();
    ws.send(JSON.stringify(payload));
  }
  function cancelOrder(orderId){if(!ws||ws.readyState!==WebSocket.OPEN||!wsSynced){error("Replay socket is not synchronized");return}error();ws.send(JSON.stringify({type:"cancel_order",order_id:orderId}))}
  function clearTrading(){if(!ws||ws.readyState!==WebSocket.OPEN||!wsSynced){error("Replay socket is not synchronized");return}selectedFillId=null;error();ws.send(JSON.stringify({type:"clear_trading"}))}
  function connect(path){
    wsPath=path;clearTimeout(wsReconnectTimer);clearTimeout(commandAckTimer);pendingCommand=null;wsSynced=false;syncControls();if(ws)ws.close();const authToken=token();if(!authToken)return goLogin();const wsOrigin=API_ORIGIN.replace(/^http/,"ws");const sep=path.includes("?")?"&":"?";const thisWs=ws=new WebSocket(`${wsOrigin}${path}${sep}access_token=${encodeURIComponent(authToken)}`);
    thisWs.onopen=()=>{if(ws!==thisWs)return;wsOpen=true;wsReconnectDelay=1000;error();syncControls()};
    thisWs.onmessage=e=>{
      if(ws!==thisWs)return;
      const x=JSON.parse(e.data);
      if(x.type==="bar")render(x.bar);
      else if(x.type==="bars_batch")renderMany(x.bars);
      else if(x.type==="fills"){setTrading(x.trading);error()}
      else if(x.type==="order_accepted"){recordAcceptedOrder(x.order);setTrading(x.trading);error(`${orderTypeLabel(x.order)} order accepted: ${x.order.side.toUpperCase()} ${x.order.quantity} · ${orderPriceText(x.order,true)}`)}
      else if(x.type==="order_cancelled"){recordCancelledOrder(x.order);setTrading(x.trading);error("Order cancelled")}
      else if(x.type==="orders_triggered"){recordTriggeredOrders(x.orders);setTrading(x.trading);error()}
      else if(x.type==="bracket_attached"){recordAttachedBracket(x.orders);setTrading(x.trading);error()}
      else if(x.type==="orders_cancelled"){if(x.reason==="oco")recordOcoCancelled(x.orders);else if(x.reason==="session_end")recordSessionEndCancelled(x.orders);setTrading(x.trading);error()}
      else if(x.type==="session_end_flatten"){recordSessionEndCancelled(x.cancelled_orders);setTrading(x.trading);error(x.fill?"Session ended — position flattened and resting orders cancelled":"Session ended — resting orders cancelled")}
      else if(x.type==="auto_flatten_changed"){$("auto-flatten").checked=!!x.enabled}
      else if(x.type==="trading_cleared"){clearConsole();setTrading(x.trading);error("Trading record cleared")}
      else if(x.type==="reset"){reset(x.warmup||[]);update(x.snapshot,true)}
      else if(x.type==="error"){pendingCommand=null;clearTimeout(commandAckTimer);error(x.error);syncControls()}
      else update(x,true);
    };
    thisWs.onerror=()=>{};
    thisWs.onclose=()=>{if(ws!==thisWs)return;wsOpen=false;wsSynced=false;pendingCommand=null;clearTimeout(commandAckTimer);syncControls();if(!sessionId||lastState==="FINISHED")return;error("Replay socket disconnected - reconnecting…");wsReconnectTimer=setTimeout(()=>connect(wsPath),wsReconnectDelay);wsReconnectDelay=Math.min(wsReconnectDelay*2,8000)};
  }

  let replayRangeInfo=null;
  async function loadRange(explicit=false){error();const p=$("product")?.value||"MES";try{replayRangeInfo=await api(`/api/replay/range?product=${encodeURIComponent(p)}`);if(!replayRangeInfo)return;$("start").value=sessionAtDefaultTime(replayRangeInfo);$("range").textContent=`${displaySeconds(replayRangeInfo.first_time)} → ${displaySeconds(replayRangeInfo.last_time)} · ${replayRangeInfo.sessions?.length||0} actual sessions`}catch(err){if(!explicit){try{replayRangeInfo=await api("/api/replay/range");if(!replayRangeInfo)return;if(replayRangeInfo.product&&$("product"))$("product").value=replayRangeInfo.product;$("start").value=sessionAtDefaultTime(replayRangeInfo);return}catch{}}error(err.message)}}
  function pickRandomTradingDate(info){const sessions=Array.isArray(info?.sessions)?info.sessions.filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x)):[];if(!sessions.length)throw new Error("No actual replay sessions are available for random selection");const valid=sessions.filter(day=>{try{const ms=Date.parse(wallTimeToUtcIso(`${day}T${DEFAULT_REPLAY_TIME}`));return ms>=Number(info.first_time)*1000&&ms<=Number(info.last_time)*1000}catch{return false}});const pool=valid.length?valid:sessions;return `${pool[Math.floor(Math.random()*pool.length)]}T${DEFAULT_REPLAY_TIME}`}
  let isStarting=false;
  async function startReplay(){if(isStarting)return;savedSessionLoaded=false;isStarting=true;$("start-btn").disabled=true;$("random-btn").disabled=true;try{error();const raw=$("start").value;if(!raw)throw new Error("Choose a start time");const x=await api("/api/replay/sessions",{method:"POST",body:JSON.stringify({product:$("product").value,start:wallTimeToUtcIso(raw),warmup:Number($("warmup").value||300),auto_flatten_at_session_end:$("auto-flatten").checked})});if(!x)return;sessionId=x.session_id;wsSynced=false;lastTrading=x.trading||null;reset(x.warmup||[]);update(x,true);renderTrading();const selected=x.contract_selection;if(selected)$("range").textContent=`Selected ${selected.contract} using ${selected.source_session||"fallback"} (${selected.reason})`;connect(x.websocket)}catch(e){error(e.message)}finally{isStarting=false;$("start-btn").disabled=false;$("random-btn").disabled=false}}
  $("product").onchange=()=>loadRange(true);$("start-btn").onclick=()=>startReplay();$("random-btn").onclick=async()=>{if(isStarting)return;if(!replayRangeInfo)await loadRange();try{$("start").value=pickRandomTradingDate(replayRangeInfo);await startReplay()}catch(e){error(e.message)}};
  $("auto-flatten").addEventListener("change",()=>{if(ws&&ws.readyState===WebSocket.OPEN&&wsSynced)ws.send(JSON.stringify({type:"set_auto_flatten",enabled:$("auto-flatten").checked}))});
  $("play").onclick=()=>command("play",{speed});$("pause").onclick=()=>command("pause");$("next").onclick=()=>command("step");$("next-day").onclick=()=>command("next_day");$("restart").onclick=()=>command("restart");
  const SPEED_STEPS=[1,5,10,25,50,100,"max"];
  $("speed-slider").addEventListener("input",()=>{const v=SPEED_STEPS[Number($("speed-slider").value)];$("speed-value").textContent=v==="max"?"Max":`${v}x`});
  $("speed-slider").addEventListener("change",()=>{speed=SPEED_STEPS[Number($("speed-slider").value)];if(lastState==="PLAYING"&&!pendingCommand)command("play",{speed})});
  $("buy-btn").onclick=()=>placeOrder("buy");$("sell-btn").onclick=()=>placeOrder("sell");
  $("trade-type").onchange=()=>syncOrderFields();
  $("trade-bracket").onchange=()=>syncOrderFields();
  $("trades-toggle").onclick=()=>{preserveChartViewport(()=>{const open=!$("workspace").classList.contains("trades-open");$("workspace").classList.toggle("trades-open",open);$("trades-toggle").setAttribute("aria-pressed",String(open));requestAnimationFrame(()=>chart.resize($("chart").clientWidth,$("chart").clientHeight))})};
  $("console-toggle").onclick=()=>{preserveChartViewport(()=>{const consoleEl=$("trading-console");const show=consoleEl.hidden;consoleEl.hidden=!show;$("console-toggle").setAttribute("aria-pressed",String(show));requestAnimationFrame(()=>chart.resize($("chart").clientWidth,$("chart").clientHeight))})};
  $("trade-clear").onclick=()=>clearTrading();
  $("trade-rows").onclick=e=>{
    const cancel=e.target.closest("button[data-order-id]");
    if(cancel){cancelOrder(cancel.dataset.orderId);return}
    const row=e.target.closest("tr[data-fill-id]");
    if(row)inspectFill(row.dataset.fillId);
  };
  $("logout").onclick=()=>logout();
  $("save-resume").onclick=()=>saveOrResume();

  (async()=>{if(!(await validateAuth()))return;await loadRange();update({state:"STOPPED"});syncOrderFields();renderTrading();syncControls();await refreshSavedStatus()})().catch(e=>error(e.message));
})();