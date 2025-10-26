// =================================================================
// === SUB-MODUL KANCELÁRIA: B2B ADMIN ===
// =================================================================

function initializeB2BAdminModule() {
    const container = document.getElementById('section-b2b-admin');
    if (!container) return;
    container.innerHTML = `
        <h3>B2B Administrácia</h3>
        <div class="b2b-tab-nav">
            <button class="b2b-tab-button active" data-b2b-tab="b2b-registrations-tab">Čakajúce Registrácie</button>
            <button class="b2b-tab-button" data-b2b-tab="b2b-customers-tab">Zoznam Odberateľov</button>
            <button class="b2b-tab-button" data-b2b-tab="b2b-pricelists-tab">Správa Cenníkov</button>
            <button class="b2b-tab-button" data-b2b-tab="b2b-orders-tab">Prehľad Objednávok</button>
            <button class="b2b-tab-button" data-b2b-tab="b2b-settings-tab">Nastavenia</button>
        </div>
        <div id="b2b-registrations-tab" class="b2b-tab-content active"><div id="b2b-registrations-container"></div></div>
        <div id="b2b-customers-tab" class="b2b-tab-content"><div id="b2b-customers-container"></div></div>
        <div id="b2b-pricelists-tab" class="b2b-tab-content">
            <div id="b2b-pricelists-container"></div>
            <div class="form-group" style="margin-top: 1.5rem;"><label for="new-pricelist-name">Vytvoriť nový cenník:</label><div style="display: flex; gap: 0.5rem;"><input type="text" id="new-pricelist-name" placeholder="Názov nového cenníka"><button id="add-new-pricelist-btn" class="btn-success" style="width: auto; margin-top:0;">Vytvoriť</button></div></div>
        </div>
        <div id="b2b-orders-tab" class="b2b-tab-content"><div id="b2b-orders-container"></div></div>
        <div id="b2b-settings-tab" class="b2b-tab-content"><div id="b2b-settings-container"></div></div>
    `;

    const tabButtons = container.querySelectorAll('.b2b-tab-button');
    const tabContents = container.querySelectorAll('.b2b-tab-content');
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            tabButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            const targetTab = button.dataset.b2bTab;
            tabContents.forEach(content => content.classList.toggle('active', content.id === targetTab));
            
            switch(targetTab) {
                case 'b2b-registrations-tab': loadPendingRegistrations(); break;
                case 'b2b-customers-tab': loadCustomersAndPricelists(); break;
                case 'b2b-pricelists-tab': loadPricelistsForManagement(); break;
                case 'b2b-orders-tab': loadB2BOrdersView(); break;
                case 'b2b-settings-tab': loadB2BSettings(); break;
            }
        });
    });
    document.getElementById('add-new-pricelist-btn').onclick = async () => { const nameInput = document.getElementById('new-pricelist-name'); const name = nameInput.value.trim(); if (!name) { showStatus("Názov novej sady nemôže byť prázdny.", true); return; } try { await apiRequest('/api/kancelaria/b2b/createPricelist', { method: 'POST', body: { name } }); nameInput.value = ''; loadPricelistsForManagement(); } catch (e) { } };
    loadPendingRegistrations();
}

