import db_connector
from datetime import datetime
import unicodedata # Import pre prácu so špeciálnymi znakmi

# =================================================================
# === POMOCNÁ FUNKCIA PRE ČISTENIE REŤAZCOV ===
# =================================================================
def slugify(value):
    """
    Normalizuje reťazec: odstráni diakritiku, prevedie na malé písmená
    a nahradí medzery podčiarkovníkmi. Ideálne pre ID a URL.
    Príklad: "Papriková Saláma" -> "paprikova_salama"
    """
    try:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
        value = value.lower().replace(' ', '_').replace('.', '')
        return value
    except:
        # Záložné riešenie pre prípad nečakaného vstupu
        return "".join(c for c in value if c.isalnum() or c in (' ', '_')).lower().replace(' ', '_')

# =================================================================
# === FUNKCIE PRE VÝROBU ===
# =================================================================

def get_warehouse_state():
    """Zdieľaná funkcia, ktorá vracia stav skladu surovín."""
    query = "SELECT nazov as name, typ as type, mnozstvo as quantity, nakupna_cena as price, min_zasoba as minStock FROM sklad ORDER BY typ, nazov"
    all_items = db_connector.execute_query(query)
    warehouse = {'Mäso': [], 'Koreniny': [], 'Obaly - Črevá': [], 'Pomocný material': [], 'all': all_items}
    for item in all_items:
        typ = item.get('type')
        if typ in warehouse:
            warehouse[typ].append(item)
    return warehouse

def get_categorized_recipes():
    """
    Získa všetky produkty, ktoré majú recept, roztriedené podľa kategórií.
    Používa robustnejší SQL dopyt s funkciou TRIM(), ktorý overuje existenciu receptu
    a správny typ produktu ('VÝROBOK%') a je odolný voči bielym znakom (medzerám) na začiatku/konci názvov.
    """
    query = """
        SELECT p.nazov_vyrobku, p.kategoria_pre_recepty 
        FROM produkty p
        JOIN (SELECT DISTINCT TRIM(nazov_vyrobku) AS nazov_vyrobku FROM recepty) r 
            ON TRIM(p.nazov_vyrobku) = r.nazov_vyrobku
        WHERE 
            p.typ_polozky LIKE 'VÝROBOK%%' 
        ORDER BY p.kategoria_pre_recepty, p.nazov_vyrobku
    """
    products = db_connector.execute_query(query)
    categorized_recipes = {}
    for product in products:
        category = product.get('kategoria_pre_recepty', 'Nezaradené')
        if category not in categorized_recipes: categorized_recipes[category] = []
        categorized_recipes[category].append(product['nazov_vyrobku'])
    return {'data': categorized_recipes}

def get_planned_production_tasks_by_category():
    """Získa automaticky naplánované výrobné úlohy (stav 'Automaticky naplánované')."""
    # OPRAVA: Použitie TRIM() pri spájaní tabuliek pre robustnosť.
    query = """
        SELECT zv.id_davky as logId, zv.nazov_vyrobku as productName, zv.planovane_mnozstvo_kg as actualKgQty, p.kategoria_pre_recepty as category 
        FROM zaznamy_vyroba AS zv 
        JOIN produkty AS p ON TRIM(zv.nazov_vyrobku) = TRIM(p.nazov_vyrobku) 
        WHERE zv.stav = 'Automaticky naplánované' AND p.typ_polozky LIKE 'VÝROBOK%%' 
        ORDER BY p.kategoria_pre_recepty, zv.nazov_vyrobku
    """
    tasks_list = db_connector.execute_query(query)
    categorized_tasks = {}
    for task in tasks_list:
        category = task.get('category') or "Nezaradené"
        if category not in categorized_tasks: categorized_tasks[category] = []
        task['displayQty'] = f"{float(task['actualKgQty']):.2f} kg"
        categorized_tasks[category].append(task)
    return categorized_tasks

def get_running_production_tasks_by_category():
    """Získa výrobné úlohy, ktoré sú aktuálne v stave 'Vo výrobe'."""
    # OPRAVA: Použitie TRIM() pri spájaní tabuliek pre robustnosť.
    query = """
        SELECT 
            zv.id_davky as logId, 
            zv.nazov_vyrobku as productName, 
            zv.planovane_mnozstvo_kg as plannedKg, 
            p.kategoria_pre_recepty as category 
        FROM zaznamy_vyroba AS zv 
        JOIN produkty AS p ON TRIM(zv.nazov_vyrobku) = TRIM(p.nazov_vyrobku) 
        WHERE zv.stav = 'Vo výrobe' 
        ORDER BY p.kategoria_pre_recepty, zv.nazov_vyrobku
    """
    tasks_list = db_connector.execute_query(query)
    categorized_tasks = {}
    for task in tasks_list:
        category = task.get('category') or "Nezaradené"
        if category not in categorized_tasks: categorized_tasks[category] = []
        task['displayQty'] = f"{float(task['plannedKg']):.2f} kg"
        categorized_tasks[category].append(task)
    return categorized_tasks

