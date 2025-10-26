// =================================================================
// === VYLEPŠENÁ LOGIKA PRE B2C PORTÁL (b2c.js) ===
// =================================================================

const B2C_STATE = {
    minOrderValue: 20.00
};

document.addEventListener('DOMContentLoaded', () => {
    checkSession();
    initializeEventListeners();
});

function initializeEventListeners() {
    document.getElementById('registerForm')?.addEventListener('submit', handleRegistration);
    document.getElementById('loginForm')?.addEventListener('submit', handleLogin);
    document.getElementById('same-address-checkbox')?.addEventListener('change', (e) => {
        document.getElementById('delivery-address-group').classList.toggle('hidden', e.target.checked);
    });

    const authSection = document.getElementById('auth-section');
    if (authSection) {
        authSection.querySelectorAll('.tab-button').forEach(button => {
            button.addEventListener('click', () => {
                authSection.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
                button.classList.add('active');
                authSection.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                document.getElementById(`${button.dataset.tab}-tab`).classList.add('active');
            });
        });
    }
}

async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(endpoint, {
            method: options.method || 'GET',
            headers: {'Content-Type': 'application/json', ...options.headers},
            body: options.body ? JSON.stringify(options.body) : null
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({error: 'Server vrátil neplatnú odpoveď.'}));
            throw new Error(errorData.error || 'Neznáma chyba servera.');
        }
        return await response.json();
    } catch (error) {
        alert(`Chyba: ${error.message}`);
        throw error;
    }
}

async function checkSession() {
    try {
        const data = await apiRequest('/api/b2c/check_session');
        updateUI(data);
    } catch (error) {
        updateUI({ loggedIn: false });
    }
}

function updateUI(sessionData) {
    const loggedOutView = document.getElementById('loggedOutView');
    const loggedInView = document.getElementById('loggedInView');
    const authLinksContainer = document.getElementById('header-auth-links');

    if (sessionData.loggedIn && sessionData.user.typ === 'B2C') {
        loggedOutView.classList.add('hidden');
        loggedInView.classList.remove('hidden');
        document.getElementById('customer-name').textContent = sessionData.user.name;
        authLinksContainer.innerHTML = `Prihlásený: <strong>${sessionData.user.name}</strong> | <a href="#" onclick="handleLogout(event)">Odhlásiť sa</a>`;
        
        const points = sessionData.user.points || 0;
        document.getElementById('customer-points').textContent = points;
        document.getElementById('claim-reward-btn').classList.toggle('hidden', points <= 0);
        
        loadCustomerView();
    } else {
        loggedOutView.classList.remove('hidden');
        loggedInView.classList.add('hidden');
        authLinksContainer.innerHTML = ''; 
        loadPublicPricelist();
    }
}

async function handleLogout(event) {
    event.preventDefault();
    await apiRequest('/api/b2c/logout', { method: 'POST' });
    checkSession(); 
}

function loadCustomerView() {
    const customerTabs = document.getElementById('customer-main-tabs');
    if (customerTabs && !customerTabs.dataset.listenerAttached) {
         customerTabs.querySelectorAll('.tab-button').forEach(button => {
            button.addEventListener('click', () => {
                customerTabs.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
                button.classList.add('active');
                document.querySelectorAll('#loggedInView .tab-content').forEach(content => content.classList.remove('active'));
                const targetContent = document.getElementById(button.dataset.tab);
                if(targetContent) targetContent.classList.add('active');
                if (button.dataset.tab === 'history-content') loadOrderHistory();
            });
        });
        customerTabs.dataset.listenerAttached = 'true';
    }
    document.querySelector('#customer-main-tabs .tab-button[data-tab="order-content"]').click();
    loadOrderForm();
}

