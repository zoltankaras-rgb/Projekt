# -*- coding: utf-8 -*-
# ADMIN backend pre B2C (Kancelária)
# - get_orders: vracia objednávky aj s 'polozky' (fallback zo súboru) a dopočíta predbežnú sumu z cenníka, ak chýba
# - finalize_order: uloží finálnu sumu, nastaví stav "Pripravená" a POŠLE e-mail so sumou (uloží aj META pre prípad chýbajúceho stĺpca)
# - credit_points: berie výlučne finálnu sumu (DB -> META), pripíše body, stav "Hotová", POŠLE e-mail
# - order-pdf: vygeneruje PDF z AKTUÁLNYCH cien v B2C cenníku (žiadne nuly)
# - get_customers: rozšírené o narodeniny/marketing/bonus tento mesiac
# - save_product_meta: uloží popis a obrázok do static/uploads/b2c/_b2c_meta.json
# - run_birthday_bonus: hromadný narodeninový bonus (100/150 b.) – idempotentné
# - customers/query + customer/orders + customer/rewards + customer/update_profile + customer/adjust_points
# - kampane (campaign/preview, campaign/send) + reporty/štatistiky (stats/*)
# - delivery windows (get/set), report odmien z META
# - giftcodes (list/upsert/delete/usage/send) – hmotné odmeny bez bodov

from flask import Blueprint, request, jsonify, make_response
from datetime import datetime
import os, json

import db_connector
import pdf_generator
import notification_handler as notify

COLL = "utf8mb4_0900_ai_ci"
kancelaria_b2c_bp = Blueprint("kancelaria_b2c", __name__)

# =================== cesty / storage ===================
BASE_DIR   = os.path.dirname(__file__)
DATA_DIR   = os.path.abspath(os.getenv("APP_DATA_DIR", os.path.join(BASE_DIR, "data")))
ORDERS_DIR = os.path.join(BASE_DIR, "static", "uploads", "orders")
B2C_DIR    = os.path.join(BASE_DIR, "static", "uploads", "b2c")
os.makedirs(ORDERS_DIR, exist_ok=True)
os.makedirs(B2C_DIR, exist_ok=True)

DW_PATH             = os.path.join(B2C_DIR, "_delivery_windows.json")
GIFTCODES_PATH      = os.path.join(B2C_DIR, "_giftcodes.json")
GIFTCODE_USAGE_PATH = os.path.join(B2C_DIR, "_giftcode_usage.json")
PROFILE_JSON_PATH   = os.path.join(DATA_DIR, "b2c_profile.json")
AWARDS_LOG_PATH     = os.path.join(DATA_DIR, "b2c_birthday_awards.json")

# =================== pomocné I/O ===================
def _read_json_or(p, d):
    try:
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f: 
                return json.load(f)
    except Exception:
        pass
    return d

def _write_json(p, data):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: 
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)

def _save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _safe_name(s) -> str:
    return "".join(ch for ch in str(s) if ch.isalnum() or ch in ("-","_"))

def _orders_dir() -> str:
    os.makedirs(ORDERS_DIR, exist_ok=True)
    return ORDERS_DIR

def _items_from_disk(order_no: str):
    fn = os.path.join(_orders_dir(), f"{_safe_name(order_no)}.json")
    try:
        if os.path.isfile(fn):
            with open(fn, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
                items = data.get("items") or []
                if isinstance(items, dict): return [items]
                if isinstance(items, list): return items
    except Exception:
        pass
    return None

# =================== helpery pre schému ===================
def _col_exists(table: str, col: str) -> bool:
    row = db_connector.execute_query("""
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = DATABASE() AND table_name=%s AND column_name=%s
      LIMIT 1
    """, (table, col), fetch="one")
    return bool(row)

def _first_col(table: str, candidates):
    for c in candidates:
        if _col_exists(table, c): return c
    return None

def _coltype(table: str, col: str) -> str:
    r = db_connector.execute_query("""
      SELECT DATA_TYPE dt FROM information_schema.columns
      WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s
      LIMIT 1
    """, (table, col), fetch="one") or {}
    return (r.get("dt") or "").lower()

def _is_numeric(table: str, col: str) -> bool:
    dt = _coltype(table, col)
    return any(k in dt for k in ("int","decimal","float","double","numeric"))

def _add_status(table: str, row_id: int, value: str):
    sc = _first_col(table, ["stav","stav_vybavenia","stav_objednavky","status"])
    if sc:
        db_connector.execute_query(f"UPDATE {table} SET {sc}=%s WHERE id=%s", (value, row_id), fetch="none")

def _get_order_row(order_id_or_number):
    """Riadok objednávky s aliasmi final/predb. + polozky + fk."""
    tbl = "b2c_objednavky"
    idc = _first_col(tbl, ["id"]) or "id"
    noc = _first_col(tbl, ["cislo_objednavky","objednavka_cislo","order_number"])
    itc = _first_col(tbl, ["polozky","polozky_json","items"])
    stc = _first_col(tbl, ["stav","stav_vybavenia","stav_objednavky","status"])
    fg  = _first_col(tbl, ["finalna_suma_s_dph","finalna_suma","final_total_s_dph","suma_s_dph","total_s_dph"])
    pg  = _first_col(tbl, ["predpokladana_suma_s_dph","suma_s_dph","total_s_dph","total_gross"])
    fkc = _first_col(tbl, ["zakaznik_id","customer_id","user_id"])

    cols = [f"o.{idc} AS id"]
    if noc: cols.append(f"o.{noc} AS cislo_objednavky")
    if itc: cols.append(f"o.{itc} AS polozky")
    if stc: cols.append(f"o.{stc} AS stav")
    if fg:  cols.append(f"o.{fg}  AS finalna_suma_s_dph")
    if pg:  cols.append(f"o.{pg}  AS predpokladana_suma_s_dph")
    if fkc: cols.append(f"o.{fkc} AS fk")

    base = f"SELECT {', '.join(cols)} FROM {tbl} o WHERE "
    if isinstance(order_id_or_number, int) or (isinstance(order_id_or_number, str) and order_id_or_number.isdigit()):
        return db_connector.execute_query(base + f"o.{idc}=%s LIMIT 1", (int(order_id_or_number),), fetch="one")
    else:
        if not noc: return None
        return db_connector.execute_query(base + f"o.{noc}=%s LIMIT 1", (str(order_id_or_number),), fetch="one")

def _resolve_customer_fk(order_row: dict) -> tuple[str|None, str|int|None]:
    """('by_zakaznik_id'| 'by_id', value)"""
    tbl = "b2c_objednavky"
    fkc = _first_col(tbl, ["zakaznik_id","customer_id","user_id"])
    if not fkc: return (None, None)
    fk = order_row.get("fk")
    if fkc == "zakaznik_id" and not _is_numeric(tbl, fkc):
        return ("by_zakaznik_id", fk)
    return ("by_id", fk)

def _coalesce_expr(tbl_name: str, alias: str, cols: list[str], out_alias: str) -> str:
    existing = [f"{alias}.{c}" for c in cols if _col_exists(tbl_name, c)]
    if not existing:
        return f"0+0 AS {out_alias}"
    return f"COALESCE({', '.join(existing + ['0'])})+0 AS {out_alias}"

# =================== ceny z cenníka ===================
def _fetch_b2c_prices(eans: list[str]) -> dict:
    base = []
    for e in eans or []:
        s = str(e or "").strip()
        if not s: continue
        base.append(s)
        if s.isdigit() and len(s) < 13:
            base.append(s.zfill(13))
    if not base: return {}
    base = list(dict.fromkeys(base))
    out = {}

    def _acc(rows):
        for r in rows or []:
            e = str(r.get("ean") or r.get("ean_produktu") or "").strip()
            if not e: continue
            out[e] = {
                "dph": float(r.get("dph") or 0.0),
                "cena": float(r.get("cena_bez_dph") or 0.0),
                "je_v_akcii": str(r.get("je_v_akcii") or "").lower() in ("1","true","t","yes","y","áno","ano"),
                "akciova_cena_bez_dph": float(r.get("akciova_cena_bez_dph") or 0.0),
            }

    ph = ",".join(["%s"] * len(base))
    q1 = f"""
      SELECT p.ean, p.dph, c.cena_bez_dph, c.je_v_akcii, c.akciova_cena_bez_dph
      FROM produkty p
      JOIN b2c_cennik_polozky c
        ON p.ean COLLATE {COLL} = c.ean_produktu COLLATE {COLL}
      WHERE p.ean COLLATE {COLL} IN ({ph})
    """
    _acc(db_connector.execute_query(q1, tuple(base)) or [])
    missing = [e for e in base if e not in out]

    if missing:
        ph2 = ",".join(["%s"] * len(missing))
        q2 = f"""
          SELECT p.ean, p.dph, c.cena_bez_dph, c.je_v_akcii, c.akciova_cena_bez_dph
          FROM produkty p
          JOIN b2c_cennik_polozky c
            ON BINARY p.ean = BINARY c.ean_produktu
          WHERE BINARY p.ean IN ({ph2})
        """
        _acc(db_connector.execute_query(q2, tuple(missing)) or [])
        missing = [e for e in missing if e not in out]

    if missing:
        ph3 = ",".join(["%s"] * len(missing))
        cen = db_connector.execute_query(
            f"SELECT ean_produktu, cena_bez_dph, je_v_akcii, akciova_cena_bez_dph "
            f"FROM b2c_cennik_polozky WHERE ean_produktu COLLATE {COLL} IN ({ph3})",
            tuple(missing)
        ) or []
        pro = db_connector.execute_query(
            f"SELECT ean, dph FROM produkty WHERE ean COLLATE {COLL} IN ({ph3})",
            tuple(missing)
        ) or []
        c_map = {str(r["ean_produktu"]).strip(): r for r in cen}
        p_map = {str(r["ean"]).strip(): r for r in pro}
        for e in missing:
            c = c_map.get(e); p = p_map.get(e)
            if c or p:
                out[e] = {
                    "dph": float((p or {}).get("dph") or 0.0),
                    "cena": float((c or {}).get("cena_bez_dph") or 0.0),
                    "je_v_akcii": str((c or {}).get("je_v_akcii") or "").lower() in ("1","true","t","yes","y","áno","ano"),
                    "akciova_cena_bez_dph": float((c or {}).get("akciova_cena_bez_dph") or 0.0),
                }
    return out

# =================== META finálky ===================
def _order_meta_path(order_no: str) -> str:
    return os.path.join(_orders_dir(), f"{_safe_name(order_no)}.meta.json")

def _write_order_meta(order_no: str, meta: dict):
    p = _order_meta_path(order_no)
    try:
        old = {}
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                old = json.load(f) or {}
    except Exception:
        old = {}
    old.update(meta or {})
    with open(p, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=2)

def _read_order_meta(order_no: str) -> dict:
    p = _order_meta_path(order_no)
    try:
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}

