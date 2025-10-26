import db_connector
import hashlib
import os
import secrets
from datetime import datetime, timedelta
import traceback
import notification_handler
import pdf_generator

# ================================================================
#  B2B HANDLER – verzia kompatibilná s DB schémou "vyrobny_system"
#
#  Kľúčové zmeny vs. pôvodný kód:
#   • heslá: stĺpce v DB sú password_salt_hex / password_hash_hex
#   • b2b_zakaznik_cennik referencuje TEXTOVÉ zakaznik_id (nie číselné id)
#   • b2b_objednavky.zakaznik_id je TEXT (zakaznik_id), JOIN-uje sa na z.zakaznik_id
#   • b2b_objednavky nemá stĺpec celkova_suma_bez_dph – netto cenu počítame z položiek
#   • b2b_objednavky_polozky: názvy stĺpcov sú nazov_vyrobku, mj, cena_bez_dph, dph...
#   • produkty.typ_polozky = 'produkt' (nie 'VÝROBOK'/'TOVAR')
#   • b2b_zakaznici: máme aj telefon a datum_registracie (už ošetrené patchom)
#
#  Pozn.: ak front-end posiela číselné id, tu ho mapujeme na textové zakaznik_id.
# ================================================================

# =================================================================
# === BEZPEČNOSTNÉ FUNKCIE PRE PRÁCU S HESLAMI ===
# =================================================================