async function loadOrderForm() {
    const container = document.getElementById('order-pricelist-container');
    container.innerHTML = '<p>Načítavam ponuku...</p>';
    try {
        const data = await apiRequest('/api/b2c/get-pricelist');
        if (data.products && Object.keys(data.products).length > 0) {
            let html = '<h2>Vytvoriť objednávku</h2>';
            const categories = Object.keys(data.products).sort((a, b) => a === 'AKCIA TÝŽĎŇA' ? -1 : (b === 'AKCIA TÝŽĎŇA' ? 1 : a.localeCompare(b)));

            for (const category of categories) {
                const categoryClass = category === 'AKCIA TÝŽĎŇA' ? 'akcia-title' : '';
                html += `<div class="product-category"><h3 class="${categoryClass}">${category}</h3>`;
                data.products[category].forEach(p => {
                    const byPieceHtml = p.mj === 'kg' 
                        ? `<label class="checkbox-label" style="font-weight:normal; margin-left:10px;">
                               <input type="checkbox" class="by-piece-checkbox" onchange="toggleItemNote(this, '${p.ean}')"> ks
                           </label>
                           <button type="button" class="by-piece-button hidden" onclick="openItemNoteModal('${p.ean}')"><i class="fas fa-edit"></i></button>`
                        : '';

                    html += `
                        <div class="product-item">
                            <strong style="cursor:help;" title="${escapeHtml(p.popis || '')}">${p.nazov_vyrobku}</strong> - <span>${p.cena_s_dph.toFixed(2)} € / ${p.mj}</span>
                            <div style="display: flex; align-items: center; gap: 10px; margin-top: 5px;">
                                <label>Množstvo:</label>
                                <input type="number" class="quantity-input" min="0" step="${p.mj === 'ks' ? '1' : '0.1'}" style="width: 80px;"
                                       data-ean="${p.ean}" data-name="${p.nazov_vyrobku}" data-price-s-dph="${p.cena_s_dph}" data-price-bez-dph="${p.cena_bez_dph}" data-unit="${p.mj}">
                                <span>${p.mj}</span>
                                ${byPieceHtml}
                            </div>
                        </div>
                    `;
                });
                html += `</div>`;
            }
            container.innerHTML = html;
            container.querySelectorAll('.quantity-input').forEach(input => {
                input.addEventListener('input', updateOrderTotal);
            });
            const deliveryDateInput = document.getElementById('deliveryDate');
            if(deliveryDateInput) {
                const tomorrow = new Date();
                tomorrow.setDate(tomorrow.getDate() + 1);
                deliveryDateInput.min = tomorrow.toISOString().split('T')[0];
                deliveryDateInput.value = deliveryDateInput.min;
            }
            // Listener pre formulár pridávame až po jeho vytvorení
            document.getElementById('orderForm').addEventListener('submit', handleOrderSubmit);
        } else {
            container.innerHTML = '<h2>Vytvoriť objednávku</h2><p>Momentálne nie sú dostupné žiadne produkty.</p>';
        }
    } catch (error) {
        container.innerHTML = `<h2>Vytvoriť objednávku</h2><p class="error">Nepodarilo sa načítať produkty: ${error.message}</p>`;
    }
}

function updateOrderTotal() {
    let total_s_dph = 0;
    let total_bez_dph = 0;
    document.querySelectorAll('#orderForm .quantity-input').forEach(input => {
        const quantity = parseFloat(input.value) || 0;
        const price_s_dph = parseFloat(input.dataset.priceSDph) || 0;
        const price_bez_dph = parseFloat(input.dataset.priceBezDph) || 0;
        total_s_dph += quantity * price_s_dph;
        total_bez_dph += quantity * price_bez_dph;
    });
    
    const total_dph = total_s_dph - total_bez_dph;
    const totalPriceEl = document.getElementById('total-price');
    const minOrderWarningEl = document.getElementById('min-order-warning');
    const submitBtn = document.querySelector('#orderForm button[type="submit"]');

    totalPriceEl.innerHTML = `
        <div style="font-size: 0.9em; text-align: right; line-height: 1.5;">
            Celkom bez DPH: ${total_bez_dph.toFixed(2).replace('.', ',')} €<br>
            DPH: ${total_dph.toFixed(2).replace('.', ',')} €<br>
            <strong style="font-size: 1.2em;">Celkom s DPH (predbežne): ${total_s_dph.toFixed(2).replace('.', ',')} €</strong>
        </div>
    `;

    if (total_s_dph > 0 && total_s_dph < B2C_STATE.minOrderValue) {
        minOrderWarningEl.classList.remove('hidden');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.style.backgroundColor = '#ccc';
        }
    } else {
        minOrderWarningEl.classList.add('hidden');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.style.backgroundColor = '';
        }
    }

    const summarySection = document.getElementById('order-summary-section');
    if (summarySection) {
        summarySection.classList.toggle('hidden', total_s_dph <= 0);
    }
}

