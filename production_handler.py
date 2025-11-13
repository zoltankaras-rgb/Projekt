import db_connector
from datetime import datetime
import unicodedata
from typing import List, Dict, Any, Tuple, Optional

# Položky, ktoré sa neodpisujú (nekonečný sklad)
INFINITE_STOCK_NAMES = {'Ľad', 'Lad', 'Voda', 'Ovar'}

# ───────────────────────── Pomocné ─────────────────────────

def slugify(value: str) -> str:
    try:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
        value = value.lower().replace(' ', '_').replace('.', '')
        return ''.join(c for c in value if c.isalnum() or c == '_')
    except Exception:
        return "".join(c for c in value if c.isalnum() or c in (' ', '_')).lower().replace(' ', '_')

def _has_col(table: str, col: str) -> bool:
    try:
        r = db_connector.execute_query(
            """
            SELECT 1
              FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = %s
               AND COLUMN_NAME  = %s
             LIMIT 1
            """,
            (table, col),
            fetch='one'
        )
        return bool(r)
    except Exception:
        return False

def _table_exists(table: str) -> bool:
    try:
        r = db_connector.execute_query(
            """
            SELECT 1
              FROM INFORMATION_SCHEMA.TABLES
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = %s
             LIMIT 1
            """,
            (table,),
            fetch='one'
        )
        return bool(r)
    except Exception:
        return False

