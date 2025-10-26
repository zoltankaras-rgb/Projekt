document.addEventListener('DOMContentLoaded', () => {
    const loader = document.getElementById('loader');
    const notification = document.getElementById('notification');
    const authViewsContainer = document.getElementById('auth-views');
    const customerPortalView = document.getElementById('view-customer-portal');
    const views = { auth: document.getElementById('view-auth'), resetRequest: document.getElementById('view-password-reset-request'), resetForm: document.getElementById('view-password-reset-form') };
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const passwordResetRequestForm = document.getElementById('passwordResetRequestForm');
    const passwordResetForm = document.getElementById('passwordResetForm');
    const tabButtons = document.querySelectorAll('.tab-button');
    const forgotPasswordLink = document.getElementById('forgot-password-link');
    const backToLoginLinks = document.querySelectorAll('.back-to-login-link');
    const logoutLink = document.getElementById('logout-link');
console.log("✅ b2b_app.js bol úspešne načítaný");
    let appState = { currentUser: null };

    function showAuthView(viewName) {
        Object.values(views).forEach(view => view.classList.add('hidden'));
        if (views[viewName]) views[viewName].classList.remove('hidden');
        hideNotification();
    }
    
    function showMainView(viewName) {
        authViewsContainer.classList.toggle('hidden', viewName !== 'auth');
        customerPortalView.classList.toggle('hidden', viewName !== 'customer');
    }

    function showLoader() { if(loader) loader.classList.remove('hidden'); }
    function hideLoader() { if(loader) loader.classList.add('hidden'); }
    function showNotification(message, type) {
        if (!notification) return;
        notification.textContent = message;
        notification.className = type;
        notification.classList.remove('hidden');
        setTimeout(hideNotification, 5000);
    }
    function hideNotification() { if(notification) notification.classList.add('hidden'); }
    
    async function apiCall(url, data) {
        showLoader();
        hideNotification();
        try {
            const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Nastala neznáma chyba na serveri.');
            return result;
        } catch (error) {
            showNotification(error.message, 'error');
            return null;
        } finally {
            hideLoader();
        }
    }
    
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = { zakaznik_id: loginForm.elements.zakaznik_id.value, password: loginForm.elements.password.value };
        const result = await apiCall('/api/b2b/login', data);
        if (result && result.userData) handleLoginSuccess(result.userData);
    });

    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const password = registerForm.elements.password.value;
        if (password.length < 6) { return showNotification('Heslo musí mať aspoň 6 znakov.', 'error'); }
        const data = {
            nazov_firmy: registerForm.elements.nazov_firmy.value,
            adresa: registerForm.elements.adresa.value,
            email: registerForm.elements.email.value,
            telefon: registerForm.elements.telefon.value,
            password: password,
            gdpr: registerForm.elements.gdpr.checked
        };
        const result = await apiCall('/api/b2b/register', data);
        if (result) {
            showNotification(result.message, 'success');
            registerForm.reset();
            document.querySelector('.tab-button[data-tab="login"]').click();
        }
    });

    passwordResetRequestForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = { email: passwordResetRequestForm.elements.email.value };
        const result = await apiCall('/api/b2b/request-reset', data);
        if (result) showNotification(result.message, 'success');
    });

    passwordResetForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const newPassword = passwordResetForm.elements.password.value;
        const confirmPassword = passwordResetForm.elements['confirm-password'].value;
        if (newPassword.length < 6) { return showNotification('Heslo musí mať aspoň 6 znakov.', 'error'); }
        if (newPassword !== confirmPassword) { return showNotification('Heslá sa nezhodujú.', 'error'); }
        const data = { token: passwordResetForm.elements.token.value, password: newPassword };
        const result = await apiCall('/api/b2b/perform-reset', data);
        if (result) {
            showNotification(result.message, 'success');
            setTimeout(() => {
                window.history.replaceState({}, document.title, window.location.pathname);
                showAuthView('auth');
            }, 2000);
        }
    });
    
    logoutLink.addEventListener('click', (e) => {
        e.preventDefault();
        sessionStorage.removeItem('b2bUser');
        appState.currentUser = null;
        loginForm.reset();
        showMainView('auth');
    });

    function handleLoginSuccess(userData) {
        appState.currentUser = userData;
        sessionStorage.setItem('b2bUser', JSON.stringify(userData));
        
        if (userData.role === 'admin') {
            return showNotification('Admin prihlásenie úspešné. Administrácia je v internom systéme.', 'success');
        } 
        
        showMainView('customer');
        document.getElementById('customer-name').textContent = userData.nazov_firmy;
        
        const announcementBar = document.getElementById('announcement-bar');
        if (userData.announcement) {
            announcementBar.textContent = userData.announcement;
            announcementBar.classList.remove('hidden');
        } else {
            announcementBar.classList.add('hidden');
        }

        const customerContent = document.getElementById('customer-dynamic-content');
        customerContent.innerHTML = '';
        
        if (userData.pricelists && userData.pricelists.length > 1) {
            renderPricelistSelector(userData.pricelists);
        } else if (userData.products) {
            renderProductTable(userData.products);
        } else {
            customerContent.innerHTML = `<p>Pre váš účet nebol nájdený žiadny priradený cenník. Prosím, kontaktujte administrátora.</p>`;
        }
    }

    function renderPricelistSelector(pricelists) {
        const customerContent = document.getElementById('customer-dynamic-content');
        let options = pricelists.map(p => `<option value="${p.id}">${p.nazov_cennika}</option>`).join('');
        customerContent.innerHTML = `
            <div id="pricelist-selector-container"><h3>Výber cenníka</h3><div class="form-group"><label for="pricelist-select">Prosím, vyberte cenník, z ktorého chcete objednať:</label><select id="pricelist-select"><option value="">-- Vyberte --</option>${options}</select></div></div>
            <div id="product-table-container"></div>`;
        document.getElementById('pricelist-select').addEventListener('change', async (e) => {
            const pricelistId = e.target.value;
            const productContainer = document.getElementById('product-table-container');
            productContainer.innerHTML = '';
            if (!pricelistId) return;
            const result = await apiCall('/api/b2b/get-products', { pricelist_id: pricelistId });
            if (result && result.products) renderProductTable(result.products, productContainer);
        });
    }

    function renderProductTable(products, container) {
        const targetContainer = container || document.getElementById('customer-dynamic-content');
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const minDate = tomorrow.toISOString().split('T')[0];
        
        let tableRows = products.map(p => {
            const price = Number(p.cena);
            if (isNaN(price)) return '';
            const isKgProduct = p.mj !== 'ks';
            return `<tr data-ean="${p.ean_produktu}" data-name="${p.nazov_vyrobku}" data-price="${price}" data-dph="${p.dph}" data-unit-type="${p.mj}">
                    <td>${p.nazov_vyrobku}</td>
                    <td>${p.ean_produktu}</td>
                    <td style="text-align:center;">${price.toFixed(2).replace('.', ',')} €</td>
                    <td style="text-align:center;">${p.dph.toFixed(2).replace('.',',')} %</td>
                    <td class="quantity-cell">
                        <input type="number" min="0" step="${isKgProduct ? '0.01' : '1'}" class="form-group quantity-input" style="width: 100px; padding: 8px; margin: 0;">
                        <span>${p.mj}</span>
                        ${isKgProduct ? '<input type="checkbox" class="by-piece-checkbox" title="Objednať na kusy"><label class="by-piece-label" title="Objednať na kusy">KS</label>' : ''}
                    </td>
                </tr>`;
        }).join('');
        const contentHTML = `<h3 style="margin-top: 40px;">Nová objednávka</h3><form id="orderForm"><table><thead><tr><th>Názov produktu</th><th>EAN</th><th>Cena/jed. (bez DPH)</th><th>DPH</th><th>Množstvo</th></tr></thead><tbody>${tableRows}</tbody></table><div class="form-group" style="margin-top: 20px;"><label for="delivery-date">Požadovaný dátum dodania:</label><input type="date" id="delivery-date" class="form-group" required min="${minDate}"></div><div class="form-group"><label for="order-note">Poznámka k objednávke:</label><textarea id="order-note" rows="3" class="form-group" style="width: 100%;"></textarea></div><div class="order-summary"><div class="order-summary-box"><p><span>Spolu bez DPH:</span> <span id="total-net">0,00 €</span></p><p><span>DPH:</span> <span id="total-vat-amount">0,00 €</span></p><p class="total"><span>Celková suma s DPH:</span> <span id="total-gross">0,00 €</span></p></div></div><button type="submit" class="button">Odoslať objednávku</button></form>`;
        
        targetContainer.innerHTML = contentHTML;
        document.querySelectorAll('.quantity-input').forEach(input => input.addEventListener('input', calculateOrderTotal));
        document.querySelectorAll('.by-piece-checkbox').forEach(box => box.addEventListener('change', (e) => handleByPieceOrder(e.target)));
        const orderForm = document.getElementById('orderForm');
        if(orderForm) orderForm.addEventListener('submit', handleOrderSubmit);
    }
    
    function handleByPieceOrder(checkbox) {
        const row = checkbox.closest('tr');
        const quantityInput = row.querySelector('.quantity-input');
        if (checkbox.checked) {
            quantityInput.step = "1";
            quantityInput.value = Math.round(quantityInput.value || 0);
            showItemNoteModal(row);
        } else {
            quantityInput.step = "0.01";
            row.dataset.itemNote = ""; // Clear note
            row.dataset.orderedUnit = "kg";
        }
        calculateOrderTotal();
    }
    
    function showItemNoteModal(row) {
        const modalContainer = document.getElementById('modal-container');
        modalContainer.innerHTML = `<div class="modal-backdrop"></div>
            <div class="modal-content">
                <div class="modal-header"><h3>Objednávka na kusy: ${row.dataset.name}</h3></div>
                <form id="item-note-form">
                    <p>Zadali ste objednávku na kusy. Ak máte špecifickú požiadavku na váhu jedného kusu, uveďte ju prosím do poznámky.</p>
                    <div class="form-group">
                        <label for="item-note-input">Poznámka k položke (napr. "dodať vo váhe 150g")</label>
                        <input type="text" id="item-note-input" value="${row.dataset.itemNote || ''}">
                    </div>
                    <button type="submit" class="button" style="width: 100%; margin:0;">Potvrdiť</button>
                </form>
            </div>`;
        modalContainer.style.display = 'flex';
        
        const closeModal = () => { modalContainer.style.display = 'none'; };
        modalContainer.querySelector('.modal-backdrop').onclick = closeModal;
        
        document.getElementById('item-note-form').onsubmit = (e) => {
            e.preventDefault();
            row.dataset.itemNote = document.getElementById('item-note-input').value;
            row.dataset.orderedUnit = "ks";
            closeModal();
        };
    }

    function calculateOrderTotal() {
        let totalNet = 0, totalVatAmount = 0;
        document.querySelectorAll('#orderForm tbody tr').forEach(row => {
            const price = parseFloat(row.dataset.price);
            const dphRate = parseFloat(row.dataset.dph) / 100;
            const quantity = parseFloat(row.querySelector('.quantity-input').value) || 0;
            const itemNet = price * quantity;
            totalNet += itemNet;
            totalVatAmount += itemNet * dphRate;
        });
        document.getElementById('total-net').textContent = `${totalNet.toFixed(2).replace('.',',')} €`;
        document.getElementById('total-vat-amount').textContent = `${totalVatAmount.toFixed(2).replace('.',',')} €`;
        document.getElementById('total-gross').textContent = `${(totalNet + totalVatAmount).toFixed(2).replace('.',',')} €`;
    }
    
    async function handleOrderSubmit(e) {
        e.preventDefault();
        const items = Array.from(document.querySelectorAll('#orderForm tbody tr')).map(row => ({
            ean: row.dataset.ean, name: row.dataset.name, price: row.dataset.price, dph: row.dataset.dph,
            quantity: parseFloat(row.querySelector('.quantity-input').value) || 0,
            unit: row.querySelector('.by-piece-checkbox')?.checked ? 'ks' : row.dataset.unitType,
            item_note: row.dataset.itemNote || ''
        })).filter(item => item.quantity > 0);

        if (items.length === 0) { return showNotification('Objednávka je prázdna.', 'error'); }
        const deliveryDate = document.getElementById('delivery-date').value;
        if (!deliveryDate) { return showNotification('Prosím, zvoľte dátum dodania.', 'error'); }

        const data = {
            userId: appState.currentUser.id,
            customerName: appState.currentUser.nazov_firmy,
            customerEmail: appState.currentUser.email,
            items: items, 
            note: document.getElementById('order-note').value.trim(), 
            deliveryDate: deliveryDate
        };
        const result = await apiCall('/api/b2b/submit-order', data);
        if (result) {
            document.getElementById('customer-dynamic-content').innerHTML = `<h3>Ďakujeme!</h3><p style="font-size: 1.5rem; text-align: center;">${result.message}</p><p style="text-align: center;">Na Váš e-mail sme odoslali potvrdenie.</p>`;
        }
    }

    function init() {
        const storedUser = sessionStorage.getItem('b2bUser');
        if (storedUser) {
            try { handleLoginSuccess(JSON.parse(storedUser)); return; } catch(e) { sessionStorage.removeItem('b2bUser'); }
        }
        const params = new URLSearchParams(window.location.search);
        const token = params.get('token');
        if (token && params.get('action') === 'resetPassword') {
            document.getElementById('reset-token-input').value = token; showMainView('auth'); showAuthView('resetForm');
        } else { showMainView('auth'); showAuthView('auth'); }
        
        tabButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                const tab = e.currentTarget.dataset.tab;
                document.getElementById('login-form-container').classList.toggle('hidden', tab !== 'login');
                document.getElementById('register-form-container').classList.toggle('hidden', tab !== 'register');
                tabButtons.forEach(btn => btn.classList.remove('active'));
                e.currentTarget.classList.add('active');
            });
        });
        forgotPasswordLink.addEventListener('click', (e) => { e.preventDefault(); showAuthView('resetRequest'); });
        backToLoginLinks.forEach(link => {
            link.addEventListener('click', (e) => { e.preventDefault(); window.history.replaceState({}, document.title, window.location.pathname); showAuthView('auth'); });
        });
    }

    init();
    
}); 
async function loadB2BOrderHistory() {
    const container = document.getElementById('history-container');
    container.innerHTML = '<p>Načítavam históriu objednávok...</p>';

    try {
        const b2bUser = JSON.parse(sessionStorage.getItem('b2bUser'));
        if (!b2bUser || !b2bUser.id) {
            container.innerHTML = '<p class="error">Chyba: používateľ nie je prihlásený.</p>';
            return;
        }

        const userId = b2bUser.id;
        const data = await apiRequest('/api/b2b/get-order-history', {
    method: 'POST',
    body: { user_id: userId }
});
        if (data && data.length > 0) {
            let html = '';
            data.forEach(order => {
                const orderDate = new Date(order.datum_vytvorenia).toLocaleDateString('sk-SK');
                const finalPrice = order.celkova_suma_s_dph
                    ? `${parseFloat(order.celkova_suma_s_dph).toFixed(2)} €`
                    : `(neuvedené)`;

                html += `
                    <div class="history-item">
                        <div class="history-header">
                            Obj. č. ${order.cislo_objednavky} (${orderDate}) - Stav: ${order.stav}
                        </div>
                        <div class="history-body">
                            <p><strong>Finálna suma:</strong> ${finalPrice}</p>
                            ${order.poznamka ? `<p><strong>Poznámka:</strong> ${order.poznamka}</p>` : ''}
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html;
        } else {
            container.innerHTML = '<p>Zatiaľ nemáte žiadne B2B objednávky.</p>';
        }

    } catch (error) {
        console.error("❌ Chyba pri načítaní B2B histórie:", error);
        container.innerHTML = '<p class="error">Nepodarilo sa načítať B2B históriu objednávok.</p>';
    }
}
