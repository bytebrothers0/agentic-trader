/**
 * Backtest Review — journal trades on historical candles.
 * Data: /api/candles (M15) + /api/backtest/trades (journal CSV).
 */
document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) lucide.createIcons();

  const state = {
    candles: [],
    trades: [],
    filter: "all",
    sel: 0,
    tradeSeries: [],
    structSeries: [],
    structLabels: [],
    structSeq: 0,
    structCache: null,
    hideBot: false,
    hideConfluence: true, // confluence zones off until asked for
  };

  const container = document.getElementById("btChart");
  const labelLayer = document.getElementById("btLabelLayer");
  const tradesBody = document.getElementById("tradesBody");
  const tradeDetail = document.getElementById("tradeDetail");
  const tradeCounter = document.getElementById("tradeCounter");
  const filterPills = document.querySelectorAll(".mode-pill[data-f]");

  const chart = LightweightCharts.createChart(container, {
    layout: {
      background: { color: "#121418" },
      textColor: "#9aa5b5",
      fontFamily: "'Inter', -apple-system, sans-serif",
      fontSize: 11,
    },
    grid: {
      vertLines: { color: "#1e222b", style: 2 },
      horzLines: { color: "#1e222b", style: 2 },
    },
    rightPriceScale: { borderColor: "#2b313d" },
    timeScale: { borderColor: "#2b313d", timeVisible: true, secondsVisible: false },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#089981",
    downColor: "#f23645",
    borderVisible: false,
    wickUpColor: "#089981",
    wickDownColor: "#f23645",
  });

  window.addEventListener("resize", () => {
    chart.resize(container.clientWidth, container.clientHeight);
  });

  const tsOf = (iso) => Math.floor(Date.parse(iso) / 1000);

  function candleIdxAtOrBefore(ts) {
    let idx = 0;
    for (let i = 0; i < state.candles.length; i++) {
      if (state.candles[i].time <= ts) idx = i;
      else break;
    }
    return idx;
  }

  function clearTrades() {
    state.tradeSeries.forEach((s) => {
      try { chart.removeSeries(s); } catch (e) {}
    });
    state.tradeSeries = [];
    try { candleSeries.setMarkers([]); } catch (e) {}
  }

  // ---- Setup structure overlay (TS / BOS / QM of the selected trade) ----

  function clearStructure() {
    state.structSeries.forEach((s) => {
      try { chart.removeSeries(s); } catch (e) {}
    });
    state.structSeries = [];
    state.structLabels = [];
    if (labelLayer) labelLayer.innerHTML = "";
  }

  function structRay(price, t0, t1, color, style, width) {
    const s = chart.addLineSeries({
      color, lineWidth: width || 1, lineStyle: style,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    s.setData([{ time: t0, value: price }, { time: t1, value: price }]);
    state.structSeries.push(s);
  }

  function structFill(top, bottom, t0, t1, css) {
    if (typeof chart.addBaselineSeries !== "function") return;
    const CLEAR = "rgba(0, 0, 0, 0)";
    const band = chart.addBaselineSeries({
      baseValue: { type: "price", price: top },
      topLineColor: CLEAR, bottomLineColor: CLEAR,
      topFillColor1: css, topFillColor2: css,
      bottomFillColor1: css, bottomFillColor2: css,
      lineWidth: 1, crosshairMarkerVisible: false,
      priceLineVisible: false, lastValueVisible: false,
    });
    band.setData([{ time: t0, value: bottom }, { time: t1, value: bottom }]);
    state.structSeries.push(band);
  }

  function pushStructLabel(tBar, price, text, cls, conf, clsFull) {
    state.structLabels.push({ tBar, price, text, cls, conf: !!conf, clsFull });
  }

  function renderStructLabels() {
    if (!labelLayer) return;
    labelLayer.innerHTML = "";
    const frag = document.createDocumentFragment();
    let visible = state.hideBot ? [] : state.structLabels;
    if (state.hideConfluence) visible = visible.filter((lb) => !lb.conf);
    [...visible, ...(state.drawingLabels || [])].forEach((lb) => {
      let x = null, y = null;
      try { x = chart.timeScale().timeToCoordinate(lb.tBar); } catch (e) {}
      try { y = candleSeries.priceToCoordinate(lb.price); } catch (e) {}
      const el = document.createElement("div");
      el.className = ("chart-tag " + (lb.clsFull || ("tag-plain " + lb.cls))).trim();
      el.textContent = lb.text;
      if (x === null || x === undefined || y === null || y === undefined) {
        el.style.display = "none";
      } else {
        el.style.display = "block";
        el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
      }
      frag.appendChild(el);
    });
    labelLayer.appendChild(frag);
  }

  try {
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => renderStructLabels());
  } catch (e) {}

  function barIdxAtOrBefore(ts) {
    let idx = 0;
    for (let i = 0; i < state.candles.length; i++) {
      if (state.candles[i].time <= ts) idx = i;
      else break;
    }
    return idx;
  }

  async function drawStructure(trade) {
    clearStructure();
    state.structCache = null;
    if (!trade || state.hideBot) return;
    const mySeq = ++state.structSeq;
    const params = new URLSearchParams({
      signal_date: trade.signal_date,
      direction: trade.direction,
      entry: trade.entry,
      model: (state.journalId || "").includes("LUAP") ? "luap_m15"
        : (state.journalId || "").includes("SIMON") ? "simon_m15"
        : "ts_m15",
    });
    let st = null;
    try {
      const res = await fetch(`/api/backtest/structure?${params.toString()}`);
      if (!res.ok) return;
      st = await res.json();
    } catch (e) {
      return;
    }
    if (mySeq !== state.structSeq) return; // superseded by newer selection
    state.structCache = { trade, st };
    renderStructure(st, trade);
  }

  function renderStructure(st, trade) {
    if (!st || !trade || state.hideBot) return;
    const fillT = trade.fill_date ? tsOf(trade.fill_date) : tsOf(trade.signal_date);
    const endIdx = Math.min(state.candles.length - 1, barIdxAtOrBefore(fillT) + 5);
    const endT = state.candles.length ? state.candles[endIdx].time : fillT;
    // Visual language AND spans match the live terminal (/): TS rays run
    // candle1 -> candle2+2 with the tag at 75%; BOS/QM/IDM run formation
    // -> +8 bars with mid tags. (Zones keep the setup-window span: the
    // payload carries no formation bar for them.)
    const items = [];
    const tsHigh = st.ts && st.ts.side
      ? st.ts.side === "HIGH"
      : (trade.direction || "").toUpperCase() !== "BULLISH";
    if (st.ts && st.ts.price != null && st.ts.time) {
      items.push({ ...st.ts,
        color: tsHigh ? "#ff5c6c" : "#00e676",
        tag: tsHigh ? "TS-H" : "TS-L",
        cls: tsHigh ? "ts-high" : "ts-low",
        width: 1, pair: true, // TS pair: candle1 -> candle2, tag at 75%
        style: LightweightCharts.LineStyle.Solid });
    }
    if (st.break && st.break.price != null && st.break.time) {
      const kind = st.break.kind || "BOS";
      const bearish = (trade.direction || "").toUpperCase() !== "BULLISH";
      const color = kind === "CHOCH" ? "#ff9100"
        : kind === "SR" ? (bearish ? "#ff1744" : "#00e676") : "#7aa2ff";
      const tag = kind === "SR" ? (bearish ? "SBR" : "RBS") : kind;
      // Live has no colored plain class for QM / SBR / RBS: gray tag-dim.
      const dim = kind === "SR";
      items.push({ ...st.break, color, tag,
        cls: kind === "CHOCH" ? "choch" : "bos",
        clsFull: dim ? "tag-dim" : undefined,
        width: 1, style: LightweightCharts.LineStyle.Solid });
    }
    if (st.qm && st.qm.price != null && st.qm.time) {
      items.push({ ...st.qm, color: "#b388ff", tag: "QM",
        cls: "", clsFull: "tag-dim",
        width: 2, style: LightweightCharts.LineStyle.Solid });
    }
    if (st.liq && st.liq.price != null && st.liq.time) {
      const liqTag = st.liq.kind || "IDM";
      items.push({ ...st.liq, color: "#ffd600", tag: liqTag, cls: "idm",
        width: 1, style: LightweightCharts.LineStyle.Solid });
    }
    (st.confluence || []).forEach((z) => {
      if (state.hideConfluence) return;
      if (z.top == null || z.bottom == null) return;
      const breaker = z.kind === "BREAKER";
      const ifvg = z.kind === "IFVG";
      const bull = !!z.bull;
      const edge = ifvg ? "#b388ff"
        : breaker ? (bull ? "#00e676" : "#ff1744")
        : z.kind === "OB" ? (bull ? "#2962ff" : "#ff6d00")
        : (bull ? "#089981" : "#f23645");
      const fill = ifvg ? "rgba(179,136,255,0.08)"
        : breaker ? (bull ? "rgba(0,230,118,0.10)" : "rgba(255,23,68,0.10)")
        : z.kind === "OB" ? (bull ? "rgba(41,98,255,0.08)" : "rgba(255,109,0,0.08)")
        : (bull ? "rgba(8,153,129,0.08)" : "rgba(242,54,69,0.08)");
      const tag = breaker ? "BRKR" : z.kind;
      const cls = breaker ? "brkr" : ifvg ? "ifvg"
        : z.kind === "OB" ? (bull ? "ob-bull" : "ob-bear")
        : (bull ? "fvg-bull" : "fvg-bear");
      items.push({ price: (z.top + z.bottom) / 2, top: z.top, bottom: z.bottom,
        color: edge, fill, tag, cls, zone: true,
        style: LightweightCharts.LineStyle.Dotted });
    });
    const fillIdx = barIdxAtOrBefore(fillT);
    items.forEach((lv) => {
      if (lv.zone) {
        // Confluence zone: dotted edges + translucent fill + mid tag.
        const zStart = state.candles[Math.max(0, fillIdx - 30)].time;
        [lv.top, lv.bottom].forEach((edgePrice) => {
          structRay(edgePrice, zStart, endT, lv.color, lv.style, 1);
        });
        structFill(lv.top, lv.bottom, zStart, endT, lv.fill);
        const mid = barIdxAtOrBefore((zStart + endT) / 2);
        pushStructLabel(state.candles[mid].time, lv.price, lv.tag, lv.cls, true);
        return;
      }
      const span = spanForLive(lv);
      if (!span) return;
      structRay(lv.price, span.startTime, span.endTime, lv.color, lv.style,
        lv.width || 1);
      const frac = lv.pair ? 0.75 : 0.5;
      const anchorT = span.startTime + (span.endTime - span.startTime) * frac;
      const mid = barIdxAtOrBefore(anchorT);
      pushStructLabel(state.candles[mid].time, lv.price, lv.tag, lv.cls,
        false, lv.clsFull);
    });
    renderStructLabels();
  }

  // Live-terminal spans: TS pair (candle1 -> candle2+2, candles are
  // adjacent by definition); everything else formation -> +8 bars.
  function spanForLive(lv) {
    if (!lv.time || !state.candles.length) return null;
    let startIdx, endIdx;
    if (lv.pair) {
      const i2 = barIdxAtOrBefore(lv.time);
      startIdx = Math.max(0, i2 - 1);
      endIdx = Math.min(state.candles.length - 1, i2 + 2);
    } else {
      startIdx = barIdxAtOrBefore(lv.time);
      endIdx = Math.min(state.candles.length - 1, startIdx + 8);
    }
    if (endIdx <= startIdx) return null;
    return { startTime: state.candles[startIdx].time,
             endTime: state.candles[endIdx].time };
  }

  // ---- Manual drawings: human levels (white dashed + note), shared
  // key with the live terminal so markings transfer between pages. ----
  const BT_SYMBOL = "XAUUSDm";
  const BT_TF = "M15";
  const DRAW_TYPES = ["TS", "QM", "BOS", "IDM", "SR"];
  const drawButtons = document.querySelectorAll(".draw-btn[data-draw]");
  const btnDrawList = document.getElementById("btnDrawList");
  const btnDrawExport = document.getElementById("btnDrawExport");
  const btnDrawImport = document.getElementById("btnDrawImport");
  const btnHideBot = document.getElementById("btnHideBot");
  const btnHideConf = document.getElementById("btnHideConf");
  const btnMagnet = document.getElementById("btnMagnet");
  if (btnMagnet) {
    btnMagnet.addEventListener("click", () => {
      state.magnet = !state.magnet;
      btnMagnet.classList.toggle("active", state.magnet);
      syncCrosshairMode();
    });
  }
  const drawImportFile = document.getElementById("drawImportFile");
  const drawList = document.getElementById("drawList");
  const drawWrap = document.querySelector(".bt-chart-wrap");

  state.drawings = [];
  state.drawingSeries = [];
  state.drawingLabels = [];
  state.drawTool = null;
  state.magnet = true; // snap drawing start-time to the bar; off = free

  // The chart's own crosshair also magnets to candle OHLC when near them.
  // Tie its mode to the toggle so OFF is free everywhere, not just at
  // placement time.
  function syncCrosshairMode() {
    try {
      chart.applyOptions({
        crosshair: {
          mode: state.magnet
            ? LightweightCharts.CrosshairMode.Magnet
            : LightweightCharts.CrosshairMode.Normal,
        },
      });
    } catch (e) {}
  }
  syncCrosshairMode();

  function drawKey() {
    return `msnr_drawings_${BT_SYMBOL}_${BT_TF}`;
  }

  function loadDrawings() {
    try {
      const raw = localStorage.getItem(drawKey());
      const arr = raw ? JSON.parse(raw) : [];
      state.drawings = Array.isArray(arr)
        ? arr.filter((d) => d && DRAW_TYPES.includes(d.type)
          && isFinite(d.price) && isFinite(d.time))
        : [];
    } catch (e) {
      state.drawings = [];
    }
  }

  function saveDrawings() {
    try {
      localStorage.setItem(drawKey(), JSON.stringify(state.drawings));
    } catch (e) {}
  }

  function clearDrawingSeries() {
    state.drawingSeries.forEach((s) => {
      try { chart.removeSeries(s); } catch (e) {}
    });
    state.drawingSeries = [];
    state.drawingLabels = [];
  }

  function renderDrawings() {
    clearDrawingSeries();
    if (!state.candles || state.candles.length === 0) return;
    const lastT = state.candles[state.candles.length - 1].time;
    state.drawings.forEach((d) => {
      const startT = state.candles[barIdxAtOrBefore(d.time)].time;
      const ray = chart.addLineSeries({
        color: "#e6ebf2",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ray.setData([
        { time: startT, value: d.price },
        { time: lastT, value: d.price }
      ]);
      state.drawingSeries.push(ray);
      state.drawingLabels.push({
        tBar: startT, price: d.price,
        text: ("✎ " + d.type + (d.note ? ": " + d.note : "")).slice(0, 60),
        cls: "draw-human",
      });
    });
    renderStructLabels();
  }

  function setDrawTool(type) {
    state.drawTool = state.drawTool === type ? null : type;
    drawButtons.forEach((b) => {
      b.classList.toggle("active", b.dataset.draw === state.drawTool);
    });
    if (drawWrap) drawWrap.classList.toggle("drawing", !!state.drawTool);
  }

  drawButtons.forEach((btn) => {
    btn.addEventListener("click", () => setDrawTool(btn.dataset.draw));
  });

  chart.subscribeClick((param) => {
    if (!state.drawTool || !param || !param.point || param.time === undefined) return;
    const tNum = Number(param.time);
    if (!isFinite(tNum) || !state.candles.length) return;
    const bi = barIdxAtOrBefore(tNum);
    const barT = state.magnet
      ? state.candles[bi].time
      : Math.round(tNum);
    // Free cursor price off the candle series (priceScale has no
    // coordinateToPrice in this charts build — the old branch always
    // threw and fell back to the bar close).
    let price = null;
    try {
      if (candleSeries && typeof candleSeries.coordinateToPrice === "function") {
        price = candleSeries.coordinateToPrice(param.point.y);
      }
    } catch (e) {}
    if (price === null || !isFinite(price)) {
      const c = state.candles[bi];
      price = c ? c.close : null;
    }
    if (price === null || !isFinite(price)) return;
    if (state.magnet) {
      // Magnet ON: stick to the nearest OHLC of the clicked bar.
      const c = state.candles[bi];
      if (c) {
        const cands = [c.open, c.high, c.low, c.close];
        price = cands.reduce((a, b) =>
          (Math.abs(b - price) < Math.abs(a - price) ? b : a));
      }
    }
    const type = state.drawTool;
    // Place immediately with an empty note (add one later via the list).
    // No window.prompt here: browsers suppress repeated dialogs, which
    // used to silently stop placements after a few drawings.
    state.drawings.push({
      id: `d${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`,
      type,
      price: Math.round(price * 1000) / 1000,
      time: barT,
      note: "",
      created_at: new Date().toISOString(),
    });
    saveDrawings();
    renderDrawings();
    renderDrawList();
    // Stay engaged (TradingView-style): click the tool again to stop.
  });

  function renderDrawList() {
    if (!drawList) return;
    if (!state.drawings.length) {
      drawList.innerHTML = `<div class="empty-state">No drawings yet. Pick a tool above, then click the chart.</div>`;
      return;
    }
    drawList.innerHTML = "";
    [...state.drawings].reverse().forEach((d) => {
      const row = document.createElement("div");
      row.className = "draw-row";
      const kind = document.createElement("span");
      kind.className = "draw-kind";
      kind.textContent = d.type;
      const pr = document.createElement("span");
      pr.className = "draw-price";
      pr.textContent = Number(d.price).toFixed(2);
      const note = document.createElement("span");
      note.className = "draw-note";
      note.textContent = d.note || "(no note — click to add)";
      note.title = "Click to edit note";
      note.addEventListener("click", () => {
        const next = window.prompt(`Note for this ${d.type} level:`, d.note || "");
        if (next === null) return;
        d.note = (next || "").slice(0, 140);
        saveDrawings();
        renderDrawings();
        renderDrawList();
      });
      const del = document.createElement("button");
      del.className = "draw-del";
      del.textContent = "✕";
      del.title = "Delete drawing";
      del.addEventListener("click", () => {
        state.drawings = state.drawings.filter((x) => x.id !== d.id);
        saveDrawings();
        renderDrawings();
        renderDrawList();
      });
      row.appendChild(kind);
      row.appendChild(pr);
      row.appendChild(note);
      row.appendChild(del);
      drawList.appendChild(row);
    });
  }

  if (btnHideBot) {
    btnHideBot.addEventListener("click", () => {
      state.hideBot = !state.hideBot;
      btnHideBot.classList.toggle("active", state.hideBot);
      const list = filteredTrades();
      const t = list[state.sel];
      drawTrades();
      renderStructLabels();
      if (!state.hideBot && t) {
        if (state.structCache && state.structCache.trade === t) {
          renderStructure(state.structCache.st, t);
        } else {
          drawStructure(t);
        }
      }
    });
  }

  if (btnHideConf) {
    btnHideConf.addEventListener("click", () => {
      state.hideConfluence = !state.hideConfluence;
      btnHideConf.classList.toggle("active", state.hideConfluence);
      const list = filteredTrades();
      const t = list[state.sel];
      clearStructure();
      drawTrades();
      renderStructLabels();
      if (!state.hideBot && t) {
        if (state.structCache && state.structCache.trade === t) {
          renderStructure(state.structCache.st, t);
        } else {
          drawStructure(t);
        }
      }
    });
  }

  if (btnDrawList) {
    btnDrawList.addEventListener("click", () => {
      if (!drawList) return;
      const open = drawList.style.display !== "none";
      drawList.style.display = open ? "none" : "block";
      if (!open) renderDrawList();
    });
  }

  if (btnDrawExport) {
    btnDrawExport.addEventListener("click", () => {
      const list = filteredTrades();
      const sel = list[state.sel];
      const tradeNo = sel ? state.trades.indexOf(sel) + 1 : null;
      const payload = {
        app: "MSNR Terminal drawings",
        version: 1,
        symbol: BT_SYMBOL,
        timeframe: BT_TF,
        exported_at: new Date().toISOString(),
        count: state.drawings.length,
        trade: sel ? {
          number: tradeNo,
          signal_date: sel.signal_date,
          fill_date: sel.fill_date,
          exit_date: sel.exit_date,
          direction: sel.direction,
          entry: sel.entry,
          sl: sel.sl,
          tp: sel.tp,
          outcome: sel.outcome,
          R: sel.R,
          confidence: sel.confidence,
          ts_side: sel.ts_side,
          ts_price: sel.ts_price,
          break_kind: sel.break_kind,
          qm_entry_level: sel.qm_entry_level,
          liq_kind: sel.liq_kind,
          liq_price: sel.liq_price,
          confluence: sel.confluence,
          fallback: sel.fallback,
          chain: sel.chain,
        } : null,
        drawings: state.drawings,
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)],
        { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = tradeNo
        ? `drawings_${BT_SYMBOL}_${BT_TF}_trade${tradeNo}.json`
        : `drawings_${BT_SYMBOL}_${BT_TF}.json`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        URL.revokeObjectURL(a.href);
        a.remove();
      }, 500);
    });
  }

  if (btnDrawImport) {
    btnDrawImport.addEventListener("click", () => {
      if (drawImportFile) drawImportFile.click();
    });
  }

  if (drawImportFile) {
    drawImportFile.addEventListener("change", () => {
      const file = drawImportFile.files && drawImportFile.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const data = JSON.parse(reader.result);
          const arr = Array.isArray(data) ? data : data.drawings;
          if (!Array.isArray(arr)) throw new Error("no drawings array");
          let added = 0;
          arr.forEach((d) => {
            if (!d || !DRAW_TYPES.includes(d.type)
                || !isFinite(Number(d.price)) || !isFinite(Number(d.time))) return;
            if (state.drawings.some((x) => x.id === d.id)) return;
            state.drawings.push({
              id: String(d.id || `d${Date.now().toString(36)}${added}`),
              type: d.type,
              price: Number(d.price),
              time: Number(d.time),
              note: String(d.note || "").slice(0, 140),
              created_at: String(d.created_at || new Date().toISOString()),
            });
            added++;
          });
          saveDrawings();
          renderDrawings();
          renderDrawList();
          alert(`Imported ${added} drawing(s).`);
        } catch (err) {
          alert(`Import failed: ${err.message}`);
        }
        drawImportFile.value = "";
      };
      reader.readAsText(file);
    });
  }

  function hline(value, t0, t1, color, width, style) {
    const s = chart.addLineSeries({
      color, lineWidth: width || 1,
      lineStyle: style || LightweightCharts.LineStyle.Solid,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    s.setData([{ time: t0, value }, { time: t1, value }]);
    state.tradeSeries.push(s);
    return s;
  }

  function fillBand(top, bottom, t0, t1, css) {
    if (typeof chart.addBaselineSeries !== "function") return;
    const CLEAR = "rgba(0, 0, 0, 0)";
    const band = chart.addBaselineSeries({
      baseValue: { type: "price", price: top },
      topLineColor: CLEAR, bottomLineColor: CLEAR,
      topFillColor1: css, topFillColor2: css,
      bottomFillColor1: css, bottomFillColor2: css,
      lineWidth: 1, crosshairMarkerVisible: false,
      priceLineVisible: false, lastValueVisible: false,
    });
    band.setData([{ time: t0, value: bottom }, { time: t1, value: bottom }]);
    state.tradeSeries.push(band);
  }

  function filteredTrades() {
    if (state.filter === "all") return state.trades;
    return state.trades.filter((t) => t.outcome === state.filter);
  }

  function drawTrades() {
    // Isolated view: only the selected setup draws (plus its structure).
    // With bot layers hidden, only the human drawings remain.
    clearTrades();
    const list = filteredTrades();
    const t = list[state.sel];
    if (!t || state.hideBot) {
      try { candleSeries.setMarkers([]); } catch (e) {}
      return;
    }
      const bull = t.direction === "BULLISH";
      const t0 = tsOf(t.fill_date || t.signal_date);
      const t1 = t.exit_date ? tsOf(t.exit_date)
        : state.candles[Math.min(state.candles.length - 1,
            candleIdxAtOrBefore(t0) + 8)].time;
      hline(t.entry, t0, t1, "#2962ff", 2, LightweightCharts.LineStyle.Solid);
      hline(t.sl, t0, t1, "#ff5c6c", 1, LightweightCharts.LineStyle.Dashed);
      hline(t.tp, t0, t1, "#00e676", 1, LightweightCharts.LineStyle.Solid);
      // QM the entry came from — live QM style (purple solid 2px).
      const qm = parseFloat(t.qm_entry_level);
      if (!isNaN(qm)) {
        hline(qm, t0, t1, "#b388ff", 2, LightweightCharts.LineStyle.Solid);
      }
      fillBand(t.tp, t.entry, t0, t1, "rgba(8,153,129,0.08)");
      fillBand(t.entry, t.sl, t0, t1, "rgba(255,145,0,0.10)");
      try {
        candleSeries.setMarkers([{
          time: t0,
          position: bull ? "belowBar" : "aboveBar",
          color: "#ffffff",
          shape: bull ? "arrowUp" : "arrowDown",
          text: `#${state.trades.indexOf(t) + 1}`,
        }]);
      } catch (e) {}
  }

  function renderTable() {
    const list = filteredTrades();
    let html = "";
    list.forEach((t, i) => {
      const n = state.trades.indexOf(t) + 1;
      const d = (t.fill_date || t.signal_date || "").slice(5, 16).replace("T", " ");
      html += `<tr data-i="${i}" class="${i === state.sel ? "selected" : ""}">`
        + `<td>${n}</td><td>${d}</td>`
        + `<td style="color:${t.direction === "BULLISH" ? "#00e676" : "#ff5c6c"};">${t.direction === "BULLISH" ? "BUY" : "SELL"}</td>`
        + `<td>${t.entry.toFixed(2)}</td>`
        + `<td class="out-${t.outcome}">${t.outcome}</td>`
        + `<td>${t.R > 0 ? "+" : ""}${t.R}</td>`
        + `<td>${t.qm_entry_level || "—"}</td></tr>`;
    });
    tradesBody.innerHTML = html || `<tr><td colspan="7" class="empty-state">No trades for this filter.</td></tr>`;
    tradesBody.querySelectorAll("tr[data-i]").forEach((row) => {
      row.addEventListener("click", () => selectTrade(parseInt(row.dataset.i, 10), true));
    });
  }

  function renderDetail() {
    const list = filteredTrades();
    const t = list[state.sel];
    tradeCounter.textContent = list.length ? `${state.sel + 1} / ${list.length}` : "0 / 0";
    if (!t) {
      tradeDetail.innerHTML = `<div class="empty-state">Select a trade.</div>`;
      return;
    }
    const n = state.trades.indexOf(t) + 1;
    const kv = (k, v) => `<div class="row"><span class="k">${k}</span><span>${v}</span></div>`;
    tradeDetail.innerHTML =
      `<div class="row"><span class="k">#${n} ${t.direction} · ${t.confidence}</span>`
      + `<span class="out-${t.outcome}">${t.outcome} ${t.R > 0 ? "+" : ""}${t.R}R</span></div>`
      + kv("Signal", (t.signal_date || "").replace("T", " ").slice(0, 16))
      + kv("Fill", (t.fill_date || "").replace("T", " ").slice(0, 16))
      + kv("Exit", (t.exit_date || "").replace("T", " ").slice(0, 16) || "—")
      + kv("Entry / SL / TP", `${t.entry.toFixed(2)} / ${t.sl.toFixed(2)} / ${t.tp.toFixed(2)}`)
      + kv("TS", `${t.ts_side || "?"} @ ${t.ts_price || "?"}`)
      + kv("Break", t.break_kind || "?")
      + kv("QM entry level", t.qm_entry_level || (t.fallback === "yes" ? "S/R (fallback)" : "?"))
      + kv("Liquidity", t.liq_kind && t.liq_price ? `${t.liq_kind} @ ${t.liq_price}` : "—")
      + kv("Confluence", t.confluence || "—")
      + `<div class="chain">${t.chain || ""}</div>`;
  }

  function renderAll(focus) {
    drawTrades();
    renderTable();
    renderDetail();
    if (focus) focusSelected();
    const list = filteredTrades();
    if (list.length) drawStructure(list[state.sel] || list[0]);
  }

  function selectTrade(i, focus) {
    const list = filteredTrades();
    if (!list.length) return;
    state.sel = Math.max(0, Math.min(i, list.length - 1));
    drawTrades();
    renderTable();
    renderDetail();
    if (focus) focusSelected();
    drawStructure(list[state.sel]);
  }

  function focusSelected() {
    const t = filteredTrades()[state.sel];
    if (!t || !state.candles.length) return;
    const t0 = tsOf(t.fill_date || t.signal_date);
    const idx = candleIdxAtOrBefore(t0);
    const lo = Math.max(0, idx - 40);
    const hi = Math.min(state.candles.length - 1, idx + 40);
    try {
      chart.timeScale().setVisibleLogicalRange({ from: lo, to: hi });
    } catch (e) {}
  }

  filterPills.forEach((pill) => {
    pill.addEventListener("click", () => {
      filterPills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      state.filter = pill.dataset.f;
      state.sel = 0;
      renderAll(false);
    });
  });

  document.getElementById("btnPrev").addEventListener("click", () => selectTrade(state.sel - 1, true));
  document.getElementById("btnNext").addEventListener("click", () => selectTrade(state.sel + 1, true));
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") selectTrade(state.sel - 1, true);
    if (e.key === "ArrowRight") selectTrade(state.sel + 1, true);
    if (e.key === "Escape" && state.drawTool) setDrawTool(state.drawTool);
  });

  async function boot() {
    try {
      const [cRes, jRes] = await Promise.all([
        fetch("/api/candles?symbol=XAUUSDm&timeframe=M15&bars=1500"),
        fetch("/api/backtest/journals"),
      ]);
      const cData = await cRes.json();
      const jData = await jRes.json();
      state.candles = cData.candles || [];
      candleSeries.setData(state.candles);
      chart.timeScale().fitContent();
      loadDrawings();
      renderDrawings();
      const sel = document.getElementById("journalSel");
      const journals = jData.journals || [];
      if (sel) {
        sel.innerHTML = "";
        journals.forEach((j) => {
          const opt = document.createElement("option");
          opt.value = j.id;
          opt.textContent =
            `${j.label} (${j.total} · ${j.tp}TP/${j.losses}SL · ${j.total_R}R)`;
          sel.appendChild(opt);
        });
        sel.value = jData.default || (journals[0] && journals[0].id) || "";
        sel.addEventListener("change", () => {
          state.sel = 0;
          state.filter = "all";
          filterPills.forEach((p) =>
            p.classList.toggle("active", p.dataset.f === "all"));
          loadTrades(sel.value);
        });
      }
      await loadTrades(sel ? sel.value : "");
    } catch (err) {
      console.error("Backtest viewer failed to load:", err);
    }
  }

  async function loadTrades(journalId) {
    state.journalId = journalId || "";
    const url = "/api/backtest/trades" + (journalId
      ? `?journal=${encodeURIComponent(journalId)}` : "");
    const tRes = await fetch(url);
    const tData = await tRes.json();
    state.trades = (tData.trades || []).filter((t) => t.entry > 0);
    state.sel = 0;
    const st = tData.stats || {};
    document.getElementById("statTP").textContent = st.tp ?? "–";
    document.getElementById("statSL").textContent = st.losses ?? "–";
    document.getElementById("statExp").textContent = st.expired ?? "–";
    document.getElementById("statR").textContent =
      (st.total_R > 0 ? "+" : "") + (st.total_R ?? "–") + "R";
    const sub = document.getElementById("brandSubtitle");
    if (sub) {
      const sel = document.getElementById("journalSel");
      const lbl = sel && sel.selectedOptions.length
        ? sel.selectedOptions[0].textContent : "Journal Sep 28 — Oct 02";
      sub.textContent = `${lbl} · ${state.trades.length} setups`;
    }
    renderAll(false);
  }

  chart.resize(container.clientWidth, container.clientHeight);
  boot();
});
