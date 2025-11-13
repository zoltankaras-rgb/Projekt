// =================================================================
// === MODUL EXPEDÍCIA – per-položka príjem, archív, zásoby, tlač ===
// =================================================================
let html5QrCode = null;

function showExpeditionView(viewId) {
  document.querySelectorAll('#expedition-module-container > .view').forEach(v => v.style.display = 'none');
  const view = document.getElementById(viewId);
  if (view) view.style.display = 'block';
  if (typeof clearStatus === 'function') clearStatus();
}

// ---------- MENU ----------
async function loadAndShowExpeditionMenu() {
  try {
    const data = await apiRequest('/api/expedicia/getExpeditionData');
    populatePendingSlicing(data.pendingTasks);
    showExpeditionView('view-expedition-menu');
  } catch (e) {}
}

function populatePendingSlicing(tasks) {
  const container = document.getElementById('pending-slicing-container');
  const section = container.closest('.section');
  if (!tasks || tasks.length === 0) { section.style.display = 'none'; return; }
  section.style.display = 'block';
  let html = `<table><thead><tr><th>Zdroj</th><th>Cieľ</th><th>Plán (ks)</th><th>Akcia</th></tr></thead><tbody>`;
  tasks.forEach(t => {
    html += `<tr>
      <td>${escapeHtml(t.bulkProductName)}</td>
      <td>${escapeHtml(t.targetProductName || '')}</td>
      <td>${escapeHtml(t.plannedPieces != null ? t.plannedPieces : '')}</td>
      <td><button class="btn-primary" style="margin:0;width:auto" onclick="finalizeSlicing('${t.logId}')">Ukončiť</button></td>
    </tr>`;
  });
  container.innerHTML = html + '</tbody></table>';
}

// ---------- PREVZATIE Z VÝROBY (po položkách) ----------
async function loadProductionDates() {
  try {
    const dates = await apiRequest('/api/expedicia/getProductionDates');
    showExpeditionView('view-expedition-date-selection');
    const container = document.getElementById('expedition-date-container');
    container.innerHTML = dates.length === 0 ? '<p>Žiadne výroby na prevzatie.</p>' : '';
    dates.forEach(d => {
      const btn = document.createElement('button');
      btn.className = 'btn-primary';
      btn.textContent = new Date(d + 'T00:00:00').toLocaleDateString('sk-SK');
      btn.onclick = () => loadProductionsByDate(d);
      container.appendChild(btn);
    });
  } catch(e) {}
}

async function loadProductionsByDate(dateStr) {
  try {
    showExpeditionView('view-expedition-batch-list');
    document.getElementById('expedition-batch-list-title').textContent =
      `Príjem výrobkov – deň výroby: ${new Date(dateStr + 'T00:00:00').toLocaleDateString('sk-SK')}`;
    document.getElementById('expedition-accept-date').value = dateStr;

    const data = await apiRequest('/api/expedicia/getProductionsByDate', { method:'POST', body:{ date: dateStr }});
    let html = `<table><thead><tr>
      <th>Produkt</th><th>Stav</th><th>Plán</th><th>Príjem</th><th>Poznámka</th><th>Akcia</th>
    </tr></thead><tbody>`;

    data.forEach(p => {
      const planned = p.mj === 'ks' ? `${p.expectedPieces || '?'} ks` : `${safeToFixed(p.plannedQty)} kg`;
      const realityInput = `<input type="number" step="${p.mj==='ks' ? 1 : 0.01}" id="actual_${p.batchId}" style="width:90px">`;
      const noteInput = `<input type="text" id="note_${p.batchId}" placeholder="Poznámka" style="width:160px">`;
      const btn = `<button class="btn-success" style="margin:0;width:auto" onclick="acceptSingleProduction('${p.batchId}','${p.mj}', this, '${dateStr}')">Prijať</button>`;

      html += `<tr data-batch-id="${p.batchId}" data-unit="${p.mj}" data-product-name="${escapeHtml(p.productName)}">
        <td>${escapeHtml(p.productName)}</td>
        <td>${escapeHtml(p.status)}</td>
        <td>${planned}</td>
        <td>${realityInput}</td>
        <td>${noteInput}</td>
        <td>${btn}</td>
      </tr>`;
    });
    html += `</tbody></table>`;
    document.getElementById('expedition-batch-table').innerHTML = html;

    // tlačidlá pod tabuľkou
    const actions = document.getElementById('expedition-action-buttons');
    actions.innerHTML = `
      <div class="btn-grid">
        <button class="btn-primary" onclick="openAcceptanceDays()"><i class="fas fa-folder-open"></i> Archív prijmu</button>
        <button class="btn-secondary" onclick="loadAndShowStockOverview()"><i class="fas fa-warehouse"></i> Skladové zásoby</button>
        <button class="btn-secondary" onclick="loadProductionDates()"><i class="fas fa-arrow-left"></i> Späť na výber dňa</button>
      </div>
    `;
  } catch(e) {}
}

