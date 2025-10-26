// =================================================================
// === LOGIKA ŠPECIFICKÁ PRE MODUL VÝROBA (VYROBA.JS) ===
// =================================================================

// --- Globálne premenné špecifické pre modul Výroba ---
let vyrobaInitialData = {};

// --- Funkcie na zobrazenie a skrytie pohľadov (views) ---
function showVyrobaView(viewId) {
    document.querySelectorAll('#production-module-container > .view').forEach(v => v.style.display = 'none');
    const view = document.getElementById(viewId);
    if (view) {
        view.style.display = 'block';
    } else {
        console.error(`Chyba: Pohľad s ID '${viewId}' nebol nájdený!`);
    }
    clearStatus(); // Funkcia z common.js
}

// --- Funkcie na načítanie a zobrazenie dát ---

async function loadAndShowProductionMenu() {
    try {
        const data = await apiRequest('/api/getProductionMenuData');
        vyrobaInitialData = data;
        
        populatePlannedTasks(data.planned_tasks);
        populateRunningTasks(data.running_tasks);
        populateProductionCategories(data.recipes);
        
        showVyrobaView('view-production-menu');
    } catch (e) {
        console.error("Nepodarilo sa načítať dáta pre menu výroby.", e);
    }
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
        container.innerHTML = '<p>Nenašli sa žiadne produkty s priradeným receptom. Nový výrobný príkaz nie je možné vytvoriť.</p><p><small>Nové recepty môžete pridať v module Kancelária.</small></p>';
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

// --- Funkcie pre interakciu používateľa ---

function showBatchPlanningView(productName, plannedWeight = '', logId = null) {
    showVyrobaView('view-start-production-batch');
    document.getElementById('batch-planning-title').textContent = `Plánovanie: ${productName}`;
    const plannedWeightEl = document.getElementById('planned-weight');
    plannedWeightEl.value = plannedWeight;
    plannedWeightEl.dataset.productName = productName;
    plannedWeightEl.dataset.logId = logId || '';
    
    document.getElementById('production-date').valueAsDate = new Date();
    
    if (plannedWeight) {
        calculateIngredientsForBatch(productName, plannedWeight);
    } else {
        document.getElementById('ingredients-check-area').innerHTML = ''; // Vyčistíme obsah
        document.getElementById('ingredients-check-area').style.display = 'none';
        document.getElementById('start-production-btn').disabled = true;
    }
}

async function calculateIngredientsForBatch(productName, plannedWeight) {
    const startBtn = document.getElementById('start-production-btn');
    const ingredientsArea = document.getElementById('ingredients-check-area');
    
    if (!productName || !plannedWeight || parseFloat(plannedWeight) <= 0) {
        ingredientsArea.style.display = 'none';
        ingredientsArea.innerHTML = '';
        startBtn.disabled = true;
        return;
    }

    try {
        const result = await apiRequest('/api/calculateRequiredIngredients', {
            method: 'POST',
            body: { productName, plannedWeight }
        });
        
        const container = document.getElementById('ingredients-table');
        container.innerHTML = '';
        if (result.data) {
            let tableHtml = '<h4>Kontrola surovín</h4><table><thead><tr><th>Surovina</th><th>Potrebné (kg)</th><th>Na sklade (kg)</th><th>Stav</th></tr></thead><tbody>';
            let allSufficient = true;
            let deficientItems = []; // Zoznam surovín v mínuse

            result.data.forEach(ing => {
                if (!ing.isSufficient) {
                    allSufficient = false;
                    deficientItems.push(ing.name);
                }
                tableHtml += `<tr class="${!ing.isSufficient ? 'loss' : ''}"><td>${escapeHtml(ing.name)}</td><td>${safeToFixed(ing.required, 3)}</td><td>${safeToFixed(ing.inStock)}</td><td>${ing.isSufficient ? '✅' : '⚠️'}</td></tr>`;
            });
            ingredientsArea.innerHTML = tableHtml + '</tbody></table>';
            
            // --- ZAČIATOK KĽÚČOVEJ ÚPRAVY ---
            // Tlačidlo bude vždy povolené, ak sú dáta v poriadku.
            startBtn.disabled = false;
            
            if (!allSufficient) {
                // Zobrazíme varovanie namiesto chyby (isError = false, ale použijeme žltú farbu).
                showStatus(`UPOZORNENIE: Sklad pôjde do mínusu pre: ${deficientItems.join(', ')}`, 'warning');
            } else {
                clearStatus();
            }
            // --- KONIEC KĽÚČOVEJ ÚPRAVY ---
        }
        ingredientsArea.style.display = 'block';
    } catch (e) {
        startBtn.disabled = true;
    }
}

async function startProduction() {
    const plannedWeightEl = document.getElementById('planned-weight');
    const data = {
        productName: plannedWeightEl.dataset.productName,
        plannedWeight: plannedWeightEl.value,
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
            body: { productName: data.productName, plannedWeight: data.plannedWeight }
        });
        
        const submissionData = { 
            ...data, 
            workerName: workerName, 
            ingredients: ingResult.data.map(i => ({ name: i.name, quantity: i.required })) 
        };

        const result = await apiRequest('/api/startProduction', {
            method: 'POST',
            body: submissionData
        });
        
        showStatus(result.message, false);
        setTimeout(() => {
            loadAndShowProductionMenu();
        }, 1500);

    } catch (e) {
       // Chyba je už spracovaná
    }
}