def generate_password_hash(password):
    """Vygeneruje bezpečnú soľ a hash pre zadané heslo pomocou PBKDF2."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 250000)
    return salt.hex(), key.hex()


def verify_password(password, salt_hex, hash_hex):
    """Overí, či sa zadané heslo zhoduje s uloženou soľou a hashom."""
    try:
        salt = bytes.fromhex(salt_hex)
        stored_key = bytes.fromhex(hash_hex)
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 250000)
        return new_key == stored_key
    except (ValueError, TypeError):
        return False


# =================================================================
# === POMOCNÉ FUNKCIE (DB kompat vrstva) ===
# =================================================================

def _get_login_id_from_numeric(user_id_or_login):
    """Ak príde číselný id (PK), premapuje na textové zakaznik_id. V opačnom prípade vráti vstup."""
    if user_id_or_login is None:
        return None
    # už textové zakaznik_id
    if isinstance(user_id_or_login, str) and not user_id_or_login.isdigit():
        return user_id_or_login
    # číslo alebo string-cislo -> lookup
    try:
        q = "SELECT zakaznik_id FROM b2b_zakaznici WHERE id = %s"
        row = db_connector.execute_query(q, (int(user_id_or_login),), fetch='one')
        return row['zakaznik_id'] if row else None
    except Exception:
        return None


def _generate_pending_login_id():
    """Vytvorí dočasné jedinečné zakaznik_id pre ne/ schválené registrácie."""
    return f"P{secrets.token_hex(6).upper()}"  # napr. 'P8F1C3A9B2D4'


# =================================================================
# === ZÍSKAVANIE DÁT PRE ZÁKAZNÍKA ===
# =================================================================

def get_products_for_pricelist(pricelist_id):
    """Získa produkty a ich ceny pre konkrétny cenník, zoskupené podľa kategórie."""
    if not pricelist_id:
        return {"error": "Chýba ID cenníka."}

    query = (
        """
        SELECT cp.ean_produktu, p.nazov_vyrobku, cp.cena, p.dph, p.mj, p.predajna_kategoria
        FROM b2b_cennik_polozky cp
        JOIN produkty p ON cp.ean_produktu = p.ean
        WHERE cp.cennik_id = %s
        ORDER BY p.predajna_kategoria, p.nazov_vyrobku
        """
    )
    products = db_connector.execute_query(query, (pricelist_id,))

    products_by_category = {}
    for p in products:
        p['cena'] = float(p['cena'] or 0)
        p['dph'] = float(p['dph'] or 0)
        category = p.get('predajna_kategoria') or 'Nezaradené'
        products_by_category.setdefault(category, []).append(p)

    return {"productsByCategory": products_by_category}


def get_customer_data(user_login_id):
    """Získa dáta pre zákazníka (textové zakaznik_id), vrátane oznamu a cenníkov."""
    if not user_login_id:
        return {"pricelists": [], "announcement": ""}

    pricelists_query = (
        """
        SELECT c.id, c.nazov_cennika
        FROM b2b_cenniky c
        JOIN b2b_zakaznik_cennik zc ON c.id = zc.cennik_id
        WHERE zc.zakaznik_id = %s
        """
    )
    pricelists = db_connector.execute_query(pricelists_query, (user_login_id,))

    announcement_record = db_connector.execute_query(
        "SELECT hodnota FROM b2b_nastavenia WHERE kluc = 'oznam'",
        fetch='one',
    )
    announcement = announcement_record['hodnota'] if announcement_record else ""

    response = {"pricelists": pricelists, "announcement": announcement}

    if not pricelists:
        return response
    if len(pricelists) == 1:
        products_data = get_products_for_pricelist(pricelists[0]['id'])
        response.update(products_data)

    return response


# =================================================================
# === PRIHLASOVANIE, REGISTRÁCIA, OBJEDNÁVKY ===
# =================================================================

def process_b2b_login(data):
    """Spracuje prihlásenie B2B zákazníka a vráti dáta pre portál."""
    zakaznik_id, password = data.get('zakaznik_id'), data.get('password')
    if not zakaznik_id or not password:
        return {"error": "Musíte zadať prihlasovacie meno aj heslo."}

    query = (
        """
        SELECT id, zakaznik_id, nazov_firmy, email,
               password_hash_hex, password_salt_hex,
               je_schvaleny, je_admin
        FROM b2b_zakaznici
        WHERE zakaznik_id = %s AND typ = 'B2B'
        """
    )
    user = db_connector.execute_query(query, (zakaznik_id,), fetch='one')

    if (not user) or (not verify_password(password, user['password_salt_hex'], user['password_hash_hex'])):
        return {"error": "Nesprávne prihlasovacie meno alebo heslo."}

    if (not user['je_admin']) and (not user['je_schvaleny']):
        return {"error": "Váš účet ešte nebol schválený administrátorom."}

    response_data = {
        "id": user['id'],
        "zakaznik_id": user['zakaznik_id'],
        "nazov_firmy": user['nazov_firmy'],
        "email": user['email'],
        "role": "admin" if user['je_admin'] else "zakaznik",
    }

    if not user['je_admin']:
        response_data.update(get_customer_data(user['zakaznik_id']))

    return {"message": "Prihlásenie úspešné.", "userData": response_data}


def process_b2b_registration(data):
    """Spracuje novú B2B registráciu, odošle notifikácie a uloží do DB."""
    required = ['email', 'nazov_firmy', 'adresa', 'adresa_dorucenia', 'telefon', 'password']
    if not all(field in data for field in required):
        return {"error": "Všetky polia sú povinné."}
    if not data.get('gdpr'):
        return {"error": "Musíte súhlasiť so spracovaním osobných údajov."}

    # Unikátny e-mail len pre B2B
    if db_connector.execute_query(
        "SELECT id FROM b2b_zakaznici WHERE email = %s AND typ = 'B2B'",
        (data['email'],),
        fetch='one',
    ):
        return {"error": "B2B účet s týmto e-mailom už existuje."}

    salt_hex, hash_hex = generate_password_hash(data['password'])

    # Zakaznik_id musí byť NOT NULL a unikátne – kým nie je schválené, použijeme dočasné ID
    pending_login = _generate_pending_login_id()

    params = (
        data['email'],
        data['nazov_firmy'],
        data['adresa'],
        data.get('adresa_dorucenia'),
        data['telefon'],
        hash_hex,
        salt_hex,
        1,  # gdpr_suhlas
        'B2B',
        pending_login,
        0,  # je_schvaleny
        0,  # je_admin
    )

    db_connector.execute_query(
        (
            """
            INSERT INTO b2b_zakaznici (
              email, nazov_firmy, adresa, adresa_dorucenia, telefon,
              password_hash_hex, password_salt_hex,
              gdpr_suhlas, typ, zakaznik_id, je_schvaleny, je_admin
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        ),
        params,
        fetch='none',
    )

    try:
        notification_handler.send_registration_pending_email(data['email'], data['nazov_firmy'])
        notification_handler.send_new_registration_admin_alert(data)
    except Exception:
        print("--- VAROVANIE: Registrácia bola úspešná, ale e-maily sa nepodarilo odoslať. Skontrolujte .env nastavenia. ---")
        print(traceback.format_exc())

    return {
        "message": (
            "Registrácia prebehla úspešne. Na Váš e-mail sme odoslali potvrdenie. "
            "Účet bude aktívny po schválení administrátorom."
        )
    }


