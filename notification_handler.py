from flask import current_app
from flask_mail import Message
import traceback
from datetime import datetime
from email.utils import parseaddr
import json

# =================================================================
# === MODUL PRE ODOSIELANIE E-MAILOVÝCH NOTIFIKÁCIÍ ===
# =================================================================

def _send_email(msg):
    """Interná funkcia na odoslanie e-mailu s robustným logovaním chýb."""
    try:
        from app import mail
        mail.send(msg)
        print(f"--- INFO: E-mail '{msg.subject}' bol úspešne odoslaný na {msg.recipients} ---")
        return True
    except Exception as e:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"KRITICKÁ CHYBA: Nepodarilo sa odoslať e-mail '{msg.subject}' na {msg.recipients}")
        print(f"Dôvod: {e}")
        print(traceback.format_exc())
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        return False

def _get_sender_tuple():
    """Pomocná funkcia na spracovanie odosielateľa z konfigurácie."""
    sender_string = current_app.config.get('MAIL_DEFAULT_SENDER')
    return parseaddr(sender_string)

# --- B2C Registrácia ---
def send_b2c_registration_email(customer_email, customer_name):
    """Odošle e-mail zákazníkovi s potvrdením o prijatí registrácie."""
    msg = Message(subject="Vitajte v našom predaji z dvora!", sender=_get_sender_tuple(), recipients=[customer_email])
    msg.html = f"<p>Dobrý deň, <strong>{customer_name}</strong>,</p><p>ďakujeme za Vašu registráciu v našom systéme Predaj z dvora.</p><p>Odteraz sa môžete prihlasovať pomocou Vášho e-mailu a zvoleného hesla.</p><br><p>S pozdravom,<br>Tím MIK s.r.o.</p>"
    return _send_email(msg)

def send_b2c_new_registration_admin_alert(reg_data):
    """Odošle notifikáciu administrátorovi o novej B2C registrácii."""
    msg = Message(subject=f"Nová B2C registrácia: {reg_data['name']}", sender=_get_sender_tuple(), recipients=["info@miksro.sk"])
    msg.html = f"<h3>Nová registrácia v systéme Predaj z dvora</h3><ul><li><strong>Meno:</strong> {reg_data['name']}</li><li><strong>E-mail:</strong> {reg_data['email']}</li><li><strong>Telefón:</strong> {reg_data['phone']}</li></ul>"
    return _send_email(msg)

# --- B2C Objednávky ---
def send_b2c_order_confirmation_email_with_pdf(order_data, pdf_attachment):
    """
    Odošle potvrdenie B2C objednávky s PDF zákazníkovi aj administrátorovi.
    """
    order_number = order_data.get('order_number', 'N/A')
    customer_name = order_data.get('customerName', 'Zákazník')
    customer_email = order_data.get('customerEmail')
    
    if not customer_email:
        print(f"--- VAROVANIE: Chýba e-mail zákazníka pre objednávku {order_number}. E-mail nebol odoslaný. ---")
        return

    # E-mail pre zákazníka
    customer_msg = Message(
        subject=f"Potvrdenie Vašej objednávky #{order_number}",
        sender=_get_sender_tuple(),
        recipients=[customer_email]
    )
    customer_msg.html = f"<p>Dobrý deň, <strong>{customer_name}</strong>,</p><p>ďakujeme, Vaša objednávka <strong>#{order_number}</strong> bola prijatá na spracovanie.</p><p>Finálna cena bude určená po presnom prevážení tovaru. V prílohe nájdete rekapituláciu Vašej objednávky.</p><br><p>S pozdravom,<br>Tím MIK s.r.o.</p>"
    customer_msg.attach(f"objednavka_{order_number}.pdf", "application/pdf", pdf_attachment)
    _send_email(customer_msg)

    # E-mail pre administrátora/expedíciu
    admin_recipients = ["miksroexpedicia@gmail.com", "info@miksro.sk"]
    admin_msg = Message(
        subject=f"Nová B2C objednávka: #{order_number} od {customer_name}",
        sender=_get_sender_tuple(),
        recipients=admin_recipients
    )
    admin_msg.html = f"""
        <h3>Nová objednávka zo systému Predaj z dvora</h3>
        <ul>
            <li><strong>Zákazník:</strong> {customer_name}</li>
            <li><strong>Číslo obj.:</strong> {order_number}</li>
            <li><strong>Dátum vyzdvihnutia:</strong> {datetime.strptime(order_data['deliveryDate'], '%Y-%m-%d').strftime('%d.%m.%Y')}</li>
            <li><strong>Predbežná suma s DPH:</strong> {order_data['totalVat']:.2f} €</li>
        </ul>
        <p>Detail objednávky je v priloženom PDF.</p>
    """
    admin_msg.attach(f"objednavka_{order_number}.pdf", "application/pdf", pdf_attachment)
    return _send_email(admin_msg)

