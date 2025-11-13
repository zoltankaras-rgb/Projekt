import os
import traceback
from typing import Any, Iterable, Optional, Tuple, Union, Callable

import mysql.connector
from mysql.connector import pooling, errors
from dotenv import load_dotenv

# Načíta premenné z .env súboru (ak existuje)
load_dotenv()

# --- KONFIGURÁCIA DATABÁZY ---------------------------------------
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_DATABASE", "vyrobny_system"),
    # MySQL Connector používa charset param od 8.0 – nech je jednotne utf8mb4
    "charset":  os.getenv("DB_CHARSET", "utf8mb4"),
}

# Session-level nastavenie (kolácia a charset)
DB_CHARSET   = os.getenv("DB_CHARSET", "utf8mb4")
DB_COLLATION = os.getenv("DB_COLLATION", "utf8mb4_slovak_ci")

# Veľkosť poolu (možné doladiť)
POOL_NAME = os.getenv("DB_POOL_NAME", "vyroba_pool")
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))

connection_pool: Optional[pooling.MySQLConnectionPool] = None

# --- Inicializácia poolu -----------------------------------------
try:
    connection_pool = pooling.MySQLConnectionPool(
        pool_name=POOL_NAME,
        pool_size=POOL_SIZE,
        **DB_CONFIG
    )
    print(">>> MySQL Connection Pool bol úspešne vytvorený.")
except mysql.connector.Error as e:
    print(f"!!! KRITICKÁ CHYBA: Nepodarilo sa pripojiť k MySQL databáze: {e}")
    print("--- Skontrolujte, či je MySQL server spustený a konfiguračné premenné v .env súbore sú správne.")


# --- Pomocné: nastavenie session pre spojenie --------------------
def _init_session(conn: mysql.connector.MySQLConnection) -> None:
    """
    Nastaví koláciu/charset pre **toto** spojenie zo poolu.
    Dôležité: pool recykluje spojenia, preto sa SET vykonáva pri každom vydaní spojenia.
    """
    try:
        cur = conn.cursor()
        # jednotná znaková sada a kolácia pre porovnávania a výsledky
        cur.execute(f"SET NAMES {DB_CHARSET} COLLATE {DB_COLLATION}")
        cur.execute(f"SET collation_connection = '{DB_COLLATION}'")
        cur.execute(f"SET character_set_client = '{DB_CHARSET}'")
        cur.execute(f"SET character_set_connection = '{DB_CHARSET}'")
        cur.execute(f"SET character_set_results = '{DB_CHARSET}'")
        # voliteľne by sa dalo nastaviť time_zone, sql_mode atď.
        cur.close()
    except Exception as e:
        # nech kvôli SET príkazu nespadne aplikácia; stačí zalogovať
        print(f"!!! UPOZORNENIE: Nepodarilo sa nastaviť session koláciu: {e}")


def get_connection():
    """
    Vezme pripojenie z poolu; ak je pool vyčerpaný, skúsime krátko počkať
    a napokon vytvoríme nouzové “priame” spojenie, aby appka nespadla.
    """
    from mysql.connector.errors import PoolError
    import time
    try:
      conn = connection_pool.get_connection()
      try:
          conn.ping(reconnect=True, attempts=1, delay=0)
      except Exception:
          pass
      return conn
    except PoolError:
      # krátka pauza a druhý pokus
      time.sleep(0.1)
      try:
          conn = connection_pool.get_connection()
          try:
              conn.ping(reconnect=True, attempts=1, delay=0)
          except Exception:
              pass
          return conn
      except PoolError:
          # núdzové priame spojenie (mimo poolu) – zabráni pádu, ale MUSÍ sa vždy zavrieť
          return mysql.connector.connect(**DB_CONFIG)

# --- Core vykonávanie dotazov ------------------------------------
def execute_query(query, params=None, fetch="all"):
    """
    fetch: "all" (default) | "one" | "none"
    - VŽDY uzatvára cursor aj connection (vracia do poolu).
    - Pri zmenových SQL (INSERT/UPDATE/DELETE/REPLACE) spraví commit.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(query, params or ())

        upper = query.lstrip().upper()
        is_write = upper.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "TRUNCATE"))
        data = None
        if fetch == "one":
            data = cur.fetchone()
        elif fetch == "all":
            data = cur.fetchall()
        else:
            data = None

        if is_write:
            conn.commit()
        return data
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        # voliteľne zaloguj:
        print("!!! DB CHYBA pri vykonávaní SQL príkazu:", query)
        raise
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()   # <<< kľúčové – vráti do poolu (alebo zatvorí priame spojenie)
        except Exception:
            pass


# --- Transakčný helper (ak potrebuješ viaceré kroky v jednej TX) --
def with_transaction(fn: Callable[[mysql.connector.MySQLConnection], Any]) -> Any:
    """
    Spustí dodanú funkciu v rámci jednej transakcie (jedno DB spojenie).
    Príklad:
        def work(conn):
            cur = conn.cursor(dictionary=True)
            cur.execute("INSERT ...", params)
            cur.execute("UPDATE ...", params)
        with_transaction(work)
    """
    conn = get_connection()
    try:
        result = fn(conn)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()