// dvojité potvrdenie + po úspechu odstrániť riadok + ak je tabuľka prázdna → späť na dni
async function acceptSingleProduction(batchId, unit, btnEl, currentDate) {
  const workerName = document.getElementById('expedition-worker-name').value;
  const acceptDate = document.getElementById('expedition-accept-date').value || new Date().toISOString().slice(0,10);
  if (!workerName) { showStatus("Zadajte meno preberajúceho pracovníka.", true); return; }

  const valRaw = (document.getElementById(`actual_${batchId}`)?.value || '').trim();
  if (!valRaw || Number(valRaw) <= 0) { showStatus("Zadajte reálne množstvo.", true); return; }
  const valNorm = String(valRaw).replace(',', '.');

  if (!confirm(`Potvrdiť príjem ${valNorm} ${unit}?`)) return;
  const retype = prompt(`Pre potvrdenie zadajte ešte raz ${unit}:`, valNorm);
  if (retype === null) return;
  if (String(retype).replace(',', '.') !== valNorm) {
    showStatus("Množstvo pri druhom zadaní nesedí. Príjem bol zrušený.", true);
    return;
  }

  const note = document.getElementById(`note_${batchId}`)?.value || '';
  btnEl.disabled = true;

  try {
    const res = await apiRequest('/api/expedicia/acceptProductionItem', {
      method:'POST',
      body: { batchId, unit, actualValue: valNorm, workerName, note, acceptDate }
    });
    showStatus(res.message, false);

    // odstrániť riadok z tabuľky
    const row = document.querySelector(`#expedition-batch-table tr[data-batch-id="${batchId}"]`);
    if (row && row.parentElement) row.parentElement.removeChild(row);

    const anyLeft = document.querySelectorAll('#expedition-batch-table tbody tr').length;
    if (!anyLeft) {
      // žiadne položky z tohto dňa – vrátime sa na výber dňa a deň už nebude v zozname
      loadProductionDates();
    }
  } catch(e) {
  } finally {
    btnEl.disabled = false;
  }
}

// ---------- ARCHÍV PRIJMU ----------
async function openAcceptanceDays() {
  try {
    const days = await apiRequest('/api/expedicia/getAcceptanceDays');
    showExpeditionView('view-expedition-acceptance-days');
    const cont = document.getElementById('acceptance-days-container');
    cont.innerHTML = days.length ? '' : '<p>Zatiaľ žiadne prijmy.</p>';
    days.forEach(d => {
      const btn = document.createElement('button');
      btn.className = 'btn-primary';
      btn.textContent = new Date(d+'T00:00:00').toLocaleDateString('sk-SK');
      btn.onclick = () => openAcceptanceArchive(d);
      cont.appendChild(btn);
    });
  } catch(e) {}
}

function openAcceptanceArchive(dateStr) {
  document.getElementById('accept-archive-date').value = dateStr || new Date().toISOString().slice(0,10);
  loadAcceptanceArchive();
}

