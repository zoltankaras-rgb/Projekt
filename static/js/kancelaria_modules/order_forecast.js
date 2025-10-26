// =================================================================
// === SUB-MODUL KANCELÁRIA: EXPEDIČNÝ PLÁN (7-DŇOVÝ PREHĽAD) ===
// =================================================================

function initializeOrderForecastModule() {
    const container = document.getElementById('section-order-forecast');
    if (!container) return;

    // --- NOVÁ ŠTRUKTÚRA S TABMI ---
    container.innerHTML = `
        <div class="b2b-tab-nav" style="margin-bottom: 0;">
            <button class="b2b-tab-button active" data-tab="forecast">7-dňový Prehľad</button>
            <button class="b2b-tab-button" data-tab="purchase">Návrh Nákupu Tovaru</button>
            <button class="b2b-tab-button" data-tab="promotions">Správa Akcií</button>
        </div>
        <div style="border: 1px solid var(--medium-gray); border-top: none; padding: 1.5rem; border-radius: 0 0 var(--border-radius) var(--border-radius);">
            <div id="forecast-tab-content" class="b2b-tab-content active">
                <p>Tento prehľad zobrazuje celkovú potrebu produktov na základe prijatých B2B objednávok. Riadky s nedostatočným skladovým množstvom sú zvýraznené na červeno.</p>
                <div id="forecast-tables-container">Načítavam dáta...</div>
            </div>
            <div id="purchase-tab-content" class="b2b-tab-content">
                <p>Návrh na nákup tovarových položiek je vypočítaný na základe minimálnych zásob a rezervácií v objednávkach na nasledujúcich 7 dní.</p>
                <div id="purchase-suggestion-container">Načítavam dáta...</div>
            </div>
            <div id="promotions-tab-content" class="b2b-tab-content">
                 <div id="promotions-manager-container">Načítavam dáta...</div>
            </div>
        </div>
    `;

    container.querySelectorAll('.b2b-tab-button').forEach(button => {
        button.addEventListener('click', (e) => {
            container.querySelectorAll('.b2b-tab-button').forEach(btn => btn.classList.remove('active'));
            e.target.classList.add('active');
            
            container.querySelectorAll('.b2b-tab-content').forEach(content => content.classList.remove('active'));
            const targetTabId = `${e.target.dataset.tab}-tab-content`;
            document.getElementById(targetTabId).classList.add('active');

            // Načítanie dát pre aktívny tab
            switch(e.target.dataset.tab) {
                case 'forecast': loadAndRenderForecast(); break;
                case 'purchase': loadAndRenderPurchaseSuggestion(); break;
                case 'promotions': loadAndRenderPromotionsManager(); break;
            }
        });
    });

    // Načítanie dát pre prvý tab
    loadAndRenderForecast();
}

async function loadAndRenderForecast() {
    const container = document.getElementById('forecast-tables-container');
    container.innerHTML = '<p style="text-align: center; padding: 2rem;">Načítavam dáta...</p>';
    try {
        const data = await apiRequest('/api/kancelaria/get_7_day_forecast');
        
        if (!data.forecast || Object.keys(data.forecast).length === 0) {
            container.innerHTML = '<p style="text-align: center; padding: 2rem;">Na nasledujúcich 7 dní nie sú žiadne objednávky.</p>';
            return;
        }

        const { dates, forecast } = data;
        const formattedDates = dates.map(d => new Date(d).toLocaleDateString('sk-SK', { day: '2-digit', month: '2-digit' }));
        let finalHtml = '';

        for(const category in forecast) {
            finalHtml += `<h4 style="margin-top: 2rem;">${category}</h4>`;
            let tableHtml = `<div class="table-container" style="max-height: none;">
                <table style="table-layout: fixed;">
                    <thead>
                        <tr>
                            <th style="width: 25%;">Produkt</th><th style="width: 10%;">Sklad</th>
                            ${formattedDates.map(d => `<th style="width: 7%;">${d}</th>`).join('')}
                            <th style="width: 10%;">Potreba</th><th style="width: 10%;">Deficit</th><th style="width: 11%;">Akcia</th>
                        </tr>
                    </thead><tbody>`;
            
            forecast[category].forEach(product => {
                const isDeficit = product.deficit > 0;
                const deficitDisplay = isDeficit ? `${Math.ceil(product.deficit)} ${product.mj}` : '0';
                const actionButton = (isDeficit && product.isManufacturable) 
                    ? `<button class="btn-warning" style="padding: 5px 10px; margin: 0; width: auto;" onclick="openUrgentProductionModal('${escapeHtml(product.name)}', ${Math.ceil(product.deficit)})">Vytvoriť výrobu</button>` 
                    : '';

                tableHtml += `
                    <tr ${isDeficit ? 'style="background-color: #fee2e2;"' : ''}>
                        <td><strong>${product.name}</strong></td><td>${product.stock_display}</td>
                        ${dates.map(d => `<td>${product.daily_needs[d] > 0 ? `${product.daily_needs[d]} ${product.mj}`: ''}</td>`).join('')}
                        <td>${product.total_needed} ${product.mj}</td><td class="${isDeficit ? 'loss' : ''}">${deficitDisplay}</td><td>${actionButton}</td>
                    </tr>`;
            });
            tableHtml += '</tbody></table></div>';
            finalHtml += tableHtml;
        }
        container.innerHTML = finalHtml;
    } catch (e) {
        container.innerHTML = `<p class="error" style="padding: 2rem;">Chyba pri načítaní prehľadu: ${e.message}</p>`;
    }
}

