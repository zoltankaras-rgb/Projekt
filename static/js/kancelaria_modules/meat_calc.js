// =================================================================
// === KANCELÁRIA: KALKULÁTOR ROZRÁBKY MÄSA ========================
// =================================================================

async function apiM(url, opts = {}) {
  try {
    const res = await apiRequest(url, opts);
    return res;
  } catch (e) {
    console.error('API error:', url, e);
    return { __error: e?.message || 'API error' };
  }
}
function ensureMeatTabsStyles(){
  if (document.getElementById('meat-inline-styles')) return;
  const s = document.createElement('style');
  s.id = 'meat-inline-styles';
  s.textContent = `
    /* Týka sa len tohto modulu */
    #section-meat-calc .b2b-tab-nav{ display:flex; gap:.5rem; flex-wrap:wrap; }
    #section-meat-calc .b2b-tab-button{
      appearance:none; border:0; cursor:pointer;
      padding:.55rem .9rem; border-radius:9999px;
      background: var(--light); color: var(--dark);
      font-family: var(--font); font-weight:600; letter-spacing:.2px;
      box-shadow: 0 1px 2px rgba(0,0,0,.06) inset;
      transition: transform .12s ease, box-shadow .15s ease,
                  background-color .15s ease, color .15s ease;
    }
    #section-meat-calc .b2b-tab-button:hover{ filter: brightness(0.98); }
    #section-meat-calc .b2b-tab-button:active{ transform: translateY(1px); }
    #section-meat-calc .b2b-tab-button.active{
      color:#fff;
      background: linear-gradient(180deg, rgba(255,255,255,.12), rgba(0,0,0,.06)), var(--primary-color);
      box-shadow: var(--shadow);
    }
    /* Fallback pre tab obsah (ak by globálne CSS neriešilo) */
    #section-meat-calc .b2b-tab-content { display:none; }
    #section-meat-calc .b2b-tab-content.active { display:block; }
    /* Aj ostatné tlačidlá v module nech sú pekne zaoblené */
    #section-meat-calc .btn { border-radius:9999px; }
  `;
  document.head.appendChild(s);
}
const $ = (id)=>document.getElementById(id);
const esc = (s)=> (window.escapeHtml?window.escapeHtml(s):String(s||''));
function initializeMeatCalcModule(){
  ensureMeatTabsStyles(); // <- pridaj toto
  const wrap = document.getElementById('section-meat-calc');
  if (!wrap) return;

  wrap.innerHTML = `
    <h3>Kalkulátor Rozrábky Mäsa</h3>

    <!-- NAV: presne ako v systéme -->
    <div class="b2b-tab-nav" id="meat-main-nav">
      <button class="b2b-tab-button active" data-meat-tab="settings">Nastavenia</button>
      <button class="b2b-tab-button" data-meat-tab="new">Evidencia (nový záznam)</button>
      <button class="b2b-tab-button" data-meat-tab="history">História</button>
      <button class="b2b-tab-button" data-meat-tab="estimate">Odhad Rozrábky</button>
    </div>

    <!-- CONTENT PANES: id = <key>-tab, presne ako inde -->
    <div id="settings-tab" class="b2b-tab-content active" style="margin-top:1rem;">
      <div class="analysis-card">
        <h4>Číselník Surovín</h4>
        <div style="display:flex; gap:.5rem; margin:.5rem 0;">
          <button class="btn btn-success" id="meat-add-material"><i class="fas fa-plus"></i> Pridať surovinu</button>
          <button class="btn btn-secondary" id="meat-refresh-materials"><i class="fas fa-rotate"></i> Obnoviť</button>
        </div>
        <div id="meat-materials-table"></div>
      </div>

      <div class="analysis-card" style="margin-top:1rem;">
        <h4>Číselník Produktov (s predajnou cenou)</h4>
        <div style="display:flex; gap:.5rem; margin:.5rem 0;">
          <button class="btn btn-success" id="meat-add-product"><i class="fas fa-plus"></i> Pridať produkt</button>
          <button class="btn btn-secondary" id="meat-refresh-products"><i class="fas fa-rotate"></i> Obnoviť</button>
        </div>
        <div id="meat-products-table"></div>
      </div>
    </div>

    <div id="new-tab" class="b2b-tab-content" style="margin-top:1rem;">
      <div class="analysis-card">
        <h4>Nový záznam rozrábky</h4>
        <form id="meat-new-form">
          <div class="form-grid" style="grid-template-columns: repeat(4, minmax(180px, 1fr)); gap:.75rem;">
            <div class="form-group"><label>Dátum</label><input type="date" name="breakdown_date" required></div>
            <div class="form-group"><label>Surovina</label><select name="material_id" id="meat-new-material" required></select></div>
            <div class="form-group"><label>Dodávateľ (voliteľné)</label><input name="supplier" placeholder="Dodávateľ"></div>
            <div class="form-group"><label>Počet kusov (voliteľné)</label><input type="number" name="units_count" step="1"></div>
            <div class="form-group"><label>Vstupná váha (kg)</label><input type="number" name="input_weight_kg" step="0.001" required></div>
            <div class="form-group"><label>Celková nákupná cena (€)</label><input type="number" name="purchase_total_cost_eur" step="0.01"></div>
            <div class="form-group"><label>alebo Jedn. cena (€/kg)</label><input type="number" name="purchase_unit_price_eur_kg" step="0.0001"></div>
            <div class="form-group"><label>Tolerancia straty (%)</label><input type="number" name="tolerance_pct" step="0.001" value="5.000"></div>
            <div class="form-group" style="grid-column:1/-1;"><label>Poznámka</label><input name="note"></div>
          </div>
        </form>
      </div>

      <div class="analysis-card" style="margin-top:1rem;">
        <h4>Výstupy (diely)</h4>
        <div id="meat-outputs-table"></div>
        <div style="display:flex; gap:.5rem; margin-top:.5rem;">
          <button class="btn btn-success" id="meat-add-output"><i class="fas fa-plus"></i> Pridať položku</button>
        </div>
      </div>

      <div class="analysis-card" style="margin-top:1rem;">
        <h4>Dodatočné náklady</h4>
        <div id="meat-extras-table"></div>
        <div style="display:flex; gap:.5rem; margin-top:.5rem;">
          <button class="btn btn-secondary" id="meat-add-extra"><i class="fas fa-plus"></i> Pridať náklad</button>
        </div>
      </div>

      <div style="display:flex; gap:.75rem; margin-top:1rem;">
        <button class="btn btn-success" id="meat-save-breakdown"><i class="fas fa-save"></i> Uložiť záznam</button>
      </div>

      <div id="meat-results" style="margin-top:1rem;"></div>
    </div>

    <div id="history-tab" class="b2b-tab-content" style="margin-top:1rem;">
      <div class="analysis-card">
        <h4>História rozrábok</h4>
        <div class="form-grid" style="grid-template-columns: repeat(5, minmax(160px, 1fr)); gap:.5rem;">
          <div class="form-group"><label>Surovina</label><select id="meat-hist-material"></select></div>
          <div class="form-group"><label>Dátum od</label><input type="date" id="meat-hist-from"></div>
          <div class="form-group"><label>Dátum do</label><input type="date" id="meat-hist-to"></div>
          <div class="form-group"><label>Dodávateľ</label><input id="meat-hist-sup"></div>
          <div class="form-group" style="align-self:end;"><button class="btn btn-secondary" id="meat-hist-load"><i class="fas fa-search"></i> Hľadať</button></div>
        </div>
        <div id="meat-hist-table" style="margin-top:.5rem;"></div>
      </div>
    </div>

    <div id="estimate-tab" class="b2b-tab-content" style="margin-top:1rem;">
      <div class="analysis-card">
        <h4>Odhad Rozrábky (štatistický)</h4>
        <div class="form-grid" style="grid-template-columns: repeat(6, minmax(160px, 1fr)); gap:.75rem;">
          <div class="form-group"><label>Surovina</label><select id="meat-est-material"></select></div>
          <div class="form-group"><label>Plánovaná váha (kg)</label><input type="number" id="meat-est-weight" step="0.001" value="1000.000"></div>
          <div class="form-group"><label>Očakávaná nákupná cena (€/kg)</label><input type="number" id="meat-est-price" step="0.0001" value="2.6000"></div>
          <div class="form-group"><label>Dodávateľ filter (voliteľné)</label><input id="meat-est-sup"></div>
          <div class="form-group"><label>Dátum od</label><input type="date" id="meat-est-from"></div>
          <div class="form-group"><label>Dátum do</label><input type="date" id="meat-est-to"></div>
        </div>

        <div class="analysis-card" style="margin-top:.75rem;">
          <h5>Odhad – dodatočné náklady</h5>
          <div id="meat-est-extras"></div>
          <div style="display:flex; gap:.5rem; margin-top:.5rem;">
            <button class="btn btn-secondary" id="meat-est-add-extra"><i class="fas fa-plus"></i> Pridať náklad</button>
          </div>
        </div>

        <div style="display:flex; gap:.75rem; margin-top:.75rem;">
          <button class="btn btn-primary" id="meat-est-run"><i class="fas fa-calculator"></i> Prepočítať odhad</button>
        </div>

        <div id="meat-est-results" style="margin-top:1rem;"></div>
      </div>
    </div>
  `;

  // Prepínanie tabov – rovnaká logika ako inde
  const tabButtons  = document.querySelectorAll('#section-meat-calc .b2b-tab-button');
  const tabContents = document.querySelectorAll('#section-meat-calc .b2b-tab-content');

  tabButtons.forEach(button=>{
    button.onclick = ()=>{
      // stav tlačidiel
      tabButtons.forEach(b=>b.classList.remove('active'));
      button.classList.add('active');

      // viditeľnosť panelov
      tabContents.forEach(c=>{ c.classList.remove('active'); c.style.display='none'; });
      const paneId = `${button.dataset.meatTab}-tab`;
      const pane   = document.getElementById(paneId);
      if (pane){ pane.classList.add('active'); pane.style.display='block'; }

      // lazy načítania podľa tabov (ak treba)
      if (button.dataset.meatTab === 'settings'){ /* nič špeciálne */ }
      if (button.dataset.meatTab === 'history'){ /* nič špeciálne */ }
    };
  });

  // Úvodný stav: len SETTINGS viditeľný
  tabContents.forEach(c=> c.style.display='none');
  const first = document.getElementById('settings-tab');
  if (first) first.style.display='block';

  // init obsahu
  loadMaterialsTable();
  loadProductsTable();
  initNewBreakdown();
  initHistory();
  initEstimate();
}

