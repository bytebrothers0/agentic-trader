/**
 * MSNR Trading Terminal — Frontend JavaScript Engine
 * Bounded Formation Rays, Candlestick Markers & Multi-Storyline Execution Deck
 */

document.addEventListener("DOMContentLoaded", () => {
  // MASTER SWITCHES — mirrors config/settings.py. Strategy on/off is now
  // driven live by the server (/api/strategy `disabled` flag) via the
  // entry-module registry, so there is no frontend strategy const.
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

  if (window.lucide) {
    lucide.createIcons();
  }

  // State Management
  const state = {
    symbol: "XAUUSDm",
    timeframe: "D1",
    chartType: "candles",
    inspectMode: "strategy", // default: clean candles, everything off
    freshness: "all",
    // Strategy view shows ONLY the selected (primary, rank #1) entry zone by
    // default. Tick "show all zones" to overlay every ranked entry.
    showAllZones: false,
    autoTrade: false,
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
      ob: false
    },
    candles: [],
    levels: [],
    strategyData: null,
    activeSignals: [],
    selectedSignalIndex: 0,
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
    M15: 800, M5: 1000, M3: 1000, M1: 1000,
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
  const toggleAllZones = document.getElementById("toggleAllZones");
  
  const overlaySymbol = document.getElementById("overlaySymbol");
  const overlayTF = document.getElementById("overlayTF");
  const overlayActiveCount = document.getElementById("overlayActiveCount");
  const levelsTableBody = document.getElementById("levelsTableBody");
  const chartContainer = document.getElementById("tvChartContainer");
  const labelLayer = document.getElementById("chartLabelLayer");

  // Storyline card elements
  const mainBiasBadge = document.getElementById("mainBiasBadge");
  const biasMN = document.getElementById("biasMN");
  const biasW1 = document.getElementById("biasW1");
  const biasD1 = document.getElementById("biasD1");
  const entryZonesList = document.getElementById("entryZonesList");
  const entryCountBadge = document.getElementById("entryCountBadge");

  // Phase 5 Account & Execution elements
  const accEquity = document.getElementById("accEquity");
  const accLeverage = document.getElementById("accLeverage");
  const autoTradeToggle = document.getElementById("autoTradeToggle");
  const btnPlaceOrder = document.getElementById("btnPlaceOrder");
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

      // 2. Fetch Multi-Storyline Strategy Core (server decides on/off
      // via the entry-module registry)
      const stratRes = await fetch(`/api/strategy?symbol=${encodeURIComponent(state.symbol)}`, { signal: controller.signal });
      if (stratRes.ok) {
        state.strategyData = await stratRes.json();
        if (controller.signal.aborted || requestId !== refreshSequence) return;
        updateStorylineUI(state.strategyData);
      }

      // 3. Fetch All Signals (Multi-Storyline Entry Zones)
      const sigRes = await fetch(`/api/signals?symbol=${encodeURIComponent(state.symbol)}`, { signal: controller.signal });
      if (sigRes.ok) {
        const sigData = await sigRes.json();
        if (controller.signal.aborted || requestId !== refreshSequence) return;
        state.activeSignals = sigData.signals || [];
        state.selectedSignalIndex = Math.min(state.selectedSignalIndex, Math.max(0, state.activeSignals.length - 1));
        renderEntryZonesList();
        updatePlaceOrderButton();
      } else {
        state.activeSignals = [];
      }

      // 4. Fetch Account & Positions (Phase 5)
      await fetchAccountMetrics();
      await fetchLivePositions();

      // 5. Indicators — TS/SR/QM/IDM (new strategy) fetch even while the
      // rest of the old MSNR stack is disabled. Legacy OCL/Apex stay empty.
      const wantTS = TS_ENABLED && state.indicators.ts;
      const wantSR = (SR_ENABLED || INDICATORS_ENABLED) && state.indicators.sr;
      const wantQM = (QM_ENABLED || INDICATORS_ENABLED) && state.indicators.qm;
      const wantIDM = IDM_ENABLED && state.indicators.idm;
      const wantBOS = BOS_ENABLED && state.indicators.bos;
      const wantFVG = FVG_ENABLED && state.indicators.fvg;
      const wantIFVG = IFVG_ENABLED && state.indicators.ifvg;
      const wantOB = OB_ENABLED && state.indicators.ob;
      const wantOCL = (OCL_ENABLED || INDICATORS_ENABLED) && state.indicators.ocl;
      const wantAPEX = (APEX_ENABLED || INDICATORS_ENABLED) && state.indicators.apex;
      const wantLegacy = wantOCL || wantAPEX;
      if (!wantTS && !wantSR && !wantQM && !wantIDM && !wantBOS && !wantFVG && !wantIFVG && !wantOB && !wantLegacy) {
        state.levels = [];
      } else {
      // 5. Fetch Raw Indicators if in inspector mode
      if (state.inspectMode !== "strategy") {
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
        });

        const indRes = await fetch(`/api/indicators?${params.toString()}`, { signal: controller.signal });
        if (indRes.ok) {
          const indData = await indRes.json();
          if (controller.signal.aborted || requestId !== refreshSequence) return;
          state.levels = indData.levels || [];
        } else {
          state.levels = [];
        }
      } else {
        state.levels = [];
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
  // Storyline Multi-TF Card Update
  // =========================================================================

  function updateStorylineUI(strat) {
    if (!strat || strat.disabled) {
      if (mainBiasBadge) {
        mainBiasBadge.textContent = "DISABLED";
        mainBiasBadge.className = "bias-badge";
      }
      if (biasMN) biasMN.textContent = "--";
      if (biasW1) biasW1.textContent = "--";
      if (biasD1) biasD1.textContent = "--";
      return;
    }
    if (!strat.storylines) return;

    const sl = strat.storylines;
    const mnObj = sl["MN1_W1"] || sl["M1_W1"];
    const mn = mnObj ? mnObj.bias : "--";
    const w1 = sl["W1_D1"] ? sl["W1_D1"].bias : "--";
    const d1 = sl["D1_H4"] ? sl["D1_H4"].bias : "--";

    biasMN.textContent = mn;
    biasMN.className = `tf-val ${mn.toLowerCase()}`;

    biasW1.textContent = w1;
    biasW1.className = `tf-val ${w1.toLowerCase()}`;

    biasD1.textContent = d1;
    biasD1.className = `tf-val ${d1.toLowerCase()}`;

    const activeBias = d1 !== "--" ? d1 : (w1 !== "--" ? w1 : (mn !== "--" ? mn : "BULLISH"));
    mainBiasBadge.textContent = activeBias;
    mainBiasBadge.className = `bias-badge ${activeBias === 'BULLISH' ? 'bias-bullish' : 'bias-bearish'}`;
  }

  // =========================================================================
  // Multi-Storyline Entry Zones List Rendering
  // =========================================================================

  function renderEntryZonesList() {
    if (!state.strategyData || state.strategyData.disabled) {
      entryCountBadge.textContent = "0 Zones";
      overlayActiveCount.textContent = "0";
      entryZonesList.innerHTML = `<div class="empty-state">Strategy disabled — enable entry modules in Bot Settings (gear).</div>`;
      return;
    }
    const signals = state.activeSignals;
    entryCountBadge.textContent = `${signals.length} Zones`;
    overlayActiveCount.textContent = `${signals.length}`;

    if (!signals || signals.length === 0) {
      entryZonesList.innerHTML = `<div class="empty-state">Scanning for valid storyline entries...</div>`;
      return;
    }

    let html = "";
    signals.forEach((sig, idx) => {
      const isSelected = idx === state.selectedSignalIndex;
      const isBuy = sig.direction === "BULLISH";
      const tagClass = isBuy ? "zone-tag-bullish" : "zone-tag-bearish";
      
      let label = "Zone";
      if (sig.model_type.includes("TS_M15")) label = "TS M15";
      else if (sig.model_type.includes("D1_ENTRY") || sig.model_type.includes("DAILY")) label = "Daily Entry";
      else if (sig.model_type.includes("W1_ENTRY") || sig.model_type.includes("WEEKLY")) label = "Weekly Entry";
      else if (sig.model_type.includes("MN_ENTRY") || sig.model_type.includes("MONTHLY")) label = "Monthly Entry";
      else if (sig.model_type.includes("14B")) label = "14B Confirm";
      else if (sig.model_type.includes("D1W4")) label = "D1W4 Retrace";
      else label = sig.model_type;

      const splitBadge = sig.secondary_entry 
        ? `<div style="margin-top: 4px; font-size: 11px; color: #a78bfa; font-weight: 500;">⚡ Split 70% @ ${sig.entry_price.toFixed(2)} (${sig.lot_size.toFixed(2)}L) | 30% @ ${sig.secondary_entry.entry_price.toFixed(2)} (${sig.secondary_entry.lot_size.toFixed(2)}L)</div>` 
        : "";

      html += `
        <div class="entry-zone-card ${isSelected ? 'active-selected' : ''}" data-idx="${idx}">
          <div class="zone-card-top">
            <span class="zone-tag ${tagClass}">[#${sig.priority_rank}] ${sig.direction} &bull; ${label}</span>
            <span class="zone-dist">${sig.distance_to_entry.toFixed(1)} pts away</span>
          </div>
          <div class="zone-card-main">
            <span class="zone-price">${sig.entry_price.toFixed(2)}</span>
            <span class="zone-model-name">${sig.ftfl_tf} &rarr; ${sig.stfl_tf} &rarr; ${sig.ttfl_tf}</span>
          </div>
          <div class="zone-card-details">
            <span>SL: <strong class="zone-sl">${sig.stop_loss.toFixed(2)}</strong></span>
            <span>TP: <strong class="zone-tp">${sig.take_profit.toFixed(2)}</strong></span>
            <span>Lots: <strong class="zone-sizing">${sig.lot_size.toFixed(2)}</strong></span>
          </div>
          ${splitBadge}
        </div>
      `;
    });

    entryZonesList.innerHTML = html;

    // Attach click listeners to entry cards
    entryZonesList.querySelectorAll(".entry-zone-card").forEach((card) => {
      card.addEventListener("click", () => {
        const idx = parseInt(card.dataset.idx);
        state.selectedSignalIndex = idx;
        renderEntryZonesList();
        updatePlaceOrderButton();
        renderVisualRaysAndMarkers();
        
        // Scroll chart to right
        chart.timeScale().scrollToPosition(0, true);
      });
    });
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

  function updatePlaceOrderButton() {
    if (!state.strategyData || state.strategyData.disabled) {
      btnPlaceOrder.innerHTML = `<i data-lucide="pause"></i> Strategy Disabled`;
      btnPlaceOrder.disabled = true;
      btnPlaceOrder.style.opacity = "0.6";
      if (window.lucide) lucide.createIcons();
      return;
    }
    if (state.activeSignals.length > 0) {
      const sig = state.activeSignals[state.selectedSignalIndex] || state.activeSignals[0];
      btnPlaceOrder.innerHTML = `<i data-lucide="send"></i> Place [${sig.priority_rank}] ${sig.direction} Limit (${sig.lot_size.toFixed(2)} Lots @ ${sig.entry_price.toFixed(2)})`;
      btnPlaceOrder.disabled = false;
      btnPlaceOrder.style.opacity = "1";
    } else {
      btnPlaceOrder.innerHTML = `<i data-lucide="clock"></i> Scanning for A+ Entry...`;
      btnPlaceOrder.disabled = true;
      btnPlaceOrder.style.opacity = "0.6";
    }
    if (window.lucide) lucide.createIcons();
  }

  btnPlaceOrder.addEventListener("click", async () => {
    if (state.activeSignals.length === 0) return;
    const sig = state.activeSignals[state.selectedSignalIndex] || state.activeSignals[0];

    const confirmed = confirm(
      `Confirm Limit Order Execution (MSNR Top-Down Analysis):\n\nSymbol: ${sig.symbol}\nModel: ${sig.model_type}\nDirection: ${sig.direction}\nEntry: ${sig.entry_price.toFixed(2)}\nStop Loss: ${sig.stop_loss.toFixed(2)}\nTake Profit: ${sig.take_profit.toFixed(2)}\nLots: ${sig.lot_size.toFixed(2)} (1% Account Risk: $${sig.risk_usd.toFixed(2)})\nStoryline: ${sig.storyline}`
    );

    if (!confirmed) return;

    try {
      const params = new URLSearchParams({
        symbol: sig.symbol,
        direction: sig.direction,
        entry: sig.entry_price,
        sl: sig.stop_loss,
        tp: sig.take_profit,
        lots: sig.lot_size
      });

      const res = await fetch(`/api/orders/place?${params.toString()}`, { method: "POST" });
      const data = await res.json();

      if (data.success) {
        alert(`Limit Order #${data.ticket} successfully placed into MT5!`);
        refreshData();
      } else {
        alert(`Order placement failed: ${data.comment || data.error}`);
      }
    } catch (e) {
      alert(`Error placing order: ${e.message}`);
    }
  });

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

    if (state.inspectMode === "strategy") {
      const signals = state.activeSignals;
      if (!signals || signals.length === 0) {
        markerSeries.setMarkers([]);
        overlayActiveCount.textContent = "0";
        return;
      }

      // Readability rule: draw ONLY the selected (primary) entry zone as a
      // TradingView-style LONG/SHORT position box. "Show all zones" overlays
      // the rest as faint context entry lines without labels.
      const drawn = state.showAllZones
        ? signals.map((sig, idx) => ({ sig, idx }))
        : [{ sig: signals[state.selectedSignalIndex] || signals[0], idx: state.selectedSignalIndex }];

      const hline = (value, span, color, width, style, lastVisible) => {
        const s = chart.addLineSeries({
          color, lineWidth: width,
          lineStyle: style,
          crosshairMarkerVisible: false,
          priceLineVisible: false,
          lastValueVisible: !!lastVisible,
        });
        s.setData([{ time: span.startTime, value }, { time: span.endTime, value }]);
        state.customRaySeries.push(s);
        return s;
      };
      // Vertical connector between two prices at one bar (box edge).
      const vline = (time, vTop, vBottom, color) => {
        const s = chart.addLineSeries({
          color, lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Solid,
          crosshairMarkerVisible: false,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        s.setData([{ time, value: vTop }, { time, value: vBottom }]);
        state.customRaySeries.push(s);
      };

      drawn.forEach(({ sig, idx }) => {
        if (!sig) return;
        const isSelected = idx === state.selectedSignalIndex;
        const isBuy = sig.direction === "BULLISH";
        const span = findCandleIndexAndSpan(sig.formation_time, isSelected ? 16 : 10);

        if (!isSelected) {
          // Faint context entry line only.
          hline(sig.entry_price, span,
            isBuy ? "rgba(0, 229, 255, 0.35)" : "rgba(255, 145, 0, 0.35)",
            1, LightweightCharts.LineStyle.Dotted, false);
          markers.push({
            time: span.startTime,
            position: isBuy ? "belowBar" : "aboveBar",
            color: isBuy ? "rgba(0, 229, 255, 0.7)" : "rgba(255, 145, 0, 0.7)",
            shape: isBuy ? "arrowUp" : "arrowDown",
          });
          return;
        }

        // --- Position box (TradingView long/short tool emulation) ---
        // Filled profit (teal) + risk (orange) zones via baseline-fill series,
        // framed by entry (blue) / TP (green) / SL (red) horizontals and
        // vertical edges. All text lives ON the lines as overlay pills.
        const entryColor = "#2962ff";
        const tpColor = "#00e676";
        const slColor = "#ff5c6c";
        const edgeColor = "rgba(148, 163, 184, 0.65)";
        const PROFIT_FILL = ["rgba(8, 153, 129, 0.30)", "rgba(8, 153, 129, 0.10)"];
        const RISK_FILL = ["rgba(255, 145, 0, 0.32)", "rgba(255, 145, 0, 0.12)"];
        const CLEAR = "rgba(0, 0, 0, 0)";

        const fillBand = (levelPrice, fillColors) => {
          if (typeof chart.addBaselineSeries !== "function") return;
          const band = chart.addBaselineSeries({
            baseValue: { type: "price", price: sig.entry_price },
            topLineColor: CLEAR,
            bottomLineColor: CLEAR,
            topFillColor1: fillColors[0],
            topFillColor2: fillColors[1],
            bottomFillColor1: fillColors[0],
            bottomFillColor2: fillColors[1],
            lineWidth: 1,
            crosshairMarkerVisible: false,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          band.setData([
            { time: span.startTime, value: levelPrice },
            { time: span.endTime, value: levelPrice },
          ]);
          state.customRaySeries.push(band);
        };
        // Profit band always hugs the TP side, risk band the SL side.
        fillBand(sig.take_profit, PROFIT_FILL);
        fillBand(sig.stop_loss, RISK_FILL);

        hline(sig.entry_price, span, entryColor, 2, LightweightCharts.LineStyle.Solid, true);
        hline(sig.take_profit, span, tpColor, 2, LightweightCharts.LineStyle.Solid, true);
        hline(sig.stop_loss, span, slColor, 2, LightweightCharts.LineStyle.Dashed, true);
        vline(span.startTime, sig.take_profit, sig.stop_loss, edgeColor);
        vline(span.endTime, sig.take_profit, sig.stop_loss, edgeColor);

        // Intermediate obstacle = 80% partial level (Video 11 management).
        if (sig.obstacle_tp) {
          hline(sig.obstacle_tp, span, "rgba(255, 213, 79, 0.9)", 2,
            LightweightCharts.LineStyle.Dashed, true);
        }

        // FTFL / STFL refinement box edges (faint context for where price must hold).
        if (sig.ftfl_box_top && sig.ftfl_box_bottom) {
          hline(sig.ftfl_box_top, span, "rgba(144, 164, 174, 0.5)", 1, LightweightCharts.LineStyle.Dotted, false);
          hline(sig.ftfl_box_bottom, span, "rgba(144, 164, 174, 0.5)", 1, LightweightCharts.LineStyle.Dotted, false);
        }
        if (sig.stfl_box_top && sig.stfl_box_bottom) {
          hline(sig.stfl_box_top, span, "rgba(0, 229, 255, 0.35)", 1, LightweightCharts.LineStyle.Dotted, false);
          hline(sig.stfl_box_bottom, span, "rgba(0, 229, 255, 0.35)", 1, LightweightCharts.LineStyle.Dotted, false);
        }

        // Risk:Reward for the tag (guard div-by-zero).
        const risk = Math.abs(sig.entry_price - sig.stop_loss);
        const reward = Math.abs(sig.take_profit - sig.entry_price);
        const rr = risk > 0 ? (reward / risk).toFixed(1) + "R" : "—";

        // Single direction arrow at formation; everything else is an on-line pill.
        markers.push({
          time: span.startTime,
          position: isBuy ? "belowBar" : "aboveBar",
          color: isBuy ? "#00e676" : "#ff5c6c",
          shape: isBuy ? "arrowUp" : "arrowDown",
        });

        pushLabel(span.endTime, sig.entry_price, `${isBuy ? "LONG" : "SHORT"} ${rr}`, "tag-pos pos-blue", "right");
        pushLabel(span.endTime, sig.take_profit, "TP", "tag-pos pos-green", "right");
        pushLabel(span.endTime, sig.stop_loss, "SL", "tag-pos pos-red", "right");
        if (sig.obstacle_tp) {
          pushLabel(span.endTime, sig.obstacle_tp, "80%", "tag-pos pos-yellow", "right");
        }
      });

      // --- Current storylines only: rejection -> breakout segment + BOS tag ---
      // Past storylines are never stored (engine keeps the latest per pair), so
      // these few faint segments are always "current", never history clutter.
      // Labels sit ON the line, TradingView-drawing style ("daily rejection").
      const tfName = (tf) => {
        const t = (tf || "").toUpperCase();
        if (t === "MN1" || t === "MN") return "monthly";
        if (t === "W1") return "weekly";
        if (t === "D1") return "daily";
        if (t === "H4") return "4h";
        if (t === "H1") return "1h";
        return t.toLowerCase();
      };
      try {
        const storylines = (state.strategyData && state.strategyData.storylines) || {};
        const seen = new Set();
        Object.values(storylines).forEach((sl) => {
          if (!sl || !sl.rejection_time || !sl.breakout_time) return;
          const rejTs = Math.floor(Date.parse(sl.rejection_time) / 1000);
          const brkTs = Math.floor(Date.parse(sl.breakout_time) / 1000);
          if (!isFinite(rejTs) || !isFinite(brkTs) || brkTs <= rejTs) return;
          const key = `${sl.rejection_price}|${rejTs}`;
          if (seen.has(key)) return; // skip alias duplicates (MN1_W1 vs MN_W1)
          seen.add(key);
          const a = findCandleIndexAndSpan(rejTs, 0);
          const b = findCandleIndexAndSpan(brkTs, 0);
          if (!a || !b) return;
          const bull = (sl.bias || "").toUpperCase() === "BULLISH";
          const seg = chart.addLineSeries({
            color: bull ? "rgba(0, 230, 118, 0.45)" : "rgba(255, 23, 68, 0.45)",
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            crosshairMarkerVisible: false,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          seg.setData([
            { time: a.startTime, value: sl.rejection_price },
            { time: b.startTime, value: sl.rejection_price },
          ]);
          state.customRaySeries.push(seg);
          // Mid-line label + BOS tag at the breakout end.
          const midBar = barAtOrBefore((a.startTime + b.startTime) / 2) || a.startTime;
          pushLabel(midBar, sl.rejection_price, `${tfName(sl.htf)} rejection`, "tag-dim", "mid");
          markers.push({
            time: b.startTime,
            position: bull ? "aboveBar" : "belowBar",
            color: bull ? "#00e676" : "#ff1744",
            shape: "circle",
            text: `${tfName(sl.ltf)} bos`,
          });
        });
      } catch (e) { /* storyline overlay is decorative; never break the chart */ }

      // Sort markers by time ascending (required by Lightweight Charts)
      markers.sort((a, b) => a.time - b.time);
      markerSeries.setMarkers(markers);
      markLabelsDirty();
      renderOverlayLabels();
      overlayActiveCount.textContent = state.showAllZones ? `${signals.length}` : "1";
      return;
    }

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
    let count = 0;
    visible.forEach((lvl) => {
      // Gap/order-block zones draw edges + fill instead of a single ray.
      if (isZoneLevel(lvl)) {
        if (lvl.category === "ob") drawOBLevel(lvl);
        else drawZoneLevel(lvl);
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
      levelsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">Indicators & strategy disabled — clean slate for new logic.</td></tr>`;
      return;
    }
    if (state.inspectMode === "strategy") {
      const signals = state.activeSignals;
      if (!state.strategyData || state.strategyData.disabled) {
        levelsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">Strategy off — enable entry modules in Bot Settings (gear), or pick an inspection view.</td></tr>`;
        return;
      }
      if (!signals || signals.length === 0) {
        levelsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">Computing Strategy Core...</td></tr>`;
        return;
      }

      let html = "";
      signals.forEach((sig, idx) => {
        const isSelected = idx === state.selectedSignalIndex;
        const distPts = sig.distance_to_entry.toFixed(1);
        const badgeClass = sig.direction === "BULLISH" ? "badge-support" : "badge-resistance";

        html += `
          <tr style="${isSelected ? 'background: rgba(0, 229, 255, 0.12);' : ''}" data-idx="${idx}">
            <td><span class="level-badge ${badgeClass}">[#${sig.priority_rank}] ${sig.direction}</span></td>
            <td style="font-weight:700; color:#00e5ff;">${sig.entry_price.toFixed(2)}</td>
            <td><span class="status-tag tag-fresh">${sig.confidence}</span></td>
            <td style="color:#00e5ff; font-weight:600;">${distPts}</td>
          </tr>
        `;
      });

      levelsTableBody.innerHTML = html;
      bindTableRowClicks();
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
        if (state.inspectMode === "strategy" && row.dataset.idx !== undefined) {
          const idx = parseInt(row.dataset.idx);
          state.selectedSignalIndex = idx;
          renderEntryZonesList();
          updatePlaceOrderButton();
          renderVisualRaysAndMarkers();
        } else {
          const p = parseFloat(row.dataset.price);
          if (!isNaN(p)) {
            levelsTableBody.querySelectorAll("tr").forEach(r => r.style.background = "");
            row.style.background = "rgba(0, 229, 255, 0.15)";
            chart.timeScale().scrollToPosition(0, true);
          }
        }
      });
    });
  }

  // =========================================================================
  // Event Listeners & Filter Controls
  // =========================================================================

  symbolSelect.addEventListener("change", (e) => {
    state.symbol = e.target.value;
    state.selectedSignalIndex = 0;
    refreshData();
  });

  tfButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tfButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.timeframe = btn.dataset.tf;
      state.selectedSignalIndex = 0;
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
        strategy: { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false },
        ts:       { sr: false, ocl: false, qm: false, apex: false, ts: true, idm: false, bos: false, fvg: false, ifvg: false, ob: false },
        idm:      { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: true, bos: false, fvg: false, ifvg: false, ob: false },
        bos:      { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: true, fvg: false, ifvg: false, ob: false },
        fvg:      { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: true, ifvg: false, ob: false },
        ifvg:     { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: true, ob: false },
        ob:       { sr: false, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: true },
        sr:       { sr: true, ocl: false, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false },
        qm:       { sr: false, ocl: false, qm: true, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false },
        ocl:      { sr: false, ocl: true, qm: false, apex: false, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false },
        apex:     { sr: false, ocl: false, qm: false, apex: true, ts: false, idm: false, bos: false, fvg: false, ifvg: false, ob: false },
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
    if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "custom";
    refreshData();
  });
  toggleOCL.addEventListener("change", (e) => {
    if (!INDICATORS_ENABLED && !OCL_ENABLED) { e.target.checked = false; return; }
    state.indicators.ocl = e.target.checked;
    if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "custom";
    refreshData();
  });
  toggleQM.addEventListener("change", (e) => {
    if (!INDICATORS_ENABLED && !QM_ENABLED) { e.target.checked = false; return; }
    state.indicators.qm = e.target.checked;
    if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "custom";
    refreshData();
  });
  toggleApex.addEventListener("change", (e) => {
    if (!INDICATORS_ENABLED && !APEX_ENABLED) { e.target.checked = false; return; }
    state.indicators.apex = e.target.checked;
    if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "custom";
    refreshData();
  });
  if (toggleTS) {
    toggleTS.addEventListener("change", (e) => {
      state.indicators.ts = e.target.checked;
      if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "ts";
      refreshData();
    });
  }
  if (toggleIDM) {
    toggleIDM.addEventListener("change", (e) => {
      if (!IDM_ENABLED) { e.target.checked = false; return; }
      state.indicators.idm = e.target.checked;
      if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "idm";
      refreshData();
    });
  }
  if (toggleBOS) {
    toggleBOS.addEventListener("change", (e) => {
      if (!BOS_ENABLED) { e.target.checked = false; return; }
      state.indicators.bos = e.target.checked;
      if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "bos";
      refreshData();
    });
  }
  if (toggleFVG) {
    toggleFVG.addEventListener("change", (e) => {
      if (!FVG_ENABLED) { e.target.checked = false; return; }
      state.indicators.fvg = e.target.checked;
      if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "fvg";
      refreshData();
    });
  }
  if (toggleIFVG) {
    toggleIFVG.addEventListener("change", (e) => {
      if (!IFVG_ENABLED) { e.target.checked = false; return; }
      state.indicators.ifvg = e.target.checked;
      if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "ifvg";
      refreshData();
    });
  }
  if (toggleOB) {
    toggleOB.addEventListener("change", (e) => {
      if (!OB_ENABLED) { e.target.checked = false; return; }
      state.indicators.ob = e.target.checked;
      if (e.target.checked && state.inspectMode === "strategy") state.inspectMode = "ob";
      refreshData();
    });
  }

  autoTradeToggle.addEventListener("change", (e) => {
    state.autoTrade = e.target.checked;
    if (state.autoTrade) {
      alert("Auto-Trading Mode Enabled: Bot will automatically place A+ Limit Orders into MT5.");
    }
  });

  if (toggleAllZones) {
    toggleAllZones.addEventListener("change", (e) => {
      state.showAllZones = e.target.checked;
      renderVisualRaysAndMarkers(); // re-render only, no refetch needed
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