# =================== ORDERS ===================
@kancelaria_b2c_bp.get("/api/kancelaria/b2c/get_orders")
def b2c_get_orders():
    """Zoznam objednávok – 'polozky' fallback zo súboru; dopočíta predbežnú sumu z cenníka, ak chýba v DB."""
    tbl = "b2c_objednavky"
    idc   = _first_col(tbl, ["id"]) or "id"
    noc   = _first_col(tbl, ["cislo_objednavky","objednavka_cislo","order_number"])
    datc  = _first_col(tbl, ["datum_objednavky","created_at","created","datum"])
    delc  = _first_col(tbl, ["pozadovany_datum_dodania","datum_dodania","delivery_date"])
    statc = _first_col(tbl, ["stav","stav_vybavenia","stav_objednavky","status"])
    predc = _first_col(tbl, ["predpokladana_suma_s_dph","suma_s_dph","total_s_dph","total_gross"])
    finalc= _first_col(tbl, ["finalna_suma_s_dph","finalna_suma","final_total_s_dph","suma_s_dph","total_s_dph"])
    itemc = _first_col(tbl, ["polozky","polozky_json","items"])
    fkcol = _first_col(tbl, ["zakaznik_id","customer_id","user_id"])
    join_on = "o.zakaznik_id = z.zakaznik_id" if fkcol == "zakaznik_id" and not _is_numeric(tbl, fkcol) else f"o.{fkcol or 'user_id'} = z.id"

    cols = [f"o.{idc} AS id", "z.nazov_firmy AS zakaznik_meno"]
    if noc:   cols.append(f"o.{noc}  AS cislo_objednavky")
    if datc:  cols.append(f"o.{datc} AS datum_objednavky")
    if delc:  cols.append(f"o.{delc} AS pozadovany_datum_dodania")
    if statc: cols.append(f"o.{statc} AS stav")
    if predc: cols.append(f"o.{predc} AS predpokladana_suma_s_dph")
    if finalc:cols.append(f"o.{finalc} AS finalna_suma_s_dph")
    if itemc: cols.append(f"o.{itemc} AS polozky")

    q = f"SELECT {', '.join(cols)} FROM {tbl} o LEFT JOIN b2b_zakaznici z ON {join_on} ORDER BY o.{datc or idc} DESC"
    rows = db_connector.execute_query(q) or []

    for r in rows:
        items = None
        if r.get("polozky") not in (None, "", []):
            if isinstance(r["polozky"], str):
                try: items = json.loads(r["polozky"])
                except Exception: items = None
            elif isinstance(r["polozky"], list):
                items = r["polozky"]
        if items is None and r.get("cislo_objednavky"):
            disk = _items_from_disk(r["cislo_objednavky"])
            if disk is not None:
                items = disk
                r["polozky"] = json.dumps(disk, ensure_ascii=False)

        if (r.get("predpokladana_suma_s_dph") in (None, 0, 0.0)) and items:
            eans   = [it.get("ean") for it in items if it and it.get("ean")]
            prices = _fetch_b2c_prices(eans)
            gross = 0.0
            for it in items:
                e = str(it.get("ean") or "").strip()
                q = float(it.get("quantity") or it.get("mnozstvo") or 0)
                p = prices.get(e) or (prices.get(e.zfill(13)) if e.isdigit() else None)
                d = float((p or {}).get("dph") or 0.0)
                n = float((p or {}).get("akciova_cena_bez_dph") or 0.0) if (p and p.get("je_v_akcii") and p.get("akciova_cena_bez_dph")) else float((p or {}).get("cena") or 0.0)
                gross += q * (n * (1.0 + d/100.0))
            r["predpokladana_suma_s_dph"] = float(f"{gross:.2f}")

    return jsonify(rows)

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/finalize_order")
def b2c_finalize_order():
    data = request.get_json(silent=True) or request.form.to_dict(flat=True) or {}

    def pick(d, keys):
        for k in keys:
            if k in d and d[k] not in (None, "", []):
                return d[k]
        return None

    def parse_price(raw):
        if raw is None:
            return None
        s = str(raw).strip().replace("€", "").replace("\u00a0", " ")
        if "," in s and "." in s and s.find(".") < s.rfind(","):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(" ", "")
            if "," in s and "." not in s:
                s = s.replace(",", ".")
        return round(float(s), 2)

    order_key = pick(data, ["order_id", "id", "order"])
    final_price = parse_price(pick(data, ["final_price", "final_gross", "total_gross", "suma_s_dph"]))
    if order_key is None or final_price is None:
        return jsonify({"error": "Chýba order_id alebo finálna cena."}), 400

    # Načítaj objednávku podľa ID
    row = _get_order_row(order_key)
    if not row:
        return jsonify({"error": "Objednávka neexistuje."}), 404

    tbl = "b2c_objednavky"
    # Nájdeme prvý existujúci cieľový stĺpec pre finálnu sumu (bez ALTERov)
    dest = next((c for c in [
        "finalna_suma_s_dph", "finalna_suma", "final_total_s_dph", "suma_s_dph", "total_s_dph", "predpokladana_suma_s_dph"
    ] if _first_col(tbl, [c])), None)

    order_no = row.get("cislo_objednavky") or str(row["id"])

    # Uložíme finálku do DB, ak máme vhodný stĺpec; vždy uložíme aj do META
    if dest:
        db_connector.execute_query(f"UPDATE {tbl} SET {dest}=%s WHERE id=%s",
                                   (final_price, row["id"]), fetch="none")
    _write_order_meta(order_no, {
        "final_gross": float(f"{final_price:.2f}"),
        "saved_at": datetime.utcnow().isoformat() + "Z"
    })

    # Stav -> Pripravená
    _add_status(tbl, row["id"], "Pripravená")

    # E-mail + SMS (cez notification_handler; SMS sa pošle automaticky s e-mailom)
    try:
        mode, fk_val = _resolve_customer_fk(row)
        cust = None
        if fk_val:
            if mode == "by_zakaznik_id" and not _is_numeric(tbl, "zakaznik_id"):
                cust = db_connector.execute_query(
                    "SELECT email FROM b2b_zakaznici WHERE zakaznik_id=%s", (fk_val,), fetch="one")
            else:
                cust = db_connector.execute_query(
                    "SELECT email FROM b2b_zakaznici WHERE id=%s", (int(fk_val),), fetch="one")
        to_mail = (cust or {}).get("email")
        if to_mail:
            notify.send_b2c_order_ready_email(to_mail, order_no, final_price)
    except Exception:
        # nechceme, aby kvôli notifikácii padla API odpoveď
        pass

    return jsonify({
        "message": "Objednávka pripravená.",
        "order_id": row["id"],
        "final_price": float(f"{final_price:.2f}")
    })

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/credit_points")
def b2c_credit_points():
    data = request.get_json(silent=True) or {}
    order_id = data.get("order_id")
    if order_id is None:
        return jsonify({"error": "Chýba order_id."}), 400

    row = _get_order_row(order_id)
    if not row:
        return jsonify({"error": "Objednávka neexistuje."}), 404

    # Zisťujeme finálku z DB, prípadne z META, ak stĺpec nemáme
    final = 0.0
    for c in ("finalna_suma_s_dph", "finalna_suma", "final_total_s_dph", "suma_s_dph", "total_s_dph"):
        if c in row and row[c] not in (None, 0, 0.0):
            try:
                final = float(row[c]); break
            except Exception:
                pass

    order_no = row.get("cislo_objednavky") or str(row["id"])
    if final <= 0:
        meta = _read_order_meta(order_no)
        try:
            final = float(meta.get("final_gross") or 0.0)
        except Exception:
            final = 0.0
    if final <= 0:
        return jsonify({"error": "Finálna suma nie je zadaná. Najprv označ objednávku ako 'Pripravená' s finálnou sumou."}), 400

    # 1 bod = 1 €
    points = int(final)

    # Pripíš body zákazníkovi (bez ALTERov, robustne podľa FK režimu)
    mode, fk_val = _resolve_customer_fk(row)
    if not fk_val:
        return jsonify({"error": "Objednávka nemá priradeného zákazníka."}), 400

    if mode == "by_zakaznik_id" and not _is_numeric("b2c_objednavky", "zakaznik_id"):
        db_connector.execute_query(
            "UPDATE b2b_zakaznici SET vernostne_body = COALESCE(vernostne_body,0) + %s WHERE zakaznik_id=%s",
            (points, fk_val), fetch="none"
        )
        cust = db_connector.execute_query(
            "SELECT email FROM b2b_zakaznici WHERE zakaznik_id=%s", (fk_val,), fetch="one")
    else:
        db_connector.execute_query(
            "UPDATE b2b_zakaznici SET vernostne_body = COALESCE(vernostne_body,0) + %s WHERE id=%s",
            (points, int(fk_val)), fetch="none"
        )
        cust = db_connector.execute_query(
            "SELECT email FROM b2b_zakaznici WHERE id=%s", (int(fk_val),), fetch="one")

    # Stav -> Hotová
    _add_status("b2c_objednavky", row["id"], "Hotová")

    # E-mail + SMS (cez notification_handler; SMS sa pošle automaticky s e-mailom)
    try:
        to_mail = (cust or {}).get("email")
        if to_mail:
            notify.send_b2c_order_completed_email(to_mail, order_no, float(f"{final:.2f}"), points)
    except Exception:
        pass

    return jsonify({
        "message": "Objednávka ukončená, body pripísané.",
        "total_paid": float(f"{final:.2f}"),
        "credited": points
    })

