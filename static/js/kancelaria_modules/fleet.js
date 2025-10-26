// =================================================================
// === SUB-MODUL KANCELÁRIA: VOZOVÝ PARK ===
// =================================================================

function initializeFleetModule() {
    const container = document.getElementById('section-fleet');
    if (!container) return;
    container.innerHTML = `
        <h3>Správa Vozového Parku</h3>
        <div style="display: flex; gap: 1rem; align-items: flex-end; margin-bottom: 1.5rem; flex-wrap: wrap;">
            <div class="form-group" style="margin-bottom: 0;">
                <label for="fleet-vehicle-select" style="margin-top: 0;">Vozidlo:</label>
                <select id="fleet-vehicle-select"></select>
            </div>
            <div class="form-group" style="margin-bottom: 0;">
                <label for="fleet-year-select" style="margin-top: 0;">Rok:</label>
                <select id="fleet-year-select"></select>
            </div>
            <div class="form-group" style="margin-bottom: 0;">
                <label for="fleet-month-select" style="margin-top: 0;">Mesiac:</label>
                <select id="fleet-month-select"></select>
            </div>
            <div style="margin-left: auto; display: flex; gap: 0.5rem;">
                 <button id="add-vehicle-btn" class="btn-success" style="margin-top: auto;"><i class="fas fa-plus"></i> Nové</button>
                 <button id="edit-vehicle-btn" class="btn-warning" style="margin-top: auto;"><i class="fas fa-edit"></i> Upraviť</button>
                 <button id="print-fleet-report-btn" class="btn-info" style="margin-top: auto;"><i class="fas fa-print"></i> Tlačiť Report</button>
            </div>
        </div>
        <div class="b2b-tab-nav" id="fleet-main-nav">
             <button class="b2b-tab-button active" data-fleet-tab="logbook">Kniha Jázd</button>
             <button class="b2b-tab-button" data-fleet-tab="refueling">Tankovanie</button>
             <button class="b2b-tab-button" data-fleet-tab="costs">Náklady</button>
             <button class="b2b-tab-button" data-fleet-tab="analysis">Analýza</button>
        </div>
        
        <div id="logbook-tab" class="b2b-tab-content active" style="margin-top: 1.5rem;">
            <div id="fleet-logbook-container" class="table-container"></div>
            <button id="save-logbook-changes-btn" class="btn-success" style="width: 100%; margin-top: 1rem;"><i class="fas fa-save"></i> Uložiť zmeny v knihe jázd</button>
        </div>
        <div id="refueling-tab" class="b2b-tab-content" style="margin-top: 1.5rem;">
            <div id="fleet-refueling-container"></div>
            <button id="add-refueling-btn" class="btn-success" style="width: 100%; margin-top: 1rem;"><i class="fas fa-gas-pump"></i> Pridať záznam o tankovaní</button>
        </div>
        <div id="costs-tab" class="b2b-tab-content" style="margin-top: 1.5rem;">
            <div id="fleet-costs-container"></div>
            <button id="add-cost-btn" class="btn-success" style="width: 100%; margin-top: 1rem;"><i class="fas fa-plus"></i> Pridať nový náklad</button>
        </div>
        <div id="analysis-tab" class="b2b-tab-content" style="margin-top: 1.5rem;">
            <div id="fleet-analysis-container"></div>
        </div>
    `;

    const vehicleSelect = document.getElementById('fleet-vehicle-select');
    const yearSelect = document.getElementById('fleet-year-select');
    const monthSelect = document.getElementById('fleet-month-select');

    const currentYear = new Date().getFullYear();
    for (let i = currentYear; i >= currentYear - 5; i--) { yearSelect.add(new Option(i, i)); }
    const monthNames = ["Január", "Február", "Marec", "Apríl", "Máj", "Jún", "Júl", "August", "September", "Október", "November", "December"];
    monthNames.forEach((name, index) => { monthSelect.add(new Option(name, index + 1)); });
    
    const today = new Date();
    yearSelect.value = today.getFullYear();
    monthSelect.value = today.getMonth() + 1;

    const loadData = () => loadAndRenderFleetData();
    vehicleSelect.onchange = loadData;
    yearSelect.onchange = loadData;
    monthSelect.onchange = loadData;

    document.getElementById('add-vehicle-btn').onclick = () => openAddEditVehicleModal();
    document.getElementById('edit-vehicle-btn').onclick = () => {
        if (fleetState.selected_vehicle_id) { openAddEditVehicleModal(fleetState.selected_vehicle_id); } 
        else { showStatus("Najprv vyberte vozidlo, ktoré chcete upraviť.", true); }
    };
    document.getElementById('save-logbook-changes-btn').onclick = handleSaveLogbook;
    document.getElementById('add-refueling-btn').onclick = () => openAddRefuelingModal(vehicleSelect.value);
    document.getElementById('print-fleet-report-btn').onclick = handlePrintFleetReport;
    document.getElementById('add-cost-btn').onclick = () => openAddEditCostModal();

    const tabButtons = document.querySelectorAll('#section-fleet .b2b-tab-button');
    tabButtons.forEach(button => {
        button.onclick = () => {
            tabButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            document.querySelectorAll('#section-fleet .b2b-tab-content').forEach(content => content.classList.remove('active'));
            document.getElementById(`${button.dataset.fleetTab}-tab`).classList.add('active');
            
            if (button.dataset.fleetTab === 'analysis') loadAndRenderFleetAnalysis();
            else if (button.dataset.fleetTab === 'costs') loadAndRenderFleetCosts();
        };
    });
    
    loadAndRenderFleetData(true);
}

