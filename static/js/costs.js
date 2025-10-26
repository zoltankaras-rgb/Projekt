// =================================================================
// === LOGIKA PRE SUB-MODUL: SPRÁVA NÁKLADOV ===
// =================================================================

let costsState = {
    year: new Date().getFullYear(),
    month: new Date().getMonth() + 1,
    data: {}
};

function initializeCostsModule() {
    const container = document.getElementById('section-costs');
    if (!container) return;

    container.innerHTML = `
        <h3>Správa Nákladov</h3>
        <div style="display: flex; gap: 1rem; align-items: flex-end; margin-bottom: 1.5rem; flex-wrap: wrap;">
            <div class="form-group" style="margin-bottom: 0;"><label for="costs-year-select" style="margin-top: 0;">Rok:</label><select id="costs-year-select"></select></div>
            <div class="form-group" style="margin-bottom: 0;"><label for="costs-month-select" style="margin-top: 0;">Mesiac:</label><select id="costs-month-select"></select></div>
        </div>
        <div class="b2b-tab-nav" id="costs-main-nav">
             <button class="b2b-tab-button active" data-view="view-costs-dashboard">Dashboard</button>
             <button class="b2b-tab-button" data-view="view-costs-energy">Energie</button>
             <button class="b2b-tab-button" data-view="view-costs-hr">Ľudské zdroje</button>
             <button class="b2b-tab-button" data-view="view-costs-operational">Prevádzkové náklady</button>
        </div>
        <div id="costs-content" style="margin-top: 1.5rem;"></div>
    `;

    const yearSelect = document.getElementById('costs-year-select');
    const monthSelect = document.getElementById('costs-month-select');
    const currentYear = new Date().getFullYear();
    for (let i = currentYear; i >= currentYear - 3; i--) yearSelect.add(new Option(i, i));
    const monthNames = ["Január", "Február", "Marec", "Apríl", "Máj", "Jún", "Júl", "August", "September", "Október", "November", "December"];
    monthNames.forEach((name, index) => monthSelect.add(new Option(name, index + 1)));
    yearSelect.value = costsState.year;
    monthSelect.value = costsState.month;

    const loadData = () => {
        costsState.year = yearSelect.value;
        costsState.month = monthSelect.value;
        loadAndRenderCostsData();
    };
    yearSelect.onchange = loadData;
    monthSelect.onchange = loadData;
    
    document.querySelectorAll('#costs-main-nav .b2b-tab-button').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('#costs-main-nav .b2b-tab-button').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            renderCurrentCostsView();
        });
    });
    loadData();
}

async function loadAndRenderCostsData() {
    const container = document.getElementById('costs-content');
    container.innerHTML = `<p>Načítavam dáta za ${costsState.month}/${costsState.year}...</p>`;
    try {
        costsState.data = await apiRequest(`/api/kancelaria/costs/getData?year=${costsState.year}&month=${costsState.month}`);
        renderCurrentCostsView();
    } catch (e) {
        container.innerHTML = `<p class="error">Chyba pri načítaní dát: ${e.message}</p>`;
    }
}

function renderCurrentCostsView() {
    const activeView = document.querySelector('#costs-main-nav .b2b-tab-button.active').dataset.view;
    switch(activeView) {
        case 'view-costs-dashboard': renderCostsDashboard(); break;
        case 'view-costs-energy': renderEnergyView(); break;
        case 'view-costs-hr': renderHrView(); break;
        case 'view-costs-operational': renderOperationalCostsView(); break;
    }
}

