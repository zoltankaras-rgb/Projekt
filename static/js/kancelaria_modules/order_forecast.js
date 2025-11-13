// static/js/kancelaria_modules/order_forecast.js
// =================================================================
// === SUB-MODUL KANCELÁRIA: EXPEDIČNÝ PLÁN / 7-DŇOVÝ PREHĽAD =====
// =================================================================

function initializeOrderForecastModule() {
  const container = document.getElementById('section-order-forecast');
  if (!container) return;

  // Shell s tabmi – jednotný štýl tlačidiel
  container.innerHTML = `
    <div class="btn-grid" style="margin-bottom:.5rem;">
      <button class="btn btn-primary js-tab" data-tab="forecast">7-dňový Prehľad</button>
      <button class="btn btn-secondary js-tab" data-tab="purchase">Návrh Nákupu Tovaru</button>
      <button class="btn btn-secondary js-tab" data-tab="promotions">Správa Akcií</button>
    </div>

    <div id="ofc-views" class="stat-card" style="padding:1rem;">
      <div id="forecast-tab-content"   data-view="forecast"   style="display:block;"></div>
      <div id="purchase-tab-content"   data-view="purchase"   style="display:none;"></div>
      <div id="promotions-tab-content" data-view="promotions" style="display:none;"></div>
    </div>
  `;

  const tabs = container.querySelectorAll('.js-tab');
  const viewsWrap = container.querySelector('#ofc-views');

  function setActiveTab(key) {
    // prepni vizuál tlačidiel
    tabs.forEach(btn => {
      btn.classList.remove('btn-primary'); btn.classList.add('btn-secondary');
      if (btn.dataset.tab === key) { btn.classList.remove('btn-secondary'); btn.classList.add('btn-primary'); }
    });
    // zobraz iba aktívny view
    Array.from(viewsWrap.children).forEach(v => v.style.display = (v.getAttribute('data-view') === key ? 'block' : 'none'));

    // lazy-load obsahu podľa tabu
    switch (key) {
      case 'forecast':  loadAndRenderForecast(); break;
      case 'purchase':  loadAndRenderPurchaseSuggestion(); break;
      case 'promotions':loadAndRenderPromotionsManager(); break;
    }
  }

  tabs.forEach(btn => btn.addEventListener('click', () => setActiveTab(btn.dataset.tab)));

  // default view
  setActiveTab('forecast');
}

// ---- spoločné helpers (nezávislé od common.js, aby POST bol vždy POST) ----
async function getJSON(url) {
  const r = await fetch(url, { method: 'GET', credentials: 'same-origin' });
  if (!r.ok) throw new Error(await r.text());
  const ct = r.headers.get('content-type') || '';
  return ct.includes('application/json') ? r.json() : r.text();
}
async function postJSON(url, payload) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type':'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(payload || {})
  });
  if (!r.ok) throw new Error(await r.text());
  const ct = r.headers.get('content-type') || '';
  return ct.includes('application/json') ? r.json() : r.text();
}

