// =================================================================
// === SUB-MODUL KANCELÁRIA: DASHBOARD (PREPRACOVANÁ VERZIA) ===
// =================================================================

function initializeDashboardModule() {
    loadDashboardData();
}

async function loadDashboardData() {
    const content = document.getElementById('section-dashboard');
    content.innerHTML = '<h3>Dashboard</h3><p>Načítavam dáta...</p>';
    try {
        const data = await apiRequest('/api/kancelaria/getDashboardData');
        
        let html = `<h3>Dashboard</h3><div id="dashboard-content">`;

        // 1. Sekcia pre aktívne akcie
        if (data.activePromotions && data.activePromotions.length > 0) {
            html += `
                <div style="background-color: #fffbe6; border: 1px solid #fde68a; padding: 1rem; border-radius: var(--border-radius); margin-bottom: 2rem;">
                    <h4 style="margin-top:0; color: #ca8a04;"><i class="fas fa-bullhorn"></i> Upozornenie na prebiehajúce akcie</h4>
                    <ul>
                        ${data.activePromotions.map(p => `<li><strong>${p.chain_name}:</strong> ${p.product_name} (do ${new Date(p.end_date).toLocaleDateString('sk-SK')})</li>`).join('')}
                    </ul>
                </div>
            `;
        }

        // 2. Sekcia pre výrobné suroviny
        html += `<h4 style="margin-top: 20px;">Výrobné suroviny pod minimálnou zásobou</h4>`;
        if (data.lowStockRaw && data.lowStockRaw.length > 0) {
            let tableRaw = '<table><thead><tr><th>Surovina</th><th>Aktuálny stav (kg)</th><th>Min. zásoba (kg)</th></tr></thead><tbody>';
            data.lowStockRaw.forEach(item => {
                tableRaw += `<tr><td>${escapeHtml(item.name)}</td><td class="loss">${safeToFixed(item.quantity)}</td><td>${safeToFixed(item.minStock)}</td></tr>`;
            });
            html += `<div class="table-container">${tableRaw}</tbody></table></div>`;
        } else {
            html += '<p>Všetky výrobné suroviny sú nad minimálnou zásobou.</p>';
        }
        html += `<p style="font-size: 0.9rem; color: #6b7280; margin-top: 0.5rem;">Pre detailný návrh nákupu surovín na základe plánu výroby, prosím, skontrolujte sekciu <strong>Plánovanie &gt; Návrh Nákupu</strong>.</p>`;
        
        // 3. Sekcia pre expedičný tovar
        html += `<h4 style="margin-top: 2rem;">Expedičný tovar pod minimálnou zásobou</h4>`;
        if (data.lowStockGoods && Object.keys(data.lowStockGoods).length > 0) {
            for (const category in data.lowStockGoods) {
                html += `<h5>${category}</h5>`;
                let tableGoods = '<table><thead><tr><th>Produkt</th><th>Aktuálny stav</th><th>Min. zásoba</th></tr></thead><tbody>';
                data.lowStockGoods[category].forEach(item => {
                    tableGoods += `<tr><td>${escapeHtml(item.name)}</td><td class="loss">${item.currentStock}</td><td>${item.minStock}</td></tr>`;
                });
                html += `<div class="table-container">${tableGoods}</tbody></table></div>`;
            }
        } else {
            html += '<p>Všetok expedičný tovar je nad minimálnou zásobou.</p>';
        }
        html += `<p style="font-size: 0.9rem; color: #6b7280; margin-top: 0.5rem;">Pre detailný návrh nákupu tovaru na základe objednávok, prosím, skontrolujte sekciu <strong>Expedičný Plán &gt; Návrh Nákupu Tovaru</strong>.</p>`;

        // 4. TOP 5 a Graf
        html += `<h4 style="margin-top: 2rem;">TOP 5 produktov (posledných 30 dní)</h4><div class="table-container" id="top-products-container"></div>`;
        html += `<h4 style="margin-top: 2rem;">Graf výroby (posledných 30 dní)</h4><div id="production-chart-container" style="width: 100%; height: 300px; text-align: center;"></div>`;

        html += `</div>`;
        content.innerHTML = html;

        populateTopProductsTable(data.topProducts);
        drawProductionChart(data.timeSeriesData);

    } catch (e) { 
        content.innerHTML = `<h3>Dashboard</h3><p class="error">Chyba pri načítaní dát pre dashboard: ${e.message}</p>`; 
    }
}

function populateTopProductsTable(items) { 
    const container = document.getElementById('top-products-container');
    if (!container) return;
    if (!items || items.length === 0) { 
        container.innerHTML = '<p>Za posledných 30 dní neboli vyrobené žiadne produkty.</p>'; 
        return; 
    }
    let table = '<table><thead><tr><th>Produkt</th><th>Vyrobené (kg)</th></tr></thead><tbody>';
    items.forEach(item => { table += `<tr><td>${escapeHtml(item.name)}</td><td>${safeToFixed(item.total)}</td></tr>`; });
    container.innerHTML = table + '</tbody></table>';
}

function loadGoogleCharts() {
    if (googleChartsLoaded) return googleChartsLoaded;
    googleChartsLoaded = new Promise((resolve) => {
        if (typeof google !== 'undefined' && google.charts) {
            google.charts.load('current', { 'packages': ['corechart'] });
            google.charts.setOnLoadCallback(resolve);
        } else { setTimeout(loadGoogleCharts, 100); }
    });
    return googleChartsLoaded;
}

async function drawProductionChart(timeSeriesData) { 
    try {
        await loadGoogleCharts();
        const container = document.getElementById('production-chart-container');
        if (!container) return;
        if (!timeSeriesData || timeSeriesData.length === 0) { 
            container.innerHTML = '<p>Žiadne dáta pre graf výroby za posledných 30 dní.</p>'; 
            return; 
        }
        const chartData = new google.visualization.DataTable();
        chartData.addColumn('date', 'Dátum');
        chartData.addColumn('number', 'Vyrobené kg');
        timeSeriesData.forEach(row => { chartData.addRow([new Date(row.production_date), parseFloat(row.total_kg)]); });
        const options = { title: 'Výroba za posledných 30 dní (kg)', legend: { position: 'none' }, colors: ['#8b5cf6'], vAxis: { title: 'Množstvo (kg)', minValue: 0 }, hAxis: { title: 'Dátum', format: 'd.M' } };
        const chart = new google.visualization.ColumnChart(container);
        chart.draw(chartData, options);
    } catch (error) {
        console.error("Chyba pri kreslení Google Chart:", error);
        const chartContainer = document.getElementById('production-chart-container');
        if (chartContainer) { chartContainer.innerHTML = '<p class="error">Graf sa nepodarilo načítať.</p>'; }
    }
}
