// =================================================================
// === LOGIKA PRE SUB-MODUL: ZISKOVOSŤ / NÁKLADY (kombinovaná verzia) ===
// =================================================================

let profitabilityState = {
    year: new Date().getFullYear(),
    month: new Date().getMonth() + 1,
    data: {},
    currentCalculation: null
};

function initializeProfitabilityModule() {
    const container = document.getElementById('section-profitability');
    if (!container) return;

    container.innerHTML = `
        <h3>Ziskovosť, Kanály a Kalkulácie</h3>
        <div style="display: flex; gap: 1rem; align-items: flex-end; margin-bottom: 1.5rem; flex-wrap: wrap;">
            <div class="form-group" style="margin-bottom: 0;"><label for="profit-year-select" style="margin-top: 0;">Rok:</label><select id="profit-year-select"></select></div>
            <div class="form-group" style="margin-bottom: 0;"><label for="profit-month-select" style="margin-top: 0;">Mesiac:</label><select id="profit-month-select"></select></div>
        </div>
        <div class="b2b-tab-nav" id="profit-main-nav">
             <button class="b2b-tab-button active" data-view="view-summary">Celkový Prehľad</button>
             <button class="b2b-tab-button" data-view="view-departments">Výnosy Oddelení</button>
             <button class="b2b-tab-button" data-view="view-production">Výnos Výroba</button>
             <button class="b2b-tab-button" data-view="view-sales-channels">Predajné Kanály</button>
             <button class="b2b-tab-button" data-view="view-calculations">Kalkulácie/Súťaže</button>
        </div>
        <div id="profitability-content" style="margin-top: 1.5rem;"><p>Vyberte rok a mesiac pre zobrazenie dát.</p></div>
    `;

    const yearSelect = document.getElementById('profit-year-select');
    const monthSelect = document.getElementById('profit-month-select');
    const currentYear = new Date().getFullYear();
    for (let i = currentYear; i >= currentYear - 3; i--) yearSelect.add(new Option(i, i));
    const monthNames = ["Január", "Február", "Marec", "Apríl", "Máj", "Jún", "Júl", "August", "September", "Október", "November", "December"];
    monthNames.forEach((name, index) => monthSelect.add(new Option(name, index + 1)));
    yearSelect.value = profitabilityState.year;
    monthSelect.value = profitabilityState.month;

    const loadData = () => {
        profitabilityState.year = yearSelect.value;
        profitabilityState.month = monthSelect.value;
        loadAndRenderProfitabilityData();
    };
    yearSelect.onchange = loadData;
    monthSelect.onchange = loadData;
    
    document.querySelectorAll('#profit-main-nav .b2b-tab-button').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('#profit-main-nav .b2b-tab-button').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            renderCurrentView();
        });
    });
    loadData();
}

async function loadAndRenderProfitabilityData() {
    const container = document.getElementById('profitability-content');
    container.innerHTML = `<p>Načítavam dáta za ${profitabilityState.month}/${profitabilityState.year}...</p>`;
    try {
        const data = await apiRequest(`/api/kancelaria/profitability/getData?year=${profitabilityState.year}&month=${profitabilityState.month}`);
        profitabilityState.data = data;
        renderCurrentView();
    } catch (e) {
        container.innerHTML = `<p class="error">Chyba pri načítaní dát ziskovosti: ${e.message}</p>`;
        profitabilityState.data = {}; // Vynulujeme dáta pri chybe
    }
}

function renderCurrentView() {
    const activeView = document.querySelector('#profit-main-nav .b2b-tab-button.active').dataset.view;
    const { department_data, sales_channels_view, calculations_view, production_view, calculations } = profitabilityState.data;

    switch(activeView) {
        case 'view-summary': renderSummaryView(calculations); break;
        case 'view-departments': renderDepartmentsView(department_data, calculations); break;
        case 'view-production': renderProductionView(production_view); break;
        case 'view-sales-channels': renderSalesChannelsView(sales_channels_view); break;
        case 'view-calculations': renderCalculationsView(calculations_view); break;
        default: document.getElementById('profitability-content').innerHTML = `<p>Neznámy pohľad.</p>`;
    }
}

