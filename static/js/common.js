// =================================================================
// === ZDIEĽANÉ FUNKCIE PRE VŠETKY MODULY (COMMON.JS) ===
// =================================================================

document.addEventListener('DOMContentLoaded', () => {
    checkUserSession();
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }
    const logoutButton = document.getElementById('logout-button');
    if (logoutButton) {
        logoutButton.addEventListener('click', handleLogout);
    }
});

async function checkUserSession() {
    try {
        const response = await fetch('/api/internal/check_session');
        const data = await response.json();
        if (data.loggedIn && data.user) {
            showApp(data.user);
        } else {
            showLogin();
        }
    } catch (error) {
        console.error('Chyba pri kontrole session:', error);
        showLogin();
    }
}

async function handleLogin(event) {
    event.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    try {
        const result = await apiRequest('/api/internal/login', {
            method: 'POST',
            body: { username, password }
        });
        if (result && result.user) {
            showApp(result.user);
        }
    } catch (error) { /* Chyba je už spracovaná v apiRequest */ }
}

async function handleLogout() {
    try {
        await apiRequest('/api/internal/logout', { method: 'POST' });
        window.location.reload();
    } catch (error) {
        window.location.reload();
    }
}

function showLogin() {
    document.getElementById('login-wrapper').classList.remove('hidden');
    document.getElementById('app-container').classList.add('hidden');
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
        requiredRole = 'expedicia';
        moduleInitializationFunction = window.loadAndShowExpeditionMenu;
    } else if (path.includes('/kancelaria')) {
        requiredRole = 'kancelaria';
        moduleInitializationFunction = window.loadAndShowOfficeMenu;
    }

    if (requiredRole && (user.role === requiredRole || user.role === 'admin')) {
        document.getElementById('login-wrapper').classList.add('hidden');
        document.getElementById('app-container').classList.remove('hidden');
        
        const userInfo = document.getElementById('user-info');
        if (userInfo) {
            userInfo.textContent = `Vitajte, ${user.full_name || user.username} (${user.role})`;
        }

        if (typeof moduleInitializationFunction === 'function') {
            moduleInitializationFunction();
        }
    } else {
        showStatus(`Nemáte oprávnenie pre modul '${requiredRole}'. Váš účet má rolu '${user.role}'.`, true);
        setTimeout(handleLogout, 3000);
    }
}

async function apiRequest(url, options = {}) {
    options.headers = { 'Content-Type': 'application/json', ...options.headers };
    if (options.body) {
        options.body = JSON.stringify(options.body);
    }

    try {
        const response = await fetch(url, options);

        // --- OPRAVA: Kontrola úspešnosti (response.ok) PRED spracovaním JSON ---
        if (!response.ok) {
            let errorMessage = `Chyba servera: ${response.status} ${response.statusText}`;
            try {
                // Skúsime, či server neposlal chybu v JSON formáte
                const errorResult = await response.json();
                if (errorResult && errorResult.error) {
                    errorMessage = errorResult.error;
                }
            } catch (e) {
                // Ak to nebol JSON (napr. pri 404 sa vráti HTML), necháme pôvodnú správu
            }

            if (response.status === 401) {
                errorMessage = "Vaša session vypršala. Prosím, prihláste sa znova.";
                setTimeout(() => window.location.reload(), 2000);
            }
             if (response.status === 404) {
                errorMessage = `Chyba 404: Požadovaná adresa [${url}] nebola nájdená na serveri.`;
            }
            throw new Error(errorMessage);
        }

        // Spracujeme JSON, až keď vieme, že je odpoveď v poriadku (status 2xx)
        const result = await response.json();

        if(result.message && options.method !== 'GET' && !url.includes('check_session')) {
            showStatus(result.message, false);
        }
        return result;
    } catch (error) {
        showStatus(error.message, true);
        throw error;
    }
}


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
    let statusEl = document.getElementById('status-notification');
    if (statusEl) {
        statusEl.style.opacity = '0';
        statusEl.style.bottom = '-60px';
    }
}

function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'})[m]);
}

function safeToFixed(num, digits = 2) {
    const val = parseFloat(String(num).replace(",","."));
    return isNaN(val) ? '0.00' : val.toFixed(digits);
}