// ------- Nastavenia: suroviny ------------------------------------
async function loadMaterialsTable(){
  const tbl = $('meat-materials-table');
  const rows = await apiM('/api/kancelaria/meat/materials');

  if (!Array.isArray(rows)) {
    console.warn('materials endpoint nevrátil pole:', rows);
    tbl.innerHTML = '<p class="error">Nepodarilo sa načítať suroviny (skontroluj route /api/kancelaria/meat/materials).</p>';
    return;
  }

  let html = '<div class="table-container"><table><thead><tr><th>Kód</th><th>Názov</th><th>Akcie</th></tr></thead><tbody>';
  rows.forEach(r=>{
    html+=`<tr>
      <td>${esc(r.code)}</td><td>${esc(r.name)}</td>
      <td><button class="btn btn-warning btn-xs" onclick='openMaterialModal(${r.id},${JSON.stringify(r)})'><i class="fas fa-edit"></i></button></td>
    </tr>`;
  });
  html += '</tbody></table></div>';
  tbl.innerHTML = html;

  $('meat-add-material').onclick = ()=> openMaterialModal(null,null);
  $('meat-refresh-materials').onclick = loadMaterialsTable;
}

function openMaterialModal(id=null, row=null){
  showModal(id?'Upraviť surovinu':'Pridať surovinu', ()=>{
    const html = `
      <form id="meat-material-form">
        <input type="hidden" name="id" value="${id||''}">
        <div class="form-grid" style="grid-template-columns:repeat(2,minmax(180px,1fr));gap:.75rem;">
          <div class="form-group"><label>Kód</label><input name="code" value="${row?.code||''}" required></div>
          <div class="form-group"><label>Názov</label><input name="name" value="${row?.name||''}" required></div>
        </div>
        <button class="btn btn-success" style="margin-top:.75rem;">Uložiť</button>
      </form>
    `;
    return { html, onReady: ()=>{
      const f=$('meat-material-form');
      f.onsubmit=async e=>{
        e.preventDefault();
        const body = Object.fromEntries(new FormData(f).entries());
        const res = await apiM('/api/kancelaria/meat/material/save',{method:'POST', body});
        if (res?.error) { showStatus(res.error, true); return; }
        $('modal-container').style.display='none';
        loadMaterialsTable();
        // obnov aj výbery v iných kartách
        fillMaterialsSelects();
      };
    }};
  });
}

