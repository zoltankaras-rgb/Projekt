import db_connector
import b2b_handler  # Potrebujeme pre hashovanie hesiel
from datetime import datetime
import traceback # <-- CHÝBAJÚCI IMPORT PRIDANÝ

def clear_database():
    """
    Vymaže dáta zo všetkých tabuliek, aby sme zaistili čistý štart.
    Postupuje v správnom poradí, aby sa predišlo problémom s cudzími kľúčmi.
    """
    print("1. Čistím databázu od starých dát...")
    
    # Dočasne vypneme kontrolu cudzích kľúčov, aby sme mohli mazať v ľubovoľnom poradí
    db_connector.execute_query("SET FOREIGN_KEY_CHECKS = 0;", fetch='none')
    
    tables_to_clear = [
        'b2b_objednavky_polozky', 'b2b_objednavky', 'b2b_zakaznik_cennik', 
        'b2b_cennik_polozky', 'b2b_cenniky', 'b2b_zakaznici',
        'zaznamy_vyroba', 'zaznamy_prijem', 'vydajky', 'skody',
        'recepty', 'produkty', 'sklad', 'inventurne_rozdiely', 'haccp_dokumenty'
    ]
    
    for table in tables_to_clear:
        try:
            db_connector.execute_query(f"TRUNCATE TABLE {table};", fetch='none')
            print(f"   - Tabuľka '{table}' bola vyčistená.")
        except Exception as e:
            print(f"   - Varovanie: Nepodarilo sa vyčistiť tabuľku '{table}'. Možno neexistuje. Chyba: {e}")
            
    # Znovu zapneme kontrolu cudzích kľúčov
    db_connector.execute_query("SET FOREIGN_KEY_CHECKS = 1;", fetch='none')
    print("-> Databáza je pripravená na nové dáta.\n")


def seed_sklad():
    """Naplní tabuľku `sklad` testovacími surovinami."""
    print("2. Vkladám testovacie suroviny do skladu...")
    suroviny = [
        ('Bravčové pliecko', 'Mäso', 150.5, 4.50, 100.0),
        ('Bravčový bok', 'Mäso', 80.2, 3.80, 50.0),
        ('Hovädzie predné', 'Mäso', 60.0, 6.20, 40.0),
        ('Soľ', 'Koreniny', 500.0, 0.80, 100.0),
        ('Čierne korenie mleté', 'Koreniny', 25.0, 12.50, 10.0),
        ('Paprika sladká', 'Koreniny', 30.0, 9.50, 15.0),
        ('Cesnak sušený', 'Koreniny', 15.0, 11.00, 5.0),
        ('Baranie črevá 22/24', 'Obaly - Črevá', 100.0, 25.00, 20.0),
        ('Umelé črevá 50mm', 'Obaly - Črevá', 250.0, 5.00, 50.0),
        ('Voda', 'Pomocný material', 9999.0, 0.00, 0.0),
        ('Ľad', 'Pomocný material', 9999.0, 0.00, 0.0)
    ]
    query = "INSERT INTO sklad (nazov, typ, mnozstvo, nakupna_cena, min_zasoba) VALUES (%s, %s, %s, %s, %s)"
    db_connector.execute_query(query, suroviny, fetch='none', multi=True)
    print(f"-> Vložených {len(suroviny)} surovín.\n")