@kancelaria_b2c_bp.get("/api/kancelaria/b2c/order-pdf")
def b2c_order_pdf():
    order_key = request.args.get("order_id") or request.args.get("order_no") or request.args.get("id")
    if not order_key:
        return jsonify({"error": "Chýba order_id."}), 400

    row = _get_order_row(order_key)
    if not row:
        return jsonify({"error": "Objednávka neexistuje."}), 404

    mode, fk_val = _resolve_customer_fk(row)
    if not fk_val:
        return jsonify({"error": "Objednávka nemá priradeného zákazníka."}), 400
    if mode == "by_zakaznik_id" and not _is_numeric("b2c_objednavky", "zakaznik_id"):
        customer = db_connector.execute_query("SELECT * FROM b2b_zakaznici WHERE zakaznik_id=%s", (fk_val,), fetch="one")
    else:
        customer = db_connector.execute_query("SELECT * FROM b2b_zakaznici WHERE id=%s", (int(fk_val),), fetch="one")
    if not customer:
        return jsonify({"error": "Zákazník nebol nájdený."}), 404

    items = None
    raw = row.get("polozky")
    if isinstance(raw, str) and raw.strip():
        try: items = json.loads(raw)
        except Exception: items = None
    elif isinstance(raw, (list, dict)):
        items = raw if isinstance(raw, list) else [raw]
    if items is None:
        order_no = row.get("cislo_objednavky") or row.get("id")
        items = _items_from_disk(order_no) or []

    prices = _fetch_b2c_prices([it.get("ean") for it in items if it.get("ean")])
    total_net = total_gross = 0.0
    enriched = []
    for it in items:
        e = str(it.get("ean") or "").strip()
        q = float(it.get("quantity") or it.get("mnozstvo") or 0)
        p = prices.get(e) or (prices.get(e.zfill(13)) if e.isdigit() else None)
        d = float((p or {}).get("dph") or 0.0)
        n = float((p or {}).get("akciova_cena_bez_dph") or 0.0) if (p and p.get("je_v_akcii") and p.get("akciova_cena_bez_dph")) else float((p or {}).get("cena") or 0.0)
        g = n * (1.0 + d/100.0)
        total_net   += n * q
        total_gross += g * q
        enriched.append({**it, "price_bez_dph": n, "price_s_dph": g, "dph_percent": d})

    order_no = row.get("cislo_objednavky") or row.get("id")
    order_data = {
        "order_number":     order_no,
        "deliveryDate":     row.get("pozadovany_datum_dodania"),
        "note":             "",
        "customerName":     customer.get("nazov_firmy"),
        "customerLoginId":  customer.get("zakaznik_id") or customer.get("id"),
        "customerAddress":  customer.get("adresa_dorucenia", customer.get("adresa")),
        "customerEmail":    customer.get("email"),
        "items":            enriched,
        "totalNet":         total_net,
        "totalVat":         (total_gross - total_net),
        "totalGross":       total_gross,
        "order_date":       datetime.now().strftime("%d.%m.%Y"),
        "uplatnena_odmena_poznamka": row.get("uplatnena_odmena_poznamka"),
    }

    # doplň doplnky z META, ak sú (napr. delivery_window/rewards)
    meta = _read_order_meta(order_no)
    if meta.get("delivery_window"): order_data["delivery_window"] = meta["delivery_window"]
    if meta.get("rewards"):         order_data["rewards"] = meta["rewards"]

    pdf, _ = pdf_generator.create_order_files(order_data)
    resp = make_response(pdf)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'inline; filename="objednavka_{order_no}.pdf"'
    return resp

# =================== CUSTOMERS (výbery) ===================
def _sk_month_genitive(m: int) -> str:
    names = ["januára","februára","marca","apríla","mája","júna","júla","augusta","septembra","októbra","novembra","decembra"]
    return names[(m-1) % 12]

