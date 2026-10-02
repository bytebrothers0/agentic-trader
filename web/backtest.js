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
  };

  const container = document.getElementById("btChart");
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
    clearTrades();
    const list = filteredTrades();
    const markers = [];
    list.forEach((t, i) => {
      const isSel = i === state.sel;
      const bull = t.direction === "BULLISH";
      const t0 = tsOf(t.fill_date || t.signal_date);
      const t1 = t.exit_date ? tsOf(t.exit_date)
        : state.candles[Math.min(state.candles.length - 1,
            candleIdxAtOrBefore(t0) + 8)].time;
      const w = isSel ? 2 : 1;
      const dim = (v) => v;
      hline(t.entry, t0, t1, "#2962ff", w, LightweightCharts.LineStyle.Solid);
      hline(t.sl, t0, t1, "#ff5c6c", 1, LightweightCharts.LineStyle.Dashed);
      hline(t.tp, t0, t1, "#00e676", 1, LightweightCharts.LineStyle.Solid);
      fillBand(t.tp, t.entry, t0, t1, "rgba(8,153,129,0.08)");
      fillBand(t.entry, t.sl, t0, t1, "rgba(255,145,0,0.10)");
      void dim;
      markers.push({
        time: t0,
        position: bull ? "belowBar" : "aboveBar",
        color: isSel ? "#ffffff" : bull ? "#00e676" : "#ff5c6c",
        shape: bull ? "arrowUp" : "arrowDown",
        text: `#${state.trades.indexOf(t) + 1}`,
      });
    });
    markers.sort((a, b) => a.time - b.time);
    try { candleSeries.setMarkers(markers); } catch (e) {}
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
  }

  function selectTrade(i, focus) {
    const list = filteredTrades();
    if (!list.length) return;
    state.sel = Math.max(0, Math.min(i, list.length - 1));
    drawTrades();
    renderTable();
    renderDetail();
    if (focus) focusSelected();
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
  });

  async function boot() {
    try {
      const [cRes, tRes] = await Promise.all([
        fetch("/api/candles?symbol=XAUUSDm&timeframe=M15&bars=600"),
        fetch("/api/backtest/trades"),
      ]);
      const cData = await cRes.json();
      const tData = await tRes.json();
      state.candles = cData.candles || [];
      state.trades = (tData.trades || []).filter((t) => t.entry > 0);
      const st = tData.stats || {};
      document.getElementById("statTP").textContent = st.tp ?? "–";
      document.getElementById("statSL").textContent = st.losses ?? "–";
      document.getElementById("statExp").textContent = st.expired ?? "–";
      document.getElementById("statR").textContent =
        (st.total_R > 0 ? "+" : "") + (st.total_R ?? "–") + "R";
      candleSeries.setData(state.candles);
      chart.timeScale().fitContent();
      renderAll(false);
    } catch (err) {
      console.error("Backtest viewer failed to load:", err);
    }
  }

  chart.resize(container.clientWidth, container.clientHeight);
  boot();
});
