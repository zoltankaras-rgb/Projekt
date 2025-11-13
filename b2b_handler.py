import os, hmac, base64, json, time
import hashlib
import secrets
import traceback
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Tuple
from flask import request

import db_connector
import pdf_generator
import notification_handler

# ───────────────── DB chyby ─────────────────
try:
    from mysql.connector import errors as db_errors
except Exception:
    class _E(Exception): ...
    class db_errors:  # type: ignore
        IntegrityError = _E
        ProgrammingError = _E
        DatabaseError = _E

# kam posielame PDF+CSV pre expedíciu
EXPEDITION_EMAIL = os.getenv("B2B_EXPEDITION_EMAIL") or "miksroexpedicia@gmail.com"

# ───────────────── DDL helpery ─────────────────
def _exec_ddl(sql: str) -> None:
    try:
        db_connector.execute_query(sql, fetch="none")
    except Exception:
        pass

def _ensure_system_settings() -> None:
    _exec_ddl("""
    CREATE TABLE IF NOT EXISTS system_settings (
      id INT AUTO_INCREMENT PRIMARY KEY,
      kluc VARCHAR(191) UNIQUE,
      hodnota TEXT,
      updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
    """)

def _ensure_pricelist_tables() -> None:
    _exec_ddl("""
    CREATE TABLE IF NOT EXISTS b2b_cenniky (
      id INT AUTO_INCREMENT PRIMARY KEY,
      nazov_cennika VARCHAR(255) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
    """)
    _exec_ddl("""
    CREATE TABLE IF NOT EXISTS b2b_cennik_polozky (
      id INT AUTO_INCREMENT PRIMARY KEY,
      cennik_id INT NOT NULL,
      ean_produktu VARCHAR(64) NOT NULL,
      nazov_vyrobku VARCHAR(255),
      cena DECIMAL(10,2) NOT NULL DEFAULT 0,
      UNIQUE KEY uq_pl (cennik_id, ean_produktu),
      CONSTRAINT fk_pl_cennik FOREIGN KEY (cennik_id) REFERENCES b2b_cenniky(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
    """)

def _ensure_mapping_table() -> None:
    _exec_ddl("""
    CREATE TABLE IF NOT EXISTS b2b_zakaznik_cennik (
      zakaznik_id VARCHAR(64) NOT NULL,
      cennik_id INT NOT NULL,
      PRIMARY KEY (zakaznik_id, cennik_id),
      KEY idx_cennik (cennik_id),
      CONSTRAINT fk_map_cennik FOREIGN KEY (cennik_id) REFERENCES b2b_cenniky(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
    """)

def _ensure_comm_table() -> None:
    _exec_ddl("""
    CREATE TABLE IF NOT EXISTS b2b_messages (
      id INT AUTO_INCREMENT PRIMARY KEY,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      customer_id INT NULL,
      zakaznik_login VARCHAR(64),
      customer_name VARCHAR(255),
      customer_email VARCHAR(255),
      subject VARCHAR(255),
      body TEXT,
      direction ENUM('in','out') NOT NULL DEFAULT 'in',
      status ENUM('new','read','closed') NOT NULL DEFAULT 'new',
      attachment_path VARCHAR(500),
      attachment_filename VARCHAR(255),
      attachment_mime VARCHAR(120),
      attachment_size INT,
      parent_id INT NULL,
      INDEX idx_status (status),
      INDEX idx_customer (customer_id),
      INDEX idx_login (zakaznik_login),
      INDEX idx_parent (parent_id),
      FOREIGN KEY (customer_id) REFERENCES b2b_zakaznici(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_slovak_ci
    """)
def _existing_columns(table_name: str) -> set[str]:
    try:
        rows = db_connector.execute_query(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            (table_name,),
            fetch="all",
        ) or []
        return {r.get("COLUMN_NAME") for r in rows}
    except Exception:
        traceback.print_exc()
        return set()

# ───────────────── Anti-bot (voliteľné) ─────────────────
SECRET = (os.getenv("SECRET_KEY") or "dev-secret").encode()

def _ua_hash(ua: str) -> str:
    return hashlib.sha256((ua or "").encode("utf-8")).hexdigest()[:16]

def issue_antibot_token(user_agent: str | None = None) -> Dict[str, Any]:
    ua = user_agent or request.headers.get("User-Agent", "")
    iat = int(time.time() * 1000)
    payload = {"iat": iat, "ua": _ua_hash(ua), "rnd": secrets.token_hex(8)}
    payload_str = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(SECRET, payload_str.encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(f"{payload_str}.{sig}".encode()).decode()
    return {"token": token, "min_delay_ms": 800, "expires_in_ms": 20 * 60 * 1000}

def _verify_antibot_token_if_present(data: dict) -> bool:
    token = (data or {}).get("ab_token")
    if not token:
        return True
    try:
        raw = base64.urlsafe_b64decode((token or "").encode()).decode()
        payload_str, sig = raw.rsplit(".", 1)
        exp = hmac.new(SECRET, payload_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(exp, sig):
            return False
        p = json.loads(payload_str)
        if p.get("ua") != _ua_hash(request.headers.get("User-Agent", "")):
            return False
        iat = int(p.get("iat", 0))
        now = int(time.time() * 1000)
        age = now - iat
        return (age >= 800) and (age <= 20 * 60 * 1000)
    except Exception:
        return False
def _get_password_column_names() -> Tuple[str, str]:
    """
    Zistí, či tabuľka b2b_zakaznici používa nové ('password_*') alebo staré ('heslo_*') stĺpce.
    Vráti dvojicu (hash_col, salt_col).
    """
    try:
        rows = db_connector.execute_query(
            """
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME='b2b_zakaznici'
              AND COLUMN_NAME IN ('password_hash_hex','password_salt_hex','heslo_hash','heslo_salt')
            """,
            fetch="all",
        ) or []
        cols = {r.get("COLUMN_NAME") for r in rows}
        if "password_hash_hex" in cols and "password_salt_hex" in cols:
            return ("password_hash_hex", "password_salt_hex")
        if "heslo_hash" in cols and "heslo_salt" in cols:
            return ("heslo_hash", "heslo_salt")
    except Exception:
        traceback.print_exc()
    # default – preferuj nové názvy
    return ("password_hash_hex", "password_salt_hex")

# ───────────────── Utility ─────────────────
def _normalize_date_to_str(d: Any) -> str:
    """YYYY-MM-DD string pre datetime/date/str/None."""
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y-%m-%d")
    return d or ""

def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return float(default)
        return float(x)
    except Exception:
        return float(default)

# ───────────────── Heslá / login helpery ─────────────────
def _hash_password(password: str) -> Tuple[str, str]:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 250000)
    return salt.hex(), key.hex()

def _verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex or "")
        stored = bytes.fromhex(hash_hex or "")
        new = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 250000)
        return secrets.compare_digest(new, stored)
    except Exception:
        return False

