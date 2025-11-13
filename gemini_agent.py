# gemini_agent.py — ERP agent (SELECT-only, repair, retry, ASK/FUNC, NLG veta, voliteľné zápisy)
# ---------------------------------------------------------------------------------------------
from __future__ import annotations
import os, re, json, html, time, random
from typing import Any, Dict, List, Optional, Tuple

# === LLM (Gemini) ============================================================
try:
    from google import genai
except Exception as _e:
    raise RuntimeError("Chýba balík `google-genai` (pip install -U google-genai)") from _e

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
if not API_KEY:
    raise RuntimeError("Nastav GEMINI_API_KEY alebo GOOGLE_API_KEY v .env")

client = genai.Client(api_key=API_KEY)

# Fallback modely + retry/backoff
DEFAULT_FALLBACKS = ["gemini-2.0-flash-lite", "gemini-1.5-flash-8b", "gemini-1.0-pro"]
ENV_FALLBACKS = [m.strip() for m in os.getenv("GEMINI_MODEL_FALLBACKS", ",".join(DEFAULT_FALLBACKS)).split(",") if m.strip()]
MODEL_BLOCKLIST = {m.strip() for m in os.getenv("GEMINI_MODEL_BLOCKLIST", "").split(",") if m.strip()}
GENAI_MAX_RETRIES   = int(os.getenv("GENAI_MAX_RETRIES", "4"))
GENAI_RETRY_BASE_MS = int(os.getenv("GENAI_RETRY_BASE_MS", "600"))  # 0.6s, 1.2s, 2.4s …
GENAI_USE_SQL_MIME  = os.getenv("GENAI_USE_SQL_MIME", "true").lower() in {"1","true","yes"}

# === DB + AI nástroje ========================================================
import db_connector
from nastroje_ai import (
    get_schema_prompt,
    vykonaj_bezpecny_sql_prikaz,
    vykonaj_dml_sql,  # na potvrdené zápisy
)

ROW_LIMIT_DEFAULT = int(os.getenv("AI_SQL_ROW_LIMIT", "200"))
ALLOW_WRITES      = os.getenv("AI_ALLOW_WRITES", "false").lower() in {"1","true","yes"}

# --- Agentove inštrukcie -----------------------------------------------------
SYSTEM = (
    "Si analytik nad ERP (MySQL). Odpovedaj po slovensky.\n"
    "Pre POSLEDNÚ otázku používateľa urob presne JEDNO z tohto:\n"
    "  1) Ak vieš odpovedať dotazom na DB: vráť IBA SQL v bloku ```sql ...``` (1 statement, SELECT/CTE SELECT).\n"
    "  2) Ak je otázka nejasná a potrebuješ spresnenie: vráť `ASK: <doplňujúca otázka>` (nič iné).\n"
    "  3) Ak potrebuješ pomocnú funkciu (napr. získať ID vozidla z EČV alebo EAN z názvu), vráť\n"
    "     `FUNC: resolve_vehicle_id {\"plate\":\"SA 889DG\"}` alebo `FUNC: resolve_product_ean {\"name\":\"Hrubá klobása\"}`.\n"
    "POŽIADAVKY NA SQL:\n"
    f" - povolené sú len SELECT dotazy (vrátane WITH ... SELECT); ak chýba LIMIT, pridaj LIMIT {ROW_LIMIT_DEFAULT}.\n"
    " - používaj presné názvy zo schémy; vždy aliasuj stĺpce a nuluj agregácie cez COALESCE.\n"
    " - SPZ/EČV porovnávaj normalizovane: REPLACE(REPLACE(UPPER(license_plate),' ',''),'-','').\n"
    " - Makrá v schéme (THIS_MONTH/TODAY/ECV_NORM) ber ako opisné a expanduj na MySQL výrazy.\n"
    " - Pri mesačnom nájazde vozidla preferuj `fleet_logs`; ak nemá záznamy, použi fallback `profit_calculations.distance_km`.\n"
    " - aliasy výsledkov nastavuj konzistentne: total_km, total_goods_out_kg, l_per_100km, max_temp_c, stock_kg.\n"

)