// --- NOVÉ FUNKCIE PRE SKLADOVÉ OPERÁCIE ---

async function loadAndShowStockLevels() {
    try {
        const warehouseData = await apiRequest('/api/getWarehouseState');
        showVyrobaView('view-stock-levels');
        const container = document.getElementById('stock-tables-container');
        container.innerHTML = '';
        for (const category in warehouseData) {
            if (category !== 'all' && warehouseData[category].length > 0) {
                const categoryName = category === 'Obaly - Črevá' ? 'Obaly' : category;
                container.innerHTML += `<h4>${escapeHtml(categoryName)}</h4><div class="table-container">${createStockTable(warehouseData[category])}</div>`;
            }
        }
    } catch (e) { /* Chyba je spracovaná v apiRequest */ }
}

function createStockTable(data) {
    if (!data || data.length === 0) return "<p>Žiadne položky.</p>";
    let table = '<table><thead><tr><th>Názov</th><th>Systém (kg)</th></tr></thead><tbody>';
    data.forEach(item => { table += `<tr><td>${escapeHtml(item.name)}</td><td>${safeToFixed(item.quantity)}</td></tr>`; });
    return table + '</tbody></table>';
}

async function loadAndShowInventory() {
    try {
        const data = await apiRequest('/api/getWarehouseState');
        showVyrobaView('view-inventory');
        const container = document.getElementById('inventory-tables-container');
        container.innerHTML = '';
        for (const category in data) {
            if (category !== 'all' && data[category].length > 0) {
                const categoryName = category === 'Obaly - Črevá' ? 'Obaly' : category;
                container.innerHTML += `<h4>${escapeHtml(categoryName)}</h4><div class="table-container">${createInventoryTable(data[category])}</div>`;
            }
        }
    } catch (e) { /* Chyba je spracovaná v apiRequest */ }
}

function createInventoryTable(items) {
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
        .filter(input => input.value)
        .map(input => ({
            name: input.dataset.itemName,
            systemQty: input.closest('tr').querySelector('td[data-system-quantity]').dataset.systemQuantity,
            realQty: input.value
        }));

    if (inventoryData.length === 0) { showStatus("Nezadali ste žiadne reálne stavy.", true); return; }
    
    try {
        const result = await apiRequest('/api/submitInventory', { 
            method: 'POST', 
            body: inventoryData 
        });
        showStatus(result.message, false);
        setTimeout(loadAndShowProductionMenu, 2000);
    } catch (e) { /* Chyba je spracovaná v apiRequest */ }
}

async function loadAndShowManualWriteoff() {
    try {
        const items = await apiRequest('/api/getAllWarehouseItems');
        showVyrobaView('view-manual-writeoff');
        const select = document.getElementById('writeoff-item-select');
        select.innerHTML = '<option value="">Vyberte surovinu...</option>';
        items.forEach(i => {
            const o = document.createElement('option');
            o.value = i.name;
            o.textContent = `${i.name} (${i.type})`;
            select.add(o);
        });
    } catch (e) { /* Chyba je spracovaná v apiRequest */ }
}

async function submitManualWriteoff() {
    const data = {
        workerName: document.getElementById('writeoff-worker-name').value,
        itemName: document.getElementById('writeoff-item-select').value,
        quantity: document.getElementById('writeoff-quantity').value,
        note: document.getElementById('writeoff-note').value
    };
    if (!data.workerName || !data.itemName || !data.quantity || !data.note) {
        showStatus("Všetky polia sú povinné.", true); return; }
    try {
        const result = await apiRequest('/api/manualWriteOff', { 
            method: 'POST', 
            body: data
        });
        showStatus(result.message, false);
        setTimeout(loadAndShowProductionMenu, 2000);
    } catch (e) { /* Chyba je spracovaná v apiRequest */ }
}