def _pending_login() -> str:
    base = "PENDING-"
    while True:
        cand = base + secrets.token_hex(4).upper()
        row = db_connector.execute_query(
            "SELECT id FROM b2b_zakaznici WHERE zakaznik_id = %s", (cand,), fetch="one"
        )
        if not row:
            return cand

def _login_from_user_id(num_or_login):
    if num_or_login is None:
        return None
    if isinstance(num_or_login, str) and not num_or_login.isdigit():
        return num_or_login
    try:
        row = db_connector.execute_query(
            "SELECT zakaznik_id FROM b2b_zakaznici WHERE id=%s",
            (int(num_or_login),),
            fetch="one",
        )
        return row["zakaznik_id"] if row else None
    except Exception:
        return None

# ───────────────── PORTÁL (produkty, login) ─────────────────
def get_products_for_pricelist(pricelist_id):
    if not pricelist_id:
        return {"error": "Chýba ID cenníka."}
    rows = db_connector.execute_query(
        """
        SELECT cp.ean_produktu, p.nazov_vyrobku, cp.cena, p.dph, p.mj, p.predajna_kategoria
        FROM b2b_cennik_polozky cp
        JOIN produkty p
          ON (p.ean COLLATE utf8mb4_slovak_ci) = (cp.ean_produktu COLLATE utf8mb4_slovak_ci)
        WHERE cp.cennik_id=%s
        ORDER BY p.predajna_kategoria, p.nazov_vyrobku
        """,
        (pricelist_id,),
    ) or []
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        r["cena"] = _to_float(r.get("cena"))
        r["dph"]  = abs(_to_float(r.get("dph")))  # DPH pozitívne
        out.setdefault(r.get("predajna_kategoria") or "Nezaradené", []).append(r)
    return {"productsByCategory": out}

def _portal_customer_payload(login_id: str):
    _ensure_system_settings()
    pricelists = db_connector.execute_query(
        """
        SELECT c.id, c.nazov_cennika
        FROM b2b_cenniky c
        JOIN b2b_zakaznik_cennik zc ON zc.cennik_id = c.id
        WHERE zc.zakaznik_id = %s
        """,
        (login_id,),
    ) or []
    row = db_connector.execute_query(
        "SELECT hodnota FROM system_settings WHERE kluc='b2b_announcement' LIMIT 1",
        fetch="one",
    )
    payload = {"pricelists": pricelists, "announcement": (row["hodnota"] if row else "")}
    if len(pricelists) == 1:
        payload |= get_products_for_pricelist(pricelists[0]["id"])
    return payload

def process_b2b_login(data: dict):
    if (data or {}).get("hp"):
        return {"error": "Neplatný vstup."}
    if not _verify_antibot_token_if_present(data):
        return {"error": "Overenie zlyhalo. Skúste znova."}

    zakaznik_id = (data or {}).get("zakaznik_id")
    password    = (data or {}).get("password")
    if not zakaznik_id or not password:
        return {"error": "Zadajte prihlasovacie meno aj heslo."}

    cols_in_db = _existing_columns("b2b_zakaznici")

    # dynamicky postavíme SELECT len zo stĺpcov, ktoré v DB sú
    select_parts = ["id", "zakaznik_id", "nazov_firmy", "email"]
    if "je_schvaleny" in cols_in_db:
        select_parts.append("je_schvaleny")
    else:
        select_parts.append("1 AS je_schvaleny")
    if "je_admin" in cols_in_db:
        select_parts.append("je_admin")
    else:
        select_parts.append("0 AS je_admin")

    # heslové stĺpce – preferuj nové, fallback na staré
    if "password_salt_hex" in cols_in_db:
        select_parts.append("password_salt_hex AS password_salt_hex")
    elif "heslo_salt" in cols_in_db:
        select_parts.append("heslo_salt AS password_salt_hex")
    else:
        return {"error": "Schéma nemá stĺpec pre SALT."}

    if "password_hash_hex" in cols_in_db:
        select_parts.append("password_hash_hex AS password_hash_hex")
    elif "heslo_hash" in cols_in_db:
        select_parts.append("heslo_hash AS password_hash_hex")
    else:
        return {"error": "Schéma nemá stĺpec pre HASH hesla."}

    where = "WHERE zakaznik_id=%s"
    if "typ" in cols_in_db:
        where += " AND typ='B2B'"

    q = f"SELECT {', '.join(select_parts)} FROM b2b_zakaznici {where} LIMIT 1"
    user = db_connector.execute_query(q, (zakaznik_id,), fetch="one")

    ok = user and _verify_password(
        password,
        user.get("password_salt_hex"),
        user.get("password_hash_hex"),
    )
    if not ok:
        return {"error": "Nesprávne meno alebo heslo."}
    if (not user.get("je_admin")) and str(user.get("je_schvaleny")) in ("0", "False", "false"):
        return {"error": "Účet zatiaľ nebol schválený administrátorom."}

    resp = {
        "id": user["id"],
        "zakaznik_id": user["zakaznik_id"],
        "nazov_firmy": user["nazov_firmy"],
        "email": user["email"],
        "role": "admin" if str(user.get("je_admin")) not in ("0", "False", "false") else "zakaznik",
    }
    if resp["role"] == "zakaznik":
        resp |= _portal_customer_payload(user["zakaznik_id"])
    return {"message": "Prihlásenie úspešné.", "userData": resp}


