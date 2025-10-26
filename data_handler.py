import db_connector
from datetime import datetime, timedelta
import math

# --- POMOCNÁ FUNKCIA NA VYKONÁVANIE SQL PRÍKAZOV ---
def execute_query(query, params=None, fetch='all', multi=False):
    """
    Bezpečne vykoná SQL príkaz a vráti výsledok.
    """
    conn = None
    cursor = None
    try:
        conn = db_connector.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        if multi:
            cursor.executemany(query, params)
        else:
            cursor.execute(query, params or ())
        
        if fetch == 'one':
            return cursor.fetchone()
        elif fetch == 'all':
            return cursor.fetchall()
        else:
            conn.commit()
            if fetch == 'lastrowid':
                return cursor.lastrowid
            return cursor.rowcount
            
    except Exception as e:
        print(f"Chyba pri vykonávaní SQL príkazu: {e}")
        if conn:
            conn.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# =================================================================
# === FUNKCIE PRE DASHBOARD A KANCELÁRIU ===
# =================================================================

def get_kancelaria_dashboard_data():
    """
    Získa dáta pre Dashboard: suroviny pod minimom, top 5 vyrobených produktov
    a dáta pre graf výroby za posledných 30 dní.
    """
    low_stock_query = "SELECT nazov as name, mnozstvo as quantity, min_zasoba as minStock FROM sklad WHERE mnozstvo < min_zasoba ORDER BY nazov"
    top_products_query = """
        SELECT nazov_vyrobku as name, SUM(realne_mnozstvo_kg) as total
        FROM zaznamy_vyroba
        WHERE datum_ukoncenia >= CURDATE() - INTERVAL 30 DAY AND stav = 'Ukončené' AND realne_mnozstvo_kg > 0
        GROUP BY nazov_vyrobku
        ORDER BY total DESC
        LIMIT 5
    """
    production_timeseries_query = """
        SELECT DATE_FORMAT(datum_ukoncenia, '%%Y-%%m-%%d') as production_date, SUM(realne_mnozstvo_kg) as total_kg
        FROM zaznamy_vyroba
        WHERE datum_ukoncenia >= CURDATE() - INTERVAL 30 DAY AND stav = 'Ukončené'
        GROUP BY production_date
        ORDER BY production_date ASC
    """
    low_stock_items = execute_query(low_stock_query)
    top_products = execute_query(top_products_query)
    time_series = execute_query(production_timeseries_query)
    
    return {
        "lowStockItems": low_stock_items,
        "topProducts": top_products,
        "timeSeriesData": time_series
    }

def get_kancelaria_base_data():
    """
    Získa základné dáta pre menu 'Kancelária'.
    """
    warehouse = get_warehouse_state()
    item_types = ['Mäso', 'Koreniny', 'Obaly - Črevá', 'Pomocný material']
    
    products_without_recipe_query = """
        SELECT nazov_vyrobku 
        FROM katalog_produktov 
        WHERE typ_produktu LIKE 'VÝROBA%%' 
        AND nazov_vyrobku NOT IN (SELECT DISTINCT nazov_vyrobku FROM recepty)
        ORDER BY nazov_vyrobku
    """
    products_list = execute_query(products_without_recipe_query)
    products_without_recipe = [p['nazov_vyrobku'] for p in products_list]

    categories_query = "SELECT DISTINCT kategoria_pre_recepty FROM katalog_produktov WHERE kategoria_pre_recepty IS NOT NULL AND kategoria_pre_recepty != '' ORDER BY kategoria_pre_recepty"
    categories_list = execute_query(categories_query)
    recipe_categories = [c['kategoria_pre_recepty'] for c in categories_list]
    
    return {
        'warehouse': warehouse, 
        'itemTypes': item_types,
        'productsWithoutRecipe': products_without_recipe,
        'recipeCategories': recipe_categories
    }