async function loadAndRenderPurchaseSuggestion() {
    const container = document.getElementById('purchase-suggestion-container');
    container.innerHTML = '<p style="text-align: center; padding: 2rem;">Načítavam návrh nákupu...</p>';
    try {
        const suggestions = await apiRequest('/api/kancelaria/get_goods_purchase_suggestion');
        if (!suggestions || suggestions.length === 0) {
            container.innerHTML = '<p>Aktuálne nie je potrebné doobjednať žiadny tovar.</p>';
            return;
        }
        let tableHtml = `<div class="table-container" style="max-height: none;"><table><thead><tr><th>Názov Tovaru</th><th>Aktuálny Sklad</th><th>Min. Sklad</th><th>Rezervované</th><th>Návrh na Nákup</th><th>Poznámka</th></tr></thead><tbody>`;
        suggestions.forEach(item => {
            tableHtml += `
                <tr>
                    <td>${item.name}</td><td>${item.stock.toFixed(2)} ${item.unit}</td><td>${item.min_stock.toFixed(2)} ${item.unit}</td>
                    <td>${item.reserved.toFixed(2)} ${item.unit}</td><td class="loss">${item.suggestion.toFixed(2)} ${item.unit}</td>
                    <td>${item.is_promo ? '<span class="btn-danger" style="padding: 2px 6px; font-size: 0.8rem; border-radius: 4px; color: white;">PREBIEHA AKCIA!</span>' : ''}</td>
                </tr>`;
        });
        tableHtml += '</tbody></table></div>';
        container.innerHTML = tableHtml;
    } catch (e) {
        container.innerHTML = `<p class="error">${e.message}</p>`;
    }
}

