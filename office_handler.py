import db_connector
from datetime import datetime, timedelta
import math
import re 
import json
from flask import render_template, make_response, request
import production_handler 
import notification_handler
import b2b_handler  # Potrebný pre hashovanie hesla pri schvaľovaní

# =================================================================
# === POMOCNÉ ===
# =================================================================
# --- util: bezpečný text pre logy ---
def txt(value):
    return "" if value is None else str(value)

def _ym_int(year, month):
    try:
        return int(year), int(month)
    except (TypeError, ValueError):
        return None, None
def _parse_num(x):
    if x is None: return None
    try: return float(str(x).replace(',', '.').strip())
    except: return None

# =================================================================
# === FUNKCIE PRE DASHBOARD A HLAVNÉ MENU KANCELÁRIE ===
# =================================================================

def get_kancelaria_dashboard_data():
    """
    Získa komplexné dáta pre hlavný dashboard v kancelárii, vrátane akcií a stavov skladov.
    """
    # 1. Výrobné suroviny pod minimom
    low_stock_raw_query = """
        SELECT nazov as name, mnozstvo as quantity, min_zasoba as minStock 
        FROM sklad 
        WHERE mnozstvo < min_zasoba AND min_zasoba > 0 
        ORDER BY nazov
    """
    low_stock_raw = db_connector.execute_query(low_stock_raw_query)

    # 2. Expedičný tovar pod minimom (DB používa 'produkt' – podporíme aj legacy prefixy)
    low_stock_goods_query = """
        SELECT
            nazov_vyrobku, predajna_kategoria, aktualny_sklad_finalny_kg,
            minimalna_zasoba_kg, minimalna_zasoba_ks, mj, vaha_balenia_g, typ_polozky
        FROM produkty
        WHERE typ_polozky = 'produkt' OR typ_polozky LIKE 'VÝROBOK%%' OR typ_polozky LIKE 'TOVAR%%'
    """
    all_goods = db_connector.execute_query(low_stock_goods_query) or []
    
    low_stock_goods_list = []
    for p in all_goods:
        stock_kg = float(p.get('aktualny_sklad_finalny_kg') or 0.0)
        min_stock_kg = float(p.get('minimalna_zasoba_kg') or 0.0)
        min_stock_ks = float(p.get('minimalna_zasoba_ks') or 0.0)
        mj = p.get('mj')
        weight_g = float(p.get('vaha_balenia_g') or 0.0)

        is_below_min = False
        current_stock_display, min_stock_display = "", ""

        if mj == 'ks':
            current_stock_ks = math.floor((stock_kg * 1000) / weight_g) if weight_g > 0 else 0
            if min_stock_ks > 0 and current_stock_ks < min_stock_ks:
                is_below_min = True
            current_stock_display = f"{current_stock_ks} ks"
            min_stock_display = f"{int(min_stock_ks)} ks"
        else:
            if min_stock_kg > 0 and stock_kg < min_stock_kg:
                is_below_min = True
            current_stock_display = f"{stock_kg:.2f} kg"
            min_stock_display = f"{min_stock_kg:.2f} kg"

        if is_below_min:
            low_stock_goods_list.append({
                "name": p['nazov_vyrobku'],
                "category": p.get('predajna_kategoria') or 'Nezaradené',
                "currentStock": current_stock_display,
                "minStock": min_stock_display
            })
    
    low_stock_goods_categorized = {}
    for item in low_stock_goods_list:
        category = item['category']
        low_stock_goods_categorized.setdefault(category, []).append(item)

    # 3. Aktívne marketingové akcie
    active_promos_query = """
        SELECT promo.product_name, promo.sale_price_net, promo.end_date, chain.name as chain_name
        FROM b2b_promotions promo
        JOIN b2b_retail_chains chain ON promo.chain_id = chain.id
        WHERE CURDATE() BETWEEN promo.start_date AND promo.end_date
        ORDER BY chain.name, promo.product_name
    """
    active_promos = db_connector.execute_query(active_promos_query)

    # 4. TOP 5 produktov a graf výroby
    top_products_query = """
        SELECT p.nazov_vyrobku as name, SUM(zv.realne_mnozstvo_kg) as total
        FROM zaznamy_vyroba zv 
        JOIN produkty p ON zv.nazov_vyrobku = p.nazov_vyrobku
        WHERE zv.datum_ukoncenia >= CURDATE() - INTERVAL 30 DAY 
          AND zv.stav IN ('Ukončené','Dokončené') 
          AND zv.realne_mnozstvo_kg > 0
        GROUP BY p.nazov_vyrobku 
        ORDER BY total DESC 
        LIMIT 5
    """
    production_timeseries_query = """
        SELECT DATE_FORMAT(datum_ukoncenia, '%%Y-%%m-%%d') as production_date, SUM(realne_mnozstvo_kg) as total_kg
        FROM zaznamy_vyroba 
        WHERE datum_ukoncenia >= CURDATE() - INTERVAL 30 DAY 
          AND stav IN ('Ukončené','Dokončené')
        GROUP BY production_date 
        ORDER BY production_date ASC
    """
    
    return {
        "lowStockRaw": low_stock_raw,
        "lowStockGoods": low_stock_goods_categorized,
        "activePromotions": active_promos,
        "topProducts": db_connector.execute_query(top_products_query),
        "timeSeriesData": db_connector.execute_query(production_timeseries_query)
    }

def get_kancelaria_base_data():
    """Získa základné dáta potrebné pre rôzne moduly v kancelárii."""
    products_without_recipe_q = """
        SELECT nazov_vyrobku FROM produkty 
        WHERE (typ_polozky = 'produkt' OR TRIM(UPPER(typ_polozky)) LIKE 'VÝROBOK%%')
          AND nazov_vyrobku NOT IN (SELECT DISTINCT nazov_vyrobku FROM recepty) 
        ORDER BY nazov_vyrobku
    """
    products_list = db_connector.execute_query(products_without_recipe_q) or []
    
    categories_q = """
        SELECT DISTINCT kategoria_pre_recepty 
        FROM produkty 
        WHERE kategoria_pre_recepty IS NOT NULL AND kategoria_pre_recepty != '' 
        ORDER BY kategoria_pre_recepty
    """
    categories_list = db_connector.execute_query(categories_q) or []
    
    return {
        'warehouse': production_handler.get_warehouse_state(), 
        'itemTypes': ['Mäso', 'Koreniny', 'Obaly - Črevá', 'Pomocný material'],
        'productsWithoutRecipe': [p['nazov_vyrobku'] for p in products_list],
        'recipeCategories': [c['kategoria_pre_recepty'] for c in categories_list]
    }

# =================================================================
# === EXPEDIČNÝ PLÁN A AKCIE ===
# =================================================================

def get_7_day_order_forecast():
    """Zostaví 7-dňový prehľad objednávok."""
    start_date = datetime.now().date()
    dates = [(start_date + timedelta(days=i)) for i in range(7)]
    date_str_list = [d.strftime('%Y-%m-%d') for d in dates]
    end_date = dates[-1]

    orders_query = """
        SELECT
            p.nazov_vyrobku, p.ean, p.aktualny_sklad_finalny_kg,
            p.mj, p.vaha_balenia_g, p.typ_polozky, p.predajna_kategoria,
            obj.pozadovany_datum_dodania, pol.mnozstvo
        FROM b2b_objednavky_polozky pol
        JOIN b2b_objednavky obj ON pol.objednavka_id = obj.id
        JOIN produkty p ON pol.ean_produktu = p.ean
        WHERE DATE(obj.pozadovany_datum_dodania) BETWEEN %s AND %s
    """
    all_orders = db_connector.execute_query(orders_query, (start_date, end_date)) or []

    forecast_data = {}
    for order in all_orders:
        product_name = order['nazov_vyrobku']
        delivery_date_str = order['pozadovany_datum_dodania'].strftime('%Y-%m-%d')

        if product_name not in forecast_data:
            stock_kg = float(order.get('aktualny_sklad_finalny_kg') or 0.0)
            mj = order.get('mj')
            weight_g = float(order.get('vaha_balenia_g') or 0.0)
            
            stock_raw = math.floor((stock_kg * 1000) / weight_g) if mj == 'ks' and weight_g > 0 else stock_kg
            stock_display = f"{int(stock_raw)} ks" if mj == 'ks' else f"{stock_raw:.2f} kg"

            forecast_data[product_name] = {
                'name': product_name, 'category': order.get('predajna_kategoria') or 'Nezaradené',
                'stock_display': stock_display, 'stock_raw': stock_raw, 'mj': mj,
                'isManufacturable': (order.get('typ_polozky') or '').lower() == 'produkt' or (order.get('typ_polozky') or '').upper().startswith('VÝROBOK'),
                'daily_needs': {d_str: 0 for d_str in date_str_list}, 'total_needed': 0
            }

        qty = float(order.get('mnozstvo') or 0)
        if delivery_date_str in forecast_data[product_name]['daily_needs']:
            forecast_data[product_name]['daily_needs'][delivery_date_str] += qty
            forecast_data[product_name]['total_needed'] += qty
    
    for product in forecast_data.values():
        product['deficit'] = product['total_needed'] - product['stock_raw']
        
    forecast_by_category = {}
    for product in sorted(forecast_data.values(), key=lambda x: x['name']):
        category = product['category']
        forecast_by_category.setdefault(category, []).append(product)

    return { "dates": date_str_list, "forecast": forecast_by_category }

def get_goods_purchase_suggestion():
    """Vypočíta návrh nákupu pre tovarové položky."""
    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=7)
    reserved_query = """
        SELECT p.ean, SUM(pol.mnozstvo) as reserved_qty 
        FROM b2b_objednavky_polozky pol 
        JOIN b2b_objednavky obj ON pol.objednavka_id = obj.id 
        JOIN produkty p ON pol.ean_produktu = p.ean 
        WHERE DATE(obj.pozadovany_datum_dodania) BETWEEN %s AND %s 
          AND (p.typ_polozky = 'produkt' OR p.typ_polozky LIKE 'TOVAR%%')
        GROUP BY p.ean
    """
    reserved_items = db_connector.execute_query(reserved_query, (start_date, end_date)) or []
    reserved_map = {item['ean']: float(item['reserved_qty']) for item in reserved_items}
    goods_query = """
        SELECT ean, nazov_vyrobku, aktualny_sklad_finalny_kg, minimalna_zasoba_kg, mj 
        FROM produkty 
        WHERE (typ_polozky = 'produkt' OR typ_polozky LIKE 'TOVAR%%') 
        ORDER BY nazov_vyrobku
    """
    all_goods = db_connector.execute_query(goods_query) or []
    active_promos_query = "SELECT product_ean FROM b2b_promotions WHERE CURDATE() BETWEEN start_date AND end_date"
    active_promos = {p['product_ean'] for p in db_connector.execute_query(active_promos_query) or []}
    suggestions = []
    for item in all_goods:
        stock = float(item.get('aktualny_sklad_finalny_kg') or 0)
        min_stock = float(item.get('minimalna_zasoba_kg') or 0)
        reserved = reserved_map.get(item['ean'], 0)
        deficit = (min_stock + reserved) - stock
        if deficit > 0:
            suggestions.append({
                "name": item['nazov_vyrobku'], "stock": stock, "min_stock": min_stock,
                "reserved": reserved, "suggestion": math.ceil(deficit),
                "unit": item.get('mj', 'kg'), "is_promo": item['ean'] in active_promos
            })
    return suggestions

