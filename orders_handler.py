# orders_handler.py
from flask import Blueprint, request, jsonify, Response
from datetime import datetime
import re

try:
    from db_connector import execute_query, get_connection
except Exception:
    raise

orders_bp = Blueprint("orders", __name__)

# ---------- helpers ----------
def has_table(table):
    try:
        r = execute_query("""
            SELECT 1 FROM INFORMATION_SCHEMA.TABLES
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME=%s LIMIT 1
        """, (table,), fetch='one')
        return bool(r)
    except Exception:
        return False

def has_col(table, col):
    try:
        r = execute_query("""
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME=%s AND COLUMN_NAME=%s LIMIT 1
        """, (table, col), fetch='one')
        return bool(r)
    except Exception:
        return False

def pick_first_existing(table, candidates):
    for c in candidates:
        if has_col(table, c):
            return c
    return None

def conn_coll(default='utf8mb4_general_ci'):
    try:
        c = execute_query("SELECT @@collation_connection AS c", fetch='one') or {}
        return c.get('c') or default
    except Exception:
        return default

def _order_dt_expr(alias: str = "o") -> str:
    """
    Bezpečný ORDER BY výraz podľa dostupných stĺpcov (žiadne preklepy).
    Preferencia: datum_dodania -> datum_objednania -> created_at -> id
    """
    cols = []
    if has_col("vyrobne_objednavky", "datum_dodania"):
        cols.append(f"{alias}.datum_dodania")
    if has_col("vyrobne_objednavky", "datum_objednania"):
        cols.append(f"{alias}.datum_objednania")
    if has_col("vyrobne_objednavky", "created_at"):
        cols.append(f"{alias}.created_at")
    if not cols:
        return f"{alias}.id"
    if len(cols) == 1:
        return cols[0]
    return "COALESCE(" + ", ".join(cols) + ")"

# ---------- tiny setup (orders tables) ----------
def ensure_tables():
    execute_query("""
    CREATE TABLE IF NOT EXISTS vyrobne_objednavky (
        id INT AUTO_INCREMENT PRIMARY KEY,
        cislo VARCHAR(64) NOT NULL UNIQUE,
        dodavatel_id INT NULL,
        dodavatel_nazov VARCHAR(255) NOT NULL,
        datum_objednania DATE NOT NULL,
        datum_dodania   DATE NULL,
        stav ENUM('draft','objednane','prijate','zrusene') NOT NULL DEFAULT 'objednane',
        mena CHAR(3) NOT NULL DEFAULT 'EUR',
        poznamka TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB;
    """, fetch='none')

    execute_query("""
    CREATE TABLE IF NOT EXISTS vyrobne_objednavky_polozky (
        id INT AUTO_INCREMENT PRIMARY KEY,
        objednavka_id INT NOT NULL,
        sklad_id INT NULL,
        nazov_suroviny VARCHAR(255) NOT NULL,
        jednotka VARCHAR(16) NOT NULL DEFAULT 'kg',
        mnozstvo_ordered DECIMAL(12,3) NOT NULL,
        cena_predpoklad DECIMAL(12,4) NULL,
        mnozstvo_dodane DECIMAL(12,3) NULL,
        cena_skutocna   DECIMAL(12,4) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_vo_p_obj FOREIGN KEY (objednavka_id)
            REFERENCES vyrobne_objednavky(id) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """, fetch='none')

def init_orders():
    ensure_tables()

# ---------- order number ----------
_slug_rx = re.compile(r"[^A-Z0-9]+")
def supplier_code(name: str) -> str:
    n = (name or "").upper().strip()
    if not n: return "SUP"
    n = _slug_rx.sub("", n)
    return n[:4] or "SUP"

def generate_order_number(dodavatel_nazov: str, datum_obj: str) -> str:
    code = supplier_code(dodavatel_nazov)
    d = datetime.strptime(datum_obj, "%Y-%m-%d").strftime("%Y%m%d")
    prefix = f"{code}-{d}"
    rows = execute_query("""
        SELECT cislo FROM vyrobne_objednavky
         WHERE cislo LIKE %s
         ORDER BY cislo DESC
         LIMIT 1
    """, (prefix + "-%",), fetch='all') or []
    if not rows: return f"{prefix}-001"
    last = rows[0]["cislo"]
    try: n = int(last.rsplit("-", 1)[-1]) + 1
    except Exception: n = 1
    return f"{prefix}-{n:03d}"

