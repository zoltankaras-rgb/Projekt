import db_connector
from datetime import datetime
import math
import json

# =================================================================
# === FUNKCIE PRE EXPEDÍCIU ===
# =================================================================

def get_expedition_data():
    """Získa dáta pre hlavné zobrazenie expedície, napr. prebiehajúce krájanie."""
    query = """
        SELECT
            zv.id_davky as logId, zv.nazov_vyrobku as bulkProductName,
            zv.planovane_mnozstvo_kg as plannedKg,
            JSON_UNQUOTE(JSON_EXTRACT(zv.detaily_zmeny, '$.cielovyNazov')) as targetProductName,
            JSON_UNQUOTE(JSON_EXTRACT(zv.detaily_zmeny, '$.planovaneKs')) as plannedPieces
        FROM zaznamy_vyroba zv
        WHERE zv.stav = 'Prebieha krájanie'
    """
    return {"pendingTasks": db_connector.execute_query(query)}

def get_production_dates():
    """Získa zoznam unikátnych dátumov výroby pre dávky čakajúce na spracovanie."""
    query = "SELECT DISTINCT DATE(datum_vyroby) as production_date FROM zaznamy_vyroba WHERE stav IN ('Vo výrobe', 'Prebieha krájanie', 'Prijaté, čaká na tlač') ORDER BY production_date DESC"
    dates = db_connector.execute_query(query)
    return [d['production_date'].strftime('%Y-%m-%d') for d in dates if d.get('production_date')]

def get_productions_by_date(date_string):
    """Získa všetky výrobné dávky pre zadaný dátum."""
    query = "SELECT zv.id_davky as batchId, zv.stav as status, zv.nazov_vyrobku as productName, zv.planovane_mnozstvo_kg as plannedQty, zv.realne_mnozstvo_kg as realQty, zv.realne_mnozstvo_ks as realPieces, p.mj, p.vaha_balenia_g as pieceWeightG, zv.datum_vyroby, zv.poznamka_expedicie FROM zaznamy_vyroba zv LEFT JOIN produkty p ON zv.nazov_vyrobku = p.nazov_vyrobku WHERE DATE(zv.datum_vyroby) = %s AND zv.stav IN ('Vo výrobe', 'Prebieha krájanie', 'Prijaté, čaká na tlač', 'Ukončené') ORDER BY zv.nazov_vyrobku"
    productions = db_connector.execute_query(query, (date_string,))
    for p in productions:
        planned_kg, weight_g = float(p.get('plannedQty') or 0.0), float(p.get('pieceWeightG') or 0.0)
        p['expectedPieces'] = math.ceil((planned_kg * 1000) / weight_g) if p.get('mj') == 'ks' and weight_g > 0 else None
        if isinstance(p.get('datum_vyroby'), datetime):
            p['datum_vyroby'] = p['datum_vyroby'].isoformat()
    return productions

def complete_multiple_productions(items):
    """Spracuje hromadné prevzatie výrobkov z výroby."""
    if not items: return {"error": "Neboli poskytnuté žiadne položky."}
    
    updates, damages = [], []
    worker_name = items[0].get('workerName') # Predpokladáme, že meno je rovnaké pre všetky
    
    for item in items:
        batch_id, status = item.get('batchId'), item.get('visualCheckStatus')
        if status == 'OK':
            val = float(item.get('actualValue') or 0.0)
            real_kg, real_ks = (val, None) if item.get('unit') != 'ks' else (None, int(val))
            updates.append(('Prijaté, čaká na tlač', real_kg, real_ks, item.get('note'), batch_id))
        elif status == 'Iné':
            updates.append(('Vo výrobe', None, None, item.get('note', 'Vrátené na opravu'), batch_id))
        elif status == 'NEPRIJATÉ':
            updates.append(('ŠKODA', None, None, item.get('note', 'Neprešlo vizuálnou kontrolou'), batch_id))
            damages.append((datetime.now(), batch_id, item.get('productName'), f"{item.get('plannedQty')} kg", item.get('note'), worker_name))
    
    if updates: db_connector.execute_query("UPDATE zaznamy_vyroba SET stav = %s, realne_mnozstvo_kg = %s, realne_mnozstvo_ks = %s, poznamka_expedicie = %s WHERE id_davky = %s", updates, fetch='none', multi=True)
    if damages: db_connector.execute_query("INSERT INTO skody (datum, id_davky, nazov_vyrobku, mnozstvo, dovod, pracovnik) VALUES (%s, %s, %s, %s, %s, %s)", damages, fetch='none', multi=True)
    return {"message": f"Úspešne spracovaných {len(items)} dávok."}

