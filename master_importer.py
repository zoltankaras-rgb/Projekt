import pandas as pd
import mysql.connector
import sys

# --- HLAVNÁ KONFIGURÁCIA ---
# V tejto sekcii si nastavíte všetko potrebné.

# 1. Zadajte presný názov vášho Excel súboru.
EXCEL_SUBOR = 'Vyrobny System v20.7.7.xlsx'

# 2. Nastavenia pripojenia k vašej MySQL databáze.
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'karas',   # <-- HESLO JE ULOŽENÉ
    'database': 'vyrobny_system'
}

# 3. Definícia importovacích úloh.
IMPORT_TASKS = [
    {
        'sheet_name': 'Sklad',
        'db_table': 'sklad',
        'column_mapping': {
            'Názov Suroviny': 'nazov',
            'Typ Suroviny': 'typ',
            'Množstvo na sklade (kg)': 'mnozstvo',
            'Priemerná nákupná cena (€/kg)': 'nakupna_cena',
            'Minimálna zásoba (kg)': 'min_zasoba'
        }
    },
    {
        'sheet_name': 'KatalógProduktov',
        'db_table': 'katalog_produktov',
        'column_mapping': {
            'EAN kód': 'ean',
            'Názov Výrobku': 'nazov_vyrobku',
            'MJ': 'mj',
            'Kategória pre Recepty': 'kategoria_pre_recepty',
            'Typ Produktu': 'typ_produktu',
            'Váha Balenia (g)': 'vaha_balenia_g',
            'Zdrojový EAN': 'zdrojovy_ean'
        }
    },
    {
        'sheet_name': 'Recepty*',
        'db_table': 'recepty',
        'column_mapping': {
            'Názov výrobku': 'nazov_vyrobku',
            'Názov Suroviny': 'nazov_suroviny',
            'Množstvo na dávku (kg)': 'mnozstvo_na_davku_kg'
        }
    },
    {
        'sheet_name': 'Záznamy o Výrobe',
        'db_table': 'zaznamy_vyroba',
        'column_mapping': {
            'ID Dávky': 'id_davky',
            'Stav': 'stav',
            'Dátum Výroby': 'datum_vyroby',
            'Názov Výrobku': 'nazov_vyrobku',
            'Plánované Množstvo (kg)': 'planovane_mnozstvo_kg',
            'Reálne Množstvo (kg)': 'realne_mnozstvo_kg',
            'Reálne Množstvo (ks)': 'realne_mnozstvo_ks',
            'Celková Cena Surovín (€)': 'celkova_cena_surovin',
            'Dátum Spustenia': 'datum_spustenia',
            'Dátum Ukončenia': 'datum_ukoncenia',
            'Zmenený Recept': 'zmeneny_recept',
            'Detaily Zmeny': 'detaily_zmeny'
        }
    },
]


# --- SAMOTNÝ SKRIPT ---

