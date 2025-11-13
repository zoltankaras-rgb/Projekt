# =================================================================
# === HANDLER PRE MODUL: SPRÁVA NÁKLADOV (energetika/HR/prevádzka)
# =================================================================

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta
import calendar
import db_connector

# Výnosy (pre dashboard) – voliteľné, ak modul ziskovosti existuje
try:
    import profitability_handler  # noqa: F401
except Exception:
    profitability_handler = None  # type: ignore

# -----------------------------------------------------------------
# Pomocné numerické utility
# -----------------------------------------------------------------
def _nz(v: Any) -> float:
    """Number-or-zero: None/'' -> 0.0, inak float(v) alebo 0.0 pri chybe."""
    try:
        return float(v) if v is not None and v != "" else 0.0
    except Exception:
        return 0.0


def _to_float_or_none(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except Exception:
        return None


def _ym(year: Any, month: Any) -> tuple[int, int]:
    """Bezpečné odčítanie roku/mesiaca z rôznych foriem (int/str/None)."""
    if year is None or month is None or str(year).strip() == "" or str(month).strip() == "":
        t = date.today()
        y, m = t.year, t.month
    else:
        y = int(year)
        m = int(month)
    if m < 1:
        m, y = 12, y - 1
    if m > 12:
        m, y = 1, y + 1
    return y, m


def _prev_month(year: int, month: int) -> tuple[int, int]:
    y, m = _ym(year, month)
    return (y, m - 1) if m > 1 else (y - 1, 12)


# -----------------------------------------------------------------
# Energetika – unified monthly row
# Tabuľka: costs_energy_monthly
# -----------------------------------------------------------------
def _ensure_energy_row(year: int, month: int) -> Dict[str, Any]:
    """Zaistí existenciu riadku pre daný mesiac; prenesie ceny a ZAČ stavy z predchádzajúceho mesiaca."""
    row = db_connector.execute_query(
        "SELECT * FROM costs_energy_monthly WHERE report_year=%s AND report_month=%s",
        (year, month), fetch="one"
    )
    if row:
        return row

    py, pm = _prev_month(year, month)
    prev = db_connector.execute_query(
        "SELECT * FROM costs_energy_monthly WHERE report_year=%s AND report_month=%s",
        (py, pm), fetch="one"
    ) or {}

    params = {
        "report_year": year, "report_month": month,
        # carry start = predch. end
        "el_prod_start_kwh":   prev.get("el_prod_end_kwh"),
        "el_other_start_kwh":  prev.get("el_other_end_kwh"),
        "el_main_start_kwh":   prev.get("el_main_end_kwh"),
        "gas_start_m3":        prev.get("gas_end_m3"),
        "water_start_m3":      prev.get("water_end_m3"),
        # ceny – prenesú sa iba pri zakladaní mesiaca
        "el_price_per_kwh_net":        prev.get("el_price_per_kwh_net"),
        "el_price_per_kwh_gross":      prev.get("el_price_per_kwh_gross"),
        "el_main_price_per_kwh_net":   prev.get("el_main_price_per_kwh_net"),
        "el_main_price_per_kwh_gross": prev.get("el_main_price_per_kwh_gross"),
        "gas_conv_kwh_per_m3":         prev.get("gas_conv_kwh_per_m3") or 10.5,
        "gas_price_per_kwh_net":       prev.get("gas_price_per_kwh_net"),
        "gas_price_per_kwh_gross":     prev.get("gas_price_per_kwh_gross"),
        "water_price_per_m3_net":      prev.get("water_price_per_m3_net"),
        "water_price_per_m3_gross":    prev.get("water_price_per_m3_gross"),
    }

    db_connector.execute_query(
        """
        INSERT INTO costs_energy_monthly
        (report_year, report_month,
         el_prod_start_kwh, el_other_start_kwh, el_main_start_kwh,
         el_price_per_kwh_net, el_price_per_kwh_gross,
         el_main_price_per_kwh_net, el_main_price_per_kwh_gross,
         gas_start_m3, gas_conv_kwh_per_m3, gas_price_per_kwh_net, gas_price_per_kwh_gross,
         water_start_m3, water_price_per_m3_net, water_price_per_m3_gross)
        VALUES (%(report_year)s, %(report_month)s,
                %(el_prod_start_kwh)s, %(el_other_start_kwh)s, %(el_main_start_kwh)s,
                %(el_price_per_kwh_net)s, %(el_price_per_kwh_gross)s,
                %(el_main_price_per_kwh_net)s, %(el_main_price_per_kwh_gross)s,
                %(gas_start_m3)s, %(gas_conv_kwh_per_m3)s, %(gas_price_per_kwh_net)s, %(gas_price_per_kwh_gross)s,
                %(water_start_m3)s, %(water_price_per_m3_net)s, %(water_price_per_m3_gross)s)
        """,
        params, fetch="none"
    )

    return db_connector.execute_query(
        "SELECT * FROM costs_energy_monthly WHERE report_year=%s AND report_month=%s",
        (year, month), fetch="one"
    )


def _update_energy_fields(year: int, month: int, updates: Dict[str, float]) -> None:
    """
    Bezpečný UPDATE cez pozičné placeholdery + carry-forward koncových stavov do ďalšieho mesiaca.
    Predpokladá existenciu riadku (zabezpečí _ensure_energy_row).
    """
    if not updates:
        return

    # 1) UPDATE aktuálneho mesiaca
    keys = list(updates.keys())
    set_sql = ", ".join([f"{k}=%s" for k in keys])
    vals = [updates[k] for k in keys] + [year, month]
    db_connector.execute_query(
        f"UPDATE costs_energy_monthly SET {set_sql} WHERE report_year=%s AND report_month=%s",
        tuple(vals), fetch="none"
    )

    # 2) carry-forward end -> start v ďalšom mesiaci
    cf_map = {
        "el_prod_end_kwh":  "el_prod_start_kwh",
        "el_other_end_kwh": "el_other_start_kwh",
        "el_main_end_kwh":  "el_main_start_kwh",
        "gas_end_m3":       "gas_start_m3",
        "water_end_m3":     "water_start_m3",
    }
    cf_updates = {cf_map[k]: updates[k] for k in updates if k in cf_map and updates[k] is not None}
    if cf_updates:
        ny, nm = _ym(year, month + 1)
        _ensure_energy_row(ny, nm)
        cf_keys = list(cf_updates.keys())
        cf_set = ", ".join([f"{k}=%s" for k in cf_keys])
        cf_vals = [cf_updates[k] for k in cf_keys] + [ny, nm]
        db_connector.execute_query(
            f"UPDATE costs_energy_monthly SET {cf_set} WHERE report_year=%s AND report_month=%s",
            tuple(cf_vals), fetch="none"
        )


# -----------------------------------------------------------------
# GET – hlavný prehľad pre UI "Správa nákladov"
# -----------------------------------------------------------------
def get_costs_data(year: Any, month: Any) -> Dict[str, Any]:
    y, m = _ym(year, month)
    row = _ensure_energy_row(y, m)

    # Elektrina – vypočítané rozdiely
    el_prod_diff = max(0.0, _nz(row.get("el_prod_end_kwh")) - _nz(row.get("el_prod_start_kwh")))
    el_oth_diff  = max(0.0, _nz(row.get("el_other_end_kwh")) - _nz(row.get("el_other_start_kwh")))
    el_sum       = el_prod_diff + el_oth_diff
    el_main_diff = max(0.0, _nz(row.get("el_main_end_kwh")) - _nz(row.get("el_main_start_kwh")))

    # Plyn – prepočet na kWh/MWh
    gas_m3  = max(0.0, _nz(row.get("gas_end_m3")) - _nz(row.get("gas_start_m3")))
    gas_kf  = _nz(row.get("gas_conv_kwh_per_m3") or 10.5)
    gas_kwh = round(gas_m3 * gas_kf, 3)
    gas_mwh = round(gas_kwh / 1000.0, 3)

    # Voda – rozdiel m3
    water_m3 = max(0.0, _nz(row.get("water_end_m3")) - _nz(row.get("water_start_m3")))

    energy = {
        "electricity": {
            "prod":  {"start_kwh": row.get("el_prod_start_kwh"),  "end_kwh": row.get("el_prod_end_kwh"),  "diff_kwh": el_prod_diff},
            "other": {"start_kwh": row.get("el_other_start_kwh"), "end_kwh": row.get("el_other_end_kwh"), "diff_kwh": el_oth_diff},
            "sum_kwh": el_sum,
            "price_net":   row.get("el_price_per_kwh_net"),
            "price_gross": row.get("el_price_per_kwh_gross"),
            "main": {
                "start_kwh": row.get("el_main_start_kwh"),
                "end_kwh":   row.get("el_main_end_kwh"),
                "diff_kwh":  el_main_diff,
                "price_net":   row.get("el_main_price_per_kwh_net"),
                "price_gross": row.get("el_main_price_per_kwh_gross"),
            }
        },
        "gas": {
            "start_m3": row.get("gas_start_m3"), "end_m3": row.get("gas_end_m3"),
            "diff_m3": gas_m3, "kwh": gas_kwh, "mwh": gas_mwh,
            "conv_kwh_per_m3": gas_kf,
            "price_net":   row.get("gas_price_per_kwh_net"),
            "price_gross": row.get("gas_price_per_kwh_gross"),
        },
        "water": {
            "start_m3": row.get("water_start_m3"), "end_m3": row.get("water_end_m3"),
            "diff_m3": water_m3,
            "price_net":   row.get("water_price_per_m3_net"),
            "price_gross": row.get("water_price_per_m3_gross"),
        },
        "summary": {
            "total_kwh": round(el_sum + gas_kwh, 3),
            "total_m3":  round(water_m3 + gas_m3, 3),
            "avg": {
                "electricity_price_net": row.get("el_price_per_kwh_net"),
                "gas_price_net_kwh":     row.get("gas_price_per_kwh_net"),
                "water_price_net_m3":    row.get("water_price_per_m3_net"),
            }
        }
    }

    # Ľudské zdroje
    hr = get_hr_block(y, m)

    # Prevádzkové náklady (detail + zoznam kategórií)
    op_items = db_connector.execute_query(
        """
        SELECT ci.*, cc.category_name
        FROM costs_items ci
        JOIN costs_categories cc ON cc.id = ci.category_id
        WHERE YEAR(ci.entry_date)=%s AND MONTH(ci.entry_date)=%s
        ORDER BY ci.entry_date DESC
        """,
        (y, m)
    ) or []
    categories = db_connector.execute_query(
        "SELECT id, category_name AS name FROM costs_categories ORDER BY category_name"
    ) or []

    operational = {"items": op_items, "categories": categories}

    return {"year": y, "month": m, "energy": energy, "hr": hr, "operational": operational}


# -----------------------------------------------------------------
# SAVE – energie (univerzálne aj sekčné)
# -----------------------------------------------------------------
def save_energy_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Univerzálne uloženie – môžeš poslať ľubovoľnú kombináciu polí elektriny/plynu/vody."""
    y, m = _ym(data.get("year"), data.get("month"))
    _ensure_energy_row(y, m)

    allow = [
        "el_prod_start_kwh","el_prod_end_kwh","el_other_start_kwh","el_other_end_kwh",
        "el_price_per_kwh_net","el_price_per_kwh_gross",
        "el_main_start_kwh","el_main_end_kwh","el_main_price_per_kwh_net","el_main_price_per_kwh_gross",
        "gas_start_m3","gas_end_m3","gas_conv_kwh_per_m3","gas_price_per_kwh_net","gas_price_per_kwh_gross",
        "water_start_m3","water_end_m3","water_price_per_m3_net","water_price_per_m3_gross",
    ]
    updates: Dict[str, float] = {}
    for k in allow:
        v = _to_float_or_none(data.get(k))
        if v is not None:
            updates[k] = v

    _update_energy_fields(y, m, updates)
    return {"message": "Dáta boli úspešne uložené."}


def save_electricity_data(data: Dict[str, Any]) -> Dict[str, Any]:
    y, m = _ym(data.get("year"), data.get("month"))
    _ensure_energy_row(y, m)
    keys = [
        "el_prod_start_kwh","el_prod_end_kwh","el_other_start_kwh","el_other_end_kwh",
        "el_price_per_kwh_net","el_price_per_kwh_gross",
        "el_main_start_kwh","el_main_end_kwh","el_main_price_per_kwh_net","el_main_price_per_kwh_gross",
    ]
    updates = {k: _to_float_or_none(data.get(k)) for k in keys}
    updates = {k: v for k, v in updates.items() if v is not None}
    _update_energy_fields(y, m, updates)
    return {"message": "Elektrina uložená."}


def save_gas_data(data: Dict[str, Any]) -> Dict[str, Any]:
    y, m = _ym(data.get("year"), data.get("month"))
    _ensure_energy_row(y, m)
    keys = ["gas_start_m3","gas_end_m3","gas_conv_kwh_per_m3","gas_price_per_kwh_net","gas_price_per_kwh_gross"]
    updates = {k: _to_float_or_none(data.get(k)) for k in keys}
    updates = {k: v for k, v in updates.items() if v is not None}
    _update_energy_fields(y, m, updates)
    return {"message": "Plyn uložený."}


def save_water_data(data: Dict[str, Any]) -> Dict[str, Any]:
    y, m = _ym(data.get("year"), data.get("month"))
    _ensure_energy_row(y, m)
    keys = ["water_start_m3","water_end_m3","water_price_per_m3_net","water_price_per_m3_gross"]
    updates = {k: _to_float_or_none(data.get(k)) for k in keys}
    updates = {k: v for k, v in updates.items() if v is not None}
    _update_energy_fields(y, m, updates)
    return {"message": "Voda uložená."}


# -----------------------------------------------------------------
# HR – Ľudské zdroje
# Tab.: costs_hr (record_year, record_month, total_salaries, total_levies)
# -----------------------------------------------------------------
def get_hr_block(year: int, month: int) -> Dict[str, Any]:
    rec = db_connector.execute_query(
        "SELECT * FROM costs_hr WHERE record_year=%s AND record_month=%s",
        (year, month), fetch="one"
    ) or {}
    return {
        "total_salaries": _nz(rec.get("total_salaries")),
        "total_levies":   _nz(rec.get("total_levies")),
    }


def save_hr_data(data: Dict[str, Any]) -> Dict[str, Any]:
    y, m = _ym(data.get("year"), data.get("month"))
    params = (y, m, _nz(data.get("total_salaries")), _nz(data.get("total_levies")))
    db_connector.execute_query(
        """
        INSERT INTO costs_hr (record_year, record_month, total_salaries, total_levies)
        VALUES (%s, %s, %s, %s) AS new
        ON DUPLICATE KEY UPDATE
            total_salaries = new.total_salaries,
            total_levies   = new.total_levies
        """,
        params, fetch="none"
    )
    return {"message": "Dáta o ľudských zdrojoch boli uložené."}


# -----------------------------------------------------------------
# Prevádzkové náklady – položky a kategórie
# -----------------------------------------------------------------
def get_operational_block(year: int, month: int) -> Dict[str, Any]:
    items = db_connector.execute_query(
        """
        SELECT ci.*, cc.category_name
        FROM costs_items ci
        JOIN costs_categories cc ON cc.id = ci.category_id
        WHERE YEAR(ci.entry_date)=%s AND MONTH(ci.entry_date)=%s
        ORDER BY ci.entry_date DESC
        """,
        (year, month)
    ) or []
    cats = db_connector.execute_query(
        "SELECT id, category_name AS name FROM costs_categories ORDER BY category_name"
    ) or []
    return {"items": items, "categories": cats}


def save_operational_cost(data: Dict[str, Any]) -> Dict[str, Any]:
    item_id = data.get("id")
    required = ["entry_date", "category_id", "name", "amount_net"]
    if not all(field in data and data[field] for field in required):
        return {"error": "Chýbajú povinné údaje."}

    params = (
        data["entry_date"],
        int(data["category_id"]),
        data["name"],
        data.get("description", ""),
        _nz(data["amount_net"]),
        1 if str(data.get("is_recurring")).lower() in ("1", "true", "yes", "y") else 0,
    )

    if item_id:
        db_connector.execute_query(
            "UPDATE costs_items SET entry_date=%s, category_id=%s, name=%s, description=%s, amount_net=%s, is_recurring=%s WHERE id=%s",
            params + (int(item_id),), fetch="none"
        )
        return {"message": "Náklad bol aktualizovaný."}
    else:
        db_connector.execute_query(
            "INSERT INTO costs_items (entry_date, category_id, name, description, amount_net, is_recurring) VALUES (%s, %s, %s, %s, %s, %s)",
            params, fetch="none"
        )
        return {"message": "Nový náklad bol pridaný."}


def delete_operational_cost(data: Dict[str, Any]) -> Dict[str, Any]:
    item_id = data.get("id")
    if not item_id:
        return {"error": "Chýba ID nákladu."}
    db_connector.execute_query("DELETE FROM costs_items WHERE id=%s", (int(item_id),), fetch="none")
    return {"message": "Náklad bol vymazaný."}


def save_cost_category(data: Dict[str, Any]) -> Dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        return {"error": "Názov kategórie nemôže byť prázdny."}
    try:
        db_connector.execute_query(
            "INSERT INTO costs_categories (category_name) VALUES (%s)",
            (name,), fetch="none"
        )
        return {"message": f"Kategória '{name}' bola úspešne pridaná."}
    except Exception as e:
        if "Duplicate entry" in str(e):
            return {"error": f"Kategória s názvom '{name}' už existuje."}
        raise


# -----------------------------------------------------------------
# Výnosy z profitability – len oddelenia: Expedícia / Rozrábka / Výroba
# -----------------------------------------------------------------
def _safe_revenue_from_profitability(year: int, month: int) -> tuple[float, Dict[str, float]]:
    """
    Vráti (total_revenue, breakdown) – breakdown: 'Expedícia', 'Rozrábka', 'Výroba'.
    Zdrojom sú dáta z profitability_handler.get_profitability_data(year, month).
    - Expedícia: department_data.exp_revenue
    - Rozrábka:  department_data.exp_from_butchering
    - Výroba:    department_data.exp_from_prod_strict (ak existuje), inak fallback na exp_from_prod
    """
    def _num(v):
        try:
            return float(v) if v is not None and v != "" else 0.0
        except Exception:
            return 0.0

    out: Dict[str, float] = {"Expedícia": 0.0, "Rozrábka": 0.0, "Výroba": 0.0}
    total = 0.0

    try:
        if not profitability_handler:
            return total, out

        pd = profitability_handler.get_profitability_data(year, month) or {}
        d  = pd.get("department_data") or {}

        exp = _num(d.get("exp_revenue"))
        roz = _num(d.get("exp_from_butchering"))
        vyr = _num(d.get("exp_from_prod_strict"))
        if vyr <= 0:
            vyr = _num(d.get("exp_from_prod"))

        out["Expedícia"] = round(exp, 2)
        out["Rozrábka"]  = round(roz, 2)
        out["Výroba"]    = round(vyr, 2)
        total = round(exp + roz + vyr, 2)
    except Exception:
        pass
    return total, out


# -----------------------------------------------------------------
# Energia – história a reporting
# -----------------------------------------------------------------
def _parse_range_args(q) -> tuple[int, int, int, int]:
    """
    Podporované:
      - ?from=2025-01&to=2025-12
      - fallback: ?year=2025&month=10 (=> from/to = rovnaký mesiac)
    """
    def _split_ym(s: str) -> tuple[int, int]:
        y, m = s.split("-")
        return int(y), int(m)
    if q.get("from") and q.get("to"):
        fy, fm = _split_ym(q.get("from"))
        ty, tm = _split_ym(q.get("to"))
    else:
        fy = int(q.get("year", datetime.utcnow().year))
        fm = int(q.get("month", datetime.utcnow().month))
        ty, tm = fy, fm
    return fy, fm, ty, tm


def _ym_key(y: int, m: int) -> int:
    return y * 100 + m


def _month_key(y: int, m: int) -> int:
    return y * 100 + m


def _month_span(from_y: int, from_m: int, to_y: int, to_m: int) -> Tuple[int, int]:
    return _month_key(from_y, from_m), _month_key(to_y, to_m)


def _electricity_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    prod = max(0.0, _nz(row.get("el_prod_end_kwh")) - _nz(row.get("el_prod_start_kwh")))
    oth  = max(0.0, _nz(row.get("el_other_end_kwh")) - _nz(row.get("el_other_start_kwh")))
    summ = prod + oth
    main = max(0.0, _nz(row.get("el_main_end_kwh")) - _nz(row.get("el_main_start_kwh")))
    price_net   = _nz(row.get("el_price_per_kwh_net"))
    price_gross = _nz(row.get("el_price_per_kwh_gross"))
    cost_net    = round(summ * price_net, 2)
    cost_gross  = round(summ * (price_gross or price_net), 2)
    return {
        "prod_kwh": round(prod, 3),
        "other_kwh": round(oth, 3),
        "sum_kwh": round(summ, 3),
        "main_kwh": round(main, 3),
        "price_net": price_net or None,
        "price_gross": price_gross or None,
        "cost_net": cost_net,
        "cost_gross": cost_gross,
        "diff_kwh_abs": round(abs(summ - main), 3),
    }


def _gas_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    diff_m3 = max(0.0, _nz(row.get("gas_end_m3")) - _nz(row.get("gas_start_m3")))
    kf = _nz(row.get("gas_conv_kwh_per_m3") or 10.5)
    kwh = round(diff_m3 * kf, 3)
    mwh = round(kwh / 1000.0, 3)
    price_net   = _nz(row.get("gas_price_per_kwh_net"))
    price_gross = _nz(row.get("gas_price_per_kwh_gross"))
    cost_net    = round(kwh * price_net, 2)
    cost_gross  = round(kwh * (price_gross or price_net), 2)
    return {
        "diff_m3": round(diff_m3, 3),
        "kwh": kwh,
        "mwh": mwh,
        "conv_kwh_per_m3": round(kf, 4),
        "price_net": price_net or None,
        "price_gross": price_gross or None,
        "cost_net": cost_net,
        "cost_gross": cost_gross,
    }


def _water_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    diff_m3 = max(0.0, _nz(row.get("water_end_m3")) - _nz(row.get("water_start_m3")))
    price_net   = _nz(row.get("water_price_per_m3_net"))
    price_gross = _nz(row.get("water_price_per_m3_gross"))
    cost_net    = round(diff_m3 * price_net, 2)
    cost_gross  = round(diff_m3 * (price_gross or price_net), 2)
    return {
        "diff_m3": round(diff_m3, 3),
        "price_net": price_net or None,
        "price_gross": price_gross or None,
        "cost_net": cost_net,
        "cost_gross": cost_gross,
    }


def _energy_row_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "electricity": _electricity_metrics(row),
        "gas":         _gas_metrics(row),
        "water":       _water_metrics(row),
    }


def get_energy_history(q: Dict[str, Any]) -> Dict[str, Any]:
    """
    História energií (JSON).
    Params: energy=[electricity|gas|water|all], scope=[month|year|range],
            year, month, from=YYYY-MM, to=YYYY-MM.
    Default = posledných 12 mesiacov do zadaného (alebo aktuálneho) mesiaca.
    """
    energy = (q.get("energy") or "all").lower()

    def _parse_ym(s: str) -> Tuple[int, int]:
        y, m = s.split("-", 1)
        return int(y), int(m)

    if q.get("from") and q.get("to"):
        fy, fm = _parse_ym(q["from"])
        ty, tm = _parse_ym(q["to"])
    else:
        if q.get("year") and q.get("month"):
            ty, tm = _ym(q["year"], q["month"])
        else:
            today = date.today()
            ty, tm = today.year, today.month
        fy, fm = ty, tm
        for _ in range(11):
            fy, fm = _prev_month(fy, fm)

    k_from, k_to = _month_span(fy, fm, ty, tm)
    rows = db_connector.execute_query(
        """
        SELECT * FROM costs_energy_monthly
        WHERE (report_year * 100 + report_month) BETWEEN %s AND %s
        ORDER BY report_year, report_month
        """,
        (k_from, k_to)
    ) or []

    series = []
    totals = {
        "electricity": {"sum_kwh": 0.0, "cost_gross": 0.0},
        "gas":         {"kwh": 0.0, "diff_m3": 0.0, "cost_gross": 0.0},
        "water":       {"diff_m3": 0.0, "cost_gross": 0.0},
    }

    for r in rows:
        y, m = int(r["report_year"]), int(r["report_month"])
        met = _energy_row_metrics(r)
        item: Dict[str, Any] = {"year": y, "month": m, "label": f"{y}-{m:02d}"}
        if energy in ("electricity", "all"):
            e = met["electricity"]
            item["electricity"] = e
            totals["electricity"]["sum_kwh"]  += e["sum_kwh"]
            totals["electricity"]["cost_gross"] += e["cost_gross"]
        if energy in ("gas", "all"):
            g = met["gas"]
            item["gas"] = g
            totals["gas"]["kwh"]      += g["kwh"]
            totals["gas"]["diff_m3"]  += g["diff_m3"]
            totals["gas"]["cost_gross"] += g["cost_gross"]
        if energy in ("water", "all"):
            w = met["water"]
            item["water"] = w
            totals["water"]["diff_m3"]   += w["diff_m3"]
            totals["water"]["cost_gross"]+= w["cost_gross"]
        series.append(item)

    months = max(1, len(series))
    averages = {
        "electricity": {"avg_kwh": round(totals["electricity"]["sum_kwh"]/months, 3), "avg_cost_gross": round(totals["electricity"]["cost_gross"]/months, 2)},
        "gas":         {"avg_kwh": round(totals["gas"]["kwh"]/months,             3), "avg_cost_gross": round(totals["gas"]["cost_gross"]/months, 2)},
        "water":       {"avg_m3":  round(totals["water"]["diff_m3"]/months,       3), "avg_cost_gross": round(totals["water"]["cost_gross"]/months, 2)},
    }

    round_tot = {
        "electricity": {"sum_kwh": round(totals["electricity"]["sum_kwh"], 3), "cost_gross": round(totals["electricity"]["cost_gross"], 2)},
        "gas":         {"kwh": round(totals["gas"]["kwh"], 3), "diff_m3": round(totals["gas"]["diff_m3"], 3), "cost_gross": round(totals["gas"]["cost_gross"], 2)},
        "water":       {"diff_m3": round(totals["water"]["diff_m3"], 3), "cost_gross": round(totals["water"]["cost_gross"], 2)},
    }

    return {
        "range": {"from": f"{fy}-{fm:02d}", "to": f"{ty}-{tm:02d}"},
        "energy": energy,
        "series": series,
        "totals": round_tot,
        "averages": averages,
    }


def get_energy_report_html(params: Dict[str, Any]):
    """
    Tlačový HTML report energií:
      scope: 'month' | 'year' | 'range'  (default 'month')
      energy: 'electricity'|'gas'|'water'|'all'
      year, month (pri scope=month)
      year       (pri scope=year)
      from='YYYY-MM', to='YYYY-MM' (pri scope=range)
    """
    scope  = (params.get("scope") or "month").lower()
    energy = (params.get("energy") or "all").lower()

    def _p(s): y, m = s.split("-"); return int(y), int(m)

    if scope == "year":
        y = int(params.get("year") or date.today().year)
        fy, fm, ty, tm = y, 1, y, 12
        title = f"Energetický report – Rok {y}"
    elif scope == "range":
        fy, fm = _p(params.get("from") or f"{date.today().year}-01")
        ty, tm = _p(params.get("to")   or f"{date.today().year}-12")
        title = f"Energetický report – {fy}-{fm:02d} až {ty}-{tm:02d}"
    else:
        y = int(params.get("year") or date.today().year)
        m = int(params.get("month") or date.today().month)
        fy, fm, ty, tm = y, m, y, m
        title = f"Energetický report – {y}-{m:02d}"

    k_from, k_to = _month_span(fy, fm, ty, tm)
    rows = db_connector.execute_query(
        """
        SELECT * FROM costs_energy_monthly
        WHERE (report_year * 100 + report_month) BETWEEN %s AND %s
        ORDER BY report_year, report_month
        """,
        (k_from, k_to)
    ) or []

    # hlavičky
    subheads = []
    if energy in ("electricity", "all"): subheads += ["El. kWh", "El. € s DPH"]
    if energy in ("gas", "all"):         subheads += ["Plyn kWh", "Plyn € s DPH"]
    if energy in ("water", "all"):       subheads += ["Voda m³", "Voda € s DPH"]

    body_rows = []
    totals = {"electricity": {"kwh": 0.0, "eur": 0.0}, "gas": {"kwh": 0.0, "eur": 0.0}, "water": {"m3": 0.0, "eur": 0.0}}
    for r in rows:
        y, m = int(r["report_year"]), int(r["report_month"])
        met = _energy_row_metrics(r)
        cells = [f"<td>{y}-{m:02d}</td>"]
        if energy in ("electricity", "all"):
            e = met["electricity"]
            cells += [f"<td style='text-align:right'>{e['sum_kwh']}</td>", f"<td style='text-align:right'>{e['cost_gross']}</td>"]
            totals["electricity"]["kwh"] += e["sum_kwh"]
            totals["electricity"]["eur"] += e["cost_gross"]
        if energy in ("gas", "all"):
            g = met["gas"]
            cells += [f"<td style='text-align:right'>{g['kwh']}</td>", f"<td style='text-align:right'>{g['cost_gross']}</td>"]
            totals["gas"]["kwh"] += g["kwh"]
            totals["gas"]["eur"] += g["cost_gross"]
        if energy in ("water", "all"):
            w = met["water"]
            cells += [f"<td style='text-align:right'>{w['diff_m3']}</td>", f"<td style='text-align:right'>{w['cost_gross']}</td>"]
            totals["water"]["m3"] += w["diff_m3"]
            totals["water"]["eur"] += w["cost_gross"]
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    total_cells = []
    if energy in ("electricity", "all"): total_cells += [f"{round(totals['electricity']['kwh'], 3)}", f"{round(totals['electricity']['eur'], 2)}"]
    if energy in ("gas", "all"):         total_cells += [f"{round(totals['gas']['kwh'], 3)}",         f"{round(totals['gas']['eur'], 2)}"]
    if energy in ("water", "all"):       total_cells += [f"{round(totals['water']['m3'], 3)}",        f"{round(totals['water']['eur'], 2)}"]
    total_row = "<tr style='font-weight:700;background:#fff7f7'><td>SPOLU</td>" + "".join([f"<td style='text-align:right'>{c}</td>" for c in total_cells]) + "</tr>"

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:Inter,system-ui,Arial,sans-serif;padding:16px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #e5e7eb;padding:6px 8px;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
th{{background:#f9fafb}}
h2{{margin:0 0 12px 0}} .small{{color:#555;margin:4px 0 12px 0}}
</style></head><body>
<h2>{title}</h2>
<p class="small">Rozsah: {fy}-{fm:02d} až {ty}-{tm:02d}</p>
<table>
  <thead><tr><th>Obdobie</th>{"".join([f"<th>{h}</th>" for h in subheads])}</tr></thead>
  <tbody>{"".join(body_rows)}{total_row}</tbody>
</table>
<script>window.print()</script>
</body></html>"""
    from flask import make_response
    return make_response(html)


# -----------------------------------------------------------------
# Dashboard data - aggregates financial data
# -----------------------------------------------------------------
def get_dashboard_data(year: int, month: int) -> Dict[str, Any]:
    """Aggregates costs and revenue data for the dashboard."""
    # Get all cost components
    energy_row = _ensure_energy_row(year, month)
    energy = _energy_row_metrics(energy_row)
    hr = get_hr_block(year, month)
    
    # Calculate total costs
    el_costs = energy["electricity"]["cost_gross"]
    gas_costs = energy["gas"]["cost_gross"]
    water_costs = energy["water"]["cost_gross"]
    hr_costs = hr["total_salaries"] + hr["total_levies"]
    
    # Get operational costs
    op_items = db_connector.execute_query(
        """
        SELECT SUM(amount_net) as total
        FROM costs_items 
        WHERE YEAR(entry_date)=%s AND MONTH(entry_date)=%s
        """,
        (year, month), fetch="one"
    )
    op_costs = _nz(op_items["total"]) if op_items else 0.0
    
    # Get revenue data
    total_revenue, revenue_breakdown = _safe_revenue_from_profitability(year, month)
    
    # Calculate totals
    total_costs = el_costs + gas_costs + water_costs + hr_costs + op_costs
    net_profit = total_revenue - total_costs
    
    return {
        "summary": {
            "total_revenue": total_revenue,
            "total_costs": total_costs,
            "net_profit": net_profit
        },
        "breakdown": {
            "Energia": el_costs + gas_costs + water_costs,
            "Ľudské zdroje": hr_costs,
            "Prevádzka": op_costs
        },
        "revenue_breakdown": revenue_breakdown
    }

# -----------------------------------------------------------------
# Tlač – finančný report A4 (náklady + výnosy)
# -----------------------------------------------------------------
def get_finance_report_html(params: Dict[str, Any]):
    """Tlačový A4 report: koláčový graf nákladov a výnosov (Expedícia / Rozrábka / Výroba) za mesiac."""
    from datetime import date
    from flask import make_response

    def _num(v):
        try:
            return float(v) if v is not None and v != "" else 0.0
        except Exception:
            return 0.0

    y = int(params.get("year", date.today().year))
    m = int(params.get("month", date.today().month))

    dash = get_dashboard_data(y, m)  # používa _safe_revenue_from_profitability()
    total_revenue = _num(dash.get("summary", {}).get("total_revenue"))
    total_costs   = _num(dash.get("summary", {}).get("total_costs"))
    net_profit    = _num(dash.get("summary", {}).get("net_profit"))
    cost_break    = dash.get("breakdown", {}) or {}
    rev_break     = dash.get("revenue_breakdown", {}) or {}

    # A4 + print-friendly CSS (portrét)
    html = f"""<!doctype html>
<html lang="sk"><head><meta charset="utf-8"><title>Finančný report {y}-{m:02d}</title>
<style>
  @page {{
    size: A4 portrait;
    margin: 12mm;
  }}
  @media print {{
    html, body {{ width: 210mm; }}
    .page {{ width: 186mm; }}
    .chart {{ height: 110mm !important; page-break-inside: avoid; }}
    .kpi p {{ font-size: 16pt; }}
  }}
  @media screen {{
    .page {{ max-width: 186mm; margin: 0 auto; }}
    .chart {{ height: 360px; }}
  }}
  body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;padding:0;color:#111827}}
  h1{{margin:0 0 8px 0;font-size:20pt}} h2{{margin:0 0 10px 0;font-size:14pt;color:#374151}}
  .muted{{color:#6b7280}} .page{{padding:12mm 0}}
  .kpi{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8mm;margin:6mm 0}}
  .kpi .card{{border:1px solid #e5e7eb;border-radius:10px;padding:5mm}}
  .kpi h3{{margin:0 0 2mm 0;font-size:10pt;color:#374151}} .kpi p{{margin:0;font-size:18pt;font-weight:700}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:8mm}}
  .card{{border:1px solid #e5e7eb;border-radius:10px;padding:6mm;page-break-inside:avoid}}
  .row{{margin:4mm 0}}
  .gain{{color:#065f46}} .loss{{color:#b91c1c}}
</style>
<script src="https://www.gstatic.com/charts/loader.js"></script>
<script>
  google.charts.load('current', {{packages:['corechart']}});
  google.charts.setOnLoadCallback(drawCharts);
  function drawCharts(){{
    // Náklady
    var dataC = new google.visualization.DataTable();
    dataC.addColumn('string','Kategória'); dataC.addColumn('number','Suma');
    {"".join([f"dataC.addRow(['{k}', {float(v):.2f}]);" for k,v in cost_break.items() if _num(v)>0])}
    var chartC = new google.visualization.PieChart(document.getElementById('pie-costs'));
    chartC.draw(dataC, {{title:'Štruktúra nákladov', pieHole:0.4, legend:{{position:'right'}}, chartArea:{{width:'85%',height:'80%'}}}});

    // Výnosy – rozdelené: Expedícia, Rozrábka, Výroba
    var dataR = new google.visualization.DataTable();
    dataR.addColumn('string','Oddelenie'); dataR.addColumn('number','Suma');
    {"".join([f"dataR.addRow(['{k}', {float(v):.2f}]);" for k,v in rev_break.items() if _num(v)>0])}
    var chartR = new google.visualization.PieChart(document.getElementById('pie-revenue'));
    chartR.draw(dataR, {{title:'Štruktúra výnosov (Expedícia / Rozrábka / Výroba)', pieHole:0.4, legend:{{position:'right'}}, chartArea:{{width:'85%',height:'80%'}}}});

    setTimeout(function(){{ window.print(); }}, 500);
  }}
</script>
</head>
<body>
  <div class="page">
    <h1>Finančný report {y}-{m:02d}</h1>
    <div class="muted">Výnosy = Expedícia + Rozrábka + Výroba &nbsp;•&nbsp; Náklady = všetky nákladové položky</div>

    <div class="kpi">
      <div class="card"><h3>Celkové Výnosy</h3><p class="{ 'gain' if total_revenue>=0 else 'loss' }">{total_revenue:.2f} €</p></div>
      <div class="card"><h3>Celkové Náklady</h3><p class="loss">{total_costs:.2f} €</p></div>
      <div class="card"><h3>Čistý Zisk</h3><p class="{ 'gain' if net_profit>=0 else 'loss' }">{net_profit:.2f} €</p></div>
    </div>

    <div class="grid">
      <div class="card"><h2>Náklady</h2><div id="pie-costs" class="chart"></div></div>
      <div class="card"><h2>Výnosy</h2><div id="pie-revenue" class="chart"></div></div>
    </div>
  </div>
</body></html>"""
    return make_response(html)