# ───────────────── Registrácia / Reset ─────────────────
def process_b2b_registration(data: dict):
    # anti-bot
    if (data or {}).get("hp"):
        return {"error": "Neplatný vstup."}
    if not _verify_antibot_token_if_present(data):
        return {"error": "Overenie zlyhalo. Skúste znova."}

    req = data or {}
    required = ["email", "nazov_firmy", "telefon", "adresa", "password"]
    for k in required:
        if not req.get(k):
            return {"error": "Všetky polia sú povinné."}
    if not req.get("gdpr"):
        return {"error": "Je potrebný súhlas so spracovaním osobných údajov."}

    # unikátny email
    if db_connector.execute_query(
        "SELECT id FROM b2b_zakaznici WHERE LOWER(email)=LOWER(%s) LIMIT 1",
        (req["email"],),
        fetch="one",
    ):
        return {"error": "Účet s týmto e-mailom už existuje."}

    # vygeneruj prihlasovacie meno a heslo
    pending_login = _pending_login()
    salt_hex, hash_hex = _hash_password(req["password"])

    cols_in_db = _existing_columns("b2b_zakaznici")

    # dynamicky poskladáme zoznam stĺpcov a hodnôt podľa reálnej schémy
    cols = []
    vals = []

    def add(col, val):
        if col in cols_in_db:
            cols.append(col)
            vals.append(val)

    # povinné “core” polia
    add("zakaznik_id", pending_login)
    add("nazov_firmy", req["nazov_firmy"])
    add("email", req["email"])
    add("telefon", req["telefon"])
    add("adresa", req["adresa"])
    add("adresa_dorucenia", req.get("adresa_dorucenia") or "")

    # typ/flagy/reset len ak existujú v tejto schéme
    add("typ", "B2B")
    add("je_schvaleny", 0)
    add("je_admin", 0)
    add("reset_token", None)
    add("reset_token_expiry", None)

    # >>> kľúčové: nastavíme OBE dvojice hesla, ak existujú <<<
    add("password_hash_hex", hash_hex)
    add("password_salt_hex", salt_hex)
    add("heslo_hash", hash_hex)
    add("heslo_salt", salt_hex)

    # bezpečnostná poistka – ak by v DB chýbalo niektoré úplne základné pole
    if "zakaznik_id" not in cols:
        return {"error": "Schéma tabuľky b2b_zakaznici je neúplná (chýba 'zakaznik_id')."}

    # skladanie SQL
    placeholders = ",".join(["%s"] * len(cols))
    sql = f"INSERT INTO b2b_zakaznici ({', '.join(cols)}) VALUES ({placeholders})"

    try:
        db_connector.execute_query(sql, tuple(vals), fetch="none")
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Registrácia zlyhala: {getattr(e, 'msg', str(e))}"}

    # notifikácie (bez blokovania registrácie pri chybe)
    try:
        notification_handler.send_registration_pending_email(
            to=req["email"], company=req["nazov_firmy"]
        )
        notification_handler.send_new_registration_admin_alert(req)
    except Exception:
        traceback.print_exc()

    return {"message": "Registrácia odoslaná. Po schválení v kancelárii dostanete e-mail."}


def request_password_reset(data: dict):
    if (data or {}).get("hp"):
        return {"error": "Neplatný vstup."}
    if not _verify_antibot_token_if_present(data):
        return {"error": "Overenie zlyhalo. Skúste znova."}
    email = (data or {}).get("email")
    if not email:
        return {"error": "Zadajte e-mail."}

    user = db_connector.execute_query(
        "SELECT id FROM b2b_zakaznici WHERE email=%s AND typ='B2B'",
        (email,),
        fetch="one",
    )
    if not user:
        return {"error": "Účet s daným e-mailom neexistuje."}
    token = secrets.token_urlsafe(32)
    expiry = datetime.now() + timedelta(hours=2)
    db_connector.execute_query(
        "UPDATE b2b_zakaznici SET reset_token=%s, reset_token_expiry=%s WHERE id=%s",
        (token, expiry, user["id"]),
        fetch="none",
    )
    try:
        notification_handler.send_password_reset_email(email, token)
    except Exception:
        traceback.print_exc()
    return {"message": "Poslali sme vám e-mail s odkazom na zmenu hesla."}

def perform_password_reset(data: dict):
    if (data or {}).get("hp"):
        return {"error": "Neplatný vstup."}
    if not _verify_antibot_token_if_present(data):
        return {"error": "Overenie zlyhalo. Skúste znova."}

    token = (data or {}).get("token") or ""
    new_password = (data or {}).get("new_password") or ""
    if len(new_password) < 6:
        return {"error": "Heslo musí mať aspoň 6 znakov."}

    user = db_connector.execute_query(
        "SELECT id, reset_token_expiry FROM b2b_zakaznici WHERE reset_token=%s LIMIT 1",
        (token,), fetch="one"
    )
    if not user:
        return {"error": "Neplatný alebo expirovaný odkaz."}
    if user.get("reset_token_expiry") and user["reset_token_expiry"] < datetime.utcnow():
        return {"error": "Odkaz na zmenu hesla expiroval."}

    salt_hex, hash_hex = _hash_password(new_password)
    hash_col, salt_col = _get_password_column_names()

    # pokus s novým schémou (má aj reset_token stĺpce)
    try:
        db_connector.execute_query(
            f"""
            UPDATE b2b_zakaznici
               SET {hash_col}=%s, {salt_col}=%s,
                   reset_token=NULL, reset_token_expiry=NULL
             WHERE id=%s
            """,
            (hash_hex, salt_hex, user["id"]),
            fetch="none",
        )
    except Exception:
        # fallback pre staršie schémy bez reset_token stĺpcov
        db_connector.execute_query(
            f"UPDATE b2b_zakaznici SET {hash_col}=%s, {salt_col}=%s WHERE id=%s",
            (hash_hex, salt_hex, user["id"]),
            fetch="none",
        )
    return {"message": "Heslo bolo zmenené. Môžete sa prihlásiť."}


# ───────────────── Kancelária – registrácie / cenníky / zákazníci / oznam ─────────────────
def get_pending_b2b_registrations():
    rows = db_connector.execute_query(
        """
        SELECT id, zakaznik_id, nazov_firmy, email, telefon, adresa, adresa_dorucenia, je_schvaleny, datum_registracie
        FROM b2b_zakaznici
        WHERE typ='B2B' AND (je_schvaleny=0 OR zakaznik_id LIKE 'PENDING-%')
        ORDER BY id DESC
        """
    ) or []
    return {"registrations": rows}