def finalize_day(date_string):
    """Finalizuje deň - presunie prijaté výrobky na sklad."""
    items = db_connector.execute_query("SELECT zv.id_davky, zv.nazov_vyrobku, zv.realne_mnozstvo_kg, zv.realne_mnozstvo_ks, zv.celkova_cena_surovin, p.ean, p.mj, p.vaha_balenia_g FROM zaznamy_vyroba zv LEFT JOIN produkty p ON zv.nazov_vyrobku = p.nazov_vyrobku WHERE DATE(zv.datum_vyroby) = %s AND zv.stav = 'Prijaté, čaká na tlač'", (date_string,))
    if not items: return {"error": "Nenašli sa žiadne dávky v stave 'Prijaté, čaká na tlač'."}
    
    updates_log, updates_catalog = [], []
    for item in items:
        cost = float(item.get('celkova_cena_surovin') or 0.0) * 1.15
        real_kg, real_ks = float(item.get('realne_mnozstvo_kg') or 0.0), int(item.get('realne_mnozstvo_ks') or 0)
        cost_per_unit = (cost / real_ks) if item['mj'] == 'ks' and real_ks > 0 else (cost / real_kg if real_kg > 0 else 0)
        updates_log.append(('Ukončené', datetime.now(), cost_per_unit, item['id_davky']))
        
        qty_add_kg = 0
        if item['mj'] == 'kg':
            qty_add_kg = real_kg
        elif item['mj'] == 'ks' and item.get('vaha_balenia_g'):
            qty_add_kg = (real_ks * float(item.get('vaha_balenia_g'))) / 1000

        if item['ean'] and qty_add_kg > 0:
            updates_catalog.append((qty_add_kg, item['ean']))
    
    if updates_log: db_connector.execute_query("UPDATE zaznamy_vyroba SET stav = %s, datum_ukoncenia = %s, cena_za_jednotku = %s WHERE id_davky = %s", updates_log, fetch='none', multi=True)
    if updates_catalog: db_connector.execute_query("UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg + %s WHERE ean = %s", updates_catalog, fetch='none', multi=True)
    return {"message": f"Deň {date_string} bol úspešne finalizovaný. {len(updates_log)} dávok ukončených."}

def get_accompanying_letter_data(batch_id):
    """Získa dáta pre sprievodný list, teraz už aj s EAN kódom."""
    query = """
        SELECT 
            zv.id_davky as batchId, 
            zv.nazov_vyrobku as productName, 
            zv.datum_vyroby as productionDate, 
            zv.realne_mnozstvo_kg as realQtyKg, 
            zv.realne_mnozstvo_ks as realQtyKs, 
            p.mj as unit,
            p.ean
        FROM zaznamy_vyroba zv 
        LEFT JOIN produkty p ON zv.nazov_vyrobku = p.nazov_vyrobku 
        WHERE zv.id_davky = %s
    """
    return db_connector.execute_query(query, (batch_id,), fetch='one')

def get_slicable_products():
    """Získa zoznam všetkých produktov, ktoré sú určené na krájanie."""
    return db_connector.execute_query("SELECT ean, nazov_vyrobku as name FROM produkty WHERE typ_polozky = 'VYROBOK_KRAJANY' ORDER BY nazov_vyrobku")

