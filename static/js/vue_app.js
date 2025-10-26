// Pomocná premenná, aby sme sa uistili, že Google Charts načítame iba raz.
let googleChartsLoaded = null;

function loadGoogleCharts() {
    // Ak už bol sľub vytvorený, vrátime ten istý, aby sa knižnica nesťahovala znova.
    if (googleChartsLoaded) {
        return googleChartsLoaded;
    }
    // Vytvoríme nový sľub (Promise).
    googleChartsLoaded = new Promise((resolve) => {
        // Skontrolujeme, či `google` objekt už existuje.
        if (typeof google !== 'undefined' && google.charts) {
            google.charts.load('current', { 'packages': ['corechart'] });
            google.charts.setOnLoadCallback(resolve);
        } else {
            // Ak nie, počkáme, kým sa načíta základný loader.js.
            // Toto je len záchranná sieť, nemalo by sa to stať.
            setTimeout(loadGoogleCharts, 100); 
        }
    });
    return googleChartsLoaded;
}


const app = Vue.createApp({
    data() {
        return {
            currentView: 'view-role-selection'
        };
    },
    methods: {
        showView(viewId) {
            this.currentView = viewId;
            document.querySelectorAll('.view').forEach(v => {
                v.style.display = 'none';
            });
            const viewToShow = document.getElementById(viewId);
            if(viewToShow) {
                viewToShow.style.display = 'block';
            }
        }
    },
    mounted() {
        window.vueApp = this;
    }
});

// === Komponent pre Dashboard ===
app.component('dashboard-view', {
    emits: ['back'],
    data() {
        return {
            isLoading: true,
            lowStockItems: [],
            topProducts: [],
            timeSeriesData: [],
            error: null
        };
    },
    mounted() {
        this.fetchDashboardData();
    },
    methods: {
        async fetchDashboardData() {
            this.isLoading = true;
            this.error = null;
            try {
                const response = await fetch('/api/getDashboardData');
                if (!response.ok) {
                    const errData = await response.json();
                    throw new Error(errData.error || 'Nepodarilo sa načítať dáta pre dashboard.');
                }
                const data = await response.json();
                this.lowStockItems = data.lowStockItems;
                this.topProducts = data.topProducts;
                this.timeSeriesData = data.timeSeriesData;
                
                this.$nextTick(() => {
                    this.drawChart();
                });

            } catch (err) {
                this.error = err.message;
            } finally {
                this.isLoading = false;
            }
        },
        async drawChart() {
            try {
                // ZMENA: Zavoláme našu novú funkciu, ktorá vráti sľub.
                await loadGoogleCharts();

                const chartContainer = this.$refs.chartDiv;
                if (!chartContainer || !this.timeSeriesData || this.timeSeriesData.length === 0) {
                    if(chartContainer) chartContainer.innerHTML = '<p>Žiadne dáta pre graf výroby za posledných 30 dní.</p>';
                    return;
                }
                
                // Od tohto bodu je kód rovnaký, ale teraz máme istotu, že knižnica je načítaná.
                const chartData = new google.visualization.DataTable();
                chartData.addColumn('date', 'Dátum');
                chartData.addColumn('number', 'Vyrobené kg');
                this.timeSeriesData.forEach(row => {
                    chartData.addRow([new Date(row.production_date), parseFloat(row.total_kg)]);
                });

                const options = { 
                    title: 'Výroba za posledných 30 dní (kg)',
                    legend: { position: 'none' },
                    colors: ['#007bff'],
                    vAxis: { title: 'Množstvo (kg)', minValue: 0 },
                    hAxis: { title: 'Dátum', format: 'd.M' }
                };

                const chart = new google.visualization.ColumnChart(chartContainer);
                chart.draw(chartData, options);

            } catch (error) {
                console.error("Chyba pri kreslení Google Chart:", error);
                if (this.$refs.chartDiv) {
                    this.$refs.chartDiv.innerHTML = '<p class="error">Graf sa nepodarilo načítať.</p>';
                }
            }
        },
        safeToFixed(num, digits = 2) {
             const val = parseFloat(String(num).replace(",","."));
             if (num === undefined || num === null || isNaN(val)) return '0.00';
             return val.toFixed(digits);
        }
    },
    template: `
        <div class="section">
            <h3>Dashboard</h3>
            
            <div v-if="isLoading" style="text-align: center; padding: 20px;">
                <p>Načítavam dáta...</p>
            </div>
            <div v-else-if="error" class="error">
                <p>Chyba: {{ error }}</p>
            </div>

            <div v-else>
                <h4 style="margin-top:0;">Suroviny pod minimálnou zásobou</h4>
                <div class="table-container">
                    <p v-if="lowStockItems.length === 0">Všetky suroviny sú nad minimálnou zásobou.</p>
                    <table v-else>
                        <thead><tr><th>Surovina</th><th>Aktuálny stav (kg)</th><th>Min. zásoba (kg)</th></tr></thead>
                        <tbody>
                            <tr v-for="item in lowStockItems" :key="item.name">
                                <td>{{ item.name }}</td>
                                <td class="loss">{{ safeToFixed(item.quantity) }}</td>
                                <td>{{ safeToFixed(item.minStock) }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <h4 style="margin-top: 20px;">TOP 5 produktov (posledných 30 dní)</h4>
                <div class="table-container">
                    <p v-if="topProducts.length === 0">Za posledných 30 dní neboli vyrobené žiadne produkty.</p>
                    <table v-else>
                        <thead><tr><th>Produkt</th><th>Vyrobené (kg)</th></tr></thead>
                        <tbody>
                            <tr v-for="item in topProducts" :key="item.name">
                                <td>{{ item.name }}</td>
                                <td>{{ safeToFixed(item.total) }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <h4 style="margin-top: 20px;">Graf výroby (posledných 30 dní)</h4>
                <div ref="chartDiv" style="width: 100%; height: 300px; margin-top: 20px; text-align: center;"></div>
            </div>
        </div>
        <button @click="$emit('back')" class="btn-secondary back-button">Späť do menu</button>
    `
});

app.mount('#app');

