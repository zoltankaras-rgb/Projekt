# services/ai_tasks.py
# -------------------------------------------------------------------
# LOGIKA PRE PLÁNOVANÉ ÚLOHY A NÁHĽADY (AI → SQL → TABUĽKA → MAIL)
# - preview_nl(question, conversation_id)
# - run_task(task_id, idempotency_key=None, throttle_seconds=10)
# - build_cron_expr(kind, time_str=None, dow=None, dom=None)
# + mail & html helpery
# -------------------------------------------------------------------
from __future__ import annotations
import uuid
import re
import html as py_html
from typing import Any, Dict, List, Optional

from flask import current_app
from flask_mail import Message

import db_connector
from gemini_agent import ask_gemini_agent

# ───────────────────────── HTML / MAIL HELPERY ─────────────────────────
# --- FRIENDLY RENDER (ľudské hlavičky + formátovanie buniek) -----------------

def _friendly_header(name: str) -> str:
    n = (name or "").lower()
    mapping = {
        "promotion_name": "Akcia",
        "product_name": "Výrobok",
        "product_ean": "EAN",
        "nazov_vyrobku": "Názov výrobku",
        "retail_chain": "Reťazec",
        "retail_chain_name": "Reťazec",
        "sale_price_net": "Cena bez DPH (€)",
        "price_eur_kg": "Cena €/kg",
        "start_date": "Začiatok",
        "end_date": "Koniec",
        "message": "Poznámka",
        "sales_kg": "Predaj (kg)",
        "centralny_sklad_kg": "Sklad (kg)",
        "stock_kg": "Sklad (kg)",
        "total_km": "Najazdené km",
        "km_driven": "Najazdené km",
        "total_km_by_sum": "Najazdené km (súčet)",
        "total_km_fallback": "Najazdené km (výkaz)",
        "l_per_100km": "Spotreba (l/100 km)",
        "device_name": "Zariadenie",
        "max_temp_c": "Max teplota (°C)",
        "at_timestamp": "Čas merania",
    }
    return mapping.get(n, name)

def _fmt_num(x, *, auto_dec=True) -> str:
    try:
        v = float(x)
        if not auto_dec:
            return f"{v:,.2f}".replace(",", " ")
        # menej ako 1 → 3 desatinné, inak 2
        d = 3 if abs(v) < 1 else 2
        return f"{v:,.{d}f}".replace(",", " ")
    except Exception:
        return "" if x is None else str(x)

# PÔVODNÚ _render_table_friendly NAHRAĎ TOUTO VERZIOU:

def _render_table_friendly(columns, rows, max_rows=200) -> str:
    rows = rows or []
    cols = [str(c) for c in (columns or (list(rows[0].keys()) if rows else []))]

    # hlavičky (preložené)
    thead = "<thead><tr>" + "".join(
        f"<th style='text-align:left;padding:8px;border-bottom:1px solid #e5e7eb;background:#f6f8fa'>{py_html.escape(_friendly_header(c))}</th>"
        for c in cols
    ) + "</tr></thead>"

    def _cell_style(k: str) -> str:
        kl = k.lower()
        # dátumy nedovoľ zalomiť
        if "date" in kl or k in ("Začiatok","Koniec"):
            return "padding:8px;border-bottom:1px solid #eee;white-space:nowrap"
        return "padding:8px;border-bottom:1px solid #eee"

    def _cell_val(k: str, v):
        kl = k.lower()
        if v is None:
            return ""
        if any(t in kl for t in ("price", "eur")):
            return _fmt_eur(v)
        if any(t in kl for t in ("kg", "km", "qty", "mnoz", "amount")):
            return _fmt_num(v)
        # reformátuj YYYY-MM-DD
        if "date" in kl:
            s = str(v)
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
            return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else py_html.escape(s)
        return py_html.escape(str(v))

    body_rows = []
    for r in rows[:max_rows]:
        tds = "".join(f"<td style='{_cell_style(c)}'>{_cell_val(c, r.get(c))}</td>" for c in cols)
        body_rows.append(f"<tr>{tds}</tr>")
    tbody = "<tbody>" + "".join(body_rows) + "</tbody>"

    return f"<table cellspacing='0' cellpadding='0' border='0' style='border-collapse:collapse;width:100%;font:13px Segoe UI,Arial,Helvetica,sans-serif'>{thead}{tbody}</table>"