function renderSalesChannelsView(data) {
    const container = document.getElementById('profitability-content');
    let html = `
       <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
           <h4>Prehľad predaja podľa kanálov</h4>
           <div>
               <button id="add-sales-channel-btn" class="btn-success" style="margin-right: 0.5rem;"><i class="fas fa-plus"></i> Nový kanál</button>
               <button class="btn-info" onclick="handlePrintProfitabilityReport('sales_channels')"><i class="fas fa-print"></i> Tlačiť Report</button>
           </div>
       </div>`;
    
    if (!data || Object.keys(data).length === 0) {
        html += '<p>Pre tento mesiac neboli nájdené žiadne dáta o predaji. Môžete vytvoriť nový predajný kanál.</p>';
    } else {
       for(const channel in data) {
           const channelData = data[channel];
           const summary = channelData.summary;
           let rowsHtml = (channelData.items || []).map(row => `
               <tr data-ean="${escapeHtml(row.product_ean)}">
                   <td>${escapeHtml(row.product_name)}</td>
                   <td><input type="number" class="sales-input" data-field="sales_kg" value="${row.sales_kg || ''}"></td>
                   <td><input type="number" step="0.0001" class="sales-input" data-field="purchase_price_net" value="${row.purchase_price_net || ''}"></td>
                   <td><input type="number" step="0.0001" class="sales-input" data-field="sell_price_net" value="${row.sell_price_net || ''}"></td>
                   <td>${safeToFixed(row.total_profit_eur)} €</td>
               </tr>
           `).join('');

           html += `
                <h5 style="margin-top: 1.5rem;">${escapeHtml(channel)}</h5>
                <div class="table-container" style="max-height: 60vh;">
                    <table class="sales-channel-table" data-channel="${escapeHtml(channel)}">
                        <thead>
                            <tr>
                                <th>Produkt</th>
                                <th>Predaj (kg)</th>
                                <th>Nákupná cena (€/kg)</th>
                                <th>Predajná cena (€/kg)</th>
                                <th>Celkový zisk (€)</th>
                            </tr>
                        </thead>
                        <tbody>${rowsHtml}</tbody>
                        <tfoot>
                            <tr class="total-row">
                                <td>SPOLU</td>
                                <td>${safeToFixed(summary.total_kg)}</td>
                                <td>${safeToFixed(summary.total_purchase, 2)} €</td>
                                <td>${safeToFixed(summary.total_sell, 2)} €</td>
                                <td>${safeToFixed(summary.total_profit, 2)} €</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
                <button class="btn-success" style="width:100%; margin-top: 1rem;" onclick="saveSalesChannelData('${escapeHtml(channel)}')">Uložiť dáta pre ${escapeHtml(channel)}</button>
            `;
       }
    }
    container.innerHTML = html;
    document.getElementById('add-sales-channel-btn').onclick = handleAddNewSalesChannel;
}


async function handleAddNewSalesChannel() {
    const channelName = prompt("Zadajte názov nového predajného kanálu (napr. Coop Jednota):");
    if (!channelName || channelName.trim() === "") return;
    try {
        await apiRequest('/api/kancelaria/profitability/setupSalesChannel', { method: 'POST', body: { year: profitabilityState.year, month: profitabilityState.month, channel_name: channelName.trim() } });
        loadAndRenderProfitabilityData();
    } catch (e) {}
}

async function saveSalesChannelData(channel) {
    const table = document.querySelector(`.sales-channel-table[data-channel="${channel}"]`);
    if (!table) return;
    const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr => {
        const ean = tr.dataset.ean;
        const rowData = { ean };
        tr.querySelectorAll('input.sales-input').forEach(input => {
            rowData[input.dataset.field] = input.value;
        });
        rowData['purchase_price_vat'] = 0;
        rowData['sell_price_vat'] = 0;
        return rowData;
    });
    try {
        await apiRequest('/api/kancelaria/profitability/saveSalesChannelData', { method: 'POST', body: { year: profitabilityState.year, month: profitabilityState.month, channel: channel, rows: rows } });
        loadAndRenderProfitabilityData();
    } catch(e) {}
}