def seed_produkty():
    """Naplní tabuľku `produkty` testovacími výrobkami."""
    print("3. Vkladám testovacie produkty do katalógu...")
    produkty = [
        # EAN, Názov, Typ, Kategória receptu, Predajná kategória, DPH, MJ, Min. zásoba kg, Min. zásoba ks, Aktuálny sklad, Dávka, Váha balenia, Zdrojový EAN
        ('8580001111111', 'Tradičná klobása', 'VÝROBOK', 'Mäkké salámy', 'Výrobky', 19.00, 'kg', 50.0, 0, 85.5, 100.0, None, None),
        ('8580001111128', 'Papriková saláma', 'VÝROBOK', 'Mäkké salámy', 'Výrobky', 19.00, 'kg', 40.0, 0, 65.0, 80.0, None, None),
        ('8580001111135', 'Papriková saláma krájaná 100g', 'VYROBOK_KRAJANY', 'Mäkké salámy', 'Výrobky', 19.00, 'ks', 0, 100, 120, None, 100, '8580001111128')
    ]
    query = """
        INSERT INTO produkty 
        (ean, nazov_vyrobku, typ_polozky, kategoria_pre_recepty, predajna_kategoria, dph, mj, minimalna_zasoba_kg, minimalna_zasoba_ks, aktualny_sklad_finalny_kg, vyrobna_davka_kg, vaha_balenia_g, zdrojovy_ean) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    db_connector.execute_query(query, produkty, fetch='none', multi=True)
    print(f"-> Vložených {len(produkty)} produktov.\n")

def seed_recepty():
    """Naplní tabuľku `recepty` testovacími receptúrami."""
    print("4. Vkladám testovacie receptúry...")
    recepty = [
        ('Tradičná klobása', 'Bravčové pliecko', 60.0),
        ('Tradičná klobása', 'Bravčový bok', 40.0),
        ('Tradičná klobása', 'Soľ', 1.8),
        ('Tradičná klobása', 'Čierne korenie mleté', 0.4),
        ('Tradičná klobása', 'Paprika sladká', 0.5),
        ('Tradičná klobása', 'Cesnak sušený', 0.3),
        ('Tradičná klobása', 'Baranie črevá 22/24', 5.0),
        ('Papriková saláma', 'Bravčové pliecko', 70.0),
        ('Papriková saláma', 'Hovädzie predné', 30.0),
        ('Papriková saláma', 'Soľ', 2.0),
        ('Papriková saláma', 'Paprika sladká', 1.5),
        ('Papriková saláma', 'Umelé črevá 50mm', 2.0),
    ]
    query = "INSERT INTO recepty (nazov_vyrobku, nazov_suroviny, mnozstvo_na_davku_kg) VALUES (%s, %s, %s)"
    db_connector.execute_query(query, recepty, fetch='none', multi=True)
    print(f"-> Vložených {len(recepty)} riadkov receptúr.\n")

def seed_b2b():
    """Vytvorí testovacieho B2B zákazníka, admina a cenník."""
    print("5. Vytváram testovacie B2B dáta...")
    
    # Zákazník
    user_login = '123456'
    user_pass = 'test'
    salt_user, hsh_user = b2b_handler.generate_password_hash(user_pass)
    customer_id = db_connector.execute_query(
        "INSERT INTO b2b_zakaznici (zakaznik_id, nazov_firmy, email, telefon, heslo_hash, heslo_salt, je_schvaleny, je_admin) VALUES (%s, %s, %s, %s, %s, %s, 1, 0)",
        (user_login, 'Test Gastro s.r.o.', 'test@gastro.sk', '0901123456', hsh_user, salt_user), fetch='lastrowid'
    )
    print(f"   -> Zákazník 'Test Gastro s.r.o.' vytvorený. Login: {user_login}, Heslo: {user_pass}")

    # Admin
    admin_login = 'admin'
    admin_pass = 'admin'
    salt_admin, hsh_admin = b2b_handler.generate_password_hash(admin_pass)
    db_connector.execute_query(
        "INSERT INTO b2b_zakaznici (zakaznik_id, nazov_firmy, email, telefon, heslo_hash, heslo_salt, je_schvaleny, je_admin) VALUES (%s, %s, %s, %s, %s, %s, 1, 1)",
        (admin_login, 'Admin MIK', 'admin@miksro.sk', '0900000000', hsh_admin, salt_admin), fetch='none'
    )
    print(f"   -> Administrátor vytvorený. Login: {admin_login}, Heslo: {admin_pass}")

    # Cenník
    cennik_id = db_connector.execute_query("INSERT INTO b2b_cenniky (nazov_cennika) VALUES ('Standardny Gastro Cennik')", fetch='lastrowid')
    db_connector.execute_query("INSERT INTO b2b_zakaznik_cennik (zakaznik_id, cennik_id) VALUES (%s, %s)", (customer_id, cennik_id), fetch='none')
    
    polozky_cennika = [
        (cennik_id, '8580001111111', 12.50),
        (cennik_id, '8580001111128', 10.80),
        (cennik_id, '8580001111135', 1.50) # Cena za 100g balenie
    ]
    db_connector.execute_query("INSERT INTO b2b_cennik_polozky (cennik_id, ean_produktu, cena) VALUES (%s, %s, %s)", polozky_cennika, fetch='none', multi=True)
    print(f"   -> Vytvorený cenník s {len(polozky_cennika)} položkami a priradený zákazníkovi.\n")

def main():
    """Hlavná funkcia, ktorá spustí všetky kroky naplnenia databázy."""
    try:
        clear_database()
        seed_sklad()
        seed_produkty()
        seed_recepty()
        seed_b2b()
        print("================================================")
        print("=== DATABÁZA BOLA ÚSPEŠNE NAPLNENÁ DÁTAMI! ===")
        print("================================================")
    except Exception as e:
        print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!! CHYBA pri napĺňaní databázy: {e}")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        traceback.print_exc()

if __name__ == '__main__':
    main()

