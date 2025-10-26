import db_connector
from datetime import datetime
import os
import csv
import traceback
from pathlib import Path

# =================================================================
# === MODUL PRE INTEGRÁCIU S EXTERNÝMI SYSTÉMAMI ===
# =================================================================

# --- KONFIGURÁCIA ---
# Odporúčanie: Tieto cesty je ideálne presunúť do .env súboru, aby sa dali ľahko meniť.
# Používame Path pre lepšiu prácu s cestami v rôznych operačných systémoch.
BASE_PATH = Path("C:/vymena_dat")
EXPORT_FOLDER = BASE_PATH / "export_z_vyroby"
IMPORT_FOLDER = BASE_PATH / "import_do_vyroby"


def generate_daily_receipt_export(export_date_str=None):
    """
    Vygeneruje CSV súbor s denným príjmom finálnych produktov na sklad.
    Súbor obsahuje EAN a celkové prijaté množstvo za deň.
    Túto funkciu volá automatická úloha (run_scheduled_tasks.py).
    """
    try:
        export_date = export_date_str or datetime.now().strftime('%Y-%m-%d')

        # Získa dáta z databázy pre daný deň
        query = """
            SELECT p.ean, zv.realne_mnozstvo_kg, zv.realne_mnozstvo_ks, p.mj as unit 
            FROM zaznamy_vyroba zv
            LEFT JOIN produkty p ON zv.nazov_vyrobku = p.nazov_vyrobku
            WHERE zv.stav = 'Ukončené' AND DATE(zv.datum_ukoncenia) = %s
        """
        records = db_connector.execute_query(query, (export_date,))

        if not records:
            return {"message": f"Pre dátum {export_date} neboli nájdené žiadne ukončené výroby na export.", "file_path": None}

        # Zoskupí dáta podľa EAN, aby sa sčítali rovnaké produkty
        consolidated = {}
        for r in records:
            if not r.get('ean'): continue
            
            ean = r['ean']
            if ean not in consolidated:
                consolidated[ean] = 0
            
            qty_to_add = float(r.get('realne_mnozstvo_ks') or 0.0) if r.get('unit') == 'ks' else float(r.get('realne_mnozstvo_kg') or 0.0)
            consolidated[ean] += qty_to_add
        
        # Vytvorí priečinok, ak neexistuje
        os.makedirs(EXPORT_FOLDER, exist_ok=True)
        
        file_name = f"prijem_{export_date.replace('-', '')}.csv"
        file_path = EXPORT_FOLDER / file_name

        # Zapíše dáta do CSV súboru s kódovaním vhodným pre Slovensko
        with open(file_path, 'w', newline='', encoding='cp1250') as csvfile:
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(['EAN', 'Mnozstvo'])  # Hlavička súboru
            for ean, quantity in consolidated.items():
                # Formátujeme číslo s desatinnou čiarkou
                writer.writerow([ean, f"{quantity:.2f}".replace('.', ',')])
        
        return {"message": f"Exportný súbor bol úspešne vygenerovaný: {file_path}", "file_path": str(file_path)}
    except Exception as e:
        print(f"!!! CHYBA pri generovaní exportu: {traceback.format_exc()}")
        return {"error": f"Nastala chyba pri zápise súboru: {e}"}


def process_stock_update_import():
    """
    Spracuje importný CSV súbor so stavom skladu finálnych produktov z externého systému.
    Očakáva súbor `sklad.csv` v importnom priečinku.
    """
    try:
        file_path = IMPORT_FOLDER / 'sklad.csv'

        if not os.path.exists(file_path):
            return {"error": f"Importný súbor nebol nájdený na ceste: {file_path}"}
        
        updates_to_catalog = []
        with open(file_path, 'r', newline='', encoding='cp1250') as csvfile:
            reader = csv.reader(csvfile, delimiter=';')
            next(reader)  # Preskočí hlavičku
            for row in reader:
                if len(row) == 2:
                    ean, quantity_str = row
                    quantity = float(quantity_str.replace(',', '.'))
                    updates_to_catalog.append((quantity, ean))

        if not updates_to_catalog:
            return {"message": "Importný súbor neobsahoval žiadne platné dáta."}

        # Aktualizuje databázu v jednej hromadnej operácii
        db_connector.execute_query(
            "UPDATE produkty SET aktualny_sklad_finalny_kg = %s WHERE ean = %s",
            updates_to_catalog,
            fetch='none',
            multi=True
        )
        
        return {"message": f"Sklad bol úspešne aktualizovaný. Počet aktualizovaných produktov: {len(updates_to_catalog)}."}
    
    except Exception as e:
        print(f"!!! CHYBA pri spracovaní importu: {traceback.format_exc()}")
        return {"error": f"Nastala chyba pri spracovaní importného súboru: {e}"}
