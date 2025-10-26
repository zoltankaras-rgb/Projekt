import db_connector
from datetime import datetime
from auth_handler import generate_password_hash, verify_password
import json
import random
import string
import traceback
import math
import pdf_generator
import notification_handler

# =================================================================
# === HANDLER PRE B2C PORTÁL (KOMPLETNÁ VERZIA) ===
# =================================================================

def process_b2c_registration(data):
    """Spracuje novú B2C registráciu a odošle notifikácie."""
    try:
        required = ['name', 'email', 'phone', 'address', 'password']
        if not all(field in data and data[field] for field in required):
            return {"error": "Chyba: Všetky polia sú povinné."}
        
        email = data['email']
        if db_connector.execute_query("SELECT id FROM b2b_zakaznici WHERE email = %s AND typ = 'B2C'", (email,), fetch='one'):
            return {"error": "Zákazník s týmto e-mailom už existuje v našom systéme."}

        salt, hsh = generate_password_hash(data['password'])
        zakaznik_id = "".join(random.choices(string.digits, k=12))
        
        params = (
            'B2C', data['name'], email, data['phone'], data['address'],
            data.get('delivery_address', data['address']), hsh, salt,
            data.get('gdpr', False), zakaznik_id,
        )
        
        db_connector.execute_query(
            "INSERT INTO b2b_zakaznici (typ, nazov_firmy, email, telefon, adresa, adresa_dorucenia, heslo_hash, heslo_salt, gdpr_suhlas, zakaznik_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            params, fetch='none'
        )
        
        notification_handler.send_b2c_registration_email(email, data['name'])
        notification_handler.send_b2c_new_registration_admin_alert(data)
        
        return {"message": "Registrácia prebehla úspešne. Vitajte! Teraz sa môžete prihlásiť."}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Nastala interná chyba servera: {e}"}

def process_b2c_login(data):
    """Spracuje prihlásenie B2C zákazníka a načíta vernostné body."""
    email, password = data.get('email'), data.get('password')
    if not email or not password:
        return {"error": "Musíte zadať e-mail aj heslo."}

    query = "SELECT id, nazov_firmy, email, heslo_hash, heslo_salt, typ, vernostne_body FROM b2b_zakaznici WHERE email = %s AND typ = 'B2C'"
    user = db_connector.execute_query(query, (email,), fetch='one')

    if not user or not verify_password(password, user['heslo_salt'], user['heslo_hash']):
        return {"error": "Nesprávny e-mail alebo heslo."}

    user_session_data = {
        'id': user['id'],
        'name': user['nazov_firmy'],
        'email': user['email'],
        'typ': user['typ'],
        'points': user.get('vernostne_body', 0) or 0
    }
    return {"message": "Prihlásenie úspešné.", "user": user_session_data}

def get_public_pricelist():
    """Získa verejný cenník s akciami a popisom produktu."""
    query = """
        SELECT 
            p.ean, p.nazov_vyrobku, p.predajna_kategoria, p.popis, p.mj, p.dph,
            c.cena_bez_dph, c.je_v_akcii, c.akciova_cena_bez_dph
        FROM produkty p
        JOIN b2c_cennik_polozky c ON p.ean = c.ean_produktu
        ORDER BY p.predajna_kategoria, p.nazov_vyrobku
    """
    products = db_connector.execute_query(query)
    products_by_category = {}
    products_by_category['AKCIA TÝŽĎŇA'] = []

    for p in products:
        dph_sadzba = float(p.get('dph') or 0.0)
        cena_bez_dph = float(p.get('cena_bez_dph') or 0.0)
        p['cena_s_dph'] = cena_bez_dph * (1 + dph_sadzba / 100)
        
        if p.get('je_v_akcii') and p.get('akciova_cena_bez_dph') is not None:
            akciova_cena_bez_dph = float(p.get('akciova_cena_bez_dph'))
            p['akciova_cena_s_dph'] = akciova_cena_bez_dph * (1 + dph_sadzba / 100)
            products_by_category['AKCIA TÝŽĎŇA'].append(p)
        else:
            category = p.get('predajna_kategoria') or 'Nezaradené'
            if category not in products_by_category:
                products_by_category[category] = []
            products_by_category[category].append(p)
    
    if not products_by_category['AKCIA TÝŽĎŇA']:
        del products_by_category['AKCIA TÝŽĎŇA']
        
    return {"products": products_by_category}