async function loadAcceptanceArchive() {
  const dateStr = document.getElementById('accept-archive-date').value || new Date().toISOString().slice(0,10);
  try {
    const res = await apiRequest(`/api/expedicia/getAcceptanceArchive?date=${encodeURIComponent(dateStr)}`);
    showExpeditionView('view-expedition-acceptance-archive');
    const c = document.getElementById('acceptance-archive-table');
    let html = `<table><thead><tr>
      <th>Čas</th><th>Šarža</th><th>Produkt</th><th>Množstvo</th><th>Prijal</th><th>Pozn./Dôvod</th><th>Akcie</th>
    </tr></thead><tbody>`;
    (res.items || []).forEach(it => {
      const time = it.updated_at ? it.updated_at : it.created_at;
      const val  = it.unit === 'kg' ? `${safeToFixed(it.prijem_kg,2)} kg` : `${it.prijem_ks} ks`;
      html += `<tr>
        <td>${escapeHtml(new Date(time).toLocaleString('sk-SK'))}</td>
        <td>${escapeHtml(it.batchId)}</td>
        <td>${escapeHtml(it.productName)}</td>
        <td>${val}</td>
        <td>${escapeHtml(it.prijal || '')}</td>
        <td>${escapeHtml(it.dovod || '')}</td>
        <td style="display:flex;gap:6px">
          <button class="btn-info" style="margin:0;width:auto" onclick="editAcceptancePrompt(${it.id}, '${it.unit}', '${it.batchId}')"><i class="fas fa-pen"></i></button>
          <button class="btn-danger" style="margin:0;width:auto" onclick="deleteAcceptancePrompt(${it.id})"><i class="fas fa-trash"></i></button>
          <button class="btn-secondary" style="margin:0;width:auto" onclick="printAccompanyingLetter('${it.batchId}')"><i class="fas fa-print"></i></button>
        </td>
      </tr>`;
    });
    html += `</tbody></table>`;
    c.innerHTML = html;
  } catch(e) {}
}

async function editAcceptancePrompt(id, unit, batchId) {
  if (!confirm("Naozaj chcete upraviť tento príjem?")) return;
  const nv = prompt(`Zadajte novú hodnotu (${unit}):`);
  if (nv === null || nv.trim()==='' || Number(nv)<=0) { showStatus("Neplatná hodnota.", true); return; }
  const reason = prompt("Uveďte dôvod úpravy (povinné):");
  if (reason===null || reason.trim()==='') { showStatus("Dôvod je povinný.", true); return; }
  const workerName = document.getElementById('expedition-worker-name')?.value || 'Neznámy';
  try {
    const res = await apiRequest('/api/expedicia/editAcceptance', { method:'POST', body:{ id, newValue:nv, unit, reason, workerName }});
    showStatus(res.message, false);
    loadAcceptanceArchive();
  } catch(e) {}
}

async function deleteAcceptancePrompt(id) {
  if (!confirm("Naozaj chcete zmazať tento príjem?")) return;
  const reason = prompt("Uveďte dôvod zmazania (povinné):");
  if (reason===null || reason.trim()==='') { showStatus("Dôvod je povinný.", true); return; }
  const workerName = document.getElementById('expedition-worker-name')?.value || 'Neznámy';
  try {
    const res = await apiRequest('/api/expedicia/deleteAcceptance', { method:'POST', body:{ id, reason, workerName }});
    showStatus(res.message, false);
    loadAcceptanceArchive();
  } catch(e) {}
}

// ---------- TLAČ SPRIEVODKY ----------
async function printAccompanyingLetter(batchId) {
  const workerName = document.getElementById('expedition-worker-name')?.value || '';
  try {
    const response = await fetch('/api/expedicia/getAccompanyingLetter', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({batchId, workerName})
    });
    if (!response.ok) throw new Error(`Chyba servera: ${response.statusText}`);
    const html = await response.text();
    const win = window.open('', '_blank');
    win.document.write(html);
    win.document.close();
  } catch (e) {
    showStatus(`Chyba pri tlači: ${e.message}`, true);
  }
}