async function loadAndRenderFleetData(initialLoad = false) {
    const vehicleSelect = document.getElementById('fleet-vehicle-select');
    const yearSelect = document.getElementById('fleet-year-select');
    const monthSelect = document.getElementById('fleet-month-select');

    let vehicleId = vehicleSelect.value;
    let year = yearSelect.value;
    let month = monthSelect.value;
    
    try {
        const url = `/api/kancelaria/fleet/getData?vehicle_id=${vehicleId || ''}&year=${year}&month=${month}`;
        const data = await apiRequest(url);
        fleetState = { ...fleetState, ...data };

        renderVehicleSelect(data.vehicles, data.selected_vehicle_id);
        renderLogbookTable(data.logs, data.selected_year, data.selected_month, data.last_odometer);
        renderRefuelingTable(data.refuelings);

        if (document.querySelector('[data-fleet-tab="analysis"].active')) {
            loadAndRenderFleetAnalysis();
        }
        if (document.querySelector('[data-fleet-tab="costs"].active')) {
            loadAndRenderFleetCosts();
        }
    } catch (e) { 
        console.error("Chyba pri načítaní dát vozového parku:", e); 
        document.getElementById('fleet-logbook-container').innerHTML = `<p class="error">${e.message}</p>`;
    }
}

function renderVehicleSelect(vehicles, selectedId) {
    const select = document.getElementById('fleet-vehicle-select');
    const currentVal = select.value;
    select.innerHTML = '';
    if (!vehicles || vehicles.length === 0) {
        select.add(new Option('Žiadne vozidlá v systéme', ''));
        return;
    }
    vehicles.forEach(v => select.add(new Option(`${v.name} (${v.license_plate})`, v.id)));
    
    if (vehicles.some(v => v.id == currentVal)) { select.value = currentVal; } 
    else if (selectedId) { select.value = selectedId; }
}