def _compose_generic_intro(rows: List[dict]) -> str:
    """Krátka súvislá veta pre 'ne-promo' výsledky."""
    if not rows:
        return "Nenašiel som žiadne záznamy pre zadané podmienky."
    r0 = rows[0]
    # KM / vozidlo
    veh = r0.get("license_plate") or r0.get("name")
    km = r0.get("total_km_by_sum") or r0.get("total_km") or r0.get("km_driven") or r0.get("km") or r0.get("total_km_fallback")
    if veh and km is not None:
        return f"Vozidlo <b>{py_html.escape(str(veh))}</b> najazdilo { _fmt_num(km) } km v danom období."
    # Teploty
    t = r0.get("max_temp_c") or r0.get("temperature")
    dev = r0.get("device_name")
    ts  = r0.get("at_timestamp")
    if t is not None:
        meta = []
        if dev: meta.append(py_html.escape(str(dev)))
        if ts:  meta.append(py_html.escape(str(ts)))
        meta_txt = f" – {'; '.join(meta)}" if meta else ""
        return f"Najvyššia zaznamenaná teplota je <b>{_fmt_num(t)}</b> °C{meta_txt}."
    # Sklad
    stock = r0.get("stock_kg") or r0.get("centralny_sklad_kg")
    if stock is not None:
        pn = r0.get("product_name") or r0.get("nazov_vyrobku")
        suffix = f" – {py_html.escape(str(pn))}" if pn else ""
        return f"Na sklade je <b>{_fmt_num(stock)}</b> kg{suffix}."
    # Fallback
    preview = ", ".join(f"{py_html.escape(str(k))}: {py_html.escape(str(v))}" for k, v in list(r0.items())[:6])
    return f"Našiel som {len(rows)} riadok/riadky. Prvý: {preview}."

def _fmt_eur(v) -> str:
    try:
        return f"{float(v):.2f} €".replace(".", ",")
    except Exception:
        return f"{v} €"

def _rows_to_html_table(columns, rows, max_rows=200):
    rows = rows or []
    if not rows:
        return "<div style='padding:.5rem;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px'>Žiadne riadky.</div>"
    thead = "<thead><tr>" + "".join(
        f"<th style='text-align:left;padding:6px 8px;border-bottom:1px solid #eee'>{py_html.escape(str(c))}</th>"
        for c in columns
    ) + "</tr></thead>"
    body = []
    for r in rows[:max_rows]:
        tds = "".join(f"<td style='padding:6px 8px;border-bottom:1px solid #eee'>{py_html.escape(str(r.get(c,'')))}</td>" for c in columns)
        body.append(f"<tr>{tds}</tr>")
    tbody = "<tbody>" + "".join(body) + "</tbody>"
    return f"<div style='max-height:60vh;overflow:auto;border:1px solid #e5e7eb;border-radius:10px'><table style='border-collapse:collapse;width:100%;font-size:13px'>{thead}{tbody}</table></div>"

def _send_task_email(to_addr: str, subject: str, html_body: str, csv_bytes: bytes = None, csv_name: str = "report.csv") -> bool:
    mail = current_app.extensions.get('mail') or globals().get('mail')
    if not mail:
        raise RuntimeError("Flask-Mail nie je inicializovaný (mail).")
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or current_app.config.get("MAIL_USERNAME")
    if isinstance(sender, (list, tuple)):
        sender = sender[0]
    msg = Message(subject=subject, recipients=[to_addr], sender=sender)
    msg.html = html_body
    if csv_bytes:
        msg.attach(filename=csv_name, content_type="text/csv", data=csv_bytes)
    with current_app.app_context():
        mail.send(msg)
    return True