# ---------- Pod minimom ----------
@orders_bp.get("/api/sklad/under-min")
def api_under_min():
    id_col    = pick_first_existing("sklad", ["id","sklad_id","produkt_id","product_id","id_skladu"])
    qty_col   = pick_first_existing("sklad", ["mnozstvo","stav_kg","mnozstvo_kg","qty","stav_skladu"])
    min_col   = pick_first_existing("sklad", ["min_mnozstvo","min_stav_kg","min_qty","minimum","min_sklad"])
    price_col = pick_first_existing("sklad", ["default_cena_eur_kg","nakupna_cena","cena","cena_kg"]) or "0"
    unit_col  = pick_first_existing("sklad", ["jednotka","unit","mj"])

    if not qty_col or not min_col:
        return jsonify({"items": []})

    id_sql   = f"s.{id_col} AS id" if id_col else "NULL AS id"
    unit_sql = f"COALESCE(s.{unit_col}, 'kg')" if unit_col else "'kg'"

    rows = execute_query(f"""
        SELECT {id_sql},
               s.nazov,
               {unit_sql} AS jednotka,
               s.{qty_col} AS qty,
               s.{min_col} AS min_qty,
               COALESCE(s.{price_col}, 0) AS price
          FROM sklad s
         WHERE s.{min_col} IS NOT NULL
           AND s.{qty_col} < s.{min_col}
         ORDER BY (s.{min_col} - s.{qty_col}) DESC
         LIMIT 1000
    """, fetch='all') or []

    for r in rows:
        try:
            r["to_buy"] = float(r["min_qty"]) - float(r["qty"])
        except Exception:
            r["to_buy"] = 0.0

    return jsonify({"items": rows})

