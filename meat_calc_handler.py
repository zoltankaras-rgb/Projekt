# =================================================================
# === HANDLER: KALKULÁTOR ROZRÁBKY MÄSA ===========================
# =================================================================
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import io

from flask import jsonify, make_response, render_template, send_file
import db_connector

# ---------- UTIL --------------------------------------------------
def _to_decimal(x, nd:int=3):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None

def _now():
    return datetime.now()

def _parse_date_any(s: str) -> datetime.date:
    """Prijme 'YYYY-MM-DD', 'DD.MM.YYYY' aj 'YYYY-MM-DDTHH:MM'."""
    if not s:
        raise ValueError
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    # posledný pokus – orež len dátumovú časť
    try:
        return datetime.fromisoformat(s[:10]).date()
    except Exception:
        raise ValueError

# ---------- ČÍSELNÍKY --------------------------------------------
def list_materials():
    q = "SELECT * FROM meat_materials WHERE is_active=1 ORDER BY name"
    return jsonify(db_connector.execute_query(q) or [])

def save_material(data):
    # {id?, code, name, is_active?}
    code = (data.get('code') or '').strip()
    name = (data.get('name') or '').strip()
    if not code or not name:
        return {"error":"Chýba code alebo name."}
    is_active = 1 if str(data.get('is_active')) in ('1','true','True','on') else 1
    if data.get('id'):
        q = "UPDATE meat_materials SET code=%s,name=%s,is_active=%s WHERE id=%s"
        db_connector.execute_query(q, (code, name, is_active, int(data['id'])), fetch='none')
    else:
        q = "INSERT INTO meat_materials (code,name,is_active) VALUES (%s,%s,%s)"
        db_connector.execute_query(q, (code,name,is_active), fetch='none')
    return {"message":"Surovina uložená."}

def list_products():
    q = "SELECT * FROM meat_products WHERE is_active=1 ORDER BY name"
    return jsonify(db_connector.execute_query(q) or [])

def save_product(data):
    # {id?, code, name, selling_price_eur_kg, is_active?}
    code = (data.get('code') or '').strip()
    name = (data.get('name') or '').strip()
    price = _to_decimal(data.get('selling_price_eur_kg'), 3)
    if not code or not name or price is None:
        return {"error":"Code, name, selling_price_eur_kg sú povinné."}
    is_active = 1 if str(data.get('is_active')) in ('1','true','True','on') else 1
    if data.get('id'):
        q = "UPDATE meat_products SET code=%s,name=%s,selling_price_eur_kg=%s,is_active=%s WHERE id=%s"
        db_connector.execute_query(q, (code,name,price,is_active, int(data['id'])), fetch='none')
    else:
        q = "INSERT INTO meat_products (code,name,selling_price_eur_kg,is_active) VALUES (%s,%s,%s,%s)"
        db_connector.execute_query(q, (code,name,price,is_active), fetch='none')
    return {"message":"Produkt uložený."}

# ---------- PRICE LOCKS (zamknuté ceny po prvom zázname) ----------
def _ensure_price_locks(material_id:int, outputs:List[Dict[str,Any]]):
    """Zamkne ceny produktov použitých v rozrábke (ak lock neexistuje) na aktuálne predajné ceny."""
    pids = [int(o['product_id']) for o in outputs if o.get('product_id')]
    if not pids: return
    placeholders = ",".join(["%s"]*len(pids))
    locked = db_connector.execute_query(
        f"SELECT product_id FROM meat_price_lock WHERE material_id=%s AND product_id IN ({placeholders})",
        tuple([material_id] + pids)
    ) or []
    exists = {int(r['product_id']) for r in locked}
    to_lock = [pid for pid in pids if pid not in exists]
    if not to_lock: return
    placeholders = ",".join(["%s"]*len(to_lock))
    rows = db_connector.execute_query(
        f"SELECT id, selling_price_eur_kg FROM meat_products WHERE id IN ({placeholders})",
        tuple(to_lock)
    ) or []
    for r in rows:
        db_connector.execute_query(
            "INSERT INTO meat_price_lock (material_id, product_id, price_eur_kg) VALUES (%s,%s,%s)",
            (material_id, int(r['id']), float(r['selling_price_eur_kg'])),
            fetch='none'
        )