def get_promotions_data():
    """Získa dáta pre správu akcií."""
    chains = db_connector.execute_query("SELECT * FROM b2b_retail_chains ORDER BY name")
    promos = db_connector.execute_query("""
        SELECT p.*, c.name as chain_name 
        FROM b2b_promotions p 
        JOIN b2b_retail_chains c ON p.chain_id = c.id 
        ORDER BY p.start_date DESC
    """)
    products = db_connector.execute_query("""
        SELECT ean, nazov_vyrobku as name 
        FROM produkty 
        WHERE typ_polozky = 'produkt' OR typ_polozky LIKE 'TOVAR%%' 
        ORDER BY name
    """)
    return {"chains": chains, "promotions": promos, "products": products}

def manage_promotion_chain(data):
    """Pridá alebo vymaže obchodný reťazec."""
    action = data.get('action')
    if action == 'add':
        name = data.get('name')
        if not name: return {"error": "Názov reťazca je povinný."}
        try:
            db_connector.execute_query("INSERT INTO b2b_retail_chains (name) VALUES (%s)", (name,), fetch='none')
            return {"message": "Reťazec pridaný."}
        except Exception: 
            return {"error": "Reťazec s týmto názvom už pravdepodobne existuje."}
    elif action == 'delete':
        chain_id = data.get('id')
        if not chain_id: return {"error": "Chýba ID reťazca."}
        db_connector.execute_query("DELETE FROM b2b_retail_chains WHERE id = %s", (chain_id,), fetch='none')
        return {"message": "Reťazec vymazaný."}
    return {"error": "Neznáma akcia."}

def save_promotion(data):
    """Uloží novú marketingovú akciu."""
    required = ['chain_id', 'ean', 'start_date', 'end_date', 'sale_price_net']
    if not all(field in data and data[field] for field in required): 
        return {"error": "Chýbajú povinné údaje."}
    product_info = db_connector.execute_query("SELECT nazov_vyrobku FROM produkty WHERE ean = %s", (data['ean'],), fetch='one')
    if not product_info: 
        return {"error": "Produkt s daným EAN nebol nájdený."}
    params = (
        data['chain_id'], data['ean'], product_info['nazov_vyrobku'], 
        data['start_date'], data['end_date'], data.get('delivery_start_date') or None, 
        float(data['sale_price_net'])
    )
    # DB: používame column 'product_ean' (nie generovaný alias 'ean')
    db_connector.execute_query(
        "INSERT INTO b2b_promotions (chain_id, product_ean, product_name, start_date, end_date, delivery_start_date, sale_price_net) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
        params, fetch='none'
    )
    return {"message": "Akcia bola úspešne uložená."}

def delete_promotion(data):
    """Vymaže akciu."""
    promo_id = data.get('id')
    if not promo_id: return {"error": "Chýba ID akcie."}
    db_connector.execute_query("DELETE FROM b2b_promotions WHERE id = %s", (promo_id,), fetch='none')
    return {"message": "Akcia bola vymazaná."}

def create_urgent_production_task(data):
    """Vytvorí jednu urgentnú výrobnú úlohu priamo z expedičného plánu."""
    product_name, quantity, production_date = data.get('productName'), data.get('quantity'), data.get('productionDate')
    if not all([product_name, quantity, production_date]): return {"error": "Chýbajú povinné údaje."}
    try:
        if float(quantity) <= 0: return {"error": "Množstvo musí byť kladné číslo."}
    except (ValueError, TypeError): return {"error": "Neplatný formát množstva."}
    safe_name = re.sub(r'[^a-zA-Z0-9]', '', product_name)[:10]
    batch_id = f"URGENT-{safe_name}-{datetime.now().strftime('%y%m%d%H%M%S%f')}"
    task_data = (batch_id, 'Automaticky naplánované', production_date, product_name, float(quantity), 'URGENT - z Expedičného Plánu')
    db_connector.execute_query("INSERT INTO zaznamy_vyroba (id_davky, stav, datum_vyroby, nazov_vyrobku, planovane_mnozstvo_kg, poznamka_expedicie) VALUES (%s, %s, %s, %s, %s, %s)", task_data, fetch='none')
    return {"message": f"Urgentná výrobná úloha pre '{product_name}' bola úspešne vytvorená."}

# =================================================================
# === SKLAD – PREHĽADY PODĽA POŽIADAVKY ===
# =================================================================
def get_raw_material_stock_overview():
    """
    Prehľad výrobného skladu: sklad_vyroba JOIN sklad.
    Frontend (stock.js) očakáva polia: nazov, quantity, typ, podtyp.
    """
    sql = """
        SELECT 
            sv.nazov,
            COALESCE(sv.mnozstvo, 0)            AS quantity,
            LOWER(COALESCE(s.typ, ''))         AS typ,
            LOWER(COALESCE(s.podtyp, ''))      AS podtyp
        FROM sklad_vyroba sv
        LEFT JOIN sklad s ON s.nazov = sv.nazov
        ORDER BY sv.nazov
    """
    rows = db_connector.execute_query(sql) or []
    items = []
    for r in rows:
        items.append({
            "nazov":    r["nazov"],
            "quantity": float(r["quantity"] or 0),
            "typ":      r["typ"] or "",
            "podtyp":   r["podtyp"] or "",
        })
    return {"items": items}


# === SKLAD – PREHĽAD SUROVÍN (iba výrobný sklad) ===
def get_production_stock_overview():
    """
    Prehľad výrobného skladu: sklad_vyroba JOIN sklad.
    Vrátime jasnú kategóriu 'cat' ∈ {'maso','koreniny','obal','pomocny_material','nezaradene'}.
    ŽIADNA 'surovina'.
    """
    sql = """
        SELECT 
            sv.nazov,
            COALESCE(sv.mnozstvo, 0) AS mnozstvo,
            LOWER(COALESCE(s.typ, ''))    AS typ,
            LOWER(COALESCE(s.podtyp, '')) AS podtyp
        FROM sklad_vyroba sv
        LEFT JOIN sklad s ON s.nazov = sv.nazov
        ORDER BY sv.nazov
    """
    rows = db_connector.execute_query(sql) or []

    def resolve_cat(typ, podtyp):
        t = (typ or '').lower()
        p = (podtyp or '').lower()
        if t in ('maso','mäso') or p == 'maso':
            return 'maso'
        if t == 'koreniny' or p == 'koreniny':
            return 'koreniny'
        if t == 'obal':
            return 'obal'
        if t == 'pomocny_material':
            return 'pomocny_material'
        return 'nezaradene'

    items = []
    for r in rows:
        cat = resolve_cat(r['typ'], r['podtyp'])
        items.append({
            "nazov": r["nazov"],
            "mnozstvo": float(r["mnozstvo"]),
            "typ": r["typ"],
            "podtyp": r["podtyp"],
            "cat": cat
        })
    return {"items": items}


# === SKLAD – VÝROBNÝ PRÍJEM (so zdrojom), podporuje viac položiek naraz ===
def receive_production_stock(payload):
    """
    Príjem na výrobný sklad – podporuje viac položiek naraz.
    POZOR: príjem je povolený LEN na existujúce karty v `sklad`.
    payload = {
      "items": [
        {
          "category": "maso" | "koreniny" | "obal" | "pomocny_material",
          "source": "rozrabka" | "expedicia" | "externy" | "ine",   # pre category='maso'
          # "supplier_id": int,                                     # pre iné kategórie, ak chceš evidovať
          "name": "...",
          "quantity": 10.5,
          "price": 2.95,   # voliteľné – ak sa uvedie, prepočíta sa vážený priemer v `sklad.nakupna_cena`
          "note": "text",
          "date": "YYYY-MM-DD HH:MM[:SS]"  # voliteľné
        }, ...
      ]
    }
    """
    if not isinstance(payload, dict):
      return {"error": "Neplatné dáta."}
    items = payload.get('items') or []
    if not items:
      return {"error": "Žiadne položky na príjem."}

    conn = db_connector.get_connection()
    try:
      cur = conn.cursor()

      for it in items:
        category = (it.get('category') or '').strip().lower()
        name     = (it.get('name') or '').strip()
        qty      = float(it.get('quantity') or 0)
        price    = it.get('price', None)
        note     = (it.get('note') or '').strip()
        dt_str   = it.get('date')
        when     = dt_str if dt_str else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not name:
          return {"error": "Položka bez názvu."}
        if qty <= 0:
          return {"error": f"Nevyhovujúce množstvo pre '{name}'."}

        # Mäso – validácia zdroja
        prijem_typ = None
        if category in ('maso','mäso'):
          src = (it.get('source') or '').strip().lower()
          if src not in ('rozrabka','expedicia','externy','ine'):
            return {"error": f"Pre '{name}' (mäso) zvoľ Zdroj: rozrabka / expedicia / externy / ine."}
          prijem_typ = src
        else:
          # ostatné kategórie – ak chceš, tu môžeš zaradiť 'dodavatel'
          prijem_typ = 'dodavatel'

        # 1) karta v `sklad` MUSÍ existovať (nezakladáme ju pri príjme!)
        cur.execute("SELECT COALESCE(mnozstvo,0), COALESCE(nakupna_cena,0) FROM sklad WHERE nazov=%s FOR UPDATE", (name,))
        row = cur.fetchone()
        if row is None:
          return {"error": f"Položka '{name}' nie je založená v sklade. Najskôr ju vytvor cez 'Pridať položku do výrobného skladu'."}
        central_qty, current_avg = float(row[0] or 0), float(row[1] or 0)

        # 2) vezmi aktuálnu zásobu vo výrobnom sklade (na váženie)
        cur.execute("SELECT COALESCE(mnozstvo,0) FROM sklad_vyroba WHERE nazov=%s FOR UPDATE", (name,))
        r2 = cur.fetchone()
        prod_qty = float(r2[0]) if r2 is not None else 0.0

        # 3) vážený priemer v `sklad.nakupna_cena` len ak máme price
        if price is not None:
          total_before = central_qty + prod_qty
          new_total = total_before + qty
          new_avg = (current_avg * total_before + float(price) * qty) / new_total if new_total > 0 else float(price)
          cur.execute("UPDATE sklad SET nakupna_cena=%s WHERE nazov=%s", (new_avg, name))

        # 4) navýš výrobný sklad
        cur.execute("""
          INSERT INTO sklad_vyroba (nazov, mnozstvo) VALUES (%s, %s)
          ON DUPLICATE KEY UPDATE mnozstvo = mnozstvo + VALUES(mnozstvo)
        """, (name, qty))

        # 5) log do prijmov – typ = zdroj (mäso), inak 'dodavatel'
        cur.execute("""
          INSERT INTO zaznamy_prijem (datum, nazov_suroviny, mnozstvo_kg, nakupna_cena_eur_kg, typ, poznamka_dodavatel)
          VALUES (%s, %s, %s, %s, %s, %s)
        """, (when, name, qty, price if price is not None else None, prijem_typ, note))

      conn.commit()
      return {"message": f"Prijatých {len(items)} položiek do výrobného skladu."}
    except Exception:
      if conn: conn.rollback()
      raise
    finally:
      if conn and conn.is_connected(): conn.close()