function renderLogbookTable(logs, year, month, lastOdometer) {
    const container = document.getElementById('fleet-logbook-container');
    const daysInMonth = new Date(year, month, 0).getDate();
    const logsMap = new Map((logs || []).map(log => [new Date(log.log_date).getDate(), log]));
    const vehicle = fleetState.vehicles.find(v => v.id == fleetState.selected_vehicle_id);

    let table = `<table><thead><tr><th>Dátum</th><th>Šofér</th><th>Zač. km</th><th>Kon. km</th><th>Najazdené</th><th>Vývoz kg</th><th>Dovoz kg</th><th>Dod. listy</th></tr></thead><tbody>`;
    let prevEndOdometer = lastOdometer;

    for (let day = 1; day <= daysInMonth; day++) {
        const log = logsMap.get(day);
        const startOdometer = log?.start_odometer !== null && log?.start_odometer !== undefined ? log.start_odometer : prevEndOdometer;
        const endOdometer = log?.end_odometer !== null && log?.end_odometer !== undefined ? log.end_odometer : '';
        const drivenKm = (startOdometer !== null && endOdometer !== '' && endOdometer > startOdometer) ? endOdometer - startOdometer : '';

        table += `<tr data-day="${day}">
            <td>${new Date(year, month - 1, day).toLocaleDateString('sk-SK')}</td>
            <td><input type="text" class="log-input" name="driver" value="${log?.driver || vehicle?.default_driver || ''}"></td>
            <td><input type="number" class="log-input odometer-start" name="start_odometer" value="${startOdometer || ''}" readonly></td>
            <td><input type="number" class="log-input odometer-end" name="end_odometer" value="${endOdometer || ''}" oninput="updateDrivenKm(this)"></td>
            <td class="driven-km">${drivenKm}</td>
            <td><input type="number" class="log-input" name="goods_out_kg" step="0.1" value="${log?.goods_out_kg || ''}"></td>
            <td><input type="number" class="log-input" name="goods_in_kg" step="0.1" value="${log?.goods_in_kg || ''}"></td>
            <td><input type="number" class="log-input" name="delivery_notes_count" value="${log?.delivery_notes_count || ''}"></td>
        </tr>`;

        if (endOdometer) { prevEndOdometer = endOdometer; }
    }
    container.innerHTML = table + `</tbody></table>`;
}

function updateDrivenKm(endOdometerInput) {
    const row = endOdometerInput.closest('tr');
    const startOdo = parseFloat(row.querySelector('.odometer-start').value) || 0;
    const endOdo = parseFloat(endOdometerInput.value) || 0;
    
    const drivenKmCell = row.querySelector('.driven-km');
    drivenKmCell.textContent = (endOdo > startOdo) ? (endOdo - startOdo) : '';
    
    let nextRow = row.nextElementSibling;
    let currentEndOdo = endOdo;
    while(nextRow) {
        const nextStartInput = nextRow.querySelector('.odometer-start');
        const nextEndInput = nextRow.querySelector('.odometer-end');
        
        nextStartInput.value = currentEndOdo > 0 ? currentEndOdo : '';
        
        const nextStartOdo = parseFloat(nextStartInput.value) || 0;
        const nextEndOdo = parseFloat(nextEndInput.value) || 0;
        
        const nextDrivenKmCell = nextRow.querySelector('.driven-km');
        nextDrivenKmCell.textContent = (nextEndOdo > nextStartOdo) ? (nextEndOdo - nextStartOdo) : '';
        
        currentEndOdo = nextEndOdo > 0 ? nextEndOdo : nextStartOdo;
        nextRow = nextRow.nextElementSibling;
    }
}

async function handleSaveLogbook() {
    const { selected_year, selected_month, selected_vehicle_id } = fleetState;
    if (!selected_vehicle_id) {
        showStatus("Nie je vybrané žiadne vozidlo. Zmeny sa neuložili.", true);
        return;
    }
    const logsToSave = [];
    document.querySelectorAll('#fleet-logbook-container tbody tr').forEach(row => {
        const inputs = row.querySelectorAll('.log-input');
        let hasData = false;
        const logData = {
            log_date: `${selected_year}-${String(selected_month).padStart(2, '0')}-${String(row.dataset.day).padStart(2, '0')}`,
            vehicle_id: selected_vehicle_id
        };
        inputs.forEach(input => {
            if (input.value.trim() !== '') hasData = true;
            logData[input.name] = input.value.trim() === '' ? null : input.value;
        });
        const drivenKm = row.querySelector('.driven-km').textContent;
        if (drivenKm) { logData.km_driven = drivenKm; hasData = true; }
        
        if (hasData || (logData.end_odometer === '' && logData.start_odometer !== null) ) {
             // Zahrnie aj riadky, kde bol vymazaný koncový stav
            logsToSave.push(logData);
        }
    });
    if (logsToSave.length === 0) { showStatus("Neboli zadané žiadne údaje na uloženie.", false); return; }
    try {
        await apiRequest('/api/kancelaria/fleet/saveLog', { method: 'POST', body: { logs: logsToSave } });
        loadAndRenderFleetData();
    } catch (e) {}
}

