/**
 * MSNR Trading Terminal — Frontend JavaScript Engine
 * Bounded Formation Rays, Candlestick Markers & Level Inspector
 */

document.addEventListener("DOMContentLoaded", () => {
  // MASTER SWITCHES — mirrors config/settings.py.
  const INDICATORS_ENABLED = false;
  const TS_ENABLED = true;
  const SR_ENABLED = true;
  const QM_ENABLED = true;
  const OCL_ENABLED = true;
  const APEX_ENABLED = true;
  const IDM_ENABLED = true;
  const BOS_ENABLED = true;
  const FVG_ENABLED = true;
  const IFVG_ENABLED = true;
  const OB_ENABLED = true;
  const TL_ENABLED = true;

  if (window.lucide) {
    lucide.createIcons();
  }

  // State Management
  const state = {
    symbol: "XAUUSDm",
    timeframe: "D1",
    chartType: "candles",
    inspectMode: "custom", // default: clean candles, everything off
    freshness: "all",
    indicators: {
      sr: false,
      ocl: false,
      qm: false,
      apex: false,
      ts: false,
      idm: false,
      bos: false,
      fvg: false,
      ifvg: false,
      ob: false,
      tl: false
    },
    candles: [],
    levels: [],
    account: null,
    positions: [],
    pendingOrders: [],
    currentPrice: 0,
    priceLines: [],
    customRaySeries: [], // Array of lineSeries used for finite bounded rays
    chartLabels: [], // HTML overlay tags pinned to line midpoints / right ends
  };

  // Bars per timeframe: intraday needs more bars to cover the same past.
  const TF_BARS = {
    MN1: 300, MN: 300, W1: 300, D1: 300,
    H4: 500, H2: 500, H1: 500,
    M15: 800, M30: 800, M45: 800, M5: 1000, M3: 1000, M1: 1000,
  };
  const tfBars = () => TF_BARS[state.timeframe] || 300;

  let refreshSequence = 0;
  let activeRefreshController = null;
  let lastChartContext = "";

  // DOM Elements
  const symbolSelect = document.getElementById("symbolSelect");
  const livePriceDisplay = document.getElementById("livePriceDisplay");
  const tfButtons = document.querySelectorAll(".tf-btn");
  const tfMoreBtn = document.getElementById("tfMoreBtn");
  const tfDropdownMenu = document.getElementById("tfDropdownMenu");
  const btnCandles = document.getElementById("btnCandles");
  const btnLine = document.getElementById("btnLine");
  const btnRefresh = document.getElementById("btnRefresh");
  const btnResetZoom = document.getElementById("btnResetZoom");
  const btnSettings = document.getElementById("btnSettings");
  const brandSection = document.getElementById("brandSection");
  const settingsDrawer = document.getElementById("settingsDrawer");
  const settingsBackdrop = document.getElementById("settingsBackdrop");
  const btnCloseSettings = document.getElementById("btnCloseSettings");
  const modulesList = document.getElementById("modulesList");
  const modulesCountBadge = document.getElementById("modulesCountBadge");
  const btnModulesAll = document.getElementById("btnModulesAll");
  const btnModulesNone = document.getElementById("btnModulesNone");
  const connectionStatus = document.getElementById("connectionStatus");
  const connectionStatusText = connectionStatus ? connectionStatus.querySelector(".status-text") : null;
  const modePills = document.querySelectorAll(".mode-pill");
  const segButtons = document.querySelectorAll(".seg-btn");
  
  const toggleSR = document.getElementById("toggleSR");
  const toggleOCL = document.getElementById("toggleOCL");
  const toggleQM = document.getElementById("toggleQM");
  const toggleApex = document.getElementById("toggleApex");
  const toggleTS = document.getElementById("toggleTS");
  const toggleIDM = document.getElementById("toggleIDM");
  const toggleBOS = document.getElementById("toggleBOS");
  const toggleFVG = document.getElementById("toggleFVG");
  const toggleIFVG = document.getElementById("toggleIFVG");
  const toggleOB = document.getElementById("toggleOB");
  const toggleTL = document.getElementById("toggleTL");
  
  const overlaySymbol = document.getElementById("overlaySymbol");
  const overlayTF = document.getElementById("overlayTF");
  const overlayActiveCount = document.getElementById("overlayActiveCount");
  const levelsTableBody = document.getElementById("levelsTableBody");
  const chartContainer = document.getElementById("tvChartContainer");
  const labelLayer = document.getElementById("chartLabelLayer");

  // Account & Positions elements
  const accEquity = document.getElementById("accEquity");
  const accLeverage = document.getElementById("accLeverage");
  const positionsTableBody = document.getElementById("positionsTableBody");

  // Initialize TradingView Lightweight Chart
  const chart = LightweightCharts.createChart(chartContainer, {
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
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: {
        color: "#00e5ff",
        width: 1,
        style: 3,
        labelBackgroundColor: "#00e5ff",
      },
      horzLine: {
        color: "#00e5ff",
        width: 1,
        style: 3,
        labelBackgroundColor: "#00e5ff",
      },
    },
    rightPriceScale: {
      borderColor: "#2b313d",
      autoScale: true,
      scaleMargins: {
        top: 0.1,
        bottom: 0.1,
      },
    },
    timeScale: {
      borderColor: "#2b313d",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#089981",
    downColor: "#f23645",
    borderVisible: false,
    wickUpColor: "#089981",
    wickDownColor: "#f23645",
  });

  const lineSeries = chart.addLineSeries({
    color: "#00e5ff",
    lineWidth: 2,
    crosshairMarkerVisible: true,
    visible: false,
  });

  function setConnectionStatus(kind, label, title) {
    if (!connectionStatus) return;
    connectionStatus.classList.remove("live", "loading", "error", "stale");
    connectionStatus.classList.add(kind);
    if (connectionStatusText) {
      connectionStatusText.textContent = label;
    }
    connectionStatus.title = title || label;
  }

  function syncChartSeriesVisibility() {
    const showCandles = state.chartType !== "line";
    const showLine = state.chartType === "line";

    candleSeries.applyOptions({ visible: showCandles });
    lineSeries.applyOptions({ visible: showLine });
  }

  // =========================================================================
  // On-chart HTML label layer (mid-line pills like TradingView drawings).
  // Markers can only sit above/below bars, so line labels ("daily rejection",
  // "LONG 2.4R", "TP"...) are absolutely-positioned pills re-pinned on every
  // pan/zoom via timeToCoordinate/priceToCoordinate.
  // Label: { tBar, price, text, cls, align: 'mid' | 'right' }
  // =========================================================================

  function pushLabel(tBar, price, text, cls, align) {
    state.chartLabels.push({ tBar, price, text, cls: cls || "", align: align || "mid" });
  }

  function clearLabels() {
    state.chartLabels = [];
    if (labelLayer) labelLayer.innerHTML = "";
  }

  // Nearest candle at or before a timestamp (mid-segment anchors must be real bars).
  function barAtOrBefore(ts) {
    if (!state.candles || state.candles.length === 0) return null;
    let lo = state.candles[0].time;
    if (ts <= lo) return lo;
    let best = lo;
    for (let i = 0; i < state.candles.length; i++) {
      if (state.candles[i].time <= ts) best = state.candles[i].time;
      else break;
    }
    return best;
  }

  function renderOverlayLabels() {
    if (!labelLayer || !state.candles || state.candles.length === 0) return;
    // Rebuild DOM only when the label set changed (flag set by renderers).
    if (!renderOverlayLabels._dirty) {
      // Still re-pin positions on view change using existing nodes.
      const nodes = labelLayer.children;
      for (let i = 0; i < nodes.length && i < state.chartLabels.length; i++) {
        pinLabelNode(nodes[i], state.chartLabels[i]);
      }
      return;
    }
    renderOverlayLabels._dirty = false;
    labelLayer.innerHTML = "";
    const frag = document.createDocumentFragment();
    state.chartLabels.forEach((lb) => {
      const el = document.createElement("div");
      el.className = ("chart-tag" + (lb.align === "right" ? " tag-right" : "") + " " + lb.cls).trim();
      el.textContent = lb.text;
      frag.appendChild(el);
      pinLabelNode(el, lb);
    });
    labelLayer.appendChild(frag);
  }

  function pinLabelNode(el, lb) {
    let x = null;
    try {
      x = chart.timeScale().timeToCoordinate(lb.tBar);
    } catch (e) { x = null; }
    let y = null;
    try {
      y = candleSeries.priceToCoordinate(lb.price);
    } catch (e) { y = null; }
    if (x === null || x === undefined || y === null || y === undefined) {
      el.style.display = "none";
      return;
    }
    el.style.display = "block";
    el.style.transform = lb.align === "right"
      ? `translate(${x + 8}px, ${y}px) translateY(-50%)`
      : `translate(${x}px, ${y}px) translate(-50%, -50%)`;
  }

  function markLabelsDirty() {
    renderOverlayLabels._dirty = true;
  }

  // Re-pin HTML labels on every pan/zoom (positions depend on the view).
  try {
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => renderOverlayLabels());
  } catch (e) {}

  window.addEventListener("resize", () => {
    chart.resize(chartContainer.clientWidth, chartContainer.clientHeight);
  });
  chart.resize(chartContainer.clientWidth, chartContainer.clientHeight);

  // =========================================================================
  // Load All Broker Symbols
  // =========================================================================

  async function loadSymbols() {
    try {
      // Never let a slow broker scan block the dashboard: 15s cap, then
      // fall back to the default symbol already in the dropdown.
      const res = await fetch("/api/symbols", { signal: AbortSignal.timeout(15000) });
      const data = await res.json();
      if (data.symbols && data.symbols.length > 0) {
        symbolSelect.innerHTML = "";
        data.symbols.forEach((sym) => {
          const opt = document.createElement("option");
          opt.value = sym;
          opt.textContent = sym;
          if (sym === state.symbol || sym === "XAUUSDm" || sym === "XAUUSD") {
            opt.selected = true;
            state.symbol = sym;
          }
          symbolSelect.appendChild(opt);
        });
      }
    } catch (err) {
      console.warn("Could not load symbol list, using defaults.", err);
    }
  }

  // =========================================================================
  // Main Data Refresh Pipeline
  // =========================================================================

  async function refreshData() {
    const requestId = ++refreshSequence;
    if (activeRefreshController) {
      activeRefreshController.abort();
    }
    const controller = new AbortController();
    activeRefreshController = controller;
    const chartContext = `${state.symbol}::${state.timeframe}`;
    const shouldFitContent = lastChartContext !== chartContext;

    try {
      btnRefresh.classList.add("spinning");
      setConnectionStatus("loading", "UPDATING", `Refreshing ${state.symbol} ${state.timeframe}`);
      overlaySymbol.textContent = state.symbol;
      overlayTF.textContent = state.timeframe;

      // 1. Fetch Candles
      const candleRes = await fetch(
        `/api/candles?symbol=${encodeURIComponent(state.symbol)}&timeframe=${state.timeframe}&bars=${tfBars()}`,
        { signal: controller.signal }
      );
      if (!candleRes.ok) throw new Error("Failed to fetch candle data.");
      const candleData = await candleRes.json();
      if (controller.signal.aborted || requestId !== refreshSequence) return;

      state.candles = candleData.candles || [];
      if (state.candles.length > 0) {
        state.currentPrice = state.candles[state.candles.length - 1].close;
        livePriceDisplay.textContent = state.currentPrice.toFixed(2);
      }

      candleSeries.setData(state.candles);
      const lineData = state.candles.map(c => ({ time: c.time, value: c.close }));
      lineSeries.setData(lineData);
      syncChartSeriesVisibility();

      // 2. Fetch Account & Positions
      await fetchAccountMetrics();
      await fetchLivePositions();

      // 3. Indicators — TS/SR/QM/IDM (new strategy) fetch even while the
      // rest of the old MSNR stack is disabled. Legacy OCL/Apex stay empty.
      const wantTS = TS_ENABLED && state.indicators.ts;
      const wantSR = (SR_ENABLED || INDICATORS_ENABLED) && state.indicators.sr;
      const wantQM = (QM_ENABLED || INDICATORS_ENABLED) && state.indicators.qm;
      const wantIDM = IDM_ENABLED && state.indicators.idm;
      const wantBOS = BOS_ENABLED && state.indicators.bos;
      const wantFVG = FVG_ENABLED && state.indicators.fvg;
      const wantIFVG = IFVG_ENABLED && state.indicators.ifvg;
      const wantOB = OB_ENABLED && state.indicators.ob;
      const wantTL = TL_ENABLED && state.indicators.tl;
      const wantOCL = (OCL_ENABLED || INDICATORS_ENABLED) && state.indicators.ocl;
      const wantAPEX = (APEX_ENABLED || INDICATORS_ENABLED) && state.indicators.apex;
      const wantLegacy = wantOCL || wantAPEX;
      if (!wantTS && !wantSR && !wantQM && !wantIDM && !wantBOS && !wantFVG && !wantIFVG && !wantOB && !wantTL && !wantLegacy) {
        state.levels = [];
      } else {
      // 5. Fetch Raw Indicators
      {
        const params = new URLSearchParams({
          symbol: state.symbol,
          timeframe: state.timeframe,
          bars: tfBars(),
          show_sr: (SR_ENABLED || INDICATORS_ENABLED) && state.indicators.sr,
          freshness_filter: state.freshness,
          show_ocl: (OCL_ENABLED || INDICATORS_ENABLED) && state.indicators.ocl,
          show_qm: (QM_ENABLED || INDICATORS_ENABLED) && state.indicators.qm,
          show_apex: (APEX_ENABLED || INDICATORS_ENABLED) && state.indicators.apex,
          show_ts: TS_ENABLED && state.indicators.ts,
          show_idm: IDM_ENABLED && state.indicators.idm,
          show_bos: BOS_ENABLED && state.indicators.bos,
          show_fvg: FVG_ENABLED && state.indicators.fvg,
          show_ifvg: IFVG_ENABLED && state.indicators.ifvg,
          show_ob: OB_ENABLED && state.indicators.ob,
          show_tl: TL_ENABLED && state.indicators.tl,
        });

        const indRes = await fetch(`/api/indicators?${params.toString()}`, { signal: controller.signal });
        if (indRes.ok) {
          const indData = await indRes.json();
          if (controller.signal.aborted || requestId !== refreshSequence) return;
          state.levels = indData.levels || [];
        } else {
          state.levels = [];
        }
      }
      } // end INDICATORS_ENABLED guard

      if (controller.signal.aborted || requestId !== refreshSequence) return;
      renderVisualRaysAndMarkers();
      renderLevelsTable();

      if (shouldFitContent) {
        chart.timeScale().fitContent();
        lastChartContext = chartContext;
      }

      setConnectionStatus("live", "MT5 LIVE", `Live data for ${state.symbol} ${state.timeframe}`);
      console.info("[MSNR UI] refresh done", { symbol: state.symbol, timeframe: state.timeframe, requestId });
    } catch (err) {
      if (err && err.name === "AbortError") {
        return;
      }
      console.error("Data load error:", err);
      setConnectionStatus("error", "OFFLINE", err && err.message ? err.message : "Refresh failed");
      levelsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state" style="color:#f23645;">Error: ${err.message}</td></tr>`;
    } finally {
      if (requestId === refreshSequence) {
        btnRefresh.classList.remove("spinning");
        if (activeRefreshController === controller) {
          activeRefreshController = null;
        }
      }
    }
  }

  // =========================================================================
  // Phase 5 Account & Live Positions Management
  // =========================================================================

  async function fetchAccountMetrics() {
    try {
      const res = await fetch("/api/account");
      if (res.ok) {
        state.account = await res.json();
        accEquity.textContent = `$${state.account.equity.toLocaleString()}`;
        accLeverage.textContent = `1:${state.account.leverage}`;
      }
    } catch (e) {}
  }

  async function fetchLivePositions() {
    try {
      const res = await fetch("/api/positions");
      if (res.ok) {
        const data = await res.json();
        state.positions = data.positions || [];
        state.pendingOrders = data.pending_orders || [];
        renderPositionsTable();
      }
    } catch (e) {}
  }

  function renderPositionsTable() {
    const allItems = [
      ...state.positions.map(p => ({ ...p, is_pos: true })),
      ...state.pendingOrders.map(o => ({ ...o, is_pos: false, profit: 0.0 }))
    ];

    if (allItems.length === 0) {
      positionsTableBody.innerHTML = `<tr><td colspan="9" class="empty-state">No active orders or positions in MT5. Ready for entry.</td></tr>`;
      return;
    }

    let html = "";
    allItems.forEach((item) => {
      const isPos = item.is_pos;
      const pnlColor = item.profit >= 0 ? "#00e676" : "#ff1744";
      const actionBtn = isPos
        ? `<button class="btn-close-pos" onclick="window.closeTrade(${item.ticket})">Close</button>`
        : `<button class="btn-close-pos" onclick="window.cancelTrade(${item.ticket})">Cancel</button>`;

      html += `
        <tr>
          <td>#${item.ticket}</td>
          <td>${item.symbol}</td>
          <td style="font-weight:700; color:${item.type.includes('BUY') ? '#00e5ff' : '#ff9100'};">${item.type}</td>
          <td>${item.lots.toFixed(2)}</td>
          <td>${item.open_price.toFixed(2)}</td>
          <td style="color:#ff1744;">${item.sl.toFixed(2)}</td>
          <td style="color:#00e676;">${item.tp.toFixed(2)}</td>
          <td style="font-weight:700; color:${pnlColor};">${isPos ? `$${item.profit.toFixed(2)}` : 'Pending'}</td>
          <td>${actionBtn}</td>
        </tr>
      `;
    });

    positionsTableBody.innerHTML = html;
  }

  window.closeTrade = async (ticket) => {
    try {
      const res = await fetch(`/api/orders/close?ticket=${ticket}`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        alert(`Position #${ticket} closed successfully.`);
        refreshData();
      }
    } catch (e) {
      alert(`Error closing position: ${e.message}`);
    }
  };

  window.cancelTrade = async (ticket) => {
    try {
      const res = await fetch(`/api/orders/cancel?ticket=${ticket}`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        alert(`Order #${ticket} cancelled.`);
        refreshData();
      }
    } catch (e) {
      alert(`Error cancelling order: ${e.message}`);
    }
  };

  // =========================================================================
  // Bounded Rays & Candlestick Markers Rendering (No screen-spanning clutter!)
  // =========================================================================

  function clearVisualRays() {
    // Remove all custom ray series
    state.customRaySeries.forEach(s => {
      try {
        chart.removeSeries(s);
      } catch (e) {}
    });
    state.customRaySeries = [];
    clearLabels();

    // Clear price lines
    state.priceLines.forEach(line => {
      try {
        candleSeries.removePriceLine(line);
      } catch (e) {}
    });
    state.priceLines = [];

    try {
      candleSeries.setMarkers([]);
    } catch (e) {}
    try {
      lineSeries.setMarkers([]);
    } catch (e) {}
  }

  // Index of nearest candle at or before a timestamp.
  function candleIndexOf(targetTs) {
    if (!state.candles || state.candles.length === 0) return 0;
    let idx = 0;
    for (let i = 0; i < state.candles.length; i++) {
      if (state.candles[i].time <= targetTs) idx = i;
      else break;
    }
    return idx;
  }

  // TS span: starts at the swept (candle 1) wick and extends 2 bars past
  // the sweeping candle so the ray visibly crosses candle 2's wick.
  function tsSpan(lvl) {
    const i1 = candleIndexOf(lvl.start_time || lvl.time);
    const i2 = candleIndexOf(lvl.time);
    const endIdx = Math.min(state.candles.length - 1, i2 + 2);
    return { startTime: state.candles[i1].time, endTime: state.candles[endIdx].time, extend: true };
  }

  function findCandleIndexAndSpan(targetTs, spanBars = 8) {
    if (!state.candles || state.candles.length === 0) return { start: null, end: null };
    
    let startIdx = 0;
    if (targetTs && targetTs > 0) {
      for (let i = 0; i < state.candles.length; i++) {
        if (state.candles[i].time <= targetTs) {
          startIdx = i;
        } else {
          break;
        }
      }
    } else {
      startIdx = Math.max(0, state.candles.length - spanBars - 2);
    }

    const endIdx = Math.min(state.candles.length - 1, startIdx + spanBars);
    return {
      startTime: state.candles[startIdx].time,
      endTime: state.candles[endIdx].time,
      startIdx,
      endIdx
    };
  }

  function renderVisualRaysAndMarkers() {
    clearVisualRays();

    if (!state.candles || state.candles.length === 0) return;
    const markers = [];
    const markerSeries = state.chartType === "line" ? lineSeries : candleSeries;

    // Full Inspector Modes — zone-to-zone rays: each level draws from its
    // formation candle to its life-cycle end (mitigation touch / break), with
    // a shorthand tag at the RIGHT end of the line. Still-active levels extend
    // a short open-ended span. Readability cap keeps the 40 most recent.
    const MAX_INSPECTOR_RAYS = 40;
    const ordered = [...state.levels].sort((a, b) => (b.time || 0) - (a.time || 0));
    const visible = ordered.slice(0, MAX_INSPECTOR_RAYS);
    const hidden = ordered.length - visible.length;

    // Short tag for the level kind (right-end label).
    const levelTag = (lvl) => {
      const t = (lvl.type || "").toUpperCase();
      if (lvl.category === "sr") {
        if (t.includes("SBR")) return "SBR";
        if (t.includes("RBS")) return "RBS";
        if (t.includes("SUPPORT")) return "S";
        if (t.includes("RESISTANCE")) return "R";
        return t.slice(0, 3);
      }
      if (lvl.category === "ocl") {
        if (t.includes("LS")) return "LS";
        if (t.includes("SOCL")) return "sOCL";
        if (t.includes("ROCL")) return "rOCL";
        if (t.includes("ONE_LAP")) return "1LAP";
        return "OCL";
      }
      if (lvl.category === "qm") return "QM";
      if (lvl.category === "idm") return "IDM";
      if (lvl.category === "bos") return (lvl.type || "").split(" ")[0] || "BOS";
      if (lvl.category === "fvg") return "FVG";
      if (lvl.category === "ifvg") return "IFVG";
      if (lvl.category === "ts") return (lvl.type || "").includes("HIGH") ? "TS-H" : "TS-L";
      if (lvl.category === "trendline") return lvl.flipped ? "BRT" : "TL";
      if (lvl.category === "apex") return t.includes("IAB") ? "IAB" : "APX";
      return t.slice(0, 3);
    };
    // Zone levels (FVG/IFVG/OB): top+bottom edges + fill band + mid label.
    const isZoneLevel = (lvl) => (lvl.category === "fvg" || lvl.category === "ifvg" || lvl.category === "ob")
      && lvl.box_top !== undefined && lvl.box_top !== null
      && lvl.box_bottom !== undefined && lvl.box_bottom !== null;

    const zoneFillBand = (top, bottom, span, css) => {
      if (typeof chart.addBaselineSeries !== "function") return;
      const CLEAR = "rgba(0, 0, 0, 0)";
      const band = chart.addBaselineSeries({
        baseValue: { type: "price", price: top },
        topLineColor: CLEAR,
        bottomLineColor: CLEAR,
        topFillColor1: css,
        topFillColor2: css,
        bottomFillColor1: css,
        bottomFillColor2: css,
        lineWidth: 1,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      band.setData([
        { time: span.startTime, value: bottom },
        { time: span.endTime, value: bottom },
      ]);
      state.customRaySeries.push(band);
    };

    const drawZoneLevel = (lvl) => {
      const bull = (lvl.type || "").includes("BULLISH");
      const isIfvg = lvl.category === "ifvg";
      const edge = isIfvg ? "#b388ff" : bull ? "#089981" : "#f23645";
      const fill = isIfvg ? "rgba(179,136,255,0.08)"
        : bull ? "rgba(8,153,129,0.08)" : "rgba(242,54,69,0.08)";
      let span;
      if (lvl.end_time && lvl.end_time > lvl.time) {
        const a = findCandleIndexAndSpan(lvl.time, 0);
        const b = findCandleIndexAndSpan(lvl.end_time, 0);
        span = { startTime: a.startTime, endTime: b.startTime };
      } else {
        span = findCandleIndexAndSpan(lvl.time, 8);
      }
      [lvl.box_top, lvl.box_bottom].forEach((edgePrice) => {
        const ray = chart.addLineSeries({
          color: edge,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        ray.setData([
          { time: span.startTime, value: edgePrice },
          { time: span.endTime, value: edgePrice }
        ]);
        state.customRaySeries.push(ray);
      });
      zoneFillBand(lvl.box_top, lvl.box_bottom, span, fill);
      const mid = (lvl.box_top + lvl.box_bottom) / 2;
      const anchorBar = barAtOrBefore((span.startTime + span.endTime) / 2) || span.startTime;
      const cls = isIfvg ? "tag-plain ifvg" : bull ? "tag-plain fvg-bull" : "tag-plain fvg-bear";
      pushLabel(anchorBar, mid, isIfvg ? "IFVG" : "FVG", cls, "mid");
    };
    // Order Blocks: origin-color edges; breakers redraw from the flip bar
    // in breaker colors (red was-bullish, green was-bearish).
    const drawOBLevel = (lvl) => {
      const breaker = (lvl.type || "").includes("BREAKER");
      const bull = (lvl.type || "").includes("BULLISH");
      const edge = !breaker ? (bull ? "#2962ff" : "#ff6d00") : (bull ? "#00e676" : "#ff1744");
      const fill = !breaker
        ? (bull ? "rgba(41,98,255,0.08)" : "rgba(255,109,0,0.08)")
        : (bull ? "rgba(0,230,118,0.10)" : "rgba(255,23,68,0.10)");
      const origEdge = bull ? "#ff6d00" : "#2962ff";
      const origFill = bull ? "rgba(255,109,0,0.08)" : "rgba(41,98,255,0.08)";
      let span;
      if (lvl.end_time && lvl.end_time > lvl.time) {
        const a = findCandleIndexAndSpan(lvl.time, 0);
        const b = findCandleIndexAndSpan(lvl.end_time, 0);
        span = { startTime: a.startTime, endTime: b.startTime };
      } else {
        span = findCandleIndexAndSpan(lvl.time, 8);
      }
      const edgeRay = (price, from, to, color) => {
        const ray = chart.addLineSeries({
          color, lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        ray.setData([{ time: from, value: price }, { time: to, value: price }]);
        state.customRaySeries.push(ray);
      };
      if (breaker && lvl.break_time && lvl.break_time > lvl.time) {
        const b = findCandleIndexAndSpan(lvl.break_time, 0);
        [lvl.box_top, lvl.box_bottom].forEach((p) => edgeRay(p, span.startTime, b.startTime, origEdge));
        zoneFillBand(lvl.box_top, lvl.box_bottom,
          { startTime: span.startTime, endTime: b.startTime }, origFill);
        [lvl.box_top, lvl.box_bottom].forEach((p) => edgeRay(p, b.startTime, span.endTime, edge));
        zoneFillBand(lvl.box_top, lvl.box_bottom,
          { startTime: b.startTime, endTime: span.endTime }, fill);
      } else {
        [lvl.box_top, lvl.box_bottom].forEach((p) => edgeRay(p, span.startTime, span.endTime, edge));
        zoneFillBand(lvl.box_top, lvl.box_bottom, span, fill);
      }
      const mid = (lvl.box_top + lvl.box_bottom) / 2;
      const anchorBar = barAtOrBefore((span.startTime + span.endTime) / 2) || span.startTime;
      const cls = breaker ? "tag-plain brkr" : bull ? "tag-plain ob-bull" : "tag-plain ob-bear";
      pushLabel(anchorBar, mid, breaker ? "BRKR" : "OB", cls, "mid");
    };
    // Event suffix: MIT = wicked/mitigated, BRK = body-broken.
    const endTag = (lvl) => {
      const tag = levelTag(lvl);
      if (lvl.end_kind === "broken") return `${tag}·BRK`;
      if (lvl.end_kind === "mitigated") return `${tag}·MIT`;
      return tag;
    };
    // Trendline segment: pivot -> end, sloped. Support (lower) teal / resistance
    // (upper) red / break-retest (flipped) orange. Broken lines go thin gray.
    const drawTrendlineLevel = (lvl) => {
      const role = (lvl.role || "").toLowerCase();
      const resistance = role === "resistance"
        || (lvl.type || "").includes("RESISTANCE")
        || (lvl.type || "").includes("UPPER");
      const flipped = !!lvl.flipped;
      const broken = lvl.end_kind === "broken";
      const retest = lvl.end_kind === "retest";
      const color = flipped ? "#ff9100"
        : (broken && !retest) ? "#5a6b7a"
        : resistance ? "#26a69a" : "#ef5350";
      const t0 = barAtOrBefore(lvl.time) || lvl.time;
      const t1 = (lvl.end_time && lvl.end_time > lvl.time)
        ? (barAtOrBefore(lvl.end_time) || lvl.end_time) : t0;
      if (t1 <= t0) return;
      const p1 = (lvl.price_end !== undefined && lvl.price_end !== null)
        ? lvl.price_end : lvl.price;
      const ray = chart.addLineSeries({
        color: color,
        lineWidth: 1,
        lineStyle: (broken && !retest)
          ? LightweightCharts.LineStyle.Dotted
          : LightweightCharts.LineStyle.Dashed,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ray.setData([
        { time: t0, value: lvl.price },
        { time: t1, value: p1 }
      ]);
      state.customRaySeries.push(ray);
      const cls = flipped ? "tag-plain tl-brt"
        : resistance ? "tag-plain tl-up" : "tag-plain tl-dn";
      const mid = barAtOrBefore((t0 + t1) / 2) || t0;
      pushLabel(mid, (lvl.price + p1) / 2, flipped ? "BRT" : "TL", cls, "mid");
      if (broken) {
        const bt = lvl.break_time ? (barAtOrBefore(lvl.break_time) || t1) : t1;
        pushLabel(bt, retest ? p1 : lvl.price, "B", cls, "mid");
      }
      if (retest && lvl.retest_time) {
        const rt = barAtOrBefore(lvl.retest_time) || t1;
        pushLabel(rt, p1, "RT", cls, "mid");
      }
    };
    let count = 0;
    visible.forEach((lvl) => {
      // Gap/order-block zones draw edges + fill instead of a single ray.
      if (isZoneLevel(lvl)) {
        if (lvl.category === "ob") drawOBLevel(lvl);
        else drawZoneLevel(lvl);
        count++;
        return;
      }
      // Trendlines: sloped pivot -> end segment (LuxAlgo-style dashed).
      if (lvl.category === "trendline") {
        drawTrendlineLevel(lvl);
        count++;
        return;
      }
      let color = "#00e5ff";
      let lineStyle = LightweightCharts.LineStyle.Solid;
      let lineWidth = 1;

      if (lvl.category === "sr") {
        if (lvl.type.includes("SUPPORT")) {
          color = lvl.state === "FRESH" ? "#00e5ff" : "#546e7a";
        } else if (lvl.type.includes("RESISTANCE")) {
          color = lvl.state === "FRESH" ? "#ff9100" : "#78909c";
        } else if (lvl.type.includes("RBS")) {
          color = "#00e676";
        } else if (lvl.type.includes("SBR")) {
          color = "#ff1744";
        }
        lineStyle = lvl.state === "FRESH" ? LightweightCharts.LineStyle.Solid : LightweightCharts.LineStyle.Dashed;
      } else if (lvl.category === "ocl") {
        color = lvl.state === "FRESH" ? "#ffd600" : "#8a7a00";
        lineStyle = LightweightCharts.LineStyle.Dotted;
        lineWidth = 2;
      } else if (lvl.category === "qm") {
        color = lvl.state === "FRESH" ? "#b388ff" : "#6d5b99";
        lineStyle = lvl.state === "FRESH" ? LightweightCharts.LineStyle.Solid : LightweightCharts.LineStyle.Dashed;
        lineWidth = 2;
      } else if (lvl.category === "apex") {
        const sup = lvl.type.includes("SUPPORT");
        color = lvl.state === "FRESH" ? (sup ? "#00e676" : "#ff1744") : "#546e7a";
        lineStyle = LightweightCharts.LineStyle.LargeDashed;
      } else if (lvl.category === "ts") {
        const bearish = (lvl.type || "").includes("HIGH");
        color = bearish ? "#ff5c6c" : "#00e676";
        lineStyle = LightweightCharts.LineStyle.Solid;
        lineWidth = 1;
      } else if (lvl.category === "idm") {
        color = "#ffd600";
        lineStyle = LightweightCharts.LineStyle.Solid;
        lineWidth = 1;
      } else if (lvl.category === "bos") {
        const choch = (lvl.type || "").includes("CHOCH");
        color = choch ? "#ff9100" : "#7aa2ff";
        lineStyle = LightweightCharts.LineStyle.Solid;
        lineWidth = 1;
      }

      // Broken levels are history: thin gray dotted, no emphasis.
      if (lvl.end_kind === "broken") {
        color = "#5a6b7a";
        lineStyle = LightweightCharts.LineStyle.Dotted;
        lineWidth = 1;
      }

      // Zone-to-zone span: formation -> life-cycle end (or short active span).
      // TS rays instead run swept-wick (candle 1) -> just past candle 2.
      let span;
      if (lvl.category === "ts" && lvl.start_time) {
        span = tsSpan(lvl);
      } else if (lvl.end_time && lvl.end_time > lvl.time) {
        const a = findCandleIndexAndSpan(lvl.time, 0);
        const b = findCandleIndexAndSpan(lvl.end_time, 0);
        span = { startTime: a.startTime, endTime: b.startTime };
      } else {
        span = findCandleIndexAndSpan(lvl.time, 8);
      }

      // Add bounded ray series
      const ray = chart.addLineSeries({
        color: color,
        lineWidth: lineWidth,
        lineStyle: lineStyle,
        priceLineVisible: false,
        lastValueVisible: false,
      });

      ray.setData([
        { time: span.startTime, value: lvl.price },
        { time: span.endTime, value: lvl.price }
      ]);
      state.customRaySeries.push(ray);

      // Shorthand text on the line (broken history: line only).
      // TS tags sit middle-right (75% along the ray), plain text, no bubble.
      if (lvl.end_kind !== "broken") {
        const frac = span.extend ? 0.75 : 0.5;
        const anchorTs = span.startTime + (span.endTime - span.startTime) * frac;
        const anchorBar = barAtOrBefore(anchorTs) || span.startTime;
        const plainCls = lvl.category === "ts"
          ? ("tag-plain " + ((lvl.type || "").includes("HIGH") ? "ts-high" : "ts-low"))
          : lvl.category === "idm"
            ? "tag-plain idm"
            : lvl.category === "bos"
              ? ("tag-plain " + ((lvl.type || "").includes("CHOCH") ? "choch" : "bos"))
              : "tag-dim";
        pushLabel(anchorBar, lvl.price, endTag(lvl), plainCls, "mid");
      }

      count++;
    });

    markers.sort((a, b) => a.time - b.time);
    markerSeries.setMarkers(markers);
    markLabelsDirty();
    renderOverlayLabels();
    overlayActiveCount.textContent = hidden > 0 ? `${count} (+${hidden} older hidden)` : `${count}`;
  }

  // =========================================================================
  // Live Levels Drawer Table
  // =========================================================================

  function renderLevelsTable() {
    const anyIndicatorOn = (TS_ENABLED && state.indicators.ts)
      || (TL_ENABLED && state.indicators.tl)
      || (IDM_ENABLED && state.indicators.idm)
      || (BOS_ENABLED && state.indicators.bos)
      || (FVG_ENABLED && state.indicators.fvg)
      || (IFVG_ENABLED && state.indicators.ifvg)
      || (OB_ENABLED && state.indicators.ob)
      || ((SR_ENABLED || INDICATORS_ENABLED) && state.indicators.sr)
      || ((QM_ENABLED || INDICATORS_ENABLED) && state.indicators.qm)
      || ((OCL_ENABLED || INDICATORS_ENABLED) && state.indicators.ocl)
      || ((APEX_ENABLED || INDICATORS_ENABLED) && state.indicators.apex);
    if (!anyIndicatorOn) {
      levelsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">No indicators enabled — pick a view or toggle a layer.</td></tr>`;
      return;
    }
    if (!state.levels || state.levels.length === 0) {
      levelsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">No levels detected with current filters.</td></tr>`;
      return;
    }

    let html = "";
    state.levels.forEach((lvl) => {
      let badgeClass = "badge-support";
      if (lvl.category === "ocl") badgeClass = "badge-ocl";
      else if (lvl.category === "qm") badgeClass = "badge-qm";
      else if (lvl.category === "idm") badgeClass = "badge-idm";
      else if (lvl.category === "bos") badgeClass = "badge-bos";
      else if (lvl.category === "fvg") badgeClass = "badge-fvg";
      else if (lvl.category === "ifvg") badgeClass = "badge-ifvg";
      else if (lvl.category === "ob") badgeClass = (lvl.type || "").includes("BREAKER") ? "badge-breaker" : "badge-ob";
      else if (lvl.category === "ts") badgeClass = "badge-ts";
      else if (lvl.category === "apex") badgeClass = "badge-apex";
      else if (lvl.type.includes("RESISTANCE")) badgeClass = "badge-resistance";

      let statusClass = "tag-fresh";
      if (lvl.state === "UNFRESH") statusClass = "tag-unfresh";
      else if (lvl.state === "BROKEN") statusClass = "tag-broken";

      const distPts = Math.abs(lvl.price - state.currentPrice).toFixed(1);

      html += `
        <tr data-price="${lvl.price}">
          <td><span class="level-badge ${badgeClass}">${lvl.type}</span></td>
          <td style="font-weight:600; color:#fff;">${lvl.price.toFixed(2)}</td>
          <td><span class="status-tag ${statusClass}">${lvl.state}</span></td>
          <td style="color:#9aa5b5;">${distPts}</td>
        </tr>
      `;
    });

    levelsTableBody.innerHTML = html;
    bindTableRowClicks();
  }

  function bindTableRowClicks() {
    levelsTableBody.querySelectorAll("tr").forEach((row) => {
      row.addEventListener("click", () => {
        const p = parseFloat(row.dataset.price);
        if (!isNaN(p)) {
          levelsTableBody.querySelectorAll("tr").forEach(r => r.style.background = "");
          row.style.background = "rgba(0, 229, 255, 0.15)";
          chart.timeScale().scrollToPosition(0, true);
        }
      });
    });
  }

  // =========================================================================
  // Event Listeners & Filter Controls
  // =========================================================================

  symbolSelect.addEventListener("change", (e) => {
    state.symbol = e.target.value;
    refreshData();
  });

  tfButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tfButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.timeframe = btn.dataset.tf;
      // Overflow dropdown: show the picked sub-TF on the toggle, close menu.
      if (tfMoreBtn && tfDropdownMenu) {
        const inMenu = btn.closest && btn.closest("#tfDropdownMenu");
        tfMoreBtn.textContent = inMenu ? (btn.textContent.trim() + " ▾") : "More ▾";
        tfMoreBtn.classList.toggle("active", !!inMenu);
        tfDropdownMenu.classList.remove("open");
      }
      refreshData();
    });
  });

  // Overflow dropdown open/close.
  if (tfMoreBtn && tfDropdownMenu) {
    tfMoreBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      tfDropdownMenu.classList.toggle("open");
    });
    document.addEventListener("click", () => tfDropdownMenu.classList.remove("open"));
  }

  btnCandles.addEventListener("click", () => {
    btnCandles.classList.add("active");
    btnLine.classList.remove("active");
    state.chartType = "candles";
    syncChartSeriesVisibility();
    renderVisualRaysAndMarkers();
  });

  btnLine.addEventListener("click", () => {
    btnLine.classList.add("active");
    btnCandles.classList.remove("active");
    state.chartType = "line";
    syncChartSeriesVisibility();
    renderVisualRaysAndMarkers();
  });

  btnRefresh.addEventListener("click", () => refreshData());
  btnResetZoom.addEventListener("click", () => chart.timeScale().fitContent());

  // =========================================================================
  // Bot Settings drawer — entry modules (strategy library management).
  // =========================================================================

  function openSettings() {
    if (settingsDrawer) settingsDrawer.classList.add("open");
    if (settingsBackdrop) settingsBackdrop.classList.add("open");
    fetchModules();
  }

  function closeSettings() {
    if (settingsDrawer) settingsDrawer.classList.remove("open");
    if (settingsBackdrop) settingsBackdrop.classList.remove("open");
  }

  async function fetchModules() {
    if (!modulesList) return;
    try {
      const res = await fetch("/api/settings/modules");
      if (!res.ok) throw new Error("settings API unavailable");
      const data = await res.json();
      renderModulesList(data.modules || []);
    } catch (err) {
      modulesList.innerHTML = `<div class="empty-state">Could not load entry modules.</div>`;
    }
  }

  function renderModulesList(modules) {
    const on = modules.filter((m) => m.enabled).length;
    if (modulesCountBadge) modulesCountBadge.textContent = `${on} on`;
    if (!modules.length) {
      modulesList.innerHTML = `<div class="empty-state">No entry modules registered.</div>`;
      return;
    }
    modulesList.innerHTML = "";
    modules.forEach((mod) => {
      const row = document.createElement("div");
      row.className = "module-row";
      const info = document.createElement("div");
      info.className = "module-info";
      const name = document.createElement("span");
      name.className = "module-name";
      name.textContent = mod.name;
      const desc = document.createElement("span");
      desc.className = "module-desc";
      desc.textContent = mod.description || mod.engine;
      info.appendChild(name);
      info.appendChild(desc);
      const toggle = document.createElement("label");
      toggle.className = "switch";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!mod.enabled;
      input.addEventListener("change", () => toggleModule(mod.id, input.checked, input));
      const slider = document.createElement("span");
      slider.className = "slider round";
      toggle.appendChild(input);
      toggle.appendChild(slider);
      row.appendChild(info);
      row.appendChild(toggle);
      modulesList.appendChild(row);
    });
    if (window.lucide) lucide.createIcons();
  }

  async function toggleModule(id, enabled, input) {
    try {
      const res = await fetch(
        `/api/settings/modules/${encodeURIComponent(id)}?enabled=${enabled}`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error("toggle failed");
      fetchModules();
      refreshData(); // entry zones + execution deck follow the registry
    } catch (err) {
      if (input) input.checked = !enabled;
    }
  }

  async function setAllModules(enabled) {
    try {
      const res = await fetch("/api/settings/modules");
      if (!res.ok) return;
      const data = await res.json();
      for (const mod of data.modules || []) {
        if (!!mod.enabled !== enabled) {
          await fetch(
            `/api/settings/modules/${encodeURIComponent(mod.id)}?enabled=${enabled}`,
            { method: "POST" }
          );
        }
      }
      fetchModules();
      refreshData();
    } catch (err) {}
  }

  if (btnSettings) btnSettings.addEventListener("click", openSettings);
  if (brandSection) brandSection.addEventListener("click", openSettings);
  if (btnCloseSettings) btnCloseSettings.addEventListener("click", closeSettings);
  if (settingsBackdrop) settingsBackdrop.addEventListener("click", closeSettings);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSettings();
  });
  if (btnModulesAll) btnModulesAll.addEventListener("click", () => setAllModules(true));
  if (btnModulesNone) btnModulesNone.addEventListener("click", () => setAllModules(false));

  modePills.forEach((pill) => {
    pill.addEventListener("click", () => {
      const mode = pill.dataset.mode;
      // Gated modes: ocl/apex need their flags (or the old stack).
      if (mode === "ocl" && !OCL_ENABLED && !INDICATORS_ENABLED) return;
      if (mode === "apex" && !APEX_ENABLED && !INDICATORS_ENABLED) return;
      if (mode === "sr" && !SR_ENABLED && !INDICATORS_ENABLED) return;
      if (mode === "qm" && !QM_ENABLED && !INDICATORS_ENABLED) return;
      if (mode === "idm" && !IDM_ENABLED) return;
      if (mode === "bos" && !BOS_ENABLED) return;
      if (mode === "fvg" && !FVG_ENABLED && !IFVG_ENABLED) return;
      if (mode === "ifvg" && !IFVG_ENABLED) return;
      if (mode === "ob" && !OB_ENABLED) return;
      modePills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      state.inspectMode = mode;

      // Every mode assigns the full indicator set explicitly.
      const MODES = {
        ts:       { sr: false, ocl: false, qm: false, apex: false, ts: true, idm: false, bos: false, fvg: false, ifvg: false, ob: false },
        idm:      { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: true, bos: false, fvg: false, ifvg: false, ob: false },
        bos:      { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: true, fvg: false, ifvg: false, ob: false },
        fvg:      { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: true, ifvg: false, ob: false },
        ifvg:     { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: true, ob: false },
        ob:       { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: true },
        sr:       { sr: true, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false, tl: false },
        qm:       { sr: false, ocl: false, qm: true, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false, tl: false },
        ocl:      { sr: false, ocl: true, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false, tl: false },
        apex:     { sr: false, ocl: false, qm: false, apex: true, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false, tl: false },
        all: {
          sr: SR_ENABLED || INDICATORS_ENABLED,
          ocl: OCL_ENABLED || INDICATORS_ENABLED,
          qm: QM_ENABLED || INDICATORS_ENABLED,
          apex: APEX_ENABLED || INDICATORS_ENABLED,
          ts: TS_ENABLED,
          idm: IDM_ENABLED,
          bos: BOS_ENABLED,
          fvg: FVG_ENABLED,
          ifvg: IFVG_ENABLED,
          ob: OB_ENABLED,
          tl: TL_ENABLED,
        },
      };
      const next = MODES[mode];
      if (!next) return;
      state.indicators = { ...next };
      toggleSR.checked = next.sr;
      toggleOCL.checked = next.ocl;
      toggleQM.checked = next.qm;
      toggleApex.checked = next.apex;
      if (toggleTS) toggleTS.checked = next.ts;
      if (toggleIDM) toggleIDM.checked = next.idm;
      if (toggleBOS) toggleBOS.checked = next.bos;
      if (toggleFVG) toggleFVG.checked = next.fvg;
      if (toggleIFVG) toggleIFVG.checked = next.ifvg;
      if (toggleOB) toggleOB.checked = next.ob;
      if (toggleTL) toggleTL.checked = next.tl;
      if (mode === "apex") btnLine.click();

      refreshData();
    });
  });

  segButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      segButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.freshness = btn.dataset.freshness;
      refreshData();
    });
  });

  toggleSR.addEventListener("change", (e) => {
    if (!INDICATORS_ENABLED && !SR_ENABLED) { e.target.checked = false; return; }
    state.indicators.sr = e.target.checked;
    refreshData();
  });
  toggleOCL.addEventListener("change", (e) => {
    if (!INDICATORS_ENABLED && !OCL_ENABLED) { e.target.checked = false; return; }
    state.indicators.ocl = e.target.checked;
    refreshData();
  });
  toggleQM.addEventListener("change", (e) => {
    if (!INDICATORS_ENABLED && !QM_ENABLED) { e.target.checked = false; return; }
    state.indicators.qm = e.target.checked;
    refreshData();
  });
  toggleApex.addEventListener("change", (e) => {
    if (!INDICATORS_ENABLED && !APEX_ENABLED) { e.target.checked = false; return; }
    state.indicators.apex = e.target.checked;
    refreshData();
  });
  if (toggleTS) {
    toggleTS.addEventListener("change", (e) => {
      state.indicators.ts = e.target.checked;
      refreshData();
    });
  }
  if (toggleIDM) {
    toggleIDM.addEventListener("change", (e) => {
      if (!IDM_ENABLED) { e.target.checked = false; return; }
      state.indicators.idm = e.target.checked;
      refreshData();
    });
  }
  if (toggleBOS) {
    toggleBOS.addEventListener("change", (e) => {
      if (!BOS_ENABLED) { e.target.checked = false; return; }
      state.indicators.bos = e.target.checked;
      refreshData();
    });
  }
  if (toggleFVG) {
    toggleFVG.addEventListener("change", (e) => {
      if (!FVG_ENABLED) { e.target.checked = false; return; }
      state.indicators.fvg = e.target.checked;
      refreshData();
    });
  }
  if (toggleIFVG) {
    toggleIFVG.addEventListener("change", (e) => {
      if (!IFVG_ENABLED) { e.target.checked = false; return; }
      state.indicators.ifvg = e.target.checked;
      refreshData();
    });
  }
  if (toggleOB) {
    toggleOB.addEventListener("change", (e) => {
      if (!OB_ENABLED) { e.target.checked = false; return; }
      state.indicators.ob = e.target.checked;
      refreshData();
    });
  }
  if (toggleTL) {
    toggleTL.addEventListener("change", (e) => {
      if (!TL_ENABLED) { e.target.checked = false; return; }
      state.indicators.tl = e.target.checked;
      refreshData();
    });
  }
  loadSymbols().then(() => {
    syncChartSeriesVisibility();
    refreshData();
  });

  setInterval(() => {
    // Skip the tick while a refresh is still in flight — piling requests
    // onto a slow MT5 connection is what wedges the dashboard.
    if (!activeRefreshController) refreshData();
  }, 10000);

  window.addEventListener("error", (event) => {
    console.error("[MSNR UI] uncaught error", event.error || event.message || event);
    setConnectionStatus("error", "ERROR", event.message || "Unhandled error");
  });

  window.addEventListener("unhandledrejection", (event) => {
    console.error("[MSNR UI] unhandled promise rejection", event.reason);
    const msg = event.reason && event.reason.message ? event.reason.message : "Unhandled async error";
    setConnectionStatus("error", "ERROR", msg);
  });
});
