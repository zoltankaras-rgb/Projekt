// =================================================================
// === KANCELÁRIA: Modul Teploty (simulované) ======================
// =================================================================

async function api(url, opts = {}) {
  return await apiRequest(url, opts);
}

function _htmlEscape(s){ return (window.escapeHtml ? window.escapeHtml(s) : String(s||'')); }
function _fmtType(t){ return t==='CHLAD'?'Chladiaci box' : (t==='MRAZ'?'Mraziaci box':'Priestor – rozrábka'); }
function _el(id){ return document.getElementById(id); }

// ------------- pomocné funkcie pre časové sloty (15 min) -------------
function _floorQuarter(d){
  const nd = new Date(d);
  nd.setSeconds(0,0);
  nd.setMinutes(Math.floor(nd.getMinutes()/15)*15);
  return nd;
}
function _endQuarterFor(dateStr, toNow){
  const [Y,M,D] = dateStr.split('-').map(Number);
  const dayStart = new Date(Y, M-1, D, 0,0,0,0);
  if (toNow){
    const now = new Date();
    if (now.getFullYear()===Y && (now.getMonth()+1)===M && now.getDate()===D){
      return _floorQuarter(now);
    }
  }
  return new Date(Y, M-1, D, 23, 45, 0, 0); // posledný slot dňa
}
function _buildTimeSlots(dateStr, toNow){
  const [Y,M,D] = dateStr.split('-').map(Number);
  const start = new Date(Y, M-1, D, 0,0,0,0);
  const end   = _endQuarterFor(dateStr, toNow);
  const slots = [];
  for (let t = new Date(start); t <= end; t.setMinutes(t.getMinutes()+15)){
    const tt = new Date(t);
    slots.push(tt.getHours().toString().padStart(2,'0')+':'+tt.getMinutes().toString().padStart(2,'0'));
  }
  return slots;
}

// =====================================================================

function initializeTempsModule(){
  const mount = _el('section-temps');
  if (!mount) return;

  mount.innerHTML = `
    <h3>Teploty – chladničky / mraziaky / rozrábka</h3>

    <div class="analysis-card" style="margin-bottom:1rem;">
      <h4 style="margin-bottom:.5rem;">Zariadenia</h4>
      <div id="temps-devices-table"></div>
      <div style="display:flex; gap:.5rem; margin-top:.75rem;">
        <button class="btn btn-success" id="temps-add-device"><i class="fas fa-plus"></i> Pridať zariadenie</button>
        <button class="btn btn-secondary" id="temps-refresh"><i class="fas fa-rotate"></i> Obnoviť</button>
      </div>
    </div>

    <div class="analysis-card">
      <h4 style="margin-bottom:.5rem;">Report</h4>
      <div class="form-grid" style="grid-template-columns: repeat(6, minmax(160px, 1fr)); gap:.75rem;">
        <div class="form-group">
          <label>Dátum</label>
          <input type="date" id="temps-report-date">
        </div>
        <div class="form-group">
          <label>Zariadenie</label>
          <select id="temps-report-device">
            <option value="">— Všetky aktívne —</option>
          </select>
        </div>
        <div class="form-group" style="align-self:end;">
          <button class="btn btn-secondary" id="temps-open-report"><i class="fas fa-print"></i> Tlačiť celý deň</button>
        </div>
        <div class="form-group" style="align-self:end;">
          <button class="btn btn-secondary" id="temps-open-report-now"><i class="fas fa-print"></i> Tlačiť dnešné (do teraz)</button>
        </div>
        <div class="form-group" style="align-self:end;">
          <button class="btn btn-secondary" id="temps-open-report-summary"><i class="fas fa-table"></i> Tlačiť súhrnný</button>
        </div>
        <div class="form-group" style="align-self:end;">
          <button class="btn btn-secondary" id="temps-open-report-summary-now"><i class="fas fa-table"></i> Súhrnný (do teraz)</button>
        </div>
        <div class="form-group" style="align-self:end;">
          <button class="btn btn-primary" id="temps-preview-today"><i class="fas fa-eye"></i> Dnešný náhľad</button>
        </div>
        <div class="form-group" style="align-self:end;">
          <button class="btn btn-primary" id="temps-preview-summary"><i class="fas fa-eye"></i> Súhrnný náhľad</button>
        </div>
      </div>
      <div id="temps-readings-day" style="margin-top:1rem;"></div>
    </div>
  `;

  _el('temps-add-device').onclick      = () => openDeviceModal();
  _el('temps-refresh').onclick         = () => loadDevices();
  _el('temps-open-report').onclick     = () => openReport(false);
  _el('temps-open-report-now').onclick = () => openReport(true);
  _el('temps-open-report-summary').onclick     = () => openReportSummary(false);
  _el('temps-open-report-summary-now').onclick = () => openReportSummary(true);
  _el('temps-preview-today').onclick   = () => previewToday();
  _el('temps-preview-summary').onclick = () => previewTodaySummary();

  // predvyplň dnešný dátum
  const d = new Date();
  _el('temps-report-date').value = d.toISOString().slice(0,10);

  loadDevices();
}

