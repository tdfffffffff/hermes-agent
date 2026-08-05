"""hermes-graph-mcp — Microsoft Graph API + IMAP/SMTP wrapper with device code auth."""
from fastapi import FastAPI, HTTPException, Query, Body
import msal, sqlite3, threading, time, os, httpx, json, re
import imaplib, smtplib, base64, email as email_lib
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

app = FastAPI(title="hermes-graph-mcp")

TENANT_ID  = os.environ["AZURE_TENANT_ID"]
CLIENT_ID  = os.environ["AZURE_CLIENT_ID"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DB_PATH    = "/data/tokens.db"
CACHE_PATH = "/data/msal_cache.json"
cache_lock = threading.Lock()

# Graph API scopes
GRAPH_SCOPES = [
    "Mail.ReadBasic", "Mail.ReadWrite", "Mail.Send",
    "Chat.Read", "Chat.ReadWrite",
    "Calendars.Read", "OnlineMeetings.Read",
    "User.Read",
]

# Exchange Online IMAP/SMTP scopes (different OAuth resource)
IMAP_SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
]

IMAP_HOST = "outlook.office365.com"
SMTP_HOST = "smtp.office365.com"

# ── Database ───────────────────────────────────────────────────────────────
def init_db():
    os.makedirs("/data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS auth_users (
        username TEXT PRIMARY KEY,
        ms_email TEXT,
        authenticated_at REAL
    )""")
    conn.commit(); conn.close()

def mark_authenticated(username: str, ms_email: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO auth_users VALUES (?,?,?)",
                 (username, ms_email, time.time()))
    conn.commit(); conn.close()

def get_ms_email(username: str):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT ms_email FROM auth_users WHERE username=?", (username,)).fetchone()
    conn.close()
    return row[0] if row else None

# ── MSAL token cache ───────────────────────────────────────────────────────
def load_cache():
    cache = msal.SerializableTokenCache()
    with cache_lock:
        if os.path.exists(CACHE_PATH):
            cache.deserialize(open(CACHE_PATH).read())
    return cache

def save_cache(cache):
    if cache.has_state_changed:
        with cache_lock:
            open(CACHE_PATH, "w").write(cache.serialize())

def make_app(cache=None):
    return msal.PublicClientApplication(
        client_id=CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )

def _get_token_for_scopes(username: str, scopes: list):
    ms_email = get_ms_email(username)
    if not ms_email:
        return None
    cache = load_cache()
    msal_client = make_app(cache)
    accounts = msal_client.get_accounts()
    acct = next((a for a in accounts if a.get("username", "").lower() == ms_email.lower()), None)
    if not acct:
        return None
    result = msal_client.acquire_token_silent(scopes, account=acct)
    if result and "access_token" in result:
        save_cache(cache)
        return result["access_token"]
    return None

def get_graph_token(username: str):
    return _get_token_for_scopes(username, GRAPH_SCOPES)

def get_imap_token(username: str):
    return _get_token_for_scopes(username, IMAP_SCOPES)

# ── Device code flows ──────────────────────────────────────────────────────
_flow_status = {}       # username -> pending|complete|error:...
_imap_flow_status = {}  # username -> pending|complete|error:...

def _run_device_flow(username: str, flow: dict, scopes_type: str = "graph"):
    cache = load_cache()
    msal_client = make_app(cache)
    result = msal_client.acquire_token_by_device_flow(flow)
    status_dict = _imap_flow_status if scopes_type == "imap" else _flow_status
    if "access_token" in result:
        save_cache(cache)
        if scopes_type == "graph":
            ms_email = result.get("id_token_claims", {}).get("preferred_username", "")
            mark_authenticated(username, ms_email)
        status_dict[username] = "complete"
    else:
        status_dict[username] = "error: " + result.get("error_description", result.get("error", "unknown"))

# ── Health ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "hermes-graph-mcp"}

# ── Auth (Graph) ───────────────────────────────────────────────────────────
@app.get("/auth/start")
def auth_start(username: str = Query(...)):
    if get_graph_token(username):
        return {"status": "already_authenticated"}
    msal_client = make_app()
    flow = msal_client.initiate_device_flow(scopes=GRAPH_SCOPES)
    if "user_code" not in flow:
        raise HTTPException(500, f"Device flow failed: {flow}")
    _flow_status[username] = "pending"
    threading.Thread(target=_run_device_flow, args=(username, flow, "graph"), daemon=True).start()
    return {
        "user_code": flow["user_code"],
        "verification_uri": flow["verification_uri"],
        "message": flow["message"],
        "expires_in": flow.get("expires_in", 900),
    }

@app.get("/auth/status")
def auth_status(username: str = Query(...)):
    if get_graph_token(username):
        return {"status": "complete"}
    return {"status": _flow_status.get(username, "not_started")}

@app.delete("/auth/revoke")
def auth_revoke(username: str = Query(...)):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM auth_users WHERE username=?", (username,))
    conn.commit(); conn.close()
    _flow_status.pop(username, None)
    _imap_flow_status.pop(username, None)
    return {"status": "revoked"}

# ── Auth (IMAP/SMTP) ───────────────────────────────────────────────────────
@app.get("/auth/start-imap")
def auth_start_imap(username: str = Query(...)):
    # First try silent token acquisition using existing session
    token = get_imap_token(username)
    if token:
        return {"status": "already_authenticated"}
    # Need new device code flow for Exchange Online resource
    ms_email = get_ms_email(username)
    if not ms_email:
        raise HTTPException(400, f"'{username}' has no Graph auth yet — call /auth/start first")
    msal_client = make_app()
    flow = msal_client.initiate_device_flow(scopes=IMAP_SCOPES)
    if "user_code" not in flow:
        raise HTTPException(500, f"IMAP device flow failed: {flow}")
    _imap_flow_status[username] = "pending"
    threading.Thread(target=_run_device_flow, args=(username, flow, "imap"), daemon=True).start()
    return {
        "user_code": flow["user_code"],
        "verification_uri": flow["verification_uri"],
        "message": flow["message"],
        "expires_in": flow.get("expires_in", 900),
    }

@app.get("/auth/status-imap")
def auth_status_imap(username: str = Query(...)):
    if get_imap_token(username):
        return {"status": "complete"}
    return {"status": _imap_flow_status.get(username, "not_started")}

# ── IMAP helpers ───────────────────────────────────────────────────────────
def _imap_connect(username: str):
    token = get_imap_token(username)
    if not token:
        raise HTTPException(401, f"'{username}' not authenticated for IMAP — call /auth/start-imap")
    ms_email = get_ms_email(username)
    auth_string = f"user={ms_email}\x01auth=Bearer {token}\x01\x01"
    auth_bytes = base64.b64encode(auth_string.encode())
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        mail.authenticate("XOAUTH2", lambda x: auth_bytes)
        return mail, ms_email
    except Exception as e:
        raise HTTPException(401, f"IMAP authentication failed: {e}")

def _decode_header_str(val):
    if not val:
        return ""
    parts = _decode_header(val)
    out = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(part)
    return " ".join(out)

def _parse_message(raw_bytes):
    msg = email_lib.message_from_bytes(raw_bytes)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not part.get("Content-Disposition"):
                body = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace")
                break
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                    body = re.sub(r'<[^>]+>', ' ', html)
                    body = re.sub(r'\s+', ' ', body).strip()
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                body = re.sub(r'<[^>]+>', ' ', body)
                body = re.sub(r'\s+', ' ', body).strip()
    return {
        "subject":  _decode_header_str(msg.get("Subject", "")),
        "from":     _decode_header_str(msg.get("From", "")),
        "to":       _decode_header_str(msg.get("To", "")),
        "date":     msg.get("Date", ""),
        "body":     body[:4000],
        "message_id": msg.get("Message-ID", ""),
    }

# ── IMAP email endpoints ───────────────────────────────────────────────────
@app.get("/api/imap/emails")
def imap_list_emails(username: str, unread_only: bool = False, days: int = 7, top: int = 20):
    mail, _ = _imap_connect(username)
    try:
        mail.select("INBOX")
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        criteria = f'(SINCE "{since}")'
        if unread_only:
            criteria = f'(UNSEEN SINCE "{since}")'
        _, data = mail.search(None, criteria)
        uids = data[0].split()
        if not uids:
            return {"value": []}
        # Fetch most recent `top` messages
        fetch_uids = uids[-top:][::-1]
        results = []
        for uid in fetch_uids:
            _, msg_data = mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)
            results.append({
                "id":               uid.decode(),
                "subject":          _decode_header_str(msg.get("Subject", "(no subject)")),
                "from":             _decode_header_str(msg.get("From", "")),
                "receivedDateTime": msg.get("Date", ""),
                "isRead":           False if unread_only else None,
                "bodyPreview":      "",
            })
        return {"value": results}
    finally:
        mail.logout()

@app.get("/api/imap/emails/{uid}")
def imap_get_email(uid: str, username: str):
    mail, _ = _imap_connect(username)
    try:
        mail.select("INBOX")
        _, msg_data = mail.fetch(uid.encode(), "(RFC822)")
        if not msg_data or not msg_data[0]:
            raise HTTPException(404, "Email not found")
        raw = msg_data[0][1]
        parsed = _parse_message(raw)
        parsed["id"] = uid
        return parsed
    finally:
        mail.logout()

@app.post("/api/imap/send")
def imap_send_email(username: str, payload: dict = Body(...)):
    token = get_imap_token(username)
    if not token:
        raise HTTPException(401, f"'{username}' not authenticated for SMTP — call /auth/start-imap")
    ms_email = get_ms_email(username)
    auth_string = f"user={ms_email}\x01auth=Bearer {token}\x01\x01"
    auth_bytes = base64.b64encode(auth_string.encode())

    msg = MIMEMultipart()
    msg["From"]    = ms_email
    msg["To"]      = payload["to"]
    msg["Subject"] = payload["subject"]
    msg.attach(MIMEText(payload["body"], "plain"))

    try:
        smtp = smtplib.SMTP(SMTP_HOST, 587)
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.auth("XOAUTH2", lambda: auth_bytes.decode(), initial_response_ok=True)
        smtp.sendmail(ms_email, payload["to"].split(","), msg.as_string())
        smtp.quit()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(500, f"SMTP send failed: {e}")

@app.post("/api/imap/reply")
def imap_reply_email(username: str, payload: dict = Body(...)):
    # Read original email to get headers, then send reply
    orig = imap_get_email(payload["uid"], username)
    return imap_send_email(username, {
        "to":      orig["from"],
        "subject": f"Re: {orig['subject']}",
        "body":    payload["body"],
    })

# ── Graph helpers ──────────────────────────────────────────────────────────
def _gget(username: str, path: str, params: dict = None):
    token = get_graph_token(username)
    if not token:
        raise HTTPException(401, f"'{username}' not authenticated — call /auth/start first")
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{GRAPH_BASE}{path}",
                  headers={"Authorization": f"Bearer {token}"},
                  params=params or {})
    if not r.is_success:
        raise HTTPException(r.status_code, r.text[:400])
    return r.json()

def _gpost(username: str, path: str, body: dict):
    token = get_graph_token(username)
    if not token:
        raise HTTPException(401, f"'{username}' not authenticated — call /auth/start first")
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{GRAPH_BASE}{path}",
                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                   json=body)
    if not r.is_success:
        raise HTTPException(r.status_code, r.text[:400])
    return r.json() if r.content else {"status": "ok"}

# ── Graph email endpoints (kept for orgs with Exchange Online REST) ─────────
@app.get("/api/emails")
def list_emails(username: str, unread_only: bool = False, days: int = 7, top: int = 20):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    filters = [f"receivedDateTime ge {since}"]
    if unread_only:
        filters.append("isRead eq false")
    return _gget(username, "/me/messages", {
        "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
        "$top": top, "$orderby": "receivedDateTime desc",
        "$filter": " and ".join(filters),
    })

@app.get("/api/emails/{email_id}")
def get_email(email_id: str, username: str):
    return _gget(username, f"/me/messages/{email_id}", {
        "$select": "id,subject,from,toRecipients,ccRecipients,body,receivedDateTime,conversationId"
    })

@app.get("/api/emails/{email_id}/thread")
def get_thread(email_id: str, username: str):
    email = _gget(username, f"/me/messages/{email_id}", {"$select": "conversationId"})
    cid = email.get("conversationId", "")
    return _gget(username, "/me/messages", {
        "$filter": f"conversationId eq '{cid}'",
        "$select": "id,subject,from,body,receivedDateTime",
        "$orderby": "receivedDateTime asc", "$top": 20,
    })

@app.post("/api/emails/send")
def send_email(username: str, payload: dict = Body(...)):
    return _gpost(username, "/me/sendMail", {
        "message": {
            "subject": payload["subject"],
            "body": {"contentType": payload.get("body_type", "Text"), "content": payload["body"]},
            "toRecipients": [{"emailAddress": {"address": a.strip()}} for a in payload["to"].split(",")],
        },
        "saveToSentItems": True,
    })

@app.post("/api/emails/{email_id}/reply")
def reply_email(email_id: str, username: str, payload: dict = Body(...)):
    return _gpost(username, f"/me/messages/{email_id}/reply",
                  {"message": {}, "comment": payload["body"]})

# ── Chats ──────────────────────────────────────────────────────────────────
@app.get("/api/chats")
def list_chats(username: str, top: int = 20):
    return _gget(username, "/me/chats", {
        "$select": "id,topic,chatType,lastUpdatedDateTime",
        "$expand": "members", "$top": top,
    })

@app.get("/api/chats/{chat_id}/messages")
def get_chat_messages(chat_id: str, username: str, top: int = 50):
    return _gget(username, f"/me/chats/{chat_id}/messages", {
        "$select": "id,from,body,createdDateTime,messageType", "$top": top,
    })

# ── Calendar ───────────────────────────────────────────────────────────────
@app.get("/api/calendar")
def list_calendar(username: str, days: int = 7, top: int = 20):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    return _gget(username, "/me/calendarView", {
        "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "$select": "id,subject,start,end,attendees,onlineMeeting,bodyPreview,location",
        "$orderby": "start/dateTime asc", "$top": top,
    })


# ── Draft reply (creates draft, does NOT send) ─────────────────────────────
@app.post("/api/emails/{email_id}/draft-reply")
def draft_reply(email_id: str, username: str, payload: dict = Body(...)):
    result = _gpost(username, f"/me/messages/{email_id}/createReply",
                    {"comment": payload["body"]})
    return {"status": "draft_created", "id": result.get("id", ""),
            "message": "Draft saved to Drafts folder — not sent."}

@app.get("/api/me")
def get_me(username: str):
    return _gget(username, "/me", {"": "displayName,mail,userPrincipalName"})

# ── Startup ────────────────────────────────────────────────────────────────
init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)
