# =================================================================
# === HANDLER PRE MODUL: SPRÁVA VOZOVÉHO PARKU (opravené) ===
# =================================================================

import db_connector
from datetime import datetime
from calendar import monthrange
from flask import render_template, make_response

def _to_int(val, fallback=None):
    try:
        return int(val)
    except (TypeError, ValueError):
        return fallback

def get_fleet_data(vehicle_id=None, year=None, month=None):
    """Získa dáta pre vozový park (prehľad)."""
    vehicles_query = "SELECT * FROM fleet_vehicles WHERE is_active = TRUE ORDER BY name"
    all_vehicles = db_connector.execute_query(vehicles_query)

    if not vehicle_id and all_vehicles:
        vehicle_id = all_vehicles[0]['id']

    today = datetime.now()
    year = _to_int(year, today.year)
    month = _to_int(month, today.month)

    logs, refuelings, last_odometer = [], [], 0
    
    if vehicle_id:
        # Denníky jázd
        logs_query = """
            SELECT * FROM fleet_logs
            WHERE vehicle_id = %s AND YEAR(log_date) = %s AND MONTH(log_date) = %s
            ORDER BY log_date ASC
        """
        logs = db_connector.execute_query(logs_query, (vehicle_id, year, month))

        # Tankovania
        refuelings_query = """
            SELECT * FROM fleet_refueling
            WHERE vehicle_id = %s AND YEAR(refueling_date) = %s AND MONTH(refueling_date) = %s
            ORDER BY refueling_date ASC
        """
        refuelings = db_connector.execute_query(refuelings_query, (vehicle_id, year, month))

        # Posledný známy stav tachometra pred aktuálnym mesiacom
        first_day_of_month = f"{year:04d}-{month:02d}-01"
        last_odo_query = """
            SELECT end_odometer
            FROM fleet_logs
            WHERE vehicle_id = %s AND log_date < %s AND end_odometer IS NOT NULL
            ORDER BY log_date DESC
            LIMIT 1
        """
        last_odo_result = db_connector.execute_query(last_odo_query, (vehicle_id, first_day_of_month), fetch='one')
        
        if last_odo_result and last_odo_result.get('end_odometer'):
            last_odometer = last_odo_result['end_odometer']
        else:
            initial_odo_query = "SELECT initial_odometer FROM fleet_vehicles WHERE id = %s"
            initial_odo_result = db_connector.execute_query(initial_odo_query, (vehicle_id,), fetch='one')
            if initial_odo_result:
                last_odometer = initial_odo_result.get('initial_odometer', 0)

    return {
        "vehicles": all_vehicles, "selected_vehicle_id": _to_int(vehicle_id) if vehicle_id else None,
        "selected_year": year, "selected_month": month,
        "logs": logs, "refuelings": refuelings, "last_odometer": last_odometer or 0
    }

def save_daily_log(data):
    """Uloží/aktualizuje viacero denných záznamov v knihe jázd."""
    logs = data.get('logs')
    if not logs:
        return {"error": "Chýbajú dáta záznamov (logs)."}

    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        for log in logs:
            vehicle_id, log_date = log.get('vehicle_id'), log.get('log_date')
            if not vehicle_id or not log_date:
                continue

            def to_int(val): return int(val) if val is not None and str(val).strip() != '' else None
            def to_float(val): return float(val) if val is not None and str(val).strip() != '' else None

            params = {
                'vehicle_id': to_int(vehicle_id), 'log_date': log_date,
                'driver': log.get('driver') or None,
                'start_odometer': to_int(log.get('start_odometer')),
                'end_odometer': to_int(log.get('end_odometer')),
                'km_driven': to_int(log.get('km_driven')),
                'goods_out_kg': to_float(log.get('goods_out_kg')),
                'goods_in_kg': to_float(log.get('goods_in_kg')),
                'delivery_notes_count': to_int(log.get('delivery_notes_count')),
            }
            query = """
                INSERT INTO fleet_logs (
                    vehicle_id, log_date, driver, start_odometer, end_odometer, km_driven, goods_out_kg, goods_in_kg, delivery_notes_count
                )
                VALUES (
                    %(vehicle_id)s, %(log_date)s, %(driver)s, %(start_odometer)s, %(end_odometer)s, %(km_driven)s, %(goods_out_kg)s, %(goods_in_kg)s, %(delivery_notes_count)s
                ) AS new
                ON DUPLICATE KEY UPDATE
                    driver = new.driver,
                    start_odometer = new.start_odometer,
                    end_odometer = new.end_odometer,
                    km_driven = new.km_driven,
                    goods_out_kg = new.goods_out_kg,
                    goods_in_kg = new.goods_in_kg,
                    delivery_notes_count = new.delivery_notes_count
            """
            cursor.execute(query, params)
        
        conn.commit()
        return {"message": "Zmeny v knihe jázd boli úspešne uložené."}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected():
            conn.close()

