# =================================================================
# === HANDLER PRE MODUL: ZISKOVOSŤ / NÁKLADY (upravené, kompatibilné) ===
# =================================================================

import db_connector
from datetime import datetime
from flask import render_template, make_response
import fleet_handler
COLL = 'utf8mb4_0900_ai_ci'
# -----------------------------
# ---- Pomocné: bezpečné zistenie existencie stĺpca v tabuľke
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
            (table, col), fetch='one'
        )
        return bool(r)
    except Exception:
        return False

def _product_manuf_avg_col() -> str | None:
    # vyber najbližší existujúci stĺpec s priemernou výrobnou €/kg
    for c in ('vyrobna_cena_eur_kg', 'vyrobna_cena', 'vyrobna_cena_avg_kg', 'vyrobna_cena_avg'):
        try:
            if _has_col('produkty', c):
                return c
        except Exception:
            pass
    return None

def compute_strict_production_revenue(year: int, month: int) -> dict:
    """
    Striktný výnos Výroby = len to, čo EXPEDÍCIA reálne prijala v danom mesiaci,
    ocenené výrobnou cenou €/kg.

    množstvo: expedicia_prijmy (kg priamo, alebo ks -> kg podľa vaha_balenia_g)
    cena:     primárne zaznamy_vyroba.cena_za_jednotku
              (ak MJ výrobku 'ks', prepočet na €/kg podľa vaha_balenia_g)
              fallback: priemerná výrobná cena z `produkty` (ak existuje)
    Výstup: {"total": float, "items": [...], "by_product": {...}}
    """
    y, m = int(year), int(month)

    # ak tabuľka expedicia_prijmy neexistuje, vráť nuly
    try:
        t_exists = db_connector.execute_query(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'expedicia_prijmy' LIMIT 1",
            fetch='one'
        )
        if not t_exists:
            return {"total": 0.0, "items": [], "by_product": {}}
    except Exception:
        return {"total": 0.0, "items": [], "by_product": {}}

    manuf_col = _product_manuf_avg_col()
    manuf_sel = f", p.{manuf_col} AS manuf_avg" if manuf_col else ", NULL AS manuf_avg"

    query = f"""
        SELECT
            ep.id, ep.id_davky, ep.nazov_vyrobku, ep.unit,
            ep.prijem_kg, ep.prijem_ks, ep.datum_prijmu,
            zv.cena_za_jednotku,
            p.ean, p.mj, p.vaha_balenia_g, p.nazov_vyrobku AS product_name
            {manuf_sel}
        FROM expedicia_prijmy ep
        LEFT JOIN zaznamy_vyroba zv ON zv.id_davky = ep.id_davky
        LEFT JOIN produkty p
          ON ep.nazov_vyrobku COLLATE {COLL} = p.nazov_vyrobku COLLATE {COLL}
        WHERE ep.is_deleted = 0
          AND YEAR(ep.datum_prijmu) = %s
          AND MONTH(ep.datum_prijmu) = %s
        ORDER BY ep.datum_prijmu ASC, ep.id ASC
    """
    rows = db_connector.execute_query(query, (y, m)) or []

    def _num(v, default=0.0):
        try:
            return float(v) if v not in (None, "") else default
        except Exception:
            return default

    total = 0.0
    items = []
    by_product = {}

    for r in rows:
        unit = (r.get('unit') or 'kg').lower()
        mj   = (r.get('mj') or 'kg').lower()
        wg   = _num(r.get('vaha_balenia_g'))

        # 1) množstvo v KG
        if unit == 'kg':
            qty_kg = _num(r.get('prijem_kg'))
        else:
            pcs    = _num(r.get('prijem_ks'))
            qty_kg = (pcs * wg) / 1000.0 if wg > 0 else 0.0

        # 2) výrobná cena €/kg
        perkg = 0.0
        cju   = r.get('cena_za_jednotku')
        if cju is not None:
            try:
                cju = float(cju)
                perkg = cju if mj == 'kg' else (cju / (wg/1000.0) if wg > 0 else 0.0)
            except Exception:
                perkg = 0.0
        if perkg <= 0.0:
            perkg = _num(r.get('manuf_avg'))

        value = qty_kg * perkg
        total += value

        # položka pre históriu
        d = r.get('datum_prijmu')
        dstr = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)
        prod = r.get('product_name') or r.get('nazov_vyrobku') or ''
        item = {
            "date": dstr,
            "batchId": r.get('id_davky'),
            "ean": r.get('ean'),
            "product": prod,
            "qty_kg": round(qty_kg, 3),
            "unit_cost_per_kg": round(perkg, 4),
            "value_eur": round(value, 2),
        }
        items.append(item)

        agg = by_product.setdefault(prod or "NEZNÁMY", {"qty_kg": 0.0, "value_eur": 0.0})
        agg["qty_kg"] += qty_kg
        agg["value_eur"] += value

    by_product = {k: {"qty_kg": round(v["qty_kg"], 3), "value_eur": round(v["value_eur"], 2)} for k, v in by_product.items()}
    return {"total": round(total, 2), "items": items, "by_product": by_product}

