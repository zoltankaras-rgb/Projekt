// =================================================================
// === SUB-MODUL KANCELÁRIA: B2C ADMINISTRÁCIA (VYLEPŠENÁ VERZIA) ===
// =================================================================

function initializeB2CAdminModule() {
    const container = document.getElementById('section-b2c-admin');
    if (!container) return;
    container.innerHTML = `
        <h3>B2C Administrácia</h3>
        <div class="b2b-tab-nav">
            <button class="b2b-tab-button active" data-b2c-tab="b2c-orders-tab">Prehľad Objednávok</button>
            <button class="b2b-tab-button" data-b2c-tab="b2c-customers-tab">Zoznam Zákazníkov</button>
            <button class="b2b-tab-button" data-b2c-tab="b2c-pricelist-tab">Správa Cenníka</button>
            <button class="b2b-tab-button" data-b2c-tab="b2c-rewards-tab">Správa Odmien</button>
        </div>
        <div id="b2c-orders-tab" class="b2b-tab-content active"><p>Načítavam objednávky...</p></div>
        <div id="b2c-customers-tab" class="b2b-tab-content"><p>Načítavam zákazníkov...</p></div>
        <div id="b2c-pricelist-tab" class="b2b-tab-content"><p>Načítavam cenník...</p></div>
        <div id="b2c-rewards-tab" class="b2b-tab-content"><p>Načítavam odmeny...</p></div>
    `;

    container.querySelectorAll('.b2b-tab-button').forEach(button => {
        button.addEventListener('click', (e) => {
            container.querySelectorAll('.b2b-tab-button').forEach(btn => btn.classList.remove('active'));
            e.target.classList.add('active');
            const targetTabId = e.target.dataset.b2cTab;
            container.querySelectorAll('.b2b-tab-content').forEach(content => content.classList.toggle('active', content.id === targetTabId));
            
            switch(targetTabId) {
                case 'b2c-orders-tab': loadB2COrders(); break;
                case 'b2c-customers-tab': loadB2CCustomers(); break;
                case 'b2c-pricelist-tab': loadB2CPricelistAdmin(); break;
                case 'b2c-rewards-tab': loadB2CRewardsAdmin(); break;
            }
        });
    });
    loadB2COrders();
}

