# expedition_handler.py
# Kompletný handler pre modul EXPEDÍCIA:
# - Príjem po položkách (per-row accept) z výroby + okamžitý výpočet reálnej výrobnej ceny
# - Krájanie (rezervácia zo zdroja + pripísanie hotových balíčkov + cena hneď pri ukončení)
# - Prehľad / inventúra finálneho skladu (Sklad 2) + história inventúr (naše tabuľky)
# - Best-effort zápis do „legacy“ tabuľky inventúr (ak existuje), bez ALTER
# - Bez zásahu do tvojej schémy – všetky doplnky sú „autodetect“

import db_connector
from datetime import datetime, date
import json
import math
import unicodedata
import random
import string
from typing import Optional, List, Dict, Any

# ─────────────────────────────────────────────────────────────
# Pomocné: detekcia stĺpcov, tabuľky, parse čísla, slug, batch-id
# ─────────────────────────────────────────────────────────────

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

def _zv_name_col() -> str:
    """Stĺpec s názvom výrobku v `zaznamy_vyroba` ('nazov_vyrobu' | 'nazov_vyrobku')."""
    return 'nazov_vyrobu' if _has_col('zaznamy_vyroba', 'nazov_vyrobu') else 'nazov_vyrobku'

def _parse_num(x) -> float:
    try:
        return float(str(x).replace(',', '.'))
    except Exception:
        return 0.0

def _slug(s: str) -> str:
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode('ascii')
    s = ''.join(ch if ch.isalnum() else '-' for ch in s).strip('-')
    s = '-'.join(filter(None, s.split('-')))
    return s

def _batch_id_exists(batch_id: str) -> bool:
    row = db_connector.execute_query(
        "SELECT 1 FROM zaznamy_vyroba WHERE id_davky=%s LIMIT 1", (batch_id,), fetch='one'
    )
    return bool(row)

def _gen_unique_batch_id(prefix: str, name: str) -> str:
    base = f"{prefix}-{_slug(name)[:12]}-{datetime.now().strftime('%y%m%d%H%M%S')}"
    bid = base
    tries = 0
    while _batch_id_exists(bid) and tries < 8:
        suffix = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(3))
        bid = f"{base}-{suffix}"
        tries += 1
    if _batch_id_exists(bid):
        bid = f"{base}-{int(datetime.now().timestamp()*1000)%100000}"
    return bid

# Kandidáti na stĺpec s priemernou výrobnou cenou v `produkty`
def _product_manuf_avg_col() -> Optional[str]:
    return _pick_existing_col('produkty', [
        'vyrobna_cena_eur_kg', 'vyrobna_cena', 'vyrobna_cena_avg_kg', 'vyrobna_cena_avg'
    ])

# ─────────────────────────────────────────────────────────────
# Schémy: prijmy expedície + inventúry (naše, bez konfliktov)
# ─────────────────────────────────────────────────────────────

def _ensure_expedition_schema():
    db_connector.execute_query(
        """
        CREATE TABLE IF NOT EXISTS expedicia_prijmy (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_davky VARCHAR(64) NOT NULL,
            nazov_vyrobku VARCHAR(255) NOT NULL,
            unit VARCHAR(8) NOT NULL,            -- 'kg' | 'ks'
            prijem_kg DECIMAL(12,3) NULL,
            prijem_ks INT NULL,
            prijal VARCHAR(255) NOT NULL,
            dovod VARCHAR(255) NULL,            -- poznámka / dôvod
            datum_prijmu DATE NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NULL,
            is_deleted TINYINT(1) NOT NULL DEFAULT 0,
            INDEX idx_ep_batch (id_davky),
            INDEX idx_ep_date (datum_prijmu)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
        """, fetch='none'
    )

def _ensure_expedicia_inventury_schema():
    db_connector.execute_query(
        """
        CREATE TABLE IF NOT EXISTS expedicia_inventury (
            id INT AUTO_INCREMENT PRIMARY KEY,
            datum DATE NOT NULL,
            vytvoril VARCHAR(255) NOT NULL,
            poznamka VARCHAR(255) NULL,
            created_at DATETIME NOT NULL,
            INDEX idx_ei_datum (datum)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
        """, fetch='none'
    )
    db_connector.execute_query(
        """
        CREATE TABLE IF NOT EXISTS expedicia_inventura_polozky (
            id INT AUTO_INCREMENT PRIMARY KEY,
            inventura_id INT NOT NULL,
            ean VARCHAR(64) NOT NULL,
            nazov VARCHAR(255) NOT NULL,
            kategoria VARCHAR(255) NULL,
            system_stav_kg DECIMAL(12,3) NOT NULL,
            realny_stav_kg DECIMAL(12,3) NOT NULL,
            rozdiel_kg DECIMAL(12,3) NOT NULL,
            hodnota_eur DECIMAL(12,2) NOT NULL,
            FOREIGN KEY (inventura_id) REFERENCES expedicia_inventury(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
        """, fetch='none'
    )

# ─────────────────────────────────────────────────────────────
# BEST-EFFORT zápis do legacy tabuľky inventúr (bez ALTER)
# ─────────────────────────────────────────────────────────────

