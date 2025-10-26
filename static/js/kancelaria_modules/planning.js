// =================================================================
// === SUB-MODUL KANCELÁRIA: PLÁNOVANIE ===
// =================================================================

function initializePlanningModule() {
    const container = document.getElementById('section-planning');
    if (!container) return;
    container.innerHTML = `
        <h3>Plánovanie a Reporty</h3>
        <div class="btn-grid">
            <button id="show-plan-btn" class="btn-primary"><i class="fas fa-tasks"></i> Plán Výroby</button>
            <button id="show-purchase-btn" class="btn-info"><i class="fas fa-shopping-cart"></i> Návrh Nákupu</button>
            <button id="show-prod-stats-btn" class="btn-secondary"><i class="fas fa-chart-bar"></i> Prehľad Výroby</button>
            <button id="show-print-reports-btn" class="btn-warning"><i class="fas fa-print"></i> Tlač Reportov</button>
        </div>
    `;
    document.getElementById('show-plan-btn').onclick = () => showModal('Týždenný Plánovač Výroby', createProductionPlanContent);
    document.getElementById('show-purchase-btn').onclick = () => showModal('Návrh Nákupu', createPurchaseSuggestionsContent);
    document.getElementById('show-prod-stats-btn').onclick = () => showModal('Prehľad Výroby', createProductionStatsContent);
    document.getElementById('show-print-reports-btn').onclick = () => showModal('Tlač Reportov', createPrintReportsContent);
}

async function createProductionPlanContent() {
    const planDataGrouped = await apiRequest('/api/kancelaria/getProductionPlan');
    let html;

    if (!planDataGrouped || Object.keys(planDataGrouped).length === 0) {
        html = "<p>Nie je potrebné nič vyrábať na základe minimálnych zásob a objednávok.</p>";
    } else {
        const days = ['Nenaplánované', 'Pondelok', 'Utorok', 'Streda', 'Štvrtok', 'Piatok'];
        const dayOptions = days.map(d => `<option value="${d}">${d}</option>`).join('');

        let tableBodyHtml = '';
        for (const [category, items] of Object.entries(planDataGrouped)) {
            tableBodyHtml += `<tbody class="production-group-tbody">
                <tr class="category-header-row" style="background-color: #f3f4f6; font-weight: bold;"><td colspan="7">${escapeHtml(category)}</td></tr>`;
            items.forEach(item => {
                tableBodyHtml += `
                    <tr data-product-name="${escapeHtml(item.nazov_vyrobku)}">
                        <td>${escapeHtml(item.nazov_vyrobku)}</td>
                        <td style="text-align: right;">${safeToFixed(item.celkova_potreba)} kg</td>
                        <td style="text-align: right;">${safeToFixed(item.aktualny_sklad)} kg</td>
                        <td><input type="number" class="planned-qty-input" value="${item.navrhovana_vyroba}" step="10" style="width: 80px; text-align: right; padding: 4px;"></td>
                        <td><select class="day-select" style="padding: 4px;">${dayOptions}</select></td>
                        <td style="text-align: center;"><input type="checkbox" class="priority-checkbox" style="width: 20px; height: 20px;"></td>
                        <td style="text-align: center;"><button class="btn-danger" style="padding:2px 8px; margin:0;" onclick="this.closest('tr').remove()">×</button></td>
                    </tr>`;
            });
            tableBodyHtml += `</tbody>`;
        }

        html = `
            <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                <p>Naplánujte výrobu priradením dňa a priority ku každej položke.</p>
                <button id="planner-settings-btn" class="btn-secondary" disabled title="Bude dostupné v ďalšom kroku"><i class="fas fa-cog"></i> Nastaviť predvolené dni</button>
            </div>
            <div class="table-container" style="max-height: 65vh;">
                <table>
                    <thead style="position: sticky; top: 0;">
                        <tr>
                            <th>Produkt</th>
                            <th>Potreba (Sklad+Obj.)</th>
                            <th>Sklad</th>
                            <th>Plánovaná výroba (kg)</th>
                            <th>Deň výroby</th>
                            <th>Priorita</th>
                            <th>Akcia</th>
                        </tr>
                    </thead>
                    ${tableBodyHtml}
                </table>
            </div>
            <button id="create-tasks-from-plan-btn" class="btn-success" style="width:100%; margin-top: 1rem;">
                <i class="fas fa-tasks"></i> Vytvoriť výrobné úlohy z plánu
            </button>
        `;
    }

    const onReady = () => {
        const btn = document.getElementById('create-tasks-from-plan-btn');
        if (btn) btn.onclick = createTasksFromPlan;
        // document.getElementById('planner-settings-btn').onclick = openPlannerSettingsModal; // Odkomentujeme v ďalšom kroku
    };
    return { html, onReady };
}