async function renderCostsDashboard() {
    const container = document.getElementById('costs-content');
    container.innerHTML = `<p>Načítavam dáta pre dashboard...</p>`;
    try {
        const data = await apiRequest(`/api/kancelaria/costs/getDashboardData?year=${costsState.year}&month=${costsState.month}`);
        
        container.innerHTML = `
            <div class="analysis-grid">
                <div class="stat-card"><h5>Celkové Výnosy</h5><p>${safeToFixed(data.summary.total_revenue)} €</p></div>
                <div class="stat-card"><h5>Celkové Náklady</h5><p class="loss">${safeToFixed(data.summary.total_costs)} €</p></div>
                <div class="stat-card"><h5>Čistý Zisk</h5><p class="${data.summary.net_profit >= 0 ? 'gain' : 'loss'}">${safeToFixed(data.summary.net_profit)} €</p></div>
            </div>
            <h4 style="margin-top: 2rem;">Štruktúra Nákladov</h4>
            <div id="costs-pie-chart" style="width: 100%; height: 400px;"></div>
        `;

        await loadGoogleCharts();
        const chartData = new google.visualization.DataTable();
        chartData.addColumn('string', 'Kategória');
        chartData.addColumn('number', 'Suma');
        
        let hasData = false;
        Object.entries(data.breakdown).forEach(([key, value]) => {
            if(parseFloat(value) > 0) {
                chartData.addRow([key, parseFloat(value)]);
                hasData = true;
            }
        });

        if (hasData) {
            const options = { title: 'Mesačné náklady podľa kategórií', pieHole: 0.4, legend: { position: 'right' } };
            const chart = new google.visualization.PieChart(document.getElementById('costs-pie-chart'));
            chart.draw(chartData, options);
        } else {
            document.getElementById('costs-pie-chart').innerHTML = "<p>Žiadne dáta na zobrazenie v grafe.</p>";
        }

    } catch(e) {
        container.innerHTML = `<p class="error">Chyba pri načítaní dát pre dashboard: ${e.message}</p>`;
    }
}

function renderEnergyView() {
    const container = document.getElementById('costs-content');
    const { electricity, gas } = costsState.data.energy;
    container.innerHTML = `
        <div class="form-grid">
            <div>
                <h4>Spotreba Elektriny</h4>
                <div class="form-grid"><div class="form-group"><label>Odpis VSE</label><input type="number" step="0.01" id="el-odpis_vse" value="${electricity.odpis_vse || ''}"></div><div class="form-group"><label>Odpis VSE NT</label><input type="number" step="0.01" id="el-odpis_vse_nt" value="${electricity.odpis_vse_nt || ''}"></div></div>
                <div class="form-grid"><div class="form-group"><label>Fakturácia VSE</label><input type="number" step="0.01" id="el-fakturacia_vse" value="${electricity.fakturacia_vse || ''}"></div><div class="form-group"><label>Fakturácia VSE NT</label><input type="number" step="0.01" id="el-fakturacia_vse_nt" value="${electricity.fakturacia_vse_nt || ''}"></div></div>
                <div class="form-grid"><div class="form-group"><label>Rozdiel VSE</label><input type="number" step="0.01" id="el-rozdiel_vse" value="${electricity.rozdiel_vse || ''}" readonly></div><div class="form-group"><label>Rozdiel VSE NT</label><input type="number" step="0.01" id="el-rozdiel_vse_nt" value="${electricity.rozdiel_vse_nt || ''}" readonly></div></div>
                <div class="form-group"><label>FA s DPH</label><input type="number" step="0.01" id="el-faktura_s_dph" value="${electricity.faktura_s_dph || ''}"></div>
                <div class="stat-card"><h5>Relevantný náklad (FA / 4.68)</h5><p id="el-final_cost">${safeToFixed(electricity.final_cost)} €</p></div>
            </div>
            <div>
                <h4>Spotreba Plynu</h4>
                <div class="form-grid"><div class="form-group"><label>Stav odpísaný</label><input type="number" step="0.001" id="gas-stav_odpisany" value="${gas.stav_odpisany || ''}"></div><div class="form-group"><label>Stav fakturovaný</label><input type="number" step="0.001" id="gas-stav_fakturovany" value="${gas.stav_fakturovany || ''}"></div></div>
                <div class="form-group"><label>Rozdiel m3</label><input type="number" step="0.001" id="gas-rozdiel_m3" value="${gas.rozdiel_m3 || ''}" readonly></div>
                <div class="form-grid"><div class="form-group"><label>Spaľovacie teplo</label><input type="number" step="0.0001" id="gas-spal_teplo" value="${gas.spal_teplo || ''}"></div><div class="form-group"><label>Objemový koeficient</label><input type="number" step="0.0001" id="gas-obj_koeficient" value="${gas.obj_koeficient || ''}"></div></div>
                <div class="form-group"><label>Spotreba kWh</label><input type="number" step="0.001" id="gas-spotreba_kwh" value="${gas.spotreba_kwh || ''}" readonly></div>
                <hr>
                <div class="form-grid"><div class="form-group"><label>Nákup plynu</label><input type="number" step="0.01" id="gas-nakup_plynu_eur" value="${gas.nakup_plynu_eur || ''}"></div><div class="form-group"><label>Distribúcia</label><input type="number" step="0.01" id="gas-distribucia_eur" value="${gas.distribucia_eur || ''}"></div></div>
                <div class="form-grid"><div class="form-group"><label>Straty</label><input type="number" step="0.01" id="gas-straty_eur" value="${gas.straty_eur || ''}"></div><div class="form-group"><label>Poplatok OKTE</label><input type="number" step="0.01" id="gas-poplatok_okte_eur" value="${gas.poplatok_okte_eur || ''}"></div></div>
                <div class="form-group"><label>Spolu bez DPH</label><input type="number" step="0.01" id="gas-spolu_bez_dph" value="${gas.spolu_bez_dph || ''}" readonly></div>
                <div class="form-group"><label>DPH</label><input type="number" step="0.01" id="gas-dph" value="${gas.dph || ''}" readonly></div>
                <div class="stat-card"><h5>Spolu s DPH</h5><p id="gas-spolu_s_dph">${safeToFixed(gas.spolu_s_dph)} €</p></div>
            </div>
        </div>
        <button class="btn-success" style="width:100%; margin-top: 1.5rem;" onclick="saveEnergyData()">Uložiť dáta o energiách</button>
    `;
    setupEnergyCalculations();
}