# ---------- SUPPLIERS ----------
@orders_bp.get("/api/objednavky/suppliers")
def api_suppliers():
    """
    Dodávatelia vhodní pre výrobu – čítame z:
      suppliers(+supplier_categories) / dodavatelia / sklad.dodavatel_id / sklad.dodavatel
    """
    only_vyroba = (str(request.args.get("only_vyroba", "")).lower() in ("1","true","yes","on"))
    coll = conn_coll()
    cat_col = pick_first_existing("sklad", ["kategoria","typ","podtyp"])

    like_parts = []
    allowed_params = []
    if cat_col:
        like_parts = [
            f"s.{cat_col} COLLATE {coll} LIKE %s",
            f"s.{cat_col} COLLATE {coll} LIKE %s",
            f"s.{cat_col} COLLATE {coll} LIKE %s",
            f"s.{cat_col} COLLATE {coll} LIKE %s",
            f"s.{cat_col} COLLATE {coll} LIKE %s",
        ]
        allowed_params = ["koren%","obal%","črev%","cerv%","pomoc%"]

    out = []

    # suppliers (+ categories)
    if has_table("suppliers") and has_col("suppliers","name"):
        has_supcats = has_table("supplier_categories") and has_col("supplier_categories","supplier_id") and has_col("supplier_categories","category")
        if only_vyroba and has_supcats:
            out = execute_query("""
                SELECT s.id, s.name AS nazov
                  FROM suppliers s
                  JOIN supplier_categories c ON c.supplier_id=s.id
                 WHERE s.is_active=1 AND c.category IN ('koreniny','obal','pomocny_material')
                 GROUP BY s.id, s.name
                 ORDER BY s.name
                 LIMIT 1000
            """, fetch='all') or []
        if not out:
            out = execute_query("""
                SELECT s.id, s.name AS nazov
                  FROM suppliers s
                 WHERE s.is_active=1
                 ORDER BY s.name
                 LIMIT 1000
            """, fetch='all') or []

    # dodavatelia (legacy)
    if not out and has_table("dodavatelia") and has_col("dodavatelia","nazov"):
        id_col   = "id" if has_col("dodavatelia","id") else None
        flag_col = pick_first_existing("dodavatelia", ["pre_vyrobu","prijem_do_vyroby","for_production","vyroba"])
        act_col  = pick_first_existing("dodavatelia", ["aktivny","active","enabled","is_active"])
        where_d = []
        if only_vyroba and flag_col: where_d.append(f"d.{flag_col}=1")
        if act_col: where_d.append(f"d.{act_col}=1")
        where_sql = ("WHERE " + " AND ".join(where_d)) if where_d else ""
        out = execute_query(f"""
            SELECT {('d.'+id_col+' AS id,') if id_col else 'NULL AS id,'} d.nazov
              FROM dodavatelia d
              {where_sql}
             ORDER BY d.nazov
             LIMIT 1000
        """, fetch='all') or []

    # sklad.dodavatel_id -> suppliers
    if not out and has_col("sklad","dodavatel_id") and has_table("suppliers") and has_col("suppliers","id") and has_col("suppliers","name"):
        if cat_col and like_parts:
            out = execute_query(f"""
                SELECT DISTINCT s2.id, s2.name AS nazov
                  FROM sklad s
                  JOIN suppliers s2 ON s2.id = s.dodavatel_id
                 WHERE {' OR '.join(like_parts)} AND s2.is_active=1
                 ORDER BY s2.name
                 LIMIT 1000
            """, tuple(allowed_params), fetch='all') or []
        if not out:
            out = execute_query("""
                SELECT DISTINCT s2.id, s2.name AS nazov
                  FROM sklad s
                  JOIN suppliers s2 ON s2.id = s.dodavatel_id
                 WHERE s2.is_active=1
                 ORDER BY s2.name
                 LIMIT 1000
            """, fetch='all') or []

    # sklad.dodavatel (meno)
    if not out and has_col("sklad","dodavatel"):
        if cat_col and like_parts:
            out = execute_query(f"""
                SELECT NULL AS id, TRIM(s.dodavatel) AS nazov
                  FROM sklad s
                 WHERE {' OR '.join(like_parts)} AND s.dodavatel IS NOT NULL AND TRIM(s.dodavatel)<>''
                 GROUP BY TRIM(s.dodavatel)
                 ORDER BY TRIM(s.dodavatel)
                 LIMIT 1000
            """, tuple(allowed_params), fetch='all') or []
        if not out:
            out = execute_query("""
                SELECT NULL AS id, TRIM(s.dodavatel) AS nazov
                  FROM sklad s
                 WHERE s.dodavatel IS NOT NULL AND TRIM(s.dodavatel)<>''
                 GROUP BY TRIM(s.dodavatel)
                 ORDER BY TRIM(s.dodavatel)
                 LIMIT 1000
            """, fetch='all') or []

    return jsonify({"suppliers": out})

