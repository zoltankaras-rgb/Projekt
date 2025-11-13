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

from datetime import datetime, timedelta
import db_connector

def _combine_date_time(date_str: str, time_str: str | None) -> datetime:
    """Poskladá datetime z 'YYYY-MM-DD' a 'HH:MM' (alebo 'HH:MM:SS'); fallback = teraz."""
    try:
        base = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        base = datetime.now()
    if not time_str:
        # ak neprišlo, začiatok je teraz (zmysluplnejšie pre reálnu prevádzku)
        return datetime.now()
    time_str = time_str.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(time_str, fmt).time()
            return datetime.combine(base.date(), t)
        except Exception:
            continue
    # fallback
    return datetime.now()

def log_hygiene_completion(data):
    """
    Zapíše splnenie úlohy.
    Nové: prijíma 'start_time' (HH:MM), automaticky vypočíta:
      - exposure_end_at = start + 15 min
      - rinse_end_at    = exposure_end_at + 10 min
      - finished_at     = rinse_end_at
    Zmäkčené: 'user' v requeste nie je povinný (ID môže byť NULL), stačí performer_name.
    """
    task_id = data.get('task_id')
    completion_date = data.get('completion_date')  # 'YYYY-MM-DD'
    performer_name = (data.get('performer_name') or '').strip()
    user_info = data.get('user') or {}  # nemusí byť prítomné
    if not all([task_id, completion_date, performer_name]):
        return {"error": "Chýbajú povinné údaje."}

    # unikát: 1 záznam na task_id + deň (ponechávam podľa tvojej logiky)
    if db_connector.execute_query(
        "SELECT id FROM hygiene_log WHERE task_id = %s AND completion_date = %s",
        (task_id, completion_date), fetch='one'
    ):
        return {"message": "Úloha už bola pre daný deň zapísaná."}

    # výpočet časov
    start_dt = _combine_date_time(completion_date, data.get('start_time'))
    exposure_end_dt = start_dt + timedelta(minutes=15)
    rinse_end_dt = exposure_end_dt + timedelta(minutes=10)
    finished_dt = rinse_end_dt

    params = (
        task_id,
        completion_date,
        user_info.get('id') if isinstance(user_info, dict) else None,
        performer_name,
        data.get('agent_id') or None,
        data.get('concentration'),
        data.get('exposure_time'),
        data.get('notes', ''),
        start_dt,
        exposure_end_dt,
        rinse_end_dt,
        finished_dt,
    )

    insert_query = """
        INSERT INTO hygiene_log (
            task_id, completion_date, user_id, user_fullname, agent_id, concentration, exposure_time, notes,
            start_at, exposure_end_at, rinse_end_at, finished_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    db_connector.execute_query(insert_query, params, fetch='none')
    return {"message": "Úloha bola zaznamenaná ako splnená."}




def check_hygiene_log(data):
    """
    Označí záznam hygieny ako skontrolovaný.
    Očakáva: {"log_id": <int>, "checker_name": <str optional>}
    Ak checker_name nie je, skús user.fullname, inak použijeme "Kontrolór".
    """
    if not data or not data.get('log_id'):
        return {"error": "Chýba log_id."}, 400

    log_id = int(data['log_id'])
    checker = (data.get('checker_name') or '').strip()
    if not checker:
        user = data.get('user') or {}
        checker = (user.get('fullname') or '').strip() or "Kontrolór"

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db_connector.execute_query(
        "UPDATE hygiene_log SET checked_by_fullname=%s, checked_at=%s WHERE id=%s",
        (checker, now, log_id),
        fetch='none'
    )
    return {"message": "Kontrola potvrdená.", "checked_by_fullname": checker}



def get_hygiene_report_data(date_str: str, period: str = 'denne'):
    """
    Vráti dáta pre report aj s časmi: start_at, exposure_end_at, rinse_end_at, finished_at.
    """
    if not date_str:
        return None
    try:
        base = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None

    if period == 'denne':
        start, end = base, base
        title = f"Denný záznam o vykonaní sanitácie ({base.strftime('%d.%m.%Y')})"
        period_str = base.strftime("%d.%m.%Y")
    elif period == 'tyzdenne':
        start = base - timedelta(days=base.weekday())
        end = start + timedelta(days=6)
        title = f"Týždenný záznam o vykonaní sanitácie ({start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')})"
        period_str = f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"
    else:
        start = date(base.year, base.month, 1)
        if base.month == 12:
            end = date(base.year, 12, 31)
        else:
            from calendar import monthrange
            end = date(base.year, base.month, monthrange(base.year, base.month)[1])
        title = f"Mesačný záznam o vykonaní sanitácie ({start.strftime('%m/%Y')})"
        period_str = f"{start.strftime('%m/%Y')}"

    q = """
        SELECT 
            l.completion_date,
            t.location,
            t.task_name,
            l.user_fullname,
            a.agent_name,
            l.concentration,
            l.exposure_time,
            l.start_at,
            l.exposure_end_at,
            l.rinse_end_at,
            l.finished_at,
            l.checked_by_fullname
        FROM hygiene_log l
        JOIN hygiene_tasks t ON t.id = l.task_id
        LEFT JOIN hygiene_agents a ON a.id = l.agent_id
        WHERE l.completion_date >= %s AND l.completion_date <= %s
        ORDER BY l.completion_date, t.location, t.task_name
    """
    rows = db_connector.execute_query(q, (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))) or []

    # transformácia (formátovanie časov na HH:MM)
    recs = []
    for r in rows:
        def fmt(dt):
            if not dt: return ''
            s = str(dt)
            # dt môže byť datetime/dátumový string; ber len čas HH:MM
            try:
                if len(s) >= 16:
                    return s[11:16]
                return s
            except Exception:
                return ''
        recs.append({
            "completion_date": r.get("completion_date"),
            "location": r.get("location"),
            "task_name": r.get("task_name"),
            "user_fullname": r.get("user_fullname"),
            "agent_name": r.get("agent_name"),
            "concentration": r.get("concentration"),
            "exposure_time": r.get("exposure_time"),
            "start_at": fmt(r.get("start_at")),
            "exposure_end_at": fmt(r.get("exposure_end_at")),
            "rinse_end_at": fmt(r.get("rinse_end_at")),
            "finished_at": fmt(r.get("finished_at")),
            "checked_by_fullname": r.get("checked_by_fullname"),
        })

    return {"title": title, "period_str": period_str, "records": recs}
