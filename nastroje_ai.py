# nastroje_ai.py
# ------------------------------------------------------------
# Schéma DB pre AI + bezpečné spúšťanie SQL:
#  - get_schema_prompt()             -> číta schema/schema_prompt.md (s cache), fallback na information_schema
#  - vykonaj_bezpecny_sql_prikaz()   -> bezpečný SELECT‑only spúšťač (povoľuje REPLACE() funkciu)
#  - vykonaj_dml_sql()               -> potvrdené zápisy (INSERT/UPDATE/DELETE/REPLACE INTO), stále blokuje DDL/I/O
# ------------------------------------------------------------

from __future__ import annotations
import os, re, json, time, datetime, decimal
from typing import Any, Dict, List, Optional

# tvoje DB API
import db_connector

# ------------- Pomocné -------------------------------------------------------
def _jsonify_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def conv(v):
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v.isoformat()
        if isinstance(v, decimal.Decimal):
            return float(v)
        return v
    return [{k: conv(v) for k, v in (r or {}).items()} for r in (rows or [])]

def _strip_sql_comments_and_strings(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    s = re.sub(r"(?m)--.*$", " ", s)
    s = re.sub(r"('([^'\\]|\\.)*'|\"([^\"\\]|\\.)*\")", " ", s)
    return s

# ------------- SELECT-only guard --------------------------------------------
_SQL_MULTI_STMT   = re.compile(r";\s*(?=\S)", re.IGNORECASE)
_SQL_ONLY_SELECT  = re.compile(r"^\s*(WITH\b.*?SELECT\b|SELECT\b)", re.IGNORECASE | re.DOTALL)
_SQL_DDL_IO       = re.compile(
    r"\b(alter|create|drop|truncate|rename|grant|revoke|load|outfile|infile|handler|set|explain|describe|show|call|sleep\s*\()",
    re.IGNORECASE,
)
_SQL_WRITE_STMT   = re.compile(r"^\s*(insert|update|delete|replace\s+into)\b", re.IGNORECASE)

def vykonaj_bezpecny_sql_prikaz(sql: str, limit_default: int = 2000) -> Dict[str, Any]:
    """
    Povolí iba SELECT/CTE SELECT, doplní LIMIT ak chýba.
    DDL/I-O a viacnásobné príkazy blokuje.
    Povoľuje funkcie typu REPLACE(), DATE_FORMAT(), atď.
    """
    if not isinstance(sql, str):
        return {"error": "SQL musí byť text."}
    candidate = (sql or "").strip().rstrip(";")
    if not candidate:
        return {"error": "SQL je prázdne."}

    # multi-statement guard
    if _SQL_MULTI_STMT.search(_strip_sql_comments_and_strings(candidate)):
        return {"error": "Zakázané sú viaceré príkazy v jednom SQL."}

    # SELECT-only
    if not _SQL_ONLY_SELECT.match(candidate):
        return {"error": "Povolené sú len SELECT dotazy (vrátane WITH ... SELECT)."}

    # zakáž DDL/I-O aj v SELECT-e
    if _SQL_DDL_IO.search(_strip_sql_comments_and_strings(candidate)):
        return {"error": "Zakázaný príkaz – povolené sú len SELECT dotazy."}

    # doplň LIMIT (ak chýba)
    if re.search(r"\bLIMIT\s+\d+", candidate, re.IGNORECASE) is None:
        candidate = f"{candidate} LIMIT {int(limit_default)}"

    try:
        rows = db_connector.execute_query(candidate, fetch="all") or []
        rows = _jsonify_rows(rows)
        cols = list(rows[0].keys()) if rows else []
        return {"columns": cols, "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}

# ------------- DML (zápisy) – len po potvrdení z frontu ---------------------
def vykonaj_dml_sql(sql: str) -> Dict[str, Any]:
    """
    Vykoná INSERT/UPDATE/DELETE/REPLACE INTO po explicitnom potvrdení.
    - stále blokuje DDL/I-O (ALTER/CREATE/DROP/…; OUTFILE/INFILE/LOAD/SET/…)
    - blokuje viacnásobné príkazy
    - vracia affected_rows ak sa dá zistiť (cez SELECT ROW_COUNT()) – best effort
    """
    if not isinstance(sql, str):
        return {"error": "SQL musí byť text."}
    candidate = (sql or "").strip().rstrip(";")
    if not candidate:
        return {"error": "SQL je prázdne."}

    clean = _strip_sql_comments_and_strings(candidate)

    if _SQL_MULTI_STMT.search(clean):
        return {"error": "Zakázané sú viaceré príkazy v jednom SQL."}

    # povoliť len zápisy (nie DDL/I-O)
    if _SQL_DDL_IO.search(clean):
        return {"error": "Zakázané DDL/I-O príkazy."}

    if not _SQL_WRITE_STMT.match(clean):
        return {"error": "Povolené sú len INSERT/UPDATE/DELETE/REPLACE INTO."}

    try:
        db_connector.execute_query(candidate, fetch="none")
        # pokus o zistenie počtu ovplyvnených riadkov
        try:
            rc_row = db_connector.execute_query("SELECT ROW_COUNT() AS rc", fetch="one") or {}
            rc = rc_row.get("rc")
        except Exception:
            rc = None
        return {"ok": True, "affected_rows": rc}
    except Exception as e:
        return {"error": str(e)}

# ------------- SCHEMA PROMPT (fallback generátor) ---------------------------
_HEURISTICS: Dict[str, str] = {
    # príklady – voliteľné vysvetlivky stĺpcov
    "ean": "Čiarový kód produktu.",
    "mj": "Merná jednotka ('kg' alebo 'ks').",
    "vaha_balenia_g": "Hmotnosť balenia v gramoch.",
    "id_davky": "ID výrobnej dávky.",
    "nazov_vyrobku": "Názov hotového výrobku.",
    "prijem_kg": "Prijaté množstvo v kg.",
    "prijem_ks": "Prijaté množstvo v ks.",
    "license_plate": "EČV/SPZ vozidla (napr. SA889DG).",
    "log_date": "Dátum záznamu jazdy.",
    "refueling_date": "Dátum tankovania.",
    "km_driven": "Ujdené kilometre.",
    "liters": "Objem paliva (l).",
    "goods_out_kg": "Roznesené kg v rámci jazdy.",
}

def _table_list() -> List[Dict[str, Any]]:
    return db_connector.execute_query(
        """
        SELECT TABLE_NAME, TABLE_COMMENT
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
        ORDER BY TABLE_NAME
        """,
        fetch="all",
    ) or []

def _columns_for(table: str) -> List[Dict[str, Any]]:
    return db_connector.execute_query(
        """
        SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table,),
        fetch="all",
    ) or []

def _relations() -> List[Dict[str, Any]]:
    return db_connector.execute_query(
        """
        SELECT k.TABLE_NAME, k.COLUMN_NAME, k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE k
        WHERE k.TABLE_SCHEMA = DATABASE() AND k.REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY k.TABLE_NAME, k.COLUMN_NAME
        """,
        fetch="all",
    ) or []

def _desc(col: str, comment: str) -> str:
    c = (comment or "").strip()
    if c:
        return c
    return _HEURISTICS.get(col.lower(), "")

def build_schema_prompt() -> str:
    parts: List[str] = []
    parts.append("### Databáza: (DATABASE()) (MySQL)\n")
    for t in _table_list():
        tname = t["TABLE_NAME"]
        tcomm = (t.get("TABLE_COMMENT") or "").strip()
        parts.append(f"Tabuľka: {tname}" + (f" — {tcomm}" if tcomm else ""))
        for c in _columns_for(tname):
            col = c["COLUMN_NAME"]
            typ = c["COLUMN_TYPE"]
            nul = c["IS_NULLABLE"]
            key = c["COLUMN_KEY"]
            dfl = c["COLUMN_DEFAULT"]
            ext = c["EXTRA"]
            line = f"  - {col}: {typ}, NULLABLE={nul}"
            if key:
                line += f", KEY={key}"
            if dfl is not None:
                line += f", DEFAULT='{str(dfl)}'"
            if ext:
                line += f", EXTRA={ext}"
            desc = _desc(col, c.get("COLUMN_COMMENT", ""))
            if desc:
                line += f" — {desc}"
            parts.append(line)
        parts.append("")
    parts.append("### Vzťahy (FK):")
    rels = _relations()
    if rels:
        for r in rels:
            parts.append(f"- {r['TABLE_NAME']}.{r['COLUMN_NAME']} → {r['REFERENCED_TABLE_NAME']}.{r['REFERENCED_COLUMN_NAME']}")
    else:
        parts.append("(žiadne cudzie kľúče)")
    parts.append("")
    return "\n".join(parts)

# ------------- Jediný súbor so schémou + procedúra + cache -------------------
_SCHEMA_FILE_CACHE = {"path": None, "mtime": 0.0, "text": ""}

def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def build_schema_prompt_from_proc(schema_name: Optional[str] = None) -> str:
    try:
        row = db_connector.execute_query("CALL sp_dump_schema_markdown(%s)", (schema_name,), fetch="one")
        md = (row or {}).get("schema_markdown", "") or ""
        return md or build_schema_prompt()
    except Exception:
        return build_schema_prompt()

def get_schema_prompt() -> str:
    """
    Primárne číta súbor (SCHEMA_PROMPT_PATH alebo schema/schema_prompt.md).
    Ak neexistuje, skúsi procedúru a uloží; ak aj to zlyhá, vráti build_schema_prompt().
    """
    path = os.getenv("SCHEMA_PROMPT_PATH")
    if not path:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "schema", "schema_prompt.md")

    try:
        st = os.stat(path)
        if _SCHEMA_FILE_CACHE["path"] != path or _SCHEMA_FILE_CACHE["mtime"] != st.st_mtime:
            txt = _read_text_file(path)
            _SCHEMA_FILE_CACHE.update({"path": path, "mtime": st.st_mtime, "text": txt})
        return _SCHEMA_FILE_CACHE["text"]
    except FileNotFoundError:
        md = build_schema_prompt_from_proc(None)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            _SCHEMA_FILE_CACHE.update({"path": path, "mtime": time.time(), "text": md})
        except Exception:
            pass
        return md or build_schema_prompt()