def start_slicing_request(packaged_product_ean, planned_pieces):
    """Spracuje požiadavku na krájanie - odpíše zdrojový produkt a vytvorí úlohu."""
    if not all([packaged_product_ean, planned_pieces and int(planned_pieces) > 0]): return {"error": "Musíte vybrať produkt a zadať platný počet kusov."}
    
    p_info = db_connector.execute_query("SELECT target.ean as target_ean, target.nazov_vyrobku as target_name, target.vaha_balenia_g as target_weight_g, target.zdrojovy_ean, source.nazov_vyrobku as source_name FROM produkty as target LEFT JOIN produkty as source ON target.zdrojovy_ean = source.ean WHERE target.ean = %s", (packaged_product_ean,), fetch='one')
    if not p_info or not p_info.get('zdrojovy_ean'): return {"error": "Produkt nebol nájdený alebo nie je prepojený so zdrojovým produktom."}
    
    required_kg = (int(planned_pieces) * float(p_info['target_weight_g'])) / 1000
    cost_info = db_connector.execute_query("SELECT cena_za_jednotku as unit_cost FROM zaznamy_vyroba WHERE nazov_vyrobku = %s AND stav = 'Ukončené' ORDER BY datum_ukoncenia DESC LIMIT 1", (p_info['source_name'],), fetch='one')
    total_cost = required_kg * float(cost_info.get('unit_cost') or 0.0)
    
    db_connector.execute_query("UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg - %s WHERE ean = %s", (required_kg, p_info['zdrojovy_ean']), fetch='none')
    
    batch_id = f"KRAJANIE-{p_info['target_name'][:10]}-{datetime.now().strftime('%y%m%d%H%M')}"
    details = json.dumps({"operacia": "krajanie", "cielovyEan": p_info["target_ean"], "cielovyNazov": p_info["target_name"], "planovaneKs": planned_pieces})
    log_params = (batch_id, 'Prebieha krájanie', datetime.now(), p_info['source_name'], required_kg, datetime.now(), total_cost, details)
    db_connector.execute_query("INSERT INTO zaznamy_vyroba (id_davky, stav, datum_vyroby, nazov_vyrobku, planovane_mnozstvo_kg, datum_spustenia, celkova_cena_surovin, detaily_zmeny) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", log_params, fetch='none')
    
    return {"message": f"Požiadavka vytvorená. Odpočítaných {required_kg:.2f} kg produktu '{p_info['source_name']}'."}

def finalize_slicing_transaction(log_id, actual_pieces):
    """Finalizuje úlohu krájania."""
    if not all([log_id, actual_pieces is not None and int(actual_pieces) >= 0]): return {"error": "Chýba ID úlohy alebo platný počet kusov."}

    original_task = db_connector.execute_query("SELECT * FROM zaznamy_vyroba WHERE id_davky = %s AND stav = 'Prebieha krájanie'", (log_id,), 'one')
    if not original_task: return {"error": f"Úloha krájania {log_id} nebola nájdená alebo už bola spracovaná."}
    
    try: details = json.loads(original_task.get('detaily_zmeny'))
    except: return {"error": "Chyba v zázname o krájaní: poškodené detaily."}
    
    target_ean, target_name = details.get('cielovyEan'), details.get('cielovyNazov')
    target_product = db_connector.execute_query("SELECT vaha_balenia_g FROM produkty WHERE ean = %s", (target_ean,), 'one')
    if not target_product or not target_product.get('vaha_balenia_g'): return {"error": f"Produkt '{target_name}' nemá definovanú váhu balenia."}
    
    real_kg = (int(actual_pieces) * float(target_product['vaha_balenia_g'])) / 1000
    update_params = ("Prijaté, čaká na tlač", target_name, actual_pieces, real_kg, log_id)
    db_connector.execute_query("UPDATE produkty SET stav = %s, nazov_vyrobku = %s, realne_mnozstvo_ks = %s, realne_mnozstvo_kg = %s WHERE id_davky = %s", update_params, 'none')

    return {"message": f"Úloha pre '{target_name}' ukončená s {actual_pieces} ks."}

def get_all_final_products():
    """Získa zoznam všetkých finálnych produktov (kg aj ks)."""
    return db_connector.execute_query("SELECT ean, nazov_vyrobku as name, mj as unit FROM produkty WHERE typ_polozky IN ('VÝROBOK', 'VYROBOK_KRAJANY', 'VÝROBOK_KUSOVY') ORDER BY nazov_vyrobku")