async function handleOrderSubmit(event) {
    event.preventDefault();
    const items = Array.from(document.querySelectorAll('#orderForm .quantity-input')).map(input => {
        const quantity = parseFloat(input.value);
        if (quantity > 0) {
            const byPieceCheckbox = input.closest('.product-item').querySelector('.by-piece-checkbox');
            return {
                ean: input.dataset.ean,
                name: input.dataset.name,
                quantity: quantity,
                unit: (byPieceCheckbox && byPieceCheckbox.checked) ? 'ks' : input.dataset.unit,
                item_note: input.dataset.itemNote || ''
            };
        }
        return null;
    }).filter(item => item !== null);

    if (items.length === 0) {
        alert("Vaša objednávka je prázdna.");
        return;
    }

    let totalValue = items.reduce((sum, item) => {
        const input = document.querySelector(`.quantity-input[data-ean="${item.ean}"]`);
        return sum + (item.quantity * (parseFloat(input.dataset.priceSDph) || 0));
    }, 0);

    if (totalValue < B2C_STATE.minOrderValue) {
        alert(`Minimálna hodnota objednávky je ${B2C_STATE.minOrderValue.toFixed(2)} €.`);
        return;
    }

    const orderData = {
        items: items,
        deliveryDate: document.getElementById('deliveryDate').value,
        note: document.getElementById('orderNote').value
    };

    try {
        const result = await apiRequest('/api/b2c/submit-order', { method: 'POST', body: orderData });
        alert(result.message);
        if (result.message.includes("úspešne")) {
            document.getElementById('orderForm').reset();
            updateOrderTotal();
            checkSession();
            document.querySelector('.tab-button[data-tab="history-content"]').click();
        }
    } catch (error) { /* Chyba je už spracovaná */ }
}

async function loadOrderHistory() {
    const container = document.getElementById('history-container');
    container.innerHTML = '<p>Načítavam históriu objednávok...</p>';
    try {
        const data = await apiRequest('/api/b2c/get-history');
        if (data.orders && data.orders.length > 0) {
            let html = '';
            data.orders.forEach(order => {
                const orderDate = new Date(order.datum_objednavky).toLocaleDateString('sk-SK');
                const deliveryDate = new Date(order.pozadovany_datum_dodania).toLocaleDateString('sk-SK');
                let itemsHtml = '<ul>' + (JSON.parse(order.polozky || '[]')).map(item => `<li>${item.name} - ${item.quantity} ${item.unit} ${item.item_note ? `<i>(${item.item_note})</i>` : ''}</li>`).join('') + '</ul>';
                if(order.uplatnena_odmena_poznamka) {
                    itemsHtml += `<p style="color: #16a34a; font-weight: bold;">+ Odmena: ${order.uplatnena_odmena_poznamka}</p>`;
                }
                const finalPrice = order.finalna_suma_s_dph ? `${parseFloat(order.finalna_suma_s_dph).toFixed(2)} €` : `(čaká na preváženie)`;

                html += `<div class="history-item"><div class="history-header">Obj. č. ${order.cislo_objednavky} (${orderDate}) - Stav: ${order.stav}</div><div class="history-body"><p><strong>Požadované vyzdvihnutie:</strong> ${deliveryDate}</p><p><strong>Položky:</strong></p>${itemsHtml}<p><strong>Finálna suma:</strong> ${finalPrice}</p></div></div>`;
            });
            container.innerHTML = html;
        } else {
            container.innerHTML = '<p>Zatiaľ nemáte žiadne objednávky.</p>';
        }
    } catch (error) {
        container.innerHTML = `<p class="error">Nepodarilo sa načítať históriu objednávok.</p>`;
    }
}

async function handleRegistration(event) {
    event.preventDefault();
    const form = event.target;
    const data = Object.fromEntries(new FormData(form).entries());
    if (document.getElementById('same-address-checkbox').checked) {
        data.delivery_address = data.address;
    }
    if (!form.elements.gdpr.checked) {
        return alert("Pre registráciu musíte súhlasiť so spracovaním osobných údajov.");
    }
    try {
        const result = await apiRequest('/api/b2c/register', { method: 'POST', body: data });
        alert(result.message);
        if (result.message.includes("úspešne")) {
            form.reset();
            document.querySelector('.tab-button[data-tab="login"]').click();
        }
    } catch (error) { /* Chyba je už spracovaná */ }
}

async function handleLogin(event) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target).entries());
    try {
        const result = await apiRequest('/api/b2c/login', { method: 'POST', body: data });
        if (result.user) checkSession(); 
    } catch (error) { /* Chyba je už spracovaná */ }
}

function openModal(modalId) { document.getElementById(modalId)?.classList.add('visible'); }
function closeModal(modalId) { document.getElementById(modalId)?.classList.remove('visible'); }