async function createTasksFromPlan() {
    const planData = [];
    const getNextDayOfWeek = (dayIndex) => { // 0=Mon, 1=Tue, ...
        const today = new Date();
        const resultDate = new Date(today);
        const currentDay = today.getDay(); // 0=Sun, 1=Mon, ..., 6=Sat
        const targetDay = dayIndex + 1; // JS Sunday is 0, we want Monday as 1
        let dayDifference = targetDay - (currentDay === 0 ? 7 : currentDay);
        if (dayDifference < 0) {
            dayDifference += 7;
        }
        resultDate.setDate(today.getDate() + dayDifference);
        return resultDate.toISOString().split('T')[0];
    };
    
    document.querySelectorAll('#modal-container tbody tr[data-product-name]').forEach((row) => {
        const dayValue = row.querySelector('.day-select').value;
        if (dayValue === 'Nenaplánované') return; // Skip unplanned items

        const dayIndex = ['Pondelok', 'Utorok', 'Streda', 'Štvrtok', 'Piatok'].indexOf(dayValue);
        const date = getNextDayOfWeek(dayIndex);
        
        planData.push({
            nazov_vyrobku: row.dataset.productName,
            navrhovana_vyroba: parseFloat(row.querySelector('.planned-qty-input').value),
            datum_vyroby: date,
            priorita: row.querySelector('.priority-checkbox').checked
        });
    });

    if (planData.length === 0) {
        showStatus("Žiadne výrobné úlohy nie sú naplánované na pracovné dni.", true);
        return;
    }

    try {
        await apiRequest('/api/kancelaria/createTasksFromPlan', { method: 'POST', body: planData });
        document.getElementById('modal-container').style.display = 'none';
    } catch (e) { 
        // Chyba je už spracovaná v apiRequest
    }
}

async function createPurchaseSuggestionsContent() {
    const suggestionsData = await apiRequest('/api/kancelaria/getPurchaseSuggestions');
    let html;
    if (!suggestionsData || suggestionsData.length === 0) {
        html = "<p>Nie je potrebné nič dokúpiť na základe plánu a minimálnych zásob.</p>";
    } else {
        let tableHtml = `<table><thead><tr><th>Surovina</th><th>Sklad (kg)</th><th>Potrebné pre výrobu (kg)</th><th>Min. zásoba (kg)</th><th class="gain">Odporúčaný nákup (kg)</th></tr></thead><tbody>`;
        suggestionsData.forEach(s => {
            tableHtml += `<tr>
                <td><strong>${escapeHtml(s.name)}</strong></td>
                <td>${safeToFixed(s.currentStock)}</td>
                <td>${safeToFixed(s.requiredForProduction)}</td>
                <td>${safeToFixed(s.minStock)}</td>
                <td class="gain">${safeToFixed(s.purchaseQty)}</td>
            </tr>`;
        });
        html = `<div class="table-container">${tableHtml}</tbody></table></div>`;
    }
    return { html };
}