def approve_b2b_registration(data: dict):
    reg_id = (data or {}).get("id")
    customer_id = (data or {}).get("customer_id") or (data or {}).get("customerId")
    pricelist_ids = (data or {}).get("pricelist_ids") or (data or {}).get("pricelistIds") or []

    if (not reg_id) or (not customer_id):
        return {"error": "Chýba id registrácie alebo zákaznícke číslo."}

    # zákaznícke číslo musí byť unikátne
    exists = db_connector.execute_query(
        "SELECT id FROM b2b_zakaznici WHERE zakaznik_id=%s",
        (customer_id,), fetch="one",
    )
    if exists:
        return {"error": f"Zákaznícke číslo '{customer_id}' už existuje."}

    db_connector.execute_query(
        "UPDATE b2b_zakaznici SET je_schvaleny=1, zakaznik_id=%s WHERE id=%s",
        (customer_id, reg_id), fetch="none",
    )

    # mapovanie na cenník (ak prišlo)
    if pricelist_ids:
        _ensure_mapping_table()
        conn = db_connector.get_connection()
        cur = conn.cursor()
        try:
            cur.executemany(
                "INSERT INTO b2b_zakaznik_cennik (zakaznik_id, cennik_id) VALUES (%s, %s)",
                [(customer_id, int(pid)) for pid in pricelist_ids],
            )
            conn.commit()
        finally:
            try:
                cur.close(); conn.close()
            except Exception:
                pass

    # pošleme potvrdzovací e-mail
    cust = db_connector.execute_query(
        "SELECT email, nazov_firmy FROM b2b_zakaznici WHERE id=%s",
        (reg_id,), fetch="one",
    )
    if cust:
        try:
            notification_handler.send_approval_email(
                cust["email"], cust["nazov_firmy"], customer_id
            )
        except Exception:
            traceback.print_exc()

    return {"message": "Registrácia schválená a notifikácia odoslaná."}

def reject_b2b_registration(data: dict):
    reg_id = (data or {}).get("id")
    reason = (data or {}).get("reason") or ""
    row = db_connector.execute_query(
        "SELECT email, nazov_firmy FROM b2b_zakaznici WHERE id=%s",
        (reg_id,),
        fetch="one",
    )
    db_connector.execute_query("DELETE FROM b2b_zakaznici WHERE id=%s", (reg_id,), fetch="none")
    if row:
        try:
            notification_handler.send_rejection_email(row["email"], row["nazov_firmy"], reason)
        except Exception:
            traceback.print_exc()
    return {"message": "Registrácia bola zamietnutá."}

def get_customers_and_pricelists():
    customers = db_connector.execute_query(
        """
        SELECT id, zakaznik_id, nazov_firmy, email, telefon, adresa, adresa_dorucenia, je_schvaleny
        FROM b2b_zakaznici WHERE typ='B2B' ORDER BY nazov_firmy
        """
    ) or []
    pricelists = db_connector.execute_query(
        "SELECT id, nazov_cennika FROM b2b_cenniky ORDER BY nazov_cennika"
    ) or []
    try:
        mapping_rows = db_connector.execute_query(
            "SELECT zakaznik_id, cennik_id FROM b2b_zakaznik_cennik"
        ) or []
    except Exception:
        _ensure_mapping_table()
        mapping_rows = db_connector.execute_query(
            "SELECT zakaznik_id, cennik_id FROM b2b_zakaznik_cennik"
        ) or []

    by_customer: Dict[str, List[int]] = {}
    for m in mapping_rows:
        by_customer.setdefault(m['zakaznik_id'], []).append(m['cennik_id'])
    return {"customers": customers, "pricelists": pricelists, "mapping": by_customer}

def update_customer_details(data: dict):
    cid = (data or {}).get("id")
    fields = (data or {}).get("fields") or {}
    if not fields:
        fields = {k: v for k, v in (data or {}).items() if k in {
            'nazov_firmy','email','telefon','adresa','adresa_dorucenia','je_schvaleny','je_admin'
        }}
    pricelist_ids = (data or {}).get("pricelist_ids") or []
    if not cid:
        return {"error": "Chýba id zákazníka."}

    sets: List[str] = []
    params: List[Any] = []
    for k in ['nazov_firmy','email','telefon','adresa','adresa_dorucenia','je_schvaleny','je_admin']:
        if k in fields:
            sets.append(f"{k}=%s")
            params.append(fields[k])
    if sets:
        db_connector.execute_query(
            "UPDATE b2b_zakaznici SET " + ", ".join(sets) + " WHERE id=%s",
            tuple(params + [cid]),
            fetch="none",
        )

    row = db_connector.execute_query("SELECT zakaznik_id FROM b2b_zakaznici WHERE id=%s", (cid,), fetch="one")
    if row and row["zakaznik_id"]:
        login = row["zakaznik_id"]
        _ensure_mapping_table()
        db_connector.execute_query("DELETE FROM b2b_zakaznik_cennik WHERE zakaznik_id = %s", (login,), fetch="none")
        if pricelist_ids:
            conn = db_connector.get_connection()
            cur = conn.cursor()
            try:
                cur.executemany(
                    "INSERT INTO b2b_zakaznik_cennik (zakaznik_id, cennik_id) VALUES (%s, %s)",
                    [(login, int(pid)) for pid in pricelist_ids],
                )
                conn.commit()
            finally:
                try:
                    cur.close(); conn.close()
                except Exception:
                    pass
    return {"message": "Zákazník aktualizovaný."}

def get_pricelists_and_products():
    _ensure_pricelist_tables()
    pricelists = db_connector.execute_query(
        "SELECT id, nazov_cennika FROM b2b_cenniky ORDER BY nazov_cennika"
    ) or []

    products = []
    try:
        products = db_connector.execute_query(
            "SELECT ean, nazov_vyrobku, COALESCE(dph,0) dph, COALESCE(mj,'ks') mj, COALESCE(predajna_kategoria,'Nezaradené') predajna_kategoria FROM produkty ORDER BY nazov_vyrobku"
        ) or []
    except Exception:
        products = []

    if not products:
        try:
            products = db_connector.execute_query(
                "SELECT ean, nazov_produktu AS nazov_vyrobku, COALESCE(dph,0) dph, COALESCE(mj,'ks') mj, COALESCE(predajna_kategoria,'Nezaradené') predajna_kategoria FROM sklad2 ORDER BY nazov_produktu"
            ) or []
        except Exception:
            products = []

    return {"pricelists": pricelists, "products": products}

def create_pricelist(data: dict):
    _ensure_pricelist_tables()
    name = (data or {}).get("nazov_cennika") or (data or {}).get("name")
    items = (data or {}).get("items") or []
    if not name:
        return {"error": "Názov cenníka je povinný."}

    conn = db_connector.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO b2b_cenniky (nazov_cennika) VALUES (%s)", (name,))
        pl_id = cur.lastrowid
        if items:
            batch = []
            for item in items:
                ean = item.get("ean") or item.get("ean_produktu")
                price = _to_float(item.get("cena") or item.get("price"))
                title = item.get("nazov_vyrobku") or ""
                if ean and price >= 0:
                    batch.append((pl_id, ean, title, price))
            if batch:
                cur.executemany(
                    "INSERT INTO b2b_cennik_polozky (cennik_id, ean_produktu, nazov_vyrobku, cena) VALUES (%s,%s,%s,%s)",
                    batch
                )
        conn.commit()
        return {"message": "Cenník vytvorený.", "id": pl_id}
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass

