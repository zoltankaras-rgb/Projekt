// static/js/task_planner.js
document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  /* ------------------- API wrapper ------------------- */
  function apiReq(url, opts) {
    if (typeof window.apiRequest === 'function') return window.apiRequest(url, opts || {});
    opts = opts || {};
    const body = opts.body ? JSON.stringify(opts.body) : undefined;
    return fetch(url, {
      method: opts.method || 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body
    }).then(async (r) => {
      let json = null;
      try { json = await r.json(); } catch (_) {}
      if (!r.ok) throw new Error(json && (json.message || json.error) || `HTTP ${r.status}`);
      return json;
    });
  }

  /* ------------------- UI helpers ------------------- */
  function h(tag, props={}, children=[]) {
    const e = document.createElement(tag);
    Object.entries(props).forEach(([k,v]) => {
      if (k === 'class') e.className = v;
      else if (k === 'html') e.innerHTML = v;
      else if (k === 'text') e.textContent = v;
      else e.setAttribute(k, v);
    });
    (Array.isArray(children) ? children : [children]).forEach(c => c && e.appendChild(c));
    return e;
  }
  function toast(msg, type){
    const n = h('div',{class:`pln-toast ${type||'info'}`, text:String(msg||'')});
    document.body.appendChild(n);
    setTimeout(() => { n.classList.add('show'); }, 10);
    setTimeout(() => { n.classList.remove('show'); setTimeout(()=>n.remove(), 300); }, 3000);
  }
  const info=(m)=>toast(m,'info'), ok=(m)=>toast(m,'ok'), err=(m)=>toast(m,'err');

  /* ------------------- Styles ------------------- */
  const css = `
  #planner-fab {
    position: fixed; right: 20px; bottom: 84px; z-index: 10000;
    display:flex; align-items:center; gap:.5rem; padding:.6rem .9rem;
    background:#10b981; color:#fff; border:0; border-radius:9999px;
    cursor:pointer; font-weight:600; box-shadow:0 8px 24px rgba(0,0,0,.18);
  }
  #planner-panel {
    position: fixed; right: 20px; bottom: 84px; z-index: 10000;
    width: 460px; max-height: 80vh; display:none; flex-direction:column;
    background:#fff; border:1px solid #e5e7eb; border-radius:12px; overflow:hidden;
    box-shadow:0 12px 28px rgba(0,0,0,.18);
  }
  #pln-head { padding:.6rem .8rem; background:#f8fafc; border-bottom:1px solid #eee; font-weight:700; display:flex; align-items:center; justify-content:space-between; }
  #pln-body { padding:.75rem; overflow:auto; }
  #pln-body .row{ display:flex; gap:.5rem; margin:.5rem 0; }
  #pln-body label{ font-size:12px; color:#334155; display:block; margin-bottom:.2rem; }
  #pln-body input[type="text"], #pln-body input[type="email"], #pln-body input[type="time"], #pln-body input[type="number"], #pln-body select, #pln-body textarea {
    width:100%; padding:.45rem .55rem; border:1px solid #e5e7eb; border-radius:8px; font-size:13px;
  }
  #pln-body textarea{ min-height:84px; resize:vertical; }
  #pln-actions { display:flex; gap:.5rem; padding:.6rem .8rem; border-top:1px solid #eee; background:#fafafa; }
  .pln-btn { background:#2563eb; color:#fff; border:0; border-radius:10px; padding:.5rem .7rem; cursor:pointer; font-weight:600; }
  .pln-btn.secondary { background:#e2e8f0; color:#111827; }
  .pln-btn[disabled]{ opacity:.6; cursor:not-allowed; }
  #pln-preview { margin-top:.75rem; border-top:1px dashed #e5e7eb; padding-top:.75rem; }
  #pln-preview .sql details summary { cursor:pointer; font-weight:600; }
  #pln-preview .sql pre { background:#0b1020; color:#e5e7eb; padding:.5rem .7rem; border-radius:8px; overflow:auto; }
  .pln-badge { font-size:12px; padding:.15rem .4rem; border-radius:9999px; background:#ecfeff; color:#0369a1; border:1px solid #bae6fd; }
  .pln-toast {
    position: fixed; right: 20px; bottom: 20px; transform: translateY(12px);
    background:#111827; color:#fff; padding:.5rem .7rem; border-radius:8px; opacity:0; transition:.2s; z-index:10001;
  }
  .pln-toast.show { opacity:1; transform:translateY(0); }
  .pln-toast.ok { background:#16a34a; } .pln-toast.err { background:#dc2626; } .pln-toast.info { background:#111827; }
  `;
  document.head.appendChild(h('style',{text:css}));

  /* ------------------- Build UI ------------------- */
  if (document.getElementById('planner-fab')) return;

  const fab = h('button', {id:'planner-fab', text:'📅 Plánovač'});
  document.body.appendChild(fab);

  const panel = h('div', {id:'planner-panel', html: `
    <div id="pln-head">
      <div>Plánovač reportov (AI ➜ mail) <span id="pln-state" class="pln-badge" style="display:none"></span></div>
      <div style="display:flex; gap:.4rem;">
        <button id="pln-new-btn" class="pln-btn secondary">Nová úloha</button>
        <button id="pln-close" class="pln-btn secondary">Zavrieť</button>
      </div>
    </div>
    <div id="pln-body">
      <div class="row">
        <div style="flex:2">
          <label>Názov úlohy</label>
          <input type="text" id="pln-name" placeholder="napr. Denný report teplôt – rozrábka">
        </div>
        <div style="flex:1">
          <label>Mail príjemcu</label>
          <input type="email" id="pln-email" placeholder="miksro@slovanet.sk">
        </div>
      </div>

      <div class="row">
        <div style="flex:1">
          <label>Textová požiadavka (prirodzený jazyk)</label>
          <textarea id="pln-question" placeholder="napr. Aká bola najvyššia teplota dnes v rozrábke?"></textarea>
        </div>
      </div>

      <div class="row">
        <div style="flex:1">
          <label>Rozvrh spúšťania</label>
          <select id="pln-schedule">
            <option value="every_5m">Každých 5 minút</option>
            <option value="every_30m">Každých 30 minút</option>
            <option value="daily">Denne v čase</option>
            <option value="weekly">Týždenne (deň + čas)</option>
            <option value="monthly">Mesačne (deň v mesiaci + čas)</option>
            <option value="custom_cron">Vlastný CRON</option>
          </select>
        </div>
        <div style="flex:1" id="pln-field-time-wrap">
          <label>Čas (HH:MM)</label>
          <input type="time" id="pln-time" value="07:30">
        </div>
        <div style="flex:1; display:none" id="pln-field-dow-wrap">
          <label>Deň v týždni</label>
          <select id="pln-dow">
            <option value="1">Pondelok</option>
            <option value="2">Utorok</option>
            <option value="3">Streda</option>
            <option value="4">Štvrtok</option>
            <option value="5">Piatok</option>
            <option value="6">Sobota</option>
            <option value="0">Nedeľa</option>
          </select>
        </div>
        <div style="flex:1; display:none" id="pln-field-dom-wrap">
          <label>Deň v mesiaci</label>
          <input type="number" id="pln-dom" min="1" max="31" value="1">
        </div>
        <div style="flex:1; display:none" id="pln-field-cron-wrap">
          <label>CRON výraz</label>
          <input type="text" id="pln-cron" placeholder="m h dom mon dow (napr. 0 7 * * 1)">
        </div>
      </div>

      <div class="row" style="align-items:center">
        <label style="display:flex; gap:.5rem; align-items:center;">
          <input type="checkbox" id="pln-autorun" checked>
          <span>Po uložení <b>hneď spustiť</b> a poslať skúšobný mail</span>
        </label>
      </div>

      <div id="pln-preview">
        <div id="pln-preview-note" style="color:#475569; font-size:12px; margin-bottom:.4rem">Náhľad: najprv klikni na „Náhľad“ – uvidíš vetu + tabuľku + interné SQL.</div>
        <div id="pln-preview-html"></div>
      </div>
    </div>
    <div id="pln-actions">
      <button id="pln-preview-btn" class="pln-btn">Náhľad</button>
      <button id="pln-save-btn" class="pln-btn">Uložiť plán</button>
      <button id="pln-run-btn" class="pln-btn secondary" disabled>Spustiť teraz</button>
    </div>
  `});
  document.body.appendChild(panel);

  /* ------------------- Position ------------------- */
  const lock = () => {
    panel.style.setProperty('position','fixed','important');
    panel.style.setProperty('right','20px','important');
    panel.style.setProperty('bottom','84px','important');
    fab.style.setProperty('position','fixed','important');
    fab.style.setProperty('right','20px','important');
    fab.style.setProperty('bottom','84px','important');
  };
  lock(); window.addEventListener('resize', lock); window.addEventListener('scroll', lock);

  /* ------------------- State ------------------- */
  let savedTaskId = null;
  let savedSnapshot = null;

  const $ = (id)=>document.getElementById(id);
  const inputs = ['pln-name','pln-email','pln-question','pln-schedule','pln-time','pln-dow','pln-dom','pln-cron','pln-autorun'];

  function snapshot() {
    return JSON.stringify({
      name: $('pln-name').value.trim(),
      email: $('pln-email').value.trim(),
      question: $('pln-question').value.trim(),
      schedule: $('pln-schedule').value,
      time: $('pln-time').value,
      dow: $('pln-dow').value,
      dom: $('pln-dom').value,
      cron: $('pln-cron').value,
      autorun: $('pln-autorun').checked,
    });
  }
  function setRunEnabled(on){ const b=$('pln-run-btn'); on ? b.removeAttribute('disabled') : b.setAttribute('disabled','true'); }
  function setSaveEnabled(on){ const b=$('pln-save-btn'); on ? b.removeAttribute('disabled') : b.setAttribute('disabled','true'); }
  function setStateBadge(text){ const b=$('pln-state'); if (!text){ b.style.display='none'; b.textContent=''; } else { b.style.display='inline-block'; b.textContent=text; } }

  function updateScheduleFields() {
    const kind = $('pln-schedule').value;
    $('pln-field-time-wrap').style.display = (kind === 'daily' || kind === 'weekly' || kind === 'monthly') ? 'block' : 'none';
    $('pln-field-dow-wrap').style.display  = (kind === 'weekly') ? 'block' : 'none';
    $('pln-field-dom-wrap').style.display  = (kind === 'monthly') ? 'block' : 'none';
    $('pln-field-cron-wrap').style.display = (kind === 'custom_cron') ? 'block' : 'none';
  }

  function markDirty() {
    setStateBadge('Neuložené zmeny');
    setSaveEnabled(true);
  }

  // re-enable Save pri akejkoľvek zmene
  inputs.forEach(id => {
    const el = $(id);
    if (!el) return;
    el.addEventListener('input', markDirty);
    el.addEventListener('change', markDirty);
  });

  /* ------------------- Handlers ------------------- */
  $('pln-schedule').addEventListener('change', updateScheduleFields);
  $('pln-close').onclick = () => { panel.style.display = 'none'; };
  $('pln-new-btn').onclick = () => {
    ['pln-name','pln-email','pln-question','pln-cron'].forEach(id => $(id).value = '');
    $('pln-schedule').value = 'every_5m';
    $('pln-time').value = '07:30'; $('pln-dow').value = '1'; $('pln-dom').value = '1';
    $('pln-autorun').checked = true;
    $('pln-preview-html').innerHTML = '';
    setRunEnabled(false); setSaveEnabled(true); setStateBadge('Nová úloha');
    updateScheduleFields();
    savedTaskId = null; savedSnapshot = null;
  };
  fab.onclick = () => {
    panel.style.display = (panel.style.display === 'flex' ? 'none' : 'flex');
    if (panel.style.display === 'flex') { updateScheduleFields(); }
  };

  // Náhľad
  $('pln-preview-btn').onclick = async () => {
    const question = ($('pln-question').value || '').trim();
    if (!question) return err('Zadaj textovú požiadavku.');
    setRunEnabled(false);
    const btn = $('pln-preview-btn'); btn.setAttribute('disabled','true');
    try {
      const res = await apiReq('/api/tasks/preview_nl', { method:'POST', body:{ question }});
      const pv = res.preview || {};
      const usedSql = (pv.used_sql || '').replace(/[&<>]/g, s=>({ '&':'&amp;','<':'&lt;','>':'&gt;' }[s]));
      const sqlBlock = `<div class="sql" style="margin-top:.6rem"><details><summary>SQL</summary><pre>${usedSql}</pre></details></div>`;
      $('pln-preview-html').innerHTML = (pv.answer_html || '') + sqlBlock;
      ok(`Náhľad hotový (riadkov: ${pv.row_count ?? 0}).`);
    } catch(e) { err(e.message || e); }
    finally { btn.removeAttribute('disabled'); }
  };

  // Uložiť plán
  $('pln-save-btn').onclick = async () => {
    const name     = ($('pln-name').value || '').trim();
    const email    = ($('pln-email').value || '').trim();
    const question = ($('pln-question').value || '').trim();
    const schedule = $('pln-schedule').value;
    const time     = $('pln-time').value || undefined;
    const dow      = $('pln-dow').value || undefined;
    const dom      = $('pln-dom').value || undefined;
    const cron     = $('pln-cron').value || undefined;
    const autorun  = $('pln-autorun').checked;

    if (!name)  return err('Zadaj názov úlohy.');
    if (!email) return err('Zadaj e-mail príjemcu.'); 
    if (!question) return err('Zadaj textovú požiadavku.');

    const body = { name, question, email, schedule_type:schedule };
    if (schedule === 'daily' || schedule === 'weekly' || schedule === 'monthly') body.time = time;
    if (schedule === 'weekly') body.dow = dow;
    if (schedule === 'monthly') body.dom = dom ? Number(dom) : undefined;
    if (schedule === 'custom_cron') body.time = cron;

    const btn = $('pln-save-btn'); btn.setAttribute('disabled','true');
    try {
      const res = await apiReq('/api/tasks/save_nl', { method:'POST', body });
      savedTaskId = res.id;
      savedSnapshot = snapshot();
      setRunEnabled(true);
      setSaveEnabled(false);
      setStateBadge(`Uložené ✓ (ID ${res.id})`);
      ok(`Úloha uložená (ID ${res.id}) – CRON: ${res.cron}`);

      // Auto-run (skúšobný mail) – predvolene zapnuté
      if (autorun && savedTaskId) {
        const runBtn = $('pln-run-btn'); runBtn.setAttribute('disabled','true');
        try {
          const runRes = await apiReq('/api/tasks/run', { method:'POST', body:{ task_id: savedTaskId }});
          ok(runRes.message || 'Úloha spustená.');
        } catch (e) { err(e.message || e); }
        finally { runBtn.removeAttribute('disabled'); }
      }
    } catch(e) {
      err(e.message || e);
      setSaveEnabled(true);
    } finally {
      btn.removeAttribute('disabled');
    }
  };

  // Spustiť teraz
  $('pln-run-btn').onclick = async () => {
    if (!savedTaskId) return err('Najprv ulož úlohu.');
    const btn = $('pln-run-btn'); btn.setAttribute('disabled','true');
    try {
      const res = await apiReq('/api/tasks/run', { method:'POST', body:{ task_id: savedTaskId }});
      ok(res.message || 'Úloha spustená.');
    } catch(e) { err(e.message || e); }
    finally { btn.removeAttribute('disabled'); }
  };
});
