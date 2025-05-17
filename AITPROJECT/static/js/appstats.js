// 1) Grab the new stat elements
const statPair  = document.getElementById('stat-pair');
const statLast  = document.getElementById('stat-last');
const statPrice = document.getElementById('stat-price');
const statPos   = document.getElementById('stat-pos');
const statAlgo  = document.getElementById('stat-algo');

// 2) Initialize pair & algo status
statPair.textContent = pairSel.value;
statAlgo.textContent = '❌';

// 3) Update pair if user changes it
pairSel.addEventListener('change', () => {
  statPair.textContent = pairSel.value;
});

// 4) In openWS() → mark algo active
ws.onopen = () => {
  running = true;
  statAlgo.textContent = '✅';
  // … your existing onopen code …
};

// 5) In closeWS() → mark algo stopped & reset
function closeWS() {
  // … your existing close code …
  statAlgo.textContent  = '❌';
  statLast.textContent  = '--';
  statPrice.textContent = '--';
}

// 6) In ws.onmessage handler, when you get a real tick:
ws.onmessage = ev => {
  if (!ev.data.startsWith('{')) {
    // real tick
    const [ts, p]     = ev.data.split(',');
    const unixSec     = Math.floor(Number(ts) / 1e9);
    statLast.textContent  = new Date(unixSec * 1000).toLocaleTimeString();
    statPrice.textContent = parseFloat(p).toFixed(6);
    // … your existing tick logic …
  }
  else {
    // dummy trade JSON
    const { trade } = JSON.parse(ev.data);
    // toggle in‑position on buy/sell
    statPos.textContent = trade.type === 'buy' ? '✅' : '❌';
    // … your existing trade logic …
  }
};
