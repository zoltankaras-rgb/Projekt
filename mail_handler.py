
import hashlib
import os
import re
import json
import traceback
from datetime import datetime
from email.utils import getaddresses, parsedate_to_datetime
from flask import current_app, g, request, session
from flask_mail import Message
import imaplib, email, mimetypes
from email.header import decode_header, make_header
from email.policy import default as email_default_policy

import db_connector

# =================================================================
# === KONFIGURÁCIA & POMOCNÉ ======================================
# =================================================================
def _get_env_bool(key, default=False):
    v = os.getenv(key, None)
    if v is None: return bool(default)
    return str(v).strip().lower() in ('1','true','yes','y','on')

def _current_user_id():
    # prispôsob podľa tvojho projektu (ak máš v g.user alebo session)
    try:
        if hasattr(g, 'user') and g.user and 'id' in g.user:
            return g.user['id']
    except Exception:
        pass
    try:
        return session.get('user_id')
    except Exception:
        return None

def _decode_mime(s):
    try:
        return str(make_header(decode_header(s or '')))
    except Exception:
        return s or ''

def _save_attachment_bytes(filename, content_type, data_bytes, message_id=None):
    storage_root = _ensure_storage_dir()
    y = datetime.utcnow().strftime('%Y')
    m = datetime.utcnow().strftime('%m')
    target_dir = os.path.join(storage_root, y, m)
    os.makedirs(target_dir, exist_ok=True)

    safe = re.sub(r'[^a-zA-Z0-9._-]+', '_', filename or 'attachment')
    full_path = os.path.join(target_dir, safe)
    with open(full_path, 'wb') as f:
        f.write(data_bytes or b'')

    size_bytes = os.path.getsize(full_path)
    h = hashlib.sha256()
    with open(full_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    sha_hex = h.hexdigest()

    att_id = db_connector.execute_query(
        """
        INSERT INTO mail_attachments
        (message_id, filename, content_type, size_bytes, storage_path, checksum_sha256, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (message_id, safe, content_type or 'application/octet-stream', size_bytes, full_path, sha_hex, _now()),
        fetch='lastrowid'
    )
    return att_id

def _exists_by_external_uid(uid):
    row = db_connector.execute_query(
        "SELECT id FROM mail_messages WHERE external_uid = %s LIMIT 1",
        (uid,), fetch='one'
    )
    return bool(row and row.get('id'))

def _exists_by_message_id(mid):
    if not mid: return False
    row = db_connector.execute_query(
        "SELECT id FROM mail_messages WHERE message_id_header = %s LIMIT 1",
        (mid,), fetch='one'
    )
    return bool(row and row.get('id'))

def _now():
    return datetime.utcnow()

def _ensure_storage_dir():
    storage = os.getenv('MAIL_STORAGE_PATH', os.path.join(os.getcwd(), 'mail_attachments'))
    os.makedirs(storage, exist_ok=True)
    return storage

def _save_attachment(fs, account_id=None, message_id=None):
    """
    Uloží súbor z request.files (werkzeug.datastructures.FileStorage) na disk
    a vytvorí záznam v tabuľke mail_attachments. Vráti attachment_id.
    """
    try:
        storage_root = _ensure_storage_dir()
        y = datetime.utcnow().strftime('%Y')
        m = datetime.utcnow().strftime('%m')
        target_dir = os.path.join(storage_root, y, m)
        os.makedirs(target_dir, exist_ok=True)

        safe_name = re.sub(r'[^a-zA-Z0-9._-]+', '_', fs.filename or 'attachment')
        full_path = os.path.join(target_dir, safe_name)
        fs.save(full_path)

        size_bytes = os.path.getsize(full_path)
        # SHA-256 (len 64 hex)
        import hashlib
        h = hashlib.sha256()
        with open(full_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        sha_hex = h.hexdigest()

        att_id = db_connector.execute_query(
            """
            INSERT INTO mail_attachments (message_id, filename, content_type, size_bytes, storage_path, checksum_sha256, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (message_id, safe_name, fs.mimetype or 'application/octet-stream', size_bytes, full_path, sha_hex, _now()),
            fetch='lastrowid'
        )
        return att_id
    except Exception:
        print("!!! Chyba pri ukladaní prílohy:", traceback.format_exc())
        raise

def _parse_addresses(value):
    """
    Vezme string alebo list a vráti JSONable list slovníkov: [{name, email}, ...].
    """
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        pairs = []
        for v in value:
            pairs.extend(getaddresses([str(v)]))
    else:
        pairs = getaddresses([str(value)])
    result = []
    for name, email in pairs:
        if email:
            result.append({"name": name or None, "email": email.strip()})
    return result

def _thread_key(subject, from_email, to_emails):
    subject_norm = (subject or '').strip().lower()
    subject_norm = re.sub(r'^(re|fwd):\s*', '', subject_norm)
    key = json.dumps({"s": subject_norm, "f": from_email, "t": sorted([t['email'] for t in to_emails])}, sort_keys=True)
    import hashlib
    return hashlib.sha1(key.encode('utf-8')).hexdigest()

def _insert_message(payload):
    """
    payload: dict s kľúčmi (subset):
      - account_id, direction, folder, subject, from_name, from_email,
        to_json, cc_json, bcc_json, message_id_header, in_reply_to,
        date_header, received_at, sent_at, is_read, is_starred, is_spam,
        body_text, body_html, raw_headers, external_uid, has_attachments
    """
    return db_connector.execute_query(
        """
        INSERT INTO mail_messages
        (account_id, direction, folder, subject, from_name, from_email,
         to_json, cc_json, bcc_json, message_id_header, in_reply_to,
         thread_key, date_header, received_at, sent_at, is_read, is_starred, is_spam,
         body_text, body_html, raw_headers, external_uid, has_attachments, created_at, updated_at)
        VALUES
        (%(account_id)s, %(direction)s, %(folder)s, %(subject)s, %(from_name)s, %(from_email)s,
         %(to_json)s, %(cc_json)s, %(bcc_json)s, %(message_id_header)s, %(in_reply_to)s,
         %(thread_key)s, %(date_header)s, %(received_at)s, %(sent_at)s, %(is_read)s, %(is_starred)s, %(is_spam)s,
         %(body_text)s, %(body_html)s, %(raw_headers)s, %(external_uid)s, %(has_attachments)s, %(created_at)s, %(updated_at)s)
        """,
        payload,
        fetch='lastrowid'
    )
def imap_test_connection():
    host = os.getenv('IMAP_HOST')
    port = int(os.getenv('IMAP_PORT', '993'))
    ssl  = _get_env_bool('IMAP_SSL', True)
    user = os.getenv('IMAP_USERNAME')
    pw   = os.getenv('IMAP_PASSWORD')
    if not (host and user and pw):
        return {"error":"Chýbajú IMAP premenné v .env (IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD)."}
    try:
        if ssl:
            M = imaplib.IMAP4_SSL(host, port)
        else:
            M = imaplib.IMAP4(host, port)
        M.login(user, pw)
        M.logout()
        return {"message":"IMAP OK"}
    except Exception as e:
        return {"error": f"IMAP zlyhal: {e}"}

def fetch_imap(limit=50, folder=None):
    host = os.getenv('IMAP_HOST')
    port = int(os.getenv('IMAP_PORT', '993'))
    ssl  = _get_env_bool('IMAP_SSL', True)
    user = os.getenv('IMAP_USERNAME')
    pw   = os.getenv('IMAP_PASSWORD')
    mailbox = folder or os.getenv('IMAP_FOLDER', 'INBOX')
    if not (host and user and pw):
        return {"error":"Chýbajú IMAP premenné v .env (IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD)."}

    fetched, skipped = 0, 0
    try:
        M = imaplib.IMAP4_SSL(host, port) if ssl else imaplib.IMAP4(host, port)
        M.login(user, pw)
        M.select(mailbox, readonly=False)

        # Vezmeme posledných N podľa UID
        typ, data = M.uid('search', None, 'ALL')
        if typ != 'OK':
            M.logout()
            return {"error": "IMAP SEARCH zlyhal."}

        uids = (data[0] or b'').split()
        if not uids:
            M.logout()
            return {"message":"Žiadne správy.", "fetched":0, "skipped":0}

        uids = uids[-int(limit):]

        for uid in uids:
            uid_str = uid.decode('utf-8', 'ignore')
            ext_uid = f"imap:{uid_str}"
            if _exists_by_external_uid(ext_uid):
                skipped += 1
                continue

            typ, msgdata = M.uid('fetch', uid, '(RFC822)')
            if typ != 'OK' or not msgdata or not msgdata[0]:
                skipped += 1
                continue

            raw = msgdata[0][1]
            msg = email.message_from_bytes(raw, policy=email_default_policy)

            subj = _decode_mime(msg.get('Subject'))
            from_field = msg.get('From', '')
            to_field = msg.get('To', '')
            cc_field = msg.get('Cc', '')
            msg_id = msg.get('Message-Id') or msg.get('Message-ID')
            in_reply_to = msg.get('In-Reply-To')
            date_hdr = msg.get('Date')

            from_list = _parse_addresses(from_field)
            from_name = from_list[0]['name'] if from_list else None
            from_email = from_list[0]['email'] if from_list else None
            to_list = _parse_addresses(to_field)
            cc_list = _parse_addresses(cc_field)

            # dátum
            try:
                date_parsed = parsedate_to_datetime(date_hdr) if date_hdr else _now()
            except Exception:
                date_parsed = _now()

            # body & attachments
            body_text, body_html = "", None
            has_attachments = False

            if msg.is_multipart():
                for part in msg.walk():
                    cdisp = part.get_content_disposition()
                    ctype = part.get_content_type()
                    fname = part.get_filename()
                    if cdisp == 'attachment' or fname:
                        has_attachments = True
                    if cdisp == 'attachment' or fname:
                        fname_dec = _decode_mime(fname) if fname else None
                        data = part.get_payload(decode=True) or b''
                        if not fname_dec:
                            ext = mimetypes.guess_extension(ctype or 'application/octet-stream') or '.bin'
                            fname_dec = f'attachment-{uid_str}{ext}'
                        # uložiť neskôr po inserte správy
                        part._cached_attachment = (fname_dec, ctype, data)  # type: ignore
                    elif ctype == 'text/plain' and not cdisp:
                        body_text += (part.get_content() or "")
                    elif ctype == 'text/html' and not cdisp:
                        body_html = (part.get_content() or body_html)
            else:
                ctype = msg.get_content_type()
                if ctype == 'text/html':
                    body_html = msg.get_content()
                else:
                    body_text = msg.get_content()

            # deduplikácia podľa Message-Id (ak chýba, berieme len podľa UID)
            if msg_id and _exists_by_message_id(msg_id):
                skipped += 1
                continue

            payload = {
                "account_id": None,
                "direction": "incoming",
                "folder": "INBOX",
                "subject": subj or '(bez predmetu)',
                "from_name": from_name,
                "from_email": from_email,
                "to_json": json.dumps(to_list, ensure_ascii=False),
                "cc_json": json.dumps(cc_list, ensure_ascii=False),
                "bcc_json": json.dumps([], ensure_ascii=False),
                "message_id_header": msg_id,
                "in_reply_to": in_reply_to,
                "thread_key": _thread_key(subj, from_email, to_list),
                "date_header": date_parsed,
                "received_at": _now(),
                "sent_at": None,
                "is_read": 0,
                "is_starred": 0,
                "is_spam": 0,
                "body_text": body_text,
                "body_html": body_html,
                "raw_headers": None,
                "external_uid": ext_uid,
                "has_attachments": 1 if has_attachments else 0,
                "created_at": _now(),
                "updated_at": _now(),
            }
            message_row_id = _insert_message(payload)

            # prílohy (ak sú)
            if msg.is_multipart():
                for part in msg.walk():
                    tup = getattr(part, '_cached_attachment', None)
                    if not tup: continue
                    fname_dec, ctype, data = tup
                    _save_attachment_bytes(fname_dec, ctype, data, message_id=message_row_id)

            fetched += 1

        M.close()
        M.logout()
        return {"message":"IMAP hotovo", "fetched": fetched, "skipped": skipped}
    except Exception as e:
        print("!!! CHYBA IMAP fetch:", traceback.format_exc())
        return {"error": f"IMAP fetch zlyhal: {e}", "fetched": fetched, "skipped": skipped}

# =================================================================
# === PUBLIC FUNKCIE PRE ROUTY (VOLÁ app.py) ======================
# =================================================================

def list_messages(folder='INBOX', page=1, page_size=50, query=None, customer_id=None, unread=None, starred=None, has_attach=None):
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 50)))
    offset = (page - 1) * page_size

    where = ["is_deleted = 0"]
    params = []

    # virtual folder: ak prišiel 'folder', filtruj podľa folderu
    if folder:
        where.append("folder = %s"); params.append(folder)

    if query:
        q = f"%{query}%"
        where.append("(subject LIKE %s OR from_email LIKE %s OR body_text LIKE %s)")
        params.extend([q, q, q])

    if customer_id:
        where.append("customer_id = %s"); params.append(int(customer_id))

    if unread is not None:
        where.append("is_read = %s"); params.append(0 if str(unread) in ('1','true','yes','y') else 1)  # unread=1 -> is_read=0

    if starred is not None:
        where.append("is_starred = %s"); params.append(1 if str(starred) in ('1','true','yes','y') else 0)

    if has_attach is not None:
        where.append("has_attachments = %s"); params.append(1 if str(has_attach) in ('1','true','yes','y') else 0)

    rows_sql = f"""
        SELECT
          id, direction, folder, subject, from_name, from_email,
          JSON_EXTRACT(to_json, '$') AS to_json,
          DATE_FORMAT(COALESCE(sent_at, received_at, created_at), '%Y-%m-%d %H:%i:%S') AS ts,
          is_read, is_starred, is_spam, has_attachments
        FROM mail_messages
        WHERE {" AND ".join(where)}
        ORDER BY COALESCE(sent_at, received_at, created_at) DESC
        LIMIT {int(page_size)} OFFSET {int(offset)}
    """
    rows = db_connector.execute_query(rows_sql, params, fetch='all')

    total_sql = f"SELECT COUNT(*) AS c FROM mail_messages WHERE {' AND '.join(where)}"
    total_row = db_connector.execute_query(total_sql, params, fetch='one')
    total = (total_row or {}).get('c', 0)
    return {"items": rows or [], "page": page, "page_size": page_size, "total": total}


