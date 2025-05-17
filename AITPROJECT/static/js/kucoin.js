// static/js/kucoin.js

document.addEventListener('DOMContentLoaded', () => {
  (async () => {
    // 1) Health-check badge
    async function loadKucoinInfo() {
      const badge = document.getElementById('kc-health');
      try {
        const res = await fetch('/kc/health');
        const j   = await res.json();
        const status = (j?.status || 'unknown').toLowerCase();

        badge.textContent = status;
        badge.className   = 'badge';

        switch (status) {
          case 'ok':
          case 'healthy':
            badge.classList.add('bg-success');
            break;
          case 'degraded':
            badge.classList.add('bg-warning');
            break;
          case 'down':
            badge.classList.add('bg-danger');
            break;
          default:
            badge.classList.add('bg-secondary');
        }
      } catch (e) {
        console.error('Health check failed', e);
        badge.textContent = 'error';
        badge.className   = 'badge bg-danger';
      }
    }

      async function loadOpenPosition() {
        const badge = document.getElementById('kc-active-orders');
        try {
          const res = await fetch('/kc/orders/open_position');
          const { has_open_position: isOpen } = await res.json();  // <-- use has_open_position
          badge.textContent = isOpen ? 'Yes' : 'No';
          badge.className   = 'badge ' + (isOpen ? 'bg-primary' : 'bg-success');
        } catch (e) {
          console.error('Open position check failed', e);
          badge.textContent = 'error';
          badge.className   = 'badge bg-danger';
        }
      }

    // 3) Balances dropdown
    async function loadBalances() {
      const listEl = document.getElementById('kc-balances-list');
      listEl.innerHTML = ''; // clear previous

      try {
        const res = await fetch('/kc/balances');
        const j   = await res.json();
        const bal = j.balances || [];

        if (bal.length === 0) {
          listEl.innerHTML = '<a class="dropdown-item text-muted" href="#">none</a>';
        } else {
          bal.forEach(b => {
            const a = document.createElement('a');
            a.className   = 'dropdown-item';
            a.href        = '#';
            a.textContent = `${b.currency}: ${b.balance}`;
            listEl.appendChild(a);
          });
        }
      } catch (e) {
        console.error('Balances fetch failed', e);
        listEl.innerHTML = '<a class="dropdown-item text-danger" href="#">error</a>';
      }
    }

    // initial load
    await loadKucoinInfo();
    await loadOpenPosition();
    await loadBalances();

    // periodic refresh
    setInterval(loadKucoinInfo,     60_000);
    setInterval(loadOpenPosition,   5_000);
    setInterval(loadBalances,       60_000);
  })();
});
