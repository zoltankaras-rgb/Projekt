// =================================================================
// === ZDIEĽANÉ FUNKCIE PRE VŠETKY MODULY (COMMON.JS) ===
// =================================================================

// --- Globálny stav pre throttling 401
window.__AUTH__ = { locked: false, last401: 0, muteMs: 6000 };

// Pomocné – určí, či je API "z cudzieho modulu" vzhľadom na aktuálnu stránku
function isForeignModuleCall(url) {
  try {
    const u = new URL(url, window.location.origin);
    const path = u.pathname || '';

    const onOfficeRoute     = window.location.pathname.includes('/kancelaria');
    const onExpeditionRoute = window.location.pathname.includes('/expedicia') || window.location.pathname.includes('/leaderexpedicia');
    const onVyrobaRoute     = window.location.pathname.includes('/vyroba');

    const isOfficeApi   = /^\/api\/kancelaria\//.test(path);
    const isExpedApi    = /^\/api\/expedicia\//.test(path);
    const isVyrobaApi   = /^\/api\/vyroba\//.test(path);

    // cudzí modul = API danej sekcie a nie sme na jej stránke
    if (isOfficeApi   && !onOfficeRoute)     return true;
    if (isExpedApi    && !onExpeditionRoute) return true;
    if (isVyrobaApi   && !onVyrobaRoute)     return true;
    return false;
  } catch (_) {
    return false;
  }
}

// =================================================================
// === API REQUEST WRAPPER (fetch + 401/403 + redirect) =============
// =================================================================

function apiURL(path) {
  if (!path) return '/';
  return path.startsWith('/') ? path : `/${path}`;
}

// Hlavný wrapper – vždy pošli cookies, jednotné handlovanie 401/403
window.apiRequest = async function apiRequestCore(url, options = {}) {
  const opts = Object.assign(
    {
      method: 'GET',
      credentials: 'include',      // dôležité – pošli session cookie
      headers: {},
    },
    options
  );

  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
    opts.body = JSON.stringify(opts.body);
  }

  let response;
  try {
    response = await fetch(url, opts);
  } catch (err) {
    console.error('[apiRequest] Network error:', err);
    return { error: 'Network error', detail: String(err) };
  }

  const ct = (response.headers.get('content-type') || '').toLowerCase();
  let payload = null;
  try {
    payload = ct.includes('application/json') ? await response.json() : await response.text();
  } catch (_) {
    payload = null;
  }

  // 401 – neautorizovaný
  if (response.status === 401) {
    const foreign = isForeignModuleCall(url);

    // Nevyhadzuj login na cudzí modul (napr. kancelárske API na leader-expedícia stránke)
    if (!foreign && typeof window.onUnauthorized === 'function') {
      const now = Date.now();
      if (now - window.__AUTH__.last401 >= window.__AUTH__.muteMs && !window.__AUTH__.locked) {
        window.__AUTH__.last401 = now;
        window.__AUTH__.locked = true;
        try { window.onUnauthorized(); } catch (_e) {}
        setTimeout(() => { window.__AUTH__.locked = false; }, window.__AUTH__.muteMs);
      }
    }
    return { error: 'Unauthorized', status: 401, raw: payload };
  }

  // 403 – zakázaný prístup
  if (!response.ok) {
    const msg = (payload && payload.error) || response.statusText || `HTTP ${response.status}`;
    return { error: msg, status: response.status, raw: payload };
  }

  // Backend redirect (napr. po logine)
  if (payload && typeof payload === 'object' && payload.redirect) {
    window.location.replace(payload.redirect);
    return;
  }

  return payload;
};

// Kompatibilita – ostatné skripty môžu volať priamo apiRequest(...)
async function apiRequest(url, options = {}) {
  return await window.apiRequest(url, options);
}

window.apiURL = apiURL;

// =================================================================
// === BOOT / NAV ==================================================
// =================================================================

document.addEventListener('DOMContentLoaded', () => {
  checkUserSession();

  const loginForm = document.getElementById('login-form');
  if (loginForm) loginForm.addEventListener('submit', handleLogin);

  const logoutButton = document.getElementById('logout-button');
  if (logoutButton) logoutButton.addEventListener('click', handleLogout);
});