def manual_receive_product(data):
    """Spracuje manuálny príjem finálneho výrobku na sklad."""
    ean, qty_str, worker, date = data.get('ean'), data.get('quantity'), data.get('workerName'), data.get('receptionDate')
    if not all([ean, qty_str, worker, date]): return {"error": "Všetky polia sú povinné."}
    
    product = db_connector.execute_query("SELECT nazov_vyrobku, mj, vaha_balenia_g FROM produkty WHERE ean = %s", (ean,), 'one')
    if not product: return {"error": "Produkt s daným EAN nebol nájdený."}

    qty = float(qty_str)
    qty_kg = qty if product['mj'] == 'kg' else (qty * float(product.get('vaha_balenia_g') or 0.0) / 1000)
    db_connector.execute_query("UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg + %s WHERE ean = %s", (qty_kg, ean), 'none')

    batch_id = f"MANUAL-PRIJEM-{datetime.now().strftime('%y%m%d%H%M')}"
    log_params = (batch_id, 'Ukončené', date, datetime.now(), product['nazov_vyrobku'], qty if product['mj'] == 'kg' else None, qty if product['mj'] == 'ks' else None, f"Manuálne prijal: {worker}")
    db_connector.execute_query("INSERT INTO zaznamy_vyroba (id_davky, stav, datum_vyroby, datum_ukoncenia, nazov_vyrobku, realne_mnozstvo_kg, realne_mnozstvo_ks, poznamka_expedicie) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", log_params, 'none')
    return {"message": f"Úspešne prijatých {qty} {product['mj']} produktu '{product['nazov_vyrobku']}'."}

def log_manual_damage(data):
    """Zapíše manuálnu škodu a odpočíta produkt zo skladu."""
    ean, qty_str, worker, note = data.get('ean'), data.get('quantity'), data.get('workerName'), data.get('note')
    if not all([ean, qty_str, worker, note]): return {"error": "Všetky polia sú povinné."}

    product = db_connector.execute_query("SELECT nazov_vyrobku, mj, vaha_balenia_g FROM produkty WHERE ean = %s", (ean,), 'one')
    if not product: return {"error": "Produkt s daným EAN nebol nájdený."}
    
    qty = float(qty_str)
    qty_kg = qty if product['mj'] == 'kg' else (qty * float(product.get('vaha_balenia_g') or 0.0) / 1000)
    db_connector.execute_query("UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg - %s WHERE ean = %s", (qty_kg, ean), 'none')

    skoda_params = (datetime.now(), f"MANUAL-SKODA-{datetime.now().strftime('%y%m%d%H%M')}", product['nazov_vyrobku'], f"{qty} {product['mj']}", note, worker)
    db_connector.execute_query("INSERT INTO skody (datum, id_davky, nazov_vyrobku, mnozstvo, dovod, pracovnik) VALUES (%s, %s, %s, %s, %s, %s)", skoda_params, 'none')
    return {"message": f"Škoda zapísaná. Sklad znížený o {qty_kg:.2f} kg."}

def get_products_for_inventory():
    """
    Získa zoznam všetkých finálnych a tovarových produktov
    pre zobrazenie v inventúrnom formulári expedície.
    """
    query = """
        SELECT 
            p.ean, p.nazov_vyrobku, p.predajna_kategoria, 
            p.aktualny_sklad_finalny_kg, p.mj, p.vaha_balenia_g
        FROM produkty p 
        WHERE p.typ_polozky LIKE 'VÝROBOK%%' OR p.typ_polozky LIKE 'TOVAR%%'
        ORDER BY p.predajna_kategoria, p.nazov_vyrobku
    """
    products = db_connector.execute_query(query)
    
    categorized_products = {}
    for product in products:
        category = product.get('predajna_kategoria') or 'Nezaradené'
        if category not in categorized_products:
            categorized_products[category] = []
        
        kg_stock = float(product.get('aktualny_sklad_finalny_kg') or 0.0)
        weight_g = float(product.get('vaha_balenia_g') or 0.0)
        if product.get('mj') == 'ks' and weight_g > 0:
            product['system_stock_display'] = f"{(kg_stock * 1000 / weight_g):.2f}".replace('.', ',')
        else:
            product['system_stock_display'] = f"{kg_stock:.2f}".replace('.', ',')

        categorized_products[category].append(product)
        
    return categorized_products