def receive_multiple_stock_items(items):
    if not items: return {"error": "Neboli poskytnuté žiadne položky na príjem."}
    stock_items = execute_query("SELECT nazov, mnozstvo, nakupna_cena FROM sklad", fetch='all')
    stock_map = {item['nazov']: {'qty': float(item.get('mnozstvo') or 0.0), 'price': float(item.get('nakupna_cena') or 0.0)} for item in stock_items}
    
    items_to_log = []
    updates_to_sklad = []

    for item in items:
        item_name = item.get('name')
        received_qty = float(item.get('quantity') or 0.0)
        received_price = float(item.get('price') or 0.0)
        if not all([item_name, received_qty > 0]): continue
        
        items_to_log.append((item.get('date'), item_name, received_qty, received_price, item.get('note')))
        
        current_item = stock_map.get(item_name, {'qty': 0, 'price': 0})
        old_qty = current_item['qty']
        old_avg_price = current_item['price']
        
        new_qty = old_qty + received_qty
        new_avg_price = ((old_qty * old_avg_price) + (received_qty * received_price)) / new_qty if new_qty > 0 else received_price
        
        updates_to_sklad.append((new_qty, new_avg_price, item_name))

    if items_to_log:
        execute_query("INSERT INTO zaznamy_prijem (datum, nazov_suroviny, mnozstvo_kg, nakupna_cena_eur_kg, poznamka_dodavatel) VALUES (%s, %s, %s, %s, %s)", items_to_log, fetch='none', multi=True)
    if updates_to_sklad:
        execute_query("UPDATE sklad SET mnozstvo = %s, nakupna_cena = %s WHERE nazov = %s", updates_to_sklad, fetch='none', multi=True)

    return {"message": f"Úspešne prijatých {len(items_to_log)} položiek na sklad."}

def calculate_production_plan():
    product_query = "SELECT nazov_vyrobku, aktualny_sklad_finalny_kg, minimalna_zasoba_kg, vyrobna_davka_kg FROM katalog_produktov WHERE TRIM(UPPER(typ_produktu)) LIKE 'VÝROBA%%'"
    products_to_plan = execute_query(product_query, fetch='all')
    
    production_plan = []
    for product in products_to_plan:
        nazov = product['nazov_vyrobku']
        aktualny_sklad = float(product.get('aktualny_sklad_finalny_kg') or 0.0)
        min_zasoba = float(product.get('minimalna_zasoba_kg') or 0.0)
        vyrobna_davka = float(product.get('vyrobna_davka_kg') or 50.0)
        if vyrobna_davka == 0: vyrobna_davka = 50.0

        potrebne_vyrobit = min_zasoba - aktualny_sklad

        if potrebne_vyrobit > 0:
            pocet_davok = math.ceil(potrebne_vyrobit / vyrobna_davka)
            finalne_mnozstvo = pocet_davok * vyrobna_davka
            plan_item = {
                "nazov_vyrobku": nazov, 
                "aktualny_sklad": aktualny_sklad,
                "minimalna_zasoba": min_zasoba, 
                "potrebne_vyrobit": potrebne_vyrobit, 
                "navrhovana_vyroba": finalne_mnozstvo
            }
            production_plan.append(plan_item)
    return production_plan

def create_production_tasks_from_plan(plan):
    if not plan: return {"message": "Plán je prázdny, neboli vytvorené žiadne nové úlohy."}
    existing_tasks_query = "SELECT nazov_vyrobku FROM zaznamy_vyroba WHERE stav = 'Automaticky naplánované'"
    existing_tasks_list = [t['nazov_vyrobku'] for t in execute_query(existing_tasks_query, fetch='all')]
    tasks_to_create = []
    for item in plan:
        if item['nazov_vyrobku'] not in existing_tasks_list:
            task = (f"AUTO-{item['nazov_vyrobku'][:10]}-{datetime.now().strftime('%y%m%d%H%M')}", 'Automaticky naplánované', datetime.now(), item['nazov_vyrobku'], item['navrhovana_vyroba'])
            tasks_to_create.append(task)
    if not tasks_to_create: return {"message": "Všetky naplánované položky už majú vytvorenú výrobnú úlohu."}
    execute_query("INSERT INTO zaznamy_vyroba (id_davky, stav, datum_vyroby, nazov_vyrobku, planovane_mnozstvo_kg) VALUES (%s, %s, %s, %s, %s)", tasks_to_create, fetch='none', multi=True)
    return {"message": f"Úspešne vytvorených {len(tasks_to_create)} nových výrobných úloh."}