def get_production_menu_data():
    """Získa všetky potrebné dáta pre menu výroby, vrátane bežiacich úloh."""
    return {
        'planned_tasks': get_planned_production_tasks_by_category(),
        'running_tasks': get_running_production_tasks_by_category(),
        'warehouse': get_warehouse_state(),
        'recipes': get_categorized_recipes().get('data')
    }

def find_recipe_data(product_name):
    """Načíta suroviny a ich množstvá pre recept daného produktu."""
    query = "SELECT nazov_suroviny, mnozstvo_na_davku_kg FROM recepty WHERE nazov_vyrobku = %s"
    return db_connector.execute_query(query, (product_name,))

def calculate_required_ingredients(product_name, planned_weight):
    """Vypočíta potrebné množstvo surovín pre výrobnú dávku."""
    if not product_name or not planned_weight or float(planned_weight) <= 0: return {"error": "Zadajte platný produkt a množstvo."}
    recipe_ingredients = find_recipe_data(product_name)
    if not recipe_ingredients: return {"error": f'Recept s názvom "{product_name}" nebol nájdený.'}
    
    batch_multiplier = float(planned_weight) / 100.0
    warehouse_map = {item['name']: item for item in get_warehouse_state()['all']}
    result_data = []
    
    for ing in recipe_ingredients:
        required_qty = float(ing.get('mnozstvo_na_davku_kg') or 0.0) * batch_multiplier
        stock_info = warehouse_map.get(ing.get('nazov_suroviny'), {})
        stock_quantity = float(stock_info.get('quantity') or 0.0)
        is_sufficient = ing.get('nazov_suroviny') in ['Ľad', 'Voda', 'Ovar'] or stock_quantity >= required_qty
        
        result_data.append({"name": ing.get('nazov_suroviny'), "type": stock_info.get('type', 'Neznámy'), "required": f"{required_qty:.3f}", "inStock": f"{stock_quantity:.2f}", "isSufficient": is_sufficient})
    return {"data": result_data}

def start_production(productName, plannedWeight, productionDate, ingredients, workerName, existingLogId=None, **kwargs):
    """
    Spustí výrobu, odpíše suroviny a zaznamená ich použitie pre spätnú sledovateľnosť.
    Pre manuálne príkazy (bez existingLogId) zaznamená aj meno pracovníka.
    """
    product_name = productName
    planned_weight = plannedWeight
    production_date = productionDate
    existing_log_id = existingLogId

    if not all([product_name, planned_weight, production_date, ingredients]):
        return {"error": "Chýbajú povinné údaje pre spustenie výroby."}
    
    # Pre nové manuálne príkazy je meno pracovníka povinné
    if not existing_log_id and not workerName:
        return {"error": "Chýba meno pracovníka pre vytvorenie novej manuálnej výrobnej úlohy."}

    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        
        ingredient_names = [ing['name'] for ing in ingredients if ing.get('name')]
        if not ingredient_names:
             raise ValueError("Výroba musí obsahovať aspoň jednu surovinu.")

        placeholders = ','.join(['%s'] * len(ingredient_names))
        cursor.execute(f"SELECT nazov, nakupna_cena FROM sklad WHERE nazov IN ({placeholders})", tuple(ingredient_names))
        price_map = {p['nazov']: float(p.get('nakupna_cena') or 0.0) for p in cursor.fetchall()}
        
        total_batch_cost = sum(float(ing['quantity']) * price_map.get(ing['name'], 0.0) for ing in ingredients)
        
        updates_to_sklad = [(float(ing['quantity']), ing['name']) for ing in ingredients if ing['name'] not in ['Ľad', 'Voda', 'Ovar']]
        if updates_to_sklad:
            cursor.executemany("UPDATE sklad SET mnozstvo = mnozstvo - %s WHERE nazov = %s", updates_to_sklad)
        
        start_time = datetime.now()
        batch_id = "" 

        if existing_log_id:
            batch_id = existing_log_id
            log_params = ('Vo výrobe', production_date, start_time, total_batch_cost, batch_id)
            cursor.execute("UPDATE zaznamy_vyroba SET stav = %s, datum_vyroby = %s, datum_spustenia = %s, celkova_cena_surovin = %s WHERE id_davky = %s", log_params)
            message = f"Príkaz {batch_id} bol spustený do výroby."
            # Vymažeme staré suroviny, ak by náhodou existovali, a vložíme nové
            cursor.execute("DELETE FROM zaznamy_vyroba_suroviny WHERE id_davky = %s", (batch_id,))
        else:
            # Tvorba unikátneho ID pre manuálne zadanú šaržu
            safe_product_name = slugify(product_name)
            safe_worker_name = slugify(workerName).upper()
            date_str = datetime.strptime(production_date, '%Y-%m-%d').strftime('%d%m%y')
            time_str = datetime.now().strftime('%H%M')
            # Nový formát ID: PAPRIKOVA_SALAMA-ZKARAS-260925-0830-100
            batch_id = f"{safe_product_name[:20]}-{safe_worker_name[:6]}-{date_str}-{time_str}-{int(float(planned_weight))}"
            
            log_params = (batch_id, 'Vo výrobe', production_date, product_name, float(planned_weight), total_batch_cost, start_time)
            cursor.execute("INSERT INTO zaznamy_vyroba (id_davky, stav, datum_vyroby, nazov_vyrobku, planovane_mnozstvo_kg, celkova_cena_surovin, datum_spustenia) VALUES (%s, %s, %s, %s, %s, %s, %s)", log_params)
            message = f"VÝROBA SPUSTENÁ! Šarža: {batch_id}."
        
        suroviny_na_zaznam = [
            (batch_id, ing['name'], float(ing['quantity'])) 
            for ing in ingredients if ing.get('name') and float(ing.get('quantity', 0)) > 0
        ]
        if suroviny_na_zaznam:
            cursor.executemany(
                "INSERT INTO zaznamy_vyroba_suroviny (id_davky, nazov_suroviny, pouzite_mnozstvo_kg) VALUES (%s, %s, %s)",
                suroviny_na_zaznam
            )

        conn.commit()
        return {"message": message}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected(): conn.close()

