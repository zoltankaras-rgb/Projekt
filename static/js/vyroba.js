// =================================================================
// === LOGIKA ŠPECIFICKÁ PRE MODUL VÝROBA (VYROBA.JS) ===
// =================================================================

let vyrobaInitialData = {};

// --- Prepínanie pohľadov ---
function showVyrobaView(viewId) {
    document.querySelectorAll('#production-module-container > .view').forEach(v => v.style.display = 'none');
    const view = document.getElementById(viewId);
    if (view) view.style.display = 'block';
    if (typeof clearStatus === 'function') clearStatus();
}

// --- Načítanie menu výroby ---
async function loadAndShowProductionMenu() {
    try {
        const data = await apiRequest('/api/getProductionMenuData');
        if (data && data.error) { showStatus(data.error, true); return; }
        vyrobaInitialData = data || {};
        populatePlannedTasks(data.planned_tasks);
        populateRunningTasks(data.running_tasks);
        populateProductionCategories(data.recipes);
        showVyrobaView('view-production-menu');
    } catch (e) {}
}

function populatePlannedTasks(tasks) {
    const container = document.getElementById('production-tasks-container');
    container.innerHTML = '';
    if (!tasks || Object.keys(tasks).length === 0) {
        container.innerHTML = "<p>Žiadne naplánované úlohy.</p>";
        return;
    }
    for (const category in tasks) {
        container.innerHTML += `<h4>${escapeHtml(category)}</h4>`;
        tasks[category].forEach(task => {
            const btn = document.createElement('button');
            btn.className = 'btn-secondary';
            btn.innerHTML = `${escapeHtml(task.productName)} - <strong>${escapeHtml(task.displayQty)}</strong>`;
            btn.onclick = () => showBatchPlanningView(task.productName, task.actualKgQty, task.logId);
            container.appendChild(btn);
        });
    }
}

function populateRunningTasks(tasks) {
    const container = document.getElementById('running-tasks-container');
    container.innerHTML = '';
    if (!tasks || Object.keys(tasks).length === 0) {
        container.innerHTML = "<p>Momentálne neprebieha žiadna výroba.</p>";
        return;
    }
    let listHtml = '<ul>';
    for (const category in tasks) {
        listHtml += `<li><strong>${escapeHtml(category)}</strong><ul>`;
        tasks[category].forEach(task => {
            listHtml += `<li>${escapeHtml(task.productName)} - ${escapeHtml(task.displayQty)}</li>`;
        });
        listHtml += `</ul></li>`;
    }
    container.innerHTML = listHtml + '</ul>';
}

function populateProductionCategories(recipes) {
    const container = document.getElementById('category-container');
    container.innerHTML = '';
    if (!recipes || Object.keys(recipes).length === 0) {
        container.innerHTML = '<p>Nenašli sa žiadne produkty s priradeným receptom. Nový výrobný príkaz nie je možné vytvoriť.</p><p><small>Nové recepty pridajte v module Kancelária.</small></p>';
        return;
    }
    for (const category in recipes) {
        const btn = document.createElement('button');
        btn.className = 'btn-primary';
        btn.textContent = category;
        btn.onclick = () => populateProductionProducts(category, recipes[category]);
        container.appendChild(btn);
    }
}

function populateProductionProducts(category, products) {
    showVyrobaView('view-start-production-product');
    document.getElementById('product-selection-title').textContent = `Krok 2: Zvoľte produkt (${category})`;
    const container = document.getElementById('product-container');
    container.innerHTML = '';
    products.forEach(product => {
        const btn = document.createElement('button');
        btn.className = 'btn-info';
        btn.textContent = product;
        btn.onclick = () => showBatchPlanningView(product);
        container.appendChild(btn);
    });
}

// --- Plánovanie dávky ---
function showBatchPlanningView(productName, plannedWeight = '', logId = null) {
    showVyrobaView('view-start-production-batch');
    document.getElementById('batch-planning-title').textContent = `Plánovanie: ${productName}`;
    const plannedWeightEl = document.getElementById('planned-weight');
    plannedWeightEl.value = plannedWeight || '';
    plannedWeightEl.dataset.productName = productName;
    plannedWeightEl.dataset.logId = logId || '';
    const prodDate = document.getElementById('production-date');
    if (!prodDate.value) prodDate.valueAsDate = new Date();

    if (plannedWeight) {
        calculateIngredientsForBatch(productName, plannedWeight);
    } else {
        document.getElementById('ingredients-check-area').style.display = 'none';
        document.getElementById('ingredients-table').innerHTML = '';
        document.getElementById('start-production-btn').disabled = true;
    }
}

