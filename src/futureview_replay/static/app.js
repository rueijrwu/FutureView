(() => {
  const $ = (id) => document.getElementById(id);
  const DISPLAY_TIME_ZONE = "America/New_York";
  let speed = 1;
  let started = false;

  const zonedPartsFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const statusFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "short",
  });
  const axisFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TIME_ZONE,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  function partsAt(date) {
    const parts = Object.fromEntries(
      zonedPartsFormatter
        .formatToParts(date)
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, part.value]),
    );
    return {
      year: Number(parts.year),
      month: Number(parts.month),
      day: Number(parts.day),
      hour: Number(parts.hour),
      minute: Number(parts.minute),
      second: Number(parts.second),
    };
  }

  function wallTimeToUtcIso(raw) {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(raw);
    if (!match) throw new Error("Invalid replay start time");
    const wanted = {
      year: Number(match[1]),
      month: Number(match[2]),
      day: Number(match[3]),
      hour: Number(match[4]),
      minute: Number(match[5]),
      second: 0,
    };
    const wantedWall = Date.UTC(
      wanted.year,
      wanted.month - 1,
      wanted.day,
      wanted.hour,
      wanted.minute,
      wanted.second,
    );
    let guess = wantedWall;
    for (let i = 0; i < 4; i += 1) {
      const shown = partsAt(new Date(guess));
      const shownWall = Date.UTC(
        shown.year,
        shown.month - 1,
        shown.day,
        shown.hour,
        shown.minute,
        shown.second,
      );
      const delta = wantedWall - shownWall;
      guess += delta;
      if (delta === 0) break;
    }
    return new Date(guess).toISOString();
  }

  function inputValue(value) {
    const p = partsAt(new Date(value));
    const pad = (n) => String(n).padStart(2, "0");
    return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
  }

  function displayTime(value) {
    return statusFormatter.format(new Date(value));
  }

  function epochMs(time) {
    if (typeof time === "number") return time * 1000;
    if (typeof time === "string") return Date.parse(time);
    return Date.UTC(time.year, time.month - 1, time.day);
  }

  const cssStyle = getComputedStyle(document.documentElement);
  const cssVar = (name, fallback) => (cssStyle.getPropertyValue(name) || fallback).trim();
  const chart = LightweightCharts.createChart($("chart"), {
    autoSize: true,
    attributionLogo: true,
    layout: { background: { type: "solid", color: cssVar("--chart-bg", "#0b1017") }, textColor: cssVar("--chart-text", "#a9b4c4") },
    grid: { vertLines: { color: cssVar("--chart-grid", "#18222f") }, horzLines: { color: cssVar("--chart-grid", "#18222f") } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Magnet },
    localization: {
      timeFormatter: (time) => statusFormatter.format(new Date(epochMs(time))),
    },
    timeScale: {
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time) => axisFormatter.format(new Date(epochMs(time))),
    },
  });
  const candles = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: cssVar("--chart-up", "#26a69a"),
    downColor: cssVar("--chart-down", "#ef5350"),
    borderVisible: false,
    wickUpColor: cssVar("--chart-up", "#26a69a"),
    wickDownColor: cssVar("--chart-down", "#ef5350"),
  });
  const volume = chart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: "volume" },
    priceScaleId: "vol",
  });
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  const chartTools = new window.FutureViewChartTools({
    chart,
    candles,
    volume,
    toolbar: $("chart-toolbar"),
    legend: $("chart-legend"),
    container: $("chart"),
    formatTime: (seconds) => statusFormatter.format(new Date(seconds * 1000)),
  });

  const candle = (b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
  const volumeBar = (b) => ({
    time: b.time,
    value: b.volume,
    color: b.close >= b.open ? "rgba(38,166,154,.45)" : "rgba(239,83,80,.45)",
  });
  function renderBar(b) {
    candles.update(candle(b));
    volume.update(volumeBar(b));
    chartTools.append(b);
  }
  function renderBars(bars) {
    bars.forEach((bar) => {
      candles.update(candle(bar));
      volume.update(volumeBar(bar));
    });
    chartTools.appendMany(bars);
  }
  function setWarmup(bars) {
    candles.setData(bars.map(candle));
    volume.setData(bars.map(volumeBar));
    chartTools.reset(bars);
    chart.timeScale().fitContent();
  }

  async function api(path, opts = {}) {
    const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    if (!response.ok) {
      let message = `${response.status}`;
      try { message = (await response.json()).detail || message; } catch {}
      throw new Error(message);
    }
    return response.json();
  }

  function state(snapshot) {
    if (!snapshot || !snapshot.state) return;
    $("status-state").textContent = snapshot.state;
    $("status-contract").textContent = snapshot.contract || "—";
    $("status-time").textContent = snapshot.cursor ? displayTime(snapshot.cursor) : "No session";
    $("play").disabled = !started || snapshot.state === "PLAYING";
    $("pause").disabled = !started || snapshot.state !== "PLAYING";
    $("next").disabled = !started || snapshot.state === "PLAYING" || snapshot.state === "FINISHED";
    $("restart").disabled = !started;
  }
  function error(message = "") { $("error").textContent = message; }

  let replayRangeInfo = null;
  async function replayRange() {
    try {
      replayRangeInfo = await api("/api/replay/range");
      $("product").value = replayRangeInfo.product;
      $("range").textContent = `${displayTime(replayRangeInfo.first)} → ${displayTime(replayRangeInfo.last)} · contract selected automatically`;
      $("start").value = inputValue(replayRangeInfo.first);
    } catch (e) {
      error(e.message);
    }
  }

  async function init() {
    try {
      await replayRange();
      state(await api("/api/replay/state"));
    } catch (e) {
      error(e.message);
    }
  }

  async function post(path, body) {
    try {
      error();
      const result = await api(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      if (result.warmup) setWarmup(result.warmup);
      state(result);
    } catch (e) {
      error(e.message);
    }
  }

  const DEFAULT_REPLAY_TIME = "08:30";
  function pickRandomTradingDate(firstSec, lastSec) {
    const minSec = Number(firstSec);
    const maxSec = Number(lastSec);
    const pad = (n) => String(n).padStart(2, "0");
    if (!Number.isFinite(minSec) || !Number.isFinite(maxSec) || maxSec <= minSec) {
      const p = partsAt(new Date(minSec * 1000));
      return `${p.year}-${pad(p.month)}-${pad(p.day)}T${DEFAULT_REPLAY_TIME}`;
    }
    const pFirst = partsAt(new Date(minSec * 1000));
    const pLast = partsAt(new Date(maxSec * 1000));
    const startDayMs = Date.UTC(pFirst.year, pFirst.month - 1, pFirst.day);
    const endDayMs = Date.UTC(pLast.year, pLast.month - 1, pLast.day);
    const totalDays = Math.max(0, Math.floor((endDayMs - startDayMs) / 86400000));
    for (let i = 0; i < 50; i++) {
      const randOffset = Math.floor(Math.random() * (totalDays + 1));
      const candDate = new Date(startDayMs + randOffset * 86400000);
      const dayOfWeek = candDate.getUTCDay();
      if (dayOfWeek === 0 || dayOfWeek === 6) continue;
      const y = candDate.getUTCFullYear();
      const m = pad(candDate.getUTCMonth() + 1);
      const d = pad(candDate.getUTCDate());
      const val = `${y}-${m}-${d}T${DEFAULT_REPLAY_TIME}`;
      const utcMs = Date.parse(wallTimeToUtcIso(val));
      if (utcMs >= minSec * 1000 && utcMs <= maxSec * 1000) {
        return val;
      }
    }
    return `${pFirst.year}-${pad(pFirst.month)}-${pad(pFirst.day)}T${DEFAULT_REPLAY_TIME}`;
  }

  let isStarting = false;
  async function startReplay() {
    if (isStarting) return;
    isStarting = true;
    $("start-btn").disabled = true;
    $("random-btn").disabled = true;
    try {
      error();
      const raw = $("start").value;
      if (!raw) throw new Error("Choose a start time");
      const result = await api("/api/replay/start", {
        method: "POST",
        body: JSON.stringify({
          product: $("product").value,
          start: wallTimeToUtcIso(raw),
          warmup: Number($("warmup").value || 300),
        }),
      });
      started = true;
      setWarmup(result.warmup || []);
      state(result);
      if (result.contract_selection) {
        const selected = result.contract_selection;
        $("range").textContent = `Selected ${selected.contract} from ${selected.source_session || "the first available session"} (${selected.reason})`;
      }
    } catch (e) {
      error(e.message);
    } finally {
      isStarting = false;
      $("start-btn").disabled = false;
      $("random-btn").disabled = false;
    }
  }

  $("start-btn").onclick = () => startReplay();
  $("random-btn").onclick = async () => {
    if (isStarting) return;
    if (!replayRangeInfo) {
      try {
        await replayRange();
      } catch (e) {
        error(e.message);
        return;
      }
    }
    const firstSec = replayRangeInfo.first_time ?? Math.floor(new Date(replayRangeInfo.first).getTime() / 1000);
    const lastSec = replayRangeInfo.last_time ?? Math.floor(new Date(replayRangeInfo.last).getTime() / 1000);
    $("start").value = pickRandomTradingDate(firstSec, lastSec);
    await startReplay();
  };
  $("next").onclick = () => post("/api/replay/step");
  $("restart").onclick = () => post("/api/replay/restart");
  $("pause").onclick = () => post("/api/replay/pause");
  $("play").onclick = () => post("/api/replay/play", { speed });
  $("speeds").onclick = (event) => {
    const button = event.target.closest("button[data-speed]");
    if (!button) return;
    document.querySelectorAll("#speeds button").forEach((x) => x.classList.remove("active"));
    button.classList.add("active");
    speed = button.dataset.speed === "max" ? "max" : Number(button.dataset.speed);
    if ($("status-state").textContent === "PLAYING") post("/api/replay/play", { speed });
  };

  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const websocket = new WebSocket(`${protocol}://${location.host}/ws/replay`);
  websocket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "bar") renderBar(message.bar);
    else if (message.type === "bars_batch") renderBars(message.bars);
    else state(message);
  };
  websocket.onerror = () => error("WebSocket disconnected");
  init();
})();