async function loadB2COrders() {
    const container = document.getElementById('b2c-orders-tab');
    container.innerHTML = '<p>Načítavam B2C objednávky...</p>';
    try {
        const orders = await apiRequest('/api/kancelaria/b2c/get_orders');
        if (!orders || orders.length === 0) { container.innerHTML = '<p>Žiadne B2C objednávky neboli nájdené.</p>'; return; }
        
        let tableHtml = `<div class="table-container"><table><thead><tr><th>Číslo obj.</th><th>Zákazník</th><th>Dátum dodania</th><th>Suma (Predb./Finálna)</th><th>Stav</th><th>Akcie</th></tr></thead><tbody>`;
        orders.forEach(order => {
            const orderDate = new Date(order.datum_objednavky).toLocaleDateString('sk-SK');
            const deliveryDate = new Date(order.pozadovany_datum_dodania).toLocaleDateString('sk-SK');
            
            let priceDisplay = `${parseFloat(order.predpokladana_suma_s_dph).toFixed(2)} €`;
            if (order.finalna_suma_s_dph) {
                priceDisplay += `<br><strong class="gain">${parseFloat(order.finalna_suma_s_dph).toFixed(2)} €</strong>`;
            }

            // START CHANGE: Logika pre tlačidlá
            const statusColors = { 'Prijatá': '#3b82f6', 'Pripravená': '#f59e0b', 'Hotová': '#16a34a', 'Zrušená': '#ef4444' };
            let statusDisplay = `<span style="font-weight:bold; color: ${statusColors[order.stav] || '#6b7280'}">${order.stav}</span>`;
            
            let actionsHtml = `<button class="btn-info" style="margin:0 5px 0 0; padding: 5px;" onclick='showB2COrderDetailModal(${JSON.stringify(order)})'><i class="fas fa-search"></i></button>`;
            
            if (order.stav === 'Prijatá') {
                actionsHtml += `<button class="btn-primary" style="margin:0 5px 0 0; padding: 5px;" title="Pripraviť objednávku (zadať finálnu cenu)" onclick="finalizeB2COrder(${order.id}, '${order.cislo_objednavky}')">Pripraviť</button>`;
            }
            if (order.stav === 'Pripravená') {
                actionsHtml += `<button class="btn-success" style="margin:0 5px 0 0; padding: 5px;" title="Objednávka vyplatená, uzavrieť a pripísať body" onclick="completeB2COrder(${order.id})">Hotová</button>`;
            }
            if (order.stav !== 'Hotová' && order.stav !== 'Zrušená') {
                actionsHtml += `<button class="btn-danger" style="margin:0; padding: 5px;" title="Zrušiť objednávku" onclick="cancelB2COrder(${order.id})"><i class="fas fa-times"></i></button>`;
            }
            // END CHANGE

            tableHtml += `<tr>
                    <td>${order.cislo_objednavky}<br><small>${orderDate}</small></td>
                    <td>${order.zakaznik_meno}</td>
                    <td>${deliveryDate}</td>
                    <td>${priceDisplay}</td>
                    <td>${statusDisplay}</td>
                    <td><div style="display:flex;">${actionsHtml}</div></td>
                </tr>`;
        });
        container.innerHTML = tableHtml + '</tbody></table></div>';
    } catch (e) { container.innerHTML = `<p class="error">Chyba pri načítaní B2C objednávok: ${e.message}</p>`; }
}

function showB2COrderDetailModal(order) {
    console.log("👉 RAW hodnoty order.polozky:", order.polozky);

    let items = [];

    try {
        if (typeof order.polozky === 'string') {
            items = JSON.parse(order.polozky);
            console.log("✅ Parsed JSON string na pole:", items);
        } else if (Array.isArray(order.polozky)) {
            items = order.polozky;
            console.log("✅ Položky sú pole:", items);
        } else {
            console.warn("⚠️ Položky nie sú ani string ani pole:", order.polozky);
        }
    } catch (e) {
        console.error("❌ Chyba pri JSON.parse:", e);
        items = [];
    }

    // EŠTE JEDNA OCHRANA
    if (!Array.isArray(items)) {
        console.warn("❌ Položky objednávky po spracovaní nie sú pole. Výstup:", items);
        items = [];
    }

    // Teraz bezpečne generujeme HTML
    let itemsHtml = '<ul>';
    items.forEach(item => {
        const name = item.name || 'Nepomenovaný produkt';
        const quantity = item.quantity || '?';
        const unit = item.unit || '';
        const note = item.poznamka_k_polozke || item.item_note || '';

        let detail = `${name} - ${quantity} ${unit}`;
        if (note) {
            detail += ` <i>(${note})</i>`;
        }
        itemsHtml += `<li>${detail}</li>`;
    });
    itemsHtml += '</ul>';

    if (order.uplatnena_odmena_poznamka) {
        itemsHtml += `<p style="color:var(--success-color); font-weight: bold;">Uplatnená odmena: ${order.uplatnena_odmena_poznamka}</p>`;
    }

   showModal(`Detail objednávky #${order.cislo_objednavky}`, () => Promise.resolve({
    html: itemsHtml + `
        <div style="text-align: right; margin-top: 1rem;">
            <button onclick="printOrderDetail()" class="btn-info">
                🖨️ Vytlačiť ako PDF
            </button>
        </div>
    `
}));

}
function printOrderDetail() {
    const modalContent = document.querySelector('#modal-container .modal-body');
    const printWindow = window.open('', '_blank');

    if (!modalContent || !printWindow) return;

    const html = `
    <html>
    <head>
        <title>Detail objednávky</title>
        <style>
            body { font-family: sans-serif; padding: 20px; }
            ul { padding-left: 20px; }
            li { margin-bottom: 0.5rem; }
            h1 { font-size: 1.4rem; margin-bottom: 1rem; }
        </style>
    </head>
    <body>
        <h1>Detail objednávky</h1>
        ${modalContent.innerHTML}
    </body>
    </html>
    `;

    printWindow.document.write(html);
    printWindow.document.close();
    printWindow.focus();
    printWindow.print();
}