def _zv_name_col() -> str:
    # názov stĺpca s menom výrobku v zaznamy_vyroba
    return 'nazov_vyrobu' if _has_col('zaznamy_vyroba', 'nazov_vyrobu') else 'nazov_vyrobku'

def _product_manuf_avg_col() -> str | None:
    for c in ('vyrobna_cena_eur_kg', 'vyrobna_cena', 'vyrobna_cena_avg_kg', 'vyrobna_cena_avg'):
        if _has_col('produkty', c):
            return c
    return None

def compute_strict_production_revenue(year: int, month: int) -> dict:
    """
    Výrobný „výnos“ strikne z reálne prijatých výrobkov v EXPEDÍCII (expedicia_prijmy),
    ohodnotený výrobnou cenou:
      - primárne podľa zaznamy_vyroba.cena_za_jednotku (€/kg alebo €/ks -> konverzia na €/kg),
      - ak chýba, fallback na priemernú výrobnú cenu produktu v `produkty` (€/kg).
    Počíta iba záznamy za daný rok/mesiac podľa expedicia_prijmy.datum_prijmu.
    Výstup:
      {"total": float, "items": [...], "by_product": {...}}
    """
    y, m = int(year), int(month)

    # ak tabuľka príjmov expedície nie je, vráť nuly
    try:
        t_exists = db_connector.execute_query(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'expedicia_prijmy' LIMIT 1",
            fetch='one'
        )
        if not t_exists:
            return {"total": 0.0, "items": [], "by_product": {}}
    except Exception:
        return {"total": 0.0, "items": [], "by_product": {}}

    zv_name = _zv_name_col()
    manuf_col = _product_manuf_avg_col()
    manuf_sel = f", p.{manuf_col} AS manuf_avg" if manuf_col else ", NULL AS manuf_avg"

    query = f"""
        SELECT
            ep.id, ep.id_davky, ep.unit, ep.prijem_kg, ep.prijem_ks, ep.datum_prijmu,
            zv.cena_za_jednotku,
            p.mj AS product_mj, p.vaha_balenia_g, p.nazov_vyrobku, p.ean
            {manuf_sel}
        FROM expedicia_prijmy ep
        LEFT JOIN zaznamy_vyroba zv ON zv.id_davky = ep.id_davky
        LEFT JOIN produkty p ON TRIM(zv.{zv_name}) = TRIM(p.nazov_vyrobku)
        WHERE ep.is_deleted = 0
          AND YEAR(ep.datum_prijmu) = %s AND MONTH(ep.datum_prijmu) = %s
        ORDER BY ep.datum_prijmu ASC, ep.id ASC
    """
    rows = db_connector.execute_query(query, (y, m)) or []

    total = 0.0
    items = []
    by_product = {}

    for r in rows:
        unit = (r.get('unit') or 'kg').lower()
        mj   = (r.get('product_mj') or 'kg').lower()
        wg   = float(r.get('vaha_balenia_g') or 0.0)

        # prijaté množstvo v KG
        if unit == 'kg':
            qty_kg = float(r.get('prijem_kg') or 0.0)
        else:
            pcs = float(r.get('prijem_ks') or 0.0)
            qty_kg = (pcs * wg) / 1000.0 if wg > 0 else 0.0

        # €/kg – z cena_za_jednotku (ak MJ je ks, konvertuj), fallback na priemernú výrobnú cenu z `produkty`
        perkg = 0.0
        cju = r.get('cena_za_jednotku')
        if cju is not None:
            try:
                cju = float(cju)
                perkg = cju if mj == 'kg' else (cju / (wg/1000.0) if wg > 0 else 0.0)
            except Exception:
                perkg = 0.0
        if perkg <= 0.0:
            mv = r.get('manuf_avg')
            try:
                perkg = float(mv) if mv is not None else 0.0
            except Exception:
                perkg = 0.0

        value = qty_kg * perkg
        total += value

        # položka do histórie
        d = r.get('datum_prijmu')
        dstr = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)
        item = {
            "date": dstr,
            "batchId": r.get('id_davky'),
            "ean": r.get('ean'),
            "product": r.get('nazov_vyrobku') or "",
            "qty_kg": round(qty_kg, 3),
            "unit_cost_per_kg": round(perkg, 4),
            "value_eur": round(value, 2),
        }
        items.append(item)

        key = item["product"] or "NEZNÁMY"
        agg = by_product.setdefault(key, {"qty_kg": 0.0, "value_eur": 0.0})
        agg["qty_kg"] += qty_kg
        agg["value_eur"] += value

    by_product = {k: {"qty_kg": round(v["qty_kg"],3), "value_eur": round(v["value_eur"],2)} for k,v in by_product.items()}
    return {"total": round(total, 2), "items": items, "by_product": by_product}