def _pick_existing_col(table: str, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if _has_col(table, c):
            return c
    return None

def _norm(s: Optional[str]) -> str:
    if not s: return ''
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('ascii')
    return s.strip().lower()

def _category_from_values(cat_raw: Optional[str], name: str) -> str:
    """
    Mapuje na: Mäso | Koreniny | Obaly | Pomocný materiál (heuristika + kategória)
    """
    s = _norm(cat_raw)
    n = _norm(name)

    if s in ('maso', 'mäso', 'meat') or any(k in s for k in ['brav', 'hovad', 'hoväd', 'hydin', 'ryb']):
        return 'Mäso'
    if s.startswith('koren') or 'korenin' in s or any(k in s for k in ['paprik', 'rasc', 'kmín', 'kmin', 'cesnak', 'dusit', 'sol', 'soľ']):
        return 'Koreniny'
    if 'obal' in s or 'cerv' in s or 'črev' in s or 'fóli' in s or 'foli' in s or 'vak' in s or 'siet' in s or 'spag' in s or 'špag' in s:
        return 'Obaly'
    if 'pomoc' in s or 'material' in s or 'materi' in s:
        return 'Pomocný materiál'

    if any(k in n for k in ['brav', 'hovad', 'hoväd', 'kurac', 'mork', 'morč', 'hydin', 'ryb', 'mlet']):
        return 'Mäso'
    if any(k in n for k in ['koren', 'paprik', 'rasc', 'kmin', 'dusit', 'sol', 'soľ', 'cesnak']):
        return 'Koreniny'
    if any(k in n for k in ['obal', 'črev', 'cerv', 'fóli', 'foli', 'vak', 'siet', 'špag', 'spag']):
        return 'Obaly'
    if n in ('voda', 'lad', 'ľad', 'ovar') or 'pomoc' in n:
        return 'Pomocný materiál'
    return 'Pomocný materiál'

def _build_sklad_select_sql() -> str:
    """
    SELECT na sklad – funguje aj bez kategoria/typ/podtyp; vráti aj cenu a min zásobu.
    """
    has_cat  = _has_col('sklad', 'kategoria')
    has_typ  = _has_col('sklad', 'typ')
    has_pod  = _has_col('sklad', 'podtyp')
    has_def  = _has_col('sklad', 'default_cena_eur_kg')
    has_buy  = _has_col('sklad', 'nakupna_cena')
    has_min  = _has_col('sklad', 'min_zasoba')
    has_inf  = _has_col('sklad', 'is_infinite_stock')

    cat_expr = 'kategoria' if has_cat else ('typ' if has_typ else ('podtyp' if has_pod else "' '"))
    price_expr = (
        "COALESCE(default_cena_eur_kg, nakupna_cena, 0)" if (has_def and has_buy)
        else ("COALESCE(default_cena_eur_kg, 0)" if has_def else ("COALESCE(nakupna_cena, 0)" if has_buy else "0"))
    )
    min_expr = "COALESCE(min_zasoba, 0)" if has_min else "0"
    inf_expr = "COALESCE(is_infinite_stock, 0)" if has_inf else "0"

    return f"""
        SELECT
            nazov AS name,
            {cat_expr} AS cat_raw,
            mnozstvo AS quantity,
            {price_expr} AS price,
            {min_expr} AS minStock,
            {inf_expr} AS is_infinite_stock
        FROM sklad
        ORDER BY nazov
    """

def _zv_name_col() -> str:
    """
    V zaznamy_vyroba zistí názov stĺpca s menom výrobku: 'nazov_vyrobu' alebo 'nazov_vyrobku'.
    """
    return 'nazov_vyrobu' if _has_col('zaznamy_vyroba', 'nazov_vyrobu') else 'nazov_vyrobku'

# ───────────────────────── Sklad / Recepty (pre UI) ─────────────────────────

def get_warehouse_state() -> Dict[str, Any]:
    rows = db_connector.execute_query(_build_sklad_select_sql()) or []
    groups: Dict[str, List[Dict[str, Any]]] = {'Mäso': [], 'Koreniny': [], 'Obaly': [], 'Pomocný materiál': []}
    all_items: List[Dict[str, Any]] = []
    for r in rows:
        name = r.get('name')
        quantity = float(r.get('quantity') or 0.0)
        price = float(r.get('price') or 0.0)
        min_stock = float(r.get('minStock') or 0.0)
        is_inf = bool(r.get('is_infinite_stock') or (name in INFINITE_STOCK_NAMES))
        cat = _category_from_values(r.get('cat_raw'), name)
        rec = {'name': name, 'type': cat, 'quantity': quantity, 'price': price, 'minStock': min_stock, 'is_infinite_stock': is_inf}
        groups.setdefault(cat, []).append(rec)
        all_items.append(rec)
    return {
        'Mäso': groups.get('Mäso', []),
        'Koreniny': groups.get('Koreniny', []),
        'Obaly': groups.get('Obaly', []),
        'Pomocný materiál': groups.get('Pomocný materiál', []),
        'all': all_items
    }

def get_categorized_recipes() -> Dict[str, Any]:
    rows = db_connector.execute_query("""
        SELECT p.nazov_vyrobku, p.kategoria_pre_recepty
          FROM produkty p
         WHERE p.typ_polozky LIKE 'VÝROBOK%%'
           AND EXISTS (SELECT 1 FROM recepty r WHERE TRIM(r.nazov_vyrobku)=TRIM(p.nazov_vyrobku) LIMIT 1)
         ORDER BY p.kategoria_pre_recepty, p.nazov_vyrobku
    """) or []
    out: Dict[str, List[str]] = {}
    for r in rows:
        out.setdefault(r.get('kategoria_pre_recepty') or 'Nezaradené', []).append(r['nazov_vyrobku'])
    return {'data': out}

def get_planned_production_tasks_by_category() -> Dict[str, List[Dict[str, Any]]]:
    zv_name = _zv_name_col()
    rows = db_connector.execute_query(f"""
        SELECT
            zv.id_davky AS logId,
            zv.{zv_name} AS productName,
            zv.planovane_mnozstvo_kg AS actualKgQty,
            p.kategoria_pre_recepty AS category
          FROM zaznamy_vyroba zv
          JOIN produkty p ON TRIM(zv.{zv_name})=TRIM(p.nazov_vyrobku)
         WHERE zv.stav='Automaticky naplánované'
           AND p.typ_polozky LIKE 'VÝROBOK%%'
         ORDER BY category, productName
    """) or []
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        cat = r.get('category') or 'Nezaradené'
        r['displayQty'] = f"{float(r['actualKgQty']):.2f} kg"
        out.setdefault(cat, []).append(r)
    return out

def get_running_production_tasks_by_category() -> Dict[str, List[Dict[str, Any]]]:
    zv_name = _zv_name_col()
    rows = db_connector.execute_query(f"""
        SELECT
            zv.id_davky AS logId,
            zv.{zv_name} AS productName,
            zv.planovane_mnozstvo_kg AS plannedKg,
            p.kategoria_pre_recepty AS category
          FROM zaznamy_vyroba zv
          JOIN produkty p ON TRIM(zv.{zv_name})=TRIM(p.nazov_vyrobku)
         WHERE zv.stav='Vo výrobe'
         ORDER BY category, productName
    """) or []
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        cat = r.get('category') or 'Nezaradené'
        r['displayQty'] = f"{float(r['plannedKg']):.2f} kg"
        out.setdefault(cat, []).append(r)
    return out

def get_production_menu_data() -> Dict[str, Any]:
    return {
        'planned_tasks': get_planned_production_tasks_by_category(),
        'running_tasks': get_running_production_tasks_by_category(),
        'warehouse': get_warehouse_state(),
        'recipes': get_categorized_recipes().get('data')
    }

# ───────────────────────── Recepty / Výpočet ─────────────────────────

def find_recipe_data(product_name: str) -> List[Dict[str, Any]]:
    return db_connector.execute_query(
        """
        SELECT nazov_suroviny, mnozstvo_na_davku_kg
          FROM recepty
         WHERE TRIM(nazov_vyrobku)=TRIM(%s)
         ORDER BY nazov_suroviny
        """,
        (product_name,)
    ) or []

def _get_product_batch_size_kg(product_name: str) -> float:
    row = db_connector.execute_query(
        "SELECT vyrobna_davka_kg FROM produkty WHERE TRIM(nazov_vyrobku)=TRIM(%s) LIMIT 1",
        (product_name,), fetch='one'
    ) or {}
    try:
        val = float(row.get('vyrobna_davka_kg') or 0.0)
        return val if val > 0 else 100.0
    except Exception:
        return 100.0

def calculate_required_ingredients(product_name, planned_weight):
    try:
        planned_weight = float(planned_weight or 0)
    except Exception:
        return {"error": "Zadajte platný produkt a množstvo."}
    if not product_name or planned_weight <= 0:
        return {"error": "Zadajte platný produkt a množstvo."}

    recipe_ingredients = find_recipe_data(product_name)
    if not recipe_ingredients:
        return {"error": f'Recept s názvom "{product_name}" nebol nájdený.'}

    batch_kg = _get_product_batch_size_kg(product_name)
    multiplier = planned_weight / batch_kg

    warehouse = get_warehouse_state()
    stock_map = {x['name']: x for x in (warehouse.get('all') or [])}

    out = []
    for ing in recipe_ingredients:
        per_batch = float(ing.get('mnozstvo_na_davku_kg') or 0.0)
        required = per_batch * multiplier
        meta = stock_map.get(ing['nazov_suroviny'], {})
        available = float(meta.get('quantity') or 0.0)
        is_sufficient = (ing['nazov_suroviny'] in INFINITE_STOCK_NAMES) or (available >= required)
        out.append({
            "name": ing['nazov_suroviny'],
            "type": meta.get('type', 'Neznámy'),
            "required": round(required, 3),
            "inStock": round(available, 2),
            "isSufficient": bool(is_sufficient),
        })
    return {"data": out, "batchKg": batch_kg, "multiplier": multiplier}

# ───────────────────────── Štart výroby (TX) ─────────────────────────

def start_production(productName, plannedWeight, productionDate, ingredients, workerName, existingLogId=None, **kwargs):
    if not all([productName, plannedWeight, productionDate, ingredients]):
        return {"error": "Chýbajú povinné údaje pre spustenie výroby."}
    if not existingLogId and not workerName:
        return {"error": "Chýba meno pracovníka pre vytvorenie manuálnej výrobnej úlohy."}

    try:
        planned_weight_val = float(plannedWeight)
    except Exception:
        return {"error": "Neplatné plánované množstvo."}

    try:
        datetime.strptime(productionDate, '%Y-%m-%d')
    except Exception:
        return {"error": "Dátum výroby musí byť vo formáte YYYY-MM-DD."}

    ing_names = [i.get('name') for i in (ingredients or []) if i.get('name')]
    if not ing_names:
        return {"error": "Výroba musí obsahovať aspoň jednu surovinu."}

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor(dictionary=True)

        # LOCK riadkov skladu pre dotknuté suroviny
        placeholders = ','.join(['%s'] * len(ing_names))
        cur.execute(f"SELECT nazov, mnozstvo FROM sklad WHERE nazov IN ({placeholders}) FOR UPDATE", tuple(ing_names))
        _ = cur.fetchall() or []

        # Odpis (nekonečné neodpisujeme)
        updates: List[Tuple[float, str]] = []
        for ing in ingredients:
            nm = ing.get('name')
            qty = float(ing.get('quantity') or 0.0)
            if nm in INFINITE_STOCK_NAMES:
                continue
            updates.append((qty, nm))
        if updates:
            cur.executemany("UPDATE sklad SET mnozstvo = mnozstvo - %s WHERE nazov = %s", updates)

        now = datetime.now()
        zv_name = _zv_name_col()

        if existingLogId:
            batch_id = existingLogId
            # cena dávky (ak sú stĺpce na sklade)
            try:
                cur.execute(f"SELECT nazov, COALESCE(default_cena_eur_kg, nakupna_cena, 0) AS cena FROM sklad WHERE nazov IN ({placeholders})", tuple(ing_names))
                price_map = {r['nazov']: float(r.get('cena') or 0.0) for r in (cur.fetchall() or [])}
                total_cost = sum(float(i.get('quantity') or 0.0) * price_map.get(i.get('name'), 0.0) for i in ingredients)
                cur.execute(
                    """
                    UPDATE zaznamy_vyroba
                       SET stav=%s,
                           datum_vyroby=%s,
                           datum_spustenia=%s,
                           celkova_cena_surovin=%s
                     WHERE id_davky=%s
                    """,
                    ('Vo výrobe', productionDate, now, total_cost, batch_id)
                )
            except Exception:
                cur.execute(
                    """
                    UPDATE zaznamy_vyroba
                       SET stav=%s,
                           datum_vyroby=%s,
                           datum_spustenia=%s
                     WHERE id_davky=%s
                    """,
                    ('Vo výrobe', productionDate, now, batch_id)
                )
            cur.execute("DELETE FROM zaznamy_vyroba_suroviny WHERE id_davky=%s", (batch_id,))
            message = f"Príkaz {batch_id} bol spustený do výroby."
        else:
            safe_product = slugify(productName)[:20]
            safe_worker = slugify(workerName).upper()[:6]
            date_str = datetime.strptime(productionDate, '%Y-%m-%d').strftime('%d%m%y')
            time_str = now.strftime('%H%M')
            batch_id = f"{safe_product}-{safe_worker}-{date_str}-{time_str}-{int(planned_weight_val)}"
            try:
                cur.execute(f"SELECT nazov, COALESCE(default_cena_eur_kg, nakupna_cena, 0) AS cena FROM sklad WHERE nazov IN ({placeholders})", tuple(ing_names))
                price_map = {r['nazov']: float(r.get('cena') or 0.0) for r in (cur.fetchall() or [])}
                total_cost = sum(float(i.get('quantity') or 0.0) * price_map.get(i.get('name'), 0.0) for i in ingredients)
                cur.execute(
                    f"""
                    INSERT INTO zaznamy_vyroba
                        (id_davky, stav, datum_vyroby, {zv_name}, planovane_mnozstvo_kg, datum_spustenia, celkova_cena_surovin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (batch_id, 'Vo výrobe', productionDate, productName, planned_weight_val, now, total_cost)
                )
            except Exception:
                cur.execute(
                    f"""
                    INSERT INTO zaznamy_vyroba
                        (id_davky, stav, datum_vyroby, {zv_name}, planovane_mnozstvo_kg, datum_spustenia)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (batch_id, 'Vo výrobe', productionDate, productName, planned_weight_val, now)
                )
            message = f"VÝROBA SPUSTENÁ! Šarža: {batch_id}."

        # Zapíš použité suroviny
        to_log = [(batch_id, i['name'], float(i['quantity'])) for i in ingredients if i.get('name') and float(i.get('quantity') or 0) > 0]
        if to_log:
            cur.executemany(
                "INSERT INTO zaznamy_vyroba_suroviny (id_davky, nazov_suroviny, pouzite_mnozstvo_kg) VALUES (%s,%s,%s)",
                to_log
            )

        conn.commit()
        return {"message": message}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected(): conn.close()

# ───────────────────────── Inventúra / Výdaj ─────────────────────────

def update_inventory(inventory_data):
    if not inventory_data:
        return {"error": "Neboli zadané žiadne platné reálne stavy."}
    updates = []
    for item in inventory_data:
        try:
            name = item['name']
            real_qty = float(item['realQty'])
            if real_qty < 0: raise ValueError()
            updates.append((real_qty, name))
        except Exception:
            return {"error": f"Neplatná položka inventúry: {item}"}
    if updates:
        db_connector.execute_query("UPDATE sklad SET mnozstvo=%s WHERE nazov=%s", updates, fetch='none', multi=True)
    return {"message": f"Inventúra dokončená. Aktualizovaných {len(updates)} položiek."}

def get_all_warehouse_items():
    return db_connector.execute_query(
        "SELECT nazov AS name, COALESCE(kategoria, typ, podtyp, '') AS type FROM sklad ORDER BY nazov"
    ) or []

def manual_warehouse_write_off(data):
    name, worker, qty_str, note = data.get('itemName'), data.get('workerName'), data.get('quantity'), data.get('note')
    if not all([name, worker, qty_str, note]):
        return {"error": "Všetky polia sú povinné."}
    try:
        qty = float(qty_str)
        if qty <= 0:
            raise ValueError("Množstvo musí byť kladné.")
    except (ValueError, TypeError):
        return {"error": "Zadané neplatné množstvo."}

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()

        # 1) Update skladu (nekonečné neodpisujeme)
        if name not in INFINITE_STOCK_NAMES:
            cur.execute("UPDATE sklad SET mnozstvo = mnozstvo - %s WHERE nazov = %s", (qty, name))

        # 2) Log výdaja – dynamicky podľa existujúcich stĺpcov v 'vydajky'
        inserted = False
        if _table_exists('vydajky'):
            col_datum    = _pick_existing_col('vydajky', ['datum','created_at','cas','datetime'])
            col_prac     = _pick_existing_col('vydajky', ['pracovnik','user','pouzivatel','operator'])
            col_nazov    = _pick_existing_col('vydajky', ['nazov_suroviny','nazov','polozka','nazov_polozky'])
            col_mnozstvo = _pick_existing_col('vydajky', ['mnozstvo_kg','mnozstvo'])
            col_pozn     = _pick_existing_col('vydajky', ['poznamka','dovod','poz'])

            if all([col_datum, col_prac, col_nazov, col_mnozstvo, col_pozn]):
                q = f"INSERT INTO vydajky ({col_datum}, {col_prac}, {col_nazov}, {col_mnozstvo}, {col_pozn}) VALUES (%s,%s,%s,%s,%s)"
                cur.execute(q, (datetime.now(), worker, name, qty, note))
                inserted = True

        # 3) Fallback log – ak sa nepodarilo do vydajky, zapíš aspoň do zaznamy_vyroba_suroviny
        if not inserted:
            cur.execute(
                """
                INSERT INTO zaznamy_vyroba_suroviny (id_davky, nazov_suroviny, pouzite_mnozstvo_kg)
                VALUES (%s, %s, %s)
                """,
                ('MANUAL-ODPIS', name, qty)
            )

        conn.commit()
        return {"message": f"Úspešne odpísaných {qty} kg suroviny '{name}'."}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected(): conn.close()