function renderHrView() {
    const container = document.getElementById('costs-content');
    const { hr } = costsState.data;
    container.innerHTML = `
        <div class="form-group"><label>Celková suma na výplatách (hrubá mzda)</label><input type="number" step="0.01" id="hr-total_salaries" value="${hr.total_salaries || ''}"></div>
        <div class="form-group"><label>Celková suma odvodov (zaplatené firmou)</label><input type="number" step="0.01" id="hr-total_levies" value="${hr.total_levies || ''}"></div>
        <div class="stat-card"><h5>Celkový náklad na ĽZ</h5><p id="hr-total-cost">${safeToFixed((hr.total_salaries || 0) + (hr.total_levies || 0))} €</p></div>
        <button class="btn-success" style="width:100%;" onclick="saveHrData()">Uložiť dáta</button>
    `;

    document.getElementById('hr-total_salaries').oninput = document.getElementById('hr-total_levies').oninput = () => {
        const salaries = parseFloat(document.getElementById('hr-total_salaries').value) || 0;
        const levies = parseFloat(document.getElementById('hr-total_levies').value) || 0;
        document.getElementById('hr-total-cost').textContent = `${safeToFixed(salaries + levies)} €`;
    };
}

function renderOperationalCostsView() {
    const container = document.getElementById('costs-content');
    const { items, categories } = costsState.data.operational;
    let rowsHtml = items.map(item => `
        <tr>
            <td>${new Date(item.entry_date).toLocaleDateString('sk-SK')}</td>
            <td>${escapeHtml(item.category_name)}</td>
            <td>${escapeHtml(item.name)}</td>
            <td>${safeToFixed(item.amount_net)} €</td>
            <td>${item.is_recurring ? 'Áno' : 'Nie'}</td>
            <td>
                <button class="btn-warning" style="padding:5px; margin:0;" onclick='showOperationalCostModal(${JSON.stringify(item)})'><i class="fas fa-edit"></i></button>
                <button class="btn-danger" style="padding:5px; margin:0 0 0 5px;" onclick="handleDeleteOperationalCost(${item.id})"><i class="fas fa-trash"></i></button>
            </td>
        </tr>
    `).join('');

    container.innerHTML = `
        <div style="display:flex; justify-content: flex-end; align-items: center; gap: 1rem; margin-bottom: 1rem;">
            <button id="manage-categories-btn" class="btn-secondary"><i class="fas fa-tags"></i> Spravovať kategórie</button>
            <button id="add-operational-cost-btn" class="btn-success"><i class="fas fa-plus"></i> Nový náklad</button>
        </div>
        <div class="table-container"><table id="operational-costs-table">
            <thead><tr><th>Dátum</th><th>Kategória</th><th>Názov/Popis</th><th>Suma (bez DPH)</th><th>Opakujúci sa</th><th>Akcie</th></tr></thead>
            <tbody>${rowsHtml || '<tr><td colspan="6" style="text-align:center;">Žiadne záznamy pre tento mesiac.</td></tr>'}</tbody>
        </table></div>
    `;
    document.getElementById('add-operational-cost-btn').onclick = () => showOperationalCostModal(null);
    document.getElementById('manage-categories-btn').onclick = showManageCategoriesModal;
}