# Pomocné pretypovanie roka/mesiaca
def _ym_int(year, month):
    return int(year), int(month)

def get_profitability_data(year, month):
    year, month = _ym_int(year, month)

    # 1) Oddelenia (ručné vstupy)
    dept_data = db_connector.execute_query(
        "SELECT * FROM profit_department_monthly WHERE report_year = %s AND report_month = %s",
        (year, month), fetch='one'
    ) or {}

    # 2) Prehľady
    production_view_data = get_production_profit_view(year, month)
    sales_channels_data  = get_sales_channels_view(year, month)
    calculations_data    = get_calculations_view(year, month)

    # 3) „Prísna“ výroba – len reálne prijaté z expedície v danom mesiaci
    strict_prod = compute_strict_production_revenue(year, month)
    strict_total = float(strict_prod.get('total') or 0.0)

    # 4) Bezpečné čísla z Oddelení (fallback, ak prísna výroba je 0)
    exp_stock_prev       = float(dept_data.get('exp_stock_prev', 0) or 0)
    exp_from_butchering  = float(dept_data.get('exp_from_butchering', 0) or 0)
    exp_from_prod_manual = float(dept_data.get('exp_from_prod', 0) or 0)   # pôvodný ručný vstup
    exp_external         = float(dept_data.get('exp_external', 0) or 0)
    exp_returns          = float(dept_data.get('exp_returns', 0) or 0)
    exp_stock_current    = float(dept_data.get('exp_stock_current', 0) or 0)
    exp_revenue          = float(dept_data.get('exp_revenue', 0) or 0)

    # 5) Zdroj pre „príjem z výroby“ do COGS (preferuj prísny)
    exp_from_prod_used  = strict_total if strict_total > 0 else exp_from_prod_manual
    prod_source         = 'strict' if strict_total > 0 else 'manual'

    # 6) Expedícia – COGS & zisk
    cost_of_goods_sold = (exp_stock_prev + exp_from_butchering + exp_from_prod_used + exp_external) - exp_returns - exp_stock_current
    exp_profit         = exp_revenue - cost_of_goods_sold

    # 7) Rozrábka
    butcher_profit      = float(dept_data.get('butcher_meat_value', 0) or 0) - float(dept_data.get('butcher_paid_goods', 0) or 0)
    butcher_revaluation = float(dept_data.get('butcher_process_value', 0) or 0) + float(dept_data.get('butcher_returns_value', 0) or 0)

    # 8) Celkový zisk (výrobný profit nechávame z production_view; „strict“ je výnos, nie profit)
    total_profit = (
        butcher_profit
        + exp_profit
        + production_view_data['summary']['total_profit']
        - float(dept_data.get('general_costs', 0) or 0)
    )

    # 9) Rozšírené dáta pre FE a iné moduly
    dept_data_out = dict(dept_data)
    dept_data_out['exp_from_prod_strict'] = strict_total
    dept_data_out['exp_from_prod_used']   = exp_from_prod_used
    dept_data_out['exp_from_prod_source'] = prod_source

    production_view_data = dict(production_view_data)
    production_view_data['strict_revenue'] = strict_total
    production_view_data['strict_items']   = strict_prod.get('items') or []

    return {
        "year": year, "month": month,
        "department_data": dept_data_out,
        "sales_channels_view": sales_channels_data,
        "calculations_view": calculations_data,
        "production_view": production_view_data,
        "production_strict": strict_prod,  # total/items/by_product
        "calculations": {
            "expedition_profit": exp_profit,
            "butchering_profit": butcher_profit,
            "butchering_revaluation": butcher_revaluation,
            "production_profit": production_view_data['summary']['total_profit'],
            "total_profit": total_profit
        }
    }