async function loadPendingRegistrations() { const container = document.getElementById('b2b-registrations-container'); container.innerHTML = '<p>Načítavam čakajúce registrácie...</p>'; try { const registrations = await apiRequest('/api/kancelaria/getPendingB2BRegistrations'); if (!registrations || registrations.length === 0) { container.innerHTML = '<p>Žiadne nové registrácie.</p>'; return; } let tableHtml = `<table><thead><tr><th>Názov firmy</th><th>Adresy</th><th>Kontakt</th><th>Dátum</th><th>Akcie</th></tr></thead><tbody>`; registrations.forEach(reg => { tableHtml += `<tr> <td>${escapeHtml(reg.nazov_firmy)}</td><td>Fakturačná: ${escapeHtml(reg.adresa || 'N/A')}<br>Doručovacia: ${escapeHtml(reg.adresa_dorucenia || 'N/A')}</td><td>${escapeHtml(reg.email)}<br>${escapeHtml(reg.telefon)}</td> <td>${new Date(reg.datum_registracie).toLocaleDateString('sk-SK')}</td> <td><div class="btn-grid" style="grid-template-columns: 1fr 1fr;"> <button class="btn-success" style="margin:0;" onclick="approveRegistration(${reg.id})">Schváliť</button> <button class="btn-danger" style="margin:0;" onclick="rejectRegistration(${reg.id})">Odmietnuť</button> </div></td> </tr>`; }); container.innerHTML = `<div class="table-container">${tableHtml}</tbody></table></div>`; } catch (e) { container.innerHTML = `<p class="error">Chyba pri načítaní registrácií: ${e.message}</p>`; } }
async function approveRegistration(registrationId) { const customerId = prompt("Zadajte interné číslo odberateľa (Login ID):"); if (!customerId) return; try { await apiRequest('/api/kancelaria/approveB2BRegistration', { method: 'POST', body: { id: registrationId, customerId: customerId } }); loadPendingRegistrations(); } catch (e) { } }
async function rejectRegistration(registrationId) { if (!confirm("Naozaj chcete natrvalo odmietnuť túto registráciu?")) return; try { await apiRequest('/api/kancelaria/rejectB2BRegistration', { method: 'POST', body: { id: registrationId } }); loadPendingRegistrations(); } catch (e) { } }
async function loadCustomersAndPricelists() { const container = document.getElementById('b2b-customers-container'); container.innerHTML = '<p>Načítavam odberateľov...</p>'; try { const data = await apiRequest('/api/kancelaria/b2b/getCustomersAndPricelists'); b2bAdminData.customers = data.customers; b2bAdminData.pricelists = data.pricelists; if (!data.customers || data.customers.length === 0) { container.innerHTML = '<p>Žiadni B2B odberatelia neboli nájdení.</p>'; return; } const pricelistMap = new Map(data.pricelists.map(p => [p.id, p.nazov_cennika])); let tableHtml = `<table><thead><tr><th>ID</th><th>Názov firmy</th><th>Kontakt a Adresy</th><th>Priradené cenníky</th><th>Akcia</th></tr></thead><tbody>`; data.customers.forEach(cust => { const assignedPricelists = cust.cennik_ids ? cust.cennik_ids.split(',').map(id => pricelistMap.get(parseInt(id)) || 'Neznámy').join(', ') : '<i>Žiadny</i>'; tableHtml += `<tr> <td>${escapeHtml(cust.zakaznik_id)}</td><td>${escapeHtml(cust.nazov_firmy)}</td> <td>${escapeHtml(cust.email)}<br>${escapeHtml(cust.telefon)}<hr style="margin: 4px 0;">Fakt.: ${escapeHtml(cust.adresa || 'N/A')}<br>Dor.: ${escapeHtml(cust.adresa_dorucenia || 'N/A')}</td><td>${escapeHtml(assignedPricelists)}</td> <td><button class="btn-warning" style="margin:0; width:auto;" onclick="openEditCustomerModal(${cust.id})">Upraviť</button></td> </tr>`; }); container.innerHTML = `<div class="table-container">${tableHtml}</tbody></table></div>`; } catch (e) { container.innerHTML = `<p class="error">Chyba pri načítaní odberateľov: ${e.message}</p>`; } }
function openEditCustomerModal(customerId) {
    const customer = b2bAdminData.customers.find(c => c.id === customerId); if (!customer) return;
    const template = document.getElementById('edit-customer-modal-template');
    showModal('Upraviť odberateľa', () => Promise.resolve({
        html: template.innerHTML, onReady: () => {
            document.getElementById('edit-customer-id').value = customer.id; document.getElementById('edit-customer-name').value = customer.nazov_firmy; document.getElementById('edit-customer-email').value = customer.email; document.getElementById('edit-customer-phone').value = customer.telefon;
            document.getElementById('edit-customer-address').value = customer.adresa || '';
            document.getElementById('edit-customer-delivery-address').value = customer.adresa_dorucenia || '';
            const pricelistContainer = document.getElementById('edit-customer-pricelists'); const assignedIds = customer.cennik_ids ? customer.cennik_ids.split(',').map(Number) : []; pricelistContainer.innerHTML = b2bAdminData.pricelists.map(p => ` <div><input type="checkbox" id="pricelist_${p.id}" value="${p.id}" ${assignedIds.includes(p.id) ? 'checked' : ''}><label for="pricelist_${p.id}">${escapeHtml(p.nazov_cennika)}</label></div> `).join(''); const form = document.getElementById('edit-customer-form'); form.onsubmit = async (e) => { e.preventDefault(); const selectedPricelists = Array.from(pricelistContainer.querySelectorAll('input:checked')).map(input => input.value); const updatedData = { id: customerId, nazov_firmy: document.getElementById('edit-customer-name').value, email: document.getElementById('edit-customer-email').value, telefon: document.getElementById('edit-customer-phone').value, adresa: document.getElementById('edit-customer-address').value, adresa_dorucenia: document.getElementById('edit-customer-delivery-address').value, pricelist_ids: selectedPricelists }; try { await apiRequest('/api/kancelaria/b2b/updateCustomer', { method: 'POST', body: updatedData }); document.getElementById('modal-container').style.display = 'none'; loadCustomersAndPricelists(); } catch (e) { } };
        }
    }));
}
async function loadPricelistsForManagement() { const container = document.getElementById('b2b-pricelists-container'); container.innerHTML = '<p>Načítavam cenníky...</p>'; try { const data = await apiRequest('/api/kancelaria/b2b/getPricelistsAndProducts'); b2bAdminData.pricelists = data.pricelists; b2bAdminData.productsByCategory = data.productsByCategory; if (!data.pricelists || data.pricelists.length === 0) { container.innerHTML = '<p>Žiadne cenníkové sady neboli nájdené.</p>'; } else { let html = ''; data.pricelists.forEach(p => { html += `<div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem; border-bottom: 1px solid var(--medium-gray);"> <span>${escapeHtml(p.nazov_cennika)}</span> <button class="btn-warning" style="margin:0; width: auto;" onclick="openEditPricelistModal(${p.id})">Upraviť položky</button> </div>`; }); container.innerHTML = html; } } catch (e) { container.innerHTML = `<p class="error">Chyba pri načítaní cenníkov: ${e.message}</p>`; } }
async function openEditPricelistModal(pricelistId) {
    const pricelist = b2bAdminData.pricelists.find(p => p.id === pricelistId); if (!pricelist) return;
    const template = document.getElementById('edit-pricelist-modal-template');
    showModal(`Upraviť cenník: ${pricelist.nazov_cennika}`, () => Promise.resolve({
        html: template.innerHTML, onReady: async () => {
            const allProductsContainer = document.getElementById('all-products-list');
            for (const category in b2bAdminData.productsByCategory) { allProductsContainer.innerHTML += `<h4 style="margin-top: 1rem; margin-bottom: 0.5rem; padding-left: 0.5rem;">${escapeHtml(category)}</h4>`; b2bAdminData.productsByCategory[category].forEach(p => { allProductsContainer.innerHTML += `<div style="padding: 0.25rem 0.5rem; cursor: pointer;" onclick="addProductToPricelist(this, {ean: '${p.ean}', name: '${escapeHtml(p.name)}'})">${escapeHtml(p.name)}</div>`; }); }
            const pricelistItemsContainer = document.getElementById('pricelist-items-list'); pricelistItemsContainer.innerHTML = 'Načítavam položky...'; const currentItemsData = await apiRequest('/api/kancelaria/b2b/getPricelistDetails', { method: 'POST', body: { id: pricelistId } }); const currentItemsMap = new Map((currentItemsData.items || []).map(i => [i.ean_produktu, parseFloat(i.cena)])); pricelistItemsContainer.innerHTML = `<table><tbody></tbody></table>`; const allProductsFlat = Object.values(b2bAdminData.productsByCategory).flat(); currentItemsMap.forEach((price, ean) => { const product = allProductsFlat.find(p => p.ean === ean); if (product) { addProductToPricelist(null, product, price, false); } }); document.getElementById('save-pricelist-changes-btn').onclick = async () => { const itemsToSave = []; document.querySelectorAll('#pricelist-items-list tbody tr').forEach(row => { itemsToSave.push({ ean: row.dataset.ean, price: row.querySelector('input').value }); }); try { await apiRequest('/api/kancelaria/b2b/updatePricelist', { method: 'POST', body: { id: pricelistId, items: itemsToSave } }); document.getElementById('modal-container').style.display = 'none'; } catch (e) { } }; document.getElementById('product-search-input').oninput = (e) => { const searchTerm = e.target.value.toLowerCase(); allProductsContainer.querySelectorAll('div[onclick]').forEach(div => { div.style.display = div.textContent.toLowerCase().includes(searchTerm) ? 'block' : 'none'; }); };
        }
    }));
}
function addProductToPricelist(element, product, price = '', shouldRemoveFromSource = true) { const pricelistTbody = document.getElementById('pricelist-items-list').querySelector('tbody'); if (!pricelistTbody || pricelistTbody.querySelector(`tr[data-ean="${product.ean}"]`)) return; const newRow = document.createElement('tr'); newRow.dataset.ean = product.ean; newRow.innerHTML = ` <td>${product.name}</td> <td><input type="number" step="0.01" value="${price}" placeholder="Cena" style="width: 80px; padding: 5px; margin-top: 0;"></td> <td><button class="btn-danger" style="margin:0; width:auto; padding: 5px;" onclick="removeProductFromPricelist(this, '${product.ean}')">X</button></td> `; pricelistTbody.appendChild(newRow); if (element && shouldRemoveFromSource) { element.style.display = 'none'; } }
function removeProductFromPricelist(button, ean) { button.closest('tr').remove(); const sourceProductDiv = document.querySelector(`#all-products-list div[onclick*="'${ean}'"]`); if (sourceProductDiv) { sourceProductDiv.style.display = 'block'; } }
async function loadB2BSettings() {
    const container = document.getElementById('b2b-settings-container');
    container.innerHTML = `<p>Načítavam nastavenia...</p>`;
    try {
        const settings = await apiRequest('/api/kancelaria/b2b/getAnnouncement');
        container.innerHTML = `
            <h4>Oznam na B2B Portáli</h4>
            <p>Tento text sa zobrazí všetkým prihláseným zákazníkom na hlavnej stránke.</p>
            <div class="form-group">
                <textarea id="b2b-announcement-text" rows="4">${settings.announcement || ''}</textarea>
            </div>
            <button id="save-announcement-btn" class="btn-success" style="width: 100%;">Uložiť oznam</button>
        `;
        document.getElementById('save-announcement-btn').onclick = async () => {
            const text = document.getElementById('b2b-announcement-text').value;
            await apiRequest('/api/kancelaria/b2b/saveAnnouncement', { method: 'POST', body: { announcement: text } });
        };
    } catch (e) {
        container.innerHTML = `<p class="error">Chyba pri načítaní nastavení: ${e.message}</p>`;
    }
}