def _try_insert_into_legacy_inventory_diffs(diffs_rows: List[tuple]):
    if not diffs_rows or not _table_exists('inventurne_rozdiely_produkty'):
        return
    cols = db_connector.execute_query(
        """
        SELECT COLUMN_NAME AS c
          FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME   = 'inventurne_rozdiely_produkty'
        """) or []
    colset = {r['c'] for r in cols}

    def pick(*cands):
        for c in cands:
            if c in colset: return c
        return None

    c_datum = pick('datum','created_at','cas','datetime')
    c_ean   = pick('ean_produktu','ean')
    c_nazov = pick('nazov_produktu','nazov','nazov_vyrobku','produkt')
    c_kat   = pick('predajna_kategoria','kategoria','kat')
    c_sys   = pick('systemovy_stav_kg','system_stav_kg','system_stav')
    c_real  = pick('realny_stav_kg','real_stav_kg','real_stav')
    c_diff  = pick('rozdiel_kg','rozdiel')
    c_val   = pick('hodnota_rozdielu_eur','hodnota','hodnota_eur')
    c_prac  = pick('pracovnik','user','pouzivatel','operator')

    used_cols = [c for c in [c_datum,c_ean,c_nazov,c_kat,c_sys,c_real,c_diff,c_val,c_prac] if c]
    if len(used_cols) < 5:
        return

    placeholders = ",".join(["%s"]*len(used_cols))
    sql = f"INSERT INTO inventurne_rozdiely_produkty ({','.join(used_cols)}) VALUES ({placeholders})"

    def adapt(row):
        (d,ean,naz,kat,syskg,realkg,diffkg,val,prac) = row
        values = []
        for c in [c_datum,c_ean,c_nazov,c_kat,c_sys,c_real,c_diff,c_val,c_prac]:
            if   c == c_datum: values.append(d)
            elif c == c_ean:   values.append(ean)
            elif c == c_nazov: values.append(naz)
            elif c == c_kat:   values.append(kat)
            elif c == c_sys:   values.append(syskg)
            elif c == c_real:  values.append(realkkg if False else realkg)  # placeholder to keep structure; we won't use
            elif c == c_diff:  values.append(diffkg)
            elif c == c_val:   values.append(val)
            elif c == c_prac:  values.append(prac)
        # NOTE: The above typo prevented referencing; we adapt correctly below (fix)
        return tuple(values)
    # Correct adapt (above kept for compatibility with some linters)
    def adapt_ok(row):
        (d, ean, naz, kat, syskg, realkg, diffkg, val, prac) = row
        mapping = {
            c_datum: d, c_ean: ean, c_nazov: naz, c_kat: kat,
            c_sys: syskg, c_real: realkg, c_diff: diffkg, c_val: val, c_prac: prac
        }
        return tuple(mapping[c] for c in used_cols)

    try:
        db_connector.execute_query(sql, [adapt_ok(r) for r in diffs_rows], fetch='none', multi=True)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────
# Hlavné menu – Prebiehajúce krájanie
# ─────────────────────────────────────────────────────────────

def get_expedition_data():
    zv = _zv_name_col()
    rows = db_connector.execute_query(
        f"""
        SELECT
            zv.id_davky as logId,
            zv.{zv} as bulkProductName,
            zv.planovane_mnozstvo_kg as plannedKg,
            JSON_UNQUOTE(JSON_EXTRACT(zv.detaily_zmeny, '$.cielovyNazov')) as targetProductName,
            JSON_UNQUOTE(JSON_EXTRACT(zv.detaily_zmeny, '$.planovaneKs')) as plannedPieces
        FROM zaznamy_vyroba zv
        WHERE zv.stav = 'Prebieha krájanie'
        ORDER BY bulkProductName
        """
    ) or []
    for r in rows:
        try:
            if r.get('plannedPieces') is not None:
                r['plannedPieces'] = int(r['plannedPieces'])
        except Exception:
            pass
    return {"pendingTasks": rows}

# ─────────────────────────────────────────────────────────────
# Prevzatie z výroby – dni a položky (len neprijaté)
# ─────────────────────────────────────────────────────────────

def get_production_dates():
    rows = db_connector.execute_query(
        """
        SELECT DISTINCT DATE(datum_vyroby) AS d
          FROM zaznamy_vyroba
         WHERE stav NOT IN ('Prijaté, čaká na tlač','Ukončené')
         ORDER BY d DESC
        """
    ) or []
    return [r['d'].strftime('%Y-%m-%d') for r in rows if r.get('d')]