// ---------- 7-dňový prehľad (B2B + B2C z JEDINÉHO volania) ----------
async function loadAndRenderForecast() {
  const container = document.getElementById('forecast-tab-content');
  if (!container) return;
  container.innerHTML = '<div class="text-muted" style="padding:1rem;">Načítavam dáta...</div>';

  // 1) Načítaj jednotný forecast (existujúci B2B endpoint)
  //    Ak backend pridá B2C dáta v tom istom payload-e (napr. 'b2c_forecast'/'forecast_b2c'/'b2c'),
  //    frontend ich automaticky zlúči a zobrazí súčty.
  let base;
  try {
    base = await getJSON('/api/kancelaria/get_7_day_forecast');
  } catch (e) {
    container.innerHTML = `<div class="error" style="padding:1rem;">Chyba pri načítaní prehľadu: ${e.message}</div>`;
    return;
  }

  // 2) Zisti, či payload obsahuje aj B2C sekciu a zmergeuj; inak zobraz B2B tak ako je
  const b2cCandidate =
    (base && (base.b2c_forecast || base.forecast_b2c || base.b2c)) ? {
      dates: base.dates || [],
      forecast: (base.b2c_forecast || base.forecast_b2c || base.b2c) || {}
    } : null;

  const payload = (b2cCandidate && b2cCandidate.forecast)
    ? mergeForecastPayloads(base, b2cCandidate)   // B2B + B2C
    : base;                                       // len B2B (bez chýbajúcich endpointov)

  // 3) Render
  try {
    const data = payload;
    if (!data?.forecast || Object.keys(data.forecast).length === 0) {
      container.innerHTML = '<div class="text-muted" style="padding:1rem;">Na nasledujúcich 7 dní nie sú žiadne objednávky.</div>';
      return;
    }

    const dates = (data.dates || []).slice(); // pole YYYY-MM-DD
    const formattedDates = dates.map(d => new Date(d).toLocaleDateString('sk-SK', { day: '2-digit', month: '2-digit' }));

    let finalHtml = `<p>Prehľad potreby produktov na základe B2B${b2cCandidate ? ' aj B2C' : ''} objednávok. Riadky s deficitom sú zvýraznené.</p>`;

    for (const category of Object.keys(data.forecast)) {
      finalHtml += `<h4 style="margin-top:1rem;">${category}</h4>`;
      let tableHtml = `
        <div class="table-container" style="max-height:none;">
          <table style="table-layout:fixed;">
            <thead>
              <tr>
                <th style="width:25%;">Produkt</th>
                <th style="width:10%;">Sklad</th>
                ${formattedDates.map(d => `<th style="width:7%;">${d}</th>`).join('')}
                <th style="width:10%;">Potreba</th>
                <th style="width:10%;">Deficit</th>
                <th style="width:11%;">Akcia</th>
              </tr>
            </thead>
            <tbody>
      `;

      (data.forecast[category] || []).forEach(product => {
        // súčet za všetky dni
        const total = dates.reduce((s, d) => s + (Number(product.daily_needs?.[d] || 0)), 0);
        const stockNum = parseStockNum(product.stock_display, product.mj);
        const deficit = Math.max(total - stockNum, 0);

        const isDeficit = deficit > 0;
        const deficitDisplay = isDeficit ? `${Math.ceil(deficit)} ${product.mj}` : '0';
        const actionBtn = (isDeficit && product.isManufacturable)
          ? `<button class="btn btn-primary" style="margin:0;" onclick="openUrgentProductionModal('${(product.name||'').replace(/'/g, "\\'")}', ${Math.ceil(deficit)})">Vytvoriť výrobu</button>`
          : '';

        tableHtml += `
          <tr ${isDeficit ? 'style="background:#fee2e2;"' : ''}>
            <td><strong>${product.name}</strong></td>
            <td>${product.stock_display}</td>
            ${dates.map(d => {
              const v = Number(product.daily_needs?.[d] || 0);
              return `<td>${v > 0 ? `${v} ${product.mj}` : ''}</td>`;
            }).join('')}
            <td>${total} ${product.mj}</td>
            <td class="${isDeficit ? 'loss' : ''}">${deficitDisplay}</td>
            <td>${actionBtn}</td>
          </tr>
        `;
      });

      tableHtml += `</tbody></table></div>`;
      finalHtml += tableHtml;
    }

    container.innerHTML = finalHtml;
  } catch (e) {
    container.innerHTML = `<div class="error" style="padding:1rem;">Chyba pri vykreslení prehľadu: ${e.message}</div>`;
  }
}

// Zlúči dva payloady forecastu (B2B + B2C) do jedného
function mergeForecastPayloads(a, b) {
  const dates = Array.from(new Set([...(a?.dates||[]), ...(b?.dates||[])])).sort();
  const out = { dates, forecast: {} };

  // pomocné mapovanie podľa kategórie + kľúča produktu (name|mj)
  const add = (src) => {
    if (!src?.forecast) return;
    for (const cat of Object.keys(src.forecast)) {
      out.forecast[cat] = out.forecast[cat] || [];
      const indexByKey = new Map(out.forecast[cat].map((p, i) => [`${p.name}__${p.mj}`, i]));

      for (const p of src.forecast[cat]) {
        const key = `${p.name}__${p.mj}`;
        let target;
        if (indexByKey.has(key)) {
          target = out.forecast[cat][indexByKey.get(key)];
        } else {
          // nový produkt v kategórii
          target = {
            name: p.name,
            mj: p.mj,
            stock_display: p.stock_display || '—',
            isManufacturable: !!p.isManufacturable,
            daily_needs: {}
          };
          dates.forEach(d => target.daily_needs[d] = 0);
          out.forecast[cat].push(target);
          indexByKey.set(key, out.forecast[cat].length - 1);
        }

        // OR pre "je vyrobiteľný"
        target.isManufacturable = !!(target.isManufacturable || p.isManufacturable);
        // ak má "krajší" stock_display (nie prázdny), zober si ho
        if ((p.stock_display || '').length > (target.stock_display || '').length) {
          target.stock_display = p.stock_display;
        }

        // sčítanie denných potrieb
        dates.forEach(d => {
          const addVal = Number(p.daily_needs?.[d] || 0);
          target.daily_needs[d] = Number(target.daily_needs[d] || 0) + addVal;
        });
      }
    }
  };

  add(a); add(b);

  // dopočítaj total/deficit (deficit sa znova prepočíta pri rendri)
  for (const cat of Object.keys(out.forecast)) {
    out.forecast[cat].forEach(p => {
      p.total_needed = out.dates.reduce((s, d) => s + Number(p.daily_needs?.[d] || 0), 0);
      p.deficit = Math.max(p.total_needed - parseStockNum(p.stock_display, p.mj), 0);
    });
  }
  return out;
}