def list_locked_prices(material_id:int):
    rows = db_connector.execute_query("""
        SELECT p.id AS product_id, p.code, p.name,
               COALESCE(mpl.price_eur_kg, p.selling_price_eur_kg) AS price_eur_kg,
               CASE WHEN mpl.product_id IS NULL THEN 0 ELSE 1 END AS is_locked
        FROM meat_products p
        LEFT JOIN meat_price_lock mpl 
               ON mpl.product_id=p.id AND mpl.material_id=%s
        WHERE p.is_active=1
        ORDER BY p.name
    """,(int(material_id),)) or []
    return jsonify(rows)

def set_locked_price(material_id:int, product_id:int, price_eur_kg:float):
    ex = db_connector.execute_query(
        "SELECT 1 FROM meat_price_lock WHERE material_id=%s AND product_id=%s",
        (int(material_id), int(product_id))
    )
    if ex:
        db_connector.execute_query(
            "UPDATE meat_price_lock SET price_eur_kg=%s, locked_at=NOW() WHERE material_id=%s AND product_id=%s",
            (float(price_eur_kg), int(material_id), int(product_id)), fetch='none'
        )
    else:
        db_connector.execute_query(
            "INSERT INTO meat_price_lock (material_id,product_id,price_eur_kg) VALUES (%s,%s,%s)",
            (int(material_id), int(product_id), float(price_eur_kg)), fetch='none'
        )
    return {"message":"Cena aktualizovaná."}