def get_sales_channels_view(year, month):
    year, month = _ym_int(year, month)
    query = f"""
        SELECT sc.*, p.nazov_vyrobku AS product_name
        FROM profit_sales_monthly sc
        JOIN produkty p
          ON sc.product_ean COLLATE {COLL} = p.ean COLLATE {COLL}
        WHERE sc.report_year = %s AND sc.report_month = %s
        ORDER BY COALESCE(sc.sales_channel,'UNSPECIFIED'), p.nazov_vyrobku
    """
    sales_data = db_connector.execute_query(query, (year, month)) or []

    sales_by_channel = {}
    for row in sales_data:
        channel = row.get('sales_channel') or 'UNSPECIFIED'
        sales_by_channel.setdefault(channel, {
            "items": [],
            "summary": {
                "total_kg": 0.0,
                "total_purchase": 0.0,
                "total_sell": 0.0,
                "total_profit": 0.0
            }
        })

        # Bezpečné numerické typy
        purchase_net = float(row.get('purchase_price_net') or 0.0)
        sell_net     = float(row.get('sell_price_net') or 0.0)
        sales_kg     = float(row.get('sales_kg') or 0.0)

        row['purchase_price_net'] = purchase_net
        row['sell_price_net']     = sell_net
        row['sales_kg']           = sales_kg

        row['total_profit_eur'] = (sell_net - purchase_net) * sales_kg
        row['profit_per_kg']    = (sell_net - purchase_net) if (purchase_net > 0 or sell_net > 0) else 0.0

        sales_by_channel[channel]['items'].append(row)

        if sales_kg > 0:
            s = sales_by_channel[channel]['summary']
            s['total_kg']       += sales_kg
            s['total_purchase'] += purchase_net * sales_kg
            s['total_sell']     += sell_net * sales_kg
            s['total_profit']   += row['total_profit_eur']

    return sales_by_channel


def get_calculations_view(year, month):
    year, month = _ym_int(year, month)
    calc_q = "SELECT * FROM profit_calculations WHERE report_year = %s AND report_month = %s ORDER BY name"
    calculations = db_connector.execute_query(calc_q, (year, month))

    if calculations:
        calc_ids = [c['id'] for c in calculations]
        if calc_ids:
            placeholders = ','.join(['%s'] * len(calc_ids))
            items_q = f"""
    SELECT pci.*, p.nazov_vyrobku AS product_name
    FROM profit_calculation_items pci
    JOIN produkty p
      ON pci.product_ean COLLATE {COLL} = p.ean COLLATE {COLL}
    WHERE pci.calculation_id IN ({placeholders})
"""

            all_items = db_connector.execute_query(items_q, tuple(calc_ids))
            items_by_calc_id = {c_id: [] for c_id in calc_ids}
            for item in all_items:
                # float istoty
                item['purchase_price_net'] = float(item.get('purchase_price_net') or 0)
                item['sell_price_net']     = float(item.get('sell_price_net') or 0)
                item['estimated_kg']       = float(item.get('estimated_kg') or 0)
                items_by_calc_id[item['calculation_id']].append(item)
            for calc in calculations: 
                calc['items'] = items_by_calc_id.get(calc['id'], [])

    # ⚙️ Bezpečná náhrada za neexistujúci stĺpec 'zv.cena_za_jednotku'
    products_q = f"""
    SELECT 
        p.ean, p.nazov_vyrobku, p.predajna_kategoria,
        (
          SELECT ROUND(zv.celkova_cena_surovin / NULLIF(zv.realne_mnozstvo_kg, 0), 4)
          FROM zaznamy_vyroba zv
          WHERE zv.nazov_vyrobku COLLATE {COLL} = p.nazov_vyrobku COLLATE {COLL}
            AND zv.stav IN ('Dokončené','Ukončené')
            AND zv.celkova_cena_surovin IS NOT NULL
            AND zv.realne_mnozstvo_kg IS NOT NULL
          ORDER BY COALESCE(zv.datum_ukoncenia, zv.datum_vyroby) DESC
          LIMIT 1
        ) AS avg_cost
    FROM produkty p
    WHERE p.typ_polozky LIKE 'VÝROBOK%%' OR p.typ_polozky LIKE 'TOVAR%%'
    ORDER BY p.predajna_kategoria, p.nazov_vyrobku
"""

    vehicles_q  = "SELECT id, name, license_plate FROM fleet_vehicles WHERE is_active = TRUE ORDER BY name"
    customers_q = "SELECT id, nazov_firmy FROM b2b_zakaznici WHERE je_admin = 0 AND je_schvaleny = 1 ORDER BY nazov_firmy"

    all_products = db_connector.execute_query(products_q)
    all_vehicles = db_connector.execute_query(vehicles_q)
    all_customers = db_connector.execute_query(customers_q)

    # doplň metriky z fleet analýzy (rok/mesiac môžu prísť ako str)
    for v in all_vehicles:
        analysis = fleet_handler.get_fleet_analysis(v['id'], year, month)
        v['cost_per_km'] = float(analysis.get('cost_per_km', 0) or 0)

    return {
        "calculations": calculations,
        "available_products": all_products,
        "available_vehicles": all_vehicles,
        "available_customers": all_customers
    }