// Z "120 kg" → 120 (ak jednotka sedí), inak hrubý pokus o číslo; keď nič, 0
function parseStockNum(stock_display, mj) {
  if (!stock_display) return 0;
  const m = String(stock_display).match(/([0-9]+(?:[.,][0-9]+)?)\s*[a-zA-Z]*/);
  if (!m) return 0;
  const n = parseFloat(m[1].replace(',', '.'));
  return Number.isFinite(n) ? n : 0;
}


// ---------- Návrh nákupu ----------
async function loadAndRenderPurchaseSuggestion() {
  const container = document.getElementById('purchase-tab-content');
  if (!container) return;
  container.innerHTML = '<div class="text-muted" style="padding:1rem;">Načítavam návrh nákupu...</div>';

  try {
    const suggestions = await getJSON('/api/kancelaria/get_goods_purchase_suggestion');
    if (!suggestions || !suggestions.length) {
      container.innerHTML = '<div class="text-muted" style="padding:1rem;">Aktuálne nie je potrebné doobjednať žiadny tovar.</div>';
      return;
    }

    let tableHtml = `
      <div class="table-container" style="max-height:none;">
        <table>
          <thead>
            <tr>
              <th>Názov Tovaru</th><th>Aktuálny Sklad</th><th>Min. Sklad</th><th>Rezervované</th><th>Návrh na Nákup</th><th>Poznámka</th>
            </tr>
          </thead>
          <tbody>
    `;

    suggestions.forEach(item => {
      tableHtml += `
        <tr>
          <td>${item.name}</td>
          <td>${Number(item.stock).toFixed(2)} ${item.unit}</td>
          <td>${Number(item.min_stock).toFixed(2)} ${item.unit}</td>
          <td>${Number(item.reserved).toFixed(2)} ${item.unit}</td>
          <td class="loss">${Number(item.suggestion).toFixed(2)} ${item.unit}</td>
          <td>${item.is_promo ? '<span class="btn btn-danger" style="padding:.125rem .4rem; font-size:.8rem;">PREBIEHA AKCIA!</span>' : ''}</td>
        </tr>
      `;
    });

    tableHtml += `</tbody></table></div>`;
    container.innerHTML = tableHtml;
  } catch (e) {
    container.innerHTML = `<div class="error" style="padding:1rem;">${e.message}</div>`;
  }
}

