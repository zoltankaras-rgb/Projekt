// =================================================================
// === HLAVNÝ SKRIPT PRE MODUL KANCELÁRIA (KANCELARIA.JS) ===
// =================================================================

// --- Globálne premenné a pomocné funkcie ---
(function () {
  if (typeof window.activeTinyMceEditor === 'undefined') {
    window.activeTinyMceEditor = null;
  }
})();

let officeInitialData = {};
let b2bAdminData = { customers: [], pricelists: [], productsByCategory: {} };
let catalogManagementData = {};
let fleetState = { vehicles: [], logs: [], refuelings: [], costs: [], analysis: {}, selected_vehicle_id: null, selected_year: null, selected_month: null, last_odometer: 0 };
let hygieneState = { agents: [] };
let googleChartsLoaded = null;

// Fallback escapeHtml (ak už existuje v common.js, použije sa ten)
if (typeof window.escapeHtml !== 'function') {
  window.escapeHtml = function (s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };
}

// Fallback apiRequest (ak už existuje v common.js, použije sa ten)
if (typeof window.apiRequest !== 'function') {
  window.apiRequest = async function (url, options = {}) {
    const opts = Object.assign({ credentials: 'same-origin', headers: {} }, options);
    if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
      opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(url, opts);
    const ct = (res.headers.get('content-type') || '').toLowerCase();
    if (res.status === 401) {
      if (typeof window.onUnauthorized === 'function') window.onUnauthorized();
      return { error: 'Unauthorized', status: 401 };
    }
    const payload = ct.includes('application/json') ? await res.json() : await res.text();
    if (!res.ok) {
      const msg = (payload && payload.error) ? payload.error : `HTTP ${res.status}`;
      return { error: msg, status: res.status, raw: payload };
    }
    return payload;
  };
}

// Jemný fallback na status, ak ho nemáš v common.js
function showStatus(msg, isError) {
  if (typeof window.status === 'function') return window.status(msg, isError);
  if (typeof window.alert === 'function' && isError) alert(msg);
  (isError ? console.error : console.log)(msg);
}

// =================================================================
// === AUTH VRSTVA ==================================================
// =================================================================

function showLogin() {
  const loginWrapper = document.getElementById('login-wrapper');
  const appContainer = document.getElementById('app-container');
  if (appContainer) appContainer.classList.add('hidden');
  if (loginWrapper)  loginWrapper.classList.remove('hidden');
}

function showApp(user) {
  const loginWrapper = document.getElementById('login-wrapper');
  const appContainer = document.getElementById('app-container');
  if (loginWrapper)  loginWrapper.classList.add('hidden');
  if (appContainer)  appContainer.classList.remove('hidden');
  const ui = document.getElementById('user-info');
  if (ui) ui.textContent = user && user.username ? `Vitajte, ${user.username}` : 'Vitajte';
}

async function tryAuthPing() {
  const r = await apiRequest('/api/kancelaria/getDashboardData', { method: 'GET' });
  if (!r || r.error) {
    if (r && r.status === 401) return false;
    // iné chyby neriešime ako logout – iba vrátime false, aby sme zobrazili login
    return false;
  }
  return true;
}

function bindLoginForm() {
  const form = document.getElementById('login-form');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    if (!username || !password) {
      showStatus('Zadaj používateľské meno a heslo.', true);
      return;
    }
    try {
      const res = await fetch('/api/internal/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      if (res.status === 401) {
        showStatus('Nesprávne prihlasovacie údaje.', true);
        return;
      }
      if (!res.ok) {
        showStatus('Prihlásenie zlyhalo. Skús znova.', true);
        return;
      }
      // očakávame JSON s informáciami o userovi; ak nie je, nevadí
      let payload = {};
      try { payload = await res.json(); } catch(_) {}
      showApp(payload && payload.user ? payload.user : { username });

      // Po úspešnom logine spusti UI
      loadAndShowOfficeMenu();
    } catch (err) {
      console.error('Login error:', err);
      showStatus('Prihlásenie sa nepodarilo (sieťová chyba).', true);
    }
  });

  const logoutBtn = document.getElementById('logout-button');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
      try {
        // preferovaný endpoint v projekte
        let res = await fetch('/api/internal/logout', { method: 'POST', credentials: 'same-origin' });
        if (!res.ok) {
          // fallback na /logout, ak existuje
          await fetch('/logout', { method: 'POST', credentials: 'same-origin' });
        }
      } catch (_) {}
      // prepnúť do login režimu
      showLogin();
    });
  }
}