async function finalizeB2COrder(orderId, orderNumber) {
    const finalPriceRaw = prompt(`KROK 1/2: Zadajte finálnu sumu s DPH po prevážení pre objednávku #${orderNumber}:`);
    if (finalPriceRaw === null) return; 
    const finalPrice = finalPriceRaw.replace(',', '.');
    try {
        await apiRequest('/api/kancelaria/b2c/finalize_order', {
            method: 'POST', body: { order_id: orderId, final_price: finalPrice }
        });
        loadB2COrders();
    } catch (e) {}
}

async function completeB2COrder(orderId) {
    showConfirmationModal({
        title: 'Potvrdenie Platby a Pripísanie Bodov',
        message: 'Potvrdzujete, že objednávka bola zákazníkom vyplatená v hotovosti? Týmto krokom sa zákazníkovi pripíšu vernostné body a objednávka sa označí ako "Hotová".',
        warning: 'Táto akcia je nezvratná!',
        onConfirm: async () => {
            try {
                await apiRequest('/api/kancelaria/b2c/credit_points', { method: 'POST', body: { order_id: orderId } });
                loadB2COrders();
            } catch (e) {}
        }
    });
}

async function cancelB2COrder(orderId) {
    const reason = prompt("Zadajte dôvod zrušenia objednávky (tento text bude odoslaný zákazníkovi):");
    if (reason === null || reason.trim() === "") {
        showStatus("Zrušenie bolo prerušené, dôvod nebol zadaný.", true);
        return;
    }
    showConfirmationModal({
        title: 'Potvrdenie zrušenia', message: 'Naozaj chcete zrušiť túto objednávku?',
        onConfirm: async () => {
            try {
                await apiRequest('/api/kancelaria/b2c/cancel_order', { method: 'POST', body: { order_id: orderId, reason: reason.trim() } });
                loadB2COrders();
            } catch (e) {}
        }
    });
}
function showB2COrderDetailModal(order) {
    let items = [];

    try {
        if (typeof order.polozky === 'string') {
            items = JSON.parse(order.polozky);
        } else if (Array.isArray(order.polozky)) {
            items = order.polozky;
        }
    } catch (e) {
        console.error("Chyba pri parsovaní položiek:", e);
        items = [];
    }

    if (!Array.isArray(items)) {
        console.warn("Položky nie sú pole:", items);
        items = [];
    }

    // 🧾 Začneme tabuľkou
    let itemsHtml = `
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr>
                    <th style="text-align:left; border-bottom: 1px solid #ccc;">Produkt</th>
                    <th style="text-align:left; border-bottom: 1px solid #ccc;">Množstvo</th>
                    <th style="text-align:left; border-bottom: 1px solid #ccc;">Jednotka</th>
                    <th style="text-align:left; border-bottom: 1px solid #ccc;">Poznámka k položke</th>
                </tr>
            </thead>
            <tbody>
    `;

    items.forEach(item => {
        const name = item.name || 'Neznámy produkt';
        const qty = item.quantity ?? '?';
        const unit = item.unit || '';
        const note = item.poznamka_k_polozke || item.item_note || '-';

        itemsHtml += `
            <tr>
                <td>${name}</td>
                <td>${qty}</td>
                <td>${unit}</td>
                <td>${note}</td>
            </tr>
        `;
    });

    itemsHtml += `
            </tbody>
        </table>
    `;

    // 📝 Poznámka k objednávke (ak existuje)
    if (order.poznamka) {
        itemsHtml += `
            <p style="margin-top: 1rem;">
                <strong>Poznámka k objednávke:</strong><br>
                <em>${order.poznamka}</em>
            </p>
        `;
    }

    // 🏆 Uplatnená odmena (ak je)
    if (order.uplatnena_odmena_poznamka) {
        itemsHtml += `
            <p style="color: var(--success-color); font-weight: bold;">
                Uplatnená odmena: ${order.uplatnena_odmena_poznamka}
            </p>
        `;
    }

    // 🖨️ Tlačidlo
    itemsHtml += `
        <div style="text-align: right; margin-top: 1.5rem;">
            <button onclick="printOrderDetail()" class="btn-info">
                🖨️ Vytlačiť ako PDF
            </button>
        </div>
    `;

    showModal(`Detail objednávky #${order.cislo_objednavky}`, () => Promise.resolve({ html: itemsHtml }));
}