def get_purchase_suggestions():
    plan = calculate_production_plan()
    warehouse_state = get_warehouse_state()
    warehouse_map = {item['name']: {'quantity': float(item.get('quantity') or 0.0), 'minStock': float(item.get('minStock') or 0.0)} for item in warehouse_state['all']}
    
    total_requirements = {}
    for item in plan:
        if item['navrhovana_vyroba'] > 0:
            ingredients_result = calculate_required_ingredients(item['nazov_vyrobku'], item['navrhovana_vyroba'])
            if 'data' in ingredients_result:
                for ing in ingredients_result['data']:
                    required = float(ing['required'])
                    if ing['name'] not in ['Ľad', 'Voda', 'Ovar']:
                        total_requirements[ing['name']] = total_requirements.get(ing['name'], 0) + required

    suggestions = []
    for name, required_qty in total_requirements.items():
        stock_item = warehouse_map.get(name)
        if stock_item:
            projected_stock = stock_item['quantity'] - required_qty
            min_stock = stock_item.get('minStock', 0.0)
            if projected_stock < min_stock:
                purchase_qty = min_stock - projected_stock
                suggestions.append({
                    "name": name, 
                    "currentStock": stock_item['quantity'], 
                    "required": required_qty, 
                    "projectedStock": projected_stock, 
                    "minStock": min_stock, 
                    "purchaseQty": purchase_qty
                })
    
    for name, stock_item in warehouse_map.items():
        if name not in total_requirements and stock_item['quantity'] < stock_item.get('minStock', 0.0):
            purchase_qty = stock_item.get('minStock', 0.0) - stock_item['quantity']
            if purchase_qty > 0:
                 suggestions.append({
                    "name": name, 
                    "currentStock": stock_item['quantity'], 
                    "required": 0, 
                    "projectedStock": stock_item['quantity'], 
                    "minStock": stock_item.get('minStock', 0.0), 
                    "purchaseQty": purchase_qty
                })

    return sorted(suggestions, key=lambda x: x['name'])

def get_production_stats(period, category):
    today = datetime.now()
    if period == 'week':
        start_date = today - timedelta(days=7)
    elif period == 'month':
        start_date = today - timedelta(days=30)
    else: # 'all'
        start_date = datetime(1970, 1, 1)

    base_query = """
        SELECT 
            zv.nazov_vyrobku,
            zv.datum_ukoncenia,
            zv.planovane_mnozstvo_kg,
            zv.realne_mnozstvo_kg,
            zv.realne_mnozstvo_ks,
            zv.celkova_cena_surovin,
            kp.kategoria_pre_recepty,
            kp.mj as unit
        FROM zaznamy_vyroba zv
        LEFT JOIN katalog_produktov kp ON zv.nazov_vyrobku = kp.nazov_vyrobku
        WHERE zv.stav = 'Ukončené' AND zv.datum_ukoncenia >= %s
    """
    params = [start_date]

    if category and category != 'Všetky':
        base_query += " AND kp.kategoria_pre_recepty = %s"
        params.append(category)

    base_query += " ORDER BY zv.datum_ukoncenia DESC"

    records = execute_query(base_query, tuple(params))
    
    return {'period': period, 'category': category, 'data': records}

# =================================================================
# === FUNKCIE PRE ADMINISTRÁCIU ===
# =================================================================

def add_new_stock_item(name, item_type, price):
    if not name or not item_type:
        return {"error": "Názov a typ suroviny sú povinné."}
    check_query = "SELECT nazov FROM sklad WHERE nazov = %s"
    if execute_query(check_query, (name,), fetch='one'):
        return {"error": f"Surovina s názvom '{name}' už existuje v sklade."}
    insert_query = "INSERT INTO sklad (nazov, typ, mnozstvo, nakupna_cena, min_zasoba) VALUES (%s, %s, 0, %s, 0)"
    execute_query(insert_query, (name, item_type, float(price or 0.0)), fetch='none')
    return {"message": f"Surovina '{name}' bola úspešne pridaná do skladu."}

