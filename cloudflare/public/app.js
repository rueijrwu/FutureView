(() => {
  const $ = (id) => document.getElementById(id);
  const DISPLAY_TIME_ZONE = "America/New_York";
  let speed = 1;
  let sessionId = null;
  let ws = null;
  let lastState = "STOPPED";

  const zonedPartsFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"});
  const statusFormatter = new Intl.DateTimeFormat("en-US", {timeZone: DISPLAY_TIME_ZONE, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23", timeZoneName:"short"});

  function partsAt(date){const parts=Object.fromEntries(zonedPartsFormatter.formatToParts(date).filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));return {year:+parts.year,month:+parts.month,day:+parts.day,hour:+parts.hour,minute:+parts.minute,second:+parts.second}}
  function wallTimeToUtcIso(raw){const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(raw);if(!m)throw new Error("Invalid replay start time");const wanted={year:+m[1],month:+m[2],day:+m[3],hour:+m[4],minute:+m[5],second:0};const wall=Date.UTC(wanted.year,wanted.month-1,wanted.day,wanted.hour,wanted.minute,0);let guess=wall;for(let i=0;i<4;i++){const shown=partsAt(new Date(guess));const shownWall=Date.UTC(shown.year,shown.month-1,shown.day,shown.hour,shown.minute,shown.second);const d=wall-shownWall;guess+=d;if(d===0)break}return new Date(guess).toISOString()}
  function inputValueFromSeconds(seconds){const p=partsAt(new Date(seconds*1000)),pad=n=>String(n).padStart(2,"0");return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`}
  function displaySeconds(seconds){return statusFormatter.format(new Date(seconds*1000))}

  const T=window.FutureViewTheme;
  // candle/indicator tooltip.showRule:"none" - the chart-legend bar above the chart is our
  // single OHLCV readout, so klinecharts' own floating tooltip would just duplicate it.
  const chart=klinecharts.init("chart",{timezone:DISPLAY_TIME_ZONE,styles:{grid:{horizontal:{color:T.grid},vertical:{color:T.grid}},candle:{bar:{upColor:T.up,downColor:T.down,noChangeColor:T.neutral,upBorderColor:T.up,downBorderColor:T.down,noChangeBorderColor:T.neutral,upWickColor:T.up,downWickColor:T.down,noChangeWickColor:T.neutral},tooltip:{showRule:"none"}},indicator:{tooltip:{showRule:"none"}}}});
  chart.createIndicator("VOL",false,{id:"volume_pane",height:100});
  const chartTools=new window.FutureViewChartTools({chart,toolbar:$("chart-toolbar"),legend:$("chart-legend"),formatTime:displaySeconds});
  const bar=b=>({timestamp:b.t*1000,open:b.o,high:b.h,low:b.l,close:b.c,volume:b.v});
  // Batches go through a single applyNewData: klinecharts recalculates and repaints every
  // indicator across the whole dataset on each updateData, so a per-bar loop is O(batch x history).
  function mergeBars(list,incoming){const out=list.slice();for(const b of incoming){const last=out[out.length-1];if(!last||b.timestamp>last.timestamp)out.push(b);else if(b.timestamp===last.timestamp)out[out.length-1]=b}return out}
  function render(b){chart.updateData(bar(b));chartTools.append(b)}function renderMany(bs){chart.applyNewData(mergeBars(chart.getDataList(),bs.map(bar)));chartTools.appendMany(bs)}function reset(bs){chart.applyNewData(bs.map(bar));chartTools.reset(bs);chart.scrollToRealTime()}function error(m=""){$("error").textContent=m}
  async function api(path,opts={}){const r=await fetch(path,{headers:{"Content-Type":"application/json"},...opts});if(!r.ok){let m=`HTTP ${r.status}`;try{m=(await r.json()).error||m}catch{}throw new Error(m)}return r.json()}
  function update(s){if(!s)return;lastState=s.state||lastState;$("state-status").textContent=lastState;$("contract-status").textContent=s.contract||$("contract-status").textContent;$("time-status").textContent=s.cursor?displaySeconds(s.cursor):"No session";$("play").disabled=!sessionId||lastState==="PLAYING";$("pause").disabled=!sessionId||lastState!=="PLAYING";$("next").disabled=!sessionId||lastState==="PLAYING"||lastState==="FINISHED";$("restart").disabled=!sessionId}
  function command(type,extra={}){if(!ws||ws.readyState!==WebSocket.OPEN){error("Replay socket is not connected");return}ws.send(JSON.stringify({type,...extra}))}
  function connect(path){if(ws)ws.close();const proto=location.protocol==="https:"?"wss":"ws";ws=new WebSocket(`${proto}://${location.host}${path}`);ws.onmessage=e=>{const x=JSON.parse(e.data);if(x.type==="bar")render(x.bar);else if(x.type==="bars_batch")renderMany(x.bars);else if(x.type==="reset"){reset(x.warmup||[]);update(x.snapshot)}else if(x.type==="error")error(x.error);else update(x)};ws.onerror=()=>error("Replay WebSocket disconnected")}
  async function loadRange(){const x=await api("/api/replay/range");$("product").value=x.product;$("start").value=inputValueFromSeconds(x.first_time);$("range").textContent=`${displaySeconds(x.first_time)} → ${displaySeconds(x.last_time)} · contract selected automatically`}
  $("start-btn").onclick=async()=>{try{error();const raw=$("start").value;if(!raw)throw new Error("Choose a start time");const x=await api("/api/replay/sessions",{method:"POST",body:JSON.stringify({product:$("product").value,start:wallTimeToUtcIso(raw),warmup:Number($("warmup").value||300)})});sessionId=x.session_id;reset(x.warmup||[]);update(x);const selected=x.contract_selection;if(selected)$("range").textContent=`Selected ${selected.contract} from ${selected.source_session||"the first available session"} (${selected.reason})`;connect(x.websocket)}catch(e){error(e.message)}};
  $("play").onclick=()=>command("play",{speed});$("pause").onclick=()=>command("pause");$("next").onclick=()=>command("step");$("restart").onclick=()=>command("restart");$("speeds").onclick=e=>{const b=e.target.closest("button[data-speed]");if(!b)return;document.querySelectorAll("#speeds button").forEach(x=>x.classList.remove("active"));b.classList.add("active");speed=b.dataset.speed==="max"?"max":Number(b.dataset.speed);if(lastState==="PLAYING")command("play",{speed})};loadRange().catch(e=>error(e.message));update({state:"STOPPED"});
})();