// ... (zvyšok súboru zostáva rovnaký) ...
async function creditB2CPoints(orderId) {
    // Tento kód sa teraz volá, keď admin zmení stav na "Hotová"
    showConfirmationModal({
        title: 'Pripísanie Vernostných Bodov a Uzavretie Objednávky',
        message: 'Zmenili ste stav na "Hotová". Týmto krokom sa zákazníkovi pripíšu body podľa finálnej ceny a objednávka sa presunie do histórie. Tento krok je nezvratný.',
        onConfirm: async () => {
            try {
                // Zavoláme API, ktoré zmení stav a zároveň pripíše body
                await apiRequest('/api/kancelaria/b2c/update_order_status', { 
                    method: 'POST', 
                    body: { order_id: orderId, status: 'Hotová' } 
                });
                loadB2COrders(); // Znova načíta objednávky, aby táto zmizla z prehľadu
            } catch (e) {}
        }
    });
}

async function loadB2CCustomers() {
    const container = document.getElementById('b2c-customers-tab');
    container.innerHTML = '<p>Načítavam B2C zákazníkov...</p>';
    try {
        const customers = await apiRequest('/api/kancelaria/b2c/get_customers');
        if (!customers || customers.length === 0) { container.innerHTML = '<p>Žiadni B2C zákazníci neboli nájdení.</p>'; return; }
        
        let tableHtml = `<div class="table-container"><table><thead><tr><th>ID</th><th>Meno</th><th>Kontakt</th><th>Adresy</th><th>Vernostné body</th></tr></thead><tbody>`;
        customers.forEach(cust => {
            tableHtml += `<tr>
                    <td>${cust.zakaznik_id}</td>
                    <td>${escapeHtml(cust.nazov_firmy)}</td>
                    <td>${escapeHtml(cust.email)}<br>${escapeHtml(cust.telefon)}</td>
                    <td><b>Fakturačná:</b> ${escapeHtml(cust.adresa)}<br><b>Doručovacia:</b> ${escapeHtml(cust.adresa_dorucenia)}</td>
                    <td>${cust.vernostne_body}</td>
                </tr>`;
        });
        container.innerHTML = tableHtml + '</tbody></table></div>';
    } catch(e) { container.innerHTML = `<p class="error">Chyba pri načítaní B2C zákazníkov: ${e.message}</p>`; }
}