async function loadDevices(){
  const tbl = _el('temps-devices-table');
  const sel = _el('temps-report-device');
  sel.innerHTML = `<option value="">— Všetky aktívne —</option>`;
  tbl.innerHTML = '<p>Načítavam…</p>';

  const rows = await api('/api/kancelaria/temps/devices');
  if (!rows || rows.length===0){
    tbl.innerHTML = '<p>Žiadne zariadenia.</p>';
    return;
  }

  // poskladaj tabuľku
  let html = `
    <div class="table-container"><table>
      <thead>
        <tr><th>#</th><th>Kód</th><th>Názov</th><th>Umiestnenie</th><th>Typ</th><th>Stav</th><th>Akcie</th></tr>
      </thead>
      <tbody>
  `;

  rows.forEach(r=>{
    html += `
      <tr>
        <td>${r.id}</td>
        <td>${_htmlEscape(r.code)}</td>
        <td>${_htmlEscape(r.name)}</td>
        <td>${_htmlEscape(r.location)}</td>
        <td>${_fmtType(r.device_type)}</td>
        <td>${r.is_active? (r.manual_off?'<span class="kpi-badge" style="background:#fee2e2;color:#991b1b;">MANUÁLNE VYPNUTÉ</span>':'Aktívny'):'Neaktívny'}</td>
        <td style="display:flex; gap:.3rem;">
          <button class="btn btn-warning btn-xs js-edit-device" data-id="${r.id}"><i class="fas fa-edit"></i></button>
          <button class="btn btn-secondary btn-xs js-outage-device" data-id="${r.id}"><i class="fas fa-calendar"></i></button>
          <button class="btn btn-danger btn-xs js-toggle-manual" data-id="${r.id}" data-next="${r.manual_off?0:1}">${r.manual_off?'Zapnúť':'Vypnúť'}</button>
        </td>
      </tr>
    `;
    // doplň do selectu pre report
    sel.insertAdjacentHTML('beforeend', `<option value="${r.id}">${_htmlEscape(r.name)} (${_htmlEscape(r.code)})</option>`);
  });

  html += '</tbody></table></div>';
  tbl.innerHTML = html;

  // naviaž akcie
  tbl.querySelectorAll('.js-edit-device').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const id = btn.dataset.id;
      const device = rows.find(x=>String(x.id)===String(id));
      openDeviceModal(id, device);
    });
  });
  tbl.querySelectorAll('.js-outage-device').forEach(btn=>{
    btn.addEventListener('click', ()=> openOutageModal(btn.dataset.id));
  });
  tbl.querySelectorAll('.js-toggle-manual').forEach(btn=>{
    btn.addEventListener('click', ()=> toggleManual(btn.dataset.id, btn.dataset.next));
  });
}

function openDeviceModal(id=null, device=null){
  showModal(id?'Upraviť zariadenie':'Pridať zariadenie', ()=>{
    const html = `
      <form id="temps-device-form">
        <input type="hidden" name="id" value="${id||''}">
        <div class="form-grid" style="grid-template-columns: repeat(2, minmax(160px, 1fr)); gap:.75rem;">
          <div class="form-group"><label>Kód</label><input name="code" value="${device?.code||''}" required></div>
          <div class="form-group"><label>Názov</label><input name="name" value="${device?.name||''}" required></div>
          <div class="form-group"><label>Umiestnenie</label><input name="location" value="${device?.location||''}" required></div>
          <div class="form-group"><label>Typ</label>
            <select name="device_type" required>
              <option value="CHLAD" ${device?.device_type==='CHLAD'?'selected':''}>Chladiaci box (0.0 – 4.2 °C)</option>
              <option value="MRAZ" ${device?.device_type==='MRAZ'?'selected':''}>Mraziaci box (-19.9 – -17.0 °C)</option>
              <option value="ROZRABKA" ${device?.device_type==='ROZRABKA'?'selected':''}>Priestor – rozrábka (2.0 – 5.0 °C)</option>
            </select>
          </div>
          <div class="form-group"><label>Aktívny</label><input type="checkbox" name="is_active" ${device?.is_active? 'checked':''}></div>
          <div class="form-group"><label>Manuálne vypnúť</label><input type="checkbox" name="manual_off" ${device?.manual_off? 'checked':''}></div>
        </div>
        <button class="btn btn-success" style="margin-top:.75rem;">Uložiť</button>
      </form>`;
    return {
      html,
      onReady: ()=>{
        const f = _el('temps-device-form');
        f.onsubmit = async (e)=>{
          e.preventDefault();
          const body = Object.fromEntries(new FormData(f).entries());
          body.is_active = f.elements.is_active.checked ? 1 : 0;
          body.manual_off = f.elements.manual_off.checked ? 1 : 0;
          await api('/api/kancelaria/temps/device/save', { method:'POST', body });
          _el('modal-container').style.display='none';
          loadDevices();
        };
      }
    }
  });
}

