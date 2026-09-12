(() => {
  const $ = (id) => document.getElementById(id);
  const DISPLAY_TIME_ZONE = "America/New_York";
  let speed = 1;
  let sessionId = null;
  let ws = null;
  let lastState = "STOPPED";

  const zonedPartsFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"});
  const statusFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23", timeZoneName:"short"});
  const axisFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23"});

  function partsAt(date){const parts=Object.fromEntries(zonedPartsFormatter.formatToParts(date).filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));return {year:+parts.year,month:+parts.month,day:+parts.day,hour:+parts.hour,minute:+parts.minute,second:+parts.second}}
  function wallTimeToUtcIso(raw){const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(raw);if(!m)throw new Error("Invalid replay start time");const wanted={year:+m[1],month:+m[2],day:+m[3],hour:+m[4],minute:+m[5],second:0};const wall=Date.UTC(wanted.year,wanted.month-1,wanted.day,wanted.hour,wanted.minute,0);let guess=wall;for(let i=0;i<4;i++){const shown=partsAt(new Date(guess));const shownWall=Date.UTC(shown.year,shown.month-1,shown.day,shown.hour,shown.minute,shown.second);const d=wall-shownWall;guess+=d;if(d===0)break}return new Date(guess).toISOString()}
  function inputValueFromSeconds(seconds){const p=partsAt(new Date(seconds*1000)),pad=n=>String(n).padStart(2,"0");return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`}
  function displaySeconds(seconds){return statusFormatter.format(new Date(seconds*1000))}
  function epochMs(time){if(typeof time==="number")return time*1000;if(typeof time==="string")return Date.parse(time);return Date.UTC(time.year,time.month-1,time.day)}

  const T=getComputedStyle(document.documentElement);
  const cssVar=(name,fallback)=>(T.getPropertyValue(name)||fallback).trim();
  const chart=LightweightCharts.createChart($("chart"),{autoSize:true,attributionLogo:true,layout:{background:{type:"solid",color:cssVar("--chart-bg","#090e15")},textColor:cssVar("--chart-text","#aab5c5")},grid:{vertLines:{color:cssVar("--chart-grid","#17202d")},horzLines:{color:cssVar("--chart-grid","#17202d")}},crosshair:{mode:LightweightCharts.CrosshairMode.Magnet},localization:{timeFormatter:t=>statusFormatter.format(new Date(epochMs(t)))},timeScale:{timeVisible:true,secondsVisible:false,tickMarkFormatter:t=>axisFormatter.format(new Date(epochMs(t)))}});
  const candles=chart.addSeries(LightweightCharts.CandlestickSeries,{upColor:cssVar("--chart-up","#26a69a"),downColor:cssVar("--chart-down","#ef5350"),borderVisible:false,wickUpColor:cssVar("--chart-up","#26a69a"),wickDownColor:cssVar("--chart-down","#ef5350")});
  const volume=chart.addSeries(LightweightCharts.HistogramSeries,{priceFormat:{type:"volume"},priceScaleId:"volume"});volume.priceScale().applyOptions({scaleMargins:{top:.8,bottom:0}});
  const chartTools=new window.FutureViewChartTools({chart,candles,volume,toolbar:$("chart-toolbar"),legend:$("chart-legend"),container:$("chart"),formatTime:displaySeconds});
  const candle=b=>({time:b.t,open:b.o,high:b.h,low:b.l,close:b.c}),vol=b=>({time:b.t,value:b.v,color:b.c>=b.o?"rgba(38,166,154,.46)":"rgba(239,83,80,.46)"});
  function render(b){candles.update(candle(b));volume.update(vol(b));chartTools.append(b)}function renderMany(bs){bs.forEach(b=>{candles.update(candle(b));volume.update(vol(b))});chartTools.appendMany(bs)}function reset(bs){candles.setData(bs.map(candle));volume.setData(bs.map(vol));chartTools.reset(bs);chart.timeScale().fitContent()}function error(m=""){$("error").textContent=m}
  async function api(path,opts={}){const r=await fetch(path,{headers:{"Content-Type":"application/json"},...opts});if(!r.ok){let m=`HTTP ${r.status}`;try{m=(await r.json()).error||m}catch{}throw new Error(m)}return r.json()}
  function update(s){if(!s)return;lastState=s.state||lastState;$("state-status").textContent=lastState;$("contract-status").textContent=s.contract||$("contract-status").textContent;$("time-status").textContent=s.cursor?displaySeconds(s.cursor):"No session";$("play").disabled=!sessionId||lastState==="PLAYING";$("pause").disabled=!sessionId||lastState!=="PLAYING";$("next").disabled=!sessionId||lastState==="PLAYING"||lastState==="FINISHED";$("restart").disabled=!sessionId}
  function command(type,extra={}){if(!ws||ws.readyState!==WebSocket.OPEN){error("Replay socket is not connected");return}ws.send(JSON.stringify({type,...extra}))}
  function connect(path){if(ws)ws.close();const proto=location.protocol==="https:"?"wss":"ws";ws=new WebSocket(`${proto}://${location.host}${path}`);ws.onmessage=e=>{const x=JSON.parse(e.data);if(x.type==="bar")render(x.bar);else if(x.type==="bars_batch")renderMany(x.bars);else if(x.type==="reset"){reset(x.warmup||[]);update(x.snapshot)}else if(x.type==="error")error(x.error);else update(x)};ws.onerror=()=>error("Replay WebSocket disconnected")}
  async function loadRange(){const x=await api("/api/replay/range");$("product").value=x.product;$("start").value=inputValueFromSeconds(x.first_time);$("range").textContent=`${displaySeconds(x.first_time)} → ${displaySeconds(x.last_time)} · contract selected automatically`}
  $("start-btn").onclick=async()=>{try{error();const raw=$("start").value;if(!raw)throw new Error("Choose a start time");const x=await api("/api/replay/sessions",{method:"POST",body:JSON.stringify({product:$("product").value,start:wallTimeToUtcIso(raw),warmup:Number($("warmup").value||300)})});sessionId=x.session_id;reset(x.warmup||[]);update(x);const selected=x.contract_selection;if(selected)$("range").textContent=`Selected ${selected.contract} from ${selected.source_session||"the first available session"} (${selected.reason})`;connect(x.websocket)}catch(e){error(e.message)}};
  $("play").onclick=()=>command("play",{speed});$("pause").onclick=()=>command("pause");$("next").onclick=()=>command("step");$("restart").onclick=()=>command("restart");$("speeds").onclick=e=>{const b=e.target.closest("button[data-speed]");if(!b)return;document.querySelectorAll("#speeds button").forEach(x=>x.classList.remove("active"));b.classList.add("active");speed=b.dataset.speed==="max"?"max":Number(b.dataset.speed);if(lastState==="PLAYING")command("play",{speed})};loadRange().catch(e=>error(e.message));update({state:"STOPPED"});
})();
