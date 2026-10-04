from fastapi import FastAPI, Query, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os, json, time, base64, threading, re, html as _html_mod
from pathlib import Path
from typing import Optional
import urllib.request, urllib.parse, urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders as email_encoders

def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = _html_mod.unescape(text)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('\xa0', ' ').strip()
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text

app = FastAPI(title="Hermes Gmail MCP")

def _load_credentials():
    _f = Path("/data/gmail-mcp/client_secrets.json")
    if _f.exists():
        try:
            _d = json.loads(_f.read_text())
            return _d.get("client_id", ""), _d.get("client_secret", "")
        except Exception:
            pass
    return os.environ.get("GMAIL_CLIENT_ID", ""), os.environ.get("GMAIL_CLIENT_SECRET", "")

CLIENT_ID, CLIENT_SECRET = _load_credentials()

# Pending sends: {pending_id: {username, to, subject, body, raw, staged_at}}
pending_sends = {}
pending_lock  = threading.Lock()
TOKEN_DIR     = Path("/data/tokens")
TOKEN_DIR.mkdir(parents=True, exist_ok=True)

AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL    = "https://oauth2.googleapis.com/token"
REVOKE_URL   = "https://oauth2.googleapis.com/revoke"
REDIRECT_URI = "http://localhost:8084/auth/callback"

SCOPES = " ".join([
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
])


# ── Helpers ───────────────────────────────────────────────────────────────────

def token_path(username: str) -> Path:
    return TOKEN_DIR / f"{username}.json"

def load_creds(username: str) -> Optional[dict]:
    p = token_path(username)
    return json.loads(p.read_text()) if p.exists() else None

def save_creds(username: str, data: dict):
    token_path(username).write_text(json.dumps(data))

def http_post(url: str, data: dict) -> dict:
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded,
          headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())

def http_get_auth(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()[:500]}

def get_valid_token(username: str) -> Optional[str]:
    creds = load_creds(username)
    if not creds:
        return None
    if creds.get("expires_at", 0) > time.time() + 60:
        return creds["access_token"]
    if not creds.get("refresh_token"):
        return None
    r = http_post(TOKEN_URL, {
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": creds["refresh_token"],
        "grant_type":    "refresh_token",
    })
    if "access_token" in r:
        creds["access_token"] = r["access_token"]
        creds["expires_at"]   = time.time() + r.get("expires_in", 3600)
        save_creds(username, creds)
        return creds["access_token"]
    return None

def gmail_get(username: str, path: str, params=None) -> dict:
    token = get_valid_token(username)
    if not token:
        return {"error": "not_authenticated"}
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/{path}"
    if params:
        # support list of tuples for repeated params (e.g. metadataHeaders)
        url += "?" + urllib.parse.urlencode(params)
    return http_get_auth(url, token)

def gmail_delete(username: str, path: str) -> dict:
    token = get_valid_token(username)
    if not token:
        return {"error": "not_authenticated"}
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/{path}"
    req = urllib.request.Request(url, method="DELETE",
          headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            return json.loads(body) if body else {"status": "deleted"}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()[:500]}