def get_message(message_id):
    """Detail správy + prílohy."""
    msg = db_connector.execute_query(
        """
        SELECT * FROM mail_messages WHERE id = %s AND is_deleted = 0
        """, (message_id,), fetch='one'
    )
    if not msg:
        return {"error": "Správa neexistuje."}
    atts = db_connector.execute_query(
        "SELECT id, filename, content_type, size_bytes FROM mail_attachments WHERE message_id = %s ORDER BY id ASC",
        (message_id,), fetch='all'
    )
    msg['attachments'] = atts
    # JSON polia ako Python objekty
    for fld in ('to_json', 'cc_json', 'bcc_json'):
        if isinstance(msg.get(fld), str):
            try:
                msg[fld] = json.loads(msg[fld])
            except Exception:
                msg[fld] = []
    return {"item": msg}

def mark_read(message_id, read=True):
    db_connector.execute_query(
        "UPDATE mail_messages SET is_read = %s, updated_at = %s WHERE id = %s",
        (1 if read else 0, _now(), message_id), fetch='none'
    )
    return {"message": "OK"}

def move_to_folder(message_id, folder):
    if folder not in ('INBOX', 'SENT', 'DRAFTS', 'SPAM', 'TRASH', 'ARCHIVE'):
        return {"error": "Neznáma zložka."}
    db_connector.execute_query(
        "UPDATE mail_messages SET folder = %s, updated_at = %s WHERE id = %s",
        (folder, _now(), message_id), fetch='none'
    )
    return {"message": "OK"}

