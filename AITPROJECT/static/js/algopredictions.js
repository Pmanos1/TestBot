document.addEventListener('DOMContentLoaded', () => {
  const predHighEl   = document.getElementById('pred-high');
  const predLowEl    = document.getElementById('pred-low');
  const perfEl       = document.getElementById('performance');
  const tradesEl     = document.getElementById('trades-taken');
  const winsEl       = document.getElementById('wins');
  const lossesEl     = document.getElementById('losses');
  const startBtn     = document.getElementById('start');
  const stopBtn      = document.getElementById('stop');
  let statusInterval = null;

  async function fetchStatus() {
    try {
      const res = await fetch('/algo/status');
      if (!res.ok) throw new Error(res.statusText);
      const {
        prediction_high,
        prediction_low,
        net_PnL,
        trades_taken,
        wins,
        losses
      } = await res.json();

      predHighEl.textContent = prediction_high != null
        ? prediction_high.toFixed(6)
        : '--';
      predLowEl.textContent  = prediction_low  != null
        ? prediction_low.toFixed(6)
        : '--';
      perfEl.textContent     = net_PnL != null
        ? net_PnL.toFixed(2)
        : '--';
      tradesEl.textContent   = Number.isInteger(trades_taken)
        ? trades_taken
        : '--';
      winsEl.textContent     = Number.isInteger(wins)
        ? wins
        : '--';
      lossesEl.textContent   = Number.isInteger(losses)
        ? losses
        : '--';
    } catch (err) {
      console.error('Error fetching algo status:', err);
    }
  }

  function startPolling() {
    // avoid double-starting
    if (statusInterval) return;
    fetchStatus();
    statusInterval = setInterval(fetchStatus, 5000);
    startBtn.disabled = true;
    stopBtn.disabled  = false;
  }

  function stopPolling() {
    clearInterval(statusInterval);
    statusInterval = null;
    startBtn.disabled = false;
    stopBtn.disabled  = true;
    predHighEl.textContent = '--';
    predLowEl.textContent  = '--';
    perfEl.textContent     = '--';
    tradesEl.textContent   = '--';
    winsEl.textContent     = '--';
    lossesEl.textContent   = '--';
  }

  startBtn.addEventListener('click', startPolling);
  stopBtn.addEventListener('click', stopPolling);

  // ** auto-start on load **
  startPolling();

  window.addEventListener('beforeunload', () => {
    clearInterval(statusInterval);
  });
});