function openOutageModal(device_id){
  showModal('Výluka zariadenia', ()=>{
    const html = `
      <form id="temps-outage-form">
        <input type="hidden" name="device_id" value="${device_id}">
        <div class="form-grid" style="grid-template-columns: repeat(3, minmax(160px, 1fr)); gap:.75rem;">
          <div class="form-group"><label>Zapnutá výluka</label><input type="checkbox" name="enabled" checked></div>
          <div class="form-group"><label>Od (HH:MM)</label><input type="time" name="start_time" value="00:00"></div>
          <div class="form-group"><label>Do (HH:MM)</label><input type="time" name="end_time" value="23:59"></div>
        </div>
        <div class="form-group">
          <label>Dni v týždni</label>
          <div style="display:flex; gap:.5rem; flex-wrap:wrap;">
            <label><input type="checkbox" name="mon" checked> Po</label>
            <label><input type="checkbox" name="tue"> Ut</label>
            <label><input type="checkbox" name="wed"> St</label>
            <label><input type="checkbox" name="thu"> Št</label>
            <label><input type="checkbox" name="fri"> Pi</label>
            <label><input type="checkbox" name="sat"> So</label>
            <label><input type="checkbox" name="sun"> Ne</label>
          </div>
          <p class="b2c-row-meta">TIP: celovíkendová výluka = zaškrtni So+Ne 00:00–23:59.</p>
        </div>
        <div class="form-grid" style="grid-template-columns: repeat(2, minmax(160px, 1fr)); gap:.75rem;">
          <div class="form-group"><label>Platí od (dátum, voliteľné)</label><input type="date" name="date_from"></div>
          <div class="form-group"><label>Platí do (dátum, voliteľné)</label><input type="date" name="date_to"></div>
        </div>
        <button class="btn btn-success"><i class="fas fa-save"></i> Uložiť výluku</button>
      </form>`;
    return {
      html,
      onReady: ()=>{
        const f = _el('temps-outage-form');
        f.onsubmit = async function(e){
          e.preventDefault();
          const body = Object.fromEntries(new FormData(f).entries());
          body.enabled = f.elements.enabled.checked ? 1:0;
          await api('/api/kancelaria/temps/outage/save',{method:'POST', body});
          _el('modal-container').style.display='none';
          showStatus('Výluka uložená.', false);
        };
      }
    };
  });
}

async function toggleManual(id, value){
  await api('/api/kancelaria/temps/device/setManual',{method:'POST', body:{id, manual_off:value}});
  loadDevices();
}

// ------------------------- REPORT tlač ----------------------------
function openReport(toNow){
  const date = _el('temps-report-date').value;
  const dev  = _el('temps-report-device').value;
  const to   = toNow ? '&to=now' : '';
  const url  = dev ? `/report/temps?date=${date}&device_id=${dev}${to}` : `/report/temps?date=${date}${to}`;
  window.open(url, '_blank');
}
function openReportSummary(toNow){
  const date = _el('temps-report-date').value;
  const dev  = _el('temps-report-device').value;
  const to   = toNow ? '&to=now' : '';
  const url  = dev
    ? `/report/temps?layout=summary&date=${date}&device_id=${dev}${to}`
    : `/report/temps?layout=summary&date=${date}${to}`;
  window.open(url, '_blank');
}