// ------- Nastavenia: produkty ------------------------------------
async function loadProductsTable(){
  const tbl = $('meat-products-table');
  const rows = await apiM('/api/kancelaria/meat/products');

  if (!Array.isArray(rows)) {
    console.warn('products endpoint nevrátil pole:', rows);
    tbl.innerHTML = '<p class="error">Nepodarilo sa načítať produkty (skontroluj route /api/kancelaria/meat/products).</p>';
    return;
  }

  let html = '<div class="table-container"><table><thead><tr><th>Kód</th><th>Produkt</th><th>Predajná cena (€/kg)</th><th>Akcie</th></tr></thead><tbody>';
  rows.forEach(r=>{
    html+=`<tr>
      <td>${esc(r.code)}</td>
      <td>${esc(r.name)}</td>
      <td>${Number(r.selling_price_eur_kg).toFixed(3)}</td>
      <td><button class="btn btn-warning btn-xs" onclick='openProductModal(${r.id},${JSON.stringify(r)})'><i class="fas fa-edit"></i></button></td>
    </tr>`;
  });
  html += '</tbody></table></div>';
  tbl.innerHTML = html;

  $('meat-add-product').onclick = ()=> openProductModal(null,null);
  $('meat-refresh-products').onclick = loadProductsTable;
}