# ---------- ULOŽENIE REÁLNEJ ROZRÁBKY -----------------------------
def save_breakdown(data):
    """
    data = {
      header:{ breakdown_date:'YYYY-MM-DD|DD.MM.YYYY|…', material_id, supplier?, note?, units_count?,
               input_weight_kg, purchase_total_cost_eur? OR purchase_unit_price_eur_kg?,
               tolerance_pct? },
      outputs:[{product_id, weight_kg}, ...],
      extras:[{name, amount_eur}, ...]
    }
    """
    header = data.get('header') or {}
    outputs = data.get('outputs') or []
    extras  = data.get('extras') or []

    # dátum – robustný parse
    try:
        bdate = _parse_date_any(header.get('breakdown_date'))
    except Exception:
        return {"error":"Neplatný dátum rozrábky."}

    material_id = header.get('material_id')
    input_w = _to_decimal(header.get('input_weight_kg'), 3)
    if not material_id or not input_w or input_w <= 0:
        return {"error":"Chýba material_id alebo input_weight_kg."}

    units_count = int(header.get('units_count') or 0) or None
    supplier    = (header.get('supplier') or '').strip() or None
    note        = (header.get('note') or '').strip() or None
    tolerance   = _to_decimal(header.get('tolerance_pct'), 3) or 0.0

    total_cost  = _to_decimal(header.get('purchase_total_cost_eur'), 2)
    unit_price  = _to_decimal(header.get('purchase_unit_price_eur_kg'), 4)
    if total_cost is None and unit_price is None:
        return {"error":"Zadaj buď celkovú nákupnú cenu alebo jednotkovú cenu €/kg."}
    if total_cost is None:
        total_cost = round(input_w * unit_price, 2)
    if unit_price is None:
        unit_price = round(total_cost / input_w, 4)

    # výstupy
    if not outputs:
        return {"error":"Musíš pridať aspoň jeden výstup."}
    sum_out = 0.0
    for o in outputs:
        w = _to_decimal(o.get('weight_kg'), 3)
        if not o.get('product_id') or w is None or w < 0:
            return {"error":"Neplatný výstup (product_id/weight_kg)."}
        sum_out += w
    diff = abs(sum_out - input_w)
    if input_w > 0 and (diff / input_w)*100 > tolerance:
        return {"error":f"Súčet výstupov ({sum_out} kg) nespĺňa toleranciu voči vstupu ({input_w} kg). Rozdiel {diff:.3f} kg."}

    # INSERT hlavičky – potrebujeme spoľahlivo lastrowid (rovnaká conn)
    qh = """INSERT INTO meat_breakdown
            (breakdown_date, material_id, supplier, note, units_count,
             input_weight_kg, purchase_unit_price_eur_kg, purchase_total_cost_eur, tolerance_pct)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
    bid = db_connector.execute_query(qh, (bdate, int(material_id), supplier, note, units_count,
                                    input_w, unit_price, total_cost, tolerance), fetch='lastrowid')

    # outputs
    for o in outputs:
        q = "INSERT INTO meat_breakdown_output (breakdown_id,product_id,weight_kg) VALUES (%s,%s,%s)"
        db_connector.execute_query(q, (bid, int(o['product_id']), _to_decimal(o['weight_kg'],3)), fetch='none')

    # extras
    for e in extras:
        if (e.get('name') or '').strip() and _to_decimal(e.get('amount_eur'),2) is not None:
            q = "INSERT INTO meat_breakdown_extra_costs (breakdown_id,name,amount_eur) VALUES (%s,%s,%s)"
            db_connector.execute_query(q, (bid, e['name'].strip(), _to_decimal(e.get('amount_eur'),2)), fetch='none')

    # auto-lock cien pre túto surovinu (len pre použité produkty)
    _ensure_price_locks(int(material_id), outputs)

    # prepočet
    compute_breakdown_results(bid)
    return {"message":"Rozrábka uložená.", "breakdown_id": bid}

# ---------- VÝPOČET: výťažnosti + nákladové ceny ------------------
def _fetch_breakdown_full(breakdown_id:int) -> Tuple[Dict[str,Any], List[Dict[str,Any]], List[Dict[str,Any]]]:
    b = db_connector.execute_query("SELECT * FROM meat_breakdown WHERE id=%s", (breakdown_id,)) or []
    if not b:
        raise ValueError("Neexistuje rozrábka.")
    header = b[0]
    outputs = db_connector.execute_query("""
        SELECT mbo.*,
               COALESCE(mpl.price_eur_kg, mp.selling_price_eur_kg) AS selling_price_eur_kg,
               mp.name AS product_name
        FROM meat_breakdown_output mbo
        JOIN meat_products mp ON mp.id=mbo.product_id
        LEFT JOIN meat_price_lock mpl 
               ON mpl.product_id=mbo.product_id AND mpl.material_id=%s
        WHERE mbo.breakdown_id=%s
        ORDER BY mp.name
    """,(header['material_id'], breakdown_id)) or []
    extras = db_connector.execute_query("SELECT * FROM meat_breakdown_extra_costs WHERE breakdown_id=%s", (breakdown_id,)) or []
    return header, outputs, extras

def compute_breakdown_results(breakdown_id:int):
    b, outputs, extras = _fetch_breakdown_full(breakdown_id)
    input_w = float(b['input_weight_kg'])
    purchase_total = float(b['purchase_total_cost_eur'] or 0.0)
    extras_total = sum(float(x['amount_eur']) for x in extras)
    joint_cost = round(purchase_total + extras_total, 2)

    sv_sum = 0.0  # ∑(váha × predajná/lock cena)
    for o in outputs:
        sv_sum += float(o['weight_kg']) * float(o['selling_price_eur_kg'])
    if sv_sum <= 0:
        raise ValueError("Nie je možné alokovať – trhová hodnota je nulová (skontroluj predajné/zamknuté ceny).")

    db_connector.execute_query("DELETE FROM meat_breakdown_result WHERE breakdown_id=%s", (breakdown_id,), fetch='none')

    for o in outputs:
        w = float(o['weight_kg'])
        sp = float(o['selling_price_eur_kg'])
        share = (w*sp) / sv_sum
        alloc = round(joint_cost * share, 2)
        cpk = round(alloc / w, 4) if w > 0 else 0.0
        yld = round((w / input_w)*100.0, 4)
        margin = round(sp - cpk, 4)
        profit = round(margin * w, 2)

        ins = """INSERT INTO meat_breakdown_result
                 (breakdown_id, product_id, weight_kg, yield_pct, allocated_cost_eur, cost_per_kg_eur,
                  selling_price_eur_kg_snap, margin_eur_per_kg, profit_eur)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        db_connector.execute_query(ins, (breakdown_id, int(o['product_id']), w, yld, alloc, cpk,
                                         sp, margin, profit), fetch='none')
    return {"message":"Prepočítané."}