@kancelaria_b2c_bp.get("/api/kancelaria/b2c/get_customers")
def b2c_get_customers():
    rows = db_connector.execute_query("""
      SELECT id, zakaznik_id, nazov_firmy, email, telefon, adresa, adresa_dorucenia,
             COALESCE(vernostne_body,0) AS vernostne_body
      FROM b2b_zakaznici
      WHERE typ='B2C'
      ORDER BY id DESC
    """) or []

    profiles   = _load_json(PROFILE_JSON_PATH, {}) or {}
    awards_log = _load_json(AWARDS_LOG_PATH, {}) or {}
    now = datetime.now(); bucket = f"{now.year:04d}-{now.month:02d}"
    awarded_this_month = (awards_log.get(bucket) or {})

    for r in rows:
        email_key = (r.get("email") or "").lower()
        prof = profiles.get(email_key) or profiles.get(r.get("email") or "")
        m = (prof or {}).get("marketing") or {}
        r["marketing_email"]      = bool(m.get("email"))
        r["marketing_sms"]        = bool(m.get("sms"))
        r["marketing_newsletter"] = bool(m.get("newsletter"))
        dob = (prof or {}).get("dob") or {}
        mm = None
        if isinstance(dob.get("md"), str) and len(dob["md"]) >= 2:
            try: mm = int(dob["md"].split("-")[0])
            except: mm = None
        elif isinstance(dob.get("iso_ymd"), str) and len(dob["iso_ymd"]) >= 7:
            try: mm = int(dob["iso_ymd"].split("-")[1])
            except: mm = None
        r["dob_month"] = mm
        r["dob_year_known"] = bool(dob.get("iso_ymd"))
        award = awarded_this_month.get(email_key) or awarded_this_month.get(r.get("email") or "")
        r["birthday_points_this_month"] = int((award or {}).get("points") or 0)

    return jsonify(rows)

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/save_product_meta")
def save_product_meta():
    data = request.get_json(silent=True) or {}
    ean = str(data.get("ean") or "").strip()
    if not ean:
        return jsonify({"error": "Chýba EAN."}), 400
    desc = (data.get("description") or "").strip()
    img  = (data.get("image_url") or "").strip()

    meta_path = os.path.join(B2C_DIR, "_b2c_meta.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    try:
        meta = {}
        if os.path.isfile(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f) or {}
    except Exception:
        meta = {}

    rec = meta.get(ean) or {}
    if desc != "": rec["popis"]   = desc
    if img  != "": rec["obrazok"] = img
    meta[ean] = rec

    _save_json(meta_path, meta)
    return jsonify({"message": "Produktové meta uložené.", "ean": ean, "description": rec.get("popis",""), "image_url": rec.get("obrazok","")})

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/run_birthday_bonus")
def run_birthday_bonus():
    expected = os.getenv("B2C_BDAY_SECRET")
    provided = request.args.get("secret") or (request.json.get("secret") if isinstance(request.json, dict) else None)
    if expected and provided != expected:
        return jsonify({"error": "unauthorized"}), 403

    now = datetime.now()
    year  = int(request.args.get("year")  or (request.json or {}).get("year")  or now.year)
    month = int(request.args.get("month") or (request.json or {}).get("month") or now.month)
    dry   = str(request.args.get("dry_run") or (request.json or {}).get("dry_run") or "0").lower() in ("1","true","yes","y")

    profiles   = _load_json(PROFILE_JSON_PATH, {}) or {}
    awards_log = _load_json(AWARDS_LOG_PATH, {}) or {}
    bucket_key = f"{year:04d}-{month:02d}"
    if bucket_key not in awards_log:
        awards_log[bucket_key] = {}

    month_gen = _sk_month_genitive(month)
    awarded, skipped = [], []

    for email, prof in (profiles or {}).items():
        try:
            if not prof or not prof.get("birthday_bonus_opt_in"):
                continue
            dob = prof.get("dob") or {}
            mm = None
            if isinstance(dob.get("md"), str) and len(dob["md"]) >= 2:
                mm = int(dob["md"].split("-")[0])
            elif isinstance(dob.get("iso_ymd"), str) and len(dob["iso_ymd"]) >= 7:
                mm = int(dob["iso_ymd"].split("-")[1])
            if mm != month:
                continue

            key = email.lower()
            if key in awards_log[bucket_key]:
                skipped.append({"email": email, "reason": "already_credited"})
                continue

            cust = db_connector.execute_query(
                "SELECT id, email, nazov_firmy FROM b2b_zakaznici WHERE LOWER(email)=LOWER(%s) AND typ='B2C' LIMIT 1",
                (email,), fetch="one"
            )
            if not cust:
                skipped.append({"email": email, "reason": "customer_not_found"})
                continue

            milestone = False
            points = 100
            age = None
            if isinstance(dob.get("iso_ymd"), str) and len(dob["iso_ymd"]) >= 4:
                try:
                    birth_year = int(dob["iso_ymd"].split("-")[0])
                    age = year - birth_year
                    if age >= 20 and age % 5 == 0:
                        milestone = True
                        points = 150
                except Exception:
                    pass

            if not dry:
                db_connector.execute_query(
                    "UPDATE b2b_zakaznici SET vernostne_body = COALESCE(vernostne_body,0) + %s WHERE id=%s",
                    (points, int(cust["id"])), fetch="none"
                )
                try:
                    notify.send_b2c_birthday_bonus_email(
                        cust.get("email"),
                        prof.get("name") or (cust.get("nazov_firmy") or ""),
                        month_gen,
                        points,
                        milestone,
                        age
                    )
                except Exception:
                    pass

                awards_log[bucket_key][key] = {"points": points, "ts": datetime.utcnow().isoformat()+"Z"}

            awarded.append({"email": email, "points": points, "milestone": milestone})
        except Exception as e:
            skipped.append({"email": email, "error": str(e)})

    _save_json(AWARDS_LOG_PATH, awards_log)

    return jsonify({
        "ok": True, "year": year, "month": month,
        "awarded_count": len(awarded), "awarded": awarded, "skipped":  skipped,
        "dry_run":  dry
    })

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/customers/query")
def customers_query():
    """
    POST JSON: { q, month_bday, has_orders, marketing_email, marketing_sms, marketing_newsletter,
                 min_points, page, page_size, sort_by, sort_dir }
    Vracia: { rows:[...], total, page, page_size }
    """
    body = request.get_json(silent=True) or {}
    q = (body.get("q") or "").strip().lower()
    month_bday = bool(body.get("month_bday"))
    has_orders = bool(body.get("has_orders"))
    m_email = bool(body.get("marketing_email"))
    m_sms   = bool(body.get("marketing_sms"))
    m_news  = bool(body.get("marketing_newsletter"))
    min_points = int(body.get("min_points") or 0)
    page = max(1, int(body.get("page") or 1))
    page_size = max(1, min(200, int(body.get("page_size") or 50)))
    sort_by = (body.get("sort_by") or "id").lower()
    sort_dir= (body.get("sort_dir") or "desc").lower()
    if sort_dir not in ("asc","desc"): sort_dir="desc"

    rows = db_connector.execute_query("""
      SELECT z.id, z.zakaznik_id, z.nazov_firmy, z.email, z.telefon, z.adresa, z.adresa_dorucenia,
             COALESCE(z.vernostne_body,0) AS vernostne_body
      FROM b2b_zakaznici z
      WHERE z.typ='B2C'
    """) or []
    profiles = _load_json(PROFILE_JSON_PATH, {}) or {}

    final_expr = _coalesce_expr(
        "b2c_objednavky", "o",
        ["finalna_suma_s_dph","finalna_suma","final_total_s_dph","suma_s_dph","total_s_dph"],
        "finalka"
    )
    pred_expr = _coalesce_expr(
        "b2c_objednavky", "o",
        ["predpokladana_suma_s_dph","suma_s_dph","total_s_dph","total_gross"],
        "pred"
    )
    noc = _first_col("b2c_objednavky", ["cislo_objednavky","objednavka_cislo","order_number"])
    dat = _first_col("b2c_objednavky", ["datum_objednavky","created_at","created","datum"])

    select_cols = ["z.id AS cust_id"]
    if noc: select_cols.append(f"o.{noc} AS cislo_objednavky")
    if dat: select_cols.append(f"o.{dat} AS datum_objednavky")
    select_cols += [final_expr, pred_expr]

    join_parts = []
    if _col_exists("b2c_objednavky", "zakaznik_id"):
        if _is_numeric("b2c_objednavky", "zakaznik_id"):
            join_parts.append("o.zakaznik_id = z.id")
        else:
            join_parts.append("o.zakaznik_id = z.zakaznik_id")
    if _col_exists("b2c_objednavky", "customer_id"):
        join_parts.append("o.customer_id = z.id")
    if _col_exists("b2c_objednavky", "user_id"):
        join_parts.append("o.user_id = z.id")

    orders_map = {}
    if join_parts:
        ord_rows = db_connector.execute_query(
            f"SELECT {', '.join(select_cols)} FROM b2c_objednavky o "
            f"JOIN b2b_zakaznici z ON ({' OR '.join(join_parts)}) WHERE z.typ='B2C'"
        ) or []
        for r in ord_rows:
            cid = r["cust_id"]
            m = orders_map.setdefault(cid, {"count":0,"last":None,"final_sum":0.0})
            m["count"] += 1
            if r.get("datum_objednavky") and (m["last"] is None or r["datum_objednavky"]>m["last"]):
                m["last"] = r["datum_objednavky"]
            m["final_sum"] += float(r.get("finalka") or 0.0)

    now = datetime.now(); cur_m = now.month
    out = []
    for r in rows:
        email_key = (r.get("email") or '').lower()
        prof = profiles.get(email_key) or profiles.get(r.get("email") or "")
        mkt = (prof or {}).get("marketing") or {}
        dob = (prof or {}).get("dob") or {}
        mm = None
        if isinstance(dob.get("md"), str) and len(dob["md"])>=2:
            try: mm = int(dob["md"].split("-")[0])
            except: mm = None
        elif isinstance(dob.get("iso_ymd"), str) and len(dob["iso_ymd"])>=7:
            try: mm = int(dob["iso_ymd"].split("-")[1])
            except: mm = None

        rec = {
            **r,
            "marketing_email": bool(mkt.get("email")),
            "marketing_sms":   bool(mkt.get("sms")),
            "marketing_newsletter": bool(mkt.get("newsletter")),
            "dob_month": mm,
            "dob_year_known": bool(dob.get("iso_ymd")),
            "birthday_bonus_opt_in": bool((prof or {}).get("birthday_bonus_opt_in"))
        }
        ord_info = orders_map.get(r["id"]) or {"count":0,"last":None,"final_sum":0.0}
        rec["orders_count"]    = ord_info["count"]
        rec["last_order_date"] = ord_info["last"]
        rec["final_paid_sum"]  = ord_info["final_sum"]

        if q:
            hay = f'{(rec.get("zakaznik_id") or "")} {(rec.get("nazov_firmy") or "")} {(rec.get("email") or "")}'.lower()
            if q not in hay: continue
        if month_bday and (mm != cur_m): continue
        if has_orders and ord_info["count"]<=0: continue
        if m_email and not rec["marketing_email"]: continue
        if m_sms   and not rec["marketing_sms"]: continue
        if m_news  and not rec["marketing_newsletter"]: continue
        if rec["vernostne_body"] < min_points: continue

        out.append(rec)

    key = sort_by; rev = (sort_dir=='desc')
    def sort_key(x):
        if key in ('vernostne_body','orders_count','final_paid_sum'): return float(x.get(key) or 0)
        if key in ('last_order_date',): return x.get(key) or ''
        return str(x.get(key) or '').lower()
    out.sort(key=sort_key, reverse=rev)

    total = len(out); start = (page-1)*page_size; end = start + page_size
    return jsonify({ "rows": out[start:end], "total": total, "page": page, "page_size": page_size })

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/customer/update_profile")
def customer_update_profile():
    data = request.get_json(silent=True) or {}
    cust_id = data.get("customer_id")
    if not cust_id: return jsonify({"error":"Chýba customer_id."}), 400

    if any(k in data for k in ("name","phone","address","delivery_address")):
        sets, vals = [], []
        if data.get("name") is not None:             sets.append("nazov_firmy=%s");       vals.append(data.get("name"))
        if data.get("phone") is not None:            sets.append("telefon=%s");           vals.append(data.get("phone"))
        if data.get("address") is not None:          sets.append("adresa=%s");            vals.append(data.get("address"))
        if data.get("delivery_address") is not None: sets.append("adresa_dorucenia=%s");  vals.append(data.get("delivery_address"))
        if sets:
            vals.append(int(cust_id))
            db_connector.execute_query(f"UPDATE b2b_zakaznici SET {', '.join(sets)} WHERE id=%s", tuple(vals), fetch="none")

    profiles = _load_json(PROFILE_JSON_PATH, {}) or {}
    cust = db_connector.execute_query("SELECT email, nazov_firmy FROM b2b_zakaznici WHERE id=%s", (int(cust_id),), fetch="one")
    if not cust or not cust.get("email"):
        return jsonify({"error":"Zákazník neexistuje alebo nemá e-mail."}), 400
    key = (cust["email"] or "").lower()

    prof = profiles.get(key) or {}
    if data.get("birthday_bonus_opt_in") is not None:
        prof["birthday_bonus_opt_in"] = bool(data["birthday_bonus_opt_in"])
    mk = prof.get("marketing") or {}
    if isinstance(data.get("marketing"), dict):
        for k in ("email","sms","newsletter"):
            if data["marketing"].get(k) is not None: mk[k] = bool(data["marketing"][k])
    prof["marketing"] = mk
    if isinstance(data.get("dob"), dict):
        dob = prof.get("dob") or {}
        md = data["dob"].get("md"); iso= data["dob"].get("iso_ymd")
        dob["md"] = md if md else None; dob["iso_ymd"] = iso if iso else None
        prof["dob"] = dob
    if data.get("name") and not prof.get("name"): prof["name"] = data.get("name")

    profiles[key] = prof
    _save_json(PROFILE_JSON_PATH, profiles)
    return jsonify({"message":"Profil uložený."})

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/customer/adjust_points")
def customer_adjust_points():
    d = request.get_json(silent=True) or {}
    cust_id = d.get("customer_id"); delta = d.get("delta")
    if not cust_id or not isinstance(delta, (int, float)) or delta==0:
        return jsonify({"error":"Chýba customer_id alebo nenulový delta."}), 400

    db_connector.execute_query(
        "UPDATE b2b_zakaznici SET vernostne_body = COALESCE(vernostne_body,0) + %s WHERE id=%s",
        (int(delta), int(cust_id)), fetch="none"
    )

    notify_flag = str(d.get("notify") or "0").lower() in ("1","true","yes","y")
    if notify_flag:
        cust = db_connector.execute_query("SELECT email, nazov_firmy FROM b2b_zakaznici WHERE id=%s", (int(cust_id),), fetch="one")
        if cust and cust.get("email"):
            try:
                tmpl = (d.get("template") or "").strip() or None
                msg  = (d.get("custom_message") or "").strip() or None
                if hasattr(notify, "send_points_awarded_email"):
                    notify.send_points_awarded_email(cust["email"], int(delta), tmpl, msg)
            except Exception:
                pass

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "b2c_points_adjustments.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.utcnow().isoformat()+"Z", "customer_id":int(cust_id), "delta":int(delta), "reason": d.get("reason")}, ensure_ascii=False) + "\n")
    return jsonify({"message":"Body upravené."})

@kancelaria_b2c_bp.get("/api/kancelaria/b2c/customer/orders")
def customer_orders():
    cust_id = request.args.get("customer_id", type=int)
    if not cust_id: return jsonify([])

    tbl = "b2c_objednavky"
    fk = _first_col(tbl, ["zakaznik_id","customer_id","user_id"])
    if not fk: return jsonify([])

    if fk == "zakaznik_id" and not _is_numeric(tbl, fk):
        key = db_connector.execute_query("SELECT zakaznik_id FROM b2b_zakaznici WHERE id=%s", (cust_id,), fetch="one")
        if not key or not key.get("zakaznik_id"): return jsonify([])
        fk_val = key["zakaznik_id"]
    else:
        fk_val = cust_id

    dat  = _first_col(tbl, ["datum_objednavky","created_at","created","datum"]) or "id"
    noc  = _first_col(tbl, ["cislo_objednavky","objednavka_cislo","order_number"]) or "id"
    delv = _first_col(tbl, ["pozadovany_datum_dodania","datum_dodania","delivery_date"])
    pred = _first_col(tbl, ["predpokladana_suma_s_dph","suma_s_dph","total_s_dph","total_gross"])
    fin  = _first_col(tbl, ["finalna_suma_s_dph","finalna_suma","final_total_s_dph","suma_s_dph","total_s_dph"])
    st   = _first_col(tbl, ["stav","stav_vybavenia","stav_objednavky","status"])
    cols = ["id", f"{noc} AS cislo_objednavky"]
    if dat: cols.append(dat+" AS datum_objednavky")
    if delv:cols.append(delv+" AS pozadovany_datum_dodania")
    if pred:cols.append(pred+" AS predpokladana_suma_s_dph")
    if fin: cols.append(fin+" AS finalna_suma_s_dph")
    if st:  cols.append(st+" AS stav")
    q = f"SELECT {', '.join(cols)} FROM {tbl} WHERE {fk}=%s ORDER BY {dat} DESC"
    return jsonify(db_connector.execute_query(q, (fk_val,)) or [])

@kancelaria_b2c_bp.get("/api/kancelaria/b2c/customer/rewards")
def customer_rewards():
    cust_id = request.args.get("customer_id", type=int)
    if not cust_id: return jsonify([])
    tbl = "b2c_uplatnene_odmeny"
    fkc = _first_col(tbl, ["zakaznik_id","customer_id","user_id"])
    fkval = cust_id
    if fkc == "zakaznik_id" and not _is_numeric("b2c_uplatnene_odmeny","zakaznik_id"):
        row = db_connector.execute_query("SELECT zakaznik_id FROM b2b_zakaznici WHERE id=%s",(cust_id,),fetch="one")
        if not row or not row.get("zakaznik_id"): return jsonify([])
        fkval = row["zakaznik_id"]
    cols = ["id","nazov_odmeny","pouzite_body"]
    if _col_exists(tbl,"datum_vytvorenia"): cols.append("datum_vytvorenia")
    elif _col_exists(tbl,"created_at"):     cols.append("created_at AS datum_vytvorenia")
    if _col_exists(tbl,"objednavka_id"):    cols.append("objednavka_id")
    q = f"SELECT {', '.join(cols)} FROM {tbl} WHERE {fkc}=%s ORDER BY id DESC LIMIT 200"
    return jsonify(db_connector.execute_query(q,(fkval,)) or [])

# =================== kampane ===================
@kancelaria_b2c_bp.post("/api/kancelaria/b2c/campaign/preview")
def campaign_preview():
    """
    Náhľad adresátov kampane podľa filtrov (rovnaké kľúče ako customers/query).
    POST: { q, month_bday, has_orders, marketing_email, marketing_sms, marketing_newsletter, min_points }
    Vracia: { count, sample:[{email,name,vernostne_body,...} (max 20)] }
    """
    filt = request.get_json(silent=True) or {}
    res = customers_query().get_json()
    rows = res.get("rows") or []
    want_news = bool(filt.get("marketing_newsletter"))
    want_email= bool(filt.get("marketing_email"))
    filtered = []
    for r in rows:
        ok = True
        if want_news and not r.get("marketing_newsletter"): ok=False
        if want_email and not r.get("marketing_email"): ok=False
        if ok: filtered.append(r)
    return jsonify({"count": len(filtered), "sample": filtered[:20]})

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/campaign/send")
def campaign_send():
    """
    Hromadná kampaň: pošle e-mail a voliteľne pripíše body.
    POST:
      {
        "filters": { ... ako customers/query ... },
        "subject": "Predmet",
        "html": "<p>Text...</p>",
        "template": "10orders|campaign|goodwill|None",
        "custom_message": "text",
        "points_delta": 0,
        "respect_optin": true
      }
    """
    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip()
    html    = (data.get("html") or "").strip()
    template= (data.get("template") or "").strip() or None
    custom  = (data.get("custom_message") or "").strip() or None
    delta   = int(data.get("points_delta") or 0)
    respect_optin = True if data.get("respect_optin", True) else False

    res = customers_query().get_json()
    candidates = res.get("rows") or []

    recipients = []
    for r in candidates:
        if not r.get("email"): continue
        if respect_optin and not (r.get("marketing_email") or r.get("marketing_newsletter")):
            continue
        recipients.append(r)

    camp_dir = os.path.join(DATA_DIR, "campaigns"); os.makedirs(camp_dir, exist_ok=True)
    camp_log = os.path.join(camp_dir, f"b2c_campaigns.jsonl")

    sent = 0; awarded = 0; errors = 0
    for r in recipients:
        to = r["email"]
        try:
            mail_html = html or f"<p>{custom or 'Ďakujeme, že ste s nami.'}</p>"
            try:
                if hasattr(notify, "send_points_awarded_email") and delta:
                    notify.send_points_awarded_email(to, delta, template, custom)
                else:
                    notify._send_email(to, subject or "Informácia od MIK s.r.o.", notify._wrap_html("Informácia od MIK s.r.o.", mail_html))
            except Exception:
                notify._send_email(to, subject or "Informácia od MIK s.r.o.", notify._wrap_html("Informácia od MIK s.r.o.", mail_html))
            sent += 1
        except Exception:
            errors += 1

        if delta:
            try:
                db_connector.execute_query(
                    "UPDATE b2b_zakaznici SET vernostne_body=COALESCE(vernostne_body,0)+%s WHERE id=%s",
                    (delta, int(r["id"])), fetch="none"
                )
                awarded += 1
            except Exception:
                errors += 1

        with open(camp_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.utcnow().isoformat()+"Z",
                "email": to, "customer_id": r["id"], "subject": subject, "delta": delta
            }, ensure_ascii=False) + "\n")

    return jsonify({"message":"Kampaň odoslaná.", "recipients": len(recipients), "sent": sent, "awarded_points_to": awarded, "errors": errors})