function renderRefuelingTable(refuelings) {
    const container = document.getElementById('fleet-refueling-container');
    if (!refuelings || refuelings.length === 0) {
        container.innerHTML = '<p>Pre tento mesiac neboli nájdené žiadne záznamy o tankovaní.</p>';
        return;
    }
    let table = `<div class="table-container"><table><thead><tr>
        <th>Dátum</th><th>Šofér</th><th>Litre</th><th>Cena/L (€)</th><th>Cena celkom (€)</th><th>Akcie</th>
    </tr></thead><tbody>`;
    refuelings.forEach(r => {
        table += `<tr>
            <td>${new Date(r.refueling_date).toLocaleDateString('sk-SK')}</td>
            <td>${escapeHtml(r.driver || '')}</td>
            <td>${r.liters}</td>
            <td>${r.price_per_liter ? safeToFixed(r.price_per_liter, 3) : ''}</td>
            <td>${r.total_price ? safeToFixed(r.total_price) : ''}</td>
            <td><button class="btn-danger" style="margin:0; padding: 5px;" onclick="handleDeleteRefueling(${r.id})"><i class="fas fa-trash"></i></button></td>
        </tr>`;
    });
    table += `</tbody></table></div>`;
    container.innerHTML = table;
}

async function handleDeleteRefueling(refuelingId) {
    showConfirmationModal({ title: 'Potvrdenie vymazania', message: 'Naozaj chcete vymazať tento záznam o tankovaní?', onConfirm: async () => { try { await apiRequest('/api/kancelaria/fleet/deleteRefueling', { method: 'POST', body: { id: refuelingId } }); loadAndRenderFleetData(); } catch (e) {} }});
}

async function openAddEditVehicleModal(vehicleId = null) {
    const contentPromise = () => Promise.resolve({
        html: document.getElementById('vehicle-modal-template').innerHTML,
        onReady: () => {
            const form = document.getElementById('vehicle-form');
            if (vehicleId) {
                const vehicle = fleetState.vehicles.find(v => v.id == vehicleId);
                if (vehicle) {
                    form.elements.id.value = vehicle.id;
                    form.elements.name.value = vehicle.name;
                    form.elements.license_plate.value = vehicle.license_plate;
                    form.elements.type.value = vehicle.type;
                    form.elements.default_driver.value = vehicle.default_driver;
                    form.elements.initial_odometer.value = vehicle.initial_odometer;
                }
            }
            form.onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(form);
                const data = Object.fromEntries(formData.entries());
                try {
                    await apiRequest('/api/kancelaria/fleet/saveVehicle', { method: 'POST', body: data });
                    document.getElementById('modal-container').style.display = 'none';
                    loadAndRenderFleetData(true);
                } catch (err) {}
            };
        }
    });
    showModal(vehicleId ? 'Upraviť vozidlo' : 'Pridať nové vozidlo', contentPromise);
}

async function openAddRefuelingModal(vehicleId) {
    if (!vehicleId) { showStatus("Najprv vyberte vozidlo.", true); return; }
    const contentPromise = () => Promise.resolve({
        html: document.getElementById('refueling-modal-template').innerHTML,
        onReady: () => {
            const form = document.getElementById('refueling-form');
            form.elements.vehicle_id.value = vehicleId;
            form.elements.refueling_date.valueAsDate = new Date();
            const vehicle = fleetState.vehicles.find(v => v.id == vehicleId);
            if (vehicle) form.elements.driver.value = vehicle.default_driver || '';
            form.onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(form);
                const data = Object.fromEntries(formData.entries());
                try {
                    await apiRequest('/api/kancelaria/fleet/saveRefueling', { method: 'POST', body: data });
                    document.getElementById('modal-container').style.display = 'none';
                    loadAndRenderFleetData();
                } catch (err) {}
            };
        }
    });
    showModal('Pridať záznam o tankovaní', contentPromise);
}