def get_breakdown(breakdown_id:int):
    b, outputs, extras = _fetch_breakdown_full(breakdown_id)
    results = db_connector.execute_query("""
        SELECT r.*, p.name AS product_name
        FROM meat_breakdown_result r
        JOIN meat_products p ON p.id=r.product_id
        WHERE r.breakdown_id=%s
        ORDER BY p.name
    """,(breakdown_id,)) or []
    return jsonify({
        "header": b,
        "outputs": outputs,
        "extras": extras,
        "results": results
    })

def list_breakdowns(material_id=None, date_from=None, date_to=None, supplier=None):
    wh = []
    params = []
    if material_id:
        wh.append("b.material_id=%s")
        params.append(int(material_id))
    if date_from:
        wh.append("b.breakdown_date>=%s")
        params.append(date_from)
    if date_to:
        wh.append("b.breakdown_date<=%s")
        params.append(date_to)
    if supplier:
        wh.append("b.supplier=%s")
        params.append(supplier)
    where = (" WHERE " + " AND ".join(wh)) if wh else ""
    rows = db_connector.execute_query(f"""
        SELECT b.*, m.name AS material_name
        FROM meat_breakdown b
        JOIN meat_materials m ON m.id=b.material_id
        {where}
        ORDER BY b.breakdown_date DESC, b.id DESC
    """, tuple(params)) or []
    return jsonify(rows)

# ---------- ODHAD – priemerné výťažnosti --------------------------
def _avg_yields(material_id:int, supplier:Optional[str]=None, date_from=None, date_to=None) -> Dict[int,float]:
    """Vážené priemerné výťažnosti z histórie pre danú surovinu (+ voliteľné filtre)."""
    wh = ["b.material_id=%s"]; params=[int(material_id)]
    if supplier:
        wh.append("b.supplier=%s"); params.append(supplier)
    if date_from:
        wh.append("b.breakdown_date >= %s"); params.append(date_from)
    if date_to:
        wh.append("b.breakdown_date <= %s"); params.append(date_to)
    where = " WHERE " + " AND ".join(wh)

    tot = db_connector.execute_query(f"SELECT SUM(b.input_weight_kg) AS w FROM meat_breakdown b {where}", tuple(params)) or []
    total_input = float(tot[0]['w'] or 0.0)
    if total_input <= 0:
        return {}

    rows = db_connector.execute_query(f"""
        SELECT mbo.product_id, SUM(mbo.weight_kg) AS w
        FROM meat_breakdown b
        JOIN meat_breakdown_output mbo ON mbo.breakdown_id=b.id
        {where}
        GROUP BY mbo.product_id
    """, tuple(params)) or []

    res={}
    for r in rows:
        res[int(r['product_id'])] = float(r['w']) / total_input
    return res  # pomer 0..1

def _get_product_id_by_code(code: str) -> Optional[int]:
    row = db_connector.execute_query("SELECT id FROM meat_products WHERE code=%s LIMIT 1", (code,), fetch='one')
    return int(row['id']) if row and row.get('id') is not None else None

def _avg_tolerance_pct(material_id:int, supplier:Optional[str]=None, date_from=None, date_to=None) -> float:
    """
    Vypočíta vážený priemer tolerance_pct (v %) podľa vstupnej váhy:
      avg_tol = SUM(input_weight * tolerance_pct) / SUM(input_weight)
    Null tolerancie sa ignorujú (berie sa 0).
    """
    wh = ["b.material_id=%s"]; params=[int(material_id)]
    if supplier:
        wh.append("b.supplier=%s"); params.append(supplier)
    if date_from:
        wh.append("b.breakdown_date >= %s"); params.append(date_from)
    if date_to:
        wh.append("b.breakdown_date <= %s"); params.append(date_to)
    where = " WHERE " + " AND ".join(wh)

    row = db_connector.execute_query(f"""
        SELECT 
          SUM(b.input_weight_kg * COALESCE(b.tolerance_pct,0)) / NULLIF(SUM(b.input_weight_kg),0) AS avg_tol
        FROM meat_breakdown b
        {where}
    """, tuple(params), fetch='one') or {}

    avg_tol = float(row.get('avg_tol') or 0.0)
    # ohranič, keby niekde bola extrémna hodnota
    if avg_tol < 0: avg_tol = 0.0
    if avg_tol > 100: avg_tol = 100.0
    return round(avg_tol, 4)