def _strip_html_to_text(s: str) -> str:
    if not s: return ""
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.I|re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:600]

# PÔVODNÚ _is_promotions_result A _compose_promotions_intro VYMEŇ ZA TOTO:

def _is_promotions_result(columns) -> tuple[bool, dict]:
    """
    Vráti (is_promo, colmap).
    - is_promo = True, ak máme aspoň produkt + cenu a aspoň jeden z (start,end).
    - colmap: mapovanie štandardných kľúčov -> reálne názvy v dátach.
    """
    cols = [str(c).lower() for c in (columns or [])]
    s = set(cols)

    def pick(cands):
        for c in cands:
            if c in s:
                return c
        return None

    colmap = {
        "product": pick(["product_name","nazov_vyrobku","name","bp.product_name"]),
        "price":   pick(["sale_price_net","price_eur_kg","bp.sale_price_net"]),
        "start":   pick(["start_date","bp.start_date"]),
        "end":     pick(["end_date","bp.end_date"]),
        "chain":   pick(["retail_chain_name","retail_chain","chain_name","bp.chain_name","brc.name"]),
        "note":    pick(["message","upozornenie","note","poznámka","poznamka"]),
    }
    has_min = bool(colmap["product"] and colmap["price"] and (colmap["start"] or colmap["end"]))
    return has_min, colmap


def _compose_promotions_intro(rows: List[dict], colmap: dict) -> str:
    """Jedna zmysluplná veta + krátky výpočet položiek (prvé 3)."""
    rows = rows or []
    if not rows:
        return "<p>Dobrý deň,</p><p>Aktuálne nie sú evidované žiadne akcie.</p><p>S pozdravom<br>Váš AI asistent</p>"

    # reťazec – ak vieme
    chains = sorted({str(r.get(colmap["chain"]) or "") for r in rows if colmap.get("chain") and r.get(colmap["chain"])})
    chain_txt = f" v <b>{py_html.escape(chains[0])}</b>" if len(chains) == 1 else ""

    # prvé 3 položky do „výčtu“
    items = []
    for r in rows[:3]:
        prod  = r.get(colmap["product"])
        price = r.get(colmap["price"])
        sdate = r.get(colmap["start"])
        edate = r.get(colmap["end"])
        note  = (r.get(colmap["note"]) or "").strip() if colmap.get("note") else ""
        # formát dátumu (YYYY-MM-DD → DD.MM.YYYY)
        def fmt_d(d):
            if not d: return ""
            ds = str(d)
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", ds)
            return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else ds
        when = f" ({fmt_d(sdate)} – {fmt_d(edate)})" if (sdate or edate) else ""
        piece = f"{py_html.escape(str(prod))} <b>{_fmt_eur(price)}</b>{when}"
        if note:
            piece += f" – {py_html.escape(note)}"
        items.append(piece)

    extra = ""
    if len(rows) > 3:
        extra = f", +{len(rows)-3} ďalšie položky"

    # finálna veta + zdvorilosti
    line = f"Prebieha akcia{chain_txt}: " + "; ".join(items) + extra + "."
    return f"<p>Dobrý deň,</p><p>{line}</p><p>S pozdravom<br>Váš AI asistent</p>"