def add_new_product(product_data):
    ean, name, category = product_data.get('ean'), product_data.get('name'), product_data.get('category')
    if not all([ean, name, category]):
        return {"error": "EAN, Názov produktu a Kategória sú povinné."}
    existing = execute_query("SELECT ean, nazov_vyrobku FROM katalog_produktov WHERE ean = %s OR nazov_vyrobku = %s", (ean, name), fetch='one')
    if existing:
        return {"error": f"Produkt s EAN '{ean}' alebo názvom '{name}' už existuje."}
    execute_query("INSERT INTO katalog_produktov (ean, nazov_vyrobku, kategoria_pre_recepty, typ_produktu, mj) VALUES (%s, %s, %s, 'VÝROBA(celok)', 'kg')", (ean, name, category), fetch='none')
    return {"message": f"Nový produkt '{name}' bol úspešne pridaný.", "newProduct": {"name": name, "category": category}}

def add_new_recipe(recipe_data):
    product_name = recipe_data.get('productName')
    ingredients = recipe_data.get('ingredients')
    if not product_name or not ingredients:
        return {"error": "Chýbajú dáta pre vytvorenie receptu."}
    if execute_query("SELECT id FROM recepty WHERE nazov_vyrobku = %s LIMIT 1", (product_name,), fetch='one'):
        return {"error": f"Recept pre produkt '{product_name}' už existuje."}
    rows_to_insert = [(product_name, ing['name'], ing['quantity']) for ing in ingredients]
    if not rows_to_insert:
        return {"error": "Recept neobsahuje žiadne suroviny."}
    execute_query("INSERT INTO recepty (nazov_vyrobku, nazov_suroviny, mnozstvo_na_davku_kg) VALUES (%s, %s, %s)", rows_to_insert, fetch='none', multi=True)
    return {"message": f"Recept pre '{product_name}' bol úspešne vytvorený."}

def get_all_recipes_for_editing():
    query = """
        SELECT kp.nazov_vyrobku, kp.kategoria_pre_recepty 
        FROM katalog_produktov kp
        WHERE kp.nazov_vyrobku IN (SELECT DISTINCT nazov_vyrobku FROM recepty)
        ORDER BY kp.kategoria_pre_recepty, kp.nazov_vyrobku
    """
    products_with_recipe = execute_query(query)
    
    categorized_recipes = {}
    for product in products_with_recipe:
        category = product.get('kategoria_pre_recepty', 'Nezaradené')
        product_name = product['nazov_vyrobku']
        if category not in categorized_recipes:
            categorized_recipes[category] = []
        categorized_recipes[category].append(product_name)
        
    return categorized_recipes

def get_recipe_details(product_name):
    if not product_name:
        return {"error": "Názov produktu nebol zadaný."}
    
    query = """
        SELECT r.nazov_suroviny as name, r.mnozstvo_na_davku_kg as quantity, s.typ as type
        FROM recepty r
        LEFT JOIN sklad s ON r.nazov_suroviny = s.nazov
        WHERE r.nazov_vyrobku = %s
    """
    ingredients = execute_query(query, (product_name,))
    if not ingredients:
        return {"error": f"Recept pre '{product_name}' nebol nájdený."}
        
    return {"productName": product_name, "ingredients": ingredients}

def update_recipe(recipe_data):
    product_name = recipe_data.get('productName')
    ingredients = recipe_data.get('ingredients')

    if not product_name or not ingredients:
        return {"error": "Chýbajú dáta pre úpravu receptu."}

    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recepty WHERE nazov_vyrobku = %s", (product_name,))
        
        rows_to_insert = [(product_name, ing['name'], ing['quantity']) for ing in ingredients]
        if rows_to_insert:
            insert_query = "INSERT INTO recepty (nazov_vyrobku, nazov_suroviny, mnozstvo_na_davku_kg) VALUES (%s, %s, %s)"
            cursor.executemany(insert_query, rows_to_insert)
            
        conn.commit()
        return {"message": f"Recept pre '{product_name}' bol úspešne upravený."}
    except Exception as e:
        conn.rollback()
        print(f"Chyba pri úprave receptu: {e}")
        return {"error": "Nastala databázová chyba pri úprave receptu."}
    finally:
        if conn and conn.is_connected():
            conn.close()

def delete_recipe(product_name):
    if not product_name:
        return {"error": "Chýba názov produktu na vymazanie."}
    
    execute_query("DELETE FROM recepty WHERE nazov_vyrobku = %s", (product_name,), fetch='none')
    return {"message": f"Recept pre '{product_name}' bol úspešne vymazaný."}

