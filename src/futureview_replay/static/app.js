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


  const chart = klinecharts.init("chart", {
    timezone: DISPLAY_TIME_ZONE,
    styles: {
      grid: { horizontal: { color: "#18222f" }, vertical: { color: "#18222f" } },
      candle: {
        bar: {
          upColor: "#26a69a",
          downColor: "#ef5350",
          noChangeColor: "#888",
          upBorderColor: "#26a69a",
          downBorderColor: "#ef5350",
          noChangeBorderColor: "#888",
          upWickColor: "#26a69a",
          downWickColor: "#ef5350",
          noChangeWickColor: "#888",
        },
      },
    },
  });
  chart.createIndicator("VOL", false, { id: "volume_pane", height: 100 });
  const chartTools = new window.FutureViewChartTools({
    chart,
    toolbar: $("chart-toolbar"),
    legend: $("chart-legend"),
    formatTime: (seconds) => statusFormatter.format(new Date(seconds * 1000)),
  });

  const kline = (b) => ({ timestamp: b.time * 1000, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume });
  function renderBar(b) {
    chart.updateData(kline(b));
    chartTools.append(b);
  }
  // Batches go through a single applyNewData: klinecharts recalculates and repaints every
  // indicator across the whole dataset on each updateData, so a per-bar loop is O(batch x history).
  function mergeBars(list, incoming) {
    const out = list.slice();
    for (const b of incoming) {
      const last = out[out.length - 1];
      if (!last || b.timestamp > last.timestamp) out.push(b);
      else if (b.timestamp === last.timestamp) out[out.length - 1] = b;
    }
    return out;
  }
  function renderBars(bars) {
    chart.applyNewData(mergeBars(chart.getDataList(), bars.map(kline)));
    chartTools.appendMany(bars);
  }
  function setWarmup(bars) {
    chart.applyNewData(bars.map(kline));
    chartTools.reset(bars);
    chart.scrollToRealTime();
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

  async function replayRange() {
    try {
      const info = await api("/api/replay/range");
      $("product").value = info.product;
      $("range").textContent = `${displayTime(info.first)} → ${displayTime(info.last)} · contract selected automatically`;
      $("start").value = inputValue(info.first);
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

  $("start-btn").onclick = async () => {
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
    }
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