def send_order_ready_email(customer_email, customer_name, order_number, final_price):
    """Odošle notifikáciu zákazníkovi, že jeho objednávka je pripravená."""
    msg = Message(subject=f"Vaša objednávka #{order_number} je pripravená", sender=_get_sender_tuple(), recipients=[customer_email])
    msg.html = f"""
        <p>Dobrý deň, <strong>{customer_name}</strong>,</p>
        <p>Vaša objednávka <strong>#{order_number}</strong> je pripravená na vyzdvihnutie.</p>
        <p>Finálna suma na úhradu po prevážení je: <strong>{final_price:.2f} €</strong>.</p>
        <p>Platba je možná v hotovosti. Tešíme sa na Vašu návštevu!</p>
        <br><p>S pozdravom,<br>Tím MIK s.r.o.</p>
    """
    return _send_email(msg)

def send_points_credited_email(customer_email, customer_name, points_added, new_total_points):
    """Odošle notifikáciu zákazníkovi o pripísaní vernostných bodov."""
    msg = Message(subject="Boli Vám pripísané vernostné body", sender=_get_sender_tuple(), recipients=[customer_email])
    msg.html = f"""
        <p>Dobrý deň, <strong>{customer_name}</strong>,</p>
        <p>ďakujeme za Váš nákup!</p>
        <p>Na Váš vernostný účet sme Vám práve pripísali <strong>{points_added} bodov</strong>.</p>
        <p>Váš celkový počet bodov je teraz <strong>{new_total_points}</strong>.</p>
        <br><p>S pozdravom,<br>Tím MIK s.r.o.</p>
    """
    return _send_email(msg)

def send_b2c_order_cancelled_email(customer_email, customer_name, order_number, reason):
    """Odošle notifikáciu zákazníkovi o zrušení jeho objednávky."""
    msg = Message(subject=f"Vaša objednávka #{order_number} bola zrušená", sender=_get_sender_tuple(), recipients=[customer_email])
    msg.html = f"""
        <p>Dobrý deň, <strong>{customer_name}</strong>,</p>
        <p>s poľutovaním Vám oznamujeme, že Vaša objednávka <strong>#{order_number}</strong> bola zrušená.</p>
        <p><strong>Dôvod:</strong> {reason}</p>
        <p>V prípade otázok nás neváhajte kontaktovať.</p>
        <br><p>S pozdravom,<br>Tím MIK s.r.o.</p>
    """
    return _send_email(msg)

# --- B2B Funkcie (zostávajú nezmenené) ---
def send_registration_pending_email(customer_email, customer_name):
    """Odošle e-mail zákazníkovi s potvrdením o prijatí registrácie."""
    msg = Message(subject="Prijatie Vašej B2B registrácie", sender=_get_sender_tuple(), recipients=[customer_email])
    msg.html = f"<p>Dobrý deň, <strong>{customer_name}</strong>,</p><p>ďakujeme za Vašu registráciu v našom B2B portáli.</p><p>Vašu žiadosť sme prijali a momentálne čaká na schválenie administrátorom. O výsledku Vás budeme informovať v samostatnom e-maile.</p><br><p>S pozdravom,<br>Tím MIK s.r.o.</p>"
    return _send_email(msg)

def send_new_registration_admin_alert(registration_data):
    """Odošle notifikáciu administrátorovi o novej registrácii."""
    msg = Message(subject=f"Nová B2B registrácia: {registration_data['nazov_firmy']}", sender=_get_sender_tuple(), recipients=["info@miksro.sk"])
    msg.html = f"<h3>Nová žiadosť o registráciu v B2B portáli</h3><ul><li><strong>Názov firmy:</strong> {registration_data['nazov_firmy']}</li><li><strong>E-mail:</strong> {registration_data['email']}</li></ul><p>Žiadosť čaká na schválenie.</p>"
    return _send_email(msg)