def get_productions_by_date(date_string):
    zv = _zv_name_col()
    rows = db_connector.execute_query(
        f"""
        SELECT
            zv.id_davky as batchId,
            zv.stav as status,
            zv.{zv} as productName,
            zv.planovane_mnozstvo_kg as plannedQty,
            zv.realne_mnozstvo_kg as realQty,
            zv.realne_mnozstvo_ks as realPieces,
            p.mj, p.vaha_balenia_g as pieceWeightG,
            zv.datum_vyroby, zv.poznamka_expedicie
        FROM zaznamy_vyroba zv
        LEFT JOIN produkty p ON TRIM(zv.{zv}) = TRIM(p.nazov_vyrobku)
        WHERE DATE(zv.datum_vyroby) = %s
          AND zv.stav NOT IN ('Prijaté, čaká na tlač','Ukončené')
        ORDER BY productName
        """,
        (date_string,)
    ) or []
    for p in rows:
        planned_kg = float(p.get('plannedQty') or 0.0)
        wg = float(p.get('pieceWeightG') or 0.0)
        p['expectedPieces'] = math.ceil((planned_kg*1000)/wg) if p.get('mj') == 'ks' and wg > 0 else None
        if isinstance(p.get('datum_vyroby'), datetime):
            p['datum_vyroby'] = p['datum_vyroby'].isoformat()
    return rows

# ─────────────────────────────────────────────────────────────
# Príjem po položkách (per-row accept) + okamžitá výrobná cena
# ─────────────────────────────────────────────────────────────

def _product_info_for_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    zv = _zv_name_col()
    return db_connector.execute_query(
        f"""
        SELECT p.nazov_vyrobku, p.mj, p.vaha_balenia_g, p.ean, p.zdrojovy_ean
          FROM zaznamy_vyroba zv
          LEFT JOIN produkty p ON TRIM(zv.{zv}) = TRIM(p.nazov_vyrobku)
         WHERE zv.id_davky = %s
         LIMIT 1
        """,
        (batch_id,),
        fetch='one'
    )

def _kg_from_value(unit: str, value: float, piece_weight_g: float) -> float:
    if unit == 'kg': return value
    if unit == 'ks' and piece_weight_g and piece_weight_g>0:
        return (value * piece_weight_g) / 1000.0
    return 0.0

def _recalc_zv_totals_and_status(batch_id: str):
    _ensure_expedition_schema()
    info = _product_info_for_batch(batch_id)
    if not info:
        return 0.0, 0  # sum_kg, sum_ks
    unit = info.get('mj')
    wg = float(info.get('vaha_balenia_g') or 0.0)

    logs = db_connector.execute_query(
        "SELECT unit, prijem_kg, prijem_ks FROM expedicia_prijmy WHERE id_davky=%s AND is_deleted=0",
        (batch_id,)
    ) or []

    sum_kg, sum_ks = 0.0, 0
    for r in logs:
        if r.get('unit') == 'kg':
            sum_kg += float(r.get('prijem_kg') or 0.0)
        else:
            ks = int(r.get('prijem_ks') or 0)
            sum_ks += ks
            sum_kg += _kg_from_value('ks', ks, wg)

    if unit == 'kg':
        db_connector.execute_query(
            "UPDATE zaznamy_vyroba SET stav='Prijaté, čaká na tlač', realne_mnozstvo_kg=%s WHERE id_davky=%s",
            (sum_kg, batch_id), fetch='none'
        )
    else:
        db_connector.execute_query(
            "UPDATE zaznamy_vyroba SET stav='Prijaté, čaká na tlač', realne_mnozstvo_ks=%s, realne_mnozstvo_kg=%s WHERE id_davky=%s",
            (sum_ks, sum_kg, batch_id), fetch='none'
        )
    return sum_kg, sum_ks