def _compose_promotions_intro(rows) -> str:
    rows = rows or []
    chains = sorted({str(r.get("retail_chain_name") or "") for r in rows if r.get("retail_chain_name")})
    if len(chains) == 1:
        hdr = f"Prebiehajúce akcie pre <b>{py_html.escape(chains[0])}</b>:"
    else:
        hdr = "Prebiehajúce akcie (k dnešnému dňu):"
    items = []
    for r in rows:
        chain   = str(r.get("retail_chain_name") or "").strip()
        prod    = str(r.get("product_name") or "").strip()
        price   = _fmt_eur(r.get("sale_price_net"))
        start   = str(r.get("start_date") or "").strip()
        end     = str(r.get("end_date") or "").strip()
        items.append(
            f"<li><b>{py_html.escape(chain)}</b> – {py_html.escape(prod)} za <b>{price}</b> "
            f"(od {py_html.escape(start)} do {py_html.escape(end)})</li>"
        )
    lst = "<ul>" + "".join(items) + "</ul>" if items else "<p>(Žiadne aktuálne akcie)</p>"
    return (
        "<p>Dobrý deň,</p>"
        f"<p>{hdr}</p>"
        f"{lst}"
        "<p><i>Nezabudnite zmeniť predajné ceny!</i></p>"
        "<p>S pozdravom<br>Váš AI asistent</p>"
    )

# ───────────────────────── CRON / SCHEDULE ─────────────────────────

_DOW_MAP = {
    "po":1, "ut":2, "st":3, "št":4, "stvrtok":4, "pia":5, "so":6, "ne":0,
    "mon":1, "monday":1, "tue":2, "tuesday":2, "wed":3, "wednesday":3,
    "thu":4, "thursday":4, "fri":5, "friday":5, "sat":6, "saturday":6,
    "sun":0, "sunday":0,
}

def _parse_hhmm(s: str):
    m = re.match(r'^\s*(\d{1,2}):(\d{2})\s*$', s or "")
    if not m: raise ValueError("Čas musí byť vo formáte HH:MM")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60): raise ValueError("Neplatný čas")
    return mi, h

def build_cron_expr(kind: str, *, time_str: str = None, dow: str|int = None, dom: int = None) -> str:
    kind = (kind or "").lower()
    if kind == "every_5m":   return "*/5 * * * *"
    if kind == "every_30m":  return "*/30 * * * *"
    if kind == "daily":
        mi, h = _parse_hhmm(time_str or "")
        return f"{mi} {h} * * *"
    if kind == "weekly":
        mi, h = _parse_hhmm(time_str or "")
        if isinstance(dow, str): d = _DOW_MAP.get(dow.strip().lower())
        else: d = int(dow) if dow is not None else None
        if d is None or not (0 <= int(d) <= 6): raise ValueError("Neplatný deň v týždni (0-6 alebo skratka)")
        return f"{mi} {h} * * {int(d)}"
    if kind == "monthly":
        mi, h = _parse_hhmm(time_str or "")
        d = int(dom or 0)
        if not (1 <= d <= 31): raise ValueError("Deň v mesiaci 1-31")
        return f"{mi} {h} {d} * *"
    if kind == "custom_cron":
        return (time_str or "").strip()
    raise ValueError("Neznámy typ rozvrhu")

# ───────────────────────── PREVIEW (AI → náhľad) ─────────────────────────