# ---------- ITEMS for a supplier ----------
@orders_bp.get("/api/objednavky/items")
def api_items_for_ordering():
    """
    Položky zo 'sklad' pre objednávanie (Koreniny/Obaly/Pomocný materiál – ak vieme; inak heuristika).
    Vracia aj EAN a poslednú reálnu/predpokladanú cenu (last_price), ktorú použijeme ako default.
    """
    dod_id  = request.args.get("dodavatel_id")
    dod_n   = (request.args.get("dodavatel_nazov") or "").strip()
    q       = (request.args.get("q") or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit", 500)), 1000))
    except Exception:
        limit = 500

    id_col    = pick_first_existing("sklad", ["id","sklad_id","produkt_id","product_id","id_skladu"])
    cat_col   = pick_first_existing("sklad", ["kategoria","typ","podtyp"])
    unit_col  = pick_first_existing("sklad", ["jednotka","unit","mj"])
    price_col = pick_first_existing("sklad", ["default_cena_eur_kg","nakupna_cena","cena","cena_kg"])
    has_dod   = has_col("sklad","dodavatel")
    has_dodid = has_col("sklad","dodavatel_id")
    ean_col   = pick_first_existing("sklad", ["ean","ean13","barcode","kod"])

    id_sql    = f"s.{id_col} AS id" if id_col else "NULL AS id"
    unit_sql  = f"COALESCE(s.{unit_col}, 'kg')" if unit_col else "'kg'"
    price_sql = f"COALESCE(s.{price_col}, 0)"   if price_col else "0"
    ean_sql   = f"s.{ean_col} AS ean" if ean_col else "NULL AS ean"

    coll = conn_coll()

    def run(where_parts, params):
        where_sql = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        return execute_query(f"""
            SELECT {id_sql},
                   {ean_sql},
                   s.nazov,
                   {unit_sql} AS jednotka,
                   {price_sql} AS default_price
              FROM sklad s
              {where_sql}
             ORDER BY s.nazov
             LIMIT %s
        """, tuple(params + [limit]), fetch='all') or []

    # filter dodávateľa
    base_where, base_params = [], []
    if dod_id and has_dodid:
        base_where.append("s.dodavatel_id = %s"); base_params.append(int(dod_id))
    elif dod_n:
        if has_dod:
            base_where.append("s.dodavatel = %s"); base_params.append(dod_n)
        elif has_dodid and has_table("suppliers") and has_col("suppliers","id") and has_col("suppliers","name"):
            r = execute_query("SELECT id FROM suppliers WHERE name=%s LIMIT 1",(dod_n,),fetch='one')
            if r: base_where.append("s.dodavatel_id = %s"); base_params.append(r["id"])
    if q:
        base_where.append(f"s.nazov COLLATE {coll} LIKE %s"); base_params.append(f"%{q}%")

    rows = []
    if cat_col:
        like_parts = [f"s.{cat_col} COLLATE {coll} LIKE %s"]*5
        where = base_where + ["(" + " OR ".join(like_parts) + ")", f"s.{cat_col} IS NOT NULL AND s.{cat_col} <> ''"]
        params = base_params + ["koren%","obal%","črev%","cerv%","pomoc%"]
        rows = run(where, params)

    if not rows:
        pats = ["koren%","korenin%","paprik%","cesnak%","km%","rasc%","soľ%","sol%","dusit%",
                "obal%","črev%","cerv%","vak%","fóli%","foli%","sieť%","spag%","špag%",
                "pomoc%","voda%","ľad%","lad%","ovar%"]
        where = base_where + ["(" + " OR ".join([f"s.nazov COLLATE {coll} LIKE %s" for _ in pats]) + ")"]
        params = base_params + pats
        rows = run(where, params)

    # last price helper
    od = _order_dt_expr("o")
    def last_price_for(sklad_id, nazov):
        if sklad_id is not None:
            if dod_id:
                r = execute_query(f"""
                    SELECT COALESCE(p.cena_skutocna, p.cena_predpoklad) AS cena
                      FROM vyrobne_objednavky_polozky p
                      JOIN vyrobne_objednavky o ON o.id=p.objednavka_id
                     WHERE p.sklad_id=%s AND o.dodavatel_id=%s
                     ORDER BY {od} DESC, p.id DESC
                     LIMIT 1
                """, (sklad_id, int(dod_id)), fetch='one')
                if r and r.get("cena") is not None: return float(r["cena"])
            if dod_n:
                r = execute_query(f"""
                    SELECT COALESCE(p.cena_skutocna, p.cena_predpoklad) AS cena
                      FROM vyrobne_objednavky_polozky p
                      JOIN vyrobne_objednavky o ON o.id=p.objednavka_id
                     WHERE p.sklad_id=%s AND o.dodavatel_nazov=%s
                     ORDER BY {od} DESC, p.id DESC
                     LIMIT 1
                """, (sklad_id, dod_n), fetch='one')
                if r and r.get("cena") is not None: return float(r["cena"])
            r = execute_query(f"""
                SELECT COALESCE(p.cena_skutocna, p.cena_predpoklad) AS cena
                  FROM vyrobne_objednavky_polozky p
                  JOIN vyrobne_objednavky o ON o.id=p.objednavka_id
                 WHERE p.sklad_id=%s
                 ORDER BY {od} DESC, p.id DESC
                 LIMIT 1
            """, (sklad_id,), fetch='one')
            if r and r.get("cena") is not None: return float(r["cena"])
        if nazov:
            if dod_n:
                r = execute_query(f"""
                    SELECT COALESCE(p.cena_skutocna, p.cena_predpoklad) AS cena
                      FROM vyrobne_objednavky_polozky p
                      JOIN vyrobne_objednavky o ON o.id=p.objednavka_id
                     WHERE p.nazov_suroviny COLLATE {coll} = %s COLLATE {coll}
                       AND o.dodavatel_nazov=%s
                     ORDER BY {od} DESC, p.id DESC
                     LIMIT 1
                """, (nazov, dod_n), fetch='one')
                if r and r.get("cena") is not None: return float(r["cena"])
            r = execute_query(f"""
                SELECT COALESCE(p.cena_skutocna, p.cena_predpoklad) AS cena
                  FROM vyrobne_objednavky_polozky p
                  JOIN vyrobne_objednavky o ON o.id=p.objednavka_id
                 WHERE p.nazov_suroviny COLLATE {coll} = %s COLLATE {coll}
                 ORDER BY {od} DESC, p.id DESC
                 LIMIT 1
            """, (nazov,), fetch='one')
            if r and r.get("cena") is not None: return float(r["cena"])
        return None

    has_prijem = has_table("zaznamy_prijem") and has_col("zaznamy_prijem","nakupna_cena_eur_kg") and has_col("zaznamy_prijem","nazov_suroviny")
    for r in rows:
        sid   = r.get("id")
        name  = r.get("nazov")
        lp = last_price_for(sid, name)
        if lp is None and has_prijem:
            rr = execute_query(f"""
                SELECT nakupna_cena_eur_kg AS cena
                  FROM zaznamy_prijem
                 WHERE nazov_suroviny COLLATE {coll} = %s COLLATE {coll}
                 ORDER BY datum DESC
                 LIMIT 1
            """, (name,), fetch='one')
            if rr and rr.get("cena") is not None:
                lp = float(rr["cena"])
        r["last_price"] = lp
        try:
            base = float(r.get("default_price") or 0)
        except Exception:
            base = 0.0
        r["default_price"] = float(lp) if lp is not None else base

    return jsonify({"items": rows})

# ---------- list / detail / last price ----------
@orders_bp.get("/api/objednavky")
def list_orders():
    stav = (request.args.get("stav") or "").strip()
    params, where = [], ""
    if stav:
        where = "WHERE o.stav = %s"; params.append(stav)

    rows = execute_query(f"""
        SELECT o.id,
               o.cislo,
               o.dodavatel_nazov,
               o.datum_objednania,
               o.datum_dodania,
               o.stav,
               COALESCE((
                   SELECT SUM(COALESCE(p.cena_predpoklad,0) * COALESCE(p.mnozstvo_ordered,0))
                     FROM vyrobne_objednavky_polozky p
                    WHERE p.objednavka_id = o.id
               ),0) AS suma_predpoklad
          FROM vyrobne_objednavky o
          {where}
         ORDER BY o.created_at DESC
         LIMIT 500
    """, tuple(params), fetch='all') or []
    return jsonify({"orders": rows})

@orders_bp.get("/api/objednavky/<int:oid>")
def order_detail(oid):
    o = execute_query("""SELECT * FROM vyrobne_objednavky WHERE id=%s""", (oid,), fetch='one')
    p = execute_query("""SELECT * FROM vyrobne_objednavky_polozky WHERE objednavka_id=%s ORDER BY id""", (oid,), fetch='all') or []
    return jsonify({"order": o, "items": p})

@orders_bp.get("/api/objednavky/last-price")
def last_price():
    sklad_id = request.args.get("sklad_id")
    nazov    = request.args.get("nazov")
    dod      = request.args.get("dodavatel_nazov")
    where, params = [], []
    if sklad_id: where.append("p.sklad_id = %s"); params.append(sklad_id)
    if nazov:    where.append("p.nazov_suroviny = %s"); params.append(nazov)
    if dod:      where.append("o.dodavatel_nazov = %s"); params.append(dod)
    wh = " AND ".join(where) or "1=1"

    od = _order_dt_expr("o")
    row = execute_query(f"""
        SELECT COALESCE(p.cena_skutocna, p.cena_predpoklad) AS cena
          FROM vyrobne_objednavky_polozky p
          JOIN vyrobne_objednavky o ON o.id = p.objednavka_id
         WHERE {wh}
         ORDER BY {od} DESC, p.id DESC
         LIMIT 1
    """, tuple(params), fetch='one')
    if row and row.get('cena') is not None:
        return jsonify({"cena": row.get("cena")})

    price_col = pick_first_existing("sklad", ["default_cena_eur_kg","nakupna_cena","cena","cena_kg"])
    if not price_col: return jsonify({"cena": None})
    id_col = pick_first_existing("sklad", ["id","sklad_id","produkt_id","product_id","id_skladu"])
    if sklad_id and id_col:
        r = execute_query(f"SELECT {price_col} AS cena FROM sklad WHERE {id_col}=%s", (sklad_id,), fetch='one')
        if r: return jsonify({"cena": r.get("cena")})
    if nazov:
        r = execute_query(f"SELECT {price_col} AS cena FROM sklad WHERE nazov=%s", (nazov,), fetch='one')
        if r: return jsonify({"cena": r.get("cena")})
    return jsonify({"cena": None})

# ---------- create / receive ----------
@orders_bp.post("/api/objednavky")
def create_order():
    data = request.get_json(force=True) or {}
    dod_nazov = (data.get("dodavatel_nazov") or "").strip()
    dod_id    = data.get("dodavatel_id")
    datum     = (data.get("datum_objednania") or datetime.utcnow().strftime("%Y-%m-%d"))[:10]
    polozky   = data.get("polozky") or []

    if not dod_nazov:
        return jsonify({"error": "Chýba dodávateľ"}), 400

    cislo = generate_order_number(dod_nazov, datum)

    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)

        # hlavička
        cur.execute("""
            INSERT INTO vyrobne_objednavky
                (cislo, dodavatel_id, dodavatel_nazov, datum_objednania, stav)
            VALUES (%s, %s, %s, %s, 'objednane')
        """, (cislo, dod_id, dod_nazov, datum))
        oid = cur.lastrowid

        # položky
        for it in polozky:
            nazov = (it.get("nazov") or "").strip()
            if not nazov:
                continue
            jednotka = (it.get("jednotka") or "kg").strip()
            try:
                mnoz = float(it.get("mnozstvo") or 0)
            except Exception:
                mnoz = 0.0
            cena = it.get("cena_predpoklad")
            cena = float(cena) if (cena not in (None, "")) else None
            sklad_id = it.get("sklad_id")

            cur.execute("""
                INSERT INTO vyrobne_objednavky_polozky
                    (objednavka_id, sklad_id, nazov_suroviny, jednotka, mnozstvo_ordered, cena_predpoklad)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (oid, sklad_id, nazov, jednotka, mnoz, cena))

        conn.commit()
        return jsonify({"ok": True, "id": oid, "cislo": cislo})
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        try:
            if conn and conn.is_connected(): conn.close()
        except Exception:
            pass

@orders_bp.put("/api/objednavky/<int:oid>/receive")
def receive_order(oid):
    data = request.get_json(force=True) or {}
    datum_dod = (data.get("datum_dodania") or datetime.utcnow().strftime("%Y-%m-%d"))[:10]
    items     = data.get("polozky") or []
    note      = data.get("poznamka")

    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)

        qty_col = pick_first_existing("sklad", ["mnozstvo","stav_kg","mnozstvo_kg","qty","stav_skladu"])
        id_col  = pick_first_existing("sklad", ["id","sklad_id","produkt_id","product_id","id_skladu"])

        for it in items:
            pid  = int(it.get("polozka_id"))
            try:
                mnoz = float(it.get("mnozstvo_dodane") or 0)
            except Exception:
                mnoz = 0.0
            cena = it.get("cena_skutocna")
            cena = float(cena) if (cena not in (None,"")) else None

            # uložiť skut. údaje
            cur.execute("""
                UPDATE vyrobne_objednavky_polozky
                   SET mnozstvo_dodane=%s, cena_skutocna=%s
                 WHERE id=%s AND objednavka_id=%s
            """, (mnoz, cena, pid, oid))

            if mnoz > 0:
                cur.execute("""
                    SELECT sklad_id, nazov_suroviny
                      FROM vyrobne_objednavky_polozky
                     WHERE id=%s AND objednavka_id=%s
                """, (pid, oid))
                r = cur.fetchone() or {}
                name = r.get("nazov_suroviny")
                sid  = r.get("sklad_id")

                # naskladni do výrobného skladu
                cur.execute("UPDATE sklad_vyroba SET mnozstvo = COALESCE(mnozstvo,0) + %s WHERE nazov=%s", (mnoz, name))
                if cur.rowcount == 0:
                    cur.execute("INSERT INTO sklad_vyroba (nazov, mnozstvo) VALUES (%s, %s)", (name, mnoz))

                # voliteľne navýšiť aj centrál 'sklad'
                if qty_col:
                    if sid and id_col:
                        cur.execute(f"UPDATE sklad SET {qty_col} = COALESCE({qty_col},0) + %s WHERE {id_col}=%s", (mnoz, sid))
                    else:
                        cur.execute(f"UPDATE sklad SET {qty_col} = COALESCE({qty_col},0) + %s WHERE nazov=%s", (mnoz, name))

        # uzavri hlavičku
        cur.execute("""
            UPDATE vyrobne_objednavky
               SET stav='prijate', datum_dodania=%s, poznamka=COALESCE(%s, poznamka)
             WHERE id=%s
        """, (datum_dod, note, oid))

        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        try:
            if conn and conn.is_connected():
                conn.close()
        except Exception:
            pass

@orders_bp.get("/kancelaria/objednavky/print/<int:oid>")
def print_order(oid):
    o = execute_query("SELECT * FROM vyrobne_objednavky WHERE id=%s", (oid,), fetch='one')
    p = execute_query("SELECT * FROM vyrobne_objednavky_polozky WHERE objednavka_id=%s ORDER BY id", (oid,), fetch='all') or []
    if not o: return Response("Objednávka nenájdená", status=404)
    total = 0.0
    for i in p:
        q = float(i.get("mnozstvo_ordered") or 0)
        pr = float((i.get("cena_skutocna") if o["stav"]=='prijate' else i.get("cena_predpoklad")) or 0)
        total += q * pr
    html = f"""
<!doctype html><html><head>
<meta charset="utf-8">
<title>Objednávka {o['cislo']}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif; margin:20px}}
h1{{margin:0 0 6px 0}}
.small{{color:#777;font-size:12px}}
table{{border-collapse:collapse;width:100%;margin-top:14px}}
th,td{{border:1px solid #ccc;padding:6px;text-align:left}}
tfoot td{{font-weight:bold}}
@media print{{ .noprint{{display:none}} }}
</style>
</head><body>
<div class="noprint"><button onclick="print()">Tlačiť</button></div>
<h1>Objednávka č. {o['cislo']}</h1>
<div class="small">Dodávateľ: <b>{o['dodavatel_nazov']}</b> | Dátum objednania: <b>{o['datum_objednania']}</b> | Stav: <b>{o['stav']}</b></div>
{"<div class='small'>Dátum dodania: <b>"+str(o['datum_dodania'])+"</b></div>" if o.get('datum_dodania') else ""}
<table>
<thead><tr><th>#</th><th>Názov</th><th>Jedn.</th><th>Množstvo</th><th>Cena/1</th><th>Medzisúčet</th></tr></thead>
<tbody>
{''.join(f"<tr><td>{i+1}</td><td>{p[i]['nazov_suroviny']}</td><td>{p[i].get('jednotka','kg')}</td><td>{p[i].get('mnozstvo_ordered')}</td><td>{(p[i].get('cena_skutocna') if o['stav']=='prijate' else p[i].get('cena_predpoklad')) or ''}</td><td>{ round((float(p[i].get('mnozstvo_ordered') or 0) * float((p[i].get('cena_skutocna') if o['stav']=='prijate' else p[i].get('cena_predpoklad')) or 0)), 2) }</td></tr>" for i in range(len(p)))}
</tbody>
<tfoot><tr><td colspan="5">Spolu</td><td>{round(total,2)}</td></tr></tfoot>
</table>
</body></html>
"""
    return Response(html, mimetype="text/html")