# === Model selection (odfiltruj nedostupné) ==================================
_AVAILABLE_MODELS_CACHE: Optional[List[str]] = None

def _list_available_model_ids() -> List[str]:
    global _AVAILABLE_MODELS_CACHE
    if _AVAILABLE_MODELS_CACHE is not None:
        return _AVAILABLE_MODELS_CACHE
    try:
        items = list(client.models.list())
        names = []
        for m in items:
            name = getattr(m, "name", "") or ""
            if name.startswith("models/"):
                name = name.split("/", 1)[1]
            if name:
                names.append(name)
        _AVAILABLE_MODELS_CACHE = names
        return names
    except Exception:
        return []

def _prioritized_models() -> List[str]:
    wanted = [PRIMARY_MODEL] + [m for m in ENV_FALLBACKS if m]
    for d in DEFAULT_FALLBACKS:
        if d not in wanted:
            wanted.append(d)
    wanted = [m for m in wanted if m and m not in MODEL_BLOCKLIST]
    avail = set(_list_available_model_ids())
    if avail:
        filtered = [m for m in wanted if (m in avail)]
        if filtered:
            return filtered
        prio = [x for x in avail if ("flash" in x or "pro" in x)]
        return sorted(prio) or list(avail)
    return wanted

# === Pomocné regexy a sanitizácia ============================================
_SQL_MULTI_STMT = re.compile(r";\s*(?=\S)", re.IGNORECASE)
_SQL_START      = re.compile(r"(?is)^\s*(with|select)\b")
_SQL_DDL_IO     = re.compile(
    r"\b(alter|create|drop|truncate|rename|grant|revoke|load|outfile|infile|handler|set|explain|describe|show|call|sleep\s*\()",
    re.IGNORECASE,
)
_SQL_WRITE      = re.compile(r"^\s*(insert|update|delete|replace\s+into)\b", re.IGNORECASE)

