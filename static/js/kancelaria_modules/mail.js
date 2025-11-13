// =================================================================
// === KANCELÁRIA – POŠTA (single-panel view) =======================
// =================================================================
(async function () {
  'use strict';

  // ---- Fallbacky -------------------------------------------------
  if (typeof window.escapeHtml !== 'function') {
    window.escapeHtml = s => s == null ? '' : String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }
  if (typeof window.apiRequest !== 'function') {
    window.apiRequest = async (url, options={})=>{
      const opts = Object.assign({ credentials:'same-origin', headers:{} }, options);
      if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
        opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
        opts.body = JSON.stringify(opts.body);
      }
      let r; try { r = await fetch(url, opts); } catch(e){ return { error:'Network error', detail:String(e) }; }
      const ct = (r.headers.get('content-type')||'').toLowerCase();
      let payload=null; try { payload = ct.includes('application/json') ? await r.json() : await r.text(); } catch(_){}
      if (r.status === 401) { if (typeof window.onUnauthorized==='function') window.onUnauthorized(); return { error:'Unauthorized', status:401, raw:payload }; }
      if (!r.ok) return { error:(payload && payload.error) || r.statusText || `HTTP ${r.status}`, status:r.status, raw:payload };
      return payload;
    };
  }

  // ---- Pomocné ---------------------------------------------------
  function formatBytes(b){ const n=Number(b||0); if(n<1024) return `${n} B`; const u=['KB','MB','GB']; let i=-1,v=n; do{v/=1024;i++;}while(v>=1024&&i<u.length-1); return `${v.toFixed(1)} ${u[i]}`; }
  function ensureArray(x){ if(Array.isArray(x))return x; if(!x)return []; try{ const j=JSON.parse(x); return Array.isArray(j)?j:[] }catch(_){ return [] } }
  function iconForFolder(f){ return f==='INBOX'?'fa-inbox':f==='SENT'?'fa-paper-plane':f==='SPAM'?'fa-ban':f==='TRASH'?'fa-trash':'fa-box-archive'; }

  // Jednoduchý view-switcher: 'list' | 'read' | 'compose' | 'signatures'
  function setView(mode){
    document.querySelectorAll('#section-mail .view').forEach(v=>v.classList.remove('active'));
    const el = document.querySelector(`#section-mail #${mode}-view`);
    if (el) el.classList.add('active');
    // vyčisti TinyMCE pri prepnutí mimo compose/signatures editorov
    if (window.tinymce && mode !== 'compose' && mode !== 'signatures') {
      try { tinymce.remove(); } catch(_){}
      
    }
  }
try {
  const one = await apiRequest(`/api/mail/signatures/${id}`);
  if (one && one.item) initial = one.item;
} catch(_) {}

  // =================================================================
  // === INIT ========================================================
  // =================================================================
  window.initializeMailModule = function initializeMailModule(){
    const container = document.getElementById('section-mail');
    if(!container) return;

    // --- MARKUP (ľavý panel + pravý single-panel) ------------------
    container.innerHTML = `
      <h3><i class="fas fa-envelope"></i> Pošta</h3>

      <div class="mail-layout">
        <!-- ĽAVÝ PANEL -->
        <aside class="mail-aside">
          <div class="card" style="padding:.75rem;">
            <div class="btn-group-vertical" style="display:flex; gap:.5rem; margin-bottom:.75rem;">
              <button class="btn-primary"   id="btn-compose"><i class="fas fa-pen"></i> Nový e-mail</button>
              <button class="btn-secondary" id="btn-refresh"><i class="fas fa-rotate"></i> Obnoviť</button>
              <button class="btn-secondary" id="btn-sync"><i class="fas fa-cloud-arrow-down"></i> Synchronizovať</button>
              <button class="btn-secondary" id="btn-imap-test"><i class="fas fa-plug"></i> Test pripojenia</button>
              <button class="btn-secondary" id="btn-signatures"><i class="fas fa-signature"></i> Podpisy</button>
            </div>

            <div class="folder-list">
              <div class="folder-title">Priečinky</div>
              <ul id="folder-ul" style="list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:.25rem;">
                ${['INBOX','SENT','SPAM','TRASH','ARCHIVE'].map(f=>`
                  <li>
                    <a href="#" class="mail-folder-link" data-folder="${f}" style="display:flex; align-items:center; gap:.5rem;">
                      <i class="fas ${iconForFolder(f)}"></i> <span>${f}</span>
                      <span class="badge" data-badge-for="${f}" style="margin-left:auto;">0</span>
                    </a>
                  </li>`).join('')}
              </ul>
            </div>

            <div class="folder-list" style="margin-top:1rem;">
              <div class="folder-title">Zákazníci (Top)</div>
              <ul id="customer-ul" style="list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:.25rem;">
                <li style="color:#6b7280;">—</li>
              </ul>
            </div>
          </div>
        </aside>

        <!-- PRAVÁ JEDNOPANELOVÁ ČASŤ -->
        <section class="mail-main" id="mail-main">
          <div class="mail-toolbar">
            <input type="text" id="mail-search" placeholder="Hľadať v predmete/od/texte..." />
            <select id="mail-filter-customer" title="Filter zákazníka"><option value="">— zákazník —</option></select>
            <button class="btn-secondary" id="btn-search"><i class="fas fa-search"></i></button>
            <button class="btn-secondary" id="btn-clear"><i class="fas fa-xmark"></i></button>
          </div>

          <!-- VIEW: ZOZNAM -->
          <div id="list-view" class="view active">
            <div class="card">
              <table id="mail-table" class="table">
                <thead><tr><th>Predmet</th><th>Od</th><th>Čas</th><th style="width:36px;"></th></tr></thead>
                <tbody><tr><td colspan="4" style="padding:1rem;color:#6b7280;">Načítavam…</td></tr></tbody>
              </table>
              <div style="display:flex; justify-content:space-between; align-items:center; padding:.5rem;">
                <button class="btn-secondary" id="btn-prev">Predchádzajúca</button>
                <span id="mail-page-info">—</span>
                <button class="btn-secondary" id="btn-next">Ďalšia</button>
              </div>
            </div>
          </div>

          <!-- VIEW: DETAIL (reader) -->
          <div id="read-view" class="view">
            <div class="card">
              <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-bottom:1px solid #e5e7eb">
                <button class="btn-secondary" id="btn-back-list"><i class="fas fa-arrow-left"></i> Späť do zoznamu</button>
                <div id="reader-actions"></div>
              </div>
              <div id="reader-body" style="padding:12px;"></div>
            </div>
          </div>

          <!-- VIEW: COMPOSE -->
          <div id="compose-view" class="view">
            <div class="card" id="compose-card"></div>
          </div>

          <!-- VIEW: SIGNATURES -->
          <div id="signatures-view" class="view">
            <div class="card" id="signatures-card"></div>
          </div>
        </section>
      </div>
    `;

    const state   = { folder:'INBOX', page:1, pageSize:20, query:'', customerId:'' };
    const elTbody = container.querySelector('#mail-table tbody');
    const elInfo  = container.querySelector('#mail-page-info');

    // Delegovaný klik na riadok
    elTbody.addEventListener('click', (ev) => {
      const tr = ev.target.closest('tr[data-id]');
      if (!tr) return;
      ev.preventDefault();
      const id = Number(tr.dataset.id);
      if (id) loadDetail(id);
    });

    // ================= Súhrny (priečinky, top zákazníci) ==========
    async function loadSummary(){
      const s = await apiRequest('/api/mail/folders/summary');
      if (s && !s.error){
        const map = {};
        (s.folders||[]).forEach(f=>{ map[f.folder]=f; });
        ['INBOX','SENT','SPAM','TRASH','ARCHIVE'].forEach(f=>{
          const b = container.querySelector(`[data-badge-for="${f}"]`);
          if (b){
            const total  = map[f]?.total  || 0;
            const unread = map[f]?.unread || 0;
            b.textContent = unread>0 ? `${total} • ${unread}` : `${total}`;
          }
        });
        const ul = container.querySelector('#customer-ul');
        ul.innerHTML = '';
        const top = s.top_customers || [];
        if (top.length===0){
          ul.innerHTML = '<li style="color:#6b7280;">—</li>';
        } else {
          top.forEach(c=>{
            const li=document.createElement('li');
            li.innerHTML = `<a href="#" class="customer-link" data-customer="${c.customer_id}" style="display:flex; gap:.5rem;">
              <i class="fas fa-user-tag"></i> <span>${escapeHtml(c.customer_name||('ID '+c.customer_id))}</span>
              <span class="badge" style="margin-left:auto;">${c.total}${c.unread? ' • '+c.unread : ''}</span>
            </a>`;
            ul.appendChild(li);
          });
          ul.querySelectorAll('.customer-link').forEach(a=>{
            a.onclick=(ev)=>{ev.preventDefault(); state.customerId=a.dataset.customer; state.page=1; setView('list'); loadList(); };
          });
        }
      }
      // filter zákazník (full list)
      const cl = await apiRequest('/api/mail/customers');
      const sel = container.querySelector('#mail-filter-customer');
      if (cl && !cl.error && sel){
        const cur = sel.value;
        sel.innerHTML = '<option value="">— zákazník —</option>' + (cl.items||[]).map(c=>`<option value="${c.customer_id}">${escapeHtml(c.customer_name||('ID '+c.customer_id))}</option>`).join('');
        if (cur) sel.value = cur;
      }
    }

    // ================= Zoznam ==================
    function setLoadingList(on){
      if(on) elTbody.innerHTML=`<tr><td colspan="4" style="padding:1rem;color:#6b7280;">Načítavam…</td></tr>`;
    }
    function updatePager(total){
      const start = total===0 ? 0 : (state.page-1)*state.pageSize+1;
      const end   = Math.min(state.page*state.pageSize, total);
      elInfo.textContent = `${start}–${end} z ${total}`;
      container.querySelector('#btn-prev').disabled = state.page<=1;
      container.querySelector('#btn-next').disabled = end>=total;
    }
    async function loadList(){
      setView('list');
      setLoadingList(true);
      const params = new URLSearchParams({ folder: state.folder, page: state.page, page_size: state.pageSize });
      if (state.query && state.query.trim()) params.set('query', state.query.trim());
      if (state.customerId) params.set('customer_id', state.customerId);

      const res = await apiRequest('/api/mail/messages?'+params.toString());
      if (res && res.error){
        elTbody.innerHTML = `<tr><td colspan="4" class="text-danger" style="padding:1rem;">${escapeHtml(res.error)}</td></tr>`;
        updatePager(0);
        return;
      }
      const items = res.items || [];
      if (items.length===0){
        elTbody.innerHTML = `<tr><td colspan="4" style="padding:1rem;color:#6b7280;">Žiadne správy.</td></tr>`;
      } else {
        elTbody.innerHTML='';
        items.forEach(row=>{
          const tr=document.createElement('tr');
          tr.dataset.id = row.id;
          tr.innerHTML = `
            <td>${escapeHtml(row.subject||'(bez predmetu)')}</td>
            <td>${escapeHtml(row.from_email||'')}</td>
            <td>${escapeHtml(row.ts||'')}</td>
            <td style="text-align:center;">${row.has_attachments?'<i class="fas fa-paperclip" title="Príloha"></i>':''}</td>
          `;
          if (!row.is_read) tr.style.fontWeight = '600';
          elTbody.appendChild(tr);
        });
      }
      updatePager(Number(res.total||0));
      loadSummary();
    }

    // ================= Detail (reader) ================
    async function loadDetail(id){
      const r = await apiRequest(`/api/mail/messages/${id}`);
      if (r && r.error){ showStatus(r.error, true); return; }
      const d   = r.item || {};
      const toA = ensureArray(d.to_json);
      const ccA = ensureArray(d.cc_json);
      const toChips = toA.map(x=> `<span class="address">${escapeHtml(x.email)}</span>`).join(' ');
      const ccChips = ccA.map(x=> `<span class="address">${escapeHtml(x.email)}</span>`).join(' ');
      const attChips = (d.attachments||[]).map(a=>`
        <a class="chip" href="/api/mail/attachments/${a.id}" target="_blank" title="Stiahnuť prílohu">
          <i class="fas fa-paperclip"></i><span>${escapeHtml(a.filename)}</span>
          <span style="opacity:.7;">(${formatBytes(a.size_bytes)})</span>
        </a>
      `).join('');

      const readerBody = document.getElementById('reader-body');
      const readerActions = document.getElementById('reader-actions');
      readerActions.innerHTML = `
        <div style="display:flex; gap:.5rem; flex-wrap:wrap;">
          <button class="btn-secondary" id="btn-reply"><i class="fas fa-reply"></i> Odpovedať</button>
          <button class="btn-secondary" id="btn-archive"><i class="fas fa-box-archive"></i> Archív</button>
          <button class="btn-warning"  id="btn-spam"><i class="fas fa-ban"></i> Spam</button>
          <button class="btn-danger"   id="btn-delete"><i class="fas fa-trash"></i> Vymazať</button>
        </div>
      `;

      readerBody.innerHTML = `
        <div class="detail">
          <div class="detail-header">
            <h4 class="subject">${escapeHtml(d.subject || '(bez predmetu)')}</h4>
          </div>

          <div class="meta">
            <div class="k">Od</div><div class="v">${escapeHtml(d.from_name||'')} &lt;${escapeHtml(d.from_email||'')}&gt;</div>
            <div class="k">Komu</div><div class="v">${toChips || '—'}</div>
            ${ccChips ? `<div class="k">Kópia</div><div class="v">${ccChips}</div>` : ''}
            <div class="k">Dátum</div><div class="v">${escapeHtml(d.sent_at || d.received_at || d.created_at || '')}</div>
          </div>

          ${(d.attachments && d.attachments.length) ? `
            <div class="attachments">
              <b>Prílohy</b>
              <div class="att-list">${attChips}</div>
            </div>` : ''}

          <div class="body-wrap">
            <div class="body">
              ${d.body_html ? d.body_html : `<pre>${escapeHtml(d.body_text || '')}</pre>`}
            </div>
          </div>

          <div style="display:flex; gap:.5rem; align-items:center; flex-wrap:wrap; margin-top:6px;">
            <label>Priradiť zákazníkovi:</label>
            <select id="assign-customer"><option value="">— vyber —</option></select>
            <button class="btn-secondary" id="btn-assign">Priradiť</button>
            <button class="btn-secondary" id="btn-map-domain">Mapovať doménu</button>
          </div>
        </div>
      `;

      // prepni na reader
      setView('read');

      // označiť ako prečítané
      await apiRequest(`/api/mail/messages/${id}/mark_read`, { method:'POST', body:{ read:true } });

      // back
      document.getElementById('btn-back-list').onclick = ()=> setView('list');

      // akcie
      const closeToList = ()=> setView('list');
      readerActions.querySelector('#btn-delete').onclick  = async ()=>{ await apiRequest(`/api/mail/messages/${id}`, { method:'DELETE' }); showStatus('Presunuté do Koša.'); closeToList(); loadList(); };
      readerActions.querySelector('#btn-spam').onclick    = async ()=>{ await apiRequest(`/api/mail/messages/${id}/move`, { method:'POST', body:{ folder:'SPAM' } }); showStatus('Presunuté do SPAM.'); closeToList(); loadList(); };
      readerActions.querySelector('#btn-archive').onclick = async ()=>{ await apiRequest(`/api/mail/messages/${id}/move`, { method:'POST', body:{ folder:'ARCHIVE' } }); showStatus('Presunuté do ARCHIVE.'); closeToList(); loadList(); };
      readerActions.querySelector('#btn-reply').onclick   = ()=> openComposeView(`Re: ${d.subject||''}`, d.from_email, d);

      // zákazníci
      const cl = await apiRequest('/api/mail/customers');
      const sel = readerBody.querySelector('#assign-customer');
      if (cl && !cl.error){
        sel.innerHTML = '<option value="">— vyber —</option>' + (cl.items||[]).map(c=>`<option value="${c.customer_id}">${escapeHtml(c.customer_name||('ID '+c.customer_id))}</option>`).join('');
      }
      readerBody.querySelector('#btn-assign').onclick = async ()=>{
        const cid = sel.value; if (!cid) return;
        const rr = await apiRequest(`/api/mail/messages/${id}/assign_customer`, { method:'POST', body:{ customer_id: cid } });
        if (rr && rr.error) return showStatus(rr.error, true);
        showStatus('Priradené.'); loadSummary();
      };
      readerBody.querySelector('#btn-map-domain').onclick = async ()=>{
        const fe = (d.from_email||'').trim(); if (!fe || !fe.includes('@')) return showStatus('Neznámy odosielateľ.', true);
        const dom = fe.split('@').pop();
        const cid = sel.value; if (!cid) return showStatus('Vyber zákazníka v selecte.', true);
        const name = sel.options[sel.selectedIndex].textContent;
        const rr = await apiRequest('/api/mail/contact_links', { method:'POST', body:{ email: fe, customer_id: cid, customer_name: name, domain: dom }});
        if (rr && rr.error) return showStatus(rr.error, true);
        showStatus('Mapovanie uložené.');
      };
    }

    // ================= Compose (vlastný view) ======================
    async function openComposeView(subjectPrefill='', toPrefill='', replied=null){
      const card = document.getElementById('compose-card');

      // podpisy
      const sigs = await apiRequest('/api/mail/signatures');
      const def  = await apiRequest('/api/mail/signatures/default');
      const signatureOptions = (sigs.items||[]).map(s=>`<option value="${s.id}" ${def.item && def.item.id===s.id?'selected':''}>${escapeHtml(s.name)}</option>`).join('');

      const quoted = replied ? (
        `<br><br><div style="border-left:3px solid #ddd; padding-left:.75rem; color:#555;">
          <div>----- Pôvodná správa -----</div>
          <div><b>Od:</b> ${escapeHtml(replied.from_email||'')}</div>
          <div><b>Dátum:</b> ${escapeHtml(replied.received_at || replied.sent_at || '')}</div>
          <div><b>Predmet:</b> ${escapeHtml(replied.subject||'')}</div>
          <div>${escapeHtml(replied.body_text||'').replace(/\n/g,'<br>')}</div>
        </div>`
      ) : '';

      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-bottom:1px solid #e5e7eb">
          <button class="btn-secondary" id="btn-back-from-compose"><i class="fas fa-arrow-left"></i> Späť do zoznamu</button>
          <div style="display:flex;gap:.5rem;">
            <button class="btn-secondary" id="btn-cancel-compose">Zavrieť</button>
            <button class="btn-primary"  id="btn-send-compose"><i class="fas fa-paper-plane"></i> Odoslať</button>
          </div>
        </div>

        <div class="card-body">
          <div class="form-grid mail-compose-grid">
            <label style="align-self:center;">Komu</label>
            <input type="text" id="compose-to" value="${escapeHtml(toPrefill||'')}" placeholder="email1@example.com, email2@example.com">

            <label style="align-self:center;">Kópia (CC)</label>
            <input type="text" id="compose-cc">

            <label style="align-self:center;">Skrytá kópia (BCC)</label>
            <input type="text" id="compose-bcc">

            <label style="align-self:center;">Predmet</label>
            <input type="text" id="compose-subject" value="${escapeHtml(subjectPrefill)}">

            <label style="align-self:center;">Podpis</label>
            <select id="compose-signature">
              <option value="">(bez podpisu)</option>
              ${signatureOptions}
            </select>
          </div>

          <div class="form-group" style="margin-top:.5rem;">
            <textarea id="compose-body-html"></textarea>
          </div>

          <div class="form-group">
            <label>Prílohy</label>
            <input type="file" id="compose-files" multiple>
          </div>
        </div>
      `;

      setView('compose');

      // TinyMCE
      try {
        if (window.tinymce) {
          try { tinymce.remove('#compose-body-html'); } catch(_){}
          tinymce.init({
            selector: '#compose-body-html',
            menubar: false,
            height: 360,
            plugins: 'link lists',
            toolbar: 'undo redo | fontfamily fontsize | bold italic underline | forecolor backcolor | alignleft aligncenter alignright | bullist numlist | link removeformat',
            branding: false,
            setup: (ed)=>{ ed.on('init', ()=>{ ed.setContent(quoted || ''); }); }
          });
        } else {
          const ta = document.getElementById('compose-body-html');
          ta.value = replied ? `\n\n----- Pôvodná správa -----\nOd: ${replied.from_email||''}\nDátum: ${replied.received_at||replied.sent_at||''}\nPredmet: ${replied.subject||''}\n\n${replied.body_text||''}` : '';
        }
      } catch (e) { console.warn('TinyMCE init error', e); }

      // Handlery
      document.getElementById('btn-back-from-compose').onclick = ()=> setView('list');
      document.getElementById('btn-cancel-compose').onclick    = ()=> setView('list');

      document.getElementById('btn-send-compose').onclick = async ()=>{
        const fd = new FormData();
        fd.append('to', document.getElementById('compose-to').value);
        fd.append('cc', document.getElementById('compose-cc').value);
        fd.append('bcc', document.getElementById('compose-bcc').value);
        fd.append('subject', document.getElementById('compose-subject').value);

        if (window.tinymce && tinymce.get('compose-body-html')) {
          fd.append('body_html', tinymce.get('compose-body-html').getContent());
        } else {
          fd.append('body_text', document.getElementById('compose-body-html').value);
        }

        const sigSel = document.getElementById('compose-signature');
        if (sigSel && sigSel.value) fd.append('signature_id', sigSel.value);

        const files = document.getElementById('compose-files').files;
        for (let i=0;i<files.length;i++) fd.append(`file${i+1}`, files[i]);

        const r = await fetch('/api/mail/send', { method:'POST', body:fd, credentials:'same-origin' });
        const j = await r.json().catch(()=>({error:'Nepodarilo sa prečítať odpoveď'}));
        if (!r.ok || j.error) return showStatus(j.error || r.statusText, true);
        showStatus('E-mail odoslaný.');
        state.folder = 'SENT'; state.page=1;
        setView('list'); loadList();
      };
    }

    // ================= Signatures (vlastný view) ===================
    async function openSignaturesManager(){
      const wrap = document.getElementById('signatures-card');
      const list = await apiRequest('/api/mail/signatures');
      const def  = await apiRequest('/api/mail/signatures/default');
      const items = list.items || [];

      wrap.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; border-bottom:1px solid #e5e7eb;">
          <button class="btn-secondary" id="btn-back-from-sign"><i class="fas fa-arrow-left"></i> Späť do zoznamu</button>
          <button class="btn-secondary" id="btn-new-signature"><i class="fas fa-plus"></i> Nový podpis</button>
        </div>

        <div class="card-body">
          ${items.length===0 ? '<div style="color:#6b7280;">Žiadne podpisy.</div>' : `
            <table class="table">
              <thead><tr><th>Názov</th><th>Default</th><th style="width:260px;"></th></tr></thead>
              <tbody>
                ${items.map(s=>`
                  <tr data-id="${s.id}">
                    <td>${escapeHtml(s.name)}</td>
                    <td>${s.is_default ? 'Áno' : 'Nie'}</td>
                    <td style="display:flex; gap:.5rem; flex-wrap:wrap;">
                      <button class="btn-secondary btn-edit">Upraviť</button>
                      <button class="btn-secondary btn-set-default"${s.is_default?' disabled':''}>Nastaviť ako default</button>
                      <button class="btn-danger btn-del">Zmazať</button>
                    </td>
                  </tr>`).join('')}
              </tbody>
            </table>
          `}

          <div id="signature-editor" class="card" style="display:none; margin-top:.75rem; padding:.75rem;">
            <h5 id="sig-title" style="margin:.25rem 0 1rem 0;">Nový podpis</h5>
            <div class="form-group"><label>Názov</label><input type="text" id="sig-name"></div>
            <div class="form-group"><label>Obsah</label><textarea id="sig-html"></textarea></div>
            <div style="display:flex; gap:.5rem; justify-content:flex-end;">
              <button class="btn-secondary" id="sig-cancel">Zrušiť</button>
              <button class="btn-primary"  id="sig-save">Uložiť</button>
            </div>
          </div>
        </div>
      `;

      setView('signatures');

      document.getElementById('btn-back-from-sign').onclick = ()=> setView('list');

      // set default
      wrap.querySelectorAll('.btn-set-default').forEach(btn=>{
        btn.onclick = async ()=>{
          const tr = btn.closest('tr'); const id = Number(tr.dataset.id);
          const name = tr.children[0].textContent;
          const res = await apiRequest(`/api/mail/signatures/${id}`, { method:'PUT', body:{ name, is_default:true }});
          if (res && res.error){ showStatus('Nastavenie defaultu zlyhalo. Otvor editor a ulož s „default“.', true); return; }
          showStatus('Nastavené ako default.'); openSignaturesManager();
        };
      });

      // delete
      wrap.querySelectorAll('.btn-del').forEach(btn=>{
        btn.onclick = async ()=>{
          const tr = btn.closest('tr'); const id = Number(tr.dataset.id);
          await apiRequest(`/api/mail/signatures/${id}`, { method:'DELETE' });
          showStatus('Zmazané.'); openSignaturesManager();
        };
      });

      // new/edit
      document.getElementById('btn-new-signature').onclick = ()=> showSigEditor(null,'','');
      wrap.querySelectorAll('.btn-edit').forEach(btn=>{
        btn.onclick = async ()=>{
          const tr = btn.closest('tr'); const id = tr.dataset.id;
          let initial = { name: tr.children[0].textContent, html: '' };
          try {
            const one = await apiRequest(`/api/mail/signatures/${id}`);
            if (one && one.item) initial = one.item;
          } catch(_) {}
          showSigEditor(id, initial.name || '', initial.html || '');
        };
      });

      function showSigEditor(id, name, html){
        const ed = document.getElementById('signature-editor');
        ed.style.display='block';
        document.getElementById('sig-title').textContent = id? 'Upraviť podpis' : 'Nový podpis';
        document.getElementById('sig-name').value = name || '';
        try { if (window.tinymce && tinymce.get('sig-html')) tinymce.remove('#sig-html'); } catch(_){}
        const ta = document.getElementById('sig-html'); ta.value = html || '';
        if (window.tinymce){
          tinymce.init({
            selector:'#sig-html', menubar:false, height:220, plugins:'link lists',
            toolbar:'undo redo | bold italic underline | forecolor | alignleft aligncenter alignright | bullist numlist | link removeformat',
            branding:false
          });
        }
        document.getElementById('sig-cancel').onclick = ()=>{ ed.style.display='none'; try{ if(window.tinymce) tinymce.remove('#sig-html'); }catch(_){ } };
        document.getElementById('sig-save').onclick = async ()=>{
          const nm = document.getElementById('sig-name').value.trim();
          const ht = (window.tinymce && tinymce.get('sig-html')) ? tinymce.get('sig-html').getContent() : document.getElementById('sig-html').value;
          if (!nm) return showStatus('Zadaj názov podpisu.', true);
          if (id){
            await apiRequest(`/api/mail/signatures/${id}`, { method:'PUT', body:{ name: nm, html: ht }});
          } else {
            await apiRequest('/api/mail/signatures', { method:'POST', body:{ name: nm, html: ht }});
          }
          showStatus('Uložené.'); openSignaturesManager();
        };
      }
    }

    // ================= Handlery toolbar & sidebar ==================
    container.querySelector('#btn-compose').onclick     = ()=> openComposeView();
    container.querySelector('#btn-refresh').onclick     = ()=> loadList();
    container.querySelector('#btn-sync').onclick        = async ()=>{ const r=await apiRequest('/api/mail/imap/fetch?limit=50',{method:'POST'}); if(r&&r.error)return showStatus('Sync zlyhal: '+r.error,true); showStatus(`Načítaných ${r.fetched||0}, preskočených ${r.skipped||0}.`); loadList(); };
    container.querySelector('#btn-imap-test').onclick   = async ()=>{ const r=await apiRequest('/api/mail/imap/test'); showStatus(r&&r.message?r.message:'IMAP OK'); };
    container.querySelector('#btn-signatures').onclick  = ()=> openSignaturesManager();

    container.querySelectorAll('.mail-folder-link').forEach(a=>{
      a.onclick=(ev)=>{
        ev.preventDefault();
        container.querySelectorAll('.mail-folder-link').forEach(x=>x.classList.remove('active'));
        a.classList.add('active');
        state.folder=a.dataset.folder; state.page=1; state.customerId='';
        setView('list'); loadList();
      };
    });

    container.querySelector('#btn-prev').onclick = ()=>{ if(state.page>1){ state.page--; loadList(); } };
    container.querySelector('#btn-next').onclick = ()=>{ state.page++; loadList(); };
    container.querySelector('#btn-search').onclick = ()=>{ state.query = container.querySelector('#mail-search').value.trim(); state.page=1; loadList(); };
    container.querySelector('#btn-clear').onclick  = ()=>{ state.query=''; state.customerId=''; container.querySelector('#mail-search').value=''; container.querySelector('#mail-filter-customer').value=''; state.page=1; loadList(); };
    container.querySelector('#mail-filter-customer').onchange = (e)=>{ state.customerId = e.target.value; state.page=1; loadList(); };

    // štart
    loadSummary();
    loadList();
  };
})();