// --- Výpočet surovín (číslovanie s čiarka→bodka) ---
async function calculateIngredientsForBatch(productName, plannedWeight) {
    const startBtn = document.getElementById('start-production-btn');
    const ingredientsArea = document.getElementById('ingredients-check-area');
    const tableContainer = document.getElementById('ingredients-table');

    const plannedNorm = String(plannedWeight || '').replace(',', '.').trim();
    const plannedNum = Number(plannedNorm);

    if (!productName || !plannedNorm || !isFinite(plannedNum) || plannedNum <= 0) {
        ingredientsArea.style.display = 'none';
        tableContainer.innerHTML = '';
        startBtn.disabled = true;
        return;
    }

    try {
        const result = await apiRequest('/api/calculateRequiredIngredients', {
            method: 'POST',
            body: { productName, plannedWeight: plannedNum }
        });

        if (result && result.error) {
            showStatus(result.error, true);
            ingredientsArea.style.display = 'none';
            tableContainer.innerHTML = '';
            startBtn.disabled = true;
            return;
        }

        const rows = (result && result.data) || [];
        if (!Array.isArray(rows) || rows.length === 0) {
            showStatus('Pre recept sa nenašli suroviny.', true);
            ingredientsArea.style.display = 'none';
            tableContainer.innerHTML = '';
            startBtn.disabled = true;
            return;
        }

        let tableHtml = '<table><thead><tr><th>Surovina</th><th>Potrebné (kg)</th><th>Na sklade (kg)</th><th>Stav</th></tr></thead><tbody>';
        let allSufficient = true;
        const deficientItems = [];

        rows.forEach(ing => {
            const req = Number(String(ing.required ?? ing.requiredKg ?? ing.required_kg).toString().replace(',', '.'));
            const stock = Number(String(ing.inStock ?? ing.availableKg ?? ing.available_kg).toString().replace(',', '.'));
            const ok = !!ing.isSufficient;
            if (!ok) { allSufficient = false; deficientItems.push(ing.name); }
            tableHtml += `<tr class="${ok ? '' : 'loss'}">
                <td>${escapeHtml(ing.name)}</td>
                <td>${safeToFixed(req, 3)}</td>
                <td>${safeToFixed(stock)}</td>
                <td>${ok ? '✅' : '⚠️'}</td>
            </tr>`;
        });

        tableContainer.innerHTML = tableHtml + '</tbody></table>';
        ingredientsArea.style.display = 'block';
        startBtn.disabled = false;

        if (!allSufficient) {
            showStatus(`UPOZORNENIE: Sklad pôjde do mínusu pre: ${deficientItems.join(', ')}`, true);
        } else {
            clearStatus();
        }
    } catch (e) {
        startBtn.disabled = true;
    }
}

