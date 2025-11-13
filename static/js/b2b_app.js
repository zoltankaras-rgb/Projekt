document.addEventListener('DOMContentLoaded', () => {
  const loader = document.getElementById('loader');
  const notification = document.getElementById('notification');
  const authViewsContainer = document.getElementById('auth-views');
  const customerPortalView = document.getElementById('view-customer-portal');

  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const passwordResetRequestForm = document.getElementById('passwordResetRequestForm');
  const passwordResetForm = document.getElementById('passwordResetForm');
  const forgotPasswordLink = document.getElementById('forgot-password-link');
  const backToLoginLinks = document.querySelectorAll('.back-to-login-link');
  const logoutLink = document.getElementById('logout-link');

  console.log('✅ b2b_app.js bol úspešne načítaný');

  let appState = { currentUser: null, products: {}, order: {} };
  let commInited = false;

  // Anti-bot (voliteľné)
  const AB = { token: null, minDelay: 800, issuedAt: 0 };
  async function getAbToken(){
    try{
      const r = await fetch('/api/b2b/ab-token', { credentials:'same-origin' });
      const j = await r.json();
      AB.token = j.token; AB.minDelay = j.min_delay_ms || 800; AB.issuedAt = performance.now();
    }catch{ AB.token = null; AB.minDelay = 800; AB.issuedAt = performance.now(); }
  }
  function ensureMinDelay(){
    const elapsed = performance.now() - (AB.issuedAt || 0);
    return new Promise(res=>setTimeout(res, Math.max(0,(AB.minDelay||800)-elapsed)));
  }
  function addHoneypot(form){
    if(!form || form.querySelector('input[name="hp"]')) return;
    const hp=document.createElement('input'); hp.type='text'; hp.name='hp'; hp.autocomplete='off'; hp.tabIndex=-1;
    hp.style.position='absolute'; hp.style.left='-10000px'; hp.style.opacity='0';
    form.appendChild(hp);
  }
  [loginForm, registerForm, passwordResetRequestForm, passwordResetForm].forEach(addHoneypot);
  getAbToken();

  // a11y autocomplete
  const setA=(id,val)=>{const el=document.getElementById(id); if(el) el.setAttribute('autocomplete',val);};
  setA('login-id','username'); setA('login-password','current-password');
  setA('reg-password','new-password'); setA('new-password','new-password'); setA('confirm-password','new-password');
  setA('reg-phone','tel');

  function showMainView(v){
    authViewsContainer?.classList.toggle('hidden', v!=='auth');
    customerPortalView?.classList.toggle('hidden', v!=='customer');
  }
  function showNotification(msg,type){
    if(!notification) return; notification.textContent=msg; notification.className=type;
    notification.classList.remove('hidden'); setTimeout(()=>notification.classList.add('hidden'),5000);
  }
  function showLoader(){ loader?.classList.remove('hidden'); }
  function hideLoader(){ loader?.classList.add('hidden'); }

  async function apiCall(url, data){
    showLoader();
    try{
      const res = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(data||{})});
      const ct = res.headers.get('Content-Type')||'';
      const out = ct.includes('application/json') ? await res.json() : { error: await res.text() };
      if(!res.ok || out.error) throw new Error(out.error || `HTTP ${res.status}`);
      return out;
    }catch(e){ showNotification(e.message||'Neznáma chyba servera.','error'); return null; }
    finally{ hideLoader(); }
  }

  // AUTH
  if (loginForm){
    loginForm.addEventListener('submit', async (e)=>{
      e.preventDefault();
      await ensureMinDelay();
      const data = {
        zakaznik_id: loginForm.elements.zakaznik_id.value,
        password: loginForm.elements.password.value,
        ab_token: AB.token,
        hp: loginForm.querySelector('input[name="hp"]')?.value || ''
      };
      const result = await apiCall('/api/b2b/login', data);
      if (result && result.userData) handleLoginSuccess(result.userData);
      getAbToken();
    });
  }

  if (registerForm){
    registerForm.addEventListener('submit', async (e)=>{
      e.preventDefault();
      const pwd = registerForm.elements.password.value;
      if (pwd.length < 6) return showNotification('Heslo musí mať aspoň 6 znakov.','error');
      await ensureMinDelay();
      const data = {
        nazov_firmy: registerForm.elements.nazov_firmy.value,
        adresa: registerForm.elements.adresa.value,
        adresa_dorucenia: (registerForm.elements.adresa_dorucenia?.value || ''),
        email: registerForm.elements.email.value,
        telefon: registerForm.elements.telefon.value,
        password: pwd, gdpr: registerForm.elements.gdpr.checked,
        ab_token: AB.token, hp: registerForm.querySelector('input[name="hp"]')?.value || ''
      };
      const out = await apiCall('/api/b2b/register', data);
      if (out){ showNotification(out.message||'Registrácia odoslaná.','success'); registerForm.reset();
        document.querySelector('.tab-button[data-tab="login"]')?.click(); }
      getAbToken();
    });
  }

  passwordResetRequestForm?.addEventListener('submit', async (e)=>{
    e.preventDefault(); await ensureMinDelay();
    const out = await apiCall('/api/b2b/request-reset',{ email: passwordResetRequestForm.elements.email.value, ab_token: AB.token, hp: passwordResetRequestForm.querySelector('input[name="hp"]')?.value || '' });
    if (out) showNotification(out.message,'success'); getAbToken();
  });

  passwordResetForm?.addEventListener('submit', async (e)=>{
    e.preventDefault();
    const p1=passwordResetForm.elements.password.value, p2=passwordResetForm.elements['confirm-password'].value;
    if (p1.length<6) return showNotification('Heslo musí mať aspoň 6 znakov.','error');
    if (p1!==p2)     return showNotification('Heslá sa nezhodujú.','error');
    await ensureMinDelay();
    const out = await apiCall('/api/b2b/perform-reset',{ token: passwordResetForm.elements.token.value, password: p1, ab_token: AB.token, hp: passwordResetForm.querySelector('input[name="hp"]')?.value || '' });
    if (out){ showNotification(out.message,'success'); setTimeout(()=>{ window.history.replaceState({},document.title,window.location.pathname); showAuthView('view-auth'); },2000); }
    getAbToken();
  });

  logoutLink?.addEventListener('click',(e)=>{
    e.preventDefault();
    sessionStorage.removeItem('b2bUser');
    appState.currentUser = null;
    loginForm?.reset();
    showMainView('auth');
  });

  // Prihlásenie → krok 1
  function handleLoginSuccess(user){
    appState.currentUser = user;
    sessionStorage.setItem('b2bUser', JSON.stringify(user));
    if (user.role === 'admin'){ showNotification('Admin prihlásenie úspešné.','success'); return; }

    showMainView('customer');
    document.getElementById('customer-name').textContent = user.nazov_firmy || '';

    const bar = document.getElementById('announcement-bar');
    if (user.announcement){ bar.textContent=user.announcement; bar.classList.remove('hidden'); }
    else bar.classList.add('hidden');

    const sel = document.getElementById('pricelist-select');
    const stepProducts = document.getElementById('step-products');
    const productsContainer = document.getElementById('products-container');
    const details = document.getElementById('order-form-details');

    stepProducts.classList.add('hidden');
    productsContainer.innerHTML = '';
    details.classList.add('hidden');
    appState.order = {}; appState.products = {};

    sel.innerHTML = '<option value="">-- Vyberte cenník --</option>';
    (user.pricelists || []).forEach(p=>{
      const o=document.createElement('option'); o.value=p.id; o.textContent=p.nazov_cennika; sel.appendChild(o);
    });

    sel.onchange = async () => {
      const id = sel.value;
      if (!id){
        stepProducts.classList.add('hidden');
        productsContainer.innerHTML = '';
        details.classList.add('hidden');
        appState.order = {}; appState.products = {};
        return;
      }
      const res = await apiCall('/api/b2b/get-products', { pricelist_id: id });
      if (!res) return;
      appState.products = res.productsByCategory || {};
      renderProducts();
      stepProducts.classList.remove('hidden');
    };

    document.getElementById('btn-back-to-pricelist').onclick = () => {
      sel.value = '';
      stepProducts.classList.add('hidden');
      productsContainer.innerHTML = '';
      details.classList.add('hidden');
      appState.order = {}; appState.products = {};
    };

    document.getElementById('btn-submit-order').onclick = submitOrder;
  }

  // render produktov
  function renderProducts(){
    const container = document.getElementById('products-container');
    const details = document.getElementById('order-form-details');
    container.innerHTML=''; appState.order={}; details.classList.add('hidden');

    const cats = Object.keys(appState.products||{});
    if (!cats.length){ container.innerHTML='<p>Pre tento cenník neboli nájdené žiadne produkty.</p>'; return; }

    cats.forEach(category=>{
      let html = `<h3>${category}</h3><table><thead><tr><th>Názov</th><th style="width: 120px; text-align: center;">Cena/MJ</th><th style="width: 250px;">Množstvo</th></tr></thead><tbody>`;
      (appState.products[category]||[]).forEach(p=>{
        const price = Number(p.cena||0).toFixed(2);
        const ean   = p.ean_produktu;
        const isKg  = (p.mj||'').toLowerCase()==='kg';
        html += `<tr data-product-ean="${ean}">
          <td>${p.nazov_vyrobku}</td>
          <td style="text-align:center;">${price} € / ${p.mj}</td>
          <td>
            <div style="display:flex;align-items:center;justify-content:space-between;gap:15px;height:40px;">
              <input type="text" inputmode="decimal" class="quantity-input" data-ean="${ean}" style="width:80px;text-align:right;">
              ${isKg?`
              <div style="display:flex;align-items:center;gap:5px;">
                <input type="checkbox" id="isPiece_${ean}" class="by-piece-checkbox" style="cursor:pointer;width:18px;height:18px;">
                <label for="isPiece_${ean}" style="font-size:.9rem;cursor:pointer;">KS</label>
                <button id="noteBtn_${ean}" class="item-note-button hidden" title="Pridať poznámku"><i class="fas fa-edit"></i></button>
              </div>`:'<div></div>'}
            </div>
          </td>
        </tr>`;
      });
      html += '</tbody></table>';
      container.insertAdjacentHTML('beforeend', html);
    });

    container.querySelectorAll('.quantity-input').forEach(i=>i.addEventListener('input', onQty));
    container.querySelectorAll('.by-piece-checkbox').forEach(chk=>chk.addEventListener('change', ()=>togglePiece(chk)));
    container.querySelectorAll('.item-note-button').forEach(btn=>btn.addEventListener('click', ()=>{
      const ean = btn.id.replace('noteBtn_',''); openItemNoteModal(ean);
    }));
  }

  function findByEan(ean){
    for(const c in appState.products){
      const p=(appState.products[c]||[]).find(x=>String(x.ean_produktu)===String(ean));
      if (p) return p;
    } return null;
  }
  function onQty(e){
    const input=e.target, ean=input.dataset.ean;
    const v=(input.value||'').replace(',','.'), q=parseFloat(v);
    if (!isNaN(q) && q>0){
      const p=findByEan(ean);
      appState.order[ean]={ ean, name:p.nazov_vyrobku, price:Number(p.cena||0), dph:Math.abs(Number(p.dph||0)), unit:p.mj, quantity:q, item_note:appState.order[ean]?.item_note||'' };
    } else delete appState.order[ean];
    updateTotals();
  }
  function togglePiece(chk){
    const ean=chk.id.replace('isPiece_',''); const btn=document.getElementById(`noteBtn_${ean}`);
    chk.checked ? btn?.classList.remove('hidden') : btn?.classList.add('hidden');
    if (!chk.checked && appState.order[ean]) appState.order[ean].item_note='';
  }
  function openItemNoteModal(ean){
    const p=findByEan(ean); const cur=appState.order[ean]?.item_note||'';
    const mc=document.getElementById('modal-container');
    mc.innerHTML=`<div class="modal-backdrop" onclick="closeModal()"></div>
      <div class="modal-content">
        <div class="modal-header"><h4>Poznámka k položke: ${p?.nazov_vyrobku||ean}</h4><button class="close-button" onclick="closeModal()">&times;</button></div>
        <div class="form-group"><label for="item-note-input">Zadajte požiadavku (napr. 150g balenia):</label><textarea id="item-note-input" rows="4">${cur}</textarea></div>
        <button class="button" onclick="saveItemNote('${ean}')">Uložiť poznámku</button>
      </div>`;
    mc.style.display='flex';
  }
  window.saveItemNote=function(ean){
    const note=document.getElementById('item-note-input').value;
    if (appState.order[ean]) appState.order[ean].item_note=note;
    else {
      const p=findByEan(ean);
      appState.order[ean]={ ean, name:p.nazov_vyrobku, price:Number(p.cena||0), dph:Math.abs(Number(p.dph||0)), unit:p.mj, quantity:0, item_note:note };
    }
    closeModal();
  };
  window.closeModal=function(){ const mc=document.getElementById('modal-container'); mc.style.display='none'; mc.innerHTML=''; };

  function updateTotals(){
    const box=document.getElementById('order-summary');
    const details=document.getElementById('order-form-details');
    const items=Object.values(appState.order);
    if (!items.length){ box.innerHTML=''; details.classList.add('hidden'); return; }
    let net=0,vat=0,gross=0;
    items.forEach(i=>{ const n=i.price*i.quantity; const v=n*((Math.abs(i.dph)||0)/100); net+=n; vat+=v; });
    gross=net+vat;
    box.innerHTML=`<div class="order-summary-box">
      <p><span>Spolu bez DPH:</span> <strong>${net.toFixed(2)} €</strong></p>
      <p><span>DPH:</span> <strong>${vat.toFixed(2)} €</strong></p>
      <p class="total"><span>Celkom s DPH:</span> <strong>${gross.toFixed(2)} €</strong></p>
    </div>`;
    details.classList.remove('hidden');
  }

  async function submitOrder(){
    const d=document.getElementById('delivery-date').value;
    if (!d) return showNotification('Zadajte požadovaný dátum dodania.','error');
    const items=Object.values(appState.order);
    if (!items.length) return showNotification('Nemáte v objednávke žiadne položky.','error');

    const out = await apiCall('/api/b2b/submit-order',{
      userId: appState.currentUser.id,
      customerName: appState.currentUser.nazov_firmy,
      customerEmail: appState.currentUser.email,
      items, deliveryDate:d,
      note: document.getElementById('order-note').value
    });
    if(!out) return;

    // reset + návrat na krok 1
    appState.order={};
    document.querySelectorAll('.quantity-input').forEach(i=>i.value='');
    document.getElementById('order-note').value='';
    document.getElementById('delivery-date').value='';
    updateTotals();

    document.getElementById('products-container').innerHTML =
      `<h3>Ďakujeme!</h3><p style="font-size:1.5rem;text-align:center;">${out.message}</p><p style="text-align:center;">Na váš e-mail sme odoslali potvrdenie.</p>`;

    setTimeout(()=>{
      const sel=document.getElementById('pricelist-select');
      const stepProducts=document.getElementById('step-products');
      sel.value=''; stepProducts.classList.add('hidden');
      document.getElementById('products-container').innerHTML='';
      document.getElementById('order-form-details').classList.add('hidden');
    }, 1500);
  }
  window.submitOrder = submitOrder;

  // História + PDF
  window.loadB2BOrderHistory = async function(){
    const cont=document.getElementById('history-container');
    cont.innerHTML='<p>Načítavam históriu objednávok...</p>';
    try{
      const uRaw=sessionStorage.getItem('b2bUser'); const u=uRaw?JSON.parse(uRaw):null;
      if (!u || !u.id){ cont.innerHTML='<p class="error">Nie ste prihlásený.</p>'; return; }
      const resp=await apiCall('/api/b2b/get-order-history',{ userId:u.id });
      const rows=(resp&&resp.orders)||[];
      if (!rows.length){ cont.innerHTML='<p>Zatiaľ nemáte žiadne B2B objednávky.</p>'; return; }
      let html='';
      rows.forEach(o=>{
        const d = o.datum_vytvorenia ? new Date(o.datum_vytvorenia).toLocaleDateString('sk-SK') : '';
        const total = (o.celkova_suma_s_dph!=null) ? Number(o.celkova_suma_s_dph).toFixed(2)+' €' : '(neuvedené)';
        const pdf   = `/api/b2b/order-pdf/${o.id}?user_id=${encodeURIComponent(u.id)}`;
        const pdfDl = `${pdf}&download=1`;
        html += `<div class="history-item" style="border:1px solid var(--border-color);border-radius:8px;margin-bottom:12px;">
          <div class="history-header" style="padding:12px;display:flex;justify-content:space-between;align-items:center;font-weight:600;">
            <span>Obj. č. ${o.cislo_objednavky}${d?` (${d})`:''} – Stav: ${o.stav||'—'}</span>
            <span>Spolu: ${total}</span>
          </div>
          <div class="history-body" style="padding:0 12px 12px 12px;">
            ${o.poznamka?`<p><strong>Poznámka:</strong> ${o.poznamka}</p>`:''}
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <a class="button" style="width:auto" href="${pdf}" target="_blank" rel="noopener">Zobraziť PDF</a>
              <a class="button secondary" style="width:auto" href="${pdfDl}" download>Stiahnuť PDF</a>
            </div>
          </div>
        </div>`;
      });
      cont.innerHTML=html;
    }catch(e){ console.error(e); cont.innerHTML='<p class="error">Nepodarilo sa načítať históriu.</p>'; }
  };

  // Komunikácia – init/submit/list
  async function initCommunicationView(){
    if (commInited) return;
    commInited = true;

    const form = document.getElementById('commForm');
    form.addEventListener('submit', async (e)=>{
      e.preventDefault();
      const subj = document.getElementById('comm-subject').value.trim();
      const body = document.getElementById('comm-body').value.trim();
      if (!subj || !body){ showNotification('Vyplňte predmet aj správu.','error'); return; }

      const fd = new FormData();
      fd.append('userId', appState.currentUser.id);
      fd.append('subject', subj);
      fd.append('body', body);
      const file = document.getElementById('comm-file').files[0];
      if (file) fd.append('file', file);

      try{
        showLoader();
        const res = await fetch('/api/b2b/messages/send',{ method:'POST', body: fd, credentials:'same-origin' });
        const out = await res.json();
        if(!res.ok || out.error) throw new Error(out.error || `HTTP ${res.status}`);
        showNotification(out.message || 'Správa odoslaná.','success');
        form.reset();
        await loadCommunicationList();
      }catch(err){
        showNotification(err.message || 'Nepodarilo sa odoslať správu.','error');
      }finally{
        hideLoader();
      }
    });

    await loadCommunicationList();
  }

  async function loadCommunicationList(){
    const list = document.getElementById('comm-list');
    list.innerHTML = '<p>Načítavam správy...</p>';
    try{
      const resp = await apiCall('/api/b2b/messages/my',{ userId: appState.currentUser.id, page:1, page_size:50 });
      const rows = (resp && resp.messages) || [];
      if (!rows.length){ list.innerHTML='<p>Zatiaľ nemáte žiadne správy.</p>'; return; }
      let html='';
      rows.forEach(m=>{
        const dt = m.created_at ? new Date(m.created_at.replace(' ','T')).toLocaleString('sk-SK') : '';
        const dir = (m.direction==='out'?'MIK → vy':'Vy → MIK');
        html += `<div style="border:1px solid var(--border-color);border-radius:8px;margin-bottom:10px;padding:10px;">
          <div style="display:flex;justify-content:space-between;gap:8px;">
            <strong>${dir}</strong>
            <span style="color:#6b7280;">${dt}</span>
          </div>
          <div style="margin-top:6px;"><strong>${m.subject || '(bez predmetu)'}</strong></div>
          <div style="white-space:pre-wrap;margin-top:6px;">${(m.body||'').replace(/</g,'&lt;')}</div>
          ${m.attachment_filename ? `<div style="margin-top:6px;color:#6b7280;">Príloha: ${m.attachment_filename}</div>`:''}
          <div style="margin-top:6px;color:#6b7280;">Stav: ${m.status}</div>
        </div>`;
      });
      list.innerHTML = html;
    }catch(e){
      console.error(e);
      list.innerHTML = '<p class="error">Nepodarilo sa načítať správy.</p>';
    }
  }

  // prepínač view
  window.showPortalView = function(viewId){
    document.querySelectorAll('#portal-views-container > div').forEach(v=>v.classList.add('hidden'));
    document.getElementById(viewId)?.classList.remove('hidden');
    document.querySelectorAll('.tab-button').forEach(b=>b.classList.remove('active'));
    if (viewId==='view-new-order') document.getElementById('tab-btn-order')?.classList.add('active');
    if (viewId==='view-order-history'){ document.getElementById('tab-btn-history')?.classList.add('active'); loadB2BOrderHistory(); }
    if (viewId==='view-communication'){ document.getElementById('tab-btn-comm')?.classList.add('active'); initCommunicationView(); }
  };

  // init
  (function init(){
    const storedUser = sessionStorage.getItem('b2bUser');
    if (storedUser){ try{ handleLoginSuccess(JSON.parse(storedUser)); return; } catch{ sessionStorage.removeItem('b2bUser'); } }
    showMainView('auth');

    document.querySelectorAll('.tab-button[data-tab]')?.forEach(btn=>{
      btn.addEventListener('click',(e)=>{
        const tab=e.currentTarget.dataset.tab;
        document.getElementById('login-form-container').classList.toggle('hidden', tab!=='login');
        document.getElementById('register-form-container').classList.toggle('hidden', tab!=='register');
        document.querySelectorAll('.tab-button').forEach(b=>b.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });
    forgotPasswordLink?.addEventListener('click',(e)=>{ e.preventDefault(); showAuthView('view-password-reset-request'); });
    backToLoginLinks?.forEach(a=>a.addEventListener('click',(e)=>{ e.preventDefault(); showAuthView('view-auth'); }));
  })();

  function showAuthView(viewId){
    document.querySelectorAll('#auth-views > div').forEach(v => v.classList.add('hidden'));
    document.getElementById(viewId)?.classList.remove('hidden');
  }
});
