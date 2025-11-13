// ============================================================================
// === SUB-MODUL KANCELÁRIA: SPRÁVA NÁKLADOV (kompletný costs.js) ===
// ============================================================================

/* ---------- Global state ---------- */
let costsState = {
  year: new Date().getFullYear(),
  month: new Date().getMonth() + 1,
  data: {}
};

/* ---------- Small helpers ---------- */
function safeToFixed(v, d = 2) {
  const n = Number(v || 0);
  return isNaN(n) ? '0.00' : n.toFixed(d);
}
function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, m => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'
  })[m]);
}
function loadGoogleCharts() {
  return new Promise(resolve => {
    if (window.google && google.visualization) return resolve();
    if (!window.google || !google.charts) {
      const s = document.createElement('script');
      s.src = 'https://www.gstatic.com/charts/loader.js';
      s.onload = () => { google.charts.load('current', { packages: ['corechart'] }); google.charts.setOnLoadCallback(resolve); };
      document.head.appendChild(s);
    } else {
      google.charts.load('current', { packages: ['corechart'] });
      google.charts.setOnLoadCallback(resolve);
    }
  });
}

/* ---------- Local „pill“ styling (rounded tabs & buttons) ---------- */
function ensureCostsPillStyles(){
  if (document.getElementById('costs-pill-styles')) return;
  const s = document.createElement('style');
  s.id = 'costs-pill-styles';
  s.textContent = `
    /* hederové taby – zaoblené (ako v celom systéme) */
    #section-costs .b2b-tab-nav{ display:flex; gap:.5rem; flex-wrap:wrap; }
    #section-costs .b2b-tab-button{
      appearance:none;border:0;cursor:pointer;
      padding:.55rem .9rem;border-radius:9999px;
      background: var(--light); color: var(--dark);
      font-family: var(--font); font-weight:600; letter-spacing:.2px;
      box-shadow: 0 1px 2px rgba(0,0,0,.06) inset;
      transition: transform .12s ease, box-shadow .15s ease, background-color .15s ease, color .15s ease;
    }
    #section-costs .b2b-tab-button:hover{ filter: brightness(0.98); }
    #section-costs .b2b-tab-button:active{ transform: translateY(1px); }
    #section-costs .b2b-tab-button.active{
      color:#fff; background: linear-gradient(180deg, rgba(255,255,255,.12), rgba(0,0,0,.06)), var(--primary-color);
      box-shadow: var(--shadow);
    }
    /* všetky tlačidlá v module pekne zaoblené */
    #section-costs .btn,
    #section-costs .btn-success,
    #section-costs .btn-secondary,
    #section-costs .btn-primary,
    #section-costs .btn-outline { border-radius:9999px; }

    /* prehľadná tabuľka energií v dashboarde */
    #section-costs .energy-summary-table{
      width:100%; border-collapse:separate; border-spacing:0; overflow:hidden;
      box-shadow: var(--shadow); border-radius: var(--radius, 12px);
      background:#fff; margin-top:.5rem;
    }
    #section-costs .energy-summary-table thead th{
      text-align:left; font-weight:700; background:#f8fafc; border-bottom:1px solid #e5e7eb; padding:10px 12px;
    }
    #section-costs .energy-summary-table tbody td{
      padding:10px 12px; border-bottom:1px solid #f1f5f9; vertical-align:middle;
    }
    #section-costs .energy-summary-table tbody tr:last-child td{ border-bottom:0; }
    #section-costs .energy-summary-table .nowrap{ white-space:nowrap; }
    #section-costs .energy-summary-table .muted{ color:#6b7280; font-size:.9em; }

    /* karty na dashboarde (sumár výnosy/náklady/zisk) */
    #section-costs .analysis-grid{
      display:grid; grid-template-columns:repeat(auto-fit, minmax(220px,1fr)); gap:12px;
    }
    #section-costs .stat-card{
      background:#fff; border-radius:var(--radius, 12px); box-shadow:var(--shadow); padding:14px;
    }
    #section-costs .stat-card h5{ margin:0 0 8px 0; font-size:14px; color:#374151; }
    #section-costs .stat-card p{ margin:0; font-size:20px; font-weight:700; }
    #section-costs .stat-card p.gain{ color:#059669; }
    #section-costs .stat-card p.loss{ color:#b91c1c; }

    /* karty v „Energie“ (ponechané) */
    #section-costs .costs-grid{ display:grid; grid-template-columns:1fr; gap:14px; }
    #section-costs .card{ background:#fff; border-radius:var(--radius,12px); box-shadow:var(--shadow); }
    #section-costs .card-header{ padding:12px 14px; border-bottom:1px solid #eef2f7; }
    #section-costs .card-body{ padding:14px; }
    #section-costs .card-footer{ padding:10px 14px; border-top:1px solid #eef2f7; display:flex; justify-content:flex-end; gap:8px; }
    #section-costs .card-title{ margin:0; font-weight:700; }
    #section-costs .card-sub{ font-size:.9em; color:#6b7280; }

    /* form grid */
    #section-costs .form-grid{ display:grid; grid-template-columns:repeat(2, minmax(200px,1fr)); gap:10px; }
    #section-costs .field{ display:flex; flex-direction:column; gap:6px; }
    #section-costs .field--full{ grid-column:1/-1; }
    #section-costs .input{ border:1px solid #e5e7eb; border-radius:8px; padding:8px 10px; }
    #section-costs .banner{ border-radius:10px; padding:8px 10px; }
    #section-costs .banner--ok{ background:#ecfdf5; color:#065f46; }
    #section-costs .banner--warn{ background:#fffbeb; color:#92400e; }
    #section-costs .banner--err{ background:#fef2f2; color:#991b1b; }

    /* tabuľka sumár energií v spodnej karte (ponechané) */
    #section-costs .table-compact table{ width:100%; border-collapse:collapse; }
    #section-costs .table-compact th, #section-costs .table-compact td{ border:1px solid #e5e7eb; padding:6px 8px; }
    #section-costs .table-compact th{ background:#f9fafb; text-align:left; }
    #section-costs .table-compact .total{ background:#fff7f7; font-weight:700; }

    /* modálne formuláre prevádzkových nákladov */
    #section-costs .oc-form{ display:grid; grid-template-columns:repeat(2,minmax(200px,1fr)); gap:10px; }
    #section-costs .oc-field{ display:flex; flex-direction:column; gap:6px; }
    #section-costs .oc-field--full{ grid-column:1/-1; }
    #section-costs .oc-label{ font-weight:600; }
    #section-costs .oc-input, #section-costs .oc-textarea, #section-costs .oc-select{ border:1px solid #e5e7eb; border-radius:8px; padding:8px 10px; }
    #section-costs .oc-inline{ display:flex; gap:8px; align-items:center; }
    #section-costs .oc-input-lg{ font-size:15px; }
    #section-costs .oc-currency{ position:relative; }
    #section-costs .oc-suffix{ position:absolute; right:10px; top:50%; transform:translateY(-50%); color:#6b7280; }
    #section-costs .oc-help{ color:#6b7280; font-size:.9em; }
    #section-costs .btn-soft{ background:#f3f4f6; }
  `;
  document.head.appendChild(s);
}

