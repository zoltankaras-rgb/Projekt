# =================================================================
# === HANDLER: SIMULOVANÉ TEPLOTY CHLADNIČIEK/MRAZIAKOV/PRIESTOROV
# =================================================================
import os
import random
import threading
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

import db_connector
from flask import jsonify, make_response, render_template

# Konštanty pre typy zariadení
TYPE_CHLAD = 'CHLAD'
TYPE_MRAZ = 'MRAZ'
TYPE_ROZRABKA = 'ROZRABKA'

# Bit masky dní: Po=1, Ut=2, St=4, Št=8, Pi=16, So=32, Ne=64
DOW_BIT = {0:1, 1:2, 2:4, 3:8, 4:16, 5:32, 6:64}

# --- UTIL ---------------------------------------------------------------------
def _now():
    return datetime.now()  # lokálny čas

def _minutes_since_midnight(dt: datetime) -> int:
    return dt.hour*60 + dt.minute

def _quarter_floor(dt: datetime) -> datetime:
    q = (dt.minute // 15) * 15
    return dt.replace(minute=q, second=0, microsecond=0)

def _quarter_next(dt: datetime) -> datetime:
    base = _quarter_floor(dt)
    nxt = base + timedelta(minutes=15)
    return nxt

def _rand_temp(device_type: str) -> float:
    if device_type == TYPE_CHLAD:
        return round(random.uniform(0.0, 4.2), 1)
    if device_type == TYPE_MRAZ:
        return round(random.uniform(-19.9, -17.0), 1)
    if device_type == TYPE_ROZRABKA:
        return round(random.uniform(2.0, 5.0), 1)
    return 0.0

# --- DB LAYER -----------------------------------------------------------------
def _fetch_devices() -> List[Dict[str, Any]]:
    q = """SELECT * FROM temps_devices WHERE is_active=1 ORDER BY id"""
    return db_connector.execute_query(q) or []

def _fetch_outages_for_devices(device_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    if not device_ids:
        return {}
    placeholders = ",".join(["%s"]*len(device_ids))
    q = f"SELECT * FROM temps_outages WHERE is_enabled=1 AND device_id IN ({placeholders})"
    rows = db_connector.execute_query(q, tuple(device_ids)) or []
    m: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        m.setdefault(r['device_id'], []).append(r)
    return m

def _is_off_now(device: Dict[str, Any], outages: List[Dict[str, Any]], dt: datetime) -> bool:
    # manuálne OFF má prioritu
    if device.get('manual_off'):
        return True
    if not outages:
        return False
    dow = dt.weekday()  # Po=0..Ne=6
    minutes = _minutes_since_midnight(dt)
    for o in outages:
        # dátumové okno
        df = o.get('date_from')
        dt_ = o.get('date_to')
        if df and dt_:
            if not (df <= dt.date() <= dt_):
                continue
        # ak maska je 0, ber pocely deň, inak skontroluj bit
        mask = int(o.get('dow_mask') or 0)
        if mask != 0 and (DOW_BIT[dow] & mask) == 0:
            continue
        start_m = int(o.get('start_minute') or 0)
        end_m   = int(o.get('end_minute') or 1439)
        if start_m <= minutes <= end_m:
            return True
    return False

def _upsert_reading(device_id: int, ts: datetime, temp: float, status: str):
    q = """
    INSERT INTO temps_readings (device_id, ts, temperature, status)
    VALUES (%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE temperature=VALUES(temperature), status=VALUES(status)
    """
    db_connector.execute_query(q, (device_id, ts, temp if status=='OK' else None, status), fetch='none')

# --- PUBLIC API LOGIKA --------------------------------------------------------
def list_devices():
    rows = db_connector.execute_query("SELECT * FROM temps_devices ORDER BY id DESC") or []
    return jsonify(rows)

def save_device(data):
    # {id?, code, name, location, device_type, is_active, manual_off}
    fields = ['code','name','location','device_type','is_active','manual_off']
    vals = [data.get(k) for k in fields]
    if not vals[0] or not vals[1] or not vals[2] or not vals[3]:
        return {"error": "Chýbajú povinné polia (code, name, location, device_type)."}
    # normalizácia
    vals[4] = 1 if str(vals[4]) in ('1','true','True','on') else 0
    vals[5] = 1 if str(vals[5]) in ('1','true','True','on') else 0

    if data.get('id'):
        q = """UPDATE temps_devices SET code=%s,name=%s,location=%s,device_type=%s,is_active=%s,manual_off=%s WHERE id=%s"""
        db_connector.execute_query(q, tuple(vals)+ (int(data['id']),), fetch='none')
    else:
        q = """INSERT INTO temps_devices (code,name,location,device_type,is_active,manual_off) VALUES (%s,%s,%s,%s,%s,%s)"""
        db_connector.execute_query(q, tuple(vals), fetch='none')

    return {"message":"Uložené."}

def set_manual_off(data):
    # {id, manual_off}
    if not data.get('id'):
        return {"error":"Chýba id."}
    val = 1 if str(data.get('manual_off')) in ('1','true','True','on') else 0
    db_connector.execute_query("UPDATE temps_devices SET manual_off=%s WHERE id=%s", (val, int(data['id'])), fetch='none')
    return {"message":"Nastavené."}

def save_outage(data):
    # {id?, device_id, enabled, mon..sun bool, start_time 'HH:MM', end_time 'HH:MM', date_from?, date_to?}
    if not data.get('device_id'):
        return {"error":"Chýba device_id."}
    mask = 0
    # PO..NE (mon..sun) -> Po=mon
    if str(data.get('mon')) in ('1','true','on','True'): mask |= 1
    if str(data.get('tue')) in ('1','true','on','True'): mask |= 2
    if str(data.get('wed')) in ('1','true','on','True'): mask |= 4
    if str(data.get('thu')) in ('1','true','on','True'): mask |= 8
    if str(data.get('fri')) in ('1','true','on','True'): mask |= 16
    if str(data.get('sat')) in ('1','true','on','True'): mask |= 32
    if str(data.get('sun')) in ('1','true','on','True'): mask |= 64

    def to_min(tstr):
        if not tstr: return 0
        hh, mm = tstr.split(':')
        return int(hh)*60+int(mm)

    start_m = to_min(data.get('start_time') or '00:00')
    end_m   = to_min(data.get('end_time') or '23:59')
    enabled = 1 if str(data.get('enabled')) in ('1','true','True','on') else 0

    params = (
        int(data['device_id']),
        enabled, mask, start_m, end_m,
        data.get('date_from') or None,
        data.get('date_to') or None
    )

    if data.get('id'):
        q = """UPDATE temps_outages
               SET is_enabled=%s, dow_mask=%s, start_minute=%s, end_minute=%s, date_from=%s, date_to=%s
               WHERE id=%s AND device_id=%s"""
        db_connector.execute_query(q, (enabled,mask,start_m,end_m, data.get('date_from') or None, data.get('date_to') or None, int(data['id']), int(data['device_id'])), fetch='none')
    else:
        q = """INSERT INTO temps_outages (device_id, is_enabled, dow_mask, start_minute, end_minute, date_from, date_to)
               VALUES (%s,%s,%s,%s,%s,%s,%s)"""
        db_connector.execute_query(q, params, fetch='none')
    return {"message":"Výluka uložená."}

def get_readings_for_date(device_id: int|None, date_str: str, to_now: bool=False):
    # date_str = 'YYYY-MM-DD'
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return make_response("Neplatný dátum.", 400)

    start = datetime(day.year, day.month, day.day, 0, 0, 0)
    end   = datetime(day.year, day.month, day.day, 23, 59, 59, 999999)
    if to_now:
        now = _now()
        if now.date() == day:
            end = now

    if device_id:
        q = """SELECT r.*, d.name, d.code, d.location, d.device_type
               FROM temps_readings r
               JOIN temps_devices d ON d.id=r.device_id
               WHERE r.device_id=%s AND r.ts >= %s AND r.ts <= %s
               ORDER BY r.ts"""
        rows = db_connector.execute_query(q, (int(device_id), start, end)) or []
        return jsonify(rows)
    else:
        q = """SELECT r.*, d.name, d.code, d.location, d.device_type
               FROM temps_readings r
               JOIN temps_devices d ON d.id=r.device_id
               WHERE r.ts >= %s AND r.ts <= %s
               ORDER BY d.id, r.ts"""
        rows = db_connector.execute_query(q, (start, end)) or []
        return jsonify(rows)
def _build_summary_grid(device_rows, start: datetime, end: datetime):
    """
    Vytvorí maticu:
      - slots: [datetime, ...] v 15-min intervaloch (od start po end_floor)
      - headers: zoznam zariadení (device_rows)
      - cells: dict[slot][device_id] = {'status': 'OK'|'OFF'|'MISS', 'temp': float|None}
    """
    # vypočítaj sloty po 15 minútach
    def quarter_floor(dt: datetime):
        q = (dt.minute // 15) * 15
        return dt.replace(minute=q, second=0, microsecond=0)
    def next_quarter(dt: datetime):
        base = quarter_floor(dt)
        return base + timedelta(minutes=15)

    slots = []
    cur = quarter_floor(start)
    end_floor = quarter_floor(end)
    while cur <= end_floor:
        slots.append(cur)
        cur = cur + timedelta(minutes=15)

    # načítaj všetky readings naraz
    ids = [d['id'] for d in device_rows]
    if not ids:
        return slots, device_rows, {}

    placeholders = ",".join(["%s"]*len(ids))
    q = f"""SELECT r.* FROM temps_readings r
            WHERE r.device_id IN ({placeholders})
              AND r.ts >= %s AND r.ts <= %s
            ORDER BY r.device_id, r.ts"""
    rows = db_connector.execute_query(q, tuple(ids)+ (start, end)) or []

    # indexuj podľa (device_id, ts)
    by_key = {}
    for r in rows:
        by_key[(r['device_id'], r['ts'])] = r

    # vyplň maticu
    cells = {}  # slot -> device_id -> cell
    for slot in slots:
        cells[slot] = {}
        for d in device_rows:
            key = (d['id'], slot)
            r = by_key.get(key)
            if r:
                if r['status'] == 'OFF':
                    cells[slot][d['id']] = {'status':'OFF', 'temp': None}
                else:
                    cells[slot][d['id']] = {'status':'OK', 'temp': float(r['temperature']) if r['temperature'] is not None else None}
            else:
                cells[slot][d['id']] = {'status':'MISS', 'temp': None}
    return slots, device_rows, cells

def report_html(date_str: str, device_id: int|None, to_now: bool=False, layout: str='detail'):
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return make_response("<h1>Chyba: Neplatný dátum.</h1>", 400)

    start = datetime(day.year, day.month, day.day, 0, 0, 0)
    end   = datetime(day.year, day.month, day.day, 23, 59, 59, 999999)
    range_end_label = "23:59"
    if to_now:
        now = _now()
        if now.date() == day:
            end = now
            range_end_label = now.strftime("%H:%M")

    if device_id:
        devs = db_connector.execute_query("SELECT * FROM temps_devices WHERE id=%s", (int(device_id),)) or []
    else:
        devs = db_connector.execute_query("SELECT * FROM temps_devices WHERE is_active=1 ORDER BY id") or []

    if layout == 'summary':
        slots, headers, cells = _build_summary_grid(devs, start, end)
        return make_response(render_template("temps_report_summary.html",
                                             date=day,
                                             range_end_label=range_end_label,
                                             slots=slots, headers=headers, cells=cells))
    # default: detail (pôvodné)
    result = []
    for d in devs:
        rows = db_connector.execute_query(
            "SELECT * FROM temps_readings WHERE device_id=%s AND ts>=%s AND ts<=%s ORDER BY ts",
            (d['id'], start, end)
        ) or []
        result.append({"device": d, "rows": rows})

    return make_response(render_template("temps_report_template.html",
                                         date=day,
                                         buckets=result,
                                         range_end_label=range_end_label))

# --- GENERÁTOR ----------------------------------------------------------------
class _TempGenerator(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            now = _now()
            target = _quarter_next(now)
            # presný spánok do najbližšieho 15-min intervalu
            time.sleep(max(0.0, (target - _now()).total_seconds()))
            self._tick()  # <- voláme metódu triedy

    def _tick(self):
        """Jeden 15-min krok – zapíše teploty/off pre všetky aktívne zariadenia."""
        ts = _quarter_floor(_now())
        devices = _fetch_devices()
        if not devices:
            return
        outages_map = _fetch_outages_for_devices([d['id'] for d in devices])

        for d in devices:
            dev_id = d['id']
            off = _is_off_now(d, outages_map.get(dev_id, []), ts)
            if off:
                _upsert_reading(dev_id, ts, 0.0, 'OFF')
            else:
                temp = _rand_temp(d['device_type'])
                _upsert_reading(dev_id, ts, temp, 'OK')

def _seed_now():
    """Zapíše okamžite jednu vzorku na aktuálny štvrťhodinový čas (ak nechceš čakať 15 min)."""
    ts = _quarter_floor(_now())
    devices = _fetch_devices()
    if not devices:
        return
    outages_map = _fetch_outages_for_devices([d['id'] for d in devices])
    for d in devices:
        dev_id = d['id']
        off = _is_off_now(d, outages_map.get(dev_id, []), ts)
        if off:
            _upsert_reading(dev_id, ts, 0.0, 'OFF')
        else:
            temp = _rand_temp(d['device_type'])
            _upsert_reading(dev_id, ts, temp, 'OK')

_generator_instance: _TempGenerator|None = None

def start_generator():
    """Spustí generátor a voliteľne urobí jeden seed hneď po štarte."""
    global _generator_instance
    if os.environ.get("TEMPS_GENERATOR", "1") != "1":
        return
    if _generator_instance is None or not _generator_instance.is_alive():
        _generator_instance = _TempGenerator()
        _generator_instance.start()
        if os.environ.get("TEMPS_SEED_ON_START", "0") == "1":
            try:
                _seed_now()
            except Exception:
                pass
