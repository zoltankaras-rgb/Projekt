// static/js/kancelaria_modules/gemini_tasks.js
(function(){
  'use strict';

  // malý helper
  async function apiP(url, opts){ return (typeof window.apiRequest==='function')
    ? window.apiRequest(url, opts||{})
    : fetch(url, { method:(opts&&opts.method)||'POST', headers:{'Content-Type':'application/json'},
                   credentials:'include', body: JSON.stringify((opts&&opts.body)||{}) }).then(r=>r.json()); }

  function el(html){ const d=document.createElement('div'); d.innerHTML=html.trim(); return d.firstElementChild; }
  function esc(s){ return String(s==null?'':s); }

  function cronHelpHTML(){
    return `
    <details class="cron-help"><summary>Pomocník k CRONu</summary>
      <div class="help-body">
        <ul>
          <li><code>0 14 * * *</code> – každý deň o 14:00</li>
          <li><code>0 8 * * 1</code> – každý pondelok 08:00</li>
          <li><code>0 */2 * * *</code> – každé 2 hodiny</li>
          <li><code>*/15 * * * *</code> – každých 15 minút</li>
        </ul>
      </div>
    </details>`;
  }

  function renderShell(root){
    root.innerHTML = `
      <h3>Asistent Gemini – plánované úlohy</h3>

      <div class="card" style="margin-bottom:1rem;">
        <div class="card-header">
          <div><strong>Nová / upraviť úlohu</strong></div>
        </div>
        <div class="card-body">
          <form id="gtask-form" class="form-grid" style="grid-template-columns:1fr 1fr;">
            <input type="hidden" id="gtask-id">
            <div class="form-group">
              <label>Názov úlohy</label>
              <input type="text" id="gtask-name" placeholder="napr. Denná kontrola skladu" required>
            </div>
            <div class="form-group">
              <label>CRON (čas spúšťania)</label>
              <input type="text" id="gtask-cron" placeholder="napr. 0 14 * * *" required>
              ${cronHelpHTML()}
            </div>
            <div class="form-group" style="grid-column:1/-1;">
              <label>Popis úlohy pre AI</label>
              <textarea id="gtask-desc" rows="3" placeholder="Čo má AI urobiť s dátami (napr. pripraviť e-mail pre nákup)..."></textarea>
            </div>
            <div class="form-group">
              <label>E-mail adresáta</label>
              <input type="email" id="gtask-email" placeholder="napr. nakup@firma.sk">
            </div>
            <div class="form-group">
              <label>SQL SELECT (voliteľné)</label>
              <textarea id="gtask-sql" rows="3" placeholder="SELECT ..."></textarea>
            </div>
            <div class="form-group">
              <label>Aktívna</label>
              <select id="gtask-enabled">
                <option value="1">Áno</option>
                <option value="0">Nie</option>
              </select>
            </div>
          </form>
          <div style="display:flex; gap:.5rem; margin-top:.5rem;">
            <button id="gtask-save" class="btn btn-success"><i class="fas fa-save"></i> Uložiť</button>
            <button id="gtask-reset" class="btn btn-secondary">Vyčistiť formulár</button>
          </div>
          <div id="gtask-msg" style="margin-top:.5rem;"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><strong>Zoznam úloh</strong></div>
        <div class="card-body">
          <div id="gtask-table-wrap" class="table-container"></div>
        </div>
      </div>
    `;
  }

  function tableHTML(rows){
    if (!rows || !rows.length){
      return `<p>Žiadne úlohy. Vytvor novú vyššie.</p>`;
    }
    const trs = rows.map(r => {
      const enabled = Number(r.is_enabled) ? 'Áno' : 'Nie';
      return `
        <tr data-id="${r.id}">
          <td>${r.id}</td>
          <td>${esc(r.nazov_ulohy||'')}</td>
          <td><code>${esc(r.cron_retazec||'')}</code></td>
          <td>${esc(r.email_adresata||'')}</td>
          <td>${esc((r.popis_ulohy_pre_ai||'').slice(0,80))}${(r.popis_ulohy_pre_ai||'').length>80?'…':''}</td>
          <td>${enabled}</td>
          <td style="white-space:nowrap;">
            <button class="btn btn-secondary btn-xs act-edit"><i class="fas fa-edit"></i></button>
            <button class="btn btn-warning btn-xs act-toggle"><i class="fas fa-power-off"></i></button>
            <button class="btn btn-info btn-xs act-run"><i class="fas fa-play"></i></button>
            <button class="btn btn-danger btn-xs act-del"><i class="fas fa-trash"></i></button>
          </td>
        </tr>`;
    }).join('');
    return `
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Názov</th><th>CRON</th><th>E-mail</th><th>Popis</th><th>Aktívna</th><th>Akcie</th>
          </tr>
        </thead>
        <tbody>${trs}</tbody>
      </table>
      <div class="b2c-row-meta" style="margin-top:.5rem;">Pozn.: Plánovač načítava zmeny každých 5 minút (alebo po reštarte <code>scheduler.py</code>).</div>
    `;
  }

  async function loadTasks(){
    const data = await apiP('/api/gemini/tasks/list', {method:'POST', body:{}});
    const wrap = document.getElementById('gtask-table-wrap');
    wrap.innerHTML = tableHTML(data && data.items || []);
    // bind akcií
    wrap.querySelectorAll('.act-edit').forEach(btn=>{
      btn.onclick = (e)=>{
        const tr = e.currentTarget.closest('tr'); const id = tr.dataset.id;
        const row = (data.items||[]).find(x => String(x.id)===String(id));
        if (!row) return;
        fillForm(row);
        window.scrollTo({top:0, behavior:'smooth'});
      };
    });
    wrap.querySelectorAll('.act-toggle').forEach(btn=>{
      btn.onclick = async (e)=>{
        const tr = e.currentTarget.closest('tr'); const id = tr.dataset.id;
        await apiP('/api/gemini/tasks/save', {method:'POST', body:{ id, is_enabled: e.currentTarget.closest('tr').children[5].innerText==='Áno'?0:1 }});
        loadTasks();
      };
    });
    wrap.querySelectorAll('.act-run').forEach(btn=>{
      btn.onclick = async (e)=>{
        const tr = e.currentTarget.closest('tr'); const id = tr.dataset.id;
        const res = await apiP('/api/gemini/tasks/run', {method:'POST', body:{ id }});
        alert( (res&&res.message) || 'Úloha spustená.' );
      };
    });
    wrap.querySelectorAll('.act-del').forEach(btn=>{
      btn.onclick = async (e)=>{
        const tr = e.currentTarget.closest('tr'); const id = tr.dataset.id;
        if (!confirm('Naozaj vymazať túto úlohu?')) return;
        await apiP('/api/gemini/tasks/delete', {method:'POST', body:{ id }});
        loadTasks();
      };
    });
  }

  function fillForm(row){
    document.getElementById('gtask-id').value = row.id || '';
    document.getElementById('gtask-name').value = row.nazov_ulohy || '';
    document.getElementById('gtask-desc').value = row.popis_ulohy_pre_ai || '';
    document.getElementById('gtask-cron').value = row.cron_retazec || '';
    document.getElementById('gtask-email').value = row.email_adresata || '';
    document.getElementById('gtask-sql').value = row.sql_text || '';
    document.getElementById('gtask-enabled').value = String(row.is_enabled ? 1 : 0);
  }

  async function saveForm(){
    const body = {
      id: document.getElementById('gtask-id').value || null,
      nazov_ulohy: document.getElementById('gtask-name').value,
      popis_ulohy_pre_ai: document.getElementById('gtask-desc').value,
      cron_retazec: document.getElementById('gtask-cron').value,
      email_adresata: document.getElementById('gtask-email').value,
      sql_text: document.getElementById('gtask-sql').value,
      is_enabled: Number(document.getElementById('gtask-enabled').value||1)
    };
    // voliteľná validácia CRONu
    const v = await apiP('/api/gemini/tasks/validate_cron',{method:'POST', body:{ cron: body.cron_retazec }});
    if (v && v.valid === false){
      document.getElementById('gtask-msg').innerHTML = `<p class="text-danger">Neplatný CRON: ${esc(v.error||'')}</p>`;
      return;
    }
    await apiP('/api/gemini/tasks/save', {method:'POST', body});
    document.getElementById('gtask-msg').innerHTML = `<p class="text-success">Úloha uložená.</p>`;
    // reset a reload
    document.getElementById('gtask-form').reset();
    document.getElementById('gtask-id').value = '';
    loadTasks();
  }

  function init(root){
    renderShell(root);
    document.getElementById('gtask-save').onclick = saveForm;
    document.getElementById('gtask-reset').onclick = ()=>{
      document.getElementById('gtask-form').reset();
      document.getElementById('gtask-id').value = '';
      document.getElementById('gtask-msg').innerHTML = '';
    };
    loadTasks();
  }

  // auto-inicializácia, keď je sekcia prítomná
  const section = document.getElementById('section-gemini-assistant');
  if (section) init(section);

})();
