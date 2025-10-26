# =================================================================
# === HANDLER PRE MODUL: SPRÁVA NÁKLADOV (upravené, kompatibilné) ===
# =================================================================

import db_connector
from datetime import datetime
import profitability_handler  # Pre prístup k výnosom (dashboard)

def _ym_int(year, month):
    return int(year), int(month)

def get_costs_data(year, month):
    """Získa všetky dáta o nákladoch pre zadané obdobie (DB-kompat)."""
    year, month = _ym_int(year, month)

    electricity = db_connector.execute_query(
        "SELECT * FROM costs_energy_electricity WHERE record_year = %s AND record_month = %s",
        (year, month), 'one'
    ) or {}
    gas = db_connector.execute_query(
        "SELECT * FROM costs_energy_gas WHERE record_year = %s AND record_month = %s",
        (year, month), 'one'
    ) or {}
    hr = db_connector.execute_query(
        "SELECT * FROM costs_hr WHERE record_year = %s AND record_month = %s",
        (year, month), 'one'
    ) or {}

    op_costs_q = """
        SELECT ci.*, cc.category_name AS category_name
        FROM costs_items ci
        JOIN costs_categories cc ON ci.category_id = cc.id
        WHERE YEAR(ci.entry_date) = %s AND MONTH(ci.entry_date) = %s
        ORDER BY ci.entry_date DESC
    """
    operational_costs = db_connector.execute_query(op_costs_q, (year, month))

    # Kategórie – DB má 'category_name' a nemá 'is_active'; pošli v tvare, ktorý chce FE
    categories = db_connector.execute_query(
        "SELECT id, category_name AS name FROM costs_categories ORDER BY category_name"
    )

    return {
        "energy": {"electricity": electricity, "gas": gas},
        "hr": hr,
        "operational": {"items": operational_costs, "categories": categories},
    }

def save_energy_data(data):
    """Uloží dáta o energiách (elektrina aj plyn) – DB-kompat, bez deprecated VALUES()."""
    year, month = _ym_int(data.get('year'), data.get('month'))

    # -------------------- ELEKTRINA --------------------
    el = data.get('electricity', {}) or {}
    # Mapovanie kľúčov: podpor oba názvy (FE môže posielať odpis_vse, my v DB máme merana_spotreba_kwh)
    merana_spotreba_kwh = el.get('merana_spotreba_kwh', el.get('odpis_vse'))
    fakturacia_vse      = el.get('fakturacia_vse')
    rozdiel_vse         = el.get('rozdiel_vse')
    fakturacia_vse_nt   = el.get('fakturacia_vse_nt')
    rozdiel_vse_nt      = el.get('rozdiel_vse_nt')
    faktura_s_dph       = el.get('faktura_s_dph')

    try:
        faktura_s_dph_f = float(faktura_s_dph) if faktura_s_dph not in (None, '') else 0.0
    except (TypeError, ValueError):
        faktura_s_dph_f = 0.0
    # Biznis koeficient podľa pôvodného kódu
    final_cost = (faktura_s_dph_f / 4.68) if faktura_s_dph_f else 0.0

    el_params = (
        year, month,
        float(merana_spotreba_kwh) if merana_spotreba_kwh not in (None, '') else None,
        float(fakturacia_vse) if fakturacia_vse not in (None, '') else None,
        float(fakturacia_vse_nt) if fakturacia_vse_nt not in (None, '') else None,
        float(rozdiel_vse) if rozdiel_vse not in (None, '') else None,
        float(rozdiel_vse_nt) if rozdiel_vse_nt not in (None, '') else None,
        faktura_s_dph_f, final_cost
    )
    el_q = """
        INSERT INTO costs_energy_electricity
          (record_year, record_month, merana_spotreba_kwh, fakturacia_vse, fakturacia_vse_nt, rozdiel_vse, rozdiel_vse_nt, faktura_s_dph, final_cost)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) AS new
        ON DUPLICATE KEY UPDATE
          merana_spotreba_kwh = new.merana_spotreba_kwh,
          fakturacia_vse      = new.fakturacia_vse,
          fakturacia_vse_nt   = new.fakturacia_vse_nt,
          rozdiel_vse         = new.rozdiel_vse,
          rozdiel_vse_nt      = new.rozdiel_vse_nt,
          faktura_s_dph       = new.faktura_s_dph,
          final_cost          = new.final_cost
    """
    db_connector.execute_query(el_q, el_params, 'none')

    # -------------------- PLYN --------------------
    gas_data = data.get('gas', {}) or {}
    # DB stĺpce: potreba_kwh, ... (FE môže posielať spotreba_kwh -> ulož ako potreba_kwh)
    potreba_kwh = gas_data.get('potreba_kwh', gas_data.get('spotreba_kwh'))
    params_gas = (
        year, month,
        float(potreba_kwh or 0),
        float(gas_data.get('nakup_plynu_eur') or 0),
        float(gas_data.get('distribucia_eur') or 0),
        float(gas_data.get('poplatok_okte_eur') or 0),
        float(gas_data.get('straty_eur') or 0),
        float(gas_data.get('spolu_bez_dph') or 0),
        float(gas_data.get('dph') or 0),
        float(gas_data.get('spolu_s_dph') or 0),
        int(gas_data.get('stav_odpisany') or 0),
        int(gas_data.get('stav_fakturovany') or 0),
    )
    gas_q = """
        INSERT INTO costs_energy_gas
          (record_year, record_month, potreba_kwh, nakup_plynu_eur, distribucia_eur, poplatok_okte_eur, straty_eur, spolu_bez_dph, dph, spolu_s_dph, stav_odpisany, stav_fakturovany)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS new
        ON DUPLICATE KEY UPDATE
          potreba_kwh      = new.potreba_kwh,
          nakup_plynu_eur  = new.nakup_plynu_eur,
          distribucia_eur  = new.distribucia_eur,
          poplatok_okte_eur= new.poplatok_okte_eur,
          straty_eur       = new.straty_eur,
          spolu_bez_dph    = new.spolu_bez_dph,
          dph              = new.dph,
          spolu_s_dph      = new.spolu_s_dph,
          stav_odpisany    = new.stav_odpisany,
          stav_fakturovany = new.stav_fakturovany
    """
    db_connector.execute_query(gas_q, params_gas, 'none')

    return {"message": "Dáta o energiách boli uložené."}

