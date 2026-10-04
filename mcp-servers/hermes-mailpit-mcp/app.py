import json
import os
import smtplib
import time
import uuid
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional
import base64
import urllib.request
import urllib.parse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

app = FastAPI(title="hermes-mailpit-mcp", version="1.0.0")

MAILPIT_API = "http://mailpit:8025/api/v1"
MAILPIT_SMTP_HOST = "mailpit"
MAILPIT_SMTP_PORT = 1025
CALENDAR_FILE = Path("/opt/data/mailpit-calendar.json")

# In-memory stores (demo scope — restarts clear these)
_pending: dict = {}   # pending_id → {to, subject, body, attachments, expires_at}
_drafts:  dict = {}   # draft_id  → {to, subject, body, attachments, created_at}
_flags:   dict = {}   # message_id → bool (starred)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mp_get(path: str, params: dict = None):
    url = MAILPIT_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def _fmt_addr(obj) -> str:
    if not obj:
        return ""
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    name = obj.get("Name", "")
    addr = obj.get("Address", "")
    return f"{name} <{addr}>" if name else addr


def _norm_message(m: dict) -> dict:
    """Normalise Mailpit message to Gmail-MCP-compatible field names."""
    return {
        "id":               m.get("ID", ""),
        "subject":          m.get("Subject", "(no subject)"),
        "from":             _fmt_addr(m.get("From")),
        "to":               _fmt_addr(m.get("To")),
        "receivedDateTime": m.get("Created", m.get("Date", "")),
        "bodyPreview":      (m.get("Snippet") or m.get("Text", ""))[:120],
        "isRead":           m.get("Read", False),
        "starred":          _flags.get(m.get("ID", ""), False),
    }


def _send_smtp(to: str, subject: str, body: str, attachments: list = None):
    """Send an email via Mailpit SMTP."""
    msg = MIMEMultipart()
    msg["From"] = "hermes@example.com"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    for att in (attachments or []):
        part = MIMEBase("application", "octet-stream")
        data = base64.b64decode(att.get("data", ""))
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename=\"{att.get('filename', 'attachment')}\"",
        )
        msg.attach(part)
    with smtplib.SMTP(MAILPIT_SMTP_HOST, MAILPIT_SMTP_PORT, timeout=10) as s:
        s.sendmail("hermes@example.com", [to], msg.as_string())


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/emails")
def list_emails(
    top:  int = Query(default=20, le=50),
    days: int = Query(default=7),
):
    # Mailpit returns newest-first; apply a limit
    r = _mp_get("/messages", {"limit": min(top, 50), "start": 0})
    if "error" in r:
        raise HTTPException(500, r["error"])

    msgs = r.get("messages") or []

    # Client-side date filter
    if days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filtered = []
        for m in msgs:
            try:
                dt_str = m.get("Created", m.get("Date", ""))
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt >= cutoff:
                    filtered.append(m)
            except Exception:
                filtered.append(m)
        msgs = filtered

    return {"value": [_norm_message(m) for m in msgs]}


@app.get("/api/emails/{email_id}")
def read_email(email_id: str):
    r = _mp_get(f"/message/{email_id}")
    if "error" in r:
        raise HTTPException(404, r["error"])
    body = r.get("Text") or ""
    return {
        "id":      r.get("ID", ""),
        "subject": r.get("Subject", "(no subject)"),
        "from":    _fmt_addr(r.get("From")),
        "to":      _fmt_addr(r.get("To")),
        "date":    r.get("Date", ""),
        "body":    body[:3000],
    }


class StageSendRequest(BaseModel):
    to:          str
    subject:     str
    body:        str
    attachments: list = []

    @field_validator("to", "subject", "body")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field cannot be empty")
        return v


@app.post("/api/emails/stage-send")
def stage_send(req: StageSendRequest):
    pid = uuid.uuid4().hex[:8]
    _pending[pid] = {
        "to":          req.to,
        "subject":     req.subject,
        "body":        req.body,
        "attachments": req.attachments,
        "expires_at":  time.time() + 600,
    }
    return {
        "pending_id": pid,
        "preview": {
            "to":          req.to,
            "subject":     req.subject,
            "body":        req.body,
            "attachments": [a.get("filename", "") for a in req.attachments],
        },
    }