/* ---------- Init ---------- */
function initializeCostsModule() {
  const container = document.getElementById('section-costs');
  if (!container) return;

  ensureCostsPillStyles();

  container.innerHTML = `
    <h3>Správa Nákladov</h3>
    <div style="display:flex; gap:1rem; align-items:flex-end; margin-bottom:1.5rem; flex-wrap:wrap;">
      <div class="form-group" style="margin-bottom:0;">
        <label for="costs-year-select" style="margin-top:0;">Rok:</label>
        <select id="costs-year-select"></select>
      </div>
      <div class="form-group" style="margin-bottom:0;">
        <label for="costs-month-select" style="margin-top:0;">Mesiac:</label>
        <select id="costs-month-select"></select>
      </div>
    </div>

    <div class="b2b-tab-nav" id="costs-main-nav">
      <button class="b2b-tab-button active" data-view="view-costs-dashboard">Dashboard</button>
      <button class="b2b-tab-button" data-view="view-costs-energy">Energie</button>
      <button class="b2b-tab-button" data-view="view-costs-hr">Ľudské zdroje</button>
      <button class="b2b-tab-button" data-view="view-costs-operational">Prevádzkové náklady</button>
    </div>

    <div id="costs-content" style="margin-top:1.5rem;"></div>
  `;

  // Populate selects
  const yearSelect = document.getElementById('costs-year-select');
  const monthSelect = document.getElementById('costs-month-select');
  const currentYear = new Date().getFullYear();
  for (let i = currentYear; i >= currentYear - 3; i--) yearSelect.add(new Option(i, i));
  const monthNames = ["Január","Február","Marec","Apríl","Máj","Jún","Júl","August","September","Október","November","December"];
  monthNames.forEach((name, idx) => monthSelect.add(new Option(name, idx + 1)));
  yearSelect.value = costsState.year;
  monthSelect.value = costsState.month;

  const loadData = () => {
    costsState.year = Number(yearSelect.value);
    costsState.month = Number(monthSelect.value);
    loadAndRenderCostsData();
  };
  yearSelect.onchange = loadData;
  monthSelect.onchange = loadData;

  document.querySelectorAll('#costs-main-nav .b2b-tab-button').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('#costs-main-nav .b2b-tab-button').forEach(b => b.classList.remove('active'));
      e.currentTarget.classList.add('active');
      renderCurrentCostsView();
    });
  });

  loadData();
}

/* ---------- Data fetch & view switch ---------- */
async function loadAndRenderCostsData() {
  const container = document.getElementById('costs-content');
  container.innerHTML = `<p>Načítavam dáta za ${costsState.month}/${costsState.year}...</p>`;
  try {
    costsState.data = await apiRequest(`/api/kancelaria/costs/getData?year=${costsState.year}&month=${costsState.month}`);
    renderCurrentCostsView();
  } catch (e) {
    container.innerHTML = `<p class="error">Chyba pri načítaní dát: ${escapeHtml(e.message)}</p>`;
  }
}

function renderCurrentCostsView() {
  const activeView = document.querySelector('#costs-main-nav .b2b-tab-button.active').dataset.view;
  switch (activeView) {
    case 'view-costs-dashboard':   renderCostsDashboard(); break;
    case 'view-costs-energy':      renderEnergyView(); break;
    case 'view-costs-hr':          renderHrView(); break;
    case 'view-costs-operational': renderOperationalCostsView(); break;
  }
}

