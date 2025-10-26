// =================================================================
// === SUB-MODUL KANCELÁRIA: SPRÁVA ERP (opravené, bez globálnych kolízií) ===
// =================================================================
(function (window) {
  'use strict';
let __officeBaseData = null;

async function ensureOfficeDataIsLoaded(){
  if (window.__officeBaseData) return;

  async function safeFetch(url){
    try{
      const res = await fetch(url, { credentials: 'same-origin' });
      const ct = (res.headers.get('content-type')||'').toLowerCase();
      if (!res.ok || !ct.includes('application/json')) return null;
      return await res.json();
    }catch(_){ return null; }
  }

  let data = await safeFetch('/api/kancelaria/baseData');
  if (!data) data = await safeFetch('/api/kancelaria/getKancelariaBaseData');

  if (!data){
    console.warn('[ERP] baseData sa nepodarilo načítať – používam fallback hodnoty.');
    window.__officeBaseData = {
      productsWithoutRecipe: [],
      recipeCategories: [],
      itemTypes: ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál']
    };
    return;
  }

  window.__officeBaseData = {
    productsWithoutRecipe: data.productsWithoutRecipe || data.products_without_recipe || data.products || [],
    recipeCategories:      data.recipeCategories      || data.recipe_categories      || data.categories || [],
    itemTypes:             data.itemTypes             || data.item_types             || data.stockCategories || ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál'],
  };
}


function getOfficeData(){
  return window.__officeBaseData || {
    productsWithoutRecipe: [],
    recipeCategories: [],
    itemTypes: ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál']
  };
}


  // ---- ZÁVISLOSTI (globálne utility z tvojho projektu) ----
  const apiRequest = window.apiRequest;                      // musí existovať
/* patched: removed duplicate ensureOfficeDataIsLoaded shadow declaration */
/* patched: removed duplicate getOfficeData shadow declaration */
// ---- Pomocné / escape ----
  function escapeHtml(s){ return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
  const byLocale = (a,b) => String(a).localeCompare(String(b),'sk');

  // ---- Fallbacky na modal/status (ak showModal/hideModal/showStatus chýbajú) ----
  const status = (msg, isError=false) => {
    if (typeof window.showStatus === 'function') window.showStatus(msg, !!isError);
    else alert(msg);
  };
  async function openModalCompat(title, contentFactory){
    if (typeof window.showModal === 'function') {
      return window.showModal(title, contentFactory);
    }
    // jednoduchý zabudovaný modal fallback
    let mc = document.getElementById('modal-container');
    if (!mc){
      mc = document.createElement('div');
      mc.id = 'modal-container';
      document.body.appendChild(mc);
    }
    mc.innerHTML = `
  <div class="__compat-backdrop" style="
    position:fixed; inset:0; display:flex; align-items:center; justify-content:center;
    background:rgba(0,0,0,.45); z-index:9999;">
    <div class="__compat-card" style="
      background:#fff; width:92%; max-width:950px; border-radius:8px;
      box-shadow:0 24px 64px rgba(0,0,0,.33);">
      <div style="display:flex; align-items:center; justify-content:space-between;
                  padding:12px 16px; border-bottom:1px solid #eee;">
        <h3 style="margin:0;">${escapeHtml(title)}</h3>
        <button id="__compat-close" class="btn-danger" style="margin:0;">×</button>
      </div>
      <div id="__compat-body" style="padding:16px;"></div>
    </div>
  </div>`;

    mc.style.display = 'block';
    const res = await (typeof contentFactory === 'function' ? contentFactory() : contentFactory);
    const body = mc.querySelector('#__compat-body');
    body.innerHTML = res?.html || '';
    if (typeof res?.onReady === 'function') { try { res.onReady(); } catch(e){ console.error(e); } }
    mc.querySelector('#__compat-close').addEventListener('click', ()=>{ mc.style.display='none'; });
    return res;
  }
  function hideModalCompat(){
    if (typeof window.hideModal === 'function') { try { window.hideModal(); return; } catch(e){} }
    const mc = document.getElementById('modal-container');
    if (mc) mc.style.display = 'none';
  }

  // ---- LOKÁLNY STAV (nič globálne okrem initializeErpAdminModule) ----
  const state = {
    catalog: null,              // dáta pre katalóg
    warehouse: null,            // { maso:[], koreniny:[], obal:[], pomocny_material:[] }
    warehouseLoadedAt: 0
  };

  // ---- Kategórie / mapovania ----
  function normalizeCatKey(x){
    const c = String(x||'').toLowerCase().trim();
    if (c === 'mäso' || c === 'maso' || c === 'meat') return 'maso';
    if (c.startsWith('koren')) return 'koreniny';
    if (c.startsWith('obal'))  return 'obal';
    if (c.startsWith('pomoc')) return 'pomocny_material';
    return c;
  }
  function displayLabelForCat(k){
    switch (normalizeCatKey(k)){
      case 'maso': return 'Mäso';
      case 'koreniny': return 'Koreniny';
      case 'obal': return 'Obaly';
      case 'pomocny_material': return 'Pomocný materiál';
      default: return k;
    }
  }
  function buildOptions(names, selected=''){
    const s = String(selected||'');
    return (names||[]).map(n=>{
      const v = String(n);
      return `<option value="${escapeHtml(v)}"${v===s?' selected':''}>${escapeHtml(v)}</option>`;
    }).join('');
  }
  function findCategoryForName(name){
    const nm = String(name||'');
    if (!state.warehouse) return null;
    for (const k of Object.keys(state.warehouse)){
      if (state.warehouse[k].includes(nm)) return k;
    }
    return null;
  }

  // ---- Allowed names pre kategórie (API) ----
  async function fetchAllowedNames(categoryKey){
    const cat = normalizeCatKey(categoryKey);
    const url = `/api/kancelaria/stock/allowed-names?category=${encodeURIComponent(cat)}`;
    try{
      const resp = await apiRequest(url);
      if (Array.isArray(resp?.items) && resp.items.length){
        return resp.items.map(it => String(it.name)).filter(Boolean);
      }
      if (Array.isArray(resp?.names)){
        return resp.names.map(String).filter(Boolean);
      }
    }catch(_){}
    return [];
  }
  async function ensureWarehouseCache(force=false){
    if (!force && state.warehouse && (Date.now()-state.warehouseLoadedAt)<30000){
      return state.warehouse;
    }
    const cats = ['maso','koreniny','obal','pomocny_material'];
    const results = await Promise.all(cats.map(c=>fetchAllowedNames(c)));
    const out = {};
    cats.forEach((c,i)=>{ out[c] = (results[i]||[]).sort(byLocale); });
    state.warehouse = out;
    state.warehouseLoadedAt = Date.now();
    return out;
  }

  // =================================================================
  // === UI ROOT (EXPORTOVANÉ) =======================================
  // =================================================================
 function initializeErpAdminModule(){
  const sec = document.getElementById('section-erp-admin');
  if (!sec) return;

  sec.innerHTML = `
    <div class="stat-card" style="margin-bottom:.75rem;">
      <h3 style="margin:0 0 .5rem 0;">Správa ERP Systému</h3>
      <div class="btn-grid" style="margin:0;">
        <button id="erp-btn-catalog" class="btn-secondary"><i class="fas fa-book"></i> Správa Katalógu</button>
        <button id="erp-btn-minstock" class="btn-secondary"><i class="fas fa-layer-group"></i> Min. Zásoby</button>
        <button id="erp-btn-newrecipe" class="btn-primary"><i class="fas fa-plus"></i> Nový Recept</button>
        <button id="erp-btn-editrecipe" class="btn-secondary"><i class="fas fa-edit"></i> Upraviť Recept</button>
        <button id="erp-btn-slicing" class="btn-secondary" style="grid-column: span 2;"><i class="fas fa-cut"></i> Krájané Produkty</button>
      </div>
    </div>
    <div id="erp-admin-content"></div>
  `;

  const mount = (factory)=> {
    const host = document.getElementById('erp-admin-content');
    host.innerHTML = '<div class="stat-card"><i class="fa-solid fa-spinner fa-spin"></i> Načítavam…</div>';
    Promise.resolve(factory()).then(res=>{
      host.innerHTML = res?.html || '';
      if (typeof res?.onReady === 'function') res.onReady();
    }).catch(()=>{
      host.innerHTML = '<div class="stat-card">Chyba načítania: ' + (err && (err.message || String(err))) + '</div>';
      console.error('[ERP] Render error:', err);
      
    });
  };

  document.getElementById('erp-btn-catalog').onclick   = ()=> mount(viewCatalogManagement);
  document.getElementById('erp-btn-minstock').onclick  = ()=> mount(viewMinStock);
  document.getElementById('erp-btn-slicing').onclick   = ()=> mount(viewSlicingManagement);
  document.getElementById('erp-btn-newrecipe').onclick = ()=> mount(viewCreateRecipeInline);
  document.getElementById('erp-btn-editrecipe').onclick= ()=> mount(viewEditRecipeListInline);


  // default – otvor rovno Nový recept
  document.getElementById('erp-btn-newrecipe').click();
}

  // =================================================================
  // === KATALÓG =====================================================
  // =================================================================
  async function viewCatalogManagement(){
    state.catalog = await apiRequest('/api/kancelaria/getCatalogManagementData');

    let tableHtml = 'Žiadne položky v katalógu.';
    if (state.catalog?.products?.length){
      tableHtml = `<table>
        <thead><tr><th>EAN</th><th>Názov</th><th>Typ</th><th>Kategórie</th><th>DPH</th><th>Akcia</th></tr></thead>
        <tbody>${
          state.catalog.products.map(p => `
            <tr>
              <td>${escapeHtml(p.ean)}</td>
              <td>${escapeHtml(p.nazov_vyrobku)}</td>
              <td>${escapeHtml(p.typ_polozky)}</td>
              <td>Recept: ${escapeHtml(p.kategoria_pre_recepty || 'N/A')}<br>Predaj: ${escapeHtml(p.predajna_kategoria || 'N/A')}</td>
              <td>${p.dph ? parseFloat(p.dph).toFixed(2) : '0.00'} %</td>
              <td><button class="btn-warning btn-edit-item" data-ean="${escapeHtml(p.ean)}" style="margin:0;width:auto;"><i class="fas fa-edit"></i></button></td>
            </tr>
          `).join('')
        }</tbody>
      </table>`;
    }

    const opts = (arr, includeEmpty=false, selected=null)=>{
      let html = includeEmpty ? '<option value="">-- nevybrané --</option>' : '';
      html += (arr||[]).map(v=>`<option value="${escapeHtml(v)}"${String(v)===String(selected)?' selected':''}>${escapeHtml(v)}</option>`).join('');
      return html;
    };

    const html = `
      <div class="table-container">${tableHtml}</div>

      <h4 style="margin-top: 2rem;">Pridať novú položku</h4>
      <form id="catalog-add-form">
        <div class="form-grid">
          <div class="form-group"><label>Typ položky</label><select id="cat-new-type" required>${opts(state.catalog.item_types)}</select></div>
          <div class="form-group"><label>Sadzba DPH</label><select id="cat-new-dph" required>${opts((state.catalog.dph_rates||[]).map(r=>r.toFixed(2)))}</select></div>
        </div>
        <div class="form-group"><label>Názov položky</label><input type="text" id="cat-new-name" placeholder="Názov položky" required></div>
        <div class="form-group"><label>EAN kód</label><input type="text" id="cat-new-ean" placeholder="EAN kód" required></div>
        <div class="form-grid">
          <div class="form-group"><label>Kategória pre recepty</label><select id="cat-new-recipe-cat">${opts(state.catalog.recipe_categories,true)}</select></div>
          <div class="form-group"><label>Predajná kategória</label><select id="cat-new-sale-cat">${opts(state.catalog.sale_categories,true)}</select></div>
        </div>
        <button type="submit" class="btn-success" style="width:100%;">Pridať položku do katalógu</button>
      </form>
    `;

    const onReady = () => {
      document.getElementById('catalog-add-form').addEventListener('submit', async (e)=>{
        e.preventDefault();
        const body = {
          new_catalog_item_type: document.getElementById('cat-new-type').value,
          new_catalog_dph:       document.getElementById('cat-new-dph').value,
          new_catalog_name:      document.getElementById('cat-new-name').value,
          new_catalog_ean:       document.getElementById('cat-new-ean').value,
          new_catalog_recipe_category: document.getElementById('cat-new-recipe-cat').value,
          new_catalog_sale_category:   document.getElementById('cat-new-sale-cat').value
        };
        try{
          await apiRequest('/api/kancelaria/addCatalogItem', { method:'POST', body });
          hideModalCompat();
          openModalCompat('Správa Centrálneho Katalógu', viewCatalogManagement);
        }catch(_){}
      });

      document.querySelectorAll('#modal-container .btn-edit-item').forEach(btn=>{
        btn.addEventListener('click', ()=>{
          const ean = btn.dataset.ean;
          openEditCatalogItemModal(ean);
        });
      });
    };

    return { html, onReady };
  }

  function openEditCatalogItemModal(ean){
    const item = state.catalog?.products?.find(p=>p.ean===ean);
    if (!item){ status('Položka nebola nájdená.', true); return; }

    const createOptions = (arr, selected=null, includeEmpty=false)=>{
      let html = includeEmpty ? '<option value="">-- nevybrané --</option>' : '';
      html += (arr||[]).map(v=>`<option value="${escapeHtml(v)}"${String(v)===String(selected)?' selected':''}>${escapeHtml(v)}</option>`).join('');
      return html;
    };

    const html = `
      <div>
        <div class="form-grid">
          <div class="form-group"><label>EAN</label><input id="edit-c-ean" disabled></div>
          <div class="form-group"><label>Typ položky</label><select id="edit-c-type"></select></div>
        </div>
        <div class="form-group"><label>Názov</label><input id="edit-c-name"></div>
        <div class="form-grid">
          <div class="form-group"><label>DPH</label><select id="edit-c-dph"></select></div>
          <div class="form-group"><label>Kategória pre recepty</label><select id="edit-c-recipe-cat"></select></div>
        </div>
        <div class="form-group"><label>Predajná kategória</label><select id="edit-c-sale-cat"></select></div>
        <div class="btn-grid">
          <button id="edit-c-save" class="btn-success">Uložiť</button>
          <button id="edit-c-del"  class="btn-danger">Vymazať</button>
        </div>
      </div>
    `;
    const onReady = ()=>{
      document.getElementById('edit-c-ean').value = item.ean;
      document.getElementById('edit-c-name').value = item.nazov_vyrobku;
      document.getElementById('edit-c-type').innerHTML = createOptions(state.catalog.item_types, item.typ_polozky);
      document.getElementById('edit-c-dph').innerHTML  = createOptions((state.catalog.dph_rates||[]).map(r=>r.toFixed(2)), parseFloat(item.dph).toFixed(2));
      document.getElementById('edit-c-recipe-cat').innerHTML = createOptions(state.catalog.recipe_categories, item.kategoria_pre_recepty, true);
      document.getElementById('edit-c-sale-cat').innerHTML   = createOptions(state.catalog.sale_categories, item.predajna_kategoria, true);

      document.getElementById('edit-c-save').onclick = async ()=>{
        const updated = {
          ean: item.ean,
          nazov_vyrobku: document.getElementById('edit-c-name').value,
          typ_polozky:   document.getElementById('edit-c-type').value,
          dph:           document.getElementById('edit-c-dph').value,
          kategoria_pre_recepty: document.getElementById('edit-c-recipe-cat').value,
          predajna_kategoria:    document.getElementById('edit-c-sale-cat').value
        };
        try{
          await apiRequest('/api/kancelaria/updateCatalogItem', { method:'POST', body: updated });
          hideModalCompat();
          openModalCompat('Správa Centrálneho Katalógu', viewCatalogManagement);
        }catch(_){}
      };

      document.getElementById('edit-c-del').onclick = async ()=>{
        if (!confirm(`Naozaj chcete natrvalo vymazať položku "${item.nazov_vyrobku}"?`)) return;
        try{
          await apiRequest('/api/kancelaria/deleteCatalogItem', { method:'POST', body:{ ean: item.ean } });
          hideModalCompat();
          openModalCompat('Správa Centrálneho Katalógu', viewCatalogManagement);
        }catch(_){}
      };
    };

    openModalCompat(`Upraviť položku: ${escapeHtml(item.nazov_vyrobku)}`, async ()=>({ html, onReady }));
  }

  // =================================================================
  // === MINIMÁLNE ZÁSOBY ===========================================
  // =================================================================
  async function viewMinStock(){
    const products = await apiRequest('/api/kancelaria/getProductsForMinStock');
    let tableHtml = 'Žiadne produkty na nastavenie.';
    if (products?.length){
      tableHtml = `<table><thead><tr><th>Názov Produktu</th><th>Jednotka</th><th>Minimálna zásoba</th></tr></thead><tbody>` +
        products.map(p=>{
          const input = (p.mj === 'ks')
            ? `<input type="number" class="ms-input" data-ean="${escapeHtml(p.ean)}" data-type="ks" value="${escapeHtml(p.minStockKs||'')}" placeholder="ks">`
            : `<input type="number" class="ms-input" data-ean="${escapeHtml(p.ean)}" data-type="kg" value="${escapeHtml(p.minStockKg||'')}" placeholder="kg" step="0.1">`;
          return `<tr><td>${escapeHtml(p.name)}</td><td>${escapeHtml(p.mj)}</td><td>${input}</td></tr>`;
        }).join('') + `</tbody></table>`;
    }
    const html = `<div class="table-container">${tableHtml}</div><button id="ms-save" class="btn-success" style="width:100%;margin-top:1rem;">Uložiť</button>`;
    const onReady = ()=>{
      document.getElementById('ms-save').onclick = async ()=>{
        const inputs = document.querySelectorAll('#modal-container .ms-input');
        const payload = {};
        Array.from(inputs).forEach(inp=>{
          if (!payload[inp.dataset.ean]) payload[inp.dataset.ean] = { ean: inp.dataset.ean };
          if (inp.dataset.type === 'kg') payload[inp.dataset.ean].minStockKg = inp.value;
          else payload[inp.dataset.ean].minStockKs = inp.value;
        });
        try{
          await apiRequest('/api/kancelaria/updateMinStockLevels', { method:'POST', body:Object.values(payload) });
          hideModalCompat();
        }catch(_){}
      };
    };
    return { html, onReady };
  }

  // =================================================================
  // === NOVÝ RECEPT =================================================
  // =================================================================
  async function viewCreateRecipe(){
    await ensureOfficeDataIsLoaded();
    await ensureWarehouseCache(true);

    const prod = getOfficeData().productsWithoutRecipe || [];
    const recipeCats = getOfficeData().recipeCategories || [];

    const html = `
      <div class="form-group">
        <label>1. Zvoľte produkt (ktorý ešte nemá recept):</label>
        <select id="rcp-product"><option value="">-- Vyberte produkt --</option>${prod.map(p=>`<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('')}</select>
      </div>
      <div class="form-group">
        <label>2. Priraďte kategóriu</label>
        <select id="rcp-cat"><option value="">-- Vyberte existujúcu --</option>${(recipeCats||[]).map(c=>`<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')}</select>
        <div style="text-align:center;margin:.5rem 0;">alebo</div>
        <input type="text" id="rcp-newcat" placeholder="Vytvorte novú kategóriu (napr. Mäkké salámy)">
      </div>

      <h4 style="margin-top:1.5rem;">3. Suroviny (na 100 kg výrobku)</h4>
      <div id="rcp-ingredients"></div>

      <div class="btn-grid" style="grid-template-columns:repeat(4,1fr)">
        <button class="btn-secondary add-ing" data-cat="maso" style="margin-top:0;">Mäso</button>
        <button class="btn-secondary add-ing" data-cat="koreniny" style="margin-top:0;">Koreniny</button>
        <button class="btn-secondary add-ing" data-cat="obal" style="margin-top:0;">Obaly</button>
        <button class="btn-secondary add-ing" data-cat="pomocny_material" style="margin-top:0;">Pomocné</button>
      </div>

      <button id="rcp-save" class="btn-success" style="margin-top:20px;width:100%;">Uložiť Recept</button>
    `;
    const onReady = ()=>{
      document.querySelectorAll('#modal-container .add-ing').forEach(btn=>{
        btn.addEventListener('click', ()=> addIngredientRow(btn.dataset.cat, false, '#modal-container'));
      });
      document.getElementById('rcp-save').onclick = submitNewRecipe;
    };
    return { html, onReady };
  }

  async function addIngredientRow(catKey, isEdit=false, ctxSel=''){
    const containerId = isEdit ? 'rcp-edit-ingredients' : 'rcp-ingredients';
    const container = document.querySelector(`${ctxSel} #${containerId}`) || document.querySelector(`#${containerId}`);
    if (!container) return;

    await ensureWarehouseCache(false);
    const names = state.warehouse[normalizeCatKey(catKey)] || [];

    const row = document.createElement('div');
    row.className = 'recipe-ingredient-row';
    row.style.cssText = 'display:grid;grid-template-columns:3fr 1.5fr auto;gap:.5rem;align-items:center;margin-bottom:.5rem;';
    row.innerHTML = `
      <select>
        <option value="" disabled selected>Vyberte (${escapeHtml(displayLabelForCat(catKey))})...</option>
        ${buildOptions(names)}
      </select>
      <input type="number" step="0.01" placeholder="Množstvo (kg)">
      <button class="btn-danger" style="margin:0;padding:5px 10px;width:auto;">X</button>
    `;
    row.querySelector('.btn-danger').addEventListener('click', ()=> row.remove());
    container.appendChild(row);
  }

  async function submitNewRecipe(){
    const productName = document.querySelector('#modal-container #rcp-product')?.value;
    if (!productName){ status('Musíte vybrať produkt.', true); return; }

    const newCategory = document.getElementById('rcp-newcat')?.value.trim();
    const existingCategory = document.getElementById('rcp-cat')?.value;
    if (!newCategory && !existingCategory){ status('Musíte vybrať existujúcu kategóriu alebo zadať novú.', true); return; }

    const rows = document.querySelectorAll('#modal-container #rcp-ingredients .recipe-ingredient-row');
    const ingredients = Array.from(rows).map(r=>({
      name: r.querySelector('select').value,
      quantity: r.querySelector('input').value
    })).filter(ing => ing.name && ing.quantity);

    if (!ingredients.length){ status('Recept musí obsahovať aspoň jednu surovinu.', true); return; }

    try{
      await apiRequest('/api/kancelaria/addNewRecipe', {
        method:'POST',
        body: { productName, ingredients, category: existingCategory, newCategory }
      });
      window.officeInitialData = {}; // zneplatni cache
      hideModalCompat();
    }catch(_){}
  }

  // =================================================================
  // === ZOZNAM / ÚPRAVA RECEPTOV ===================================
  // =================================================================
  async function viewEditRecipeList(){
    const recipes = await apiRequest('/api/kancelaria/getAllRecipes');
    let html = '';
    if (!recipes || !Object.keys(recipes).length){
      html = '<p>Nenašli sa žiadne recepty na úpravu.</p>';
    }else{
      for (const category in recipes){
        const buttons = recipes[category].map(name=>(
          `<button class="btn-primary rcp-open" data-name="${escapeHtml(name)}" style="margin-top:.5rem;">${escapeHtml(name)}</button>`
        )).join('');
        html += `<h4>${escapeHtml(category)}</h4><div class="btn-grid">${buttons}</div>`;
      }
    }
    const onReady = ()=>{
      document.querySelectorAll('#modal-container .rcp-open').forEach(btn=>{
        btn.addEventListener('click', ()=>{
          const name = btn.dataset.name;
          hideModalCompat();
          openModalCompat(`Upraviť Recept: ${escapeHtml(name)}`, ()=>viewEditRecipeContent(name));
        });
      });
    };
    return { html, onReady };
  }

  async function viewEditRecipeContent(productName){
    await ensureOfficeDataIsLoaded();
    await ensureWarehouseCache(true);
    const recipeDetails = await apiRequest('/api/kancelaria/getRecipeDetails', { method:'POST', body:{ productName } });

    let ingredientsHtml = '';
    (recipeDetails?.ingredients || []).forEach(ing=>{
      const catKey = findCategoryForName(ing.name) || 'maso';
      const list = state.warehouse[catKey] || [];
      const options = buildOptions(list, ing.name);
      ingredientsHtml += `
        <div class="recipe-ingredient-row" style="display:grid;grid-template-columns:3fr 1.5fr auto;gap:.5rem;align-items:center;margin-bottom:.5rem;">
          <select>${options}</select>
          <input type="number" step="0.01" placeholder="Množstvo (kg)" value="${escapeHtml(String(ing.quantity))}">
          <button class="btn-danger" style="margin:0;padding:5px 10px;width:auto;">X</button>
        </div>`;
    });

    const html = `
      <div id="rcp-edit-ingredients">${ingredientsHtml}</div>

      <div class="btn-grid" style="grid-template-columns:repeat(4,1fr)">
        <button class="btn-secondary add-ing" data-cat="maso" style="margin-top:0;">Mäso</button>
        <button class="btn-secondary add-ing" data-cat="koreniny" style="margin-top:0;">Koreniny</button>
        <button class="btn-secondary add-ing" data-cat="obal" style="margin-top:0;">Obaly</button>
        <button class="btn-secondary add-ing" data-cat="pomocny_material" style="margin-top:0;">Pomocné</button>
      </div>

      <div class="btn-grid" style="margin-top:20px;">
        <button id="rcp-update" class="btn-success">Uložiť Zmeny</button>
        <button id="rcp-delete" class="btn-danger">Vymazať Recept</button>
      </div>
    `;
    const onReady = ()=>{
      document.querySelectorAll('#modal-container #rcp-edit-ingredients .btn-danger')
        .forEach(b => b.addEventListener('click', e => e.currentTarget.parentElement.remove()));

      document.querySelectorAll('#modal-container .add-ing').forEach(btn=>{
        btn.addEventListener('click', ()=> addIngredientRow(btn.dataset.cat, true, '#modal-container'));
      });

      document.getElementById('rcp-update').onclick = () => submitRecipeUpdate(productName);
      document.getElementById('rcp-delete').onclick = () => deleteCurrentRecipe(productName);
    };
    return { html, onReady };
  }

  async function submitRecipeUpdate(productName){
    const rows = document.querySelectorAll('#modal-container #rcp-edit-ingredients .recipe-ingredient-row');
    const ingredients = Array.from(rows).map(r=>({
      name: r.querySelector('select').value,
      quantity: r.querySelector('input').value
    })).filter(ing => ing.name && ing.quantity);
    try{
      await apiRequest('/api/kancelaria/updateRecipe', { method:'POST', body:{ productName, ingredients } });
      hideModalCompat();
    }catch(_){}
  }
  async function deleteCurrentRecipe(productName){
    if (!confirm(`Naozaj chcete natrvalo vymazať recept pre produkt "${productName}"?`)) return;
    try{
      await apiRequest('/api/kancelaria/deleteRecipe', { method:'POST', body:{ productName } });
      hideModalCompat();
    }catch(_){}
  }

  // =================================================================
  // === SPRÁVA KRÁJANÝCH PRODUKTOV =================================
  // =================================================================
  async function viewSlicingManagement(){
    const data = await apiRequest('/api/kancelaria/getSlicingManagementData');
    const sourceOptions = (data?.sourceProducts||[]).map(p=>`<option value="${escapeHtml(p.ean)}">${escapeHtml(p.name)}</option>`).join('');
    let unlinkedHtml = 'Žiadne nepriradené krájané produkty.';
    if (data?.unlinkedSlicedProducts?.length){
      unlinkedHtml = '<table><tbody>' + data.unlinkedSlicedProducts.map(p =>
        `<tr><td>${escapeHtml(p.name)}</td><td><button class="btn-success link-sliced" data-target-ean="${escapeHtml(p.ean)}" style="margin:0;width:auto;">Prepojiť</button></td></tr>`
      ).join('') + '</tbody></table>';
    }
    const html = `
      <label for="slc-source">1. Vyberte zdrojový produkt (celok)</label>
      <select id="slc-source"><option value="">-- Vyberte --</option>${sourceOptions}</select>

      <div id="slc-target" class="hidden" style="margin-top:20px;">
        <h4>2. Priraďte krájaný produkt (balíček)</h4>
        <div id="slc-link" class="table-container">${unlinkedHtml}</div>

        <fieldset style="margin-top:1rem;border:1px solid var(--medium-gray);padding:1rem;border-radius:var(--border-radius);">
          <legend>ALEBO: Vytvoriť nový</legend>
          <label>Názov:</label><input type="text" id="slc-new-name">
          <label style="margin-top:.5rem;">EAN:</label><input type="text" id="slc-new-ean">
          <label style="margin-top:.5rem;">Váha (g):</label><input type="number" id="slc-new-weight">
          <button id="slc-create" class="btn-success" style="width:100%;margin-top:1rem;">Vytvoriť a prepojiť</button>
        </fieldset>
      </div>
    `;
    const onReady = ()=>{
      const srcSel = document.getElementById('slc-source');
      const tgtSec = document.getElementById('slc-target');
      srcSel.onchange = ()=> tgtSec.classList.toggle('hidden', !srcSel.value);

      document.getElementById('slc-link').addEventListener('click', async (e)=>{
        const btn = e.target.closest('.link-sliced');
        if (!btn) return;
        const sourceEan = srcSel.value;
        if (!sourceEan){ status('Najprv vyberte zdrojový produkt.', true); return; }
        const targetEan = btn.dataset.targetEan;
        try{
          await apiRequest('/api/kancelaria/linkSlicedProduct', { method:'POST', body:{ sourceEan, targetEan } });
          hideModalCompat();
          openModalCompat('Správa Krájaných Produktov', viewSlicingManagement);
        }catch(_){}
      });

      document.getElementById('slc-create').onclick = async ()=>{
        const sourceEan = srcSel.value;
        if (!sourceEan){ status('Najprv vyberte zdrojový produkt.', true); return; }
        const newData = {
          sourceEan,
          name:  document.getElementById('slc-new-name').value,
          ean:   document.getElementById('slc-new-ean').value,
          weight:document.getElementById('slc-new-weight').value
        };
        if (!newData.name || !newData.ean || !newData.weight){ status('Všetky polia sú povinné.', true); return; }
        try{
          await apiRequest('/api/kancelaria/createAndLinkSlicedProduct', { method:'POST', body:newData });
          hideModalCompat();
          openModalCompat('Správa Krájaných Produktov', viewSlicingManagement);
        }catch(_){}
      };
    };
    return { html, onReady };
  }
window.initializeErpAdminModule = initializeErpAdminModule;
(window);
// === NOVÝ RECEPT – inline render do #erp-admin-content ======================
async function viewCreateRecipeInline(){
  await ensureOfficeDataIsLoaded();
  const base = getOfficeData();

  const productOpts = (base.productsWithoutRecipe || [])
    .map(n => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
  const catOpts = (base.recipeCategories || [])
    .map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');

  const html = `
    <div class="stat-card">
      <h3 style="margin-top:0;">Nový recept</h3>
      <form id="rcp-create-form" autocomplete="off">
        <div class="form-grid">

          <div class="form-group">
            <label>Produkt</label>
            ${ (productOpts && productOpts.length)
                ? `<select id="rcp-product"><option value="">-- Vyberte produkt --</option>${productOpts}</select>
                    <small>alebo <a href="#" id="rcp-toggle-manual">zadajte ručne</a></small>
                    <input id="rcp-product-manual" class="hidden" type="text" placeholder="Názov produktu">`
                : `<input id="rcp-product-manual" type="text" placeholder="Názov produktu">`
              }
          </div>
          <div class="form-group">
            <label>Kategória receptu</label>
            <select id="rcp-cat"><option value="">-- Vyberte --</option>${catOpts}</select>
            <small>alebo nová:</small>
            <input id="rcp-newcat" type="text" placeholder="Nová kategória (nepovinné)">
          </div>
        </div>

        <h4>Suroviny</h4>
        <div id="rcp-ingredients"></div>
        <div style="margin: .5rem 0 1rem;">
          <button type="button" id="rcp-add-row" class="btn-secondary"><i class="fas fa-plus"></i> Pridať surovinu</button>
        </div>

        <div id="rcp-cost" class="muted" style="margin:.5rem 0 1rem;">Odhad ceny dávky: —</div>

        <div style="display:flex; gap:.75rem; justify-content:flex-end;">
          <button type="submit" class="btn-primary"><i class="fas fa-save"></i> Uložiť recept</button>
        </div>
      </form>
    </div>
  `;

  const onReady = () => {
    const host = document.getElementById('rcp-ingredients');
    // Manual product toggle
    const toggle = document.getElementById('rcp-toggle-manual');
    if (toggle){
      toggle.addEventListener('click', (e)=>{
        e.preventDefault();
        const sel = document.getElementById('rcp-product');
        const inp = document.getElementById('rcp-product-manual');
        if (sel) sel.classList.toggle('hidden');
        if (inp) inp.classList.toggle('hidden');
      });
    }

    const categories = (base.itemTypes || ['Mäso','Koreniny','Obaly - Črevá','Pomocný material']);

    async function buildNameOptions(cat, selectEl, priceEl){
      if (!cat){ selectEl.innerHTML = '<option value="">' + '-- Najprv vyberte kategóriu --' + '</option>'; priceEl.textContent = '—'; return; }
      try{
        const data = await apiRequest(`/api/kancelaria/stock/allowed-names?category=${encodeURIComponent(cat)}`);
        const items = data?.items || [];
        if (!items.length) throw new Error('Žiadne položky pre danú kategóriu.');
        selectEl.innerHTML = `<option value="">-- Vyberte --</option>`
          + items.map(i => `<option data-price="${i.last_price ?? ''}" value="${escapeHtml(i.name)}">${escapeHtml(i.name)}</option>`).join('');
        selectEl.onchange = () => {
          const p = selectEl.selectedOptions[0]?.dataset.price;
          priceEl.textContent = p ? `${parseFloat(p).toFixed(2)} €/kg` : '—';
          recomputeCost();
        };
      }catch(err){
        console.warn('[ERP] allowed-names zlyhalo, prepínam na textové pole:', err);
        const input = document.createElement('input');
        input.type = 'text';
        input.placeholder = 'Názov suroviny';
        input.className = 'rcp-name-input';
        selectEl.replaceWith(input);
      }
    }

    const parseNum = v => parseFloat(String(v).replace(',','.'));

    function addRow(prefill){
      const row = document.createElement('div');
      row.className = 'recipe-ingredient-row';
      row.innerHTML = `
        <div class="form-grid">
          <div class="form-group">
            <label>Kategória suroviny</label>
            <select class="rcp-cat-sel">
              <option value="">-- Vyberte --</option>
              ${categories.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label>Názov suroviny</label>
            <select class="rcp-name-sel"></select>
            <small class="muted">Posledná cena: <span class="rcp-price">—</span></small>
          </div>
          <div class="form-group">
            <label>Množstvo na dávku (kg)</label>
            <input class="rcp-qty" type="number" step="0.001" min="0" placeholder="0.000">
          </div>
          <div class="form-group" style="align-self:end;">
            <button type="button" class="btn-danger rcp-del"><i class="fas fa-trash"></i></button>
          </div>
        </div>
      `;
      host.appendChild(row);

      const selCat  = row.querySelector('.rcp-cat-sel');
      const selName = row.querySelector('.rcp-name-sel');
      const priceEl = row.querySelector('.rcp-price');
      const qtyEl   = row.querySelector('.rcp-qty');

      selCat.onchange = () => buildNameOptions(selCat.value, selName, priceEl);
      qtyEl.oninput = recomputeCost;
      row.querySelector('.rcp-del').onclick = () => { row.remove(); recomputeCost(); };

      if (prefill){
        selCat.value = prefill.category || '';
        selCat.dispatchEvent(new Event('change'));
        setTimeout(() => {
          selName.value = prefill.name || '';
          selName.dispatchEvent(new Event('change'));
          qtyEl.value = prefill.quantity ?? '';
          recomputeCost();
        }, 200);
      }
    }

    function recomputeCost(){
      const rows = Array.from(document.querySelectorAll('#rcp-ingredients .recipe-ingredient-row'));
      let sum = 0;
      for (const r of rows){
        const sel = r.querySelector('.rcp-name-sel');
        const qty = parseNum(r.querySelector('.rcp-qty').value||0) || 0;
        const price = parseNum(sel?.selectedOptions?.[0]?.dataset.price || '') || 0;
        sum += qty * price;
      }
      document.getElementById('rcp-cost').textContent = sum ? `Odhad ceny dávky: ${sum.toFixed(2)} €` : 'Odhad ceny dávky: —';
    }

    // jedna prázdna rada na úvod
    addRow();

    document.getElementById('rcp-add-row').onclick = () => addRow();

    document.getElementById('rcp-create-form').addEventListener('submit', async (e)=>{
      e.preventDefault();
      const sel = document.getElementById('rcp-product');
      const manual = document.getElementById('rcp-product-manual');
      const productName = (manual && !manual.classList.contains('hidden') && manual.value.trim())
                          || (sel && !sel.classList.contains('hidden') && sel.value)
                          || '';
      const newCategory = document.getElementById('rcp-newcat').value.trim();
      const existingCat = document.getElementById('rcp-cat').value;
      if (!productName){ status('Vyberte produkt.', true); return; }
      if (!newCategory && !existingCat){ status('Zvoľte kategóriu alebo zadajte novú.', true); return; }
      const rows = Array.from(document.querySelectorAll('#rcp-ingredients .recipe-ingredient-row'));
      const ingredients = rows.map(r => ({
        name: r.querySelector('.rcp-name-sel').value,
        quantity: parseNum(r.querySelector('.rcp-qty').value)
      })).filter(i => i.name && i.quantity > 0);
      if (!ingredients.length){ status('Recept musí obsahovať aspoň jednu surovinu.', true); return; }

      await apiRequest('/api/kancelaria/addNewRecipe', {
        method:'POST',
        body: { productName, ingredients, category: existingCat, newCategory }
      });
      status('Recept uložený.', false);
      mount(()=> renderRecipeEditorInline(productName)); // rovno otvor editor
    });
  };

  return { html, onReady };
}

// === ZOZNAM RECEPTOV – výber produktu na úpravu ==============================
async function viewEditRecipeListInline(){
  const recipes = await apiRequest('/api/kancelaria/getAllRecipes');
  let html = `<div class="stat-card"><h3 style="margin-top:0;">Upraviť recept</h3>`;
  if (!recipes || !Object.keys(recipes).length){
    html += '<p>Nenašli sa žiadne recepty na úpravu.</p>';
  } else {
    for (const category of Object.keys(recipes)){
      const buttons = recipes[category].map(name =>
        `<button class="btn-secondary rcp-open" data-name="${escapeHtml(name)}" style="margin:.25rem .25rem 0 0;">${escapeHtml(name)}</button>`
      ).join('');
      html += `<h4>${escapeHtml(category || 'Nezaradené')}</h4><div>${buttons}</div>`;
    }
  }
  html += `</div>`;
  const onReady = () => {
    document.querySelectorAll('.rcp-open').forEach(btn=>{
      btn.addEventListener('click', ()=> mount(()=> renderRecipeEditorInline(btn.dataset.name)));
    });
  };
  return { html, onReady };
}

// === EDITOR RECEPTU – inline =================================================
async function renderRecipeEditorInline(productName){
  await ensureOfficeDataIsLoaded();
  const base = getOfficeData();
  const details = await apiRequest('/api/kancelaria/getRecipeDetails', { method:'POST', body:{ productName } });
  const catOpts = (base.recipeCategories || [])
    .map(c => `<option value="${escapeHtml(c)}" ${details?.category===c?'selected':''}>${escapeHtml(c)}</option>`).join('');

  const html = `
    <div class="stat-card">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h3 style="margin-top:0;">Upraviť recept – ${escapeHtml(productName)}</h3>
        <div style="display:flex; gap:.5rem;">
          <button id="rcp-save" class="btn-primary"><i class="fas fa-save"></i> Uložiť zmeny</button>
          <button id="rcp-delete" class="btn-danger"><i class="fas fa-trash"></i> Vymazať recept</button>
        </div>
      </div>
      <div class="form-group">
        <label>Kategória receptu</label>
        <select id="rcp-cat"><option value="">-- Vyberte --</option>${catOpts}</select>
        <small>alebo nová:</small>
        <input id="rcp-newcat" type="text" placeholder="Nová kategória (nepovinné)">
      </div>
      <h4>Suroviny</h4>
      <div id="rcp-ingredients"></div>
      <div style="margin: .5rem 0 1rem;">
        <button type="button" id="rcp-add-row" class="btn-secondary"><i class="fas fa-plus"></i> Pridať surovinu</button>
      </div>
      <div id="rcp-cost" class="muted" style="margin:.5rem 0 1rem;">Odhad ceny dávky: —</div>
    </div>
  `;

  const onReady = ()=>{
    const host = document.getElementById('rcp-ingredients');
    // Manual product toggle
    const toggle = document.getElementById('rcp-toggle-manual');
    if (toggle){
      toggle.addEventListener('click', (e)=>{
        e.preventDefault();
        const sel = document.getElementById('rcp-product');
        const inp = document.getElementById('rcp-product-manual');
        if (sel) sel.classList.toggle('hidden');
        if (inp) inp.classList.toggle('hidden');
      });
    }

    const categories = (base.itemTypes || ['Mäso','Koreniny','Obaly - Črevá','Pomocný material']);
    const parseNum = v => parseFloat(String(v).replace(',','.'));

    async function buildNameOptions(cat, selectEl, priceEl){
      if (!cat){ selectEl.innerHTML = '<option value="">' + '-- Najprv vyberte kategóriu --' + '</option>'; priceEl.textContent = '—'; return; }
      try{
        const data = await apiRequest(`/api/kancelaria/stock/allowed-names?category=${encodeURIComponent(cat)}`);
        const items = data?.items || [];
        if (!items.length) throw new Error('Žiadne položky pre danú kategóriu.');
        selectEl.innerHTML = `<option value="">-- Vyberte --</option>`
          + items.map(i => `<option data-price="${i.last_price ?? ''}" value="${escapeHtml(i.name)}">${escapeHtml(i.name)}</option>`).join('');
        selectEl.onchange = () => {
          const p = selectEl.selectedOptions[0]?.dataset.price;
          priceEl.textContent = p ? `${parseFloat(p).toFixed(2)} €/kg` : '—';
          recomputeCost();
        };
      }catch(err){
        console.warn('[ERP] allowed-names (editor) zlyhalo, prepínam na textové pole:', err);
        const input = document.createElement('input');
        input.type = 'text';
        input.placeholder = 'Názov suroviny';
        input.className = 'rcp-name-input';
        selectEl.replaceWith(input);
      }
    }

    function addRow(prefill){
      const row = document.createElement('div');
      row.className = 'recipe-ingredient-row';
      row.innerHTML = `
        <div class="form-grid">
          <div class="form-group">
            <label>Kategória suroviny</label>
            <select class="rcp-cat-sel">
              <option value="">-- Vyberte --</option>
              ${categories.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label>Názov suroviny</label>
            <select class="rcp-name-sel"></select>
            <small class="muted">Posledná cena: <span class="rcp-price">—</span></small>
          </div>
          <div class="form-group">
            <label>Množstvo na dávku (kg)</label>
            <input class="rcp-qty" type="number" step="0.001" min="0" placeholder="0.000">
          </div>
          <div class="form-group" style="align-self:end;">
            <button type="button" class="btn-danger rcp-del"><i class="fas fa-trash"></i></button>
          </div>
        </div>
      `;
      host.appendChild(row);

      const selCat  = row.querySelector('.rcp-cat-sel');
      const selName = row.querySelector('.rcp-name-sel');
      const priceEl = row.querySelector('.rcp-price');
      const qtyEl   = row.querySelector('.rcp-qty');

      selCat.onchange = () => buildNameOptions(selCat.value, selName, priceEl);
      qtyEl.oninput = recomputeCost;
      row.querySelector('.rcp-del').onclick = () => { row.remove(); recomputeCost(); };

      if (prefill){
        selCat.value = prefill.category || '';
        selCat.dispatchEvent(new Event('change'));
        setTimeout(()=>{
          selName.value = prefill.name || '';
          selName.dispatchEvent(new Event('change'));
          qtyEl.value = prefill.quantity ?? '';
          recomputeCost();
        }, 200);
      }
    }

    function recomputeCost(){
      const rows = Array.from(document.querySelectorAll('#rcp-ingredients .recipe-ingredient-row'));
      let sum = 0;
      for (const r of rows){
        const sel = r.querySelector('.rcp-name-sel');
        const qty = parseNum(r.querySelector('.rcp-qty').value||0) || 0;
        const price = parseNum(sel?.selectedOptions?.[0]?.dataset.price || '') || 0;
        sum += qty * price;
      }
      document.getElementById('rcp-cost').textContent = sum ? `Odhad ceny dávky: ${sum.toFixed(2)} €` : 'Odhad ceny dávky: —';
    }

    // predvyplň existujúce suroviny
    (details?.ingredients || []).forEach(ing => {
      addRow({ category: ing.category || '', name: ing.name, quantity: ing.quantity });
    });
    if (!(details?.ingredients || []).length){
      addRow();
    }

    document.getElementById('rcp-add-row').onclick = () => addRow();

    document.getElementById('rcp-save').onclick = async ()=>{
      const newCategory = document.getElementById('rcp-newcat').value.trim();
      const existingCat = document.getElementById('rcp-cat').value;
      const rows = Array.from(document.querySelectorAll('#rcp-ingredients .recipe-ingredient-row'));
      const ingredients = rows.map(r => ({
        name: r.querySelector('.rcp-name-sel').value,
        quantity: parseNum(r.querySelector('.rcp-qty').value)
      })).filter(i => i.name && i.quantity > 0);
      await apiRequest('/api/kancelaria/updateRecipe', {
        method:'POST',
        body: { productName, ingredients, category: existingCat, newCategory }
      });
      status('Recept uložený.', false);
    };

    document.getElementById('rcp-delete').onclick = async ()=>{
      if (!confirm('Naozaj vymazať recept?')) return;
      await apiRequest('/api/kancelaria/deleteRecipe', { method:'POST', body:{ productName } });
      status('Recept vymazaný.', false);
      mount(viewEditRecipeListInline);
    };
  };

  return { html, onReady };
}})