def save_vehicle(data):
    """Uloží nové vozidlo alebo aktualizuje existujúce."""
    vehicle_id = data.get('id')
    required = ['license_plate', 'name', 'initial_odometer']
    if not all(field in data for field in required):
        return {"error": "ŠPZ, Názov a Počiatočný stav tachometra sú povinné."}
    params = (
        data['license_plate'], data['name'], data.get('type'),
        data.get('default_driver'), _to_int(data['initial_odometer'], 0)
    )
    if vehicle_id:
        query = "UPDATE fleet_vehicles SET license_plate=%s, name=%s, type=%s, default_driver=%s, initial_odometer=%s WHERE id=%s"
        db_connector.execute_query(query, params + (vehicle_id,), fetch='none')
        return {"message": "Údaje o vozidle boli aktualizované."}
    else:
        query = "INSERT INTO fleet_vehicles (license_plate, name, type, default_driver, initial_odometer) VALUES (%s, %s, %s, %s, %s)"
        try:
            db_connector.execute_query(query, params, fetch='none')
            return {"message": "Nové vozidlo bolo úspešne pridané."}
        except Exception as e:
            if 'UNIQUE constraint' in str(e) or 'Duplicate entry' in str(e):
                return {"error": f"Vozidlo s ŠPZ '{data['license_plate']}' už existuje."}
            raise e

def save_refueling(data):
    """Uloží nový záznam o tankovaní s automatickým výpočtom celkovej ceny."""
    required = ['vehicle_id', 'refueling_date', 'liters']
    if not all(field in data for field in required if data.get(field)):
        return {"error": "Chýbajú povinné polia (dátum, litre)."}
    
    liters = float(data.get('liters', 0))
    price_per_liter = float(data.get('price_per_liter', 0))
    total_price = liters * price_per_liter if price_per_liter > 0 else float(data.get('total_price', 0))
    
    params = (data['vehicle_id'], data['refueling_date'], data.get('driver'), liters, price_per_liter, total_price)
    query = "INSERT INTO fleet_refueling (vehicle_id, refueling_date, driver, liters, price_per_liter, total_price) VALUES (%s, %s, %s, %s, %s, %s)"
    db_connector.execute_query(query, params, fetch='none')
    return {"message": "Záznam o tankovaní bol úspešne pridaný."}

def delete_refueling(data):
    """Vymaže záznam o tankovaní."""
    refueling_id = data.get('id')
    if not refueling_id:
        return {"error": "Chýba ID záznamu na vymazanie."}
    db_connector.execute_query("DELETE FROM fleet_refueling WHERE id = %s", (refueling_id,), fetch='none')
    return {"message": "Záznam o tankovaní bol vymazaný."}

def get_fleet_analysis(vehicle_id, year, month):
    """Pripraví komplexnú analýzu pre vozidlo (náklady/kilometre/palivo)."""
    year = _to_int(year)
    month = _to_int(month)
    if not all([vehicle_id, year, month]):
        return {"error": "Chýbajú parametre pre analýzu."}

    log_summary_q = """
        SELECT SUM(km_driven) as total_km, SUM(goods_out_kg) as total_goods_out
        FROM fleet_logs
        WHERE vehicle_id = %s AND YEAR(log_date) = %s AND MONTH(log_date) = %s
    """
    log_summary = db_connector.execute_query(log_summary_q, (vehicle_id, year, month), 'one') or {}

    refueling_summary_q = """
        SELECT SUM(liters) as total_liters, SUM(total_price) as total_fuel_cost
        FROM fleet_refueling
        WHERE vehicle_id = %s AND YEAR(refueling_date) = %s AND MONTH(refueling_date) = %s
    """
    refueling_summary = db_connector.execute_query(refueling_summary_q, (vehicle_id, year, month), 'one') or {}
    
    start_of_month_dt = datetime(year, month, 1)
    end_of_month_dt = start_of_month_dt.replace(day=monthrange(year, month)[1])
    
    costs_q = """
        SELECT SUM(monthly_cost) as total_other_costs 
        FROM fleet_costs 
        WHERE (vehicle_id = %s OR vehicle_id IS NULL) 
          AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)
    """
    other_costs_result = db_connector.execute_query(costs_q, (vehicle_id, end_of_month_dt.date(), start_of_month_dt.date()), 'one') or {}
    
    total_km         = float(log_summary.get('total_km') or 0)
    total_goods_out  = float(log_summary.get('total_goods_out') or 0)
    total_fuel_cost  = float(refueling_summary.get('total_fuel_cost') or 0)
    total_liters     = float(refueling_summary.get('total_liters') or 0)
    total_other_costs= float(other_costs_result.get('total_other_costs') or 0)
    
    total_costs      = total_fuel_cost + total_other_costs
    cost_per_km      = (total_costs / total_km) if total_km > 0 else 0.0
    cost_per_kg_goods= ((total_costs * 1.1) / total_goods_out) if total_goods_out > 0 else 0.0
    avg_consumption  = ((total_liters / total_km) * 100) if total_km > 0 else 0.0

    return {
        "total_costs": total_costs, "total_km": total_km, "cost_per_km": cost_per_km,
        "total_goods_out_kg": total_goods_out, "cost_per_kg_goods": cost_per_kg_goods,
        "avg_consumption": avg_consumption
    }