/* ---------- Dashboard ---------- */
async function renderCostsDashboard() {
  const container = document.getElementById('costs-content');
  container.innerHTML = `<p>Načítavam dáta pre dashboard...</p>`;
  try {
    // sumarizačné dáta (výnosy/náklady/zisk + breakdown)
    const dash = await apiRequest(`/api/kancelaria/costs/getDashboardData?year=${costsState.year}&month=${costsState.month}`);
    // detailné dáta energií z hlavného state (kWh/m3 a jednotkové ceny)
    let energyFull = costsState.data?.energy || {};
    if (!energyFull || !energyFull.electricity) {
      const g = await apiRequest(`/api/kancelaria/costs/getData?year=${costsState.year}&month=${costsState.month}`);
      energyFull = g?.energy || {};
    }
    const el = energyFull.electricity || {};
    const gas = energyFull.gas || {};
    const water = energyFull.water || {};

    const elSumKwh   = Number(el.sum_kwh || 0);
    const elPrice    = Number(el.price_gross || el.price_net || 0);
    const elCost     = elSumKwh * elPrice;

    const gasKwh     = Number(gas.kwh || 0);
    const gasPrice   = Number(gas.price_gross || gas.price_net || 0);
    const gasCost    = gasKwh * gasPrice;

    const waterM3    = Number(water.diff_m3 || 0);
    const waterPrice = Number(water.price_gross || water.price_net || 0);
    const waterCost  = waterM3 * waterPrice;

    container.innerHTML = `
  <div class="analysis-grid">
    <div class="stat-card"><h5>Celkové Výnosy</h5><p class="${(dash.summary?.total_revenue||0)>=0?'gain':''}">${safeToFixed(dash.summary?.total_revenue)} €</p></div>
    <div class="stat-card"><h5>Celkové Náklady</h5><p class="loss">${safeToFixed(dash.summary?.total_costs)} €</p></div>
    <div class="stat-card"><h5>Čistý Zisk</h5><p class="${(dash.summary?.net_profit||0) >= 0 ? 'gain' : 'loss'}">${safeToFixed(dash.summary?.net_profit)} €</p></div>
  </div>

  <div style="display:flex; gap:12px; align-items:center; margin-top:10px;">
    <button id="btn-print-finance" class="btn btn-primary"><i class="fas fa-print"></i> Tlačiť finančný report</button>
  </div>

  <div class="grid-2" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px,1fr)); gap:16px; margin-top:16px;">
    <div>
      <h4>Štruktúra Nákladov</h4>
      <div id="costs-pie-chart" style="width:100%; height:360px;"></div>
    </div>
    <div>
      <h4>Štruktúra Výnosov</h4>
      <div id="revenue-pie-chart" style="width:100%; height:360px;"></div>
    </div>
  </div>
`;

document.getElementById('btn-print-finance').onclick = () => {
  window.open(`/report/costs/finance?year=${costsState.year}&month=${costsState.month}`,'_blank');
};

// Pie chart – náklady
await loadGoogleCharts();
const costData = new google.visualization.DataTable();
costData.addColumn('string', 'Kategória');
costData.addColumn('number', 'Suma');
let hasCost = false;
Object.entries(dash.breakdown || {}).forEach(([k, v]) => {
  const n = parseFloat(v || 0);
  if (n > 0) { costData.addRow([k, n]); hasCost = true; }
});
if (hasCost) {
  const optionsC = { title: 'Mesačné náklady podľa kategórií', pieHole: 0.4, legend: { position: 'right' } };
  new google.visualization.PieChart(document.getElementById('costs-pie-chart')).draw(costData, optionsC);
} else {
  document.getElementById('costs-pie-chart').innerHTML = "<p>Žiadne dáta na zobrazenie.</p>";
}

// Pie chart – výnosy (Rozrábka&Expedícia + Výroba)
const revData = new google.visualization.DataTable();
revData.addColumn('string', 'Oddelenie');
revData.addColumn('number', 'Suma');
let hasRev = false;
Object.entries(dash.revenue_breakdown || {}).forEach(([k, v]) => {
  const n = parseFloat(v || 0);
  if (n > 0) { revData.addRow([k, n]); hasRev = true; }
});
if (hasRev) {
  const optionsR = { title: 'Mesačné výnosy podľa oddelení', pieHole: 0.4, legend: { position: 'right' } };
  new google.visualization.PieChart(document.getElementById('revenue-pie-chart')).draw(revData, optionsR);
} else {
  document.getElementById('revenue-pie-chart').innerHTML = "<p>Žiadne dáta na zobrazenie.</p>";
}


  } catch (e) {
    container.innerHTML = `<p class="error">Chyba pri načítaní dát pre dashboard: ${escapeHtml(e.message)}</p>`;
  }
}