def submit_b2b_order(data):
    """Spracuje finálne odoslanie B2B objednávky – plne kompatibilné so schémou."""
    user_id = data.get('userId')  # môže byť číselné id
    items = data.get('items')
    note = data.get('note')
    delivery_date = data.get('deliveryDate')
    customer_email = data.get('customerEmail')
    customer_name = data.get('customerName')

    if not all([user_id, items, delivery_date, customer_email]):
        return {"error": "Chýbajú povinné údaje pre spracovanie objednávky."}

    # Získať info o zákazníkovi (podľa číselného id) a zároveň získať textové zakaznik_id
    customer_info = db_connector.execute_query(
        "SELECT id, zakaznik_id, nazov_firmy, adresa FROM b2b_zakaznici WHERE id = %s",
        (user_id,),
        fetch='one',
    ) or {}
    login_id = customer_info.get('zakaznik_id') or _get_login_id_from_numeric(user_id)

    final_customer_name = customer_name or customer_info.get('nazov_firmy')
    if not final_customer_name or not login_id:
        return {"error": "Nepodarilo sa načítať údaje o zákazníkovi."}

    # Súčet cien z položiek (netto a s DPH – ak položky obsahujú DPH, berieme ju; inak navrchu súčet s rovnakou DPH nevieme spoľahlivo)
    total_net = sum(float(item['price']) * float(item['quantity']) for item in items)
    # Pozn.: total_vat (s DPH) môže byť zložené – pre jednoduchosť odhadneme z položiek, ak majú dph
    total_gross = sum(
        float(item['price']) * (1 + float(item.get('dph', 0)) / 100.0) * float(item['quantity'])
        for item in items
    )

    order_number = f"B2B-{login_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Príprava lookupu produktov pre doplnenie dph/kategórie/mj/typ/váha
    eans = [i['ean'] for i in items if i.get('ean')]
    product_rows = []
    if eans:
        placeholders = ','.join(['%s'] * len(eans))
        product_rows = db_connector.execute_query(
            f"SELECT ean, dph, predajna_kategoria, vaha_balenia_g, typ_polozky, mj, nazov_vyrobku FROM produkty WHERE ean IN ({placeholders})",
            tuple(eans),
        )
    prod_map = {r['ean']: r for r in product_rows}

    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        # INSERT do hlavičky – schéma má tieto polia; 'stav' defaultuje na 'Prijatá'
        cursor.execute(
            (
                """
                INSERT INTO b2b_objednavky (
                  cislo_objednavky, zakaznik_id, nazov_firmy, adresa,
                  pozadovany_datum_dodania, poznamka, celkova_suma_s_dph
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
            ),
            (
                order_number,
                login_id,
                final_customer_name,
                customer_info.get('adresa', ''),
                delivery_date,
                note,
                total_gross,
            ),
        )
        order_id = cursor.lastrowid

        # Položky – mapovanie na reálne názvy stĺpcov v DB
        items_to_insert = []
        for i in items:
            ean = i.get('ean')
            pm = prod_map.get(ean, {})
            items_to_insert.append(
                (
                    order_id,
                    ean,
                    i.get('name') or pm.get('nazov_vyrobku') or '',
                    float(i.get('quantity', 0)),
                    pm.get('mj') or i.get('unit', 'kg'),
                    float(i.get('dph', pm.get('dph') or 0) or 0),
                    pm.get('predajna_kategoria'),
                    pm.get('vaha_balenia_g'),
                    pm.get('typ_polozky'),
                    float(i.get('price', 0)),  # cena_bez_dph
                    delivery_date,
                )
            )

        cursor.executemany(
            (
                """
                INSERT INTO b2b_objednavky_polozky (
                  objednavka_id, ean_produktu, nazov_vyrobku, mnozstvo, mj, dph,
                  predajna_kategoria, vaha_balenia_g, typ_polozky, cena_bez_dph, pozadovany_datum_dodania
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
            ),
            items_to_insert,
        )

        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        print("!!! KRITICKÁ CHYBA pri ukladaní objednávky do DB !!!")
        traceback.print_exc()
        return {"error": "Objednávku sa nepodarilo uložiť do databázy."}
    finally:
        if conn and conn.is_connected():
            conn.close()

    order_data_for_docs = {
        'order_number': order_number,
        'deliveryDate': delivery_date,
        'note': note,
        'customerName': final_customer_name,
        'userId': login_id,
        'customerEmail': customer_email,
        'items': items,
        'totalNet': float(total_net),
        'totalVat': float(total_gross),
        'order_date': datetime.now().strftime('%d.%m.%Y'),
        'customerLoginId': login_id,
        'customerAddress': customer_info.get('adresa', 'Neuvedená'),
        'customerIco': 'Neuvedené',
        'customerDic': 'Neuvedené',
        'customerIcDph': 'Neuvedené',
    }

    try:
        pdf_content, csv_content = pdf_generator.create_order_files(order_data_for_docs)
    except Exception:
        print(
            f"--- VAROVANIE: Objednávka {order_number} bola uložená, ale dokumenty sa nepodarilo vygenerovať. E-maily nebudú odoslané. ---"
        )
        print(traceback.format_exc())
        return {
            "status": "success",
            "message": f"Objednávka {order_number} bola prijatá, ale pri generovaní dokumentov nastala chyba.",
        }

    return {
        "status": "success",
        "message": f"Vaša objednávka {order_number} bola úspešne prijatá.",
        "order_data": order_data_for_docs,
        "pdf_attachment": pdf_content,
        "csv_attachment": csv_content,
    }


# =================================================================
# === OBNOVA HESLA ===
# =================================================================

def request_password_reset(data):
    email = data.get('email')
    if not email:
        return {"error": "E-mail je povinný údaj."}
    user = db_connector.execute_query("SELECT id FROM b2b_zakaznici WHERE email = %s", (email,), fetch='one')
    if not user:
        return {"message": "Ak účet s týmto e-mailom existuje, odkaz na obnovu hesla bol odoslaný."}
    token = secrets.token_urlsafe(32)
    token_expiry = datetime.now() + timedelta(minutes=15)
    db_connector.execute_query(
        "UPDATE b2b_zakaznici SET reset_token = %s, reset_token_expiry = %s WHERE id = %s",
        (token, token_expiry, user['id']),
        fetch='none',
    )
    reset_link = f"http://127.0.0.1:5000/b2b?action=resetPassword&token={token}"

    try:
        notification_handler.send_password_reset_email(email, reset_link)
    except Exception:
        print("--- VAROVANIE: Žiadosť o reset hesla bola zaznamenaná, ale e-mail sa nepodarilo odoslať. ---")
        print(traceback.format_exc())

    return {"message": "Ak účet s týmto e-mailom existuje, odkaz na obnovu hesla bol odoslaný."}


def perform_password_reset(data):
    token, new_password = data.get('token'), data.get('password')
    if not token or not new_password:
        return {"error": "Token a nové heslo sú povinné."}
    user = db_connector.execute_query(
        "SELECT id, reset_token_expiry FROM b2b_zakaznici WHERE reset_token = %s",
        (token,),
        fetch='one',
    )
    if (not user) or (user['reset_token_expiry'] < datetime.now()):
        return {"error": "Odkaz na obnovu hesla je neplatný alebo jeho platnosť vypršala."}
    salt_hex, hash_hex = generate_password_hash(new_password)
    db_connector.execute_query(
        "UPDATE b2b_zakaznici SET password_hash_hex = %s, password_salt_hex = %s, reset_token = NULL, reset_token_expiry = NULL WHERE id = %s",
        (hash_hex, salt_hex, user['id']),
        fetch='none',
    )
    return {"message": "Heslo bolo úspešne zmenené. Môžete sa prihlásiť."}


# =================================================================
# === ADMINISTRÁCIA B2B (pre interný systém) ===
# =================================================================

def get_pending_b2b_registrations():
    return db_connector.execute_query(
        (
            """
            SELECT id, nazov_firmy, adresa, adresa_dorucenia, email, telefon, datum_registracie
            FROM b2b_zakaznici
            WHERE je_schvaleny = 0 AND typ = 'B2B'
            ORDER BY datum_registracie DESC
            """
        )
    )


def approve_b2b_registration(data):
    reg_id, customer_id = data.get('id'), data.get('customerId')
    if not reg_id or not customer_id:
        return {"error": "Chýba ID registrácie alebo ID odberateľa."}
    if db_connector.execute_query(
        "SELECT id FROM b2b_zakaznici WHERE zakaznik_id = %s",
        (customer_id,),
        fetch='one',
    ):
        return {"error": f"Zákaznícke číslo '{customer_id}' už je pridelené."}
    db_connector.execute_query(
        "UPDATE b2b_zakaznici SET je_schvaleny = 1, zakaznik_id = %s WHERE id = %s",
        (customer_id, reg_id),
        fetch='none',
    )
    customer_info = db_connector.execute_query(
        "SELECT email, nazov_firmy FROM b2b_zakaznici WHERE id = %s",
        (reg_id,),
        fetch='one',
    )
    if customer_info:
        try:
            notification_handler.send_approval_email(
                customer_info['email'], customer_info['nazov_firmy'], customer_id
            )
        except Exception:
            print(
                f"--- VAROVANIE: Registrácia pre {customer_info['nazov_firmy']} bola schválená, ale e-mail sa nepodarilo odoslať. ---"
            )
            print(traceback.format_exc())
    return {"message": "Registrácia bola schválená a notifikácia odoslaná."}


def reject_b2b_registration(data):
    rows_deleted = db_connector.execute_query(
        "DELETE FROM b2b_zakaznici WHERE id = %s AND je_schvaleny = 0",
        (data.get('id'),),
        fetch='none',
    )
    return {"message": "Registrácia bola odmietnutá."} if rows_deleted > 0 else {"error": "Registráciu sa nepodarilo nájsť."}


def get_customers_and_pricelists():
    customers_q = (
        """
        SELECT z.id, z.zakaznik_id, z.nazov_firmy, z.email, z.telefon, z.adresa, z.adresa_dorucenia,
               GROUP_CONCAT(zc.cennik_id) AS cennik_ids
        FROM b2b_zakaznici z
        LEFT JOIN b2b_zakaznik_cennik zc ON z.zakaznik_id = zc.zakaznik_id
        WHERE z.je_admin = 0 AND z.typ = 'B2B'
        GROUP BY z.id
        """
    )
    pricelists_q = "SELECT id, nazov_cennika FROM b2b_cenniky ORDER BY nazov_cennika"
    return {
        "customers": db_connector.execute_query(customers_q),
        "pricelists": db_connector.execute_query(pricelists_q),
    }


def update_customer_details(data):
    customer_id = data.get('id')  # číselné id
    name = data.get('nazov_firmy')
    email = data.get('email')
    phone = data.get('telefon')
    pricelist_ids = list(dict.fromkeys(data.get('pricelist_ids', [])))  # deduplikuj
    address = data.get('adresa')
    delivery_address = data.get('adresa_dorucenia')

    # Mapuj na textové zakaznik_id
    zakaznik_id = _get_login_id_from_numeric(customer_id)
    if not zakaznik_id:
        return {"error": "Zákazník neexistuje."}

    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE b2b_zakaznici SET nazov_firmy = %s, email = %s, telefon = %s, adresa = %s, adresa_dorucenia = %s WHERE id = %s",
            (name, email, phone, address, delivery_address, customer_id),
        )
        # Zmaž mapovania podľa TEXTOVÉHO zakaznik_id
        cursor.execute(
            "DELETE FROM b2b_zakaznik_cennik WHERE zakaznik_id = %s",
            (zakaznik_id,),
        )
        if pricelist_ids:
            upsert_sql = (
                """
                INSERT INTO b2b_zakaznik_cennik (zakaznik_id, cennik_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE cennik_id = VALUES(cennik_id)
                """
            )
            cursor.executemany(
                upsert_sql, [(zakaznik_id, pid) for pid in pricelist_ids]
            )
        conn.commit()
        return {"message": "Údaje zákazníka boli aktualizované."}
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected():
            conn.close()


