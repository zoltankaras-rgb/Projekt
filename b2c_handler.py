# -*- coding: utf-8 -*-
"""
B2C handler – registrácia, login, cenník, objednávky, vernostné odmeny.

Bez migrácie DB:
- zistenie dostupných stĺpcov a skladanie SQL podľa skutočnej schémy,
- jednotná kolácia pri porovnávaní EAN,
- fallbacky pre stav odmien a pre vloženie objednávky,
- súborový trezor hesiel, ak v tabuľke chýbajú heslo_hash/heslo_salt,
- podpora FK na zákazníka cez b2b_zakaznici.id aj b2b_zakaznici.zakaznik_id,
- outbox HTML potvrdenie objednávky (ak e-mail neodíde),
- ceny/DPH z B2C cenníka (robustne) v submit_b2c_order aj v histórii.

DOPLNENÉ:
- delivery_window: Po–Pia 08:00–12:00 / 12:00–15:00 – prenesené do order_data, META, e-mailu, PDF
- reward_code (gift-only): pridelí darček bez bodov, max. 1×/zákazníka (evidencia v _giftcode_usage.json),
  darček sa zobrazí v order_data.rewards + META + e-mail + PDF
"""

import os
import json
import random
import string
import traceback
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import db_connector
from auth_handler import generate_password_hash, verify_password
import pdf_generator
import notification_handler

# Jednotná kolácia pri porovnávaní textových stĺpcov (EAN, atď.)
COLL = "utf8mb4_0900_ai_ci"


# ---------------------------------------------------------------------
# Password-storage fallback (ak DB nemá heslo_hash/heslo_salt)
# ---------------------------------------------------------------------
def _b2c_passwords_path() -> str:
    base = os.path.dirname(__file__)
    folder = os.path.join(base, "static", "uploads", "b2c")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "b2c_passwords.json")

def _load_password_store() -> dict:
    try:
        with open(_b2c_passwords_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save_password_store(d: dict):
    p = _b2c_passwords_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# ---------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------
def _table_has_columns(table: str, columns: List[str]) -> bool:
    """True, ak tabuľka obsahuje VŠETKY zadané stĺpce."""
    if not columns:
        return True
    sql = """
        SELECT COLUMN_NAME AS col
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name   = %s
          AND COLUMN_NAME IN ({})
    """.format(",".join(["%s"] * len(columns)))
    params = tuple([table] + list(columns))
    rows = db_connector.execute_query(sql, params) or []
    present = {(r.get("col") if isinstance(r, dict) else list(r.values())[0]) for r in rows}
    return all(c in present for c in columns)

def _first_existing_col(table: str, candidates: List[str]) -> Optional[str]:
    """Vráti prvý existujúci stĺpec z kandidátov, alebo None."""
    for c in candidates:
        if _table_has_columns(table, [c]):
            return c
    return None

def _column_data_type(table: str, column: str) -> Optional[str]:
    """Vráti data_type z information_schema (napr. 'int', 'bigint', 'varchar'...)."""
    try:
        row = db_connector.execute_query(
            "SELECT DATA_TYPE AS dt FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name=%s AND column_name=%s",
            (table, column), fetch="one"
        )
        return (row or {}).get("dt")
    except Exception:
        return None

def _is_numeric_col(table: str, column: str) -> bool:
    dt = (_column_data_type(table, column) or "").lower()
    return any(k in dt for k in ("int", "decimal", "float", "double", "numeric"))


# ---------------------------------------------------------------------
# Meta/obrázky pre produkty (doplnkové info)
# ---------------------------------------------------------------------
def _b2c_meta_path() -> str:
    base = os.path.dirname(__file__)
    folder = os.path.join(base, "static", "uploads", "b2c")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "_b2c_meta.json")

def _b2c_meta_load() -> dict:
    try:
        with open(_b2c_meta_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _b2c_img_map_path() -> str:
    base = os.path.dirname(__file__)
    folder = os.path.join(base, "static", "uploads", "b2c")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "_images_map.json")