async function loadB2BOrdersView() {
    const container = document.getElementById('b2b-orders-container');
    const today = new Date().toISOString().split('T')[0];
    container.innerHTML = `
        <div style="display:flex; gap: 1rem; align-items: flex-end; margin-bottom: 1.5rem;">
            <div class="form-group" style="flex:1; margin-bottom: 0;">
                <label for="order-filter-start" style="margin-top:0;">Zobraziť objednávky s dodaním od:</label>
                <input type="date" id="order-filter-start" value="${today}">
            </div>
            <div class="form-group" style="flex:1; margin-bottom: 0;">
                <label for="order-filter-end" style="margin-top:0;">do:</label>
                <input type="date" id="order-filter-end" value="${today}">
            </div>
            <button id="filter-orders-btn" class="btn-primary" style="margin-bottom: 0; height: fit-content;">Filtrovať</button>
        </div>
        <div id="orders-table-container" class="table-container"><p>Načítavam objednávky...</p></div>
    `;

    const loadOrders = async () => {
        const tableContainer = document.getElementById('orders-table-container');
        tableContainer.innerHTML = '<p>Načítavam...</p>';
        const filters = {
            startDate: document.getElementById('order-filter-start').value,
            endDate: document.getElementById('order-filter-end').value
        };
        const result = await apiRequest('/api/kancelaria/b2b/getAllOrders', { method: 'POST', body: filters });
        if (result && result.orders) {
            if (result.orders.length === 0) {
                tableContainer.innerHTML = '<p>Pre zadané obdobie neboli nájdené žiadne objednávky.</p>';
                return;
            }
            let tableHtml = `<table><thead><tr>
                <th>Číslo obj.</th><th>Zákazník</th><th>Dátum obj.</th><th>Dátum dodania</th><th>Suma (s DPH)</th><th>Akcie</th>
                </tr></thead><tbody>`;
            result.orders.forEach(order => {
                const orderDate = new Date(order.datum_objednavky).toLocaleString('sk-SK');
                const deliveryDate = new Date(order.pozadovany_datum_dodania).toLocaleDateString('sk-SK');
                tableHtml += `
                    <tr>
                        <td>${order.cislo_objednavky}</td>
                        <td>${order.nazov_firmy}</td>
                        <td>${orderDate}</td>
                        <td>${deliveryDate}</td>
                        <td>${parseFloat(order.celkova_suma_s_dph).toFixed(2).replace('.',',')} €</td>
                        <td>
                            <button class="btn-info" style="margin:0; padding: 5px;" onclick="showAdminOrderDetailModal(${order.id})"><i class="fas fa-search"></i> Detail</button>
                            <button class="btn-secondary" style="margin:0; padding: 5px;" onclick="window.open('/api/kancelaria/b2b/print_order_pdf/${order.id}', '_blank')"><i class="fas fa-print"></i> Tlačiť</button>
                        </td>
                    </tr>`;
            });
            tableContainer.innerHTML = tableHtml + '</tbody></table>';
        } else {
             tableContainer.innerHTML = '<p class="error">Nepodarilo sa načítať objednávky.</p>';
        }
    };

    document.getElementById('filter-orders-btn').onclick = loadOrders;
    loadOrders();
}

async function showAdminOrderDetailModal(orderId) {
    const contentPromise = async () => {
        const order = await apiRequest(`/api/kancelaria/b2b/get_order_details/${orderId}`);
        let itemsHtml = order.items.map(item => `
            <tr>
                <td>${item.name} ${item.item_note ? `<br><small><i>Pozn: ${item.item_note}</i></small>` : ''}</td>
                <td>${item.quantity} ${item.unit}</td>
                <td>${item.price.toFixed(2)} €</td>
                <td>${(item.quantity * item.price).toFixed(2)} €</td>
            </tr>
        `).join('');

        return {
            html: `
                <p><strong>Zákazník:</strong> ${order.customerName}</p>
                <p><strong>Dátum dodania:</strong> ${new Date(order.deliveryDate).toLocaleDateString('sk-SK')}</p>
                ${order.note ? `<p><strong>Poznámka:</strong> ${order.note}</p>` : ''}
                <div class="table-container">
                    <table>
                        <thead><tr><th>Názov</th><th>Množstvo</th><th>Cena/MJ</th><th>Spolu</th></tr></thead>
                        <tbody>${itemsHtml}</tbody>
                    </table>
                </div>
            `
        };
    };
    showModal('Detail Objednávky', contentPromise);
}