def get_pricelists_and_products():
    pricelists = db_connector.execute_query(
        "SELECT id, nazov_cennika FROM b2b_cenniky ORDER BY nazov_cennika"
    )
    # DB kompat: produktové položky – typ_polozky = 'produkt'
    products = db_connector.execute_query(
        (
            """
            SELECT ean, nazov_vyrobku AS name, predajna_kategoria, dph
            FROM produkty
            WHERE typ_polozky = 'produkt'
            ORDER BY predajna_kategoria, nazov_vyrobku
            """
        )
    )
    products_by_category = {}
    for p in products:
        category = p.get('predajna_kategoria') or 'Nezaradené'
        products_by_category.setdefault(category, []).append(p)
    return {"pricelists": pricelists, "productsByCategory": products_by_category}


def create_pricelist(data):
    name = data.get('name')
    if not name:
        return {"error": "Názov cenníka je povinný."}
    try:
        new_id = db_connector.execute_query(
            "INSERT INTO b2b_cenniky (nazov_cennika) VALUES (%s)",
            (name,),
            fetch='lastrowid',
        )
        return {"message": f"Cenník '{name}' bol vytvorený.", "newPricelist": {"id": new_id, "nazov_cennika": name}}
    except Exception as e:
        if 'UNIQUE' in str(e) or 'Duplicate entry' in str(e):
            return {"error": "Cenník s týmto názvom už existuje."}
        raise e