/* ---------- Energie (cards + History/Print) ---------- */
function renderEnergyView() {
  const container = document.getElementById('costs-content');
  const E = costsState.data?.energy || {};
  const el = E.electricity || {};
  const gas = E.gas || {};
  const water = E.water || {};
  const fmt = (v, d=2) => (v==null || isNaN(v)) ? '' : Number(v).toFixed(d);

  // banner pre kontrolu rozdielov
  const sumProdOther = Number(el?.prod?.diff_kwh || 0) + Number(el?.other?.diff_kwh || 0);
  const mainDiff     = Number(el?.main?.diff_kwh || 0);
  const diffAbs      = Math.abs(sumProdOther - mainDiff);
  let bannerClass = 'banner--ok', bannerText = 'Merania sedia.';
  if (diffAbs > 0.01 && diffAbs <= 5) { bannerClass='banner--warn'; bannerText=`Poznámka: rozdiel ${fmt(diffAbs,2)} kWh.`; }
  if (diffAbs > 5) { bannerClass='banner--err';  bannerText=`Upozornenie: výrazný rozdiel ${fmt(diffAbs,2)} kWh.`; }

  container.innerHTML = `
    <div class="costs-grid">
      <!-- ELEKTRINA -->
      <section class="card">
        <div class="card-header">
          <h4 class="card-title">Elektrina</h4>
          <div class="card-sub">Výroba & Ostatné + Hlavné meradlo</div>
        </div>
        <div class="card-footer" style="justify-content:flex-start">
          <button type="button" class="btn btn-outline" id="btn-energy-history" onclick="openEnergyHistoryModal()">História & Tlač</button>
        </div>
        <div class="card-body">
          <div class="banner ${bannerClass}">${bannerText}</div>
          <div class="form-grid">
            <div class="field"><label>Výroba – Zač. stav (kWh)</label>
              <input type="number" step="0.001" class="input" id="el_prod_start_kwh" value="${fmt(el?.prod?.start_kwh,3)}">
            </div>
            <div class="field"><label>Výroba – Konc. stav (kWh)</label>
              <input type="number" step="0.001" class="input" id="el_prod_end_kwh" value="${fmt(el?.prod?.end_kwh,3)}">
            </div>
            <div class="field"><label>Ostatné – Zač. stav (kWh)</label>
              <input type="number" step="0.001" class="input" id="el_other_start_kwh" value="${fmt(el?.other?.start_kwh,3)}">
            </div>
            <div class="field"><label>Ostatné – Konc. stav (kWh)</label>
              <input type="number" step="0.001" class="input" id="el_other_end_kwh" value="${fmt(el?.other?.end_kwh,3)}">
            </div>
            <div class="field"><label>Cena / kWh bez DPH</label>
              <input type="number" step="0.000001" class="input" id="el_price_per_kwh_net" value="${fmt(el?.price_net,6)}">
            </div>
            <div class="field"><label>Cena / kWh s DPH</label>
              <input type="number" step="0.000001" class="input" id="el_price_per_kwh_gross" value="${fmt(el?.price_gross,6)}">
            </div>
            <div class="field"><label>Hlavné meradlo – Zač. (kWh)</label>
              <input type="number" step="0.001" class="input" id="el_main_start_kwh" value="${fmt(el?.main?.start_kwh,3)}">
            </div>
            <div class="field"><label>Hlavné meradlo – Konc. (kWh)</label>
              <input type="number" step="0.001" class="input" id="el_main_end_kwh" value="${fmt(el?.main?.end_kwh,3)}">
            </div>
            <div class="field"><label>Hlavné meradlo – Cena bez DPH</label>
              <input type="number" step="0.000001" class="input" id="el_main_price_per_kwh_net" value="${fmt(el?.main?.price_net,6)}">
            </div>
            <div class="field"><label>Hlavné meradlo – Cena s DPH</label>
              <input type="number" step="0.000001" class="input" id="el_main_price_per_kwh_gross" value="${fmt(el?.main?.price_gross,6)}">
            </div>
            <div class="field field--full">
              <div class="kpi ${diffAbs > 5 ? 'kpi--err' : diffAbs > 0.01 ? 'kpi--warn' : 'kpi--ok'}">
                <div class="kpi-value" id="kpi-el-sum">${fmt(sumProdOther,3)}</div><div class="kpi-unit">kWh</div>
                <div class="note">Výroba + Ostatné</div>
                <div style="margin:0 .5rem">vs</div>
                <div class="kpi-value" id="kpi-el-main">${fmt(mainDiff,3)}</div><div class="kpi-unit">kWh</div>
                <div class="note">Hlavné meradlo</div>
              </div>
            </div>
          </div>
        </div>
        <div class="card-footer">
          <button type="button" class="btn btn-success" id="btn-save-electricity">Uložiť elektrinu</button>
        </div>
      </section>

      <!-- PLYN -->
      <section class="card">
        <div class="card-header">
          <h4 class="card-title">Plyn</h4>
          <div class="card-sub">Prepočet m³ → kWh / MWh</div>
        </div>
        <div class="card-body">
          <div class="form-grid">
            <div class="field"><label>Zač. stav (m³)</label>
              <input type="number" step="0.001" class="input" id="gas_start_m3" value="${fmt(gas?.start_m3,3)}">
            </div>
            <div class="field"><label>Konc. stav (m³)</label>
              <input type="number" step="0.001" class="input" id="gas_end_m3" value="${fmt(gas?.end_m3,3)}">
            </div>
            <div class="field"><label>Faktor (kWh / m³)</label>
              <input type="number" step="0.0001" class="input" id="gas_conv_kwh_per_m3" value="${fmt(gas?.conv_kwh_per_m3,4)}">
            </div>
            <div class="field"><label>Rozdiel (m³)</label>
              <input type="text" readonly class="input" id="gas_diff_m3_ro" value="${fmt(gas?.diff_m3,3)}">
            </div>
            <div class="field"><label>kWh</label>
              <input type="text" readonly class="input" id="gas_kwh_ro" value="${fmt(gas?.kwh,3)}">
            </div>
            <div class="field"><label>MWh</label>
              <input type="text" readonly class="input" id="gas_mwh_ro" value="${fmt(gas?.mwh,3)}">
            </div>
            <div class="field"><label>Cena / kWh bez DPH</label>
              <input type="number" step="0.000001" class="input" id="gas_price_per_kwh_net" value="${fmt(gas?.price_net,6)}">
            </div>
            <div class="field"><label>Cena / kWh s DPH</label>
              <input type="number" step="0.000001" class="input" id="gas_price_per_kwh_gross" value="${fmt(gas?.price_gross,6)}">
            </div>
          </div>
        </div>
        <div class="card-footer">
          <button type="button" class="btn btn-success" id="btn-save-gas">Uložiť plyn</button>
        </div>
      </section>

      <!-- VODA -->
      <section class="card">
        <div class="card-header">
          <h4 class="card-title">Voda</h4>
          <div class="card-sub">Mesačný rozdiel m³ a cena</div>
        </div>
        <div class="card-body">
          <div class="form-grid">
            <div class="field"><label>Zač. stav (m³)</label>
              <input type="number" step="0.001" class="input" id="water_start_m3" value="${fmt(water?.start_m3,3)}">
            </div>
            <div class="field"><label>Konc. stav (m³)</label>
              <input type="number" step="0.001" class="input" id="water_end_m3" value="${fmt(water?.end_m3,3)}">
            </div>
            <div class="field"><label>Rozdiel (m³)</label>
              <input type="text" readonly class="input" id="water_diff_ro" value="${fmt(water?.diff_m3,3)}">
            </div>
            <div class="field"><label>Cena / m³ bez DPH</label>
              <input type="number" step="0.000001" class="input" id="water_price_per_m3_net" value="${fmt(water?.price_net,6)}">
            </div>
            <div class="field"><label>Cena / m³ s DPH</label>
              <input type="number" step="0.000001" class="input" id="water_price_per_m3_gross" value="${fmt(water?.price_gross,6)}">
            </div>
          </div>
        </div>
        <div class="card-footer">
          <button type="button" class="btn btn-success" id="btn-save-water">Uložiť vodu</button>
        </div>
      </section>

      <!-- SUMÁR -->
      <section class="card">
        <div class="card-header">
          <h4 class="card-title">Sumár energií</h4>
          <div class="card-sub">Priemerné ceny a celková spotreba</div>
        </div>
        <div class="card-body table-compact">
          <table>
            <thead><tr><th>Kategória</th><th>Priemer (bez DPH)</th><th>Spotreba</th><th>Pozn.</th></tr></thead>
            <tbody>
              <tr><td><strong>Elektrina</strong></td><td>${fmt(E?.summary?.avg?.electricity_price_net,6)} €/kWh</td><td>${fmt(el?.sum_kwh||0,3)} kWh</td><td>Výroba+Ostatné</td></tr>
              <tr><td><strong>Plyn</strong></td><td>${fmt(E?.summary?.avg?.gas_price_net_kwh,6)} €/kWh</td><td>${fmt(gas?.kwh||0,3)} kWh ( ${fmt(gas?.diff_m3||0,3)} m³ )</td><td>Faktor ${fmt(gas?.conv_kwh_per_m3||0,4)}</td></tr>
              <tr><td><strong>Voda</strong></td><td>${fmt(E?.summary?.avg?.water_price_net_m3,6)} €/m³</td><td>${fmt(water?.diff_m3||0,3)} m³</td><td></td></tr>
              <tr class="total"><td><strong>SPOLU</strong></td><td>—</td><td>${fmt((E?.summary?.total_kwh)||0,3)} kWh / ${fmt(((gas?.diff_m3||0)+(water?.diff_m3||0)),3)} m³</td><td></td></tr>
            </tbody>
          </table>
        </div>
        <div class="card-footer" style="justify-content:flex-start">
          <button type="button" class="btn btn-secondary" id="btn-energy-history-2" onclick="openEnergyHistoryModal()">História & Tlač</button>
        </div>
      </section>
    </div>
  `;

  // Fallback delegácia (ak by CSP blokovala inline onclick)
  container.addEventListener('click', function(ev){
   const btn = ev.target.closest('#btn-energy-history, #btn-energy-history-2');
   if (btn && typeof window.openEnergyHistoryModal === 'function') window.openEnergyHistoryModal();
  });

  // Live recalc (banner + plyn & voda)
  const ids = ['el_prod_start_kwh','el_prod_end_kwh','el_other_start_kwh','el_other_end_kwh','el_main_start_kwh','el_main_end_kwh','gas_start_m3','gas_end_m3','gas_conv_kwh_per_m3','water_start_m3','water_end_m3'];
  ids.forEach(id=>{
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => {
      const ps = parseFloat(document.getElementById('el_prod_start_kwh').value||0);
      const pe = parseFloat(document.getElementById('el_prod_end_kwh').value||0);
      const os = parseFloat(document.getElementById('el_other_start_kwh').value||0);
      const oe = parseFloat(document.getElementById('el_other_end_kwh').value||0);
      const ms = parseFloat(document.getElementById('el_main_start_kwh').value||0);
      const me = parseFloat(document.getElementById('el_main_end_kwh').value||0);

      const sumPO = Math.max(0,(pe-ps)) + Math.max(0,(oe-os));
      const main  = Math.max(0,(me-ms));
      const dAbs  = Math.abs(sumPO - main);

      document.getElementById('kpi-el-sum').textContent  = safeToFixed(sumPO,3);
      document.getElementById('kpi-el-main').textContent = safeToFixed(main,3);

      const banner = container.querySelector('.banner');
      if (dAbs <= 0.01) { banner.className='banner banner--ok'; banner.textContent='Merania sedia.'; }
      else if (dAbs <= 5) { banner.className='banner banner--warn'; banner.textContent=`Poznámka: rozdiel ${safeToFixed(dAbs,2)} kWh.`; }
      else { banner.className='banner banner--err'; banner.textContent=`Upozornenie: výrazný rozdiel ${safeToFixed(dAbs,2)} kWh.`; }

      // plyn
      const gs = parseFloat(document.getElementById('gas_start_m3').value||0);
      const ge = parseFloat(document.getElementById('gas_end_m3').value||0);
      const gf = parseFloat(document.getElementById('gas_conv_kwh_per_m3').value||0);
      const gdiff = Math.max(0,(ge-gs));
      const gkwh  = gdiff * (gf||0);
      const mwh   = gkwh/1000;
      document.getElementById('gas_diff_m3_ro').value = safeToFixed(gdiff,3);
      document.getElementById('gas_kwh_ro').value    = safeToFixed(gkwh,3);
      document.getElementById('gas_mwh_ro').value    = safeToFixed(mwh,3);

      // voda
      const ws = parseFloat(document.getElementById('water_start_m3').value||0);
      const we = parseFloat(document.getElementById('water_end_m3').value||0);
      document.getElementById('water_diff_ro').value = safeToFixed(Math.max(0,(we-ws)),3);
    });
  });

  // Save handlers (sekčné endpointy)
  const valOrNull = (inp) => { if (!inp) return null; const v = inp.value; return (v===''||v==null)?null:v; };

  document.getElementById('btn-save-electricity').onclick = async () => {
    const body = {
      year: costsState.year, month: costsState.month,
      el_prod_start_kwh:  valOrNull(document.getElementById('el_prod_start_kwh')),
      el_prod_end_kwh:    valOrNull(document.getElementById('el_prod_end_kwh')),
      el_other_start_kwh: valOrNull(document.getElementById('el_other_start_kwh')),
      el_other_end_kwh:   valOrNull(document.getElementById('el_other_end_kwh')),
      el_price_per_kwh_net:   valOrNull(document.getElementById('el_price_per_kwh_net')),
      el_price_per_kwh_gross: valOrNull(document.getElementById('el_price_per_kwh_gross')),
      el_main_start_kwh:  valOrNull(document.getElementById('el_main_start_kwh')),
      el_main_end_kwh:    valOrNull(document.getElementById('el_main_end_kwh')),
      el_main_price_per_kwh_net:   valOrNull(document.getElementById('el_main_price_per_kwh_net')),
      el_main_price_per_kwh_gross: valOrNull(document.getElementById('el_main_price_per_kwh_gross'))
    };
    try { await apiRequest('/api/kancelaria/costs/saveElectricity',{method:'POST',body}); showStatus('Elektrina uložená.',false); await loadAndRenderCostsData(); } catch(e){}
  };

  document.getElementById('btn-save-gas').onclick = async () => {
    const body = {
      year: costsState.year, month: costsState.month,
      gas_start_m3: valOrNull(document.getElementById('gas_start_m3')),
      gas_end_m3:   valOrNull(document.getElementById('gas_end_m3')),
      gas_conv_kwh_per_m3: valOrNull(document.getElementById('gas_conv_kwh_per_m3')),
      gas_price_per_kwh_net:   valOrNull(document.getElementById('gas_price_per_kwh_net')),
      gas_price_per_kwh_gross: valOrNull(document.getElementById('gas_price_per_kwh_gross'))
    };
    try { await apiRequest('/api/kancelaria/costs/saveGas',{method:'POST',body}); showStatus('Plyn uložený.',false); await loadAndRenderCostsData(); } catch(e){}
  };

  document.getElementById('btn-save-water').onclick = async () => {
    const body = {
      year: costsState.year, month: costsState.month,
      water_start_m3: valOrNull(document.getElementById('water_start_m3')),
      water_end_m3:   valOrNull(document.getElementById('water_end_m3')),
      water_price_per_m3_net:   valOrNull(document.getElementById('water_price_per_m3_net')),
      water_price_per_m3_gross: valOrNull(document.getElementById('water_price_per_m3_gross'))
    };
    try { await apiRequest('/api/kancelaria/costs/saveWater',{method:'POST',body}); showStatus('Voda uložená.',false); await loadAndRenderCostsData(); } catch(e){}
  };
}