def get_fleet_costs(vehicle_id=None):
    """Získa zoznam všetkých nákladov, buď pre vozidlo alebo všeobecné."""
    query = "SELECT * FROM fleet_costs WHERE vehicle_id = %s OR vehicle_id IS NULL ORDER BY valid_from DESC"
    return db_connector.execute_query(query, (vehicle_id,))

def save_fleet_cost(data):
    """Uloží nový alebo aktualizuje existujúci náklad."""
    cost_id = data.get('id') if data.get('id') else None
    required = ['cost_name', 'cost_type', 'monthly_cost', 'valid_from']
    if not all(field in data for field in required):
        return {"error": "Chýbajú povinné polia."}
    
    vehicle_id_to_save = data.get('vehicle_id') if data.get('is_vehicle_specific') else None
    
    params = (
        data['cost_name'], data['cost_type'], float(data['monthly_cost']),
        data['valid_from'], data.get('valid_to') or None, vehicle_id_to_save
    )

    if cost_id:
        query = "UPDATE fleet_costs SET cost_name=%s, cost_type=%s, monthly_cost=%s, valid_from=%s, valid_to=%s, vehicle_id=%s WHERE id=%s"
        db_connector.execute_query(query, params + (cost_id,), fetch='none')
        return {"message": "Náklad bol aktualizovaný."}
    else:
        query = "INSERT INTO fleet_costs (cost_name, cost_type, monthly_cost, valid_from, valid_to, vehicle_id) VALUES (%s, %s, %s, %s, %s, %s)"
        db_connector.execute_query(query, params, fetch='none')
        return {"message": "Nový náklad bol pridaný."}

def delete_fleet_cost(data):
    """Vymaže náklad z databázy."""
    cost_id = data.get('id')
    if not cost_id:
        return {"error": "Chýba ID nákladu."}
    db_connector.execute_query("DELETE FROM fleet_costs WHERE id = %s", (cost_id,), fetch='none')
    return {"message": "Náklad bol vymazaný."}

def get_report_html_content(vehicle_id, year, month):
    """Pripraví HTML obsah pre tlačový report."""
    year = _to_int(year)
    month = _to_int(month)
    if not all([vehicle_id, year, month]):
        return make_response("<h1>Chyba: Chýbajú parametre pre report.</h1>", 400)

    data = get_fleet_data(vehicle_id, year, month)
    analysis = get_fleet_analysis(vehicle_id, year, month)
    
    start_of_month = datetime(year, month, 1)
    end_of_month = start_of_month.replace(day=monthrange(year, month)[1])
    
    costs_q = """
        SELECT * FROM fleet_costs 
        WHERE (vehicle_id = %s OR vehicle_id IS NULL) 
          AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)
    """
    all_costs = db_connector.execute_query(costs_q, (vehicle_id, end_of_month.date(), start_of_month.date()))

    fixed_costs = [c for c in all_costs if c['cost_type'] in ['MZDA', 'POISTENIE', 'DIALNICNA', 'INE']]
    variable_costs = [c for c in all_costs if c['cost_type'] in ['SERVIS', 'PNEUMATIKY', 'SKODA']]

    template_data = {
        "vehicle": next((v for v in data['vehicles'] if v['id'] == vehicle_id), {}),
        "period": f"{month:02d}/{year}",
        "logs": data['logs'],
        "refuelings": data['refuelings'],
        "analysis": analysis,
        "fixed_costs": fixed_costs,
        "variable_costs": variable_costs
    }
    return make_response(render_template('fleet_report_template.html', **template_data))