# === SKLAD – vytvorenie novej položky priamo z prehľadu (s EAN + počiatočné množstvo do výrobného skladu) ===
def create_production_item(data):
    if not isinstance(data, dict): return {"error": "Neplatné dáta."}
    name = (data.get('name') or '').strip()
    if not name: return {"error": "Názov je povinný."}
    qty   = float(data.get('quantity') or 0.0)
    if qty < 0: return {"error": "Množstvo musí byť >= 0."}
    price = data.get('price', None)
    typ   = _normalize_category(data.get('category') or '')
    ean   = (data.get('ean') or '').strip()

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT nazov FROM sklad WHERE nazov=%s", (name,))
        exists = cur.fetchone() is not None

        if not exists:
            cur.execute("""
                INSERT INTO sklad (nazov, typ, mnozstvo, nakupna_cena, min_zasoba)
                VALUES (%s, %s, 0, %s, 0)
            """, (name, typ, price if price is not None else None))
        else:
            if price is not None:
                cur.execute("UPDATE sklad SET typ=%s, nakupna_cena=%s WHERE nazov=%s", (typ, price, name))
            else:
                cur.execute("UPDATE sklad SET typ=%s WHERE nazov=%s", (typ, name))

        if qty and qty != 0:
            cur.execute("""
                INSERT INTO sklad_vyroba (nazov, mnozstvo)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE mnozstvo = mnozstvo + VALUES(mnozstvo)
            """, (name, qty))
            cur.execute("""
                INSERT INTO zaznamy_prijem (datum, nazov_suroviny, mnozstvo_kg, nakupna_cena_eur_kg, typ, poznamka_dodavatel)
                VALUES (NOW(), %s, %s, %s, %s, %s)
            """, (name, qty, price if price is not None else None, 'prijem', typ))

        if ean:
            try:
                cur.execute("""
                    INSERT INTO katalog_produktov (ean, nazov_vyrobku, mj, kategoria_pre_recepty, typ_polozky)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE nazov_vyrobku=VALUES(nazov_vyrobku),
                                            kategoria_pre_recepty=VALUES(kategoria_pre_recepty),
                                            typ_polozky=VALUES(typ_polozky)
                """, (ean, name, ('ks' if typ=='obal' else 'kg'), typ, typ))
            except Exception:
                pass

        conn.commit()
        return {"message": f"Položka '{name}' bola pridaná do výrobného skladu.", "created": True}
    except Exception:
        if conn: conn.rollback()
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()
def update_production_item_qty(data=None):
    """
    Nastaví absolútne množstvo (kg) pre položku vo výrobnom sklade.
    Ak `data` nepríde, načíta sa z request.get_json().
    Očakáva JSON: { "name": "...", "quantity": float }
    """
    if data is None:
        data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"error": "Neplatné dáta."}

    name = (data.get("name") or "").strip()
    if not name:
        return {"error": "Názov je povinný."}

    try:
        qty = float(data.get("quantity", 0))
        if qty < 0:
            return {"error": "Množstvo musí byť >= 0."}
    except Exception:
        return {"error": "Neplatné množstvo."}

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT mnozstvo FROM sklad_vyroba WHERE nazov=%s", (name,))
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO sklad_vyroba (nazov, mnozstvo) VALUES (%s, %s)", (name, qty))
        else:
            cur.execute("UPDATE sklad_vyroba SET mnozstvo=%s WHERE nazov=%s", (qty, name))
        conn.commit()
        return {"ok": True}
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()

def delete_production_item(data=None):
    """
    Zmaže položku zo `sklad_vyroba`. Ak `data` nepríde cez handle_request,
    načíta sa z request.get_json().
    Očakáva JSON: { "name": "..." }
    """
    if data is None:
        data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"error": "Neplatné dáta."}

    name = (data.get("name") or "").strip()
    if not name:
        return {"error": "Názov je povinný."}

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sklad_vyroba WHERE nazov=%s", (name,))
        conn.commit()
        return {"ok": True}
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()


def get_comprehensive_stock_view():
    """Celkový prehľad skladu: vráť produkty zoskupené podľa predajnej kategórie; len centrálny sklad (2)."""
    q = """
        SELECT 
            p.ean, p.nazov_vyrobku AS name, p.predajna_kategoria AS category,
            p.aktualny_sklad_finalny_kg AS stock_kg, p.vaha_balenia_g, p.mj AS unit,
            (
              SELECT ROUND(zv.celkova_cena_surovin / NULLIF(zv.realne_mnozstvo_kg, 0), 4)
              FROM zaznamy_vyroba zv
              WHERE zv.nazov_vyrobku = p.nazov_vyrobku
                AND zv.stav IN ('Ukončené','Dokončené')
                AND zv.celkova_cena_surovin IS NOT NULL
                AND zv.realne_mnozstvo_kg IS NOT NULL
              ORDER BY COALESCE(zv.datum_ukoncenia, zv.datum_vyroby) DESC
              LIMIT 1
            ) AS price
        FROM produkty p
        WHERE p.typ_polozky = 'produkt' OR p.typ_polozky LIKE 'VÝROBOK%%' OR p.typ_polozky LIKE 'TOVAR%%'
        ORDER BY category, name
    """
    rows = db_connector.execute_query(q) or []

    grouped = {}
    flat = []
    for p in rows:
        unit = p.get('unit') or 'kg'
        qty_kg = float(p.get('stock_kg') or 0.0)
        w = float(p.get('vaha_balenia_g') or 0.0)
        qty = (qty_kg * 1000 / w) if unit == 'ks' and w > 0 else qty_kg
        item = {
            "ean": p['ean'], "name": p['name'],
            "category": p.get('category') or 'Nezaradené',
            "quantity": qty, "unit": unit,
            "price": float(p.get('price') or 0.0),
            "sklad1": 0.0, "sklad2": qty_kg
        }
        flat.append(item)
        grouped.setdefault(item['category'], []).append(item)

    return {"products": flat, "groupedByCategory": grouped}
# =========================
# Dodávatelia – CRUD a helpery (vložiť do office_handler.py)
# =========================

from datetime import datetime

ALLOWED_SUPPLIER_CATEGORIES = {"koreniny", "obal", "pomocny_material"}

def _normalize_category(cat: str) -> str:
    c = (cat or '').strip().lower()
    if c in ('mäso','maso','meat'): return 'maso'
    if c.startswith('koren'):       return 'koreniny'
    if c.startswith('obal'):        return 'obal'
    if c.startswith('pomoc'):       return 'pomocny_material'
    return 'surovina'  # fallback


