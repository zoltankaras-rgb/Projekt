# pdf_generator.py
# -----------------------------------------------------------------------------
# Profesionálne PDF + CSV potvrdenie objednávky (Unicode/diakritika, logo,
# blok Dodávateľ/ Odberateľ, rozpis DPH, čisté tabuľky, A4 layout).
# Názov a EAN sú v jednom stĺpci „Položka“; numerické stĺpce majú pevné šírky,
# hlavičky sa lámu do 2 riadkov, čísla sú v Paragraphoch (Num) → nič nepretŕča.
# DOPLNENÉ: Vyzdvihnutie / doručenie + Odmeny v PDF aj CSV.
# -----------------------------------------------------------------------------

import os
import io
import csv
from html import escape as html_escape
from datetime import datetime, date

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, Image
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ──────────────── Brand / farby ────────────────
BRAND = colors.HexColor("#b91c1c")
ACC   = colors.HexColor("#111827")
GRAY  = colors.HexColor("#6b7280")
LINE  = colors.HexColor("#e5e7eb")
HEAD  = colors.HexColor("#f3f4f6")

# ──────────────── Helpery ────────────────
def _esc(s) -> str:
    return html_escape("" if s is None else str(s))

def _pick(dct, *keys, default=""):
    for k in keys:
        if k in dct and dct[k] not in (None, ""):
            return dct[k]
    return default

def _to_float(x, default=0.0):
    try:
        if x is None or x == "":
            return float(default)
        return float(x)
    except Exception:
        return float(default)

def _fmt_eur(val: float) -> str:
    s = f"{float(val):,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", " ")
    return f"{s} €"

def _safe_date_str(s):
    if not s:
        return ""
    if isinstance(s, (datetime, date)):
        return s.strftime("%d.%m.%Y")
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        return str(s)

