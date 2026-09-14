(() => {
  const TV = window.LightweightCharts;
  const LCD = window.LightweightChartsDrawing;
  const sessionFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  });

  // Single source of truth for chart colors is the CSS custom properties on :root
  // (see style.css). Nothing here should hardcode a hex value as a *default*; the
  // color pickers wired up below let the user override any of these at runtime.
  function readTheme() {
    const style = getComputedStyle(document.documentElement);
    const v = (name, fallback) => (style.getPropertyValue(name) || fallback).trim();
    return {
      sma5: v("--chart-sma5", "#4da3ff"),
      sma10: v("--chart-sma10", "#34d399"),
      sma20: v("--chart-sma20", "#f0b90b"),
      sma60: v("--chart-sma60", "#ff8a3d"),
      vwap: v("--chart-vwap", "#bb86fc"),
      overlay: v("--chart-overlay", "#f0b90b"),
    };
  }
  const THEME = readTheme();

  function normalize(raw) {
    return {
      time: Number(raw.t ?? raw.time),
      open: Number(raw.o ?? raw.open),
      high: Number(raw.h ?? raw.high),
      low: Number(raw.l ?? raw.low),
      close: Number(raw.c ?? raw.close),
      volume: Number(raw.v ?? raw.volume),
    };
  }

  function sessionKey(seconds) {
    const parts = Object.fromEntries(
      sessionFormatter.formatToParts(new Date(seconds * 1000))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, part.value]),
    );
    const date = new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)));
    if (Number(parts.hour) >= 18) date.setUTCDate(date.getUTCDate() + 1);
    return date.toISOString().slice(0, 10);
  }

  // period-based SMAs the toolbar exposes, plus VWAP (session-anchored, no period)
  const SMA_PERIODS = { sma5: 5, sma10: 10, sma20: 20, sma60: 60 };

  // Draw-tool button -> lightweight-charts-drawing registry type name.
  const DRAW_TOOLS = {
    trend: "trend-line",
    ray: "ray",
    hline: "horizontal-line",
    vline: "vertical-line",
    rect: "rectangle",
    fib: "fib-retracement",
    text: "text-annotation",
  };

  class FutureViewChartTools {
    constructor({ chart, candles, volume, toolbar, legend, container, formatTime }) {
      this.chart = chart;
      this.candles = candles;
      this.volume = volume;
      this.toolbar = toolbar;
      this.legend = legend;
      this.container = container;
      this.formatTime = formatTime;
      this.bars = [];
      this.logScale = false;
      this.autoScale = false;
      // lightweight-charts defaults crosshair.mode to Magnet (CrosshairMode.Magnet = 1),
      // so magnet snapping is already on before we touch it - this just makes the
      // toolbar button reflect that instead of showing off while it's actually on.
      this.magnet = true;
      this.indicatorWidths = { sma5: 2, sma10: 2, sma20: 2, sma60: 2, vwap: 2 };
      this.vwapSession = null;
      this.vwapPriceVolume = 0;
      this.vwapVolume = 0;
      this.indicatorColors = { sma5: THEME.sma5, sma10: THEME.sma10, sma20: THEME.sma20, sma60: THEME.sma60, vwap: THEME.vwap };
      this.indicators = {};
      Object.keys(this.indicatorColors).forEach((key) => {
        this.indicators[key] = chart.addSeries(TV.LineSeries, this._lineOptions(this.indicatorColors[key], this.indicatorWidths[key]));
      });
      Object.values(this.indicators).forEach((series) => series.applyOptions({ visible: false }));

      // Drawing tools: lightweight-charts ships no click-to-draw glue for its own
      // primitives, so DrawingManager only wires selection/drag-editing on attach();
      // the "click toolbar button, click chart, tool appears" flow below is ours.
      this.drawManager = new LCD.DrawingManager();
      this.drawManager.attach(chart, candles, container);
      this.registry = LCD.getToolRegistry();
      this.drawColor = THEME.overlay;
      this.activeDrawTool = null;
      this.interactionHandler = null;
      this.drawingIds = [];
      this.previewId = null;
      this.menuEl = null;
      this.editorEl = null;
      this.dragState = null;

      this._bind();
      this._showLegend(null);
    }

    _lineOptions(color, lineWidth) {
      return {
        color,
        lineWidth,
        crosshairMarkerVisible: false,
        lastValueVisible: true,
        priceLineVisible: false,
      };
    }

    _bind() {
      this.toolbar.addEventListener("click", (event) => {
        const swatch = event.target.closest("button.fv-color-swatch");
        if (swatch) {
          event.stopPropagation();
          if (swatch.dataset.indicatorColor) {
            const key = swatch.dataset.indicatorColor;
            this._openColorPopup(swatch, this.indicatorColors[key], (color) => {
              this._paintSwatch(swatch, color);
              this._setIndicatorColor(key, color);
            });
          } else if (swatch.id === "draw-color") {
            this._openColorPopup(swatch, this.drawColor, (color) => {
              this._paintSwatch(swatch, color);
              this.drawColor = color;
            });
          }
          return;
        }
        const button = event.target.closest("button[data-tool]");
        if (!button) return;
        const tool = button.dataset.tool;
        if (tool in this.indicators) this._toggleIndicator(tool, button);
        else if (tool === "crosshair") this._toggleCrosshair(button);
        else if (tool in DRAW_TOOLS) this._armDrawTool(tool, button);
        else if (tool === "undo") this._undoDrawing();
        else if (tool === "clear") this._clearDrawings();
        else if (tool === "zoom-in") this._zoom(0.72);
        else if (tool === "zoom-out") this._zoom(1.38);
        else if (tool === "fit") this._fit();
        else if (tool === "latest") this.chart.timeScale().scrollToRealTime();
        else if (tool === "log") this._toggleLog(button);
      });
      this.toolbar.querySelectorAll("button.fv-color-swatch[data-indicator-color]").forEach((swatch) => {
        this._paintSwatch(swatch, this.indicatorColors[swatch.dataset.indicatorColor]);
      });
      const drawColorSwatch = this.toolbar.querySelector("#draw-color");
      if (drawColorSwatch) this._paintSwatch(drawColorSwatch, this.drawColor);
      const magnetButton = this.toolbar.querySelector('[data-tool="crosshair"]');
      if (magnetButton) {
        magnetButton.classList.toggle("active", this.magnet);
        magnetButton.setAttribute("aria-pressed", String(this.magnet));
      }



      this.chart.subscribeClick((param) => this._handleDrawClick(param));
      this.chart.subscribeCrosshairMove((param) => {
        this.lastCrosshairParam = param;
        this._showLegend(param);
      });

      // Live dashed preview while placing a multi-anchor drawing (trend/ray/rect/fib) -
      // otherwise nothing is visible between the first click and the completing click.
      this.container.addEventListener("mousemove", (event) => this._handlePreviewMove(event));
      // Right-click a drawing for Delete / Edit text, instead of only Undo (last-drawn) / Clear (all).
      this.container.addEventListener("contextmenu", (event) => this._handleContextMenu(event));
      // Left-drag an existing drawing to move it. DrawingManager.attach() already wires
      // its own container mousedown/mousemove/mouseup for per-anchor resize (only once a
      // drawing is selected and the grab lands within 8px of an anchor) - that fires
      // first since it was registered in the constructor before _bind() runs, so we only
      // need to step aside for that exact case and otherwise own the gesture ourselves.
      this.container.addEventListener("mousedown", (event) => this._handleDragStart(event));
      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        if (this.interactionHandler) this.interactionHandler.onKeyDown("Escape");
        else this._cancelDrawing();
      });
    }

    _containerPoint(event) {
      const rect = this.container.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    }

    _anchorAtPoint(point) {
      const time = this.chart.timeScale().coordinateToTime(point.x);
      const price = this.candles.coordinateToPrice(point.y);
      if (time == null || price == null || !Number.isFinite(price)) return null;
      return { time, price };
    }

    _toggleIndicator(name, button) {
      const visible = !button.classList.contains("active");
      button.classList.toggle("active", visible);
      button.setAttribute("aria-pressed", String(visible));
      this.indicators[name].applyOptions({ visible });
    }

    _setIndicatorColor(key, color) {
      this.indicatorColors[key] = color;
      this.indicators[key].applyOptions({ color });
    }

    _setIndicatorWidth(key, width) {
      this.indicatorWidths[key] = width;
      this.indicators[key].applyOptions({ lineWidth: width });
    }

    _toggleCrosshair(button) {
      this.magnet = !this.magnet;
      button.classList.toggle("active", this.magnet);
      button.setAttribute("aria-pressed", String(this.magnet));
      this.chart.applyOptions({
        crosshair: { mode: this.magnet ? TV.CrosshairMode.Magnet : TV.CrosshairMode.Normal },
      });
    }

    // Anchor placement (idle -> placing -> complete, Escape -> cancel) is delegated to
    // the plugin's own InteractionHandler FSM rather than hand-rolled bookkeeping for
    // tools that need 2+ clicks - DrawingManager itself never wires this up
    // (createOverlay-style click-to-place is opt-in), but the FSM it ships for exactly
    // this purpose is public and exported.
    //
    // Single-anchor tools (h-line, v-line) bypass the FSM: its onMouseDown only checks
    // requiredAnchors in the 'placing' branch, never in 'idle', so a 1-anchor tool adds
    // its one anchor, lands in 'placing', and then silently never reaches 'complete' -
    // confirmed by tracing state after a real click (stuck at "placing", zero drawings
    // created). That's a real defect in the library for this case, not a missing
    // feature to build around inside it, so these tools place directly on click instead,
    // the same way text-annotation already does.
    _armDrawTool(tool, button) {
      const wasArmed = this.activeDrawTool === tool;
      this._cancelDrawing();
      if (wasArmed) return;
      this.activeDrawTool = tool;
      button.classList.add("armed");
      // Match TradingView: chart panning/scroll-zoom is suspended while a drawing tool
      // is armed, so a natural click-drag-release places the tool instead of silently
      // scrolling the chart out from under the cursor mid-draw.
      this.chart.applyOptions({ handleScroll: false, handleScale: false });
      if (tool === "text") return;
      const registryType = DRAW_TOOLS[tool];
      const def = this.registry.get(registryType);
      if (def.requiredAnchors <= 1) return;
      this.interactionHandler = new LCD.InteractionHandler({
        requiredAnchors: def.requiredAnchors,
        pixelToChart: (point) => this._anchorAtPoint(point),
        onPreviewMove: (previewAnchor) => this._renderPreview(registryType, this.interactionHandler.getAnchors(), previewAnchor),
        onComplete: () => {
          this._finalizeDrawing(registryType, this.interactionHandler.getAnchors(), {});
          this._cancelDrawing();
        },
        onCancel: () => this._cancelDrawing(),
      });
    }

    _cancelDrawing() {
      this.toolbar.querySelectorAll("button[data-tool].armed").forEach((b) => b.classList.remove("armed"));
      this.activeDrawTool = null;
      this.interactionHandler = null;
      this.chart.applyOptions({ handleScroll: true, handleScale: true });
      this._clearPreview();
      this._closeEditor();
    }

    _handleDrawClick(param) {
      if (this.editorEl) return; // don't let a click behind the text editor start a new anchor
      if (!this.activeDrawTool || !param.point) return;

      if (this.activeDrawTool === "text") {
        if (!param.time) return;
        const price = this.candles.coordinateToPrice(param.point.y);
        if (price == null || !Number.isFinite(price)) return;
        const anchor = { time: param.time, price };
        this._openTextEditor(param.point, "", (text) => {
          if (text) this._finalizeDrawing("text-annotation", [anchor], { text, backgroundColor: "transparent" });
          this._cancelDrawing();
        });
        return;
      }

      const registryType = DRAW_TOOLS[this.activeDrawTool];
      const def = this.registry.get(registryType);
      if (def.requiredAnchors <= 1) {
        if (!param.time) return;
        const price = this.candles.coordinateToPrice(param.point.y);
        if (price == null || !Number.isFinite(price)) return;
        this._finalizeDrawing(registryType, [{ time: param.time, price }], {});
        this._cancelDrawing();
        return;
      }

      this.interactionHandler?.onMouseDown({ point: param.point, time: param.time ?? null, price: null, srcEvent: null });
    }

    _finalizeDrawing(registryType, anchors, options) {
      const id = `fv_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      const style = { lineColor: this.drawColor, lineWidth: 2, fillColor: `${this.drawColor}33` };
      const drawing = this.registry.createDrawing(registryType, id, anchors, style, options);
      this.drawManager.addDrawing(drawing);
      this.drawingIds.push(id);
      return id;
    }

    // ---- Live preview: a dashed ghost of the pending drawing that follows the mouse,
    // fed by InteractionHandler's onPreviewMove rather than tracked here. ----
    _handlePreviewMove(event) {
      if (this.interactionHandler && this.activeDrawTool !== "text") {
        this.interactionHandler.onMouseMove({ point: this._containerPoint(event), time: null, price: null, srcEvent: null });
        return;
      }
      // Hover feedback: show a move cursor over a drawing (magnet-widened) when idle,
      // so a line too thin to click precisely still reads as grabbable.
      if (this.dragState || this.activeDrawTool || this.editorEl) return;
      const hit = this._hitTestMagnet(this._containerPoint(event));
      this.container.style.cursor = hit ? "move" : "";
    }

    // testHit() on each drawing type is a fixed, small pixel threshold (5-10px) with no
    // way to widen it from outside - so for a "magnet" that forgives an imprecise click on
    // a thin line, we retry the library's own hitTest at a small ring of points around the
    // cursor instead of the exact point, rather than reimplementing per-type hit geometry.
    static MAGNET_HIT_RADIUS = 6;

    _hitTestMagnet(point) {
      let hit = this.drawManager.hitTest(point);
      if (hit) return hit;
      const r = FutureViewChartTools.MAGNET_HIT_RADIUS;
      const offsets = [[r, 0], [-r, 0], [0, r], [0, -r], [r, r], [r, -r], [-r, r], [-r, -r]];
      for (const [dx, dy] of offsets) {
        hit = this.drawManager.hitTest({ x: point.x + dx, y: point.y + dy });
        if (hit) return hit;
      }
      return null;
    }

    _viewport() {
      const rect = this.container.getBoundingClientRect();
      return {
        width: rect.width,
        height: rect.height,
        timeScale: {
          coordinateToTime: (x) => this.chart.timeScale().coordinateToTime(x),
          timeToCoordinate: (t) => this.chart.timeScale().timeToCoordinate(t),
          logicalToCoordinate: (l) => this.chart.timeScale().logicalToCoordinate(l),
        },
        priceScale: {
          coordinateToPrice: (y) => this.candles.coordinateToPrice(y),
          priceToCoordinate: (p) => this.candles.priceToCoordinate(p),
        },
      };
    }

    _handleDragStart(event) {
      if (event.button !== 0 || this.editorEl || this.activeDrawTool) return;
      const point = this._containerPoint(event);
      const hit = this._hitTestMagnet(point);
      if (!hit) return;

      // A grab within 8px of an anchor on an already-selected drawing is a resize -
      // DrawingManager's own mousedown handler (wired in attach(), runs before this one)
      // already started that drag, so back off instead of also translating the whole shape.
      const isSelected = this.drawManager.getSelectedDrawing()?.id === hit.id;
      if (isSelected && hit.hitTestAnchor(point, this._viewport()) !== null) return;

      const time = this.chart.timeScale().coordinateToTime(point.x);
      const price = this.candles.coordinateToPrice(point.y);
      if (time == null || price == null || !Number.isFinite(price)) return;

      event.preventDefault();
      this.dragState = {
        drawing: hit,
        startAnchors: hit.anchors.map((a) => ({ ...a })),
        startTime: time,
        startPrice: price,
      };
      this.chart.applyOptions({ handleScroll: false, handleScale: false });
      this.container.style.cursor = "move";
      this._onDragMove = (e) => this._handleDragMove(e);
      this._onDragEnd = (e) => this._handleDragEnd(e);
      document.addEventListener("mousemove", this._onDragMove);
      document.addEventListener("mouseup", this._onDragEnd);
    }

    _handleDragMove(event) {
      if (!this.dragState) return;
      const point = this._containerPoint(event);
      const time = this.chart.timeScale().coordinateToTime(point.x);
      const price = this.candles.coordinateToPrice(point.y);
      if (time == null || price == null || !Number.isFinite(price)) return;
      const timeDelta = time - this.dragState.startTime;
      const priceDelta = price - this.dragState.startPrice;
      const newAnchors = this.dragState.startAnchors.map((a) => ({ time: a.time + timeDelta, price: a.price + priceDelta }));
      this.dragState.drawing.setAnchors(newAnchors);
    }

    _handleDragEnd() {
      if (!this.dragState) return;
      this.dragState = null;
      this.chart.applyOptions({ handleScroll: true, handleScale: true });
      this.container.style.cursor = "";
      document.removeEventListener("mousemove", this._onDragMove);
      document.removeEventListener("mouseup", this._onDragEnd);
    }

    _renderPreview(registryType, anchors, previewAnchor) {
      const style = { lineColor: this.drawColor, lineWidth: 1, lineDash: [4, 4], fillColor: `${this.drawColor}1a` };
      const drawing = this.registry.createDrawing(registryType, "__preview__", [...anchors, previewAnchor], style, {});
      if (this.previewId) this.drawManager.removeDrawing(this.previewId);
      this.drawManager.addDrawing(drawing);
      this.previewId = drawing.id;
    }

    _clearPreview() {
      if (this.previewId) this.drawManager.removeDrawing(this.previewId);
      this.previewId = null;
    }

    _undoDrawing() {
      const id = this.drawingIds.pop();
      if (id) this.drawManager.removeDrawing(id);
    }

    _clearDrawings() {
      this.drawManager.clearAll();
      this.drawingIds = [];
    }

    _removeDrawingById(id) {
      this.drawManager.removeDrawing(id);
      this.drawingIds = this.drawingIds.filter((existing) => existing !== id);
    }

    // ---- Right-click menu: makes a drawing (or an indicator line) feel like an
    // object you can act on - restyle or delete - not just something Undo/Clear touches. ----
    _handleContextMenu(event) {
      const point = this._containerPoint(event);
      const hit = this._hitTestMagnet(point);
      if (hit) {
        event.preventDefault();
        return this._showDrawingMenu(event.clientX, event.clientY, hit);
      }
      const indicatorKey = this._hitTestIndicator(point);
      if (indicatorKey) {
        event.preventDefault();
        return this._showIndicatorMenu(event.clientX, event.clientY, indicatorKey);
      }
    }

    _hitTestIndicator(point) {
      const data = this.lastCrosshairParam?.seriesData;
      if (!data) return null;
      const TOLERANCE = 6;
      for (const [key, series] of Object.entries(this.indicators)) {
        if (!series.options().visible) continue;
        const point2 = data.get(series);
        const value = typeof point2 === "number" ? point2 : point2?.value;
        if (value == null) continue;
        const y = series.priceToCoordinate(value);
        if (y != null && Math.abs(y - point.y) <= TOLERANCE) return key;
      }
      return null;
    }

    _hideMenu() {
      if (this.menuEl) {
        this.menuEl.remove();
        this.menuEl = null;
      }
    }

    _openMenu(clientX, clientY, buildRows) {
      this._hideMenu();
      const menu = document.createElement("div");
      menu.className = "fv-context-menu";
      menu.style.left = `${clientX}px`;
      menu.style.top = `${clientY}px`;
      buildRows(menu);
      document.body.appendChild(menu);
      this.menuEl = menu;
      const closeOnce = (ev) => {
        if (!menu.contains(ev.target)) {
          this._hideMenu();
          document.removeEventListener("mousedown", closeOnce, true);
        }
      };
      setTimeout(() => document.addEventListener("mousedown", closeOnce, true), 0);
      return menu;
    }

    _menuRow(menu, label, control) {
      const row = document.createElement("div");
      row.className = "fv-menu-row";
      const span = document.createElement("span");
      span.textContent = label;
      row.append(span, control);
      menu.appendChild(row);
      return row;
    }

    // TradingView's own color controls are a swatch button that opens a small preset
    // palette, not a bare native <input type="color"> - matching that keeps picking a
    // color a single click for the common case, with the native picker kept only as a
    // "Custom" fallback swatch inside the popup.
    static PRESET_COLORS = [
      "#f0b90b", "#ffffff", "#b2b5be", "#787b86", "#2962ff", "#089981",
      "#f23645", "#ff9800", "#9c27b0", "#00bcd4", "#4caf50", "#000000",
    ];

    _menuColorRow(menu, label, value, onChange) {
      const swatch = document.createElement("button");
      swatch.type = "button";
      swatch.className = "fv-color-swatch";
      this._paintSwatch(swatch, value);
      swatch.onclick = (event) => {
        event.stopPropagation();
        this._openColorPopup(swatch, value, (color) => {
          value = color;
          this._paintSwatch(swatch, color);
          onChange(color);
        });
      };
      this._menuRow(menu, label, swatch);
    }

    _paintSwatch(swatch, value) {
      swatch.style.background =
        !value || value === "transparent"
          ? "repeating-conic-gradient(#666 0% 25%, #333 0% 50%) 50% / 8px 8px"
          : value;
    }

    _openColorPopup(anchorEl, currentValue, onChange) {
      document.querySelector(".fv-color-popup")?.remove();
      const popup = document.createElement("div");
      popup.className = "fv-color-popup";

      FutureViewChartTools.PRESET_COLORS.forEach((color) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "fv-color-swatch-item";
        item.style.background = color;
        if (color.toLowerCase() === String(currentValue || "").toLowerCase()) item.classList.add("selected");
        item.onclick = (event) => {
          event.stopPropagation();
          onChange(color);
          popup.remove();
        };
        popup.appendChild(item);
      });

      const custom = document.createElement("input");
      custom.type = "color";
      custom.className = "fv-color-swatch-item fv-color-custom";
      custom.title = "Custom color";
      custom.value = /^#[0-9a-f]{6}$/i.test(currentValue) ? currentValue : "#ffffff";
      custom.onclick = (event) => event.stopPropagation();
      custom.oninput = () => onChange(custom.value);
      popup.appendChild(custom);

      document.body.appendChild(popup);
      const rect = anchorEl.getBoundingClientRect();
      popup.style.left = `${rect.left}px`;
      popup.style.top = `${rect.bottom + 4}px`;

      const closeOnce = (event) => {
        if (!popup.contains(event.target)) {
          popup.remove();
          document.removeEventListener("mousedown", closeOnce, true);
        }
      };
      setTimeout(() => document.addEventListener("mousedown", closeOnce, true), 0);
    }

    _menuSelectRow(menu, label, value, options, onChange) {
      const select = document.createElement("select");
      options.forEach(([optValue, optLabel]) => {
        const opt = document.createElement("option");
        opt.value = optValue;
        opt.textContent = optLabel;
        opt.selected = optValue === String(value);
        select.appendChild(opt);
      });
      select.onchange = () => onChange(select.value);
      this._menuRow(menu, label, select);
    }

    _menuCheckboxRow(menu, label, checked, onChange) {
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!checked;
      input.onchange = () => onChange(input.checked);
      this._menuRow(menu, label, input);
    }

    _menuButton(menu, label, onClick) {
      const button = document.createElement("button");
      button.className = "fv-menu-action";
      button.textContent = label;
      button.onclick = onClick;
      menu.appendChild(button);
    }

    _menuDivider(menu) {
      const hr = document.createElement("div");
      hr.className = "fv-menu-divider";
      menu.appendChild(hr);
    }

    static LINE_DASHES = { solid: [], dashed: [6, 4], dotted: [2, 2] };

    _dashKey(dash) {
      const entry = Object.entries(FutureViewChartTools.LINE_DASHES).find(([, value]) => JSON.stringify(value) === JSON.stringify(dash || []));
      return entry ? entry[0] : "solid";
    }

    static TEXT_FONT_SIZES = ["10", "12", "14", "16", "18", "24", "32"];
    static TEXT_BG_TRANSPARENT = "transparent";

    _showDrawingMenu(clientX, clientY, drawing) {
      this._openMenu(clientX, clientY, (menu) => {
        if (drawing.type === "text-annotation") {
          this._menuColorRow(menu, "Text color", drawing.style.labelColor || "#2962ff", (v) => { drawing.style = { ...drawing.style, labelColor: v }; });
          this._menuSelectRow(menu, "Text size", String(drawing.textOptions?.fontSize ?? 14), FutureViewChartTools.TEXT_FONT_SIZES.map((s) => [s, `${s}px`]), (v) => {
            drawing.setTextOptions({ fontSize: Number(v) });
          });
          const bgIsTransparent = !drawing.textOptions?.backgroundColor || drawing.textOptions.backgroundColor === FutureViewChartTools.TEXT_BG_TRANSPARENT;
          this._menuColorRow(menu, "Background", bgIsTransparent ? "#000000" : drawing.textOptions.backgroundColor.slice(0, 7), (v) => {
            drawing.setTextOptions({ backgroundColor: v });
          });
          this._menuCheckboxRow(menu, "Transparent background", bgIsTransparent, (checked) => {
            drawing.setTextOptions({ backgroundColor: checked ? FutureViewChartTools.TEXT_BG_TRANSPARENT : "#000000" });
          });
          const borderIsNone = !drawing.textOptions?.borderColor || drawing.textOptions.borderColor === "transparent";
          this._menuColorRow(menu, "Outline", borderIsNone ? drawing.style.lineColor : drawing.textOptions.borderColor.slice(0, 7), (v) => {
            drawing.setTextOptions({ borderColor: v });
          });
          this._menuCheckboxRow(menu, "No outline", borderIsNone, (checked) => {
            drawing.setTextOptions({ borderColor: checked ? "transparent" : drawing.style.lineColor });
          });
        } else {
          this._menuColorRow(menu, "Line color", drawing.style.lineColor, (v) => { drawing.style = { ...drawing.style, lineColor: v }; });
          this._menuSelectRow(menu, "Line style", this._dashKey(drawing.style.lineDash), [["solid", "Solid"], ["dashed", "Dashed"], ["dotted", "Dotted"]], (v) => {
            drawing.style = { ...drawing.style, lineDash: FutureViewChartTools.LINE_DASHES[v] };
          });
          this._menuSelectRow(menu, "Line width", String(drawing.style.lineWidth), [["1", "1px"], ["2", "2px"], ["3", "3px"], ["4", "4px"]], (v) => {
            drawing.style = { ...drawing.style, lineWidth: Number(v) };
          });
        }

        if (drawing.type === "rectangle") {
          this._menuColorRow(menu, "Fill color", (drawing.style.fillColor || "#00000033").slice(0, 7), (v) => {
            drawing.style = { ...drawing.style, fillColor: `${v}33` };
          });
          this._menuCheckboxRow(menu, "Filled", drawing.rectangleOptions?.filled, (checked) => drawing.setRectangleOptions({ filled: checked }));
        }

        if (drawing.type === "fib-retracement") {
          this._menuDivider(menu);
          this._menuCheckboxRow(menu, "Extend lines", drawing.fibOptions?.extendLines, (checked) => drawing.setFibOptions({ extendLines: checked }));
          this._menuCheckboxRow(menu, "Reverse", drawing.fibOptions?.reverseDirection, (checked) => drawing.setFibOptions({ reverseDirection: checked }));
          this._menuCheckboxRow(menu, "Show prices", drawing.fibOptions?.showPrices, (checked) => drawing.setFibOptions({ showPrices: checked }));
          this._menuCheckboxRow(menu, "Show %", drawing.fibOptions?.showPercentages, (checked) => drawing.setFibOptions({ showPercentages: checked }));
        }

        this._menuDivider(menu);
        if (drawing.type === "text-annotation") {
          this._menuButton(menu, "Edit text", () => {
            this._hideMenu();
            const rect = this.container.getBoundingClientRect();
            const anchorPoint = this.chart.timeScale().timeToCoordinate(drawing.anchors[0].time);
            const priceCoord = this.candles.priceToCoordinate(drawing.anchors[0].price);
            const screenPoint = { x: anchorPoint ?? clientX - rect.left, y: priceCoord ?? clientY - rect.top };
            this._openTextEditor(screenPoint, drawing.textOptions?.text || "", (text) => {
              if (text) drawing.setText(text);
            });
          });
        }
        this._menuButton(menu, "Delete", () => {
          this._removeDrawingById(drawing.id);
          this._hideMenu();
        });
      });
    }

    _showIndicatorMenu(clientX, clientY, key) {
      this._openMenu(clientX, clientY, (menu) => {
        this._menuColorRow(menu, "Line color", this.indicatorColors[key], (v) => this._setIndicatorColor(key, v));
        this._menuSelectRow(menu, "Line width", String(this.indicatorWidths[key]), [["1", "1px"], ["2", "2px"], ["3", "3px"], ["4", "4px"]], (v) => this._setIndicatorWidth(key, Number(v)));
        this._menuDivider(menu);
        this._menuButton(menu, "Remove", () => {
          const button = this.toolbar.querySelector(`[data-tool="${key}"]`);
          if (button) this._toggleIndicator(key, button);
          this._hideMenu();
        });
      });
    }

    // ---- Inline text editor: a small contenteditable box positioned at the click,
    // instead of a blocking window.prompt(). Enter commits, Escape/blur-empty cancels. ----
    _openTextEditor(point, initialText, onCommit) {
      this._closeEditor();
      const rect = this.container.getBoundingClientRect();
      const box = document.createElement("div");
      box.className = "fv-text-editor";
      box.contentEditable = "true";
      box.textContent = initialText;
      box.style.left = `${rect.left + point.x}px`;
      box.style.top = `${rect.top + point.y}px`;
      box.style.borderColor = this.drawColor;
      document.body.appendChild(box);
      this.editorEl = box;
      box.focus();
      document.execCommand?.("selectAll", false, null);

      let settled = false;
      const commit = () => {
        if (settled) return;
        settled = true;
        const text = box.textContent.trim();
        box.remove();
        if (this.editorEl === box) this.editorEl = null;
        onCommit(text);
      };
      const cancel = () => {
        if (settled) return;
        settled = true;
        box.remove();
        if (this.editorEl === box) this.editorEl = null;
      };
      box.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          commit();
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancel();
        }
      });
      box.addEventListener("blur", commit);
    }

    _closeEditor() {
      if (this.editorEl) {
        this.editorEl.remove();
        this.editorEl = null;
      }
    }

    _toggleLog(button) {
      this.logScale = !this.logScale;
      button.classList.toggle("active", this.logScale);
      button.setAttribute("aria-pressed", String(this.logScale));
      this.candles.priceScale().applyOptions({
        mode: this.logScale ? TV.PriceScaleMode.Logarithmic : TV.PriceScaleMode.Normal,
      });
      button.textContent = this.logScale ? "Log" : "Linear";
    }

    _fit() {
      this.candles.priceScale().applyOptions({ autoScale: true });
      this.chart.timeScale().fitContent();
      this.candles.priceScale().applyOptions({ autoScale: false });
    }

    _zoom(factor) {
      const range = this.chart.timeScale().getVisibleLogicalRange();
      if (!range) return this.chart.timeScale().fitContent();
      const center = (range.from + range.to) / 2;
      const half = Math.max(5, ((range.to - range.from) * factor) / 2);
      this.chart.timeScale().setVisibleLogicalRange({ from: center - half, to: center + half });
    }

    _showLegend(param) {
      let bar = null;
      let volume = null;
      if (param?.time != null && param.seriesData) {
        bar = param.seriesData.get(this.candles) ?? null;
        volume = param.seriesData.get(this.volume)?.value ?? null;
      }
      if (!bar && this.bars.length) {
        bar = this.bars.at(-1);
        volume = bar.volume;
      }
      if (!bar) {
        this.legend.textContent = "O —  H —  L —  C —  V —";
        return;
      }
      const time = Number(param?.time ?? bar.time);
      this.legend.textContent = `${this.formatTime(time)}  O ${Number(bar.open).toFixed(2)}  H ${Number(bar.high).toFixed(2)}  L ${Number(bar.low).toFixed(2)}  C ${Number(bar.close).toFixed(2)}  V ${Number(volume ?? 0).toLocaleString()}`;
    }

    _indicatorData() {
      const series = { sma5: [], sma10: [], sma20: [], sma60: [] };
      const sums = { sma5: 0, sma10: 0, sma20: 0, sma60: 0 };
      const vwap = [];
      let currentSession = null;
      let cumulativePriceVolume = 0;
      let cumulativeVolume = 0;
      this.bars.forEach((bar, index) => {
        Object.entries(SMA_PERIODS).forEach(([key, period]) => {
          sums[key] += bar.close;
          if (index >= period) sums[key] -= this.bars[index - period].close;
          if (index >= period - 1) series[key].push({ time: bar.time, value: sums[key] / period });
        });
        const key = sessionKey(bar.time);
        if (key !== currentSession) {
          currentSession = key;
          cumulativePriceVolume = 0;
          cumulativeVolume = 0;
        }
        const typical = (bar.high + bar.low + bar.close) / 3;
        cumulativePriceVolume += typical * bar.volume;
        cumulativeVolume += bar.volume;
        if (cumulativeVolume > 0) vwap.push({ time: bar.time, value: cumulativePriceVolume / cumulativeVolume });
      });
      this.vwapSession = currentSession;
      this.vwapPriceVolume = cumulativePriceVolume;
      this.vwapVolume = cumulativeVolume;
      return { ...series, vwap };
    }

    _refreshIndicators() {
      const data = this._indicatorData();
      Object.entries(data).forEach(([name, values]) => this.indicators[name].setData(values));
    }

    reset(rawBars) {
      this.bars = rawBars.map(normalize);
      this._refreshIndicators();
      this._showLegend(null);
    }

    append(rawBar) {
      const replaced = this._appendNormalized(normalize(rawBar));
      if (replaced) this._refreshIndicators();
      else this._updateIndicatorsForLastBar();
      this._showLegend(null);
    }

    appendMany(rawBars) {
      let rebuild = false;
      rawBars.map(normalize).forEach((bar) => {
        const replaced = this._appendNormalized(bar);
        if (replaced) rebuild = true;
        else if (!rebuild) this._updateIndicatorsForLastBar();
      });
      if (rebuild) this._refreshIndicators();
      this._showLegend(null);
    }

    _appendNormalized(bar) {
      const last = this.bars.at(-1);
      if (last && bar.time < last.time) return true;
      if (last && bar.time === last.time) {
        this.bars[this.bars.length - 1] = bar;
        return true;
      }
      this.bars.push(bar);
      return false;
    }

    _updateIndicatorsForLastBar() {
      const bar = this.bars.at(-1);
      if (!bar) return;
      Object.entries(SMA_PERIODS).forEach(([key, period]) => {
        if (this.bars.length < period) return;
        const values = this.bars.slice(-period);
        this.indicators[key].update({ time: bar.time, value: values.reduce((sum, item) => sum + item.close, 0) / period });
      });
      const key = sessionKey(bar.time);
      if (key !== this.vwapSession) {
        this.vwapSession = key;
        this.vwapPriceVolume = 0;
        this.vwapVolume = 0;
      }
      this.vwapPriceVolume += ((bar.high + bar.low + bar.close) / 3) * bar.volume;
      this.vwapVolume += bar.volume;
      if (this.vwapVolume > 0) {
        this.indicators.vwap.update({ time: bar.time, value: this.vwapPriceVolume / this.vwapVolume });
      }
    }
  }

  window.FutureViewChartTools = FutureViewChartTools;
})();