def save_calculation(data):
    # roky/mesiace môžu prísť ako stringy
    data['year']  = int(data.get('year'))
    data['month'] = int(data.get('month'))

    calc_id = data.get('id') or None
    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        calc_params = (
            data['name'], data['year'], data['month'],
            data.get('vehicle_id') or None,
            float(data.get('distance_km') or 0),
            float(data.get('transport_cost') or 0)
        )
        if calc_id:
            cursor.execute(
                "UPDATE profit_calculations SET name=%s, report_year=%s, report_month=%s, vehicle_id=%s, distance_km=%s, transport_cost=%s WHERE id=%s",
                calc_params + (calc_id,)
            )
        else:
            cursor.execute(
                "INSERT INTO profit_calculations (name, report_year, report_month, vehicle_id, distance_km, transport_cost) VALUES (%s, %s, %s, %s, %s, %s)",
                calc_params
            )
            calc_id = cursor.lastrowid

        cursor.execute("DELETE FROM profit_calculation_items WHERE calculation_id = %s", (calc_id,))
        items = data.get('items', [])
        if items:
            items_to_insert = [
                (
                    calc_id, i['product_ean'],
                    float(i.get('estimated_kg') or 0),
                    float(i.get('purchase_price_net') or 0),
                    float(i.get('sell_price_net') or 0)
                )
                for i in items
            ]
            if items_to_insert:
                cursor.executemany(
                    "INSERT INTO profit_calculation_items (calculation_id, product_ean, estimated_kg, purchase_price_net, sell_price_net) VALUES (%s, %s, %s, %s, %s)",
                    items_to_insert
                )
        conn.commit()
        return {"message": f"Kalkulácia '{data['name']}' bola úspešne uložená."}
    except Exception as e:
        if conn: conn.rollback(); raise e
    finally:
        if conn and conn.is_connected(): conn.close()

def delete_calculation(data):
    db_connector.execute_query("DELETE FROM profit_calculations WHERE id = %s", (data.get('id'),), fetch='none')
    return {"message": "Kalkulácia bola vymazaná."}

def setup_new_sales_channel(data):
    # rok/mesiac ako int
    year  = int(data.get('year'))
    month = int(data.get('month'))
    channel_name = (data.get('channel_name') or '').strip()
    if not all([year, month, channel_name]): 
        return {"error": "Chýbajú dáta."}

    products_q = "SELECT ean, nazov_vyrobku FROM produkty WHERE typ_polozky LIKE 'VÝROBOK%%' OR typ_polozky LIKE 'TOVAR%%'"
    all_products = db_connector.execute_query(products_q)
    if not all_products:
        return {"message": "V katalógu nie sú žiadne produkty na pridanie."}

    available_products_with_costs = get_calculations_view(year, month)['available_products']
    prod_costs = {p['ean']: p.get('avg_cost', 0) for p in available_products_with_costs}

    records_to_insert = [
        (year, month, channel_name, p['ean'], float(prod_costs.get(p['ean'], 0) or 0))
        for p in all_products
    ]

    query = """
        INSERT IGNORE INTO profit_sales_monthly
            (report_year, report_month, sales_channel, product_ean, purchase_price_net)
        VALUES (%s, %s, %s, %s, %s)
    """
    rows_affected = db_connector.execute_query(query, records_to_insert, fetch='rowcount', multi=True)
    return {"message": f"Kanál '{channel_name}' bol pripravený. Pridaných {rows_affected} produktov."}

def save_sales_channel_data(data):
    year  = int(data.get('year'))
    month = int(data.get('month'))
    channel = data.get('channel')
    rows = data.get('rows', [])
    if not all([year, month, channel, rows]): 
        return {"error": "Chýbajú dáta."}

    data_to_save = [
        (
            float(r.get('sales_kg') or 0),
            float(r.get('purchase_price_net') or 0),
            float(r.get('purchase_price_vat') or 0),
            float(r.get('sell_price_net') or 0),
            float(r.get('sell_price_vat') or 0),
            year, month, channel, r['ean']
        )
        for r in rows
    ]

    query = """
        UPDATE profit_sales_monthly
        SET sales_kg=%s, purchase_price_net=%s, purchase_price_vat=%s, sell_price_net=%s, sell_price_vat=%s
        WHERE report_year=%s AND report_month=%s AND sales_channel=%s AND product_ean=%s
    """
    db_connector.execute_query(query, data_to_save, fetch='none', multi=True)
    return {"message": f"Dáta pre kanál '{channel}' boli uložené."}