def _strip_sql_comments_and_strings(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    s = re.sub(r"(?m)--.*$", " ", s)
    s = re.sub(r"('([^'\\]|\\.)*'|\"([^\"\\]|\\.)*\")", " ", s)
    return s

def _classify_sql(sql: str) -> str:
    s = (sql or "").strip()
    s_clean = _strip_sql_comments_and_strings(s)
    if _SQL_MULTI_STMT.search(s_clean):
        return "unsafe"
    if _SQL_START.search(s):
        if _SQL_DDL_IO.search(s_clean):
            return "unsafe"
        return "select"
    if _SQL_WRITE.search(s_clean):
        if _SQL_DDL_IO.search(s_clean):
            return "unsafe"
        return "write"
    return "unsafe"

def _trim_trailing_natural_language(sql: str) -> str:
    x = sql.replace("```", " ")
    m = re.search(r"\bAND\s+[A-Za-zÁ-ž][A-Za-zÁ-ž\s\?\,\.\-]{3,}$", x, flags=re.IGNORECASE | re.MULTILINE)
    if m: return x[:m.start()].rstrip()
    m2 = re.search(r"(?is)\blimit\s+\d+(\s*,\s*\d+)?\s+[A-Za-zÁ-ž]", x)
    if m2: return x[:m2.start()].rstrip()
    m3 = re.search(r"\?[^\n]*$", x)
    if m3: return x[:m3.start()].rstrip()
    return x

def _detect_ask_or_func(text: str) -> Tuple[str, Optional[str], Optional[Tuple[str, dict]]]:
    if not text:
        return "none", None, None
    m = re.search(r"(?im)^\s*ASK:\s*(.+)$", text)
    if m:
        return "ask", m.group(1).strip(), None
    m = re.search(r"(?ims)^\s*FUNC\s*:\s*([A-Za-z0-9_]+)\s*(\{.*\})?\s*$", text)
    if m:
        name = m.group(1).strip()
        argj = m.group(2) or "{}"
        try:
            args = json.loads(argj)
        except Exception:
            args = {}
        return "func", None, (name, args)
    return "none", None, None

def _extract_sql_only(text: str) -> Optional[str]:
    m = re.search(r"```sql\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if m:
        return _trim_trailing_natural_language(m.group(1).strip())
    s = re.search(r"(?is)\b(with|select)\b", text)
    if s:
        cut = text[s.start():]
        sql = re.split(r";\s*\n?|$", cut, maxsplit=1)[0].strip()
        return _trim_trailing_natural_language(sql)
    return None

def _force_limit(sql: str, limit: int = ROW_LIMIT_DEFAULT) -> str:
    s = sql.strip().rstrip(";")
    if re.search(r"\blimit\s+\d+", s, re.IGNORECASE):
        return s
    return s + f" LIMIT {int(limit)}"

# === Render tabuľky + NLG veta ===============================================
def _rows_to_html(rows: List[Dict[str, Any]], sql: Optional[str]) -> str:
    rows = rows or []
    if not rows:
        tbl = "<div class='ai-empty'>Žiadne riadky.</div>"
    else:
        cols = list(rows[0].keys())
        thead = "<thead><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in cols) + "</tr></thead>"
        body  = []
        for r in rows[:1000]:
            tds = "".join(f"<td>{html.escape(str(r.get(c,'')))}</td>" for c in cols)
            body.append(f"<tr>{tds}</tr>")
        tbody = "<tbody>" + "".join(body) + "</tbody>"
        tbl   = f"<div class='ai-table-wrap'><table class='ai-table'>{thead}{tbody}</table></div>"
    sql_block = f"<details class='ai-sql'><summary>SQL</summary><pre>{html.escape(sql or '')}</pre></details>" if sql else ""
    return tbl + sql_block

def _fmt_num(v: Any, decimals: Optional[int] = None) -> str:
    try:
        if isinstance(v, bool): return "1" if v else "0"
        if isinstance(v, int):  return f"{v:,}".replace(",", " ")
        x = float(v)
        if decimals is None:
            decimals = 3 if abs(x) < 1 else 2
        s = f"{x:,.{decimals}f}"
        return s.replace(",", " ").replace(".", ",")
    except Exception:
        return str(v)

def _nlg_sentence(question: str, rows: List[Dict[str, Any]]) -> str:
    """Heuristická 1–2 vetová odpoveď v slovenčine z prvého riadku výsledku."""
    if not rows:
        q = (question or "").strip().rstrip("?")
        return f"K tvojej otázke „{q}“ som nenašiel žiadne záznamy."

    r0 = rows[0]
    # mapy pre case-insensitive prístup
    key_map = {k.lower(): k for k in r0.keys()}
    def has(*alts): return any(a.lower() in key_map for a in alts)
    def val(*alts):
        for a in alts:
            k = a.lower()
            if k in key_map: return r0[key_map[k]]
        return None

    # --- 1) Vozidlo / kilometre ---
    if has("license_plate") and has("total_km_by_sum","total_km","total_km_driven","km","km_driven","sum_km","km_calc","total_km_by_odometer"):
        plate = str(val("license_plate"))
        veh   = val("vehicle_name","name")
        km    = val("total_km_by_sum","total_km","total_km_driven","km","km_driven","sum_km","total_km_by_odometer","km_calc")
        vtxt  = f" ({veh})" if veh else ""
        km_s  = _fmt_num(km, 0)
        return f"Auto {plate}{vtxt} najazdilo v danom období spolu {km_s} km."

    # --- 2) Spotreba l/100 km ---
    if has("l_per_100km"):
        l = val("l_per_100km")
        liters = val("liters_total","liters")
        base = f"Priemerná spotreba je {_fmt_num(l,2)} l/100 km."
        if liters is not None:
            base += f" Celkové natankované množstvo je {_fmt_num(liters,2)} l."
        return base

    # --- 3) Teplota (max) — rozpoznaj aj slovenské aliasy ---
    # podporované aliasy: max_temp_c, temperature, max_teplota, najvyssia_teplota, najvyššia_teplota
    if has("max_temp_c","temperature","max_teplota","najvyssia_teplota","najvyššia_teplota"):
        t = val("max_temp_c","temperature","max_teplota","najvyssia_teplota","najvyššia_teplota")
        dev = val("device_name","zariadenie","name","device")
        ts  = val("at_timestamp","cas","timestamp","ts","datetime")
        t_s = _fmt_num(t, 2)
        if dev and ts:
            return f"Najvyššia nameraná teplota bola {t_s} °C o {ts} na zariadení {dev}."
        if dev:
            return f"Najvyššia nameraná teplota bola {t_s} °C na zariadení {dev}."
        return f"Najvyššia nameraná teplota bola {t_s} °C."

    # --- 4) Stav zásob (kg) ---
    if has("stock_kg","centralny_sklad_kg","aktualny_sklad_finalny_kg"):
        prod = val("nazov_vyrobku")
        ean  = val("ean")
        qty  = val("stock_kg","centralny_sklad_kg","aktualny_sklad_finalny_kg")
        what = prod or (f"EAN {ean}" if ean else "položky")
        return f"Na sklade je pre {what} {_fmt_num(qty,3)} kg."

    # --- 5) Roznesené kg ---
    if has("total_goods_out_kg","goods_out_kg"):
        v = val("total_goods_out_kg","goods_out_kg")
        return f"Celkovo bolo roznesených {_fmt_num(v,3)} kg tovaru."

    # --- 6) Univerzálny fallback (krátka veta) ---
    cols = list(r0.keys())[:4]
    kvs = ", ".join(f"{c}: {r0[c]}" for c in cols)
    return f"Našiel som {len(rows)} riadkov; prvý riadok: {kvs}."

# === Pamäť + logovanie =======================================================
def _load_session(cid: str) -> Dict[str, Any]:
    r = db_connector.execute_query(
        "SELECT memory_json FROM assistant_sessions WHERE conversation_id=%s",
        (cid,), fetch="one"
    ) or {}
    try:
        return json.loads(r.get("memory_json") or "{}") or {"entities": {}}
    except Exception:
        return {"entities": {}}

def _save_session(cid: str, user_id: Any, mem: Dict[str, Any]) -> None:
    db_connector.execute_query(
        "INSERT INTO assistant_sessions(conversation_id, user_id, memory_json, last_seen) "
        "VALUES (%s,%s,%s,NOW()) "
        "ON DUPLICATE KEY UPDATE user_id=VALUES(user_id), memory_json=VALUES(memory_json), last_seen=NOW()",
        (cid, user_id, json.dumps(mem, ensure_ascii=False)), fetch="none"
    )

def _log(user_id: Any, question: str, used_sql: Optional[str], row_count: int, error: Optional[str]) -> None:
    try:
        db_connector.execute_query(
            "INSERT INTO assistant_query_log(created_at, user_id, question, used_sql, row_count, error) "
            "VALUES (NOW(), %s, %s, %s, %s, %s)",
            (user_id, question, used_sql, row_count, error), fetch="none"
        )
    except Exception:
        pass

# === Gemini volanie s retry/fallback ========================================
def _call_llm_with_model(prompt: str, model_name: str) -> str:
    if GENAI_USE_SQL_MIME:
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                generation_config={"response_mime_type": "application/sql"},
            )
            return (getattr(resp, "text", None) or str(resp)).strip()
        except Exception:
            pass
    resp = client.models.generate_content(model=model_name, contents=prompt)
    return (getattr(resp, "text", None) or str(resp)).strip()

def _call_llm(prompt: str) -> str:
    models = _prioritized_models()
    last_err = None
    for attempt in range(GENAI_MAX_RETRIES):
        if attempt > 0 and len(models) > 1:
            head, rest = models[0], models[1:]
            random.shuffle(rest)
            models = [head] + rest
        for m in models:
            try:
                return _call_llm_with_model(prompt, m)
            except Exception as e:
                em = str(e)
                if "NOT_FOUND" in em or "404" in em:
                    last_err = e
                    continue
                if "429" in em or "RESOURCE_EXHAUSTED" in em:
                    last_err = e
                    back_ms = ((2 ** attempt) * GENAI_RETRY_BASE_MS) + random.randint(0, 250)
                    time.sleep(back_ms / 1000.0)
                    continue
                raise
    raise RuntimeError(f"GENAI_429_OR_MODEL_UNAVAILABLE: {last_err or 'exhausted/not found'}")

def _repair_sql(bad_sql: str, schema_md: str) -> Optional[str]:
    prompt = (
        "ÚLOHA: Dostal si kandidátske SQL, ktoré môže byť poškodené alebo mať nalepený text.\n"
        "Vráť IBA jeden platný SELECT/CTE v bloku ```sql ...```.\n"
        f"SCHEMA_PROMPT:\n{schema_md}\n"
        f"KANDIDÁTSKE_SQL:\n```sql\n{bad_sql}\n```\n"
    )
    try:
        raw = _call_llm(prompt)
        fixed = _extract_sql_only(raw)
        return fixed
    except Exception:
        return None

# === Pomocné „funkcie“ (FUNC:) ==============================================
def _func_resolve_vehicle_id(args: Dict[str, Any]) -> Dict[str, Any]:
    plate = (args.get("plate") or "").strip()
    if not plate:
        return {"error": "Chýba 'plate'."}
    norm = re.sub(r"[\s\-]", "", plate).upper()
    row = db_connector.execute_query(
        "SELECT id, license_plate, name FROM fleet_vehicles "
        "WHERE REPLACE(REPLACE(UPPER(license_plate),' ',''),'-','') = %s LIMIT 1",
        (norm,), fetch="one"
    ) or {}
    if not row:
        return {"rows": [], "row_count": 0, "html": f"<p>Nenašiel som vozidlo pre EČV <b>{html.escape(plate)}</b>.</p>"}
    html_snip = f"<p>Nájdené vozidlo: <b>{html.escape(row['license_plate'])}</b> — {html.escape(row.get('name',''))} (id={row['id']}).</p>"
    return {"rows": [row], "row_count": 1, "html": html_snip}

def _func_resolve_product_ean(args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "Chýba 'name'."}
    q = "%" + name.lower() + "%"
    rows = db_connector.execute_query(
        "SELECT ean, nazov_vyrobku, aktualny_sklad_finalny_kg "
        "FROM produkty WHERE LOWER(nazov_vyrobku) LIKE %s ORDER BY aktualny_sklad_finalny_kg DESC LIMIT 10",
        (q,), fetch="all"
    ) or []
    if not rows:
        return {"rows": [], "row_count": 0, "html": f"<p>Nenašiel som produkt podľa názvu <b>{html.escape(name)}</b>.</p>"}
    tbl = _rows_to_html(rows, None)
    return {"rows": rows, "row_count": len(rows), "html": "<p>Možné zhody podľa názvu:</p>" + tbl}

_FUNC_REGISTRY = {
    "resolve_vehicle_id": _func_resolve_vehicle_id,
    "resolve_product_ean": _func_resolve_product_ean,
}

# === Verejná funkcia =========================================================
def ask_gemini_agent(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    *,
    conversation_id: Optional[str] = None,
    user_id: Optional[Any] = None,
    confirm: bool = False,
) -> Dict[str, Any]:
    """
    Vráti JSON pre frontend:
      { answer, answer_html, used_sql, result_meta, data:{columns,rows}, (pending_write)? (needs_clarification)? }
    """
    cid = conversation_id or "default"
    q   = (question or "").strip()
    if not q:
        return {"answer":"", "answer_html":"", "used_sql":None, "result_meta":{}}

    schema_md   = get_schema_prompt()
    memory      = _load_session(cid) or {"entities": {}}

    memory_hint = ""
    if memory.get("entities"):
        try:
            memory_hint = "\nKONTEXT_PAMÄŤ: " + json.dumps(memory["entities"], ensure_ascii=False) + "\n"
        except Exception:
            pass

    prompt = f"{SYSTEM}\nSCHEMA_PROMPT:\n{schema_md}\n{memory_hint}\nOTÁZKA:\n{q}"
    try:
        raw = _call_llm(prompt)
    except Exception as e:
        em = str(e)
        if "GENAI_429" in em or "RESOURCE_EXHAUSTED" in em or "MODEL_UNAVAILABLE" in em or "NOT_FOUND" in em:
            msg = "Služba modelu je dočasne preťažená alebo model nie je dostupný. Skúste to znova o chvíľu."
            return {"answer": msg, "answer_html": f"<p>{html.escape(msg)}</p>", "used_sql": None,
                    "result_meta": {"model_used": PRIMARY_MODEL, "retry": GENAI_MAX_RETRIES}}
        raise

    # ASK / FUNC / SQL
    mode, ask_q, func_t = _detect_ask_or_func(raw)
    if mode == "ask" and ask_q:
        return {
            "answer": ask_q,
            "answer_html": f"<p><b>Upresni prosím:</b> {html.escape(ask_q)}</p>",
            "used_sql": None,
            "needs_clarification": True,
            "result_meta": {"model_used": PRIMARY_MODEL}
        }
    if mode == "func" and func_t:
        name, args = func_t
        fn = _FUNC_REGISTRY.get(name)
        if not fn:
            msg = f"Neznáma pomocná funkcia: {name}"
            return {"answer": msg, "answer_html": f"<p>{html.escape(msg)}</p>", "used_sql": None, "result_meta": {"model_used": PRIMARY_MODEL}}
        res = fn(args or {})
        html_snip = res.get("html") or ""
        rows = res.get("rows") or []
        rc   = int(res.get("row_count") or 0)
        sentence = _nlg_sentence(q, rows)
        return {
            "answer": sentence,
            "answer_html": f"<p class='ai-meta'>{html.escape(sentence)}</p>" + (html_snip or _rows_to_html(rows, None)),
            "used_sql": None,
            "result_meta": {"row_count": rc, "model_used": PRIMARY_MODEL},
            "data": {"columns": (list(rows[0].keys()) if rows else []), "rows": rows[:1000]}
        }

    # SQL vetva
    sql = _extract_sql_only(raw)
    if not sql:
        _log(user_id, q, None, 0, "sql_not_found")
        msg = "Model nevygeneroval použiteľný SQL dotaz. Skús otázku upresniť (tabuľky, polia)."
        return {"answer": msg, "answer_html": f"<p>{html.escape(msg)}</p>", "used_sql": None, "result_meta": {"model_used": PRIMARY_MODEL}}
    sql = sql.strip().rstrip(";")

    kind = _classify_sql(sql)

    # === WRITE (len ak povolené a potvrdené) ================================
    if kind == "write":
        if not ALLOW_WRITES:
            _log(user_id, q, None, 0, "write_disabled")
            msg = "Zápisy do DB sú vypnuté. Ak ich chceš používať, nastav AI_ALLOW_WRITES=true a použi potvrdenie."
            return {"answer": msg, "answer_html": f"<p>{html.escape(msg)}</p>", "used_sql": None, "result_meta": {"model_used": PRIMARY_MODEL}}
        if not confirm:
            return {
                "answer": "Návrh na zápis je pripravený. Potvrdiť vykonanie?",
                "answer_html": f"<div class='ai-warn'><b>POZOR:</b> Návrh na zápis do DB. Je potrebné potvrdenie.</div>"
                               f"<details class='ai-sql'><summary>SQL (návrh)</summary><pre>{html.escape(sql)}</pre></details>",
                "pending_write": {"sql": sql},
                "used_sql": None,
                "result_meta": {"row_count": 0, "model_used": PRIMARY_MODEL}
            }
        exec_res = vykonaj_dml_sql(sql)
        if exec_res.get("error"):
            _log(user_id, q, sql, 0, exec_res["error"])
            return {
                "answer": f"Chyba zápisu: {exec_res['error']}",
                "answer_html": f"<p><b>Chyba zápisu:</b> {html.escape(exec_res['error'])}</p>"
                               f"<details class='ai-sql'><summary>SQL</summary><pre>{html.escape(sql)}</pre></details>",
                "used_sql": sql,
                "result_meta": {"row_count": 0, "model_used": PRIMARY_MODEL}
            }
        affected = exec_res.get("affected_rows")
        _log(user_id, q, sql, affected if isinstance(affected, int) else -1, None)
        msg = f"Zápis vykonaný. Ovl. riadkov: {affected if affected is not None else 'neznáme'}."
        return {
            "answer": msg,
            "answer_html": f"<p>{html.escape(msg)}</p><details class='ai-sql'><summary>SQL</summary><pre>{html.escape(sql)}</pre></details>",
            "used_sql": sql,
            "result_meta": {"row_count": affected if isinstance(affected, int) else 0, "model_used": PRIMARY_MODEL}
        }

    # === SELECT-only: doplň LIMIT, spusti ===================================
    if kind != "select":
        _log(user_id, q, sql, 0, "unsafe_sql")
        msg = "Z bezpečnostných dôvodov vykonávam len SELECT (vrátane WITH)."
        return {"answer": msg, "answer_html": f"<p>{html.escape(msg)}</p>", "used_sql": None, "result_meta": {"model_used": PRIMARY_MODEL}}

    sql_final = _force_limit(sql, ROW_LIMIT_DEFAULT)
    res = vykonaj_bezpecny_sql_prikaz(sql_final, limit_default=ROW_LIMIT_DEFAULT)
    if res.get("error"):
        err = str(res["error"])
        if re.search(r"syntax|You have an error in your SQL", err, re.IGNORECASE):
            fixed = _repair_sql(sql_final, schema_md)
            if fixed and _classify_sql(fixed) == "select":
                sql_final = _force_limit(fixed, ROW_LIMIT_DEFAULT)
                res = vykonaj_bezpecny_sql_prikaz(sql_final, limit_default=ROW_LIMIT_DEFAULT)

        if res.get("error"):
            _log(user_id, q, sql_final, 0, res["error"])
            return {
                "answer": f"Chyba SQL: {res['error']}",
                "answer_html": f"<p><b>Chyba SQL:</b> {html.escape(res['error'])}</p>"
                               f"<details class='ai-sql'><summary>SQL</summary><pre>{html.escape(sql_final)}</pre></details>",
                "used_sql": sql_final,
                "result_meta": {"row_count": 0, "model_used": PRIMARY_MODEL}
            }

    rows = res.get("rows") or []
    rc   = int(res.get("row_count") or 0)
    _log(user_id, q, sql_final, rc, None)

    # jednoduchá pamäť – drobné entity
    try:
        memory.setdefault("entities", {})
        for tok in re.findall(r"\b\d{8,14}\b", q):
            memory["entities"][tok] = memory["entities"].get(tok, 0) + 1
        _save_session(cid, user_id, memory)
    except Exception:
        pass

    # >>> NLG veta (celou vetou)
    sentence = _nlg_sentence(q, rows)
    html_tbl = _rows_to_html(rows, sql_final)

    return {
        "answer": sentence,
        "answer_html": f"<p class='ai-meta'>{html.escape(sentence)}</p>" + html_tbl,
        "used_sql": sql_final,
        "result_meta": {"row_count": rc, "model_used": PRIMARY_MODEL, "memory": memory.get("entities", {})},
        "data": {"columns": res.get("columns") or (list(rows[0].keys()) if rows else []), "rows": rows[:1000]}
    }
