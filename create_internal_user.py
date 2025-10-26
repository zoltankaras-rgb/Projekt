import getpass
import sys
import os
import traceback

# --- Začiatok Opravy ---
# Tento blok kódu zabezpečí, že skript nájde ostatné moduly (napr. db_connector),
# aj keď ho spúšťame samostatne z príkazového riadku.
# Pridá hlavný priečinok projektu do cesty, kde Python hľadá súbory.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- Koniec Opravy ---

import db_connector
import auth_handler

def create_user():
    """
    Interaktívny skript na vytvorenie nového interného používateľa v databáze.
    """
    print("--- Vytvorenie nového interného používateľa ---")
    
    try:
        username = input("Zadajte používateľské meno: ").strip()
        password = getpass.getpass("Zadajte heslo (nebude viditeľné): ").strip()
        password_confirm = getpass.getpass("Zopakujte heslo: ").strip()
        
        if not all([username, password]):
            print("\nCHYBA: Meno a heslo nesmú byť prázdne.")
            return

        if password != password_confirm:
            print("\nCHYBA: Heslá sa nezhodujú.")
            return

        print("Dostupné roly: vyroba, expedicia, kancelaria, admin")
        role = input("Zadajte rolu používateľa: ").strip().lower()
        if role not in ['vyroba', 'expedicia', 'kancelaria', 'admin']:
            print(f"\nCHYBA: Neplatná rola '{role}'.")
            return
            
        full_name = input("Zadajte celé meno používateľa (voliteľné): ").strip()

        # Overenie, či používateľ už neexistuje
        if db_connector.execute_query("SELECT id FROM internal_users WHERE username = %s", (username,), fetch='one'):
            print(f"\nCHYBA: Používateľ s menom '{username}' už existuje.")
            return
            
        # Vytvorenie hashu a saltu
        salt, hsh = auth_handler.generate_password_hash(password)
        
        # Vloženie do databázy
        params = (username, hsh, salt, role, full_name)
        db_connector.execute_query(
            "INSERT INTO internal_users (username, password_hash, password_salt, role, full_name) VALUES (%s, %s, %s, %s, %s)",
            params,
            fetch='none'
        )
        
        print(f"\nÚSPECH: Používateľ '{username}' s rolou '{role}' bol úspešne vytvorený.")

    except Exception as e:
        print(f"\n!!! NEOČAKÁVANÁ CHYBA PRI VYTVÁRANÍ POUŽÍVATEĽA !!!")
        print(traceback.format_exc())

if __name__ == '__main__':
    create_user()