def get_slicing_management_data():
    source_query = "SELECT ean, nazov_vyrobku as name FROM katalog_produktov WHERE typ_produktu LIKE 'VÝROBA%%' ORDER BY nazov_vyrobku"
    target_query = """
        SELECT ean, nazov_vyrobku as name 
        FROM katalog_produktov 
        WHERE TRIM(UPPER(typ_produktu)) = 'KRÁJANIE' 
        AND (zdrojovy_ean IS NULL OR zdrojovy_ean = '' OR zdrojovy_ean = 'nan') 
        ORDER BY nazov_vyrobku
    """
    source_products = execute_query(source_query)
    unlinked_sliced_products = execute_query(target_query)
    
    return {
        "sourceProducts": source_products,
        "unlinkedSlicedProducts": unlinked_sliced_products
    }

def link_sliced_product(source_ean, target_ean):
    if not source_ean or not target_ean:
        return {"error": "Chýba zdrojový alebo cieľový EAN."}
    
    execute_query("UPDATE katalog_produktov SET zdrojovy_ean = %s WHERE ean = %s", (source_ean, target_ean), fetch='none')
    return {"message": "Produkty boli úspešne prepojené."}

def create_and_link_sliced_product(data):
    source_ean = data.get('sourceEan')
    new_name = data.get('name')
    new_ean = data.get('ean')
    new_weight = data.get('weight')

    if not all([source_ean, new_name, new_ean, new_weight]):
        return {"error": "Všetky polia pre vytvorenie nového produktu sú povinné."}

    existing = execute_query("SELECT ean FROM katalog_produktov WHERE ean = %s", (new_ean,), fetch='one')
    if existing:
        return {"error": f"Produkt s EAN kódom '{new_ean}' už existuje."}

    insert_query = """
        INSERT INTO katalog_produktov 
        (ean, nazov_vyrobku, mj, typ_produktu, vaha_balenia_g, zdrojovy_ean) 
        VALUES (%s, %s, 'ks', 'KRÁJANIE', %s, %s)
    """
    execute_query(insert_query, (new_ean, new_name, new_weight, source_ean), fetch='none')
    return {"message": f"Nový krájaný produkt '{new_name}' bol vytvorený a prepojený."}

def get_products_for_min_stock():
    query = "SELECT ean, nazov_vyrobku as name, mj, minimalna_zasoba_kg as minStockKg, minimalna_zasoba_ks as minStockKs FROM katalog_produktov WHERE typ_produktu LIKE 'VÝROBA%%' OR typ_produktu = 'KRÁJANIE' ORDER BY nazov_vyrobku"
    return execute_query(query)

def update_min_stock_levels(products_data):
    if not products_data:
        return {"error": "Neboli poskytnuté žiadne dáta na aktualizáciu."}
        
    updates = [(p['minStockKg'], p['minStockKs'], p['ean']) for p in products_data]
    
    execute_query("UPDATE katalog_produktov SET minimalna_zasoba_kg = %s, minimalna_zasoba_ks = %s WHERE ean = %s", updates, fetch='none', multi=True)
    
    return {"message": f"Minimálne zásoby boli úspešne aktualizované pre {len(updates)} produktov."}

# =================================================================
# === FUNKCIE PRE VÝROBU ===
# =================================================================

def get_warehouse_state():
    query = "SELECT nazov as name, typ as type, mnozstvo as quantity, nakupna_cena as price, min_zasoba as minStock FROM sklad ORDER BY typ, nazov"
    all_items = execute_query(query)
    warehouse = {'meat': [], 'spices': [], 'casings': [], 'auxiliary': [], 'all': all_items}
    for item in all_items:
        typ = item.get('type')
        if typ == 'Mäso': warehouse['meat'].append(item)
        elif typ == 'Koreniny': warehouse['spices'].append(item)
        elif typ == 'Obaly - Črevá': warehouse['casings'].append(item)
        elif typ == 'Pomocný material': warehouse['auxiliary'].append(item)
    return warehouse