def submit_product_inventory(inventory_data, worker_name):
    """
    Spracuje dáta z inventúry finálnych produktov, zapíše rozdiely
    a aktualizuje stav skladu.
    """
    if not inventory_data:
        return {"error": "Neboli zadané žiadne platné reálne stavy."}

    eans = [item['ean'] for item in inventory_data]
    if not eans:
        return {"message": "Žiadne položky na spracovanie."}
    placeholders = ','.join(['%s'] * len(eans))
    
    products_query = f"""
        SELECT 
            p.ean, p.nazov_vyrobku, p.predajna_kategoria,
            p.aktualny_sklad_finalny_kg, p.mj, p.vaha_balenia_g,
            (SELECT zv.cena_za_jednotku 
             FROM zaznamy_vyroba zv 
             WHERE zv.nazov_vyrobku = p.nazov_vyrobku AND zv.stav = 'Ukončené' AND zv.cena_za_jednotku > 0
             ORDER BY zv.datum_ukoncenia DESC LIMIT 1) as unit_cost
        FROM produkty p
        WHERE p.ean IN ({placeholders})
    """
    all_products_list = db_connector.execute_query(products_query, tuple(eans))
    products_map = {p['ean']: p for p in all_products_list}

    differences_to_log = []
    updates_to_produkty = []

    for item in inventory_data:
        ean, real_qty_str = item.get('ean'), item.get('realQty')
        product_info = products_map.get(ean)
        
        if not all([ean, real_qty_str, product_info]): continue

        real_qty_num = float(real_qty_str.replace(',', '.'))
        real_qty_kg = 0
        
        if product_info['mj'] == 'kg':
            real_qty_kg = real_qty_num
        elif product_info['mj'] == 'ks' and product_info.get('vaha_balenia_g'):
            real_qty_kg = (real_qty_num * float(product_info['vaha_balenia_g'])) / 1000.0
        
        system_qty_kg = float(product_info.get('aktualny_sklad_finalny_kg') or 0.0)
        
        if abs(real_qty_kg - system_qty_kg) > 0.001:
            diff_kg = real_qty_kg - system_qty_kg
            unit_cost = float(product_info.get('unit_cost') or 0.0)
            price_per_kg = unit_cost
            
            if product_info['mj'] == 'ks' and product_info.get('vaha_balenia_g') and product_info['vaha_balenia_g'] > 0:
                price_per_kg = (unit_cost * 1000) / float(product_info['vaha_balenia_g'])

            diff_value_eur = diff_kg * price_per_kg

            log_entry = (datetime.now(), ean, product_info['nazov_vyrobku'], product_info['predajna_kategoria'], system_qty_kg, real_qty_kg, diff_kg, diff_value_eur, worker_name)
            differences_to_log.append(log_entry)
            updates_to_produkty.append((real_qty_kg, ean))

    if differences_to_log:
        db_connector.execute_query(
            """INSERT INTO inventurne_rozdiely_produkty 
               (datum, ean_produktu, nazov_produktu, predajna_kategoria, systemovy_stav_kg, realny_stav_kg, rozdiel_kg, hodnota_rozdielu_eur, pracovnik) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            differences_to_log, fetch='none', multi=True
        )
    if updates_to_produkty:
        db_connector.execute_query(
            "UPDATE produkty SET aktualny_sklad_finalny_kg = %s WHERE ean = %s",
            updates_to_produkty, fetch='none', multi=True
        )
    
    return {"message": f"Inventúra finálnych produktov dokončená. Aktualizovaných {len(updates_to_produkty)} položiek."}

def get_traceability_info(batch_id):
    """
    Získa všetky dostupné informácie o výrobnej šarži pre účely sledovateľnosti.
    """
    if not batch_id:
        return {"error": "Chýba ID šarže."}

    batch_info_query = """
        SELECT 
            zv.id_davky, zv.nazov_vyrobku, zv.stav,
            zv.datum_vyroby, zv.datum_spustenia, zv.datum_ukoncenia,
            zv.planovane_mnozstvo_kg, zv.realne_mnozstvo_kg, zv.realne_mnozstvo_ks,
            p.mj, p.ean
        FROM zaznamy_vyroba zv
        LEFT JOIN produkty p ON zv.nazov_vyrobku = p.nazov_vyrobku
        WHERE zv.id_davky = %s
    """
    batch_info = db_connector.execute_query(batch_info_query, (batch_id,), fetch='one')

    if not batch_info:
        return {"error": f"Šarža s ID '{batch_id}' nebola nájdená."}

    ingredients_query = """
        SELECT nazov_suroviny, pouzite_mnozstvo_kg
        FROM zaznamy_vyroba_suroviny
        WHERE id_davky = %s
        ORDER BY pouzite_mnozstvo_kg DESC
    """
    ingredients = db_connector.execute_query(ingredients_query, (batch_id,))

    return {
        "batch_info": batch_info,
        "ingredients": ingredients
    }