def _ensure_suppliers_tables():
    ddl_suppliers = """
    CREATE TABLE IF NOT EXISTS suppliers (
      id INT AUTO_INCREMENT PRIMARY KEY,
      name VARCHAR(255) NOT NULL UNIQUE,
      phone VARCHAR(50),
      email VARCHAR(255),
      address TEXT,
      is_active TINYINT NOT NULL DEFAULT 1,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    ddl_cats = """
    CREATE TABLE IF NOT EXISTS supplier_categories (
      supplier_id INT NOT NULL,
      category ENUM('koreniny','obal','pomocny_material') NOT NULL,
      PRIMARY KEY (supplier_id, category),
      CONSTRAINT fk_supplier_categories_supplier
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(ddl_suppliers)
        cur.execute(ddl_cats)
        conn.commit()
    finally:
        if conn and conn.is_connected():
            conn.close()

def list_suppliers(category: str | None = None):
    """
    GET zoznam dodávateľov. Voliteľne filter podľa kategórie (?category=koreniny|obal|pomocny_material).
    Vracia: {"items":[{"id":..,"name":"..","phone":"..","email":"..","address":"..","categories":[...]},...]}
    """
    _ensure_suppliers_tables()
    params = []
    if category:
        cat = _normalize_category(category)
        if cat not in ALLOWED_SUPPLIER_CATEGORIES:
            return {"items": []}
        sql = """
          SELECT s.id, s.name, s.phone, s.email, s.address, s.is_active,
                 GROUP_CONCAT(sc.category ORDER BY sc.category) AS cats
          FROM suppliers s
          JOIN supplier_categories sc ON sc.supplier_id = s.id
          WHERE s.is_active = 1 AND sc.category = %s
          GROUP BY s.id
          ORDER BY s.name
        """
        params = [cat]
    else:
        sql = """
          SELECT s.id, s.name, s.phone, s.email, s.address, s.is_active,
                 GROUP_CONCAT(sc.category ORDER BY sc.category) AS cats
          FROM suppliers s
          LEFT JOIN supplier_categories sc ON sc.supplier_id = s.id
          WHERE s.is_active = 1
          GROUP BY s.id
          ORDER BY s.name
        """
    rows = db_connector.execute_query(sql, tuple(params)) or []
    items = []
    for r in rows:
        cats = (r.get("cats") or "")
        items.append({
            "id": r["id"],
            "name": r["name"],
            "phone": r.get("phone"),
            "email": r.get("email"),
            "address": r.get("address"),
            "is_active": int(r.get("is_active") or 0),
            "categories": [c for c in cats.split(",") if c]
        })
    return {"items": items}

def create_supplier(data: dict):
    """
    POST nový dodávateľ:
      {"name":"...", "phone":"...", "email":"...", "address":"...", "categories":["koreniny","obal",...]}
    """
    _ensure_suppliers_tables()
    name = (data.get("name") or "").strip()
    if not name:
        return {"error": "Názov je povinný."}
    phone = (data.get("phone") or "").strip() or None
    email = (data.get("email") or "").strip() or None
    address = (data.get("address") or "").strip() or None
    cats_in = data.get("categories") or []
    cats = []
    for c in cats_in:
        nc = _normalize_category(c)
        if nc in ALLOWED_SUPPLIER_CATEGORIES and nc not in cats:
            cats.append(nc)

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        # duplicitny názov?
        cur.execute("SELECT id FROM suppliers WHERE name=%s", (name,))
        if cur.fetchone():
            return {"error": "Dodávateľ s týmto názvom už existuje."}
        cur.execute(
            "INSERT INTO suppliers (name, phone, email, address, is_active) VALUES (%s,%s,%s,%s,1)",
            (name, phone, email, address)
        )
        supplier_id = cur.lastrowid
        if cats:
            cur.executemany(
                "INSERT INTO supplier_categories (supplier_id, category) VALUES (%s,%s)",
                [(supplier_id, c) for c in cats]
            )
        conn.commit()
        return {"message": "Dodávateľ pridaný.", "id": supplier_id}
    except Exception:
        if conn: conn.rollback()
        raise
    finally:
        if conn and conn.is_connected(): conn.close()

def update_supplier(data: dict):
    """
    PUT update dodávateľa:
      {"id":123, "name":"...", "phone":"...", "email":"...", "address":"...", "is_active":1/0, "categories":[...]}
    """
    _ensure_suppliers_tables()
    sid = data.get("id")
    if not sid:
        return {"error": "Chýba ID dodávateľa."}
    name = (data.get("name") or "").strip()
    if not name:
        return {"error": "Názov je povinný."}
    phone = (data.get("phone") or "").strip() or None
    email = (data.get("email") or "").strip() or None
    address = (data.get("address") or "").strip() or None
    is_active = 1 if bool(data.get("is_active", 1)) else 0
    cats_in = data.get("categories") or []
    cats = []
    for c in cats_in:
        nc = _normalize_category(c)
        if nc in ALLOWED_SUPPLIER_CATEGORIES and nc not in cats:
            cats.append(nc)

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE suppliers SET name=%s, phone=%s, email=%s, address=%s, is_active=%s WHERE id=%s",
                    (name, phone, email, address, is_active, sid))
        # refresh categories
        cur.execute("DELETE FROM supplier_categories WHERE supplier_id=%s", (sid,))
        if cats:
            cur.executemany(
                "INSERT INTO supplier_categories (supplier_id, category) VALUES (%s,%s)",
                [(sid, c) for c in cats]
            )
        conn.commit()
        return {"message": "Dodávateľ upravený."}
    except Exception:
        if conn: conn.rollback()
        raise
    finally:
        if conn and conn.is_connected(): conn.close()

def delete_supplier(supplier_id: int):
    """DELETE dodávateľa – kaskádovo sa zmažú aj kategórie."""
    _ensure_suppliers_tables()
    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM suppliers WHERE id=%s", (supplier_id,))
        conn.commit()
        return {"message": "Dodávateľ zmazaný."}
    except Exception:
        if conn: conn.rollback()
        raise
    finally:
        if conn and conn.is_connected(): conn.close()

# =================================================================
# === PLÁNOVANIE A ERP ===
# =================================================================
def receive_production_stock(data):
    items = (data or {}).get("items") or []
    if not items: return {"error": "Žiadne položky na príjem."}
    now = datetime.now()
    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        for it in items:
            name = (it.get("name") or "").strip()
            typ  = (it.get("type") or "surovina").strip()
            qty  = float(it.get("quantity") or 0)
            price= it.get("price", None)
            note = (it.get("note") or "").strip()
            if not name or qty <= 0: return {"error": f"Neplatná položka '{name}'."}
            # ensure in central register
            cur.execute("INSERT IGNORE INTO sklad (nazov, typ, mnozstvo, nakupna_cena, min_zasoba) VALUES (%s,%s,%s,%s,%s)",
                        (name, typ, 0, price if price is not None else None, 0))
            # increment production store
            cur.execute("INSERT INTO sklad_vyroba (nazov, mnozstvo) VALUES (%s,%s) ON DUPLICATE KEY UPDATE mnozstvo = mnozstvo + VALUES(mnozstvo)", (name, qty))
            # log receipt
            cur.execute("INSERT INTO zaznamy_prijem (datum, nazov_suroviny, mnozstvo_kg, nakupna_cena_eur_kg, typ, poznamka_dodavatel) VALUES (%s,%s,%s,%s,%s,%s)",
                        (now, name, qty, price if price is not None else None, 'vyroba', note))
        conn.commit()
        return {"message": f"Prijaté do výrobného skladu: {len(items)} položiek."}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected(): conn.close()

def transfer_to_production(data, user=None):
    items = (data or {}).get("items") or []
    if not items: return {"error":"Žiadne položky na presun."}
    operator = (user or {}).get("full_name") or "Systém"
    now = datetime.now()
    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        for it in items:
            name = (it.get("name") or "").strip()
            qty  = float(it.get("quantity") or 0)
            note = (it.get("note") or "")
            if not name or qty <= 0: return {"error": f"Neplatná položka '{name}'."}
            # check central qty
            row = db_connector.execute_query("SELECT mnozstvo, nakupna_cena FROM sklad WHERE nazov=%s", (name,), 'one')
            if not row: return {"error": f"Položka '{name}' neexistuje v centrálnom sklade."}
            current = float(row.get('mnozstvo') or 0)
            if current < qty: return {"error": f"Nedostatok na sklade pre '{name}'. K dispozícii {current:.3f} kg."}
            # dec central
            cur.execute("UPDATE sklad SET mnozstvo = mnozstvo - %s WHERE nazov=%s", (qty, name))
            # inc production
            cur.execute("INSERT INTO sklad_vyroba (nazov, mnozstvo) VALUES (%s,%s) ON DUPLICATE KEY UPDATE mnozstvo = mnozstvo + VALUES(mnozstvo)", (name, qty))
            # logs: central issue + production receipt
            cur.execute("INSERT INTO vydajky (datum, pracovnik, nazov, mnozstvo, poznamka) VALUES (%s,%s,%s,%s,%s)",
                        (now, operator, name, qty, f"Presun do Sklad 1. {note}".strip()))
            cur.execute("INSERT INTO zaznamy_prijem (datum, nazov_suroviny, mnozstvo_kg, nakupna_cena_eur_kg, typ, poznamka_dodavatel) VALUES (%s,%s,%s,%s,%s,%s)",
                        (now, name, qty, row.get('nakupna_cena'), 'transfer', f"Z Sklad 2. {note}".strip()))
        conn.commit()
        return {"message": f"Presunuté na výrobu: {len(items)} položiek."}
    except Exception:
        if conn: conn.rollback()
        raise
    finally:
        if conn and conn.is_connected(): conn.close()

def calculate_production_plan():
    """Vypočíta inteligentný plán výroby."""
    end_date = datetime.now() + timedelta(days=7)
    orders_query = """
        SELECT pol.ean_produktu, SUM(pol.mnozstvo) as total_ordered_qty 
        FROM b2b_objednavky obj 
        JOIN b2b_objednavky_polozky pol ON obj.id = pol.objednavka_id 
        WHERE obj.pozadovany_datum_dodania BETWEEN CURDATE() AND %s 
        GROUP BY pol.ean_produktu
    """
    ordered_items = db_connector.execute_query(orders_query, (end_date.strftime('%Y-%m-%d'),)) or []
    ordered_map = {item['ean_produktu']: float(item['total_ordered_qty']) for item in ordered_items}
    products_query = """
        SELECT ean, nazov_vyrobku, kategoria_pre_recepty, aktualny_sklad_finalny_kg, minimalna_zasoba_kg, vyrobna_davka_kg 
        FROM produkty 
        WHERE (typ_polozky = 'produkt' OR TRIM(UPPER(typ_polozky)) LIKE 'VÝROBOK%%')
          AND (minimalna_zasoba_kg > 0 OR ean IN (SELECT DISTINCT ean_produktu FROM b2b_objednavky_polozky))
    """
    products_to_plan = db_connector.execute_query(products_query) or []
    plan = []
    for p in products_to_plan:
        sklad = float(p.get('aktualny_sklad_finalny_kg') or 0.0)
        min_zasoba = float(p.get('minimalna_zasoba_kg') or 0.0)
        dopyt = ordered_map.get(p['ean'], 0.0)
        celkova_potreba = dopyt + min_zasoba
        potrebne_vyrobit = celkova_potreba - sklad
        if potrebne_vyrobit > 0:
            davka = float(p.get('vyrobna_davka_kg') or 50.0) or 50.0
            navrhovana_vyroba = math.ceil(potrebne_vyrobit / davka) * davka
            plan.append({
                "nazov_vyrobku": p['nazov_vyrobku'], 
                "kategoria": p.get('kategoria_pre_recepty') or 'Nezaradené', 
                "aktualny_sklad": sklad, 
                "celkova_potreba": celkova_potreba, 
                "navrhovana_vyroba": navrhovana_vyroba
            })
    plan_grouped = {}
    for item in plan:
        plan_grouped.setdefault(item['kategoria'], []).append(item)
    return plan_grouped

def create_production_tasks_from_plan(plan):
    """Vytvorí výrobné úlohy z týždenného plánu."""
    if not plan: return {"message": "Plán je prázdny."}
    existing_q = "SELECT id_davky FROM zaznamy_vyroba WHERE stav = 'Automaticky naplánované'"
    existing_tasks = {t['id_davky'] for t in db_connector.execute_query(existing_q) or []}
    tasks_to_create = []
    for item in plan:
        product_name, production_date = item.get('nazov_vyrobku'), item.get('datum_vyroby')
        safe_name = re.sub(r'[^a-zA-Z0-9]', '', product_name)[:10]
        batch_id = f"AUTO-{safe_name}-{datetime.now().strftime('%y%m%d%H%M%S%f')}"
        if batch_id not in existing_tasks:
            task = (batch_id, 'Automaticky naplánované', production_date, product_name, item.get('navrhovana_vyroba'), 'Priorita' if item.get('priorita') else '')
            tasks_to_create.append(task)
            existing_tasks.add(batch_id)
    if not tasks_to_create: 
        return {"message": "Všetky položky už majú úlohu."}
    db_connector.execute_query(
        "INSERT INTO zaznamy_vyroba (id_davky, stav, datum_vyroby, nazov_vyrobku, planovane_mnozstvo_kg, poznamka_expedicie) VALUES (%s, %s, %s, %s, %s, %s)", 
        tasks_to_create, 'none', True
    )
    return {"message": f"Vytvorených {len(tasks_to_create)} nových úloh."}

