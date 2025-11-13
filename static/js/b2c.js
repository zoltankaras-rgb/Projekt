// =================================================================
// === B2C PORTÁL – klientská logika (b2c.js) =======================
// =================================================================

const B2C_STATE = {
  minOrderValue: 20.00
};

// Inicializácia po načítaní DOM
document.addEventListener('DOMContentLoaded', () => {
  checkSession();
  initializeEventListeners();
  setupCaptcha(); // anti-bot iba ak existuje registračný formulár
});

// -----------------------------------------------------------------
// Anti-bot (captcha + honeypot + timestamp)
// -----------------------------------------------------------------
function setupCaptcha() {
  const regForm = document.getElementById('registerForm');
  if (!regForm) return;

  // timestamp (ms) – minimálny čas vyplnenia
  const tsInput = regForm.querySelector('input[name="form_ts"]');
  if (tsInput) tsInput.value = String(Date.now());

  // honeypot
  const hp = regForm.querySelector('input[name="hp_url"]');
  if (hp) hp.value = '';

  // otázka "nie som robot"
  fetch('/api/b2c/captcha/new')
    .then(r => r.json())
    .then(d => {
      const q = document.getElementById('captcha-question');
      if (q) q.textContent = d.question || 'Koľko je 3 + 4?';
    })
    .catch(() => {});
}

function refreshCaptcha() {
  setupCaptcha();
}

// -----------------------------------------------------------------
// Všeobecné helpers
// -----------------------------------------------------------------

async function apiRequest(endpoint, options = {}) {
  try {
    const response = await fetch(endpoint, {
      method: options.method || 'GET',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      body: options.body ? JSON.stringify(options.body) : null
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Server vrátil neplatnú odpoveď.' }));
      throw new Error(errorData.error || 'Neznáma chyba servera.');
    }
    return await response.json();
  } catch (error) {
    alert(`Chyba: ${error.message}`);
    throw error;
  }
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' })[m]);
}

function openModal(modalId)  { document.getElementById(modalId)?.classList.add('visible'); }
function closeModal(modalId) { document.getElementById(modalId)?.classList.remove('visible'); }

// -----------------------------------------------------------------
// Session + UI
// -----------------------------------------------------------------
async function checkSession() {
  try {
    const data = await apiRequest('/api/b2c/check_session');
    updateUI(data);
  } catch (_) {
    updateUI({ loggedIn: false });
  }
}

function updateUI(sessionData) {
  const loggedOutView = document.getElementById('loggedOutView');
  const loggedInView  = document.getElementById('loggedInView');
  const authLinksContainer = document.getElementById('header-auth-links');

  if (sessionData.loggedIn && sessionData.user?.typ === 'B2C') {
    loggedOutView?.classList.add('hidden');
    loggedInView?.classList.remove('hidden');
    document.getElementById('customer-name').textContent = sessionData.user.name || '';
    authLinksContainer.innerHTML = `Prihlásený: <strong>${escapeHtml(sessionData.user.name || '')}</strong> | <a href="#" onclick="handleLogout(event)">Odhlásiť sa</a>`;

    const points = sessionData.user.points || 0;
    document.getElementById('customer-points').textContent = points;
    document.getElementById('claim-reward-btn')?.classList.toggle('hidden', points <= 0);

    loadCustomerView();
  } else {
    loggedOutView?.classList.remove('hidden');
    loggedInView?.classList.add('hidden');
    if (authLinksContainer) authLinksContainer.innerHTML = '';
    loadPublicPricelist();
  }
}

async function handleLogout(event) {
  event.preventDefault();
  await apiRequest('/api/b2c/logout', { method: 'POST' });
  checkSession();
}

function initializeEventListeners() {
  // Auth formuláre
  document.getElementById('registerForm')?.addEventListener('submit', handleRegistration);
  document.getElementById('loginForm')?.addEventListener('submit', handleLogin);

  // Prepínač doručovacej adresy
  document.getElementById('same-address-checkbox')?.addEventListener('change', (e) => {
    document.getElementById('delivery-address-group')?.classList.toggle('hidden', e.target.checked);
  });

  // Tab v auth sekcii (login/registrácia)
  const authSection = document.getElementById('auth-section');
  if (authSection) {
    authSection.querySelectorAll('.tab-button').forEach(button => {
      button.addEventListener('click', () => {
        authSection.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
        button.classList.add('active');
        authSection.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        document.getElementById(`${button.dataset.tab}-tab`)?.classList.add('active');
      });
    });
  }
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
        if (targetContent) targetContent.classList.add('active');
        if (button.dataset.tab === 'history-content') loadOrderHistory();
      });
    });
    customerTabs.dataset.listenerAttached = 'true';
  }
  // default – otvor „Nová objednávka“
  document.querySelector('#customer-main-tabs .tab-button[data-tab="order-content"]')?.click();
  loadOrderForm();
}