// Skontroluje session a zobrazí UI podľa role
async function checkUserSession() {
  try {
    const response = await fetch('/api/internal/check_session', { credentials: 'include' });
    const data = await response.json();
    if (data.loggedIn && data.user) {
      // Vedúci na /expedicia patrí na leaderské UI
      if ((data.user.role || '').toLowerCase() === 'veduci' &&
          window.location.pathname.includes('/expedicia')) {
        window.location.replace('/leaderexpedicia');
        return;
      }
      showApp(data.user);
    } else {
      showLogin();
    }
  } catch (e) {
    console.error('Chyba pri kontrole session:', e);
    showLogin();
  }
}

// =================================================================
// === AUTH (login / logout) =======================================
// =================================================================

// Login – zavolá /api/internal/login a po úspechu presmeruje na redirect
async function handleLogin(event) {
  event.preventDefault();
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;

  // TODO: ak máš pre každý modul vlastný login, tu môžeš podľa URL zmeniť module:
  //   /vyroba      -> module: 'vyroba'
  //   /kancelaria  -> module: 'kancelaria'
  //   /expedicia   -> module: 'expedicia'
  let moduleSlug = 'expedicia';
  const path = window.location.pathname;
  if (path.includes('/vyroba')) moduleSlug = 'vyroba';
  else if (path.includes('/kancelaria')) moduleSlug = 'kancelaria';
  else if (path.includes('/expedicia') || path.includes('/leaderexpedicia')) moduleSlug = 'expedicia';

  try {
    const login = await apiRequest('/api/internal/login', {
      method: 'POST',
      body: { username, password, module: moduleSlug }
    });

    if (!login) {
      showStatus('Chyba prihlásenia.', true);
      return;
    }

    if (login.error) {
      showStatus(login.error || 'Chyba prihlásenia.', true);
      return;
    }

    // apiRequest už vie spraviť redirect ak server vráti {redirect:"..."}
    if (login.redirect) {
      window.location.replace(login.redirect);
      return;
    }

    if (login.user) {
      // Vedúci expedície -> leader UI
      if ((login.user.role || '').toLowerCase() === 'veduci') {
        window.location.replace('/leaderexpedicia');
        return;
      }
      showApp(login.user);
    } else {
      showStatus('Chyba prihlásenia.', true);
    }
  } catch (error) {
    console.error('Chyba pri logine:', error);
    showStatus('Chyba prihlásenia', true);
  }
}

async function handleLogout() {
  try {
    await apiRequest('/api/internal/logout', { method: 'POST' });
    window.location.reload();
  } catch (_) {
    window.location.reload();
  }
}

// =================================================================
// === UI SWITCH (login vs app + moduly podľa role) ================
// =================================================================

function showLogin() {
  const lw = document.getElementById('login-wrapper');
  const ac = document.getElementById('app-container');
  if (lw) lw.classList.remove('hidden');
  if (ac) ac.classList.add('hidden');
}

/**
 * Zobrazí hlavnú aplikáciu a overí rolu používateľa.
 * @param {object} user - Objekt s informáciami o prihlásenom používateľovi.
 */
function showApp(user) {
  let requiredRole = null;
  let moduleInitializationFunction = null;
  const path = window.location.pathname;

  if (path.includes('/vyroba')) {
    requiredRole = 'vyroba';
    moduleInitializationFunction = window.loadAndShowProductionMenu;

  } else if (path.includes('/expedicia')) {
    // Vedúci patrí na leader UI – presmeruj
    if ((user.role || '').toLowerCase() === 'veduci') {
      window.location.replace('/leaderexpedicia');
      return;
    }
    // Pracovník expedície (pôvodné UI)
    requiredRole = 'expedicia';
    moduleInitializationFunction = window.loadAndShowExpeditionMenu;

  } else if (path.includes('/leaderexpedicia')) {
    // Leader UI – stačí skryť login a ukázať app; načítanie robí leaderexpediction.js
    const lw = document.getElementById('login-wrapper');
    const ac = document.getElementById('app-container');
    if (lw) lw.classList.add('hidden');
    if (ac) ac.classList.remove('hidden');

    const userInfo = document.getElementById('user-info');
    if (userInfo) {
      userInfo.textContent = `Vitajte, ${user.full_name || user.username} (${user.role})`;
    }
    return;

  } else if (path.includes('/kancelaria')) {
    requiredRole = 'kancelaria';
    moduleInitializationFunction = window.loadAndShowOfficeMenu;
  }

  if (!requiredRole) {
    // default – len skry login, ukáž app (napr. index)
    const lw = document.getElementById('login-wrapper');
    const ac = document.getElementById('app-container');
    if (lw) lw.classList.add('hidden');
    if (ac) ac.classList.remove('hidden');
    return;
  }

  if (user.role === requiredRole || user.role === 'admin') {
    const lw = document.getElementById('login-wrapper');
    const ac = document.getElementById('app-container');
    if (lw) lw.classList.add('hidden');
    if (ac) ac.classList.remove('hidden');

    const userInfo = document.getElementById('user-info');
    if (userInfo) {
      userInfo.textContent = `Vitajte, ${user.full_name || user.username} (${user.role})`;
    }

    if (typeof moduleInitializationFunction === 'function') {
      moduleInitializationFunction();
    }
  } else {
    showStatus(`Nemáte oprávnenie pre modul '${requiredRole}'. Váš účet má rolu '${user.role}'.`, true);
    // necháme usera, nech sa rozhodne, či sa odhlási / prepne
  }
}

