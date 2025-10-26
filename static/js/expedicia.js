// =================================================================
// === LOGIKA ŠPECIFICKÁ PRE MODUL EXPEDÍCIA (EXPEDICIA.JS) ===
// =================================================================
let html5QrCode = null; // Globálna premenná pre inštanciu skenera

function showExpeditionView(viewId) {
    document.querySelectorAll('#expedition-module-container > .view').forEach(v => v.style.display = 'none');
    const view = document.getElementById(viewId);
    if (view) {
        view.style.display = 'block';
    } else {
        console.error(`Chyba: Pohľad s ID '${viewId}' nebol nájdený!`);
    }
    clearStatus();
}

async function loadAndShowExpeditionMenu() {
    try {
        const data = await apiRequest('/api/expedicia/getExpeditionData');
        populatePendingSlicing(data.pendingTasks);
        showExpeditionView('view-expedition-menu');
    } catch (e) {
        console.error("Nepodarilo sa načítať dáta pre menu expedície.", e);
    }
}

function populatePendingSlicing(tasks) {
    const container = document.getElementById('pending-slicing-container');
    const section = container.closest('.section');
    if (!tasks || tasks.length === 0) {
        section.style.display = 'none';
        return;
    }
    section.style.display = 'block';
    let tableHtml = `<table><thead><tr><th>Zdroj</th><th>Cieľ</th><th>Plán (ks)</th><th>Akcia</th></tr></thead><tbody>`;
    tasks.forEach(task => {
        tableHtml += `<tr>
            <td>${escapeHtml(task.bulkProductName)}</td>
            <td>${escapeHtml(task.targetProductName)}</td>
            <td>${escapeHtml(task.plannedPieces)}</td>
            <td><button class="btn-primary" style="margin:0; width:auto;" onclick="finalizeSlicing('${task.logId}')">Ukončiť</button></td>
        </tr>`;
    });
    container.innerHTML = tableHtml + '</tbody></table>';
}