def get_categorized_recipes():
    query = "SELECT nazov_vyrobku, kategoria_pre_recepty FROM katalog_produktov WHERE kategoria_pre_recepty IS NOT NULL AND kategoria_pre_recepty != '' AND TRIM(UPPER(typ_produktu)) LIKE 'VÝROBA%' ORDER BY nazov_vyrobku"
    products = execute_query(query)
    categorized_recipes = {}
    for product in products:
        category = product['kategoria_pre_recepty']
        product_name = product['nazov_vyrobku']
        if category not in categorized_recipes: categorized_recipes[category] = []
        categorized_recipes[category].append(product_name)
    return {'data': categorized_recipes}

def get_active_production_tasks_by_category():
    query = "SELECT zv.id_davky as logId, zv.nazov_vyrobku as productName, zv.planovane_mnozstvo_kg as actualKgQty, kp.kategoria_pre_recepty as category FROM zaznamy_vyroba AS zv JOIN katalog_produktov AS kp ON zv.nazov_vyrobku = kp.nazov_vyrobku WHERE zv.stav = 'Automaticky naplánované' AND TRIM(UPPER(kp.typ_produktu)) LIKE 'VÝROBA%' ORDER BY kp.kategoria_pre_recepty, zv.nazov_vyrobku"
    tasks_list = execute_query(query)
    categorized_tasks = {}
    for task in tasks_list:
        category = task.get('category') or "Nezaradené"
        if category not in categorized_tasks: categorized_tasks[category] = []
        task['displayQty'] = f"{float(task['actualKgQty']):.2f} kg"
        categorized_tasks[category].append(task)
    return categorized_tasks

def get_production_menu_data():
    tasks = get_active_production_tasks_by_category()
    warehouse = get_warehouse_state()
    recipes = get_categorized_recipes()
    return {'tasks': tasks, 'warehouse': warehouse, 'recipes': recipes.get('data')}

def find_recipe_data(product_name):
    query = "SELECT nazov_suroviny, mnozstvo_na_davku_kg FROM recepty WHERE nazov_vyrobku = %s"
    return execute_query(query, (product_name,))

def calculate_required_ingredients(product_name, planned_weight):
    if not product_name or not planned_weight or float(planned_weight) <= 0: return {"error": "Zadajte platný produkt a množstvo."}
    recipe_ingredients = find_recipe_data(product_name)
    if not recipe_ingredients: return {"error": f'Recept s názvom "{product_name}" nebol nájdený v databáze.'}
    planned_weight_float = float(planned_weight); batch_multiplier = planned_weight_float / 100.0
    warehouse_map = {item['name']: item for item in get_warehouse_state()['all']}
    result_data = []; special_ingredients = ['Ľad', 'Voda', 'Ovar']
    for ing in recipe_ingredients:
        mnozstvo_v_recepte = ing.get('mnozstvo_na_davku_kg') or 0.0
        required_qty = float(mnozstvo_v_recepte) * batch_multiplier
        stock_info = warehouse_map.get(ing.get('nazov_suroviny'), {})
        stock_quantity = stock_info.get('quantity') or 0.0
        stock_type = stock_info.get('type', 'Neznámy')
        is_sufficient = True
        if ing.get('nazov_suroviny') not in special_ingredients:
            if stock_quantity < required_qty: is_sufficient = False
        result_data.append({"name": ing.get('nazov_suroviny'), "type": stock_type, "required": f"{required_qty:.3f}", "inStock": f"{stock_quantity:.2f}", "isSufficient": is_sufficient})
    return {"data": result_data}