def get_pricelist_details(data):
    return {
        "items": db_connector.execute_query(
            "SELECT ean_produktu, cena FROM b2b_cennik_polozky WHERE cennik_id = %s",
            (data.get('id'),),
        )
    }


def update_pricelist(data):
    pricelist_id, items = data.get('id'), data.get('items', [])
    conn = db_connector.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM b2b_cennik_polozky WHERE cennik_id = %s",
            (pricelist_id,),
        )
        if items:
            items_to_insert = [
                (pricelist_id, i['ean'], i['price']) for i in items if i.get('price')
            ]
            if items_to_insert:
                cursor.executemany(
                    "INSERT INTO b2b_cennik_polozky (cennik_id, ean_produktu, cena) VALUES (%s, %s, %s)",
                    items_to_insert,
                )
        conn.commit()
        return {"message": "Cenník bol aktualizovaný."}
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected():
            conn.close()


def get_announcement():
    result = db_connector.execute_query(
        "SELECT hodnota FROM b2b_nastavenia WHERE kluc = 'oznam'",
        fetch='one',
    )
    return {"announcement": result['hodnota'] if result else ""}


def save_announcement(data):
    announcement_text = data.get('announcement', '')
    query = (
        "INSERT INTO b2b_nastavenia (kluc, hodnota) VALUES ('oznam', %s) "
        "ON DUPLICATE KEY UPDATE hodnota = VALUES(hodnota)"
    )
    db_connector.execute_query(query, (announcement_text,), fetch='none')
    return {"message": "Oznam bol úspešne aktualizovaný."}


