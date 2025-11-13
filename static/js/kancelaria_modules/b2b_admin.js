// static/js/kancelaria_modules/b2b_admin.js
// =================================================================
// === SUB-MODUL KANCELÁRIA: B2B ADMIN (inline editor, bez modálov) =
// === Rozšírené o záložku „Komunikácia“ (správy zákazník ↔ kancelária)
// =================================================================
(function (root, doc) {
  'use strict';

  // ---- Fallback utily (ak by neboli načítané z common.js) ----------
  const showStatus = (root.showStatus) ? root.showStatus : (msg, isError=false)=>{
    (isError?console.error:console.log)(msg);
    const el = doc.getElementById('status-bar');
    if (el) { el.textContent = msg; el.style.color = isError?'#b91c1c':'#166534'; }
  };
  const escapeHtml = (root.escapeHtml) ? root.escapeHtml : (s)=>String(s ?? '')
    .replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const apiRequest = (root.apiRequest) ? root.apiRequest : async (url, opts={})=>{
    const res = await fetch(url, {
      method: opts.method || 'GET',
      headers: {'Content-Type': 'application/json'},
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials: 'same-origin'
    });
    if (!res.ok) { let t=''; try{ t=await res.text(); }catch(_){ } throw new Error(`HTTP ${res.status} ${res.statusText} – ${t.slice(0,200)}`); }
    const ct = (res.headers.get('content-type')||'').toLowerCase();
    return ct.includes('application/json') ? res.json() : {};
  };

  // form-data POST (bez Content-Type hlavičky, kvôli prílohám)
  async function apiPostForm(url, formData){
    const res = await fetch(url, { method:'POST', body: formData, credentials:'same-origin' });
    const ct = (res.headers.get('content-type')||'').toLowerCase();
    const out = ct.includes('application/json') ? await res.json() : {};
    if (!res.ok || out.error) throw new Error(out.error || `HTTP ${res.status} ${res.statusText}`);
    return out;
  }

  // ---- Pomocné ------------------------------------------------------
  const state = {
    customers: [],
    pricelists: [],
    mapping: {},             // { zakaznik_id (login) : [cennik_id,...] }
    productsByCategory: {},  // { category: [{ ean, nazov_vyrobku, dph, mj, ... }, ...] }
    productsByEan: {},       // { ean: { ean, name } }
  };

  function h(tag, attrs = {}, html = '') {
    const el = doc.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else el.setAttribute(k, v);
    });
    if (html) el.innerHTML = html;
    return el;
  }

  function ensureContainer(id) {
    const el = doc.getElementById(id);
    if (!el) {
      console.error(`Missing container #${id}`);
      showStatus(`Chýba kontajner #${id}`, true);
      return null;
    }
    return el;
  }

  // ---- Bezpečné volanie endpointu (fallback názvy) ------------------
  // POZOR: musí byť async, lebo vo vnútri await-ujeme