async function loadB2CPricelistAdmin() {
    const container = document.getElementById('b2c-pricelist-tab');
    container.innerHTML = '<p>Načítavam B2C cenník...</p>';
    try {
        const data = await apiRequest('/api/kancelaria/b2c/get_pricelist_admin');
        const { pricelist, all_products } = data;
        
        const productsByCategory = all_products.reduce((acc, p) => {
            const category = p.predajna_kategoria || 'Nezaradené';
            if (!acc[category]) acc[category] = [];
            acc[category].push(p);
            return acc;
        }, {});

        let availableProductsHtml = '<h4>Dostupné produkty na pridanie</h4><input type="text" id="product-search" placeholder="Hľadať produkt..." style="margin-bottom: 1rem;"><div class="table-container" style="max-height: 50vh;">';
        for (const category in productsByCategory) {
            availableProductsHtml += `<h5>${category}</h5>`;
            productsByCategory[category].forEach(p => {
                availableProductsHtml += `<div class="add-product-row" data-ean="${p.ean}" data-name="${escapeHtml(p.nazov_vyrobku)}" data-dph="${p.dph}">${escapeHtml(p.nazov_vyrobku)}</div>`;
            });
        }
        availableProductsHtml += '</div>';

        let pricelistTableHtml = `<h4>Aktuálny B2C Cenník</h4><div class="table-container" style="max-height: 50vh;"><table id="b2c-pricelist-table"><thead><tr><th>Produkt</th><th>Cena bez DPH</th><th>Akcia?</th><th>Akciová Cena</th><th>Odstrániť</th></tr></thead><tbody></tbody></table></div>`;
        
        container.innerHTML = `<div class="form-grid"><div>${availableProductsHtml}</div><div>${pricelistTableHtml}</div></div><button class="btn-success" style="width: 100%; margin-top: 1rem;" onclick="saveB2CPricelistChanges()">Uložiť zmeny v cenníku</button>`;
        
        const pricelistEans = new Set(pricelist.map(item => item.ean_produktu));
        pricelist.forEach(item => addProductToAdminPricelist(item, false));
        
        container.querySelectorAll('.add-product-row').forEach(row => {
            if (pricelistEans.has(row.dataset.ean)) {
                row.classList.add('hidden');
            }
            row.addEventListener('click', () => {
                const productData = { ean_produktu: row.dataset.ean, nazov_vyrobku: row.dataset.name, dph: row.dataset.dph, cena_bez_dph: 0 };
                addProductToAdminPricelist(productData, true);
                row.classList.add('hidden');
            });
        });
        
        document.getElementById('product-search').addEventListener('input', (e) => {
            const searchTerm = e.target.value.toLowerCase();
            document.querySelectorAll('.add-product-row').forEach(row => {
                const isVisible = row.textContent.toLowerCase().includes(searchTerm);
                row.style.display = isVisible ? 'block' : 'none';
            });
        });

    } catch (e) { container.innerHTML = `<p class="error">Chyba pri načítaní cenníka: ${e.message}</p>`; }
}

function addProductToAdminPricelist(itemData, isNew) {
    const tableBody = document.querySelector('#b2c-pricelist-table tbody');
    const newRow = tableBody.insertRow();
    newRow.dataset.ean = itemData.ean_produktu;
    
    // Zabezpečíme, že cena je vždy číslo
    const cenaBezDph = parseFloat(itemData.cena_bez_dph || 0);

    const isAkcia = isNew ? false : itemData.je_v_akcii;
    const salePrice = isNew ? '' : (itemData.akciova_cena_bez_dph || '');

    newRow.innerHTML = `
        <td>${escapeHtml(itemData.nazov_vyrobku)}</td>
        <td><input type="number" step="0.01" class="pricelist-input-price" value="${cenaBezDph.toFixed(2)}"></td>
        <td><input type="checkbox" class="is-akcia-checkbox" ${isAkcia ? 'checked' : ''} onchange="toggleSalePriceInput(this)"></td>
        <td><input type="number" step="0.01" class="sale-price-input" value="${salePrice ? parseFloat(salePrice).toFixed(2) : ''}" ${!isAkcia ? 'disabled' : ''}></td>
        <td><button class="btn-danger" style="padding:2px 8px; margin:0;" onclick="removeProductFromB2CPricelist(this)">X</button></td>
    `;
}

function toggleSalePriceInput(checkbox) {
    const row = checkbox.closest('tr');
    const salePriceInput = row.querySelector('.sale-price-input');
    salePriceInput.disabled = !checkbox.checked;
    if (!checkbox.checked) {
        salePriceInput.value = '';
    }
}