// ---------- SKLADOVÉ ZÁSOBY (Sklad 2 – prehľad) ----------
async function loadAndShowStockOverview() {
  try {
    const data = await apiRequest('/api/expedicia/getProductsForInventory');
    showExpeditionView('view-expedition-stock-overview');
    const container = document.getElementById('stock-overview-tables-container');
    container.innerHTML = '';
    for (const category in data) {
      if (data[category].length > 0) {
        container.innerHTML += `<h4>${escapeHtml(category)}</h4><div class="table-container">${createStockTable(data[category])}</div>`;
      }
    }
  } catch(e) {}
}
function createStockTable(items) {
  let t = `<table><thead><tr><th>Názov</th><th>MJ</th><th>Sklad (kg)</th><th>Systém (ks/kg)</th></tr></thead><tbody>`;
  items.forEach(i=>{
    t += `<tr>
      <td>${escapeHtml(i.nazov_vyrobku)}</td>
      <td>${escapeHtml(i.mj)}</td>
      <td>${safeToFixed(i.aktualny_sklad_finalny_kg||0)}</td>
      <td>${i.system_stock_display}</td>
    </tr>`;
  });
  return t + '</tbody></table>';
}

// ---------- INVENTÚRA (Sklad 2) ----------
async function loadAndShowProductInventory() {
  try {
    const data = await apiRequest('/api/expedicia/getProductsForInventory');
    showExpeditionView('view-expedition-inventory');
    const container = document.getElementById('product-inventory-tables-container');
    container.innerHTML = '';
    for (const category in data) {
      if (data[category].length > 0) {
        container.innerHTML += `<h4>${escapeHtml(category)}</h4><div class="table-container">${createProductInventoryTable(data[category])}</div>`;
      }
    }
  } catch(e) {}
}
function createProductInventoryTable(items) {
  let t = `<table><thead><tr><th>Názov</th><th>Systém (ks/kg)</th><th>Reálny (ks/kg)</th></tr></thead><tbody>`;
  items.forEach(i=>{
    t += `<tr>
      <td>${escapeHtml(i.nazov_vyrobku)} (${i.mj})</td>
      <td>${i.system_stock_display}</td>
      <td><input type="number" step="0.01" data-ean="${escapeHtml(i.ean)}" class="product-inventory-input"></td>
    </tr>`;
  });
  return t + '</tbody></table>';
}
async function submitProductInventory() {
  const workerName = document.getElementById('inventory-worker-name').value;
  if (!workerName) { showStatus("Zadajte meno pracovníka.", true); return; }
  const items = Array.from(document.querySelectorAll('.product-inventory-input'))
    .filter(i => i.value && i.value.trim()!=='')
    .map(i => ({ ean: i.dataset.ean, realQty: i.value }));
  if (items.length===0) { showStatus("Nezadali ste reálne stavy.", true); return; }
  try {
    const res = await apiRequest('/api/expedicia/submitProductInventory', { method:'POST', body:{ inventoryData: items, workerName } });
    showStatus(res.message, false);
    setTimeout(loadAndShowExpeditionMenu, 1500);
  } catch(e) {}
}

// ---------- MANUÁLNY PRÍJEM ----------
async function loadAndShowManualReceive() {
  try {
    const products = await apiRequest('/api/expedicia/getAllFinalProducts');
    showExpeditionView('view-expedition-manual-receive');
    const sel = document.getElementById('manual-receive-product-select');
    sel.innerHTML = '<option value="">Vyberte produkt...</option>';
    products.forEach(p=>{
      const o = document.createElement('option'); o.value = p.ean; o.textContent = `${p.name} (${p.unit})`; sel.add(o);
    });
    document.getElementById('manual-receive-date').valueAsDate = new Date();
  } catch(e) {}
}
async function submitManualReceive() {
  const data = {
    workerName: document.getElementById('manual-receive-worker-name').value,
    receptionDate: document.getElementById('manual-receive-date').value,
    ean: document.getElementById('manual-receive-product-select').value,
    quantity: document.getElementById('manual-receive-quantity').value
  };
  if (!data.workerName || !data.ean || !data.quantity || !data.receptionDate) { showStatus("Všetky polia sú povinné.", true); return; }
  try {
    const res = await apiRequest('/api/expedicia/manualReceiveProduct', { method:'POST', body:data });
    showStatus(res.message, false);
    setTimeout(loadAndShowExpeditionMenu, 1500);
  } catch(e) {}
}