def send_approval_email(customer_email, customer_name, customer_login_id):
    """Odošle e-mail zákazníkovi o schválení jeho registrácie."""
    msg = Message(subject="Vaša B2B registrácia bola schválená", sender=_get_sender_tuple(), recipients=[customer_email])
    msg.html = f"<p>Dobrý deň, <strong>{customer_name}</strong>,</p><p>Vaša B2B registrácia bola schválená.</p><p>Vaše prihlasovacie číslo odberateľa je: <strong>{customer_login_id}</strong></p><br><p>S pozdravom,<br>Tím MIK s.r.o.</p>"
    return _send_email(msg)
    
def send_order_confirmation_email(order_data, pdf_attachment, csv_attachment):
    """
    Odošle potvrdenie B2B objednávky zákazníkovi a notifikáciu administrátorovi.
    """
    order_number = order_data['order_number']
    
    # E-mail pre zákazníka
    customer_msg = Message(
        subject=f"Potvrdenie objednávky #{order_number}",
        sender=_get_sender_tuple(),
        recipients=[order_data['customerEmail']]
    )
    customer_msg.html = f"<p>Dobrý deň, <strong>{order_data['customerName']}</strong>,</p><p>ďakujeme za Vašu objednávku. Potvrdzujeme jej prijatie.</p><p>V prílohe nájdete detail objednávky.</p><br><p>S pozdravom,<br>Tím MIK s.r.o.</p>"
    customer_msg.attach(f"objednavka_{order_number}.pdf", "application/pdf", pdf_attachment)
    _send_email(customer_msg)

    # E-mail pre administrátora
    admin_msg = Message(
        subject=f"Nová B2B objednávka: #{order_number} od {order_data['customerName']}",
        sender=_get_sender_tuple(),
        recipients=["info@miksro.sk"]
    )
    admin_msg.html = f"""
        <h3>Nová objednávka prijatá cez B2B portál</h3>
        <ul>
            <li><strong>Zákazník:</strong> {order_data['customerName']} (ID odberateľa: {order_data['customerLoginId']})</li>
            <li><strong>Číslo objednávky:</strong> {order_number}</li>
            <li><strong>Požadovaný dátum dodania:</strong> {datetime.strptime(order_data['deliveryDate'], '%Y-%m-%d').strftime('%d.%m.%Y')}</li>
            <li><strong>Celková suma s DPH:</strong> {order_data['totalVat']:.2f} €</li>
        </ul>
        <p>Detail objednávky je priložený v PDF a CSV formáte.</p>
    """
    admin_msg.attach(f"objednavka_{order_number}.pdf", "application/pdf", pdf_attachment)
    admin_msg.attach(f"objednavka_{order_number}.csv", "text/csv", csv_attachment)
    return _send_email(admin_msg)
def send_b2c_order_ready_email(email, customer_name, order_number, final_price):
    subject = f"Objednávka č. {order_number} je pripravená na vyzdvihnutie"
    sender = _get_sender_tuple()

    body_html = f"""
    <p>Dobrý deň, <strong>{customer_name}</strong>,</p>
    <p>Vaša objednávka č. <strong>{order_number}</strong> bola úspešne spracovaná a je pripravená na vyzdvihnutie.</p>
    <p><strong>Suma na úhradu:</strong> {final_price:.2f} €</p>
    <br>
    <p>S pozdravom,<br>
    Tím MIK s.r.o.</p>
    """

    msg = Message(
        subject=subject,
        sender=sender,
        recipients=[email]
    )
    msg.html = body_html

    _send_email(msg)


def send_password_reset_email(customer_email, reset_link):
    """Odošle e-mail s odkazom na obnovu hesla."""
    msg = Message(
        subject="Obnova hesla pre B2B portál",
        sender=_get_sender_tuple(),
        recipients=[customer_email]
    )
    msg.html = f"""
        <p>Dobrý deň,</p>
        <p>obdržali sme žiadosť o obnovu hesla pre Váš účet. Pre nastavenie nového hesla kliknite na nasledujúci odkaz:</p>
        <p><a href="{reset_link}" style="padding: 10px 15px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">Nastaviť nové heslo</a></p>
        <p><small>Odkaz je platný 15 minút. Ak ste o obnovu nežiadali, tento e-mail prosím ignorujte.</small></p>
        <br>
        <p>S pozdravom,<br>Tím MIK s.r.o.</p>
    """
    return _send_email(msg)