function removeProductFromB2CPricelist(button) {
    const row = button.closest('tr');
    const ean = row.dataset.ean;
    row.remove();
    const availableRow = document.querySelector(`.add-product-row[data-ean="${ean}"]`);
    if (availableRow) availableRow.classList.remove('hidden');
}

async function saveB2CPricelistChanges() {
    const rows = document.querySelectorAll('#b2c-pricelist-table tbody tr');
    const items_to_save = [];
    rows.forEach(row => {
        const isAkciaCheckbox = row.querySelector('.is-akcia-checkbox');
        items_to_save.push({
            ean: row.dataset.ean,
            price: row.querySelector('.pricelist-input-price').value,
            is_akcia: isAkciaCheckbox.checked,
            sale_price: row.querySelector('.sale-price-input').value
        });
    });
    try {
        await apiRequest('/api/kancelaria/b2c/update_pricelist', { method: 'POST', body: { items: items_to_save } });
    } catch (e) {}
}

async function loadB2CRewardsAdmin() {
    const container = document.getElementById('b2c-rewards-tab');
    container.innerHTML = '<p>Načítavam odmeny...</p>';
    try {
        const rewards = await apiRequest('/api/kancelaria/b2c/get_rewards');
        
        let rewardsTableHtml = 'Žiadne odmeny neboli definované.';
        if (rewards && rewards.length > 0) {
            rewardsTableHtml = `<table><thead><tr><th>Názov odmeny</th><th>Potrebné body</th><th>Stav</th><th>Akcia</th></tr></thead><tbody>`;
            rewards.forEach(r => {
                rewardsTableHtml += `<tr>
                    <td>${escapeHtml(r.nazov_odmeny)}</td>
                    <td>${r.potrebne_body}</td>
                    <td>${r.je_aktivna ? '<span class="gain">Aktívna</span>' : '<span class="loss">Neaktívna</span>'}</td>
                    <td>
                        <button class="btn-warning" style="margin:0; padding: 5px;" onclick="toggleB2CRewardStatus(${r.id}, ${r.je_aktivna})">
                            ${r.je_aktivna ? 'Deaktivovať' : 'Aktivovať'}
                        </button>
                    </td>
                </tr>`;
            });
            rewardsTableHtml += `</tbody></table>`;
        }
        
        container.innerHTML = `
            <div class="form-grid">
                <div>
                    <h4>Vytvoriť novú odmenu</h4>
                    <form id="new-reward-form">
                        <div class="form-group"><label>Názov odmeny</label><input type="text" id="new-reward-name" required></div>
                        <div class="form-group"><label>Počet bodov potrebných na uplatnenie</label><input type="number" id="new-reward-points" required min="1"></div>
                        <button type="submit" class="btn-success" style="width: 100%;">Vytvoriť odmenu</button>
                    </form>
                </div>
                <div>
                    <h4>Zoznam odmien</h4>
                    <div class="table-container">${rewardsTableHtml}</div>
                </div>
            </div>
        `;
        
        document.getElementById('new-reward-form').addEventListener('submit', addNewB2CReward);

    } catch(e) { container.innerHTML = `<p class="error">Chyba pri načítaní odmien: ${e.message}</p>`; }
}

async function addNewB2CReward(event) {
    event.preventDefault();
    const data = {
        name: document.getElementById('new-reward-name').value,
        points: document.getElementById('new-reward-points').value
    };
    try {
        await apiRequest('/api/kancelaria/b2c/add_reward', { method: 'POST', body: data });
        document.getElementById('new-reward-form').reset();
        loadB2CRewardsAdmin(); // Refresh the view
    } catch(e) {}
}

async function toggleB2CRewardStatus(rewardId, currentStatus) {
    try {
        await apiRequest('/api/kancelaria/b2c/toggle_reward_status', { method: 'POST', body: { id: rewardId, status: currentStatus } });
        loadB2CRewardsAdmin(); // Refresh the view
    } catch(e) {}
}

