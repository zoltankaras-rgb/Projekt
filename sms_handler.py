# -*- coding: utf-8 -*-
# sms_handler.py – O2 SMS Connector (smstools.sk) integrácia

from __future__ import annotations
import os, json, time, ssl, re, urllib.request, urllib.error
from typing import List, Dict, Any, Optional

SMS_API_BASE = os.getenv("SMS_API_BASE") or "https://api-tls12.smstools.sk/3"
SMS_API_KEY  = os.getenv("SMS_API_KEY") or os.getenv("SMSTOOLS_API_KEY") or os.getenv("SMS_TOOLS_API_KEY")
SMS_SENDER_ID = (os.getenv("SMS_SENDER_ID") or "MIK").upper().replace(" ", "")[:11]
SMS_SIMPLE_TEXT_DEFAULT = str(os.getenv("SMS_SIMPLE_TEXT_DEFAULT", "true")).lower() in ("1","true","yes")
SMS_OUTBOX_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads", "sms")
os.makedirs(SMS_OUTBOX_DIR, exist_ok=True)

def _normalize_sender(sender: Optional[str]) -> str:
    s = (sender or SMS_SENDER_ID or "MIK").upper()
    s = re.sub(r"[^A-Z0-9._-]", "", s)  # bez diakritiky a medzier
    return (s or "MIK")[:11]

def normalize_msisdn(number: str, default_cc: str = "421") -> Optional[str]:
    if not number: return None
    n = re.sub(r"[^\d+]", "", str(number))
    if n.startswith("00"): n = "+" + n[2:]
    if n.startswith("+"):  pass
    elif n.startswith(default_cc): n = "+" + n
    elif n.startswith("0") and len(n) >= 9: n = f"+{default_cc}{n[1:]}"
    elif len(n) == 9 and n[0] in "9": n = f"+{default_cc}{n}"
    else: return None
    return n

def _http_post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json;charset=UTF-8", "Accept": "application/json"}
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            raw = resp.read()
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {"id": "INA_CHYBA", "note": "Neplatná JSON odpoveď", "raw": raw[:200].decode("utf-8","ignore")}
    except urllib.error.HTTPError as e:
        return {"id": "HTTP_ERROR", "status": e.code, "note": e.read().decode("utf-8","ignore")}
    except Exception as e:
        return {"id": "NETWORK_ERROR", "note": str(e)}

def send_batch(message: str,
               recipients: List[str],
               sender: Optional[str] = None,
               simple_text: Optional[bool] = None,
               department: Optional[str] = None,
               schedule: Optional[str] = None,
               callback_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Odošle dávku SMS cez /3/send_batch.
    recipients: list už normalizovaných +421… (normalize_msisdn používať vopred)
    """
    if not SMS_API_KEY:
        return {"id": "CONFIG_MISSING", "note": "Chýba SMS_API_KEY v .env"}

    rec = [{"phonenr": r} for r in recipients if r]
    if not rec:
        return {"id": "NO_RECIPIENTS", "note": "Žiadni príjemcovia"}

    payload: Dict[str, Any] = {
        "auth": {"apikey": SMS_API_KEY},
        "data": {
            "message": message or "",
            "sender": {"text": _normalize_sender(sender)},
            "recipients": rec
        }
    }
    if simple_text is None:
        simple_text = SMS_SIMPLE_TEXT_DEFAULT
    payload["data"]["simple_text"] = "true" if simple_text else "false"
    if department:   payload["data"]["department"] = str(department)
    if schedule:     payload["data"]["schedule"]   = str(schedule)
    if callback_url: payload["data"]["callback"]   = {"url": str(callback_url)}

    url = f"{SMS_API_BASE}/send_batch"
    res = _http_post_json(url, payload)

    # ulož „outbox“ log pre audit
    ts = time.strftime("%Y%m%d%H%M%S")
    try:
        fn = os.path.join(SMS_OUTBOX_DIR, f"{ts}_send_batch.json")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(json.dumps({"request": payload, "response": res}, ensure_ascii=False, indent=2))
    except Exception:
        pass
    return res

def get_state(batch_id: Optional[str] = None, msg_id: Optional[str] = None) -> Dict[str, Any]:
    if not SMS_API_KEY:
        return {"id": "CONFIG_MISSING", "note": "Chýba SMS_API_KEY v .env"}
    data: Dict[str, Any] = {}
    if batch_id: data["batch_id"] = batch_id
    if msg_id:   data["msg_id"]   = msg_id
    payload = {"auth": {"apikey": SMS_API_KEY}, "data": data}
    url = f"{SMS_API_BASE}/sms_get_state"
    return _http_post_json(url, payload)
