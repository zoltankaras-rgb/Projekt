# tasks.py
# ===========================================
# Proaktívne úlohy pre ERP (scheduler volá tieto funkcie)
# - používa nové SDK:  pip install google-genai
# - AI model: GEMINI_MODEL (napr. gemini-2.0-flash / gemini-2.5-flash)
# - e-mail: použije tvoj mail_handler.send_email, inak SMTP localhost
# ===========================================

import os
import datetime
from typing import List, Dict, Any, Optional

# --- DB konektor (tvoj existujúci modul) ---
try:
    import db_connector
except Exception as e:
    raise RuntimeError("Nepodarilo sa importovať db_connector. Uisti sa, že modul je v PYTHONPATH.") from e

# --- AI (Nové SDK) ---
from google import genai
_GEMINI_KEY = os.getenv("GEMINI_API_KEY")
client: Optional[genai.Client] = None
if _GEMINI_KEY:
    try:
        client = genai.Client(api_key=_GEMINI_KEY)
    except Exception:
        client = None  # fallback: pobežíme bez AI

MODEL = (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@example.com")


# ========================= Pomocné =========================

def posli_email(to_addr: str, subject: str, text: str) -> None:
    """
    Najprv skúsi tvoj mail handler (ak ho máš), inak odošle cez lokálny SMTP.
    """
    # 1) Tvoj existujúci nástroj, ak je k dispozícii
    try:
        from mail_handler import send_email  # type: ignore
        send_email(to_addr, subject, text, html=None)
        return
    except Exception:
        pass

    # 2) Jednoduchý fallback: SMTP localhost (plain text)
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(text, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = DEFAULT_FROM_EMAIL
        msg["To"] = to_addr
        with smtplib.SMTP("localhost") as s:
            s.send_message(msg)
    except Exception:
        # nechceme padnúť, iba ticho neodoslať
        pass


def _rows_to_markdown(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def _is_select(sql: str) -> bool:
    if not isinstance(sql, str):
        return False
    s = sql.strip().lstrip("(")  # toleruj CTE s () na začiatku
    return s.lower().startswith("select") or s.lower().startswith("with")


def _safe_select(sql: str) -> List[Dict[str, Any]]:
    """
    Povolené sú iba SELECT (vrátane CTE WITH ... SELECT).
    """
    if not _is_select(sql):
        return []
    return db_connector.execute_query(sql, fetch="all") or []


def _ai_summarize_markdown(md_text: str, system_prompt: str) -> str:
    """
    Vygeneruj krátke, profesionálne zhrnutie (ak AI je k dispozícii).
    Ak AI nie je k dispozícii, vráť pôvodný text.
    """
    if not client:
        return md_text

    try:
        prompt = f"{system_prompt}\n\n{md_text}"
        resp = client.models.generate_content(model=MODEL, contents=prompt)
        text = getattr(resp, "text", None) or str(resp)
        return text
    except Exception:
        # fallback: vráť raw md
        return md_text


# ========================= Úlohy =========================

def uloha_kontrola_skladu(email_to: str) -> str:
    """
    Denne o 14:00: nájdi položky pod minimom (sklad vs. produkty) a pošli stručný e-mail.
    """
    sql = """
    SELECT 
        p.nazov_vyrobku AS nazov,
        COALESCE(s.mnozstvo_kg, s.mnozstvo, 0) AS mnozstvo,
        COALESCE(p.min_zasoba_kg, p.min_zasoba, 0) AS min_zasoba,
        p.mj
    FROM sklad s
    JOIN produkty p ON p.ean = s.ean
    WHERE COALESCE(s.mnozstvo_kg, s.mnozstvo, 0) < COALESCE(p.min_zasoba_kg, p.min_zasoba, 0)
    ORDER BY (COALESCE(p.min_zasoba_kg, p.min_zasoba, 0) - COALESCE(s.mnozstvo_kg, s.mnozstvo, 0)) DESC
    LIMIT 200
    """
    rows = _safe_select(sql)
    if not rows:
        return "Všetko v poriadku – nič nie je pod minimom."

    md = _rows_to_markdown(rows)
    system = (
        "Si manažér skladu. Na základe tabuľky nižšie priprav stručný a profesionálny e-mail "
        "pre oddelenie nákupu so zoznamom surovín, ktoré treba urgentne doobjednať. "
        "Použi odrážky (názov, aktuálne množstvo vs. minimum, MJ) a krátky záver s odporúčaním."
    )
    text = _ai_summarize_markdown(md, system)
    posli_email(email_to, "Sklad pod minimom – urgentné doobjednávky", text)
    return f"Odoslaný email na {email_to} – položky pod minimom: {len(rows)}."


def vykonaj_db_ulohu(task_id: int) -> str:
    """
    Spustí definovanú úlohu z tabuľky `automatizovane_ulohy`:
      - ak má SQL SELECT, vykoná ho,
      - vytvorí zhrnutie pomocou AI (ak je dostupná),
      - odošle e-mail (ak je zadaný),
      - zapíše log do `automatizovane_ulohy_log`.
    """
    # 1) Načítaj definíciu
    t = db_connector.execute_query(
        "SELECT * FROM automatizovane_ulohy WHERE id=%s",
        (task_id,), fetch="one"
    )
    if not t:
        return f"Úloha {task_id} neexistuje."
    if not int(t.get("is_enabled", 1)):
        return f"Úloha {task_id} je vypnutá."

    name = t.get("nazov_ulohy") or f"Úloha #{task_id}"
    email_to = (t.get("email_adresata") or "").strip()
    popis = (t.get("popis_ulohy_pre_ai") or "").strip()
    sql_text = (t.get("sql_text") or "").strip()

    # 2) Spusti SELECT (ak je)
    rows: List[Dict[str, Any]] = []
    if sql_text and _is_select(sql_text):
        try:
            rows = _safe_select(sql_text)
        except Exception as e:
            rows = [{"chyba": f"SQL zlyhalo: {e}"}]

    # 3) Zhrnutie (AI ak je dostupná)
    md = _rows_to_markdown(rows) if rows else "_Bez dát (žiadny riadok)._"
    system = popis or "Zhrň priložené dáta a priprav stručný manažérsky e-mail (slovensky)."
    text = _ai_summarize_markdown(md, system)

    # 4) Pošli e-mail (ak je zadaný)
    if email_to:
        posli_email(email_to, name, text)

    # 5) Log do tabuľky
    try:
        db_connector.execute_query(
            """
            INSERT INTO automatizovane_ulohy_log(task_id, executed_at, row_count, summary)
            VALUES (%s, NOW(), %s, %s)
            """,
            (task_id, len(rows), text[:2000])
        )
    except Exception:
        # logovanie nech nezhodí job
        pass

    return f"Úloha {task_id} vykonaná – email: {email_to or '-'}, riadkov: {len(rows)}."