@app.post("/api/emails/confirm-send")
def confirm_send(pending_id: str = Query(...)):
    p = _pending.pop(pending_id, None)
    if not p:
        raise HTTPException(404, f"No pending send with id '{pending_id}'")
    if time.time() > p["expires_at"]:
        raise HTTPException(410, "Pending send has expired — please stage again")
    try:
        _send_smtp(p["to"], p["subject"], p["body"], p.get("attachments", []))
    except Exception as e:
        raise HTTPException(500, f"SMTP error: {e}")
    return {"status": "sent"}


class DraftRequest(BaseModel):
    to:          str
    subject:     str
    body:        str
    attachments: list = []


@app.post("/api/emails/draft-new")
def draft_new(req: DraftRequest):
    did = uuid.uuid4().hex[:8]
    _drafts[did] = {
        "draft_id":    did,
        "to":          req.to,
        "subject":     req.subject,
        "body":        req.body,
        "attachments": req.attachments,
        "created_at":  time.time(),
    }
    return {"status": "draft_saved", "draft_id": did}


class DraftReplyRequest(BaseModel):
    body: str


@app.post("/api/emails/{email_id}/draft-reply")
def draft_reply(email_id: str, req: DraftReplyRequest):
    orig = _mp_get(f"/message/{email_id}")
    if "error" in orig:
        raise HTTPException(404, orig["error"])
    subj = orig.get("Subject", "")
    if not subj.lower().startswith("re:"):
        subj = "Re: " + subj
    to = _fmt_addr(orig.get("From"))
    did = uuid.uuid4().hex[:8]
    _drafts[did] = {
        "draft_id":   did,
        "to":         to,
        "subject":    subj,
        "body":       req.body,
        "created_at": time.time(),
    }
    return {"status": "draft_saved", "draft_id": did}


@app.get("/api/drafts")
def list_drafts(top: int = Query(default=20, le=50)):
    drafts = sorted(_drafts.values(), key=lambda d: d["created_at"], reverse=True)[:top]
    return {
        "drafts": [
            {
                "draft_id": d["draft_id"],
                "to":       d.get("to", ""),
                "subject":  d.get("subject", "(no subject)"),
                "snippet":  d.get("body", "")[:120],
            }
            for d in drafts
        ]
    }


@app.post("/api/drafts/{draft_id}/send")
def send_draft(draft_id: str):
    d = _drafts.pop(draft_id, None)
    if not d:
        raise HTTPException(404, f"Draft '{draft_id}' not found")
    try:
        _send_smtp(d["to"], d["subject"], d["body"], d.get("attachments", []))
    except Exception as e:
        _drafts[draft_id] = d  # put it back
        raise HTTPException(500, f"SMTP error: {e}")
    return {"status": "sent", "id": draft_id}


@app.delete("/api/drafts/{draft_id}")
def delete_draft(draft_id: str):
    _drafts.pop(draft_id, None)
    return {"status": "deleted"}


@app.post("/api/emails/{email_id}/flag")
def flag_email(email_id: str, starred: bool = Query(default=True)):
    _flags[email_id] = starred
    return {"status": "starred" if starred else "unstarred", "id": email_id}


@app.get("/api/calendar")
def get_calendar(days: int = Query(default=1), top: int = Query(default=10, le=20)):
    if not CALENDAR_FILE.exists():
        return {"value": []}
    try:
        events = json.loads(CALENDAR_FILE.read_text())
    except Exception as e:
        raise HTTPException(500, f"Calendar read error: {e}")

    # Filter to today's window
    if days <= 0:
        return {"value": []}
    now_utc = datetime.now(timezone.utc)
    # Use local date (SGT = UTC+8) for "today"
    sgt_offset = timedelta(hours=8)
    today_sgt = (now_utc + sgt_offset).date()
    cutoff_end = today_sgt + timedelta(days=days)

    filtered = []
    for ev in events:
        try:
            start_str = ev.get("start", "")
            dt = datetime.fromisoformat(start_str)
            ev_date = dt.date()
            if today_sgt <= ev_date < cutoff_end:
                filtered.append(ev)
        except Exception:
            filtered.append(ev)

    return {"value": filtered[:top]}
