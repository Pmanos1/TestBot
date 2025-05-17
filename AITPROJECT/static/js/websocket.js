// static/js/websocket.js

document.addEventListener('DOMContentLoaded', () => {
  // ——————————————————————————————————————————
  // 0) Sanity check for the chart library
  // ——————————————————————————————————————————
  if (!window.LightweightCharts?.createChart) {
    console.error("⚠️ LightweightCharts not loaded");
    document.getElementById("chart").innerHTML =
      '<div class="alert alert-danger">Chart library failed to load. Please refresh the page.</div>';
    return;
  }

  // ——————————————————————————————————————————
  // 1) Grab DOM elements
  // ——————————————————————————————————————————
  const priceEl   = document.getElementById("price"),
        lastEl    = document.getElementById("last"),
        pairSel   = document.getElementById("pair"),
        startBtn  = document.getElementById("start"),
        stopBtn   = document.getElementById("stop"),
        closeBtn  = document.getElementById("close");

  let ws             = null,
      running        = false,
      closeInterval  = null,
      firstTickTime  = null;     // track when the first tick arrives

  // ——————————————————————————————————————————
  // 2) Helper to POST to FastAPI
  // ——————————————————————————————————————————
  async function post(path) {
    const res = await fetch(path, { method: 'POST' });
    if (!res.ok) throw await res.json();
    return res.json();
  }

  // ——————————————————————————————————————————
  // 3) Open the price-feed WebSocket
  // ——————————————————————————————————————————
  function openFeedWS() {
    if (running) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/${pairSel.value}`);

    ws.onopen = () => {
      running           = true;
      pairSel.disabled  = true;
      startBtn.disabled = true;
      stopBtn.disabled  = false;
      closeBtn.disabled = false;
      priceEl.textContent = "--";
      lastEl.textContent  = "--";
      lineSeries.setData([]);
      firstTickTime = null;     // reset for this session
    };

    ws.onerror = e => console.error("WS error", e);

    ws.onmessage = ev => {
      const [ts, p] = ev.data.split(",");
      if (!ts || !p) return;
      // compute localTime in seconds (align with chart timeScale)
      const localTime = Number(ts) / 1e9 - (new Date().getTimezoneOffset() * 60);
      // record first tick
      if (!firstTickTime) {
        firstTickTime = localTime;
      }
      lineSeries.update({ time: localTime, value: +p });
      priceEl.textContent = p;
      lastEl.textContent  = new Date(Number(ts) / 1e6).toLocaleTimeString();
    };
  }

  // ——————————————————————————————————————————
  // 4) Close the WebSocket and reset UI
  // ——————————————————————————————————————————
  function closeFeedWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
      ws.close(1000, "Client stop requested");
    }
    ws = null;
    running           = false;
    pairSel.disabled  = false;
    startBtn.disabled = false;
    stopBtn.disabled  = true;
    closeBtn.disabled = true;
    priceEl.textContent = "--";
    lastEl.textContent  = "--";
    lineSeries.setData([]);
    firstTickTime = null;
  }

  // ——————————————————————————————————————————
  // 5) Build your chart
  // ——————————————————————————————————————————
  const chart      = LightweightCharts.createChart(document.getElementById("chart"), {
    layout:          { backgroundColor:'#fff', textColor:'#333' },
    grid:            { vertLines:{ color:'#f0f0f0' }, horzLines:{ color:'#f0f0f0' } },
    rightPriceScale: { scaleMargins:{ top:0.1, bottom:0.1 } },
    timeScale:       { timeVisible:true, secondsVisible:true }
  });
  const lineSeries = chart.addLineSeries({ lineWidth: 2 });

  // ——————————————————————————————————————————
  // 5a) Fetch historical trades and plot markers, then refresh periodically
  // ——————————————————————————————————————————
  const tzOffsetSec = new Date().getTimezoneOffset() * 60;
  async function plotTradeMarkers() {
    if (!firstTickTime) {
      // no ticks yet, skip plotting
      return;
    }
    try {
      const res    = await fetch('/algo/trades');
      let trades   = await res.json();
      // only include trades at or after first tick
      trades = trades.filter(t => (t.time - tzOffsetSec) >= firstTickTime);
      const markers = trades.map(t => ({
        time:     t.time - tzOffsetSec,
        position: t.type === 'buy' ? 'belowBar' : 'aboveBar',
        color:    t.type === 'buy' ? 'green'     : 'red',
        shape:    t.type === 'buy' ? 'arrowUp'   : 'arrowDown',
        text:     t.type === 'buy' ? 'BUY'       : 'SELL',
      }));
      lineSeries.setMarkers(markers);
    } catch (err) {
      console.error("Could not load trade markers", err);
    }
  }
  plotTradeMarkers();
  setInterval(plotTradeMarkers, 5000);

  // ——————————————————————————————————————————
  // 6) Sync UI to backend state on load (and on-demand)
  // ——————————————————————————————————————————
  async function syncUI() {
    let feedRuns = false, algoRuns = false;
    try {
      const res1 = await fetch(`/feed/status/${pairSel.value}`);
      feedRuns = (await res1.json()).running;
    } catch (_) {}
    try {
      const res2 = await fetch(`/algo/status`);
      algoRuns = (await res2.json()).running;
    } catch (_) {}

    // Reconnect feed if needed
    if (feedRuns) openFeedWS();
    else           closeFeedWS();

    // Button states
    startBtn.disabled = feedRuns || algoRuns;
    stopBtn.disabled  = !(feedRuns || algoRuns);
    closeBtn.disabled = !algoRuns;
  }

  // Call it once on load
  syncUI();

  // ——————————————————————————————————————————
  // 7) Wire up START
  // ——————————————————————————————————————————
  startBtn.addEventListener('click', async () => {
    try {
      await post(`/start/${pairSel.value}`);
      openFeedWS();
    } catch (feedErr) {
      console.error("Feed start failed", feedErr);
      return;
    }
    try {
      await post('/algo/start');
      console.log("✅ Algorithm started");
    } catch (algoErr) {
      console.error("Algo start failed", algoErr);
    }
    syncUI();
  });

  // ——————————————————————————————————————————
  // 8) Wire up STOP
  // ——————————————————————————————————————————
  stopBtn.addEventListener('click', async () => {
    closeFeedWS();
    try {
      await post(`/stop/${pairSel.value}`);
      console.log(`🛑 Feed stopped for ${pairSel.value}`);
    } catch (feedErr) {
      console.error("Feed stop failed", feedErr);
    }
    try {
      await post('/algo/stop');
      console.log("🛑 Algorithm stopping");
    } catch (algoErr) {
      console.error("Algo stop failed", algoErr);
    }
    syncUI();
  });

  // ——————————————————————————————————————————
  // 9) Wire up CLOSE (sell-only then shutdown)
  // ——————————————————————————————————————————
  closeBtn.addEventListener('click', async () => {
    try {
      await post('/algo/close');
      closeBtn.disabled   = true;
      closeBtn.textContent = 'Closing…';
      closeInterval = setInterval(async () => {
        try {
          const res = await fetch('/kc/orders/active_status');
          const { has_active_orders } = await res.json();
          if (!has_active_orders) {
            clearInterval(closeInterval);
            closeFeedWS();
            closeBtn.textContent = 'Closed';
            syncUI();
          }
        } catch (e) {
          console.error('Error checking active status during close:', e);
        }
      }, 5000);
    } catch (err) {
      console.error('Close request failed', err);
    }
  });

  // ——————————————————————————————————————————
  // 10) Cleanup on page unload
  // ——————————————————————————————————————————
  window.addEventListener('beforeunload', () => {
    closeFeedWS();
    if (closeInterval) clearInterval(closeInterval);
  });
});