async function loadAndRenderFleetAnalysis() {
    const container = document.getElementById('fleet-analysis-container');
    const { selected_vehicle_id, selected_year, selected_month } = fleetState;
    if (!selected_vehicle_id) { container.innerHTML = '<p>Najprv vyberte vozidlo pre zobrazenie analýzy.</p>'; return; }
    container.innerHTML = '<p>Načítavam analýzu...</p>';
    try {
        const url = `/api/kancelaria/fleet/getAnalysis?vehicle_id=${selected_vehicle_id}&year=${selected_year}&month=${selected_month}`;
        const data = await apiRequest(url);
        fleetState.analysis = data;
        container.innerHTML = `
            <div class="analysis-grid">
                <div class="stat-card"><h5>Celkové náklady</h5><p>${safeToFixed(data.total_costs)} €</p></div>
                <div class="stat-card"><h5>Celkovo najazdené</h5><p>${data.total_km} km</p></div>
                <div class="stat-card"><h5>Náklady na 1 km</h5><p>${safeToFixed(data.cost_per_km)} €</p></div>
                <div class="stat-card"><h5>Celkový vývoz</h5><p>${safeToFixed(data.total_goods_out_kg)} kg</p></div>
                <div class="stat-card"><h5>Cena za 1 kg tovaru</h5><p>${safeToFixed(data.cost_per_kg_goods)} €</p></div>
                <div class="stat-card"><h5>Priemerná spotreba</h5><p>${safeToFixed(data.avg_consumption)} L/100km</p></div>
            </div>`;
    } catch (e) { container.innerHTML = `<p class="error">Chyba pri načítaní analýzy: ${e.message}</p>`; }
}

async function loadAndRenderFleetCosts() {
    const container = document.getElementById('fleet-costs-container');
    const { selected_vehicle_id } = fleetState;
    if (!selected_vehicle_id) { container.innerHTML = '<p>Najprv vyberte vozidlo.</p>'; return; }
    container.innerHTML = '<p>Načítavam náklady...</p>';
    try {
        const costs = await apiRequest(`/api/kancelaria/fleet/getCosts?vehicle_id=${selected_vehicle_id}`);
        fleetState.costs = costs;
        if (!costs || costs.length === 0) { container.innerHTML = '<p>Pre toto vozidlo neboli nájdené žiadne náklady.</p>'; return; }
        let table = `<div class="table-container"><table><thead><tr>
            <th>Názov</th><th>Typ</th><th>Platnosť</th><th>Mesačná suma (€)</th><th>Akcie</th>
        </tr></thead><tbody>`;
        costs.forEach(c => {
            const validity = c.valid_to ? `${new Date(c.valid_from).toLocaleDateString('sk-SK')} - ${new Date(c.valid_to).toLocaleDateString('sk-SK')}` : `od ${new Date(c.valid_from).toLocaleDateString('sk-SK')}`;
            table += `<tr>
                <td>${escapeHtml(c.cost_name)}</td>
                <td>${escapeHtml(c.cost_type)}</td>
                <td>${validity}</td>
                <td>${safeToFixed(c.monthly_cost)}</td>
                <td>
                    <button class="btn-warning" style="margin:0; padding: 5px;" onclick='openAddEditCostModal(${JSON.stringify(c)})'><i class="fas fa-edit"></i></button>
                    <button class="btn-danger" style="margin:0; padding: 5px;" onclick="handleDeleteCost(${c.id})"><i class="fas fa-trash"></i></button>
                </td>
            </tr>`;
        });
        container.innerHTML = table + '</tbody></table></div>';
    } catch (e) { container.innerHTML = `<p class="error">Chyba pri načítaní nákladov: ${e.message}</p>`; }
}