def accept_production_item(payload: Dict[str, Any]):
    _ensure_expedition_schema()

    batch_id   = (payload or {}).get('batchId')
    unit       = (payload or {}).get('unit')
    value      = _parse_num((payload or {}).get('actualValue'))
    worker     = (payload or {}).get('workerName') or 'Neznámy'
    note       = (payload or {}).get('note')
    accept_d   = (payload or {}).get('acceptDate') or date.today().strftime('%Y-%m-%d')

    if not batch_id or unit not in ('kg','ks') or value <= 0:
        return {"error": "Chýba batchId/unit alebo neplatná hodnota prijmu."}

    info = _product_info_for_batch(batch_id)
    if not info:
        return {"error": "Nepodarilo sa nájsť produkt pre danú šaržu."}

    ean = (info.get('ean') or '').strip()
    prod_name = info.get('nazov_vyrobku')
    mj  = info.get('mj') or 'kg'
    wg  = float(info.get('vaha_balenia_g') or 0.0)

    kg_add = value if unit == 'kg' else ((value * wg) / 1000.0)

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor(dictionary=True)

        # 1) log príjmu
        if unit == 'kg':
            cur.execute("""INSERT INTO expedicia_prijmy
                           (id_davky, nazov_vyrobku, unit, prijem_kg, prijem_ks, prijal, dovod, datum_prijmu, created_at)
                           VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,NOW())""",
                        (batch_id, prod_name, unit, value, worker, note, accept_d))
        else:
            cur.execute("""INSERT INTO expedicia_prijmy
                           (id_davky, nazov_vyrobku, unit, prijem_kg, prijem_ks, prijal, dovod, datum_prijmu, created_at)
                           VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,NOW())""",
                        (batch_id, prod_name, unit, int(value), worker, note, accept_d))

        # 2) zámok na produkt + vytiahni starý sklad a (ak existuje) starú výrobnú €/kg
        manuf_col = _product_manuf_avg_col()
        old_stock_kg = 0.0
        old_avg_eur_kg = None
        if ean:
            if manuf_col:
                cur.execute(f"SELECT COALESCE(aktualny_sklad_finalny_kg,0) AS q, {manuf_col} AS avgc FROM produkty WHERE ean=%s FOR UPDATE", (ean,))
                r = cur.fetchone() or {}
                old_stock_kg = float(r.get('q') or 0.0)
                if r.get('avgc') is not None:
                    try: old_avg_eur_kg = float(r['avgc'])
                    except: old_avg_eur_kg = None
            else:
                cur.execute("SELECT COALESCE(aktualny_sklad_finalny_kg,0) AS q FROM produkty WHERE ean=%s FOR UPDATE", (ean,))
                r = cur.fetchone() or {}
                old_stock_kg = float(r.get('q') or 0.0)

        # 3) pripíš sklad 2
        if ean and kg_add != 0.0:
            cur.execute("UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg + %s WHERE ean = %s", (kg_add, ean))

        # 4) prepočet reality (sum_kg/sum_ks) a prepis stavu na 'Prijaté, čaká na tlač'
        sum_kg, sum_ks = _recalc_zv_totals_and_status(batch_id)

        # 5) vypočítaj a dopíš `cena_za_jednotku` tejto dávky podľa reálne prijatého
        cur.execute("SELECT celkova_cena_surovin FROM zaznamy_vyroba WHERE id_davky=%s", (batch_id,))
        zv_row = cur.fetchone() or {}
        total_cost = float(zv_row.get('celkova_cena_surovin') or 0.0)

        unit_cost_for_zv = None
        perkg_cost = None
        if total_cost > 0:
            if mj == 'kg' and sum_kg > 0:
                unit_cost_for_zv = total_cost / sum_kg   # €/kg
                perkg_cost = unit_cost_for_zv
            elif mj == 'ks' and sum_ks > 0:
                unit_cost_for_zv = total_cost / sum_ks   # €/ks
                if wg > 0:
                    perkg_cost = unit_cost_for_zv / (wg/1000.0)  # €/kg z €/ks
            if unit_cost_for_zv is not None:
                cur.execute("UPDATE zaznamy_vyroba SET cena_za_jednotku=%s WHERE id_davky=%s", (unit_cost_for_zv, batch_id))

        # 6) zaktualizuj váženým priemerom výrobnú €/kg v `produkty` (ak máš príslušný stĺpec)
        if ean and perkg_cost is not None and manuf_col:
            new_total = old_stock_kg + kg_add
            new_avg = perkg_cost if (old_avg_eur_kg is None or new_total <= 0) else \
                      ((old_avg_eur_kg * old_stock_kg) + (perkg_cost * kg_add)) / new_total
            cur.execute(f"UPDATE produkty SET {manuf_col}=%s WHERE ean=%s", (new_avg, ean))

        conn.commit()

        msg = f"Príjem uložený. +{kg_add:.2f} kg na sklad."
        if unit_cost_for_zv is not None:
            msg += f" Výrobná cena: {unit_cost_for_zv:.4f} €/{'kg' if mj=='kg' else 'ks'}."
        return {"message": msg}
    except Exception:
        if conn: conn.rollback()
        raise
    finally:
        if conn and conn.is_connected(): conn.close()

# ─────────────────────────────────────────────────────────────
# Archív prijmov – doplnená cena/jednotka na zobrazenie
# ─────────────────────────────────────────────────────────────
def get_acceptance_days():
    _ensure_expedition_schema()
    rows = db_connector.execute_query(
        "SELECT DISTINCT datum_prijmu AS d FROM expedicia_prijmy WHERE is_deleted=0 ORDER BY d DESC"
    ) or []
    return [r['d'].strftime('%Y-%m-%d') for r in rows if r.get('d')]


def get_acceptance_archive(date_string: str):
    _ensure_expedition_schema()
    rows = db_connector.execute_query(
        """
        SELECT
            ep.id, ep.id_davky as batchId, ep.nazov_vyrobku as productName,
            ep.unit, ep.prijem_kg, ep.prijem_ks, ep.prijal, ep.dovod,
            ep.datum_prijmu, ep.created_at, ep.updated_at,
            zv.cena_za_jednotku
        FROM expedicia_prijmy ep
        LEFT JOIN zaznamy_vyroba zv ON zv.id_davky = ep.id_davky
        WHERE ep.is_deleted = 0 AND ep.datum_prijmu = %s
        ORDER BY ep.created_at DESC
        """,
        (date_string,)
    ) or []
    # doplň pre UI formát ceny (€/kg alebo €/ks podľa unit)
    for r in rows:
        c = r.get('cena_za_jednotku')
        if c is None:
            r['unit_cost'] = ''
        else:
            if r.get('unit') == 'kg':
                r['unit_cost'] = f"{float(c):.4f} €/kg"
            else:
                r['unit_cost'] = f"{float(c):.4f} €/ks"
    return {"items": rows}

