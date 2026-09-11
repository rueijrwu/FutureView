(() => {
  const $ = (id) => document.getElementById(id);
  const DISPLAY_TIME_ZONE = "America/New_York";
  let speed = 1;
  let sessionId = null;
  let ws = null;
  let lastState = "STOPPED";

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

  function inputValueFromSeconds(seconds) {
    const p = partsAt(new Date(seconds * 1000));
    const pad = (n) => String(n).padStart(2, "0");
    return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
  }

  function displaySeconds(seconds) {
    return statusFormatter.format(new Date(seconds * 1000));
  }

  function epochMs(time) {
    if (typeof time === "number") return time * 1000;
    if (typeof time === "string") return Date.parse(time);
    return Date.UTC(time.year, time.month - 1, time.day);
  }

  const chart = LightweightCharts.createChart($("chart"), {
    autoSize: true,
    attributionLogo: true,
    layout: { background: { type: "solid", color: "#090e15" }, textColor: "#aab5c5" },
    grid: { vertLines: { color: "#17202d" }, horzLines: { color: "#17202d" } },
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
    upColor: "#26a69a",
    downColor: "#ef5350",
    borderVisible: false,
    wickUpColor: "#26a69a",
    wickDownColor: "#ef5350",
  });
  const volume = chart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: "volume" },
    priceScaleId: "volume",
  });
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

  const candle = (b) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c });
  const volumeBar = (b) => ({
    time: b.t,
    value: b.v,
    color: b.c >= b.o ? "rgba(38,166,154,.46)" : "rgba(239,83,80,.46)",
  });
  function render(b) {
    candles.update(candle(b));
    volume.update(volumeBar(b));
  }
  function reset(bars) {
    candles.setData(bars.map(candle));
    volume.setData(bars.map(volumeBar));
    chart.timeScale().fitContent();
  }
  function error(message = "") { $("error").textContent = message; }

  async function api(path, opts = {}) {
    const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try { message = (await response.json()).error || message; } catch {}
      throw new Error(message);
    }
    return response.json();
  }

  function update(snapshot) {
    if (!snapshot) return;
    lastState = snapshot.state || lastState;
    $("state-status").textContent = lastState;
    $("contract-status").textContent = snapshot.contract || $("contract-status").textContent;
    $("time-status").textContent = snapshot.cursor ? displaySeconds(snapshot.cursor) : "No session";
    $("play").disabled = !sessionId || lastState === "PLAYING";
    $("pause").disabled = !sessionId || lastState !== "PLAYING";
    $("next").disabled = !sessionId || lastState === "PLAYING" || lastState === "FINISHED";
    $("restart").disabled = !sessionId;
  }

  function command(type, extra = {}) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      error("Replay socket is not connected");
      return;
    }
    ws.send(JSON.stringify({ type, ...extra }));
  }

  function connect(path) {
    if (ws) ws.close();
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${protocol}://${location.host}${path}`);
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "bar") render(message.bar);
      else if (message.type === "bars_batch") message.bars.forEach(render);
      else if (message.type === "reset") {
        reset(message.warmup || []);
        update(message.snapshot);
      } else if (message.type === "error") error(message.error);
      else update(message);
    };
    ws.onerror = () => error("Replay WebSocket disconnected");
  }

  async function loadContracts() {
    const data = await api("/api/contracts");
    $("contract").innerHTML = data.contracts.map((c) => `<option value="${c.contract}">${c.contract}</option>`).join("");
    if (data.contracts.length) selectContract(data.contracts[0].contract, data.contracts[0]);
  }

  async function selectContract(name, provided) {
    const contract = provided || await api(`/api/contracts/${encodeURIComponent(name)}`);
    $("range").textContent = `${displaySeconds(contract.first_time)} → ${displaySeconds(contract.last_time)} · ${Number(contract.bars).toLocaleString()} bars`;
    $("start").value = inputValueFromSeconds(contract.first_time);
  }

  $("contract").onchange = () => selectContract($("contract").value).catch((e) => error(e.message));
  $("start-btn").onclick = async () => {
    try {
      error();
      const raw = $("start").value;
      if (!raw) throw new Error("Choose a start time");
      const result = await api("/api/replay/sessions", {
        method: "POST",
        body: JSON.stringify({
          contract: $("contract").value,
          start: wallTimeToUtcIso(raw),
          warmup: Number($("warmup").value || 300),
        }),
      });
      sessionId = result.session_id;
      reset(result.warmup || []);
      update(result);
      connect(result.websocket);
    } catch (e) {
      error(e.message);
    }
  };
  $("play").onclick = () => command("play", { speed });
  $("pause").onclick = () => command("pause");
  $("next").onclick = () => command("step");
  $("restart").onclick = () => command("restart");
  $("speeds").onclick = (event) => {
    const button = event.target.closest("button[data-speed]");
    if (!button) return;
    document.querySelectorAll("#speeds button").forEach((x) => x.classList.remove("active"));
    button.classList.add("active");
    speed = button.dataset.speed === "max" ? "max" : Number(button.dataset.speed);
    if (lastState === "PLAYING") command("play", { speed });
  };

  loadContracts().catch((e) => error(e.message));
  update({ state: "STOPPED" });
})();