def _b2c_img_load() -> dict:
    try:
        with open(_b2c_img_map_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------
# Pomocné funkcie pre ceny/DPH a EANy
# ---------------------------------------------------------------------
def _to_float(v, default=0.0):
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", ".")
        return float(s) if s != "" else default
    except Exception:
        return default

def _norm_ean(e):
    return str(e or "").strip()

def _variants_ean(e):
    """Varianty EAN (napr. doplnenie na 13 číslic)."""
    e = _norm_ean(e)
    vs = [e]
    if e.isdigit() and len(e) < 13:
        vs.append(e.zfill(13))
    return list(dict.fromkeys(vs))  # unikátne poradie

def _is_true_flag(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "t", "y", "yes", "áno", "ano")

def _fetch_b2c_prices(eans: List[str]) -> Dict[str, Dict[str, float]]:
    """
    Map {ean: {'dph': float, 'cena': float, 'je_v_akcii': bool, 'akciova_cena_bez_dph': float}}.
    Robustné dohľadanie: COLLATE, fallback BINARY a zero-pad (napr. '21101' -> '000000021101').
    """
    base: List[str] = []
    for e in eans or []:
        s = str(e or "").strip()
        if not s:
            continue
        base.append(s)
        if s.isdigit() and len(s) < 13:
            base.append(s.zfill(13))
    if not base:
        return {}
    base = list(dict.fromkeys(base))

    out: Dict[str, Dict[str, float]] = {}

    def _upsert(rows):
        for r in rows or []:
            e = str(r.get("ean") or r.get("ean_produktu") or "").strip()
            if not e:
                continue
            out[e] = {
                "dph": float(r.get("dph") or 0.0),
                "cena": float(r.get("cena_bez_dph") or 0.0),
                "je_v_akcii": str(r.get("je_v_akcii") or "").lower() in ("1","true","t","yes","y","áno","ano"),
                "akciova_cena_bez_dph": float(r.get("akciova_cena_bez_dph") or 0.0),
            }

    # 1) JOIN s jednotnou koláciou
    ph = ",".join(["%s"] * len(base))
    q1 = f"""
      SELECT p.ean, p.dph, c.cena_bez_dph, c.je_v_akcii, c.akciova_cena_bez_dph
      FROM produkty p
      JOIN b2c_cennik_polozky c
        ON p.ean COLLATE {COLL} = c.ean_produktu COLLATE {COLL}
      WHERE p.ean COLLATE {COLL} IN ({ph})
    """
    _upsert(db_connector.execute_query(q1, tuple(base)) or [])

    missing = [e for e in base if e not in out]

    # 2) fallback – BINARY porovnávanie
    if missing:
        ph2 = ",".join(["%s"] * len(missing))
        q2 = f"""
          SELECT p.ean, p.dph, c.cena_bez_dph, c.je_v_akcii, c.akciova_cena_bez_dph
          FROM produkty p
          JOIN b2c_cennik_polozky c
            ON BINARY p.ean = BINARY c.ean_produktu
          WHERE BINARY p.ean IN ({ph2})
        """
        _upsert(db_connector.execute_query(q2, tuple(missing)) or [])
        missing = [e for e in missing if e not in out]

    # 3) posledný fallback – načítaj oddelene a spoj v Pythone
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


# ---------------------------------------------------------------------
# Outbox helper (HTML potvrdenie)
# ---------------------------------------------------------------------
def _outbox_write(filename: str, html: str) -> str:
    base_dir = os.path.join(os.path.dirname(__file__), "static", "uploads", "outbox")
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return f"/static/uploads/outbox/{filename}"

def _get_customer_ids(user_id: int) -> Optional[Dict[str, Any]]:
    """Načíta identifikátory zákazníka (id aj zakaznik_id)."""
    return db_connector.execute_query(
        "SELECT id, zakaznik_id, nazov_firmy, email, adresa, adresa_dorucenia "
        "FROM b2b_zakaznici WHERE id = %s", (user_id,), fetch="one"
    )

# ---------------------------------------------------------------------
# Delivery window formatter (for email/PDF)
# ---------------------------------------------------------------------
def _format_delivery_window(dw_id_or_label: str, delivery_date: str | None = None) -> str:
    """
    Ak príde ID (napr. '2025-11-12_0800-1200'), zobraz '12.11.2025 • 08:00–12:00'.
    Ak príde slovný label (napr. 'workdays_12_15' alebo 'Po–Pia 12:00–15:00'), zobraz ľudskú verziu.
    """
    raw = (dw_id_or_label or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if "workdays_08_12" in low:
        return "Po–Pia 08:00–12:00"
    if "workdays_12_15" in low:
        return "Po–Pia 12:00–15:00"
    # YYYY-MM-DD_label
    if "_" in raw and raw[:10].count("-") == 2:
        try:
            d = raw[:10]
            label = raw[11:].replace("-", "–")
            dn = datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
            return f"{dn} • {label[:2]}:{label[2:4]}–{label[5:7]}:{label[7:9]}" if len(label) >= 9 else f"{dn} • {label}"
        except Exception:
            pass
    return raw


# =================================================================
# ===============  HANDLER PRE B2C PORTÁL  ========================
# =================================================================

# -------------------------------
# Registrácia
# -------------------------------
def process_b2c_registration(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Registrácia B2C:
    - kontrola povinných polí,
    - kontrola duplicity e-mailu (naprieč tabuľkou),
    - hash + salt (DB, alebo súborový trezor),
    - notifikácie.
    """
    try:
        required = ["name", "email", "phone", "address", "password"]
        if not all(data.get(k) for k in required):
            return {"error": "Chyba: Vyplňte všetky povinné polia (meno, e-mail, telefón, adresa, heslo)."}

        name    = (data.get("name") or "").strip()
        email   = (data.get("email") or "").strip().lower()
        phone   = (data.get("phone") or "").strip()
        address = (data.get("address") or "").strip()
        delivery_address = (data.get("delivery_address") or address).strip()
        password = data.get("password") or ""
        gdpr_ok  = bool(data.get("gdpr"))

        # unikátnosť e-mailu
        exists = db_connector.execute_query(
            "SELECT id, typ FROM b2b_zakaznici WHERE email = %s LIMIT 1",
            (email,), fetch="one"
        )
        if exists:
            return {"error": "Tento e-mail je už registrovaný. Prihláste sa, alebo použite iný e-mail."}

        # hash hesla
        salt, hsh = generate_password_hash(password)

        has_pw_cols = _table_has_columns("b2b_zakaznici", ["heslo_hash", "heslo_salt"])
        zakaznik_id = "".join(random.choices(string.digits, k=12))

        if has_pw_cols:
            sql = ("INSERT INTO b2b_zakaznici "
                   "(typ, nazov_firmy, email, telefon, adresa, adresa_dorucenia, "
                   " heslo_hash, heslo_salt, gdpr_suhlas, zakaznik_id) "
                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
            params = ("B2C", name, email, phone, address, delivery_address, hsh, salt, int(gdpr_ok), zakaznik_id)
            db_connector.execute_query(sql, params, fetch="none")
        else:
            sql = ("INSERT INTO b2b_zakaznici "
                   "(typ, nazov_firmy, email, telefon, adresa, adresa_dorucenia, gdpr_suhlas, zakaznik_id) "
                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)")
            params = ("B2C", name, email, phone, address, delivery_address, int(gdpr_ok), zakaznik_id)
            db_connector.execute_query(sql, params, fetch="none")

            store = _load_password_store()
            store[email] = {"salt": salt, "hash": hsh, "updated_at": datetime.utcnow().isoformat()}
            _save_password_store(store)

        try:
            notification_handler.send_b2c_registration_email(email, name)
            notification_handler.send_b2c_new_registration_admin_alert({
                "name": name, "email": email, "phone": phone, "address": address
            })
        except Exception:
            pass

        return {"message": "Registrácia prebehla úspešne. Vitajte! Teraz sa môžete prihlásiť."}

    except Exception as e:
        msg = str(e)
        if "1062" in msg or "Duplicate entry" in msg:
            return {"error": "Tento e-mail je už registrovaný. Prihláste sa, alebo použite iný e-mail."}
        return {"error": f"Nastala interná chyba servera: {e}"}  # nech sa zobrazí konkrétna príčina


# -------------------------------
# Login
# -------------------------------
def process_b2c_login(data: Dict[str, Any]) -> Dict[str, Any]:
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return {"error": "Musíte zadať e-mail aj heslo."}

    has_pw_cols = _table_has_columns("b2b_zakaznici", ["heslo_hash", "heslo_salt"])

    if has_pw_cols:
        q = ("SELECT id, nazov_firmy, email, typ, vernostne_body, heslo_hash, heslo_salt "
             "FROM b2b_zakaznici WHERE email = %s AND typ = 'B2C'")
        user = db_connector.execute_query(q, (email,), fetch="one")
        if not user or not verify_password(password, user["heslo_salt"], user["heslo_hash"]):
            return {"error": "Nesprávny e-mail alebo heslo."}
    else:
        base_q = ("SELECT id, nazov_firmy, email, typ, vernostne_body "
                  "FROM b2b_zakaznici WHERE email = %s AND typ = 'B2C'")
        user = db_connector.execute_query(base_q, (email,), fetch="one")
        if not user:
            return {"error": "Nesprávny e-mail alebo heslo."}
        store = _load_password_store()
        cred = store.get(email)
        if cred and verify_password(password, cred["salt"], cred["hash"]):
            pass
        else:
            if _table_has_columns("b2b_zakaznici", ["heslo"]):
                row = db_connector.execute_query(
                    "SELECT heslo FROM b2b_zakaznici WHERE email = %s AND typ = 'B2C'",
                    (email,), fetch="one"
                )
                if not row or (row["heslo"] or "") != password:
                    return {"error": "Nesprávny e-mail alebo heslo."}
            else:
                return {"error": "Nesprávny e-mail alebo heslo."}

    return {
        "message": "Prihlásenie úspešné.",
        "user": {
            "id": user["id"],
            "name": user.get("nazov_firmy"),
            "email": user.get("email"),
            "typ": user.get("typ", "B2C"),
            "points": user.get("vernostne_body", 0) or 0,
        }
    }


# -------------------------------
# Verejný cenník (pre výpis pred loginom)
# -------------------------------
def build_public_payload(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def to_float(v, default=0.0):
        try:
            if v is None:
                return default
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip().replace(",", ".")
            return float(s) if s != "" else default
        except Exception:
            return default

    products_by_cat: Dict[str, List[Dict[str, Any]]] = {}
    akcia_items: List[Dict[str, Any]] = []

    for r in rows:
        ean   = str(r.get("ean") or "").strip()
        name  = r.get("nazov_vyrobku") or ""
        cat   = r.get("predajna_kategoria") or "Nezaradené"
        popis = r.get("popis") or ""
        mj    = r.get("mj") or "ks"
        dph   = to_float(r.get("dph"), 0.0)

        base_price = to_float(r.get("cena_bez_dph"))
        sale_price = to_float(r.get("akciova_cena_bez_dph"))
        is_sale_flag = str(r.get("je_v_akcii", 0)).lower() in ("1", "true", "t", "yes", "y")

        use_sale = is_sale_flag and sale_price > 0
        effective = sale_price if use_sale else base_price
        cena_s_dph = round(effective * (1.0 + dph / 100.0), 4)

        item = {
            "ean": ean,
            "nazov_vyrobku": name,
            "popis": popis,
            "mj": mj,
            "dph": dph,
            "cena_bez_dph": round(effective, 4),
            "cena_s_dph": cena_s_dph,
            "obrazok_url": r.get("obrazok_url") or "",
            "je_v_akcii": 1 if use_sale else 0,
        }

        products_by_cat.setdefault(cat, []).append(item)
        if use_sale:
            akcia_items.append(item.copy())

    for cat, lst in products_by_cat.items():
        lst.sort(key=lambda x: x["nazov_vyrobku"].lower())

    if akcia_items:
        akcia_items.sort(key=lambda x: x["nazov_vyrobku"].lower())
        products_by_cat["AKCIA TÝŽĎŇA"] = akcia_items

    return {"products": products_by_cat}

def get_public_pricelist() -> Dict[str, Any]:
    query = f"""
        SELECT 
            p.ean, p.nazov_vyrobku, p.predajna_kategoria, p.mj, p.dph,
            c.cena_bez_dph, c.je_v_akcii, c.akciova_cena_bez_dph
        FROM produkty p
        JOIN b2c_cennik_polozky c
          ON p.ean COLLATE {COLL} = c.ean_produktu COLLATE {COLL}
        ORDER BY p.predajna_kategoria, p.nazov_vyrobku
    """
    rows = db_connector.execute_query(query) or []

    meta = _b2c_meta_load()
    img_map = _b2c_img_load()
    for r in rows:
        ean = r["ean"]
        m = meta.get(ean, {})
        r["popis"] = m.get("popis", "")
        r["obrazok_url"] = m.get("obrazok", "") or img_map.get(ean, "")

    return build_public_payload(rows)


# -------------------------------
# Odmeny – zistenie/označenie (vernostné body)
# -------------------------------
def _find_claimed_reward(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Zistí čakajúcu uplatnenú odmenu PRE TOHTO ZÁKAZNÍKA.
    Ak tabuľka nemá stĺpce stavu, radšej NEVRACIA nič (žiadny "posledný záznam").
    """
    cust = _get_customer_ids(user_id)
    if not cust:
        return None

    table = "b2c_uplatnene_odmeny"
    fk_col = _first_existing_col(table, ["zakaznik_id", "customer_id", "user_id"])
    if not fk_col:
        return None

    has_stav_vyb = _table_has_columns(table, ["stav_vybavenia"])
    has_stav     = _table_has_columns(table, ["stav"])

    # Bez stĺpcov stavu nevieme bezpečne rozhodnúť → nič
    if not (has_stav_vyb or has_stav):
        return None

    # hodnota FK (ber ohľad na typ zakaznik_id)
    if fk_col == "zakaznik_id":
        fk_val = cust.get("zakaznik_id") if not isinstance(cust.get("zakaznik_id"), (int, float)) else int(cust["zakaznik_id"])
    else:
        fk_val = cust["id"]

    for st_col in (["stav_vybavenia"] if has_stav_vyb else []) + (["stav"] if has_stav else []):
        row = db_connector.execute_query(
            f"SELECT id, nazov_odmeny FROM {table} WHERE {fk_col}=%s AND {st_col}=%s ORDER BY id DESC LIMIT 1",
            (fk_val, "Čaká na vybavenie"), fetch="one"
        )
        if row:
            return row
    return None


def _mark_reward_fulfilled(order_id: int, reward_row_id: int):
    """Označí uplatnenú odmenu ako vybavenú s ohľadom na dostupné stĺpce."""
    table = "b2c_uplatnene_odmeny"
    has_stav_vyb = _table_has_columns(table, ["stav_vybavenia"])
    has_stav     = _table_has_columns(table, ["stav"])
    has_order_id = _table_has_columns(table, ["objednavka_id"])

    if has_stav_vyb and has_order_id:
        db_connector.execute_query(
            f"UPDATE {table} SET stav_vybavenia = 'Vybavené', objednavka_id = %s WHERE id = %s",
            (order_id, reward_row_id), fetch="none"
        )
    elif has_stav and has_order_id:
        db_connector.execute_query(
            f"UPDATE {table} SET stav = 'Vybavené', objednavka_id = %s WHERE id = %s",
            (order_id, reward_row_id), fetch="none"
        )
    elif has_stav_vyb:
        db_connector.execute_query(
            f"UPDATE {table} SET stav_vybavenia = 'Vybavené' WHERE id = %s",
            (reward_row_id,), fetch="none"
        )
    elif has_stav:
        db_connector.execute_query(
            f"UPDATE {table} SET stav = 'Vybavené' WHERE id = %s",
            (reward_row_id,), fetch="none"
        )
    elif has_order_id:
        db_connector.execute_query(
            f"UPDATE {table} SET objednavka_id = %s WHERE id = %s",
            (order_id, reward_row_id), fetch="none"
        )


# -------------------------------
# Gift kódy – súborová evidencia (bez DB)
# -------------------------------
def _giftcodes_path() -> str:
    base = os.path.dirname(__file__)
    folder = os.path.join(base, "static", "uploads", "b2c")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "_giftcodes.json")

def _giftcode_usage_path() -> str:
    base = os.path.dirname(__file__)
    folder = os.path.join(base, "static", "uploads", "b2c")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "_giftcode_usage.json")

def _giftcodes_load() -> dict:
    try:
        with open(_giftcodes_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {"codes": []}
    except Exception:
        return {"codes": []}

def _giftcode_find(code: str) -> Optional[dict]:
    if not code:
        return None
    up = code.strip().upper()
    store = _giftcodes_load()
    for c in (store.get("codes") or []):
        if str(c.get("code","")).upper() == up:
            return c
    return None

def _giftcode_usage_load() -> dict:
    try:
        with open(_giftcode_usage_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _giftcode_used(code: str, user_key: str) -> bool:
    usage = _giftcode_usage_load()
    return str(user_key) in (usage.get(code) or {})

def _giftcode_mark_used(code: str, user_key: str, order_no: str):
    usage = _giftcode_usage_load()
    per_code = usage.get(code) or {}
    per_code[str(user_key)] = {"ts": datetime.utcnow().isoformat()+"Z", "order_no": order_no}
    usage[code] = per_code
    tmp = _giftcode_usage_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(usage, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _giftcode_usage_path())


# -------------------------------
# Objednávka
# -------------------------------
def submit_b2c_order(user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    conn = None
    cursor = None
    try:
        items = data.get("items")
        delivery_date = data.get("deliveryDate")
        note = data.get("note")

        if not all([user_id, items, delivery_date]):
            return {"error": "Chýbajú povinné údaje pre spracovanie objednávky."}

        # priprav „raw_items“ a EANy
        raw_items: List[Dict[str, Any]] = []
        eans: List[str] = []
        for it in (items or []):
            if not it:
                continue
            e = _norm_ean(it.get("ean"))
            q = _to_float(it.get("quantity"), 0.0)
            if e and q > 0:
                raw_items.append({
                    "ean": e,
                    "name": it.get("name") or it.get("nazov") or it.get("nazov_vyrobku"),
                    "quantity": q,
                    "unit": it.get("unit") or it.get("mj"),
                    "item_note": it.get("item_note") or it.get("poznamka_k_polozke") or ""
                })
                eans.append(e)
        if not raw_items:
            return {"error": "Objednávka neobsahuje žiadne položky."}

        # ROBUSTNÉ CENY Z CENNÍKA
        prices = _fetch_b2c_prices(eans)

        # výpočet súm + obohatenie položiek (aj PDF-kompat polia)
        total_net = 0.0
        total_gross = 0.0
        items_with_details: List[Dict[str, Any]] = []

        for it in raw_items:
            ean = it["ean"]
            q   = it["quantity"]
            p   = prices.get(ean) or (prices.get(ean.zfill(13)) if ean.isdigit() else None)

            dph_pct = _to_float((p or {}).get("dph"))
            if p and p.get("je_v_akcii") and _to_float(p.get("akciova_cena_bez_dph")) > 0:
                net = _to_float(p.get("akciova_cena_bez_dph"))
            else:
                net = _to_float((p or {}).get("cena"))

            gross = net * (1.0 + dph_pct/100.0)

            total_net   += net   * q
            total_gross += gross * q

            # PDF-kompat klúče + naše klúče
            items_with_details.append({
                # naše
                "ean": ean,
                "name": it.get("name"),
                "quantity": q,
                "unit": it.get("unit"),
                "item_note": it.get("item_note"),
                "price_bez_dph": net,
                "price_s_dph":   gross,
                "dph_percent":   dph_pct,
                # PDF-kompat (slovenské názvy, riadkové súčty)
                "nazov": it.get("name"),
                "mnozstvo": q,
                "mj": it.get("unit"),
                "cena_bez_dph": net,
                "cena_s_dph": gross,
                "dph": dph_pct,
                "line_total_bez_dph": round(net*q, 2),
                "line_total_s_dph": round(gross*q, 2),
            })

        total_vat = total_gross - total_net
        order_number = f"B2C-{user_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Gift-code (bez bodov, 1×)
        rewards = []
        reward_code = (data.get("reward_code") or data.get("promo_code") or "").strip().upper()
        gift_applied = False
        if reward_code:
            rd = _giftcode_find(reward_code)
            if rd:
                # user_key na evidenciu – preferuj numeric id
                user_key = str(user_id)
                if not _giftcode_used(reward_code, user_key):
                    gift = rd.get("gift_item") or {}
                    label = gift.get("label") or rd.get("reward_label") or "Odmena"
                    try:
                        qty = float(gift.get("qty") or rd.get("qty") or 1)
                    except Exception:
                        qty = 1.0
                    rewards.append({"type": "giftcode", "label": label, "qty": qty, "code": reward_code})
                    gift_applied = True
                # ak už použitý, nič – upozornenie vyrieši public API na svojej vrstve

        # DB zápis – dynamicky podľa schémy
        conn = db_connector.get_connection()
        cursor = conn.cursor(dictionary=True)
        customer = _get_customer_ids(user_id)
        if not customer:
            return {"error": "Zákazník pre objednávku nebol nájdený."}

        tbl = "b2c_objednavky"
        cols, vals = [], []
        col_customer_id   = _first_existing_col(tbl, ["zakaznik_id","customer_id","user_id"])
        col_order_number  = _first_existing_col(tbl, ["cislo_objednavky","objednavka_cislo","order_number"])
        col_delivery_date = _first_existing_col(tbl, ["pozadovany_datum_dodania","datum_dodania","delivery_date"])
        col_note          = _first_existing_col(tbl, ["poznamka","note"])
        col_total_net     = _first_existing_col(tbl, ["predpokladana_suma_bez_dph","suma_bez_dph","total_bez_dph","total_net"])
        col_total_vat     = _first_existing_col(tbl, ["predpokladana_dph","dph","total_dph","vat_amount"])
        col_total_gross   = _first_existing_col(tbl, ["predpokladana_suma_s_dph","suma_s_dph","total_s_dph","total_gross"])
        col_items         = _first_existing_col(tbl, ["polozky","polozky_json","items"])
        col_reward_note   = _first_existing_col(tbl, ["uplatnena_odmena_poznamka","reward_note"])

        if col_customer_id:
            if col_customer_id == "zakaznik_id" and not _is_numeric_col(tbl, col_customer_id):
                fk_val = customer.get("zakaznik_id")
                if not fk_val:
                    return {"error": "Váš účet nemá priradené zákaznícke číslo (zakaznik_id). Kontaktujte podporu."}
                cols.append(col_customer_id); vals.append(fk_val)
            else:
                cols.append(col_customer_id); vals.append(customer["id"])

        if col_order_number:  cols.append(col_order_number);  vals.append(order_number)
        if col_delivery_date: cols.append(col_delivery_date); vals.append(delivery_date)
        if col_note:          cols.append(col_note);          vals.append(note or "")
        if col_total_net:     cols.append(col_total_net);     vals.append(round(total_net, 2))
        if col_total_vat:     cols.append(col_total_vat);     vals.append(round(total_vat, 2))
        if col_total_gross:   cols.append(col_total_gross);   vals.append(round(total_gross, 2))
        if col_items:         cols.append(col_items);         vals.append(json.dumps(items_with_details, ensure_ascii=False))

        # prípadná bodová odmena (starý mechanizmus)
        reward_note = None
        claimed = _find_claimed_reward(user_id)
        if claimed:
            reward_note = claimed.get("nazov_odmeny")
            if col_reward_note and reward_note:
                cols.append(col_reward_note); vals.append(reward_note)

        placeholders = ",".join(["%s"] * len(vals))
        cursor.execute(f"INSERT INTO {tbl} ({', '.join(cols)}) VALUES ({placeholders})", tuple(vals))
        order_id = cursor.lastrowid
        if claimed and order_id:
            _mark_reward_fulfilled(order_id, claimed["id"])
        conn.commit()

        # PDF/MAIL dáta (pridáme delivery_window a rewards z payloadu/gift kódu)
        order_data_for_docs = {
            "order_number":     order_number,
            "deliveryDate":     delivery_date,
            "note":             note or "",
            "customerName":     customer.get("nazov_firmy"),
            "customerLoginId":  customer.get("zakaznik_id", "N/A"),
            "customerAddress":  customer.get("adresa_dorucenia", customer.get("adresa", "Neuvedená")),
            "customerEmail":    customer.get("email"),
            "items":            items_with_details,
            # súčty – viac aliasov pre kompatibilitu
            "totalNet":         round(total_net, 2),
            "totalVat":         round(total_vat, 2),
            "totalGross":       round(total_gross, 2),
            "total_vat":        round(total_vat, 2),
            "suma_bez_dph":     round(total_net, 2),
            "suma_s_dph":       round(total_gross, 2),
            "dph":              round(total_vat, 2),
            "order_date":       datetime.now().strftime("%d.%m.%Y"),
            "uplatnena_odmena_poznamka": reward_note,
        }

        # prenes doplnky
        dw_payload = (data or {}).get("delivery_window")
        if dw_payload:
            order_data_for_docs["delivery_window"] = dw_payload
            order_data_for_docs["deliveryWindowPretty"] = _format_delivery_window(dw_payload, delivery_date)

        if rewards:
            order_data_for_docs["rewards"] = rewards

        # PDF
        pdf_content, _ = pdf_generator.create_order_files(order_data_for_docs)

        # Outbox s doplnkami (pre istotu)
        extras_html = ""
        if order_data_for_docs.get("deliveryWindowPretty"):
            extras_html += f"<p>Vyzdvihnutie/doručenie: <b>{order_data_for_docs['deliveryWindowPretty']}</b></p>"
        elif order_data_for_docs.get("delivery_window"):
            extras_html += f"<p>Vyzdvihnutie/doručenie: <b>{order_data_for_docs['delivery_window']}</b></p>"
        if order_data_for_docs.get("rewards"):
            extras_html += "<p><b>Odmeny:</b> " + ", ".join(f"{r.get('label','Odmena')} × {r.get('qty',1)}" for r in order_data_for_docs["rewards"]) + "</p>"

        confirm_html = f"""
          <h3>Objednávka {order_data_for_docs['order_number']}</h3>
          <p>Požadovaný dátum vyzdvihnutia: <b>{order_data_for_docs['deliveryDate']}</b></p>
          {extras_html}
          <p>Suma s DPH: <b>{order_data_for_docs['totalGross']:.2f} €</b></p>
          <p>Ďakujeme za objednávku.</p>
        """
        _ = _outbox_write(f"order_confirmation_{order_data_for_docs['order_number']}.html", confirm_html)

        # META + evidencia použitia gift-kódu
        try:
            meta = {}
            if order_data_for_docs.get("delivery_window"):
                meta["delivery_window"] = order_data_for_docs["delivery_window"]
            if order_data_for_docs.get("rewards"):
                meta["rewards"] = order_data_for_docs["rewards"]
            if meta:
                p = os.path.join(os.path.dirname(__file__), "static", "uploads", "orders", f"{order_number}.meta.json")
                old = {}
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8") as f:
                        old = json.load(f) or {}
                if meta.get("rewards"):
                    prev = old.get("rewards") or []
                    old["rewards"] = prev + meta["rewards"]
                    meta = {k: v for k, v in meta.items() if k != "rewards"}
                old.update(meta or {})
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(old, f, ensure_ascii=False, indent=2)
            if gift_applied:
                _giftcode_mark_used(reward_code, str(user_id), order_number)
        except Exception:
            pass

        try:
            notification_handler.send_b2c_order_confirmation(
                order_data_for_docs["customerEmail"], order_data_for_docs, pdf_content
            )
        except Exception:
            pass

        return {
            "message": "Vaša objednávka bola úspešne prijatá. Potvrdenie sme Vám zaslali na e-mail.",
            "order_data": order_data_for_docs,
            "pdf_attachment": pdf_content
        }

    except Exception as e:
        if conn: conn.rollback()
        traceback.print_exc()
        return {"error": f"Nastala interná chyba servera: {e}"}
    finally:
        if conn and conn.is_connected():
            if cursor: cursor.close()
            conn.close()



# -------------------------------
# História objednávok
# -------------------------------
def get_order_history(user_id: int) -> dict:
    """História objednávok pre B2C – s položkami a cenami (z B2C cenníka)."""
    if not user_id:
        return {"orders": []}

    tbl = "b2c_objednavky"
    fk_col = _first_existing_col(tbl, ["zakaznik_id", "customer_id", "user_id"])
    if not fk_col:
        return {"orders": []}

    if fk_col == "zakaznik_id":
        cust = db_connector.execute_query("SELECT zakaznik_id FROM b2b_zakaznici WHERE id = %s", (user_id,), fetch="one")
        if not cust or not cust.get("zakaznik_id"):
            return {"orders": []}
        fk_val = cust["zakaznik_id"]
        if _is_numeric_col(tbl, fk_col):
            fk_val = user_id
    else:
        fk_val = user_id

    no_col    = _first_existing_col(tbl, ["cislo_objednavky", "objednavka_cislo", "order_number"])
    del_col   = _first_existing_col(tbl, ["pozadovany_datum_dodania", "datum_dodania", "delivery_date"])
    dat_col   = _first_existing_col(tbl, ["datum_objednavky", "created_at", "created", "datum"])
    fin_col   = _first_existing_col(tbl, ["finalna_suma_s_dph", "finalna_suma", "final_total_s_dph"])
    pred_col  = _first_existing_col(tbl, ["predpokladana_suma_s_dph", "suma_s_dph", "total_s_dph", "total_gross"])
    items_col = _first_existing_col(tbl, ["polozky", "polozky_json", "items"])

    cols = ["id"]
    if no_col:   cols.append(f"{no_col} AS cislo_objednavky")
    if del_col:  cols.append(f"{del_col} AS pozadovany_datum_dodania")
    if dat_col:  cols.append(f"{dat_col} AS datum_objednavky")
    if fin_col:  cols.append(f"{fin_col} AS finalna_suma_s_dph")
    if pred_col: cols.append(f"{pred_col} AS predpokladana_suma_s_dph")
    if items_col:cols.append(f"{items_col} AS polozky")

    order_by = dat_col or "id"
    sql = f"SELECT {', '.join(cols)} FROM {tbl} WHERE {fk_col} = %s ORDER BY {order_by} DESC"
    rows = db_connector.execute_query(sql, (fk_val,)) or []

    # fallback cesta k JSON objednávkam
    orders_dir = os.path.join(os.path.dirname(__file__), "static", "uploads", "orders")

    for r in rows:
        # načítaj položky (DB alebo JSON súbor)
        items = []
        raw = r.get("polozky")
        if isinstance(raw, str) and raw.strip():
            try:
                items = json.loads(raw)
            except Exception:
                items = []
        elif isinstance(raw, (list, dict)):
            items = raw if isinstance(raw, list) else [raw]

        if not items:
            order_no = r.get("cislo_objednavky") or r.get("id")
            safe = "".join(ch for ch in str(order_no) if ch.isalnum() or ch in ("-","_"))
            json_path = os.path.join(orders_dir, f"{safe}.json")
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    od = json.load(f) or {}
                    js = od.get("items") or []
                    if isinstance(js, dict): js = [js]
                    if isinstance(js, list):
                        items = js
            except Exception:
                items = []

        # dotiahni ceny z cenníka – robustne
        eans = [it.get("ean") for it in items if it.get("ean")]
        prices = _fetch_b2c_prices(eans)

        total_net = 0.0
        total_gross = 0.0
        enriched = []

        for it in items:
            ean = _norm_ean(it.get("ean"))
            qty = _to_float(it.get("quantity") or it.get("mnozstvo"))
            if qty <= 0:
                qty = 0.0

            pr = prices.get(ean) or (prices.get(ean.zfill(13)) if ean.isdigit() else None)

            dph_pct = _to_float((pr or {}).get("dph"))
            if pr and pr.get("je_v_akcii") and _to_float(pr.get("akciova_cena_bez_dph")) > 0:
                net = _to_float(pr.get("akciova_cena_bez_dph"))
            else:
                net = _to_float((pr or {}).get("cena"))

            gross = net * (1.0 + dph_pct/100.0)

            total_net   += net   * qty
            total_gross += gross * qty

            enriched.append({
                **it,
                "price_bez_dph": net,
                "price_s_dph":   gross,
                "dph_percent":   dph_pct,
            })

        # doplň predbežné sumy, ak chýbajú
        if r.get("predpokladana_suma_s_dph") is None:
            r["predpokladana_suma_bez_dph"] = total_net
            r["predpokladana_dph"]          = total_gross - total_net
            r["predpokladana_suma_s_dph"]   = total_gross

        r["items"]   = enriched
        r["polozky"] = json.dumps(enriched, ensure_ascii=False)

    return {"orders": rows}


# -------------------------------
# Vernostné odmeny (body)
# -------------------------------
def get_available_rewards() -> Dict[str, Any]:
    q = "SELECT id, nazov_odmeny, potrebne_body FROM b2c_vernostne_odmeny WHERE je_aktivna = TRUE ORDER BY potrebne_body ASC"
    return {"rewards": db_connector.execute_query(q) or []}

def claim_reward(user_id: int, reward_id: int) -> Dict[str, Any]:
    if not all([user_id, reward_id]):
        return {"error": "Chýbajú povinné údaje."}

    reward = db_connector.execute_query(
        "SELECT nazov_odmeny, potrebne_body FROM b2c_vernostne_odmeny WHERE id = %s AND je_aktivna = TRUE",
        (reward_id,), fetch="one"
    )
    if not reward:
        return {"error": "Požadovaná odmena neexistuje alebo nie je aktívna."}

    points_needed = reward["potrebne_body"]
    reward_name = reward["nazov_odmeny"]

    conn = db_connector.get_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT vernostne_body FROM b2b_zakaznici WHERE id = %s FOR UPDATE", (user_id,))
        customer = cursor.fetchone()
        if not customer:
            raise Exception("Zákazník nebol nájdený.")

        current_points = customer.get("vernostne_body") or 0
        if current_points < points_needed:
            return {"error": "Nemáte dostatok bodov na uplatnenie tejto odmeny."}

        new_points = current_points - points_needed
        cursor.execute("UPDATE b2b_zakaznici SET vernostne_body = %s WHERE id = %s", (new_points, user_id))

        # dynamický insert do b2c_uplatnene_odmeny (FK môže byť rôzny)
        table = "b2c_uplatnene_odmeny"
        fk_col = _first_existing_col(table, ["zakaznik_id", "customer_id", "user_id"]) or "zakaznik_id"
        cols = [fk_col, "odmena_id", "nazov_odmeny", "pouzite_body"]
        vals = []
        if fk_col == "zakaznik_id" and not _is_numeric_col(table, fk_col):
            cust = _get_customer_ids(user_id)
            if not cust or not cust.get("zakaznik_id"):
                return {"error": "Zákazník nemá zakaznik_id."}
            vals.append(cust["zakaznik_id"])
        else:
            vals.append(user_id)
        vals.extend([reward_id, reward_name, points_needed])

        placeholders = ",".join(["%s"] * len(vals))
        db_connector.execute_query(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals), fetch="none"
        )

        conn.commit()
        return {"message": f"Odmena '{reward_name}' bola úspešne uplatnená! Bude priložená k nasledujúcej objednávke.",
                "new_points": new_points}
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected():
            if cursor:
                cursor.close()
            conn.close()