async function openAddEditCostModal(cost = null) {
    const { selected_vehicle_id } = fleetState;
    if (!selected_vehicle_id && !cost?.vehicle_id) {
        showStatus("Najprv vyberte vozidlo, ku ktorému chcete pridať náklad.", true);
        return;
    }

    const contentPromise = () => Promise.resolve({
        html: `
            <form id="cost-form">
                <input type="hidden" name="id" value="${cost?.id || ''}">
                <input type="hidden" name="vehicle_id" value="${cost?.vehicle_id || selected_vehicle_id}">
                <div class="form-group"><label>Názov nákladu (napr. PZP Alianz)</label><input type="text" name="cost_name" value="${escapeHtml(cost?.cost_name || '')}" required></div>
                <div class="form-group"><label>Typ nákladu</label><select name="cost_type" required>
                    <option value="MZDA" ${cost?.cost_type === 'MZDA' ? 'selected' : ''}>MZDA</option>
                    <option value="POISTENIE" ${cost?.cost_type === 'POISTENIE' ? 'selected' : ''}>POISTENIE</option>
                    <option value="SERVIS" ${cost?.cost_type === 'SERVIS' ? 'selected' : ''}>SERVIS</option>
                    <option value="PNEUMATIKY" ${cost?.cost_type === 'PNEUMATIKY' ? 'selected' : ''}>PNEUMATIKY</option>
                    <option value="DIALNICNA" ${cost?.cost_type === 'DIALNICNA' ? 'selected' : ''}>DIALNICNA</option>
                    <option value="SKODA" ${cost?.cost_type === 'SKODA' ? 'selected' : ''}>SKODA</option>
                    <option value="INE" ${cost?.cost_type === 'INE' ? 'selected' : ''}>INE</option>
                </select></div>
                <div class="form-group"><label>Mesačná suma (€)</label><input type="number" step="0.01" name="monthly_cost" value="${cost?.monthly_cost || ''}" required></div>
                <div class="form-grid">
                    <div class="form-group"><label>Platné od</label><input type="date" name="valid_from" value="${cost ? new Date(cost.valid_from).toISOString().split('T')[0] : ''}" required></div>
                    <div class="form-group"><label>Platné do (nechajte prázdne, ak platí stále)</label><input type="date" name="valid_to" value="${cost?.valid_to ? new Date(cost.valid_to).toISOString().split('T')[0] : ''}"></div>
                </div>
                <div class="form-group" style="display: flex; align-items: center; gap: 10px;">
                    <input type="checkbox" id="is-vehicle-specific-checkbox" name="is_vehicle_specific" ${cost?.vehicle_id ? 'checked' : (cost === null ? 'checked' : '')} style="width: auto; margin-top: 0;">
                    <label for="is-vehicle-specific-checkbox" style="margin: 0;">Náklad sa viaže na toto konkrétne vozidlo</label>
                </div>
                <button type="submit" class="btn-success" style="width:100%;">${cost ? 'Uložiť zmeny' : 'Vytvoriť náklad'}</button>
            </form>`,
        onReady: () => {
            const form = document.getElementById('cost-form');
            if (!cost) form.elements.valid_from.valueAsDate = new Date();
            document.getElementById('is-vehicle-specific-checkbox').onchange = (e) => { form.elements.vehicle_id.value = e.target.checked ? selected_vehicle_id : ''; };
            form.onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(form);
                const data = Object.fromEntries(formData.entries());
                data.is_vehicle_specific = document.getElementById('is-vehicle-specific-checkbox').checked;
                try {
                    await apiRequest('/api/kancelaria/fleet/saveCost', { method: 'POST', body: data });
                    document.getElementById('modal-container').style.display = 'none';
                    loadAndRenderFleetCosts();
                    loadAndRenderFleetAnalysis();
                } catch (err) {}
            };
        }
    });
    showModal(cost ? 'Upraviť náklad' : 'Pridať nový náklad', contentPromise);
}

async function handleDeleteCost(costId) {
    const cost = fleetState.costs.find(c => c.id === costId);
    if (!cost) return;
    showConfirmationModal({
        title: 'Potvrdenie vymazania',
        message: `Naozaj chcete natrvalo vymazať náklad "${cost.cost_name}"?`,
        warning: 'Táto akcia je nezvratná!',
        onConfirm: async () => {
            try {
                await apiRequest('/api/kancelaria/fleet/deleteCost', { method: 'POST', body: { id: costId } });
                loadAndRenderFleetCosts();
                loadAndRenderFleetAnalysis();
            } catch (e) {}
        }
    });
}

async function handlePrintFleetReport() {
    const { selected_vehicle_id, selected_year, selected_month } = fleetState;
    if (!selected_vehicle_id) { showStatus("Najprv vyberte vozidlo.", true); return; }
    window.open(`/report/fleet?vehicle_id=${selected_vehicle_id}&year=${selected_year}&month=${selected_month}`, '_blank');
}
