import mysql.connector
from mysql.connector import pooling, errors
import os
import traceback
from dotenv import load_dotenv

# Načíta premenné z .env súboru
load_dotenv()

# --- KONFIGURÁCIA DATABÁZY ---
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', 'karas'),
    'database': os.getenv('DB_DATABASE', 'vyrobny_system'),
    # doplnené: nech spojenie používa správnu znak. sadu už od začiatku
    'charset': os.getenv('DB_CHARSET', 'utf8mb4'),
}

# defenzívne: kolácia pre session (Používame ju v _init_session)
DB_COLLATION = os.getenv('DB_COLLATION', 'utf8mb4_slovak_ci')
DB_CHARSET   = os.getenv('DB_CHARSET',   'utf8mb4')

connection_pool = None
try:
    connection_pool = pooling.MySQLConnectionPool(
        pool_name="vyroba_pool",
        pool_size=5,
        **DB_CONFIG
    )
    print(">>> MySQL Connection Pool bol úspešne vytvorený.")
except mysql.connector.Error as e:
    print(f"!!! KRITICKÁ CHYBA: Nepodarilo sa pripojiť k MySQL databáze: {e}")
    print("--- Skontrolujte, či je MySQL server spustený a konfiguračné premenné v .env súbore sú správne.")

def _init_session(conn):
    """
    Nastaví koláciu/charset pre **toto** spojenie zo poolu.
    Dôležité: pool vracia už existujúce spojenia, preto to robíme pokaždé.
    """
    try:
        cur = conn.cursor()
        # jednotná znaková sada a kolácia pre porovnávanie literálov/temporaries v tejto session
        cur.execute(f"SET NAMES {DB_CHARSET} COLLATE {DB_COLLATION}")
        cur.execute(f"SET collation_connection = '{DB_COLLATION}'")
        cur.execute(f"SET character_set_client = '{DB_CHARSET}'")
        cur.execute(f"SET character_set_connection = '{DB_CHARSET}'")
        cur.execute(f"SET character_set_results = '{DB_CHARSET}'")
        cur.close()
    except Exception as e:
        # nech to nespadne kvôli SET príkazu, ale zalogujme si to
        print(f"!!! UPOZORNENIE: Nepodarilo sa nastaviť session koláciu: {e}")

def get_connection():
    """Získa jedno voľné pripojenie z pool-u a nastaví session koláciu/charset."""
    if not connection_pool:
        raise Exception("Connection pool nie je k dispozícii. Aplikácia sa nemôže pripojiť k databáze.")
    conn = connection_pool.get_connection()
    _init_session(conn)
    return conn

def execute_query(query, params=None, fetch='all', multi=False):
    """
    Centrálna a bezpečná funkcia na vykonávanie SQL príkazov.
    Využíva transakcie pre bezpečnosť dát.
    - fetch: 'all' | 'one' | 'none' | 'lastrowid'
    - multi: True => executemany
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        if multi:
            cursor.executemany(query, params)
        else:
            cursor.execute(query, params or ())

        if fetch == 'one':
            return cursor.fetchone()
        elif fetch == 'all':
            return cursor.fetchall()
        else:  # 'none', 'lastrowid' atď., kde sa vykonáva zápis
            conn.commit()
            if fetch == 'lastrowid':
                return cursor.lastrowid
            return cursor.rowcount

    except errors.Error as e:
        # Diagnostika: vypíšeme prvých ~100 znakov dotazu a kľúčové info o session kolácii
        print(f"!!! DB CHYBA pri vykonávaní SQL príkazu: {query[:100]}...")
        try:
            if conn:
                info_cur = conn.cursor()
                info_cur.execute("SELECT @@character_set_connection, @@collation_connection")
                cs_conn, coll_conn = info_cur.fetchone()
                info_cur.close()
                print(f"@@character_set_connection={cs_conn}, @@collation_connection={coll_conn}")
        except Exception:
            pass
        print(traceback.format_exc())
        if conn:
            conn.rollback()  # V prípade chyby vráti všetky zmeny späť
        raise e  # Pošle chybu ďalej, aby ju zachytil handle_request v app.py

    except Exception as e:
        # iné typy výnimiek (napr. Python errors)
        print(f"!!! DB CHYBA pri vykonávaní SQL príkazu: {query[:100]}...")
        print(traceback.format_exc())
        if conn:
            conn.rollback()
        raise e

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
