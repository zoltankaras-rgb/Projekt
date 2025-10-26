# =================================================================
# === HANDLER PRE MODUL: HYGIENICKÝ REŽIM (PROFESIONÁLNA VERZIA) ===
# =================================================================

import db_connector
from datetime import datetime, date, timedelta

def get_hygiene_plan_for_date(target_date_str=None):
    """
    Zostaví denný plán hygieny pre zadaný dátum, vrátane detailov o splnení a kontrole.
    """
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date() if target_date_str else date.today()
    except ValueError:
        target_date = date.today()

    all_tasks_query = "SELECT id, task_name, location, frequency, description, default_agent_id, default_concentration, default_exposure_time FROM hygiene_tasks WHERE is_active = TRUE ORDER BY location, task_name"
    all_tasks = db_connector.execute_query(all_tasks_query)

    completed_log_query = "SELECT * FROM hygiene_log WHERE completion_date = %s"
    completed_logs = db_connector.execute_query(completed_log_query, (target_date,))
    completed_logs_map = {log['task_id']: log for log in completed_logs}

    plan_by_location = {}
    
    for task in all_tasks:
        is_due = False
        freq = task['frequency']
        if freq == 'denne': is_due = True
        elif freq == 'tyzdenne' and target_date.weekday() == 0: is_due = True
        elif freq == 'mesacne' and target_date.day == 1: is_due = True
        elif freq == 'stvrtronne' and target_date.day == 1 and target_date.month in [1, 4, 7, 10]: is_due = True
        elif freq == 'rocne' and target_date.day == 1 and target_date.month == 1: is_due = True

        if is_due:
            location = task['location']
            if location not in plan_by_location:
                plan_by_location[location] = []
            
            task['completion_details'] = completed_logs_map.get(task['id'])
            plan_by_location[location].append(task)
            
    return {"plan": plan_by_location, "date": target_date.strftime('%Y-%m-%d')}

def get_hygiene_agents():
    """Vráti zoznam všetkých aktívnych čistiacich prostriedkov."""
    return db_connector.execute_query("SELECT id, agent_name FROM hygiene_agents WHERE is_active = TRUE ORDER BY agent_name")

def save_hygiene_agent(data):
    """Uloží nový alebo aktualizuje existujúci čistiaci prostriedok."""
    agent_id, agent_name = data.get('id'), data.get('agent_name')
    if not agent_name: return {"error": "Názov prostriedku je povinný."}
    is_active = data.get('is_active', True)
    if agent_id:
        db_connector.execute_query("UPDATE hygiene_agents SET agent_name = %s, is_active = %s WHERE id = %s", (agent_name, is_active, agent_id), fetch='none')
        return {"message": "Prostriedok bol aktualizovaný."}
    else:
        db_connector.execute_query("INSERT INTO hygiene_agents (agent_name, is_active) VALUES (%s, %s)", (agent_name, is_active), fetch='none')
        return {"message": "Nový prostriedok bol pridaný."}

def get_all_hygiene_tasks():
    """Vráti zoznam všetkých definovaných hygienických úloh pre administráciu."""
    return db_connector.execute_query("SELECT * FROM hygiene_tasks ORDER BY location, task_name")

def save_hygiene_task(data):
    """Uloží novú alebo aktualizuje existujúcu hygienickú úlohu s predvoľbami."""
    task_id = data.get('id')
    required = ['task_name', 'location', 'frequency']
    if not all(field in data for field in required): return {"error": "Názov, umiestnenie a frekvencia sú povinné."}
    params = (data['task_name'], data['location'], data['frequency'], data.get('description', ''), data.get('default_agent_id') or None, data.get('default_concentration'), data.get('default_exposure_time'), data.get('is_active', True))
    if task_id:
        query = "UPDATE hygiene_tasks SET task_name=%s, location=%s, frequency=%s, description=%s, default_agent_id=%s, default_concentration=%s, default_exposure_time=%s, is_active=%s WHERE id=%s"
        db_connector.execute_query(query, params + (task_id,), fetch='none')
        return {"message": "Úloha bola aktualizovaná."}
    else:
        query = "INSERT INTO hygiene_tasks (task_name, location, frequency, description, default_agent_id, default_concentration, default_exposure_time, is_active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        db_connector.execute_query(query, params, fetch='none')
        return {"message": "Nová úloha bola vytvorená."}

def log_hygiene_completion(data):
    """Zapíše detailný záznam o splnení úlohy, teraz už aj s menom vykonávajúceho."""
    task_id, completion_date, user_info, performer_name = data.get('task_id'), data.get('completion_date'), data.get('user'), data.get('performer_name')
    if not all([task_id, completion_date, user_info, performer_name]): return {"error": "Chýbajú povinné údaje."}
    if db_connector.execute_query("SELECT id FROM hygiene_log WHERE task_id = %s AND completion_date = %s", (task_id, completion_date), fetch='one'):
        return {"message": "Úloha už bola pre daný deň zapísaná."}
    params = (task_id, completion_date, user_info.get('id'), performer_name, data.get('agent_id') or None, data.get('concentration'), data.get('exposure_time'), data.get('notes', ''))
    insert_query = "INSERT INTO hygiene_log (task_id, completion_date, user_id, user_fullname, agent_id, concentration, exposure_time, notes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    db_connector.execute_query(insert_query, params, fetch='none')
    return {"message": "Úloha bola zaznamenaná ako splnená."}

def check_hygiene_log(data):
    """Zaznamená kontrolu vykonanej úlohy."""
    log_id, user_info = data.get('log_id'), data.get('user')
    if not all([log_id, user_info]): return {"error": "Chýbajú povinné údaje."}
    params = (user_info.get('full_name'), datetime.now(), log_id)
    db_connector.execute_query("UPDATE hygiene_log SET checked_by_fullname = %s, checked_at = %s WHERE id = %s", params, 'none')
    return {"message": "Úloha skontrolovaná."}

def get_hygiene_report_data(report_date_str, period='denne'):
    """Pripraví dáta pre tlačový report pre RVPS pre rôzne obdobia."""
    if not report_date_str: return None
    try:
        base_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
    except ValueError:
        return None

    if period == 'tyzdenne':
        start_date = base_date - timedelta(days=base_date.weekday())
        end_date = start_date + timedelta(days=4)
        title = f"Týždenný Záznam o Vykonaní Sanitácie ({start_date.strftime('%d.%m.')} - {end_date.strftime('%d.%m.%Y')})"
    elif period == 'mesacne':
        start_date = base_date.replace(day=1)
        end_date = (start_date + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        title = f"Mesačný Záznam o Vykonaní Sanitácie ({start_date.strftime('%m/%Y')})"
    else:
        start_date = end_date = base_date
        title = f"Denný Záznam o Vykonaní Sanitácie ({start_date.strftime('%d.%m.%Y')})"
        
    query = """
        SELECT ht.task_name, ht.location, hl.user_fullname, hl.completion_date, ha.agent_name,
               hl.concentration, hl.exposure_time, hl.checked_by_fullname, hl.checked_at
        FROM hygiene_log hl JOIN hygiene_tasks ht ON hl.task_id = ht.id LEFT JOIN hygiene_agents ha ON hl.agent_id = ha.id
        WHERE hl.completion_date BETWEEN %s AND %s ORDER BY hl.completion_date, ht.location, ht.task_name
    """
    records = db_connector.execute_query(query, (start_date, end_date))
    
    # OPRAVA: Namiesto zoskupovania tu, posielame priamo zoznam záznamov
    return {"records": records, "title": title, "period_str": f"{start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}"}