def _fmt_dw(raw: str) -> str:
    """Ľudské zobrazenie časového okna (podporuje 'workdays_*' aj 'YYYY-MM-DD_0800-1200')."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if "workdays_08_12" in low:
        return "Po–Pia 08:00–12:00"
    if "workdays_12_15" in low:
        return "Po–Pia 12:00–15:00"
    if "_" in raw and raw[:10].count("-") == 2:
        try:
            d = datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
            label = raw[11:].replace("-", "–")
            # ak má tvar 0800-1200 → 08:00–12:00
            if len(label) >= 9 and label[4] == '0' or label[4] == '1':
                return f"{d} • {label[:2]}:{label[2:4]}–{label[5:7]}:{label[7:9]}"
            return f"{d} • {label}"
        except Exception:
            pass
    return raw

# ──────────────── Fonty s diakritikou ────────────────
def _try_register_font(name, path):
    try:
        if path and os.path.isfile(path):
            pdfmetrics.registerFont(TTFont(name, path))
            return True
    except Exception:
        pass
    return False

def _register_fonts():
    base_env = os.getenv("PDF_FONT_PATH")
    bold_env = os.getenv("PDF_FONT_BOLD_PATH")
    base_candidates = [
        base_env,
        "static/fonts/DejaVuSans.ttf",
        "assets/fonts/DejaVuSans.ttf",
        "fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/DejaVuSans.ttf",
    ]
    bold_candidates = [
        bold_env,
        "static/fonts/DejaVuSans-Bold.ttf",
        "assets/fonts/DejaVuSans-Bold.ttf",
        "fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/DejaVuSans-Bold.ttf",
    ]

    base_name = "DejaVuSans"
    bold_name = "DejaVuSans-Bold"
    base_ok = any(_try_register_font(base_name, p) for p in base_candidates if p)
    bold_ok = any(_try_register_font(bold_name, p) for p in bold_candidates if p)

    if not base_ok:
        if _try_register_font("NotoSans", "static/fonts/NotoSans-Regular.ttf"):
            base_name = "NotoSans"
            if _try_register_font("NotoSans-Bold", "static/fonts/NotoSans-Bold.ttf"):
                bold_name = "NotoSans-Bold"
            else:
                bold_name = base_name
        elif _try_register_font("Arial", "C:/Windows/Fonts/arial.ttf"):
            base_name = "Arial"
            if _try_register_font("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"):
                bold_name = "Arial-Bold"
            else:
                bold_name = base_name
        else:
            base_name = "Helvetica"
            bold_name = "Helvetica-Bold"
    if not bold_ok and bold_name == "DejaVuSans-Bold":
        bold_name = base_name

    return base_name, bold_name

# ──────────────── Logo ────────────────
def _load_logo(order_data: dict):
    p = _pick(order_data, "company_logo_path", default=None) or os.getenv("PDF_LOGO_PATH")
    if not p:
        for candidate in ("static/logo.png", "static/img/logo.png", "assets/logo.png"):
            if os.path.isfile(candidate):
                p = candidate
                break
    if p and os.path.isfile(p):
        try:
            img = Image(p)
            img.drawHeight = 45
            img.drawWidth  = 150
            img.hAlign = "LEFT"
            return img
        except Exception:
            return None
    return None

# ──────────────── CSV ────────────────
def _make_csv(order):
    sio = io.StringIO(newline="")
    w = csv.writer(sio, delimiter=';', quoting=csv.QUOTE_MINIMAL)

    w.writerow(["Objednávka", order["order_no"]])
    w.writerow(["Zákazník", order["customer_name"]])
    w.writerow(["Adresa", order["customer_address"]])
    w.writerow(["Dátum dodania", _safe_date_str(order["delivery_date"])])
    if order.get("delivery_window"):
        w.writerow(["Vyzdvihnutie / doručenie", order["delivery_window"]])
    if order.get("points_reward_note"):
        w.writerow(["Vernostná odmena", order["points_reward_note"]])
    if order.get("rewards"):
        for r in order["rewards"]:
            w.writerow(["Odmena (darček)", f"{r.get('label','Odmena')} × {r.get('qty',1)}"])
    if order["note"]:
        w.writerow(["Poznámka", order["note"]])
    w.writerow([])

    # hlavička položiek – pridávam posledný stĺpec
    w.writerow([
        "Položka", "EAN", "MJ", "Množstvo",
        "Cena bez DPH", "DPH %",
        "Medzisúčet bez DPH", "DPH €", "Suma s DPH",
        "Cenníková cena bez DPH"
    ])

    for it in order["items"]:
        plp = it.get("pricelist_price")
        plp_str = f"{_to_float(plp):.2f}" if plp is not None else ""
        w.writerow([
            it["name"], it["ean"], it["unit"],
            f"{it['qty']:.2f}", f"{it['price']:.2f}", f"{it['dph']:.2f}",
            f"{it['line_net']:.2f}", f"{it['line_vat']:.2f}", f"{it['line_gross']:.2f}",
            plp_str
        ])

    w.writerow([])
    w.writerow(["DPH rozpis"])
    w.writerow(["Sadzba", "Základ bez DPH", "DPH €"])
    printed = set()
    for r in order["canonical_rates"]:
        w.writerow([f"{r:.2f} %", f"{order['base_by_rate'].get(r,0.0):.2f}", f"{order['vat_by_rate'].get(r,0.0):.2f}"])
        printed.add(r)
    for r in order["rates_sorted"]:
        if r not in printed:
            w.writerow([f"{r:.2f} %", f"{order['base_by_rate'][r]:.2f}", f"{order['vat_by_rate'][r]:.2f}"])

    w.writerow([])
    w.writerow(["Celkom bez DPH", f"{order['total_net']:.2f}"])
    w.writerow(["DPH spolu", f"{order['total_vat']:.2f}"])
    w.writerow(["Celkom s DPH", f"{order['total_gross']:.2f}"])

    return sio.getvalue().encode("utf-8-sig")

# ──────────────── PDF ────────────────
def _make_pdf(order):
    base_font, bold_font = _register_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=26, bottomMargin=26, leftMargin=28, rightMargin=28
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Small',  parent=styles['Normal'], fontName=base_font, fontSize=9,  leading=12, textColor=GRAY))
    styles.add(ParagraphStyle(name='Tiny',   parent=styles['Normal'], fontName=base_font, fontSize=8,  leading=10, textColor=GRAY))
    styles.add(ParagraphStyle(name='Right',  parent=styles['Normal'], fontName=base_font, alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='Center', parent=styles['Normal'], fontName=base_font, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='HeadC',  parent=styles['Normal'], fontName=bold_font, alignment=TA_CENTER, fontSize=9))
    styles.add(ParagraphStyle(name='H2',     parent=styles['Heading2'], fontName=bold_font, textColor=BRAND, spaceBefore=6, spaceAfter=6))
    styles['Normal'].fontName = base_font
    styles['Title'].fontName  = bold_font

    num_style = ParagraphStyle('Num', parent=styles['Right'], fontName=base_font, fontSize=9, rightIndent=0)

    story = []

    # Horný pás: logo + názov dokumentu a číslo
    logo = _load_logo(order)
    right_block = [
        [Paragraph(f"<font color='{ACC.hexval()}' size='14'><b>Potvrdenie objednávky</b></font>", styles['Right'])],
        [Paragraph(f"<b>Číslo:</b> {_esc(order['order_no'])}", styles['Right'])],
        [Paragraph(f"<b>Dátum dodania:</b> {_safe_date_str(order['delivery_date'])}", styles['Right'])],
    ]
    head_tbl = Table(
        [[logo if logo else Paragraph("<b>MIK s.r.o.</b>", styles['Normal']), right_block]],
        colWidths=[doc.width * 0.46, doc.width * 0.54]
    )
    head_tbl.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LINEBELOW', (0,0), (-1,0), 0.8, BRAND),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(head_tbl)
    story.append(Spacer(1, 8))

    # Dodávateľ / Odberateľ
    supplier_name   = os.getenv("PDF_SUPPLIER_NAME",   "MIK, s.r.o.")
    supplier_ico    = os.getenv("PDF_SUPPLIER_ICO",    "34099514")
    supplier_dic    = os.getenv("PDF_SUPPLIER_DIC",    "2020374125")
    supplier_icdph  = os.getenv("PDF_SUPPLIER_ICDPH",  "SK 2020374125, podľa §4, registrácia od 26.9.1994")
    supplier_addr   = os.getenv("PDF_SUPPLIER_ADDR",   "Hollého č.1999/13\n927 05 Šaľa")

    supplier_block = [
        Paragraph("<b>Dodávateľ</b>", styles['Normal']),
        Paragraph(_esc(supplier_name), styles['Normal']),
        Paragraph(f"IČO: {_esc(supplier_ico)}", styles['Small']),
        Paragraph(f"DIČ: {_esc(supplier_dic)}", styles['Small']),
        Paragraph(f"IČ DPH: {_esc(supplier_icdph)}", styles['Small']),
        Paragraph(_esc(supplier_addr).replace("\n", "<br/>"), styles['Small']),
    ]
    customer_block = [
        Paragraph("<b>Odberateľ</b>", styles['Normal']),
        Paragraph(_esc(order['customer_name'] or "—"), styles['Normal']),
        Paragraph(_esc(order['customer_address'] or "—").replace("\n", "<br/>"), styles['Small']),
    ]
    duo = Table([[supplier_block, customer_block]], colWidths=[doc.width * 0.48, doc.width * 0.52])
    duo.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.5, LINE),
        ('INNERGRID', (0,0), (-1,-1), 0.5, LINE),
        ('BACKGROUND', (0,0), (0,0), HEAD),
        ('BACKGROUND', (1,0), (1,0), HEAD),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(duo)
    if order.get("note"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>Poznámka:</b> {_esc(order['note'])}", styles['Normal']))
    story.append(Spacer(1, 8))

    # ─────────────── VYZDVIHNUTIE + ODMENY blok (nové) ───────────────
    extras_rows = []
    if order.get("delivery_window"):
        extras_rows.append([
            Paragraph("<b>Vyzdvihnutie / doručenie</b>", styles['Normal']),
            Paragraph(_esc(order["delivery_window"]), styles['Normal'])
        ])

    if order.get("points_reward_note") or order.get("rewards"):
        # Build bullet list: vernostná + darčeky
        bullets_html = []
        if order.get("points_reward_note"):
            bullets_html.append(f"Vernostná odmena: {_esc(order['points_reward_note'])}")
        for r in (order.get("rewards") or []):
            bullets_html.append(f"{_esc(r.get('label') or 'Odmena')} × {_esc(r.get('qty') or 1)}")
        bullets_html = "<br/>".join(f"• {line}" for line in bullets_html)
        extras_rows.append([
            Paragraph("<b>Odmeny</b>", styles['Normal']),
            Paragraph(bullets_html, styles['Normal'])
        ])

    if extras_rows:
        extras_tbl = Table(extras_rows, colWidths=[doc.width*0.30, doc.width*0.70])
        extras_tbl.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 0.5, LINE),
            ('INNERGRID', (0,0), (-1,-1), 0.5, LINE),
            ('BACKGROUND', (0,0), (0,0), HEAD),
            ('BACKGROUND', (0,1), (0,-1), HEAD),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(extras_tbl)
        story.append(Spacer(1, 10))

    # ─────────────── Tabuľka položiek ───────────────
    colw = [190, 28, 46, 60, 36, 68, 48, 63]  # Položka | MJ | Množstvo | Cena | % | Základ | DPH | Spolu

    head = [
        Paragraph("Položka", styles['HeadC']),
        Paragraph("MJ", styles['HeadC']),
        Paragraph("Množstvo", styles['HeadC']),
        Paragraph("Cena<br/>bez DPH", styles['HeadC']),
        Paragraph("DPH<br/>%", styles['HeadC']),
        Paragraph("Základ<br/>bez DPH", styles['HeadC']),
        Paragraph("DPH €", styles['HeadC']),
        Paragraph("Spolu<br/>s DPH", styles['HeadC']),
    ]
    data = [head]

    for it in order["items"]:
        item_lines = f"<b>{_esc(it['name'])}</b><br/><font size='8' color='{GRAY.hexval()}'>EAN: {_esc(it['ean'])}</font>"
        if it.get("item_note"):
            item_lines += f"<br/><font size='8' color='{GRAY.hexval()}'>Pozn.: {_esc(it['item_note'])}</font>"

        data.append([
            Paragraph(item_lines, styles['Normal']),
            Paragraph(_esc(it["unit"]), styles['Center']),
            Paragraph(f"{it['qty']:.2f}", num_style),
            Paragraph(f"{it['price']:.2f}", num_style),
            Paragraph(f"{it['dph']:.2f}", num_style),
            Paragraph(f"{it['line_net']:.2f}", num_style),
            Paragraph(f"{it['line_vat']:.2f}", num_style),
            Paragraph(f"{it['line_gross']:.2f}", num_style),
        ])

    items_tbl = Table(data, colWidths=colw, repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), base_font),
        ('GRID', (0,0), (-1,-1), 0.3, LINE),
        ('BACKGROUND', (0,0), (-1,0), HEAD),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('VALIGN', (0,1), (-1,-1), 'TOP'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.whitesmoke]),
        ('LEFTPADDING',  (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING',  (2,1), (-1,-1), 2),
        ('RIGHTPADDING', (2,1), (-1,-1), 2),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 12))

    # Rozpis DPH podľa sadzieb
    story.append(Paragraph("<b>Rozpis podľa sadzieb DPH</b>", styles['Normal']))
    vat_rows = [[Paragraph("Sadzba", styles['HeadC']),
                 Paragraph("Základ<br/>bez DPH", styles['HeadC']),
                 Paragraph("DPH €", styles['HeadC'])]]
    printed = set()
    for rate in order["canonical_rates"]:
        vat_rows.append([
            Paragraph(f"{rate:.2f} %", styles['Center']),
            Paragraph(f"{order['base_by_rate'].get(rate,0.0):.2f}", num_style),
            Paragraph(f"{order['vat_by_rate'].get(rate,0.0):.2f}",  num_style),
        ])
        printed.add(rate)
    for rate in order["rates_sorted"]:
        if rate not in printed:
            vat_rows.append([
                Paragraph(f"{rate:.2f} %", styles['Center']),
                Paragraph(f"{order['base_by_rate'][rate]:.2f}", num_style),
                Paragraph(f"{order['vat_by_rate'][rate]:.2f}",  num_style),
            ])

    vat_tbl = Table(vat_rows, colWidths=[100, 160, 120])
    vat_tbl.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), base_font),
        ('GRID', (0,0), (-1,-1), 0.3, LINE),
        ('BACKGROUND', (0,0), (-1,0), HEAD),
        ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING',(0,0), (-1,-1), 4),
    ]))
    story.append(vat_tbl)
    story.append(Spacer(1, 10))

    # Súhrn (vpravo)
    summary_tbl = Table([
        ["Celkom bez DPH:", _fmt_eur(order["total_net"])],
        ["DPH spolu:",      _fmt_eur(order["total_vat"])],
        ["Celkom s DPH:",   _fmt_eur(order["total_gross"])],
    ], colWidths=[200, 140])
    summary_tbl.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), base_font),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('LINEABOVE', (0,2), (-1,2), 0.5, LINE),
        ('FONTNAME', (0,2), (1,2), bold_font),
        ('TEXTCOLOR', (0,2), (1,2), ACC),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    wrap = Table([[summary_tbl]], colWidths=[doc.width], hAlign='RIGHT')
    wrap.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'RIGHT')]))
    story.append(wrap)
    story.append(Spacer(1, 12))

    # Podpisy
    sign_tbl = Table([
        ["Vystavil", "", "Prevzal"],
        ["", "", ""]
    ], colWidths=[doc.width*0.33, doc.width*0.34, doc.width*0.33])
    sign_tbl.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), base_font),
        ('LINEABOVE', (0,1), (0,1), 0.6, LINE),
        ('LINEABOVE', (2,1), (2,1), 0.6, LINE),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    story.append(sign_tbl)
    story.append(Spacer(1, 6))

    # Pätička
    gen = datetime.now().strftime("%d.%m.%Y %H:%M")
    foot = Paragraph(f"<font size='8' color='{GRAY.hexval()}'>Vygenerované {gen}</font>",
                     ParagraphStyle('Foot', fontName=base_font, alignment=TA_RIGHT))
    story.append(KeepTogether(foot))

    doc.build(story)
    return buf.getvalue()

# ──────────────── Vstup → výpočet → CSV + PDF ────────────────
def create_order_files(order_data: dict):
    """
    Očakáva order_data s kľúčmi:
      - order_number, customerName, customerAddress, deliveryDate, note, items
      - voliteľne: deliveryWindowPretty | delivery_window
                   rewards: [ {label, qty, ...}, ... ]
                   uplatnena_odmena_poznamka (vernostná odmena)
    """
    # primárne info
    order_no   = _pick(order_data, "orderNumber", "order_number", default="—")
    cust_name  = _pick(order_data, "customerName", "customer_name", default="")
    cust_addr  = _pick(order_data, "customerAddress", "customer_address", default="")
    deliv_date = _pick(order_data, "deliveryDate", "delivery_date", default="")
    note       = _pick(order_data, "note", default="")
    raw_items  = order_data.get("items", []) or []

    # doplnky – delivery window + odmeny
    dw_raw     = _pick(order_data, "deliveryWindowPretty", "delivery_window", default="")
    delivery_window = _fmt_dw(dw_raw) if dw_raw else ""
    points_reward_note = _pick(order_data, "uplatnena_odmena_poznamka", default="")  # vernostná odmena textom
    rewards_list = []
    for r in (order_data.get("rewards") or []):
        if not isinstance(r, dict): 
            continue
        rewards_list.append({"label": r.get("label") or "Odmena", "qty": r.get("qty") or 1})

    # položky + súčty
    items = []
    rates = set()
    total_net = 0.0
    total_vat = 0.0
    for it in raw_items:
        name = it.get("name") or it.get("nazov_vyrobku") or ""
        ean  = it.get("ean")  or it.get("ean_produktu") or ""
        unit = it.get("unit") or it.get("mj") or "ks"
        qty  = _to_float(it.get("quantity") or it.get("mnozstvo"))
        price= _to_float(it.get("price") or it.get("cena") or it.get("cena_bez_dph"))
        dph  = abs(_to_float(it.get("dph") or it.get("vat") or it.get("dph_percent")))
        line_net   = _to_float(it.get("line_net"),   default=price * qty)
        line_vat   = _to_float(it.get("line_vat"),   default=line_net * (dph/100.0))
        line_gross = _to_float(it.get("line_gross"), default=line_net + line_vat)
        total_net += line_net
        total_vat += line_vat
        rates.add(dph)
        items.append({
            "name": name, "ean": ean, "unit": unit,
            "qty": qty, "price": price, "dph": dph,
            "line_net": line_net, "line_vat": line_vat, "line_gross": line_gross,
            "item_note": it.get("item_note") or "",
        })

    total_gross = total_net + total_vat
    canonical = [5.0, 10.0, 19.0, 23.0]
    base_by_rate = {r: 0.0 for r in canonical}
    vat_by_rate  = {r: 0.0 for r in canonical}
    for it in items:
        r = float(it["dph"])
        base_by_rate[r] = base_by_rate.get(r, 0.0) + it["line_net"]
        vat_by_rate[r]  = vat_by_rate.get(r, 0.0)  + it["line_vat"]
    others = sorted([r for r in rates if r not in canonical])

    # skompilované dáta pre PDF/CSV
    order = {
        "order_no": order_no,
        "customer_name": cust_name,
        "customer_address": cust_addr,
        "delivery_date": deliv_date,
        "delivery_window": delivery_window,              # NOVÉ: pekne formátované časové okno
        "points_reward_note": points_reward_note,        # vernostná odmena (string)
        "rewards": rewards_list,                         # darčeky (list)
        "note": note,
        "items": items,
        "total_net": total_net,
        "total_vat": total_vat,
        "total_gross": total_gross,
        "canonical_rates": canonical,
        "rates_sorted": others,
        "base_by_rate": base_by_rate,
        "vat_by_rate":  vat_by_rate,
        "company_logo_path": order_data.get("company_logo_path"),
    }

    csv_bytes = _make_csv(order)
    pdf_bytes = _make_pdf(order)
    return pdf_bytes, csv_bytes