def start_production(product_name, planned_weight, production_date, ingredients, existing_log_id=None):
    planned_weight_float = float(planned_weight); total_batch_cost = 0; updates_to_sklad = []
    ingredient_names = [ing['name'] for ing in ingredients]
    prices_list = execute_query(f"SELECT nazov, nakupna_cena FROM sklad WHERE nazov IN ({','.join(['%s'] * len(ingredient_names))})", ingredient_names) if ingredient_names else []
    price_map = {p['nazov']: (p['nakupna_cena'] or 0) for p in prices_list}
    for ingredient in ingredients:
        quantity_to_deduct = float(ingredient['quantity'])
        price = float(price_map.get(ingredient['name'], 0) or 0.0)
        total_batch_cost += quantity_to_deduct * price
        updates_to_sklad.append((quantity_to_deduct, ingredient['name']))
    if updates_to_sklad:
        execute_query("UPDATE sklad SET mnozstvo = mnozstvo - %s WHERE nazov = %s", updates_to_sklad, fetch='none', multi=True)
    start_time = datetime.now()
    if existing_log_id:
        log_params = ('Vo výrobe', production_date, start_time, total_batch_cost, existing_log_id)
        execute_query("UPDATE zaznamy_vyroba SET stav = %s, datum_vyroby = %s, datum_spustenia = %s, celkova_cena_surovin = %s WHERE id_davky = %s", log_params, fetch='none')
        return {"message": f"Príkaz {existing_log_id} bol spustený do výroby."}
    else:
        batch_id = f"{product_name} {start_time.strftime('%d.%m.%y-%H:%M:%S')}"
        log_params = (batch_id, 'Vo výrobe', production_date, product_name, planned_weight_float, total_batch_cost, start_time)
        execute_query("INSERT INTO zaznamy_vyroba (id_davky, stav, datum_vyroby, nazov_vyrobku, planovane_mnozstvo_kg, celkova_cena_surovin, datum_spustenia) VALUES (%s, %s, %s, %s, %s, %s, %s)", log_params, fetch='none')
        return {"message": f"VÝROBA SPUSTENÁ! Šarža: {batch_id}."}

def update_inventory(inventory_data):
    if not inventory_data: return {"error": "Neboli zadané žiadne platné reálne stavy na úpravu."}
    warehouse_items = get_warehouse_state()['all']
    price_map = {item['name']: item['price'] for item in warehouse_items}
    type_map = {item['name']: item['type'] for item in warehouse_items}
    differences_to_log = []; updates_to_sklad = []
    for item in inventory_data:
        real_qty = float(item['realQty']); system_qty = float(item['systemQty']); diff = real_qty - system_qty
        if diff != 0:
            price = float(price_map.get(item['name'], 0.0) or 0.0)
            log_entry = (datetime.now(), item['name'], type_map.get(item['name'], 'Neznámy'), system_qty, real_qty, diff, (diff * price))
            differences_to_log.append(log_entry)
            updates_to_sklad.append((real_qty, item['name']))
    if differences_to_log:
        execute_query("INSERT INTO inventurne_rozdiely (datum, nazov_suroviny, typ_suroviny, systemovy_stav_kg, realny_stav_kg, rozdiel_kg, hodnota_rozdielu_eur) VALUES (%s, %s, %s, %s, %s, %s, %s)", differences_to_log, fetch='none', multi=True)
    if updates_to_sklad:
        execute_query("UPDATE sklad SET mnozstvo = %s WHERE nazov = %s", updates_to_sklad, fetch='none', multi=True)
    return {"message": f"Inventúra dokončená. Aktualizovaných {len(updates_to_sklad)} položiek."}

def get_all_warehouse_items():
    return execute_query("SELECT nazov as name, typ as type FROM sklad ORDER BY typ, nazov")

def manual_warehouse_write_off(data):
    worker_name = data.get('workerName'); item_name = data.get('itemName'); quantity_str = data.get('quantity'); note = data.get('note')
    if not all([worker_name, item_name, quantity_str, note]): return {"error": "Všetky polia sú povinné."}
    try:
        quantity = float(quantity_str)
        if quantity <= 0: raise ValueError("Množstvo musí byť kladné číslo.")
    except (ValueError, TypeError): return {"error": "Zadané neplatné množstvo."}
    
    execute_query("UPDATE sklad SET mnozstvo = mnozstvo - %s WHERE nazov = %s", (quantity, item_name), fetch='none')
    execute_query("INSERT INTO vydajky (datum, pracovnik, nazov_suroviny, mnozstvo_kg, poznamka) VALUES (%s, %s, %s, %s, %s)", (datetime.now(), worker_name, item_name, quantity, note), fetch='none')
    
    return {"message": f"Úspešne odpísaných {quantity} kg suroviny '{item_name}'."}


# =================================================================
# === FUNKCIE PRE REPORTY ===
# =================================================================