def get_purchase_suggestions():
    """Vygeneruje návrh na nákup surovín."""
    plan_flat = [item for sublist in calculate_production_plan().values() for item in sublist]
    warehouse_map = {item['name']: {'quantity': float(item.get('quantity') or 0.0), 'minStock': float(item.get('minStock') or 0.0)} for item in production_handler.get_warehouse_state()['all']}
    total_requirements = {}
    for item in plan_flat:
        if item['navrhovana_vyroba'] > 0:
            ingredients_result = production_handler.calculate_required_ingredients(item['nazov_vyrobku'], item['navrhovana_vyroba'])
            if 'data' in ingredients_result:
                for ing in ingredients_result['data']:
                    if ing['name'] not in ['Ľad', 'Voda', 'Ovar']:
                        total_requirements[ing['name']] = total_requirements.get(ing['name'], 0) + float(ing['required'])
    suggestions = []
    for name, required_qty in total_requirements.items():
        stock_item = warehouse_map.get(name)
        if stock_item:
            projected_stock, min_stock = stock_item['quantity'] - required_qty, stock_item.get('minStock', 0.0)
            if projected_stock < min_stock:
                purchase_qty = min_stock - projected_stock
                suggestions.append({"name": name, "currentStock": stock_item['quantity'], "requiredForProduction": required_qty, "minStock": min_stock, "purchaseQty": purchase_qty})
    for name, stock_item in warehouse_map.items():
        if not any(s['name'] == name for s in suggestions) and stock_item['quantity'] < stock_item.get('minStock', 0.0):
            purchase_qty = stock_item.get('minStock', 0.0) - stock_item['quantity']
            if purchase_qty > 0: suggestions.append({"name": name, "currentStock": stock_item['quantity'], "requiredForProduction": 0, "minStock": stock_item.get('minStock', 0.0), "purchaseQty": purchase_qty})
    return sorted(suggestions, key=lambda x: x['name'])

# =================================================================
# === FUNKCIE PRE ADMINISTRÁCIU ERP SYSTÉMU (SPRÁVA KATALÓGU) ===
# =================================================================

def add_new_stock_item(data):
    """Pridá novú surovinu do skladu."""
    name, item_type, price = data.get('name'), data.get('type'), data.get('price')
    if not name or not item_type: return {"error": "Názov a typ sú povinné."}
    if db_connector.execute_query("SELECT nazov FROM sklad WHERE nazov = %s", (name,), fetch='one'): return {"error": f"Surovina '{name}' už existuje."}
    db_connector.execute_query("INSERT INTO sklad (nazov, typ, mnozstvo, nakupna_cena, min_zasoba) VALUES (%s, %s, 0, %s, 0)", (name, item_type, float(price or 0.0)), fetch='none')
    return {"message": f"Surovina '{name}' pridaná."}

def get_catalog_management_data():
    """Získa dáta pre správu centrálneho katalógu."""
    products_query = "SELECT ean, nazov_vyrobku, typ_polozky, kategoria_pre_recepty, predajna_kategoria, dph FROM produkty ORDER BY typ_polozky, nazov_vyrobku"
    # Legacy typy v UI ponecháme, DB používa 'produkt'
    item_types = ['VÝROBOK', 'VÝROBOK_KRAJANY', 'VÝROBOK_KUSOVY', 'TOVAR', 'TOVAR_KUSOVY']
    dph_rates = [5.00, 10.00, 19.00, 23.00]
    sale_categories = ['Výrobky', 'Bravčové mäso chladené', 'Bravčové mäso mrazené', 'Hovädzie mäso chladené', 'Hovädzie mäso mrazené', 'Hydinové mäso chladené', 'Hydinové mäso mrazené', 'Ryby mrazené', 'Zelenina', 'Tovar']
    recipe_cat_query = "SELECT DISTINCT kategoria_pre_recepty FROM produkty WHERE kategoria_pre_recepty IS NOT NULL AND kategoria_pre_recepty != '' ORDER BY 1"
    recipe_categories = [r['kategoria_pre_recepty'] for r in db_connector.execute_query(recipe_cat_query) or []]
    return {"products": db_connector.execute_query(products_query), "recipe_categories": recipe_categories, "sale_categories": sale_categories, "item_types": item_types, "dph_rates": dph_rates}

def add_catalog_item(data):
    """Pridá novú položku do katalógu."""
    ean, name, item_type, dph = data.get('new_catalog_ean'), data.get('new_catalog_name'), data.get('new_catalog_item_type'), data.get('new_catalog_dph')
    if not all([ean, name, item_type, dph]): return {"error": "EAN, Názov, Typ a DPH sú povinné."}
    if db_connector.execute_query("SELECT ean FROM produkty WHERE ean = %s", (ean,), fetch='one'): return {"error": f"EAN '{ean}' už existuje."}
    if db_connector.execute_query("SELECT ean FROM produkty WHERE nazov_vyrobku = %s", (name,), fetch='one'): return {"error": f"Názov '{name}' už existuje."}
    mj = 'ks' if item_type in ['VÝROBOK_KRAJANY', 'VÝROBOK_KUSOVY', 'TOVAR_KUSOVY'] else 'kg'
    # DB: ukladaj 'produkt' ako typ_polozky
    params = (ean, name, 'produkt', data.get('new_catalog_recipe_category') or None, data.get('new_catalog_sale_category') or None, dph, mj)
    db_connector.execute_query("INSERT INTO produkty (ean, nazov_vyrobku, typ_polozky, kategoria_pre_recepty, predajna_kategoria, dph, mj) VALUES (%s, %s, %s, %s, %s, %s, %s)", params, fetch='none')
    return {"message": f"Položka '{name}' pridaná."}

def update_catalog_item(data):
    """Aktualizuje položku v katalógu."""
    ean = data.get('ean')
    if not ean: return {"error": "Chýba EAN."}
    # typ_polozky držíme v DB ako 'produkt'
    typ = data.get('typ_polozky') if data.get('typ_polozky') == 'produkt' else 'produkt'
    params = (data.get('nazov_vyrobku'), typ, data.get('kategoria_pre_recepty') or None, data.get('predajna_kategoria') or None, float(data.get('dph', 0)), ean)
    db_connector.execute_query("UPDATE produkty SET nazov_vyrobku = %s, typ_polozky = %s, kategoria_pre_recepty = %s, predajna_kategoria = %s, dph = %s WHERE ean = %s", params, fetch='none')
    return {"message": f"Položka {ean} aktualizovaná."}

def delete_catalog_item(data):
    """Vymaže položku z katalógu."""
    ean = data.get('ean')
    if not ean: return {"error": "Chýba EAN."}
    if db_connector.execute_query("SELECT id FROM recepty WHERE nazov_vyrobku = (SELECT nazov_vyrobku FROM produkty WHERE ean = %s)", (ean,), fetch='one'): return {"error": "Nemožno vymazať, je použitá v recepte."}
    if db_connector.execute_query("SELECT ean FROM produkty WHERE zdrojovy_ean = %s", (ean,), fetch='one'): return {"error": "Nemožno vymazať, je zdrojom pre krájanie."}
    db_connector.execute_query("DELETE FROM produkty WHERE ean = %s", (ean,), fetch='none')
    return {"message": f"Položka {ean} vymazaná."}

def add_new_recipe(recipe_data):
    product_name = (recipe_data or {}).get('productName')
    ingredients = (recipe_data or {}).get('ingredients') or []
    category = ((recipe_data or {}).get('newCategory') or '').strip() or (recipe_data or {}).get('category')
    if not product_name or not category:
        return {"error": "Chýba produkt alebo kategória."}
    rows_to_insert = []
    for ing in ingredients:
        name = (ing or {}).get('name')
        qty = _parse_num((ing or {}).get('quantity'))
        if name and qty and qty > 0:
            rows_to_insert.append((product_name, name, qty))
    if not rows_to_insert:
        return {"error": "Recept musí obsahovať aspoň jednu platnú surovinu."}

    exists = db_connector.execute_query(
        "SELECT 1 FROM recepty WHERE TRIM(nazov_vyrobku)=TRIM(%s) LIMIT 1", (product_name,), fetch='one'
    )
    if exists: return {"error": f"Recept pre '{product_name}' už existuje."}

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO recepty (nazov_vyrobku, nazov_suroviny, mnozstvo_na_davku_kg) VALUES (%s,%s,%s)",
            rows_to_insert
        )
        cur.execute("UPDATE produkty SET kategoria_pre_recepty=%s WHERE TRIM(nazov_vyrobku)=TRIM(%s)",
                    (category, product_name))
        conn.commit()
        return {"message": f"Recept pre '{product_name}' bol vytvorený."}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected(): conn.close()

def get_allowed_raw_names(category: str):
    """
    Filter názvov podľa 4 kategórií (bez 'surovina').
    Fallback berie aj starý zápis typ='surovina' + podtyp=('maso'|'koreniny').
    Výstup: {"items":[{"name":"...", "last_price": 2.95},...], "names":[...]}
    """
    c = (category or '').strip().lower()
    if c in ('mäso','maso','meat'):
        where = "LOWER(s.typ) IN ('mäso','maso') OR (s.typ='surovina' AND LOWER(s.podtyp)='maso')"
    elif c.startswith('koren'):
        where = "LOWER(s.typ)='koreniny' OR (s.typ='surovina' AND LOWER(s.podtyp)='koreniny')"
    elif c.startswith('obal'):
        where = "LOWER(s.typ)='obal'"
    elif c.startswith('pomoc'):
        where = "LOWER(s.typ)='pomocny_material'"
    else:
        return {"items": [], "names": []}

    sql = f"""
        SELECT s.nazov AS name,
               (SELECT z.nakupna_cena_eur_kg
                  FROM zaznamy_prijem z
                 WHERE z.nazov_suroviny = s.nazov
                   AND z.nakupna_cena_eur_kg IS NOT NULL
                 ORDER BY z.datum DESC
                 LIMIT 1) AS last_price
          FROM sklad s
         WHERE {where}
         ORDER BY s.nazov
    """
    rows = db_connector.execute_query(sql) or []
    items = [{"name": r["name"], "last_price": (float(r["last_price"]) if r["last_price"] is not None else None)}
             for r in rows]
    return {"items": items, "names": [it["name"] for it in items]}


