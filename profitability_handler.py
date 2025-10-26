# =================================================================
# === HANDLER PRE MODUL: ZISKOVOSŤ / NÁKLADY (upravené, kompatibilné) ===
# =================================================================

import db_connector
from datetime import datetime
from flask import render_template, make_response
import fleet_handler

# -----------------------------
# Pomocné pretypovanie roka/mesiaca
def _ym_int(year, month):
    return int(year), int(month)

def get_profitability_data(year, month):
    year, month = _ym_int(year, month)
    dept_data = db_connector.execute_query(
        "SELECT * FROM profit_department_monthly WHERE report_year = %s AND report_month = %s",
        (year, month), fetch='one'
    ) or {}

    production_view_data = get_production_profit_view(year, month)
    sales_channels_data  = get_sales_channels_view(year, month)
    calculations_data    = get_calculations_view(year, month)

    # Bezpečne vyťahuj kľúče (ak stĺpce v DB neexistujú, bude 0)
    exp_stock_prev      = float(dept_data.get('exp_stock_prev', 0) or 0)
    exp_from_butchering = float(dept_data.get('exp_from_butchering', 0) or 0)
    exp_from_prod       = float(dept_data.get('exp_from_prod', 0) or 0)
    exp_external        = float(dept_data.get('exp_external', 0) or 0)
    exp_returns         = float(dept_data.get('exp_returns', 0) or 0)
    exp_stock_current   = float(dept_data.get('exp_stock_current', 0) or 0)
    exp_revenue         = float(dept_data.get('exp_revenue', 0) or 0)

    cost_of_goods_sold = (exp_stock_prev + exp_from_butchering + exp_from_prod + exp_external) - exp_returns - exp_stock_current
    exp_profit         = exp_revenue - cost_of_goods_sold

    butcher_profit      = float(dept_data.get('butcher_meat_value', 0) or 0) - float(dept_data.get('butcher_paid_goods', 0) or 0)
    butcher_revaluation = float(dept_data.get('butcher_process_value', 0) or 0) + float(dept_data.get('butcher_returns_value', 0) or 0)

    total_profit = (
        butcher_profit
        + exp_profit
        + production_view_data['summary']['total_profit']
        - float(dept_data.get('general_costs', 0) or 0)
    )

    return {
        "year": year, "month": month,
        "department_data": dept_data,
        "sales_channels_view": sales_channels_data,
        "calculations_view": calculations_data,
        "production_view": production_view_data,
        "calculations": {
            "expedition_profit": exp_profit, "butchering_profit": butcher_profit,
            "butchering_revaluation": butcher_revaluation,
            "production_profit": production_view_data['summary']['total_profit'],
            "total_profit": total_profit
        }
    }

def get_sales_channels_view(year, month):
    year, month = _ym_int(year, month)
    query = """
        SELECT sc.*, p.nazov_vyrobku AS product_name
        FROM profit_sales_monthly sc
        JOIN produkty p ON sc.product_ean = p.ean
        WHERE sc.report_year = %s AND sc.report_month = %s 
        ORDER BY COALESCE(sc.sales_channel,'UNSPECIFIED'), p.nazov_vyrobku
    """
    sales_data = db_connector.execute_query(query, (year, month))

    sales_by_channel = {}
    for row in sales_data:
        channel = row.get('sales_channel') or 'UNSPECIFIED'
        if channel not in sales_by_channel:
            sales_by_channel[channel] = {
                'items': [], 
                'summary': {'total_kg': 0.0, 'total_purchase': 0.0, 'total_sell': 0.0, 'total_profit': 0.0}
            }

        # Bezpečné numerické typy
        purchase_net = float(row.get('purchase_price_net') or 0)
        sell_net     = float(row.get('sell_price_net') or 0)
        sales_kg     = float(row.get('sales_kg') or 0)

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
                JOIN produkty p ON pci.product_ean = p.ean
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
    products_q = """
        SELECT 
            p.ean, p.nazov_vyrobku, p.predajna_kategoria,
            (
              SELECT ROUND(zv.celkova_cena_surovin / NULLIF(zv.realne_mnozstvo_kg, 0), 4)
              FROM zaznamy_vyroba zv
              WHERE zv.nazov_vyrobku = p.nazov_vyrobku
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

    # Polia, ktoré posiela UI – budú uložené do profit_department_monthly
    fields = [
        'exp_stock_prev', 'exp_from_butchering', 'exp_from_prod', 'exp_external',
        'exp_returns', 'exp_stock_current', 'exp_revenue',
        'butcher_meat_value', 'butcher_paid_goods', 'butcher_process_value', 'butcher_returns_value',
        'general_costs'
    ]
    params = {field: float(data.get(field) or 0.0) for field in fields}
    params['report_year']  = year
    params['report_month'] = month

    # Použi alias 'new' namiesto deprecated VALUES()
    query = """
        INSERT INTO profit_department_monthly
          (report_year, report_month,
           exp_stock_prev, exp_from_butchering, exp_from_prod, exp_external, exp_returns, exp_stock_current, exp_revenue,
           butcher_meat_value, butcher_paid_goods, butcher_process_value, butcher_returns_value, general_costs)
        VALUES
          (%(report_year)s, %(report_month)s,
           %(exp_stock_prev)s, %(exp_from_butchering)s, %(exp_from_prod)s, %(exp_external)s, %(exp_returns)s, %(exp_stock_current)s, %(exp_revenue)s,
           %(butcher_meat_value)s, %(butcher_paid_goods)s, %(butcher_process_value)s, %(butcher_returns_value)s, %(general_costs)s)
        AS new
        ON DUPLICATE KEY UPDATE
           exp_stock_prev      = new.exp_stock_prev,
           exp_from_butchering = new.exp_from_butchering,
           exp_from_prod       = new.exp_from_prod,
           exp_external        = new.exp_external,
           exp_returns         = new.exp_returns,
           exp_stock_current   = new.exp_stock_current,
           exp_revenue         = new.exp_revenue,
           butcher_meat_value  = new.butcher_meat_value,
           butcher_paid_goods  = new.butcher_paid_goods,
           butcher_process_value = new.butcher_process_value,
           butcher_returns_value = new.butcher_returns_value,
           general_costs       = new.general_costs
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
