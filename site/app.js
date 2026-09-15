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

  function token(){return localStorage.getItem(TOKEN_KEY)||""}
  function clearAuth(){localStorage.removeItem(TOKEN_KEY);localStorage.removeItem(USER_KEY)}
  function goLogin(){clearAuth();location.replace("/login.html")}

  const zonedPartsFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"});
  const statusFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23", timeZoneName:"short"});
  const axisFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23"});
  function partsAt(date){const parts=Object.fromEntries(zonedPartsFormatter.formatToParts(date).filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));return {year:+parts.year,month:+parts.month,day:+parts.day,hour:+parts.hour,minute:+parts.minute,second:+parts.second}}
  function wallTimeToUtcIso(raw){const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(raw);if(!m)throw new Error("Invalid replay start time");const wanted={year:+m[1],month:+m[2],day:+m[3],hour:+m[4],minute:+m[5],second:0};const wall=Date.UTC(wanted.year,wanted.month-1,wanted.day,wanted.hour,wanted.minute,0);let guess=wall;for(let i=0;i<4;i++){const shown=partsAt(new Date(guess));const shownWall=Date.UTC(shown.year,shown.month-1,shown.day,shown.hour,shown.minute,shown.second);const d=wall-shownWall;guess+=d;if(d===0)break}return new Date(guess).toISOString()}
  function inputValueFromSeconds(seconds){const p=partsAt(new Date(seconds*1000)),pad=n=>String(n).padStart(2,"0");return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`}
  function displaySeconds(seconds){return statusFormatter.format(new Date(seconds*1000))}
  function epochMs(time){if(typeof time==="number")return time*1000;if(typeof time==="string")return Date.parse(time);return Date.UTC(time.year,time.month-1,time.day)}
  function sessionAtDefaultTime(info){
    const sessions=Array.isArray(info?.sessions)?info.sessions.filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x)):[];
    for(const day of sessions){
      const value=`${day}T${DEFAULT_REPLAY_TIME}`;
      try{
        const ms=Date.parse(wallTimeToUtcIso(value));
        if(ms>=Number(info.first_time)*1000&&ms<=Number(info.last_time)*1000)return value;
      }catch{}
    }
    if(sessions.length)return `${sessions[0]}T${DEFAULT_REPLAY_TIME}`;
    const p=partsAt(new Date(Number(info.first_time)*1000)),pad=n=>String(n).padStart(2,"0");
    return `${p.year}-${pad(p.month)}-${pad(p.day)}T${DEFAULT_REPLAY_TIME}`;
  }

  const T=getComputedStyle(document.documentElement);
  const cssVar=(name,fallback)=>(T.getPropertyValue(name)||fallback).trim();
  const chart=LightweightCharts.createChart($("chart"),{autoSize:true,attributionLogo:true,layout:{background:{type:"solid",color:cssVar("--chart-bg","#090e15")},textColor:cssVar("--chart-text","#aab5c5")},grid:{vertLines:{color:cssVar("--chart-grid","#17202d")},horzLines:{color:cssVar("--chart-grid","#17202d")}},crosshair:{mode:LightweightCharts.CrosshairMode.Magnet},localization:{timeFormatter:t=>statusFormatter.format(new Date(epochMs(t)))},timeScale:{timeVisible:true,secondsVisible:false,tickMarkFormatter:t=>axisFormatter.format(new Date(epochMs(t)))}});
  const candles=chart.addSeries(LightweightCharts.CandlestickSeries,{upColor:cssVar("--chart-up","#26a69a"),downColor:cssVar("--chart-down","#ef5350"),borderVisible:false,wickUpColor:cssVar("--chart-up","#26a69a"),wickDownColor:cssVar("--chart-down","#ef5350")});
  const volume=chart.addSeries(LightweightCharts.HistogramSeries,{priceFormat:{type:"volume"},priceScaleId:"volume"});volume.priceScale().applyOptions({scaleMargins:{top:.8,bottom:0}});
  const chartTools=new window.FutureViewChartTools({chart,candles,volume,toolbar:$("chart-toolbar"),legend:$("chart-legend"),container:$("chart"),formatTime:displaySeconds});
  const candle=b=>({time:b.t,open:b.o,high:b.h,low:b.l,close:b.c}),vol=b=>({time:b.t,value:b.v,color:b.c>=b.o?"rgba(38,166,154,.46)":"rgba(239,83,80,.46)"});
  function render(b){candles.update(candle(b));volume.update(vol(b));chartTools.append(b);$("time-status").textContent=displaySeconds(b.t)}
  function renderMany(bs){bs.forEach(b=>{candles.update(candle(b));volume.update(vol(b))});chartTools.appendMany(bs);if(bs.length)$("time-status").textContent=displaySeconds(bs[bs.length-1].t)}
  function reset(bs){chartTools._cancelDrawing?.();candles.setData(bs.map(candle));volume.setData(bs.map(vol));chartTools.reset(bs);chartTools.fit()}
  function error(m=""){$("error").textContent=m}
  async function api(path,opts={}){
    const authToken=token();
    if(!authToken)return goLogin();
    const r=await fetch(`${API_ORIGIN}${path}`,{headers:{"Content-Type":"application/json","Authorization":`Bearer ${authToken}`,...(opts.headers||{})},...opts});
    if(r.status===401)return goLogin();
    if(!r.ok){let m=`HTTP ${r.status}`;try{m=(await r.json()).error||m}catch{}throw new Error(m)}
    return r.json();
  }

  async function validateAuth(){
    const authToken=token();
    if(!authToken){goLogin();return false}
    const r=await fetch(`${API_ORIGIN}/api/auth/me`,{cache:"no-store",headers:{"Authorization":`Bearer ${authToken}`}});
    if(!r.ok){goLogin();return false}
    return true;
  }

  async function logout(){
    const authToken=token();
    try{if(authToken)await fetch(`${API_ORIGIN}/api/auth/logout`,{method:"POST",headers:{"Authorization":`Bearer ${authToken}`}})}catch{}
    goLogin();
  }

  function syncControls(){const ready=!!sessionId&&wsOpen&&wsSynced;const busy=!!pendingCommand;$("play").disabled=!ready||busy||lastState==="PLAYING"||lastState==="FINISHED";$("pause").disabled=!ready||busy||lastState!=="PLAYING";$("next").disabled=!ready||busy||lastState==="PLAYING"||lastState==="FINISHED";$("restart").disabled=!ready||busy;}
  function update(s,authoritative=false){if(!s)return;if(s.state)lastState=s.state;if(authoritative){wsSynced=true;pendingCommand=null;clearTimeout(commandAckTimer);commandAckTimer=null;}$("state-status").textContent=lastState;if(s.contract)$("contract-status").textContent=s.contract;if(s.cursor!=null)$("time-status").textContent=displaySeconds(s.cursor);else if(!sessionId)$("time-status").textContent="No session";syncControls();}
  function command(type,extra={}){if(!ws||ws.readyState!==WebSocket.OPEN||!wsSynced){error("Replay socket is not synchronized - reconnecting…");if(wsPath)connect(wsPath);return}pendingCommand=type;if(type==="play")lastState="PLAYING";else if(type==="pause"||type==="restart")lastState="PAUSED";update({state:lastState});ws.send(JSON.stringify({type,...extra}));clearTimeout(commandAckTimer);commandAckTimer=setTimeout(()=>{if(pendingCommand===type){pendingCommand=null;wsSynced=false;error("Replay command acknowledgement timed out - resynchronizing…");syncControls();if(wsPath)connect(wsPath)}},2000);}
  function connect(path){wsPath=path;clearTimeout(wsReconnectTimer);clearTimeout(commandAckTimer);pendingCommand=null;wsSynced=false;syncControls();if(ws)ws.close();const authToken=token();if(!authToken)return goLogin();const wsOrigin=API_ORIGIN.replace(/^http/,"ws");const sep=path.includes("?")?"&":"?";const thisWs=ws=new WebSocket(`${wsOrigin}${path}${sep}access_token=${encodeURIComponent(authToken)}`);thisWs.onopen=()=>{if(ws!==thisWs)return;wsOpen=true;wsReconnectDelay=1000;error();syncControls()};thisWs.onmessage=e=>{if(ws!==thisWs)return;const x=JSON.parse(e.data);if(x.type==="bar")render(x.bar);else if(x.type==="bars_batch")renderMany(x.bars);else if(x.type==="reset"){reset(x.warmup||[]);update(x.snapshot,true)}else if(x.type==="error"){pendingCommand=null;clearTimeout(commandAckTimer);error(x.error);syncControls()}else update(x,true)};thisWs.onerror=()=>{};thisWs.onclose=()=>{if(ws!==thisWs)return;wsOpen=false;wsSynced=false;pendingCommand=null;clearTimeout(commandAckTimer);syncControls();if(!sessionId||lastState==="FINISHED")return;error("Replay socket disconnected - reconnecting…");wsReconnectTimer=setTimeout(()=>connect(wsPath),wsReconnectDelay);wsReconnectDelay=Math.min(wsReconnectDelay*2,8000)}}

  let replayRangeInfo=null;
  async function loadRange(explicit=false){error();const p=$("product")?.value||"MES";try{replayRangeInfo=await api(`/api/replay/range?product=${encodeURIComponent(p)}`);if(!replayRangeInfo)return;$("start").value=sessionAtDefaultTime(replayRangeInfo);$("range").textContent=`${displaySeconds(replayRangeInfo.first_time)} → ${displaySeconds(replayRangeInfo.last_time)} · ${replayRangeInfo.sessions?.length||0} actual sessions`}catch(err){if(!explicit){try{replayRangeInfo=await api("/api/replay/range");if(!replayRangeInfo)return;if(replayRangeInfo.product&&$("product"))$("product").value=replayRangeInfo.product;$("start").value=sessionAtDefaultTime(replayRangeInfo);return}catch{}}error(err.message)}}
  function pickRandomTradingDate(info){const sessions=Array.isArray(info?.sessions)?info.sessions.filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x)):[];if(!sessions.length)throw new Error("No actual replay sessions are available for random selection");const valid=sessions.filter(day=>{try{const ms=Date.parse(wallTimeToUtcIso(`${day}T${DEFAULT_REPLAY_TIME}`));return ms>=Number(info.first_time)*1000&&ms<=Number(info.last_time)*1000}catch{return false}});const pool=valid.length?valid:sessions;return `${pool[Math.floor(Math.random()*pool.length)]}T${DEFAULT_REPLAY_TIME}`;}
  let isStarting=false;
  async function startReplay(){if(isStarting)return;isStarting=true;$("start-btn").disabled=true;$("random-btn").disabled=true;try{error();const raw=$("start").value;if(!raw)throw new Error("Choose a start time");const x=await api("/api/replay/sessions",{method:"POST",body:JSON.stringify({product:$("product").value,start:wallTimeToUtcIso(raw),warmup:Number($("warmup").value||300)})});if(!x)return;sessionId=x.session_id;wsSynced=false;reset(x.warmup||[]);update(x,true);const selected=x.contract_selection;if(selected)$("range").textContent=`Selected ${selected.contract} using ${selected.source_session||"fallback"} (${selected.reason})`;connect(x.websocket)}catch(e){error(e.message)}finally{isStarting=false;$("start-btn").disabled=false;$("random-btn").disabled=false;}}
  $("product").onchange=()=>loadRange(true);
  $("start-btn").onclick=()=>startReplay();
  $("random-btn").onclick=async()=>{if(isStarting)return;if(!replayRangeInfo)await loadRange();try{$("start").value=pickRandomTradingDate(replayRangeInfo);await startReplay()}catch(e){error(e.message)}};
  $("play").onclick=()=>command("play",{speed});$("pause").onclick=()=>command("pause");$("next").onclick=()=>command("step");$("restart").onclick=()=>command("restart");
  $("speeds").onclick=e=>{const b=e.target.closest("button[data-speed]");if(!b)return;document.querySelectorAll("#speeds button").forEach(x=>x.classList.remove("active"));b.classList.add("active");speed=b.dataset.speed==="max"?"max":Number(b.dataset.speed);if(lastState==="PLAYING"&&!pendingCommand)command("play",{speed})};
  $("logout").onclick=()=>logout();

  (async()=>{if(!(await validateAuth()))return;await loadRange();update({state:"STOPPED"});})().catch(e=>error(e.message));
})();