def get_all_recipes_for_editing():
    q = """
      SELECT p.nazov_vyrobku, p.kategoria_pre_recepty
        FROM produkty p
        JOIN (SELECT DISTINCT TRIM(nazov_vyrobku) AS nazov_vyrobku FROM recepty) r
          ON TRIM(p.nazov_vyrobku) = r.nazov_vyrobku
       WHERE p.typ_polozky LIKE 'VÝROBOK%%'
       ORDER BY p.kategoria_pre_recepty, p.nazov_vyrobku
    """
    rows = db_connector.execute_query(q) or []
    out = {}
    for r in rows:
        cat = r.get('kategoria_pre_recepty') or 'Nezaradené'
        out.setdefault(cat, []).append(r['nazov_vyrobku'])
    return out

def get_recipe_details(product_name: str):
    if not product_name: return {"error": "Chýba názov produktu."}
    prod = db_connector.execute_query(
        "SELECT kategoria_pre_recepty FROM produkty WHERE TRIM(nazov_vyrobku)=TRIM(%s)",
        (product_name,), fetch='one'
    ) or {}
    category = prod.get('kategoria_pre_recepty')
    ingredients_q = """
        SELECT r.nazov_suroviny AS name,
               r.mnozstvo_na_davku_kg AS quantity,
               s.kategoria AS category,
               (SELECT z.nakupna_cena_eur_kg
                  FROM zaznamy_prijem z
                 WHERE z.nazov_suroviny = r.nazov_suroviny
                   AND z.nakupna_cena_eur_kg IS NOT NULL
                 ORDER BY z.datum DESC
                 LIMIT 1) AS last_price,
               s.is_infinite_stock,
               s.default_cena_eur_kg
          FROM recepty r
          LEFT JOIN sklad s ON s.nazov = r.nazov_suroviny
         WHERE TRIM(r.nazov_vyrobku)=TRIM(%s)
         ORDER BY r.nazov_suroviny
    """
    ing = db_connector.execute_query(ingredients_q, (product_name,)) or []
    ingredients = []
    for i in ing:
        price = i["last_price"]
        if price is None: price = i["default_cena_eur_kg"]
        if price is None and int(i.get("is_infinite_stock") or 0) == 1: price = 0.20
        ingredients.append({
            "name": i["name"],
            "category": i["category"],
            "quantity": float(i["quantity"]) if i["quantity"] is not None else None,
            "last_price": float(price) if price is not None else None
        })
    return {"productName": product_name, "category": category, "ingredients": ingredients}

def update_recipe(recipe_data):
    product_name = (recipe_data or {}).get('productName')
    ingredients = (recipe_data or {}).get('ingredients') or []
    category = ((recipe_data or {}).get('newCategory') or '').strip() or (recipe_data or {}).get('category')
    if not product_name: return {"error": "Chýba názov produktu."}
    rows_to_insert = []
    for ing in ingredients:
        name = (ing or {}).get('name')
        qty = _parse_num((ing or {}).get('quantity'))
        if name and qty and qty > 0:
            rows_to_insert.append((product_name, name, qty))

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM recepty WHERE TRIM(nazov_vyrobku)=TRIM(%s)", (product_name,))
        if rows_to_insert:
            cur.executemany(
                "INSERT INTO recepty (nazov_vyrobku, nazov_suroviny, mnozstvo_na_davku_kg) VALUES (%s,%s,%s)",
                rows_to_insert
            )
        if category:
            cur.execute("UPDATE produkty SET kategoria_pre_recepty=%s WHERE TRIM(nazov_vyrobku)=TRIM(%s)",
                        (category, product_name))
        conn.commit()
        return {"message": f"Recept pre '{product_name}' bol upravený."}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected(): conn.close()

def delete_recipe(product_name):
    if not product_name: return {"error": "Chýba názov produktu."}
    db_connector.execute_query(
        "DELETE FROM recepty WHERE TRIM(nazov_vyrobku)=TRIM(%s)", (product_name,), fetch='none'
    )
    return {"message": f"Recept pre '{product_name}' vymazaný."}

def get_slicing_management_data():
    """Získa dáta pre správu krájaných produktov s robustnejšími dopytmi."""
    source_query = """
        SELECT ean, nazov_vyrobku as name 
        FROM produkty 
        WHERE (TRIM(UPPER(typ_polozky)) IN ('VÝROBOK', 'VÝROBOK_KUSOVY')) OR typ_polozky='produkt'
        ORDER BY nazov_vyrobku
    """
    target_query = """
        SELECT ean, nazov_vyrobku as name FROM produkty
        WHERE TRIM(UPPER(typ_polozky)) = 'VÝROBOK_KRAJANY'
        AND (zdrojovy_ean IS NULL OR TRIM(zdrojovy_ean) = '' OR zdrojovy_ean = 'nan')
        ORDER BY nazov_vyrobku
    """
    return {"sourceProducts": db_connector.execute_query(source_query), "unlinkedSlicedProducts": db_connector.execute_query(target_query)}

def link_sliced_product(data):
    source_ean, target_ean = data.get('sourceEan'), data.get('targetEan')
    if not source_ean or not target_ean: return {"error": "Chýba EAN."}
    db_connector.execute_query("UPDATE produkty SET zdrojovy_ean = %s WHERE ean = %s", (source_ean, target_ean), fetch='none')
    return {"message": "Produkty prepojené."}

def create_and_link_sliced_product(data):
    """Vytvorí a prepojí nový krájaný produkt."""
    source_ean, new_name, new_ean, new_weight = data.get('sourceEan'), data.get('name'), data.get('ean'), data.get('weight')
    if not all([source_ean, new_name, new_ean, new_weight]): return {"error": "Všetky polia sú povinné."}
    if db_connector.execute_query("SELECT ean FROM produkty WHERE ean = %s", (new_ean,), fetch='one'): return {"error": f"EAN '{new_ean}' už existuje."}
    source_product = db_connector.execute_query("SELECT predajna_kategoria, dph FROM produkty WHERE ean = %s", (source_ean,), fetch='one')
    if not source_product: return {"error": "Zdrojový produkt nebol nájdený."}
    sale_cat, dph_rate = source_product.get('predajna_kategoria', 'Výrobky'), source_product.get('dph', 19.00)
    insert_query = """
        INSERT INTO produkty (ean, nazov_vyrobku, mj, typ_polozky, vaha_balenia_g, zdrojovy_ean, dph, predajna_kategoria) 
        VALUES (%s, %s, 'ks', 'produkt', %s, %s, %s, %s)
    """
    db_connector.execute_query(insert_query, (new_ean, new_name, new_weight, source_ean, dph_rate, sale_cat), fetch='none')
    return {"message": f"Produkt '{new_name}' vytvorený a prepojený."}

def get_products_for_min_stock():
    """Načíta finálne produkty pre nastavenie minimálnych zásob."""
    query = """
        SELECT ean, nazov_vyrobku as name, mj, minimalna_zasoba_kg as minStockKg, minimalna_zasoba_ks as minStockKs 
        FROM produkty 
        WHERE typ_polozky='produkt' OR typ_polozky IN ('VÝROBOK','VÝROBOK_KRAJANY','VÝROBOK_KUSOVY')
        ORDER BY nazov_vyrobku
    """
    return db_connector.execute_query(query)

def update_min_stock_levels(products_data):
    """Aktualizuje minimálne zásoby pre zadané produkty."""
    if not products_data: return {"error": "Žiadne dáta na aktualizáciu."}
    updates = [(p.get('minStockKg') if p.get('minStockKg') != '' else None, p.get('minStockKs') if p.get('minStockKs') != '' else None, p.get('ean')) for p in products_data]
    if not updates: return {"error": "Žiadne platné dáta na aktualizáciu."}
    db_connector.execute_query("UPDATE produkty SET minimalna_zasoba_kg = %s, minimalna_zasoba_ks = %s WHERE ean = %s", updates, fetch='none', multi=True)
    return {"message": f"Minimálne zásoby aktualizované pre {len(updates)} produktov."}

# =================================================================
# === FUNKCIE PRE REPORTY A ŠTATISTIKY ===
# =================================================================

def get_production_stats(period, category):
    """Získa štatistiky výroby a škôd za dané obdobie."""
    today = datetime.now()
    if period == 'week': start_date = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'month': start_date = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else: start_date = datetime(1970, 1, 1)
    base_query = """
        SELECT zv.*, p.kategoria_pre_recepty, p.mj as unit 
        FROM zaznamy_vyroba zv 
        LEFT JOIN produkty p ON zv.nazov_vyrobku = p.nazov_vyrobku 
        WHERE zv.stav IN ('Ukončené','Dokončené') AND zv.datum_ukoncenia >= %s
    """
    params = [start_date]
    if category and category != 'Všetky': 
        base_query += " AND p.kategoria_pre_recepty = %s"; params.append(category)
    base_query += " ORDER BY zv.datum_ukoncenia DESC"
    records = db_connector.execute_query(base_query, tuple(params)) or []
    damage_query = """
        SELECT s.*, p.kategoria_pre_recepty, zv.celkova_cena_surovin as naklady_skody 
        FROM skody s 
        LEFT JOIN produkty p ON s.nazov_vyrobku = p.nazov_vyrobku 
        LEFT JOIN zaznamy_vyroba zv ON s.id_davky = zv.id_davky 
        WHERE s.datum >= %s
    """
    damage_params = [start_date]
    if category and category != 'Všetky': 
        damage_query += " AND p.kategoria_pre_recepty = %s"; damage_params.append(category)
    damage_query += " ORDER BY s.datum DESC"
    damage_records = db_connector.execute_query(damage_query, tuple(damage_params)) or []
    for record in records:
        plan_kg, real_kg = float(record.get('planovane_mnozstvo_kg') or 0.0), float(record.get('realne_mnozstvo_kg') or 0.0)
        record['vytaznost'] = ((real_kg / plan_kg) - 1) * 100 if plan_kg > 0 else 0
        unit_cost = float(record.get('cena_za_jednotku') or 0.0)
        # fallback: ak 'cena_za_jednotku' chýba, dopočítaj
        if unit_cost == 0 and float(record.get('realne_mnozstvo_kg') or 0) > 0:
            total_cost = float(record.get('celkova_cena_surovin') or 0.0)
            unit_cost = total_cost / float(record.get('realne_mnozstvo_kg'))
        record['cena_bez_energii'], record['cena_s_energiami'] = unit_cost, unit_cost * 1.15 if unit_cost > 0 else 0.0
    return {'data': records, 'damage_data': damage_records}