# =================== štatistiky / reporty ===================
def _orders_agg(date_from: str=None, date_to: str=None):
    tbl = "b2c_objednavky"
    dat = _first_col(tbl, ["datum_objednavky","created_at","created","datum"]) or "id"
    final_expr = _coalesce_expr(tbl, "o", ["finalna_suma_s_dph","finalna_suma","final_total_s_dph","suma_s_dph","total_s_dph"], "finalka")
    pred_expr  = _coalesce_expr(tbl, "o", ["predpokladana_suma_s_dph","suma_s_dph","total_s_dph","total_gross"], "pred")
    cols = [f"o.{dat} AS datum", final_expr, pred_expr]
    q = f"SELECT {', '.join(cols)} FROM {tbl} o"
    params = []
    if date_from or date_to:
        q += " WHERE 1=1"
        if date_from: q += " AND DATE(o." + dat + ") >= %s"; params.append(date_from)
        if date_to:   q += " AND DATE(o." + dat + ") <= %s"; params.append(date_to)
    return db_connector.execute_query(q, tuple(params) if params else None) or []

@kancelaria_b2c_bp.get("/api/kancelaria/b2c/stats/overview")
def stats_overview():
    df = request.args.get("date_from"); dt = request.args.get("date_to")
    ords = _orders_agg(df, dt)
    orders = len(ords)
    final_sum = sum(float(o.get("finalka") or 0.0) for o in ords)
    avg_order = (final_sum / orders) if orders else 0.0

    tbl = "b2c_objednavky"
    fk = _first_col(tbl, ["zakaznik_id","customer_id","user_id"])
    dat= _first_col(tbl, ["datum_objednavky","created_at","created","datum"]) or "id"
    customers_active = 0
    if fk:
        q = f"SELECT COUNT(DISTINCT {fk}) AS c FROM {tbl} WHERE 1=1"
        params = []
        if df: q += f" AND DATE({dat}) >= %s"; params.append(df)
        if dt: q += f" AND DATE({dat}) <= %s"; params.append(dt)
        r = db_connector.execute_query(q, tuple(params) if params else None, fetch="one") or {}
        customers_active = int(r.get("c") or 0)

    rew_tbl = "b2c_uplatnene_odmeny"
    rewards_redeemed = 0
    if _col_exists(rew_tbl,"datum_vytvorenia") or _col_exists(rew_tbl,"created_at"):
        date_col = _first_col(rew_tbl, ["datum_vytvorenia","created_at"])
        q = f"SELECT COUNT(*) c FROM {rew_tbl} WHERE 1=1"
        params=[]
        if df: q += f" AND DATE({date_col}) >= %s"; params.append(df)
        if dt: q += f" AND DATE({date_col}) <= %s"; params.append(dt)
        r = db_connector.execute_query(q, tuple(params) if params else None, fetch="one") or {}
        rewards_redeemed = int(r.get("c") or 0)

    points_manual = 0
    adj_log = os.path.join(DATA_DIR, "b2c_points_adjustments.jsonl")
    if os.path.isfile(adj_log):
        with open(adj_log, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    tsd = rec.get("ts","")[:10]
                    if (not df or tsd >= df) and (not dt or tsd <= dt):
                        points_manual += int(rec.get("delta") or 0)
                except: pass

    bday_points = 0
    data = _load_json(AWARDS_LOG_PATH, {}) or {}
    for ym, bucket in (data or {}).items():
        try:
            y,m = ym.split("-"); d = f"{y}-{m}-01"
            if (not df or d >= df) and (not dt or d <= dt):
                for v in (bucket or {}).values():
                    bday_points += int((v or {}).get("points") or 0)
        except: pass

    return jsonify({
        "orders": orders,
        "final_sum": round(final_sum,2),
        "avg_order": round(avg_order,2),
        "customers_active": customers_active,
        "rewards_redeemed": rewards_redeemed,
        "points_awarded_manual": points_manual,
        "points_awarded_birthday": bday_points
    })

@kancelaria_b2c_bp.get("/api/kancelaria/b2c/stats/top_customers")
def stats_top_customers():
    limit = int(request.args.get("limit") or 20)
    df = request.args.get("date_from"); dt = request.args.get("date_to")
    tbl = "b2c_objednavky"
    fk  = _first_col(tbl, ["zakaznik_id","customer_id","user_id"])
    dat = _first_col(tbl, ["datum_objednavky","created_at","created","datum"]) or "id"
    final_expr = _coalesce_expr(tbl,"o",["finalna_suma_s_dph","finalna_suma","final_total_s_dph","suma_s_dph","total_s_dph"],"finalka")
    if not fk:
        return jsonify([])
    q = f"""
      SELECT z.id AS customer_id, z.zakaznik_id, z.nazov_firmy, z.email,
             SUM({final_expr.split(' AS ')[0]}) AS suma
      FROM b2c_objednavky o
      JOIN b2b_zakaznici z ON (
        { ' OR '.join([p for p in [
            "o.zakaznik_id=z.zakaznik_id" if _col_exists(tbl,"zakaznik_id") and not _is_numeric(tbl,"zakaznik_id") else None,
            "o.zakaznik_id=z.id"          if _col_exists(tbl,"zakaznik_id") and _is_numeric(tbl,"zakaznik_id") else None,
            "o.customer_id=z.id"          if _col_exists(tbl,"customer_id") else None,
            "o.user_id=z.id"              if _col_exists(tbl,"user_id") else None
        ] if p]) }
      )
      WHERE z.typ='B2C'
    """
    params=[]
    if df: q += f" AND DATE(o.{dat}) >= %s"; params.append(df)
    if dt: q += f" AND DATE(o.{dat}) <= %s"; params.append(dt)
    q += " GROUP BY z.id, z.zakaznik_id, z.nazov_firmy, z.email ORDER BY suma DESC LIMIT %s"
    params.append(limit)
    return jsonify(db_connector.execute_query(q, tuple(params), fetch='all') or [])

@kancelaria_b2c_bp.get("/api/kancelaria/b2c/stats/rewards_usage")
def stats_rewards_usage():
    df = request.args.get("date_from"); dt = request.args.get("date_to")
    tbl="b2c_uplatnene_odmeny"
    if not _col_exists(tbl,"nazov_odmeny"): return jsonify([])
    date_col = _first_col(tbl, ["datum_vytvorenia","created_at"])
    q = f"SELECT nazov_odmeny, COUNT(*) cnt, SUM(COALESCE(pouzite_body,0)) points FROM {tbl} WHERE 1=1"
    params=[]
    if date_col:
        if df: q += f" AND DATE({date_col}) >= %s"; params.append(df)
        if dt: q += f" AND DATE({date_col}) <= %s"; params.append(dt)
    q += " GROUP BY nazov_odmeny ORDER BY cnt DESC"
    return jsonify(db_connector.execute_query(q, tuple(params) if params else None) or [])

# =================== gift codes (hmotné odmeny) ===================
@kancelaria_b2c_bp.get("/api/kancelaria/b2c/giftcodes/list")
def giftcodes_list():
    """Zoznam gift kódov (bez bodov) – každý má svoju hmotnú odmenu."""
    return jsonify(_read_json_or(GIFTCODES_PATH, {"codes": []}))

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/giftcodes/upsert")
def giftcodes_upsert():
    d = request.get_json(silent=True) or request.form.to_dict(flat=True) or {}
    code = (d.get("code") or "").strip().upper()
    if not code:
        return jsonify({"error": "Chýba code."}), 400
    gift_item = d.get("gift_item") or {}
    label = (gift_item.get("label") or d.get("reward_label") or d.get("label") or "Odmena").strip()
    try:
        qty = float(gift_item.get("qty") or d.get("qty") or 1)
    except Exception:
        qty = 1.0

    store = _read_json_or(GIFTCODES_PATH, {"codes": []})
    codes = store.get("codes") or []
    payload = {"code": code, "gift_item": {"label": label, "qty": qty}}

    found = None
    for c in codes:
        if str(c.get("code","")).upper() == code:
            found = c; break
    if found: found.update(payload)
    else: codes.append(payload)
    store["codes"] = codes
    _write_json(GIFTCODES_PATH, store)
    return jsonify({"ok": True, "codes": codes})

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/giftcodes/delete")
def giftcodes_delete():
    d = request.get_json(silent=True) or request.form.to_dict(flat=True) or {}
    code = (d.get("code") or "").strip().upper()
    if not code:
        return jsonify({"error": "Chýba code."}), 400
    store = _read_json_or(GIFTCODES_PATH, {"codes": []})
    before = len(store.get("codes") or [])
    store["codes"] = [c for c in (store.get("codes") or []) if str(c.get("code","")).upper() != code]
    _write_json(GIFTCODES_PATH, store)
    return jsonify({"ok": True, "removed": before - len(store.get("codes") or [])})

@kancelaria_b2c_bp.get("/api/kancelaria/b2c/giftcodes/usage")
def giftcodes_usage():
    """?user_id= alebo ?email= – vráti zoznam gift kódov použitých daným používateľom."""
    user_id = (request.args.get("user_id") or "").strip()
    email   = (request.args.get("email") or "").strip().lower()
    if not user_id and not email:
        return jsonify({"error": "Uveďte user_id alebo email."}), 400
    key = user_id or email
    usage = _read_json_or(GIFTCODE_USAGE_PATH, {})
    out = []
    for code, per_code in (usage or {}).items():
        if str(key) in (per_code or {}):
            rec = (per_code or {}).get(str(key)) or {}
            out.append({"code": code, "used_at": rec.get("ts"), "order_no": rec.get("order_no")})
    return jsonify({"user_key": key, "used_codes": out})

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/giftcodes/send")
def giftcodes_send():
    """
    Pošle darčekový kód vybraným zákazníkom (bez bodov).
    Body:
      {
        "code": "DARCEK-XYZ",
        "emails": ["user1@example.com","user2@example.com"],
        "subject": "Vaša odmena",
        "message": "Ahoj, tu je tvoj darčekový kód: {{code}}"
      }
    """
    d = request.get_json(silent=True) or {}
    code = (d.get("code") or "").strip().upper()
    emails = [e for e in (d.get("emails") or []) if e]
    subject = (d.get("subject") or "Darčekový kód").strip()
    message = (d.get("message") or "Váš kód: {{code}}").replace("{{code}}", code)

    if not code or not emails:
        return jsonify({"error": "Chýba code alebo emails."}), 400

    sent, failed = [], []
    for to in emails:
        try:
            if hasattr(notify, "_send_email"):
                notify._send_email(to, subject, notify._wrap_html(subject, f"<p>{message}</p>"))
            elif hasattr(notify, "send_points_awarded_email"):
                notify.send_points_awarded_email(to, 0, None, message)
            sent.append(to)
        except Exception:
            failed.append(to)

    if not sent and not hasattr(notify, "_send_email"):
        out_dir = os.path.join(DATA_DIR, "outbox"); os.makedirs(out_dir, exist_ok=True)
        import uuid
        for to in emails:
            fn = os.path.join(out_dir, f"giftcode_{code}_{uuid.uuid4().hex}.eml")
            with open(fn, "w", encoding="utf-8") as f:
                f.write(f"To: {to}\nSubject: {subject}\nContent-Type: text/plain; charset=utf-8\n\n{message}")
            sent.append(to)

    return jsonify({"ok": True, "sent": sent, "failed": failed})

# =================== DELIVERY WINDOWS ===================
@kancelaria_b2c_bp.get("/api/kancelaria/b2c/delivery_windows/get")
def delivery_windows_get():
    return jsonify({"windows": _read_json_or(DW_PATH, [])})

@kancelaria_b2c_bp.post("/api/kancelaria/b2c/delivery_windows/set")
def delivery_windows_set():
    d = request.get_json(silent=True) or {}
    windows = d.get("windows")
    if not isinstance(windows, list):
        return jsonify({"error":"Očakávam pole 'windows'."}), 400
    cleaned = []
    for w in windows:
        if not isinstance(w, dict): continue
        date  = (w.get("date") or "").strip()
        label = (w.get("label") or "").strip()
        idv   = (w.get("id") or f"{date}_{label}".replace(":","").replace("–","-").lower())
        if date and label:
            cleaned.append({"id": idv, "date": date, "label": label})
    _write_json(DW_PATH, cleaned)
    return jsonify({"ok": True, "windows": cleaned})

# =================== REPORT odmien (z *.meta.json) ===================
@kancelaria_b2c_bp.get("/api/kancelaria/b2c/reports/rewards")
def rewards_report():
    """Sčíta darčeky z *.meta.json podľa názvu odmeny (label)."""
    import csv, io
    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")
    fmt       = (request.args.get("format") or "json").lower()

    def in_range(path):
        if not (date_from or date_to): return True
        try:
            ts = os.path.getmtime(path); d = datetime.fromtimestamp(ts).date()
        except Exception:
            return True
        if date_from:
            y,m,dd = map(int, date_from.split("-"))
            if d < datetime(y,m,dd).date(): return False
        if date_to:
            y,m,dd = map(int, date_to.split("-"))
            if d > datetime(y,m,dd).date(): return False
        return True

    entries, summary = [], {}
    for fn in os.listdir(ORDERS_DIR):
        if not fn.endswith(".meta.json"): continue
        p = os.path.join(ORDERS_DIR, fn)
        if not in_range(p): continue
        meta = _read_json_or(p, {})
        for r in (meta.get("rewards") or []):
            label = r.get("label") or "Odmena"
            typ   = r.get("type") or "reward"
            try: qty = float(r.get("qty") or 1)
            except Exception: qty = 1.0
            entries.append({"order_no": fn[:-10], "type": typ, "label": label, "qty": qty, "points": r.get("points")})
            key = (typ, label); summary[key] = summary.get(key, 0) + qty

    if fmt == "csv":
        out = io.StringIO(); w = csv.writer(out, delimiter=';')
        w.writerow(["order_no","type","label","qty","points"])
        for e in entries: w.writerow([e["order_no"], e["type"], e["label"], e["qty"], e.get("points","")])
        resp = make_response(out.getvalue())
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = "attachment; filename=rewards_report.csv"
        return resp

    summary_list = [{"type": k[0], "label": k[1], "qty": v} for k,v in summary.items()]
    return jsonify({"entries": entries, "summary": summary_list})
@kancelaria_b2c_bp.get("/api/kancelaria/getPendingB2BRegistrations")
def get_pending_b2b_registrations():
    """
    Vráti čakajúce B2B registrácie (robustne – ak status stĺpec nie je, vráti prázdny zoznam).
    """
    tbl = "b2b_zakaznici"
    # skúšaj rôzne stĺpce stavu
    status_col = _first_col(tbl, ["stav_registracie","stav","status"])
    created_col= _first_col(tbl, ["datum_registracie","created_at","created","datum"])
    cols = ["id","nazov_firmy","email","telefon","adresa"]
    if created_col: cols.append(f"{created_col} AS datum_registracie")
    q = f"SELECT {', '.join(cols)} FROM {tbl} WHERE typ='B2B'"
    params = []
    if status_col:
        q += f" AND {status_col} IN (%s,%s,%s)"
        params += ["Na schválenie","Čaká na schválenie","pending"]
    if created_col:
        q += f" ORDER BY {created_col} DESC"
    else:
        q += " ORDER BY id DESC"
    rows = db_connector.execute_query(q, tuple(params) if params else None) or []
    return jsonify(rows)
@kancelaria_b2c_bp.post("/api/kancelaria/b2c/cancel_order")
def cancel_b2c_order():
    """
    Zruší B2C objednávku. Body: { order_id | order_number, reason? }
    Nastaví stav "Zrušená", uloží dôvod do META a pošle e-mail zákazníkovi (ak vieme).
    """
    d = request.get_json(silent=True) or request.form.to_dict(flat=True) or {}
    order_key = d.get("order_id") or d.get("order_number") or d.get("id") or d.get("cislo_objednavky")
    reason = (d.get("reason") or "").strip()

    if not order_key:
        return jsonify({"error":"Chýba order_id/order_number."}), 400

    row = _get_order_row(order_key)
    if not row:
        return jsonify({"error":"Objednávka neexistuje."}), 404

    order_no = row.get("cislo_objednavky") or str(row["id"])
    _add_status("b2c_objednavky", row["id"], "Zrušená")
    _write_order_meta(order_no, {"cancel_reason": reason, "cancelled_at": datetime.utcnow().isoformat()+"Z"})

    # pokus o e-mail zákazníkovi
    try:
        mode, fk_val = _resolve_customer_fk(row)
        cust = None
        if fk_val:
            if mode == "by_zakaznik_id" and not _is_numeric("b2c_objednavky", "zakaznik_id"):
                cust = db_connector.execute_query("SELECT email FROM b2b_zakaznici WHERE zakaznik_id=%s", (fk_val,), fetch="one")
            else:
                cust = db_connector.execute_query("SELECT email FROM b2b_zakaznici WHERE id=%s", (int(fk_val),), fetch="one")
        to_mail = (cust or {}).get("email")
        if to_mail and hasattr(notify, "_send_email"):
            subj = f"Objednávka {order_no} – zrušená"
            body = f"<p>Vaša objednávka {order_no} bola zrušená.</p>" + (f"<p>Dôvod: {reason}</p>" if reason else "")
            notify._send_email(to_mail, subj, notify._wrap_html(subj, body))
    except Exception:
        pass

    return jsonify({"message":"Objednávka zrušená.", "order_no": order_no})
from datetime import datetime, date, timedelta

from datetime import datetime, date, timedelta

@kancelaria_b2c_bp.get("/api/kancelaria/getDashboardData")
def get_dashboard_data():
    """
    Dashboard karty + prehľad objednávok na najbližších 7 dní.

    - b2b_orders: prijaté B2B objednávky v období (podľa dátumu prijatia)
    - b2c_orders: prijaté B2C objednávky v období (podľa dátumu prijatia)
    - b2c_registrations: nové B2C registrácie v období
    - b2b_pending_orders: B2B objednávky čakajúce na potvrdenie v období
    - next7Days: počty objednávok (B2B/B2C) po dňoch na najbližšie dni podľa dátumu dodania/ vyzdvihnutia

    GET ?date_from=YYYY-MM-DD&?date_to=YYYY-MM-DD (voliteľné – pre KPI karty)
    """

    def _dt(s):
        if not s: return None
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None

    df = _dt(request.args.get("date_from")) or date.today()
    dt_ = _dt(request.args.get("date_to"))   or df

    # --- helper na spočítanie v intervale podľa detegovaného dátumového stĺpca
    def _count_in_period(table: str, date_candidates: list[str], where_extra: str = "", params_extra: tuple = ()):
        dcol = _first_col(table, date_candidates)
        if not dcol:
            # fallback – ak tabuľka nemá vhodný dátumový stĺpec, vráť celkový count
            r = db_connector.execute_query(f"SELECT COUNT(*) c FROM {table}", fetch="one") or {}
            return int(r.get("c") or 0)
        sql = f"SELECT COUNT(*) c FROM {table} WHERE DATE({dcol}) BETWEEN %s AND %s"
        params = [df.isoformat(), dt_.isoformat()]
        if where_clause := (where_extra or "").strip():
            sql += f" AND ({where_clause})"
            if params_extra:
                params.extend(list(params_extra))
        r = db_connector.execute_query(sql, tuple(params), fetch="one") or {}
        return int(r.get("c") or 0)

    # --- 1) KPI: prijate B2B/B2C
    b2b_orders = _count_in_period("b2b_objednavky", ["datum_objednavky","created_at","created","datum"])
    b2c_orders = _count_in_period("b2c_objednavky", ["datum_objednavky","created_at","created","datum"])

    # --- 2) KPI: nove B2C registracie
    b2c_regs = _count_in_period("b2b_zakaznici", ["datum_registracie","created_at","created","datum"], "LOWER(typ)='b2c'")

    # --- 3) KPI: B2B čaká na potvrdenie
    status_col = _first_col("b2b_objednavky", ["stav","stav_objednavky","status"])
    recv_col   = _first_col("b2b_objednavky", ["datum_objednavky","created_at","created","datum"])
    b2b_pending = 0
    if status_col and recv_col:
        pats = ["prijat", "na potvr", "čaká", "caka"]
        cond = " OR ".join([f"LOWER({status_col}) LIKE %s" for _ in pats])
        params = tuple([f"%{p}%" for p in pats] + [df.isoformat(), dt_.isoformat()])
        sql = (f"SELECT COUNT(*) c FROM b2b_objednavky "
               f"WHERE ({cond}) AND DATE({recv_col}) BETWEEN %s AND %s")
        r = db_connector.execute_query(sql, params, fetch="one") or {}
        b2b_pending = int(r.get("c") or 0)

    # --- 4) Next 7 days podľa dátumu dodania/ vyzdvihnutia
    def _counts_by_day(table: str, delivery_candidates: list[str], start: date, end: date) -> dict:
        dcol = _col = _first_col(table, delivery_candidates)
        if not dcol:
            return {}
        sql = (f"SELECT DATE({dcol}) AS d, COUNT(*) AS c "
               f"FROM {table} WHERE DATE({dcol}) BETWEEN %s AND %s GROUP BY DATE({dcol})")
        db_nt = db_connector.execute_query(sql, (start.isoformat(), end.isoformat())) or []
        rows = db_nt
        out = {}
        for r in rows:
            # r môže byť dict alebo tuple – v tvojom db_connector to už mapuje na dicty, ale pre istotu:
            day = r["d"] if isinstance(r, dict) else r[0]
            cnt = int(r["c"] if isinstance(r, dict) else r[1])
            out[str(day)] = cnt
        return out

    dcol_b2c = ["pozadovany_datum_dodania","datum_dodania","delivery_date"]
    dcol_b2b = ["pozadovany_datum_dodania","datum_dodania","delivery_date"]

    start7 = date.today()
    end7   = start7 + timedelta(days=6)

    map_b2c = _counts_by_day("b2c_objednavky", dcol_b2c, start7, end7)
    map_b2b = _counts_by_day("b2b_objednavky", dcol_b2b, start7, end7)

    next7 = []
    for i in range(7):
        d = start7 + i*timedelta(days=1)
        key = d.iso8601() if hasattr(d, "iso8601") else d.isoformat()
        b2c = int(map_b2c.get(key, 0))
        b2b = int(map_b2b.get(key, 0))
        next7.append({
            "date": key,
            "b2c": b2c,
            "b2b": b2b,
            "total": b2c + b2b
        })

    return jsonify({
        "period": {"date_from": df.isoformat(), "date_to": dt_.isoformat()},
        "cards": {
            "b2b_orders":         {"count": b2b_orders,        "label": "B2B prijaté"},
            "b2c_orders":         {"count": b2c_orders,        "label": "B2C prijaté"},
            "b2c_registrations":  {"count": b2c_regs,          "label": "B2C nové registrácie"},
            "b2b_pending_orders": {"count": b2b_pending,       "label": "B2B čaká na potvrdenie"},
        },
        "next7Days": next7,
        # placeholdery pre ostatné sekcie, aby dashboard.js nespadol, kým si nedoplníš vlastné zdroje:
        "activePromotions": [],
        "lowStockRaw": [],
        "lowStockGoods": {},
        "topProducts": [],
        "timeSeriesData": []
    })