def gmail_post(username: str, path: str, body: dict) -> dict:
    token = get_valid_token(username)
    if not token:
        return {"error": "not_authenticated"}
    url  = f"https://gmail.googleapis.com/gmail/v1/users/me/{path}"
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data,
           headers={"Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()[:500]}

def body_to_html(text: str) -> str:
    import html, re

    def _is_bullet(line):
        return bool(re.match(r'^[-*•]\s', line.lstrip()))

    def _strip_marker(line):
        return re.sub(r'^[-*•]\s+', '', line.lstrip())

    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'\r\n', '\n', text).strip()
    blocks = re.split(r'\n{2,}', text)
    parts = []
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue
        bullet_idx = [i for i, l in enumerate(lines) if _is_bullet(l)]
        if bullet_idx and bullet_idx[0] == 0:
            # All-bullet block
            items = ''.join('<li>' + html.escape(_strip_marker(l)) + '</li>'
                            for l in lines if _is_bullet(l))
            parts.append('<ul style="margin:0 0 12px 0;padding-left:20px">' + items + '</ul>')
        elif bullet_idx:
            # Intro text followed by bullet items — split at first bullet
            first_b = bullet_idx[0]
            intro = '<br>'.join(html.escape(l) for l in lines[:first_b])
            parts.append('<p style="margin:0 0 4px 0">' + intro + '</p>')
            items = ''.join('<li>' + html.escape(_strip_marker(l)) + '</li>'
                            for l in lines[first_b:] if _is_bullet(l))
            parts.append('<ul style="margin:0 0 12px 0;padding-left:20px">' + items + '</ul>')
        elif (len(lines) >= 2 and len(lines[0]) <= 60
              and any(len(l) > 80 for l in lines[1:])):
            # Short heading + long body — bold the heading
            heading = html.escape(lines[0])
            rest = '<br>'.join(html.escape(l) for l in lines[1:])
            parts.append(
                '<p style="margin:0 0 12px 0">'
                '<strong>' + heading + '</strong><br>' + rest + '</p>'
            )
        else:
            content = '<br>'.join(html.escape(l) for l in lines)
            parts.append('<p style="margin:0 0 12px 0">' + content + '</p>')
    return (
        '<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        'color:#202124;line-height:1.6">'
        + ''.join(parts)
        + '</body></html>'
    )

def make_raw(to: str, subject: str, body: str,
             reply_to_id: str = None, thread_id: str = None,
             attachments: list = None) -> dict:
    html_body  = body_to_html(body)
    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(html_body, "html"))
        for att in attachments:
            mime_type = att.get("mime_type", "application/octet-stream")
            main, sub = (mime_type.split("/", 1) if "/" in mime_type
                         else ("application", "octet-stream"))
            part = MIMEBase(main, sub)
            part.set_payload(base64.b64decode(att["data"]))
            email_encoders.encode_base64(part)
            part.add_header("Content-Disposition",
                            f'attachment; filename="{att["filename"]}"')
            msg.attach(part)
    else:
        msg = MIMEText(html_body, "html")

    msg["To"]      = to
    msg["Subject"] = subject
    if reply_to_id:
        msg["In-Reply-To"] = reply_to_id
        msg["References"]  = reply_to_id
    raw    = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = {"raw": raw}
    if thread_id:
        result["threadId"] = thread_id
    return result

def parse_headers(msg: dict) -> dict:
    return {h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])}

def extract_body(msg: dict) -> str:
    payload = msg.get("payload", {})
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    return ""


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/start")
def auth_start(username: str = Query(...)):
    if get_valid_token(username):
        return {"status": "already_authenticated"}

    params = urllib.parse.urlencode({
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         SCOPES,
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         username,
    })
    auth_url = f"{AUTH_URL}?{params}"
    return {"auth_url": auth_url}


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(code: str = Query(None), state: str = Query(None),
                  error: str = Query(None)):
    if error or not code or not state:
        return HTMLResponse(content=f"""
        <html><body style="font-family:sans-serif;text-align:center;padding:60px">
        <h2>❌ Sign-in failed</h2>
        <p>{error or 'Missing code or state'}</p>
        <p>Return to Hermes and try again.</p>
        </body></html>""", status_code=400)

    r = http_post(TOKEN_URL, {
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    })

    if "access_token" not in r:
        err = r.get("error_description", r.get("error", "token exchange failed"))
        return HTMLResponse(content=f"""
        <html><body style="font-family:sans-serif;text-align:center;padding:60px">
        <h2>❌ Token exchange failed</h2><p>{err}</p>
        </body></html>""", status_code=400)

    save_creds(state, {
        "access_token":  r["access_token"],
        "refresh_token": r.get("refresh_token", ""),
        "expires_at":    time.time() + r.get("expires_in", 3600),
    })

    return HTMLResponse(content="""
    <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#f0fdf4">
    <h2 style="color:#16a34a">✅ Gmail connected!</h2>
    <p>You're signed in. Return to Hermes and continue.</p>
    <script>setTimeout(()=>window.close(),3000)</script>
    </body></html>""")


@app.get("/auth/status")
def auth_status(username: str = Query(...)):
    return {"status": "complete" if get_valid_token(username) else "not_started"}


@app.delete("/auth/revoke")
def auth_revoke(username: str = Query(...)):
    creds = load_creds(username)
    if creds and creds.get("access_token"):
        http_post(REVOKE_URL, {"token": creds["access_token"]})
    token_path(username).unlink(missing_ok=True)
    return {"status": "revoked"}