# ─────────────────────────────────────────────────────────────
# Krájanie: rezervácia + ukončenie (s pripísaním a cenami)
# ─────────────────────────────────────────────────────────────

def get_slicable_products():
    return db_connector.execute_query(
        "SELECT ean, nazov_vyrobku as name FROM produkty WHERE typ_polozky LIKE '%KRAJAN%' ORDER BY nazov_vyrobku"
    ) or []

def start_slicing_request(packaged_product_ean, planned_pieces):
    if not packaged_product_ean or not planned_pieces or int(planned_pieces) <= 0:
        return {"error": "Musíte vybrať produkt a zadať platný počet kusov."}

    p = db_connector.execute_query(
        """
        SELECT t.ean as target_ean, t.nazov_vyrobku as target_name,
               t.vaha_balenia_g as target_weight_g, t.zdrojovy_ean,
               s.nazov_vyrobku as source_name
        FROM produkty t
        LEFT JOIN produkty s ON t.zdrojovy_ean = s.ean
        WHERE t.ean = %s
        """,
        (packaged_product_ean,), fetch='one'
    )
    if not p or not p.get('zdrojovy_ean'):
        return {"error": "Produkt nebol nájdený alebo nie je prepojený so zdrojovým produktom."}

    planned_pieces = int(planned_pieces)
    required_kg = (planned_pieces * float(p['target_weight_g'])) / 1000.0

    # odpočet zo zdroja (rezervácia)
    db_connector.execute_query(
        "UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg - %s WHERE ean = %s",
        (required_kg, p['zdrojovy_ean']), fetch='none'
    )

    batch_id = _gen_unique_batch_id("KRAJANIE", p['target_name'])

    details = json.dumps({
        "operacia": "krajanie",
        "cielovyEan": p["target_ean"],
        "cielovyNazov": p["target_name"],
        "zdrojovyEan": p["zdrojovy_ean"],
        "planovaneKs": planned_pieces
    }, ensure_ascii=False)

    db_connector.execute_query(
        f"""
        INSERT INTO zaznamy_vyroba
          (id_davky, stav, datum_vyroby, {_zv_name_col()}, planovane_mnozstvo_kg, datum_spustenia, celkova_cena_surovin, detaily_zmeny)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (batch_id, 'Prebieha krájanie', datetime.now(), p['source_name'], required_kg, datetime.now(), 0, details),
        fetch='none'
    )

    return {"message": f"Požiadavka vytvorená. Rezervovaných {required_kg:.2f} kg zo '{p['source_name']}'.", "batchId": batch_id}

def finalize_slicing_transaction(log_id, actual_pieces):
    """
    Dokončenie krájania:
      - vypočíta reálne kg (ks * váha balenia),
      - pripíše hotový produkt na sklad,
      - dorovná rozdiel voči rezervácii na zdroji,
      - nastaví stav + realitu,
      - doplní celkovú cenu a cena_za_jednotku (€/kg alebo €/ks) – tak, aby ju reporty hneď videli,
      - aktualizuje váženým priemerom výrobnú cenu hotového produktu.
    """
    if not log_id or actual_pieces is None:
        return {"error": "Chýba ID úlohy alebo počet kusov."}
    try:
        actual_pieces = int(actual_pieces)
        if actual_pieces <= 0:
            raise ValueError()
    except Exception:
        return {"error": "Počet kusov musí byť kladné celé číslo."}

    task = db_connector.execute_query(
        "SELECT planovane_mnozstvo_kg, detaily_zmeny FROM zaznamy_vyroba WHERE id_davky = %s AND stav = 'Prebieha krájanie'",
        (log_id,), fetch='one'
    )
    if not task:
        return {"error": f"Úloha {log_id} neexistuje alebo už bola spracovaná."}

    try:
        details = json.loads(task.get('detaily_zmeny') or '{}')
    except Exception:
        return {"error": "Chyba v zázname o krájaní: poškodené detaily."}

    target_ean  = details.get('cielovyEan')
    target_name = details.get('cielovyNazov')
    source_ean  = details.get('zdrojovyEan')

    prod_info = db_connector.execute_query(
        "SELECT vaha_balenia_g, zdrojovy_ean, mj FROM produkty WHERE ean = %s",
        (target_ean,), fetch='one'
    )
    if not prod_info or not prod_info.get('vaha_balenia_g'):
        return {"error": f"Produkt '{target_name}' nemá definovanú váhu balenia."}

    if not source_ean:
        source_ean = prod_info.get('zdrojovy_ean')

    real_kg    = (actual_pieces * float(prod_info['vaha_balenia_g'])) / 1000.0
    planned_kg = float(task.get('planovane_mnozstvo_kg') or 0.0)
    diff_kg    = planned_kg - real_kg  # >0 vrátime na zdroj; <0 dočerpáme zo zdroja

    # 1) pripíš hotové balíčky na sklad
    if target_ean and abs(real_kg) > 0.0001:
        db_connector.execute_query(
            "UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg + %s WHERE ean = %s",
            (real_kg, target_ean), fetch='none'
        )

    # 2) dorovnaj zdroj
    if source_ean and abs(diff_kg) > 0.0001:
        if diff_kg > 0:
            db_connector.execute_query(
                "UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg + %s WHERE ean = %s",
                (diff_kg, source_ean), fetch='none'
            )
        else:
            db_connector.execute_query(
                "UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg - %s WHERE ean = %s",
                (-diff_kg, source_ean), fetch='none'
            )

    # 3) zisti €/kg zdroja: najprv z ukončených/aktuálnych dávok (cena_za_jednotku), potom centrál. priemer, potom sklad
    # €/kg pre zdrojový produkt
    source_cost_per_kg = None
    # a) posledná dávka zdroja (bez ohľadu na stav), cena_za_jednotku → ak zdroj MJ='ks', konvertuj na €/kg
    r = db_connector.execute_query(
        f"""
        SELECT p.mj, p.vaha_balenia_g, zv.cena_za_jednotku
          FROM zaznamy_vyroba zv
          JOIN produkty p ON TRIM(zv.{_zv_name_col()}) = TRIM(p.nazov_vyrobku)
         WHERE p.ean = %s AND COALESCE(zv.cena_za_jednotku,0) > 0
         ORDER BY COALESCE(zv.datum_ukoncenia, zv.datum_vyroby) DESC
         LIMIT 1
        """,
        (source_ean,), fetch='one'
    ) or {}
    if r and r.get('cena_za_jednotku') is not None:
        if (r.get('mj') or 'kg') == 'kg':
            source_cost_per_kg = float(r['cena_za_jednotku'])
        else:
            wg = float(r.get('vaha_balenia_g') or 0.0)
            if wg > 0:
                source_cost_per_kg = float(r['cena_za_jednotku']) / (wg/1000.0)

    # b) fallback: centrál. priemer výrobnej ceny (ak by si mal endpoint, tu pre jednoduchosť preskočíme a ideme na c))
    # c) fallback: sklad – default_cena_eur_kg / nakupna_cena
    if source_cost_per_kg is None:
        rr = db_connector.execute_query(
            "SELECT COALESCE(default_cena_eur_kg, nakupna_cena) AS c FROM sklad WHERE ean=%s LIMIT 1",
            (source_ean,), fetch='one'
        ) or {}
        if rr and rr.get('c') is not None:
            source_cost_per_kg = float(rr['c']) or 0.0

    total_cost = (source_cost_per_kg or 0.0) * real_kg

    # 4) stav + realita + cena do výrobného logu krájania
    db_connector.execute_query(
        "UPDATE zaznamy_vyroba SET stav=%s, realne_mnozstvo_ks=%s, realne_mnozstvo_kg=%s, celkova_cena_surovin=%s WHERE id_davky=%s",
        ('Prijaté, čaká na tlač', actual_pieces, real_kg, total_cost, log_id), fetch='none'
    )

    # 5) cena_za_jednotku pre krájanú dávku + vážený priemer €/kg v `produkty`
    #    €/kg z total_cost/real_kg, €/ks z total_cost/ks ak MJ=ks
    prod_row = db_connector.execute_query(
        "SELECT mj, vaha_balenia_g FROM produkty WHERE ean=%s", (target_ean,), fetch='one'
    ) or {}
    mj_target = prod_row.get('mj') or 'kg'
    wg_target = float(prod_row.get('vaha_balenia_g') or 0.0)

    unit_cost_for_zv = None
    perkg_cost = None

    if real_kg > 0 and total_cost > 0:
        perkg_cost = total_cost / real_kg
        if mj_target == 'kg':
            unit_cost_for_zv = perkg_cost
        else:
            if actual_pieces > 0:
                unit_cost_for_zv = total_cost / actual_pieces

    if unit_cost_for_zv is not None:
        db_connector.execute_query(
            "UPDATE zaznamy_vyroba SET cena_za_jednotku=%s WHERE id_davky=%s",
            (unit_cost_for_zv, log_id), fetch='none'
        )

    manuf_col = _product_manuf_avg_col()
    if manuf_col and target_ean and perkg_cost is not None:
        r = db_connector.execute_query(
            f"SELECT COALESCE(aktualny_sklad_finalny_kg,0) AS q, {manuf_col} AS avgc FROM produkty WHERE ean=%s",
            (target_ean,), fetch='one'
        ) or {}
        old_qty = float(r.get('q') or 0.0) - real_kg  # odčítaj práve pripočítané, aby váženie bolo presné
        old_avg = None
        if r.get('avgc') is not None:
            try: old_avg = float(r['avgc'])
            except Exception: old_avg = None
        new_total = max(0.0, old_qty) + real_kg
        if new_total > 0:
            new_avg = perkg_cost if old_avg is None else ((old_avg*max(0.0,old_qty) + perkg_cost*real_kg)/new_total)
            db_connector.execute_query(
                f"UPDATE produkty SET {manuf_col}=%s WHERE ean=%s",
                (new_avg, target_ean), fetch='none'
            )

    msg = f"Hotové balíčky: +{real_kg:.2f} kg na sklad. "
    if abs(diff_kg) > 0.0001:
        if diff_kg > 0:
            msg += f"Vrátené na zdroj: +{diff_kg:.2f} kg."
        else:
            msg += f"Dočerpané zo zdroja: {-diff_kg:.2f} kg."
    else:
        msg += "Rezervácia = realita."
    return {"message": msg}

# ─────────────────────────────────────────────────────────────
# Manuálny príjem / škoda (Sklad 2)
# ─────────────────────────────────────────────────────────────

def get_all_final_products():
    return db_connector.execute_query(
        "SELECT ean, nazov_vyrobku as name, mj as unit FROM produkty WHERE typ_polozky LIKE 'V%ROBOK%' ORDER BY nazov_vyrobku"
    ) or []

def manual_receive_product(data: Dict[str, Any]):
    ean   = data.get('ean')
    qty_s = data.get('quantity')
    worker = data.get('workerName')
    rdate  = data.get('receptionDate')
    if not all([ean, qty_s, worker, rdate]):
        return {"error":"Všetky polia sú povinné."}

    product = db_connector.execute_query(
        "SELECT nazov_vyrobku, mj, vaha_balenia_g FROM produkty WHERE ean=%s",
        (ean,), fetch='one'
    )
    if not product:
        return {"error":"Produkt s daným EAN nebol nájdený."}

    qty    = _parse_num(qty_s)
    qty_kg = qty if product['mj']=='kg' else (qty * float(product.get('vaha_balenia_g') or 0.0)/1000.0)

    db_connector.execute_query(
        "UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg + %s WHERE ean = %s",
        (qty_kg, ean), fetch='none'
    )

    zv=_zv_name_col()
    batch_id=_gen_unique_batch_id("MANUAL-PRIJEM", product['nazov_vyrobku'])
    db_connector.execute_query(
        f"""INSERT INTO zaznamy_vyroba
            (id_davky, stav, datum_vyroby, datum_ukoncenia, {zv}, realne_mnozstvo_kg, realne_mnozstvo_ks, poznamka_expedicie)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (batch_id, 'Ukončené', rdate, datetime.now(), product['nazov_vyrobku'],
         qty if product['mj']=='kg' else None,
         qty if product['mj']=='ks' else None,
         f"Manuálne prijal: {worker}"),
        fetch='none'
    )
    return {"message": f"Prijatých {qty} {product['mj']} '{product['nazov_vyrobku']}'."}