def delete_message(message_id):
    db_connector.execute_query(
        "UPDATE mail_messages SET is_deleted = 1, updated_at = %s WHERE id = %s",
        (_now(), message_id), fetch='none'
    )
    return {"message": "OK"}

def send_email_from_form(flask_request):
    """
    Príjem z UI (multipart/form-data).
    Polia: to, cc, bcc, subject, body_text, body_html, signature_id (voliteľné), attachments[*]
    """
    try:
        from app import mail  # lazy import
        form = flask_request.form

        # adresy
        to_addrs = _parse_addresses(form.get('to'))
        cc_addrs = _parse_addresses(form.get('cc'))
        bcc_addrs = _parse_addresses(form.get('bcc'))
        subject  = form.get('subject') or '(bez predmetu)'
        body_text = form.get('body_text') or ''
        body_html = form.get('body_html') or None

        # --- podpis -------------------------------------------------
        signature_id = form.get('signature_id')
        sig_html = None
        if signature_id:
            row = db_connector.execute_query("SELECT html FROM mail_signatures WHERE id=%s", (signature_id,), fetch='one')
            if row: sig_html = row['html']
        if not sig_html:
            row = db_connector.execute_query("SELECT html FROM mail_signatures WHERE is_default=1 LIMIT 1", fetch='one')
            if row: sig_html = row['html']

        # zlep HTML/Plain s podpisom
        if sig_html:
            if body_html:
                body_html = (body_html or '') + '<br><br>' + sig_html
            else:
                # strip HTML podpis na plain
                import re
                plain_sig = re.sub(r'<[^>]+>', '', sig_html or '').strip()
                body_text = (body_text or '') + ('\n\n' + plain_sig if plain_sig else '')

        if not to_addrs:
            return {"error": "Pole 'Komu' je povinné."}

        # zostavenie a odoslanie
        msg = Message(subject=subject,
                      recipients=[a['email'] for a in to_addrs],
                      cc=[a['email'] for a in cc_addrs] if cc_addrs else None,
                      bcc=[a['email'] for a in bcc_addrs] if bcc_addrs else None)

        if body_html:
            msg.html = body_html
            if body_text:  # voliteľný plain alternatívny part
                msg.body = body_text
        else:
            msg.body = body_text or '(bez textu)'

        # prílohy
        has_attachments = False
        for fs in flask_request.files.values():
            if not fs or not getattr(fs, 'filename', None):
                continue
            has_attachments = True
            msg.attach(filename=fs.filename,
                       content_type=fs.mimetype or 'application/octet-stream',
                       data=fs.read())
            fs.stream.seek(0)  # reset streamu – neskôr ukladáme na disk

        mail.send(msg)

        # log do DB
        payload = {
            "account_id": None,
            "direction": "outgoing",
            "folder": "SENT",
            "subject": subject,
            "from_name": None, "from_email": None,
            "to_json": json.dumps(to_addrs, ensure_ascii=False),
            "cc_json": json.dumps(cc_addrs, ensure_ascii=False) if cc_addrs else json.dumps([], ensure_ascii=False),
            "bcc_json": json.dumps(bcc_addrs, ensure_ascii=False) if bcc_addrs else json.dumps([], ensure_ascii=False),
            "message_id_header": None, "in_reply_to": None,
            "thread_key": _thread_key(subject, None, to_addrs),
            "date_header": _now(), "received_at": None, "sent_at": _now(),
            "is_read": 1, "is_starred": 0, "is_spam": 0,
            "body_text": body_text, "body_html": body_html,
            "raw_headers": None, "external_uid": None,
            "has_attachments": 1 if has_attachments else 0,
            "created_at": _now(), "updated_at": _now(),
        }
        message_row_id = _insert_message(payload)

        # uloženie príloh na disk
        for fs in flask_request.files.values():
            if not fs or not getattr(fs, 'filename', None):
                continue
            fs.stream.seek(0)
            _save_attachment(fs, message_id=message_row_id)

        # auto-klasifikácia (ak ju máš v súbore)
        try:
            _auto_classify_message(message_row_id, None, to_addrs, subject)
        except Exception:
            pass

        return {"message": "Odoslané.", "id": message_row_id}
    except Exception:
        print("!!! CHYBA pri odosielaní e-mailu:", traceback.format_exc())
        return {"error": "Nepodarilo sa odoslať e-mail."}