/* ---------- Energetická História & Tlač (modal) ---------- */
function openEnergyHistoryModal(){
  const today = new Date();
  const ym = (y,m)=>`${y}-${String(m).padStart(2,'0')}`;
  const yNow = today.getFullYear(), mNow = today.getMonth()+1;
  const defFrom = ym(mNow>1?yNow:yNow-1, mNow>1?mNow-1:12);

  const contentPromise = () => Promise.resolve({
    html: `
      <form id="energy-history-form">
        <div class="form-grid" style="grid-template-columns:repeat(12,1fr);gap:10px;">
          <div class="field"><label>Energia</label>
            <select class="input" name="energy">
              <option value="all">Všetky</option>
              <option value="electricity">Elektrina</option>
              <option value="gas">Plyn</option>
              <option value="water">Voda</option>
            </select>
          </div>
          <div class="field"><label>Rozsah</label>
            <select class="input" name="scope">
              <option value="month">Mesiac</option>
              <option value="year">Rok</option>
              <option value="range">Rozsah</option>
            </select>
          </div>
          <div class="field"><label>Rok</label><input class="input" type="number" name="year" min="2000" max="2100" value="${costsState.year}"></div>
          <div class="field"><label>Mesiac</label><input class="input" type="number" name="month" min="1" max="12" value="${costsState.month}"></div>
          <div class="field"><label>Od (YYYY-MM)</label><input class="input" type="month" name="from" value="${defFrom}"></div>
          <div class="field"><label>Do (YYYY-MM)</label><input class="input" type="month" name="to" value="${ym(yNow,mNow)}"></div>
        </div>

        <div class="btn-row" style="margin-top:10px;">
          <button type="button" class="btn btn-secondary" id="btn-view-history">Zobraziť históriu</button>
          <button type="button" class="btn btn-primary" id="btn-print-energy"><i class="fas fa-print"></i> Tlačiť</button>
        </div>

        <div id="energy-history-table" class="table-container" style="margin-top:10px; max-height:60vh;"></div>
      </form>
    `,
    onReady: () => {
      const form = document.getElementById('energy-history-form');
      const tbl  = document.getElementById('energy-history-table');

      const buildQuery = () => {
        const d = Object.fromEntries(new FormData(form).entries());
        const p = new URLSearchParams();
        p.set('energy', d.energy);
        if (d.scope === 'month') { p.set('year', d.year); p.set('month', d.month); }
        if (d.scope === 'year')  { p.set('year', d.year); }
        if (d.scope === 'range') { if (d.from) p.set('from', d.from); if (d.to) p.set('to', d.to); }
        return { d, p };
      };

      document.getElementById('btn-view-history').onclick = async () => {
        const { d, p } = buildQuery();
        try {
          const data = await apiRequest(`/api/kancelaria/costs/getEnergyHistory?${p.toString()}`);
          // render tabuľky
          let head = '<th>Obdobie</th>';
          if (data.energy==='all' || data.energy==='electricity') head += '<th>El. kWh</th><th>El. € s DPH</th>';
          if (data.energy==='all' || data.energy==='gas')         head += '<th>Plyn kWh</th><th>Plyn € s DPH</th>';
          if (data.energy==='all' || data.energy==='water')       head += '<th>Voda m³</th><th>Voda € s DPH</th>';

          let rows = '';
          (data.series||[]).forEach(it=>{
            rows += `<tr><td>${it.label}</td>`;
            if (data.energy==='all' || data.energy==='electricity') rows += `<td style="text-align:right">${safeToFixed(it.electricity?.sum_kwh,3)}</td><td style="text-align:right">${safeToFixed(it.electricity?.cost_gross,2)}</td>`;
            if (data.energy==='all' || data.energy==='gas')         rows += `<td style="text-align:right">${safeToFixed(it.gas?.kwh,3)}</td><td style="text-align:right">${safeToFixed(it.gas?.cost_gross,2)}</td>`;
            if (data.energy==='all' || data.energy==='water')       rows += `<td style="text-align:right">${safeToFixed(it.water?.diff_m3,3)}</td><td style="text-align:right">${safeToFixed(it.water?.cost_gross,2)}</td>`;
            rows += `</tr>`;
          });

          // riadok SPOLU
          let totalRow = '<td><strong>SPOLU</strong></td>';
          if (data.energy==='all' || data.energy==='electricity') totalRow += `<td style="text-align:right"><strong>${safeToFixed(data.totals?.electricity?.sum_kwh,3)}</strong></td><td style="text-align:right"><strong>${safeToFixed(data.totals?.electricity?.cost_gross,2)}</strong></td>`;
          if (data.energy==='all' || data.energy==='gas')         totalRow += `<td style="text-align:right"><strong>${safeToFixed(data.totals?.gas?.kwh,3)}</strong></td><td style="text-align:right"><strong>${safeToFixed(data.totals?.gas?.cost_gross,2)}</strong></td>`;
          if (data.energy==='all' || data.energy==='water')       totalRow += `<td style="text-align:right"><strong>${safeToFixed(data.totals?.water?.diff_m3,3)}</strong></td><td style="text-align:right"><strong>${safeToFixed(data.totals?.water?.cost_gross,2)}</strong></td>`;

          tbl.innerHTML = `<table>
            <thead><tr>${head}</tr></thead>
            <tbody>${rows}<tr class="total">${totalRow}</tr></tbody>
          </table>`;
        } catch (e) {
          tbl.innerHTML = `<p class="error">Chyba načítania histórie: ${escapeHtml(e.message)}</p>`;
        }
      };

      document.getElementById('btn-print-energy').onclick = () => {
        const { d, p } = buildQuery();
        p.set('scope', d.scope || 'month');
        window.open(`/report/costs/energy?${p.toString()}`, '_blank');
      };
    }
  });

  showModal('Energia – História & Tlač', contentPromise);
}
// Export, aby inline onclick aj delegácia fungovali
window.openEnergyHistoryModal = openEnergyHistoryModal;