def save_department_data(data):
    year  = int(data.get('year'))
    month = int(data.get('month'))
    if not year or not month:
        return {"error": "Chýba rok alebo mesiac."}

    # všetky spravované polia v tabuľke
    fields = [
        'exp_stock_prev', 'exp_from_butchering', 'exp_from_prod', 'exp_external',
        'exp_returns', 'exp_stock_current', 'exp_revenue',
        'butcher_meat_value', 'butcher_paid_goods', 'butcher_process_value', 'butcher_returns_value',
        'general_costs'
    ]

    # načítaj existujúci riadok (ak je)
    existing = db_connector.execute_query(
        "SELECT * FROM profit_department_monthly WHERE report_year=%s AND report_month=%s",
        (year, month), fetch='one'
    ) or {}

    # poskladaj hodnoty takto:
    # - ak pole prišlo v requeste → použijeme ho (float)
    # - ak nie a v DB je hodnota → ponecháme ju
    # - ak riadok zatiaľ nie je → použijeme 0
    values = {}
    for f in fields:
        if f in data and data.get(f) not in (None, ''):
            try:
                values[f] = float(data.get(f))
            except Exception:
                values[f] = 0.0
        else:
            values[f] = float(existing.get(f, 0) or 0)

    params = {"report_year": year, "report_month": month, **values}

    query = """
        INSERT INTO profit_department_monthly
          (report_year, report_month,
           exp_stock_prev, exp_from_butchering, exp_from_prod, exp_external, exp_returns, exp_stock_current, exp_revenue,
           butcher_meat_value, butcher_paid_goods, butcher_process_value, butcher_returns_value, general_costs)
        VALUES
          (%(report_year)s, %(report_month)s,
           %(exp_stock_prev)s, %(exp_from_butchering)s, %(exp_from_prod)s, %(exp_external)s, %(exp_returns)s, %(exp_stock_current)s, %(exp_revenue)s,
           %(butcher_meat_value)s, %(butcher_paid_goods)s, %(butcher_process_value)s, %(butcher_returns_value)s, %(general_costs)s)
        ON DUPLICATE KEY UPDATE
           exp_stock_prev        = VALUES(exp_stock_prev),
           exp_from_butchering   = VALUES(exp_from_butchering),
           exp_from_prod         = VALUES(exp_from_prod),
           exp_external          = VALUES(exp_external),
           exp_returns           = VALUES(exp_returns),
           exp_stock_current     = VALUES(exp_stock_current),
           exp_revenue           = VALUES(exp_revenue),
           butcher_meat_value    = VALUES(butcher_meat_value),
           butcher_paid_goods    = VALUES(butcher_paid_goods),
           butcher_process_value = VALUES(butcher_process_value),
           butcher_returns_value = VALUES(butcher_returns_value),
           general_costs         = VALUES(general_costs)
    """
    db_connector.execute_query(query, params, fetch='none')
    return {"message": "Dáta boli úspešne uložené."}


def get_production_profit_view(year, month):
    year, month = _ym_int(year, month)
    products_query = """
        SELECT ean, nazov_vyrobku, typ_polozky, mj, vaha_balenia_g
        FROM produkty
        WHERE typ_polozky LIKE 'VÝROBOK%%'
        ORDER BY nazov_vyrobku
    """
    all_products = db_connector.execute_query(products_query)

    prod_manual_data_query = "SELECT * FROM profit_production_monthly WHERE report_year = %s AND report_month = %s"
    prod_manual_data = {row['product_ean']: row for row in db_connector.execute_query(prod_manual_data_query, (year, month))}

    available_products_with_costs = get_calculations_view(year, month).get('available_products', [])
    prod_costs = {p['nazov_vyrobku']: p.get('avg_cost') for p in available_products_with_costs}

    table_rows, summary = [], {'total_profit': 0.0, 'total_kg': 0.0, 'total_kg_no_pkg': 0.0, 'jars_200': 0.0, 'jars_500': 0.0, 'lids': 0.0}

    for p in all_products:
        manual_data   = prod_manual_data.get(p['ean'], {}) or {}
        prod_cost     = float(prod_costs.get(p['nazov_vyrobku'], 0) or 0)
        transfer_price= float(manual_data.get('transfer_price_per_unit') or (prod_cost * 1.1 if prod_cost > 0 else 0))
        sales_kg      = float(manual_data.get('expedition_sales_kg') or 0)
        profit        = (transfer_price - prod_cost) * sales_kg if (sales_kg > 0 and prod_cost > 0) else 0.0

        summary['total_profit'] += profit
        table_rows.append({
            "ean": p['ean'],
            "name": p['nazov_vyrobku'],
            "exp_stock_kg": 0.0,
            "exp_sales_kg": sales_kg,
            "production_cost": prod_cost,
            "transfer_price": transfer_price,
            "profit": profit
        })

        is_packaged_or_sliced = p['typ_polozky'] in ['VÝROBOK_KUSOVY', 'VÝROBOK_KRAJANY']
        if not is_packaged_or_sliced:
            summary['total_kg_no_pkg'] += sales_kg

        weight_g = float(p.get('vaha_balenia_g') or 0)
        if weight_g > 0 and sales_kg > 0:
            num_pieces = (sales_kg * 1000.0) / weight_g
            lowname = (p['nazov_vyrobku'] or '').lower()
            if ('paštéta' in lowname) or ('pašteta' in lowname) or ('pečeňový' in lowname) or ('pecenovy' in lowname):
                if int(weight_g) == 200: summary['jars_200'] += num_pieces
                if int(weight_g) == 500: summary['jars_500'] += num_pieces
                summary['lids'] += num_pieces
        summary['total_kg'] += sales_kg

    return {"rows": table_rows, "summary": summary}