async function loadAndRenderPromotionsManager() {
    const container = document.getElementById('promotions-manager-container');
    container.innerHTML = '<p style="text-align: center; padding: 2rem;">Načítavam správu akcií...</p>';
    try {
        const data = await apiRequest('/api/kancelaria/get_promotions_data');
        const { chains, promotions, products } = data;
        const today = new Date().toISOString().split('T')[0];

        const productOptions = products.map(p => `<option value="${p.ean}">${p.name}</option>`).join('');
        const chainOptions = chains.map(c => `<option value="${c.id}">${c.name}</option>`).join('');

        let promotionsHtml = promotions.map(p => `
            <tr>
                <td>${p.chain_name}</td><td>${p.product_name}</td><td>${new Date(p.start_date).toLocaleDateString('sk-SK')} - ${new Date(p.end_date).toLocaleDateString('sk-SK')}</td>
                <td>${parseFloat(p.sale_price_net).toFixed(2)} €</td>
                <td><button class="btn-danger" style="margin:0;padding:5px;" onclick="deletePromotion(${p.id})"><i class="fas fa-trash"></i></button></td>
            </tr>
        `).join('');

        container.innerHTML = `
            <div class="form-grid">
                <div>
                    <h4>Vytvoriť Novú Akciu</h4>
                    <form id="add-promotion-form">
                        <div class="form-group"><label>Obchodný Reťazec</label><select name="chain_id" required>${chainOptions}</select></div>
                        <div class="form-group"><label>Produkt v Akcii</label><select name="ean" required>${productOptions}</select></div>
                        <div class="form-grid"><div class="form-group"><label>Platnosť Od</label><input type="date" name="start_date" value="${today}" required></div><div class="form-group"><label>Platnosť Do</label><input type="date" name="end_date" value="${today}" required></div></div>
                        <div class="form-group"><label>Cena Počas Akcie (bez DPH)</label><input type="number" name="sale_price_net" step="0.01" required></div>
                        <button type="submit" class="btn-success" style="width:100%;">Uložiť Akciu</button>
                    </form>
                </div>
                <div>
                    <h4>Správa Obchodných Reťazcov</h4>
                    <ul id="chains-list">${chains.map(c => `<li>${c.name} <button onclick="manageChain('delete', ${c.id})" class="btn-danger" style="padding: 2px 6px; font-size: 0.8rem; margin-left: 10px;">X</button></li>`).join('')}</ul>
                    <div class="form-group" style="display:flex; gap: 10px; align-items: flex-end;">
                        <div style="flex-grow:1;"><label>Nový reťazec:</label><input type="text" id="new-chain-name"></div>
                        <button onclick="manageChain('add')" class="btn-primary" style="margin:0; height: 45px;">Pridať</button>
                    </div>
                </div>
            </div>
            <h4 style="margin-top: 2rem;">Prehľad Naplánovaných Akcií</h4>
            <div class="table-container" style="max-height: none;"><table><thead><tr><th>Reťazec</th><th>Produkt</th><th>Trvanie</th><th>Akciová Cena</th><th></th></tr></thead><tbody>${promotionsHtml}</tbody></table></div>
        `;
        document.getElementById('add-promotion-form').onsubmit = saveNewPromotion;
    } catch(e) {
        container.innerHTML = `<p class="error">${e.message}</p>`;
    }
}

async function saveNewPromotion(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const data = Object.fromEntries(formData.entries());
    try {
        await apiRequest('/api/kancelaria/save_promotion', { method: 'POST', body: data });
        e.target.reset();
        loadAndRenderPromotionsManager();
    } catch (err) {}
}

async function manageChain(action, id = null) {
    let data = { action };
    if (action === 'add') {
        data.name = document.getElementById('new-chain-name').value;
        if (!data.name) return;
    } else {
        data.id = id;
    }
    try {
        await apiRequest('/api/kancelaria/manage_promotion_chain', { method: 'POST', body: data });
        loadAndRenderPromotionsManager();
    } catch (err) {}
}

async function deletePromotion(id) {
    if (!confirm('Naozaj chcete vymazať túto akciu?')) return;
    try {
        await apiRequest('/api/kancelaria/delete_promotion', { method: 'POST', body: { id } });
        loadAndRenderPromotionsManager();
    } catch (err) {}
}

function openUrgentProductionModal(productName, requiredQty) {
    const today = new Date().toISOString().split('T')[0];
    const contentPromise = () => Promise.resolve({
        html: `
            <form id="urgent-production-form">
                <p>Vytvárate urgentnú výrobnú požiadavku pre produkt:</p>
                <h3 style="text-align: left; border: none; margin-bottom: 1rem;">${productName}</h3>
                <div class="form-group">
                    <label for="urgent-prod-qty">Požadované množstvo (kg):</label>
                    <input type="number" id="urgent-prod-qty" value="${requiredQty}" step="any" required>
                </div>
                <div class="form-group">
                    <label for="urgent-prod-date">Požadovaný dátum výroby:</label>
                    <input type="date" id="urgent-prod-date" value="${today}" required>
                </div>
                <button type="submit" class="btn-success" style="width: 100%;">Odoslať požiadavku do výroby</button>
            </form>
        `,
        onReady: () => {
            document.getElementById('urgent-production-form').onsubmit = async (e) => {
                e.preventDefault();
                const data = {
                    productName: productName,
                    quantity: document.getElementById('urgent-prod-qty').value,
                    productionDate: document.getElementById('urgent-prod-date').value
                };
                try {
                    await apiRequest('/api/kancelaria/create_urgent_task', { method: 'POST', body: data });
                    document.getElementById('modal-container').style.display = 'none';
                    loadAndRenderForecast();
                } catch (err) {}
            };
        }
    });
    showModal('Urgentná výrobná požiadavka', contentPromise);
}