// --- Spustenie výroby ---
async function startProduction() {
    const plannedWeightEl = document.getElementById('planned-weight');

    const plannedNorm = String(plannedWeightEl.value || '').replace(',', '.').trim();
    const plannedNum = Number(plannedNorm);

    const data = {
        productName: plannedWeightEl.dataset.productName,
        plannedWeight: plannedNum,
        productionDate: document.getElementById('production-date').value,
        existingLogId: plannedWeightEl.dataset.logId || null
    };

    if (!data.productName || !data.plannedWeight || !data.productionDate) {
        showStatus("Všetky polia sú povinné.", true);
        return;
    }

    const userInfoEl = document.getElementById('user-info');
    const workerName = userInfoEl ? (userInfoEl.textContent.match(/Vitajte, (.*?)\s\(/)?.[1] || 'Neznamy') : 'Neznamy';

    try {
        const ingResult = await apiRequest('/api/calculateRequiredIngredients', {
            method: 'POST',
            body: { productName: data.productName, plannedWeight: plannedNum }
        });
        if (ingResult && ingResult.error) {
            showStatus(ingResult.error, true);
            return;
        }

        const submissionData = {
            ...data,
            workerName,
            ingredients: (ingResult.data || []).map(i => ({
                name: i.name,
                quantity: Number(String(i.required ?? i.requiredKg).toString().replace(',', '.'))
            }))
        };

        const result = await apiRequest('/api/startProduction', {
            method: 'POST',
            body: submissionData
        });

        if (result && result.error) {
            showStatus(result.error, true);
            return;
        }

        showStatus((result && result.message) || 'Výroba spustená.', false);
        setTimeout(() => loadAndShowProductionMenu(), 1500);
    } catch (e) {}
}

// ============================================================================
// === SKLAD – PREHĽAD (podľa kategórií Mäso, Koreniny, Obaly, Pomocný materiál)
// ============================================================================
async function loadAndShowStockLevels() {
    try {
        const data = await apiRequest('/api/getWarehouseState');
        if (data && data.error) { showStatus(data.error, true); return; }
        showVyrobaView('view-stock-levels');
        const container = document.getElementById('stock-tables-container');
        container.innerHTML = '';

        const order = ['Mäso', 'Koreniny', 'Obaly', 'Pomocný materiál'];
        order.forEach(cat => {
            const rows = data[cat] || [];
            container.innerHTML += `
                <h4>${escapeHtml(cat)}</h4>
                <div class="table-container">
                    ${createStockTable(rows)}
                </div>`;
        });
    } catch (e) {}
}

function createStockTable(data) {
    if (!data || data.length === 0) return "<p>Žiadne položky.</p>";
    let table = '<table><thead><tr><th>Názov</th><th>Kategória</th><th>Systém (kg)</th><th>Min</th></tr></thead><tbody>';
    data.forEach(item => {
        const warn = (Number(item.quantity) < Number(item.minStock)) ? ' style="color:#ef4444;font-weight:600;"' : '';
        table += `<tr${warn}>
            <td>${escapeHtml(item.name)}</td>
            <td>${escapeHtml(item.type || '')}</td>
            <td>${safeToFixed(item.quantity)}</td>
            <td>${safeToFixed(item.minStock || 0)}</td>
        </tr>`;
    });
    return table + '</tbody></table>';
}

// ============================================================================
// === SKLAD – INVENTÚRA (tiež rozdelená podľa kategórií)
// ============================================================================
async function loadAndShowInventory() {
    try {
        const data = await apiRequest('/api/getWarehouseState');
        if (data && data.error) { showStatus(data.error, true); return; }
        showVyrobaView('view-inventory');
        const container = document.getElementById('inventory-tables-container');
        container.innerHTML = '';

        const order = ['Mäso', 'Koreniny', 'Obaly', 'Pomocný materiál'];
        order.forEach(cat => {
            const rows = data[cat] || [];
            container.innerHTML += `
                <h4>${escapeHtml(cat)}</h4>
                <div class="table-container">
                    ${createInventoryTable(rows)}
                </div>`;
        });
    } catch (e) {}
}

function createInventoryTable(items) {
    if (!items || items.length === 0) return "<p>Žiadne položky.</p>";
    let table = '<table><thead><tr><th>Názov</th><th>Systém (kg)</th><th>Reálny stav (kg)</th></tr></thead><tbody>';
    items.forEach(item => {
        table += `<tr>
            <td>${escapeHtml(item.name)}</td>
            <td data-system-quantity="${item.quantity}">${safeToFixed(item.quantity)}</td>
            <td><input type="number" step="0.01" data-item-name="${escapeHtml(item.name)}" class="inventory-input"></td>
        </tr>`;
    });
    return table + '</tbody></table>';
}

async function submitInventory() {
    const inventoryData = Array.from(document.querySelectorAll('.inventory-input'))
        .filter(input => input.value !== '')
        .map(input => ({
            name: input.dataset.itemName,
            systemQty: input.closest('tr').querySelector('td[data-system-quantity]').dataset.systemQuantity,
            realQty: input.value
        }));
    if (inventoryData.length === 0) { showStatus("Nezadali ste žiadne reálne stavy.", true); return; }
    try {
        const result = await apiRequest('/api/submitInventory', { method: 'POST', body: inventoryData });
        if (result && result.error) { showStatus(result.error, true); return; }
        showStatus(result.message, false);
        setTimeout(loadAndShowProductionMenu, 2000);
    } catch (e) {}
}

// ============================================================================
// === SKLAD – Manuálny výdaj (zostáva nezmenené) ===
// ============================================================================
async function loadAndShowManualWriteoff() {
    try {
        const items = await apiRequest('/api/getAllWarehouseItems');
        if (items && items.error) { showStatus(items.error, true); return; }
        showVyrobaView('view-manual-writeoff');
        const select = document.getElementById('writeoff-item-select');
        select.innerHTML = '<option value="">Vyberte surovinu...</option>';
        items.forEach(i => {
            const o = document.createElement('option');
            o.value = i.name;
            o.textContent = `${i.name} (${i.type || ''})`;
            select.add(o);
        });
    } catch (e) {}
}

async function submitManualWriteoff() {
    const data = {
        workerName: document.getElementById('writeoff-worker-name').value,
        itemName: document.getElementById('writeoff-item-select').value,
        quantity: document.getElementById('writeoff-quantity').value,
        note: document.getElementById('writeoff-note').value
    };
    if (!data.workerName || !data.itemName || !data.quantity || !data.note) {
        showStatus("Všetky polia sú povinné.", true); return;
    }
    try {
        const result = await apiRequest('/api/manualWriteOff', { method: 'POST', body: data });
        if (result && result.error) { showStatus(result.error, true); return; }
        showStatus(result.message, false);
        setTimeout(loadAndShowProductionMenu, 2000);
    } catch (e) {}
}

// export pre common.js -> showApp()
window.loadAndShowProductionMenu = loadAndShowProductionMenu;
