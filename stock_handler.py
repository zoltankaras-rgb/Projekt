# stock_handler.py
from flask import Blueprint, request, jsonify, Response
from datetime import datetime
from typing import Any, Dict, Optional, List
import re

import db_connector

stock_bp = Blueprint("stock", __name__)

# ------------------------- helpers (schema) -------------------------

def _has_col(table: str, col: str) -> bool:
    try:
        r = db_connector.execute_query("""
            SELECT 1
              FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = %s
               AND COLUMN_NAME  = %s
             LIMIT 1
        """, (table, col), fetch='one')
        return bool(r)
    except Exception:
        return False

def _first_col(table: str, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if _has_col(table, c):
            return c
    return None

def _conn_coll(default='utf8mb4_general_ci') -> str:
    try:
        r = db_connector.execute_query("SELECT @@collation_connection AS c", fetch='one') or {}
        return r.get('c') or default
    except Exception:
        return default

# ------------------------- small DB setup --------------------------

def _ensure_suppliers_schema():
    # ľahký CRM pre dodávateľov (používa ho aj objednávkový modul)
    db_connector.execute_query("""
        CREATE TABLE IF NOT EXISTS suppliers (
          id INT AUTO_INCREMENT PRIMARY KEY,
          name VARCHAR(255) NOT NULL,
          phone VARCHAR(64),
          email VARCHAR(255),
          address VARCHAR(255),
          is_active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
    """, fetch='none')
    db_connector.execute_query("""
        CREATE TABLE IF NOT EXISTS supplier_categories (
          supplier_id INT NOT NULL,
          category VARCHAR(64) NOT NULL,
          PRIMARY KEY (supplier_id, category),
          CONSTRAINT fk_supcat_supplier FOREIGN KEY (supplier_id)
            REFERENCES suppliers(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
    """, fetch='none')

def _index_exists(table: str, idx: str) -> bool:
    r = db_connector.execute_query("""
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s
         LIMIT 1
    """, (table, idx), fetch='one')
    return bool(r)

def _fk_exists(table: str, fk: str) -> bool:
    r = db_connector.execute_query("""
        SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
         WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME=%s
           AND CONSTRAINT_TYPE='FOREIGN KEY' AND CONSTRAINT_NAME=%s
         LIMIT 1
    """, (table, fk), fetch='one')
    return bool(r)

def _ensure_link_to_supplier():
    # 1) dodavatel_id stĺpec
    if not _has_col("sklad", "dodavatel_id"):
        db_connector.execute_query("ALTER TABLE sklad ADD COLUMN dodavatel_id INT NULL", fetch='none')

    # 2) index
    if not _index_exists("sklad", "idx_sklad_dodavatel_id"):
        db_connector.execute_query("CREATE INDEX idx_sklad_dodavatel_id ON sklad(dodavatel_id)", fetch='none')

    # 3) FK
    if not _fk_exists("sklad", "fk_sklad_supplier"):
        db_connector.execute_query("""
            ALTER TABLE sklad
              ADD CONSTRAINT fk_sklad_supplier
              FOREIGN KEY (dodavatel_id) REFERENCES suppliers(id)
              ON DELETE SET NULL
        """, fetch='none')

    # 4) istota kategorizácie (typ/podtyp/kategoria)
    for col in ("typ","podtyp","kategoria"):
        if not _has_col("sklad", col):
            try:
                db_connector.execute_query(f"ALTER TABLE sklad ADD COLUMN {col} VARCHAR(64) NULL", fetch='none')
            except Exception:
                pass


def init_stock():
    _ensure_suppliers_schema()
    _ensure_link_to_supplier()

# ------------------------- core queries ----------------------------

def _get_production_overview():
    sql = """
        SELECT 
            sv.nazov,
            COALESCE(sv.mnozstvo, 0)  AS quantity,
            COALESCE(s.typ, '')       AS typ,
            COALESCE(s.podtyp, '')    AS podtyp
        FROM sklad_vyroba sv
        LEFT JOIN sklad s ON s.nazov = sv.nazov
        ORDER BY sv.nazov
    """
    rows = db_connector.execute_query(sql) or []
    return {"items": [
        {"nazov": r["nazov"], "quantity": float(r["quantity"] or 0),
         "typ": (r["typ"] or ""), "podtyp": (r["podtyp"] or "")}
        for r in rows
    ]}

def _get_allowed_names(category: Optional[str]):
    # vráti názvy + poslednú cenu pre intake (podľa kategórie)
    cat = (category or "").strip().lower()
    cat_col = _first_col("sklad", ["kategoria","typ","podtyp"])
    if not cat_col:
        rows = db_connector.execute_query("SELECT nazov FROM sklad ORDER BY nazov") or []
        return {"items": [{"name": r["nazov"], "last_price": None} for r in rows]}

    coll = _conn_coll()
    label_map = {
        'maso': 'Mäso',
        'koreniny': 'Koreniny',
        'obal': 'Obaly - Črevá',
        'pomocny_material': 'Pomocný materiál',
    }
    patterns = {
        'maso': ['maso%','mäso%','brav%','hoväd%','hovad%','kurac%','hydin%','ryb%','mlet%'],
        'koreniny': ['koren%','korenin%','paprik%','rasc%','kmín%','kmin%','cesnak%','sol%','soľ%','dusit%'],
        'obal': ['obal%','črev%','cerv%','vak%','fóli%','foli%','sieť%','spag%','špag%'],
        'pomocny_material': ['pomoc%','voda%','ľad%','lad%','ovar%']
    }
    where_parts, params = [], []
    if cat in label_map:
        where_parts.append(f"s.{cat_col} COLLATE {coll} = %s COLLATE {coll}")
        params.append(label_map[cat])
    elif cat:
        pats = patterns.get(cat, [])
        if pats:
            where_parts.append("(" + " OR ".join([f"s.{cat_col} COLLATE {coll} LIKE %s"]*len(pats)) + ")")
            params.extend(pats)

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    rows = db_connector.execute_query(f"""
        SELECT s.nazov AS name,
               (SELECT z.nakupna_cena_eur_kg
                  FROM zaznamy_prijem z
                 WHERE z.nazov_suroviny COLLATE {coll} = s.nazov COLLATE {coll}
                 ORDER BY z.datum DESC
                 LIMIT 1) AS last_price
          FROM sklad s
          {where_sql}
         ORDER BY s.nazov
         LIMIT 1000
    """, tuple(params)) or []
    return {"items": [{"name": r["name"], "last_price": (float(r["last_price"]) if r["last_price"] is not None else None)} for r in rows]}

def _last_price_for(name: str):
    coll = _conn_coll()
    row = db_connector.execute_query(f"""
        SELECT z.nakupna_cena_eur_kg AS price
          FROM zaznamy_prijem z
         WHERE z.nazov_suroviny COLLATE {coll} = %s COLLATE {coll}
         ORDER BY z.datum DESC
         LIMIT 1
    """, (name,), fetch='one')
    if row and row.get("price") is not None:
        return float(row["price"])
    # fallback na sklad
    price_col = _first_col("sklad", ["default_cena_eur_kg","nakupna_cena","cena","cena_kg"])
    r2 = db_connector.execute_query(
        f"SELECT {price_col} AS price FROM sklad WHERE nazov=%s", (name,), fetch='one'
    ) if price_col else None
    return (float(r2["price"]) if (r2 and r2.get("price") is not None) else None)

# ------------------------- unified intake --------------------------

@stock_bp.post("/api/kancelaria/stock/receiveProduction")
def receive_production():
    """
    Unified intake:
    payload: { items: [
      {category:'maso'|'koreniny'|'obal'|'pomocny_material',
       source?:'rozrabka'|'expedicia'|'externy'|'ine',  # len pre Mäso
       supplier_id?: <int>,                             # pre ostatné
       name:'...', quantity:<float>, price?:<float>, note?:'...', date?:'YYYY-mm-dd HH:MM:SS'}
    ] }
    """
    data = request.get_json(force=True) or {}
    items = data.get('items') or []
    if not items:
        return jsonify({"error":"Žiadne položky na príjem."}), 400

    conn = db_connector.get_connection()
    try:
        cur = conn.cursor()
        for it in items:
            cat   = (it.get('category') or '').strip().lower()
            name  = (it.get('name') or '').strip()
            qty   = float(it.get('quantity') or 0)
            price = (it.get('price') if it.get('price') not in (None, '') else None)
            note  = (it.get('note') or '').strip()
            when  = (it.get('date') or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            if not name or qty <= 0:
                conn.rollback()
                return jsonify({"error": f"Neplatná položka (name/quantity): {name}"}), 400

            # zdroj alebo dodávateľ
            if cat in ('maso','mäso'):
                src = (it.get('source') or '').strip().lower()
                if src not in ('rozrabka','expedicia','externy','ine'):
                    conn.rollback()
                    return jsonify({"error": f"Zvoľ Zdroj pre mäso (rozrabka/expedicia/externy/ine) — {name}"}), 400
                prijem_typ = src
            else:
                prijem_typ = 'dodavatel'
                sup_id = it.get('supplier_id')
                if sup_id:
                    # ak máme dodavatel_id a v sklade je stĺpec, nastav ho
                    if _has_col("sklad","dodavatel_id"):
                        db_connector.execute_query("UPDATE sklad SET dodavatel_id=%s WHERE nazov=%s", (int(sup_id), name), fetch='none')

            # karta v sklade musí existovať
            cur.execute("SELECT COALESCE(mnozstvo,0), COALESCE(nakupna_cena,0) FROM sklad WHERE nazov=%s FOR UPDATE", (name,))
            r0 = cur.fetchone()
            if r0 is None:
                conn.rollback()
                return jsonify({"error": f"Položka '{name}' nie je založená v sklad(e)."}), 400
            central_qty, avg_now = float(r0[0] or 0), float(r0[1] or 0)

            # zásoba výrobný sklad (na váženie ceny)
            cur.execute("SELECT COALESCE(mnozstvo,0) FROM sklad_vyroba WHERE nazov=%s FOR UPDATE", (name,))
            r1 = cur.fetchone()
            prod_qty = float(r1[0]) if r1 else 0.0

            # vážený priemer v sklade (ak prišla cena)
            if price is not None:
                total_before = central_qty + prod_qty
                new_total = total_before + qty
                new_avg = (avg_now * total_before + float(price) * qty) / new_total if new_total > 0 else float(price)
                cur.execute("UPDATE sklad SET nakupna_cena=%s WHERE nazov=%s", (new_avg, name))

            # navýš výrobný sklad
            cur.execute("""
                INSERT INTO sklad_vyroba (nazov, mnozstvo) VALUES (%s,%s)
                ON DUPLICATE KEY UPDATE mnozstvo = mnozstvo + VALUES(mnozstvo)
            """, (name, qty))

            # log do príjmov
            cur.execute("""
                INSERT INTO zaznamy_prijem (datum, nazov_suroviny, mnozstvo_kg, nakupna_cena_eur_kg, typ, poznamka_dodavatel)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (when, name, qty, price if price is not None else None, prijem_typ, note))

        conn.commit()
        return jsonify({"message": f"Príjem uložený ({len(items)} riadkov)."})
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected(): conn.close()

# ------------------------- read views ------------------------------

@stock_bp.get("/api/kancelaria/getRawMaterialStockOverview")
def get_raw_material_stock_overview():
    return jsonify(_get_production_overview())

@stock_bp.get("/api/kancelaria/getComprehensiveStockView")
def get_comprehensive_stock_view():
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
    for r in rows:
        unit = r.get('unit') or 'kg'
        qty_kg = float(r.get('stock_kg') or 0.0)
        w = float(r.get('vaha_balenia_g') or 0.0)
        qty = (qty_kg * 1000 / w) if unit == 'ks' and w > 0 else qty_kg
        item = {"ean": r['ean'], "name": r['name'], "category": r.get('category') or 'Nezaradené',
                "quantity": qty, "unit": unit, "price": float(r.get('price') or 0.0),
                "sklad1": 0.0, "sklad2": qty_kg}
        grouped.setdefault(item['category'], []).append(item)
    return jsonify({"groupedByCategory": grouped})

@stock_bp.get("/api/kancelaria/stock/allowed-names")
def stock_allowed_names():
    return jsonify(_get_allowed_names(request.args.get("category")))

@stock_bp.get("/api/kancelaria/stock/last-price")
def stock_last_price():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"last_price": None})
    return jsonify({"last_price": _last_price_for(name)})

# ------------------------- item CRUD / FULL edit -------------------

@stock_bp.post("/api/kancelaria/stock/createProductionItem")
def create_production_item():
    """
    {category, ean?, name, quantity, price?}
    - založí kartu v `sklad` (ak chýba), vyplní typ/kategóriu
    - navýši výrob. sklad o quantity
    """
    data = request.get_json(force=True) or {}
    cat = (data.get('category') or '').strip().lower()
    if cat in ('mäso','maso','meat'): cat = 'maso'
    name = (data.get('name') or '').strip()
    ean  = (data.get('ean') or None)
    qty  = float(data.get('quantity') or 0)
    price= (data.get('price') if data.get('price') not in (None,'') else None)
    if not name:
        return jsonify({"error":"Chýba názov."}), 400
    if qty < 0:
        return jsonify({"error":"Neplatné množstvo."}), 400

    # karta v sklade
    exists = db_connector.execute_query("SELECT 1 FROM sklad WHERE nazov=%s", (name,), fetch='one')
    if not exists:
        map_typ = {'maso':'Mäso','koreniny':'Koreniny','obal':'Obaly - Črevá','pomocny_material':'Pomocný materiál'}
        fields, values = ['nazov'], [name]
        if _has_col("sklad","typ"):        fields.append("typ");        values.append(map_typ.get(cat,''))
        if _has_col("sklad","podtyp"):     fields.append("podtyp");     values.append('')
        if _has_col("sklad","kategoria"):  fields.append("kategoria");  values.append(cat)
        if _has_col("sklad","ean") and ean: fields.append("ean");       values.append(ean)
        if _has_col("sklad","mnozstvo"):   fields.append("mnozstvo");   values.append(0)
        if price is not None:
            if _has_col("sklad","nakupna_cena"): fields.append("nakupna_cena"); values.append(float(price))
            elif _has_col("sklad","default_cena_eur_kg"): fields.append("default_cena_eur_kg"); values.append(float(price))
        ph = ",".join(["%s"]*len(values))
        db_connector.execute_query(f"INSERT INTO sklad ({', '.join(fields)}) VALUES ({ph})", tuple(values), fetch='none')

    # navýš výrob. sklad
    db_connector.execute_query("""
        INSERT INTO sklad_vyroba (nazov, mnozstvo) VALUES (%s,%s)
        ON DUPLICATE KEY UPDATE mnozstvo = mnozstvo + VALUES(mnozstvo)
    """, (name, qty), fetch='none')

    return jsonify({"message":"Položka pridaná do výrobného skladu."})

@stock_bp.post("/api/kancelaria/stock/updateProductionItemQty")
def update_production_item_qty():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name or "quantity" not in data:
        return jsonify({"error":"Chýba name/quantity."}), 400
    try:
        qty = float(str(data.get("quantity")).replace(',', '.'))
    except Exception:
        return jsonify({"error":"Neplatné množstvo."}), 400
    if qty < 0:
        return jsonify({"error":"Neplatné množstvo."}), 400

    exists = db_connector.execute_query("SELECT 1 FROM sklad_vyroba WHERE nazov=%s", (name,), fetch='one')
    if exists:
        db_connector.execute_query("UPDATE sklad_vyroba SET mnozstvo=%s WHERE nazov=%s", (qty, name), fetch='none')
    else:
        db_connector.execute_query("INSERT INTO sklad_vyroba (nazov, mnozstvo) VALUES (%s,%s)", (name, qty), fetch='none')
    return jsonify({"message":"Množstvo uložené."})

@stock_bp.post("/api/kancelaria/stock/deleteProductionItem")
def delete_production_item():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error":"Chýba názov."}), 400
    db_connector.execute_query("DELETE FROM sklad_vyroba WHERE nazov=%s", (name,), fetch='none')
    return jsonify({"message":"Položka odstránená z výrobného skladu."})

@stock_bp.get("/api/kancelaria/stock/item")
def get_stock_item():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error":"Chýba name"}), 400

    def has(table, col):
        r = db_connector.execute_query("""
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s LIMIT 1
        """, (table, col), fetch='one')
        return bool(r)

    cols = [
        "nazov","ean","typ","podtyp","kategoria","jednotka","unit","mj",
        "mnozstvo","min_mnozstvo","min_zasoba","min_stav_kg",
        "nakupna_cena","default_cena_eur_kg","dodavatel","dodavatel_id"
    ]
    have = [c for c in cols if has("sklad", c)]
    sel = ", ".join(have) if have else "nazov"
    row = db_connector.execute_query(f"SELECT {sel} FROM sklad WHERE nazov=%s", (name,), fetch='one') or {}
    return jsonify({"item": row})


@stock_bp.post("/api/kancelaria/stock/saveItem")
def save_stock_item():
    """
    Plná editácia karty v `sklad`.
    payload: {
      original_name: 'pôvodný názov' (POVINNÉ),
      name?, ean?, typ?, podtyp?, kategoria?,
      jednotka?/mj?, min_mnozstvo?/min_zasoba?/min_stav_kg?,
      nakupna_cena?/default_cena_eur_kg?,
      dodavatel_id? (preferované), dodavatel? (meno)
    }
    """
    d = request.get_json(force=True) or {}
    old = (d.get("original_name") or "").strip()
    if not old:
        return jsonify({"error":"Chýba original_name"}), 400

    def has(col):
        r = db_connector.execute_query("""
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='sklad' AND COLUMN_NAME=%s LIMIT 1
        """, (col,), fetch='one')
        return bool(r)

    # ak prišiel dodávateľ menom a nie id -> dohľadaj id
    if (not d.get("dodavatel_id")) and d.get("dodavatel"):
        r = db_connector.execute_query("SELECT id FROM suppliers WHERE name=%s LIMIT 1", (d["dodavatel"],), fetch='one')
        if r: d["dodavatel_id"] = r["id"]

    sets, params = [], []
    mapping = [
        ("name","nazov"), ("ean","ean"),
        ("typ","typ"), ("podtyp","podtyp"), ("kategoria","kategoria"),
        ("jednotka","jednotka"), ("mj","mj"),
        ("min_mnozstvo","min_mnozstvo"), ("min_zasoba","min_zasoba"), ("min_stav_kg","min_stav_kg"),
        ("nakupna_cena","nakupna_cena"), ("default_cena_eur_kg","default_cena_eur_kg"),
        ("dodavatel_id","dodavatel_id"), ("dodavatel","dodavatel"),
    ]
    for src, col in mapping:
        if src in d and has(col):
            sets.append(f"{col}=%s"); params.append(d.get(src))

    if not sets:
        return jsonify({"message":"Bez zmien."})

    params.append(old)
    db_connector.execute_query(f"UPDATE sklad SET {', '.join(sets)} WHERE nazov=%s", tuple(params), fetch='none')

    # ak sa mení názov – premenuj aj vo výrobnom sklade
    if "name" in d and (d.get("name") or "").strip() and d["name"].strip() != old:
        db_connector.execute_query("UPDATE sklad_vyroba SET nazov=%s WHERE nazov=%s", (d["name"].strip(), old), fetch='none')

    return jsonify({"message":"Karta uložená."})

# ------------------------- suppliers CRUD --------------------------

@stock_bp.get("/api/kancelaria/suppliers")
def suppliers_list():
    _ensure_suppliers_schema()
    cat = (request.args.get("category") or "").strip().lower() or None
    rows = db_connector.execute_query("SELECT id, name, phone, email, address FROM suppliers WHERE is_active=1 ORDER BY name") or []
    cats = db_connector.execute_query("SELECT supplier_id, category FROM supplier_categories", fetch='all') or []
    by = {}
    for c in cats: by.setdefault(c['supplier_id'], []).append(c['category'])
    out = []
    for r in rows:
        cs = by.get(r['id'], [])
        if cat and cat not in cs: continue
        o = dict(r); o["categories"] = cs
        out.append(o)
    return jsonify({"items": out})

@stock_bp.post("/api/kancelaria/suppliers")
def supplier_create():
    _ensure_suppliers_schema()
    d = request.get_json(force=True) or {}
    name = (d.get("name") or "").strip()
    if not name: return jsonify({"error":"Názov je povinný."}), 400
    phone = d.get("phone"); email = d.get("email"); address = d.get("address")
    new_id = db_connector.execute_query(
        "INSERT INTO suppliers (name, phone, email, address, is_active, created_at, updated_at) VALUES (%s,%s,%s,%s,1,NOW(),NOW())",
        (name, phone, email, address), fetch='lastrowid'
    )
    cats = d.get("categories") or []
    if cats:
        db_connector.execute_query("INSERT INTO supplier_categories (supplier_id, category) VALUES (%s,%s)",
                                   [(new_id, c) for c in cats], multi=True, fetch='none')
    return jsonify({"message":"Dodávateľ pridaný.", "id": new_id})

@stock_bp.put("/api/kancelaria/suppliers/<int:sup_id>")
def supplier_update(sup_id: int):
    _ensure_suppliers_schema()
    d = request.get_json(force=True) or {}
    name = (d.get("name") or "").strip()
    if not name: return jsonify({"error":"Názov je povinný."}), 400
    phone = d.get("phone"); email = d.get("email"); address = d.get("address")
    db_connector.execute_query("UPDATE suppliers SET name=%s, phone=%s, email=%s, address=%s, updated_at=NOW() WHERE id=%s",
                               (name, phone, email, address, sup_id), fetch='none')
    db_connector.execute_query("DELETE FROM supplier_categories WHERE supplier_id=%s", (sup_id,), fetch='none')
    cats = d.get("categories") or []
    if cats:
        db_connector.execute_query("INSERT INTO supplier_categories (supplier_id, category) VALUES (%s,%s)",
                                   [(sup_id, c) for c in cats], multi=True, fetch='none')
    return jsonify({"message":"Dodávateľ upravený."})

@stock_bp.delete("/api/kancelaria/suppliers/<int:sup_id>")
def supplier_delete(sup_id: int):
    _ensure_suppliers_schema()
    db_connector.execute_query("UPDATE suppliers SET is_active=0, updated_at=NOW() WHERE id=%s", (sup_id,), fetch='none')
    return jsonify({"message":"Dodávateľ zmazaný."})