// --------------------- Náhľad (detail) 00:00 → teraz -------------
async function previewToday(){
  const box  = _el('temps-readings-day');
  const date = _el('temps-report-date').value;
  const dev  = _el('temps-report-device').value;
  box.innerHTML = '<p>Načítavam dnešné záznamy…</p>';

  const url  = dev
    ? `/api/kancelaria/temps/readings?date=${date}&device_id=${dev}&to=now`
    : `/api/kancelaria/temps/readings?date=${date}&to=now`;

  const rows = await api(url);
  if (!rows || rows.length===0){
    box.innerHTML = '<p>Žiadne záznamy pre zadané filtre.</p>';
    return;
  }

  // Zoskup podľa zariadenia
  const byDev = new Map();
  rows.forEach(r=>{
    const key = r.device_id || r.id || 'x';
    if (!byDev.has(key)) byDev.set(key, { meta: r, rows: [] });
    byDev.get(key).rows.push(r);
  });

  let html = '';
  byDev.forEach((bucket)=>{
    const m = bucket.meta;
    html += `
      <div class="analysis-card" style="margin-bottom:1rem;">
        <h4>${_htmlEscape(m.name)} (${_htmlEscape(m.code||'')}) · ${_htmlEscape(m.location||'')} · ${_fmtType(m.device_type||'')}</h4>
        <div class="table-container">
          <table>
            <thead><tr><th>Čas</th><th>Teplota (°C)</th><th>Stav</th></tr></thead>
            <tbody>
              ${
                bucket.rows.length
                  ? bucket.rows.map(r=>`
                      <tr>
                        <td>${new Date(r.ts).toLocaleTimeString('sk-SK',{hour:'2-digit',minute:'2-digit'})}</td>
                        <td>${r.status==='OK' ? (Number(r.temperature).toFixed(1)) : '—'}</td>
                        <td>${r.status==='OK' ? 'OK' : '<span class="kpi-badge" style="background:#fee2e2;color:#991b1b;">BOX VYPNUTÝ</span>'}</td>
                      </tr>
                    `).join('')
                  : '<tr><td colspan="3">Žiadne záznamy.</td></tr>'
              }
            </tbody>
          </table>
        </div>
      </div>`;
  });

  box.innerHTML = html;
}

// --------------------- Súhrnný (pivot) náhľad --------------------
async function previewTodaySummary(){
  const box  = _el('temps-readings-day');
  const date = _el('temps-report-date').value;
  const dev  = _el('temps-report-device').value;
  box.innerHTML = '<p>Načítavam súhrn…</p>';

  // zoznam zariadení – z selectu
  let devices = [];
  if (dev) {
    const opt = _el('temps-report-device').selectedOptions[0];
    const plateMatch = opt.text.match(/\(([^)]+)\)/);
    devices = [{ id: Number(dev), name: opt.text.replace(/\s*\([^)]*\)\s*$/,''), code: (plateMatch && plateMatch[1]) || '' }];
  } else {
    const sel = _el('temps-report-device');
    devices = Array.from(sel.options)
      .filter(o=>o.value)
      .map(o=>{
        const m = o.text.match(/\(([^)]+)\)/);
        return { id: Number(o.value), name: o.text.replace(/\s*\([^)]*\)\s*$/,''), code: (m&&m[1])||'' }
      });
  }
  if (!devices.length){ box.innerHTML = '<p>Žiadne zariadenia.</p>'; return; }

  // načítaj readings (do teraz)
  const url  = dev
    ? `/api/kancelaria/temps/readings?date=${date}&device_id=${dev}&to=now`
    : `/api/kancelaria/temps/readings?date=${date}&to=now`;
  const rows = await api(url);

  // index podľa času → device_id
  const byTime = new Map(); // "HH:MM" -> Map(deviceId -> record)
  rows.forEach(r=>{
    const t = new Date(r.ts);
    const key = t.getHours().toString().padStart(2,'0')+':'+t.getMinutes().toString().padStart(2,'0');
    if (!byTime.has(key)) byTime.set(key, new Map());
    byTime.get(key).set(r.device_id, r);
  });

  // vybuduj všetky 15-min sloty 00:00 → teraz
  const slots = _buildTimeSlots(date, true);
  if (!slots.length){ box.innerHTML = '<p>Žiadne záznamy pre zvolený deň.</p>'; return; }

  // kreslenie pivot tabuľky
  let html = '<div class="table-container"><table><thead><tr><th>Čas</th>';
  devices.forEach(d => html += `<th>${_htmlEscape(d.name)}</th>`);
  html += '</tr></thead><tbody>';

  slots.forEach(t=>{
    html += `<tr><td>${t}</td>`;
    devices.forEach(d=>{
      const rec = (byTime.get(t) || new Map()).get(d.id);
      if (rec){
        if (rec.status === 'OK') html += `<td>${Number(rec.temperature).toFixed(1)}</td>`;
        else                     html += `<td style="color:#991b1b;font-weight:600;">OFF</td>`;
      } else {
        html += `<td style="color:#9ca3af;">—</td>`;
      }
    });
    html += '</tr>';
  });

  html += '</tbody></table></div>';
  box.innerHTML = html;
}

/* Auto-register sekcia */
(function(){
  const container = document.getElementById('section-temps');
  if (container) initializeTempsModule();
})();