// ---------- POŽIADAVKA KRÁJANIE ----------
async function loadAndShowSlicingRequest() {
  try {
    const products = await apiRequest('/api/expedicia/getSlicableProducts');
    showExpeditionView('view-expedition-slicing-request');
    const sel = document.getElementById('slicing-product-select');
    sel.innerHTML = '<option value="">Vyberte finálny balíček...</option>';
    products.forEach(p => {
      const o = document.createElement('option'); o.value = p.ean; o.textContent = p.name; sel.add(o);
    });
  } catch(e) {}
}
async function submitSlicingRequest() {
  const ean = document.getElementById('slicing-product-select').value;
  const pcs = document.getElementById('slicing-planned-pieces').value;
  if (!ean || !pcs || Number(pcs)<=0) { showStatus("Zadajte produkt a počet kusov.", true); return; }
  try {
    const res = await apiRequest('/api/expedicia/startSlicingRequest', { method:'POST', body:{ ean, pieces: parseInt(pcs) } });
    showStatus(res.message, false);
    setTimeout(loadAndShowExpeditionMenu, 1200);
  } catch(e) {}
}

// ---------- SKENER ----------
function startBarcodeScanner() {
  showExpeditionView('view-expedition-scanner');
  const out = document.getElementById('scan-result'); out.textContent = '';
  html5QrCode = new Html5Qrcode("scanner-container");
  const ok = (txt)=>{ out.textContent = `Naskenovaný kód: ${txt}`; stopBarcodeScanner(); window.open(`/traceability/${txt}`, '_blank'); };
  const cfg = { fps:10, qrbox:{width:250,height:250} };
  html5QrCode.start({ facingMode: "environment" }, cfg, ok).catch(err => { showStatus(`Chyba kamery: ${err}`, true); showExpeditionView('view-expedition-menu'); });
}
function stopBarcodeScanner() {
  if (html5QrCode && html5QrCode.isScanning) { html5QrCode.stop().then(()=>{}).catch(()=>{}); }
  showExpeditionView('view-expedition-menu');
}

// ---------- KRAJANIE – FINÁLNE UKONČENIE (DOPLNENÉ) ----------
async function finalizeSlicing(logId) {
  const pcs = prompt("Zadajte reálny počet kusov:");
  if (pcs===null || pcs.trim()==='' || isNaN(parseInt(pcs)) || parseInt(pcs)<=0) { showStatus("Neplatná hodnota.", true); return; }
  try {
    const res = await apiRequest('/api/expedicia/finalizeSlicing', { method:'POST', body:{ logId, actualPieces: parseInt(pcs) }});
    showStatus(res.message, false);
    loadAndShowExpeditionMenu(); // obnoví sekciu „Prebiehajúce krájanie“
  } catch(e) {}
}

// ========= EXPORT PRE onclick (globálna viditeľnosť) =========
window.loadAndShowExpeditionMenu = loadAndShowExpeditionMenu;
window.loadProductionDates         = loadProductionDates;
window.loadProductionsByDate       = loadProductionsByDate;
window.acceptSingleProduction      = acceptSingleProduction;
window.openAcceptanceDays          = openAcceptanceDays;
window.openAcceptanceArchive       = openAcceptanceArchive;
window.loadAcceptanceArchive       = loadAcceptanceArchive;
window.printAccompanyingLetter     = printAccompanyingLetter;
window.loadAndShowProductInventory = loadAndShowProductInventory;
window.submitProductInventory      = submitProductInventory;
window.loadAndShowManualReceive    = loadAndShowManualReceive;
window.submitManualReceive         = submitManualReceive;
window.loadAndShowSlicingRequest   = loadAndShowSlicingRequest;
window.submitSlicingRequest        = submitSlicingRequest;
window.startBarcodeScanner         = startBarcodeScanner;
window.finalizeSlicing             = finalizeSlicing;
window.loadAndShowStockOverview    = loadAndShowStockOverview;
