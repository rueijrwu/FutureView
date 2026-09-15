(() => {
  const $ = (id) => document.getElementById(id);
  const DISPLAY_TIME_ZONE = "America/New_York";
  let speed = 1;
  let started = false;
  let currentState = "STOPPED";
  let commandPending = false;

  const zonedPartsFormatter = new Intl.DateTimeFormat("en-US", { timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23" });
  const statusFormatter = new Intl.DateTimeFormat("en-US", { timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23", timeZoneName:"short" });
  const axisFormatter = new Intl.DateTimeFormat("en-US", { timeZone: DISPLAY_TIME_ZONE, month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23" });

  function partsAt(date) { const parts=Object.fromEntries(zonedPartsFormatter.formatToParts(date).filter((p)=>p.type!=="literal").map((p)=>[p.type,p.value])); return {year:+parts.year,month:+parts.month,day:+parts.day,hour:+parts.hour,minute:+parts.minute,second:+parts.second}; }
  function wallTimeToUtcIso(raw) { const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(raw); if(!m)throw new Error("Invalid replay start time"); const wanted={year:+m[1],month:+m[2],day:+m[3],hour:+m[4],minute:+m[5],second:0}; const wall=Date.UTC(wanted.year,wanted.month-1,wanted.day,wanted.hour,wanted.minute,0); let guess=wall; for(let i=0;i<4;i++){const shown=partsAt(new Date(guess));const shownWall=Date.UTC(shown.year,shown.month-1,shown.day,shown.hour,shown.minute,shown.second);const d=wall-shownWall;guess+=d;if(d===0)break} return new Date(guess).toISOString(); }
  function inputValue(value) { const p=partsAt(new Date(value)),pad=(n)=>String(n).padStart(2,"0"); return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`; }
  function displayTime(value) { return statusFormatter.format(new Date(value)); }
  function epochMs(time) { if(typeof time==="number")return time*1000;if(typeof time==="string")return Date.parse(time);return Date.UTC(time.year,time.month-1,time.day); }

  const cssStyle=getComputedStyle(document.documentElement); const cssVar=(name,fallback)=>(cssStyle.getPropertyValue(name)||fallback).trim();
  const chart=LightweightCharts.createChart($("chart"),{autoSize:true,attributionLogo:true,layout:{background:{type:"solid",color:cssVar("--chart-bg","#0b1017")},textColor:cssVar("--chart-text","#a9b4c4")},grid:{vertLines:{color:cssVar("--chart-grid","#18222f")},horzLines:{color:cssVar("--chart-grid","#18222f")}},crosshair:{mode:LightweightCharts.CrosshairMode.Magnet},localization:{timeFormatter:(time)=>statusFormatter.format(new Date(epochMs(time)))},timeScale:{timeVisible:true,secondsVisible:false,tickMarkFormatter:(time)=>axisFormatter.format(new Date(epochMs(time)))}});
  const candles=chart.addSeries(LightweightCharts.CandlestickSeries,{upColor:cssVar("--chart-up","#26a69a"),downColor:cssVar("--chart-down","#ef5350"),borderVisible:false,wickUpColor:cssVar("--chart-up","#26a69a"),wickDownColor:cssVar("--chart-down","#ef5350")});
  const volume=chart.addSeries(LightweightCharts.HistogramSeries,{priceFormat:{type:"volume"},priceScaleId:"vol"}); volume.priceScale().applyOptions({scaleMargins:{top:.78,bottom:0}});
  const chartTools=new window.FutureViewChartTools({chart,candles,volume,toolbar:$("chart-toolbar"),legend:$("chart-legend"),container:$("chart"),formatTime:(seconds)=>statusFormatter.format(new Date(seconds*1000))});
  const candle=(b)=>({time:b.time,open:b.open,high:b.high,low:b.low,close:b.close});
  const volumeBar=(b)=>({time:b.time,value:b.volume,color:b.close>=b.open?"rgba(38,166,154,.45)":"rgba(239,83,80,.45)"});
  function renderBar(b){candles.update(candle(b));volume.update(volumeBar(b));chartTools.append(b);$("status-time").textContent=displayTime(b.timestamp||(b.time*1000));}
  function renderBars(bars){bars.forEach((bar)=>{candles.update(candle(bar));volume.update(volumeBar(bar));});chartTools.appendMany(bars);if(bars.length){const last=bars[bars.length-1];$("status-time").textContent=displayTime(last.timestamp||(last.time*1000));}}
  function setWarmup(bars){chartTools._cancelDrawing?.();candles.setData(bars.map(candle));volume.setData(bars.map(volumeBar));chartTools.reset(bars);chartTools.fit();}

  async function api(path,opts={}){const response=await fetch(path,{headers:{"Content-Type":"application/json"},...opts});if(!response.ok){let message=`${response.status}`;try{message=(await response.json()).detail||message}catch{}throw new Error(message)}return response.json();}
  function syncControls(){const busy=commandPending;$("play").disabled=!started||busy||currentState==="PLAYING"||currentState==="FINISHED";$("pause").disabled=!started||busy||currentState!=="PLAYING";$("next").disabled=!started||busy||currentState==="PLAYING"||currentState==="FINISHED";$("restart").disabled=!started||busy;}
  function state(snapshot){if(!snapshot||!snapshot.state)return;currentState=snapshot.state;$("status-state").textContent=currentState;$("status-contract").textContent=snapshot.contract||"—";$("status-time").textContent=snapshot.cursor?displayTime(snapshot.cursor):"No session";syncControls();}
  function error(message=""){$("error").textContent=message;}

  let replayRangeInfo=null;
  async function replayRange(explicit=false){try{error();const product=$("product")?.value||"MES";try{replayRangeInfo=await api(`/api/replay/range?product=${encodeURIComponent(product)}`)}catch(err){if(!explicit){replayRangeInfo=await api("/api/replay/range");if(replayRangeInfo.product&&$("product"))$("product").value=replayRangeInfo.product}else throw err}$("range").textContent=`${displayTime(replayRangeInfo.first)} → ${displayTime(replayRangeInfo.last)} · ${replayRangeInfo.sessions?.length||0} actual sessions`;$("start").value=inputValue(replayRangeInfo.first)}catch(e){error(e.message)}}
  async function init(){try{await replayRange();const snapshot=await api("/api/replay/state");if(snapshot?.contract)started=true;state(snapshot)}catch(e){error(e.message)}}

  async function post(path,body,optimisticState=null){if(commandPending)return;commandPending=true;if(optimisticState){currentState=optimisticState;$("status-state").textContent=currentState;}syncControls();try{error();const result=await api(path,{method:"POST",body:body?JSON.stringify(body):undefined});if(result.warmup)setWarmup(result.warmup);state(result)}catch(e){error(e.message);try{state(await api("/api/replay/state"))}catch{}}finally{commandPending=false;syncControls();}}

  const DEFAULT_REPLAY_TIME="08:30";
  function pickRandomTradingDate(info){const sessions=Array.isArray(info?.sessions)?info.sessions.filter((x)=>/^\d{4}-\d{2}-\d{2}$/.test(x)):[];if(!sessions.length)throw new Error("No actual replay sessions are available for random selection");const firstSec=info.first_time??Math.floor(new Date(info.first).getTime()/1000);const lastSec=info.last_time??Math.floor(new Date(info.last).getTime()/1000);const valid=sessions.filter((day)=>{try{const ms=Date.parse(wallTimeToUtcIso(`${day}T${DEFAULT_REPLAY_TIME}`));return ms>=firstSec*1000&&ms<=lastSec*1000}catch{return false}});const pool=valid.length?valid:sessions;return `${pool[Math.floor(Math.random()*pool.length)]}T${DEFAULT_REPLAY_TIME}`;}

  let isStarting=false;
  async function startReplay(){if(isStarting)return;isStarting=true;$("start-btn").disabled=true;$("random-btn").disabled=true;try{error();const raw=$("start").value;if(!raw)throw new Error("Choose a start time");const result=await api("/api/replay/start",{method:"POST",body:JSON.stringify({product:$("product").value,start:wallTimeToUtcIso(raw),warmup:Number($("warmup").value||300)})});started=true;setWarmup(result.warmup||[]);state(result);if(result.contract_selection){const selected=result.contract_selection;$("range").textContent=`Selected ${selected.contract} using ${selected.source_session||"fallback"} (${selected.reason})`}}catch(e){error(e.message)}finally{isStarting=false;$("start-btn").disabled=false;$("random-btn").disabled=false;}}

  $("product").onchange=()=>replayRange(true);
  $("start-btn").onclick=()=>startReplay();
  $("random-btn").onclick=async()=>{if(isStarting)return;if(!replayRangeInfo)await replayRange();try{$("start").value=pickRandomTradingDate(replayRangeInfo);await startReplay()}catch(e){error(e.message)}};
  $("next").onclick=()=>post("/api/replay/step");
  $("restart").onclick=()=>post("/api/replay/restart",null,"PAUSED");
  $("pause").onclick=()=>post("/api/replay/pause",null,"PAUSED");
  $("play").onclick=()=>post("/api/replay/play",{speed},"PLAYING");
  $("speeds").onclick=(event)=>{const button=event.target.closest("button[data-speed]");if(!button)return;document.querySelectorAll("#speeds button").forEach((x)=>x.classList.remove("active"));button.classList.add("active");speed=button.dataset.speed==="max"?"max":Number(button.dataset.speed);if(currentState==="PLAYING"&&!commandPending)post("/api/replay/play",{speed},"PLAYING")};

  const protocol=location.protocol==="https:"?"wss":"ws";const websocket=new WebSocket(`${protocol}://${location.host}/ws/replay`);websocket.onmessage=(event)=>{const message=JSON.parse(event.data);if(message.type==="bar")renderBar(message.bar);else if(message.type==="bars_batch")renderBars(message.bars);else if(!commandPending)state(message)};websocket.onerror=()=>error("WebSocket disconnected");
  init();
})();
