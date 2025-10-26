import csv
import io
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib import colors
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.setFont("DejaVuSans", 9)
        self.drawRightString(20*cm, 1.5*cm, f"Strana {self._pageNumber} z {page_count}")

def create_order_files(order_data):
    """
    Vygeneruje profesionálne PDF a voliteľne CSV pre objednávku.
    """
    csv_content = None
    if order_data.get('items') and 'price' in order_data['items'][0]:
        output_csv = io.StringIO()
        writer = csv.writer(output_csv, delimiter=';')
        
        writer.writerow(['Názov odberateľa:', order_data.get('customerName', '')])
        writer.writerow(['Číslo odberateľa:', order_data.get('customerLoginId', '')])
        writer.writerow(['Dátum dodania:', datetime.strptime(order_data['deliveryDate'], '%Y-%m-%d').strftime('%d.%m.%Y')])
        writer.writerow(['Číslo objednávky:', order_data.get('order_number', '')])
        writer.writerow([]) 
        
        writer.writerow(['EAN kód', 'Názov položky', 'Objednané množstvo', 'Cena bez DPH'])
        
        for item in order_data.get('items', []):
            writer.writerow([
                f"'{str(item.get('ean'))}",
                item.get('name'), 
                f"{float(item.get('quantity', 0)):.2f}".replace('.',','),
                f"{float(item.get('price', 0)):.2f}".replace('.',',')
            ])
            
        csv_content = output_csv.getvalue().encode('utf-8-sig')
        output_csv.close()

    output_pdf = io.BytesIO()
    doc = SimpleDocTemplate(output_pdf, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=2.5*cm)
    
    try:
        pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
    except Exception:
        print("--- VAROVANIE: Font DejaVuSans nebol nájdený. Diakritika v PDF nemusí fungovať správne. ---")

    styles = getSampleStyleSheet()
    styles['Normal'].fontName = 'DejaVuSans'
    styles['Normal'].fontSize = 10
    styles['Normal'].leading = 12

    styles.add(ParagraphStyle(name='Bold', parent=styles['Normal'], fontName='DejaVuSans-Bold'))
    styles.add(ParagraphStyle(name='RightAlign', parent=styles['Normal'], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='Center', parent=styles['Normal'], alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='Address', parent=styles['Normal'], leftIndent=10))
    
    elements = []
    
    logo_path = 'https://www.miksro.sk/wp-content/uploads/2025/09/Dizajn-bez-nazvu-1.png'
    try:
        logo = Image(logo_path, width=5*cm, height=2.5*cm)
        logo.hAlign = 'LEFT'
    except Exception as e:
        logo = Paragraph("MIK s.r.o.", styles['Bold'])
        print(f"--- VAROVANIE: Logo sa nepodarilo načítať. Dôvod: {e} ---")

    header_text = Paragraph(f"<font size='16'>Potvrdenie objednávky</font><br/><font size='12'>{order_data['order_number']}</font>", styles['RightAlign'])
    header_table = Table([[logo, header_text]], colWidths=[8*cm, 9.5*cm], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    elements.append(header_table)
    elements.append(Spacer(1, 1*cm))

    supplier_details = """
        <b>Dodávateľ:</b><br/>
        MIK s.r.o.<br/>
        Hollého 1999/13<br/>
        927 05 Šaľa<br/>
        IČO: 34099514<br/>
        DIČ: 2020374125<br/>
        IČ DPH: SK2020374125<br/>
    """
    customer_details = f"""
        <b>Odberateľ:</b><br/>
        {order_data.get('customerName', 'N/A')}<br/>
        {order_data.get('customerAddress', 'Adresa neuvedená')}<br/><br/>
        <b>ID Zákazníka:</b> {order_data.get('customerLoginId', 'N/A')}
    """
    address_table = Table([[Paragraph(supplier_details, styles['Normal']), Paragraph(customer_details, styles['Normal'])]], 
                          colWidths=[8.75*cm, 8.75*cm], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    elements.append(address_table)
    elements.append(Spacer(1, 1*cm))

    details_data = [[Paragraph(f"<b>Dátum objednania:</b> {order_data.get('order_date', datetime.now().strftime('%d.%m.%Y'))}", styles['Normal']), 
                     Paragraph(f"<b>Požadovaný dátum dodania:</b> {datetime.strptime(order_data['deliveryDate'], '%Y-%m-%d').strftime('%d.%m.%Y')}", styles['RightAlign'])]]
    elements.append(Table(details_data, colWidths=[8.75*cm, 8.75*cm]))
    elements.append(Spacer(1, 0.7*cm))

    is_b2c = 'price_s_dph' in order_data.get('items', [{}])[0]
    if is_b2c:
        table_header = [Paragraph(f'<b>{h}</b>', styles['Normal']) for h in ['Názov produktu', 'Množstvo', 'Predb. Cena/jed.', 'Predb. Spolu s DPH']]
    else:
        table_header = [Paragraph(f'<b>{h}</b>', styles['Normal']) for h in ['EAN', 'Názov produktu', 'Množstvo', 'MJ', 'Cena/MJ', 'Spolu bez DPH']]
    table_data = [table_header]

    for item in order_data.get('items', []):
        cell_html = f"{item.get('name', '')}"
        if item.get('item_note') or item.get('poznamka_k_polozke'):
            cell_html += f"<br/><font size='8.5' color='#4A5568'><i>Pozn: {item.get('item_note') or item.get('poznamka_k_polozke')}</i></font>"
        name_cell_content = Paragraph(cell_html, styles['Normal'])
        
        if is_b2c:
            row = [
                name_cell_content,
                Paragraph(f"{float(item.get('quantity', 0)):.2f} {item.get('unit', 'kg')}", styles['RightAlign']),
                Paragraph(f"{float(item.get('price_s_dph', 0)):.2f} €", styles['RightAlign']),
                Paragraph(f"{float(item.get('price_s_dph', 0)) * float(item.get('quantity', 0)):.2f} €", styles['RightAlign']),
            ]
        else:
            row = [
                Paragraph(str(item.get('ean')), styles['Normal']), name_cell_content,
                Paragraph(f"{float(item.get('quantity', 0)):.2f}", styles['RightAlign']),
                Paragraph(item.get('unit', 'kg'), styles['Center']),
                Paragraph(f"{float(item.get('price', 0)):.2f} €", styles['RightAlign']),
                Paragraph(f"{float(item.get('price', 0)) * float(item.get('quantity', 0)):.2f} €", styles['RightAlign']),
            ]
        table_data.append(row)

    col_widths = [8*cm, 3*cm, 3*cm, 3.5*cm] if is_b2c else [2.5*cm, 7*cm, 2*cm, 1*cm, 2.5*cm, 2.5*cm]
    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F3F4F6')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.5*cm))

    note = order_data.get('note')
    if note and note.strip():
        note_text = f"<b>Poznámka k objednávke:</b><br/>{note.replace('/n', '<br/>')}"
        note_p = Paragraph(note_text, styles['Normal'])
        note_table = Table([[note_p]], colWidths=[17.5*cm], style=[('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F3F4F6')), ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E5E7EB')), ('PADDING', (0,0), (-1,-1), 10),])
        elements.append(note_table)
        elements.append(Spacer(1, 0.5*cm))
        
    reward = order_data.get('uplatnena_odmena_poznamka')
    if reward:
        reward_text = f"<b>Uplatnená vernostná odmena:</b> {reward}"
        reward_p = Paragraph(reward_text, ParagraphStyle(name='RewardStyle', parent=styles['Normal'], textColor=colors.green, fontName='DejaVuSans-Bold'))
        elements.append(reward_p)
        elements.append(Spacer(1, 0.5*cm))

    total_net = order_data.get('totalNet', 0)
    total_vat_price = order_data.get('totalVat', 0)
    total_dph = total_vat_price - total_net

    # --- START CHANGE: Použitie objektu Paragraph pre všetky bunky v súhrne ---
    summary_data = [
        ['', Paragraph('Celkom bez DPH:', styles['RightAlign']), Paragraph(f"{total_net:.2f} €", styles['RightAlign'])],
        ['', Paragraph('DPH:', styles['RightAlign']), Paragraph(f"{total_dph:.2f} €", styles['RightAlign'])],
        ['', Paragraph('<b>Celkom s DPH (predbežne):</b>', styles['RightAlign']), Paragraph(f"<b>{total_vat_price:.2f} €</b>", styles['RightAlign'])],
    ]
    # --- END CHANGE ---

    summary_table = Table(summary_data, colWidths=[12.5*cm, 3*cm, 2*cm], style=[
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTNAME', (0,2), (-1,2), 'DejaVuSans-Bold'),
        ('SIZE', (0,2), (-1,2), 12),
        ('TOPPADDING', (0,2), (-1,2), 8),
        ('LINEABOVE', (1,2), (2,2), 1, colors.black)
    ])
    elements.append(summary_table)
    elements.append(Spacer(1, 1*cm))
    
    elements.append(Paragraph("Ďakujeme za Vašu objednávku.", styles['Center']))
    elements.append(Paragraph("<i>Doklad bol vygenerovaný automaticky podnikovým systémom.</i>", styles['Center']))
    
    doc.build(elements, canvasmaker=NumberedCanvas)
    
    pdf_content = output_pdf.getvalue()
    output_pdf.close()

    return pdf_content, csv_content