/* ---------- Ľudské zdroje ---------- */
function renderHrView() {
  const container = document.getElementById('costs-content');
  const hr = costsState.data?.hr || {};
  container.innerHTML = `
    <div class="form-group"><label>Celková suma na výplatách (hrubá mzda)</label>
      <input type="number" step="0.01" id="hr-total_salaries" value="${hr.total_salaries ?? ''}">
    </div>
    <div class="form-group"><label>Celková suma odvodov (zaplatené firmou)</label>
      <input type="number" step="0.01" id="hr-total_levies" value="${hr.total_levies ?? ''}">
    </div>
    <div class="stat-card"><h5>Celkový náklad na ĽZ</h5>
      <p id="hr-total-cost">${safeToFixed((hr.total_salaries || 0) + (hr.total_levies || 0))} €</p>
    </div>
    <button class="btn btn-success" style="width:100%; margin-top:10px;" onclick="saveHrData()">Uložiť dáta</button>
  `;

  const recalc = () => {
    const s = parseFloat(document.getElementById('hr-total_salaries').value) || 0;
    const l = parseFloat(document.getElementById('hr-total_levies').value) || 0;
    document.getElementById('hr-total-cost').textContent = `${safeToFixed(s + l)} €`;
  };
  document.getElementById('hr-total_salaries').oninput =
  document.getElementById('hr-total_levies').oninput = recalc;
}