def submit_b2c_order(user_id, data):
    """Spracuje B2C objednávku, uloží ju, vygeneruje PDF a vráti dáta pre email."""
    conn = None
    cursor = None
    try:
        items, delivery_date, note = data.get('items'), data.get('deliveryDate'), data.get('note')
        if not all([user_id, items, delivery_date]):
            return {"error": "Chýbajú povinné údaje pre spracovanie objednávky."}

        eans = [item['ean'] for item in items]
        if not eans: return {"error": "Objednávka neobsahuje žiadne položky."}
        
        placeholders = ','.join(['%s'] * len(eans))
        price_query = f"SELECT p.ean, p.dph, c.cena_bez_dph, c.je_v_akcii, c.akciova_cena_bez_dph FROM produkty p JOIN b2c_cennik_polozky c ON p.ean = c.ean_produktu WHERE p.ean IN ({placeholders})"
        db_prices = db_connector.execute_query(price_query, tuple(eans))
        price_map = {p['ean']: p for p in db_prices}

        total_price_s_dph, total_price_bez_dph = 0, 0
        items_with_details = []

        for item in items:
            db_price_info = price_map.get(item['ean'])
            if not db_price_info: continue
            dph_sadzba = float(db_price_info.get('dph', 0)) / 100
            cena_bez_dph = float(db_price_info.get('akciova_cena_bez_dph')) if db_price_info.get('je_v_akcii') and db_price_info.get('akciova_cena_bez_dph') is not None else float(db_price_info.get('cena_bez_dph', 0))
            cena_s_dph = cena_bez_dph * (1 + dph_sadzba)
            quantity = float(item['quantity'])
            total_price_bez_dph += cena_bez_dph * quantity
            total_price_s_dph += cena_s_dph * quantity
            items_with_details.append({**item, 'price_s_dph': cena_s_dph, 'price_bez_dph': cena_bez_dph, 'dph_percent': dph_sadzba * 100})

        total_dph = total_price_s_dph - total_price_bez_dph
        order_number = f"B2C-{user_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        conn = db_connector.get_connection()
        cursor = conn.cursor(dictionary=True)
        reward_note = None
        claimed_reward = db_connector.execute_query("SELECT id, nazov_odmeny FROM b2c_uplatnene_odmeny WHERE zakaznik_id = %s AND stav_vybavenia = 'Čaká na vybavenie' LIMIT 1", (user_id,), fetch='one')
        if claimed_reward: reward_note = claimed_reward['nazov_odmeny']
        params = (user_id, order_number, delivery_date, note, total_price_bez_dph, total_dph, total_price_s_dph, json.dumps(items_with_details), reward_note)
        cursor.execute("INSERT INTO b2c_objednavky (zakaznik_id, cislo_objednavky, pozadovany_datum_dodania, poznamka, predpokladana_suma_bez_dph, predpokladana_dph, predpokladana_suma_s_dph, polozky, uplatnena_odmena_poznamka) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", params)
        order_id = cursor.lastrowid
        if claimed_reward: cursor.execute("UPDATE b2c_uplatnene_odmeny SET stav_vybavenia = 'Vybavené', objednavka_id = %s WHERE id = %s", (order_id, claimed_reward['id']))
        conn.commit()
        
        customer = db_connector.execute_query("SELECT * FROM b2b_zakaznici WHERE id=%s", (user_id,), 'one')
        if not customer: return {"error": "Zákazník pre objednávku nebol nájdený."}
        
        # --- START CHANGE: Pridanie odmeny do dát pre PDF ---
        order_data_for_docs = {
            'order_number': order_number, 'deliveryDate': delivery_date, 'note': note,
            'customerName': customer.get('nazov_firmy'), 'customerLoginId': customer.get('zakaznik_id', 'N/A'),
            'customerAddress': customer.get('adresa_dorucenia', customer.get('adresa', 'Neuvedená')),
            'customerEmail': customer.get('email'),
            'items': items_with_details,
            'totalNet': total_price_bez_dph, 'totalVat': total_price_s_dph,
            'order_date': datetime.now().strftime('%d.%m.%Y'),
            'uplatnena_odmena_poznamka': reward_note
        }
        # --- END CHANGE ---

        pdf_content, _ = pdf_generator.create_order_files(order_data_for_docs)

        return {
            "message": "Vaša objednávka bola úspešne prijatá. Potvrdenie sme Vám zaslali na e-mail.",
            "order_data": order_data_for_docs,
            "pdf_attachment": pdf_content
        }

    except Exception as e:
        if conn: conn.rollback()
        traceback.print_exc()
        raise e
    finally:
        if conn and conn.is_connected():
            if cursor: cursor.close()
            conn.close()