// Globálny callback pre 401 z common.js
window.onUnauthorized = (function () {
  let notified = false;
  return function () {
    if (notified) return; // zabrániť opakovaniu
    notified = true;
    showLogin();
    showStatus('Vaša session vypršala. Prosím, prihláste sa znova.', true);
    // Po zobrazení loginu môžeme po krátkom čase resetnúť flag, aby sa prípadné ďalšie 401 dali znovu oznámiť
    setTimeout(() => { notified = false; }, 1500);
  };
})();

// =================================================================
// === ŠTART A SIDEBAR =============================================
// =================================================================

function loadAndShowOfficeMenu() {
  initializeSidebar();

  // Úvodná sekcia
  document.querySelectorAll('.main-content .content-section').forEach(s => s.style.display = 'none');
  const dashboardSection = document.getElementById('section-dashboard');
  if (dashboardSection) dashboardSection.style.display = 'block';

  setupSection('section-dashboard');
}

function initializeSidebar() {
  const sidebarLinks = document.querySelectorAll('.sidebar-nav a.sidebar-link');
  const contentSections = document.querySelectorAll('.main-content .content-section');

  sidebarLinks.forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      sidebarLinks.forEach(l => l.classList.remove('active'));
      link.classList.add('active');

      const targetSectionId = link.dataset.section;
      const targetSection = document.getElementById(targetSectionId);
      if (!targetSection) return;

      contentSections.forEach(s => s.style.display = 'none');
      targetSection.style.display = 'block';
      setupSection(targetSectionId);
    });
  });
}

// =================================================================
// === NÁRADIE NA DYNAMICKÝ IMPORT (ERP, MAIL, SMS) =================
// =================================================================

function loadScriptOnce(src, dataAttr) {
  return new Promise((resolve, reject) => {
    const existing = Array.from(document.scripts).find(s =>
      s.getAttribute(dataAttr) === '1' || (s.src && s.src.indexOf(src) !== -1)
    );
    if (existing) {
      if (existing.dataset.loaded === '1') return resolve();
      existing.addEventListener('load', () => resolve());
      existing.addEventListener('error', () => reject(new Error('Načítanie skriptu zlyhalo: ' + src)));
      return;
    }
    const s = document.createElement('script');
    s.src = src + (src.indexOf('?') === -1 ? '?' : '&') + 'v=' + Date.now();
    s.defer = true;
    s.setAttribute(dataAttr, '1');
    s.onload  = () => { s.dataset.loaded = '1'; resolve(); };
    s.onerror = () => reject(new Error('Načítanie skriptu zlyhalo: ' + src));
    document.head.appendChild(s);
  });
}

async function ensureErpAdminLoaded() {
  if (typeof window.initializeErpAdminModule === 'function') return;
  await loadScriptOnce('/static/js/kancelaria_modules/erp_admin.js', 'data-erp-admin');
}

async function ensureMailLoaded() {
  if (typeof window.initializeMailModule === 'function') return;
  await loadScriptOnce('/static/js/kancelaria_modules/mail.js', 'data-mail');
}

async function ensureSmsLoaded() {
  if (typeof window.initializeSMSConnectorModule === 'function') return;
  await loadScriptOnce('/static/js/kancelaria_modules/sms_connector.js', 'data-sms');
}