def signatures_get_one(sig_id: int):
    row = db_connector.execute_query(
        "SELECT id, name, html, is_default FROM mail_signatures WHERE id=%s",
        (sig_id,), fetch='one'
    )
    if not row:
        return {"error": "Podpis neexistuje."}
    return {"item": row}

def handle_inbound_webhook(flask_request, token):
    """
    End-point pre externé služby (Mailgun/Sendgrid/Postmark...). Overí 'token' podľa .env (MAIL_INBOUND_SECRET).
    Prijíma multipart/form-data alebo JSON. Uloží prijatú správu a prílohy.
    """
    expected = os.getenv('MAIL_INBOUND_SECRET')
    if not expected or token != expected:
        return {"error": "Neplatný alebo chýbajúci token."}, 403

    try:
        # 1) Rozparsovať dáta
        if flask_request.is_json:
            data = flask_request.get_json(silent=True) or {}
            files = []  # JSON hooky zvyčajne posielajú prílohy cez URL, toto MVP ich ignoruje
        else:
            data = flask_request.form.to_dict(flat=True)
            files = list(flask_request.files.values())

        # Provider-agnostické polia
        subj = data.get('subject') or data.get('Subject') or '(bez predmetu)'
        from_field = data.get('from') or data.get('sender') or data.get('From')
        to_field = data.get('to') or data.get('recipient') or data.get('To')
        cc_field = data.get('cc') or data.get('Cc')
        text = data.get('text') or data.get('body-plain') or ''
        html = data.get('html') or data.get('body-html')
        msg_id = data.get('Message-Id') or data.get('message-id') or data.get('message_id')
        in_reply_to = data.get('In-Reply-To') or data.get('in-reply-to') or data.get('in_reply_to')
        date_hdr = data.get('Date') or data.get('date')

        # 2) Normalizácia adries
        from_list = _parse_addresses(from_field)
        from_name = from_list[0]['name'] if from_list else None
        from_email = from_list[0]['email'] if from_list else None
        to_list = _parse_addresses(to_field)
        cc_list = _parse_addresses(cc_field)

        # 3) Datumy
        if date_hdr:
            try:
                date_parsed = parsedate_to_datetime(date_hdr)
            except Exception:
                date_parsed = _now()
        else:
            date_parsed = _now()

        # 4) Insert message
        payload = {
            "account_id": None,
            "direction": "incoming",
            "folder": "INBOX",
            "subject": subj,
            "from_name": from_name,
            "from_email": from_email,
            "to_json": json.dumps(to_list, ensure_ascii=False),
            "cc_json": json.dumps(cc_list, ensure_ascii=False),
            "bcc_json": json.dumps([], ensure_ascii=False),
            "message_id_header": msg_id,
            "in_reply_to": in_reply_to,
            "thread_key": _thread_key(subj, from_email, to_list),
            "date_header": date_parsed,
            "received_at": _now(),
            "sent_at": None,
            "is_read": 0,
            "is_starred": 0,
            "is_spam": 0,
            "body_text": text,
            "body_html": html,
            "raw_headers": None,
            "external_uid": None,
            "has_attachments": 1 if files else 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        message_row_id = _insert_message(payload)

        # 5) Prílohy
        for fs in files:
            if not fs or not getattr(fs, 'filename', None):
                continue
            _save_attachment(fs, message_id=message_row_id)

        return {"message": "OK", "id": message_row_id}
    except Exception:
        print("!!! CHYBA pri prijme e-mailu (webhook):", traceback.format_exc())
        return {"error": "Nepodarilo sa spracovať prichádzajúci e-mail."}, 500
def signatures_list():
    rows = db_connector.execute_query("""
        SELECT id, name, is_default
        FROM mail_signatures
        ORDER BY is_default DESC, name ASC
    """, fetch='all')
    return {"items": rows}

def signatures_create(name, html, is_default=False):
    if is_default:
        db_connector.execute_query("UPDATE mail_signatures SET is_default=0", fetch='none')
    new_id = db_connector.execute_query("""
        INSERT INTO mail_signatures (user_id, name, html, is_default, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (_current_user_id(), name, html, 1 if is_default else 0, _now(), _now()), fetch='lastrowid')
    return {"id": new_id}

def signatures_update(sig_id, name, html, is_default=False):
    if is_default:
        db_connector.execute_query("UPDATE mail_signatures SET is_default=0", fetch='none')
    db_connector.execute_query("""
        UPDATE mail_signatures SET name=%s, html=%s, is_default=%s, updated_at=%s
        WHERE id=%s
    """, (name, html, 1 if is_default else 0, _now(), sig_id), fetch='none')
    return {"message": "OK"}

def signatures_delete(sig_id):
    db_connector.execute_query("DELETE FROM mail_signatures WHERE id=%s", (sig_id,), fetch='none')
    return {"message": "OK"}

def signatures_get_default():
    row = db_connector.execute_query("SELECT id, name, html FROM mail_signatures WHERE is_default=1 LIMIT 1", fetch='one')
    return {"item": row} if row else {"item": None}
def customers_list():
    rows = db_connector.execute_query("""
        SELECT customer_id, MAX(customer_name) AS customer_name
        FROM mail_contact_links
        GROUP BY customer_id
        ORDER BY customer_name
    """, fetch='all')
    return {"items": rows}

def contact_links_create(email, customer_id, customer_name=None, domain=None):
    email = (email or '').strip().lower()
    domain = (domain or (email.split('@')[-1] if '@' in email else None))
    new_id = db_connector.execute_query("""
        INSERT INTO mail_contact_links (email, domain, customer_id, customer_name, created_at)
        VALUES (%s,%s,%s,%s,%s)
    """, (email, domain, int(customer_id), customer_name, _now()), fetch='lastrowid')
    return {"id": new_id}

def message_assign_customer(message_id, customer_id):
    db_connector.execute_query("UPDATE mail_messages SET customer_id=%s, updated_at=%s WHERE id=%s",
                               (int(customer_id), _now(), int(message_id)), fetch='none')
    return {"message": "OK"}
def _auto_classify_message(message_row_id, from_email, to_list, subject):
    cid = None
    # 1) email exact
    if from_email:
        row = db_connector.execute_query(
            "SELECT customer_id FROM mail_contact_links WHERE email=%s LIMIT 1",
            (from_email.strip().lower(),), fetch='one'
        )
        if row: cid = row['customer_id']
        else:
            # 2) domain
            dom = from_email.split('@')[-1].lower()
            row = db_connector.execute_query(
                "SELECT customer_id FROM mail_contact_links WHERE domain=%s LIMIT 1",
                (dom,), fetch='one'
            )
            if row: cid = row['customer_id']

    if cid:
        db_connector.execute_query("UPDATE mail_messages SET customer_id=%s WHERE id=%s",
                                   (cid, message_row_id), fetch='none')

    # 3) pravidlá
    rules = db_connector.execute_query(
        "SELECT * FROM mail_rules WHERE active=1 ORDER BY priority ASC", fetch='all'
    )
    subj = (subject or '').lower()
    sndr = (from_email or '').lower()
    dom  = sndr.split('@')[-1] if '@' in sndr else sndr

    for r in rules or []:
        if r.get('match_sender') and r['match_sender'].lower() not in sndr:
            continue
        if r.get('match_domain') and r['match_domain'].lower() != dom:
            continue
        if r.get('match_subject') and r['match_subject'].lower() not in subj:
            continue

        updates = []
        params  = []
        if r.get('customer_id'):
            updates.append("customer_id=%s"); params.append(r['customer_id'])
        if r.get('target_folder'):
            updates.append("folder=%s"); params.append(r['target_folder'])
        if r.get('set_starred') is not None:
            updates.append("is_starred=%s"); params.append(1 if r['set_starred'] else 0)
        if r.get('set_read') is not None:
            updates.append("is_read=%s"); params.append(1 if r['set_read'] else 0)
        if updates:
            updates.append("updated_at=%s"); params.append(_now())
            params.append(message_row_id)
            db_connector.execute_query(f"UPDATE mail_messages SET {', '.join(updates)} WHERE id=%s",
                                       tuple(params), fetch='none')
        break  # prvé match stačí
def folder_summary():
    """
    Súhrny pre priečinky + TOP zákazníci na paneli vľavo.
    - folders: [{folder, total, unread}]
    - top_customers: [{customer_id, customer_name, total, unread}]
    """
    # počítadlá priečinkov
    folders = db_connector.execute_query("""
        SELECT
          folder,
          SUM(CASE WHEN is_deleted=0 THEN 1 ELSE 0 END)       AS total,
          SUM(CASE WHEN is_deleted=0 AND is_read=0 THEN 1 ELSE 0 END) AS unread
        FROM mail_messages
        GROUP BY folder
    """, fetch='all') or []

    # TOP zákazníci podľa počtu správ
    top_customers = db_connector.execute_query("""
        SELECT
          mm.customer_id,
          COALESCE(MAX(mcl.customer_name), CONCAT('ID ', mm.customer_id)) AS customer_name,
          COUNT(*) AS total,
          SUM(CASE WHEN mm.is_read=0 THEN 1 ELSE 0 END) AS unread
        FROM mail_messages mm
        LEFT JOIN mail_contact_links mcl ON mcl.customer_id = mm.customer_id
        WHERE mm.is_deleted = 0 AND mm.customer_id IS NOT NULL
        GROUP BY mm.customer_id
        ORDER BY total DESC
        LIMIT 10
    """, fetch='all') or []

    return {"folders": folders, "top_customers": top_customers}