// --- ZAČIATOK KĽÚČOVEJ ÚPRAVY: Logika prepojenia s výrobou ---
async function loadProductionDates() {
    try {
        const dates = await apiRequest('/api/expedicia/getProductionDates');
        showExpeditionView('view-expedition-date-selection');
        const container = document.getElementById('expedition-date-container');
        container.innerHTML = dates.length === 0 ? '<p>Žiadne výroby na prevzatie.</p>' : '';
        dates.forEach(date => {
            const btn = document.createElement('button');
            btn.className = 'btn-primary';
            btn.textContent = new Date(date + 'T00:00:00').toLocaleDateString('sk-SK');
            btn.onclick = () => loadProductionsByDate(date);
            container.appendChild(btn);
        });
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}

async function loadProductionsByDate(date) {
    try {
        showExpeditionView('view-expedition-batch-list');
        document.getElementById('expedition-batch-list-title').textContent = `Výroba zo dňa: ${new Date(date + 'T00:00:00').toLocaleDateString('sk-SK')}`;
        const productions = await apiRequest('/api/expedicia/getProductionsByDate', { 
            method: 'POST', 
            body: {date} 
        });
        
        const container = document.getElementById('expedition-batch-table');
        const actionButtons = document.getElementById('expedition-action-buttons');
        let tableHtml = '<table><thead><tr><th>Produkt</th><th>Stav</th><th>Plán</th><th>Realita</th><th>Akcie</th><th>Poznámka</th></tr></thead><tbody>';
        let hasPending = false;
        let hasReadyForPrint = false;

        productions.forEach(p => {
            const isCompleted = p.status === 'Ukončené';
            const isReadyForPrint = p.status === 'Prijaté, čaká na tlač';
            if (!isCompleted && !isReadyForPrint) hasPending = true;
            if (isReadyForPrint) hasReadyForPrint = true;

            const planned = p.mj === 'ks' ? `${p.expectedPieces || '?'} ks` : `${safeToFixed(p.plannedQty)} kg`;
            let reality = (isCompleted || isReadyForPrint) ? (p.mj === 'ks' ? `${p.realPieces} ks` : `${safeToFixed(p.realQty)} kg`) : `<input type="number" id="actual_${p.batchId}" step="${p.mj === 'ks' ? 1 : 0.01}" style="width: 80px;">`;
            
            let actionsHtml = '';
            if (isCompleted || isReadyForPrint) {
                actionsHtml = `
                    <div style="display: flex; gap: 5px; justify-content: center;">
                        <button class="btn-info" style="margin:0;width:auto;flex:1; padding: 5px;" onclick="printAccompanyingLetter('${p.batchId}')" title="Tlačiť sprievodku"><i class="fas fa-print"></i></button>
                        <button class="btn-secondary" style="margin:0;width:auto;flex:1; padding: 5px;" onclick="showTraceability('${p.batchId}')" title="Detail šarže"><i class="fas fa-search"></i></button>
                    </div>
                `;
            } else {
                actionsHtml = `<select id="status_${p.batchId}"><option value="OK">OK</option><option value="NEPRIJATÉ">NEPRIJATÉ</option><option value="Iné">Iné</option></select>`;
            }

            let rowClass = isReadyForPrint ? 'batch-row-ok' : '';

            tableHtml += `<tr class="${rowClass}" data-batch-id="${p.batchId}" data-unit="${p.mj}" data-product-name="${escapeHtml(p.productName)}" data-planned-qty="${p.plannedQty}" data-production-date="${p.datum_vyroby}">
                <td>${escapeHtml(p.productName)}</td><td>${escapeHtml(p.status)}</td><td>${planned}</td><td>${reality}</td><td>${actionsHtml}</td>
                <td>${isCompleted || isReadyForPrint ? (p.poznamka_expedicie || '') : `<input type="text" id="note_${p.batchId}">`}</td></tr>`;
        });
        container.innerHTML = tableHtml + '</tbody></table>';

        actionButtons.innerHTML = '';
        if (hasPending) {
            actionButtons.innerHTML += `<button class="btn-success" onclick="completeProductions('${date}')">Potvrdiť prevzatie</button>`;
        }
        if (hasReadyForPrint) {
            actionButtons.innerHTML += `<button class="btn-danger" onclick="finalizeDay('${date}')">Finalizovať deň (uzávierka)</button>`;
        }
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}
// --- KONIEC KĽÚČOVEJ ÚPRAVY ---

function showTraceability(batchId) {
    window.open(`/traceability/${batchId}`, '_blank');
}
async function completeProductions(date) {
    const workerName = document.getElementById('expedition-worker-name').value;
    if (!workerName) { showStatus("Zadajte meno preberajúceho pracovníka.", true); return; }

    const itemsToComplete = Array.from(document.querySelectorAll('#expedition-batch-table tbody tr'))
        .map(row => ({
            batchId: row.dataset.batchId, workerName, productName: row.dataset.productName, plannedQty: row.dataset.plannedQty, unit: row.dataset.unit,
            visualCheckStatus: document.getElementById(`status_${row.dataset.batchId}`)?.value,
            actualValue: document.getElementById(`actual_${row.dataset.batchId}`)?.value,
            note: document.getElementById(`note_${row.dataset.batchId}`)?.value
        }))
        .filter(item => item.visualCheckStatus && (item.visualCheckStatus !== 'OK' || item.actualValue));

    if (itemsToComplete.length === 0) { showStatus("Nič na spracovanie. Zadajte reálne hodnoty pre položky so stavom OK.", true); return; }

    try {
        const result = await apiRequest('/api/expedicia/completeProductions', { 
            method: 'POST', 
            body: itemsToComplete 
        });
        showStatus(result.message, false);
        if (date) loadProductionsByDate(date);
    } catch (e) { /* Chyba je spracovaná */ }
}

async function finalizeDay(date) {
    if (!confirm(`Naozaj chcete finalizovať deň ${date}? Táto akcia presunie všetky prijaté výrobky na finálny sklad a ukončí výrobné príkazy.`)) return;
    try {
        const result = await apiRequest('/api/expedicia/finalizeDay', { 
            method: 'POST', 
            body: {date}
        });
        showStatus(result.message, false);
        loadProductionsByDate(date);
    } catch(e) { /* Chyba je spracovaná */ }
}

async function printAccompanyingLetter(batchId) {
    const workerName = document.getElementById('expedition-worker-name').value;
    if (!workerName) { showStatus("Zadajte meno preberajúceho pracovníka.", true); return; }
    try {
        const response = await fetch('/api/expedicia/getAccompanyingLetter', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({batchId, workerName}) 
        });
        if (!response.ok) throw new Error(`Chyba servera: ${response.statusText}`);
        const htmlContent = await response.text();
        const newWindow = window.open('', '_blank');
        newWindow.document.write(htmlContent);
        newWindow.document.close();
    } catch (e) { 
        showStatus(`Chyba pri tlači: ${e.message}`, true);
    }
}


async function finalizeSlicing(logId) {
    const actualPieces = prompt("Zadajte reálny počet kusov, ktorý bol nakrájaný:");
    if (actualPieces === null || actualPieces === "" || isNaN(parseInt(actualPieces))) {
        showStatus("Zadaný neplatný počet kusov.", true);
        return;
    }
    try {
        const result = await apiRequest('/api/expedicia/finalizeSlicing', { 
            method: 'POST', 
            body: {logId, actualPieces: parseInt(actualPieces)} 
        });
        showStatus(result.message, false);
        loadAndShowExpeditionMenu();
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}

async function loadAndShowProductInventory() {
    try {
        const data = await apiRequest('/api/expedicia/getProductsForInventory');
        showExpeditionView('view-expedition-inventory');
        const container = document.getElementById('product-inventory-tables-container');
        container.innerHTML = '';
        for (const category in data) {
            if (data[category].length > 0) {
                container.innerHTML += `<h4>${escapeHtml(category)}</h4><div class="table-container">${createProductInventoryTable(data[category])}</div>`;
            }
        }
    } catch (e) { /* Chyba je spracovaná v apiRequest */ }
}

function createProductInventoryTable(items) {
    let table = `<table><thead><tr><th>Názov Produktu</th><th>Systém (ks/kg)</th><th>Reálny stav (ks/kg)</th></tr></thead><tbody>`;
    items.forEach(item => {
        table += `<tr>
            <td>${escapeHtml(item.nazov_vyrobku)} (${item.mj})</td>
            <td>${item.system_stock_display}</td>
            <td><input type="number" step="0.01" data-ean="${escapeHtml(item.ean)}" class="product-inventory-input"></td>
        </tr>`;
    });
    return table + '</tbody></table>';
}

async function submitProductInventory() {
    const workerName = document.getElementById('inventory-worker-name').value;
    if (!workerName) {
        showStatus("Zadajte meno pracovníka, ktorý vykonáva inventúru.", true);
        return;
    }
    const inventoryData = Array.from(document.querySelectorAll('.product-inventory-input'))
        .filter(input => input.value)
        .map(input => ({ ean: input.dataset.ean, realQty: input.value }));

    if (inventoryData.length === 0) {
        showStatus("Nezadali ste žiadne reálne stavy.", true);
        return;
    }
    try {
        const result = await apiRequest('/api/expedicia/submitProductInventory', { 
            method: 'POST', 
            body: { workerName: workerName, inventoryData: inventoryData }
        });
        showStatus(result.message, false);
        setTimeout(loadAndShowExpeditionMenu, 2000);
    } catch (e) { /* Chyba je spracovaná v apiRequest */ }
}

async function loadAndShowManualReceive() {
    try {
        const products = await apiRequest('/api/expedicia/getAllFinalProducts');
        showExpeditionView('view-expedition-manual-receive');
        const select = document.getElementById('manual-receive-product-select');
        select.innerHTML = '<option value="">Vyberte produkt...</option>';
        products.forEach(p => {
            const o = document.createElement('option');
            o.value = p.ean;
            o.textContent = `${p.name} (${p.unit})`;
            select.add(o);
        });
        document.getElementById('manual-receive-date').valueAsDate = new Date();
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}

async function submitManualReceive() {
    const data = {
        workerName: document.getElementById('manual-receive-worker-name').value,
        receptionDate: document.getElementById('manual-receive-date').value,
        ean: document.getElementById('manual-receive-product-select').value,
        quantity: document.getElementById('manual-receive-quantity').value
    };
    if (!data.workerName || !data.ean || !data.quantity) { showStatus("Všetky polia sú povinné.", true); return; }
    try {
        const result = await apiRequest('/api/expedicia/manualReceiveProduct', { 
            method: 'POST', body: data 
        });
        showStatus(result.message, false);
        setTimeout(loadAndShowExpeditionMenu, 2000);
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}

async function loadAndShowSlicingRequest() {
    try {
        const products = await apiRequest('/api/expedicia/getSlicableProducts');
        showExpeditionView('view-expedition-slicing-request');
        const select = document.getElementById('slicing-product-select');
        select.innerHTML = '<option value="">Vyberte produkt na krájanie...</option>';
        products.forEach(p => {
            const o = document.createElement('option');
            o.value = p.ean;
            o.textContent = p.name;
            select.add(o);
        });
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}

async function submitSlicingRequest() {
    const data = {
        ean: document.getElementById('slicing-product-select').value,
        pieces: document.getElementById('slicing-planned-pieces').value
    };
    if (!data.ean || !data.pieces) { showStatus("Vyberte produkt a zadajte počet kusov.", true); return; }
    try {
        const result = await apiRequest('/api/expedicia/startSlicingRequest', { 
            method: 'POST', body: data 
        });
        showStatus(result.message, false);
        setTimeout(loadAndShowExpeditionMenu, 2000);
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}

async function loadAndShowManualDamage() {
    try {
        const products = await apiRequest('/api/expedicia/getAllFinalProducts');
        showExpeditionView('view-expedition-manual-damage');
        const select = document.getElementById('damage-product-select');
        select.innerHTML = '<option value="">Vyberte produkt...</option>';
        products.forEach(p => {
            const o = document.createElement('option');
            o.value = p.ean;
            o.textContent = `${p.name} (${p.unit})`;
            select.add(o);
        });
        select.onchange = (e) => {
            const selectedOption = e.target.options[e.target.selectedIndex];
            document.getElementById('damage-quantity-label').textContent = `Množstvo (${selectedOption.textContent.match(/\((.*)\)/)[1]})`;
        };
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}

async function submitManualDamage() {
    const data = {
        workerName: document.getElementById('damage-worker-name').value,
        ean: document.getElementById('damage-product-select').value,
        quantity: document.getElementById('damage-quantity').value,
        note: document.getElementById('damage-note').value
    };
    if (!data.workerName || !data.ean || !data.quantity || !data.note) { showStatus("Všetky polia sú povinné.", true); return; }
    try {
        const result = await apiRequest('/api/expedicia/logManualDamage', { 
            method: 'POST', body: data 
        });
        showStatus(result.message, false);
        setTimeout(loadAndShowExpeditionMenu, 2000);
    } catch(e) { /* Chyba je spracovaná v apiRequest */ }
}

function startBarcodeScanner() {
    showExpeditionView('view-expedition-scanner');
    const scanResultEl = document.getElementById('scan-result');
    scanResultEl.textContent = '';
    
    html5QrCode = new Html5Qrcode("scanner-container");
    const qrCodeSuccessCallback = (decodedText, decodedResult) => {
        scanResultEl.textContent = `Naskenovaný kód: ${decodedText}`;
        stopBarcodeScanner();
        showTraceability(decodedText);
    };
    const config = { fps: 10, qrbox: { width: 250, height: 250 } };

    html5QrCode.start({ facingMode: "environment" }, config, qrCodeSuccessCallback)
        .catch(err => {
            showStatus(`Chyba pri spúšťaní kamery: ${err}`, true);
            showExpeditionView('view-expedition-menu');
        });
}

function stopBarcodeScanner() {
    if (html5QrCode && html5QrCode.isScanning) {
        html5QrCode.stop().then(ignore => {
        }).catch(err => {
            console.error("Nepodarilo sa zastaviť skener.", err);
        });
    }
    showExpeditionView('view-expedition-menu');
}