// =================================================================
// === INIT DÁT KANCELÁRIE (ak potrebné) ===========================
// =================================================================
async function ensureOfficeDataIsLoaded() {
  if (Object.keys(officeInitialData).length !== 0) return;

  async function safeFetchJson(url) {
    try {
      const res = await fetch(url, { credentials: 'same-origin' });
      if (!res.ok) return null;
      const ct = (res.headers.get('content-type') || '').toLowerCase();
      if (!ct.includes('application/json')) return null;
      return await res.json();
    } catch (_) {
      return null;
    }
  }

  let data = await safeFetchJson('/api/kancelaria/baseData');
  if (!data) data = await safeFetchJson('/api/kancelaria/getKancelariaBaseData');

  if (!data) {
    console.warn('[Kancelaria] baseData sa nepodarilo načítať – používam fallback hodnoty.');
    officeInitialData = {
      productsWithoutRecipe: [],
      recipeCategories: [],
      itemTypes: ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál'],
    };
    return;
  }

  officeInitialData = {
    productsWithoutRecipe: data.productsWithoutRecipe || data.products_without_recipe || data.products || [],
    recipeCategories:      data.recipeCategories      || data.recipe_categories      || data.categories || [],
    itemTypes:             data.itemTypes             || data.item_types             || data.stockCategories || ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál'],
  };
}

// =================================================================
// === ROUTER: PREPÍNAČ SEKCIÍ =====================================
// =================================================================

async function setupSection(sectionId) {
  const sectionElement = document.getElementById(sectionId);
  if (!sectionElement) return;

  if (sectionId === 'section-erp-admin') {
    if (sectionElement.dataset.initialized === 'true' &&
        typeof window.initializeErpAdminModule === 'function') return;
    try {
      await ensureErpAdminLoaded();
      if (typeof window.initializeErpAdminModule === 'function') {
        window.initializeErpAdminModule();
        sectionElement.dataset.initialized = 'true';
      } else {
        console.error('initializeErpAdminModule stále nie je definovaná po načítaní erp_admin.js');
        showStatus('Nepodarilo sa načítať Správu ERP (erp_admin.js).', true);
      }
    } catch (err) {
      console.error('Načítanie erp_admin.js zlyhalo:', err);
      showStatus('Nepodarilo sa načítať Správu ERP (erp_admin.js).', true);
    }
    return;
  }

  if (sectionId === 'section-mail') {
    if (sectionElement.dataset.initialized === 'true' &&
        typeof window.initializeMailModule === 'function') return;
    try {
      await ensureMailLoaded();
      if (typeof window.initializeMailModule === 'function') {
        window.initializeMailModule();
        sectionElement.dataset.initialized = 'true';
      } else {
        console.error('initializeMailModule stále nie je definovaná po načítaní mail.js');
        showStatus('Nepodarilo sa načítať Poštu (mail.js).', true);
      }
    } catch (err) {
      console.error('Načítanie mail.js zlyhalo:', err);
      showStatus('Nepodarilo sa načítať Poštu (mail.js).', true);
    }
    return;
  }

  if (!sectionElement.dataset.initialized) {
    switch (sectionId) {
      case 'section-dashboard':       if (typeof initializeDashboardModule === 'function') initializeDashboardModule(); break;
      case 'section-order-forecast':  if (typeof initializeOrderForecastModule === 'function') initializeOrderForecastModule(); break;
      case 'section-stock':           if (typeof initializeStockModule === 'function') initializeStockModule(); break;
      case 'section-planning':        if (typeof initializePlanningModule === 'function') initializePlanningModule(); break;
      case 'section-b2b-admin':
        if (typeof initializeB2BAdminModule === 'function') {
          initializeB2BAdminModule();
        } else {
          console.error('B2B modul sa nenačítal – chýba initializeB2BAdminModule');
          showStatus('B2B modul sa nenačítal. Skús obnoviť stránku (Ctrl+F5).', true);
        }
        break;
      case 'section-b2c-admin':       if (typeof initializeB2CAdminModule === 'function') initializeB2CAdminModule(); break;
      case 'section-haccp':           if (typeof initializeHaccpModule === 'function') initializeHaccpModule(); break;
      case 'section-fleet':           if (typeof initializeFleetModule === 'function') initializeFleetModule(); break;
      case 'section-hygiene':         if (typeof initializeHygieneModule === 'function') initializeHygieneModule(); break;
      case 'section-profitability':   if (typeof initializeProfitabilityModule === 'function') initializeProfitabilityModule(); break;
      case 'section-costs':           if (typeof initializeCostsModule === 'function') initializeCostsModule(); break;
      case 'section-sms-connector':
        try {
          await ensureSmsLoaded();
          if (typeof window.initializeSMSConnectorModule === 'function') {
            window.initializeSMSConnectorModule();
          } else {
            showStatus('Nepodarilo sa načítať SMS modul.', true);
          }
        } catch (e) {
          console.error('Načítanie sms_connector.js zlyhalo:', e);
          showStatus('Nepodarilo sa načítať SMS modul.', true);
        }
        break;
    }
    sectionElement.dataset.initialized = 'true';
  }
}

