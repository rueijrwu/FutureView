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
  let selectedFillId = null;
  let lastMarkerSignature = null;

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
  function sessionAtDefaultTime(info){const sessions=Array.isArray(info?.sessions)?info.sessions.filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x)):[];for(const day of sessions){const value=`${day}T${DEFAULT_REPLAY_TIME}`;try{const ms=Date.parse(wallTimeToUtcIso(value));if(ms>=Number(info.first_time)*1000&&ms<=Number(info.last_time)*1000)return value}catch{}}if(sessions.length)return `${sessions[0]}T${DEFAULT_REPLAY_TIME}`;const p=partsAt(new Date(Number(info.first_time)*1000)),pad=n=>String(n).padStart(2,"0");return `${p.year}-${pad(p.month)}-${pad(p.day)}T${DEFAULT_REPLAY_TIME}`}

  const T=getComputedStyle(document.documentElement);const cssVar=(name,fallback)=>(T.getPropertyValue(name)||fallback).trim();
  const chart=LightweightCharts.createChart($("chart"),{autoSize:true,attributionLogo:true,layout:{background:{type:"solid",color:cssVar("--chart-bg","#090e15")},textColor:cssVar("--chart-text","#aab5c5")},grid:{vertLines:{color:cssVar("--chart-grid","#17202d")},horzLines:{color:cssVar("--chart-grid","#17202d")}},crosshair:{mode:LightweightCharts.CrosshairMode.Magnet},localization:{timeFormatter:t=>statusFormatter.format(new Date(epochMs(t)))},timeScale:{timeVisible:true,secondsVisible:false,shiftVisibleRangeOnNewBar:false,tickMarkFormatter:t=>axisFormatter.format(new Date(epochMs(t)))}});
  const candles=chart.addSeries(LightweightCharts.CandlestickSeries,{upColor:cssVar("--chart-up","#26a69a"),downColor:cssVar("--chart-down","#ef5350"),borderVisible:false,wickUpColor:cssVar("--chart-up","#26a69a"),wickDownColor:cssVar("--chart-down","#ef5350")});
  const volume=chart.addSeries(LightweightCharts.HistogramSeries,{priceFormat:{type:"volume"},priceScaleId:"volume"});volume.priceScale().applyOptions({scaleMargins:{top:.8,bottom:0}});
  const tradeMarkers=typeof LightweightCharts.createSeriesMarkers==="function"?LightweightCharts.createSeriesMarkers(candles,[]):null;
  const chartTools=new window.FutureViewChartTools({chart,candles,volume,toolbar:$("chart-toolbar"),legend:$("chart-legend"),container:$("chart"),formatTime:displaySeconds});
  const candle=b=>({time:b.t,open:b.o,high:b.h,low:b.l,close:b.c}),vol=b=>({time:b.t,value:b.v,color:b.c>=b.o?"rgba(38,166,154,.46)":"rgba(239,83,80,.46)"});
  function preserveChartViewport(mutator){const ts=chart.timeScale();const logical=ts.getVisibleLogicalRange?.()||null;const time=logical?null:(ts.getVisibleRange?.()||null);mutator();const restore=()=>{try{if(logical&&typeof ts.setVisibleLogicalRange==="function")ts.setVisibleLogicalRange(logical);else if(time)ts.setVisibleRange(time)}catch{}};restore();requestAnimationFrame(restore)}
  function applyPnlClass(el,value){el.classList.toggle("pnl-positive",Number(value)>0);el.classList.toggle("pnl-negative",Number(value)<0)}
  function derivedTrading(){if(!lastTrading)return null;const t={...lastTrading};if(Number(t.position_qty)!==0&&Number.isFinite(Number(lastMarkPrice))){t.unrealized_pnl=(Number(lastMarkPrice)-Number(t.avg_price))*Number(t.position_qty)*Number(t.point_value||0);t.total_pnl=Number(t.realized_pnl||0)+t.unrealized_pnl-Number(t.commission||0)-Number(t.slippage||0)}return t}
  function renderTradeMarkers(){if(!tradeMarkers)return;const fills=lastTrading?.fills||[];const signature=fills.map(f=>`${f.id}:${f.filled_at_ts}:${f.side}:${f.quantity}`).join("|");if(signature===lastMarkerSignature)return;lastMarkerSignature=signature;preserveChartViewport(()=>{tradeMarkers.setMarkers(fills.map(f=>({time:Number(f.filled_at_ts),position:f.side==="buy"?"belowBar":"aboveBar",color:f.side==="buy"?cssVar("--chart-up","#26a69a"):cssVar("--chart-down","#ef5350"),shape:f.side==="buy"?"arrowUp":"arrowDown",text:`${f.side==="buy"?"B":"S"}${f.quantity}`,id:f.id,size:1})))})}
  function renderConsole(fills){const el=$("trade-detail");if(!fills.length){el.textContent="No trading activity yet.";return}el.textContent=fills.map(f=>`#${f.sequence}  ${displaySeconds(f.filled_at_ts)}  ${f.side.toUpperCase()} ${f.quantity} ${lastTrading?.contract||""} @ ${number(f.fill_price)}  Realized ${money(f.realized_delta)}  → ${Number(f.position_after)===0?"Flat":`${Number(f.position_after)>0?"Long":"Short"} ${Math.abs(Number(f.position_after))}`} ${Number(f.position_after)===0?"":`@ ${number(f.avg_price_after)}`}`).join("\n")}
  function renderTrading(){const t=derivedTrading();if(!t){$("trade-position").textContent="Flat";$("trade-avg").textContent="—";$("trade-unrealized").textContent="$0.00";$("trade-realized").textContent="$0.00";$("trade-total").textContent="$0.00";$("trade-rows").innerHTML='<tr class="trade-empty"><td colspan="5">No trades yet</td></tr>';$("trades-toggle").textContent="Trades";renderConsole([]);return}const qty=Number(t.position_qty)||0;$("trade-position").textContent=qty===0?"Flat":`${qty>0?"Long":"Short"} ${Math.abs(qty)}`;$("trade-avg").textContent=qty===0?"—":number(t.avg_price);$("trade-unrealized").textContent=money(t.unrealized_pnl);applyPnlClass($("trade-unrealized"),t.unrealized_pnl);$("trade-realized").textContent=money(t.realized_pnl);applyPnlClass($("trade-realized"),t.realized_pnl);$("trade-total").textContent=money(t.total_pnl);applyPnlClass($("trade-total"),t.total_pnl);const fills=t.fills||[];$("trades-toggle").textContent=fills.length?`Trades ${fills.length}`:"Trades";renderConsole(fills);if(!fills.length){$("trade-rows").innerHTML='<tr class="trade-empty"><td colspan="5">No trades yet</td></tr>';return}$("trade-rows").innerHTML=fills.map(f=>`<tr class="trade-row${selectedFillId===f.id?" selected":""}" data-fill-id="${f.id}"><td>${f.sequence}</td><td class="${f.side==="buy"?"buy-text":"sell-text"}">${f.side==="buy"?"Buy":"Sell"}</td><td>${f.quantity}</td><td>${number(f.fill_price)}</td><td class="${Number(f.realized_delta)>0?"pnl-positive":Number(f.realized_delta)<0?"pnl-negative":""}">${money(f.realized_delta)}</td></tr>`).join("")}
  function setTrading(trading){if(!trading)return;lastTrading=trading;renderTrading();renderTradeMarkers();syncControls()}
  function inspectFill(fillId){const fill=(lastTrading?.fills||[]).find(f=>f.id===fillId);if(!fill)return;selectedFillId=fill.id;renderTrading();const before=Number(fill.filled_at_ts)-3600,after=Number(fill.filled_at_ts)+3600;try{chart.timeScale().setVisibleRange({from:before,to:after})}catch{}}
  function render(b){preserveChartViewport(()=>{candles.update(candle(b));volume.update(vol(b));chartTools.append(b)});lastMarkPrice=Number(b.c);$("time-status").textContent=displaySeconds(b.t);renderTrading()}
  function renderMany(bs){preserveChartViewport(()=>{bs.forEach(b=>{candles.update(candle(b));volume.update(vol(b))});chartTools.appendMany(bs)});if(bs.length){lastMarkPrice=Number(bs[bs.length-1].c);$("time-status").textContent=displaySeconds(bs[bs.length-1].t);renderTrading()}}
  function reset(bs){chartTools._cancelDrawing?.();candles.setData(bs.map(candle));volume.setData(bs.map(vol));chartTools.reset(bs);chartTools.fit();lastMarkPrice=bs.length?Number(bs[bs.length-1].c):null;selectedFillId=null;lastMarkerSignature=null;renderTradeMarkers()}
  function error(m=""){$("error").textContent=m}
  async function api(path,opts={}){const authToken=token();if(!authToken)return goLogin();const r=await fetch(`${API_ORIGIN}${path}`,{headers:{"Content-Type":"application/json","Authorization":`Bearer ${authToken}`,...(opts.headers||{})},...opts});if(r.status===401)return goLogin();if(!r.ok){let m=`HTTP ${r.status}`;try{m=(await r.json()).error||m}catch{}throw new Error(m)}return r.json()}
  async function validateAuth(){const authToken=token();if(!authToken){goLogin();return false}const r=await fetch(`${API_ORIGIN}/api/auth/me`,{cache:"no-store",headers:{"Authorization":`Bearer ${authToken}`}});if(!r.ok){goLogin();return false}return true}
  async function logout(){const authToken=token();try{if(authToken)await fetch(`${API_ORIGIN}/api/auth/logout`,{method:"POST",headers:{"Authorization":`Bearer ${authToken}`}})}catch{}goLogin()}
  function syncControls(){const ready=!!sessionId&&wsOpen&&wsSynced;const busy=!!pendingCommand;const finished=lastState==="FINISHED";$("play").disabled=!ready||busy||lastState==="PLAYING"||finished;$("pause").disabled=!ready||busy||lastState!=="PLAYING";$("next").disabled=!ready||busy||lastState==="PLAYING"||finished;$("restart").disabled=!ready||busy;$("buy-btn").disabled=!ready||finished;$("sell-btn").disabled=!ready||finished;$("trade-qty").disabled=!ready||finished;$("trade-clear").disabled=!ready}
  function update(s,authoritative=false){if(!s)return;if(s.state)lastState=s.state;if(authoritative){wsSynced=true;pendingCommand=null;clearTimeout(commandAckTimer);commandAckTimer=null}$("state-status").textContent=lastState;if(s.contract)$("contract-status").textContent=s.contract;if(s.cursor!=null)$("time-status").textContent=displaySeconds(s.cursor);else if(!sessionId)$("time-status").textContent="No session";if(s.trading)setTrading(s.trading);syncControls()}
  function command(type,extra={}){if(!ws||ws.readyState!==WebSocket.OPEN||!wsSynced){error("Replay socket is not synchronized - reconnecting…");if(wsPath)connect(wsPath);return}pendingCommand=type;if(type==="play")lastState="PLAYING";else if(type==="pause"||type==="restart")lastState="PAUSED";update({state:lastState});ws.send(JSON.stringify({type,...extra}));clearTimeout(commandAckTimer);commandAckTimer=setTimeout(()=>{if(pendingCommand===type){pendingCommand=null;wsSynced=false;error("Replay command acknowledgement timed out - resynchronizing…");syncControls();if(wsPath)connect(wsPath)}},2000)}
  function placeOrder(side){if(!ws||ws.readyState!==WebSocket.OPEN||!wsSynced){error("Replay socket is not synchronized");return}const quantity=Number($("trade-qty").value);if(!Number.isInteger(quantity)||quantity<1||quantity>100){error("Quantity must be an integer from 1 to 100");return}error();ws.send(JSON.stringify({type:"order",side,quantity}))}
  function clearTrading(){if(!ws||ws.readyState!==WebSocket.OPEN||!wsSynced){error("Replay socket is not synchronized");return}selectedFillId=null;error();ws.send(JSON.stringify({type:"clear_trading"}))}
  function connect(path){wsPath=path;clearTimeout(wsReconnectTimer);clearTimeout(commandAckTimer);pendingCommand=null;wsSynced=false