async function showRewardsModal() {
    const listContainer = document.getElementById('rewards-list-container');
    document.getElementById('modal-customer-points').textContent = document.getElementById('customer-points').textContent;
    listContainer.innerHTML = '<p>Načítavam dostupné odmeny...</p>';
    openModal('rewards-modal');
    try {
        const data = await apiRequest('/api/b2c/get_rewards');
        const currentPoints = parseInt(document.getElementById('modal-customer-points').textContent);
        if (data.rewards && data.rewards.length > 0) {
            let html = '';
            let hasAvailableReward = false;
            data.rewards.forEach(reward => {
                const canAfford = currentPoints >= reward.potrebne_body;
                if (canAfford) hasAvailableReward = true;
                html += `<div class="history-item" style="padding:10px; opacity: ${canAfford ? '1' : '0.5'};">
                    <strong>${reward.nazov_odmeny}</strong> (${reward.potrebne_body} bodov)
                    <button class="button button-small" style="float:right;" ${!canAfford ? 'disabled' : ''} onclick="claimReward(${reward.id}, ${reward.potrebne_body})">Vybrať</button>
                </div>`;
            });
            listContainer.innerHTML = hasAvailableReward ? html : '<p>Nemáte dostatok bodov na uplatnenie žiadnej z dostupných odmien.</p>';
        } else {
            listContainer.innerHTML = '<p>Momentálne nie sú k dispozícii žiadne odmeny.</p>';
        }
    } catch(e) { listContainer.innerHTML = `<p class="error">Nepodarilo sa načítať odmeny: ${e.message}</p>`; }
}

async function claimReward(rewardId, pointsNeeded) {
    if (confirm(`Naozaj si chcete uplatniť túto odmenu za ${pointsNeeded} bodov? Bude pridaná k Vašej nasledujúcej objednávke.`)) {
        try {
            const result = await apiRequest('/api/b2c/claim_reward', { method: 'POST', body: { reward_id: rewardId } });
            alert(result.message);
            if (result.new_points !== undefined) {
                document.getElementById('customer-points').textContent = result.new_points;
                document.getElementById('modal-customer-points').textContent = result.new_points;
                document.getElementById('claim-reward-btn').classList.toggle('hidden', result.new_points <= 0);
            }
            closeModal('rewards-modal');
        } catch(e) {}
    }
}

function toggleItemNote(checkbox, ean) {
    const itemDiv = checkbox.closest('.product-item');
    const noteButton = itemDiv.querySelector('.by-piece-button');
    const quantityInput = itemDiv.querySelector('.quantity-input');
    
    noteButton.classList.toggle('hidden', !checkbox.checked);
    if (checkbox.checked) {
        quantityInput.step = "1";
        if (quantityInput.value) {
            quantityInput.value = Math.round(parseFloat(quantityInput.value));
        }
        openItemNoteModal(ean);
    } else {
        quantityInput.step = "0.1";
        quantityInput.dataset.itemNote = "";
    }
    updateOrderTotal();
}

function openItemNoteModal(ean) {
    const input = document.querySelector(`.quantity-input[data-ean="${ean}"]`);
    const modal = document.getElementById('item-note-modal');
    modal.querySelector('#item-note-modal-title').textContent = `Poznámka k: ${input.dataset.name}`;
    const noteTextarea = modal.querySelector('#item-note-input');
    noteTextarea.value = input.dataset.itemNote || '';
    modal.querySelector('#save-item-note-btn').onclick = () => {
        input.dataset.itemNote = noteTextarea.value;
        closeModal('item-note-modal');
    };
    openModal('item-note-modal');
}

function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'})[m]);
}

async function loadPublicPricelist() {
    const container = document.getElementById('public-pricelist-container');
    container.innerHTML = '<h2>Naša ponuka</h2><p>Načítavam produkty...</p>';
    try {
        const data = await apiRequest('/api/b2c/get-pricelist');
        if (data.products && Object.keys(data.products).length > 0) {
            let html = '<h2>Naša ponuka</h2>';
            const categories = Object.keys(data.products).sort((a, b) => a === 'AKCIA TÝŽĎŇA' ? -1 : (b === 'AKCIA TÝŽĎŇA' ? 1 : a.localeCompare(b)));
            
            for (const category of categories) {
                const categoryClass = category === 'AKCIA TÝŽĎŇA' ? 'akcia-title' : '';
                html += `<div class="product-category"><h3 class="${categoryClass}">${category}</h3>`;
                data.products[category].forEach(p => {
                    html += `
                        <div class="product-item">
                            <strong>${p.nazov_vyrobku}</strong> - 
                            <span>${p.cena_s_dph.toFixed(2)} € / ${p.mj}</span>
                            <p style="font-size: 0.9em; color: #666;">${p.popis || ''}</p>
                        </div>
                    `;
                });
                html += `</div>`;
            }
            container.innerHTML = html;
        } else {
            container.innerHTML = '<h2>Naša ponuka</h2><p>Momentálne nie sú dostupné žiadne produkty.</p>';
        }
    } catch (error) {
        container.innerHTML = `<h2>Naša ponuka</h2><p class="error">Nepodarilo sa načítať produkty: ${error.message}</p>`;
    }
}

