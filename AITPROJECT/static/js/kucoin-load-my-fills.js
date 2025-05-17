// static/js/kucoin-load-data.js

console.log("🔔 kucoin-load-data.js loaded");

const DT_OPTS = {
  responsive: true,
  pageLength: 25,
  order: [[0, 'desc']],
  dom: 'Bfrtip',
  buttons: ['copy', 'csv', 'excel'],
  language: { emptyTable: "No data available" }
};

let dtFills, dtOrders;

// ─── Fetch fills and update the Fills table ─────────────────────────────────
async function updateFills(limit = 20) {
  try {
    const res = await fetch(`/kc/my-fills?limit=${limit}`);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const { fills } = await res.json();

    const rows = fills.map(f => {
      const dtStr    = new Date(f.createdAt).toLocaleString();
      const avgPrice = f.dealSize > 0
        ? (parseFloat(f.dealFunds) / parseFloat(f.dealSize)).toFixed(6)
        : '0.000000';
      const pnl      = (f.side==='sell' ? '+' : '-') + parseFloat(f.dealFunds).toFixed(6);
      return [
        dtStr,
        f.symbol,
        f.side.toUpperCase(),
        f.orderType.toUpperCase(),
        f.dealSize,
        avgPrice,
        `${parseFloat(f.fee).toFixed(6)} ${f.feeCurrency}`
      ];
    });

    dtFills.clear();
    dtFills.rows.add(rows);
    dtFills.draw();

  } catch (err) {
    console.error("❌ updateFills error:", err);
  }
}

// ─── Fetch orders and update the Orders table ───────────────────────────────
async function updateOrders(limit = 20) {
  try {
    const res = await fetch(`/kc/orders?limit=${limit}`);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const { orders } = await res.json();

    const rows = orders.map(o => {
      const dtStr  = new Date(o.createdAt).toLocaleString();
      const status = o.isActive ? 'ACTIVE' : 'DONE';
      return [
        dtStr,
        o.symbol,
        o.side.toUpperCase(),
        o.type,
        parseFloat(o.price).toFixed(6),
        o.size,
        status
      ];
    });

    dtOrders.clear();
    dtOrders.rows.add(rows);
    dtOrders.draw();

  } catch (err) {
    console.error("❌ updateOrders error:", err);
  }
}

// ─── Initialize on DOM ready ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // build both tables
  dtFills = $('#trade-data-table').DataTable(DT_OPTS);
  dtOrders= $('#orders-table').DataTable(DT_OPTS);

  // initial load
  updateFills(20);
  updateOrders(20);

  // poll every 60s
  setInterval(() => {
    updateFills(20);
    updateOrders(20);
  }, 60_000);
});