def preview_nl(*, question: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
    conv_id = conversation_id or f"task_preview_{uuid.uuid4().hex[:10]}"
    out = ask_gemini_agent(question, history=[], conversation_id=conv_id, confirm=False)
    columns = (out.get("data") or {}).get("columns") or []
    rows    = (out.get("data") or {}).get("rows") or []
    row_count = int(out.get("result_meta", {}).get("row_count") or len(rows))
    sql_block = (
        "<details><summary>SQL</summary>"
        f"<pre style='background:#0b1020;color:#e5e7eb;padding:.5rem;border-radius:8px;overflow:auto'>{py_html.escape(out.get('used_sql') or '')}</pre>"
        "</details>"
    )
    email_html = f"<h3 style='margin:0 0 .5rem 0'>Náhľad výsledku</h3>{out.get('answer_html','')}{sql_block}"
    return {
        "answer": out.get("answer") or "",
        "answer_html": out.get("answer_html") or "",
        "row_count": row_count,
        "columns": columns,
        "rows": rows[:200],
        "used_sql": out.get("used_sql"),
        "email_html": email_html,
        "needs_clarification": bool(out.get("needs_clarification")),
        "pending_write": bool(out.get("pending_write")),
    }

# ───────────────────────── RUN (úloha → mail) ─────────────────────────

def run_task(task_id: int, *, idempotency_key: str | None = None, throttle_seconds: int = 10) -> Dict[str, Any]:
    # LOCK (ak padne, neblokuj)
    lock_name = f"auto_task_lock_{int(task_id)}"
    try:
        got = db_connector.execute_query("SELECT GET_LOCK(%s, 0) AS ok", (lock_name,), fetch="one")
        if not got or int(got.get("ok") or 0) != 1:
            return {"ok": False, "message": f"Úloha {task_id} práve beží (LOCK)."}
    except Exception:
        pass

    try:
        task = db_connector.execute_query(
            "SELECT id, nazov_ulohy, popis_ulohy_pre_ai, cron_retazec, email_adresata, sql_text, is_enabled "
            "FROM automatizovane_ulohy WHERE id=%s",
            (task_id,), fetch="one"
        )
        if not task:
            return {"ok": False, "message": f"Úloha {task_id} neexistuje."}

        title    = task.get("nazov_ulohy") or f"Úloha {task_id}"
        email_to = (task.get("email_adresata") or "").strip()
        question = (task.get("popis_ulohy_pre_ai") or "").strip()
        sql_text = (task.get("sql_text") or "").strip()

        # throttle
        try:
            last = db_connector.execute_query(
                "SELECT executed_at FROM automatizovane_ulohy_log WHERE task_id=%s ORDER BY executed_at DESC LIMIT 1",
                (task_id,), fetch="one"
            ) or {}
            if last and last.get("executed_at") is not None:
                diff_row = db_connector.execute_query(
                    "SELECT TIMESTAMPDIFF(SECOND, %s, NOW()) AS diff",
                    (last["executed_at"],), fetch="one"
                ) or {}
                diff = int(diff_row.get("diff") or 9999)
                if diff < int(throttle_seconds):
                    msg = f"Úloha {task_id} throttled ({diff}s < {throttle_seconds}s); mail skip."
                    try:
                        db_connector.execute_query(
                            "INSERT INTO automatizovane_ulohy_log(task_id, executed_at, row_count, summary) "
                            "VALUES (%s, NOW(), %s, %s)",
                            (task_id, 0, f"email: {email_to or '-'}, riadkov: 0 | MAIL: SKIPPED (throttled {diff}s)"),
                            fetch="none"
                        )
                    except Exception:
                        pass
                    return {"ok": False, "message": msg}
        except Exception:
            pass

        # idempotency
        if idempotency_key:
            dup = db_connector.execute_query(
                "SELECT 1 AS x FROM automatizovane_ulohy_log "
                "WHERE task_id=%s AND executed_at >= NOW() - INTERVAL 1 HOUR "
                "AND summary LIKE %s LIMIT 1",
                (task_id, f"%IDEMP:{idempotency_key}%"), fetch="one"
            )
            if dup:
                return {"ok": False, "message": f"Úloha {task_id}: duplicitný idempotency_key → SKIP."}

        # dáta
        columns, rows, row_count = [], [], 0
        sql_err, used_sql, answer_html = None, None, ""
        needs_clar = False

        try:
            if question and not sql_text:
                out = ask_gemini_agent(question, history=[], conversation_id=f"task_{task_id}", confirm=False)
                needs_clar  = bool(out.get("needs_clarification"))
                answer_html = out.get("answer_html") or ""
                used_sql    = out.get("used_sql") or ""
                data        = out.get("data") or {}
                columns     = data.get("columns") or []
                rows        = data.get("rows") or []
                row_count   = int(out.get("result_meta", {}).get("row_count") or len(rows))
            else:
                if sql_text:
                    from nastroje_ai import vykonaj_bezpecny_sql_prikaz
                    res = vykonaj_bezpecny_sql_prikaz(sql_text, limit_default=5000)
                    if res.get("error"):
                        sql_err = str(res["error"])
                    else:
                        columns   = res.get("columns") or []
                        rows      = res.get("rows") or []
                        row_count = int(res.get("row_count") or 0)
                        used_sql  = sql_text
                else:
                    columns, rows, row_count = [], [], 0
        except Exception as e:
            sql_err = f"Výnimka: {e}"

        # e-mail HTML (pozdrav → veta → pekná tabuľka → malý SQL)
                # e-mail HTML (pozdrav → veta → pekná tabuľka; SQL NEPOSIELAME)
        if sql_err:
            body = (
                f"<div style='font:14px Segoe UI,Arial,Helvetica,sans-serif;color:#111'>"
                f"<h2 style='margin:0 0 10px 0'>{py_html.escape(title)}</h2>"
                f"<p style='margin:0 0 10px 0;color:#b91c1c'><b>Chyba:</b> {py_html.escape(sql_err)}</p>"
                f"<p style='color:#6b7280;font-size:12px;margin-top:12px'>S pozdravom<br>Váš AI asistent</p>"
                f"</div>"
            )
        else:
            is_promo, colmap = _is_promotions_result(columns)
            if is_promo:
                intro_html = _compose_promotions_intro(rows, colmap)
                # premapuj stĺpce pre tabuľku do príjemného poradia
                order = [c for c in [colmap["product"], colmap["price"], colmap["start"], colmap["end"], colmap["note"]] if c]
                # urob shallow kópie s výberom poradia
                tbl_cols = order
                tbl_rows = [{k: r.get(k) for k in order} for r in rows]
                table_html = _render_table_friendly(tbl_cols, tbl_rows)
            else:
                intro_html = f"<p>Dobrý deň,</p><p>{_compose_generic_intro(rows)}</p><p>S pozdravom<br>Váš AI asistent</p>"
                table_html = _render_table_friendly(columns, rows)

            body = (
                f"<div style='font:14px Segoe UI,Arial,Helvetica,sans-serif;color:#111'>"
                f"<h2 style='margin:0 0 10px 0'>{py_html.escape(title)}</h2>"
                f"{intro_html}"
                f"{table_html}"
                f"</div>"
            )


        # odoslanie
        mail_status, mail_error = "SKIPPED", None
        if email_to:
            try:
                if not needs_clar:
                    # ľudský subject
                    suffix = f" – položky: {row_count}"
                    subject = f"[Asistent Mik] {title}{suffix}"
                    _send_task_email(email_to, subject, body, csv_bytes=None)
                    mail_status = "SENT OK"
                else:
                    mail_status = "SKIPPED (needs_clarification)"
            except Exception as e:
                mail_status, mail_error = "ERROR", str(e)

        # log
        idem_tag = f" | IDEMP:{idempotency_key}" if idempotency_key else ""
        summary = f"email: {email_to or '-'}, riadkov: {row_count}"
        if sql_err:
            summary += f" | SQL ERROR: {sql_err}"
        summary += f" | MAIL: {mail_status}{idem_tag}"
        if mail_error:
            summary += f" ({mail_error})"
        try:
            db_connector.execute_query(
                "INSERT INTO automatizovane_ulohy_log(task_id, executed_at, row_count, summary) VALUES (%s, NOW(), %s, %s)",
                (task_id, row_count, summary), fetch="none"
            )
        except Exception:
            pass

        if sql_err:
            return {"ok": False, "message": f"Úloha {task_id} zlyhala – {summary}"}
        if needs_clar:
            return {"ok": False, "message": f"Úloha {task_id} potrebuje upresniť – {summary}"}
        if mail_status != "SENT OK":
            return {"ok": False, "message": f"Úloha {task_id} vykonaná – {summary}"}
        return {"ok": True, "message": f"Úloha {task_id} vykonaná – {summary}"}

    finally:
        try:
            db_connector.execute_query("SELECT RELEASE_LOCK(%s)", (lock_name,), fetch="none")
        except Exception:
            pass