def get_pricelist_details(data: dict):
    pl_id = (data or {}).get("id")
    if not pl_id:
        return {"error": "Chýba id cenníka."}
    pl = db_connector.execute_query(
        "SELECT id, nazov_cennika FROM b2b_cenniky WHERE id=%s", (pl_id,), fetch="one"
    )
    if not pl:
        return {"error": "Cenník neexistuje."}
    items = db_connector.execute_query(
        "SELECT ean_produktu, nazov_vyrobku, cena FROM b2b_cennik_polozky WHERE cennik_id = %s ORDER BY nazov_vyrobku",
        (pl_id,),
    ) or []
    return {"pricelist": pl, "items": items}

def update_pricelist(data: dict):
    _ensure_pricelist_tables()
    pl_id = (data or {}).get("id")
    items = (data or {}).get("items") or []
    if not pl_id:
        return {"error": "Chýba id cenníka."}

    eans: List[str] = []
    pairs: List[Tuple[str, float]] = []
    for it in items:
        e = str(it.get("ean") if "ean" in it else it.get("ean_produktu"))
        c = _to_float(it.get("price") if "price" in it else it.get("cena"))
        if e and c >= 0:
            eans.append(e)
            pairs.append((e, c))

    name_map: Dict[str, str] = {}
    if eans:
        ph = ",".join(["%s"] * len(eans))
        rows = db_connector.execute_query(
            f"SELECT ean, nazov_vyrobku FROM produkty WHERE ean IN ({ph})",
            tuple(eans),
        ) or []
        for r in rows:
            name_map[str(r["ean"])] = r["nazov_vyrobku"]
        if len(name_map) < len(eans):
            rows2 = db_connector.execute_query(
                f"SELECT ean, nazov_produktu AS nazov_vyrobku FROM sklad2 WHERE ean IN ({ph})",
                tuple(eans),
            ) or []
            for r in rows2:
                name_map[str(r["ean"])] = r["nazov_vyrobku"]

    conn = db_connector.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM b2b_cennik_polozky WHERE cennik_id=%s", (pl_id,))
        if pairs:
            batch = [(pl_id, e, name_map.get(e) or f"EAN {e}", price) for (e, price) in pairs]
            cur.executemany(
                "INSERT INTO b2b_cennik_polozky (cennik_id, ean_produktu, nazov_vyrobku, cena) VALUES (%s,%s,%s,%s)",
                batch,
            )
        conn.commit()
        return {"message": "Cenník aktualizovaný.", "count": len(pairs)}
    except Exception:
        conn.rollback()
        traceback.print_exc()
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass

def get_announcement():
    _ensure_system_settings()
    row = db_connector.execute_query(
        "SELECT hodnota FROM system_settings WHERE kluc='b2b_announcement' LIMIT 1",
        fetch="one",
    )
    return {"announcement": (row["hodnota"] if row else "")}

def save_announcement(data: dict):
    text = (data or {}).get("announcement", "")
    _ensure_system_settings()
    exists = db_connector.execute_query(
        "SELECT kluc FROM system_settings WHERE kluc='b2b_announcement' LIMIT 1",
        fetch="one"
    )
    if exists:
        db_connector.execute_query(
            "UPDATE system_settings SET hodnota=%s WHERE kluc='b2b_announcement'",
            (text,), fetch='none'
        )
    else:
        db_connector.execute_query(
            "INSERT INTO system_settings (kluc, hodnota) VALUES ('b2b_announcement', %s)",
            (text,), fetch='none'
        )
    return {"message": "Oznam uložený."}

def _get_pricelist_price_map(login_id: str, eans: List[str]) -> Dict[str, float]:
    try:
        if not login_id or not eans:
            return {}
        _ensure_mapping_table()
        rows = db_connector.execute_query(
            "SELECT cennik_id FROM b2b_zakaznik_cennik WHERE zakaznik_id=%s ORDER BY cennik_id",
            (login_id,)
        ) or []
        if not rows:
            return {}
        # zoberieme prvý priradený cenník
        pl_id = int(rows[0].get("cennik_id") or list(rows[0].values())[0])
        ph = ",".join(["%s"] * len(eans))
        q = f"SELECT ean_produktu, cena FROM b2b_cennik_polozky WHERE cennik_id=%s AND ean_produktu IN ({ph})"
        params = [pl_id] + [str(e) for e in eans]
        items = db_connector.execute_query(q, tuple(params)) or []
        return {str(r["ean_produktu"]): float(r["cena"]) for r in items if r.get("ean_produktu") is not None}
    except Exception:
        traceback.print_exc()
        return {}