function openProductModal(id=null, row=null){
  showModal(id?'Upraviť produkt':'Pridať produkt', ()=>{
    const html = `
      <form id="meat-product-form">
        <input type="hidden" name="id" value="${id||''}">
        <div class="form-grid" style="grid-template-columns:repeat(3,minmax(160px,1fr));gap:.75rem;">
          <div class="form-group"><label>Kód</label><input name="code" value="${row?.code||''}" required></div>
          <div class="form-group"><label>Názov</label><input name="name" value="${row?.name||''}" required></div>
          <div class="form-group"><label>Predajná cena (€/kg)</label><input type="number" name="selling_price_eur_kg" step="0.001" value="${row?.selling_price_eur_kg||''}" required></div>
        </div>
        <button class="btn btn-success" style="margin-top:.75rem;">Uložiť</button>
      </form>
    `;
    return { html, onReady: ()=>{
      const f=$('meat-product-form');
      f.onsubmit=async e=>{
        e.preventDefault();
        const body = Object.fromEntries(new FormData(f).entries());
        const res = await apiM('/api/kancelaria/meat/product/save',{method:'POST', body});
        if (res?.error) { showStatus(res.error, true); return; }
        $('modal-container').style.display='none';
        loadProductsTable();
      };
    }};
  });
}

// ------- Evidencia (nový záznam) ---------------------------------
let MEAT_PRODUCTS_CACHE = [];

async function fillMaterialsSelects(){
  const mats = await apiM('/api/kancelaria/meat/materials');
  const selNew = $('meat-new-material');
  const selHist= $('meat-hist-material');
  const selEst = $('meat-est-material');

  [selNew, selHist, selEst].forEach(s=>{
    if (!s) return;
    if (!Array.isArray(mats)) {
      console.warn('materials endpoint nevrátil pole:', mats);
      s.innerHTML = `<option value="">— (chyba API) —</option>`;
      return;
    }
    s.innerHTML = `<option value="">— Vyber —</option>` + mats.map(m=>`<option value="${m.id}">${esc(m.name)} (${esc(m.code)})</option>`).join('');
  });
}