def save_production_profit_data(data):
    year  = int(data.get('year'))
    month = int(data.get('month'))
    rows  = data.get('rows', [])
    if not all([year, month, rows]): 
        return {"error": "Chýbajú dáta."}

    data_to_save = [
        (year, month, row['ean'], float(row.get('expedition_sales_kg') or 0), float(row.get('transfer_price') or 0))
        for row in rows
    ]

    query = """
        INSERT INTO profit_production_monthly
          (report_year, report_month, product_ean, expedition_sales_kg, transfer_price_per_unit)
        VALUES (%s, %s, %s, %s, %s) AS new
        ON DUPLICATE KEY UPDATE
          expedition_sales_kg    = new.expedition_sales_kg,
          transfer_price_per_unit= new.transfer_price_per_unit
    """
    db_connector.execute_query(query, data_to_save, fetch='none', multi=True)
    return {"message": "Dáta pre ziskovosť výroby boli uložené."}

def get_profitability_report_html(year, month, report_type):
    year, month = _ym_int(year, month)
    full_data = get_profitability_data(year, month)


    # Pretypovanie čísel v 'calculations' reporte (bezpečnosť pre šablónu)
    if report_type == 'calculations':
        for calc in full_data.get('calculations_view', {}).get('calculations', []) or []:
            calc['distance_km']   = float(calc.get('distance_km') or 0)
            calc['transport_cost']= float(calc.get('transport_cost') or 0)
            for item in calc.get('items', []) or []:
                item['purchase_price_net'] = float(item.get('purchase_price_net') or 0)
                item['sell_price_net']     = float(item.get('sell_price_net') or 0)
                item['estimated_kg']       = float(item.get('estimated_kg') or 0)

    title_map = {
        'departments': 'Report Výnosov Oddelení',
        'production': 'Report Výnosu Výroby',
        'sales_channels': 'Report Predajných Kanálov',
        'calculations': 'Report Kalkulácií a Súťaží',
        'summary': 'Celkový Prehľad Ziskovosti'
    }
    template_data = {
        "title": title_map.get(report_type, 'Report Ziskovosti'),
        "report_type": report_type,
        "period": f"{month}/{year}",
        "data": full_data,
        "today": datetime.now().strftime('%d.%m.%Y')
    }
    return make_response(render_template('profitability_report_template.html', **template_data))
# -----------------------------------------------------------------
# História a reporting (Ziskovosť)
# -----------------------------------------------------------------
from datetime import date

def _parse_ym_param(s: str) -> tuple[int, int]:
    y, m = s.split('-', 1)
    return int(y), int(m)

def _iter_months(fy: int, fm: int, ty: int, tm: int):
    y, m = fy, fm
    while (y < ty) or (y == ty and m <= tm):
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1

def _mk_summary_row(year: int, month: int, data: dict) -> dict:
    # použijeme už vyrátané "calculations" z get_profitability_data
    c = data.get('calculations') or {}
    return {
        "year": year, "month": month, "label": f"{year}-{month:02d}",
        "expedition_profit": float(c.get('expedition_profit') or 0),
        "butchering_profit": float(c.get('butchering_profit') or 0),
        "production_profit": float(c.get('production_profit') or 0),
        "total_profit": float(c.get('total_profit') or 0),
    }

def get_profitability_history(args: dict):
    """JSON história ziskovosti podľa rozsahu + typu. Primárne 'summary' tabuľka za mesiace."""
    scope = (args.get('scope') or 'month').lower()
    rtype = (args.get('type') or 'summary').lower()

    # urči rozsah
    if scope == 'year':
        y = int(args.get('year') or date.today().year)
        fy, fm, ty, tm = y, 1, y, 12
    elif scope == 'range':
        fy, fm = _parse_ym_param(args.get('from') or f"{date.today().year}-01")
        ty, tm = _parse_ym_param(args.get('to')   or f"{date.today().year}-12")
    else:
        y = int(args.get('year') or date.today().year)
        m = int(args.get('month') or date.today().month)
        fy, fm, ty, tm = y, m, y, m

    series = []
    totals = {"expedition_profit":0.0, "butchering_profit":0.0, "production_profit":0.0, "total_profit":0.0}

    # Zatiaľ pripravíme históriu pre 'summary' (najdôležitejší use-case)
    if rtype == 'summary':
        for y, m in _iter_months(fy, fm, ty, tm):
            d = get_profitability_data(y, m)
            row = _mk_summary_row(y, m, d)
            series.append(row)
            for k in totals.keys():
                totals[k] += float(row.get(k) or 0.0)

        months = max(1, len(series))
        averages = { k: round(v / months, 2) for k, v in totals.items() }
        return {
            "range": {"from": f"{fy}-{fm:02d}", "to": f"{ty}-{tm:02d}"},
            "type": rtype,
            "series": series,
            "totals": {k: round(v, 2) for k, v in totals.items()},
            "averages": averages
        }

    # iné typy – v1 vraciame len po mesiacoch total_profit (aby UI vedelo aspoň niečo zobraziť)
    for y, m in _iter_months(fy, fm, ty, tm):
        d = get_profitability_data(y, m)
        c = d.get('calculations') or {}
        series.append({"year":y, "month":m, "label":f"{y}-{m:02d}", "total_profit": float(c.get('total_profit') or 0)})

    return {"range":{"from":f"{fy}-{fm:02d}","to":f"{ty}-{tm:02d}"}, "type":rtype, "series":series}