def _get_product_id_by_code(code: str) -> Optional[int]:
    row = db_connector.execute_query("SELECT id FROM meat_products WHERE code=%s LIMIT 1", (code,), fetch='one')
    return int(row['id']) if row and row.get('id') is not None else None

def _get_product_codes(ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    placeholders = ",".join(["%s"]*len(ids))
    rows = db_connector.execute_query(
        f"SELECT id, code FROM meat_products WHERE id IN ({placeholders})",
        tuple(ids), fetch='all'
    ) or []
    return { int(r["id"]): (r["code"] or "").strip().upper() for r in rows }

def estimate(material_id:int, planned_weight_kg:float, expected_purchase_unit_price:float,
             supplier:Optional[str]=None, date_from=None, date_to=None, extra_costs:list|None=None):
    # 1) Priemerné výťažnosti z histórie
    yields = _avg_yields(material_id, supplier, date_from, date_to)  # {product_id: fraction 0..1}
    if not yields:
        return {"error":"Nie sú dostupné historické dáta pre zvolený filter (materiál/dodávateľ/dátumy)."}

    # 2) Vylúč STRATA z odhadu a renormalizuj na 100 %
    pid_list = list(yields.keys())
    codes = _get_product_codes(pid_list)
    for pid in list(yields.keys()):
        if codes.get(pid) == "STRATA":
            yields.pop(pid, None)
    if not yields:
        return {"error":"Historické dáta po odfiltrovaní položky STRATA neobsahujú žiadne predajné diely."}

    s = float(sum(yields.values()))
    if s <= 0:
        return {"error":"Výťažnosti po odfiltrovaní sú nulové. Skontroluj historické záznamy."}
    for k in list(yields.keys()):
        yields[k] = float(yields[k]) / s  # teraz ∑yields = 1.0

    # 3) Priemerná Tolerancia straty (%) – vážená vstupom
    avg_tol_pct = _avg_tolerance_pct(material_id, supplier, date_from, date_to)  # napr. 3.25
    tol_factor = max(0.0, 1.0 - (avg_tol_pct / 100.0))

    # Efektívna výstupná váha (plán – strata)
    effective_output_weight = planned_weight_kg * tol_factor

    # 4) Ceny – preferuj lock pre materiál, inak predajné
    locks = db_connector.execute_query(
        "SELECT product_id, price_eur_kg FROM meat_price_lock WHERE material_id=%s",
        (int(material_id),)
    ) or []
    lock_map = { int(r['product_id']): float(r['price_eur_kg']) for r in locks }
    all_prices = db_connector.execute_query("SELECT id, selling_price_eur_kg FROM meat_products WHERE is_active=1") or []
    prices = { int(r['id']): (lock_map.get(int(r['id'])) if int(r['id']) in lock_map else float(r['selling_price_eur_kg']))
               for r in all_prices }

    # 5) Odhad váh – ∑w == effective_output_weight
    est_rows=[]
    for pid, y in yields.items():
        w = effective_output_weight * float(y)
        sp = prices.get(pid, 0.0)
        est_rows.append({"product_id":pid, "weight_kg":w, "selling_price":sp})

    # 6) Spoločný náklad: celý nákup (plán) + extra
    joint_cost = round(
        planned_weight_kg * expected_purchase_unit_price
        + sum(float(x.get('amount_eur') or 0) for x in (extra_costs or [])),
        2
    )

    # 7) Alokácia: podľa hodnoty; pri nulovej hodnote → váhová
    sv_sum = sum(r['weight_kg'] * r['selling_price'] for r in est_rows)
    use_weight_based = sv_sum <= 0.0
    total_w = sum(r['weight_kg'] for r in est_rows) if use_weight_based else 1.0

    results=[]
    for r in est_rows:
        share = (r['weight_kg']/total_w) if use_weight_based else ((r['weight_kg']*r['selling_price'])/sv_sum)
        alloc = round(joint_cost * share, 2)
        cpk   = round(alloc / r['weight_kg'], 4) if r['weight_kg']>0 else 0.0
        margin= round(r['selling_price'] - cpk, 4)
        profit= round(margin * r['weight_kg'], 2)
        results.append({
            "product_id":r['product_id'],
            "weight_kg":round(r['weight_kg'],3),
            "yield_pct": round((r['weight_kg']/planned_weight_kg)*100.0, 4),  # voči plánu
            "cost_alloc_eur":alloc,
            "cost_per_kg_eur":cpk,
            "selling_price_eur_kg":r['selling_price'],
            "margin_eur_per_kg":margin,
            "profit_eur":profit
        })

    return {
        "planned_weight_kg": planned_weight_kg,
        "avg_tolerance_pct": avg_tol_pct,
        "effective_output_weight_kg": round(effective_output_weight, 3),
        "joint_cost_eur": joint_cost,
        "sum_estimated_weight_kg": round(sum(r["weight_kg"] for r in results), 3),
        "rows": results
    }


# ---------- PROFITABILITY REPORT (existujúci breakdown) -----------
def profitability(breakdown_id:int):
    rows = db_connector.execute_query("""
        SELECT r.*, p.name AS product_name
        FROM meat_breakdown_result r
        JOIN meat_products p ON p.id=r.product_id
        WHERE r.breakdown_id=%s ORDER BY p.name
    """,(breakdown_id,)) or []
    tot_profit = sum(float(r['profit_eur']) for r in rows)
    tot_alloc  = sum(float(r['allocated_cost_eur']) for r in rows)
    return jsonify({"rows":rows, "total_profit_eur": round(tot_profit,2), "total_allocated_cost_eur": round(tot_alloc,2)})

# ---------- EXPORT: Excel (XLSX) ----------------------------------
def export_breakdown_excel(breakdown_id:int):
    import xlsxwriter
    b, _, _ = _fetch_breakdown_full(breakdown_id)
    rows = db_connector.execute_query("""
        SELECT p.code, p.name, r.weight_kg, r.yield_pct, r.cost_per_kg_eur, r.selling_price_eur_kg_snap, r.margin_eur_per_kg, r.profit_eur
        FROM meat_breakdown_result r
        JOIN meat_products p ON p.id=r.product_id
        WHERE r.breakdown_id=%s ORDER BY p.name
    """, (breakdown_id,)) or []

    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = wb.add_worksheet("Rozrábka")

    headers = ["Kód","Produkt","Váha (kg)","Výťažnosť (%)","Náklad €/kg","Predaj €/kg","Marža €/kg","Zisk (€)"]
    for c,h in enumerate(headers): ws.write(0,c,h)
    for r,row in enumerate(rows, start=1):
        ws.write(r,0,row['code']); ws.write(r,1,row['name'])
        ws.write_number(r,2,float(row['weight_kg']))
        ws.write_number(r,3,float(row['yield_pct']))
        ws.write_number(r,4,float(row['cost_per_kg_eur']))
        ws.write_number(r,5,float(row['selling_price_eur_kg_snap']))
        ws.write_number(r,6,float(row['margin_eur_per_kg']))
        ws.write_number(r,7,float(row['profit_eur']))
    wb.close()
    output.seek(0)
    filename = f"rozrabka_{b['id']}_{b['breakdown_date']}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# =================================================================
# ==================== HTML REPORTS ===============================
# =================================================================
def report_breakdown_html(breakdown_id:int):
    b, outputs, extras = _fetch_breakdown_full(breakdown_id)
    results = db_connector.execute_query("""
        SELECT r.*, p.name AS product_name, p.code AS product_code
        FROM meat_breakdown_result r
        JOIN meat_products p ON p.id=r.product_id
        WHERE r.breakdown_id=%s
        ORDER BY p.name
    """,(breakdown_id,)) or []
    return make_response(render_template("meat_breakdown_report.html",
                                         header=b, outputs=outputs, extras=extras, results=results))