async function callFirstOk(calls) {
  let lastErr;
  for (const c of calls) {
    try {
      return await apiRequest(c.url, c.opts || {});
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error('Žiadny endpoint nevrátil OK.');
}

  // ==================================================================
  // INIT & TABS (len jedna aktívna sekcia; tlačidlá zjednotené)
  // ==================================================================
  let unreadTimer = null;

  function initializeB2BAdminModule() {
    const rootEl = doc.getElementById('section-b2b-admin');
    if (!rootEl) return;

    rootEl.innerHTML = `
      <style>
        .badge {
          display:inline-block; min-width:1.5em; padding:0 .4em;
          background:#b91c1c; color:#fff; border-radius:999px; font-size:.75rem;
        }
        .muted { color:#6b7280; }
        .btn-grid { display:grid; gap:.5rem; grid-template-columns:repeat(6,minmax(0,1fr)); }
        .inline-actions { display:flex; gap:.5rem; flex-wrap:wrap; }
        .msg-row { border:1px solid var(--divider,#e5e7eb); border-radius:8px; padding:.6rem; margin-bottom:.6rem; }
        .msg-head { display:flex; justify-content:space-between; align-items:center; gap:.5rem; }
        .msg-body { white-space:pre-wrap; margin-top:.5rem; }
        .msg-reply { margin-top:.6rem; border-top:1px dashed #e5e7eb; padding-top:.6rem; }
        .btn-link { background:none; border:none; color:#2563eb; cursor:pointer; padding:0; }
      </style>

      <h3>B2B Administrácia</h3>
      <div class="b2b-tab-nav btn-grid" style="margin-bottom:.5rem;">
        <button class="btn btn-primary  js-tab" data-b2b-tab="b2b-registrations-tab">Čakajúce registrácie</button>
        <button class="btn btn-secondary js-tab" data-b2b-tab="b2b-customers-tab">Zoznam odberateľov</button>
        <button class="btn btn-secondary js-tab" data-b2b-tab="b2b-pricelists-tab">Správa cenníkov</button>
        <button class="btn btn-secondary js-tab" data-b2b-tab="b2b-orders-tab">Prehľad objednávok</button>
        <button class="btn btn-secondary js-tab" data-b2b-tab="b2b-comm-tab">Komunikácia <span id="b2b-comm-badge" class="badge" style="display:none">0</span></button>
        <button class="btn btn-secondary js-tab" data-b2b-tab="b2b-settings-tab">Nastavenia</button>
      </div>

      <div id="ofc-views" class="stat-card" style="padding:1rem;">
        <div id="b2b-registrations-tab" class="b2b-tab-content" style="display:block;">
          <div id="b2b-registrations-container"></div>
        </div>

        <div id="b2b-customers-tab" class="b2b-tab-content" style="display:none;">
          <div id="b2b-customers-container"></div>
        </div>

        <div id="b2b-pricelists-tab" class="b2b-tab-content" style="display:none;">
          <div id="b2b-pricelists-container"></div>
          <div class="form-group" style="margin-top: 1.5rem;">
            <label for="new-pricelist-name">Vytvoriť nový cenník:</label>
            <div style="display:flex;gap:.5rem;">
              <input type="text" id="new-pricelist-name" placeholder="Názov nového cenníka">
              <button id="add-new-pricelist-btn" class="btn btn-success" style="width:auto;margin:0;">Vytvoriť</button>
            </div>
          </div>
        </div>

        <div id="b2b-orders-tab" class="b2b-tab-content" style="display:none;">
          <div id="b2b-orders-container"></div>
        </div>

        <div id="b2b-comm-tab" class="b2b-tab-content" style="display:none;">
          <div id="b2b-comm-container"></div>
        </div>

        <div id="b2b-settings-tab" class="b2b-tab-content" style="display:none;">
          <div id="b2b-settings-container"></div>
        </div>
      </div>
    `;

    const tabButtons  = rootEl.querySelectorAll('.js-tab');
    const tabContents = rootEl.querySelectorAll('.b2b-tab-content');

    function stopUnreadPolling(){
      if (unreadTimer) { clearInterval(unreadTimer); unreadTimer = null; }
    }
    function startUnreadPolling(){
      const badge = doc.getElementById('b2b-comm-badge');
      const refresh = async ()=>{
        try{
          const r = await callFirstOk([
            {url:'/api/kancelaria/b2b/messages/unread'},
            {url:'/api/kancelaria/b2b/messages_unread'}
          ]);
          const n = Number((r && r.unread) || 0);
          if (badge){
            if (n > 0){ badge.textContent = String(n); badge.style.display='inline-block'; }
            else { badge.style.display='none'; }
          }
        }catch(_){ /* swallow */ }
      };
      refresh();
      unreadTimer = setInterval(refresh, 30000);
    }

    function setActiveTab(targetId){
      // 1) prepni tlačidlá
      tabButtons.forEach(b => {
        const isActive = (b.dataset.b2bTab === targetId);
        b.classList.toggle('btn-primary',  isActive);
        b.classList.toggle('btn-secondary',!isActive);
      });
      // 2) zobrazenie
      tabContents.forEach(c => { c.style.display = (c.id === targetId ? 'block' : 'none'); });

      // 3) lazy-load + unread
      stopUnreadPolling();
      switch (targetId) {
        case 'b2b-registrations-tab': loadPendingRegistrations(); break;
        case 'b2b-customers-tab':     loadCustomersAndPricelists(); break;
        case 'b2b-pricelists-tab':    loadPricelistsForManagement(); break;
        case 'b2b-orders-tab':        loadB2BOrdersView(); break;
        case 'b2b-comm-tab':          loadCommView(); startUnreadPolling(); break;
        case 'b2b-settings-tab':      loadB2BSettings(); break;
      }
    }

    tabButtons.forEach(btn => btn.addEventListener('click', () => setActiveTab(btn.dataset.b2bTab)));

    // vytvoriť cenník
    const createBtn = rootEl.querySelector('#add-new-pricelist-btn');
    createBtn.onclick = async () => {
      const nameInput = doc.getElementById('new-pricelist-name');
      const name = (nameInput?.value || '').trim();
      if (!name) { showStatus('Názov novej sady nemôže byť prázdny.', true); return; }
      try {
        await callFirstOk([
          {url:'/api/kancelaria/b2b/createPricelist',        opts:{method:'POST', body:{ name }}},
          {url:'/api/kancelaria/b2b/create_pricelist',       opts:{method:'POST', body:{ name }}},
          {url:'/api/kancelaria/b2b/create_pricelist_admin', opts:{method:'POST', body:{ name }}},
        ]);
        nameInput.value = '';
        showStatus('Cenník vytvorený.', false);
        setActiveTab('b2b-pricelists-tab');
      } catch (e) { showStatus(e.message||String(e), true); }
    };

    // default tab
    setActiveTab('b2b-registrations-tab');
  }

  // ==================================================================
// REGISTRÁCIE – načítanie zoznamu + akcie schváliť/odmietnuť
// ==================================================================
async function loadPendingRegistrations(){
  const box = ensureContainer('b2b-registrations-container'); if (!box) return;
  box.innerHTML = '<p>Načítavam čakajúce registrácie…</p>';
  try {
    const data = await callFirstOk([
      { url: '/api/kancelaria/b2b/getPendingB2BRegistrations' },
      { url: '/api/kancelaria/getPendingB2BRegistrations' },
      { url: '/api/kancelaria/b2b/get_pending_registrations' }
    ]);
    const regs = Array.isArray(data) ? data : (data && data.registrations) ? data.registrations : [];
    if (!regs.length) { box.innerHTML = '<p>Žiadne nové registrácie.</p>'; return; }

    let html = `<div class="table-container"><table>
      <thead><tr>
        <th>Názov firmy</th><th>Adresy</th><th>Kontakt</th>
        <th>Dátum</th><th>Prideliť zákaznícke číslo</th><th>Akcie</th>
      </tr></thead><tbody>`;

    regs.forEach(r=>{
      html += `<tr data-id="${r.id}">
        <td>${escapeHtml(r.nazov_firmy || '')}</td>
        <td>
          Fakt.: ${escapeHtml(r.adresa || '—')}<br>
          Dor.: ${escapeHtml(r.adresa_dorucenia || '—')}
        </td>
        <td>${escapeHtml(r.email||'')}<br>${escapeHtml(r.telefon||'')}</td>
        <td>${r.datum_registracie ? new Date(r.datum_registracie).toLocaleDateString('sk-SK') : ''}</td>
        <td>
          <input name="customer_id" class="form-control" placeholder="napr. 9104063_2503918"
                 value="${escapeHtml(r.zakaznik_id && r.zakaznik_id.startsWith('PENDING-') ? '' : (r.zakaznik_id || ''))}">
        </td>
        <td class="inline-actions">
          <button class="btn btn-success"   data-act="approve" data-id="${r.id}">Schváliť</button>
          <button class="btn btn-danger"    data-act="reject"  data-id="${r.id}">Zamietnuť</button>
        </td>
      </tr>`;
    });

    html += `</tbody></table></div>`;
    box.innerHTML = html;

    // schváliť
    box.querySelectorAll('button[data-act="approve"]').forEach(btn=>{
      btn.onclick = async ()=>{
        const tr = btn.closest('tr'); const id = Number(btn.dataset.id);
        const cid = (tr.querySelector('input[name="customer_id"]')?.value || '').trim();
        if (!cid) { showStatus('Zadajte zákaznícke číslo.', true); return; }
        btn.disabled = true; btn.textContent = 'Schvaľujem…';
        try {
          await callFirstOk([
            { url:'/api/kancelaria/approveB2BRegistration', opts:{ method:'POST', body:{ id, customer_id: cid } } }
          ]);
          showStatus('Registrácia schválená.', false);
          tr.remove(); // okamžite zmizne
          // voliteľne aj refresh, ak chceš: loadPendingRegistrations();
        } catch (e) {
          showStatus(e.message || String(e), true);
        } finally {
          btn.disabled = false; btn.textContent = 'Schváliť';
        }
      };
    });

    // zamietnuť
    box.querySelectorAll('button[data-act="reject"]').forEach(btn=>{
      btn.onclick = async ()=>{
        const tr = btn.closest('tr'); const id = Number(btn.dataset.id);
        if (!confirm('Naozaj chcete odmietnuť túto registráciu?')) return;
        btn.disabled = true; btn.textContent = 'Zamietam…';
        try {
          await callFirstOk([
            { url:'/api/kancelaria/rejectB2BRegistration', opts:{ method:'POST', body:{ id } } }
          ]);
          showStatus('Registrácia odmietnutá.', false);
          tr.remove();
        } catch (e) {
          showStatus(e.message || String(e), true);
        } finally {
          btn.disabled = false; btn.textContent = 'Zamietnuť';
        }
      };
    });
  } catch (e) {
    box.innerHTML = `<p class="error">Chyba pri načítaní registrácií: ${escapeHtml(e.message||String(e))}</p>`;
  }
}

  // ==================================================================
  // ZOZNAM ODBERATEĽOV + INLINE EDITOR
  // ==================================================================
  async function loadCustomersAndPricelists(){
    const box = ensureContainer('b2b-customers-container'); if (!box) return;
    box.innerHTML = '<p>Načítavam odberateľov…</p>';
    try {
      const data = await callFirstOk([
        {url:'/api/kancelaria/b2b/getCustomersAndPricelists'},
        {url:'/api/kancelaria/b2b/get_customers_and_pricelists'}
      ]);

      state.customers  = Array.isArray(data?.customers)  ? data.customers  : [];
      state.pricelists = Array.isArray(data?.pricelists) ? data.pricelists : [];
      state.mapping    = (data && data.mapping) ? data.mapping : {};

      if (state.customers.length === 0){
        box.innerHTML = '<p>Žiadni B2B odberatelia neboli nájdení.</p>';
        return;
      }

      const plMap = new Map(state.pricelists.map(p=>[p.id, p.nazov_cennika]));
      let html = `<div class="table-container"><table>
      <thead><tr>
        <th>Login</th><th>Názov</th><th>Kontakt / Adresy</th><th>Priradené cenníky</th><th>Akcia</th>
      </tr></thead><tbody>`;

      state.customers.forEach(c=>{
        const assignedIds = state.mapping[c.zakaznik_id] || state.mapping[c.id] || [];
        const assigned = (assignedIds || []).map(id => plMap.get(Number(id)) || `ID ${id}`).join(', ') || '<i>Žiadny</i>';
        html += `<tr>
          <td>${escapeHtml(c.zakaznik_id||'')}</td>
          <td>${escapeHtml(c.nazov_firmy||'')}</td>
          <td>${escapeHtml(c.email||'')}<br>${escapeHtml(c.telefon||'')}
              <hr style="margin:4px 0;">
              Fakt.: ${escapeHtml(c.adresa||'—')}<br>
              Dor.: ${escapeHtml(c.adresa_dorucenia||'—')}
          </td>
          <td>${assigned}</td>
          <td><button class="btn btn-secondary" data-edit="${c.id}" style="margin:0">Upraviť</button></td>
        </tr>`;
      });
      html += `</tbody></table></div><div id="b2b-customer-editor"></div>`;
      box.innerHTML = html;

      box.querySelectorAll('button[data-edit]').forEach(btn=>{
        btn.onclick = ()=>{
          const id = Number(btn.dataset.edit);
          const cust = state.customers.find(c=> c.id===id);
          if (!cust){ showStatus('Odberateľ sa nenašiel.', true); return; }
          renderCustomerEditorInline(cust);
        };
      });

    } catch (e) {
      box.innerHTML = `<p class="error">Chyba pri načítaní odberateľov: ${escapeHtml(e.message||String(e))}</p>`;
    }
  }

  function renderCustomerEditorInline(customer){
    const host = ensureContainer('b2b-customers-container'); if (!host) return;
    const editor = h('div', { class:'stat-card' });
    const plItems = state.pricelists || [];

    const assignedIds = state.mapping[customer.zakaznik_id] || state.mapping[customer.id] || [];
    let plHtml = '';
    plItems.forEach(p=>{
      const checked = assignedIds.includes(p.id) ? 'checked' : '';
      plHtml += `<label style="display:block;margin:.25rem 0">
        <input type="checkbox" class="pl-chk" value="${p.id}" ${checked}> ${escapeHtml(p.nazov_cennika)}
      </label>`;
    });

    editor.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h3 style="margin:0;">Upraviť odberateľa</h3>
        <div><button class="btn btn-secondary" id="cust-back-btn">Späť na zoznam</button></div>
      </div>
      <div class="form-grid" style="grid-template-columns: 1fr 1fr; gap:16px; margin-top:12px;">
        <div class="form-group"><label>ID (login)</label><input id="cust-login" value="${escapeHtml(String(customer.zakaznik_id||''))}" disabled></div>
        <div class="form-group"><label>Názov firmy</label><input id="cust-name" value="${escapeHtml(customer.nazov_firmy||'')}" placeholder="Názov firmy"></div>
        <div class="form-group"><label>E-mail</label><input id="cust-email" value="${escapeHtml(customer.email||'')}" placeholder="email@firma.sk"></div>
        <div class="form-group"><label>Telefón</label><input id="cust-phone" value="${escapeHtml(customer.telefon||'')}" placeholder="+421…"></div>
        <div class="form-group"><label>Fakturačná adresa</label><textarea id="cust-addr" rows="2">${escapeHtml(customer.adresa||'')}</textarea></div>
        <div class="form-group"><label>Doručovacia adresa</label><textarea id="cust-addr-delivery" rows="2">${escapeHtml(customer.adresa_dorucenia||'')}</textarea></div>
      </div>
      <div class="stat-card" style="margin-top:1rem;">
        <h4>Priradené cenníky</h4>
        <div id="cust-pl-list">${plHtml || '<i>Žiadne cenníky</i>'}</div>
      </div>
      <div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem;">
        <button class="btn btn-primary" id="cust-save-btn">Uložiť</button>
      </div>
    `;

    editor.querySelector('#cust-back-btn').onclick = ()=> loadCustomersAndPricelists();

    editor.querySelector('#cust-save-btn').onclick = async ()=>{
      const ids = Array.from(editor.querySelectorAll('.pl-chk:checked')).map(chk=> Number(chk.value));
      const body = {
        id: customer.id,
        nazov_firmy:       (editor.querySelector('#cust-name').value||'').trim(),
        email:             (editor.querySelector('#cust-email').value||'').trim(),
        telefon:           (editor.querySelector('#cust-phone').value||'').trim(),
        adresa:            (editor.querySelector('#cust-addr').value||'').trim(),
        adresa_dorucenia:  (editor.querySelector('#cust-addr-delivery').value||'').trim(),
        pricelist_ids:     ids
      };
      if (!body.nazov_firmy){ showStatus('Vyplňte názov firmy.', true); return; }
      try{
        await callFirstOk([
          {url:'/api/kancelaria/b2b/updateCustomer',          opts:{method:'POST', body}},
          {url:'/api/kancelaria/b2b/updateCustomerDetails',   opts:{method:'POST', body}},
          {url:'/api/kancelaria/b2b/update_customer_details', opts:{method:'POST', body}},
        ]);
        showStatus('Odberateľ bol uložený.', false);
        // lokálne obnov mapping
        state.mapping[customer.zakaznik_id] = ids;
        loadCustomersAndPricelists();
      }catch(e){ showStatus(e.message||String(e), true); }
    };

    const mount = doc.getElementById('b2b-customers-container');
    const old = doc.getElementById('b2b-customer-editor');
    if (old) old.remove();
    const holder = h('div', { id:'b2b-customer-editor' });
    holder.appendChild(editor);
    mount.appendChild(holder);
    holder.scrollIntoView({behavior:'smooth', block:'start'});
  }

  // ==================================================================
  // SPRÁVA CENNÍKOV + INLINE EDITOR
  // ==================================================================
  function buildCategoriesFromFlatProducts(products){
    const out = {};
    const byEan = {};
    (products||[]).forEach(p=>{
      const cat = p.predajna_kategoria || 'Nezaradené';
      out[cat] = out[cat] || [];
      out[cat].push(p);
      const e = String(p.ean || '');
      if (e) byEan[e] = { ean: e, name: p.nazov_vyrobku || '' };
    });
    return { byCat: out, byEan };
  }

  async function loadPricelistsForManagement(){
    const box = ensureContainer('b2b-pricelists-container'); if (!box) return;
    box.innerHTML = '<p>Načítavam cenníky…</p>';
    try{
      const data = await callFirstOk([
        {url:'/api/kancelaria/b2b/getPricelistsAndProducts'},
        {url:'/api/kancelaria/b2b/get_pricelists_and_products'}
      ]);

      state.pricelists = Array.isArray(data?.pricelists) ? data.pricelists : [];

      if (data && data.productsByCategory){
        state.productsByCategory = data.productsByCategory || {};
        state.productsByEan = {};
        Object.values(state.productsByCategory).flat().forEach(p => {
          const e = String(p.ean || p.ean_produktu || '');
          const name = p.name || p.nazov_vyrobku || '';
          if (e) state.productsByEan[e] = { ean:e, name };
        });
      } else {
        const flat = Array.isArray(data?.products) ? data.products : [];
        const grouped = buildCategoriesFromFlatProducts(flat);
        state.productsByCategory = grouped.byCat;
        state.productsByEan = grouped.byEan;
      }

      if (state.pricelists.length === 0){
        box.innerHTML = '<p>Žiadne cenníky.</p>';
        return;
      }
      let html = '';
      state.pricelists.forEach(pl=>{
        html += `
          <div class="flex-row" style="display:flex;justify-content:space-between;align-items:center;padding:.5rem 0;border-bottom:1px solid var(--divider,#e5e7eb);">
            <div><strong>${escapeHtml(pl.nazov_cennika)}</strong></div>
            <div><button class="btn btn-secondary" data-edit-pl="${pl.id}" style="margin:0">Upraviť položky</button></div>
          </div>`;
      });
      box.innerHTML = html + `<div id="b2b-pl-editor"></div>`;

      box.querySelectorAll('button[data-edit-pl]').forEach(btn=>{
        btn.onclick = ()=> renderPricelistEditorInline(Number(btn.dataset.editPl));
      });

    }catch(e){
      box.innerHTML = `<p class="error">Chyba pri načítaní cenníkov: ${escapeHtml(e.message||String(e))}</p>`;
    }
  }

  async function renderPricelistEditorInline(pricelistId){
    const host = ensureContainer('b2b-pricelists-container'); if (!host) return;

    const pl = state.pricelists.find(p => Number(p.id) === Number(pricelistId));
    if (!pl){ showStatus('Cenník sa nenašiel.', true); return; }

    const editorWrap = h('div', { id:'b2b-pl-editor', class:'stat-card' });
    editorWrap.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h3 style="margin:0;">Upraviť cenník: ${escapeHtml(pl.nazov_cennika)}</h3>
        <button class="btn btn-secondary" id="pl-back-btn">Späť na zoznam</button>
      </div>

      <div class="form-grid" style="grid-template-columns: 1fr 1fr; gap: 16px; margin-top:12px;">
        <div class="form-group" style="margin:0">
          <label>Filter produktov</label>
          <input id="pl-filter" type="text" placeholder="Hľadať produkt…">
          <div id="pl-source" class="table-container" style="max-height:380px;overflow:auto;margin-top:.5rem;"></div>
        </div>
        <div class="form-group" style="margin:0">
          <label>Položky v cenníku</label>
          <div id="pl-target" class="table-container" style="max-height:440px;overflow:auto;">
            <table><thead><tr><th>Produkt</th><th style="width:120px">Cena</th><th style="width:60px"></th></tr></thead><tbody id="pl-target-body"></tbody></table>
          </div>
          <div style="text-align:right;margin-top:.75rem;">
            <button class="btn btn-primary" id="pl-save-btn">Uložiť zmeny</button>
          </div>
        </div>
      </div>
    `;

    editorWrap.querySelector('#pl-back-btn').onclick = ()=> loadPricelistsForManagement();

    const srcHost = editorWrap.querySelector('#pl-source');
    const tgtBody = editorWrap.querySelector('#pl-target-body');
    const filterI = editorWrap.querySelector('#pl-filter');

    // existujúce položky
    tgtBody.innerHTML = '<tr><td colspan="3">Načítavam…</td></tr>';
    let currentMap = new Map(); // ean -> price
    try {
      const cur = await callFirstOk([
        {url:'/api/kancelaria/b2b/getPricelistDetails',           opts:{method:'POST', body:{ id: pricelistId }}},
        {url:'/api/kancelaria/b2b/get_pricelist_details',         opts:{method:'POST', body:{ id: pricelistId }}},
      ]);
      const items = (cur && cur.items) || [];
      items.forEach(it => currentMap.set(String(it.ean_produktu || it.ean), parseFloat(it.cena)));
    } catch (_) { currentMap = new Map(); }

    const renderSource = ()=>{
      const catsObj = state.productsByCategory || {};
      const cats = Object.keys(catsObj);
      const q = (filterI?.value || '').toLowerCase();

      if (cats.length === 0){
        srcHost.innerHTML = '<p class="muted">Žiadne položky</p>';
        return;
      }

      cats.sort((a,b)=> a.localeCompare(b,'sk'));
      let html = '';
      cats.forEach(cat=>{
        const rows = catsObj[cat] || [];
        const vis = rows.filter(p=>{
          const ean  = String(p.ean || p.ean_produktu || '');
          const name = String(p.nazov_vyrobku || p.name || '');
          const notAdded = !currentMap.has(ean);
          const match = !q || name.toLowerCase().includes(q) || ean.includes(q);
          return notAdded && match;
        });
        if (!vis.length) return;
        html += `<h4 style="margin:.5rem 0;">${escapeHtml(cat)}</h4><table><tbody>`;
        vis.forEach(p=>{
          const e = String(p.ean || p.ean_produktu || '');
          const n = String(p.nazov_vyrobku || p.name || `EAN ${e}`);
          const escE = escapeHtml(e), escN = escapeHtml(n);
          html += `
            <tr>
              <td>${escN}</td>
              <td style="width:120px">
                <input type="number" class="pl-price" data-ean="${escE}" step="0.01" placeholder="Cena" style="width:100px">
              </td>
              <td style="width:60px">
                <button class="btn btn-primary" data-add="${escE}" style="margin:0">Pridať</button>
              </td>
            </tr>`;
        });
        html += `</tbody></table>`;
      });
      srcHost.innerHTML = html || `<p class="muted">Žiadne položky</p>`;

      srcHost.querySelectorAll('button[data-add]').forEach(b=>{
        b.onclick = ()=>{
          const ean = b.dataset.add;
          const priceInput = srcHost.querySelector(`input.pl-price[data-ean="${CSS.escape(ean)}"]`);
          const price = parseFloat((priceInput?.value || '').replace(',','.'));
          if (!(price > 0)){ showStatus('Zadaj cenu > 0', true); return; }
          currentMap.set(String(ean), price);
          renderTarget();
          renderSource();
        };
      });
    };

    const renderTarget = ()=>{
      if (currentMap.size === 0){
        tgtBody.innerHTML = `<tr><td colspan="3"><i>Žiadne položky</i></td></tr>`;
        return;
      }
      let html = '';
      Array.from(currentMap.keys()).sort().forEach(ean=>{
        const p = state.productsByEan[ean] || { name:`EAN ${ean}` };
        const price = currentMap.get(ean) || 0;
        const escName = escapeHtml(p.name||`EAN ${ean}`);
        html += `
          <tr data-ean="${escapeHtml(ean)}">
            <td>${escName}<div class="muted" style="font-size:.8rem">${escapeHtml(ean)}</div></td>
            <td><input type="number" class="pl-price-edit" value="${price}" step="0.01" style="width:100px"></td>
            <td><button class="btn btn-danger" data-del="${escapeHtml(ean)}" style="margin:0">X</button></td>
          </tr>`;
      });
      tgtBody.innerHTML = html;

      tgtBody.querySelectorAll('button[data-del]').forEach(b=>{
        b.onclick = ()=>{
          const ean = b.dataset.del;
          currentMap.delete(ean);
          renderTarget();
          renderSource();
        };
      });
    };

    filterI.addEventListener('input', ()=> renderSource());

    // initial render
    renderSource();
    renderTarget();

    // uloženie
    editorWrap.querySelector('#pl-save-btn').onclick = async ()=>{
      const items = [];
      editorWrap.querySelectorAll('#pl-target-body tr').forEach(tr=>{
        const ean = tr.dataset.ean;
        const price = parseFloat(tr.querySelector('.pl-price-edit')?.value||'0');
        if (ean && price > 0) items.push({ ean, price });
      });
      try{
        await callFirstOk([
          {url:'/api/kancelaria/b2b/updatePricelist',   opts:{method:'POST', body:{ id: Number(pricelistId), items }}},
          {url:'/api/kancelaria/b2b/update_pricelist',  opts:{method:'POST', body:{ id: Number(pricelistId), items }}},
        ]);
        showStatus('Cenník uložený.', false);
        loadPricelistsForManagement();
      }catch(e){ showStatus(e.message||String(e), true); }
    };

    const old = doc.getElementById('b2b-pl-editor');
    if (old) old.remove();
    host.appendChild(editorWrap);
    editorWrap.scrollIntoView({behavior:'smooth', block:'start'});
  }

  // ==================================================================
  // PREHĽAD OBJEDNÁVOK (inline)
  // ==================================================================
  async function loadB2BOrdersView(){
    const box = ensureContainer('b2b-orders-container'); if (!box) return;
    const today = new Date().toISOString().slice(0,10);
    box.innerHTML = `
      <div style="display:flex; gap: 1rem; align-items: flex-end; margin-bottom: 1.5rem;">
        <div class="form-group" style="flex:1; margin-bottom:0;">
          <label for="order-filter-start">Zobraziť dodávky od</label>
          <input type="date" id="order-filter-start" value="${today}">
        </div>
        <div class="form-group" style="flex:1; margin-bottom:0;">
          <label for="order-filter-end">do</label>
          <input type="date" id="order-filter-end" value="${today}">
        </div>
        <button id="filter-orders-btn" class="btn btn-primary" style="margin:0">Filtrovať</button>
      </div>
      <div id="orders-table-container" class="table-container"><p>Načítavam…</p></div>
    `;

    const refresh = async ()=>{
      const start = doc.getElementById('order-filter-start').value;
      const end   = doc.getElementById('order-filter-end').value;
      const target= doc.getElementById('orders-table-container');
      try{
        const res = await callFirstOk([
          {url:'/api/kancelaria/b2b/getAllOrders',  opts:{method:'POST', body:{ startDate: start, endDate: end }}},
          {url:'/api/kancelaria/b2b/get_orders',    opts:{method:'POST', body:{ startDate: start, endDate: end }}},
        ]);
        const rows = res?.orders || [];
        if (rows.length === 0){ target.innerHTML = '<p>Žiadne objednávky v danom období.</p>'; return; }
        let html = `<table><thead><tr>
            <th>Číslo obj.</th><th>Zákazník</th><th>Dátum obj.</th><th>Dátum dodania</th><th>Suma (s DPH)</th><th>Akcie</th>
          </tr></thead><tbody>`;
        rows.forEach(o=>{
          const od = o.datum_objednavky ? new Date(o.datum_objednavky).toLocaleString('sk-SK') : '';
          const dd = o.pozadovany_datum_dodania ? new Date(o.pozadovany_datum_dodania).toLocaleDateString('sk-SK') : '';
          html += `<tr>
            <td>${escapeHtml(o.cislo_objednavky || String(o.id))}</td>
            <td>${escapeHtml(o.nazov_firmy || '')}</td>
            <td>${escapeHtml(od)}</td>
            <td>${escapeHtml(dd)}</td>
            <td>${o.celkova_suma_s_dph ? Number(o.celkova_suma_s_dph).toFixed(2) : '0.00'} €</td>
            <td>
              <button class="btn btn-secondary" data-print="${o.id}" style="margin:0"><i class="fas fa-print"></i> Tlačiť</button>
            </td>
          </tr>`;
        });
        html += '</tbody></table>';
        target.innerHTML = html;

        target.querySelectorAll('button[data-print]').forEach(b=>{
          b.onclick = ()=> root.open(`/api/kancelaria/b2b/print_order_pdf/${b.dataset.print}`, '_blank');
        });
      }catch(e){
        target.innerHTML = `<p class="error">Chyba: ${escapeHtml(e.message||String(e))}</p>`;
      }
    };

    doc.getElementById('filter-orders-btn').onclick = refresh;
    refresh();
  }

  // ==================================================================
  // NASTAVENIA
  // ==================================================================
  async function loadB2BSettings(){
    const box = ensureContainer('b2b-settings-container'); if (!box) return;
    box.innerHTML = '<p>Načítavam…</p>';
    try{
      const s = await callFirstOk([
        {url:'/api/kancelaria/b2b/getAnnouncement'},
        {url:'/api/kancelaria/b2b/get_announcement'}
      ]);
      box.innerHTML = `
        <h4>Oznam na B2B portáli</h4>
        <p>Tento text sa zobrazuje všetkým prihláseným zákazníkom.</p>
        <div class="form-group"><textarea id="b2b-ann-txt" rows="4">${escapeHtml(s?.announcement||'')}</textarea></div>
        <button class="btn btn-success" id="b2b-ann-save">Uložiť oznam</button>`;
      doc.getElementById('b2b-ann-save').onclick = async ()=>{
        const txt = doc.getElementById('b2b-ann-txt').value;
        try{
          await callFirstOk([
            {url:'/api/kancelaria/b2b/saveAnnouncement',  opts:{method:'POST', body:{ announcement: txt }}},
            {url:'/api/kancelaria/b2b/save_announcement', opts:{method:'POST', body:{ announcement: txt }}},
          ]);
          showStatus('Oznámenie uložené.', false);
        }catch(e){ showStatus(e.message||String(e), true); }
      };
    }catch(e){
      box.innerHTML = `<p class="error">Chyba: ${escapeHtml(e.message||String(e))}</p>`;
    }
  }

  // ==================================================================
  // KOMUNIKÁCIA (záložka)
  // ==================================================================
  async function loadCommView(){
    const box = ensureContainer('b2b-comm-container'); if (!box) return;
    box.innerHTML = '<p>Načítavam…</p>';

    // načítaj zákazníkov pre filter (ak ešte nie sú)
    try {
      if (!state.customers.length){
        const data = await callFirstOk([
          {url:'/api/kancelaria/b2b/getCustomersAndPricelists'},
          {url:'/api/kancelaria/b2b/get_customers_and_pricelists'}
        ]);
        state.customers  = Array.isArray(data?.customers)  ? data.customers  : [];
      }
    } catch (_) { /* ignore */ }

    const custOptions = ['<option value="">Všetci odberatelia</option>']
      .concat((state.customers||[]).map(c => `<option value="${c.id}">${escapeHtml(c.nazov_firmy||'')}${c.zakaznik_id ? ' ('+escapeHtml(c.zakaznik_id)+')' : ''}</option>`))
      .join('');

    box.innerHTML = `
      <div style="display:flex; gap:.75rem; align-items:flex-end; flex-wrap:wrap; margin-bottom:1rem;">
        <div class="form-group" style="min-width:220px; margin:0;">
          <label for="comm-status">Stav</label>
          <select id="comm-status">
            <option value="new">Nové</option>
            <option value="read">Prečítané</option>
            <option value="all">Všetko</option>
          </select>
        </div>
        <div class="form-group" style="min-width:280px; margin:0;">
          <label for="comm-customer">Odberateľ</label>
          <select id="comm-customer">${custOptions}</select>
        </div>
        <div class="form-group" style="min-width:240px; margin:0;">
          <label for="comm-q">Hľadať</label>
          <input id="comm-q" type="text" placeholder="predmet, text, odberateľ…">
        </div>
        <button id="comm-filter-btn" class="btn btn-primary" style="margin:0;">Filtrovať</button>
      </div>
      <div id="comm-list-container"><p>Načítavam správy…</p></div>
    `;

    const refresh = async ()=>{
      const container = doc.getElementById('comm-list-container');
      container.innerHTML = '<p>Načítavam správy…</p>';
      const status = String(doc.getElementById('comm-status').value || 'new');
      const customer_id = doc.getElementById('comm-customer').value;
      const q = (doc.getElementById('comm-q').value || '').trim();

      // manuálny GET s query parametrami
      const qs = new URLSearchParams();
      if (status && status !== 'all') qs.set('status', status);
      if (customer_id) qs.set('customer_id', customer_id);
      if (q) qs.set('q', q);

      let data;
      try{
        const r = await fetch('/api/kancelaria/b2b/messages' + (qs.toString()?`?${qs}`:''), { credentials:'same-origin' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        data = await r.json();
      }catch(e){
        try{
          const r2 = await fetch('/api/kancelaria/b2b/messages_list' + (qs.toString()?`?${qs}`:''), { credentials:'same-origin' });
          if (!r2.ok) throw new Error(`HTTP ${r2.status}`);
          data = await r2.json();
        }catch(err){
          container.innerHTML = `<p class="error">Chyba: ${escapeHtml(err.message||String(err))}</p>`;
          return;
        }
      }

      const rows = (data && data.messages) || [];
      if (!rows.length){ container.innerHTML = '<p>Žiadne správy.</p>'; return; }

      let html = '';
      rows.forEach(m=>{
        const dt = m.created_at ? new Date(String(m.created_at).replace(' ','T')).toLocaleString('sk-SK') : '';
        const dir = (m.direction==='out') ? 'MIK → Zákazník' : 'Zákazník → MIK';
        const name = `${escapeHtml(m.customer_name||'')} ${m.zakaznik_login?`<span class="muted">(${escapeHtml(m.zakaznik_login)})</span>`:''}`;
        const att = m.attachment_filename ? `<a class="btn-link" href="/api/kancelaria/b2b/messages/attachment/${m.id}" target="_blank" rel="noopener">${escapeHtml(m.attachment_filename)}</a>` : '<span class="muted">—</span>';
        const statusLabel = m.status==='new' ? '<span class="badge">nové</span>' : '<span class="muted">prečítané</span>';
        html += `
          <div class="msg-row" data-msg-id="${m.id}">
            <div class="msg-head">
              <div>
                <div><strong>${escapeHtml(m.subject||'(bez predmetu)')}</strong> ${statusLabel}</div>
                <div class="muted">${dt} • ${dir} • ${name}</div>
                <div class="muted">Príloha: ${att}</div>
              </div>
              <div class="inline-actions">
                <button class="btn btn-secondary" data-cmd="toggle" style="margin:0">Zobraziť</button>
                <button class="btn btn-success"   data-cmd="read"   style="margin:0">Prečítané</button>
                ${m.direction==='in'
                  ? `<button class="btn btn-primary" data-cmd="reply" style="margin:0">Odpovedať</button>`
                  : ``}
              </div>
            </div>
            <div class="msg-body" style="display:none;"></div>
          </div>`;
      });
      container.innerHTML = html;

      // akcie
      container.querySelectorAll('[data-cmd="toggle"]').forEach(btn=>{
        btn.onclick = ()=>{
          const row = btn.closest('.msg-row');
          const body = row.querySelector('.msg-body');
          if (body.dataset.loaded!=='1'){
            const id = Number(row.dataset.msgId);
            const rec = rows.find(x=> Number(x.id)===id);
            body.innerHTML = `<pre class="msg-body">${escapeHtml(rec?.body || '')}</pre>`;
            body.dataset.loaded='1';
          }
          body.style.display = (body.style.display==='none' ? 'block' : 'none');
        };
      });

      container.querySelectorAll('[data-cmd="read"]').forEach(btn=>{
        btn.onclick = async ()=>{
          const row = btn.closest('.msg-row');
          const id = Number(row.dataset.msgId);
          try{
            await callFirstOk([
              {url:'/api/kancelaria/b2b/messages/mark-read', opts:{method:'POST', body:{ id }}},
              {url:'/api/kancelaria/b2b/messages_mark_read', opts:{method:'POST', body:{ id }}},
            ]);
            showStatus('Označené ako prečítané.', false);
            refresh();
          }catch(e){ showStatus(e.message||String(e), true); }
        };
      });

      container.querySelectorAll('[data-cmd="reply"]').forEach(btn=>{
        btn.onclick = ()=>{
          const row = btn.closest('.msg-row');
          const id = Number(row.dataset.msgId);
          const body = row.querySelector('.msg-body');
          body.style.display='block';
          if (body.querySelector('form')) return;
          body.insertAdjacentHTML('beforeend', `
            <div class="msg-reply">
              <form class="reply-form" enctype="multipart/form-data">
                <div class="form-group"><label>Predmet</label><input name="subject" type="text" placeholder="Re: …"></div>
                <div class="form-group"><label>Správa</label><textarea name="body" rows="4" required></textarea></div>
                <div class="form-group"><label>Príloha (voliteľné)</label><input name="file" type="file"></div>
                <div class="inline-actions" style="justify-content:flex-end;">
                  <button class="btn btn-primary" type="submit" style="margin:0">Odoslať</button>
                </div>
              </form>
            </div>`);
          const form = body.querySelector('form.reply-form');
          form.onsubmit = async (e)=>{
            e.preventDefault();
            const fd = new FormData(form);
            fd.append('id', String(id));
            try{
              await apiPostForm('/api/kancelaria/b2b/messages/reply', fd);
              showStatus('Odpoveď odoslaná.', false);
              refresh();
            }catch(err){ showStatus(err.message||String(err), true); }
          };
        };
      });
    };

    doc.getElementById('comm-filter-btn').onclick = refresh;
    refresh();
  }

  // ------------------ Export init do globálu -------------------------
  (function (g) { g.initializeB2BAdminModule = initializeB2BAdminModule; })
  (typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));

})(typeof window !== 'undefined' ? window
  : (typeof globalThis !== 'undefined' ? globalThis : this),
  typeof document !== 'undefined' ? document : undefined);
