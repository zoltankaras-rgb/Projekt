// =================================================================
// === SUB-MODUL KANCELÁRIA: PLÁNOVANIE ===
// =================================================================

function initializePlanningModule() {
  const container = document.getElementById('section-planning');
  if (!container) return;

  container.innerHTML = `
    <h3>Plánovanie a Reporty</h3>
    <div class="btn-grid">
      <button id="show-plan-btn" class="btn-primary"><i class="fas fa-tasks"></i> Plán Výroby</button>
      <button id="show-purchase-btn" class="btn-info"><i class="fas fa-shopping-cart"></i> Návrh Nákupu</button>
      <button id="show-prod-stats-btn" class="btn-secondary"><i class="fas fa-chart-bar"></i> Prehľad Výroby</button>
      <button id="show-reception-report-btn" class="btn-primary"><i class="fas fa-clipboard-list"></i> Príjem z výroby</button>
      <button id="show-print-reports-btn" class="btn-warning"><i class="fas fa-print"></i> Tlač Reportov</button>
    </div>

    <!-- NOVÉ: inline kontajner pre plánovač -->
    <div id="planner-inline-root" class="card" style="margin-top:1rem; display:none;"></div>
  `;

  document.getElementById('show-reception-report-btn').onclick =
    () => showModal('Príjem z výroby (podľa dátumu)', createReceptionReportContent);

  // NAMIETO modalu vyrenderujeme plánovač inline
  document.getElementById('show-plan-btn').onclick = () => {
    document.getElementById('planner-inline-root').style.display = 'block';
    renderProductionPlanInline();
    // scroll k plánovaču
    document.getElementById('planner-inline-root').scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  // Ostatné nechávame v modale (bez zmien)
  document.getElementById('show-purchase-btn').onclick =
    () => showModal('Návrh Nákupu', createPurchaseSuggestionsContent);
  document.getElementById('show-prod-stats-btn').onclick =
    () => showModal('Prehľad Výroby', createProductionStatsContent);
  document.getElementById('show-print-reports-btn').onclick =
    () => showModal('Tlač Reportov', createPrintReportsContent);
}

async function createProductionPlanContent() {
    const planDataGrouped = await apiRequest('/api/kancelaria/getProductionPlan');
    let html;

    if (!planDataGrouped || Object.keys(planDataGrouped).length === 0) {
        html = "<p>Nie je potrebné nič vyrábať na základe minimálnych zásob a objednávok.</p>";
    } else {
        const days = ['Nenaplánované', 'Pondelok', 'Utorok', 'Streda', 'Štvrtok', 'Piatok'];
        const dayOptions = days.map(d => `<option value="${d}">${d}</option>`).join('');

        let tableBodyHtml = '';
        for (const [category, items] of Object.entries(planDataGrouped)) {
            tableBodyHtml += `<tbody class="production-group-tbody">
                <tr class="category-header-row" style="background-color: #f3f4f6; font-weight: bold;"><td colspan="7">${escapeHtml(category)}</td></tr>`;
            items.forEach(item => {
                tableBodyHtml += `
                    <tr data-product-name="${escapeHtml(item.nazov_vyrobku)}">
                        <td>${escapeHtml(item.nazov_vyrobku)}</td>
                        <td style="text-align: right;">${safeToFixed(item.celkova_potreba)} kg</td>
                        <td style="text-align: right;">${safeToFixed(item.aktualny_sklad)} kg</td>
                        <td><input type="number" class="planned-qty-input" value="${item.navrhovana_vyroba}" step="10" style="width: 80px; text-align: right; padding: 4px;"></td>
                        <td><select class="day-select" style="padding: 4px;">${dayOptions}</select></td>
                        <td style="text-align: center;"><input type="checkbox" class="priority-checkbox" style="width: 20px; height: 20px;"></td>
                        <td style="text-align: center;"><button class="btn-danger" style="padding:2px 8px; margin:0;" onclick="this.closest('tr').remove()">×</button></td>
                    </tr>`;
            });
            tableBodyHtml += `</tbody>`;
        }

        html = `
            <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                <p>Naplánujte výrobu priradením dňa a priority ku každej položke.</p>
                <button id="planner-settings-btn" class="btn-secondary" disabled title="Bude dostupné v ďalšom kroku"><i class="fas fa-cog"></i> Nastaviť predvolené dni</button>
            </div>
            <div class="table-container" style="max-height: 65vh;">
                <table>
                    <thead style="position: sticky; top: 0;">
                        <tr>
                            <th>Produkt</th>
                            <th>Potreba (Sklad+Obj.)</th>
                            <th>Sklad</th>
                            <th>Plánovaná výroba (kg)</th>
                            <th>Deň výroby</th>
                            <th>Priorita</th>
                            <th>Akcia</th>
                        </tr>
                    </thead>
                    ${tableBodyHtml}
                </table>
            </div>
            <button id="create-tasks-from-plan-btn" class="btn-success" style="width:100%; margin-top: 1rem;">
                <i class="fas fa-tasks"></i> Vytvoriť výrobné úlohy z plánu
            </button>
        `;
    }

    const onReady = () => {
        const btn = document.getElementById('create-tasks-from-plan-btn');
        if (btn) btn.onclick = createTasksFromPlan;
        // document.getElementById('planner-settings-btn').onclick = openPlannerSettingsModal; // Odkomentujeme v ďalšom kroku
    };
    return { html, onReady };
}

async function createTasksFromPlan() {
  // Najprv skús inline, potom modal (spätná kompatibilita)
  const scope = document.getElementById('planner-inline-root') || document.getElementById('modal-container');
  if (!scope) { showStatus("Plánovač nie je dostupný.", true); return; }

  const planData = [];

  const getNextDayOfWeek = (dayIndex) => { // 0=Mon, 1=Tue, ...
    const today = new Date();
    const resultDate = new Date(today);
    const currentDay = today.getDay(); // 0=Sun..6=Sat
    const targetDay = dayIndex + 1;    // chceme Po=1
    let diff = targetDay - (currentDay === 0 ? 7 : currentDay);
    if (diff < 0) diff += 7;
    resultDate.setDate(today.getDate() + diff);
    return resultDate.toISOString().split('T')[0];
  };

  scope.querySelectorAll('tbody tr[data-product-name]').forEach((row) => {
    const dayValue = row.querySelector('.day-select')?.value || 'Nenaplánované';
    if (dayValue === 'Nenaplánované') return;

    const dayIndex = ['Pondelok', 'Utorok', 'Streda', 'Štvrtok', 'Piatok'].indexOf(dayValue);
    const date = getNextDayOfWeek(Math.max(0, dayIndex));

    planData.push({
      nazov_vyrobku: row.dataset.productName,
      navrhovana_vyroba: parseFloat(row.querySelector('.planned-qty-input').value || '0'),
      datum_vyroby: date,
      priorita: !!row.querySelector('.priority-checkbox')?.checked
    });
  });

  if (planData.length === 0) {
    showStatus("Žiadne výrobné úlohy nie sú naplánované na pracovné dni.", true);
    return;
  }

  try {
    await apiRequest('/api/kancelaria/createTasksFromPlan', { method: 'POST', body: planData });
    showStatus("Výrobné úlohy vytvorené.", false);
    // ak by to bežalo v modale, môžeš zatvoriť
    const modal = document.getElementById('modal-container');
    if (modal && modal.contains(scope)) modal.style.display = 'none';
  } catch (e) {
    // apiRequest rieši chyby
  }
}

async function createPurchaseSuggestionsContent() {
    const suggestionsData = await apiRequest('/api/kancelaria/getPurchaseSuggestions');
    let html;
    if (!suggestionsData || suggestionsData.length === 0) {
        html = "<p>Nie je potrebné nič dokúpiť na základe plánu a minimálnych zásob.</p>";
    } else {
        let tableHtml = `<table><thead><tr><th>Surovina</th><th>Sklad (kg)</th><th>Potrebné pre výrobu (kg)</th><th>Min. zásoba (kg)</th><th class="gain">Odporúčaný nákup (kg)</th></tr></thead><tbody>`;
        suggestionsData.forEach(s => {
            tableHtml += `<tr>
                <td><strong>${escapeHtml(s.name)}</strong></td>
                <td>${safeToFixed(s.currentStock)}</td>
                <td>${safeToFixed(s.requiredForProduction)}</td>
                <td>${safeToFixed(s.minStock)}</td>
                <td class="gain">${safeToFixed(s.purchaseQty)}</td>
            </tr>`;
        });
        html = `<div class="table-container">${tableHtml}</tbody></table></div>`;
    }
    return { html };
}

async function createProductionStatsContent() {
    await ensureOfficeDataIsLoaded();
    const categories = ['Všetky', ...(officeInitialData.recipeCategories || [])];
    const categoryOptions = categories.map(c => `<option value="${c}">${c}</option>`).join('');
    const html = `<div style="display: flex; gap: 10px; align-items: end; flex-wrap: wrap;"><div style="flex-grow: 1; min-width: 200px;"><label for="stats-category-filter">Filtrovať kategóriu:</label><select id="stats-category-filter">${categoryOptions}</select></div><button id="load-stats-week-btn" class="btn-secondary" style="margin: 0; flex-shrink: 0;">Tento Týždeň</button><button id="load-stats-month-btn" class="btn-secondary" style="margin: 0; flex-shrink: 0;">Tento Mesiac</button></div><div id="production-stats-table-container" style="margin-top: 1.5rem;"></div><div id="production-damage-table-container" style="margin-top: 1.5rem;"></div>`;
    const onReady = () => {
        const weekBtn = document.getElementById('load-stats-week-btn');
        const monthBtn = document.getElementById('load-stats-month-btn');
        const categoryEl = document.getElementById('stats-category-filter');
        let currentPeriod = 'week';
        const loadStats = async () => {
            weekBtn.style.backgroundColor = currentPeriod === 'week' ? 'var(--primary-color)' : 'var(--secondary-color)';
            monthBtn.style.backgroundColor = currentPeriod === 'month' ? 'var(--primary-color)' : 'var(--secondary-color)';
            const category = categoryEl.value;
            const result = await apiRequest('/api/kancelaria/getProductionStats', { method: 'POST', body: { period: currentPeriod, category } });
            const container = document.getElementById('production-stats-table-container');
            if (!result.data || result.data.length === 0) {
                container.innerHTML = "<h4>Výroba</h4><p>Nenašli sa žiadne výrobné záznamy pre zvolené obdobie.</p>";
            } else {
                let tableHtml = `<h4>Výroba</h4><table><thead><tr><th>Dátum</th><th>Produkt</th><th>Plán</th><th>Realita</th><th>Výťažnosť</th><th>Cena/jed. bez E.</th><th>Cena/jed. s E.</th></tr></thead><tbody>`;
                result.data.forEach(d => {
                    const reality = d.unit === 'ks' ? `${d.realne_mnozstvo_ks} ks` : `${safeToFixed(d.realne_mnozstvo_kg)} kg`;
                    const yieldVal = d.vytaznost;
                    const yieldClass = yieldVal < 0 ? 'loss' : 'gain';
                    const yieldSign = yieldVal > 0 ? '+' : '';
                    tableHtml += `<tr><td>${new Date(d.datum_ukoncenia).toLocaleDateString('sk-SK')}</td><td>${escapeHtml(d.nazov_vyrobku)}</td><td>${safeToFixed(d.planovane_mnozstvo_kg)} kg</td><td>${reality}</td><td class="${yieldClass}">${yieldSign}${safeToFixed(yieldVal)} %</td><td>${safeToFixed(d.cena_bez_energii)} €/${d.unit}</td><td>${safeToFixed(d.cena_s_energiami)} €/${d.unit}</td></tr>`;
                });
                container.innerHTML = `<div class="table-container">${tableHtml}</tbody></table></div>`;
            }
            const damageContainer = document.getElementById('production-damage-table-container');
            if (result.damage_data && result.damage_data.length > 0) {
                let damageHtml = `<h4>Škody</h4><table><thead><tr><th>Dátum</th><th>Produkt</th><th>Množstvo</th><th>Pracovník</th><th>Dôvod</th><th>Náklady</th></tr></thead><tbody>`;
                result.damage_data.forEach(d => {
                    damageHtml += `<tr><td>${new Date(d.datum).toLocaleDateString('sk-SK')}</td><td>${escapeHtml(d.nazov_vyrobku)}</td><td>${escapeHtml(d.mnozstvo)}</td><td>${escapeHtml(d.pracovnik)}</td><td>${escapeHtml(d.dovod)}</td><td class="loss">${d.naklady_skody ? safeToFixed(d.naklady_skody) + ' €' : 'N/A'}</td></tr>`;
                });
                damageContainer.innerHTML = `<div class="table-container">${damageHtml}</tbody></table></div>`;
            } else {
                damageContainer.innerHTML = '<h4>Škody</h4><p>Nenašli sa žiadne záznamy o škodách.</p>';
            }
        };
        weekBtn.onclick = () => { currentPeriod = 'week'; loadStats(); };
        monthBtn.onclick = () => { currentPeriod = 'month'; loadStats(); };
        categoryEl.onchange = () => loadStats();
        loadStats();
    };
    return { html, onReady };
}
async function createReceptionReportContent() {
  const to = new Date();
  const from = new Date(to); from.setDate(from.getDate() - 6);
  const html = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.75rem;align-items:end">
      <div><label>Od (dátum PRÍJMU):</label><input type="date" id="rr-date-from" value="${from.toISOString().slice(0,10)}"></div>
      <div><label>Do (dátum PRÍJMU):</label><input type="date" id="rr-date-to"   value="${to.toISOString().slice(0,10)}"></div>
      <div><label>Koeficient réžií:</label><input type="number" id="rr-overhead" step="0.01" value="1.15"></div>
      <div><button class="btn-primary" id="rr-load-btn"><i class="fas fa-download"></i> Načítať</button></div>
    </div>
    <div id="rr-table" class="table-container" style="margin-top:1rem"></div>
  `;
  const onReady = () => {
    document.getElementById('rr-load-btn').onclick = loadReceptionReport;
  };
  return { html, onReady };
}

async function loadReceptionReport() {
  const date_from = document.getElementById('rr-date-from').value;
  const date_to   = document.getElementById('rr-date-to').value;
  const overhead  = parseFloat(document.getElementById('rr-overhead').value || '1.15');
  if (!date_from || !date_to) { showStatus("Zadajte od-do.", true); return; }

  const res = await apiRequest('/api/kancelaria/receptionReport', {
    method: 'POST', body: { date_from, date_to, overhead_coeff: overhead }
  });
  const table = document.getElementById('rr-table');
  if (!res || !res.rows || res.rows.length === 0) {
    table.innerHTML = '<div style="padding:1rem">V období nebol žiadny príjem.</div>'; return;
  }
  let html = `<table>
    <thead>
      <tr>
        <th>Produkt</th><th>MJ</th>
        <th>Plán (kg)</th><th>Realita (kg)</th><th>Výťažnosť (%)</th>
        <th>Cena/jed. bez E.</th><th>Cena/jed. s E.</th>
      </tr>
    </thead><tbody>`;
  res.rows.forEach(r => {
    html += `<tr>
      <td>${escapeHtml(r.product)}</td>
      <td>${escapeHtml(r.unit)}</td>
      <td style="text-align:right">${Number(r.planned_kg).toFixed(3)}</td>
      <td style="text-align:right">${Number(r.real_kg).toFixed(3)}</td>
      <td style="text-align:right">${r.yield_pct != null ? Number(r.yield_pct).toFixed(2) : ''}</td>
      <td style="text-align:right">${Number(r.unit_cost_no_overhead).toFixed(4)}</td>
      <td style="text-align:right">${Number(r.unit_cost_with_overhead).toFixed(4)}</td>
    </tr>`;
  });
  html += `</tbody>
    <tfoot>
      <tr>
        <th colspan="2" style="text-align:right">Súčty:</th>
        <th style="text-align:right">${Number(res.totals.planned_kg).toFixed(3)}</th>
        <th style="text-align:right">${Number(res.totals.real_kg).toFixed(3)}</th>
        <th style="text-align:right">${Number(res.totals.yield_pct).toFixed(2)}</th>
        <th colspan="2"></th>
      </tr>
    </tfoot></table>`;
  table.innerHTML = html;
}

async function createPrintReportsContent() { 
    await ensureOfficeDataIsLoaded(); 
    const categories = ['Všetky', ...(officeInitialData.itemTypes || [])]; 
    const categoryOptions = categories.map(c => `<option value="${c}">${c}</option>`).join(''); 
    const today = new Date().toISOString().split('T')[0]; 
    const html = ` <h4>Report Príjmu Surovín</h4> <div style="display: flex; gap: 10px; align-items: end; flex-wrap: wrap;"> <div style="flex-grow: 1; min-width:200px;"><label for="report-receipt-category">Kategória:</label><select id="report-receipt-category">${categoryOptions}</select></div> <button id="gen-receipt-day-btn" class="btn-info" style="margin: 0;">Dnes</button> <button id="gen-receipt-week-btn" class="btn-info" style="margin: 0;">Týždeň</button> <button id="gen-receipt-month-btn" class="btn-info" style="margin: 0;">Mesiac</button> </div> <h4 style="margin-top: 2rem;">Report Inventúrnych Rozdielov Surovín</h4> <div style="display: flex; gap: 10px; align-items: end;"> <div style="flex-grow: 1;"><label for="report-inventory-date">Dátum inventúry:</label><input type="date" id="report-inventory-date" value="${today}"></div> <button id="gen-inventory-report-btn" class="btn-warning" style="margin: 0;">Tlačiť Report</button> </div>`; 
    const onReady = () => { 
        document.getElementById('gen-receipt-day-btn').onclick = () => generateReceiptReport('day'); 
        document.getElementById('gen-receipt-week-btn').onclick = () => generateReceiptReport('week'); 
        document.getElementById('gen-receipt-month-btn').onclick = () => generateReceiptReport('month'); 
        document.getElementById('gen-inventory-report-btn').onclick = generateInventoryReport; 
    }; 
    return { html, onReady }; 
}

function generateReceiptReport(period) { 
    const category = document.getElementById('report-receipt-category').value; 
    window.open(`/report/receipt?period=${period}&category=${encodeURIComponent(category)}`, '_blank'); 
}

function generateInventoryReport() { 
    const date = document.getElementById('report-inventory-date').value; 
    if (!date) return showStatus("Zvoľte dátum.", true); 
    window.open(`/report/inventory?date=${date}`, '_blank'); 
}

function ensurePlannerStyles() {
  if (document.getElementById('planner-styles')) return;
  const css = `
    /* decent, čisté štýly pre inline plánovač */
    .planner-toolbar { display:flex; gap:.75rem; align-items:center; flex-wrap:wrap; margin-bottom:.75rem }
    .planner-toolbar .spacer { flex:1 }
    .planner-stat { font-size:.9rem; color:#555 }
    .planner-grid { display:grid; grid-template-columns: 1fr; gap: .75rem; }
    .planner-card { border:1px solid #e5e7eb; border-radius:8px; padding:12px; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,.04) }
    .planner-table-container { max-height: 62vh; overflow:auto; border-radius:8px; border:1px solid #e5e7eb; }
    .planner-table-container table { width:100%; border-collapse:collapse; }
    .planner-table-container thead th { position:sticky; top:0; background:#f8fafc; z-index:1 }
    .planner-table-container th, .planner-table-container td { border-bottom:1px solid #f1f5f9; padding:8px; text-align:left }
    .planner-cat-row { background:#f3f4f6; font-weight:600 }
    .planner-actions { display:flex; gap:.5rem; align-items:center; }
    .chip { display:inline-flex; align-items:center; gap:.35rem; padding:.2rem .5rem; background:#f1f5f9; border-radius:999px; font-size:.8rem; color:#334155 }
    .chip b { font-weight:700; color:#0f172a }
    @media (min-width: 1100px) {
      .planner-grid { grid-template-columns: 2fr 1fr; }
    }
  `;
  const s = document.createElement('style');
  s.id = 'planner-styles';
  s.textContent = css;
  document.head.appendChild(s);
}

async function renderProductionPlanInline() {
  ensurePlannerStyles();
  const root = document.getElementById('planner-inline-root');
  if (!root) return;

  root.innerHTML = `
    <div class="planner-toolbar">
      <h3 style="margin:0">Týždenný Plánovač Výroby</h3>
      <div class="spacer"></div>
      <input id="planner-search" type="search" placeholder="Hľadať produkt…" style="min-width:220px; padding:6px 8px">
      <select id="planner-category" style="padding:6px 8px"><option value="__ALL__">Všetky kategórie</option></select>
      <button id="planner-refresh" class="btn-secondary" style="margin:0"><i class="fas fa-sync-alt"></i> Obnoviť</button>
      <button id="planner-create-tasks" class="btn-success" style="margin:0"><i class="fas fa-tasks"></i> Vytvoriť úlohy</button>
    </div>
    <div class="planner-grid">
      <div class="planner-card">
        <div id="planner-table" class="planner-table-container"></div>
      </div>
      <div class="planner-card">
        <h4 style="margin:0 0 .5rem 0">Zhrnutie</h4>
        <div class="planner-stat" id="planner-summary">
          <span class="chip"><b>0</b> položiek</span>
          <span class="chip"><b>0</b> kg potreba</span>
          <span class="chip"><b>0</b> kg navrhovaná výroba</span>
        </div>
        <p style="margin-top:1rem;color:#475569">Tip: zadaj „Deň výroby“ a označ „Priorita“ pri dôležitých položkách. Následne klikni <em>Vytvoriť úlohy</em>.</p>
      </div>
    </div>
  `;

  const elSearch = root.querySelector('#planner-search');
  const elCat    = root.querySelector('#planner-category');
  const elTable  = root.querySelector('#planner-table');
  const elCreate = root.querySelector('#planner-create-tasks');
  const elRefresh= root.querySelector('#planner-refresh');
  const elSummary= root.querySelector('#planner-summary');

  const days = ['Nenaplánované', 'Pondelok', 'Utorok', 'Streda', 'Štvrtok', 'Piatok'];
  const dayOptions = days.map(d => `<option value="${d}">${d}</option>`).join('');

  let DATA = {};      // { category: [items...] }
  let CATS = [];      // ['Mleté', 'Údeniny', ...]
  let FILTER = { q:'', cat:'__ALL__' };

  const safeToFixedLocal = (v) => (v==null || isNaN(v)) ? '0' : Number(v).toFixed(3);

  async function load() {
    // načítaj plán zo servera
    const res = await apiRequest('/api/kancelaria/getProductionPlan');
    DATA = res || {};
    CATS = Object.keys(DATA);
    // naplň select kategórií
    elCat.innerHTML = `<option value="__ALL__">Všetky kategórie</option>` + CATS.map(c=>`<option value="${c}">${escapeHtml(c)}</option>`).join('');
    render();
  }

  function matches(item) {
    const q = FILTER.q.trim().toLowerCase();
    if (FILTER.cat !== '__ALL__' && FILTER.cat !== item.__cat) return false;
    if (!q) return true;
    return (item.nazov_vyrobku || '').toLowerCase().includes(q);
  }

  function computeSummary(rows) {
    const cnt = rows.length;
    const need = rows.reduce((s,r)=>s + (Number(r.celkova_potreba)||0), 0);
    const make = rows.reduce((s,r)=>s + (Number(r.navrhovana_vyroba)||0), 0);
    elSummary.innerHTML = `
      <span class="chip"><b>${cnt}</b> položiek</span>
      <span class="chip"><b>${safeToFixedLocal(need)}</b> kg potreba</span>
      <span class="chip"><b>${safeToFixedLocal(make)}</b> kg navrhovaná výroba</span>
    `;
  }

  function render() {
    // priprav ploché pole s kategóriou pri každom riadku
    const flat = [];
    for (const [cat, items] of Object.entries(DATA)) {
      (items||[]).forEach(it => flat.push(Object.assign({__cat:cat}, it)));
    }
    const rows = flat.filter(matches);

    computeSummary(rows);

    if (rows.length === 0) {
      elTable.innerHTML = `<div style="padding:1rem">Nie je potrebné nič vyrábať na základe minimálnych zásob a objednávok.</div>`;
      return;
    }

    // roztrieď späť podľa kategórie (len tie, ktoré prešli filtrom)
    const byCat = {};
    rows.forEach(r => (byCat[r.__cat] = byCat[r.__cat] || []).push(r));

    let html = `
      <table>
        <thead>
          <tr>
            <th>Produkt</th>
            <th>Potreba (Sklad+Obj.)</th>
            <th>Sklad</th>
            <th>Plánovaná výroba (kg)</th>
            <th>Deň výroby</th>
            <th>Priorita</th>
            <th>Akcia</th>
          </tr>
        </thead>
    `;

    for (const [cat, items] of Object.entries(byCat)) {
      html += `<tbody class="production-group-tbody">
        <tr class="planner-cat-row"><td colspan="7">${escapeHtml(cat)}</td></tr>
      `;
      items.forEach(item => {
        html += `
          <tr data-product-name="${escapeHtml(item.nazov_vyrobku)}">
            <td>${escapeHtml(item.nazov_vyrobku)}</td>
            <td style="text-align:right">${safeToFixed(item.celkova_potreba)} kg</td>
            <td style="text-align:right">${safeToFixed(item.aktualny_sklad)} kg</td>
            <td><input type="number" class="planned-qty-input" value="${item.navrhovana_vyroba}" step="10" style="width: 90px; text-align:right; padding:4px"></td>
            <td><select class="day-select" style="padding:4px">${dayOptions}</select></td>
            <td style="text-align:center"><input type="checkbox" class="priority-checkbox" style="width:20px;height:20px"></td>
            <td style="text-align:center"><button class="btn-danger" style="padding:2px 8px;margin:0" onclick="this.closest('tr').remove()">×</button></td>
          </tr>
        `;
      });
      html += `</tbody>`;
    }
    html += `</table>`;

    elTable.innerHTML = html;
  }

  // eventy
  elSearch.oninput = (e) => { FILTER.q = e.target.value || ''; render(); };
  elCat.onchange   = (e) => { FILTER.cat = e.target.value || '__ALL__'; render(); };
  elRefresh.onclick= () => load();
  elCreate.onclick = () => createTasksFromPlan();

  // prvé načítanie
  load();
}