async function initNewBreakdown(){
  await fillMaterialsSelects();

  const prods = await apiM('/api/kancelaria/meat/products');
  MEAT_PRODUCTS_CACHE = Array.isArray(prods) ? prods : [];
  if (!Array.isArray(prods)) {
    console.warn('products endpoint nevrátil pole:', prods);
  }

  // outputs table
  const outWrap = $('meat-outputs-table');
  outWrap.innerHTML = buildOutputsTable([]);
  $('meat-add-output').onclick = ()=> addOutputRow();

  // extras table
  const exWrap = $('meat-extras-table');
  exWrap.innerHTML = buildExtrasTable([]);
  $('meat-add-extra').onclick = ()=> addExtraRow();

  // save
  $('meat-save-breakdown').onclick = saveBreakdown;
}

function buildOutputsTable(rows){
  return `
    <div class="table-container"><table id="meat-outputs">
      <thead><tr><th>Produkt</th><th>Váha (kg)</th><th>Akcia</th></tr></thead>
      <tbody>
        ${rows.map(buildOutputRow).join('')}
      </tbody>
    </table></div>`;
}

function buildOutputRow(r={}, idx=Date.now()){
  const opts = (MEAT_PRODUCTS_CACHE||[]).map(p=>`<option value="${p.id}" ${String(p.id)===String(r.product_id)?'selected':''}>${esc(p.name)} (${esc(p.code)})</option>`).join('');
  return `<tr data-row="${idx}">
    <td><select class="meat-out-product">${opts}</select></td>
    <td><input type="number" class="meat-out-weight" step="0.001" value="${r.weight_kg||''}"></td>
    <td><button class="btn btn-danger btn-xs" onclick="this.closest('tr').remove()"><i class="fas fa-trash"></i></button></td>
  </tr>`;
}
function addOutputRow(){ $('meat-outputs').querySelector('tbody').insertAdjacentHTML('beforeend', buildOutputRow({})); }

function buildExtrasTable(rows){
  return `
    <div class="table-container"><table id="meat-extras">
      <thead><tr><th>Názov nákladu</th><th>Suma (€)</th><th>Akcia</th></tr></thead>
      <tbody>
        ${rows.map(buildExtraRow).join('')}
      </tbody>
    </table></div>`;
}
function buildExtraRow(r={}, idx=Date.now()){
  return `<tr data-row="${idx}">
    <td><input class="meat-extra-name" value="${esc(r.name||'')}"></td>
    <td><input type="number" class="meat-extra-amount" step="0.01" value="${r.amount_eur||''}"></td>
    <td><button class="btn btn-danger btn-xs" onclick="this.closest('tr').remove()"><i class="fas fa-trash"></i></button></td>
  </tr>`;
}
function addExtraRow(){ $('meat-extras').querySelector('tbody').insertAdjacentHTML('beforeend', buildExtraRow({})); }

async function saveBreakdown(){
  const f = $('meat-new-form');
  const header = Object.fromEntries(new FormData(f).entries());

  // collect outputs
  const outputs = Array.from(document.querySelectorAll('#meat-outputs tbody tr')).map(tr=>{
    return {
      product_id: tr.querySelector('.meat-out-product').value,
      weight_kg: tr.querySelector('.meat-out-weight').value
    };
  }).filter(x=>x.product_id && x.weight_kg);

  const extras = Array.from(document.querySelectorAll('#meat-extras tbody tr')).map(tr=>{
    return {
      name: tr.querySelector('.meat-extra-name').value,
      amount_eur: tr.querySelector('.meat-extra-amount').value
    };
  }).filter(x=>x.name && x.amount_eur);

  const payload = { header, outputs, extras };
  const res = await apiM('/api/kancelaria/meat/breakdown/save', { method:'POST', body:payload });
  if (res?.error){ showStatus(res.error, true); return; }
  if (!res?.breakdown_id){ showStatus('Záznam sa nepodarilo uložiť (chýba breakdown_id).', true); return; }

  showStatus('Záznam uložený a prepočítaný.', false);
  // načítaj výsledok
  const data = await apiM('/api/kancelaria/meat/breakdown?id='+res.breakdown_id);
  if (data?.header) renderResults(data);
  else showStatus('Nepodarilo sa načítať výsledok.', true);
}