// =================================================================
// === MODÁLNE OKNÁ =================================================
// =================================================================

async function showModal(title, contentPromise) {
  const modalContainer = document.getElementById('modal-container');
  modalContainer.innerHTML =
    `<div class="modal-backdrop"></div>
     <div class="modal-content">
       <div class="modal-header">
         <h3>${escapeHtml(title || '')}</h3>
         <button class="close-btn" title="Zavrieť">&times;</button>
       </div>
       <div class="modal-body"><p>Načítavam...</p></div>
     </div>`;
  modalContainer.style.display = 'flex';

  const closeModal = () => {
    try {
      if (window.activeTinyMceEditor) {
        tinymce.remove(window.activeTinyMceEditor);
        window.activeTinyMceEditor = null;
      }
    } catch(_){}
    modalContainer.style.display = 'none';
    modalContainer.innerHTML = '';
  };
  modalContainer.querySelector('.close-btn').onclick = closeModal;
  modalContainer.querySelector('.modal-backdrop').onclick = closeModal;

  try {
    const maybePromise = (typeof contentPromise === 'function') ? contentPromise() : contentPromise;
    const result = await Promise.resolve(maybePromise);
    if (typeof result === 'string') {
      modalContainer.querySelector('.modal-body').innerHTML = result;
    } else if (result && typeof result === 'object' && 'html' in result) {
      modalContainer.querySelector('.modal-body').innerHTML = result.html;
      if (typeof result.onReady === 'function') result.onReady();
    } else {
      modalContainer.querySelector('.modal-body').innerHTML = '<p class="error">Neplatný obsah modalu.</p>';
    }
  } catch (e) {
    modalContainer.querySelector('.modal-body').innerHTML =
      `<p class="error">Chyba pri načítaní obsahu: ${e && e.message ? escapeHtml(e.message) : escapeHtml(String(e))}</p>`;
  }
}

// Sprístupni showModal globálne (niektoré moduly ho volajú priamo)
window.showModal = showModal;

// =================================================================
// === BOOT ========================================================
// =================================================================

document.addEventListener('DOMContentLoaded', async () => {
  try {
    bindLoginForm();
    // Auth brána – iba ak sme prihlásení, spustíme aplikáciu
    const loggedIn = await tryAuthPing();
    if (loggedIn) {
      showApp();
      loadAndShowOfficeMenu();
    } else {
      showLogin();
    }
  } catch (e) {
    console.error('Inicializácia Kancelárie zlyhala:', e);
    showStatus('Nepodarilo sa inicializovať modul Kancelária.', true);
    showLogin();
  }
});