def get_receipt_report_html(period, category):
    """Pripraví dáta a vyrenderuje HTML report o príjme surovín pomocou šablóny."""
    today = datetime.now()
    if period == 'day':
        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start_date = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'month':
        start_date = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else: # Fallback pre neočakávanú hodnotu
        start_date = datetime(1970, 1, 1)

    query = """
        SELECT p.datum, p.nazov_suroviny, s.typ, p.mnozstvo_kg, p.nakupna_cena_eur_kg, p.poznamka_dodavatel
        FROM zaznamy_prijem p LEFT JOIN sklad s ON p.nazov_suroviny = s.nazov WHERE p.datum >= %s
    """
    params = [start_date]
    if category and category != 'Všetky':
        query += " AND s.typ = %s"
        params.append(category)
    query += " ORDER BY p.datum DESC, p.nazov_suroviny"
    
    records = db_connector.execute_query(query, tuple(params)) or []
    total_value = sum((float(r.get('mnozstvo_kg') or 0) * float(r.get('nakupna_cena_eur_kg') or 0)) for r in records)
    
    template_data = {
        "title": "Report Príjmu Surovín",
        "report_info": f"Obdobie: {period}, Kategória: {category}",
        "report_date": today.strftime('%d.%m.%Y'),
        "is_receipt_report": True,
        "data": records,
        "total_value": total_value
    }
    return make_response(render_template('report_template.html', **template_data))

def get_inventory_difference_report_html(date_str):
    """Pripraví dáta a vyrenderuje HTML report o inventúrnych rozdieloch pomocou šablóny."""
    if not date_str:
        return make_response("<h1>Chyba: Nebol zadaný dátum pre report.</h1>", 400)
        
    records = db_connector.execute_query("SELECT * FROM inventurne_rozdiely WHERE DATE(datum) = %s ORDER BY nazov_suroviny", (date_str,)) or []
    total_diff_value = sum(float(r.get('hodnota_rozdielu_eur') or 0.0) for r in records)
    
    template_data = {
        "title": "Report Inventúrnych Rozdielov",
        "report_date": datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y'),
        "is_inventory_report": True,
        "data": records,
        "total_diff_value": total_diff_value
    }
    return make_response(render_template('report_template.html', **template_data))

# --- HACCP ---
def get_haccp_docs(): return db_connector.execute_query("SELECT id, nazov as title FROM haccp_dokumenty ORDER BY nazov")

def get_haccp_doc_content(doc_id):
    if not doc_id: return {"error": "Chýba ID dokumentu."}
    return db_connector.execute_query("SELECT id, nazov as title, obsah as content FROM haccp_dokumenty WHERE id = %s", (doc_id,), fetch='one')

def save_haccp_doc(data):
    doc_id, title, content = data.get('id'), data.get('title'), data.get('content')
    if not title: return {"error": "Názov je povinný."}
    if doc_id:
        db_connector.execute_query("UPDATE haccp_dokumenty SET nazov = %s, obsah = %s WHERE id = %s", (title, content, doc_id), fetch='none')
        return {"message": "Dokument aktualizovaný.", "updated_id": doc_id}
    else:
        new_id = db_connector.execute_query("INSERT INTO haccp_dokumenty (nazov, obsah) VALUES (%s, %s)", (title, content), fetch='lastrowid')
        return {"message": "Nový dokument vytvorený.", "new_id": new_id}

# =================================================================
# === B2B ADMINISTRÁCIA (upravené na textové zakaznik_id) ===
# =================================================================

def get_pending_b2b_registrations():
    return db_connector.execute_query("""
        SELECT id, nazov_firmy, adresa, adresa_dorucenia, email, telefon, datum_registracie 
        FROM b2b_zakaznici 
        WHERE je_schvaleny = 0 AND typ = 'B2B' 
        ORDER BY datum_registracie DESC
    """)

def approve_b2b_registration(data):
    reg_id, customer_id = data.get('id'), data.get('customerId')
    if not reg_id or not customer_id: return {"error": "Chýba ID registrácie alebo ID odberateľa."}
    if db_connector.execute_query("SELECT id FROM b2b_zakaznici WHERE zakaznik_id = %s", (customer_id,), fetch='one'):
        return {"error": f"Zákaznícke číslo '{customer_id}' už je pridelené."}
    db_connector.execute_query("UPDATE b2b_zakaznici SET je_schvaleny = 1, zakaznik_id = %s WHERE id = %s", (customer_id, reg_id), fetch='none')
    customer_info = db_connector.execute_query("SELECT email, nazov_firmy FROM b2b_zakaznici WHERE id = %s", (reg_id,), fetch='one')
    if customer_info:
        try:
            notification_handler.send_approval_email(customer_info['email'], customer_info['nazov_firmy'], customer_id)
        except Exception:
            print(f"--- VAROVANIE: Registrácia pre {customer_info['nazov_firmy']} bola schválená, ale e-mail sa nepodarilo odoslať. ---")
    return {"message": "Registrácia bola schválená a notifikácia odoslaná."}

def reject_b2b_registration(data):
    rows_deleted = db_connector.execute_query("DELETE FROM b2b_zakaznici WHERE id = %s AND je_schvaleny = 0", (data.get('id'),), fetch='none')
    return {"message": "Registrácia bola odmietnutá."} if rows_deleted > 0 else {"error": "Registráciu sa nepodarilo nájsť."}

def get_customers_and_pricelists():
    customers_q = """
        SELECT z.id, z.zakaznik_id, z.nazov_firmy, z.email, z.telefon, z.adresa, z.adresa_dorucenia, GROUP_CONCAT(zc.cennik_id) as cennik_ids 
        FROM b2b_zakaznici z 
        LEFT JOIN b2b_zakaznik_cennik zc ON z.zakaznik_id = zc.zakaznik_id 
        WHERE z.je_admin = 0 AND z.typ = 'B2B' 
        GROUP BY z.id
    """
    pricelists_q = "SELECT id, nazov_cennika FROM b2b_cenniky ORDER BY nazov_cennika"
    return {"customers": db_connector.execute_query(customers_q), "pricelists": db_connector.execute_query(pricelists_q)}

def update_customer_details(data):
    customer_id, name, email, phone, pricelist_ids = data.get('id'), data.get('nazov_firmy'), data.get('email'), data.get('telefon'), data.get('pricelist_ids', [])
    address = data.get('adresa')
    delivery_address = data.get('adresa_dorucenia')
    # z id -> textové zakaznik_id
    zak_row = db_connector.execute_query("SELECT zakaznik_id FROM b2b_zakaznici WHERE id=%s", (customer_id,), 'one')
    if not zak_row: return {"error": "Zákazník neexistuje."}
    zak_login = zak_row['zakaznik_id']
    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE b2b_zakaznici SET nazov_firmy = %s, email = %s, telefon = %s, adresa = %s, adresa_dorucenia = %s WHERE id = %s", (name, email, phone, address, delivery_address, customer_id))
        cursor.execute("DELETE FROM b2b_zakaznik_cennik WHERE zakaznik_id = %s", (zak_login,))
        if pricelist_ids:
            upsert_sql = """
                INSERT INTO b2b_zakaznik_cennik (zakaznik_id, cennik_id) VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE cennik_id = VALUES(cennik_id)
            """
            cursor.executemany(upsert_sql, [(zak_login, pid) for pid in dict.fromkeys(pricelist_ids)])
        conn.commit()
        return {"message": "Údaje zákazníka boli aktualizované."}
    except Exception as e:
        if conn: conn.rollback(); raise e
    finally:
        if conn and conn.is_connected(): conn.close()

def get_pricelists_and_products():
    pricelists = db_connector.execute_query("SELECT id, nazov_cennika FROM b2b_cenniky ORDER BY nazov_cennika")
    products = db_connector.execute_query("""
        SELECT ean, nazov_vyrobku as name, predajna_kategoria, dph 
        FROM produkty 
        WHERE typ_polozky='produkt' OR typ_polozky LIKE 'VÝROBOK%%' OR typ_polozky LIKE 'TOVAR%%' 
        ORDER BY predajna_kategoria, nazov_vyrobku
    """)
    products_by_category = {}
    for p in products or []:
        category = p.get('predajna_kategoria') or 'Nezaradené'
        products_by_category.setdefault(category, []).append(p)
    return {"pricelists": pricelists, "productsByCategory": products_by_category}

def create_pricelist(data):
    name = data.get('name')
    if not name: return {"error": "Názov cenníka je povinný."}
    try:
        new_id = db_connector.execute_query("INSERT INTO b2b_cenniky (nazov_cennika) VALUES (%s)", (name,), fetch='lastrowid')
        return {"message": f"Cenník '{name}' bol vytvorený.", "newPricelist": {"id": new_id, "nazov_cennika": name}}
    except Exception as e:
        if 'UNIQUE' in str(e) or 'Duplicate entry' in str(e): return {"error": "Cenník s týmto názvom už existuje."}
        raise e

def get_pricelist_details(data):
    return {"items": db_connector.execute_query("SELECT ean_produktu, cena FROM b2b_cennik_polozky WHERE cennik_id = %s", (data.get('id'),))}

def update_pricelist(data):
    pricelist_id, items = data.get('id'), data.get('items', [])
    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM b2b_cennik_polozky WHERE cennik_id = %s", (pricelist_id,))
        if items:
            items_to_insert = [(pricelist_id, i['ean'], i['price']) for i in items if i.get('price')]
            if items_to_insert:
                cursor.executemany("INSERT INTO b2b_cennik_polozky (cennik_id, ean_produktu, cena) VALUES (%s, %s, %s)", items_to_insert)
        conn.commit()
        return {"message": "Cenník bol aktualizovaný."}
    except Exception as e:
        if conn: conn.rollback(); raise e
    finally:
        if conn and conn.is_connected(): conn.close()

def get_announcement():
    result = db_connector.execute_query("SELECT hodnota FROM b2b_nastavenia WHERE kluc = 'oznam'", fetch='one')
    return {"announcement": result['hodnota'] if result else ""}

def save_announcement(data):
    announcement_text = data.get('announcement', '')
    query = """
        INSERT INTO b2b_nastavenia (kluc, hodnota) VALUES ('oznam', %s) AS new 
        ON DUPLICATE KEY UPDATE hodnota = new.hodnota
    """
    db_connector.execute_query(query, (announcement_text,), fetch='none')
    return {"message": "Oznam bol úspešne aktualizovaný."}

