// static/js/leaderexpediction.js
(function (root, doc) {
  'use strict';

  // ========================= HELPERS / FALLBACKS ===========================
  const $  = (sel, el = doc) => (el || doc).querySelector(sel);
  const $$ = (sel, el = doc) => Array.from((el || doc).querySelectorAll(sel));
  if (!root.$)  root.$  = $;
  if (!root.$$ ) root.$$ = $$;

  const escapeHtml = (s)=> String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  const todayISO  = () => new Date().toISOString().slice(0,10);
  const safeStr   = v => String(v ?? '').trim();
  const toNum     = (v,d=0)=>{ const n = Number(String(v??'').replace(/[^\d.,-]/g,'').replace(',','.')); return Number.isFinite(n) ? n : d; };
  const fmt2      = n => (Number(n||0)).toFixed(2);

  // unified fetch
  const apiRequest = (root.apiRequest) ? root.apiRequest : async (url, options={})=>{
    const opts = Object.assign({credentials:'same-origin', headers:{}}, options);
    if (opts.body && typeof opts.body==='object' && !(opts.body instanceof FormData)) {
      opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(url, opts);
    const ct  = (res.headers.get('content-type')||'').toLowerCase();
    const data= ct.includes('application/json')? await res.json(): await res.text();
    if (!res.ok) throw new Error((data && data.error) || res.statusText || ('HTTP '+res.status));
    return data;
  };

  const showStatus = (root.showStatus) ? root.showStatus : (msg,isErr=false)=>{
    (isErr?console.error:console.log)(msg);
    let el = $('#status-bar'); if(!el){ el = doc.createElement('div'); el.id='status-bar';
      el.style.cssText='position:fixed;left:16px;bottom:16px;padding:10px 14px;border-radius:10px;background:#111;color:#fff;z-index:9999';
      doc.body.appendChild(el);
    }
    el.textContent = msg; el.style.background = isErr?'#b91c1c':'#166534';
    clearTimeout(el._t); el._t=setTimeout(()=> el.remove(), 3500);
  };

  // ====================== NÁZVY PRODUKTOV PODĽA EAN ========================
  const __nameByEAN = Object.create(null);
  async function ensureNamesForEans(eanList){
    const missing = (eanList || [])
      .map(e => String(e || '').trim())
      .filter(e => e && __nameByEAN[e] == null);

    if (!missing.length) return __nameByEAN;

    try {
      const map = await apiRequest('/api/leader/catalog/names?eans=' + encodeURIComponent(missing.join(',')));
      Object.keys(map || {}).forEach(e => { __nameByEAN[String(e)] = String(map[e] || ''); });
    } catch (_) { /* ticho – názvy sú voliteľné */ }
    return __nameByEAN;
  }

  // ========================= MODALY (FF-safe) ==============================
  function modalPrompt({title,label,placeholder='',type='text',okText='OK',cancelText='Zrušiť',pattern=null}) {
    return new Promise((resolve)=>{
      const wrapId='ldr-mini-modal';
      let wrap=document.getElementById(wrapId);
      if(!wrap){
        wrap=document.createElement('div'); wrap.id=wrapId;
        wrap.innerHTML=`<div style="position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:10000">
          <div style="max-width:520px;width:clamp(300px,92vw,520px);background:#fff;border-radius:12px;box-shadow:0 30px 80px rgba(0,0,0,.35);overflow:hidden">
            <div style="display:flex;align-items:center;padding:12px 14px;border-bottom:1px solid #eee;background:#f8fafc;font-weight:600" id="mm-title"></div>
            <div style="padding:14px" id="mm-body"></div>
            <div style="display:flex;gap:.5rem;justify-content:flex-end;padding:12px;border-top:1px solid #eee">
              <button class="btn btn-secondary" id="mm-cancel">${cancelText}</button>
              <button class="btn btn-primary"   id="mm-ok">${okText}</button>
            </div>
          </div>
        </div>`;
        document.body.appendChild(wrap);
      }
      const t=wrap.querySelector('#mm-title'), b=wrap.querySelector('#mm-body'), ok=wrap.querySelector('#mm-ok'), cc=wrap.querySelector('#mm-cancel');
      t.textContent=title||'Potvrdenie';
      b.innerHTML = type==='textarea'
        ? `<label class="muted" style="display:block;margin-bottom:6px">${escapeHtml(label||'')}</label><textarea id="mm-input" rows="4" placeholder="${escapeHtml(placeholder)}" style="width:100%;padding:.5rem;border:1px solid #e5e7eb;border-radius:8px"></textarea>`
        : `<label class="muted" style="display:block;margin-bottom:6px">${escapeHtml(label||'')}</label><input id="mm-input" type="${type}" placeholder="${escapeHtml(placeholder)}" style="width:100%;padding:.5rem;border:1px solid #e5e7eb;border-radius:8px">`;
      wrap.style.display='block';
      const ip=b.querySelector('#mm-input'); setTimeout(()=>ip.focus(),10);
      function done(v){ wrap.style.display='none'; resolve(v); }
      cc.onclick=()=>done(null);
      ok.onclick=()=>{
        const v=(ip.value||'').trim();
        if (pattern && !pattern.test(v)) { ip.focus(); return; }
        done(v);
      };
      ip.addEventListener('keydown',(e)=>{ if(e.key==='Enter' && type!=='textarea'){ ok.click(); }});
    });
  }
  function modalConfirm({title,message,okText='Áno',cancelText='Nie'}){
    return new Promise((resolve)=>{
      const id='ldr-confirm-modal';
      let w=document.getElementById(id);
      if(!w){
        w=document.createElement('div'); w.id=id;
        w.innerHTML=`<div style="position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:10000">
          <div style="max-width:480px;width:clamp(300px,92vw,480px);background:#fff;border-radius:12px;box-shadow:0 30px 80px rgba(0,0,0,.35);overflow:hidden">
            <div style="display:flex;align-items:center;padding:12px 14px;border-bottom:1px solid #eee;background:#f8fafc;font-weight:600" id="cf-title"></div>
            <div style="padding:14px" id="cf-msg"></div>
            <div style="display:flex;gap:.5rem;justify-content:flex-end;padding:12px;border-top:1px solid #eee">
              <button class="btn btn-secondary" id="cf-no">${cancelText}</button>
              <button class="btn btn-primary"   id="cf-yes">${okText}</button>
            </div>
          </div>
        </div>`;
        document.body.appendChild(w);
      }
      w.querySelector('#cf-title').textContent = title || 'Potvrdenie';
      w.querySelector('#cf-msg').innerHTML = message || '';
      w.style.display='block';
      const yes=w.querySelector('#cf-yes'), no=w.querySelector('#cf-no');
      function done(v){ w.style.display='none'; resolve(v); }
      no.onclick=()=>done(false); yes.onclick=()=>done(true);
    });
  }
  function modal(title, inner, onReady){
    let wrap = $('#ldr-modal');
    if (!wrap){
      wrap = doc.createElement('div'); wrap.id='ldr-modal';
      wrap.innerHTML = `
        <div class="b2c-modal-backdrop" style="position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:10000"></div>
        <div class="b2c-modal-card" style="position:fixed;inset:auto;max-width:780px;width:clamp(320px,92vw,780px);background:#fff;border-radius:14px;box-shadow:0 30px 80px rgba(0,0,0,.35);z-index:10001;overflow:hidden"></div>`;
      doc.body.appendChild(wrap);
    }
    const card = wrap.querySelector('.b2c-modal-card');
    card.innerHTML = `
      <div style="display:flex;align-items:center;gap:.5rem;padding:14px 16px;border-bottom:1px solid #eee;background:#f8fafc">
        <div style="font:600 16px/1.2 Inter,system-ui">${escapeHtml(title||'')}</div>
        <button type="button" style="margin-left:auto;border:0;background:transparent;font-size:18px;cursor:pointer" aria-label="Zavrieť" onclick="closeModal()">×</button>
      </div>
      <div class="b2c-modal-body" style="padding:16px;max-height:70vh;overflow:auto">${inner||''}</div>`;
    wrap.style.display = 'block';
    root.closeModal = ()=> { wrap.style.display='none'; };
    if (typeof onReady === 'function') onReady(card.querySelector('.b2c-modal-body'));
  }

  // ========================= SHARED B2B STATE (single) =====================
  var __pickedCustomer    = null;
  var __pickedPricelist   = null;
  var __pricelistMapByEAN = Object.create(null);

  // ============================== DASHBOARD ================================
  async function loadDashboard(){
    const $id = (s)=>document.getElementById(s);
    const d = ($id('ldr-date') && $id('ldr-date').value) || todayISO();
    const skDate = (iso)=> new Date((iso||todayISO()) + 'T00:00:00').toLocaleDateString('sk-SK');
    const E = (html)=> escapeHtml(html||'');

    try{
      const r = await apiRequest(`/api/leader/dashboard?date=${encodeURIComponent(d)}`);
      $id('kpi-b2c').textContent   = (r.kpi && r.kpi.b2c_count!=null)   ? r.kpi.b2c_count   : '—';
      $id('kpi-b2b').textContent   = (r.kpi && r.kpi.b2b_count!=null)   ? r.kpi.b2b_count   : '—';
      $id('kpi-items').textContent = (r.kpi && r.kpi.items_total!=null) ? r.kpi.items_total : '—';
      $id('kpi-sum').textContent   = (r.kpi && r.kpi.sum_total!=null)   ? `${fmt2(r.kpi.sum_total)} €` : '—';

      // plán výroby – preview
      const planHost = $id('plan-preview');
      if (Array.isArray(r.production_plan_preview) && r.production_plan_preview.length){
        planHost.innerHTML = r.production_plan_preview.map(p=>`
          <div style="padding:8px;border-bottom:1px solid #eee;display:flex;gap:8px;align-items:center;${p.is_tomorrow?'background:#fff7ed;border-left:3px solid #f59e0b;':''}">
            <div style="width:120px"><b>${skDate(p.date)}</b></div>
            <div class="muted">${E(p.note||'')}</div>
            ${p.is_tomorrow ? '<span style="margin-left:auto;color:#f59e0b;font-weight:600">Zajtra</span>' : ''}
          </div>`).join('');
      } else { planHost.innerHTML = '<div class="muted">Žiadne dáta.</div>'; }

      // next 7
      const office = await apiRequest('/api/kancelaria/getDashboardData').catch(()=>({error:'fail'}));
      const nextHost = document.getElementById('leader-next7');
      let next7 = [];
      if (!office.error && Array.isArray(office.next7Days)) next7 = office.next7Days;
      else if (Array.isArray(r.next7_orders)) next7 = r.next7_orders;

      if (next7.length){
        const rows = next7.map(x=>{
          const dt = x.date || x.day || x.d || d;
          const b2c = Number(x.b2c||0), b2b = Number(x.b2b||0);
          const total = (x.total!=null) ? x.total : (b2c+b2b);
          const wd = new Date((dt||d)+'T00:00:00').toLocaleDateString('sk-SK',{ weekday:'short' });
          return `<tr><td>${skDate(dt)}</td><td>${wd}</td><td class="num">${b2c}</td><td class="num">${b2b}</td><td class="num"><strong>${total}</strong></td></tr>`;
        }).join('');
        nextHost.innerHTML = `
          <div class="card" style="margin-top:16px">
            <div class="card-header"><strong>Objednávky na najbližších 7 dní</strong></div>
            <div class="card-body">
              <div class="table-container">
                <table class="tbl">
                  <thead><tr><th>Dátum</th><th>Deň</th><th>B2C</th><th>B2B</th><th>Spolu</th></tr></thead>
                  <tbody>${rows}</tbody>
                </table>
              </div>
            </div>
          </div>`;
      } else { nextHost.innerHTML = ''; }

      // low stock mirror
      const lowHost = document.getElementById('leader-lowstock-goods');
      if (!office.error && office.lowStockGoods && Object.keys(office.lowStockGoods).length){
        let html = '<div class="card" style="margin-top:16px"><div class="card-header"><strong>Expedičný tovar pod minimálnou zásobou</strong></div><div class="card-body">';
        for (const cat of Object.keys(office.lowStockGoods)){
          const items = office.lowStockGoods[cat] || [];
          html += `<h4 style="margin:.25rem 0">${escapeHtml(cat)}</h4>
            <div class="table-container"><table class="tbl">
              <thead><tr><th>Produkt</th><th>Aktuálny stav</th><th>Min. zásoba</th></tr></thead><tbody>
                ${items.map(it=>`<tr>
                  <td>${escapeHtml(it.name||it.product||'')}</td>
                  <td class="loss">${fmt2(toNum(it.currentStock,0))}</td>
                  <td>${fmt2(toNum(it.minStock,0))}</td>
                </tr>`).join('')}
              </tbody></table></div>`;
        }
        lowHost.innerHTML = html + '</div></div>';
      } else if (office?.status===403) {
        lowHost.innerHTML = `<div class="card" style="margin-top:16px"><div class="card-header"><strong>Expedičný tovar pod minimálnou zásobou</strong></div><div class="card-body"><div class="muted">Nemáte oprávnenie zobraziť tieto dáta.</div></div></div>`;
      } else { lowHost.innerHTML = ''; }

      // promos mirror
      const promosHost = document.getElementById('leader-promos');
      const promos = await apiRequest('/api/kancelaria/get_promotions_data').catch(()=>({error:'fail'}));
      if (!promos.error && Array.isArray(promos.promotions) && promos.promotions.length){
        const today = new Date(); today.setHours(0,0,0,0);
        const mapped = promos.promotions.map(p=>{
          const s = p.start_date ? new Date(p.start_date+'T00:00:00') : null;
          const e = p.end_date   ? new Date(p.end_date  +'T00:00:00') : null;
          let stateText='Bez termínu', badge='badge-gray';
          if (s && e){
            if (today < s){ stateText = `Začne o ${Math.round((s-today)/86400000)} d`; badge='badge-blue'; }
            else if (today > e){ stateText = 'Ukončená'; badge='badge-gray'; }
            else {
              const left = Math.round((e-today)/86400000);
              stateText = left===0 ? 'Končí dnes' : `Prebieha (ešte ${left} d)`; badge = left===0 ? 'badge-orange' : 'badge-green';
            }
          }
          return {
            chain: (p.chain_name||p.chain||''),
            product: (p.product_name||p.product||''),
            period: `${s? s.toLocaleDateString('sk-SK'):'—'} – ${e? e.toLocaleDateString('sk-SK'):'—'}`,
            badge, stateText
          };
        });
        promosHost.innerHTML = `
          <div class="card" style="margin-top:16px">
            <div class="card-header"><strong>Akcie na supermarkety</strong></div>
            <div class="card-body">
              <div class="table-container">
                <table class="tbl">
                  <thead><tr><th>Reťazec</th><th>Produkt</th><th>Obdobie</th><th>Stav</th></tr></thead>
                  <tbody>
                    ${mapped.map(p=>`<tr>
                      <td>${escapeHtml(p.chain)}</td>
                      <td><strong>${escapeHtml(p.product)}</strong></td>
                      <td>${p.period}</td>
                      <td><span class="${p.badge}" style="display:inline-block;padding:.2rem .5rem;border-radius:10px">${escapeHtml(p.stateText)}</span></td>
                    </tr>`).join('')}
                  </tbody>
                </table>
              </div>
            </div>
          </div>`;
      } else if (promos?.status === 403) {
        promosHost.innerHTML = `<div class="card" style="margin-top:16px"><div class="card-header"><strong>Akcie na supermarkety</strong></div><div class="card-body"><div class="muted">Nemáte oprávnenie zobraziť tieto dáta.</div></div></div>`;
      } else { promosHost.innerHTML = ''; }

      // forecast mirror
      const fcHost = document.getElementById('leader-forecast');
      const fc = await apiRequest('/api/kancelaria/get_7_day_forecast').catch(()=>({error:'fail'}));
      if (!fc.error && fc && fc.dates && fc.forecast){
        const rx = /([0-9]+(?:[.,][0-9]+)?)/;
        Object.keys(fc.forecast).forEach(cat=>{
          (fc.forecast[cat]||[]).forEach(p=>{
            const m = String(p.stock_display||'').match(rx);
            p.stock_display_num = m ? parseFloat(m[1].replace(',','.')) : 0;
          });
        });
        let html = '<div class="card" style="margin-top:16px"><div class="card-header"><strong>7-dňový prehľad výrobkov</strong></div><div class="card-body">';
        const dates = fc.dates;
        for (const cat of Object.keys(fc.forecast)){
          const items = fc.forecast[cat]||[];
          html += `<h4 style="margin:.25rem 0">${escapeHtml(cat)}</h4>`;
          let rows = '';
          items.forEach(p=>{
            const total = dates.reduce((s,dx)=> s + (Number(p.daily_needs?.[dx]||0)), 0);
            const def   = Math.max(total - (p.stock_display_num||0), 0);
            rows += `<tr ${def>0?'style="background:#fee2e2"':''}>
              <td><strong>${escapeHtml(p.name||'')}</strong></td>
              <td>${escapeHtml(p.stock_display || '—')}</td>
              ${dates.map(dx=>`<td>${Number(p.daily_needs?.[dx]||0) || ''}</td>`).join('')}
              <td>${total}</td><td class="${def>0?'loss':''}">${def}</td>
            </tr>`;
          });
          html += `<div class="table-container" style="max-height:none;"><table class="tbl"><thead>
            <tr><th>Produkt</th><th>Sklad</th>${dates.map(dx=>`<th>${new Date(dx).toLocaleDateString('sk-SK',{day:'2-digit',month:'2-digit'})}</th>`).join('')}
            <th>Potreba</th><th>Deficit</th></tr>
          </thead><tbody>${rows}</tbody></table></div>`;
        }
        fcHost.innerHTML = html + '</div></div>';
      } else if (fc?.status === 403) {
        fcHost.innerHTML = `<div class="card" style="margin-top:16px"><div class="card-header"><strong>7-dňový prehľad výrobkov</strong></div><div class="card-body"><div class="muted">Nemáte oprávnenie zobraziť tieto dáta.</div></div></div>`;
      } else { fcHost.innerHTML = ''; }

    }catch(e){
      showStatus(e.message||String(e), true);
    }
  }
  async function commitPlan(){
    const d = $('#ldr-date').value || todayISO();
    try{
      await apiRequest(`/api/leader/production/plan?start=${encodeURIComponent(d)}&days=7&commit=1`);
      showStatus('Plán výroby zapísaný.', false);
    }catch(e){ showStatus(e.message||String(e), true); }
  }

  // ============================== B2C =======================================
  function robustItemsParse(raw){
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    if (typeof raw === 'string'){
      try { return JSON.parse(raw); } catch(_){
        try { return JSON.parse(raw.replace(/'/g,'"')); } catch(_){ return []; }
      }
    }
    return [];
  }
  function ldr_showB2CDetail(order){
    let items = robustItemsParse(order.polozky ?? order.polozky_json ?? order.items ?? '[]');
    const rows = items.map(it=>{
      const name = it.name||it.nazov||it.nazov_vyrobku||'—';
      const qty  = (it.quantity ?? it.mnozstvo ?? '');
      const mj   = (it.unit || it.mj || '');
      const note = (it.poznamka_k_polozke || it.item_note || '');
      return `<tr><td>${escapeHtml(name)}</td><td>${escapeHtml(String(qty))}</td><td>${escapeHtml(mj)}</td><td>${escapeHtml(note)}</td></tr>`;
    }).join('');
    const html = `
      <div class="table-container">
        <table class="tbl"><thead><tr><th>Produkt</th><th>Množstvo</th><th>MJ</th><th>Poznámka</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" class="muted">Žiadne položky</td></tr>'}</tbody></table>
      </div>
      <div style="text-align:right;margin-top:10px">
        <button class="btn btn-secondary" onclick="window.open('/api/kancelaria/b2c/order-pdf?order_id=${encodeURIComponent(order.cislo_objednavky||order.id)}','_blank')">
          <i class="fas fa-print"></i> PDF objednávky
        </button>
      </div>`;
    try { modal('Detail objednávky #' + escapeHtml(order.cislo_objednavky||order.id), html); }
    catch (e) { showStatus('Nepodarilo sa zobraziť detail: '+ (e.message||e), true); if (typeof closeModal === 'function') closeModal(); }
  }
  async function ldr_markReady(order){
    const id = order.id; const no = order.cislo_objednavky || id;
    const priceStr = await modalPrompt({ title:`Finálna cena – #${no}`, label:'Zadajte finálnu cenu s DPH (napr. 12.34)', placeholder:'12.34', type:'text', pattern:/^\d+(?:[.,]\d{1,2})?$/ });
    if (priceStr===null) return;
    const price = String(priceStr).replace(',','.').trim();
    try{
      await apiRequest('/api/kancelaria/b2c/markReady', { method:'POST', body:{ order_id:id, final_price: price } });
      await apiRequest('/api/kancelaria/b2c/sms/ready',   { method:'POST', body:{ order_id:id, order_no:no, final_price:price } }).catch(()=>{});
      await apiRequest('/api/kancelaria/b2c/email/ready', { method:'POST', body:{ order_id:id, order_no:no, final_price:price } }).catch(()=>{});
      showStatus('Objednávka je v stave „Pripravená“.', false);
      loadB2C();
    }catch(e){ showStatus(e.message||String(e), true); }
  }
  async function ldr_closeOrder(order){
    const id = order.id; const no = order.cislo_objednavky || id;
    const ok = await modalConfirm({title:'Uzavrieť objednávku', message:`Označiť #${escapeHtml(no)} ako HOTOVÁ a pripísať body?`});
    if (!ok) return;
    try{
      await apiRequest('/api/kancelaria/b2c/closeOrder', { method:'POST', body:{ order_id:id } });
      await apiRequest('/api/kancelaria/b2c/sms/completed',   { method:'POST', body:{ order_id:id } }).catch(()=>{});
      await apiRequest('/api/kancelaria/b2c/email/completed', { method:'POST', body:{ order_id:id } }).catch(()=>{});
      showStatus('Objednávka uzavretá.', false);
      loadB2C();
    }catch(e){
      const priceStr = await modalPrompt({ title:`Finálna cena – #${no}`, label:'Zadajte finálnu cenu s DPH (napr. 12.34)', placeholder:'12.34', type:'text', pattern:/^\d+(?:[.,]\d{1,2})?$/ });
      if (priceStr===null) return;
      try{
        const price = String(priceStr).replace(',','.').trim();
        await apiRequest('/api/kancelaria/b2c/markReady', { method:'POST', body:{ order_id:id, final_price: price } });
        await apiRequest('/api/kancelaria/b2c/closeOrder', { method:'POST', body:{ order_id:id } });
        await apiRequest('/api/kancelaria/b2c/sms/completed',   { method:'POST', body:{ order_id:id } }).catch(()=>{});
        await apiRequest('/api/kancelaria/b2c/email/completed', { method:'POST', body:{ order_id:id } }).catch(()=>{});
        showStatus('Objednávka uzavretá.', false);
        loadB2C();
      }catch(e2){ showStatus(e2.message||String(e2), true); }
    }
  }
  async function ldr_cancelOrder(order){
    const id = order.id; const no = order.cislo_objednavky || id;
    const reason = await modalPrompt({ title:`Zrušiť objednávku #${no}`, label:'Dôvod zrušenia (zobrazí sa zákazníkovi):', type:'textarea', placeholder:'Dôvod…' });
    if (reason===null || !reason.trim()){ showStatus('Zrušenie prerušené – dôvod chýba.', true); return; }
    try{ await apiRequest('/api/leader/b2c/cancel_order', { method:'POST', body:{ order_id:id, reason: reason.trim() } }); showStatus('Objednávka zrušená.', false); loadB2C(); }
    catch(e){ showStatus(e.message||String(e), true); }
  }
  async function loadB2C(){
    const tb = $('#tbl-b2c tbody');
    const d  = $('#b2c-date').value || todayISO();
    tb.innerHTML = '<tr><td colspan="6" class="muted">Načítavam…</td></tr>';
    try{
      const rows = await apiRequest(`/api/leader/b2c/orders?date=${encodeURIComponent(d)}`);
      if (!rows.length){ tb.innerHTML = '<tr><td colspan="6" class="muted">Žiadne objednávky.</td></tr>'; return; }

      tb.innerHTML = rows.map(o=>{
        const id   = o.id;
        const no   = o.cislo_objednavky || id;
        const ddel = o.pozadovany_datum_dodania || '';
        const pred = toNum(o.predpokladana_suma_s_dph ?? o.predpokladana_suma ?? o.pred ?? 0, 0);
        const fin  = (o.finalna_suma_s_dph ?? o.finalna_suma ?? null);
        const finNum = (fin!=null ? toNum(fin,0) : null);
        const price = (finNum!=null && finNum>0) ? `${fmt2(pred)} € / <strong style="color:#16a34a">${fmt2(finNum)} €</strong>` : `${fmt2(pred)} € / <span class="muted">—</span>`;
        const who = (o.zakaznik_meno || o.nazov_firmy || '');
        let act = `<button class="btn btn-sm" data-b2c-detail="${id}">Detail</button> `;
        if (o.stav==='Prijatá')    act += `<button class="btn btn-sm" data-b2c-ready="${id}">Pripraviť</button> `;
        if (o.stav==='Pripravená') act += `<button class="btn btn-sm" data-b2c-done ="${id}">Hotová</button> `;
        if (o.stav!=='Hotová' && o.stav!=='Zrušená') act += `<button class="btn btn-sm" data-b2c-cancel="${id}">Zrušiť</button>`;
        return `<tr data-id="${escapeHtml(String(id))}">
          <td>${escapeHtml(no)}</td>
          <td>${escapeHtml(who)}</td>
          <td>${escapeHtml(ddel||'')}</td>
          <td>${price}</td>
          <td>${escapeHtml(o.stav||'')}</td>
          <td>${act}</td>
        </tr>`;
      }).join('');

      $$('[data-b2c-detail]').forEach(b=> b.onclick = ()=>{ const id = b.getAttribute('data-b2c-detail'); const row = rows.find(x=> String(x.id)===String(id)); if (row) ldr_showB2CDetail(row); });
      $$('[data-b2c-ready]').forEach(b=> b.onclick = ()=>{ const id = b.getAttribute('data-b2c-ready'); const row = rows.find(x=> String(x.id)===String(id)); if (row) ldr_markReady(row); });
      $$('[data-b2c-done]').forEach(b=> b.onclick = ()=>{ const id = b.getAttribute('data-b2c-done'); const row = rows.find(x=> String(x.id)===String(id)); if (row) ldr_closeOrder(row); });
      $$('[data-b2c-cancel]').forEach(b=> b.onclick = ()=>{ const id = b.getAttribute('data-b2c-cancel'); const row = rows.find(x=> String(x.id)===String(id)); if (row) ldr_cancelOrder(row); });

    }catch(e){
      tb.innerHTML = `<tr><td colspan="6" class="muted">Chyba: ${escapeHtml(e.message||'')}</td></tr>`;
    }
  }

  // ============================== B2B =======================================
  function getB2bFilter(){ const v = safeStr($('#b2b-filter')?.value || ''); const group = !!$('#b2b-group')?.checked; return { q:v.toLowerCase(), group }; }
  async function openB2bPdfSmart(id){
    const u = `/api/leader/b2b/order-pdf?order_id=${encodeURIComponent(id)}`;
    try{ const r = await fetch(u, {method:'HEAD'}); if (r.ok || r.status===302) { window.open(u,'_blank'); return; } window.open(u,'_blank'); }
    catch(_){ window.open(u,'_blank'); }
  }
  function priceCell(row){
    const pred = toNum(row.predpokladana_suma_s_dph ?? row.predpokladana_suma ?? row.pred ?? 0,0);
    const fin  = (row.finalna_suma_s_dph ?? row.finalna_suma ?? null);
    const finNum = (fin!=null ? toNum(fin,0) : null);
    return (finNum!=null && finNum>0) ? `${fmt2(pred)} € / <strong style="color:#16a34a">${fmt2(finNum)} €</strong>` : `${fmt2(pred)} € / <span class="muted">—</span>`;
  }

  async function loadB2B(){
  // pomocné
  const fmtSK = (iso)=> new Date((iso||todayISO())+'T00:00:00').toLocaleDateString('sk-SK',{day:'2-digit',month:'2-digit'});
  const mondayOf = (iso)=> {
    const d = new Date((iso||todayISO())+'T00:00:00');
    const dow = (d.getDay()+6)%7; // Po=0..Ne=6
    d.setDate(d.getDate() - dow);
    return d;
  };
  const addDays = (d,i)=> { const x = new Date(d); x.setDate(x.getDate()+i); return x.toISOString().slice(0,10); };

  const d = $('#b2b-date').value || todayISO();
  const tb = $('#tbl-b2b tbody');
  const weekMode = !!$('#b2b-week')?.checked;
  const rangeTag = $('#b2b-range-tag');
  tb.innerHTML='<tr><td colspan="6" class="muted">Načítavam…</td></tr>';

  try{
    let rows = [];
    if (!weekMode){
      // 1 deň (pôvodné)
      rows = await apiRequest(`/api/leader/b2b/orders?date=${encodeURIComponent(d)}`);
      if (rangeTag) rangeTag.textContent = '';
    } else {
      // týždeň Po–Pi podľa vybraného dátumu
      const mon = mondayOf(d);
      const days = [0,1,2,3,4].map(i => addDays(mon, i));
      const resp = await Promise.all(days.map(iso => apiRequest(`/api/leader/b2b/orders?date=${encodeURIComponent(iso)}`)));
      rows = resp.flat();
      if (rangeTag) rangeTag.textContent = `Rozsah: ${fmtSK(days[0])} – ${fmtSK(days[4])}`;
    }

    const {q, group} = getB2bFilter ? getB2bFilter() : {q:'',group:false};
    // filter odberateľa
    let list = rows.filter(r=>{
      const who = (r.odberatel || r.zakaznik_meno || r.nazov_firmy || '').toLowerCase();
      return !q || who.includes(q);
    });

    if (!list.length){ tb.innerHTML='<tr><td colspan="6" class="muted">Žiadne objednávky.</td></tr>'; return; }

    if (!group){
      tb.innerHTML = list.map(r=>{
        const id   = r.cislo_objednavky || r.id;
        const who  = safeStr(r.odberatel || '');
        const ddel = r.pozadovany_datum_dodania || '';
        return `<tr>
          <td>${escapeHtml(id)}</td>
          <td>${escapeHtml(who)}</td>
          <td>${escapeHtml(ddel||'')}</td>
          <td>${priceCell(r)}</td>
          <td>${escapeHtml(r.stav||'')}</td>
          <td>
            <button class="btn btn-sm" data-b2b-pdf="${escapeHtml(id)}">PDF</button>
            <button class="btn btn-sm" data-b2b-edit="${escapeHtml(id)}">Upraviť</button>
          </td>
        </tr>`;
      }).join('');
    } else {
      // zoskupiť podľa termínu dodania
      const groups = {};
      list.forEach(r=>{
        const key = r.pozadovany_datum_dodania || '(bez dátumu)';
        (groups[key] = groups[key] || []).push(r);
      });

      // utrieď skupiny podľa dátumu (bez dátumu posledné)
      const keys = Object.keys(groups).sort((a,b)=>{
        if (a==='(bez dátumu)' && b==='(bez dátumu)') return 0;
        if (a==='(bez dátumu)') return  1;
        if (b==='(bez dátumu)') return -1;
        return a.localeCompare(b);
      });

      tb.innerHTML = keys.map(k=>{
        const rowsHtml = groups[k].map(r=>{
          const id  = r.cislo_objednavky || r.id;
          const who = safeStr(r.odberatel || '');
          return `<tr>
            <td>${escapeHtml(id)}</td>
            <td>${escapeHtml(who)}</td>
            <td>${priceCell(r)}</td>
            <td>${escapeHtml(r.stav||'')}</td>
            <td>
              <button class="btn btn-sm" data-b2b-pdf="${escapeHtml(id)}">PDF</button>
              <button class="btn btn-sm" data-b2b-edit="${escapeHtml(id)}">Upraviť</button>
            </td>
          </tr>`;
        }).join('');
        const label = (k && k !== '(bez dátumu)') ? `${fmtSK(k)} (${k})` : k;
        return `<tr class="muted"><td colspan="6"><strong>Dodanie:</strong> ${escapeHtml(label)}</td></tr>${rowsHtml}`;
      }).join('');
    }

    // actions
    $$('[data-b2b-pdf]').forEach(b=> b.onclick = ()=> openB2bPdfSmart(b.getAttribute('data-b2b-pdf')) );
    $$('[data-b2b-edit]').forEach(b=> b.onclick = ()=>{
      const id = b.getAttribute('data-b2b-edit');
      const row = rows.find(x=> String(x.cislo_objednavky||x.id) === id);
      if (row) openB2BEditModal(row);
    });

    // ak ešte nie je filter bar (po prvom loade ho vytvor)
    if (!$('#b2b-filter')) injectB2bFilterUI();

  }catch(e){
    tb.innerHTML = `<tr><td colspan="6" class="muted">Chyba: ${escapeHtml(e.message||'')}</td></tr>`;
  }
}

  function injectB2bFilterUI(){
  const wrap = $('#leader-b2b .card .card-body');
  if (!wrap) return;

  const holder = doc.createElement('div');
  holder.style.cssText = 'display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-top:.5rem';
  holder.innerHTML = `
    <input id="b2b-filter" placeholder="Hľadať odberateľa" style="padding:.5rem;border:1px solid #e5e7eb;border-radius:8px;min-width:220px">
    <label style="display:inline-flex;align-items:center;gap:.35rem">
      <input type="checkbox" id="b2b-group"> Zoskupiť podľa termínu dodania
    </label>
    <label style="display:inline-flex;align-items:center;gap:.35rem">
      <input type="checkbox" id="b2b-week"> Týždeň (Po–Pi)
    </label>
    <span id="b2b-range-tag" class="muted" style="margin-left:auto"></span>
  `;
  wrap.appendChild(holder);

  const reload = ()=> loadB2B();
  $('#b2b-filter').addEventListener('input', reload);
  $('#b2b-group').addEventListener('change', reload);
  $('#b2b-week').addEventListener('change', reload);
}


  // =========================== Manuálna B2B ================================
  async function searchSuppliers(q){
    q = safeStr(q); if (q.length < 2) return [];
    try{
      const all = await apiRequest('/api/leader/b2b/getCustomersAndPricelists');
      const rows = (all && all.customers) ? all.customers : (Array.isArray(all)? all : []);
      return rows
        .filter(x=> ((x.name||'') + ' ' + (x.email||'')).toLowerCase().includes(q.toLowerCase()))
        .map(x=>({ id:x.id, name:x.name, code:x.email||'' }));
    }catch(_){ return []; }
  }
  async function fetchPricelists(customerId){
    const r = await apiRequest(`/api/leader/b2b/get_pricelists?customer_id=${encodeURIComponent(customerId)}`);
    if (Array.isArray(r)) return r;
    if (r && Array.isArray(r.pricelists)) return r.pricelists;
    if (r && Array.isArray(r.rows)) return r.rows;
    return [];
  }

  async function renderPricelistPreview(pricelist, mount){
  const items = Array.isArray(pricelist?.items) ? pricelist.items : [];
  // doplň mená podľa EAN
  await ensureNamesForEans(items.map(it => it && it.ean).filter(Boolean));

  // ✅ správny selector (bez nadbytočnej ')')
  const box = mount.querySelector('#nb2b-pl-preview') || (()=>{
    const d = doc.createElement('div');
    d.id = 'nb2b-pl-preview';
    d.style.marginTop = '.5rem';
    mount.appendChild(d);
    return d;
  })();

  if (!items.length){
    box.innerHTML = '<div class="muted">Cenník je prázdny.</div>';
    return;
  }

  box.innerHTML = `
    <div style="display:flex;gap:.5rem;align-items:center;margin:.5rem 0 .25rem">
      <input id="nb2b-pl-search" placeholder="Filtrovať EAN / názov…" style="flex:1;padding:.4rem;border:1px solid #e5e7eb;border-radius:8px">
      <span class="muted">${items.length} položiek</span>
    </div>
    <div class="table-container" style="max-height:260px;overflow:auto;border:1px solid #eee;border-radius:8px">
      <table class="tbl" style="width:100%">
        <thead><tr><th>EAN</th><th>Produkt</th><th>Cena bez DPH</th><th style="width:160px">Množstvo</th><th>MJ</th><th></th></tr></thead>
        <tbody></tbody>
      </table>
    </div>`;
  const tbody  = box.querySelector('tbody');
  const search = box.querySelector('#nb2b-pl-search');

  const getItemName = (it)=> __nameByEAN[String(it.ean||'')] || it.name || it.nazov || it.product_name || '';

  function redraw(){
    const q = (search.value || '').toLowerCase();
    const rows = items.filter(it=>{
      const e = String(it.ean || '');
      const nm = getItemName(it).toLowerCase();
      return !q || e.includes(q) || nm.includes(q);
    }).slice(0, 500);

    tbody.innerHTML = rows.map(it=>{
      const e   = String(it.ean || '');
      const nm  = getItemName(it);
      const pr  = Number(it.price || it.cena_bez_dph || 0);
      return `<tr data-ean="${escapeHtml(e)}" data-price="${pr}" data-name="${escapeHtml(nm)}">
        <td>${escapeHtml(e)}</td>
        <td>${escapeHtml(nm)}</td>
        <td>${fmt2(pr)} €</td>
        <td><input type="number" class="plpv-qty" min="0.001" step="0.001" value="1" style="width:100%"></td>
        <td><select class="plpv-mj"><option>ks</option><option>kg</option></select></td>
        <td><button class="btn btn-sm" data-add>Pridať</button></td>
      </tr>`;
    }).join('');

    $$('[data-add]', tbody).forEach(btn=>{
      btn.onclick = ()=>{
        const tr    = btn.closest('tr');
        const ean   = tr.dataset.ean;
        const price = Number(tr.dataset.price || 0);
        const name  = tr.dataset.name || (__nameByEAN[ean] || '');
        const qty   = toNum(tr.querySelector('.plpv-qty').value, 1);
        const mj    = tr.querySelector('.plpv-mj').value || 'ks';

        const nb = $('#nb2b-items tbody') || (()=>{
          const t = $('#nb2b-items'); const b = doc.createElement('tbody'); t.appendChild(b); return b;
        })();
        const row = doc.createElement('tr');
        row.innerHTML = `
          <td><input class="nb2b-ean"   value="${escapeHtml(ean)}"></td>
          <td><input class="nb2b-name"  value="${escapeHtml(name)}"></td>
          <td><input class="nb2b-qty"   type="number" step="0.001" min="0" value="${fmt2(qty)}"></td>
          <td><input class="nb2b-mj"    value="${escapeHtml(mj)}" style="width:60px"></td>
          <td><input class="nb2b-price" type="number" step="0.01" min="0" value="${fmt2(price)}"></td>
          <td><button class="btn btn-sm" data-del>×</button></td>`;
        nb.appendChild(row);
        row.querySelector('[data-del]').onclick = ()=> row.remove();
        if (ean) __pricelistMapByEAN[ean] = price;
        showStatus('Položka pridaná z cenníka.', false);
      };
    });
  }
  search.oninput = redraw; redraw();
}


  function addManualRow(tb){
    const tr = doc.createElement('tr');
    tr.innerHTML = `
      <td><input class="nb2b-ean"  placeholder="EAN"></td>
      <td><input class="nb2b-name" placeholder="Názov"></td>
      <td><input class="nb2b-qty"  type="number" step="0.001" min="0"></td>
      <td><input class="nb2b-mj"   value="ks" style="width:60px"></td>
      <td><input class="nb2b-price" type="number" step="0.01" min="0"></td>
      <td><button class="btn btn-sm" data-del>×</button></td>`;
    tb.appendChild(tr);
    tr.querySelector('[data-del]').onclick = ()=> tr.remove();
    tr.querySelector('.nb2b-ean').addEventListener('change', ()=>{
      const e = safeStr(tr.querySelector('.nb2b-ean').value);
      if (e && __pricelistMapByEAN && __pricelistMapByEAN[e]!=null){
        tr.querySelector('.nb2b-price').value = fmt2(__pricelistMapByEAN[e]);
      }
    });
  }

  async function saveManualB2B(){
    const odberatel    = safeStr($('#nb2b-name').value);
    const datum_dodania= $('#nb2b-date').value || todayISO();
    const poznamka     = safeStr($('#nb2b-note').value);
    const tb = $('#nb2b-items tbody'); const items=[];
    $$('.nb2b-ean', tb).forEach((e,i)=>{
      const ean  = safeStr(e.value);
      const name = safeStr($$('.nb2b-name', tb)[i].value);
      const qty  = toNum($$('.nb2b-qty',  tb)[i].value,0);
      const mj   = safeStr($$('.nb2b-mj',   tb)[i].value||'ks');
      const price= toNum($$('.nb2b-price', tb)[i].value,0);
      if (ean && name && qty>0) items.push({ ean, name, quantity:qty, unit:mj, cena_bez_dph:price });
    });
    if (!odberatel && !__pickedCustomer){ showStatus('Vyber odberateľa (alebo zadaj názov).', true); return; }
    if (!items.length){ showStatus('Pridaj aspoň 1 položku', true); return; }
    try{
      const body = { odberatel, datum_dodania, poznamka, items };
      if (__pickedCustomer && __pickedCustomer.id) body.customer_id = __pickedCustomer.id;
      const res = await apiRequest('/api/leader/b2b/orders', { method:'POST', body });
      if (!res || !res.order_id){ showStatus('Server nevrátil ID objednávky.', true); return; }
      await apiRequest(`/api/leader/b2b/notify_order`, { method:'POST', body:{ order_id: res.order_id } }).catch(()=>{});
      showStatus('B2B objednávka uložená.', false);
      $$('[data-section="leader-b2b"]')[0]?.click();
      loadB2B();
    }catch(e){ showStatus(e.message||String(e), true); }
  }

  function openB2BEditModal(row){
    let items = (()=>{
      const raw = row.polozky_json || row.polozky || row.items || '[]';
      try { return typeof raw==='string'? JSON.parse(raw) : (Array.isArray(raw)? raw : []); }catch(_){ return []; }
    })();
    const no = row.cislo_objednavky || row.id;
    const html = `
      <div>
        <div class="muted" style="margin-bottom:.5rem">Úprava objednávky #${escapeHtml(no)} • Dodanie: ${escapeHtml(row.pozadovany_datum_dodania||'')}</div>
        <table id="b2b-edit-tbl" class="tbl" style="width:100%">
          <thead><tr><th>EAN</th><th>Názov</th><th>Množstvo</th><th>MJ</th><th>cena bez DPH</th><th></th></tr></thead>
          <tbody>${items.map(it=>`
            <tr>
              <td><input class="e-ean" value="${escapeHtml(it.ean||it.ean_produktu||'')}"></td>
              <td><input class="e-name" value="${escapeHtml(it.name||it.nazov||it.nazov_vyrobku||'')}"></td>
              <td><input class="e-qty" type="number" step="0.001" min="0" value="${escapeHtml(String(it.quantity||it.mnozstvo||0))}"></td>
              <td><input class="e-mj"  value="${escapeHtml(it.unit||it.mj||'ks')}"></td>
              <td><input class="e-price" type="number" step="0.01" min="0" value="${escapeHtml(String(it.cena_bez_dph||0))}"></td>
              <td><button class="btn btn-sm" data-del>×</button></td>
            </tr>`).join('')}
          </tbody>
        </table>
        <button class="btn btn-secondary" id="b2b-edit-add" style="margin-top:.5rem">+ položka</button>
        <div style="text-align:right;margin-top:10px">
          <button class="btn btn-secondary" id="b2b-edit-cancel">Zrušiť</button>
          <button class="btn btn-primary"   id="b2b-edit-save">Uložiť a odoslať potvrdenie</button>
        </div>
      </div>`;
    modal(`Upraviť B2B objednávku #${escapeHtml(no)}`, html, (body)=>{
      const tb = body.querySelector('#b2b-edit-tbl tbody');
      body.querySelector('#b2b-edit-add').onclick = ()=> {
        const tr = doc.createElement('tr');
        tr.innerHTML = `
          <td><input class="e-ean"></td>
          <td><input class="e-name"></td>
          <td><input class="e-qty" type="number" step="0.001" min="0"></td>
          <td><input class="e-mj"  value="ks"></td>
          <td><input class="e-price" type="number" step="0.01" min="0"></td>
          <td><button class="btn btn-sm" data-del>×</button></td>`;
        tb.appendChild(tr); tr.querySelector('[data-del]').onclick=()=>tr.remove();
      };
      tb.querySelectorAll('[data-del]').forEach(b=> b.onclick = ()=> b.closest('tr').remove());
      body.querySelector('#b2b-edit-cancel').onclick = ()=> closeModal();

      body.querySelector('#b2b-edit-save').onclick = async ()=>{
        const rows = Array.from(tb.querySelectorAll('tr')).map(tr=>{
          return {
            ean:  safeStr(tr.querySelector('.e-ean').value),
            name: safeStr(tr.querySelector('.e-name').value),
            quantity: toNum(tr.querySelector('.e-qty').value,0),
            unit: safeStr(tr.querySelector('.e-mj').value||'ks'),
            cena_bez_dph: toNum(tr.querySelector('.e-price').value,0)
          };
        }).filter(x=> x.ean && x.name && x.quantity>0);
        if (!rows.length){ showStatus('Pridaj aspoň jednu položku.', true); return; }
        try{
          await apiRequest('/api/leader/b2b/update_order', { method:'POST', body:{ order_id: row.id, items: rows } });
          await apiRequest('/api/leader/b2b/notify_order', { method:'POST', body:{ order_id: row.id } }).catch(()=>{});
          showStatus('Objednávka upravená a potvrdenie odoslané.', false);
          closeModal(); loadB2B();
        }catch(e){ showStatus(e.message||String(e), true); }
      };
    });
  }

  // ============================== KRÁJAČKY ==================================
  // ============================== KRÁJAČKY ==================================
  async function submitNewCutJob(payload) {
  try {
    lockUI?.();
    const resp = await apiRequest('/api/leader/cut_jobs', { method: 'POST', body: payload });
    if (resp?.error) return; // 401/403 spracuje common.js a presmeruje
    closeNewJobModal();
    refreshCutJobsList();
  } catch (err) {
    console.error(err);
    showStatus?.('Nepodarilo sa pridať úlohu.');
  } finally {
    unlockUI?.(); // KĽÚČOVÉ: vždy odomknúť overlay
  }
}

async function loadCutJobs(){
  const d  = $('#cut-date').value || todayISO();
  const tb = $('#tbl-cut tbody');
  tb.innerHTML = '<tr><td colspan="9" class="muted">Načítavam…</td></tr>';

  try{
    const rows = await apiRequest(`/api/leader/cut_jobs?date=${encodeURIComponent(d)}`);

    tb.innerHTML = rows.length ? rows.map(r=>`
      <tr data-id="${escapeHtml(r.id||'')}">
        <td>${escapeHtml(r.id||'')}</td>
        <td>${escapeHtml(r.order_id||'')}</td>
        <td>${escapeHtml(r.ean||'')}</td>
        <td>${escapeHtml(r.nazov_vyrobku||'')}</td>
        <td>${escapeHtml(r.mnozstvo ?? '')}</td>
        <td>${escapeHtml(r.mj||'ks')}</td>
        <td>${escapeHtml(r.due_date||'')}</td>
        <td>${escapeHtml(r.stav||'')}</td>
        <td>
          <button class="btn btn-sm" data-cut="priprava" data-id="${escapeHtml(r.id||'')}" ${r.stav==='priprava'?'disabled':''}>→ príprava</button>
          <button class="btn btn-sm" data-cut="hotovo"   data-id="${escapeHtml(r.id||'')}" ${r.stav==='hotovo'  ?'disabled':''}>✓ hotovo</button>
        </td>
      </tr>
    `).join('') : '<tr><td colspan="9" class="muted">Žiadne úlohy.</td></tr>';

    $$('#tbl-cut button[data-cut]').forEach(b=>{
      b.onclick = async ()=>{
        const id = b.getAttribute('data-id');
        const st = b.getAttribute('data-cut');
        try{
          if (st === 'hotovo'){
            const tr       = b.closest('tr');
            const planned  = toNum(tr && $('td:nth-child(5)', tr).textContent, 0);
            let realPieces = window.prompt('Počet hotových balíčkov (ks):', String(planned || ''));
            if (realPieces === null) return; // zrušené
            realPieces = toNum(realPieces, 0);
            if (!Number.isFinite(realPieces) || realPieces <= 0){
              showStatus('Zadaj kladný počet kusov.', true);
              return;
            }
            await apiRequest(`/api/leader/cut_jobs/${encodeURIComponent(id)}`, {
              method:'PATCH',
              body: { stav:'hotovo', real_ks: realPieces }
            });
          } else {
            await apiRequest(`/api/leader/cut_jobs/${encodeURIComponent(id)}`, {
              method:'PATCH',
              body: { stav:'priprava' }
            });
          }
          showStatus('Stav uložený.', false);
          loadCutJobs();
        } catch(e){
          showStatus(e.message || String(e), true);
        }
      };
    });

  } catch(e){
    tb.innerHTML = `<tr><td colspan="9" class="error">${escapeHtml(e.message || String(e))}</td></tr>`;
  }
}

  function openNewCutModal(){
    const html = `
      <div class="form-grid">
        <div class="form-group"><label>Objednávka (voliteľné)</label><input id="cut-order"></div>
        <div class="form-group"><label>EAN</label><input id="cut-ean"></div>
        <div class="form-group"><label>Názov výrobku</label><input id="cut-name"></div>
        <div class="form-group"><label>Množstvo</label><input id="cut-qty" type="number" step="0.001" min="0"></div>
        <div class="form-group"><label>MJ</label><input id="cut-mj" value="kg"></div>
        <div class="form-group"><label>Termín</label><input id="cut-due" type="date" value="${todayISO()}"></div>
      </div>
      <div style="text-align:right;margin-top:10px">
        <button class="btn btn-secondary" id="cut-cancel">Zrušiť</button>
        <button class="btn btn-primary"   id="cut-save">Uložiť úlohu</button>
      </div>`;
    modal('Nová úloha', html, (body)=>{
      $('#cut-cancel', body).onclick = ()=> closeModal();
      $('#cut-save', body).onclick = async ()=>{
        const payload = {
          order_id:  safeStr($('#cut-order', body).value) || null,
          ean:       safeStr($('#cut-ean',   body).value),
          name:      safeStr($('#cut-name',  body).value),
          quantity:  toNum($('#cut-qty',    body).value, 0),
          unit:      safeStr($('#cut-mj',   body).value||'kg'),
          due_date:  $('#cut-due', body).value || todayISO()
        };
        if (!payload.ean || !payload.name || !payload.quantity){ showStatus('Vyplň EAN, názov a množstvo', true); return; }
        try{ await apiRequest('/api/leader/cut_jobs', { method:'POST', body: payload }); showStatus('Úloha uložená.', false); closeModal(); loadCutJobs(); }
        catch(e){ showStatus(e.message||String(e), true); }
      };
    });
  }

  // ============================== AUTOCOMPLETE DODÁVATEĽ ===================
  function attachSupplierAutocomplete(){
    const input = $('#nb2b-name'); if (!input) return;

    let popup = $('#nb2b-suggest');
    if (!popup){
      popup = doc.createElement('div'); popup.id='nb2b-suggest';
      popup.style.cssText='position:absolute;z-index:1000;background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.15);display:none;max-height:240px;overflow:auto';
      doc.body.appendChild(popup);
    }
    function position(){ const r = input.getBoundingClientRect(); popup.style.left=(window.scrollX+r.left)+'px'; popup.style.top=(window.scrollY+r.bottom+4)+'px'; popup.style.minWidth=r.width+'px'; }

    input.addEventListener('input', async ()=>{
      const q = input.value.trim();
      if (q.length < 2){ popup.style.display='none'; return; }
      position(); popup.innerHTML = '<div style="padding:.5rem" class="muted">Hľadám…</div>'; popup.style.display='block';

      const list = await searchSuppliers(q);
      if (!list.length){ popup.innerHTML = '<div style="padding:.5rem" class="muted">Žiadne výsledky</div>'; return; }

      popup.innerHTML = list.map(x=>`<div data-id="${escapeHtml(String(x.id))}" data-json='${escapeHtml(JSON.stringify(x))}' style="padding:.4rem .6rem;cursor:pointer">${escapeHtml(x.name)} <span class="muted">(${escapeHtml(x.code||'')})</span></div>`).join('');
      Array.from(popup.children).forEach(div=>{
        div.onclick = async ()=>{
          const data = JSON.parse(div.getAttribute('data-json'));
          __pickedCustomer = data;
          input.value = data.name; popup.style.display='none';

          const box = $('#nb2b-pl-box') || (()=>{
            const d = doc.createElement('div'); d.id='nb2b-pl-box'; d.className='muted'; d.style.margin='8px 0';
            const body = $('#manual-b2b-form .card-body') || $('#leader-manual-b2b .card .card-body') || doc.body;
            body.insertBefore(d, body.firstChild); return d;
          })();

          const pls = await fetchPricelists(data.id);
          if (!pls.length){ box.innerHTML = '<div class="muted">Pre odberateľa nie sú evidované cenníky.</div>'; __pickedPricelist=null; __pricelistMapByEAN=Object.create(null); return; }

          box.innerHTML = `
            <label>Vyber cenník:</label>
            <select id="nb2b-pl" style="min-width:260px">${pls.map(p=>`<option value="${escapeHtml(p.id)}">${escapeHtml(p.name||('Cenník '+String(p.id||'')))}</option>`).join('')}</select>
            <div id="nb2b-pl-note" class="muted" style="margin-top:.25rem">Ceny položiek sa doplnia pri pridávaní EAN z vybraného cenníka.</div>
            <div id="nb2b-pl-preview" style="margin-top:.5rem"></div>`;

          __pickedPricelist = pls[0]||null;
          __pricelistMapByEAN = Object.create(null);
          if (__pickedPricelist && Array.isArray(__pickedPricelist.items)){
            __pickedPricelist.items.forEach(it=>{ if (it && it.ean != null) __pricelistMapByEAN[String(it.ean)] = toNum(it.price||it.cena_bez_dph||0,0); });
          }
          renderPricelistPreview(__pickedPricelist, box);

          $('#nb2b-pl').onchange = (e)=>{
            const pick = pls.find(x=> String(x.id) === e.target.value);
            __pickedPricelist = pick || null;
            __pricelistMapByEAN = Object.create(null);
            if (__pickedPricelist && Array.isArray(__pickedPricelist.items)){
              __pricelistMapByEAN = Object.create(null);
              __pickedPricelist.items.forEach(it=>{ if (it && it.ean != null) __pricelistMapByEAN[String(it.ean)] = toNum(it.price||it.cena_bez_dph||0,0); });
            }
            renderPricelistPreview(__pickedPricelist, box);
          };
        };
      });
    });

    window.addEventListener('resize', ()=>{ if(popup.style.display==='block') position(); });
    document.addEventListener('click', (e)=>{ if (!popup.contains(e.target) && e.target!==input) popup.style.display='none'; });
  }

  // ============================== BOOT =====================================
  function boot(){
    // nav – guard na chýbajúce sekcie (žiadny crash)
    $$('.sidebar-link').forEach(a=>{
      a.onclick = ()=>{
        $$('.sidebar-link').forEach(x=> x.classList.remove('active'));
        a.classList.add('active');
        const secId = a.getAttribute('data-section');
        const target = secId ? $('#'+secId) : null;
        $$('.content-section').forEach(s=> s.classList.remove('active'));
        if (target) target.classList.add('active'); else console.warn('[leader] section not found:', secId);
      };
    });

    // defaults
    $('#ldr-date') && ($('#ldr-date').value = todayISO());
    $('#b2c-date') && ($('#b2c-date').value = todayISO());
    $('#b2b-date') && ($('#b2b-date').value = todayISO());
    $('#cut-date') && ($('#cut-date').value = todayISO());
    $('#nb2b-date') && ($('#nb2b-date').value = todayISO());

    // handlers
    $('#ldr-refresh') && ($('#ldr-refresh').onclick = loadDashboard);
    $('#plan-commit') && ($('#plan-commit').onclick = commitPlan);

    $('#b2c-refresh') && ($('#b2c-refresh').onclick = loadB2C);
    $('#b2b-refresh') && ($('#b2b-refresh').onclick = loadB2B);

    attachSupplierAutocomplete();
    $('#nb2b-add')  && ($('#nb2b-add').onclick  = ()=> addManualRow($('#nb2b-items tbody')));
    $('#nb2b-save') && ($('#nb2b-save').onclick = saveManualB2B);

    $('#cut-refresh') && ($('#cut-refresh').onclick = loadCutJobs);
    $('#cut-new')     && ($('#cut-new').onclick     = openNewCutModal);

    loadDashboard(); loadB2C(); loadB2B(); loadCutJobs();
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', boot);
  else boot();

})(window, document);