def update_inventory(inventory_data):
    """Spracuje dáta z inventúry, zapíše rozdiely a aktualizuje stav skladu."""
    if not inventory_data: return {"error": "Neboli zadané žiadne platné reálne stavy."}
    
    warehouse_map = {item['name']: {'price': float(item.get('price') or 0.0), 'type': item.get('type')} for item in get_warehouse_state()['all']}
    
    differences_to_log, updates_to_sklad = [], []
    for item in inventory_data:
        real_qty, system_qty = float(item['realQty']), float(item['systemQty'])
        if (diff := real_qty - system_qty) != 0:
            price = warehouse_map.get(item['name'], {}).get('price', 0.0)
            log_entry = (datetime.now(), item['name'], warehouse_map.get(item['name'], {}).get('type', 'Neznámy'), system_qty, real_qty, diff, (diff * price))
            differences_to_log.append(log_entry)
            updates_to_sklad.append((real_qty, item['name']))
            
    if differences_to_log:
        db_connector.execute_query("INSERT INTO inventurne_rozdiely (datum, nazov_suroviny, typ_suroviny, systemovy_stav_kg, realny_stav_kg, rozdiel_kg, hodnota_rozdielu_eur) VALUES (%s, %s, %s, %s, %s, %s, %s)", differences_to_log, fetch='none', multi=True)
    if updates_to_sklad:
        db_connector.execute_query("UPDATE sklad SET mnozstvo = %s WHERE nazov = %s", updates_to_sklad, fetch='none', multi=True)
    
    return {"message": f"Inventúra dokončená. Aktualizovaných {len(updates_to_sklad)} položiek."}

def get_all_warehouse_items():
    """Vráti zoznam všetkých surovín zo skladu pre výberové polia."""
    return db_connector.execute_query("SELECT nazov as name, typ as type FROM sklad ORDER BY typ, nazov")

def manual_warehouse_write_off(data):
    """Spracuje manuálny výdaj suroviny zo skladu."""
    name, worker, qty_str, note = data.get('itemName'), data.get('workerName'), data.get('quantity'), data.get('note')
    if not all([name, worker, qty_str, note]): return {"error": "Všetky polia sú povinné."}
    try:
        qty = float(qty_str)
        if qty <= 0: raise ValueError("Množstvo musí byť kladné.")
    except (ValueError, TypeError): return {"error": "Zadané neplatné množstvo."}
    
    db_connector.execute_query("UPDATE sklad SET mnozstvo = mnozstvo - %s WHERE nazov = %s", (qty, name), fetch='none')
    db_connector.execute_query("INSERT INTO vydajky (datum, pracovnik, nazov_suroviny, mnozstvo_kg, poznamka) VALUES (%s, %s, %s, %s, %s)", (datetime.now(), worker, name, qty, note), fetch='none')
    
    return {"message": f"Úspešne odpísaných {qty} kg suroviny '{name}'."}