function renderCalculationsView(data) {
    const container = document.getElementById('profitability-content');
    let html = `
        <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
            <h4>Prehľad kalkulácií a súťaží</h4>
            <div>
                <button id="add-calculation-btn" class="btn-success"><i class="fas fa-plus"></i> Nová kalkulácia</button>
                <button class="btn-info" onclick="handlePrintProfitabilityReport('calculations')"><i class="fas fa-print"></i> Tlačiť Report</button>
            </div>
        </div>`;
    
    if (!data || !data.calculations || data.calculations.length === 0) {
        html += '<p>Pre tento mesiac neboli vytvorené žiadne kalkulácie.</p>';
    } else {
        html += '<div class="table-container"><table><thead><tr><th>Názov</th><th>Položiek</th><th>Akcie</th></tr></thead><tbody>';
        data.calculations.forEach(calc => {
            html += `<tr><td>${escapeHtml(calc.name)}</td><td>${(calc.items || []).length}</td><td>
                <button class="btn-warning" style="margin:0; padding: 5px;" onclick='showCalculationModal(${JSON.stringify(calc)})'><i class="fas fa-edit"></i> Upraviť</button>
                <button class="btn-danger" style="margin:0; padding: 5px; margin-left: 5px;" onclick="handleDeleteCalculation(${calc.id})"><i class="fas fa-trash"></i> Vymazať</button>
            </td></tr>`;
        });
        html += '</tbody></table></div>';
    }
    container.innerHTML = html;
    document.getElementById('add-calculation-btn').onclick = () => showCalculationModal(null);
}

async function showCalculationModal(calculationData) {
    profitabilityState.currentCalculation = calculationData ? JSON.parse(JSON.stringify(calculationData)) : { id: null, name: '', items: [], vehicle_id: null, distance_km: 0 };
    
    if (!profitabilityState.data.calculations_view) {
        showStatus("Chyba: Dáta pre kalkulácie nie sú dostupné.", true);
        return;
    }
    const { available_products, available_vehicles, available_customers } = profitabilityState.data.calculations_view;
    
    const vehicleOptions = (available_vehicles || []).map(v => `<option value="${v.id}" data-cost-km="${v.cost_per_km}">${escapeHtml(v.name)} (${escapeHtml(v.license_plate)})</option>`).join('');
    const customerOptions = (available_customers || []).map(c => `<option value="${c.id}">${escapeHtml(c.nazov_firmy)}</option>`).join('');
    
    const modalContentPromise = () => Promise.resolve({
        html: document.getElementById('calculation-modal-template').innerHTML,
        onReady: () => {
            document.getElementById('calc-name').value = profitabilityState.currentCalculation.name;
            const vehicleSelect = document.getElementById('calc-vehicle');
            vehicleSelect.innerHTML = '<option value="">-- Nevybrané --</option>' + vehicleOptions;
            if (profitabilityState.currentCalculation.vehicle_id) vehicleSelect.value = profitabilityState.currentCalculation.vehicle_id;
            document.getElementById('calc-distance').value = profitabilityState.currentCalculation.distance_km || 0;
            document.getElementById('calc-customer-ref').innerHTML = '<option value="">-- Žiadny --</option>' + customerOptions;
            
            const productsByCategory = (available_products || []).reduce((acc, p) => {
                const category = p.predajna_kategoria || 'Nezaradené';
                if (!acc[category]) acc[category] = [];
                acc[category].push(p);
                return acc;
            }, {});

            let productHtml = '';
            for(const category in productsByCategory) {
                productHtml += `<h5>${escapeHtml(category)}</h5><table><tbody>`;
                productHtml += productsByCategory[category].map(p => `<tr style="cursor: pointer;" onclick="addProductToCalculation({ product_ean: '${p.ean}', product_name: '${escapeHtml(p.nazov_vyrobku)}', purchase_price_net: ${p.avg_cost || 0}, estimated_kg: 1 })"><td>${escapeHtml(p.nazov_vyrobku)}</td><td>${safeToFixed(p.avg_cost, 4)} €</td></tr>`).join('');
                productHtml += '</tbody></table>';
            }
            document.getElementById('available-products-container').innerHTML = productHtml;

            (profitabilityState.currentCalculation.items || []).forEach(item => addProductToCalculation(item));
            updateCalculationSummary();

            document.getElementById('product-search-input').oninput = (e) => {
                const searchTerm = e.target.value.toLowerCase();
                document.querySelectorAll('#available-products-container tbody tr').forEach(tr => tr.style.display = tr.textContent.toLowerCase().includes(searchTerm) ? '' : 'none');
                document.querySelectorAll('#available-products-container h5').forEach(h5 => {
                    const table = h5.nextElementSibling;
                    const hasVisibleRows = Array.from(table.querySelectorAll('tr')).some(tr => tr.style.display !== 'none');
                    h5.style.display = hasVisibleRows ? '' : 'none';
                });
            };
            document.getElementById('calc-vehicle').onchange = updateCalculationSummary;
            document.getElementById('calc-distance').oninput = updateCalculationSummary;
            document.getElementById('calculation-form').onsubmit = handleSaveCalculation;
        }
    });
    showModal(calculationData ? 'Upraviť kalkuláciu' : 'Nová kalkulácia', modalContentPromise);
}