# ───────────────── Objednávky ─────────────────
def submit_b2b_order(data: dict):
    user_id        = (data or {}).get("userId")
    items_in       = (data or {}).get("items") or []
    note           = (data or {}).get("note")
    delivery_date  = (data or {}).get("deliveryDate")
    customer_email = (data or {}).get("customerEmail")

    if not (user_id and items_in and delivery_date and customer_email):
        return {"error": "Chýbajú povinné údaje (zákazník, položky, dátum dodania, e-mail)."}

    cust = db_connector.execute_query(
        "SELECT id, zakaznik_id, nazov_firmy, adresa FROM b2b_zakaznici WHERE id=%s",
        (user_id,), fetch="one",
    )
    if not cust:
        return {"error": "Zákazník neexistuje."}
    login_id = cust["zakaznik_id"]

    # DPH, MJ, názvy z 'produkty' podľa EAN
    eans = [str(it.get("ean")) for it in items_in if it.get("ean")]
    pmap: Dict[str, Any] = {}
    if eans:
        ph = ",".join(["%s"] * len(eans))
        rows = db_connector.execute_query(
            f"SELECT ean, dph, predajna_kategoria, vaha_balenia_g, typ_polozky, mj, nazov_vyrobku FROM produkty WHERE ean IN ({ph})",
            tuple(eans)
        ) or []
        pmap = {str(r["ean"]): r for r in rows}

    # doplníme cenníkové ceny na základe priradeného cenníka
    pricelist_price_by_ean = _get_pricelist_price_map(login_id, eans)

    pdf_items: List[Dict[str, Any]] = []
    total_net = 0.0
    total_vat = 0.0

    for it in items_in:
        qty   = _to_float(it.get("quantity"))
        price = _to_float(it.get("price"))               # bez DPH / MJ (objednávková cena)
        pm    = pmap.get(str(it.get("ean"))) or {}
        dph   = abs(_to_float(pm.get("dph", it.get("dph"))))
        line_net = price * qty
        line_vat = line_net * (dph / 100.0)
        total_net += line_net
        total_vat += line_vat
        pdf_items.append({
            "ean": str(it.get("ean")),
            "name": it.get("name") or pm.get("nazov_vyrobku") or "",
            "unit": it.get("unit") or pm.get("mj") or "ks",
            "quantity": qty,
            "price": price,                  # objednávková cena bez DPH
            "dph": dph,
            "line_net": line_net,
            "line_vat": line_vat,
            "line_gross": line_net + line_vat,
            "pricelist_price": pricelist_price_by_ean.get(str(it.get("ean")))  # << nový údaj
        })

    total_gross = total_net + total_vat

    order_payload = {
        "order_number": None,  # doplníme po INSERTe
        "customerName": cust["nazov_firmy"],
        "customerAddress": cust["adresa"],
        "deliveryDate": delivery_date,
        "note": note,
        "items": pdf_items,
        "totalNet": total_net,
        "totalVat": total_vat,
        "totalWithVat": total_gross,
    }

    # uloženie hlavičky + položiek
    order_number = f"B2B-{login_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    conn = db_connector.get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO b2b_objednavky
              (cislo_objednavky, zakaznik_id, nazov_firmy, adresa, pozadovany_datum_dodania, poznamka, celkova_suma_s_dph)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (order_number, login_id, cust["nazov_firmy"], cust["adresa"], _normalize_date_to_str(delivery_date), note, total_gross)
        )
        oid = cur.lastrowid

        lines: List[Tuple[Any, ...]] = []
        for i in pdf_items:
            pm = pmap.get(str(i.get("ean"))) or {}
            lines.append((
                oid,
                i.get("ean"),
                i.get("name") or pm.get("nazov_vyrobku") or "",
                i["quantity"],
                pm.get("mj") or i.get("unit") or "ks",
                abs(_to_float(pm.get("dph", i.get("dph")))),
                pm.get("predajna_kategoria"),
                pm.get("vaha_balenia_g"),
                pm.get("typ_polozky"),
                i["price"],  # bez DPH
                _normalize_date_to_str(delivery_date),
            ))
        cur.executemany(
            """
            INSERT INTO b2b_objednavky_polozky
              (objednavka_id, ean_produktu, nazov_vyrobku, mnozstvo, mj, dph, predajna_kategoria, vaha_balenia_g, typ_polozky, cena_bez_dph, pozadovany_datum_dodania)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            lines
        )
        conn.commit()
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass

    # vygenerujeme PDF + CSV a odošleme
    order_payload["order_number"] = order_number
    try:
        pdf_bytes, csv_bytes = pdf_generator.create_order_files(order_payload)
        # zákazník – PDF
        try:
            notification_handler.send_order_confirmation_email(
                to=customer_email, order_number=order_number, pdf_content=pdf_bytes, csv_content=None
            )
        except Exception:
            traceback.print_exc()
        # expedícia – PDF + CSV
        try:
            notification_handler.send_order_confirmation_email(
                to=EXPEDITION_EMAIL, order_number=order_number, pdf_content=pdf_bytes, csv_content=csv_bytes
            )
        except Exception:
            traceback.print_exc()
    except Exception:
        traceback.print_exc()

    return {
        "status": "success",
        "message": f"Objednávka {order_number} bola prijatá.",
        "order_data": order_payload,
    }

def get_order_history(user_id):
    login = _login_from_user_id(user_id) or user_id
    rows = db_connector.execute_query(
        """
        SELECT id, cislo_objednavky, datum_objednavky AS datum_vytvorenia, stav, celkova_suma_s_dph, poznamka
        FROM b2b_objednavky
        WHERE zakaznik_id=%s
        ORDER BY datum_objednavky DESC
        """,
        (login,),
    ) or []
    return {"orders": rows}

def get_all_b2b_orders(filters=None):
    filters = filters or {}
    where: List[str] = []
    params: List[Any] = []
    if filters.get("from_date"):
        where.append("datum_objednavky >= %s")
        params.append(filters["from_date"])
    if filters.get("to_date"):
        where.append("datum_objednavky < %s")
        params.append(filters["to_date"])
    if filters.get("customer"):
        where.append("zakaznik_id=%s")
        params.append(filters["customer"])
    q = "SELECT id, cislo_objednavky, zakaznik_id, nazov_firmy, datum_objednavky, pozadovany_datum_dodania, stav, celkova_suma_s_dph FROM b2b_objednavky"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY datum_objednavky DESC"
    rows = db_connector.execute_query(q, tuple(params) if params else None) or []
    return {"orders": rows}

def get_b2b_order_details(data_or_id):
    if isinstance(data_or_id, dict):
        oid = data_or_id.get("id")
    else:
        oid = data_or_id
    if not oid:
        return {"error": "Chýba id objednávky."}
    head = db_connector.execute_query("SELECT * FROM b2b_objednavky WHERE id = %s", (oid,), fetch="one")
    if not head:
        return {"error": "Objednávka neexistuje."}
    items = db_connector.execute_query(
        "SELECT * FROM b2b_objednavky_polozky WHERE objednavka_id = %s ORDER BY id",
        (oid,),
    ) or []
    return {"order": head, "items": items}

# ───────────────── PDF payloady ─────────────────
def build_order_pdf_for_customer(order_id: int, user_id: int):
    if not order_id or not user_id:
        return {"error": "Chýba objednávka alebo používateľ.", "code": 400}

    head = db_connector.execute_query(
        "SELECT id, cislo_objednavky, zakaznik_id, nazov_firmy, adresa, pozadovany_datum_dodania, datum_objednavky, celkova_suma_s_dph "
        "FROM b2b_objednavky WHERE id=%s", (order_id,), fetch='one'
    )
    if not head:
        return {"error": "Objednávka neexistuje.", "code": 404}

    user_row = db_connector.execute_query(
        "SELECT zakaznik_id FROM b2b_zakaznici WHERE id=%s", (user_id,), fetch='one'
    )
    if not user_row:
        return {"error": "Používateľ neexistuje.", "code": 404}
    if str(head['zakaznik_id']) != str(user_row['zakaznik_id']):
        return {"error": "Nedovolený prístup k objednávke.", "code": 403}

    items = db_connector.execute_query(
        "SELECT ean_produktu, nazov_vyrobku, mnozstvo, mj, dph, cena_bez_dph "
        "FROM b2b_objednavky_polozky WHERE objednavka_id=%s ORDER BY id", (order_id,)
    ) or []

    mapped: List[Dict[str, Any]] = []
    total_net = 0.0
    total_vat = 0.0
    for it in items:
        qty   = _to_float(it.get("mnozstvo"))
        price = _to_float(it.get("cena_bez_dph"))
        dph   = abs(_to_float(it.get("dph")))
        line_net = price * qty
        line_vat = line_net * (dph / 100.0)
        total_net += line_net
        total_vat += line_vat
        mapped.append({
            "ean": it.get("ean_produktu"),
            "name": it.get("nazov_vyrobku"),
            "quantity": qty,
            "unit": it.get("mj") or "ks",
            "price": price,
            "dph": dph,
            "vatPercent": dph,
            "line_net": line_net, "line_vat": line_vat, "line_gross": line_net + line_vat,
            "lineNet": line_net,  "lineVAT": line_vat,  "lineGross": line_net + line_vat,
            "net": line_net, "vat_amount": line_vat, "gross": line_net + line_vat,
        })

    delivery_norm = _normalize_date_to_str(head.get("pozadovany_datum_dodania"))
    total_gross = total_net + total_vat

    data = {
        "order_number": head["cislo_objednavky"],
        "customer_name": head["nazov_firmy"],
        "customer_address": head["adresa"],
        "delivery_date": delivery_norm,
        "note": "",
        "items": mapped,
        "total_net": total_net,
        "total_vat": total_vat,
        "total_with_vat": total_gross,
        # aliasy pre pdf_generator
        "orderNumber": head["cislo_objednavky"],
        "customerName": head["nazov_firmy"],
        "customerAddress": head["adresa"],
        "deliveryDate": delivery_norm,
        "totalNet": total_net,
        "totalVat": total_vat,
        "totalWithVat": total_gross,
        "sum_dph": total_vat,
        "sum_vat": total_vat,
        "totalVatAmount": total_vat,
        "totalNetAmount": total_net,
        "totalGross": total_gross,
        "totalGrossWithVat": total_gross,
    }

    pdf_bytes, _ = pdf_generator.create_order_files(data)
    return {"pdf": pdf_bytes, "filename": f"objednavka_{head['cislo_objednavky']}.pdf"}

def build_order_pdf_payload_admin(order_id: int) -> dict:
    """
    Admin payload pre pdf_generator.create_order_files() – bez kontroly vlastníka.
    DPH sa berie z 'produkty', súhrny sú spočítané, posielajú sa aj aliasy.
    """
    if not order_id:
        return {"error": "Chýba id objednávky."}

    head = db_connector.execute_query(
        "SELECT id, cislo_objednavky, zakaznik_id, nazov_firmy, adresa, "
        "       pozadovany_datum_dodania, datum_objednavky, celkova_suma_s_dph, poznamka "
        "FROM b2b_objednavky WHERE id=%s",
        (order_id,), fetch="one"
    )
    if not head:
        return {"error": "Objednávka neexistuje."}

    rows = db_connector.execute_query(
        "SELECT ean_produktu, nazov_vyrobku, mnozstvo, mj, dph, cena_bez_dph "
        "FROM b2b_objednavky_polozky WHERE objednavka_id=%s ORDER BY id",
        (order_id,)
    ) or []

    eans = [r["ean_produktu"] for r in rows if r.get("ean_produktu")]
    pmap = {}
    if eans:
        ph = ",".join(["%s"] * len(eans))
        prod_rows = db_connector.execute_query(
            f"SELECT ean, dph, nazov_vyrobku, mj FROM produkty WHERE ean IN ({ph})",
            tuple(eans)
        ) or []
        pmap = {pr["ean"]: pr for pr in prod_rows}

    items: List[Dict[str, Any]] = []
    total_net = 0.0
    total_vat = 0.0
    for r in rows:
        qty   = _to_float(r.get("mnozstvo"))
        price = _to_float(r.get("cena_bez_dph"))
        pm    = pmap.get(r.get("ean_produktu")) or {}
        dph   = abs(_to_float(pm.get("dph", r.get("dph"))))
        line_net = price * qty
        line_vat = line_net * (dph / 100.0)
        total_net += line_net
        total_vat += line_vat
        items.append({
            "ean": r.get("ean_produktu"),
            "name": r.get("nazov_vyrobku") or pm.get("nazov_vyrobku") or "",
            "quantity": qty,
            "unit": r.get("mj") or pm.get("mj") or "ks",
            "price": price,
            "dph": dph,
            "vatPercent": dph,
            "line_net": line_net, "line_vat": line_vat, "line_gross": line_net + line_vat,
            "lineNet": line_net,  "lineVAT": line_vat,  "lineGross": line_net + line_vat,
            "net": line_net, "vat_amount": line_vat, "gross": line_net + line_vat,
        })

    delivery = head.get("pozadovany_datum_dodania")
    if isinstance(delivery, (datetime, date)):
        delivery = delivery.strftime("%Y-%m-%d")
    elif delivery is None:
        delivery = ""

    total_gross = total_net + total_vat

    payload = {
        "order_number": head["cislo_objednavky"],
        "customer_name": head["nazov_firmy"],
        "customer_address": head["adresa"],
        "delivery_date": delivery,
        "note": head.get("poznamka") or "",
        "items": items,

        "total_net": total_net,
        "total_vat": total_vat,
        "total_with_vat": total_gross,

        # aliasy
        "orderNumber": head["cislo_objednavky"],
        "customerName": head["nazov_firmy"],
        "customerAddress": head["adresa"],
        "deliveryDate": delivery,
        "totalNet": total_net,
        "totalVat": total_vat,
        "totalWithVat": total_gross,
        "sum_dph": total_vat,
        "sum_vat": total_vat,
        "totalVatAmount": total_vat,
        "totalNetAmount": total_net,
        "totalGross": total_gross,
        "totalGrossWithVat": total_gross,
    }
    return payload

# ───────────────── Komunikácia ─────────────────
def _comm_inbox_email():
    return os.getenv('B2B_COMM_EMAIL') or os.getenv('ADMIN_NOTIFY_EMAIL') or os.getenv('MAIL_DEFAULT_SENDER') or os.getenv('MAIL_USERNAME')

def _safe_name(name: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    return "".join(ch if ch in keep else "_" for ch in (name or ""))[:180] or "priloha"

def portal_message_send(req):
    _ensure_comm_table()
    user_id = req.form.get('userId', type=int)
    subject = (req.form.get('subject') or '').strip()
    body    = (req.form.get('body') or '').strip()
    if not (user_id and subject and body):
        return {"error":"Chýbajú povinné polia."}

    cust = db_connector.execute_query("SELECT id, zakaznik_id, nazov_firmy, email FROM b2b_zakaznici WHERE id=%s",(user_id,),fetch="one")
    if not cust:
        return {"error":"Zákazník neexistuje."}
    login = cust['zakaznik_id']
    cname = cust['nazov_firmy']
    cemail = cust['email']

    # uloženie prílohy
    file = req.files.get('file')
    a_path = a_name = a_mime = None
    a_size = None
    if file and file.filename:
        base_dir = os.path.join(os.getcwd(), 'storage', 'b2b_comm', datetime.now().strftime('%Y/%m'))
        os.makedirs(base_dir, exist_ok=True)
        a_name = _safe_name(file.filename)
        a_path = os.path.join(base_dir, f"{int(time.time())}_{a_name}")
        a_mime = file.mimetype or 'application/octet-stream'
        file.save(a_path)
        try:
            a_size = os.path.getsize(a_path)
        except Exception:
            a_size = None

    # DB záznam
    db_connector.execute_query(
        "INSERT INTO b2b_messages (customer_id, zakaznik_login, customer_name, customer_email, subject, body, direction, status, attachment_path, attachment_filename, attachment_mime, attachment_size) "
        "VALUES (%s,%s,%s,%s,%s,%s,'in','new',%s,%s,%s,%s)",
        (user_id, login, cname, cemail, subject, body, a_path, a_name, a_mime, a_size),
        fetch="none"
    )

    # email adminovi
    try:
        to_admin = _comm_inbox_email()
        if to_admin:
            html = f"<p><strong>B2B správa od:</strong> {cname} ({login}) &lt;{cemail}&gt;</p><p><strong>Predmet:</strong> {subject}</p><p><pre style='white-space:pre-wrap'>{body}</pre></p>"
            attachments = []
            if a_path and os.path.isfile(a_path):
                with open(a_path,'rb') as fh:
                    attachments.append((a_name, fh.read(), a_mime or 'application/octet-stream'))
            notification_handler._send_email(to_admin, f"B2B správa – {cname} ({login})", notification_handler._wrap_html("B2B správa", html), attachments)
    except Exception:
        traceback.print_exc()

    return {"message":"Správa bola odoslaná."}

def portal_my_messages(user_id: int, page:int=1, page_size:int=50):
    _ensure_comm_table()
    off = max(0, (int(page or 1)-1)*max(1,int(page_size or 50)))
    rows = db_connector.execute_query(
        "SELECT id, created_at, subject, body, direction, status, attachment_filename FROM b2b_messages WHERE customer_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (user_id, max(1,int(page_size or 50)), off)
    ) or []
    return {"messages": rows}

def admin_messages_list(args):
    _ensure_comm_table()
    where=[]; params=[]
    status = args.get('status')
    customer_id = args.get('customer_id', type=int)
    q = args.get('q')
    if status and status.lower()!='all':
        where.append("status=%s"); params.append(status.lower())
    if customer_id:
        where.append("customer_id=%s"); params.append(customer_id)
    if q:
        where.append("(subject LIKE %s OR body LIKE %s OR customer_name LIKE %s OR zakaznik_login LIKE %s)")
        like = f"%{q}%"; params += [like,like,like,like]
    sql = "SELECT id, created_at, customer_id, zakaznik_login, customer_name, customer_email, subject, LEFT(body,1000) body, direction, status, attachment_filename FROM b2b_messages"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY status='new' DESC, created_at DESC LIMIT 200"
    rows = db_connector.execute_query(sql, tuple(params) if params else None) or []
    return {"messages": rows}

def admin_messages_unread_count():
    _ensure_comm_table()
    row = db_connector.execute_query("SELECT COUNT(*) AS c FROM b2b_messages WHERE status='new'", fetch="one") or {"c":0}
    return {"unread": int(row["c"] or 0)}

def admin_messages_mark_read(data: dict):
    _ensure_comm_table()
    mid = (data or {}).get("id")
    if not mid:
        return {"error":"Chýba id správy."}
    db_connector.execute_query("UPDATE b2b_messages SET status='read' WHERE id=%s",(mid,),fetch="none")
    return {"message":"Označené ako prečítané."}

def admin_messages_reply(req):
    _ensure_comm_table()
    mid = req.form.get('id', type=int)
    body = (req.form.get('body') or '').strip()
    subject = (req.form.get('subject') or '').strip()
    if not (mid and body):
        return {"error":"Chýbajú povinné polia."}
    orig = db_connector.execute_query("SELECT * FROM b2b_messages WHERE id=%s",(mid,),fetch="one")
    if not orig:
        return {"error":"Pôvodná správa neexistuje."}
    to = orig["customer_email"]
    cname = orig["customer_name"]
    login = orig["zakaznik_login"]

    # príloha
    file = req.files.get('file')
    a_path=a_name=a_mime=None
    a_size=None
    if file and file.filename:
        base_dir = os.path.join(os.getcwd(), 'storage', 'b2b_comm', datetime.now().strftime('%Y/%m'))
        os.makedirs(base_dir, exist_ok=True)
        a_name = _safe_name(file.filename)
        a_path = os.path.join(base_dir, f"{int(time.time())}_{a_name}")
        a_mime = file.mimetype or 'application/octet-stream'
        file.save(a_path)
        try:
            a_size=os.path.getsize(a_path)
        except Exception:
            a_size=None

    # uložiť outbound
    db_connector.execute_query(
        "INSERT INTO b2b_messages (customer_id, zakaznik_login, customer_name, customer_email, subject, body, direction, status, attachment_path, attachment_filename, attachment_mime, attachment_size, parent_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,'out','read',%s,%s,%s,%s,%s)",
        (orig["customer_id"], login, cname, to, subject or (f"Re: {orig.get('subject') or ''}"), body, a_path, a_name, a_mime, a_size, mid),
        fetch="none"
    )

    # e-mail zákazníkovi
    try:
        html = f"<p>Dobrý deň,</p><p>{body.replace(chr(10),'<br/>')}</p><hr/><p style='color:#666'>Re: {orig.get('subject') or ''}</p>"
        attachments = []
        if a_path and os.path.isfile(a_path):
            with open(a_path,'rb') as fh:
                attachments.append((a_name, fh.read(), a_mime or 'application/octet-stream'))
        notification_handler._send_email(to, subject or f"Re: {orig.get('subject') or ''}", notification_handler._wrap_html("Správa od MIK s.r.o.", html), attachments)
    except Exception:
        traceback.print_exc()

    return {"message":"Odpoveď odoslaná."}