function setupEnergyCalculations() {
    const el_inputs = ['el-odpis_vse', 'el-fakturacia_vse', 'el-odpis_vse_nt', 'el-fakturacia_vse_nt', 'el-faktura_s_dph'];
    el_inputs.forEach(id => document.getElementById(id)?.addEventListener('input', () => {
        const odpis = parseFloat(document.getElementById('el-odpis_vse').value) || 0;
        const fakt = parseFloat(document.getElementById('el-fakturacia_vse').value) || 0;
        document.getElementById('el-rozdiel_vse').value = (fakt - odpis).toFixed(2);
        
        const odpis_nt = parseFloat(document.getElementById('el-odpis_vse_nt').value) || 0;
        const fakt_nt = parseFloat(document.getElementById('el-fakturacia_vse_nt').value) || 0;
        document.getElementById('el-rozdiel_vse_nt').value = (fakt_nt - odpis_nt).toFixed(2);

        const fa_s_dph = parseFloat(document.getElementById('el-faktura_s_dph').value) || 0;
        document.getElementById('el-final_cost').textContent = `${safeToFixed(fa_s_dph / 4.68)} €`;
    }));

    const gas_inputs = ['gas-stav_odpisany', 'gas-stav_fakturovany', 'gas-spal_teplo', 'gas-obj_koeficient', 'gas-nakup_plynu_eur', 'gas-distribucia_eur', 'gas-straty_eur', 'gas-poplatok_okte_eur'];
    gas_inputs.forEach(id => document.getElementById(id)?.addEventListener('input', () => {
        const odpis = parseFloat(document.getElementById('gas-stav_odpisany').value) || 0;
        const fakt = parseFloat(document.getElementById('gas-stav_fakturovany').value) || 0;
        const rozdiel = fakt - odpis;
        document.getElementById('gas-rozdiel_m3').value = rozdiel.toFixed(3);

        const spal_teplo = parseFloat(document.getElementById('gas-spal_teplo').value) || 0;
        const koef = parseFloat(document.getElementById('gas-obj_koeficient').value) || 0;
        const spotreba_kwh = rozdiel * spal_teplo * koef;
        document.getElementById('gas-spotreba_kwh').value = spotreba_kwh.toFixed(3);

        const nakup = parseFloat(document.getElementById('gas-nakup_plynu_eur').value) || 0;
        const dist = parseFloat(document.getElementById('gas-distribucia_eur').value) || 0;
        const straty = parseFloat(document.getElementById('gas-straty_eur').value) || 0;
        const okte = parseFloat(document.getElementById('gas-poplatok_okte_eur').value) || 0;
        const bez_dph = nakup + dist + straty + okte;
        const dph = bez_dph * 0.20;
        const s_dph = bez_dph + dph;

        document.getElementById('gas-spolu_bez_dph').value = bez_dph.toFixed(2);
        document.getElementById('gas-dph').value = dph.toFixed(2);
        document.getElementById('gas-spolu_s_dph').textContent = `${safeToFixed(s_dph)} €`;
    }));
}

async function saveEnergyData() {
    const data = {
        year: costsState.year, month: costsState.month,
        electricity: {
            odpis_vse: document.getElementById('el-odpis_vse').value,
            fakturacia_vse: document.getElementById('el-fakturacia_vse').value,
            rozdiel_vse: document.getElementById('el-rozdiel_vse').value,
            odpis_vse_nt: document.getElementById('el-odpis_vse_nt').value,
            fakturacia_vse_nt: document.getElementById('el-fakturacia_vse_nt').value,
            rozdiel_vse_nt: document.getElementById('el-rozdiel_vse_nt').value,
            faktura_s_dph: document.getElementById('el-faktura_s_dph').value,
        },
        gas: {
            stav_odpisany: document.getElementById('gas-stav_odpisany').value,
            stav_fakturovany: document.getElementById('gas-stav_fakturovany').value,
            rozdiel_m3: document.getElementById('gas-rozdiel_m3').value,
            spal_teplo: document.getElementById('gas-spal_teplo').value,
            obj_koeficient: document.getElementById('gas-obj_koeficient').value,
            spotreba_kwh: document.getElementById('gas-spotreba_kwh').value,
            nakup_plynu_eur: document.getElementById('gas-nakup_plynu_eur').value,
            distribucia_eur: document.getElementById('gas-distribucia_eur').value,
            straty_eur: document.getElementById('gas-straty_eur').value,
            poplatok_okte_eur: document.getElementById('gas-poplatok_okte_eur').value,
            spolu_bez_dph: document.getElementById('gas-spolu_bez_dph').value,
            dph: document.getElementById('gas-dph').value,
            spolu_s_dph: (parseFloat(document.getElementById('gas-spolu_bez_dph').value) || 0) * 1.20
        }
    };
    try { await apiRequest('/api/kancelaria/costs/saveEnergy', { method: 'POST', body: data }); } catch(e) {}
}