# ── Gmail ─────────────────────────────────────────────────────────────────────

@app.get("/api/me")
def get_me(username: str = Query(...)):
    token = get_valid_token(username)
    if not token:
        return {"error": "not_authenticated"}
    r = http_get_auth("https://www.googleapis.com/oauth2/v2/userinfo", token)
    return {"displayName": r.get("name", username), "email": r.get("email", "")}


@app.get("/api/calendar")
def list_calendar(username: str = Query(...), days: int = Query(1), top: int = Query(10), week_view: bool = Query(False), weeks_back: int = Query(0), days_back: int = Query(0), months_back: int = Query(0), month_view: bool = Query(False)):
    import datetime
    token = get_valid_token(username)
    if not token:
        return {"error": "not_authenticated"}
    now      = datetime.datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if week_view:
        days_since_monday = day_start.weekday()  # Monday=0, Sunday=6
        this_monday = day_start - datetime.timedelta(days=days_since_monday)
        week_start = this_monday - datetime.timedelta(weeks=weeks_back)
        time_min  = week_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max  = (week_start + datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif month_view:
        import calendar as _cal
        _anchor  = day_start.replace(day=1)
        _last_day = _cal.monthrange(_anchor.year, _anchor.month)[1]
        time_min = _anchor.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (_anchor.replace(day=_last_day) + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif months_back > 0:
        import calendar as _cal
        _m = day_start.month - months_back
        _y = day_start.year + (_m - 1) // 12
        _m = ((_m - 1) % 12) + 1
        _anchor  = day_start.replace(year=_y, month=_m, day=1)
        _last_day = _cal.monthrange(_y, _m)[1]
        time_min = _anchor.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (_anchor.replace(day=_last_day) + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif days_back > 0:
        _anchor  = day_start - datetime.timedelta(days=days_back)
        time_min = _anchor.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (_anchor + datetime.timedelta(days=max(days, 1))).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        time_min  = (day_start - datetime.timedelta(days=weeks_back * 7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max  = (day_start + datetime.timedelta(days=max(days, 1))).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = urllib.parse.urlencode({
        "timeMin":       time_min,
        "timeMax":       time_max,
        "singleEvents":  "true",
        "orderBy":       "startTime",
        "maxResults":    min(top, 50),
    })
    r = http_get_auth(
        f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{params}", token
    )
    if "error" in r:
        return r
    events = []
    for item in r.get("items", []):
        start = item.get("start", {})
        end   = item.get("end", {})
        # Detect online meeting platform and join link
        _conf     = item.get("conferenceData") or {}
        _solution = (_conf.get("conferenceSolution") or {})
        _platform = _solution.get("name", "")
        _join_url = ""
        for _ep in _conf.get("entryPoints", []):
            if _ep.get("entryPointType") == "video":
                _join_url = _ep.get("uri", "")
                break
        if not _join_url:
            _join_url = item.get("hangoutLink", "")
        if not _platform and _join_url:
            _platform = "Google Meet"

        events.append({
            "id":          item.get("id", ""),
            "summary":     item.get("summary", "(no title)"),
            "start":       start.get("dateTime", start.get("date", "")),
            "end":         end.get("dateTime",   end.get("date",   "")),
            "location":    item.get("location", ""),
            "online":      bool(_join_url or _platform),
            "platform":    _platform,
            "join_url":    _join_url,
            "description": _strip_html(item.get("description") or "")[:1000],
            "attendees": [
                {"email":       a.get("email", ""),
                 "displayName": a.get("displayName", a.get("email", "")),
                 "self":        a.get("self", False)}
                for a in item.get("attendees", [])
            ],
            "attachments": [
                {"title":    a.get("title", ""),
                 "mimeType": a.get("mimeType", ""),
                 "fileUrl":  a.get("fileUrl", "")}
                for a in item.get("attachments", [])
            ],
        })
    return {"value": events}


LABEL_MAP = {
    "inbox":   "INBOX",
    "drafts":  "DRAFT",
    "draft":   "DRAFT",
    "sent":    "SENT",
    "starred": "STARRED",
    "spam":    "SPAM",
    "trash":   "TRASH",
}

@app.get("/api/emails")
def list_emails(
    username:    str  = Query(...),
    days:        int  = Query(7),
    top:         int  = Query(30),
    unread_only: bool = Query(False),
    label:       str  = Query("INBOX"),
):
    label_id = LABEL_MAP.get(label.lower(), label.upper())
    params: dict = {"maxResults": min(top, 50), "labelIds": label_id}

    if days > 0 and label_id not in ("DRAFT",):
        cutoff = int(time.time()) - days * 86400
        q = f"after:{cutoff}"
        if unread_only:
            q += " is:unread"
        params["q"] = q
    elif unread_only:
        params["q"] = "is:unread"

    r = gmail_get(username, "messages", params)
    if "error" in r:
        return r

    result = []
    for m in r.get("messages", [])[:top]:
        detail = gmail_get(username, f"messages/{m['id']}", [
            ("format", "metadata"),
            ("metadataHeaders", "Subject"),
            ("metadataHeaders", "From"),
            ("metadataHeaders", "To"),
            ("metadataHeaders", "Date"),
        ])
        if "error" not in detail:
            h = parse_headers(detail)
            result.append({
                "id":               m["id"],
                "threadId":         m.get("threadId"),
                "subject":          h.get("subject", "(no subject)"),
                "from":             h.get("from", ""),
                "to":               h.get("to", ""),
                "receivedDateTime": h.get("date", ""),
                "bodyPreview":      _html_mod.unescape(detail.get("snippet", ""))[:120],
                "isRead":           "UNREAD" not in detail.get("labelIds", []),
                "labels":           detail.get("labelIds", []),
            })
    return {"value": result, "label": label_id}


@app.get("/api/emails/{email_id}")
def get_email(email_id: str, username: str = Query(...)):
    r = gmail_get(username, f"messages/{email_id}", {"format": "full"})
    if "error" in r:
        return r
    h = parse_headers(r)
    return {
        "id":        r.get("id"),
        "threadId":  r.get("threadId"),
        "subject":   h.get("subject", "(no subject)"),
        "from":      h.get("from", ""),
        "to":        h.get("to", ""),
        "date":      h.get("date", ""),
        "snippet":   r.get("snippet", ""),
        "body":      extract_body(r)[:3000],
        "labels":    r.get("labelIds", []),
        "messageId": h.get("message-id", ""),
    }


class AttachmentData(BaseModel):
    filename:  str
    data:      str  # base64 encoded
    mime_type: str = "application/octet-stream"

class SendBody(BaseModel):
    to:          str
    subject:     str
    body:        str
    attachments: list[AttachmentData] = []

@app.post("/api/emails/stage-send")
def stage_send(username: str = Query(...), payload: SendBody = Body(...)):
    import uuid
    pending_id = str(uuid.uuid4())[:8]
    with pending_lock:
        pending_sends[pending_id] = {
            "username":    username,
            "to":          payload.to,
            "subject":     payload.subject,
            "body":        payload.body,
            "attachments": [a.model_dump() for a in payload.attachments],
            "staged_at":   time.time(),
        }
    return {
        "pending_id": pending_id,
        "preview": {
            "to":          payload.to,
            "subject":     payload.subject,
            "body":        payload.body,
            "attachments": [a.filename for a in payload.attachments],
        }
    }

@app.post("/api/emails/confirm-send")
def confirm_send(pending_id: str = Query(...)):
    with pending_lock:
        pending = pending_sends.pop(pending_id, None)
    if not pending:
        return {"error": "No pending email found. Stage the email again."}
    if time.time() - pending["staged_at"] > 600:
        return {"error": "Pending email expired. Stage it again."}
    msg = make_raw(pending["to"], pending["subject"], pending["body"],
                   attachments=pending.get("attachments") or None)
    r   = gmail_post(pending["username"], "messages/send", msg)
    if "error" in r:
        return r
    return {"status": "sent", "id": r.get("id")}


@app.get("/api/drafts")
def list_drafts(username: str = Query(...), top: int = Query(20)):
    r = gmail_get(username, "drafts", [("maxResults", min(top, 50))])
    if "error" in r:
        return r
    result = []
    for d in r.get("drafts", []):
        draft_id = d.get("id")
        msg_id   = d.get("message", {}).get("id")
        if not msg_id:
            continue
        detail = gmail_get(username, f"messages/{msg_id}", [
            ("format", "metadata"),
            ("metadataHeaders", "Subject"),
            ("metadataHeaders", "From"),
            ("metadataHeaders", "To"),
            ("metadataHeaders", "Date"),
        ])
        h = parse_headers(detail) if "error" not in detail else {}
        result.append({
            "draft_id": draft_id,
            "message_id": msg_id,
            "subject":  h.get("subject", "(no subject)"),
            "to":       h.get("to", ""),
            "snippet":  detail.get("snippet", "")[:120],
        })
    return {"drafts": result}


@app.post("/api/drafts/{draft_id}/send")
def send_draft(draft_id: str, username: str = Query(...)):
    r = gmail_post(username, f"drafts/{draft_id}/send", {"id": draft_id})
    if "error" in r:
        return r
    return {"status": "sent", "id": r.get("id")}


@app.delete("/api/drafts/{draft_id}")
def delete_draft(draft_id: str, username: str = Query(...)):
    r = gmail_delete(username, f"drafts/{draft_id}")
    if "error" in r:
        return r
    return {"status": "deleted"}


@app.post("/api/emails/draft-new")
def draft_new(username: str = Query(...), payload: SendBody = Body(...)):
    atts = [a.model_dump() for a in payload.attachments] or None
    msg  = make_raw(payload.to, payload.subject, payload.body, attachments=atts)
    r    = gmail_post(username, "drafts", {"message": msg})
    if "error" in r:
        return r
    return {"status": "draft_saved", "id": r.get("id")}


@app.post("/api/emails/{email_id}/flag")
def flag_email(email_id: str, username: str = Query(...), starred: bool = Query(True)):
    body = {
        "addLabelIds":    ["STARRED"] if starred else [],
        "removeLabelIds": [] if starred else ["STARRED"],
    }
    r = gmail_post(username, f"messages/{email_id}/modify", body)
    if "error" in r:
        return r
    labels = r.get("labelIds", [])
    return {"status": "starred" if "STARRED" in labels else "unstarred", "id": r.get("id")}


class ReplyBody(BaseModel):
    body: str

@app.post("/api/emails/{email_id}/draft-reply")
def draft_reply(email_id: str, username: str = Query(...), payload: ReplyBody = Body(...)):
    orig = gmail_get(username, f"messages/{email_id}",
                     {"format": "metadata",
                      "metadataHeaders": "Subject,From,Message-ID"})
    if "error" in orig:
        return orig

    h         = parse_headers(orig)
    thread_id = orig.get("threadId")
    subject   = h.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    to        = h.get("from", "")
    msg_id    = h.get("message-id", "")

    mime = make_raw(to, subject, payload.body, reply_to_id=msg_id, thread_id=thread_id)
    r    = gmail_post(username, "drafts", {"message": mime})
    if "error" in r:
        return r
    return {"status": "draft_saved", "id": r.get("id")}


class ReplyWithAttachBody(BaseModel):
    body:        str
    attachments: list[AttachmentData] = []


@app.post("/api/emails/{email_id}/send-reply")
def send_reply_with_attachment(email_id: str, username: str = Query(...),
                               payload: ReplyWithAttachBody = Body(...)):
    """Send a reply in-thread with optional file attachments."""
    orig = gmail_get(username, f"messages/{email_id}",
                     {"format": "metadata",
                      "metadataHeaders": "Subject,From,Message-ID"})
    if "error" in orig:
        return orig

    h         = parse_headers(orig)
    thread_id = orig.get("threadId")
    subject   = h.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    to      = h.get("from", "")
    msg_id  = h.get("message-id", "")

    atts = [a.model_dump() for a in payload.attachments] or None
    mime = make_raw(to, subject, payload.body,
                    reply_to_id=msg_id, thread_id=thread_id, attachments=atts)
    r = gmail_post(username, "messages/send", mime)
    if "error" in r:
        return r
    return {
        "status":      "sent",
        "id":          r.get("id"),
        "to":          to,
        "subject":     subject,
        "attachments": [a.filename for a in payload.attachments],
    }
fastapi==0.111.0
uvicorn==0.30.1
pydantic==2.7.4