// -----------------------------------------------------------------
// Registrácia + Login
// -----------------------------------------------------------------
async function handleRegistration(event) {
  event.preventDefault();
  const form = event.target;

  // Bezpečné nájdenie prvkov
  const termsEl   = form.querySelector('input[name="gdpr_terms"]');
  const privacyEl = form.querySelector('input[name="gdpr_privacy"]');
  const sameEl    = document.getElementById('same-address-checkbox');
  const tsEl      = form.querySelector('input[name="form_ts"]');

  // Over GDPR (2 povinné checkboxy)
  const termsOk   = !!(termsEl && termsEl.checked);
  const privacyOk = !!(privacyEl && privacyEl.checked);
  if (!termsOk || !privacyOk) {
    alert('Pre registráciu musíte potvrdiť Podmienky a Ochranu osobných údajov.');
    return;
  }

  // Doplň timestamp, ak chýba
  if (tsEl && !tsEl.value) tsEl.value = String(Date.now());

  // Zober dáta z formulára
  const fd = new FormData(form);

  // Ak je "rovnaká adresa" zaškrtnuté, doplň delivery_address
  if (sameEl && sameEl.checked) {
    fd.set('delivery_address', fd.get('address') || '');
  }

  // Kompatibilita – backend môže očakávať aj binárny flag "gdpr"
  fd.set('gdpr', '1');

  // Prevod na obyč. objekt
  const data = Object.fromEntries(fd.entries());

  try {
    const result = await apiRequest('/api/b2c/register', { method: 'POST', body: data });
    alert(result.message || 'OK');

    // Po úspechu reset + prepnúť na login + obnoviť captcha a timestamp
    if ((result.message || '').toLowerCase().includes('úspešne')) {
      form.reset();
      document.querySelector('.tab-button[data-tab="login"]')?.click();

      try {
        const d = await fetch('/api/b2c/captcha/new').then(r => r.json());
        const q = document.getElementById('captcha-question');
        if (q) q.textContent = d.question || 'Koľko je 3 + 4?';
        if (tsEl) tsEl.value = String(Date.now());
      } catch (_) {}
    }
  } catch (_) {
    // apiRequest už zobrazil chybu; skúsme len obnoviť captcha/timestamp
    try {
      const d = await fetch('/api/b2c/captcha/new').then(r => r.json());
      const q = document.getElementById('captcha-question');
      if (q) q.textContent = d.question || 'Koľko je 3 + 4?';
      if (tsEl) tsEl.value = String(Date.now());
    } catch (_) {}
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  try {
    const result = await apiRequest('/api/b2c/login', { method: 'POST', body: data });
    if (result.user) checkSession();
  } catch (_) {}
}

// -----------------------------------------------------------------
// Verejný cenník (pred loginom)
// -----------------------------------------------------------------
async function loadPublicPricelist() {
  const container = document.getElementById('public-pricelist-container');
  if (!container) return;
  container.innerHTML = '<h2>Naša ponuka</h2><p>Načítavam produkty...</p>';
  try {
    const data = await apiRequest('/api/b2c/get-pricelist');
    if (data.products && Object.keys(data.products).length > 0) {
      let html = '<h2>Naša ponuka</h2>';
      const categories = Object.keys(data.products).sort((a, b) =>
        a === 'AKCIA TÝŽĎŇA' ? -1 : (b === 'AKCIA TÝŽĎA' ? 1 : a.localeCompare(b))
      );

      for (const category of categories) {
        const categoryClass = category === 'AKCIA TÝŽĎŇA' ? 'akcia-title' : '';
        html += `<div class="product-category"><h3 class="${categoryClass}">${escapeHtml(category)}</h3>`;
        data.products[category].forEach(p => {
          const titleHtml = `
            <strong class="product-title"
                    data-img="${p.obrazok_url || ''}"
                    style="cursor:${p.obrazok_url ? 'zoom-in' : 'help'}"
                    title="${escapeHtml(p.popis || '')}">
              ${escapeHtml(p.nazov_vyrobku)}
            </strong>`;
          html += `
            <div class="product-item">
              ${titleHtml} - 
              <span>${Number(p.cena_s_dph).toFixed(2)} € / ${p.mj}</span>
              ${p.popis ? `<p style="font-size: .9em; color:#666;">${escapeHtml(p.popis)}</p>` : ''}
            </div>`;
        });
        html += `</div>`;
      }
      container.innerHTML = html;

      attachImageHoverPreviews(container); // náhľady obrázkov (hover/klik)
    } else {
      container.innerHTML = '<h2>Naša ponuka</h2><p>Momentálne nie sú dostupné žiadne produkty.</p>';
    }
  } catch (error) {
    container.innerHTML = `<h2>Naša ponuka</h2><p class="error">Nepodarilo sa načítať produkty: ${escapeHtml(error.message)}</p>`;
  }
}

// -----------------------------------------------------------------
// Objednávka – tvorba & odoslanie
// -----------------------------------------------------------------
async function loadOrderForm() {
  const container = document.getElementById('order-pricelist-container');
  if (!container) return;
  container.innerHTML = '<p>Načítavam ponuku...</p>';
  try {
    const data = await apiRequest('/api/b2c/get-pricelist');
    if (data.products && Object.keys(data.products).length > 0) {
      let html = '<h2>Vytvoriť objednávku</h2>';
      const categories = Object.keys(data.products).sort((a, b) =>
        a === 'AKCIA TÝŽĎŇA' ? -1 : (b === 'AKCIA TÝŽĎŇA' ? 1 : a.localeCompare(b))
      );

      for (const category of categories) {
        const categoryClass = category === 'AKCIA TÝŽĎŇA' ? 'akcia-title' : '';
        html += `<div class="product-category"><h3 class="${categoryClass}">${escapeHtml(category)}</h3>`;
        data.products[category].forEach(p => {
          const byPieceHtml = p.mj === 'kg'
            ? `<label class="checkbox-label" style="font-weight:normal; margin-left:10px;">
                 <input type="checkbox" class="by-piece-checkbox" onchange="toggleItemNote(this, '${p.ean}')"> ks
               </label>
               <button type="button" class="by-piece-button hidden" onclick="openItemNoteModal('${p.ean}')"><i class="fas fa-edit"></i></button>`
            : '';

          const titleHtml = `
            <strong class="product-title"
                    data-img="${p.obrazok_url || ''}"
                    style="cursor:${p.obrazok_url ? 'zoom-in' : 'help'}"
                    title="${escapeHtml(p.popis || '')}">
              ${escapeHtml(p.nazov_vyrobku)}
            </strong>`;

          html += `
            <div class="product-item">
              ${titleHtml} - <span>${Number(p.cena_s_dph).toFixed(2)} € / ${p.mj}</span>
              <div style="display:flex; align-items:center; gap:10px; margin-top:5px;">
                <label>Množstvo:</label>
                <input type="number" class="quantity-input" min="0" step="${p.mj === 'ks' ? '1' : '0.1'}" style="width:80px;"
                       data-ean="${p.ean}"
                       data-name="${escapeHtml(p.nazov_vyrobku)}"
                       data-price-s-dph="${p.cena_s_dph}"
                       data-price-bez-dph="${p.cena_bez_dph}"
                       data-unit="${p.mj}">
                <span>${p.mj}</span>
                ${byPieceHtml}
              </div>
            </div>`;
        });
        html += `</div>`;
      }
      container.innerHTML = html;

      // eventy na množstvá
      container.querySelectorAll('.quantity-input').forEach(input => {
        input.addEventListener('input', updateOrderTotal);
      });

      // náhľady obrázkov (hover/klik)
      attachImageHoverPreviews(container);

      // dátum dodania – default zajtra
      const deliveryDateInput = document.getElementById('deliveryDate');
      if (deliveryDateInput) {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        deliveryDateInput.min = tomorrow.toISOString().split('T')[0];
        deliveryDateInput.value = deliveryDateInput.min;
      }

      // doplnky: časové okno + kód odmeny (vloží do DOM a načíta sloty)
      ensureOrderExtras();

      // submit formulára
      document.getElementById('orderForm')?.addEventListener('submit', handleOrderSubmit);
      updateOrderTotal();
    } else {
      container.innerHTML = '<h2>Vytvoriť objednávku</h2><p>Momentálne nie sú dostupné žiadne produkty.</p>';
    }
  } catch (error) {
    container.innerHTML = `<h2>Vytvoriť objednávku</h2><p class="error">Nepodarilo sa načítať produkty: ${escapeHtml(error.message)}</p>`;
  }
}

function updateOrderTotal() {
  let total_s_dph = 0;
  let total_bez_dph = 0;

  document.querySelectorAll('#orderForm .quantity-input').forEach(input => {
    const quantity      = parseFloat(input.value) || 0;
    const price_s_dph   = parseFloat(input.dataset.priceSDph) || 0;
    const price_bez_dph = parseFloat(input.dataset.priceBezDph) || 0;
    total_s_dph   += quantity * price_s_dph;
    total_bez_dph += quantity * price_bez_dph;
  });

  const total_dph = total_s_dph - total_bez_dph;
  const totalPriceEl       = document.getElementById('total-price');
  const minOrderWarningEl  = document.getElementById('min-order-warning');
  const submitBtn          = document.querySelector('#orderForm button[type="submit"]');

  if (totalPriceEl) {
    totalPriceEl.innerHTML = `
      <div style="font-size:.9em; text-align:right; line-height:1.5;">
        Celkom bez DPH: ${total_bez_dph.toFixed(2).replace('.', ',')} €<br>
        DPH: ${total_dph.toFixed(2).replace('.', ',')} €<br>
        <strong style="font-size:1.2em;">Celkom s DPH (predbežne): ${total_s_dph.toFixed(2).replace('.', ',')} €</strong>
      </div>`;
  }

  if (minOrderWarningEl && submitBtn) {
    if (total_s_dph > 0 && total_s_dph < B2C_STATE.minOrderValue) {
      minOrderWarningEl.classList.remove('hidden');
      submitBtn.disabled = true;
      submitBtn.style.backgroundColor = '#ccc';
    } else {
      minOrderWarningEl.classList.add('hidden');
      submitBtn.disabled = false;
      submitBtn.style.backgroundColor = '';
    }
  }

  const summarySection = document.getElementById('order-summary-section');
  if (summarySection) summarySection.classList.toggle('hidden', total_s_dph <= 0);
}

async function handleOrderSubmit(event) {
  event.preventDefault();

  const items = Array.from(document.querySelectorAll('#orderForm .quantity-input')).map(input => {
    const quantity = parseFloat(input.value);
    if (quantity > 0) {
      const byPieceCheckbox = input.closest('.product-item')?.querySelector('.by-piece-checkbox');
      return {
        ean: input.dataset.ean,
        name: input.dataset.name,
        quantity: quantity,
        unit: (byPieceCheckbox && byPieceCheckbox.checked) ? 'ks' : input.dataset.unit,
        item_note: input.dataset.itemNote || ''
      };
    }
    return null;
  }).filter(Boolean);

  if (!items.length) {
    alert("Vaša objednávka je prázdna.");
    return;
  }

  // min. hodnota
  const totalValue = items.reduce((sum, item) => {
    const input = document.querySelector(`.quantity-input[data-ean="${item.ean}"]`);
    return sum + (item.quantity * (parseFloat(input.dataset.priceSDph) || 0));
  }, 0);

  if (totalValue < B2C_STATE.minOrderValue) {
    alert(`Minimálna hodnota objednávky je ${B2C_STATE.minOrderValue.toFixed(2)} €.`);
    return;
  }

  const orderData = {
    items: items,
    deliveryDate: document.getElementById('deliveryDate')?.value,
    note: document.getElementById('orderNote')?.value,
    // DOPLNENÉ: dodacie okno + kód odmeny (hmotný darček)
    delivery_window: document.getElementById('deliveryWindow')?.value || '',
    reward_code: document.getElementById('rewardCode')?.value?.trim() || ''
  };

  try {
    const result = await apiRequest('/api/b2c/submit-order', { method: 'POST', body: orderData });
    alert(result.message);

    if ((result.message || '').includes("úspešne")) {
      document.getElementById('orderForm')?.reset();
      updateOrderTotal();
      checkSession(); // obnov body a stav
      document.querySelector('.tab-button[data-tab="history-content"]')?.click();
    }
  } catch (_) {}
}

// -----------------------------------------------------------------
// História objednávok – robustné zobrazenie položiek
// -----------------------------------------------------------------
async function loadOrderHistory() {
  const container = document.getElementById('history-container');
  if (!container) return;
  container.innerHTML = '<p>Načítavam históriu objednávok...</p>';
  try {
    const data = await apiRequest('/api/b2c/get-history');
    if (data.orders && data.orders.length > 0) {
      let html = '';
      data.orders.forEach(order => {
        const orderDate    = order.datum_objednavky ? new Date(order.datum_objednavky).toLocaleDateString('sk-SK') : '';
        const deliveryDate = order.pozadovany_datum_dodania ? new Date(order.pozadovany_datum_dodania).toLocaleDateString('sk-SK') : '';

        // preferuj už parsované 'items', inak parsuj 'polozky'
        let items = Array.isArray(order.items) ? order.items : [];
        if (!items.length && typeof order.polozky === 'string') {
          try { items = JSON.parse(order.polozky || '[]'); } catch { items = []; }
        }

        let itemsHtml = '<ul>' + items.map(item => {
          const nm  = item.name || item.nazov || item.nazov_vyrobku || '—';
          const qty = item.quantity ?? item.mnozstvo ?? '';
          const un  = item.unit || item.mj || '';
          const nt  = item.item_note || item.poznamka_k_polozke || '';
          return `<li>${escapeHtml(nm)} - ${escapeHtml(String(qty))} ${escapeHtml(un)} ${nt ? `<i>(${escapeHtml(nt)})</i>` : ''}</li>`;
        }).join('') + '</ul>';

        const finalPrice = (order.finalna_suma_s_dph != null)
          ? `${parseFloat(order.finalna_suma_s_dph).toFixed(2)} €`
          : `(čaká na preváženie)`;
        const stav = order.stav || '';

        html += `
          <div class="history-item">
            <div class="history-header">
              Obj. č. ${escapeHtml(order.cislo_objednavky || String(order.id))} ${orderDate ? `(${orderDate})` : ''} ${stav ? `- Stav: ${escapeHtml(stav)}` : ''}
            </div>
            <div class="history-body">
              ${deliveryDate ? `<p><strong>Požadované vyzdvihnutie:</strong> ${deliveryDate}</p>` : ''}
              <p><strong>Položky:</strong></p>
              ${itemsHtml}
              <p><strong>Finálna suma:</strong> ${finalPrice}</p>
            </div>
          </div>`;
      });
      container.innerHTML = html;
    } else {
      container.innerHTML = '<p>Zatiaľ nemáte žiadne objednávky.</p>';
    }
  } catch (error) {
    container.innerHTML = `<p class="error">Nepodarilo sa načítať históriu objednávok.</p>`;
  }
}

// -----------------------------------------------------------------
// Vernostné odmeny (modál)
// -----------------------------------------------------------------
async function showRewardsModal() {
  const listContainer = document.getElementById('rewards-list-container');
  document.getElementById('modal-customer-points').textContent = document.getElementById('customer-points').textContent;
  listContainer.innerHTML = '<p>Načítavam dostupné odmeny...</p>';
  openModal('rewards-modal');
  try {
    const data = await apiRequest('/api/b2c/get_rewards');
    const currentPoints = parseInt(document.getElementById('modal-customer-points').textContent || '0', 10);
    if (data.rewards && data.rewards.length > 0) {
      let html = '';
      let hasAvailableReward = false;
      data.rewards.forEach(reward => {
        const canAfford = currentPoints >= reward.potrebne_body;
        if (canAfford) hasAvailableReward = true;
        html += `<div class="history-item" style="padding:10px; opacity:${canAfford ? '1' : '0.5'};">
          <strong>${escapeHtml(reward.nazov_odmeny)}</strong> (${reward.potrebne_body} bodov)
          <button class="button button-small" style="float:right;" ${!canAfford ? 'disabled' : ''} onclick="claimReward(${reward.id}, ${reward.potrebne_body})">Vybrať</button>
        </div>`;
      });
      listContainer.innerHTML = hasAvailableReward ? html : '<p>Nemáte dostatok bodov na uplatnenie žiadnej z dostupných odmien.</p>';
    } else {
      listContainer.innerHTML = '<p>Momentálne nie sú k dispozícii žiadne odmeny.</p>';
    }
  } catch (e) {
    listContainer.innerHTML = `<p class="error">Nepodarilo sa načítať odmeny: ${escapeHtml(e.message)}</p>`;
  }
}

async function claimReward(rewardId, pointsNeeded) {
  if (!confirm(`Naozaj si chcete uplatniť túto odmenu za ${pointsNeeded} bodov? Bude pridaná k Vašej nasledujúcej objednávke.`)) return;
  try {
    const result = await apiRequest('/api/b2c/claim_reward', { method: 'POST', body: { reward_id: rewardId } });
    alert(result.message);
    if (result.new_points !== undefined) {
      document.getElementById('customer-points').textContent = result.new_points;
      document.getElementById('modal-customer-points').textContent = result.new_points;
      document.getElementById('claim-reward-btn')?.classList.toggle('hidden', result.new_points <= 0);
    }
    closeModal('rewards-modal');
  } catch (_) {}
}

// -----------------------------------------------------------------
// Poznámky k položkám „na kusy“ + náhľad obrázkov
// -----------------------------------------------------------------
function toggleItemNote(checkbox, ean) {
  const itemDiv = checkbox.closest('.product-item');
  const noteButton = itemDiv.querySelector('.by-piece-button');
  const quantityInput = itemDiv.querySelector('.quantity-input');

  if (noteButton) noteButton.classList.toggle('hidden', !checkbox.checked);
  if (quantityInput) {
    if (checkbox.checked) {
      quantityInput.step = "1";
      if (quantityInput.value) quantityInput.value = String(Math.round(parseFloat(quantityInput.value)));
      openItemNoteModal(ean);
    } else {
      quantityInput.step = "0.1";
      quantityInput.dataset.itemNote = "";
    }
  }
  updateOrderTotal();
}

function openItemNoteModal(ean) {
  const input = document.querySelector(`.quantity-input[data-ean="${ean}"]`);
  if (!input) return;
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

/** Plávajúci náhľad obrázka pre .product-title[data-img] */
function attachImageHoverPreviews(root = document) {
  let preview = document.getElementById('b2c-img-preview');
  if (!preview) {
    preview = document.createElement('div');
    preview.id = 'b2c-img-preview';
    preview.style.position = 'fixed';
    preview.style.display = 'none';
    preview.style.zIndex = '10000';
    preview.style.background = '#fff';
    preview.style.border = '1px solid #e5e7eb';
    preview.style.padding = '4px';
    preview.style.boxShadow = '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)';
    preview.innerHTML = '<img alt="náhľad" style="max-width:320px;max-height:240px;display:block;">';
    document.body.appendChild(preview);
  }
  const imgEl = preview.querySelector('img');

  root.querySelectorAll('.product-title[data-img]').forEach(el => {
    const url = el.getAttribute('data-img');
    if (!url) return;

    const show = (e) => {
      imgEl.src = url;
      position(e);
      preview.style.display = 'block';
    };
    const hide = () => { preview.style.display = 'none'; };

    const position = (e) => {
      const offset = 16;
      let x = (e.clientX || 0) + offset;
      let y = (e.clientY || 0) + offset;
      const vw = window.innerWidth, vh = window.innerHeight;
      const rect = preview.getBoundingClientRect();
      if (x + rect.width > vw)  x = vw - rect.width - offset;
      if (y + rect.height > vh) y = vh - rect.height - offset;
      preview.style.left = x + 'px';
      preview.style.top  = y + 'px';
    };

    el.addEventListener('mouseenter', show);
    el.addEventListener('mousemove', (e) => { if (preview.style.display === 'block') position(e); });
    el.addEventListener('mouseleave', hide);
    el.addEventListener('click', show); // klik tiež zobrazí
  });
}

// === DOPLNOK: Info modal pre produkty (recyklované z tvojho doplnku) ===
function ensureProductInfoModal(){
  if (document.getElementById('product-info-modal')) return;
  const wrap = document.createElement('div');
  wrap.id = 'product-info-modal';
  wrap.className = 'modal-overlay';
  wrap.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h4 id="pi-title"></h4>
        <button class="modal-close" onclick="closeModal('product-info-modal')">&times;</button>
      </div>
      <div id="pi-body"></div>
    </div>`;
  document.body.appendChild(wrap);
}
function openProductInfo(name, img, desc){
  ensureProductInfoModal();
  const m = document.getElementById('product-info-modal');
  m.querySelector('#pi-title').textContent = name || 'Info o produkte';
  const safeDesc = escapeHtml(desc || '');
  const imgHtml = img ? `<img src="${img}" alt="${escapeHtml(name||'')}" style="max-width:100%;max-height:280px;display:block;margin-bottom:8px;border:1px solid #e5e7eb;border-radius:8px">` : '';
  m.querySelector('#pi-body').innerHTML = `${imgHtml}<div style="white-space:pre-wrap;color:#334155">${safeDesc || '<span class="muted">Bez popisu.</span>'}</div>`;
  openModal('product-info-modal');
}
/** ======= INFO MODAL (detail produktu) a striktné pravidlá odosielania ======= **/

// 1) Garant: objednávka sa pošle len fyzickým klikom na tlačidlo "Odoslať"
function enforceManualSubmit() {
  const form = document.getElementById('orderForm');
  if (!form) return;

  // Blokuj Enter (okrem textarea)
  form.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target && e.target.tagName !== 'TEXTAREA') e.preventDefault();
  });

  // Dovoľ odoslanie iba po pointer kliku na submit
  let submitViaPointer = false;
  form.addEventListener('pointerdown', (e) => {
    const btn = e.target && e.target.closest('button[type="submit"], input[type="submit"]');
    if (btn) submitViaPointer = true;
  }, true);

  form.addEventListener('submit', (e) => {
    if (!submitViaPointer) e.preventDefault();
    submitViaPointer = false;
  });

  // Všetky tlačidlá v cenníku nesmú byť submit
  form.querySelectorAll('#order-pricelist-container button').forEach((b) => {
    if (!b.getAttribute('type')) b.setAttribute('type', 'button');
    if (b.type.toLowerCase() === 'submit') b.type = 'button';
  });
}

// 2) Detailný INFO modal
function ensureProductInfoModalV2() {
  if (document.getElementById('product-info-modal')) return;
  const wrap = document.createElement('div');
  wrap.id = 'product-info-modal';
  wrap.className = 'modal-overlay';
  wrap.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h4>Informácie o produkte</h4>
        <button class="modal-close" aria-label="Zavrieť" onclick="closeModal('product-info-modal')">&times;</button>
      </div>
      <div class="modal-body">
        <div id="pim-title" style="font-weight:700;font-size:1.05rem"></div>
        <div id="pim-meta" class="meta"></div>
        <div class="kv" id="pim-kv"></div>
        <div id="pim-desc" style="margin-top:10px"></div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
}

// Použi dataset z tlačidla (bez hoverov, bez náhľadov)
function handleInfoClick(btn) {
  ensureProductInfoModalV2();

  const row = btn.closest('.product-item') || document;
  const data = {
    title:       btn.dataset.title       || row.dataset.title       || '',
    price:       btn.dataset.price       || row.dataset.price       || '',
    unit:        btn.dataset.unit        || row.dataset.unit        || '',
    composition: btn.dataset.composition || row.dataset.composition || '',
    allergens:   btn.dataset.allergens   || row.dataset.allergens   || '',
    storage:     btn.dataset.storage     || row.dataset.storage     || '',
    origin:      btn.dataset.origin      || row.dataset.origin      || '',
    description: btn.dataset.description || row.dataset.description || ''
  };

  const m = document.getElementById('product-info-modal');
  m.querySelector('#pim-title').textContent = data.title || 'Produkt';
  m.querySelector('#pim-meta').textContent  = [data.price, data.unit].filter(Boolean).join(' · ');

  const kv = m.querySelector('#pim-kv');
  kv.innerHTML = '';
  if (data.composition) kv.innerHTML += `<div>Zloženie</div><div>${escapeHtml(data.composition)}</div>`;
  if (data.allergens)   kv.innerHTML += `<div>Alergény</div><div>${escapeHtml(data.allergens)}</div>`;
  if (data.storage)     kv.innerHTML += `<div>Skladovanie</div><div>${escapeHtml(data.storage)}</div>`;
  if (data.origin)      kv.innerHTML += `<div>Pôvod</div><div>${escapeHtml(data.origin)}</div>`;

  m.querySelector('#pim-desc').textContent = data.description || '';
  openModal('product-info-modal');
}

// === Override: doplň ? info do verejnej ponuky ===
// === PUBLIC: cenník pred prihlásením (bez hover obrázkov, s Info modalom) ===
const _orig_loadPublicPricelist = loadPublicPricelist;
loadPublicPricelist = async function(){
  const container = document.getElementById('public-pricelist-container');
  if (!container) return _orig_loadPublicPricelist();
  container.innerHTML = '<h2>Naša ponuka</h2><p>Načítavam produkty...</p>';
  try{
    const data = await apiRequest('/api/b2c/get-pricelist');
    if (data.products && Object.keys(data.products).length){
      let html = '<h2>Naša ponuka</h2>';
      const cats = Object.keys(data.products).sort((a,b)=> a==='AKCIA TÝŽĎA'?-1:(b==='AKCIA TÝŽĎA'?1:a.localeCompare(b)));
      for (const cat of cats){
        html += `<div class="product-category"><h3>${escapeHtml(cat)}</h3>`;
        data.products[cat].forEach(p=>{
          // priprav dáta do datasetov
          const title = escapeHtml(p.nazov_vyrobku);
          const price = `${Number(p.cena_s_dph).toFixed(2)} €`;
          const unit  = p.mj;
          const composition = p.zlozenie || '';
          const allergens   = p.alergeny || '';
          const storage     = p.skladovanie || '';
          const origin      = p.povod || '';
          const desc        = p.popis || '';

          // render: názov | cena | jednotka | akcie (INFO)
          html += `
            <div class="product-item"
                 data-title="${title}"
                 data-price="${escapeHtml(price)}"
                 data-unit="${escapeHtml(unit)}"
                 data-composition="${escapeHtml(composition)}"
                 data-allergens="${escapeHtml(allergens)}"
                 data-storage="${escapeHtml(storage)}"
                 data-origin="${escapeHtml(origin)}"
                 data-description="${escapeHtml(desc)}">
              <div class="pi-title"><strong>${title}</strong></div>
              <div class="pi-price">${escapeHtml(price)} / ${escapeHtml(unit)}</div>
              <div class="pi-qty"></div>
              <div class="pi-actions">
                <button type="button" class="info-btn"
                        data-title="${title}"
                        data-price="${escapeHtml(price)}"
                        data-unit="${escapeHtml(unit)}"
                        data-composition="${escapeHtml(composition)}"
                        data-allergens="${escapeHtml(allergens)}"
                        data-storage="${escapeHtml(storage)}"
                        data-origin="${escapeHtml(origin)}"
                        data-description="${escapeHtml(desc)}"
                        onclick="handleInfoClick(this)">
                  <i class="fa fa-circle-info"></i> Info
                </button>
              </div>
            </div>`;
        });
        html += `</div>`;
      }
      container.innerHTML = html;
      // ZÁMERNE nevoláme attachImageHoverPreviews – nechceme hover náhľady
    }else{
      container.innerHTML = '<h2>Naša ponuka</h2><p>Momentálne nie sú dostupné žiadne produkty.</p>';
    }
  }catch(e){
    container.innerHTML = `<h2>Naša ponuka</h2><p class="error">Nepodarilo sa načítať produkty: ${escapeHtml(e.message)}</p>`;
  }
};

// === ORDER: cenník po prihlásení (grid + Info vpravo, len klik "Odoslať" odosiela) ===
const _orig_loadOrderForm = loadOrderForm;
loadOrderForm = async function(){
  const container = document.getElementById('order-pricelist-container');
  if (!container) return _orig_loadOrderForm();
  container.innerHTML = '<p>Načítavam ponuku...</p>';
  try{
    const data = await apiRequest('/api/b2c/get-pricelist');
    if (data.products && Object.keys(data.products).length){
      let html = '<h2>Vytvoriť objednávku</h2>';
      const cats = Object.keys(data.products).sort((a,b)=> a==='AKCIA TÝŽĎA'?-1:(b==='AKCIA TÝŽĎA'?1:a.localeCompare(b)));

      for (const cat of cats){
        html += `<div class="product-category"><h3 class="${cat==='AKCIA TÝŽĎA'?'akcia-title':''}">${escapeHtml(cat)}</h3>`;
        data.products[cat].forEach(p=>{
          const title = escapeHtml(p.nazov_vyrobku);
          const price = `${Number(p.cena_s_dph).toFixed(2)} €`;
          const unit  = p.mj;
          const byPieceHtml = p.mj==='kg'
            ? `<label class="checkbox-label" style="font-weight:normal;">
                 <input type="checkbox" class="by-piece-checkbox" onchange="toggleItemNote(this, '${p.ean}')"> ks
               </label>
               <button type="button" class="by-piece-button hidden" onclick="openItemNoteModal('${p.ean}')"><i class="fas fa-edit"></i></button>`
            : '';

          html += `
          <div class="product-item"
               data-title="${title}"
               data-price="${escapeHtml(price)}"
               data-unit="${escapeHtml(unit)}"
               data-composition="${escapeHtml(p.zlozenie||'')}"
               data-allergens="${escapeHtml(p.alergeny||'')}"
               data-storage="${escapeHtml(p.skladovanie||'')}"
               data-origin="${escapeHtml(p.povod||'')}"
               data-description="${escapeHtml(p.popis||'')}">

            <div class="pi-title"><strong>${title}</strong></div>
            <div class="pi-price">${escapeHtml(price)} / ${escapeHtml(unit)}</div>

            <div class="pi-qty" style="display:flex;align-items:center;gap:10px;">
              <label for="qty-${p.ean}" style="white-space:nowrap;">Množstvo:</label>
              <input id="qty-${p.ean}" type="number" class="quantity-input" min="0" step="${p.mj==='ks'?'1':'0.1'}" style="width:110px;"
                     data-ean="${p.ean}"
                     data-name="${title}"
                     data-price-s-dph="${p.cena_s_dph}"
                     data-price-bez-dph="${p.cena_bez_dph}"
                     data-unit="${p.mj}">
              <span>${p.mj}</span>
              ${byPieceHtml}
            </div>

            <div class="pi-actions">
              <button type="button" class="info-btn"
                      data-title="${title}"
                      data-price="${escapeHtml(price)}"
                      data-unit="${escapeHtml(unit)}"
                      data-composition="${escapeHtml(p.zlozenie||'')}"
                      data-allergens="${escapeHtml(p.alergeny||'')}"
                      data-storage="${escapeHtml(p.skladovanie||'')}"
                      data-origin="${escapeHtml(p.povod||'')}"
                      data-description="${escapeHtml(p.popis||'')}"
                      onclick="handleInfoClick(this)">
                <i class="fa fa-circle-info"></i> Info
              </button>
            </div>
          </div>`;
        });
        html += `</div>`;
      }

      container.innerHTML = html;

      // Eventy na množstvá a zákaz Enter-submit
      container.querySelectorAll('.quantity-input').forEach(input => {
        input.addEventListener('input', updateOrderTotal);
      });

      // DÁTUM – zajtrajšok
      const deliveryDateInput = document.getElementById('deliveryDate');
      if (deliveryDateInput){
        const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate()+1);
        deliveryDateInput.min = tomorrow.toISOString().split('T')[0];
        deliveryDateInput.value = deliveryDateInput.min;
      }

      // Doplnky
      ensureOrderExtras();

      // Form submit + guardy
      document.getElementById('orderForm')?.addEventListener('submit', handleOrderSubmit);
      enforceManualSubmit();

      updateOrderTotal();
    }else{
      container.innerHTML = '<h2>Vytvoriť objednávku</h2><p>Momentálne nie sú dostupné žiadne produkty.</p>';
    }
  }catch(e){
    container.innerHTML = `<h2>Vytvoriť objednávku</h2><p class="error">Nepodarilo sa načítať produkty: ${escapeHtml(e.message)}</p>`;
  }
};

// -----------------------------------------------------------------
// DOPLNOK – bez zásahu do šablóny: dodacie okno + kód odmeny
// -----------------------------------------------------------------
function ensureOrderExtras() {
  const host = document.getElementById('order-summary-section') || document.getElementById('orderForm') || document.body;
  if (!host) return;

  // 1) Časové okno
  if (!document.getElementById('deliveryWindow')) {
    const g = document.createElement('div');
    g.className = 'form-group';
    g.innerHTML = `
      <label for="deliveryWindow">Časové okno doručenia (nepovinné):</label>
      <select id="deliveryWindow" name="deliveryWindow">
        <option value="">-- vyberte časové okno (nepovinné) --</option>
      </select>`;
    const target = document.querySelector('.total-summary') || host.lastChild;
    host.insertBefore(g, target);
    // načítaj sloty
    loadDeliveryWindows();
  }

  // 2) Kód odmeny (hmotný darček)
  if (!document.getElementById('rewardCode')) {
    const g = document.createElement('div');
    g.className = 'form-group';
    g.innerHTML = `
      <label for="rewardCode">Kód odmeny (nepovinné):</label>
      <input type="text" id="rewardCode" name="rewardCode" placeholder="NAPR: DARCEK-KLOBASA">`;
    const target = document.querySelector('.total-summary') || host.lastChild;
    host.insertBefore(g, target);
  }
}

async function loadDeliveryWindows() {
  const sel = document.getElementById('deliveryWindow');
  if (!sel) return;

  // presne dve pracovné okná, Po–Pia, najneskôr do 15:00
  sel.innerHTML = [
    '<option value="">-- vyberte časové okno (nepovinné) --</option>',
    '<option value="workdays_08_12">Po–Pia 08:00–12:00</option>',
    '<option value="workdays_12_15">Po–Pia 12:00–15:00</option>'
  ].join('');
}