// ---------- Správa akcií ----------
async function loadAndRenderPromotionsManager() {
  const container = document.getElementById('promotions-tab-content');
  if (!container) return;
  container.innerHTML = '<div class="text-muted" style="padding:1rem;">Načítavam správu akcií...</div>';

  try {
    const data = await getJSON('/api/kancelaria/get_promotions_data');
    const { chains = [], promotions = [], products = [] } = data || {};
    const today = new Date().toISOString().split('T')[0];

    const productOptions = products.map(p => `<option value="${p.ean}">${p.name}</option>`).join('');
    const chainOptions   = chains.map(c => `<option value="${c.id}">${c.name}</option>`).join('');

    const promosRows = promotions.map(p => `
      <tr>
        <td>${p.chain_name}</td>
        <td>${p.product_name}</td>
        <td>${new Date(p.start_date).toLocaleDateString('sk-SK')} - ${new Date(p.end_date).toLocaleDateString('sk-SK')}</td>
        <td>${Number(p.sale_price_net).toFixed(2)} €</td>
        <td><button class="btn btn-danger" style="margin:0;" onclick="deletePromotion(${p.id})"><i class="fas fa-trash"></i></button></td>
      </tr>
    `).join('');

    container.innerHTML = `
      <div class="form-grid">
        <div>
          <h4>Vytvoriť Novú Akciu</h4>
          <form id="add-promotion-form">
            <div class="form-group"><label>Obchodný Reťazec</label><select name="chain_id" required>${chainOptions}</select></div>
            <div class="form-group"><label>Produkt v Akcii</label><select name="ean" required>${productOptions}</select></div>
            <div class="form-grid">
              <div class="form-group"><label>Platnosť Od</label><input type="date" name="start_date" value="${today}" required></div>
              <div class="form-group"><label>Platnosť Do</label><input type="date" name="end_date" value="${today}" required></div>
            </div>
            <div class="form-group"><label>Cena Počas Akcie (bez DPH)</label><input type="number" name="sale_price_net" step="0.01" required></div>
            <button type="submit" class="btn btn-success" style="width:100%;">Uložiť Akciu</button>
          </form>
        </div>

        <div>
          <h4>Správa Obchodných Reťazcov</h4>
          <ul id="chains-list">${chains.map(c => `<li>${c.name} <button onclick="manageChain('delete', ${c.id})" class="btn btn-danger" style="padding:.125rem .4rem; font-size:.8rem; margin-left:.5rem;">X</button></li>`).join('')}</ul>
          <div class="form-group" style="display:flex; gap:.5rem; align-items:flex-end;">
            <div style="flex:1;">
              <label>Nový reťazec:</label>
              <input type="text" id="new-chain-name">
            </div>
            <button onclick="manageChain('add')" class="btn btn-primary" style="margin:0; height:45px;">Pridať</button>
          </div>
        </div>
      </div>

      <h4 style="margin-top:1rem;">Prehľad Naplánovaných Akcií</h4>
      <div class="table-container" style="max-height:none;">
        <table>
          <thead><tr><th>Reťazec</th><th>Produkt</th><th>Trvanie</th><th>Akciová Cena</th><th></th></tr></thead>
          <tbody>${promosRows}</tbody>
        </table>
      </div>
    `;

    // submit handler – vždy POST (cez postJSON)
    document.getElementById('add-promotion-form').onsubmit = saveNewPromotion;
  } catch (e) {
    container.innerHTML = `<div class="error" style="padding:1rem;">${e.message}</div>`;
  }
}

async function saveNewPromotion(e) {
  e.preventDefault();
  const formData = new FormData(e.target);
  const payload = Object.fromEntries(formData.entries());
  try {
    await postJSON('/api/kancelaria/save_promotion', payload);
    e.target.reset();
    loadAndRenderPromotionsManager();
  } catch (err) {
    alert('Chyba pri ukladaní akcie: ' + err.message);
  }
}

async function manageChain(action, id = null) {
  const payload = { action };
  if (action === 'add') {
    payload.name = (document.getElementById('new-chain-name').value || '').trim();
    if (!payload.name) return;
  } else {
    payload.id = id;
  }
  try {
    await postJSON('/api/kancelaria/manage_promotion_chain', payload);
    loadAndRenderPromotionsManager();
  } catch (err) {
    alert('Chyba: ' + err.message);
  }
}

async function deletePromotion(id) {
  if (!confirm('Naozaj chcete vymazať túto akciu?')) return;
  try {
    await postJSON('/api/kancelaria/delete_promotion', { id });
    loadAndRenderPromotionsManager();
  } catch (err) {
    alert('Chyba mazania: ' + err.message);
  }
}

// ---------- Urgentná výroba ----------
function openUrgentProductionModal(productName, requiredQty) {
  const today = new Date().toISOString().split('T')[0];
  const contentPromise = () => Promise.resolve({
    html: `
      <form id="urgent-production-form">
        <p>Vytvárate urgentnú výrobnú požiadavku pre produkt:</p>
        <h3 style="text-align:left; border:none; margin-bottom:1rem;">${productName}</h3>
        <div class="form-group">
          <label for="urgent-prod-qty">Požadované množstvo (kg):</label>
          <input type="number" id="urgent-prod-qty" value="${requiredQty}" step="any" required>
        </div>
        <div class="form-group">
          <label for="urgent-prod-date">Požadovaný dátum výroby:</label>
          <input type="date" id="urgent-prod-date" value="${today}" required>
        </div>
        <button type="submit" class="btn btn-success" style="width:100%;">Odoslať požiadavku do výroby</button>
      </form>
    `,
    onReady: () => {
      document.getElementById('urgent-production-form').onsubmit = async (e) => {
        e.preventDefault();
        const data = {
          productName: productName,
          quantity: document.getElementById('urgent-prod-qty').value,
          productionDate: document.getElementById('urgent-prod-date').value
        };
        try {
          await postJSON('/api/kancelaria/create_urgent_task', data);
          document.getElementById('modal-container').style.display = 'none';
          loadAndRenderForecast();
        } catch (err) {
          alert('Chyba odoslania: ' + err.message);
        }
      };
    }
  });
  showModal('Urgentná výrobná požiadavka', contentPromise);
}

// (voliteľne) export na globál
window.initializeOrderForecastModule = initializeOrderForecastModule;