// =================================================================
// === STATUS BAR (notifikácie) ====================================
// =================================================================

let statusTimeout;
function showStatus(message, isError = false) {
  let statusEl = document.getElementById('status-notification');
  if (!statusEl) {
    statusEl = document.createElement('div');
    statusEl.id = 'status-notification';
    document.body.appendChild(statusEl);
    Object.assign(statusEl.style, {
      position: 'fixed', bottom: '-60px', left: '50%', transform: 'translateX(-50%)',
      padding: '1rem 1.5rem', borderRadius: '0.5rem', color: 'white',
      boxShadow: '0 4px 6px rgba(0,0,0,0.1)', zIndex: '2000',
      opacity: '0', transition: 'opacity 0.3s, bottom 0.3s'
    });
  }

  statusEl.textContent = message;
  statusEl.style.backgroundColor = isError ? 'var(--danger-color)' : 'var(--success-color)';

  clearTimeout(statusTimeout);

  setTimeout(() => {
    statusEl.style.bottom = '20px';
    statusEl.style.opacity = '1';
  }, 10);

  statusTimeout = setTimeout(() => {
    statusEl.style.opacity = '0';
    statusEl.style.bottom = '-60px';
  }, 4000);
}

function clearStatus() {
  const statusEl = document.getElementById('status-notification');
  if (statusEl) {
    statusEl.style.opacity = '0';
    statusEl.style.bottom = '-60px';
  }
}

// =================================================================
// === PRIDANÉ: kompatibilita pre VÝROBU (wrappre) =================
// =================================================================
(function ensureVyrobaCompatibility() {
  function ensureWrappers() {
    try {
      // 1) login-wrapper -> ak chýba
      var loginWrapper = document.getElementById('login-wrapper');
      var loginContainer = document.getElementById('login-container') || document.getElementById('login');
      if (!loginWrapper && loginContainer && loginContainer.parentNode) {
        var wrapper = document.createElement('div');
        wrapper.id = 'login-wrapper';
        loginContainer.parentNode.insertBefore(wrapper, loginContainer);
        wrapper.appendChild(loginContainer);
      }
      // 2) app-container -> ak chýba
      var appContainer = document.getElementById('app-container');
      var appOuter = document.getElementById('app');
      if (!appContainer && appOuter) {
        var inner = appOuter.querySelector('#app-container') || appOuter.firstElementChild;
        if (inner && !inner.id) inner.id = 'app-container';
      }
    } catch(e) {
      console.warn('[common.js] Vyroba compatibility wrapper skipped:', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('readystatechange', function onrs() {
      if (document.readyState === 'interactive') ensureWrappers();
    });
  } else {
    ensureWrappers();
  }

  // Predvolené správanie pre 401 – ukázať login s throttlingom
  window.onUnauthorized = function() {
    const now = Date.now();
    if (now - window.__AUTH__.last401 < window.__AUTH__.muteMs || window.__AUTH__.locked) return;
    window.__AUTH__.last401 = now;
    window.__AUTH__.locked = true;

    try {
      var lw = document.getElementById('login-wrapper');
      if (lw && lw.classList) lw.classList.remove('hidden');
      var ac = document.getElementById('app-container');
      if (ac && ac.classList) ac.classList.add('hidden');
      if (typeof showStatus === 'function') {
        showStatus('Vaša session vypršala. Prosím, prihláste sa znova.', true);
      }
    } catch(_e){}

    setTimeout(()=>{ window.__AUTH__.locked = false; }, window.__AUTH__.muteMs);
  };
})();