async function createProductionStatsContent() {
    await ensureOfficeDataIsLoaded();
    const categories = ['Všetky', ...(officeInitialData.recipeCategories || [])];
    const categoryOptions = categories.map(c => `<option value="${c}">${c}</option>`).join('');
    const html = `<div style="display: flex; gap: 10px; align-items: end; flex-wrap: wrap;"><div style="flex-grow: 1; min-width: 200px;"><label for="stats-category-filter">Filtrovať kategóriu:</label><select id="stats-category-filter">${categoryOptions}</select></div><button id="load-stats-week-btn" class="btn-secondary" style="margin: 0; flex-shrink: 0;">Tento Týždeň</button><button id="load-stats-month-btn" class="btn-secondary" style="margin: 0; flex-shrink: 0;">Tento Mesiac</button></div><div id="production-stats-table-container" style="margin-top: 1.5rem;"></div><div id="production-damage-table-container" style="margin-top: 1.5rem;"></div>`;
    const onReady = () => {
        const weekBtn = document.getElementById('load-stats-week-btn');
        const monthBtn = document.getElementById('load-stats-month-btn');
        const categoryEl = document.getElementById('stats-category-filter');
        let currentPeriod = 'week';
        const loadStats = async () => {
            weekBtn.style.backgroundColor = currentPeriod === 'week' ? 'var(--primary-color)' : 'var(--secondary-color)';
            monthBtn.style.backgroundColor = currentPeriod === 'month' ? 'var(--primary-color)' : 'var(--secondary-color)';
            const category = categoryEl.value;
            const result = await apiRequest('/api/kancelaria/getProductionStats', { method: 'POST', body: { period: currentPeriod, category } });
            const container = document.getElementById('production-stats-table-container');
            if (!result.data || result.data.length === 0) {
                container.innerHTML = "<h4>Výroba</h4><p>Nenašli sa žiadne výrobné záznamy pre zvolené obdobie.</p>";
            } else {
                let tableHtml = `<h4>Výroba</h4><table><thead><tr><th>Dátum</th><th>Produkt</th><th>Plán</th><th>Realita</th><th>Výťažnosť</th><th>Cena/jed. bez E.</th><th>Cena/jed. s E.</th></tr></thead><tbody>`;
                result.data.forEach(d => {
                    const reality = d.unit === 'ks' ? `${d.realne_mnozstvo_ks} ks` : `${safeToFixed(d.realne_mnozstvo_kg)} kg`;
                    const yieldVal = d.vytaznost;
                    const yieldClass = yieldVal < 0 ? 'loss' : 'gain';
                    const yieldSign = yieldVal > 0 ? '+' : '';
                    tableHtml += `<tr><td>${new Date(d.datum_ukoncenia).toLocaleDateString('sk-SK')}</td><td>${escapeHtml(d.nazov_vyrobku)}</td><td>${safeToFixed(d.planovane_mnozstvo_kg)} kg</td><td>${reality}</td><td class="${yieldClass}">${yieldSign}${safeToFixed(yieldVal)} %</td><td>${safeToFixed(d.cena_bez_energii)} €/${d.unit}</td><td>${safeToFixed(d.cena_s_energiami)} €/${d.unit}</td></tr>`;
                });
                container.innerHTML = `<div class="table-container">${tableHtml}</tbody></table></div>`;
            }
            const damageContainer = document.getElementById('production-damage-table-container');
            if (result.damage_data && result.damage_data.length > 0) {
                let damageHtml = `<h4>Škody</h4><table><thead><tr><th>Dátum</th><th>Produkt</th><th>Množstvo</th><th>Pracovník</th><th>Dôvod</th><th>Náklady</th></tr></thead><tbody>`;
                result.damage_data.forEach(d => {
                    damageHtml += `<tr><td>${new Date(d.datum).toLocaleDateString('sk-SK')}</td><td>${escapeHtml(d.nazov_vyrobku)}</td><td>${escapeHtml(d.mnozstvo)}</td><td>${escapeHtml(d.pracovnik)}</td><td>${escapeHtml(d.dovod)}</td><td class="loss">${d.naklady_skody ? safeToFixed(d.naklady_skody) + ' €' : 'N/A'}</td></tr>`;
                });
                damageContainer.innerHTML = `<div class="table-container">${damageHtml}</tbody></table></div>`;
            } else {
                damageContainer.innerHTML = '<h4>Škody</h4><p>Nenašli sa žiadne záznamy o škodách.</p>';
            }
        };
        weekBtn.onclick = () => { currentPeriod = 'week'; loadStats(); };
        monthBtn.onclick = () => { currentPeriod = 'month'; loadStats(); };
        categoryEl.onchange = () => loadStats();
        loadStats();
    };
    return { html, onReady };
}

async function createPrintReportsContent() { 
    await ensureOfficeDataIsLoaded(); 
    const categories = ['Všetky', ...(officeInitialData.itemTypes || [])]; 
    const categoryOptions = categories.map(c => `<option value="${c}">${c}</option>`).join(''); 
    const today = new Date().toISOString().split('T')[0]; 
    const html = ` <h4>Report Príjmu Surovín</h4> <div style="display: flex; gap: 10px; align-items: end; flex-wrap: wrap;"> <div style="flex-grow: 1; min-width:200px;"><label for="report-receipt-category">Kategória:</label><select id="report-receipt-category">${categoryOptions}</select></div> <button id="gen-receipt-day-btn" class="btn-info" style="margin: 0;">Dnes</button> <button id="gen-receipt-week-btn" class="btn-info" style="margin: 0;">Týždeň</button> <button id="gen-receipt-month-btn" class="btn-info" style="margin: 0;">Mesiac</button> </div> <h4 style="margin-top: 2rem;">Report Inventúrnych Rozdielov Surovín</h4> <div style="display: flex; gap: 10px; align-items: end;"> <div style="flex-grow: 1;"><label for="report-inventory-date">Dátum inventúry:</label><input type="date" id="report-inventory-date" value="${today}"></div> <button id="gen-inventory-report-btn" class="btn-warning" style="margin: 0;">Tlačiť Report</button> </div>`; 
    const onReady = () => { 
        document.getElementById('gen-receipt-day-btn').onclick = () => generateReceiptReport('day'); 
        document.getElementById('gen-receipt-week-btn').onclick = () => generateReceiptReport('week'); 
        document.getElementById('gen-receipt-month-btn').onclick = () => generateReceiptReport('month'); 
        document.getElementById('gen-inventory-report-btn').onclick = generateInventoryReport; 
    }; 
    return { html, onReady }; 
}

function generateReceiptReport(period) { 
    const category = document.getElementById('report-receipt-category').value; 
    window.open(`/report/receipt?period=${period}&category=${encodeURIComponent(category)}`, '_blank'); 
}

function generateInventoryReport() { 
    const date = document.getElementById('report-inventory-date').value; 
    if (!date) return showStatus("Zvoľte dátum.", true); 
    window.open(`/report/inventory?date=${date}`, '_blank'); 
}