async function saveHrData() {
    const data = { year: costsState.year, month: costsState.month, total_salaries: document.getElementById('hr-total_salaries').value, total_levies: document.getElementById('hr-total_levies').value };
    try { await apiRequest('/api/kancelaria/costs/saveHr', { method: 'POST', body: data }); } catch(e) {}
}

function showOperationalCostModal(item) {
    const categories = costsState.data.operational.categories;
    const categoryOptions = categories.map(c => `<option value="${c.id}" ${item && item.category_id == c.id ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('');

    const contentPromise = () => Promise.resolve({
        html: `
            <form id="op-cost-form">
                <input type="hidden" name="id" value="${item?.id || ''}">
                <div class="form-group"><label>Dátum</label><input type="date" name="entry_date" value="${item ? item.entry_date.split('T')[0] : new Date().toISOString().split('T')[0]}" required></div>
                <div class="form-grid">
                    <div class="form-group"><label>Kategória</label><select name="category_id" required>${categoryOptions}</select></div>
                    <div class="form-group"><label>Suma (bez DPH)</label><input type="number" step="0.01" name="amount_net" value="${item?.amount_net || ''}" required></div>
                </div>
                <div class="form-group"><label>Názov / Popis položky</label><input type="text" name="name" value="${escapeHtml(item?.name || '')}" required></div>
                <div class="form-group"><label>Poznámka</label><textarea name="description" rows="2">${escapeHtml(item?.description || '')}</textarea></div>
                <div class="form-group" style="display:flex; align-items:center; gap:10px;"><input type="checkbox" name="is_recurring" ${item?.is_recurring ? 'checked' : ''} style="width:auto;"><label style="margin:0;">Opakujúci sa náklad</label></div>
                <button type="submit" class="btn-success" style="width:100%;">${item ? 'Uložiť zmeny' : 'Pridať náklad'}</button>
            </form>
        `,
        onReady: () => {
            document.getElementById('op-cost-form').onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData.entries());
                data.is_recurring = e.target.elements.is_recurring.checked;
                try {
                    await apiRequest('/api/kancelaria/costs/saveOperational', { method: 'POST', body: data });
                    document.getElementById('modal-container').style.display = 'none';
                    loadAndRenderCostsData();
                } catch (err) {}
            };
        }
    });
    showModal(item ? 'Upraviť náklad' : 'Nový prevádzkový náklad', contentPromise);
}

async function handleDeleteOperationalCost(itemId) {
    showConfirmationModal({
        title: 'Potvrdenie vymazania', message: 'Naozaj chcete vymazať tento náklad?', warning: 'Táto akcia je nezvratná!',
        onConfirm: async () => {
            try {
                await apiRequest('/api/kancelaria/costs/deleteOperational', { method: 'POST', body: { id: itemId } });
                loadAndRenderCostsData();
            } catch (e) {}
        }
    });
}

function showManageCategoriesModal() {
    const { categories } = costsState.data.operational;
    let categoriesHtml = categories.map(c => `<li>${escapeHtml(c.name)}</li>`).join('');

    const contentPromise = () => Promise.resolve({
        html: `
            <h4>Existujúce kategórie</h4>
            <ul>${categoriesHtml || '<li>Žiadne kategórie.</li>'}</ul>
            <hr>
            <h4>Pridať novú kategóriu</h4>
            <form id="add-category-form">
                <div class="form-group">
                    <label for="new-category-name">Názov novej kategórie</label>
                    <input type="text" id="new-category-name" required>
                </div>
                <button type="submit" class="btn-success" style="width:100%;">Uložiť kategóriu</button>
            </form>
        `,
        onReady: () => {
            document.getElementById('add-category-form').onsubmit = async (e) => {
                e.preventDefault();
                const newName = document.getElementById('new-category-name').value;
                try {
                    await apiRequest('/api/kancelaria/costs/saveCategory', { method: 'POST', body: { name: newName } });
                    document.getElementById('modal-container').style.display = 'none';
                    // Po úspešnom pridaní kategórie sa načíta a prekreslí aktuálny pohľad
                    loadAndRenderCostsData(); 
                } catch (err) {}
            };
        }
    });
    showModal('Správa kategórií nákladov', contentPromise);
}