def get_order_history(user_id):
    """Získa históriu objednávok pre B2C zákazníka."""
    if not user_id: return {"error": "Chýba ID zákazníka."}
    query = "SELECT * FROM b2c_objednavky WHERE zakaznik_id = %s ORDER BY datum_objednavky DESC"
    orders = db_connector.execute_query(query, (user_id,))
    return {"orders": orders}

def get_available_rewards():
    """Získa zoznam všetkých aktívnych vernostných odmien."""
    query = "SELECT id, nazov_odmeny, potrebne_body FROM b2c_vernostne_odmeny WHERE je_aktivna = TRUE ORDER BY potrebne_body ASC"
    return {"rewards": db_connector.execute_query(query)}

def claim_reward(user_id, reward_id):
    """Spracuje uplatnenie odmeny zákazníkom."""
    if not all([user_id, reward_id]): return {"error": "Chýbajú povinné údaje."}

    reward_query = "SELECT nazov_odmeny, potrebne_body FROM b2c_vernostne_odmeny WHERE id = %s AND je_aktivna = TRUE"
    reward = db_connector.execute_query(reward_query, (reward_id,), fetch='one')
    if not reward: return {"error": "Požadovaná odmena neexistuje alebo nie je aktívna."}

    points_needed, reward_name = reward['potrebne_body'], reward['nazov_odmeny']

    conn = db_connector.get_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT vernostne_body FROM b2b_zakaznici WHERE id = %s FOR UPDATE", (user_id,))
        customer = cursor.fetchone()

        if not customer: raise Exception("Zákazník nebol nájdený.")
        
        current_points = customer.get('vernostne_body') or 0
        if current_points < points_needed: return {"error": "Nemáte dostatok bodov na uplatnenie tejto odmeny."}

        new_points = current_points - points_needed
        cursor.execute("UPDATE b2b_zakaznici SET vernostne_body = %s WHERE id = %s", (new_points, user_id))
        
        cursor.execute(
            "INSERT INTO b2c_uplatnene_odmeny (zakaznik_id, odmena_id, nazov_odmeny, pouzite_body) VALUES (%s, %s, %s, %s)",
            (user_id, reward_id, reward_name, points_needed)
        )
        conn.commit()
        return {"message": f"Odmena '{reward_name}' bola úspešne uplatnená! Bude priložená k nasledujúcej objednávke.", "new_points": new_points}
    except Exception as e:
        if conn: conn.rollback()
        raise e
    finally:
        if conn and conn.is_connected():
            if cursor: cursor.close()
            conn.close()

