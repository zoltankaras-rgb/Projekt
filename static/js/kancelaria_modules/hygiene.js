// =================================================================
// === SUB-MODUL KANCELÁRIA: HYGIENICKÝ REŽIM (kompletný súbor) ===
// =================================================================

// Global state guard – nevzniknú kolízie s inými súbormi
(function () {
  if (typeof window.hygieneState === 'undefined') {
    window.hygieneState = {
      agents: [],
      tasks: [],
      plan: [],
      selectedDate: null,
      filters: {}
    };
  }
})();

// Malý helper na HTML escapovanie (vezme existujúci, ak je)
const _esc = (typeof window.escapeHtml === 'function')
  ? window.escapeHtml
  : function (str) {
      return String(str || '').replace(/[&<>"']/g, m => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      })[m]);
    };

// ---------- Init modulu ----------
function initializeHygieneModule() {
  const container = document.getElementById('section-hygiene');
  if (!container) return;

  container.innerHTML = `
    <h3>Hygienický Plán</h3>
    <div style="display:flex; gap:1rem; align-items:flex-end; margin-bottom:1.5rem; flex-wrap:wrap;">
      <div class="form-group" style="margin-bottom:0;">
        <label for="hygiene-date-picker" style="margin-top:0;">Zobraziť plán/report pre dátum:</label>
        <input type="date" id="hygiene-date-picker">
      </div>
      <div class="form-group" style="margin-bottom:0;">
        <label for="hygiene-period-select" style="margin-top:0;">Typ reportu:</label>
        <select id="hygiene-period-select">
          <option value="denne">Denný</option>
          <option value="tyzdenne">Týždenný</option>
          <option value="mesacne">Mesačný</option>
        </select>
      </div>
      <button id="print-hygiene-report-btn" class="btn btn-info" style="margin-top:auto; height:fit-content;">
        <i class="fas fa-print"></i> Tlačiť Report
      </button>
      <div style="margin-left:auto;">
        <button id="manage-hygiene-agents-btn" class="btn btn-secondary" style="margin-top:auto;">
          <i class="fas fa-flask"></i> Spravovať Prostriedky
        </button>
        <button id="manage-hygiene-tasks-btn" class="btn btn-secondary" style="margin-top:auto;">
          <i class="fas fa-cogs"></i> Spravovať Úlohy
        </button>
      </div>
    </div>
    <div id="hygiene-plan-container"><p>Načítavam plán...</p></div>
  `;

  const datePicker = document.getElementById('hygiene-date-picker');
  datePicker.valueAsDate = new Date();
  datePicker.onchange = () => loadHygienePlan(datePicker.value);

  document.getElementById('manage-hygiene-tasks-btn').onclick = openHygieneTasksAdminModal;
  document.getElementById('manage-hygiene-agents-btn').onclick = openHygieneAgentsAdminModal;
  document.getElementById('print-hygiene-report-btn').onclick = () => {
    const period = document.getElementById('hygiene-period-select').value;
    window.open(`/report/hygiene?date=${datePicker.value}&period=${period}`, '_blank');
  };

  loadHygienePlan(datePicker.value);
}

// ---------- Načítanie a render plánu ----------
async function loadHygienePlan(dateStr) {
  const container = document.getElementById('hygiene-plan-container');
  container.innerHTML = '<p>Načítavam plán...</p>';
  try {
    const data = await apiRequest(`/api/kancelaria/hygiene/getPlan?date=${dateStr}`);
    window.hygieneState.selectedDate = data.date || dateStr;
    renderHygienePlan(data.plan || {}, window.hygieneState.selectedDate);
  } catch (e) {
    container.innerHTML = `<p class="error">Chyba: ${_esc(e.message)}</p>`;
  }
}

function renderHygienePlan(planData, date) {
  const container = document.getElementById('hygiene-plan-container');
  if (!planData || Object.keys(planData).length === 0) {
    container.innerHTML = '<h4>Pre tento deň nie sú naplánované žiadne hygienické úlohy.</h4>';
    return;
  }

  let html = '';
  for (const location in planData) {
    html += `<h4 style="margin-top:1.5rem;">${_esc(location)}</h4>`;
    planData[location].forEach(task => {
      const details = task.completion_details;
      let actionButton = '';
      if (details) {
        if (details.checked_by_fullname) {
          actionButton = `
            <button class="btn btn-success" disabled style="width:auto; margin:0;"
              title="Skontroloval: ${_esc(details.checked_by_fullname)}">
              <i class="fas fa-check-double"></i> Hotovo
            </button>`;
        } else {
          actionButton = `
            <button class="btn btn-warning" style="width:auto; margin:0;"
              onclick="checkHygieneLog(${details.id}, '${date}')"
              title="Vykonal: ${_esc(details.user_fullname || '')}">
              <i class="fas fa-check"></i> Skontrolovať
            </button>`;
        }
      } else {
        actionButton = `
          <button class="btn btn-primary" style="width:auto; margin:0;"
            onclick='openLogCompletionModal(${JSON.stringify(task)}, "${date}")'>
            Vykonať
          </button>`;
      }

      html += `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:.75rem; border-bottom:1px solid var(--medium-gray);">
          <span>${_esc(task.task_name)}</span>
          ${actionButton}
        </div>`;
    });
  }
  container.innerHTML = html;
}

// ---------- Pomocné ----------
function getLoggedInUserFullName() {
  const userInfoEl = document.getElementById('user-info');
  if (!userInfoEl) return 'Pracovník Kancelárie';
  const match = userInfoEl.textContent.match(/Vitajte,\s*(.*?)\s*\(/);
  return match ? match[1] : 'Pracovník Kancelárie';
}

// ---------- Logovanie vykonania (s časmi) ----------
async function openLogCompletionModal(task, date) {
  // lazy load prostriedkov
  if (!Array.isArray(window.hygieneState.agents) || window.hygieneState.agents.length === 0) {
    window.hygieneState.agents = await apiRequest('/api/kancelaria/hygiene/getAgents');
  }
  const agentOptions = (window.hygieneState.agents || [])
    .map(a => `<option value="${a.id}" ${String(task.default_agent_id) === String(a.id) ? 'selected' : ''}>${_esc(a.agent_name)}</option>`)
    .join('');

  const contentPromise = () => Promise.resolve({
    html: `
      <form id="log-completion-form">
        <div class="form-group">
          <label>Vykonal(a)</label>
          <input type="text" name="performer_name" value="${_esc(getLoggedInUserFullName())}" required>
        </div>

        <div class="form-grid">
          <div class="form-group">
            <label>Začiatok pôsobenia</label>
            <input type="time" name="start_time" required>
          </div>
          <div class="form-group">
            <label>Prostriedok</label>
            <select name="agent_id">
              <option value="">-- Bez prostriedku --</option>
              ${agentOptions}
            </select>
          </div>
        </div>

        <div class="form-grid">
          <div class="form-group">
            <label>Koncentrácia</label>
            <input type="text" name="concentration" value="${_esc(task.default_concentration || '')}">
          </div>
          <div class="form-group">
            <label>Čas pôsobenia (info)</label>
            <input type="text" name="exposure_time" value="${_esc(task.default_exposure_time || '15 min')}" placeholder="napr. 15 min">
          </div>
        </div>

        <div class="form-group">
          <label>Poznámka</label>
          <textarea name="notes" rows="3"></textarea>
        </div>

        <div class="b2c-row-meta" id="auto-times-hint" style="margin:.25rem 0 1rem 0;"></div>
        <button type="submit" class="btn btn-success" style="width:100%;">Potvrdiť vykonanie</button>
      </form>
    `,
    onReady: () => {
      const form = document.getElementById('log-completion-form');
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      form.elements.start_time.value = `${hh}:${mm}`;

      // živý náhľad automatických časov (start +15, +10)
      const hint = document.getElementById('auto-times-hint');
      const renderHint = () => {
        const v = form.elements.start_time.value;
        if (!v) { hint.textContent = ''; return; }
        const [H, M] = v.split(':').map(Number);
        const base = new Date(now.getFullYear(), now.getMonth(), now.getDate(), H || 0, M || 0, 0);
        const exposureEnd = new Date(base.getTime() + 15 * 60000);
        const rinseEnd = new Date(exposureEnd.getTime() + 10 * 60000);
        const fmt = (d) => String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
        hint.innerHTML = `Koniec pôsobenia: <strong>${fmt(exposureEnd)}</strong> &nbsp;•&nbsp; Koniec oplachu / dokončenie: <strong>${fmt(rinseEnd)}</strong>`;
      };
      form.elements.start_time.addEventListener('input', renderHint);
      renderHint();

      form.onsubmit = async (e) => {
        e.preventDefault();
        const formData = new FormData(form);
        const data = Object.fromEntries(formData.entries());
        data.task_id = task.id;
        data.completion_date = date; // YYYY-MM-DD

        try {
          await apiRequest('/api/kancelaria/hygiene/logCompletion', { method: 'POST', body: data });
          const modal = document.getElementById('modal-container');
          if (modal) modal.style.display = 'none';
          loadHygienePlan(date);
        } catch (err) { /* apiRequest ukáže chybu */ }
      };
    }
  });

  showModal(`Vykonať: ${_esc(task.task_name)}`, contentPromise);
}

// ---------- Potvrdenie kontroly ----------
async function checkHygieneLog(logId, date) {
  const defaultName = localStorage.getItem('hygiene_checker_name') || getLoggedInUserFullName();

  const contentPromise = () => Promise.resolve({
    html: `
      <form id="hygiene-check-form">
        <div class="form-group">
          <label>Meno kontrolóra</label>
          <input type="text" name="checker_name" value="${_esc(defaultName)}" required>
        </div>
        <div class="form-group" style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" id="remember_checker" checked style="width:auto;">
          <label for="remember_checker" style="margin:0;">Zapamätať pre ďalšie kontroly</label>
        </div>
        <button type="submit" class="btn btn-success" style="width:100%;">Potvrdiť kontrolu</button>
      </form>
    `,
    onReady: () => {
      const form = document.getElementById('hygiene-check-form');
      form.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        const name = (fd.get('checker_name') || '').toString().trim();
        if (!name) return;
        if (document.getElementById('remember_checker').checked) {
          localStorage.setItem('hygiene_checker_name', name);
        }
        try {
          await apiRequest('/api/kancelaria/hygiene/checkLog', {
            method: 'POST',
            body: { log_id: logId, checker_name: name }
          });
          const modal = document.getElementById('modal-container');
          if (modal) modal.style.display = 'none';
          loadHygienePlan(date);
        } catch (err) {}
      };
    }
  });

  showModal('Potvrdenie kontroly', contentPromise);
}

// ---------- Admin: ÚLOHY ----------
async function openHygieneTasksAdminModal() {
  const contentPromise = async () => {
    const tasks = await apiRequest('/api/kancelaria/hygiene/getTasks');
    let tableHtml = 'Žiadne definované úlohy.';
    if (tasks && tasks.length > 0) {
      tableHtml = `<table>
        <thead><tr><th>Názov</th><th>Umiestnenie</th><th>Frekvencia</th><th>Stav</th><th>Akcia</th></tr></thead><tbody>`;
      tasks.forEach(task => {
        tableHtml += `<tr>
          <td>${_esc(task.task_name)}</td>
          <td>${_esc(task.location)}</td>
          <td>${_esc(task.frequency)}</td>
          <td>${task.is_active ? 'Aktívna' : 'Neaktívna'}</td>
          <td><button class="btn btn-warning btn-sm" style="margin:0; width:auto;"
            onclick='openAddEditHygieneTaskModal(${JSON.stringify(task)})'>
            <i class="fas fa-edit"></i></button></td>
        </tr>`;
      });
      tableHtml += `</tbody></table>`;
    }
    return {
      html: `<div class="table-container">${tableHtml}</div>
             <button class="btn btn-success" style="width:100%; margin-top:1rem;"
               onclick="openAddEditHygieneTaskModal()">
               <i class="fas fa-plus"></i> Pridať novú úlohu
             </button>`
    };
  };
  showModal('Správa hygienických úloh', contentPromise);
}

function openAddEditHygieneTaskModal(task = null) {
  const contentPromise = async () => {
    if (!Array.isArray(window.hygieneState.agents) || window.hygieneState.agents.length === 0) {
      window.hygieneState.agents = await apiRequest('/api/kancelaria/hygiene/getAgents');
    }
    const agentOptions = (window.hygieneState.agents || [])
      .map(a => `<option value="${a.id}" ${task && String(task.default_agent_id) === String(a.id) ? 'selected' : ''}>${_esc(a.agent_name)}</option>`)
      .join('');

    return {
      html: `
        <form id="hygiene-task-form">
          <input type="hidden" name="id" value="${task?.id || ''}">
          <div class="form-group">
            <label>Názov úlohy</label>
            <input type="text" name="task_name" value="${_esc(task?.task_name || '')}" required>
          </div>
          <div class="form-grid">
            <div class="form-group">
              <label>Umiestnenie</label>
              <input type="text" name="location" value="${_esc(task?.location || '')}" required>
            </div>
            <div class="form-group">
              <label>Frekvencia</label>
              <select name="frequency" required>
                <option value="denne" ${task?.frequency === 'denne' ? 'selected' : ''}>Denne</option>
                <option value="tyzdenne" ${task?.frequency === 'tyzdenne' ? 'selected' : ''}>Týždenne</option>
                <option value="mesacne" ${task?.frequency === 'mesacne' ? 'selected' : ''}>Mesačne</option>
                <option value="stvrtronne" ${task?.frequency === 'stvrtronne' ? 'selected' : ''}>Štvrťročne</option>
                <option value="rocne" ${task?.frequency === 'rocne' ? 'selected' : ''}>Ročne</option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <label>Popis (nepovinné)</label>
            <textarea name="description" rows="2">${_esc(task?.description || '')}</textarea>
          </div>
          <hr><h4 style="text-align:left; border:none; margin-bottom:1rem;">Predvolené hodnoty (nepovinné)</h4>
          <div class="form-group">
            <label>Predvolený prostriedok</label>
            <select name="default_agent_id">
              <option value="">-- Žiadny --</option>
              ${agentOptions}
            </select>
          </div>
          <div class="form-grid">
            <div class="form-group">
              <label>Predvolená koncentrácia</label>
              <input type="text" name="default_concentration" value="${_esc(task?.default_concentration || '')}">
            </div>
            <div class="form-group">
              <label>Predvolený čas pôsobenia</label>
              <input type="text" name="default_exposure_time" value="${_esc(task?.default_exposure_time || '')}">
            </div>
          </div>
          <div class="form-group" style="display:flex; align-items:center; gap:10px; margin-top:1rem;">
            <input type="checkbox" name="is_active" ${task ? (task.is_active ? 'checked' : '') : 'checked'} style="width:auto; margin-top:0;">
            <label style="margin:0;">Úloha je aktívna</label>
          </div>
          <button type="submit" class="btn btn-success" style="width:100%;">${task ? 'Uložiť zmeny' : 'Vytvoriť úlohu'}</button>
        </form>
      `,
      onReady: () => {
        document.getElementById('hygiene-task-form').onsubmit = async (e) => {
          e.preventDefault();
          const fd = new FormData(e.target);
          const data = Object.fromEntries(fd.entries());
          data.is_active = e.target.elements.is_active.checked;

          try {
            await apiRequest('/api/kancelaria/hygiene/saveTask', { method: 'POST', body: data });
            const modal = document.getElementById('modal-container');
            if (modal) modal.style.display = 'none';
            openHygieneTasksAdminModal();
            if (window.hygieneState.selectedDate) loadHygienePlan(window.hygieneState.selectedDate);
          } catch (err) {}
        };
      }
    };
  };
  showModal(task ? 'Upraviť úlohu' : 'Pridať novú úlohu', contentPromise);
}

// ---------- Admin: PROSTRIEDKY ----------
async function openHygieneAgentsAdminModal() {
  const contentPromise = async () => {
    const agents = await apiRequest('/api/kancelaria/hygiene/getAgents');
    window.hygieneState.agents = agents || [];

    let tableHtml = 'Žiadne definované prostriedky.';
    if (agents && agents.length > 0) {
      tableHtml = `<table>
        <thead><tr><th>Názov prostriedku</th><th>Akcia</th></tr></thead><tbody>`;
      agents.forEach(agent => {
        tableHtml += `<tr>
          <td>${_esc(agent.agent_name)}</td>
          <td><button class="btn btn-warning btn-sm" style="margin:0; width:auto;"
            onclick='openAddEditHygieneAgentModal(${JSON.stringify(agent)})'>
            <i class="fas fa-edit"></i></button></td>
        </tr>`;
      });
      tableHtml += `</tbody></table>`;
    }
    return {
      html: `<div class="table-container">${tableHtml}</div>
             <button class="btn btn-success" style="width:100%; margin-top:1rem;"
               onclick="openAddEditHygieneAgentModal()">
               <i class="fas fa-plus"></i> Pridať nový prostriedok
             </button>`
    };
  };
  showModal('Správa čistiacich prostriedkov', contentPromise);
}

function openAddEditHygieneAgentModal(agent = null) {
  const contentPromise = () => Promise.resolve({
    html: `
      <form id="hygiene-agent-form">
        <input type="hidden" name="id" value="${agent?.id || ''}">
        <div class="form-group">
          <label>Názov prostriedku</label>
          <input type="text" name="agent_name" value="${_esc(agent?.agent_name || '')}" required>
        </div>
        <button type="submit" class="btn btn-success" style="width:100%;">${agent ? 'Uložiť zmeny' : 'Vytvoriť prostriedok'}</button>
      </form>
    `,
    onReady: () => {
      document.getElementById('hygiene-agent-form').onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const data = Object.fromEntries(fd.entries());
        try {
          await apiRequest('/api/kancelaria/hygiene/saveAgent', { method: 'POST', body: data });
          const modal = document.getElementById('modal-container');
          if (modal) modal.style.display = 'none';
          openHygieneAgentsAdminModal();
        } catch (err) {}
      };
    }
  });
  showModal(agent ? 'Upraviť prostriedok' : 'Pridať nový prostriedok', contentPromise);
}

// ---------- Export funkcií do window (pre onclick a setupSection) ----------
Object.assign(window, {
  initializeHygieneModule,
  loadHygienePlan,
  openLogCompletionModal,
  checkHygieneLog,
  openHygieneTasksAdminModal,
  openAddEditHygieneTaskModal,
  openHygieneAgentsAdminModal,
  openAddEditHygieneAgentModal
});