function renderResults(data){
  const el = $('meat-results');
  const b = data.header;
  const results = data.results || [];
  const extras = data.extras || [];

  let html = `
    <div class="analysis-card">
      <h4>Výsledky – rozrábka #${b.id} (${b.breakdown_date})</h4>
      <div class="table-container"><table>
        <thead><tr>
          <th>Produkt</th><th>Váha (kg)</th><th>Výťažnosť (%)</th><th>Náklad €/kg</th><th>Predaj €/kg</th><th>Marža €/kg</th><th>Zisk (€)</th>
        </tr></thead>
        <tbody>
          ${results.map(r=>`
            <tr>
              <td>${esc(r.product_name)}</td>
              <td>${Number(r.weight_kg).toFixed(3)}</td>
              <td>${Number(r.yield_pct).toFixed(4)}</td>
              <td>${Number(r.cost_per_kg_eur).toFixed(4)}</td>
              <td>${Number(r.selling_price_eur_kg_snap).toFixed(3)}</td>
              <td>${Number(r.margin_eur_per_kg).toFixed(4)}</td>
              <td>${Number(r.profit_eur).toFixed(2)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table></div>

      <div style="display:flex; gap:.5rem; margin-top:.75rem;">
        <a class="btn btn-secondary" href="/report/meat/breakdown?id=${b.id}" target="_blank"><i class="fas fa-print"></i> Tlač</a>
        <a class="btn btn-secondary" href="/api/kancelaria/meat/breakdown/export?id=${b.id}"><i class="fas fa-file-excel"></i> Export XLSX</a>
      </div>
    </div>
  `;
  el.innerHTML = html;
}

// ------- História -------------------------------------------------
function initHistory(){
  fillMaterialsSelects();
  $('meat-hist-load').onclick = loadHistory;
}

async function loadHistory(){
  const params = new URLSearchParams();
  const mid = $('meat-hist-material').value; if (mid) params.set('material_id', mid);
  const df  = $('meat-hist-from').value;     if (df)  params.set('date_from', df);
  const dt  = $('meat-hist-to').value;       if (dt)  params.set('date_to', dt);
  const sup = $('meat-hist-sup').value;      if (sup) params.set('supplier', sup);

  const rows = await apiM('/api/kancelaria/meat/breakdowns?'+params.toString());
  const div = $('meat-hist-table');

  if (!Array.isArray(rows)) {
    console.warn('breakdowns endpoint nevrátil pole:', rows);
    div.innerHTML = '<p class="error">Nepodarilo sa načítať históriu (skontroluj route /api/kancelaria/meat/breakdowns).</p>';
    return;
  }
  if (!rows.length){ div.innerHTML='<p>Žiadne dáta.</p>'; return; }

  let html = '<div class="table-container"><table><thead><tr><th>Dátum</th><th>Surovina</th><th>Dodávateľ</th><th>Vstup (kg)</th><th>€ celkom</th><th>Akcie</th></tr></thead><tbody>';
  rows.forEach(r=>{
    html += `<tr>
      <td>${r.breakdown_date}</td>
      <td>${esc(r.material_name)}</td>
      <td>${esc(r.supplier||'')}</td>
      <td>${Number(r.input_weight_kg).toFixed(3)}</td>
      <td>${Number(r.purchase_total_cost_eur||0).toFixed(2)}</td>
      <td><a class="btn btn-secondary btn-xs" href="/report/meat/breakdown?id=${r.id}" target="_blank"><i class="fas fa-file"></i> Detail</a></td>
    </tr>`;
  });
  html += '</tbody></table></div>';
  div.innerHTML = html;
}

// ------- Odhad ----------------------------------------------------
function initEstimate(){
  fillMaterialsSelects();
  // extras
  $('meat-est-extras').innerHTML = buildEstExtrasTable([]);
  $('meat-est-add-extra').onclick = ()=> addEstExtraRow();
  $('meat-est-run').onclick = runEstimate;
}

function buildEstExtrasTable(rows){
  return `
    <div class="table-container"><table id="meat-est-extras-table">
      <thead><tr><th>Názov nákladu</th><th>Suma (€)</th><th>Akcia</th></tr></thead>
      <tbody>
        ${rows.map(r=> buildEstExtraRow(r)).join('')}
      </tbody>
    </table></div>`;
}
function buildEstExtraRow(r={}, idx=Date.now()){
  return `<tr data-row="${idx}">
    <td><input class="meat-est-extra-name" value="${esc(r.name||'')}"></td>
    <td><input type="number" class="meat-est-extra-amount" step="0.01" value="${r.amount_eur||''}"></td>
    <td><button class="btn btn-danger btn-xs" onclick="this.closest('tr').remove()"><i class="fas fa-trash"></i></button></td>
  </tr>`;
}
function addEstExtraRow(){
  $('meat-est-extras-table').querySelector('tbody').insertAdjacentHTML('beforeend', buildEstExtraRow({}));
}

async function runEstimate(){
  const material_id = $('meat-est-material').value;
  const planned_weight_kg = Number($('meat-est-weight').value||0);
  const expected_purchase_unit_price = Number($('meat-est-price').value||0);
  const supplier = $('meat-est-sup').value || null;
  const date_from= $('meat-est-from').value || null;
  const date_to  = $('meat-est-to').value || null;

  const extras = Array.from(document.querySelectorAll('#meat-est-extras-table tbody tr')).map(tr=>({
    name: tr.querySelector('.meat-est-extra-name').value,
    amount_eur: tr.querySelector('.meat-est-extra-amount').value
  })).filter(x=>x.name && x.amount_eur);

  const payload = { material_id: Number(material_id), planned_weight_kg, expected_purchase_unit_price, supplier, date_from, date_to, extras };
  const res = await apiM('/api/kancelaria/meat/estimate',{method:'POST', body:payload});
  const box = $('meat-est-results');

  if (res?.error){ box.innerHTML = `<p class="error">${esc(res.error)}</p>`; return; }
  if (!res || !Array.isArray(res.rows)) { box.innerHTML = '<p class="error">Chybná odpoveď od API.</p>'; return; }

  // cache produktov – ak ešte neboli načítané
  if (!Array.isArray(MEAT_PRODUCTS_CACHE) || !MEAT_PRODUCTS_CACHE.length) {
    const prods = await apiM('/api/kancelaria/meat/products');
    MEAT_PRODUCTS_CACHE = Array.isArray(prods) ? prods : [];
  }

  const rows = res.rows||[];
let html = `
  <div class="analysis-card">
    <h4>Odhad výsledkov</h4>
    <div class="table-container"><table>
        <thead><tr>
          <th>Produkt</th><th>Váha (kg)</th><th>Výťažnosť (%)</th><th>Náklad €/kg</th><th>Predaj €/kg</th><th>Marža €/kg</th><th>Zisk (€)</th>
        </tr></thead>
        <tbody>
          ${rows.map(r=>{
            const p = (MEAT_PRODUCTS_CACHE||[]).find(x=>String(x.id)===String(r.product_id));
            return `<tr>
              <td>${esc(p ? p.name : '#'+r.product_id)}</td>
              <td>${Number(r.weight_kg).toFixed(3)}</td>
              <td>${Number(r.yield_pct).toFixed(4)}</td>
              <td>${Number(r.cost_per_kg_eur).toFixed(4)}</td>
              <td>${Number(r.selling_price_eur_kg).toFixed(3)}</td>
              <td>${Number(r.margin_eur_per_kg).toFixed(4)}</td>
              <td>${Number(r.profit_eur).toFixed(2)}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table></div>
    </div>
  `;
  box.innerHTML = html;
 const sumKg = rows.reduce((a,b)=> a + Number(b.weight_kg||0), 0);
html += `
  <div style="display:flex; gap:.5rem; flex-wrap:wrap; margin:.5rem 0;">
    <span class="kpi-badge">Plánovaná nákupná váha: <strong>${Number(res.planned_weight_kg).toFixed(3)} kg</strong></span>
    <span class="kpi-badge">Priem. tolerancia straty: <strong>${Number(res.avg_tolerance_pct||0).toFixed(2)} %</strong></span>
    <span class="kpi-badge">Efektívna výstupná váha: <strong>${Number(res.effective_output_weight_kg||0).toFixed(3)} kg</strong></span>
    <span class="kpi-badge">Súčet odhadovaných váh: <strong>${sumKg.toFixed(3)} kg</strong></span>
  </div>
`;
}

/* Auto-register */
(function(){
  const root = document.getElementById('section-meat-calc');
  if (root) initializeMeatCalcModule();
})();