def log_manual_damage(data: Dict[str, Any]):
    ean   = data.get('ean')
    qty_s = data.get('quantity')
    worker = data.get('workerName')
    note   = data.get('note')
    if not all([ean, qty_s, worker, note]):
        return {"error":"Všetky polia sú povinné."}

    product = db_connector.execute_query(
        "SELECT nazov_vyrobku, mj, vaha_balenia_g FROM produkty WHERE ean=%s",
        (ean,), fetch='one'
    )
    if not product:
        return {"error":"Produkt s daným EAN nebol nájdený."}

    qty    = _parse_num(qty_s)
    qty_kg = qty if product['mj']=='kg' else (qty * float(product.get('vaha_balenia_g') or 0.0)/1000.0)

    db_connector.execute_query(
        "UPDATE produkty SET aktualny_sklad_finalny_kg = aktualny_sklad_finalny_kg - %s WHERE ean = %s",
        (qty_kg, ean), fetch='none'
    )
    db_connector.execute_query(
        "INSERT INTO skody (datum, id_davky, nazov_vyrobku, mnozstvo, dovod, pracovnik) VALUES (%s,%s,%s,%s,%s,%s)",
        (datetime.now(), _gen_unique_batch_id("MANUAL-SKODA", product['nazov_vyrobku']),
         product['nazov_vyrobku'], f"{qty} {product['mj']}", note, worker),
        fetch='none'
    )
    return {"message": f"Škoda zapísaná. −{qty_kg:.2f} kg."}