def process_task(task, xls, conn):
    """Spracuje jednu importovaciu úlohu s finálnou opravou."""
    sheet_name = task['sheet_name']
    db_table = task['db_table']
    column_mapping = task['column_mapping']
    
    print("-" * 50)
    
    try:
        df = None
        if sheet_name.endswith('*'):
            prefix = sheet_name[:-1]
            matching_sheets = [s for s in xls.sheet_names if s.startswith(prefix)]
            if not matching_sheets:
                print(f"Preskakujem: Nenašli sa žiadne hárky začínajúce na '{prefix}'.")
                return
            
            print(f"Načítavam a spájam hárky: {', '.join(matching_sheets)}...")
            df_list = []
            for s in matching_sheets:
                temp_df = pd.read_excel(xls, sheet_name=s)
                temp_df = temp_df.loc[:, temp_df.columns.notna()]
                df_list.append(temp_df)

            if not df_list:
                 print("Žiadne dáta na spojenie.")
                 return

            df = pd.concat(df_list, ignore_index=True)
        else:
            print(f"Načítavam hárok '{sheet_name}'...")
            df = pd.read_excel(xls, sheet_name=sheet_name)
            df = df.loc[:, df.columns.notna()]

        # --- OPRAVA EAN KÓDOV ---
        # Explicitne konvertujeme stĺpce s EAN kódmi na text (string),
        # aby sa predišlo ich načítaniu ako desatinné číslo (napr. 232401.0).
        if 'EAN kód' in df.columns:
            # .astype(str) skonvertuje všetko na text
            # .str.replace() odstráni '.0' na konci, ak tam je
            df['EAN kód'] = df['EAN kód'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        if 'Zdrojový EAN' in df.columns:
            # To isté pre zdrojové EANy
            df['Zdrojový EAN'] = df['Zdrojový EAN'].astype(str).str.replace(r'\.0$', '', regex=True)
        # --- KONIEC OPRAVY ---

        expected_excel_columns = list(column_mapping.keys())
        existing_columns_in_excel = [col for col in expected_excel_columns if col in df.columns]
        
        df_cleaned = df[existing_columns_in_excel]
        df_renamed = df_cleaned.rename(columns=column_mapping)

        # --- KONTROLA A ODSTRÁNENIE DUPLICÍT PRE ZÁZNAMY O VÝROBE ---
        if db_table == 'zaznamy_vyroba' and 'id_davky' in df_renamed.columns:
            original_rows = len(df_renamed)
            # Odstráni duplikáty na základe stĺpca 'id_davky', ponechá prvý výskyt
            df_renamed.drop_duplicates(subset=['id_davky'], keep='first', inplace=True)
            dropped_rows = original_rows - len(df_renamed)
            if dropped_rows > 0:
                print(f"UPOZORNENIE: Odstránených {dropped_rows} duplicitných záznamov v '{sheet_name}' na základe 'ID Dávky'.")
        
        if df_renamed.empty:
            print("Žiadne platné dáta po očistení. Prechádzam na ďalšiu úlohu.")
            return
        df_final = df_renamed.dropna(subset=[list(df_renamed.columns)[0]])
        
        print(f"Nájdených {len(df_final)} platných riadkov na import do tabuľky '{db_table}'.")
        
        if len(df_final) == 0:
            print("Žiadne dáta na import. Prechádzam na ďalšiu úlohu.")
            return

        cursor = conn.cursor()
        print(f"Mažem staré dáta z tabuľky '{db_table}'...")
        cursor.execute(f"TRUNCATE TABLE {db_table}")

        stlpce_str = ', '.join(f"`{col}`" for col in df_final.columns)
        placeholders = ', '.join(['%s'] * len(df_final.columns))
        sql_prikaz = f"INSERT INTO `{db_table}` ({stlpce_str}) VALUES ({placeholders})"
        
        # Agresívne nahradenie všetkých NaN hodnôt za None
        df_for_db = df_final.astype(object).where(pd.notnull(df_final), None)
        data_na_vlozenie = [tuple(row) for row in df_for_db.itertuples(index=False)]
        
        print("Vkladám nové dáta...")
        cursor.executemany(sql_prikaz, data_na_vlozenie)
        conn.commit()
        
        print(f"ÚSPECH: {cursor.rowcount} riadkov bolo úspešne naimportovaných do '{db_table}'.")

    except Exception as e:
        print(f"!!! CHYBA pri spracovaní '{sheet_name}': {e}")
        if conn: conn.rollback()

def run_migration():
    """Hlavná funkcia, ktorá prejde všetky úlohy a spustí import."""
    try:
        xls = pd.ExcelFile(EXCEL_SUBOR)
    except FileNotFoundError:
        print(f"\nCHYBA: Súbor '{EXCEL_SUBOR}' nebol nájdený!")
        print("Uistite sa, že súbor je v rovnakom priečinku ako tento skript.")
        sys.exit(1)

    conn = None
    try:
        print("Pripájam sa k MySQL databáze...")
        conn = mysql.connector.connect(**DB_CONFIG)
        print("Pripojenie úspešné.")

        for task in IMPORT_TASKS:
            process_task(task, xls, conn)

    except mysql.connector.Error as err:
        print(f"\nCHYBA DATABÁZY: {err}")
        print("Skontrolujte prístupové údaje (heslo) a či je MySQL server spustený.")
        sys.exit(1)
    finally:
        if conn and conn.is_connected():
            conn.close()
            print("\nSpojenie s databázou bolo ukončené.")

if __name__ == '__main__':
    run_migration()