def get_all_b2b_orders(filters):
    """Získa všetky B2B objednávky pre administrátorský prehľad, s možnosťou filtrovania."""
    start_date = filters.get('startDate') or '1970-01-01'
    end_date = filters.get('endDate') or '2999-12-31'
    query = """
        SELECT o.*, z.nazov_firmy 
        FROM b2b_objednavky o
        JOIN b2b_zakaznici z ON o.zakaznik_id = z.zakaznik_id
        WHERE DATE(o.pozadovany_datum_dodania) BETWEEN %s AND %s
        ORDER BY o.pozadovany_datum_dodania DESC, o.datum_objednavky DESC
    """
    orders = db_connector.execute_query(query, (start_date, end_date))
    return {"orders": orders}

def get_b2b_order_details(order_id):
    """Získa detail jednej konkrétnej objednávky pre zobrazenie v administrácii."""
    if not order_id: return {"error": "Chýba ID objednávky."}
    
    order_q = """
        SELECT o.*, z.nazov_firmy, z.zakaznik_id as customerLoginId, z.adresa as customerAddress
        FROM b2b_objednavky o
        JOIN b2b_zakaznici z ON o.zakaznik_id = z.zakaznik_id
        WHERE o.id = %s
    """
    order = db_connector.execute_query(order_q, (order_id,), fetch='one')
    if not order: return {"error": "Objednávka nebola nájdená."}

    items_q = """
        SELECT ean_produktu, nazov_vyrobku, mnozstvo, cena_bez_dph, mj, dph 
        FROM b2b_objednavky_polozky 
        WHERE objednavka_id = %s
    """
    items = db_connector.execute_query(items_q, (order_id,)) or []

    total_net = sum(float(i.get('cena_bez_dph') or 0) * float(i.get('mnozstvo') or 0) for i in items)

    order_data = {
        'id': order['id'],
        'order_number': order['cislo_objednavky'],
        'deliveryDate': order['pozadovany_datum_dodania'].strftime('%Y-%m-%d') if order.get('pozadovany_datum_dodania') else None,
        'note': order.get('poznamka'),
        'customerName': order['nazov_firmy'],
        'customerLoginId': order['customerLoginId'],
        'customerAddress': order['customerAddress'],
        'order_date': order['datum_objednavky'].strftime('%d.%m.%Y') if order.get('datum_objednavky') else None,
        'totalNet': float(total_net),
        'totalVat': float(order.get('celkova_suma_s_dph') or 0),
        'items': [
            {
                'ean': i['ean_produktu'],
                'name': i['nazov_vyrobku'],
                'quantity': float(i['mnozstvo']),
                'price': float(i['cena_bez_dph'] or 0),
                'unit': i.get('mj') or 'kg',
                'dph': float(i.get('dph') or 0),
                'item_note': None
            } for i in items
        ]
    }
    return order_data

# =================================================================
# === B2C ADMINISTRÁCIA (upravené JOINy, bezpečné ukladanie) ===
# =================================================================

def get_b2c_orders_for_admin():
    """Získa všetky B2C objednávky pre administrátorský prehľad."""
    query = """
        SELECT o.*, z.nazov_firmy as zakaznik_meno
        FROM b2c_objednavky o
        JOIN b2b_zakaznici z ON o.zakaznik_id = z.zakaznik_id
        ORDER BY 
            CASE o.stav
                WHEN 'Prijatá' THEN 1
                WHEN 'Pripravená' THEN 2
                WHEN 'Hotová' THEN 3
                WHEN 'Zrušená' THEN 4
                ELSE 5
            END,
            o.pozadovany_datum_dodania ASC, 
            o.datum_objednavky ASC
    """
    orders = db_connector.execute_query(query)
    return orders

def finalize_b2c_order(data):
    """Finalizuje objednávku – uloží 'Pripravená' a poznámku s finálnou cenou (DB nemá finalné stĺpce)."""
    order_id = data.get('order_id')
    final_price_s_dph_str = data.get('final_price')
    if not all([order_id, final_price_s_dph_str]): return {"error": "Chýba ID objednávky alebo finálna cena."}
    try:
        final_price_s_dph = float(str(final_price_s_dph_str).replace(',', '.'))
        if final_price_s_dph <= 0: return {"error": "Finálna cena musí byť kladné číslo."}
    except (ValueError, TypeError):
        return {"error": "Neplatný formát finálnej ceny."}

    db_connector.execute_query(
        "UPDATE b2c_objednavky SET stav = 'Pripravená', poznamka = CONCAT(IFNULL(poznamka,''), ' | FINAL:', %s, '€') WHERE id = %s",
        (final_price_s_dph, order_id), 'none'
    )
    return {"message": "Objednávka bola finalizovaná ('Pripravená')."}

def credit_b2c_loyalty_points(data):
    """Označí objednávku ako 'Hotová' a pripíše vernostné body z celkovej sumy s DPH."""
    order_id = data.get('order_id')
    if not order_id: return {"error": "Chýba ID objednávky."}
    order = db_connector.execute_query("SELECT * FROM b2c_objednavky WHERE id = %s", (order_id,), 'one')
    if not order: return {"error": "Objednávka nebola nájdená."}
    if order['stav'] != 'Pripravená': return {"error": "Body je možné pripísať len pre objednávku v stave 'Pripravená'."}

    final_price = float(order.get('celkova_suma_s_dph') or 0.0)
    if final_price <= 0: return {"error": "Objednávka nemá evidovanú celkovú cenu."}

    points_to_add = math.floor(final_price)
    # získať textové zakaznik_id (keďže b2c_objednavky ho má v tomto tvare)
    cust_login = order['zakaznik_id']
    db_connector.execute_query(
        "UPDATE b2b_zakaznici SET vernostne_body = vernostne_body + %s WHERE zakaznik_id = %s",
        (points_to_add, cust_login), 'none'
    )
    db_connector.execute_query(
        "UPDATE b2c_objednavky SET stav = 'Hotová' WHERE id = %s",
        (order_id,), 'none'
    )
    return {"message": f"Pripísaných {points_to_add} bodov. Objednávka je 'Hotová'."}

def cancel_b2c_order(data):
    """Zruší B2C objednávku a odošle notifikáciu zákazníkovi."""
    order_id, reason = data.get('order_id'), data.get('reason')
    if not all([order_id, reason]): return {"error": "Chýba ID objednávky alebo dôvod zrušenia."}
    db_connector.execute_query(
        "UPDATE b2c_objednavky SET stav = 'Zrušená', poznamka = CONCAT(IFNULL(poznamka, ''), ' | ZRUŠENÉ: ', %s) WHERE id = %s",
        (reason, order_id), fetch='none'
    )
    order = db_connector.execute_query("SELECT zakaznik_id, cislo_objednavky FROM b2c_objednavky WHERE id = %s", (order_id,), 'one')
    if order:
        customer = db_connector.execute_query("SELECT nazov_firmy, email FROM b2b_zakaznici WHERE zakaznik_id = %s", (order['zakaznik_id'],), 'one')
        if customer:
            try:
                notification_handler.send_b2c_order_cancelled_email(customer['email'], customer['nazov_firmy'], order['cislo_objednavky'], reason)
            except Exception as e:
                print(f"Chyba pri odosielaní notifikácie o zrušení B2C objednávky: {e}")
    return {"message": "Objednávka bola zrušená a zákazník notifikovaný."}

def get_b2c_customers_for_admin():
    """Získa zoznam všetkých B2C zákazníkov."""
    query = "SELECT zakaznik_id, nazov_firmy, email, telefon, adresa, adresa_dorucenia, vernostne_body FROM b2b_zakaznici WHERE typ = 'B2C' ORDER BY nazov_firmy"
    return db_connector.execute_query(query)

def get_b2c_pricelist_for_admin():
    """Získa dáta pre administráciu B2C cenníka."""
    all_products_q = """
        SELECT ean, nazov_vyrobku, predajna_kategoria, dph 
        FROM produkty 
        WHERE typ_polozky='produkt' OR typ_polozky LIKE 'VÝROBOK%%' OR typ_polozky LIKE 'TOVAR%%'
        ORDER BY predajna_kategoria, nazov_vyrobku
    """
    all_products = db_connector.execute_query(all_products_q)
    pricelist_q = """
        SELECT c.ean_produktu, p.nazov_vyrobku, p.dph, c.cena_bez_dph, c.je_v_akcii, c.akciova_cena_bez_dph 
        FROM b2c_cennik_polozky c 
        JOIN produkty p ON c.ean_produktu = p.ean
    """
    pricelist_items = db_connector.execute_query(pricelist_q)
    return {"all_products": all_products, "pricelist": pricelist_items}

def update_b2c_pricelist(data):
    """Vymaže starý B2C cenník a vloží nový."""
    items = data.get('items', [])
    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE b2c_cennik_polozky")
        if items:
            items_to_insert = [
                (i['ean'], float(i.get('price', 0)), bool(i.get('is_akcia', False)), 
                 float(i.get('sale_price')) if i.get('is_akcia') and i.get('sale_price') else None) 
                for i in items
            ]
            query = "INSERT INTO b2c_cennik_polozky (ean_produktu, cena_bez_dph, je_v_akcii, akciova_cena_bez_dph) VALUES (%s, %s, %s, %s)"
            cursor.executemany(query, items_to_insert)
        conn.commit()
        return {"message": "B2C cenník bol aktualizovaný."}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected(): conn.close()

def get_b2c_rewards_for_admin():
    """Získa zoznam všetkých vernostných odmien."""
    query = "SELECT id, nazov_odmeny, potrebne_body, je_aktivna FROM b2c_vernostne_odmeny ORDER BY potrebne_body ASC"
    return db_connector.execute_query(query)

def add_b2c_reward(data):
    """Pridá novú vernostnú odmenu."""
    name, points = data.get('name'), data.get('points')
    if not all([name, points]): return {"error": "Názov a body sú povinné."}
    try:
        if int(points) <= 0: return {"error": "Body musia byť kladné číslo."}
    except (ValueError, TypeError): return {"error": "Neplatný formát bodov."}
    query = "INSERT INTO b2c_vernostne_odmeny (nazov_odmeny, potrebne_body) VALUES (%s, %s)"
    db_connector.execute_query(query, (name, int(points)), fetch='none')
    return {"message": f"Odmena '{name}' pridaná."}

def toggle_b2c_reward_status(data):
    """Aktivuje alebo deaktivuje odmenu."""
    reward_id, current_status = data.get('id'), data.get('status')
    if not reward_id: return {"error": "Chýba ID odmeny."}
    query = "UPDATE b2c_vernostne_odmeny SET je_aktivna = %s WHERE id = %s"
    db_connector.execute_query(query, (not bool(current_status), reward_id), fetch='none')
    return {"message": "Stav odmeny zmenený."}
   
