import hashlib
import os

# =================================================================
# === BEZPEČNOSTNÉ FUNKCIE PRE PRÁCU S HESLAMI (INTERNÍ POUŽÍVATELIA) ===
# =================================================================

def generate_password_hash(password):
    """
    Vygeneruje bezpečnú "soľ" (salt) a hash pre zadané heslo.
    Používa moderný a odporúčaný algoritmus PBKDF2 s vysokým počtom iterácií.
    
    Args:
        password (str): Heslo v čitateľnej podobe.
        
    Returns:
        tuple: Dvojica (salt_hex, hash_hex) pripravená na uloženie do databázy.
    """
    # Vygeneruje náhodných 32 bytov pre soľ, čo je viac než dostatočné
    salt = os.urandom(32)
    
    # Vytvorí hash hesla pomocou PBKDF2. Počet iterácií (napr. 250000) sťažuje útoky hrubou silou.
    key = hashlib.pbkdf2_hmac(
        'sha256',  # Použitý hashovací algoritmus
        password.encode('utf-8'),  # Heslo prekonvertované na byty
        salt,  # Naša unikátna soľ
        250000  # Počet iterácií
    )
    
    # Vrátime soľ a hash ako hexadecimálne reťazce pre jednoduché uloženie do textového stĺpca v DB
    return salt.hex(), key.hex()

def verify_password(password, salt_hex, hash_hex):
    """
    Overí, či sa zadané heslo zhoduje s uloženou soľou a hashom.
    
    Args:
        password (str): Heslo, ktoré zadal používateľ pri prihlasovaní.
        salt_hex (str): Soľ načítaná z databázy (v hex formáte).
        hash_hex (str): Hash načítaný z databázy (v hex formáte).
        
    Returns:
        bool: True, ak sa heslá zhodujú, inak False.
    """
    try:
        # Prekonvertujeme hex reťazce späť na byty
        salt = bytes.fromhex(salt_hex)
        stored_key = bytes.fromhex(hash_hex)
        
        # Vytvoríme nový hash s použitím hesla od používateľa a soli z databázy.
        # Je kľúčové použiť presne tie isté parametre ako pri generovaní!
        new_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            250000
        )
        
        # Bezpečné porovnanie oboch hashov. Vráti True alebo False.
        return new_key == stored_key
        
    except (ValueError, TypeError):
        # Ak by salt_hex alebo hash_hex neboli platné hex reťazce, vrátime False
        return False