def save_hr_data(data):
    year, month = _ym_int(data.get('year'), data.get('month'))
    params = (year, month, float(data.get('total_salaries') or 0), float(data.get('total_levies') or 0))
    query = """
        INSERT INTO costs_hr (record_year, record_month, total_salaries, total_levies)
        VALUES (%s, %s, %s, %s) AS new
        ON DUPLICATE KEY UPDATE
          total_salaries = new.total_salaries,
          total_levies   = new.total_levies
    """
    db_connector.execute_query(query, params, 'none')
    return {"message": "Dáta o ľudských zdrojoch boli uložené."}

def save_operational_cost(data):
    item_id = data.get('id')
    required = ['entry_date', 'category_id', 'name', 'amount_net']
    if not all(field in data and data[field] for field in required):
        return {"error": "Chýbajú povinné údaje."}
    params = (
        data['entry_date'],
        int(data['category_id']),
        data['name'],
        data.get('description', ''),
        float(data['amount_net']),
        bool(data.get('is_recurring'))
    )
    if item_id:
        db_connector.execute_query(
            "UPDATE costs_items SET entry_date=%s, category_id=%s, name=%s, description=%s, amount_net=%s, is_recurring=%s WHERE id=%s",
            params + (item_id,), fetch='none'
        )
        return {"message": "Náklad bol aktualizovaný."}
    else:
        db_connector.execute_query(
            "INSERT INTO costs_items (entry_date, category_id, name, description, amount_net, is_recurring) VALUES (%s, %s, %s, %s, %s, %s)",
            params, fetch='none'
        )
        return {"message": "Nový náklad bol pridaný."}

def delete_operational_cost(data):
    item_id = data.get('id')
    if not item_id:
        return {"error": "Chýba ID nákladu."}
    db_connector.execute_query("DELETE FROM costs_items WHERE id = %s", (item_id,), 'none')
    return {"message": "Náklad bol vymazaný."}

def save_cost_category(data):
    name = (data.get('name') or '').strip()
    if not name:
        return {"error": "Názov kategórie nemôže byť prázdny."}
    try:
        db_connector.execute_query("INSERT INTO costs_categories (category_name) VALUES (%s)", (name,), 'none')
        return {"message": f"Kategória '{name}' bola úspešne pridaná."}
    except Exception as e:
        if 'Duplicate entry' in str(e):
            return {"error": f"Kategória s názvom '{name}' už existuje."}
        raise e

def get_dashboard_data(year, month):
    year, month = _ym_int(year, month)
    profit_data = profitability_handler.get_profitability_data(year, month)
    total_revenue = float(profit_data.get('department_data', {}).get('exp_revenue', 0) or 0)

    costs_data = get_costs_data(year, month)

    # Pretypovanie všetkých hodnôt na float pred sčítaním
    el_cost = float(costs_data.get('energy', {}).get('electricity', {}).get('final_cost', 0) or 0)
    gas_cost = float(costs_data.get('energy', {}).get('gas', {}).get('spolu_s_dph', 0) or 0)
    hr_cost = float(costs_data.get('hr', {}).get('total_salaries', 0) or 0) + float(costs_data.get('hr', {}).get('total_levies', 0) or 0)

    op_costs_by_cat = {}
    for item in costs_data.get('operational', {}).get('items', []) or []:
        cat_name = item.get('category_name') or 'Nezaradené'
        op_costs_by_cat[cat_name] = op_costs_by_cat.get(cat_name, 0) + float(item.get('amount_net') or 0)

    total_op_cost = sum(op_costs_by_cat.values())
    total_costs = el_cost + gas_cost + hr_cost + total_op_cost
    net_profit = total_revenue - total_costs

    return {
        "summary": {"total_revenue": total_revenue, "total_costs": total_costs, "net_profit": net_profit},
        "breakdown": {"Energia - Elektrina": el_cost, "Energia - Plyn": gas_cost, "Ľudské zdroje": hr_cost, **op_costs_by_cat},
    }
