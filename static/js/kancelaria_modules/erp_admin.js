// =================================================================
// === SUB-MODUL KANCELÁRIA: SPRÁVA ERP (stabilné, bez kolízií) ====
// =================================================================
(function (window, document) {
  'use strict';

  // --------------------------- Helpers ----------------------------
  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function showStatus(msg, isError=false){
    if (typeof window.status === 'function') return window.status(msg, isError);
    if (typeof window.showStatus === 'function') return window.showStatus(msg, isError);
    (isError?console.error:console.log)(msg);
  }
  function $(sel, root){ return (root||document).querySelector(sel); }
  function onClick(sel, fn, root){ const el=$(sel,root); if (el) el.onclick=fn; return !!el; }
  const byLocale = (a,b)=> String(a).localeCompare(String(b),'sk');

  const apiRequest = window.apiRequest || (async (url, opts={})=>{
    const res = await fetch(url, {
      method: opts.method||'GET',
      headers: {'Content-Type':'application/json'},
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials:'same-origin'
    });
    if (!res.ok){
      let t=''; try{ t=await res.text(); }catch(_){}
      throw new Error(`HTTP ${res.status} ${res.statusText} – ${t.slice(0,200)}`);
    }
    const ct=(res.headers.get('content-type')||'').toLowerCase();
    return ct.includes('application/json') ? res.json() : {};
  });

  // --------------- Modal fallback (ak v projekte chýba) ------------
  const openModalCompat = (typeof window.showModal==='function')
    ? window.showModal
    : function openModalCompat(title, contentFactory){
        let mc = $('#modal-container'); if (!mc){ mc=document.createElement('div'); mc.id='modal-container'; document.body.appendChild(mc); }
        mc.innerHTML = `
          <div class="modal-backdrop" style="position:fixed;inset:0;background:rgba(0,0,0,.45)"></div>
          <div class="modal-content" style="position:fixed;inset:5% 5% auto 5%;background:#fff;border-radius:8px;max-height:90vh;overflow:auto;">
            <div class="modal-header" style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eee;padding:12px 16px;">
              <h3 style="margin:0;">${escapeHtml(title)}</h3>
              <button class="close-btn" style="margin:0;font-size:24px;line-height:1;background:none;border:none;cursor:pointer">&times;</button>
            </div>
            <div class="modal-body" id="__compat-body" style="padding:16px;">Načítavam…</div>
          </div>`;
        mc.style.display='flex';
        const close=()=>{ mc.style.display='none'; mc.innerHTML=''; };
        onClick('.close-btn', close, mc); onClick('.modal-backdrop', close, mc);

        Promise.resolve(typeof contentFactory==='function'?contentFactory():contentFactory)
          .then(res=>{ $('#__compat-body', mc).innerHTML = res?.html || ''; if (typeof res?.onReady==='function'){ try{ res.onReady(); }catch(e){ console.error(e);} } })
          .catch(err=>{ $('#__compat-body', mc).innerHTML = `<p class="error">Chyba: ${escapeHtml(err?.message||String(err))}</p>`; console.error(err); });
        return mc;
      };

  const hideModalCompat = (typeof window.hideModal==='function')
    ? window.hideModal
    : function hideModalCompat(){ const mc=$('#modal-container'); if (mc){ mc.style.display='none'; mc.innerHTML=''; } };

  // ---------------------- Mount kontajnera -------------------------
  window.erpMount = window.erpMount || function (factory) {
    const host = $('#erp-admin-content');
    if (!host){ console.error('Chýba #erp-admin-content'); return; }
    host.innerHTML = '<div class="stat-card"><i class="fa-solid fa-spinner fa-spin"></i> Načítavam…</div>';
    Promise.resolve(factory())
      .then(res=>{ host.innerHTML = res?.html || ''; if (typeof res?.onReady==='function'){ try{ res.onReady(); }catch(e){ console.error(e);} } })
      .catch(err=>{ host.innerHTML = '<div class="stat-card">Chyba načítania: '+(err?.message||String(err))+'</div>'; console.error(err); });
  };

  // --------------------- Loader baseData (no-throw) ----------------
  window.__officeBaseData = window.__officeBaseData || null;
  async function ensureOfficeDataIsLoaded(){
    if (window.__officeBaseData) return;
    async function safeFetch(url){
      try{
        const r = await fetch(url,{credentials:'same-origin'});
        const ct=(r.headers.get('content-type')||'').toLowerCase();
        if(!r.ok || !ct.includes('application/json')) return null;
        return await r.json();
      }catch(_){ return null; }
    }
    let data = await safeFetch('/api/kancelaria/baseData');
    if (!data) data = await safeFetch('/api/kancelaria/getKancelariaBaseData');
    if (!data){
      console.warn('[ERP] baseData sa nepodarilo načítať – používam fallback.');
      window.__officeBaseData = {
        productsWithoutRecipe: [],
        recipeCategories: [],
        itemTypes: ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál'],
      };
      return;
    }
    window.__officeBaseData = {
      productsWithoutRecipe: data.productsWithoutRecipe || data.products_without_recipe || data.products || [],
      recipeCategories:      data.recipeCategories      || data.recipe_categories      || data.categories || [],
      itemTypes:             data.itemTypes             || data.item_types             || data.stockCategories || ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál'],
    };
  }
  function getOfficeData(){ return window.__officeBaseData || { productsWithoutRecipe:[], recipeCategories:[], itemTypes:['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál'] }; }

  // --------------------- Sklad cache & kategórie -------------------
  const state = { warehouse:null, warehouseLoadedAt:0, catalog:null };
  function normalizeCatKey(x){ const c=String(x||'').toLowerCase().trim(); if(c==='mäso'||c==='maso'||c==='meat')return 'maso'; if(c.startsWith('koren'))return 'koreniny'; if(c.startsWith('obal'))return 'obal'; if(c.startsWith('pomoc'))return 'pomocny_material'; return c; }
  function displayLabelForCat(k){ return ({maso:'Mäso', koreniny:'Koreniny', obal:'Obaly – Črevá', pomocny_material:'Pomocný materiál'})[normalizeCatKey(k)] || k; }

  async function fetchAllowedNames(categoryKey){
    const cat = normalizeCatKey(categoryKey);
    try{
      const resp = await apiRequest(`/api/kancelaria/stock/allowed-names?category=${encodeURIComponent(cat)}`);
      if (Array.isArray(resp?.items)) return resp.items.map(i=>String(i.name)).filter(Boolean);
      if (Array.isArray(resp?.names)) return resp.names.map(String).filter(Boolean);
    }catch(_){}
    return [];
  }
  async function ensureWarehouseCache(force=false){
    if (!force && state.warehouse && (Date.now()-state.warehouseLoadedAt)<30000) return state.warehouse;
    const cats=['maso','koreniny','obal','pomocny_material'];
    const results = await Promise.all(cats.map(c=>fetchAllowedNames(c)));
    const out={}; cats.forEach((c,i)=> out[c]=(results[i]||[]).sort(byLocale) );
    state.warehouse=out; state.warehouseLoadedAt=Date.now(); return out;
  }

  // ==================== ROOT UI – Správa ERP =======================
  function initializeErpAdminModule(){
    const sec = $('#section-erp-admin'); if(!sec) return;
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
    $('#erp-btn-catalog').onclick   = ()=> window.erpMount(viewCatalogManagement);
    $('#erp-btn-minstock').onclick  = ()=> window.erpMount(viewMinStock);
    $('#erp-btn-slicing').onclick   = ()=> window.erpMount(viewSlicingManagement);
    $('#erp-btn-newrecipe').onclick = ()=> window.erpMount(viewCreateRecipeInline);
    $('#erp-btn-editrecipe').onclick= ()=> window.erpMount(viewEditRecipeListInline);
    // default – kľudne prepni na viewCatalogManagement, ak chceš
    $('#erp-btn-catalog').click();
  }

  // ======================= SPRÁVA KATALÓGU =========================
  async function viewCatalogManagement(){
    // === 1) načítanie katalógu – vždy čerstvé dáta (cache buster) ===
    state.catalog = await apiRequest('/api/kancelaria/getCatalogManagementData?ts=' + Date.now()) || {};
    await ensureOfficeDataIsLoaded();
    const base = getOfficeData();

    // productsWithoutRecipe – lokálny set (pre filter „bez receptu“)
    window.__officeBaseData = window.__officeBaseData || {};
    if (!Array.isArray(window.__officeBaseData.productsWithoutRecipe)) {
      window.__officeBaseData.productsWithoutRecipe = base.productsWithoutRecipe || [];
    }
    const noRecipeSet = new Set((window.__officeBaseData.productsWithoutRecipe||[]).map(String));

    const itemTypes  = Array.isArray(state.catalog.item_types)?state.catalog.item_types:[];
    const saleCats   = Array.isArray(state.catalog.sale_categories)?state.catalog.sale_categories:[];
    const dphRates   = Array.isArray(state.catalog.dph_rates)?state.catalog.dph_rates:[];
    // --- SHADOW MERGE: spoj server a lokálne upserty podľa EAN ----
    window.__catalogShadowUpserts = window.__catalogShadowUpserts || {};
    const shadow = window.__catalogShadowUpserts;

    const mergeProducts = (serverList)=> {
      const m = new Map((serverList||[]).map(p => [String(p.ean||'').trim(), {...p}]));
      for (const [ean, upd] of Object.entries(shadow)) {
        const k = String(ean).trim();
        const prev = m.get(k) || {};
        m.set(k, {...prev, ...upd});
      }
      return Array.from(m.values());
    };

    let products = mergeProducts(Array.isArray(state.catalog.products)? state.catalog.products:[]);
    const byEAN  = new Map(products.map(p => [String(p.ean||'').trim(), p]));
    const byName = new Map(products.map(p => [String(p.nazov_vyrobku||'').trim(), p]));

    const selectOpts = (arr, includeEmpty=false, selected=null) => {
      let html = includeEmpty?'<option value="">-- nevybrané --</option>':'';
      html += (arr||[]).map(v=>`<option value="${escapeHtml(v)}"${String(selected)===String(v)?' selected':''}>${escapeHtml(v)}</option>`).join('');
      return html;
    };
    const typeOptsFilter = ['-- Všetky typy --', ...itemTypes].map(t=>`<option value="${t==='-- Všetky typy --'? '':escapeHtml(t)}">${escapeHtml(t)}</option>`).join('');

    // === 2) UI hlavička + export/import toolbar ===
    const html = `
      <div class="stat-card" style="margin-bottom:1rem;">
        <h3 style="margin:0 0 .5rem 0;">Centrálny katalóg produktov</h3>
        <div class="form-grid" style="grid-template-columns: 1.2fr 1fr 1fr;">
          <div class="form-group"><label>Hľadať (názov alebo EAN)</label><input type="text" id="cat-search" placeholder="napr. saláma / 8580..." /></div>
          <div class="form-group"><label>Filter podľa typu</label><select id="cat-type-filter">${typeOptsFilter}</select></div>
          <div class="form-group" style="display:flex;align-items:flex-end;gap:.5rem;">
            <input type="checkbox" id="cat-only-norecipe" />
            <label for="cat-only-norecipe" style="margin:0;">Zobraziť len výrobky bez receptu</label>
          </div>
        </div>
        <div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem">
          <button id="cat-export-csv" class="btn-secondary"><i class="fas fa-file-export"></i> Export CSV</button>
          <button id="cat-import-csv" class="btn-primary"><i class="fas fa-file-import"></i> Import CSV</button>
          <button id="cat-download-template" class="btn-info"><i class="fas fa-download"></i> Stiahnuť šablónu CSV</button>
          <input id="cat-import-file" type="file" accept=".csv,text/csv" style="display:none" />
        </div>
        <small class="muted">
          CSV stĺpce: <code>EAN;Nazov;Typ_polozky;DPH;Predajna_kategoria;Kategoria_pre_recepty;Vyrobna_davka_kg;Vaha_balenia_g;Zdrojovy_EAN</code>
          (akceptujeme aj <code>,</code> a diakritiku v hlavičke). Riadky sa upsertujú podľa <strong>EAN</strong>.
        </small>
      </div>

      <div class="table-container" id="cat-table">
        <table class="tbl">
          <thead><tr>
            <th style="width:130px;">EAN</th>
            <th>Názov</th>
            <th style="width:150px;">Typ</th>
            <th>Kategórie</th>
            <th style="width:90px;text-align:right;">DPH</th>
            <th style="width:120px;">Recept</th>
            <th style="width:160px;">Zdrojový produkt</th>
            <th style="width:160px;">Akcie</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>

      <h4 style="margin-top: 2rem;">Pridať novú položku</h4>
      <form id="catalog-add-form">
        <div class="form-grid">
          <div class="form-group"><label>Typ položky</label><select id="cat-new-type" required>${selectOpts(itemTypes,true)}</select></div>
          <div class="form-group"><label>Sadzba DPH</label><select id="cat-new-dph" required>${selectOpts((dphRates||[]).map(r=>Number(r).toFixed(2)),true)}</select></div>
        </div>
        <div class="form-group"><label>Názov položky</label><input type="text" id="cat-new-name" required></div>
        <div class="form-group"><label>EAN kód</label><input type="text" id="cat-new-ean" required></div>
        <div class="form-group"><label>Predajná kategória</label><select id="cat-new-sale-cat">${selectOpts(saleCats,true)}</select></div>
        <div class="form-group">
          <label style="display:flex;align-items:center;gap:.5rem;">
            <input type="checkbox" id="cat-new-made" /> JA VYRÁBAM (výrobok bez receptu)
          </label>
        </div>
        <button type="submit" class="btn-success" style="width:100%;">Pridať položku do katalógu</button>
      </form>
    `;

    const onReady = ()=>{
      const tbody = document.querySelector('#cat-table tbody');
      const txt   = document.getElementById('cat-search');
      const sel   = document.getElementById('cat-type-filter');
      const cb    = document.getElementById('cat-only-norecipe');
      const btnExport = document.getElementById('cat-export-csv');
      const btnImport = document.getElementById('cat-import-csv');
      const btnTpl    = document.getElementById('cat-download-template');
      const fileInput = document.getElementById('cat-import-file');

      // po vstupe do view defaultne zobraz všetko
      if (sel) sel.value = '';
      if (cb)  cb.checked = false;

      function badgeRecipe(p){
        const isMade = String(p.typ_polozky||'').toUpperCase().startsWith('VÝROBOK') || String(p.typ_polozky||'').toLowerCase()==='produkt';
        const hasExplicitSource = (p.source_ean && String(p.source_ean).trim().length) || (p.source_name && String(p.source_name).trim().length);
        const hasRecipe = isMade ? (hasExplicitSource || !noRecipeSet.has(String(p.nazov_vyrobku))) : null;
        return (hasRecipe===true)
          ? '<span style="background:#16a34a;color:#fff;padding:.15rem .4rem;border-radius:.35rem;font-size:.8rem;">má recept</span>'
          : (hasRecipe===false)
            ? '<span style="background:#ef4444;color:#fff;padding:.15rem .4rem;border-radius:.35rem;font-size:.8rem;">NEMÁ RECEPT</span>'
            : '<span style="background:#9ca3af;color:#111;padding:.15rem .4rem;border-radius:.35rem;font-size:.8rem;">—</span>';
      }
      function sourceLabel(p){
        const src = p.source_ean ? byEAN.get(String(p.source_ean)) : (p.source_name ? byName.get(String(p.source_name)) : null);
        if (src) return `${escapeHtml(src.nazov_vyrobku||'')} <span class="muted">(${escapeHtml(src.ean||'')})</span>`;
        if (p.source_ean)  return `<span class="muted">${escapeHtml(p.source_ean)}</span>`;
        if (p.source_name) return `<span class="muted">${escapeHtml(p.source_name)}</span>`;
        return '—';
      }

      function renderTable(){
        if (!tbody) return;
        const q=(txt?.value||'').toLowerCase();
        const t=sel?.value||'';
        const only=!!cb?.checked;

        const rows = products
          .filter(p=>{
            const hay=(String(p.nazov_vyrobku)+' '+String(p.ean)).toLowerCase();
            const okQ = !q || hay.includes(q);
            const okT = !t || String(p.typ_polozky)===t;
            const isMade = String(p.typ_polozky||'').toUpperCase().startsWith('VÝROBOK') || String(p.typ_polozky||'').toLowerCase()==='produkt';
            const hasExplicitSource = (p.source_ean && String(p.source_ean).trim().length) || (p.source_name && String(p.source_name).trim().length);
            const treatAsHasRecipe = isMade ? (hasExplicitSource || !noRecipeSet.has(String(p.nazov_vyrobku))) : null;
            const okR = !only || (isMade && treatAsHasRecipe===false);
            return okQ && okT && okR;
          })
          .map(p=>{
            const cats = [p.kategoria_pre_recepty, p.predajna_kategoria].filter(Boolean).map(escapeHtml).join(' / ');
            const dph  = (Number(p.dph||0)).toFixed(2);
            return `<tr data-ean="${escapeHtml(String(p.ean||''))}">
              <td>${escapeHtml(p.ean||'')}</td>
              <td>${escapeHtml(p.nazov_vyrobku||'')}</td>
              <td>${escapeHtml(p.typ_polozky||'')}</td>
              <td>${cats||'—'}</td>
              <td style="text-align:right;">${dph}%</td>
              <td>${badgeRecipe(p)}</td>
              <td>${sourceLabel(p)}</td>
              <td>
                <button class="btn-secondary btn-sm btn-edit" style="margin-right:.35rem;">Upraviť</button>
                <button class="btn-danger   btn-sm btn-del">Zmazať</button>
              </td>
            </tr>`;
          }).join('');

        tbody.innerHTML = rows || '<tr><td colspan="8">Žiadne záznamy.</td></tr>';
      }

      // === EXPORT / IMPORT (IMPORT = upsert + okamžitý shadow sync) =====
      btnExport?.addEventListener('click', ()=>{
        const cols = ["EAN","Nazov","Typ_polozky","DPH","Predajna_kategoria","Kategoria_pre_recepty","Vyrobna_davka_kg","Vaha_balenia_g","Zdrojovy_EAN"];
        const lines = [cols.join(';')];
        products.forEach(p=>{
          const rec = [
            p.ean ?? '', p.nazov_vyrobku ?? '', p.typ_polozky ?? '',
            (p.dph!=null? Number(p.dph).toFixed(2) : ''),
            p.predajna_kategoria ?? '', p.kategoria_pre_recepty ?? '',
            (p.vyrobna_davka_kg!=null? String(p.vyrobna_davka_kg) : ''),
            (p.vaha_balenia_g!=null? String(p.vaha_balenia_g) : ''),
            p.source_ean ?? ''
          ];
          const esc = (s)=> String(s).replace(/;/g, ',').replace(/\r?\n/g, ' ').trim();
          lines.push(rec.map(esc).join(';'));
        });
        const blob = new Blob([lines.join('\r\n')], {type:'text/csv;charset=utf-8;'});
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'Tovar_export.csv'; a.click(); URL.revokeObjectURL(a.href);
      });

      btnTpl?.addEventListener('click', ()=>{
        const h = "EAN;Nazov;Typ_polozky;DPH;Predajna_kategoria;Kategoria_pre_recepty;Vyrobna_davka_kg;Vaha_balenia_g;Zdrojovy_EAN\r\n";
        const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([h], {type:'text/csv;charset=utf-8;'})); a.download = 'Tovar_sablona.csv'; a.click(); URL.revokeObjectURL(a.href);
      });

      btnImport?.addEventListener('click', ()=> fileInput?.click());
      fileInput?.addEventListener('change', async (e)=>{
        const f = e.target.files?.[0]; if (!f) return;

        const norm = (s) => String(s||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '');
        const SPLIT = (line, delim) => { const out=[]; let cur='',q=false; for (let i=0;i<line.length;i++){ const c=line[i]; if(c==='"'){ if(q&&line[i+1]==='"'){cur+='"';i++;} else q=!q; } else if(c===delim && !q){ out.push(cur.trim()); cur=''; } else cur+=c; } out.push(cur.trim()); return out; };
        const detectDelim = (txt) => { const h=txt.slice(0,300); const sc=(h.match(/;/g)||[]).length, cc=(h.match(/,/g)||[]).length, tc=(h.match(/\t/g)||[]).length; return sc>=cc&&sc>=tc?';':(cc>=sc&&cc>=tc?',':'\t'); };
        const parseNum = (v) => { if(v==null) return null; const t=String(v).replace('%','').replace(/\s/g,'').replace(',','.'); if(t==='') return null; const n=parseFloat(t); return Number.isFinite(n)?n:null; };

        const HEADER_MAP = {
          EAN:['ean','kodean','ean_kod','eanovykod','ean13'],
          NAME:['nazov','nazovpolozky','nazovproduktu','nazovvyrobku','name','produkt','tovar','productname'],
          TYPE:['typpolozky','typ','typproduktu','typkatalogu','typ_polozky'],
          DPH:['dph','sadzbadph','vat','dphsadzba'],
          SALE:['predajnakategoria','predajna_kategoria','kategoria','kategoria_predajna'],
          RCAT:['kategoria_prerecepty','kategoria_pre_recepty','recipecategory','receptkategoria'],
          BATCH:['vyrobnadavkakg','vyrobna_davka_kg','davkakg','batchkg'],
          PACK:['vahabalenia','vahabalenia_g','vaha_g','hmotnostg','weightg'],
          SRC:['zdrojovy_ean','sourceean','zdrojean']
        };
        const buildIndex = (head) => { const idx={}; const H=head.map(norm); for (const [k,ali] of Object.entries(HEADER_MAP)) idx[k]=H.findIndex(h=>ali.includes(h)); return idx; };

        let text; try { text = await f.text(); } catch { showStatus('CSV sa nepodarilo načítať.', true); return; }
        const delim = detectDelim(text);
        const lines = text.split(/\r?\n/).filter(l=>l.trim().length>0);
        if (lines.length<=1){ showStatus('CSV je prázdne.', true); return; }

        const head = SPLIT(lines[0], delim);
        const ix = buildIndex(head);
        if (ix.EAN<0 || ix.NAME<0){ showStatus("V CSV musia byť aspoň stĺpce EAN a Nazov/Názov.", true); return; }

        const callStrict = async (url, body) => {
          const res = await apiRequest(url, { method:'POST', body });
          if (res && (res.error || res.status === 'error')) throw new Error(res.error || res.message || 'Chyba API');
          return res;
        };

        const localKnown = new Set(products.map(p => String(p.ean||'').trim()));
        let ok=0, fail=0;

        for (let i=1;i<lines.length;i++){
          try{
            const cols = SPLIT(lines[i], delim); if (!cols.length) continue;
            const curEAN  = (cols[ix.EAN]  || '').trim();
            const curName = (cols[ix.NAME] || '').trim();
            if (!curEAN || !curName) continue;

            const typ  = ix.TYPE  >= 0 ? (cols[ix.TYPE] || '').trim() : '';
            const dph  = ix.DPH   >= 0 ? parseNum(cols[ix.DPH]) : null;
            const sale = ix.SALE  >= 0 ? (cols[ix.SALE] || '').trim() : '';
            const rcat = ix.RCAT  >= 0 ? (cols[ix.RCAT] || '').trim() : '';
            const batch= ix.BATCH >= 0 && cols[ix.BATCH]!=='' ? parseNum(cols[ix.BATCH]) : null;
            const pack = ix.PACK  >= 0 && cols[ix.PACK] !=='' ? parseNum(cols[ix.PACK])  : null;
            const src  = ix.SRC   >= 0 ? (cols[ix.SRC]   || '').trim() : '';

            const updBody = { ean:curEAN, nazov_vyrobku:curName, typ_polozky:typ, dph, predajna_kategoria:sale,
                              kategoria_pre_recepty:rcat, vyrobna_davka_kg:batch, vaha_balenia_g:pack,
                              source_ean: (src||null), mark_has_recipe_if_sliced: true };

            let updated = false;
            try{
              if (localKnown.has(curEAN)) { await callStrict('/api/kancelaria/updateCatalogItem', updBody); updated = true; }
              else { await callStrict('/api/kancelaria/updateCatalogItem', updBody); updated = true; localKnown.add(curEAN); }
            }catch{ updated = false; }

            if (!updated){
              await callStrict('/api/kancelaria/addCatalogItem', {
                new_catalog_item_type: typ,
                new_catalog_dph: (dph!=null? dph.toFixed(2):''),
                new_catalog_name: curName,
                new_catalog_ean: curEAN,
                new_catalog_sale_category: sale,
                new_catalog_is_made: false
              });
              localKnown.add(curEAN);
              try{ await callStrict('/api/kancelaria/updateCatalogItem', updBody); }catch{}
            }

            // === okamžitý SHADOW + lokálny sync ==========
            const patch = { ean:curEAN, nazov_vyrobku:curName, typ_polozky:typ, dph, predajna_kategoria:sale,
                            kategoria_pre_recepty:rcat, vyrobna_davka_kg:batch, vaha_balenia_g:pack, source_ean:(src||null) };
            shadow[curEAN] = { ...(shadow[curEAN]||{}), ...patch };
            if (!byEAN.has(curEAN)) { products.push(patch); byEAN.set(curEAN, patch); byName.set(curName, patch); }
            else { Object.assign(byEAN.get(curEAN), patch); }

            const isSliced = String(typ||'').toUpperCase().startsWith('VÝROBOK_K');
            if (isSliced && src) noRecipeSet.delete(curName);

            ok++;
          }catch{ fail++; }
        }

        // po importe vypni filter „len bez receptu“ a ukáž všetko
        if (cb) cb.checked = false;
        if (sel) sel.value = '';
        renderTable();

        showStatus(`Import CSV dokončený: ${ok} OK, ${fail} chýb.`, fail>0);

        // plný refresh a merge zo servera (hneď, bez reloadu)
        try{
          const fresh = await apiRequest('/api/kancelaria/getCatalogManagementData?ts=' + Date.now());
          const merged = mergeProducts(fresh?.products || []);
          products = merged;
          byEAN.clear(); byName.clear();
          products.forEach(p => { byEAN.set(String(p.ean||'').trim(), p); byName.set(String(p.nazov_vyrobku||'').trim(), p); });
          renderTable();
        }catch{}
        // reset input
        e.target.value = '';
      });

      // === edit/delete + add ==========================================
      tbody?.addEventListener('click', (ev)=>{
        const row = ev.target.closest('tr[data-ean]');
        if (!row) return;
        const ean = row.getAttribute('data-ean');
        const p = byEAN.get(ean); if (!p) return;

        if (ev.target.closest('.btn-edit')) openEditModal(p);
        if (ev.target.closest('.btn-del'))  confirmDelete(p);
      });

      function openEditModal(p){
        const recipeCats = base.recipeCategories || [];
        const SRC_TYPES = ['VÝROBOK','VÝROBOK_KRAJANY','VÝROBOK_KUSOVY','PRODUKT','Produkt','produkt'];
        const srcCandidates = products.filter(x => SRC_TYPES.includes(String(x.typ_polozky||'').toUpperCase()));
        const datalistIdEAN='__src_eans', datalistIdNAME='__src_names';

        const html = `
          <form id="cat-edit-form" style="max-width:920px">
            <div class="form-grid">
              <div class="form-group"><label>EAN</label><input id="edit-ean" type="text" required value="${escapeHtml(p.ean||'')}"></div>
              <div class="form-group"><label>Názov</label><input id="edit-name" type="text" required value="${escapeHtml(p.nazov_vyrobku||'')}"></div>
              <div class="form-group"><label>Typ položky</label><select id="edit-type" required>${selectOpts(itemTypes,true,p.typ_polozky)}</select></div>
            </div>
            <div class="form-grid">
              <div class="form-group"><label>Sadzba DPH</label><select id="edit-dph" required>${selectOpts((dphRates||[]).map(r=>Number(r).toFixed(2)),true,(Number(p.dph||0)).toFixed(2))}</select></div>
              <div class="form-group"><label>Predajná kategória</label><select id="edit-sale">${selectOpts(saleCats,true,p.predajna_kategoria)}</select></div>
              <div class="form-group">
                <label>Kategória pre recepty</label>
                <input id="edit-rcat" list="__rcats" type="text" value="${escapeHtml(p.kategoria_pre_recepty||'')}">
                <datalist id="__rcats">${(recipeCats||[]).map(c=>`<option value="${escapeHtml(c)}">`).join('')}</datalist>
              </div>
            </div>
            <div class="form-grid">
              <div class="form-group"><label>Výrobná dávka (kg)</label><input id="edit-batch" type="number" step="0.001" min="0" value="${p.vyrobna_davka_kg!=null?p.vyrobna_davka_kg:''}"></div>
              <div class="form-group"><label>Váha balenia (g)</label><input id="edit-pack" type="number" step="1" min="0" value="${p.vaha_balenia_g!=null?p.vaha_balenia_g:''}"></div>
            </div>
            <fieldset style="border:1px solid #e5e7eb;border-radius:8px;padding:10px;margin-top:10px;">
              <legend style="font-size:.95rem;color:#334155;">Zdrojový produkt pre krájané/kusové balenia</legend>
              <div class="form-grid">
                <div class="form-group">
                  <label>Zdrojový produkt – EAN</label>
                  <input id="edit-src-ean" list="${datalistIdEAN}" type="text" value="${escapeHtml(p.source_ean||'')}">
                  <datalist id="${datalistIdEAN}">
                    ${srcCandidates.map(s=>`<option value="${escapeHtml(s.ean||'')}">${escapeHtml(s.nazov_vyrobku||'')}</option>`).join('')}
                  </datalist>
                </div>
                <div class="form-group">
                  <label>Zdrojový produkt – názov</label>
                  <input id="edit-src-name" list="${datalistIdNAME}" type="text" value="${escapeHtml(p.source_name||'')}">
                  <datalist id="${datalistIdNAME}">
                    ${srcCandidates.map(s=>`<option value="${escapeHtml(s.nazov_vyrobku||'')}">${escapeHtml(s.ean||'')}</option>`).join('')}
                  </datalist>
                </div>
                <div class="form-group">
                  <label>&nbsp;</label>
                  <button type="button" id="clear-src" class="btn-secondary">Odstrániť zdroj</button>
                </div>
              </div>
            </fieldset>
            <div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:.5rem;">
              <button type="button" class="btn-secondary" id="edit-cancel">Zavrieť</button>
              <button type="submit"  class="btn-primary"><i class="fas fa-save"></i> Uložiť zmeny</button>
            </div>
          </form>
        `;
        openModalCompat('Upraviť položku – ' + (p.nazov_vyrobku||p.ean||''), {
          html,
          onReady(){
            document.getElementById('clear-src')?.addEventListener('click', ()=>{
              const a=document.getElementById('edit-src-ean'); const b=document.getElementById('edit-src-name');
              if(a) a.value=''; if(b) b.value='';
            });
            document.getElementById('edit-cancel')?.addEventListener('click', hideModalCompat);
            document.getElementById('cat-edit-form')?.addEventListener('submit', async (e)=>{
              e.preventDefault();
              const payload = {
                id: p.id ?? p.produkt_id ?? null,
                original_ean: String(p.ean||''),
                ean: document.getElementById('edit-ean')?.value?.trim(),
                nazov_vyrobku: document.getElementById('edit-name')?.value?.trim(),
                typ_polozky: document.getElementById('edit-type')?.value || '',
                dph: parseFloat(String(document.getElementById('edit-dph')?.value||'').replace(',','.')),
                predajna_kategoria: document.getElementById('edit-sale')?.value || '',
                kategoria_pre_recepty: document.getElementById('edit-rcat')?.value || '',
                vyrobna_davka_kg: (()=>{
                  const v = document.getElementById('edit-batch')?.value; return v===''? null : parseFloat(String(v).replace(',','.'));
                })(),
                vaha_balenia_g: (()=>{
                  const v = document.getElementById('edit-pack')?.value; return v===''? null : parseFloat(String(v).replace(',','.'));
                })(),
                source_ean: (document.getElementById('edit-src-ean')?.value||'').trim() || null,
                source_name:(document.getElementById('edit-src-name')?.value||'').trim() || null,
                mark_has_recipe_if_sliced: true
              };
              if (!payload.ean || !payload.nazov_vyrobku){ showStatus('EAN aj Názov sú povinné.', true); return; }
              try{
                await apiRequest('/api/kancelaria/updateCatalogItem', { method:'POST', body: payload });
                // SHADOW + lokálny sync (hneď uvidíš zmenu)
                const patch = { ean:payload.ean, nazov_vyrobku:payload.nazov_vyrobku, typ_polozky:payload.typ_polozky,
                                dph:payload.dph, predajna_kategoria:payload.predajna_kategoria,
                                kategoria_pre_recepty:payload.kategoria_pre_recepty, vyrobna_davka_kg:payload.vyrobna_davka_kg,
                                vaha_balenia_g:payload.vaha_balenia_g, source_ean:payload.source_ean, source_name:payload.source_name };
                shadow[payload.ean] = { ...(shadow[payload.ean]||{}), ...patch };
                if (!byEAN.has(payload.ean)) { products.push(patch); byEAN.set(payload.ean, patch); byName.set(payload.nazov_vyrobku, patch); }
                else { Object.assign(byEAN.get(payload.ean), patch); }
                // ak je krájaný/kusový a má zdroj, skry z „bez receptu“
                const isSliced = String(payload.typ_polozky||'').toUpperCase().startsWith('VÝROBOK_K');
                if (isSliced && (payload.source_ean || payload.source_name)) noRecipeSet.delete(payload.nazov_vyrobku);
                renderTable();
                showStatus('Zmeny uložené.', false);
                hideModalCompat();
              }catch(err){
                showStatus('Ukladanie zlyhalo: ' + (err?.message || String(err)), true);
              }
            });
          }
        });
      }

      async function confirmDelete(p){
        if (!confirm(`Naozaj zmazať položku:\n\n${p.nazov_vyrobku || p.ean}`)) return;
        try{
          await apiRequest('/api/kancelaria/deleteCatalogItem', { method:'POST', body:{ id:(p.id ?? p.produkt_id ?? null), ean:p.ean } });
          delete shadow[String(p.ean||'').trim()];
          products = products.filter(x => String(x.ean||'') !== String(p.ean||''));
          byEAN.delete(String(p.ean||'')); byName.delete(String(p.nazov_vyrobku||''));
          renderTable();
          showStatus('Položka zmazaná.', false);
        }catch(err){
          showStatus('Mazanie zlyhalo: ' + (err?.message || String(err)), true);
        }
      }

      // ADD – doplnenie do shadow + lokál
      document.getElementById('catalog-add-form')?.addEventListener('submit', async (e)=>{
        e.preventDefault();
        const payload = {
          new_catalog_item_type: document.getElementById('cat-new-type')?.value,
          new_catalog_dph:       document.getElementById('cat-new-dph')?.value,
          new_catalog_name:      document.getElementById('cat-new-name')?.value,
          new_catalog_ean:       document.getElementById('cat-new-ean')?.value,
          new_catalog_sale_category: document.getElementById('cat-new-sale-cat')?.value,
          new_catalog_is_made:   !!(document.getElementById('cat-new-made')?.checked)
        };
        if (!payload.new_catalog_item_type || !payload.new_catalog_dph || !payload.new_catalog_name || !payload.new_catalog_ean){
          showStatus('Vyplň všetky povinné polia.', true); return;
        }
        try{
          await apiRequest('/api/kancelaria/addCatalogItem', {method:'POST', body:payload});
          const patch = { ean:payload.new_catalog_ean, nazov_vyrobku:payload.new_catalog_name,
                          typ_polozky:payload.new_catalog_item_type, dph:parseFloat(payload.new_catalog_dph),
                          predajna_kategoria:payload.new_catalog_sale_category };
          shadow[patch.ean] = { ...(shadow[patch.ean]||{}), ...patch };
          products.push(patch); byEAN.set(patch.ean, patch); byName.set(patch.nazov_vyrobku, patch);
          renderTable();
          showStatus('Položka pridaná.', false);
        }catch(err){
          showStatus('Nepodarilo sa pridať položku: '+(err?.message||String(err)), true);
        }
      });

      // UI eventy
      txt?.addEventListener('input', renderTable);
      sel?.addEventListener('change', renderTable);
      cb?.addEventListener('change', renderTable);
      renderTable();
    };

    return { html, onReady };
  }

  // ===================== MINIMÁLNE ZÁSOBY (EDITOR) =================
  async function viewMinStock(){
    const rows = await apiRequest('/api/kancelaria/getProductsForMinStock') || [];
    const data = Array.isArray(rows) ? rows : [];
    const original = new Map(data.map(r => [String(r.ean), {kg: (r.minStockKg===''||r.minStockKg==null?NaN:Number(r.minStockKg)), ks: (r.minStockKs===''||r.minStockKs==null?NaN:Number(r.minStockKs))}]));

    const html = `
      <div class="erp-panel">
        <div class="panel-head" style="display:flex;justify-content:space-between;gap:.5rem;align-items:center;">
          <h2>Minimálne zásoby (Katalóg výrobkov a tovaru)</h2>
          <div style="display:flex;gap:.5rem;">
            <button class="btn-secondary" id="btn-back-cat">Späť na Katalóg</button>
            <button class="btn-primary" id="btn-save-min">Uložiť minimálne zásoby</button>
          </div>
        </div>

        <div class="stat-card" style="margin-bottom:.75rem;">
          <div class="form-grid" style="grid-template-columns: 1.2fr 1fr;">
            <div class="form-group"><label>Filtrovať názov/EAN</label><input id="ms-filter" type="text" placeholder="napr. klobása / 8580..." /></div>
            <div class="form-group" style="display:flex;align-items:flex-end;gap:.5rem;">
              <input type="checkbox" id="ms-only-changed" />
              <label for="ms-only-changed" style="margin:0;">Zobraziť len zmenené položky</label>
            </div>
          </div>
        </div>

        <div class="table-wrap">
          <table class="tbl" id="ms-table">
            <thead>
              <tr>
                <th style="width:140px;">EAN</th>
                <th>Názov</th>
                <th style="width:90px;">MJ</th>
                <th style="width:140px; text-align:right;">Min (kg)</th>
                <th style="width:140px; text-align:right;">Min (ks)</th>
              </tr>
            </thead>
            <tbody>
              ${data.map(r => `
                <tr data-ean="${String(r.ean)}">
                  <td>${String(r.ean)}</td>
                  <td>${escapeHtml(r.name)}</td>
                  <td>${escapeHtml(r.mj||'')}</td>
                  <td style="text-align:right">
                    <input class="ms-kg" type="number" step="0.001" min="0" placeholder="—" value="${(r.minStockKg ?? '')}" style="width:120px;text-align:right;">
                  </td>
                  <td style="text-align:right">
                    <input class="ms-ks" type="number" step="1" min="0" placeholder="—" value="${(r.minStockKs ?? '')}" style="width:120px;text-align:right;">
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

    const onReady = ()=>{
      const backBtn  = document.getElementById('btn-back-cat');
      if (backBtn) backBtn.onclick = ()=> window.erpMount(viewCatalogManagement);

      const tbl = document.getElementById('ms-table');
      const inpFilter = document.getElementById('ms-filter');
      const cbChanged = document.getElementById('ms-only-changed');

      function isChanged(tr){
        const ean = String(tr?.dataset?.ean||'');
        const kg = tr.querySelector('.ms-kg')?.value ?? '';
        const ks = tr.querySelector('.ms-ks')?.value ?? '';
        const o  = original.get(ean) || {kg: NaN, ks: NaN};
        const kgN = kg==='' ? NaN : Number(kg);
        const ksN = ks==='' ? NaN : Number(ks);
        const okg = isNaN(o.kg) ? NaN : Number(o.kg);
        const oks = isNaN(o.ks) ? NaN : Number(o.ks);
        return (isNaN(kgN) !== isNaN(okg)) || (!isNaN(kgN) && kgN !== okg) || (isNaN(ksN) !== isNaN(oks)) || (!isNaN(ksN) && ksN !== oks);
      }

      function applyFilter(){
        const q = (inpFilter?.value||'').toLowerCase().trim();
        const only = !!cbChanged?.checked;
        tbl?.querySelectorAll('tbody tr')?.forEach(tr=>{
          const e = tr.dataset.ean || '';
          const n = tr.children[1]?.textContent || '';
          const hay = (e + ' ' + n).toLowerCase();
          const matchQ = !q || hay.includes(q);
          const matchC = !only || isChanged(tr);
          tr.style.display = (matchQ && matchC) ? '' : 'none';
        });
      }
      inpFilter?.addEventListener('input', applyFilter);
      cbChanged?.addEventListener('change', applyFilter);

      const saveBtn = document.getElementById('btn-save-min');
      if (saveBtn){
        saveBtn.onclick = async ()=>{
          const payload = [];
          tbl?.querySelectorAll('tbody tr')?.forEach(tr=>{
            const ean = tr.dataset.ean;
            const kgv = tr.querySelector('.ms-kg')?.value ?? '';
            const ksv = tr.querySelector('.ms-ks')?.value ?? '';
            if (ean) payload.push({ ean, minStockKg: kgv, minStockKs: ksv });
          });
          if (!payload.length){ showStatus('Žiadne dáta na uloženie.', true); return; }
          try {
            const res = await apiRequest('/api/kancelaria/updateMinStockLevels', { method:'POST', body: payload });
            payload.forEach(p=>{ original.set(String(p.ean), { kg: (p.minStockKg===''?NaN:Number(p.minStockKg)), ks: (p.minStockKs===''?NaN:Number(p.minStockKs)), }); });
            showStatus(res?.message || 'Minimálne zásoby uložené.', false);
            applyFilter();
          } catch (err){ showStatus('Ukladanie zlyhalo: ' + (err?.message || String(err)), true); }
        };
      }
    };

    return { html, onReady };
  }

  // ===================== NOVÝ RECEPT (INLINE) ======================
  async function viewCreateRecipeInline() {
    await ensureOfficeDataIsLoaded();
    await ensureWarehouseCache(true);
    const base = getOfficeData();

    const productOpts = (base.productsWithoutRecipe || []).map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
    const catOpts = (base.recipeCategories || []).map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');

    const html = `
      <div class="stat-card">
        <h3 style="margin-top:0;">Nový recept</h3>
        <form id="rcp-create-form" autocomplete="off">
          <div class="form-grid">
            <div class="form-group">
              <label>Produkt (existujúci „VÝROBOK“ bez receptu)</label>
              <select id="rcp-product" required>
                <option value="">-- Vyberte produkt --</option>
                ${productOpts}
              </select>
            </div>
            <div class="form-group">
              <label>Kategória receptu</label>
              <select id="rcp-cat"><option value="">-- Vyberte --</option>${catOpts}</select>
              <small>alebo nová:</small>
              <input id="rcp-newcat" type="text" placeholder="Nová kategória (nepovinné)">
            </div>
          </div>

          <h4 style="margin-top:1rem;">Suroviny podľa kategórií</h4>
          <div class="form-grid" style="grid-template-columns:repeat(4,minmax(280px,1fr)); gap:1rem;">
            ${['maso','koreniny','obal','pomocny_material'].map(key => `
              <div class="classSlot stat-card">
                <h5>${escapeHtml(({'maso':'Mäso','koreniny':'Koreniny','obal':'Obaly - Črevá','pomocny_material':'Pomocný materiál'})[key])}</h5>
                <input type="text" class="flt" data-key="${key}" placeholder="Hľadať..." style="width:100%;margin:0 0 .5rem 0;">
                <select class="sel" data-key="${key}" size="10" style="width:100%;min-height:220px;"></select>
                <div style="display:flex;gap:.5rem;align-items:center;margin-top:.5rem;">
                  <input class="qty" data-key="${key}" type="number" step="0.001" min="0" placeholder="kg" style="flex:1;">
                  <button type="button" class="btn-secondary add" data-key="${key}" style="width:auto;">Pridať</button>
                </div>
                <div class="muted" style="font-size:.85rem;">Posledná cena: <span class="price" data-key="${key}">—</span></div>
              </div>`).join('')}
          </div>

          <h4 style="margin-top:1rem;">Súpis surovín</h4>
          <div class="table-container">
            <table id="rcp-table" style="width:100%;">
              <thead><tr><th>Kategória</th><th>Názov</th><th>Množstvo (kg)</th><th>Cena €/kg</th><th></th></tr></thead>
              <tbody></tbody>
            </table>
          </div>

          <div id="rcp-cost" class="muted" style="margin:1rem 0;">Odhad ceny dávky: —</div>

          <div style="display:flex; gap:.75rem; justify-content:flex-end;">
            <button type="submit" class="btn-primary"><i class="fas fa-save"></i> Uložiť recept</button>
          </div>
        </form>
      </div>
    `;

    const onReady = async () => {
      const tbody = document.querySelector('#rcp-table tbody');
      const parseNum = (v) => parseFloat(String(v).replace(',','.'));

      const catKeys = ['maso','koreniny','obal','pomocny_material'];
      const namesByKey = {};
      const heur = {
        maso:   n => /mäso|maso|brav|hoväd|kurac|morč|mork|slanina|pečeň|pecen/i.test(n),
        koreniny:n=> /koren|paprik|rasc|cesnak|soľ|sol|pepper|kmín|kmin/i.test(n),
        obal:   n => /obal|črev|cerv|vak|fóli|foli|obalovac/i.test(n),
        pomocny_material:n=> /voda|ľad|lad|ovar|ľadová/i.test(n)
      };

      async function fetchList(key){
        let arr = [];
        try{
          const r = await apiRequest(`/api/kancelaria/stock/allowed-names?category=${encodeURIComponent(key)}`);
          arr = (r?.items||[]).map(i=>({ name:String(i.name), price:(i.last_price!=null?Number(i.last_price):null) }));
        }catch(_){ arr = []; }
        if (!arr.length){
          try{
            const rAll = await apiRequest(`/api/kancelaria/stock/allowed-names?category=__all`);
            const all  = (rAll?.items||[]).map(i=>({ name:String(i.name), price:(i.last_price!=null?Number(i.last_price):null) }));
            arr = all.filter(x => heur[key](x.name));
            if (key==='pomocny_material'){
              const names = new Set(arr.map(i=>i.name.toLowerCase()));
              ['Voda','Ľad','Ovar'].forEach(nm=>{ if(!names.has(nm.toLowerCase())) arr.push({name:nm, price:0.20}); });
            }
          }catch(_){}
        }
        namesByKey[key] = arr.sort((a,b)=> byLocale(a.name,b.name));
      }
      await Promise.all(catKeys.map(fetchList));

      function fillSelect(key, filter=''){
        const sel = document.querySelector(`select.sel[data-key="${key}"]`);
        const priceSpan = document.querySelector(`.price[data-key="${key}"]`);
        if (!sel || !priceSpan) return;
        const list = (namesByKey[key] || []).filter(x => x.name.toLowerCase().includes((filter||'').toLowerCase()));
        sel.innerHTML = list.map(x => `<option data-name="${escapeHtml(x.name)}" data-price="${x.price ?? ''}">${escapeHtml(x.name)}</option>`).join('');
        priceSpan.textContent = '—';
        sel.onchange = () => {
          const p = sel.selectedOptions[0]?.dataset.price;
          priceSpan.textContent = p ? `${parseFloat(p).toFixed(2)} €/kg` : '—';
        };
      }

      // init panely
      catKeys.forEach((k) => {
        const sel = document.querySelector(`select.sel[data-key="${k}"]`);
        const flt = document.querySelector(`input.flt[data-key="${k}"]`);
        fillSelect(k, '');
        if (flt) flt.addEventListener('input', () => fillSelect(k, flt.value));
        if (sel) sel.addEventListener('change', () => sel.onchange && sel.onchange());
      });

      function recomputeCost() {
        if (!tbody) return;
        let sum = 0;
        tbody.querySelectorAll('tr').forEach((tr) => {
          const qty  = parseNum(tr.querySelector('.qty')?.value || 0) || 0;
          const pstr = tr.querySelector('.p')?.textContent || '0';
          const price= parseNum(pstr) || 0;
          sum += qty * price;
        });
        const costEl = document.getElementById('rcp-cost');
        if (costEl) costEl.textContent = sum ? `Odhad ceny dávky: ${sum.toFixed(2)} €` : 'Odhad ceny dávky: —';
      }

      function addToTable(key) {
        if (!tbody) return;
        const sel = document.querySelector(`select.sel[data-key="${key}"]`);
        const qtyEl = document.querySelector(`input.qty[data-key="${key}"]`);
        if (!sel || !qtyEl) return;
        const name  = sel.selectedOptions[0]?.dataset.name || '';
        const price = parseNum(sel.selectedOptions[0]?.dataset.price || 0);
        const qty   = parseNum(qtyEl.value);
        if (!name || !qty || qty <= 0) { showStatus('Vyberte surovinu a zadajte množstvo.', true); return; }

        const trEl = document.createElement('tr');
        trEl.innerHTML = `
          <td>${escapeHtml(({'maso':'Mäso','koreniny':'Koreniny','obal':'Obaly – Črevá','pomocny_material':'Pomocný materiál'})[key])}</td>
          <td>${escapeHtml(name)}</td>
          <td><input type="number" class="qty" step="0.001" min="0" value="${qty.toFixed(3)}" style="width:120px"></td>
          <td class="p">${price ? price.toFixed(2) : '0.00'}</td>
          <td><button type="button" class="btn-danger del" title="Odstrániť" style="margin:0;padding:4px 8px;width:auto;">X</button></td>
        `;
        trEl.querySelector('.del').onclick = () => { trEl.remove(); recomputeCost(); };
        trEl.querySelector('.qty').oninput = recomputeCost;

        tbody.appendChild(trEl);
        qtyEl.value = '';
        sel.focus();
        recomputeCost();
      }

      document.querySelectorAll('.add[data-key]').forEach(btn=>{
        btn.addEventListener('click', ()=> addToTable(btn.dataset.key));
      });

      const form = document.getElementById('rcp-create-form');
      if (form) form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const productName = document.getElementById('rcp-product')?.value || '';
        const newCategory = document.getElementById('rcp-newcat')?.value.trim() || '';
        const existingCat = document.getElementById('rcp-cat')?.value || '';
        if (!productName){ showStatus('Vyberte produkt.', true); return; }
        if (!newCategory && !existingCat){ showStatus('Zvoľte kategóriu alebo zadajte novú.', true); return; }
        const rows = tbody ? Array.from(tbody.querySelectorAll('tr')) : [];
        const ingredients = rows.map(tr => ({
          name: tr.children[1].textContent,
          quantity: parseFloat(tr.querySelector('.qty').value)
        })).filter(x => x.name && x.quantity > 0);
        if (!ingredients.length){ showStatus('Recept musí obsahovať aspoň jednu surovinu.', true); return; }

        await apiRequest('/api/kancelaria/addNewRecipe', {
          method: 'POST',
          body: { productName, ingredients, category: existingCat, newCategory }
        });
        showStatus('Recept uložený.', false);
        window.erpMount(() => renderRecipeEditorInline(productName));
      });
    };

    return { html, onReady };
  }

  // ===================== ZOZNAM/ÚPRAVA RECEPTOV ====================
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
    const onReady = ()=>{ document.querySelectorAll('.rcp-open').forEach(btn=> btn.addEventListener('click', ()=> window.erpMount(()=> renderRecipeEditorInline(btn.dataset.name))) ); };
    return { html, onReady };
  }

  // ===================== EDITOR RECEPTU (INLINE) ===================
  async function renderRecipeEditorInline(productName){
    await ensureOfficeDataIsLoaded();
    await ensureWarehouseCache(true);
    const base = getOfficeData();
    const details = await apiRequest('/api/kancelaria/getRecipeDetails', {method:'POST', body:{productName}});

    const catOpts = (base.recipeCategories||[]).map(c=>`<option value="${escapeHtml(c)}" ${details?.category===c?'selected':''}>${escapeHtml(c)}</option>`).join('');

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
      </div>`;

    const onReady = ()=>{
      const host = $('#rcp-ingredients');
      const categories = (base.itemTypes || ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál']);
      const parseNum = v=> parseFloat(String(v).replace(',','.'));

      async function buildNameOptions(cat, selectEl, priceEl){
        if (!cat){ selectEl.innerHTML = '<option value="">-- Najprv vyberte kategóriu --</option>'; priceEl.textContent='—'; return; }
        try{
          const data = await apiRequest(`/api/kancelaria/stock/allowed-names?category=${encodeURIComponent(cat)}`);
          const items = data?.items || [];
          if (!items.length) throw new Error('Žiadne položky pre danú kategóriu.');
          selectEl.innerHTML = `<option value="">-- Vyberte --</option>` + items.map(i=>`<option data-price="${i.last_price ?? ''}" value="${escapeHtml(i.name)}">${escapeHtml(i.name)}</option>`).join('');
          selectEl.onchange = ()=>{ const p=selectEl.selectedOptions[0]?.dataset.price; priceEl.textContent = p?`${parseFloat(p).toFixed(2)} €/kg`:'—'; recomputeCost(); };
        }catch(err){
          console.warn('[ERP] allowed-names (editor) zlyhalo, prepínam na textové pole:', err);
          const input=document.createElement('input'); input.type='text'; input.placeholder='Názov suroviny'; input.className='rcp-name-input';
          selectEl.replaceWith(input);
        }
      }

      function addRow(prefill){
        const row=document.createElement('div');
        row.className='recipe-ingredient-row';
        row.innerHTML=`
          <div class="form-grid">
            <div class="form-group">
              <label>Kategória suroviny</label>
              <select class="rcp-cat-sel">
                <option value="">-- Vyberte --</option>
                ${categories.map(c=>`<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')}
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
          </div>`;
        host.appendChild(row);

        const selCat=row.querySelector('.rcp-cat-sel');
        const selName=row.querySelector('.rcp-name-sel');
        const priceEl=row.querySelector('.rcp-price');
        const qtyEl=row.querySelector('.rcp-qty');

        selCat.onchange=()=> buildNameOptions(selCat.value, selName, priceEl);
        qtyEl.oninput=recomputeCost;
        row.querySelector('.rcp-del').onclick=()=>{ row.remove(); recomputeCost(); };

        if (prefill){
          selCat.value=prefill.category||''; selCat.dispatchEvent(new Event('change'));
          setTimeout(()=>{ selName.value=prefill.name||''; selName.dispatchEvent(new Event('change')); qtyEl.value=prefill.quantity??''; recomputeCost(); },200);
        }
      }

      function recomputeCost(){
        const rows = Array.from(document.querySelectorAll('#rcp-ingredients .recipe-ingredient-row'));
        let sum=0;
        for (const r of rows){
          const sel=r.querySelector('.rcp-name-sel');
          const qty=parseNum(r.querySelector('.rcp-qty').value||0)||0;
          const price=parseNum(sel?.selectedOptions?.[0]?.dataset.price||'')||0;
          sum += qty*price;
        }
        const costEl = $('#rcp-cost'); if (costEl) costEl.textContent = sum ? `Odhad ceny dávky: ${sum.toFixed(2)} €` : 'Odhad ceny dávky: —';
      }

      (details?.ingredients||[]).forEach(ing=> addRow({category:ing.category||'', name:ing.name, quantity:ing.quantity}) );
      if (!(details?.ingredients||[]).length) addRow();

      onClick('#rcp-add-row', ()=> addRow());
      onClick('#rcp-save', async ()=>{
        const newCategory=$('#rcp-newcat')?.value.trim()||'';
        const existingCat=$('#rcp-cat')?.value||'';
        const rows = Array.from(document.querySelectorAll('#rcp-ingredients .recipe-ingredient-row'));
        const parseNum = v=> parseFloat(String(v).replace(',','.'));
        const ingredients = rows.map(r=>({
          name: r.querySelector('.rcp-name-sel') ? r.querySelector('.rcp-name-sel').value
               : (r.querySelector('.rcp-name-input') ? r.querySelector('.rcp-name-input').value.trim() : ''),
          quantity: parseNum(r.querySelector('.rcp-qty').value)
        })).filter(i=> i.name && i.quantity>0);
        await apiRequest('/api/kancelaria/updateRecipe', {method:'POST', body:{productName, ingredients, category:existingCat, newCategory}});
        showStatus('Recept uložený.', false);
      });
      onClick('#rcp-delete', async ()=>{
        if (!confirm('Naozaj vymazať recept?')) return;
        await apiRequest('/api/kancelaria/deleteRecipe', {method:'POST', body:{productName}});
        showStatus('Recept vymazaný.', false);
        window.erpMount(viewEditRecipeListInline);
      });
    };

    return { html, onReady };
  }

  // ===================== KRÁJANÉ PRODUKTY ==========================
  async function viewSlicingManagement(){
    const data = await apiRequest('/api/kancelaria/getSlicingManagementData');

    const sourceOptions = (data?.sourceProducts||[])
      .map(p=>`<option value="${escapeHtml(p.ean)}">${escapeHtml(p.name)}</option>`)
      .join('');

    const rows = (data?.slicedProducts||[]).map(p=>{
      const linked = !!(p.zdrojovy_ean && String(p.zdrojovy_ean).trim() !== '' && String(p.zdrojovy_ean).toLowerCase() !== 'nan');
      const weightVal = (p.vaha_balenia_g!=null && p.vaha_balenia_g!=='') ? Number(p.vaha_balenia_g).toFixed(0) : '';
      const status = linked ? `prepojené: <code>${escapeHtml(p.zdrojovy_ean)}</code>` : '<b>neprepojené</b>';
      const btnLbl = linked ? 'Zmeniť zdroj' : 'Prepojiť';
      return `<tr data-target-ean="${escapeHtml(p.ean)}">
        <td>${escapeHtml(p.name)}</td>
        <td>${escapeHtml(p.ean)}</td>
        <td style="text-align:right">
          <input class="slc-weight" type="number" min="1" step="1" placeholder="g" value="${weightVal}" style="width:100px;text-align:right;">
        </td>
        <td>${status}</td>
        <td><button class="btn-primary link-sliced" style="margin:0;width:auto;">${btnLbl}</button></td>
      </tr>`;
    }).join('') || '<tr><td colspan="5">Žiadne krájané produkty.</td></tr>';

    const html = `
      <div class="stat-card">
        <label for="slc-source"><b>1.</b> Vyberte zdrojový produkt (celok)</label>
        <select id="slc-source"><option value="">-- Vyberte --</option>${sourceOptions}</select>
      </div>

      <div class="table-container" id="slc-target" style="margin-top:16px;">
        <h4><b>2.</b> Priraďte krájaný produkt (balíček)</h4>
        <table class="tbl">
          <thead><tr><th>Názov</th><th>EAN</th><th style="text-align:right">Váha (g)</th><th>Stav</th><th>Akcia</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;

    const onReady = ()=>{
      const srcSel = $('#slc-source');
      $('#slc-target')?.addEventListener('click', async e=>{
        const btn = e.target.closest?.('.link-sliced'); if (!btn) return;
        const tr = btn.closest('tr');
        const sourceEan = srcSel?.value||''; if (!sourceEan){ showStatus('Najprv vyberte zdrojový produkt (celok).', true); return; }
        const targetEan = tr?.dataset?.targetEan; if (!targetEan) return;
        const w = tr?.querySelector('.slc-weight')?.value;
        const wNum = Number(w);
        if (!w || isNaN(wNum) || wNum <= 0){ showStatus('Zadajte váhu balíčka v gramoch (> 0).', true); return; }
        try{
          const resp = await apiRequest('/api/kancelaria/linkSlicedProduct', { method:'POST', body:{ sourceEan, targetEan, weight: wNum } });
          // okamžitá vizuálna odozva
          tr.querySelector('.slc-weight').value = String(resp?.savedWeight ?? wNum);
          const statusCell = tr.children[3];
          if (statusCell) statusCell.innerHTML = `prepojené: <code>${escapeHtml(sourceEan)}</code>`;
          showStatus('Prepojené.', false);
          window.erpMount(viewSlicingManagement);
        }catch(err){
          showStatus('Prepojenie zlyhalo: ' + (err?.message || String(err)), true);
        }
      });
    };

    return { html, onReady };
  }

  // ------------------ Export init do globálu -----------------------
  window.initializeErpAdminModule = initializeErpAdminModule;

})(window, document);