def get_profitability_report_html_ex(params: dict):
    """
    Rozšírený HTML report:
      scope = 'month' | 'year' | 'range'
      type  = 'summary' | 'departments' | 'production' | 'sales_channels' | 'calculations'
      year, month  (pri scope=month)
      from=YYYY-MM, to=YYYY-MM (pri scope=range)
    """
    scope = (params.get('scope') or 'month').lower()
    rtype = (params.get('type') or 'summary').lower()

    if scope == 'year':
        y = int(params.get('year') or date.today().year)
        fy, fm, ty, tm = y, 1, y, 12
        title = f"Ziskovosť – Report za rok {y}"
    elif scope == 'range':
        fy, fm = _parse_ym_param(params.get('from') or f"{date.today().year}-01")
        ty, tm = _parse_ym_param(params.get('to')   or f"{date.today().year}-12")
        title = f"Ziskovosť – Report {fy}-{fm:02d} až {ty}-{tm:02d}"
    else:
        y = int(params.get('year') or date.today().year)
        m = int(params.get('month') or date.today().month)
        fy, fm, ty, tm = y, m, y, m
        title = f"Ziskovosť – Report {y}-{m:02d}"

    # MONTH: použijeme tvoju existujúcu šablónu profitability_report_template.html
    if scope == 'month':
        return get_profitability_report_html(y, m, rtype)

    # YEAR/RANGE: v1 – kompaktná tabuľka "summary" (mesiace v riadkoch)
    if rtype == 'summary':
        rows_html = ""
        totals = {"expedition_profit":0.0,"butchering_profit":0.0,"production_profit":0.0,"total_profit":0.0}
        for yy, mm in _iter_months(fy, fm, ty, tm):
            d = get_profitability_data(yy, mm)
            c = d.get('calculations') or {}
            ep = float(c.get('expedition_profit') or 0)
            bp = float(c.get('butchering_profit') or 0)
            pp = float(c.get('production_profit') or 0)
            tp = float(c.get('total_profit') or 0)
            rows_html += f"<tr><td>{yy}-{mm:02d}</td><td style='text-align:right'>{ep:.2f}</td><td style='text-align:right'>{bp:.2f}</td><td style='text-align:right'>{pp:.2f}</td><td style='text-align:right'>{tp:.2f}</td></tr>"
            totals["expedition_profit"]+=ep; totals["butchering_profit"]+=bp; totals["production_profit"]+=pp; totals["total_profit"]+=tp
        total_row = f"<tr style='font-weight:700;background:#fff7f7'><td>SPOLU</td><td style='text-align:right'>{totals['expedition_profit']:.2f}</td><td style='text-align:right'>{totals['butchering_profit']:.2f}</td><td style='text-align:right'>{totals['production_profit']:.2f}</td><td style='text-align:right'>{totals['total_profit']:.2f}</td></tr>"

        html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:Inter,system-ui,Arial,sans-serif;padding:16px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #e5e7eb;padding:6px 8px;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
th{{background:#f9fafb}}
h2{{margin:0 0 12px 0}}
.small{{color:#555;margin:4px 0 12px 0}}
</style></head><body>
<h2>{title}</h2>
<p class="small">Rozsah: {fy}-{fm:02d} až {ty}-{tm:02d}</p>
<table>
  <thead><tr><th>Obdobie</th><th>Expedícia (€)</th><th>Rozrábka (€)</th><th>Výroba (€)</th><th>Spolu zisk (€)</th></tr></thead>
  <tbody>{rows_html}{total_row}</tbody>
</table>
<script>window.print()</script>
</body></html>"""
        from flask import make_response
        return make_response(html)

    # Iné typy pri YEAR/RANGE – zatiaľ fallback s poznámkou (môžeme dopracovať na želanie)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head>
<body><h3>{title}</h3><p>Viacmesačný report typu <b>{rtype}</b> zatiaľ nie je dostupný. Zvoľte typ <b>summary</b> alebo tlačte po mesiacoch.</p>
<script>window.print()</script></body></html>"""
    from flask import make_response
    return make_response(html)