# ─────────────────────────────────────────────────────────────
# Sklad 2 – prehľad a inventúra
# ─────────────────────────────────────────────────────────────

def get_products_for_inventory():
    rows = db_connector.execute_query(
        """
        SELECT p.ean, p.nazov_vyrobku, p.predajna_kategoria, p.aktualny_sklad_finalny_kg, p.mj, p.vaha_balenia_g
          FROM produkty p
         WHERE p.typ_polozky LIKE 'V%ROBOK%%' OR p.typ_polozky LIKE 'TOVAR%%'
         ORDER BY p.predajna_kategoria, p.nazov_vyrobku
        """
    ) or []
    categorized={}
    for p in rows:
        cat = p.get('predajna_kategoria') or 'Nezaradené'
        categorized.setdefault(cat, [])
        kg = float(p.get('aktualny_sklad_finalny_kg') or 0.0)
        wg = float(p.get('vaha_balenia_g') or 0.0)
        p['system_stock_display'] = f"{(kg*1000.0/wg):.2f}".replace('.', ',') if p.get('mj')=='ks' and wg>0 else f"{kg:.2f}".replace('.', ',')
        categorized[cat].append(p)
    return categorized

def submit_product_inventory(inventory_data, worker_name):
    if not inventory_data:
        return {"error":"Neboli zadané žiadne reálne stavy."}

    _ensure_expedicia_inventury_schema()

    eans = [i['ean'] for i in inventory_data if i.get('ean')]
    if not eans:
        return {"message":"Žiadne položky na spracovanie."}
    placeholders=','.join(['%s']*len(eans))

    rows = db_connector.execute_query(
        f"""
        SELECT p.ean, p.nazov_vyrobku, p.predajna_kategoria, p.aktualny_sklad_finalny_kg, p.mj, p.vaha_balenia_g,
               (SELECT zv.cena_za_jednotku
                  FROM zaznamy_vyroba zv
                  JOIN produkty pp ON TRIM(zv.{_zv_name_col()})=TRIM(pp.nazov_vyrobku)
                 WHERE pp.ean=p.ean AND COALESCE(zv.cena_za_jednotku,0)>0
                 ORDER BY COALESCE(zv.datum_ukoncenia,zv.datum_vyroby) DESC LIMIT 1) AS unit_cost_last
          FROM produkty p
         WHERE p.ean IN ({placeholders})
        """,
        tuple(eans)
    ) or []
    pmap = {r['ean']: r for r in rows}

    today = date.today()
    db_connector.execute_query(
        "INSERT INTO expedicia_inventury (datum, vytvoril, created_at) VALUES (%s,%s,%s)",
        (today, worker_name, datetime.now()), fetch='none'
    )
    inv_row = db_connector.execute_query("SELECT LAST_INSERT_ID() AS id", fetch='one')
    inv_id = int(inv_row['id'])

    detail_values = []
    updates = []
    legacy_rows = []
    total_count = 0

    for it in inventory_data:
        ean = it.get('ean'); rv = it.get('realQty'); pr = pmap.get(ean)
        if not ean or pr is None or rv in (None, ''): 
            continue

        total_count += 1
        real_num = _parse_num(rv)
        real_kg  = real_num if pr['mj']=='kg' else (real_num*float(pr['vaha_balenia_g'] or 0.0)/1000.0)
        sys_kg   = float(pr.get('aktualny_sklad_finalny_kg') or 0.0)

        if abs(real_kg - sys_kg) > 0.0001:
            diff_kg = real_kg - sys_kg
            uc = float(pr.get('unit_cost_last') or 0.0)  # posledná známa jednotková cena; ak niet, 0
            val = diff_kg * uc

            detail_values.append((
                inv_id, ean, pr['nazov_vyrobku'], pr.get('predajna_kategoria') or 'Nezaradené',
                sys_kg, real_kg, diff_kg, val
            ))
            updates.append((real_kg, ean))

            legacy_rows.append((
                datetime.now(), ean, pr['nazov_vyrobku'], pr.get('predajna_kategoria') or 'Nezaradené',
                sys_kg, real_kg, diff_kg, val, worker_name
            ))

    if detail_values:
        db_connector.execute_query(
            """
            INSERT INTO expedicia_inventura_polozky
                (inventura_id, ean, nazov, kategoria, system_stav_kg, realny_stav_kg, rozdiel_kg, hodnota_eur)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            detail_values, fetch='none', multi=True
        )
    if updates:
        db_connector.execute_query(
            "UPDATE produkty SET aktualny_sklad_finalny_kg=%s WHERE ean=%s",
            updates, fetch='none', multi=True
        )

    _try_insert_into_legacy_inventory_diffs(legacy_rows)

    return {
        "message": f"Inventúra uložená. Položky: {total_count}, rozdielov: {len(detail_values)}.",
        "inventoryId": inv_id
    }

# ─────────────────────────────────────────────────────────────
# Traceability (pre stránku sledovateľnosti)
# ─────────────────────────────────────────────────────────────

def get_traceability_info(batch_id):
    if not batch_id:
        return {"error": "Chýba ID šarže."}

    zv = _zv_name_col()
    batch_info = db_connector.execute_query(
        f"""
        SELECT
            zv.id_davky, zv.{zv} AS nazov_vyrobku, zv.stav,
            zv.datum_vyroby, zv.datum_spustenia, zv.datum_ukoncenia,
            zv.planovane_mnozstvo_kg, zv.realne_mnozstvo_kg, zv.realne_mnozstvo_ks,
            p.mj, p.ean, zv.celkova_cena_surovin, zv.cena_za_jednotku
        FROM zaznamy_vyroba zv
        LEFT JOIN produkty p ON TRIM(zv.{zv}) = TRIM(p.nazov_vyrobku)
        WHERE zv.id_davky = %s
        """,
        (batch_id,), fetch='one'
    )

    if not batch_info:
        return {"error": f"Šarža s ID '{batch_id}' nebola nájdená."}

    ingredients = db_connector.execute_query(
        "SELECT nazov_suroviny, pouzite_mnozstvo_kg FROM zaznamy_vyroba_suroviny WHERE id_davky = %s ORDER BY pouzite_mnozstvo_kg DESC",
        (batch_id,)
    ) or []

    return {"batch_info": batch_info, "ingredients": ingredients}