def get_receipt_report_html(period, category):
    today = datetime.now()
    if period == 'day':
        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start_date = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'month':
        start_date = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start_date = datetime(1970, 1, 1)

    query = """
        SELECT p.datum, p.nazov_suroviny, s.typ, p.mnozstvo_kg, p.nakupna_cena_eur_kg, p.poznamka_dodavatel
        FROM zaznamy_prijem p
        LEFT JOIN sklad s ON p.nazov_suroviny = s.nazov
        WHERE p.datum >= %s
    """
    params = [start_date]
    if category and category != 'Všetky':
        query += " AND s.typ = %s"
        params.append(category)
    query += " ORDER BY p.datum DESC, p.nazov_suroviny"
    
    records = execute_query(query, tuple(params))

    body_rows = ""
    total_value = 0
    for row in records:
        value = (row.get('mnozstvo_kg') or 0) * (row.get('nakupna_cena_eur_kg') or 0)
        total_value += value
        body_rows += f"""
        <tr>
            <td>{row['datum'].strftime('%d.%m.%Y')}</td>
            <td>{row['nazov_suroviny']}</td>
            <td>{row['typ']}</td>
            <td>{float(row['mnozstvo_kg']):.2f} kg</td>
            <td>{float(row['nakupna_cena_eur_kg']):.4f} €</td>
            <td>{float(value):.2f} €</td>
            <td>{row['poznamka_dodavatel']}</td>
        </tr>
        """
    
    html = f"""
    <html>
    <head><title>Report Príjmu</title><style>body{{font-family:sans-serif;}} table{{width:100%; border-collapse:collapse;}} th,td{{border:1px solid #ddd; padding:8px;}} th{{background-color:#f2f2f2;}} .total-row td{{font-weight:bold;}}</style></head>
    <body>
        <h1>Report Príjmu Surovín</h1>
        <p><strong>Obdobie:</strong> {period}, <strong>Kategória:</strong> {category}</p>
        <table>
            <thead><tr><th>Dátum</th><th>Názov</th><th>Typ</th><th>Množstvo</th><th>Cena/kg</th><th>Hodnota</th><th>Dodávateľ</th></tr></thead>
            <tbody>
                {body_rows}
                <tr class="total-row"><td colspan="5">Celková hodnota príjmu</td><td colspan="2">{total_value:.2f} €</td></tr>
            </tbody>
        </table>
        <script>window.onload = function() {{ window.print(); }};</script>
    </body>
    </html>
    """
    return html

def get_inventory_difference_report_html(date_str):
    if not date_str:
        return "<h1>Chyba: Nebol zadaný dátum.</h1>"

    query = "SELECT * FROM inventurne_rozdiely WHERE DATE(datum) = %s ORDER BY nazov_suroviny"
    records = execute_query(query, (date_str,))

    body_rows = ""
    total_diff_value = 0
    for row in records:
        diff_value = float(row.get('hodnota_rozdielu_eur') or 0.0)
        total_diff_value += diff_value
        body_rows += f"""
        <tr>
            <td>{row['nazov_suroviny']}</td>
            <td>{float(row['systemovy_stav_kg']):.2f} kg</td>
            <td>{float(row['realny_stav_kg']):.2f} kg</td>
            <td style="color: {'red' if row['rozdiel_kg'] < 0 else 'green'};">{float(row['rozdiel_kg']):.2f} kg</td>
            <td style="color: {'red' if diff_value < 0 else 'green'};">{diff_value:.2f} €</td>
        </tr>
        """
        
    html = f"""
    <html>
    <head><title>Report Inventúrnych Rozdielov</title><style>body{{font-family:sans-serif;}} table{{width:100%; border-collapse:collapse;}} th,td{{border:1px solid #ddd; padding:8px;}} th{{background-color:#f2f2f2;}} .total-row td{{font-weight:bold;}}</style></head>
    <body>
        <h1>Report Inventúrnych Rozdielov zo dňa {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')}</h1>
        <table>
            <thead><tr><th>Surovina</th><th>Systémový stav</th><th>Reálny stav</th><th>Rozdiel (kg)</th><th>Rozdiel (€)</th></tr></thead>
            <tbody>
                {body_rows}
                <tr class="total-row"><td colspan="4">Celkový rozdiel v hodnote</td><td>{total_diff_value:.2f} €</td></tr>
            </tbody>
        </table>
        <script>window.onload = function() {{ window.print(); }};</script>
    </body>
    </html>
    """
    return html