async function saveHrData() {
  const data = {
    year: costsState.year,
    month: costsState.month,
    total_salaries: document.getElementById('hr-total_salaries').value,
    total_levies:   document.getElementById('hr-total_levies').value
  };
  try {
    await apiRequest('/api/kancelaria/costs/saveHr', { method: 'POST', body: data });
    showStatus('Dáta o ĽZ boli uložené.', false);
    await loadAndRenderCostsData();
  } catch (e) {}
}
window.saveHrData = saveHrData;

/* ---------- Prevádzkové náklady ---------- */
function renderOperationalCostsView() {
  const container = document.getElementById('costs-content');
  const operational = costsState.data?.operational || {};
  const items = operational.items || [];
  let rowsHtml = items.map(item => `
    <tr>
      <td>${new Date(item.entry_date).toLocaleDateString('sk-SK')}</td>
      <td>${escapeHtml(item.category_name)}</td>
      <td>${escapeHtml(item.name)}</td>
      <td>${safeToFixed(item.amount_net)} €</td>
      <td>${item.is_recurring ? 'Áno' : 'Nie'}</td>
      <td>
        <button class="btn btn-warning btn-sm" style="margin:0;" onclick='openOperationalCostModal(${JSON.stringify(item)})'><i class="fas fa-edit"></i></button>
        <button class="btn btn-danger btn-sm" style="margin:0 0 0 6px;" onclick="handleDeleteOperationalCost(${item.id})"><i class="fas fa-trash"></i></button>
      </td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div style="display:flex; justify-content:flex-end; align-items:center; gap:1rem; margin-bottom:1rem;">
      <button id="manage-categories-btn" class="btn btn-secondary"><i class="fas fa-tags"></i> Spravovať kategórie</button>
      <button id="add-operational-cost-btn" class="btn btn-success"><i class="fas fa-plus"></i> Nový náklad</button>
    </div>
    <div class="table-container"><table id="operational-costs-table">
      <thead><tr><th>Dátum</th><th>Kategória</th><th>Názov/Popis</th><th>Suma (bez DPH)</th><th>Opakujúci sa</th><th>Akcie</th></tr></thead>
      <tbody>${rowsHtml || '<tr><td colspan="6" style="text-align:center;">Žiadne záznamy pre tento mesiac.</td></tr>'}</tbody>
    </table></div>
  `;
  document.getElementById('add-operational-cost-btn').onclick = () => openOperationalCostModal(null);
  document.getElementById('manage-categories-btn').onclick = showManageCategoriesModal;
}

async function openOperationalCostModal(item = null) {
  // načítaj kategórie, ak nemáme
  if (!costsState?.data?.operational?.categories || !costsState.data.operational.categories.length) {
    const data = await apiRequest(`/api/kancelaria/costs/getData?year=${costsState.year}&month=${costsState.month}`);
    costsState.data = data;
  }
  const cats = costsState.data.operational.categories || [];
  const catOptions = cats.map(c => `<option value="${c.id}" ${item && String(item.category_id)===String(c.id)?'selected':''}>${escapeHtml(c.name)}</option>`).join('');
  const toISO = d => d.toISOString().slice(0,10);
  const defDate = item?.entry_date ? String(item.entry_date).slice(0,10) : toISO(new Date());

  const contentPromise = () => Promise.resolve({
    html: `
      <form id="op-cost-form" class="oc-form">
        <input type="hidden" name="id" value="${item?.id || ''}">
        <div class="oc-field">
          <label class="oc-label">Dátum</label>
          <input type="date" class="oc-input" name="entry_date" value="${defDate}" required>
        </div>

        <div class="oc-field">
          <label class="oc-label">Kategória</label>
          <div class="oc-inline">
            <select class="oc-select" name="category_id" id="op-category" required>
              <option value="">— vyber kategóriu —</option>
              ${catOptions}
            </select>
            <button type="button" class="btn btn-soft btn-sm" id="op-add-cat-btn" title="Pridať kategóriu">+ Kategória</button>
          </div>
          <div id="op-add-cat-row" class="oc-inline" style="margin-top:6px; display:none;">
            <input type="text" class="oc-input" id="op-new-cat-name" placeholder="Názov kategórie">
            <button type="button" class="btn btn-secondary btn-sm" id="op-save-cat">Uložiť</button>
            <button type="button" class="btn btn-soft btn-sm" id="op-cancel-cat">Zrušiť</button>
          </div>
        </div>

        <div class="oc-field oc-field--full">
          <label class="oc-label">Názov nákladu</label>
          <input type="text" class="oc-input oc-input-lg" name="name" placeholder="napr. Mobilný operátor Orange" value="${escapeHtml(item?.name || '')}" required>
          <div class="oc-help">Napíš stručne, aby sa v prehľade dalo rýchlo filtrovať.</div>
        </div>

        <div class="oc-field">
          <label class="oc-label">Suma (bez DPH)</label>
          <div class="oc-currency">
            <input type="number" step="0.01" inputmode="decimal" class="oc-input oc-input-lg" name="amount_net" id="op-amount" value="${item?.amount_net != null ? String(item.amount_net) : ''}" required>
            <span class="oc-suffix">€</span>
          </div>
        </div>

        <div class="oc-field">
          <label class="oc-label">Pravidelné</label>
          <div class="oc-inline">
            <input type="checkbox" name="is_recurring" id="op-recurring" ${item?.is_recurring ? 'checked' : ''} style="width:auto;">
            <label for="op-recurring" class="oc-help" style="margin:0;">Ak sa opakuje mesačne.</label>
          </div>
        </div>

        <div class="oc-field oc-field--full">
          <label class="oc-label">Popis (nepovinné)</label>
          <textarea class="oc-textarea" name="description" rows="3" placeholder="Poznámka, číslo zmluvy…">${escapeHtml(item?.description || '')}</textarea>
        </div>

        <div class="oc-field oc-field--full oc-row">
          <button type="button" class="btn btn-secondary" id="op-cancel">Zavrieť</button>
          <button type="submit" class="btn btn-primary">${item ? 'Uložiť zmeny' : 'Pridať náklad'}</button>
        </div>
      </form>
    `,
    onReady: () => {
      const modal = document.getElementById('modal-container');
      const form  = document.getElementById('op-cost-form');
      const catBtn = document.getElementById('op-add-cat-btn');
      const catRow = document.getElementById('op-add-cat-row');
      const saveCat= document.getElementById('op-save-cat');
      const cancelCat = document.getElementById('op-cancel-cat');
      const catSel = document.getElementById('op-category');

      form.querySelector('#op-amount')?.focus();
      catBtn.onclick = () => { catRow.style.display = 'flex'; };
      cancelCat.onclick = () => { catRow.style.display = 'none'; };

      saveCat.onclick = async () => {
        const name = (document.getElementById('op-new-cat-name').value || '').trim();
        if (!name) { showStatus('Zadaj názov kategórie.', true); return; }
        try {
          const res = await apiRequest('/api/kancelaria/costs/saveCategory', { method:'POST', body:{ name } });
          showStatus(res.message || 'Kategória pridaná.', false);
          const data = await apiRequest(`/api/kancelaria/costs/getData?year=${costsState.year}&month=${costsState.month}`);
          costsState.data = data;
          const options = (data.operational.categories||[]).map(c=>`<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
          catSel.innerHTML = `<option value="">— vyber kategóriu —</option>${options}`;
          catSel.value = (data.operational.categories||[]).find(c=>c.name===name)?.id || '';
          catRow.style.display = 'none';
        } catch(e){}
      };

      document.getElementById('op-cancel').onclick = () => { if (modal) modal.style.display='none'; };

      form.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        const body = Object.fromEntries(fd.entries());
        body.is_recurring = form.elements.is_recurring.checked;
        if (!body.category_id) { showStatus('Vyber kategóriu.', true); return; }
        if (!body.name) { showStatus('Zadaj názov nákladu.', true); return; }
        if (!body.amount_net) { showStatus('Zadaj sumu (bez DPH).', true); return; }
        try {
          await apiRequest('/api/kancelaria/costs/saveOperational', { method:'POST', body });
          showStatus('Náklad uložený.', false);
          if (modal) modal.style.display = 'none';
          await loadAndRenderCostsData();
        } catch(e){}
      };
    }
  });

  showModal(item ? 'Upraviť prevádzkový náklad' : 'Nový prevádzkový náklad', contentPromise);
}
window.openOperationalCostModal = openOperationalCostModal;

async function handleDeleteOperationalCost(itemId) {
  showConfirmationModal({
    title: 'Potvrdenie vymazania',
    message: 'Naozaj chcete vymazať tento náklad?',
    warning: 'Táto akcia je nezvratná!',
    onConfirm: async () => {
      try {
        await apiRequest('/api/kancelaria/costs/deleteOperational', { method:'POST', body:{ id:itemId } });
        await loadAndRenderCostsData();
      } catch (e) {}
    }
  });
}
window.handleDeleteOperationalCost = handleDeleteOperationalCost;

function showManageCategoriesModal() {
  const cats = costsState.data?.operational?.categories || [];
  const list = cats.map(c => `<li>${escapeHtml(c.name)}</li>`).join('');
  const contentPromise = () => Promise.resolve({
    html: `
      <h4>Existujúce kategórie</h4>
      <ul>${list || '<li>Žiadne kategórie.</li>'}</ul>
      <hr>
      <h4>Pridať novú kategóriu</h4>
      <form id="add-category-form">
        <div class="form-group"><label for="new-category-name">Názov novej kategórie</label>
          <input type="text" id="new-category-name" required></div>
        <button type="submit" class="btn btn-success" style="width:100%;">Uložiť kategóriu</button>
      </form>
    `,
    onReady: () => {
      document.getElementById('add-category-form').onsubmit = async (e) => {
        e.preventDefault();
        const name = document.getElementById('new-category-name').value.trim();
        if (!name) { showStatus('Zadaj názov kategórie.', true); return; }
        try {
          await apiRequest('/api/kancelaria/costs/saveCategory', { method:'POST', body:{ name } });
          document.getElementById('modal-container').style.display = 'none';
          await loadAndRenderCostsData();
        } catch (err) {}
      };
    }
  });
  showModal('Správa kategórií nákladov', contentPromise);
}
window.showManageCategoriesModal = showManageCategoriesModal;

/* ---------- Exports for external callers ---------- */
window.initializeCostsModule = initializeCostsModule;
