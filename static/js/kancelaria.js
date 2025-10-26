// =================================================================
// === HLAVNÝ SKRIPT PRE MODUL KANCELÁRIA (KANCELARIA.JS) ===
// =================================================================

// --- Globálne premenné a pomocné funkcie ---
let officeInitialData = {};
let b2bAdminData = { customers: [], pricelists: [], productsByCategory: {} };
let activeTinyMceEditor = null;
let catalogManagementData = {};
let fleetState = { vehicles: [], logs: [], refuelings: [], costs: [], analysis: {}, selected_vehicle_id: null, selected_year: null, selected_month: null, last_odometer: 0 };
let hygieneState = { agents: [] };
let googleChartsLoaded = null;


function loadAndShowOfficeMenu() {
    initializeSidebar();
    
    // --- OPRAVA: Explicitné zobrazenie úvodnej sekcie pri štarte ---
    // Najprv skryjeme všetky sekcie a potom zobrazíme iba dashboard
    document.querySelectorAll('.main-content .content-section').forEach(s => s.style.display = 'none');
    const dashboardSection = document.getElementById('section-dashboard');
    if (dashboardSection) {
        dashboardSection.style.display = 'block';
    }
    
    // Načítame obsah pre úvodnú sekciu
    setupSection('section-dashboard');
}

function initializeSidebar() {
    const sidebarLinks = document.querySelectorAll('.sidebar-nav a.sidebar-link');
    const contentSections = document.querySelectorAll('.main-content .content-section');
    
    sidebarLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Vizuálne označenie aktívneho odkazu v menu
            sidebarLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            
            const targetSectionId = link.dataset.section;
            const targetSection = document.getElementById(targetSectionId);
            
            if (targetSection) {
                // --- OPRAVA: Priame a spoľahlivejšie prepínanie viditeľnosti ---
                // Skryjeme všetky sekcie
                contentSections.forEach(s => s.style.display = 'none');
                // Zobrazíme iba tú cieľovú
                targetSection.style.display = 'block';
                
                // Načítame obsah pre zobrazenú sekciu
                setupSection(targetSectionId);
            }
        });
    });
}

/**
 * "Dirigent" - táto funkcia na základe ID sekcie zavolá príslušnú
 * inicializačnú funkciu z oddeleného modulu.
 * @param {string} sectionId - ID sekcie, ktorá sa má zobraziť.
 */
function setupSection(sectionId) {
    const sectionElement = document.getElementById(sectionId);
    // Inicializujeme každú sekciu iba raz, aby sme neopakovali API volania
    if (sectionElement && !sectionElement.dataset.initialized) {
        switch (sectionId) {
            case 'section-dashboard':       initializeDashboardModule(); break;
            // --- OPRAVA: Chýbajúce volanie pre inicializáciu nového modulu ---
            case 'section-order-forecast':  initializeOrderForecastModule(); break;
            case 'section-stock':           initializeStockModule(); break;
            case 'section-planning':        initializePlanningModule(); break;
            case 'section-erp-admin':       initializeErpAdminModule(); break;
            case 'section-b2b-admin':       initializeB2BAdminModule(); break;
            case 'section-b2c-admin':       initializeB2CAdminModule(); break;
            case 'section-haccp':           initializeHaccpModule(); break;
            case 'section-fleet':           initializeFleetModule(); break;
            case 'section-hygiene':         initializeHygieneModule(); break;
            case 'section-profitability':   initializeProfitabilityModule(); break;
            case 'section-costs':           initializeCostsModule(); break;
        }
        sectionElement.dataset.initialized = 'true';
    }
}

async function ensureOfficeDataIsLoaded() {
    if (Object.keys(officeInitialData).length === 0) {
        try {
            officeInitialData = await apiRequest('/api/kancelaria/getKancelariaBaseData');
        } catch (e) {
            showStatus("Nepodarilo sa načítať základné dáta zo servera.", true);
            throw e;
        }
    }
}

// --- ZDIEĽANÉ FUNKCIE PRE MODÁLNE OKNÁ ---
async function showModal(title, contentPromise) {
    const modalContainer = document.getElementById('modal-container');
    modalContainer.innerHTML = `<div class="modal-backdrop"></div><div class="modal-content"><div class="modal-header"><h3>${title}</h3><button class="close-btn">&times;</button></div><div class="modal-body"><p>Načítavam...</p></div></div>`;
    modalContainer.style.display = 'flex';
    const closeModal = () => {
        if (activeTinyMceEditor) { tinymce.remove(activeTinyMceEditor); activeTinyMceEditor = null; }
        modalContainer.style.display = 'none';
        modalContainer.innerHTML = '';
    };
    modalContainer.querySelector('.close-btn').onclick = closeModal;
    modalContainer.querySelector('.modal-backdrop').onclick = closeModal;
    try {
        const content = await contentPromise(); 
        modalContainer.querySelector('.modal-body').innerHTML = content.html;
        if (content.onReady && typeof content.onReady === 'function') {
            content.onReady();
        }
    } catch (e) {
        modalContainer.querySelector('.modal-body').innerHTML = `<p class="error">Chyba pri načítaní obsahu: ${e.message}</p>`;
    }
}

function showConfirmationModal({ title, message, warning, onConfirm }) {
    const template = document.getElementById('confirmation-modal-template');
    const contentPromise = () => Promise.resolve({
        html: template.innerHTML,
        onReady: () => {
            document.getElementById('confirmation-message').textContent = message;
            const warningEl = document.getElementById('confirmation-warning');
            if (warning) {
                warningEl.textContent = warning;
                warningEl.style.display = 'block';
            } else {
                warningEl.style.display = 'none';
            }
            const confirmBtn = document.getElementById('confirm-action-btn');
            const cancelBtn = document.getElementById('cancel-confirmation-btn');
            confirmBtn.onclick = () => {
                onConfirm();
                document.getElementById('modal-container').style.display = 'none';
            };
            cancelBtn.onclick = () => {
                document.getElementById('modal-container').style.display = 'none';
            };
        }
    });
    showModal(title, contentPromise);
}