def get_all_b2b_orders(filters):
    """Získa všetky B2B objednávky pre administrátorský prehľad, s možnosťou filtrovania."""
    start_date = filters.get('startDate') or '1970-01-01'
    end_date = filters.get('endDate') or '2999-12-31'

    query = (
        """
        SELECT o.*, z.nazov_firmy
        FROM b2b_objednavky o
        JOIN b2b_zakaznici z ON o.zakaznik_id = z.zakaznik_id
        WHERE DATE(o.pozadovany_datum_dodania) BETWEEN %s AND %s
        ORDER BY o.pozadovany_datum_dodania DESC, o.datum_objednavky DESC
        """
    )
    orders = db_connector.execute_query(query, (start_date, end_date))
    return {"orders": orders}


def get_b2b_order_details(order_id):
    """Získa detail jednej konkrétnej objednávky pre zobrazenie v administrácii."""
    if not order_id:
        return {"error": "Chýba ID objednávky."}

    order_q = (
        """
        SELECT o.*, z.nazov_firmy, z.zakaznik_id AS customerLoginId, z.adresa AS customerAddress
        FROM b2b_objednavky o
        JOIN b2b_zakaznici z ON o.zakaznik_id = z.zakaznik_id
        WHERE o.id = %s
        """
    )
    order = db_connector.execute_query(order_q, (order_id,), fetch='one')

    if not order:
        return {"error": "Objednávka nebola nájdená."}

    items_q = (
        "SELECT ean_produktu, nazov_vyrobku, mnozstvo, cena_bez_dph, mj, dph FROM b2b_objednavky_polozky WHERE objednavka_id = %s"
    )
    items = db_connector.execute_query(items_q, (order_id,))

    total_net = sum(float(i['cena_bez_dph'] or 0) * float(i['mnozstvo'] or 0) for i in items)

    order_data = {
        'id': order['id'],
        'order_number': order['cislo_objednavky'],
        'deliveryDate': order['pozadovany_datum_dodania'].strftime('%Y-%m-%d') if order.get('pozadovany_datum_dodania') else None,
        'note': order.get('poznamka'),
        'customerName': order['nazov_firmy'],
        'customerLoginId': order['customerLoginId'],
        'customerAddress': order['customerAddress'],
        'order_date': order['datum_objednavky'].strftime('%d.%m.%Y') if order.get('datum_objednavky') else None,
        'totalNet': float(total_net),
        'totalVat': float(order.get('celkova_suma_s_dph') or 0),
        'items': [
            {
                'ean': i['ean_produktu'],
                'name': i['nazov_vyrobku'],
                'quantity': float(i['mnozstvo'] or 0),
                'price': float(i['cena_bez_dph'] or 0),
                'unit': i.get('mj') or 'kg',
                'dph': float(i.get('dph') or 0),
                'item_note': None,
            }
            for i in items
        ],
    }
    return order_data


from db_connector import execute_query


def get_order_history(user_id):
    # ak príde číselné id, premapuj na textové zakaznik_id
    zak_login = _get_login_id_from_numeric(user_id)
    if not zak_login:
        zak_login = user_id  # skús priamo
    query = (
        """
        SELECT id, cislo_objednavky, datum_objednavky AS datum_vytvorenia, stav,
               celkova_suma_s_dph, poznamka
        FROM b2b_objednavky
        WHERE zakaznik_id = %s
        ORDER BY datum_objednavky DESC
        """
    )
    return execute_query(query, (zak_login,))