function addProductToCalculation(productData) {
    const tbody = document.getElementById('calc-items-tbody');
    if (!tbody || tbody.querySelector(`tr[data-ean="${productData.product_ean}"]`)) return; 
    
    const newRow = document.createElement('tr');
    newRow.dataset.ean = productData.product_ean;
    newRow.dataset.name = productData.product_name;
    newRow.dataset.purchasePrice = productData.purchase_price_net;

    newRow.innerHTML = `<td>${escapeHtml(productData.product_name)}</td><td><input type="number" step="0.01" class="calc-input" data-field="estimated_kg" value="${productData.estimated_kg || '1'}"></td><td>${safeToFixed(productData.purchase_price_net, 4)}</td><td><input type="number" step="0.01" class="calc-input" data-field="sell_price_net" value="${productData.sell_price_net || ''}"></td><td class="row-profit">0.00</td><td><button type="button" class="btn-danger" style="padding: 5px; margin:0;" onclick="this.closest('tr').remove(); updateCalculationSummary();"><i class="fas fa-times"></i></button></td>`;
    tbody.appendChild(newRow);
    
    newRow.querySelectorAll('.calc-input').forEach(input => input.oninput = () => updateCalculationSummary());
    updateCalculationSummary();
}

function updateCalculationSummary() {
    let totalPurchase = 0, totalSell = 0;
    document.querySelectorAll('#calc-items-tbody tr').forEach(row => {
        const purchasePrice = parseFloat(row.dataset.purchasePrice) || 0;
        const estimatedKg = parseFloat(row.querySelector('[data-field="estimated_kg"]').value) || 0;
        const sellPrice = parseFloat(row.querySelector('[data-field="sell_price_net"]').value) || 0;
        const rowProfit = (sellPrice - purchasePrice) * estimatedKg;
        row.querySelector('.row-profit').textContent = safeToFixed(rowProfit);
        totalPurchase += purchasePrice * estimatedKg;
        totalSell += sellPrice * estimatedKg;
    });
    const vehicleSelect = document.getElementById('calc-vehicle');
    const selectedOption = vehicleSelect.options[vehicleSelect.selectedIndex];
    const costPerKm = parseFloat(selectedOption?.dataset.costKm) || 0;
    const distance = parseFloat(document.getElementById('calc-distance').value) || 0;
    const transportCost = costPerKm * distance * 2;
    const totalProfit = totalSell - totalPurchase;
    const finalProfit = totalProfit - transportCost;
    document.getElementById('summary-total-sell').textContent = `${safeToFixed(totalSell)} €`;
    document.getElementById('summary-total-purchase').textContent = `${safeToFixed(totalPurchase)} €`;
    document.getElementById('summary-transport-cost').textContent = `${safeToFixed(transportCost)} €`;
    document.getElementById('summary-final-profit').textContent = `${safeToFixed(finalProfit)} €`;
}
async function handleSaveCalculation(event) {
    event.preventDefault();
    const items = Array.from(document.querySelectorAll('#calc-items-tbody tr')).map(row => ({ product_ean: row.dataset.ean, estimated_kg: row.querySelector('[data-field="estimated_kg"]').value, purchase_price_net: row.dataset.purchasePrice, sell_price_net: row.querySelector('[data-field="sell_price_net"]').value }));
    const vehicleSelect = document.getElementById('calc-vehicle');
    const selectedOption = vehicleSelect.options[vehicleSelect.selectedIndex];
    const costPerKm = parseFloat(selectedOption?.dataset.costKm) || 0;
    const distance = parseFloat(document.getElementById('calc-distance').value) || 0;
    const dataToSave = { id: profitabilityState.currentCalculation.id, year: profitabilityState.year, month: profitabilityState.month, name: document.getElementById('calc-name').value, vehicle_id: document.getElementById('calc-vehicle').value, distance_km: distance, transport_cost: costPerKm * distance * 2, items: items };
    try {
        await apiRequest('/api/kancelaria/profitability/saveCalculation', { method: 'POST', body: dataToSave });
        document.getElementById('modal-container').style.display = 'none';
        loadAndRenderProfitabilityData();
    } catch (e) {}
}
async function handleDeleteCalculation(calcId) {
    showConfirmationModal({ title: 'Potvrdenie vymazania', message: 'Naozaj chcete natrvalo vymazať túto kalkuláciu?', warning: 'Táto akcia je nezvratná!', onConfirm: async () => { try { await apiRequest('/api/kancelaria/profitability/deleteCalculation', { method: 'POST', body: { id: calcId } }); loadAndRenderProfitabilityData(); } catch (e) {} } });
}
function renderProductionView(data) {
    const container = document.getElementById('profitability-content');
    if (!data) {
        container.innerHTML = '<h4>Prehľad ziskovosti výroby</h4><p class="error">Dáta pre ziskovosť výroby sa nepodarilo načítať.</p>';
        return;
    }
    let rowsHtml = data.rows.map(row => `<tr><td>${escapeHtml(row.name)}</td><td>${row.exp_stock_kg}</td><td><input type="number" step="0.01" class="profit-prod-input" data-ean="${row.ean}" data-field="expedition_sales_kg" value="${row.exp_sales_kg || ''}" style="width: 80px;"></td><td>${safeToFixed(row.production_cost, 4)} €</td><td><input type="number" step="0.0001" class="profit-prod-input" data-ean="${row.ean}" data-field="transfer_price" value="${row.transfer_price || ''}" style="width: 100px;"></td><td>${safeToFixed(row.profit)} €</td></tr>`).join('');
    container.innerHTML = `<div style="display:flex; justify-content: flex-end; margin-bottom: 1rem;"><button class="btn-info" onclick="handlePrintProfitabilityReport('production')"><i class="fas fa-print"></i> Tlačiť Report</button></div><h4>Prehľad ziskovosti výroby</h4><div class="table-container" style="max-height: 50vh;"><table id="production-profit-table"><thead><tr><th>Názov výrobku</th><th>Zásoba Expedícia [kg]</th><th>Predaj Expedícia [kg]</th><th>Výrobná cena [€/jed]</th><th>Príjem Exp. [€/jed]</th><th>Zisk Predané [€]</th></tr></thead><tbody>${rowsHtml}</tbody></table></div><button class="btn-success" style="width:100%; margin-top: 1rem;" onclick="saveProductionProfitData()">Uložiť dáta výroby</button><h4 style="margin-top: 2rem;">Súhrn výroby</h4><div class="form-group"><label for="worker-count-input">Počet pracovníkov vo výrobe:</label><input type="number" id="worker-count-input" value="1" style="width: 100px;"></div><div class="table-container"><table><tbody><tr><td>Spolu KG predané (vrátane pohárov)</td><td id="summary-total-kg">${safeToFixed(data.summary.total_kg)} kg</td></tr><tr><td>Spolu KG bez pohárov, mastí a krájaných</td><td id="summary-total-kg-no-pkg">${safeToFixed(data.summary.total_kg_no_pkg)} kg</td></tr><tr><td>Poháre 200g</td><td>${Math.round(data.summary.jars_200)} ks</td></tr><tr><td>Poháre 500g</td><td>${Math.round(data.summary.jars_500)} ks</td></tr><tr><td>Viečka spolu</td><td>${Math.round(data.summary.lids)} ks</td></tr><tr><td>Produkcia na 1 pracovníka / deň</td><td id="summary-prod-per-worker"></td></tr></tbody></table></div>`;
    const workerInput = document.getElementById('worker-count-input');
    const updateProductivity = () => { const workers = parseInt(workerInput.value) || 1; const daysInMonth = new Date(profitabilityState.year, profitabilityState.month, 0).getDate(); const productivity = data.summary.total_kg / daysInMonth / workers; document.getElementById('summary-prod-per-worker').textContent = `${safeToFixed(productivity)} kg`; };
    workerInput.oninput = updateProductivity;
    updateProductivity();
}
function renderDepartmentsView(data, calculations) {
    const container = document.getElementById('profitability-content');
    if (!data || !calculations) {
        container.innerHTML = '<h4>Výnosy Oddelení</h4><p class="error">Dáta pre výnosy oddelení sa nepodarilo načítať.</p>';
        return;
    }
    container.innerHTML = `<div style="display:flex; justify-content: flex-end; margin-bottom: 1rem;"><button class="btn-info" onclick="handlePrintProfitabilityReport('departments')"><i class="fas fa-print"></i> Tlačiť Report</button></div><div class="form-grid"><div><h4>Výnos Expedícia</h4><div class="form-group"><label>Zásoba (predch. mesiac) [€]</label><input type="number" step="0.01" id="exp_stock_prev" value="${data.exp_stock_prev || ''}"></div><div class="form-group"><label>Tovar z rozrábky [€]</label><input type="number" step="0.01" id="exp_from_butchering" value="${data.exp_from_butchering || ''}"></div><div class="form-group"><label>Tovar z výroby [€]</label><input type="number" step="0.01" id="exp_from_prod" value="${data.exp_from_prod || ''}"></div><div class="form-group"><label>Tovar cudzí [€]</label><input type="number" step="0.01" id="exp_external" value="${data.exp_external || ''}"></div><div class="form-group"><label>Vrátený tovar [€]</label><input type="number" step="0.01" id="exp_returns" value="${data.exp_returns || ''}"></div><div class="form-group"><label>Zásoba (aktuálny mesiac) [€]</label><input type="number" step="0.01" id="exp_stock_current" value="${data.exp_stock_current || ''}"></div><div class="form-group"><label>Tržba (aktuálny mesiac) [€]</label><input type="number" step="0.01" id="exp_revenue" value="${data.exp_revenue || ''}"></div><div class="stat-card"><h5>Vypočítaný zisk z expedície</h5><p>${safeToFixed(calculations.expedition_profit)} €</p></div></div><div><h4>Výnos Rozrábka</h4><div class="form-group"><label>Mäso z rozrábky [€]</label><input type="number" step="0.01" id="butcher_meat_value" value="${data.butcher_meat_value || ''}"></div><div class="form-group"><label>Zaplatený tovar [€]</label><input type="number" step="0.01" id="butcher_paid_goods" value="${data.butcher_paid_goods || ''}"></div><div class="form-group"><label>Rozrábka [€]</label><input type="number" step="0.01" id="butcher_process_value" value="${data.butcher_process_value || ''}"></div><div class="form-group"><label>Vrátenka [€]</label><input type="number" step="0.01" id="butcher_returns_value" value="${data.butcher_returns_value || ''}"></div><div class="stat-card"><h5>Zisk (Mäso - Zaplatené)</h5><p>${safeToFixed(calculations.butchering_profit)} €</p></div><div class="stat-card" style="margin-top:1rem;"><h5>Precenenie (Rozrábka + Vrátenka)</h5><p>${safeToFixed(calculations.butchering_revaluation)} €</p></div></div></div><button class="btn-success" style="width:100%; margin-top: 1.5rem;" onclick="saveDepartmentData()">Uložiť dáta oddelení</button>`;
}
function renderSummaryView(calculations) {
    const container = document.getElementById('profitability-content');
    if (!calculations) {
        container.innerHTML = '<h4>Celkový Prehľad Ziskovosti</h4><p class="error">Dáta pre celkový prehľad sa nepodarilo načítať.</p>';
        return;
    }
    container.innerHTML = `<div style="display:flex; justify-content: flex-end; margin-bottom: 1rem;"><button class="btn-info" onclick="handlePrintProfitabilityReport('summary')"><i class="fas fa-print"></i> Tlačiť Report</button></div><h4>Celkový Prehľad Ziskovosti</h4><div class="table-container"><table><tbody><tr><td>Zisk z Expedície</td><td>${safeToFixed(calculations.expedition_profit)} €</td></tr><tr><td>Zisk z Rozrábky</td><td>${safeToFixed(calculations.butchering_profit)} €</td></tr><tr><td>Zisk z Výroby</td><td>${safeToFixed(calculations.production_profit)} €</td></tr><tr style="font-weight: bold;"><td>Celkové náklady</td><td><input type="number" step="0.01" id="general_costs_summary" value="${(profitabilityState.data.department_data || {}).general_costs || ''}"></td></tr><tr style="font-weight: bold; font-size: 1.2rem; background-color: var(--light-gray);"><td>Celkový Firemný Zisk</td><td>${safeToFixed(calculations.total_profit)} €</td></tr></tbody></table></div><button class="btn-success" style="width:100%; margin-top: 1rem;" onclick="saveDepartmentData()">Uložiť celkové náklady</button>`;
}
async function saveDepartmentData() {
    const data = { year: profitabilityState.year, month: profitabilityState.month, exp_stock_prev: document.getElementById('exp_stock_prev')?.value, exp_from_butchering: document.getElementById('exp_from_butchering')?.value, exp_from_prod: document.getElementById('exp_from_prod')?.value, exp_external: document.getElementById('exp_external')?.value, exp_returns: document.getElementById('exp_returns')?.value, exp_stock_current: document.getElementById('exp_stock_current')?.value, exp_revenue: document.getElementById('exp_revenue')?.value, butcher_meat_value: document.getElementById('butcher_meat_value')?.value, butcher_paid_goods: document.getElementById('butcher_paid_goods')?.value, butcher_process_value: document.getElementById('butcher_process_value')?.value, butcher_returns_value: document.getElementById('butcher_returns_value')?.value, general_costs: document.getElementById('general_costs_summary')?.value || document.querySelector('#profitability-content input[type="number"][id^="general_costs"]')?.value, };
    try { await apiRequest('/api/kancelaria/profitability/saveDepartmentData', { method: 'POST', body: data }); loadAndRenderProfitabilityData(); } catch (e) {}
}
async function saveProductionProfitData() {
    const rows = Array.from(document.querySelectorAll('#production-profit-table tbody tr')).map(tr => ({ ean: tr.querySelector('.profit-prod-input').dataset.ean, expedition_sales_kg: tr.querySelector('[data-field="expedition_sales_kg"]').value, transfer_price: tr.querySelector('[data-field="transfer_price"]').value }));
    try { await apiRequest('/api/kancelaria/profitability/saveProductionData', { method: 'POST', body: { year: profitabilityState.year, month: profitabilityState.month, rows: rows } }); loadAndRenderProfitabilityData(); } catch(e) {}
}
function handlePrintProfitabilityReport(reportType) {
    const { year, month } = profitabilityState;
    window.open(`/report/profitability?year=${year}&month=${month}&type=${reportType}`, '_blank');
}

